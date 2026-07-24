"""Controller-authored wire-level tests for the native Anthropic ``httpx``
adapter (architecture §§4.1, 4.3 Anthropic, 4.6; plan P1-T5).

Pins:

* ``AnthropicProvider`` (``src/halfblood/generation/providers/anthropic.py``)
  implements the ``LLMProvider`` protocol from P1-T4 using ``httpx`` only —
  no ``anthropic`` SDK import anywhere in this module.
* Exact request wire shape: ``POST {base_url}/v1/messages`` with
  ``x-api-key``, ``anthropic-version: 2023-06-01``, forced
  ``tool_choice={"type":"tool","name":"record_annotations"}``.
* Response normalization: exactly one matching ``tool_use`` block is
  required; extra content blocks become a warning, not a failure; a valid
  empty ``annotations`` list is success; per-item validation drops
  individual malformed annotations without failing the page (legacy
  parity — even when every item drops, matching the pre-P1-T5 generator's
  ``test_all_items_invalid_is_empty_success_not_page_failure`` contract).
  Stricter "wholly invalid response is a page failure" semantics are
  explicitly OUT of scope here — that's P1-T6's bounded-parsing job.
* Error taxonomy mapping is transport-owned: 401/403->Authentication,
  404->NotFound, 429->RateLimit (honors ``Retry-After``),
  408/409/425/5xx->Transient (bounded retry), everything else non-2xx
  (400, 413, ...) -> ``ProviderConfigurationError`` (deliberately the ONE
  bucket for "not otherwise classified 4xx" in P1-5 — never
  ``ProviderCapabilityError``, which P1-T6 reserves exclusively for its
  auto-mode downgrade trigger).
* ``stop_reason`` handling mirrors the pre-P1-T5 generator exactly:
  ``max_tokens`` -> one escalated retry with a larger token budget, then
  ``IncompleteResponseError``; ``refusal`` -> ``ProviderSafetyRefusal``;
  every other value (``end_turn``, ``tool_use``, or anything unexpected)
  is decided purely by tool_use-block presence, NOT by an allowlist of
  known-good stop reasons -- a response carrying a valid tool block under
  an unusual stop_reason must still succeed.
* Retries use an injected deterministic sleep/random source -- no real
  time.sleep anywhere in this file, no network.
* No API key or Authorization-shaped substring ever appears in a raised
  error's message.

No real network calls anywhere in this file.
"""

from __future__ import annotations

import json

import httpx
import pytest

from halfblood.generation.errors import (
    IncompleteResponseError,
    ProviderAuthenticationError,
    ProviderConfigurationError,
    ProviderNotFoundError,
    ProviderRateLimitError,
    ProviderSafetyRefusal,
    ProviderTransientError,
    StructuredOutputError,
)
from halfblood.generation.providers.anthropic import (
    ANTHROPIC_API_VERSION,
    AnthropicProvider,
)
from halfblood.generation.providers.base import GenerationRequest
from halfblood.generation.schema import generate_annotation_schema

API_KEY = "sk-ant-test-fake-key-not-real"
BASE_URL = "https://api.anthropic.com"


def _request(**overrides: object) -> GenerationRequest:
    fields: dict[str, object] = dict(
        system_prompt="You are the Prince.",
        user_prompt="Annotate this page.",
        schema=generate_annotation_schema(),
        model="claude-sonnet-5",
        max_tokens=2048,
        structured_output_mode="tool",
    )
    fields.update(overrides)
    return GenerationRequest(**fields)  # type: ignore[arg-type]


def _tool_use_body(
    annotations: list[dict],
    *,
    stop_reason: str = "tool_use",
    extra_blocks: list[dict] | None = None,
    input_tokens: int = 100,
    output_tokens: int = 50,
) -> dict:
    content = list(extra_blocks or [])
    content.append(
        {
            "type": "tool_use",
            "id": "toolu_01abc",
            "name": "record_annotations",
            "input": {"annotations": annotations},
        }
    )
    return {
        "id": "msg_01xyz",
        "type": "message",
        "role": "assistant",
        "content": content,
        "model": "claude-sonnet-5",
        "stop_reason": stop_reason,
        "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens},
    }


