"""Native Anthropic Messages API adapter over ``httpx`` — no vendor SDK.

Implements the ``LLMProvider`` protocol (P1-T4) against
``POST /v1/messages`` directly. This is the safety-anchor adapter: it must
match the pre-P1-T5 SDK-based generator's forced-tool-use behavior exactly,
while normalizing responses/errors/usage/retries onto the P1-T4 taxonomy and
report model.

Retry ownership: this module is the ONLY place in the codebase that retries
an Anthropic request. The vendor SDK is no longer imported anywhere in
``src/`` after this task — there is nothing left for this loop to double up
with.
"""

from __future__ import annotations

import random
import time
from collections.abc import Callable
from dataclasses import replace

import httpx
from pydantic import ValidationError

from halfblood.generation.errors import (
    IncompleteResponseError,
    ProviderConfigurationError,
    ProviderError,
    ProviderRateLimitError,
    ProviderSafetyRefusal,
    ProviderTransientError,
    StructuredOutputError,
    classify_status_code,
    redact_secrets,
)
from halfblood.generation.providers.base import (
    GenerationRequest,
    GenerationResult,
    GenerationUsage,
    ProviderCapabilities,
)
from halfblood.generation.schema import AnnotationDraft, RecordAnnotations

ANTHROPIC_API_VERSION = "2023-06-01"
_MESSAGES_PATH = "/v1/messages"
_TOOL_NAME = "record_annotations"
_TOOL_DESCRIPTION = (
    "Record the margin annotations produced for this page. Call this "
    "exactly once with the complete list of annotations for the page."
)

DEFAULT_MAX_RETRIES = 2
DEFAULT_TIMEOUT_SECONDS = 60.0
_BACKOFF_BASE_SECONDS = 1.0
_BACKOFF_CAP_SECONDS = 30.0
_INCOMPLETE_RESPONSE_MAX_TOKENS_CEILING = 8192


