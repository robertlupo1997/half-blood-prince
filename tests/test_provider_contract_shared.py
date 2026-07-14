"""Shared provider contract suite — parametrized over AnthropicProvider and OpenAICompatibleProvider.

Asserts the normalized invariants that BOTH adapters must satisfy per the LLMProvider
protocol (P1-T4). Each adapter receives a MockTransport returning its own valid
success-format response; no network calls are made anywhere in this file.

This file is intentionally separate from test_provider_contract.py so that its
ModuleNotFoundError on openai_compat / registry (not yet built) does not break the
~40 already-green tests in the existing file.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from halfblood.generation.providers.openai_compat import OpenAICompatibleProvider

from halfblood.generation.providers.anthropic import AnthropicProvider
from halfblood.generation.providers.base import (
    GenerationRequest,
    GenerationResult,
    GenerationUsage,
    LLMProvider,
    ProviderCapabilities,
)
from halfblood.generation.schema import RecordAnnotations, generate_annotation_schema

# ---------------------------------------------------------------------------
# Per-adapter valid-success mock responses
# ---------------------------------------------------------------------------

_ANTHROPIC_SUCCESS: dict = {
    "id": "msg_shared_01",
    "type": "message",
    "role": "assistant",
    "content": [
        {
            "type": "tool_use",
            "id": "toolu_shared_01",
            "name": "record_annotations",
            "input": {"annotations": []},
        }
    ],
    "stop_reason": "tool_use",
    "usage": {"input_tokens": 100, "output_tokens": 50},
}

_OPENAI_COMPAT_SUCCESS: dict = {
    "id": "chatcmpl-shared-01",
    "choices": [
        {
            "message": {
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": "call_shared_01",
                        "type": "function",
                        "function": {
                            "name": "record_annotations",
                            "arguments": json.dumps({"annotations": []}),
                        },
                    }
                ],
            },
            "finish_reason": "tool_calls",
        }
    ],
    "usage": {"prompt_tokens": 100, "completion_tokens": 50},
}


# ---------------------------------------------------------------------------
# Provider factories
# ---------------------------------------------------------------------------


def _make_anthropic() -> AnthropicProvider:
    return AnthropicProvider(
        api_key="sk-ant-shared-fake",
        transport=httpx.MockTransport(
            lambda r: httpx.Response(200, json=_ANTHROPIC_SUCCESS)
        ),
        sleep_fn=lambda _: None,
        rand_fn=lambda: 0.5,
    )


def _make_openai_compat() -> OpenAICompatibleProvider:
    return OpenAICompatibleProvider(
        api_key="sk-openai-shared-fake",
        base_url="https://api.example.com/v1",
        capabilities=ProviderCapabilities(
            supports_tool_calling=True,
            supports_json_schema=False,
            supports_strict_json_schema=False,
            supports_prompt_fallback=True,
        ),
        structured_output="tool",
        transport=httpx.MockTransport(
            lambda r: httpx.Response(200, json=_OPENAI_COMPAT_SUCCESS)
        ),
        sleep_fn=lambda _: None,
        rand_fn=lambda: 0.5,
    )


def _sample_request() -> GenerationRequest:
    return GenerationRequest(
        system_prompt="You are the Prince.",
        user_prompt="Annotate this page.",
        schema=generate_annotation_schema(),
        model="test-model",
        max_tokens=1024,
    )


# ---------------------------------------------------------------------------
# Parametrized fixture
# ---------------------------------------------------------------------------


@pytest.fixture(
    params=["anthropic", "openai_compat"],
    ids=["anthropic", "openai_compat"],
)
def provider_and_result(request: pytest.FixtureRequest) -> GenerationResult:
    if request.param == "anthropic":
        p: LLMProvider = _make_anthropic()
    else:
        p = _make_openai_compat()
    return p.complete(_sample_request())


# ---------------------------------------------------------------------------
# Shared invariants
# ---------------------------------------------------------------------------


def test_complete_returns_generation_result(provider_and_result: Any) -> None:
    assert isinstance(provider_and_result, GenerationResult)


def test_parsed_is_record_annotations(provider_and_result: Any) -> None:
    assert isinstance(provider_and_result.parsed, RecordAnnotations)


def test_finish_reason_is_nonempty_string(provider_and_result: Any) -> None:
    result: GenerationResult = provider_and_result
    assert isinstance(result.finish_reason, str)
    assert result.finish_reason  # non-empty


def test_usage_is_generation_usage(provider_and_result: Any) -> None:
    result: GenerationResult = provider_and_result
    assert isinstance(result.usage, GenerationUsage)
    assert result.usage.input_tokens >= 0
    assert result.usage.output_tokens >= 0


def test_attempts_at_least_one(provider_and_result: Any) -> None:
    result: GenerationResult = provider_and_result
    assert result.attempts >= 1


def test_structured_output_mode_is_set(provider_and_result: Any) -> None:
    """structured_output_mode is a non-empty string — exact value differs per adapter."""
    result: GenerationResult = provider_and_result
    assert result.structured_output_mode  # non-None, non-empty


def test_capabilities_returns_provider_capabilities() -> None:
    """capabilities property on both adapters returns a ProviderCapabilities instance."""
    for make in (_make_anthropic, _make_openai_compat):
        provider = make()
        caps = provider.capabilities
        assert isinstance(caps, ProviderCapabilities)
        # At least one mode must be advertised as supported
        assert (
            caps.supports_tool_calling
            or caps.supports_json_schema
            or caps.supports_prompt_fallback
        )
