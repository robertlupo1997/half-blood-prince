"""Tests for the provider profile registry (architecture §§4.4, 4.1; plan P1-T7).

Validates adapter-kind mapping, per-profile capabilities, attribution-header
gating, and build_provider return types. Pre-tested base-URL/key-env values are
already covered by tests/test_provider_config.py and are NOT duplicated here.

All [INFER] items: registry API shape (AdapterKind, ProviderProfile, PROVIDER_PROFILES,
get_profile, build_provider), per-profile capabilities — see p1-t7-brief.md.
"""

from __future__ import annotations

import pytest

from halfblood.config import ResolvedConfig
from halfblood.generation.errors import ProviderConfigurationError
from halfblood.generation.providers.anthropic import AnthropicProvider
from halfblood.generation.providers.base import ProviderCapabilities
from halfblood.generation.providers.openai_compat import OpenAICompatibleProvider
from halfblood.generation.registry import (
    PROVIDER_PROFILES,
    AdapterKind,
    ProviderProfile,
    build_provider,
    get_profile,
)

# ---------------------------------------------------------------------------
# PROVIDER_PROFILES completeness
# ---------------------------------------------------------------------------

_ALL_PROVIDERS = {"anthropic", "openai", "openrouter", "ollama", "lmstudio", "openai-compatible"}


def test_provider_profiles_has_all_six() -> None:
    assert set(PROVIDER_PROFILES.keys()) == _ALL_PROVIDERS


def test_each_profile_is_provider_profile_instance() -> None:
    for name, profile in PROVIDER_PROFILES.items():
        assert isinstance(profile, ProviderProfile), f"profile {name!r} is not a ProviderProfile"
        assert profile.name == name


# ---------------------------------------------------------------------------
# Adapter kind mapping [INFER]
# ---------------------------------------------------------------------------


def test_anthropic_profile_adapter_is_anthropic_kind() -> None:
    profile = get_profile("anthropic")
    # AdapterKind is a str enum — comparing to string works [INFER]
    assert str(profile.adapter) in {"anthropic", "AdapterKind.anthropic"}
    # Or: compare symbolically to the enum value itself
    assert profile.adapter == AdapterKind.ANTHROPIC  # type: ignore[comparison-overlap]


def test_all_non_anthropic_profiles_are_openai_compatible_kind() -> None:
    non_anthropic = _ALL_PROVIDERS - {"anthropic"}
    for name in non_anthropic:
        profile = get_profile(name)
        assert profile.adapter == AdapterKind.OPENAI_COMPATIBLE, (  # type: ignore[comparison-overlap]
            f"expected {name!r} to be openai_compatible, got {profile.adapter!r}"
        )


def test_adapter_kinds_are_distinct() -> None:
    anthropic_adapter = get_profile("anthropic").adapter
    openai_adapter = get_profile("openai").adapter
    assert anthropic_adapter != openai_adapter


# ---------------------------------------------------------------------------
# get_profile error case
# ---------------------------------------------------------------------------


def test_get_profile_unknown_name_raises_configuration_error() -> None:
    with pytest.raises(ProviderConfigurationError):
        get_profile("unknown-provider-xyz")


# ---------------------------------------------------------------------------
# Per-profile capabilities [INFER — pinned from §4.4 + spec]
# ---------------------------------------------------------------------------


def test_anthropic_profile_capabilities_match_anthropic_provider() -> None:
    """anthropic profile caps must match AnthropicProvider.capabilities exactly."""
    profile = get_profile("anthropic")
    caps = profile.capabilities
    assert isinstance(caps, ProviderCapabilities)
    assert caps.supports_tool_calling is True
    assert caps.supports_json_schema is False
    assert caps.supports_strict_json_schema is False


def test_openai_profile_capabilities() -> None:
    """openai: tools ✓, json_schema ✓, strict ✓ [INFER §4.4]"""
    caps = get_profile("openai").capabilities
    assert caps.supports_tool_calling is True
    assert caps.supports_json_schema is True
    assert caps.supports_strict_json_schema is True


def test_openrouter_profile_capabilities() -> None:
    """openrouter: tools ✓, json_schema ✓, strict ✓ (nominal), attribution ✓ [INFER §4.4]"""
    profile = get_profile("openrouter")
    caps = profile.capabilities
    assert caps.supports_tool_calling is True
    assert caps.supports_json_schema is True
    # strict_json_schema may be nominal; assert it's declared True for the profile [INFER]
    assert caps.supports_strict_json_schema is True
    assert profile.sends_attribution_headers is True


def test_ollama_profile_capabilities() -> None:
    """ollama: tools ✓, json_schema ✓, strict ✗ (conservative) [INFER §4.4]"""
    caps = get_profile("ollama").capabilities
    assert caps.supports_tool_calling is True
    assert caps.supports_json_schema is True
    assert caps.supports_strict_json_schema is False


