"""Wire-level tests for the OpenAI Chat Completions adapter (architecture §§4.1, 4.3, 4.4; plan P1-T7).

Context7 was unreachable during test authoring — all wire-protocol facts are [INFER]
from the well-known OpenAI Chat Completions contract and architecture §§4.1, 4.3, 4.4.
See .superpowers/sdd/p1-t7-brief.md "Controller inferences" for the complete list.

Pins:
* POST {base_url}/chat/completions                                                    [INFER]
* Auth: Authorization: Bearer <api_key> ONLY when api_key is not None                [INFER]
* Forced function body: tools=[{type:function,function:{name,description,parameters,
  strict:bool}}], tool_choice={type:function,function:{name}}, parallel_tool_calls=False
                                                                                      [INFER]
* JSON Schema mode: response_format={type:json_schema,json_schema:{name,strict,schema}} [INFER]
* Prompt mode: response_format={type:json_object}                                     [INFER]
* max_tokens field name (not max_completion_tokens)                                   [INFER]
* Response: choices[0].message; tool_calls[*].function.arguments is a JSON string    [INFER]
* finish_reason: stop|tool_calls|length|content_filter                                [INFER]
* usage: {prompt_tokens, completion_tokens}                                           [INFER]
* request-id: x-request-id header; fallback to body id field                         [INFER]
* Error body: {error:{message,type,code,param}}                                       [INFER]
* structured_output_mode reports "function" for forced-function call                  [INFER]
* Capability-400: error body mentions tools/function/response_format keywords         [INFER]
"""

from __future__ import annotations

import json

import httpx
import pytest
from halfblood.generation.providers.openai_compat import OpenAICompatibleProvider

from halfblood.generation.errors import (
    IncompleteResponseError,
    ProviderAuthenticationError,
    ProviderCapabilityError,
    ProviderConfigurationError,
    ProviderNotFoundError,
    ProviderRateLimitError,
    ProviderSafetyRefusal,
    ProviderTransientError,
    StructuredOutputError,
)
from halfblood.generation.providers.base import GenerationRequest, ProviderCapabilities
from halfblood.generation.schema import generate_annotation_schema

API_KEY = "sk-test-fake-key-not-real"
BASE_URL = "https://api.example.com/v1"


# ---------------------------------------------------------------------------
# Capability presets
# ---------------------------------------------------------------------------


def _caps_tool_only() -> ProviderCapabilities:
    return ProviderCapabilities(
        supports_tool_calling=True,
        supports_json_schema=False,
        supports_strict_json_schema=False,
        supports_prompt_fallback=True,
    )


def _caps_tool_strict() -> ProviderCapabilities:
    return ProviderCapabilities(
        supports_tool_calling=True,
        supports_json_schema=False,
        supports_strict_json_schema=True,
        supports_prompt_fallback=True,
    )


def _caps_json_schema_only() -> ProviderCapabilities:
    """Supports json-schema but NOT tool calling — auto selects json-schema."""
    return ProviderCapabilities(
        supports_tool_calling=False,
        supports_json_schema=True,
        supports_strict_json_schema=True,
        supports_prompt_fallback=True,
    )


def _caps_prompt_only() -> ProviderCapabilities:
    return ProviderCapabilities(
        supports_tool_calling=False,
        supports_json_schema=False,
        supports_strict_json_schema=False,
        supports_prompt_fallback=True,
    )