def _provider(handler, **kwargs: object) -> AnthropicProvider:
    transport = httpx.MockTransport(handler)
    return AnthropicProvider(
        api_key=API_KEY,
        base_url=BASE_URL,
        transport=transport,
        sleep_fn=lambda _seconds: None,
        rand_fn=lambda: 0.5,
        **kwargs,  # type: ignore[arg-type]
    )


def _json_response(status_code: int, body: dict, headers: dict | None = None) -> httpx.Response:
    return httpx.Response(status_code, json=body, headers=headers or {})


def _error_body(error_type: str, message: str = "boom") -> dict:
    return {"type": "error", "error": {"type": error_type, "message": message}}


VALID_ANNOTATION = {
    "target_text": "Add the powdered root and stir twice.",
    "annotation_type": "correction",
    "content": "No. Crush it, don't cut it.",
    "confidence": 0.9,
    "position": "margin_right",
}


# ---------------------------------------------------------------------------
# Wire shape
# ---------------------------------------------------------------------------


def test_no_anthropic_sdk_import() -> None:
    import ast
    from pathlib import Path

    src = Path("src/halfblood/generation/providers/anthropic.py").read_text()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert all(not alias.name.startswith("anthropic") for alias in node.names)
        if isinstance(node, ast.ImportFrom) and node.module:
            assert not node.module.startswith("anthropic")


def test_request_url_headers_and_payload_shape() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["headers"] = request.headers
        captured["body"] = json.loads(request.content)
        return _json_response(200, _tool_use_body([]))

    provider = _provider(handler)
    provider.complete(_request())

    assert captured["url"] == f"{BASE_URL}/v1/messages"
    assert captured["headers"]["x-api-key"] == API_KEY
    assert captured["headers"]["anthropic-version"] == ANTHROPIC_API_VERSION
    assert ANTHROPIC_API_VERSION == "2023-06-01"
    assert "authorization" not in captured["headers"]

    body = captured["body"]
    assert body["model"] == "claude-sonnet-5"
    assert body["max_tokens"] == 2048
    assert body["system"] == "You are the Prince."
    assert body["messages"] == [{"role": "user", "content": "Annotate this page."}]
    assert body["tool_choice"] == {"type": "tool", "name": "record_annotations"}
    assert len(body["tools"]) == 1
    assert body["tools"][0]["name"] == "record_annotations"
    assert body["tools"][0]["input_schema"] == generate_annotation_schema()


def test_capabilities_declare_tool_only() -> None:
    provider = _provider(lambda r: _json_response(200, _tool_use_body([])))
    caps = provider.capabilities
    assert caps.supports_tool_calling is True
    assert caps.supports_json_schema is False


# ---------------------------------------------------------------------------
# Successful parsing
# ---------------------------------------------------------------------------


def test_valid_empty_annotations_is_success() -> None:
    provider = _provider(lambda r: _json_response(200, _tool_use_body([])))
    result = provider.complete(_request())
    assert result.parsed.annotations == []
    assert result.finish_reason == "tool_use"
    assert result.structured_output_mode == "tool"
    assert result.attempts == 1


def test_tool_use_message_parses_fields_and_usage_and_request_id() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _json_response(
            200,
            _tool_use_body([VALID_ANNOTATION], input_tokens=321, output_tokens=45),
            headers={"request-id": "req_018EeWyXxfu5"},
        )

    provider = _provider(handler)
    result = provider.complete(_request())

    assert len(result.parsed.annotations) == 1
    draft = result.parsed.annotations[0]
    assert draft.target_text == VALID_ANNOTATION["target_text"]
    assert draft.content == VALID_ANNOTATION["content"]
    assert draft.confidence == 0.9
    assert draft.position == "margin_right"
    assert result.usage.input_tokens == 321
    assert result.usage.output_tokens == 45
    assert result.request_id == "req_018EeWyXxfu5"


