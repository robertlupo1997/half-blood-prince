"""Controller-authored contract tests for the provider-agnostic LLM layer
(architecture §§3.2, 4.6; plan P1-T4).

Pins:

* ``GenerationRequest``/``GenerationResult``/``GenerationUsage``/
  ``ProviderCapabilities`` and the ``LLMProvider`` protocol
  (``src/halfblood/generation/providers/base.py``).
* The normalized error taxonomy — 10 classes, each declaring ``retryable``
  (``src/halfblood/generation/errors.py``) — has zero Anthropic/OpenAI
  imports, and never leaks a secret-shaped substring into a constructed
  error's message.
* HTTP status codes classify into the taxonomy only where the status alone
  is unambiguous; ambiguous statuses (400/422/200) are left to the adapter.
* ``halfblood.config.ProviderConfigurationError`` (P1-T3) and this module's
  ``ProviderConfigurationError`` are the SAME class object — no duplicate
  taxonomy member.

No real network calls anywhere in this file.
"""

from __future__ import annotations

import ast
import inspect

import pytest

from halfblood.generation.errors import (
    AnnotationValidationError,
    IncompleteResponseError,
    ProviderAuthenticationError,
    ProviderCapabilityError,
    ProviderConfigurationError,
    ProviderError,
    ProviderNotFoundError,
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
    LLMProvider,
    ProviderCapabilities,
)
from halfblood.generation.schema import RecordAnnotations

# ---------------------------------------------------------------------------
# LLMProvider protocol + request/result dataclasses
# ---------------------------------------------------------------------------


class _FakeProvider:
    """A minimal, protocol-compatible provider — no HTTP, no vendor SDK."""

    def __init__(self, result: GenerationResult) -> None:
        self._result = result
        self.last_request: GenerationRequest | None = None

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            supports_tool_calling=True,
            supports_json_schema=True,
            supports_strict_json_schema=True,
        )

    def complete(self, request: GenerationRequest) -> GenerationResult:
        self.last_request = request
        return self._result


def _sample_request(**overrides: object) -> GenerationRequest:
    fields: dict[str, object] = dict(
        system_prompt="You are Snape, annotating a Potions textbook.",
        user_prompt="Annotate this page.",
        schema={"type": "object", "title": "record_annotations"},
        model="claude-sonnet-5",
        max_tokens=1024,
    )
    fields.update(overrides)
    return GenerationRequest(**fields)  # type: ignore[arg-type]


def _sample_result(**overrides: object) -> GenerationResult:
    fields: dict[str, object] = dict(
        parsed=RecordAnnotations(annotations=[]),
        request_id="req-123",
        finish_reason="stop",
        usage=GenerationUsage(input_tokens=100, output_tokens=20),
        latency_seconds=0.42,
        structured_output_mode="tool",
    )
    fields.update(overrides)
    return GenerationResult(**fields)  # type: ignore[arg-type]


def test_fake_provider_satisfies_the_llm_provider_protocol() -> None:
    provider = _FakeProvider(_sample_result())
    assert isinstance(provider, LLMProvider)


def test_complete_returns_protocol_compatible_result_fields() -> None:
    result = _sample_result()
    provider = _FakeProvider(result)
    request = _sample_request()

    returned = provider.complete(request)

    assert provider.last_request is request
    assert returned.parsed is result.parsed
    assert isinstance(returned.parsed, RecordAnnotations)
    assert returned.request_id == "req-123"
    assert returned.finish_reason == "stop"
    assert returned.usage.input_tokens == 100
    assert returned.usage.output_tokens == 20
    assert returned.usage.total_tokens == 120
    assert returned.latency_seconds == pytest.approx(0.42)
    assert returned.structured_output_mode == "tool"
    assert returned.warnings == ()
    assert returned.attempts == 1


def test_generation_result_accepts_warnings_and_attempts() -> None:
    result = _sample_result(warnings=("text block ignored alongside tool_use",), attempts=2)
    assert result.warnings == ("text block ignored alongside tool_use",)
    assert result.attempts == 2


def test_generation_request_defaults() -> None:
    request = _sample_request()
    assert request.structured_output_mode == "tool"
    assert request.temperature is None
    assert dict(request.metadata) == {}


def test_generation_request_accepts_metadata_and_temperature() -> None:
    request = _sample_request(temperature=0.7, metadata={"unit_id": "page-1", "ordinal": 1})
    assert request.temperature == pytest.approx(0.7)
    assert dict(request.metadata) == {"unit_id": "page-1", "ordinal": 1}


def test_provider_capabilities_fields() -> None:
    caps = ProviderCapabilities(
        supports_tool_calling=True,
        supports_json_schema=False,
        supports_strict_json_schema=False,
    )
    assert caps.supports_tool_calling is True
    assert caps.supports_json_schema is False
    assert caps.supports_prompt_fallback is True  # default
    assert caps.max_output_tokens is None  # default


def _imported_top_level_module_names(module: object) -> set[str]:
    source = inspect.getsource(module)  # type: ignore[arg-type]
    tree = ast.parse(source)
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[0])
    return names


def test_provider_base_module_imports_no_vendor_sdk() -> None:
    import halfblood.generation.providers.base as base_module

    imported = _imported_top_level_module_names(base_module)
    assert "anthropic" not in imported
    assert "openai" not in imported