def _caps_full() -> ProviderCapabilities:
    return ProviderCapabilities(
        supports_tool_calling=True,
        supports_json_schema=True,
        supports_strict_json_schema=True,
        supports_prompt_fallback=True,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _provider(
    handler,
    *,
    api_key: str | None = API_KEY,
    capabilities: ProviderCapabilities | None = None,
    structured_output: str = "tool",
    max_retries: int = 2,
    extra_headers=None,
) -> OpenAICompatibleProvider:
    return OpenAICompatibleProvider(
        api_key=api_key,
        base_url=BASE_URL,
        capabilities=capabilities if capabilities is not None else _caps_tool_only(),
        structured_output=structured_output,
        max_retries=max_retries,
        extra_headers=extra_headers,
        transport=httpx.MockTransport(handler),
        sleep_fn=lambda _seconds: None,
        rand_fn=lambda: 0.5,
    )


def _request(**overrides: object) -> GenerationRequest:
    fields: dict[str, object] = dict(
        system_prompt="You are the Prince.",
        user_prompt="Annotate this page.",
        schema=generate_annotation_schema(),
        model="gpt-4o",
        max_tokens=2048,
    )
    fields.update(overrides)
    return GenerationRequest(**fields)  # type: ignore[arg-type]


def _json_response(
    status_code: int, body: dict, headers: dict | None = None
) -> httpx.Response:
    return httpx.Response(status_code, json=body, headers=headers or {})


def _tool_call_body(
    annotations: list[dict],
    *,
    finish_reason: str = "tool_calls",
    prompt_tokens: int = 100,
    completion_tokens: int = 50,
    body_id: str = "chatcmpl-test01",
) -> dict:
    """Minimal valid OpenAI Chat Completions response with a function tool call."""
    return {
        "id": body_id,
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "tool_calls": [
                        {
                            "id": "call_01",
                            "type": "function",
                            "function": {
                                "name": "record_annotations",
                                "arguments": json.dumps({"annotations": annotations}),
                            },
                        }
                    ],
                },
                "finish_reason": finish_reason,
            }
        ],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
        },
    }


def _legacy_function_call_body(annotations: list[dict]) -> dict:
    """Legacy function_call response (no tool_calls key)."""
    return {
        "id": "chatcmpl-legacy01",
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "function_call": {
                        "name": "record_annotations",
                        "arguments": json.dumps({"annotations": annotations}),
                    },
                },
                "finish_reason": "function_call",
            }
        ],
        "usage": {"prompt_tokens": 80, "completion_tokens": 40},
    }


def _json_schema_body(
    annotations: list[dict], *, finish_reason: str = "stop", body_id: str = "chatcmpl-js01"
) -> dict:
    """response_format json_schema response: choices[0].message.content is JSON."""
    return {
        "id": body_id,
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": json.dumps({"annotations": annotations}),
                },
                "finish_reason": finish_reason,
            }
        ],
        "usage": {"prompt_tokens": 90, "completion_tokens": 45},
    }


def _prompt_body(annotations: list[dict], *, finish_reason: str = "stop") -> dict:
    """Prompt-mode response: choices[0].message.content is free text with JSON."""
    return {
        "id": "chatcmpl-prompt01",
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": json.dumps({"annotations": annotations}),
                },
                "finish_reason": finish_reason,
            }
        ],
        "usage": {"prompt_tokens": 70, "completion_tokens": 30},
    }


def _error_body(message: str, *, type_: str = "invalid_request_error") -> dict:
    return {"error": {"message": message, "type": type_, "code": None, "param": None}}


VALID_ANNOTATION = {
    "target_text": "Add powdered root and stir twice.",
    "annotation_type": "correction",
    "content": "No. Crush it.",
    "confidence": 0.9,
    "position": "margin_right",
}


# ---------------------------------------------------------------------------
# Wire shape — forced function
# ---------------------------------------------------------------------------


def test_forced_function_request_wire_shape() -> None:
    """[INFER] Forced-function body shape: tools, tool_choice, parallel_tool_calls."""
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        captured["body"] = json.loads(request.content)
        return _json_response(200, _tool_call_body([]))

    provider = _provider(handler, structured_output="tool")
    provider.complete(_request())

    assert captured["url"] == f"{BASE_URL}/chat/completions"
    assert captured["headers"].get("authorization") == f"Bearer {API_KEY}"

    body = captured["body"]
    assert body["model"] == "gpt-4o"
    assert body["max_tokens"] == 2048  # [INFER] field name

    # messages: system + user
    messages = body["messages"]
    assert messages[0]["role"] == "system"
    assert messages[0]["content"] == "You are the Prince."
    assert messages[1]["role"] == "user"
    assert messages[1]["content"] == "Annotate this page."

    # tools array
    assert len(body["tools"]) == 1
    tool = body["tools"][0]
    assert tool["type"] == "function"
    func = tool["function"]
    assert func["name"] == "record_annotations"
    assert "parameters" in func
    assert isinstance(func.get("strict"), bool)  # strict field present [INFER]

    # tool_choice [INFER]
    assert body["tool_choice"] == {
        "type": "function",
        "function": {"name": "record_annotations"},
    }
    # parallel_tool_calls [INFER]
    assert body.get("parallel_tool_calls") is False