def test_non_default_position_value_survives_parsing() -> None:
    """Safety net carried over from P1-T2's field-name decision (wire key
    stays ``position``, not v2's ``requested_placement``): a non-default
    value must survive parsing, not be silently reset to the
    ``margin_right`` fallback."""
    non_default = dict(VALID_ANNOTATION, position="between_lines")
    provider = _provider(lambda r: _json_response(200, _tool_use_body([non_default])))
    result = provider.complete(_request())
    assert result.parsed.annotations[0].position == "between_lines"


def test_defaults_applied_for_omitted_optional_fields() -> None:
    sparse = {
        "target_text": "Some text.",
        "annotation_type": "doodle_note",
        "content": "Obviously.",
    }
    provider = _provider(lambda r: _json_response(200, _tool_use_body([sparse])))
    result = provider.complete(_request())
    draft = result.parsed.annotations[0]
    assert draft.confidence == 0.8
    assert draft.position == "margin_right"


def test_invalid_individual_annotation_is_dropped_not_fatal() -> None:
    bad = {"target_text": "", "annotation_type": "correction", "content": "x"}
    provider = _provider(
        lambda r: _json_response(
            200, _tool_use_body([VALID_ANNOTATION, bad, "not-a-dict"])
        )
    )
    result = provider.complete(_request())
    assert len(result.parsed.annotations) == 1
    assert result.parsed.annotations[0].target_text == VALID_ANNOTATION["target_text"]
    assert any("dropped" in w.lower() or "invalid" in w.lower() for w in result.warnings)


def test_all_items_invalid_is_empty_success_not_page_failure() -> None:
    bad_one = {"target_text": "", "annotation_type": "correction", "content": "x"}
    bad_two = {"target_text": "ok", "annotation_type": "not-a-real-type", "content": "y"}
    provider = _provider(lambda r: _json_response(200, _tool_use_body([bad_one, bad_two])))
    result = provider.complete(_request())
    assert result.parsed.annotations == []
    assert len(result.warnings) >= 2


def test_text_block_alongside_tool_block_parses_with_warning() -> None:
    extra = [{"type": "text", "text": "Here are the annotations:"}]
    provider = _provider(
        lambda r: _json_response(
            200, _tool_use_body([VALID_ANNOTATION], extra_blocks=extra)
        )
    )
    result = provider.complete(_request())
    assert len(result.parsed.annotations) == 1
    assert any("extra" in w.lower() or "content block" in w.lower() for w in result.warnings)


# ---------------------------------------------------------------------------
# Malformed / missing tool_use block -> StructuredOutputError
# ---------------------------------------------------------------------------


def test_no_matching_tool_block_is_structured_output_error() -> None:
    body = _tool_use_body([])
    body["content"] = [{"type": "text", "text": "no tool call here"}]
    provider = _provider(lambda r: _json_response(200, body))
    with pytest.raises(StructuredOutputError):
        provider.complete(_request())


def test_wrongly_named_tool_block_is_structured_output_error() -> None:
    body = _tool_use_body([])
    body["content"] = [
        {"type": "tool_use", "id": "toolu_1", "name": "some_other_tool", "input": {}}
    ]
    provider = _provider(lambda r: _json_response(200, body))
    with pytest.raises(StructuredOutputError):
        provider.complete(_request())


def test_multiple_matching_tool_blocks_is_structured_output_error() -> None:
    block = {
        "type": "tool_use",
        "id": "toolu_1",
        "name": "record_annotations",
        "input": {"annotations": []},
    }
    body = _tool_use_body([])
    body["content"] = [block, dict(block, id="toolu_2")]
    provider = _provider(lambda r: _json_response(200, body))
    with pytest.raises(StructuredOutputError):
        provider.complete(_request())