def test_errors_module_imports_no_vendor_sdk() -> None:
    import halfblood.generation.errors as errors_module

    imported = _imported_top_level_module_names(errors_module)
    assert "anthropic" not in imported
    assert "openai" not in imported


# ---------------------------------------------------------------------------
# Error taxonomy: retryability, base class, HTTP status classification
# ---------------------------------------------------------------------------

_TAXONOMY: list[tuple[type[ProviderError], bool]] = [
    (ProviderConfigurationError, False),
    (ProviderAuthenticationError, False),
    (ProviderNotFoundError, False),
    (ProviderCapabilityError, False),
    (ProviderRateLimitError, True),
    (ProviderTransientError, True),
    (ProviderSafetyRefusal, False),
    (IncompleteResponseError, True),
    (StructuredOutputError, False),
    (AnnotationValidationError, False),
]


@pytest.mark.parametrize("error_cls,expected_retryable", _TAXONOMY)
def test_taxonomy_class_declares_retryability(
    error_cls: type[ProviderError], expected_retryable: bool
) -> None:
    assert error_cls.retryable is expected_retryable
    assert issubclass(error_cls, ProviderError)


def test_taxonomy_has_exactly_ten_classes() -> None:
    assert len(_TAXONOMY) == 10


def test_provider_configuration_error_is_also_a_value_error() -> None:
    assert issubclass(ProviderConfigurationError, ValueError)


def test_config_module_reexports_the_same_configuration_error_class() -> None:
    from halfblood.config import ProviderConfigurationError as ConfigError

    assert ConfigError is ProviderConfigurationError


@pytest.mark.parametrize(
    "status_code,expected_cls",
    [
        (401, ProviderAuthenticationError),
        (403, ProviderAuthenticationError),
        (404, ProviderNotFoundError),
        (408, ProviderTransientError),
        (409, ProviderTransientError),
        (425, ProviderTransientError),
        (429, ProviderRateLimitError),
        (500, ProviderTransientError),
        (502, ProviderTransientError),
        (503, ProviderTransientError),
        (599, ProviderTransientError),
    ],
)
def test_classify_status_code_unambiguous_statuses(
    status_code: int, expected_cls: type[ProviderError]
) -> None:
    assert classify_status_code(status_code) is expected_cls


@pytest.mark.parametrize("status_code", [200, 301, 400, 422])
def test_classify_status_code_ambiguous_statuses_return_none(status_code: int) -> None:
    assert classify_status_code(status_code) is None


# ---------------------------------------------------------------------------
# Secret redaction
# ---------------------------------------------------------------------------


def test_redact_secrets_scrubs_bearer_token() -> None:
    raw = "upstream rejected: Authorization: Bearer sk-ant-fake1234567890 (expired)"
    cleaned = redact_secrets(raw)
    assert "sk-ant-fake1234567890" not in cleaned


def test_redact_secrets_scrubs_query_style_key() -> None:
    raw = "GET https://api.example.com/v1?api_key=super-secret-value failed with 401"
    cleaned = redact_secrets(raw)
    assert "super-secret-value" not in cleaned


def test_redact_secrets_leaves_ordinary_text_untouched() -> None:
    raw = "the model returned a truncated response after 1024 tokens"
    assert redact_secrets(raw) == raw


def test_provider_error_message_is_redacted_on_construction() -> None:
    err = ProviderAuthenticationError(
        "denied, saw header Authorization: Bearer sk-ant-fake999999", status_code=401
    )
    assert "sk-ant-fake999999" not in str(err)
    assert "sk-ant-fake999999" not in repr(err)


def test_provider_error_carries_status_code() -> None:
    err = ProviderNotFoundError("model not found", status_code=404)
    assert err.status_code == 404


def test_rate_limit_error_carries_retry_after() -> None:
    err = ProviderRateLimitError("slow down", status_code=429, retry_after=12.5)
    assert err.retry_after == pytest.approx(12.5)
    assert err.status_code == 429


def test_rate_limit_error_retry_after_defaults_to_none() -> None:
    err = ProviderRateLimitError("slow down", status_code=429)
    assert err.retry_after is None


def test_capability_error_carries_requested_mode() -> None:
    err = ProviderCapabilityError("tools unsupported", requested_mode="tool")
    assert err.requested_mode == "tool"


# ---------------------------------------------------------------------------
# Package-level re-exports (`halfblood.generation`)
# ---------------------------------------------------------------------------


def test_generation_package_exports_public_surface() -> None:
    import halfblood.generation as generation

    expected = {
        "LLMProvider",
        "GenerationRequest",
        "GenerationResult",
        "GenerationUsage",
        "ProviderCapabilities",
        "ProviderError",
        "ProviderConfigurationError",
        "ProviderAuthenticationError",
        "ProviderNotFoundError",
        "ProviderCapabilityError",
        "ProviderRateLimitError",
        "ProviderTransientError",
        "ProviderSafetyRefusal",
        "IncompleteResponseError",
        "StructuredOutputError",
        "AnnotationValidationError",
        "classify_status_code",
        "redact_secrets",
        "GenerationReport",
        "PageGenerationStatus",
        "AllPagesFailedError",
    }
    assert expected.issubset(set(generation.__all__))
    for name in expected:
        assert hasattr(generation, name), f"halfblood.generation is missing {name!r}"