def test_strict_field_reflects_supports_strict_json_schema() -> None:
    """[INFER] strict in function schema matches capabilities.supports_strict_json_schema."""
    bodies: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return _json_response(200, _tool_call_body([]))

    OpenAICompatibleProvider(
        api_key=API_KEY,
        base_url=BASE_URL,
        capabilities=_caps_tool_strict(),
        structured_output="tool",
        transport=httpx.MockTransport(handler),
        sleep_fn=lambda _: None,
        rand_fn=lambda: 0.5,
    ).complete(_request())
    assert bodies[0]["tools"][0]["function"]["strict"] is True

    OpenAICompatibleProvider(
        api_key=API_KEY,
        base_url=BASE_URL,
        capabilities=_caps_tool_only(),
        structured_output="tool",
        transport=httpx.MockTransport(handler),
        sleep_fn=lambda _: None,
        rand_fn=lambda: 0.5,
    ).complete(_request())
    assert bodies[1]["tools"][0]["function"]["strict"] is False


def test_json_schema_request_wire_shape() -> None:
    """[INFER] json_schema response_format body."""
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return _json_response(200, _json_schema_body([]))

    _provider(
        handler,
        capabilities=_caps_json_schema_only(),
        structured_output="json-schema",
    ).complete(_request())

    body = captured["body"]
    assert "tools" not in body
    assert "tool_choice" not in body
    rf = body.get("response_format", {})
    assert rf.get("type") == "json_schema"
    js = rf.get("json_schema", {})
    assert js.get("name") == "record_annotations"
    assert js.get("strict") is True
    assert "schema" in js


def test_prompt_request_wire_shape() -> None:
    """[INFER] json_object response_format hint for prompt mode."""
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return _json_response(200, _prompt_body([]))

    _provider(
        handler,
        capabilities=_caps_prompt_only(),
        structured_output="prompt",
    ).complete(_request())

    body = captured["body"]
    assert "tools" not in body
    rf = body.get("response_format", {})
    assert rf.get("type") == "json_object"  # [INFER]


# ---------------------------------------------------------------------------
# Auth header
# ---------------------------------------------------------------------------


def test_auth_bearer_present_with_key() -> None:
    headers_seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        headers_seen.append(dict(request.headers))
        return _json_response(200, _tool_call_body([]))

    _provider(handler, api_key="sk-real-key-xyz").complete(_request())
    assert headers_seen[0].get("authorization") == "Bearer sk-real-key-xyz"


def test_auth_bearer_absent_without_key() -> None:
    """No Authorization header when api_key is None (ollama/lmstudio pattern)."""
    headers_seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        headers_seen.append(dict(request.headers))
        return _json_response(200, _tool_call_body([]))

    _provider(handler, api_key=None).complete(_request())
    assert "authorization" not in headers_seen[0]


def test_extra_headers_are_forwarded() -> None:
    """extra_headers appear verbatim in the request (e.g. OpenRouter attribution)."""
    headers_seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        headers_seen.append(dict(request.headers))
        return _json_response(200, _tool_call_body([]))

    extra = {"HTTP-Referer": "https://halfblood.example", "X-Title": "HalfBloodPrince"}
    _provider(handler, extra_headers=extra).complete(_request())

    seen = headers_seen[0]
    for key, value in extra.items():
        # httpx lowercases header names
        assert seen.get(key.lower(), seen.get(key)) == value


# ---------------------------------------------------------------------------
# Successful parsing
# ---------------------------------------------------------------------------


def test_function_tool_call_parses_valid_annotations() -> None:
    provider = _provider(lambda r: _json_response(200, _tool_call_body([VALID_ANNOTATION])))
    result = provider.complete(_request())
    assert len(result.parsed.annotations) == 1
    draft = result.parsed.annotations[0]
    assert draft.target_text == VALID_ANNOTATION["target_text"]
    assert draft.content == VALID_ANNOTATION["content"]
    assert result.structured_output_mode == "function"  # [INFER]
    assert result.finish_reason == "tool_calls"
    assert result.attempts == 1


def test_valid_empty_annotation_list_is_success() -> None:
    result = _provider(lambda r: _json_response(200, _tool_call_body([]))).complete(_request())
    assert result.parsed.annotations == []
    assert result.structured_output_mode == "function"  # [INFER]