class AnthropicProvider:
    """Talk to the Anthropic Messages API over ``httpx``."""

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = "https://api.anthropic.com",
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        max_retries: int = DEFAULT_MAX_RETRIES,
        transport: httpx.BaseTransport | None = None,
        sleep_fn: Callable[[float], None] = time.sleep,
        rand_fn: Callable[[], float] = random.random,
    ) -> None:
        self._api_key = api_key
        self._max_retries = max_retries
        self._sleep_fn = sleep_fn
        self._rand_fn = rand_fn
        self._client = httpx.Client(base_url=base_url, timeout=timeout_seconds, transport=transport)

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            supports_tool_calling=True,
            supports_json_schema=False,
            supports_strict_json_schema=False,
            supports_prompt_fallback=True,
            max_output_tokens=None,
        )

    def complete(self, request: GenerationRequest) -> GenerationResult:
        max_tokens = request.max_tokens
        escalated = False
        attempts = 0
        elapsed_start = time.monotonic()

        while True:
            attempts += 1
            body = self._build_body(request, max_tokens=max_tokens)
            try:
                response = self._client.post(
                    _MESSAGES_PATH,
                    json=body,
                    headers={
                        "x-api-key": self._api_key,
                        "anthropic-version": ANTHROPIC_API_VERSION,
                        "content-type": "application/json",
                    },
                )
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                transport_error = ProviderTransientError(redact_secrets(str(exc)))
                if attempts <= self._max_retries and self._should_retry_attempt(
                    attempts, elapsed_start
                ):
                    self._sleep_fn(self._backoff_seconds(attempts, retry_after=None))
                    continue
                _record_attempts(transport_error, attempts)
                raise transport_error from exc

            if response.status_code == 200:
                try:
                    outcome = self._parse_success(response, request=request, max_tokens=max_tokens)
                except _Truncated:
                    if not escalated:
                        escalated = True
                        max_tokens = min(max_tokens * 2, _INCOMPLETE_RESPONSE_MAX_TOKENS_CEILING)
                        continue
                    incomplete_error = IncompleteResponseError(
                        "response was truncated at max_tokens after one "
                        "escalated retry with a larger token budget"
                    )
                    _record_attempts(incomplete_error, attempts)
                    raise incomplete_error from None
                except StructuredOutputError as exc:
                    # A 200 carrying no usable tool_use block. Model/gateway
                    # misbehaviour rather than a decision, so it is retryable on the
                    # same bounded budget as a transport failure. ProviderSafetyRefusal
                    # is a sibling class and is deliberately NOT caught — a refusal is
                    # a decision, not a glitch.
                    if attempts <= self._max_retries and self._should_retry_attempt(
                        attempts, elapsed_start
                    ):
                        self._sleep_fn(self._backoff_seconds(attempts, retry_after=None))
                        continue
                    _record_attempts(exc, attempts)
                    raise
                return replace(
                    outcome,
                    attempts=attempts,
                    latency_seconds=time.monotonic() - elapsed_start,
                )

            response_error = self._classify_error_response(response)
            retryable = isinstance(response_error, (ProviderRateLimitError, ProviderTransientError))
            if (
                retryable
                and attempts <= self._max_retries
                and self._should_retry_attempt(attempts, elapsed_start)
            ):
                retry_after = getattr(response_error, "retry_after", None)
                self._sleep_fn(self._backoff_seconds(attempts, retry_after=retry_after))
                continue
            _record_attempts(response_error, attempts)
            raise response_error

    def _build_body(self, request: GenerationRequest, *, max_tokens: int) -> dict[str, object]:
        return {
            "model": request.model,
            "max_tokens": max_tokens,
            "system": request.system_prompt,
            "messages": [{"role": "user", "content": request.user_prompt}],
            "tools": [
                {
                    "name": _TOOL_NAME,
                    "description": _TOOL_DESCRIPTION,
                    "input_schema": dict(request.schema),
                }
            ],
            "tool_choice": {"type": "tool", "name": _TOOL_NAME},
        }

    def _should_retry_attempt(self, attempts: int, elapsed_start: float) -> bool:
        return time.monotonic() - elapsed_start < 60.0

    def _backoff_seconds(self, attempt: int, *, retry_after: float | None) -> float:
        if retry_after is not None:
            return min(retry_after, _BACKOFF_CAP_SECONDS)
        cap = min(_BACKOFF_CAP_SECONDS, _BACKOFF_BASE_SECONDS * (2**attempt))
        return self._rand_fn() * cap

    def _classify_error_response(self, response: httpx.Response) -> ProviderError:
        try:
            body = response.json()
            message = str(body.get("error", {}).get("message", response.text))
        except ValueError:
            message = response.text
        message = redact_secrets(message)

        if response.status_code == 429:
            retry_after_header = response.headers.get("retry-after")
            retry_after = float(retry_after_header) if retry_after_header else None
            return ProviderRateLimitError(
                message, status_code=response.status_code, retry_after=retry_after
            )

        taxonomy_cls = classify_status_code(response.status_code)
        if taxonomy_cls is not None:
            return taxonomy_cls(message, status_code=response.status_code)

        return ProviderConfigurationError(message, status_code=response.status_code)

    def _parse_success(
        self, response: httpx.Response, *, request: GenerationRequest, max_tokens: int
    ) -> GenerationResult:
        body = response.json()
        stop_reason = body.get("stop_reason")
        content = body.get("content") or []
        usage_raw = body.get("usage") or {}
        request_id = response.headers.get("request-id")

        if stop_reason == "refusal":
            stop_details = body.get("stop_details") or {}
            raise ProviderSafetyRefusal(redact_secrets(f"Anthropic refused: {stop_details}"))

        if stop_reason == "max_tokens":
            raise _Truncated()

        matching = [
            block
            for block in content
            if isinstance(block, dict)
            and block.get("type") == "tool_use"
            and block.get("name") == _TOOL_NAME
        ]
        if not matching:
            raise StructuredOutputError("no record_annotations tool_use block was present")
        if len(matching) != 1:
            raise StructuredOutputError("multiple record_annotations tool_use blocks were present")

        warnings: list[str] = []
        if len(content) != 1:
            warnings.append(
                f"response included {len(content) - 1} extra content block(s) "
                "alongside record_annotations"
            )

        tool_input = matching[0].get("input")
        if not isinstance(tool_input, dict):
            raise StructuredOutputError("record_annotations input was not a JSON object")
        if "annotations" not in tool_input:
            raise StructuredOutputError("record_annotations input omitted the annotations key")
        raw_annotations = tool_input["annotations"]
        if not isinstance(raw_annotations, list):
            raise StructuredOutputError("record_annotations annotations value was not a list")

        drafts: list[AnnotationDraft] = []
        for item in raw_annotations:
            try:
                drafts.append(AnnotationDraft.model_validate(item))
            except ValidationError as exc:
                warnings.append(f"dropped invalid annotation: {exc}")

        parsed = RecordAnnotations(annotations=drafts)
        usage = GenerationUsage(
            input_tokens=int(usage_raw.get("input_tokens", 0)),
            output_tokens=int(usage_raw.get("output_tokens", 0)),
        )
        return GenerationResult(
            parsed=parsed,
            request_id=request_id,
            finish_reason=str(stop_reason),
            usage=usage,
            latency_seconds=0.0,
            structured_output_mode="tool",
            warnings=tuple(warnings),
        )


class _Truncated(Exception):
    """Internal control-flow signal for a response truncated at max_tokens."""


def _record_attempts(error: ProviderError, attempts: int) -> None:
    error.__dict__["attempts"] = attempts