@pytest.mark.parametrize(
    "bad_input",
    [
        "not-a-dict",
        {},
        {"annotations": "not-a-list"},
    ],
)
def test_malformed_tool_input_is_structured_output_error(bad_input: object) -> None:
    body = _tool_use_body([])
    body["content"] = [
        {"type": "tool_use", "id": "toolu_1", "name": "record_annotations", "input": bad_input}
    ]
    provider = _provider(lambda r: _json_response(200, body))
    with pytest.raises(StructuredOutputError):
        provider.complete(_request())


# ---------------------------------------------------------------------------
# stop_reason handling
# ---------------------------------------------------------------------------


def test_refusal_stop_reason_is_safety_refusal() -> None:
    body = _tool_use_body([])
    body["stop_reason"] = "refusal"
    body["content"] = []
    body["stop_details"] = {"type": "refusal", "category": "cyber"}
    provider = _provider(lambda r: _json_response(200, body))
    with pytest.raises(ProviderSafetyRefusal):
        provider.complete(_request())


def test_unusual_stop_reason_with_valid_tool_block_still_succeeds() -> None:
    """A tool_use block present under a non-standard stop_reason must not
    be rejected by an allowlist -- block presence decides success, not the
    stop_reason value (parity with the pre-P1-T5 generator, which branched
    only on max_tokens)."""
    provider = _provider(
        lambda r: _json_response(
            200, _tool_use_body([VALID_ANNOTATION], stop_reason="pause_turn")
        )
    )
    result = provider.complete(_request())
    assert len(result.parsed.annotations) == 1


def test_max_tokens_truncation_escalates_once_then_fails() -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        calls.append(body["max_tokens"])
        return _json_response(200, _tool_use_body([], stop_reason="max_tokens"))

    provider = _provider(handler)
    with pytest.raises(IncompleteResponseError):
        provider.complete(_request(max_tokens=2048))

    assert len(calls) == 2
    assert calls[0] == 2048
    assert calls[1] > 2048


def test_max_tokens_truncation_succeeds_on_escalated_retry() -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        calls.append(body["max_tokens"])
        if len(calls) == 1:
            return _json_response(200, _tool_use_body([], stop_reason="max_tokens"))
        return _json_response(200, _tool_use_body([VALID_ANNOTATION]))

    provider = _provider(handler)
    result = provider.complete(_request(max_tokens=2048))
    assert len(calls) == 2
    assert len(result.parsed.annotations) == 1


# ---------------------------------------------------------------------------
# HTTP status -> taxonomy, retries
# ---------------------------------------------------------------------------


def test_401_is_authentication_error_no_retry() -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return _json_response(401, _error_body("authentication_error"))

    provider = _provider(handler)
    with pytest.raises(ProviderAuthenticationError):
        provider.complete(_request())
    assert len(calls) == 1


def test_404_is_not_found_error_no_retry() -> None:
    provider = _provider(lambda r: _json_response(404, _error_body("not_found_error")))
    with pytest.raises(ProviderNotFoundError):
        provider.complete(_request())


def test_400_is_configuration_error_no_retry_not_capability() -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return _json_response(400, _error_body("invalid_request_error"))

    provider = _provider(handler)
    with pytest.raises(ProviderConfigurationError):
        provider.complete(_request())
    assert len(calls) == 1


def test_413_unmapped_status_is_configuration_error() -> None:
    provider = _provider(lambda r: _json_response(413, _error_body("request_too_large")))
    with pytest.raises(ProviderConfigurationError):
        provider.complete(_request())


def test_429_retries_honoring_retry_after() -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) == 1:
            return _json_response(
                429, _error_body("rate_limit_error"), headers={"retry-after": "2"}
            )
        return _json_response(200, _tool_use_body([VALID_ANNOTATION]))

    sleeps: list[float] = []
    provider = _provider(handler, max_retries=2)
    provider._sleep_fn = sleeps.append  # type: ignore[attr-defined]
    result = provider.complete(_request())
    assert len(calls) == 2
    assert len(result.parsed.annotations) == 1
    assert sleeps and sleeps[0] == pytest.approx(2.0)


