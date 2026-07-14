"""OpenAI-compatible Chat Completions adapter over ``httpx``.

The adapter deliberately implements the small, broadly compatible
Chat Completions surface directly instead of depending on a vendor SDK.
Retries are owned exclusively by this module.
"""

from __future__ import annotations

import json
import random
import time
from collections.abc import Callable, Mapping
from dataclasses import replace
from typing import Any, cast

import httpx

from halfblood.generation.errors import (
    IncompleteResponseError,
    ProviderCapabilityError,
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
    StructuredOutputMode,
)
from halfblood.generation.structured_output import (
    DEFAULT_PARSE_LIMITS,
    TOOL_NAME,
    CanonicalMode,
    ParseLimits,
    StructuredOutputPin,
    StructuredOutputPolicy,
    parse_json_schema_mode,
    parse_prompt_mode,
    parse_tool_mode,
)

_CHAT_PATH = "/chat/completions"
_TOOL_DESCRIPTION = (
    "Record the margin annotations produced for this page. "
    "Call this exactly once with the complete list of annotations for the page."
)
DEFAULT_MAX_RETRIES = 2
DEFAULT_TIMEOUT_SECONDS = 60.0
_BACKOFF_BASE_SECONDS = 1.0
_BACKOFF_CAP_SECONDS = 30.0
_INCOMPLETE_RESPONSE_MAX_TOKENS_CEILING = 8192
_PROMPT_EXAMPLE = '{"annotations":[]}'