def test_legacy_function_call_parses() -> None:
    """[INFER] Legacy function_call response (no tool_calls) parsed via parse_tool_mode."""
    result = _provider(
        lambda r: _json_response(200, _legacy_function_call_body([VALID_ANNOTATION]))
    ).complete(_request())
    assert len(result.parsed.annotations) == 1
    assert result.structured_output_mode == "function"  # [INFER]


def test_json_schema_content_parses() -> None:
    result = _provider(
        lambda r: _json_response(200, _json_schema_body([VALID_ANNOTATION])),
        capabilities=_caps_json_schema_only(),
        structured_output="json-schema",
    ).complete(_request())
    assert len(result.parsed.annotations) == 1
    assert result.structured_output_mode == "json-schema"


def test_refusal_field_is_safety_refusal() -> None:
    refusal_body = {
        "id": "chatcmpl-refusal01",
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "refusal": "I cannot annotate this content.",
                    "content": None,
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 30, "completion_tokens": 10},
    }
    with pytest.raises(ProviderSafetyRefusal):
        _provider(
            lambda r: _json_response(200, refusal_body),
            capabilities=_caps_json_schema_only(),
            structured_output="json-schema",
        ).complete(_request())


def test_length_finish_reason_raises_incomplete_error() -> None:
    with pytest.raises(IncompleteResponseError):
        _provider(
            lambda r: _json_response(200, _json_schema_body([], finish_reason="length")),
            capabilities=_caps_json_schema_only(),
            structured_output="json-schema",
        ).complete(_request())


def test_tool_mode_length_finish_reason_escalates_once_then_fails() -> None:
    """finish_reason='length' in tool mode → escalate token budget once, then IncompleteResponseError."""
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        calls.append(body.get("max_tokens", body.get("max_completion_tokens", 0)))
        return _json_response(200, _tool_call_body([], finish_reason="length"))

    with pytest.raises(IncompleteResponseError):
        _provider(handler).complete(_request(max_tokens=2048))

    assert len(calls) == 2
    assert calls[0] == 2048
    assert calls[1] > 2048


def test_usage_and_request_id_captured() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _json_response(
            200,
            _tool_call_body([VALID_ANNOTATION], prompt_tokens=321, completion_tokens=45),
            headers={"x-request-id": "req-abc-001"},
        )

    result = _provider(handler).complete(_request())
    assert result.usage.input_tokens == 321
    assert result.usage.output_tokens == 45
    assert result.request_id == "req-abc-001"


def test_request_id_fallback_to_body_id() -> None:
    """When x-request-id header is absent, fall back to body id field. [INFER]"""
    result = _provider(
        lambda r: _json_response(200, _tool_call_body([], body_id="chatcmpl-bodyid-xyz"))
    ).complete(_request())
    assert result.request_id == "chatcmpl-bodyid-xyz"


def test_malformed_arguments_is_structured_output_error() -> None:
    bad_body = {
        "id": "chatcmpl-bad01",
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "tool_calls": [
                        {
                            "id": "call_bad",
                            "type": "function",
                            "function": {
                                "name": "record_annotations",
                                "arguments": "not-json{{{",
                            },
                        }
                    ],
                },
                "finish_reason": "tool_calls",
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
    }
    with pytest.raises(StructuredOutputError):
        _provider(lambda r: _json_response(200, bad_body)).complete(_request())


def test_over_limit_arguments_is_structured_output_error() -> None:
    """Arguments exceeding ParseLimits.max_response_bytes raise StructuredOutputError.

    The adapter dispatches to parse_tool_mode (P1-T6); limit enforcement is
    tested here at the parse level to avoid needing a huge literal string.
    """
    from halfblood.generation.structured_output import ParseLimits, parse_tool_mode

    big_args = json.dumps({"annotations": [VALID_ANNOTATION]})
    tiny_limits = ParseLimits(max_response_bytes=10)
    assert len(big_args.encode()) > 10

    msg = {
        "tool_calls": [
            {
                "function": {
                    "name": "record_annotations",
                    "arguments": big_args,
                }
            }
        ]
    }
    with pytest.raises(StructuredOutputError):
        parse_tool_mode(msg, limits=tiny_limits)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# HTTP status → taxonomy, retries
# ---------------------------------------------------------------------------