def test_429_exhausts_retries_then_raises_rate_limit_error() -> None:
    provider = _provider(
        lambda r: _json_response(429, _error_body("rate_limit_error")), max_retries=2
    )
    with pytest.raises(ProviderRateLimitError):
        provider.complete(_request())


@pytest.mark.parametrize("status", [408, 409, 425, 500, 503, 529])
def test_transient_statuses_are_bounded_retried(status: int) -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) == 1:
            return _json_response(status, _error_body("api_error"))
        return _json_response(200, _tool_use_body([VALID_ANNOTATION]))

    provider = _provider(handler, max_retries=2)
    result = provider.complete(_request())
    assert len(calls) == 2
    assert len(result.parsed.annotations) == 1


def test_transient_status_exhausts_retries_then_raises() -> None:
    provider = _provider(lambda r: _json_response(500, _error_body("api_error")), max_retries=1)
    with pytest.raises(ProviderTransientError):
        provider.complete(_request())


def test_connection_timeout_is_transient_and_retried() -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) == 1:
            raise httpx.ConnectTimeout("timed out", request=request)
        return _json_response(200, _tool_use_body([VALID_ANNOTATION]))

    provider = _provider(handler, max_retries=2)
    result = provider.complete(_request())
    assert len(calls) == 2
    assert len(result.parsed.annotations) == 1


def test_attempts_are_recorded_on_success_and_on_final_error() -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) < 3:
            return _json_response(500, _error_body("api_error"))
        return _json_response(200, _tool_use_body([VALID_ANNOTATION]))

    provider = _provider(handler, max_retries=3)
    result = provider.complete(_request())
    assert result.attempts == 3

    provider2 = _provider(lambda r: _json_response(500, _error_body("api_error")), max_retries=1)
    try:
        provider2.complete(_request())
        pytest.fail("expected ProviderTransientError")
    except ProviderTransientError as exc:
        assert getattr(exc, "attempts", None) == 2


# ---------------------------------------------------------------------------
# Secret redaction
# ---------------------------------------------------------------------------


def test_error_message_never_contains_the_api_key() -> None:
    provider = _provider(
        lambda r: _json_response(
            401,
            _error_body(
                "authentication_error",
                message=f"Invalid Authorization: Bearer {API_KEY}",
            ),
        )
    )
    with pytest.raises(ProviderAuthenticationError) as excinfo:
        provider.complete(_request())
    assert API_KEY not in str(excinfo.value)


# ---------------------------------------------------------------------------
# Malformed 200 responses are retried by the provider (the sole retry owner).
#
# Mirrors the OpenAI-compatible provider. A 200 whose body carries no usable
# tool_use block is model/gateway misbehaviour, not a decision, and cost a whole
# chapter per run when it escaped the retry loop uncaught.
# ---------------------------------------------------------------------------


def test_malformed_success_body_retries_and_succeeds() -> None:
    """A 200 with no tool_use block must be retried, not fatal."""
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) == 1:
            return _json_response(
                200,
                {
                    "id": "msg_bad",
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "text", "text": "no tool use here"}],
                    "model": "claude-sonnet-5",
                    "stop_reason": "end_turn",
                    "usage": {"input_tokens": 1, "output_tokens": 1},
                },
            )
        return _json_response(200, _tool_use_body([VALID_ANNOTATION]))

    result = _provider(handler, max_retries=2).complete(_request())

    assert len(calls) == 2, "the malformed 200 should have been retried"
    assert len(result.parsed.annotations) == 1
    assert result.attempts == 2


def test_malformed_success_body_exhausts_retries_and_raises() -> None:
    """Retries stay bounded — a permanently malformed provider still fails."""
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return _json_response(
            200,
            {
                "id": "msg_bad",
                "type": "message",
                "role": "assistant",
                "content": [{"type": "text", "text": "still no tool use"}],
                "model": "claude-sonnet-5",
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 1, "output_tokens": 1},
            },
        )

    with pytest.raises(StructuredOutputError):
        _provider(handler, max_retries=2).complete(_request())

    assert len(calls) == 3, f"expected 1 initial + 2 retries, got {len(calls)}"