class OpenAICompatibleProvider:
    """Talk to any OpenAI-compatible Chat Completions endpoint over ``httpx``."""

    def __init__(
        self,
        api_key: str | None,
        *,
        base_url: str,
        capabilities: ProviderCapabilities,
        structured_output: str = "auto",
        strict: bool = False,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        max_retries: int = DEFAULT_MAX_RETRIES,
        extra_headers: Mapping[str, str] | None = None,
        transport: httpx.BaseTransport | None = None,
        sleep_fn: Callable[[float], None] = time.sleep,
        rand_fn: Callable[[], float] = random.random,
    ) -> None:
        # Config presets call forced tool use "function" while the shared
        # negotiation policy calls the canonical strategy "tool".
        normalized_output = "tool" if structured_output == "function" else structured_output
        allowed_outputs = {"auto", "tool", "json-schema", "prompt"}
        if normalized_output not in allowed_outputs:
            raise ProviderConfigurationError(
                f"Unknown structured-output mode: {structured_output}"
            )

        self._api_key = api_key
        self._capabilities = capabilities
        self._structured_output = cast(StructuredOutputPin, normalized_output)
        self._strict = strict
        self._max_retries = max_retries
        self._extra_headers = dict(extra_headers or {})
        self._sleep_fn = sleep_fn
        self._rand_fn = rand_fn
        self._parse_limits: ParseLimits = DEFAULT_PARSE_LIMITS
        self._client = httpx.Client(
            base_url=base_url,
            timeout=timeout_seconds,
            transport=transport,
        )

    @property
    def capabilities(self) -> ProviderCapabilities:
        return self._capabilities

    def complete(self, request: GenerationRequest) -> GenerationResult:
        policy = StructuredOutputPolicy(pin=self._structured_output, strict=self._strict)
        current_mode = policy.select(self._capabilities)
        already_downgraded = False
        max_tokens = request.max_tokens
        escalated = False
        attempts = 0
        elapsed_start = time.monotonic()

        while True:
            attempts += 1
            body = self._build_body(request, mode=current_mode, max_tokens=max_tokens)
            try:
                response = self._client.post(
                    _CHAT_PATH,
                    json=body,
                    headers=self._request_headers(),
                )
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                transport_error = ProviderTransientError(self._redact(str(exc)))
                if attempts <= self._max_retries and self._should_retry_attempt(
                    attempts, elapsed_start
                ):
                    self._sleep_fn(self._backoff_seconds(attempts, retry_after=None))
                    continue
                _record_attempts(transport_error, attempts)
                raise transport_error from exc

            if response.status_code == 200:
                try:
                    outcome = self._parse_success(response, mode=current_mode)
                except _Truncated:
                    if not escalated:
                        escalated = True
                        max_tokens = min(
                            max_tokens * 2,
                            _INCOMPLETE_RESPONSE_MAX_TOKENS_CEILING,
                        )
                        continue
                    incomplete_error = IncompleteResponseError(
                        "response was truncated at max_tokens after one "
                        "escalated retry with a larger token budget"
                    )
                    _record_attempts(incomplete_error, attempts)
                    raise incomplete_error from None
                return replace(
                    outcome,
                    attempts=attempts,
                    latency_seconds=time.monotonic() - elapsed_start,
                )

            response_error = self._classify_error_response(
                response,
                current_mode=current_mode,
            )
            if isinstance(response_error, ProviderCapabilityError) and policy.allows_downgrade(
                response_error,
                already_downgraded=already_downgraded,
            ):
                next_mode = policy.next_mode(current_mode, self._capabilities)
                if next_mode is not None:
                    already_downgraded = True
                    current_mode = next_mode
                    continue

            retryable = isinstance(
                response_error,
                (ProviderRateLimitError, ProviderTransientError),
            )
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

    def _request_headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._api_key is not None:
            headers["Authorization"] = f"Bearer {self._api_key}"
        headers.update(self._extra_headers)
        return headers

    def _build_body(
        self,
        request: GenerationRequest,
        *,
        mode: CanonicalMode,
        max_tokens: int,
    ) -> dict[str, Any]:
        system_prompt = request.system_prompt
        if mode == "prompt":
            schema_json = json.dumps(
                dict(request.schema),
                sort_keys=True,
                separators=(",", ":"),
            )
            system_prompt = (
                f"{system_prompt}\n\n"
                "Return exactly one JSON object matching the schema below. "
                "Do not use Markdown fences or add prose.\n"
                f"Schema: {schema_json}\nExample: {_PROMPT_EXAMPLE}"
            )

        body: dict[str, Any] = {
            "model": request.model,
            "max_tokens": max_tokens,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": request.user_prompt},
            ],
        }
        if request.temperature is not None:
            body["temperature"] = request.temperature

        schema = dict(request.schema)
        if mode == "tool":
            body.update(
                {
                    "tools": [
                        {
                            "type": "function",
                            "function": {
                                "name": TOOL_NAME,
                                "description": _TOOL_DESCRIPTION,
                                "parameters": schema,
                                "strict": self._capabilities.supports_strict_json_schema,
                            },
                        }
                    ],
                    "tool_choice": {
                        "type": "function",
                        "function": {"name": TOOL_NAME},
                    },
                    "parallel_tool_calls": False,
                }
            )
        elif mode == "json-schema":
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": TOOL_NAME,
                    "strict": True,
                    "schema": schema,
                },
            }
        else:
            body["response_format"] = {"type": "json_object"}
        return body

    def _parse_success(
        self,
        response: httpx.Response,
        *,
        mode: CanonicalMode,
    ) -> GenerationResult:
        try:
            body = response.json()
        except ValueError as exc:
            raise StructuredOutputError("Provider returned invalid JSON") from exc
        if not isinstance(body, Mapping):
            raise StructuredOutputError("Provider response root was not a JSON object")

        choices = body.get("choices")
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], Mapping):
            raise StructuredOutputError("Provider response did not contain a choice")
        choice = choices[0]
        message = choice.get("message")
        if not isinstance(message, Mapping):
            raise StructuredOutputError("Provider choice did not contain an assistant message")

        finish_reason_raw = choice.get("finish_reason")
        finish_reason = None if finish_reason_raw is None else str(finish_reason_raw)
        if message.get("refusal"):
            raise ProviderSafetyRefusal("Provider refused the structured-output request")
        if finish_reason == "content_filter":
            raise ProviderSafetyRefusal("Provider stopped for content safety")

        warnings: tuple[str, ...] = ()
        result_mode: StructuredOutputMode
        if mode == "tool":
            if finish_reason in {"length", "max_tokens"}:
                raise _Truncated()
            parsed = parse_tool_mode(message, limits=self._parse_limits)
            result_mode = "function"
        elif mode == "json-schema":
            parsed = parse_json_schema_mode(
                message,
                finish_reason=finish_reason,
                limits=self._parse_limits,
            )
            result_mode = "json-schema"
        else:
            content = message.get("content", "")
            parsed = parse_prompt_mode(
                content if isinstance(content, str) else "",
                limits=self._parse_limits,
            )
            result_mode = "prompt"
            warnings = ("prompt-mode structured output is less reliable",)

        usage_raw = body.get("usage")
        usage = usage_raw if isinstance(usage_raw, Mapping) else {}
        request_id = response.headers.get("x-request-id")
        if request_id is None:
            body_id = body.get("id")
            request_id = str(body_id) if body_id is not None else None

        return GenerationResult(
            parsed=parsed,
            request_id=request_id,
            finish_reason=finish_reason or "unknown",
            usage=GenerationUsage(
                input_tokens=_token_count(usage.get("prompt_tokens")),
                output_tokens=_token_count(usage.get("completion_tokens")),
            ),
            latency_seconds=0.0,
            structured_output_mode=result_mode,
            warnings=warnings,
        )

    def _classify_error_response(
        self,
        response: httpx.Response,
        *,
        current_mode: CanonicalMode,
    ) -> ProviderError:
        try:
            body = response.json()
        except ValueError:
            message = response.text
        else:
            error = body.get("error") if isinstance(body, Mapping) else None
            if isinstance(error, Mapping):
                message = str(error.get("message", response.text))
            else:
                message = response.text
        message = self._redact(message)

        if response.status_code == 429:
            retry_after_header = response.headers.get("retry-after")
            try:
                retry_after = float(retry_after_header) if retry_after_header else None
            except ValueError:
                retry_after = None
            return ProviderRateLimitError(
                message,
                status_code=response.status_code,
                retry_after=retry_after,
            )

        taxonomy_cls = classify_status_code(response.status_code)
        if taxonomy_cls is not None:
            return taxonomy_cls(message, status_code=response.status_code)

        capability_keywords = ("tools", "function", "response_format")
        if response.status_code == 400 and any(
            keyword in message.lower() for keyword in capability_keywords
        ):
            return ProviderCapabilityError(
                message,
                status_code=response.status_code,
                requested_mode=current_mode,
            )

        return ProviderConfigurationError(
            message,
            status_code=response.status_code,
        )

    def _redact(self, message: str) -> str:
        redacted = redact_secrets(message)
        if self._api_key:
            redacted = redacted.replace(self._api_key, "[REDACTED]")
        return redacted

    def _should_retry_attempt(self, attempts: int, elapsed_start: float) -> bool:
        return time.monotonic() - elapsed_start < 60.0

    def _backoff_seconds(self, attempt: int, *, retry_after: float | None) -> float:
        if retry_after is not None:
            return min(retry_after, _BACKOFF_CAP_SECONDS)
        cap = min(_BACKOFF_CAP_SECONDS, _BACKOFF_BASE_SECONDS * (2**attempt))
        return self._rand_fn() * cap


class _Truncated(Exception):
    """Internal control-flow signal for a tool response truncated at max_tokens."""


def _token_count(value: Any) -> int:
    """Normalize optional compatible-provider usage fields to non-negative integers."""
    try:
        return max(int(value or 0), 0)
    except (TypeError, ValueError):
        return 0


def _record_attempts(error: ProviderError, attempts: int) -> None:
    error.__dict__["attempts"] = attempts