def test_401_is_authentication_error_no_retry() -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return _json_response(401, _error_body("Unauthorized"))

    with pytest.raises(ProviderAuthenticationError):
        _provider(handler).complete(_request())
    assert len(calls) == 1


def test_403_is_authentication_error_no_retry() -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return _json_response(403, _error_body("Forbidden"))

    with pytest.raises(ProviderAuthenticationError):
        _provider(handler).complete(_request())
    assert len(calls) == 1


def test_404_is_not_found_error_no_retry() -> None:
    with pytest.raises(ProviderNotFoundError):
        _provider(lambda r: _json_response(404, _error_body("Not found"))).complete(_request())


def test_413_is_configuration_error_no_retry() -> None:
    with pytest.raises(ProviderConfigurationError):
        _provider(lambda r: _json_response(413, _error_body("Request too large"))).complete(
            _request()
        )


def test_429_retries_honoring_retry_after() -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) == 1:
            return _json_response(
                429, _error_body("rate limited"), headers={"retry-after": "3"}
            )
        return _json_response(200, _tool_call_body([VALID_ANNOTATION]))

    sleeps: list[float] = []
    provider = OpenAICompatibleProvider(
        api_key=API_KEY,
        base_url=BASE_URL,
        capabilities=_caps_tool_only(),
        structured_output="tool",
        max_retries=2,
        transport=httpx.MockTransport(handler),
        sleep_fn=sleeps.append,
        rand_fn=lambda: 0.5,
    )
    result = provider.complete(_request())
    assert len(calls) == 2
    assert len(result.parsed.annotations) == 1
    assert sleeps and sleeps[0] == pytest.approx(3.0)


def test_429_exhausts_retries_raises_rate_limit() -> None:
    with pytest.raises(ProviderRateLimitError):
        OpenAICompatibleProvider(
            api_key=API_KEY,
            base_url=BASE_URL,
            capabilities=_caps_tool_only(),
            structured_output="tool",
            max_retries=2,
            transport=httpx.MockTransport(
                lambda r: _json_response(429, _error_body("rate limited"))
            ),
            sleep_fn=lambda _: None,
            rand_fn=lambda: 0.5,
        ).complete(_request())


@pytest.mark.parametrize("status", [408, 409, 425, 500, 503])
def test_transient_statuses_retry_and_succeed(status: int) -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) == 1:
            return _json_response(status, _error_body("transient"))
        return _json_response(200, _tool_call_body([VALID_ANNOTATION]))

    result = OpenAICompatibleProvider(
        api_key=API_KEY,
        base_url=BASE_URL,
        capabilities=_caps_tool_only(),
        structured_output="tool",
        max_retries=2,
        transport=httpx.MockTransport(handler),
        sleep_fn=lambda _: None,
        rand_fn=lambda: 0.5,
    ).complete(_request())
    assert len(calls) == 2
    assert len(result.parsed.annotations) == 1


def test_transient_status_exhausts_retries_raises() -> None:
    with pytest.raises(ProviderTransientError):
        OpenAICompatibleProvider(
            api_key=API_KEY,
            base_url=BASE_URL,
            capabilities=_caps_tool_only(),
            structured_output="tool",
            max_retries=1,
            transport=httpx.MockTransport(
                lambda r: _json_response(500, _error_body("server error"))
            ),
            sleep_fn=lambda _: None,
            rand_fn=lambda: 0.5,
        ).complete(_request())


def test_connection_timeout_is_transient_retried() -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) == 1:
            raise httpx.ConnectTimeout("timed out", request=request)
        return _json_response(200, _tool_call_body([VALID_ANNOTATION]))

    result = OpenAICompatibleProvider(
        api_key=API_KEY,
        base_url=BASE_URL,
        capabilities=_caps_tool_only(),
        structured_output="tool",
        max_retries=2,
        transport=httpx.MockTransport(handler),
        sleep_fn=lambda _: None,
        rand_fn=lambda: 0.5,
    ).complete(_request())
    assert len(calls) == 2
    assert len(result.parsed.annotations) == 1


def test_capability_400_raises_capability_error() -> None:
    """[INFER] 400 whose error body mentions tools/function/response_format → ProviderCapabilityError."""
    body = _error_body("This model does not support tools or function calling")
    with pytest.raises(ProviderCapabilityError):
        _provider(lambda r: _json_response(400, body)).complete(_request())