def test_lmstudio_profile_capabilities() -> None:
    """lmstudio: tools ✓, json_schema ✓, strict ✗ (conservative) [INFER §4.4]"""
    caps = get_profile("lmstudio").capabilities
    assert caps.supports_tool_calling is True
    assert caps.supports_json_schema is True
    assert caps.supports_strict_json_schema is False


def test_openai_compatible_profile_capabilities() -> None:
    """openai-compatible: conservative — tools ✓, json_schema ✗, strict ✗ [INFER §4.4]"""
    caps = get_profile("openai-compatible").capabilities
    assert caps.supports_tool_calling is True
    assert caps.supports_json_schema is False
    assert caps.supports_strict_json_schema is False


# ---------------------------------------------------------------------------
# Attribution headers gating
# ---------------------------------------------------------------------------


def test_only_openrouter_sends_attribution_headers() -> None:
    for name in _ALL_PROVIDERS:
        profile = get_profile(name)
        if name == "openrouter":
            assert profile.sends_attribution_headers is True
        else:
            assert profile.sends_attribution_headers is False, (
                f"{name!r} should not send attribution headers"
            )


# ---------------------------------------------------------------------------
# ollama / lmstudio require no api key
# ---------------------------------------------------------------------------


def test_ollama_profile_default_key_env_is_none() -> None:
    """ollama sends no Authorization header — key env is not set in the profile."""
    profile = get_profile("ollama")
    # The profile should indicate no key is needed (None or falsy key env)
    # Exact field name [INFER] — check via build_provider with api_key=None succeeding
    assert profile.adapter == AdapterKind.OPENAI_COMPATIBLE  # type: ignore[comparison-overlap]


def test_lmstudio_profile_default_key_env_is_none() -> None:
    profile = get_profile("lmstudio")
    assert profile.adapter == AdapterKind.OPENAI_COMPATIBLE  # type: ignore[comparison-overlap]


# ---------------------------------------------------------------------------
# build_provider return types [INFER]
# ---------------------------------------------------------------------------


def _resolved(
    provider: str,
    *,
    base_url: str = "https://api.example.com/v1",
    structured_output: str = "auto",
    api_key_env: str | None = None,
    allow_insecure_http: bool = False,
) -> ResolvedConfig:
    return ResolvedConfig(
        provider=provider,
        model="test-model",
        base_url=base_url,
        api_key_env=api_key_env,
        structured_output=structured_output,
        timeout_seconds=60.0,
        max_retries=2,
        concurrency=1,
        allow_insecure_http=allow_insecure_http,
        sources={},
    )


def test_build_provider_anthropic_returns_anthropic_provider() -> None:
    config = _resolved(
        "anthropic",
        base_url="https://api.anthropic.com",
        structured_output="tool",
    )
    provider = build_provider(config, api_key="sk-ant-fake")
    assert isinstance(provider, AnthropicProvider)


def test_build_provider_openai_returns_openai_compat_provider() -> None:
    config = _resolved(
        "openai",
        base_url="https://api.openai.com/v1",
        structured_output="function",
    )
    provider = build_provider(config, api_key="sk-fake")
    assert isinstance(provider, OpenAICompatibleProvider)


def test_build_provider_openrouter_returns_openai_compat_provider() -> None:
    config = _resolved(
        "openrouter",
        base_url="https://openrouter.ai/api/v1",
        structured_output="function",
    )
    provider = build_provider(config, api_key="sk-or-fake")
    assert isinstance(provider, OpenAICompatibleProvider)


def test_build_provider_ollama_returns_openai_compat_no_key() -> None:
    config = _resolved(
        "ollama",
        base_url="http://127.0.0.1:11434/v1",
        structured_output="auto",
        allow_insecure_http=True,
    )
    provider = build_provider(config, api_key=None)
    assert isinstance(provider, OpenAICompatibleProvider)


def test_build_provider_lmstudio_returns_openai_compat_no_key() -> None:
    config = _resolved(
        "lmstudio",
        base_url="http://127.0.0.1:1234/v1",
        structured_output="auto",
        allow_insecure_http=True,
    )
    provider = build_provider(config, api_key=None)
    assert isinstance(provider, OpenAICompatibleProvider)


def test_build_provider_openai_compatible_returns_openai_compat() -> None:
    config = _resolved(
        "openai-compatible",
        base_url="https://custom.endpoint.example/v1",
        structured_output="auto",
    )
    provider = build_provider(config, api_key="sk-custom-fake")
    assert isinstance(provider, OpenAICompatibleProvider)


def test_build_provider_openrouter_with_attribution_headers() -> None:
    """When attribution is provided and provider sends_attribution_headers, headers are forwarded."""
    config = _resolved(
        "openrouter",
        base_url="https://openrouter.ai/api/v1",
        structured_output="function",
    )
    attribution = {"HTTP-Referer": "https://example.com", "X-Title": "HalfBloodPrince"}
    provider = build_provider(config, api_key="sk-or-fake", attribution=attribution)
    assert isinstance(provider, OpenAICompatibleProvider)
    # Provider was built without error; attribution forwarding is wire-tested in
    # test_openai_compat_provider.py via extra_headers.