def test_other_400_is_configuration_error() -> None:
    """400 whose error is unrelated to structured output → ProviderConfigurationError."""
    body = _error_body("model not found")
    with pytest.raises(ProviderConfigurationError):
        _provider(lambda r: _json_response(400, body)).complete(_request())


def test_attempts_recorded_on_success_and_final_error() -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) < 3:
            return _json_response(500, _error_body("server error"))
        return _json_response(200, _tool_call_body([VALID_ANNOTATION]))

    result = OpenAICompatibleProvider(
        api_key=API_KEY,
        base_url=BASE_URL,
        capabilities=_caps_tool_only(),
        structured_output="tool",
        max_retries=3,
        transport=httpx.MockTransport(handler),
        sleep_fn=lambda _: None,
        rand_fn=lambda: 0.5,
    ).complete(_request())
    assert result.attempts == 3

    try:
        OpenAICompatibleProvider(
            api_key=API_KEY,
            base_url=BASE_URL,
            capabilities=_caps_tool_only(),
            structured_output="tool",
            max_retries=1,
            transport=httpx.MockTransport(
                lambda r: _json_response(500, _error_body("error"))
            ),
            sleep_fn=lambda _: None,
            rand_fn=lambda: 0.5,
        ).complete(_request())
        pytest.fail("expected ProviderTransientError")
    except ProviderTransientError as exc:
        assert getattr(exc, "attempts", None) == 2


def test_error_message_never_contains_api_key() -> None:
    provider = _provider(
        lambda r: _json_response(
            401, _error_body(f"Invalid Authorization: Bearer {API_KEY}")
        )
    )
    with pytest.raises(ProviderAuthenticationError) as excinfo:
        provider.complete(_request())
    assert API_KEY not in str(excinfo.value)


# ---------------------------------------------------------------------------
# Downgrade behavior
# ---------------------------------------------------------------------------


def test_capability_400_under_auto_triggers_one_downgrade() -> None:
    """[INFER] capability-400 under auto → exactly ONE downgrade; second call uses next mode."""
    calls: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        calls.append(body)
        if len(calls) == 1:
            return _json_response(
                400, _error_body("This model does not support tools or function calling")
            )
        # Second call (downgraded to json-schema) succeeds
        return _json_response(200, _json_schema_body([VALID_ANNOTATION]))

    # Full caps so auto chain is: tool → json-schema → prompt
    result = OpenAICompatibleProvider(
        api_key=API_KEY,
        base_url=BASE_URL,
        capabilities=_caps_full(),
        structured_output="auto",
        transport=httpx.MockTransport(handler),
        sleep_fn=lambda _: None,
        rand_fn=lambda: 0.5,
    ).complete(_request())

    assert len(calls) == 2
    assert "tools" in calls[0]          # first call used tool/function mode
    assert "response_format" in calls[1]  # second call used json-schema
    assert len(result.parsed.annotations) == 1


def test_no_downgrade_on_structured_output_error() -> None:
    """StructuredOutputError (malformed response) does NOT trigger a second call."""
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        bad_body = {
            "id": "chatcmpl-bad",
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "tool_calls": [
                            {
                                "id": "call_bad",
                                "type": "function",
                                "function": {
                                    "name": "record_annotations",
                                    "arguments": "{invalid",
                                },
                            }
                        ],
                    },
                    "finish_reason": "tool_calls",
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        }
        return _json_response(200, bad_body)

    with pytest.raises(StructuredOutputError):
        OpenAICompatibleProvider(
            api_key=API_KEY,
            base_url=BASE_URL,
            capabilities=_caps_full(),
            structured_output="auto",
            transport=httpx.MockTransport(handler),
            sleep_fn=lambda _: None,
            rand_fn=lambda: 0.5,
        ).complete(_request())
    assert len(calls) == 1  # no second call


def test_pinned_mode_capability_400_raises_no_downgrade() -> None:
    """capability-400 with a pinned (non-auto) mode raises immediately, no downgrade."""
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return _json_response(
            400, _error_body("This model does not support tools or function calling")
        )

    with pytest.raises(ProviderCapabilityError):
        _provider(
            handler,
            capabilities=_caps_full(),
            structured_output="tool",  # pinned, not auto
        ).complete(_request())
    assert len(calls) == 1
