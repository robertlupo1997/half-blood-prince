"""Static provider profiles and adapter construction."""

from __future__ import annotations

import enum
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from halfblood.generation.errors import ProviderConfigurationError
from halfblood.generation.providers.anthropic import AnthropicProvider
from halfblood.generation.providers.base import LLMProvider, ProviderCapabilities
from halfblood.generation.providers.openai_compat import OpenAICompatibleProvider
from halfblood.generation.providers.stub import StubProvider

if TYPE_CHECKING:
    from halfblood.config import ResolvedConfig


class AdapterKind(str, enum.Enum):  # noqa: UP042 - pinned public interface
    """String enum identifying one of the two supported wire adapters."""

    ANTHROPIC = "anthropic"
    OPENAI_COMPATIBLE = "openai_compatible"

    def __str__(self) -> str:
        return self.value

@dataclass(frozen=True)
class ProviderProfile:
    name: str
    adapter: AdapterKind
    capabilities: ProviderCapabilities
    default_structured_output: str
    sends_attribution_headers: bool = field(default=False)


def _capabilities(
    *,
    json_schema: bool,
    strict_json_schema: bool,
) -> ProviderCapabilities:
    return ProviderCapabilities(
        supports_tool_calling=True,
        supports_json_schema=json_schema,
        supports_strict_json_schema=strict_json_schema,
        supports_prompt_fallback=True,
        max_output_tokens=None,
    )


PROVIDER_PROFILES: dict[str, ProviderProfile] = {
    "anthropic": ProviderProfile(
        name="anthropic",
        adapter=AdapterKind.ANTHROPIC,
        capabilities=_capabilities(json_schema=False, strict_json_schema=False),
        default_structured_output="tool",
    ),
    "openai": ProviderProfile(
        name="openai",
        adapter=AdapterKind.OPENAI_COMPATIBLE,
        capabilities=_capabilities(json_schema=True, strict_json_schema=True),
        default_structured_output="function",
    ),
    "openrouter": ProviderProfile(
        name="openrouter",
        adapter=AdapterKind.OPENAI_COMPATIBLE,
        capabilities=_capabilities(json_schema=True, strict_json_schema=True),
        default_structured_output="function",
        sends_attribution_headers=True,
    ),
    "ollama": ProviderProfile(
        name="ollama",
        adapter=AdapterKind.OPENAI_COMPATIBLE,
        capabilities=_capabilities(json_schema=True, strict_json_schema=False),
        default_structured_output="auto",
    ),
    "lmstudio": ProviderProfile(
        name="lmstudio",
        adapter=AdapterKind.OPENAI_COMPATIBLE,
        capabilities=_capabilities(json_schema=True, strict_json_schema=False),
        default_structured_output="auto",
    ),
    "openai-compatible": ProviderProfile(
        name="openai-compatible",
        adapter=AdapterKind.OPENAI_COMPATIBLE,
        capabilities=_capabilities(json_schema=False, strict_json_schema=False),
        default_structured_output="auto",
    ),
}


def get_profile(name: str) -> ProviderProfile:
    """Return the named profile or raise a normalized configuration error."""
    try:
        return PROVIDER_PROFILES[name]
    except KeyError as exc:
        raise ProviderConfigurationError(f"Unknown provider: {name}") from exc


def build_provider(
    config: ResolvedConfig,
    *,
    api_key: str | None,
    attribution: Mapping[str, str] | None = None,
) -> LLMProvider:
    """Construct an adapter from already-resolved, nonsecret configuration."""
    if config.provider == "stub":
        return StubProvider()
    profile = get_profile(config.provider)
    if profile.adapter is AdapterKind.ANTHROPIC:
        if api_key is None:
            raise ProviderConfigurationError("Anthropic requires an API key")
        return AnthropicProvider(
            api_key,
            base_url=config.base_url,
            timeout_seconds=config.timeout_seconds,
            max_retries=config.max_retries,
        )

    extra_headers = (
        attribution
        if profile.sends_attribution_headers and attribution is not None
        else None
    )
    return OpenAICompatibleProvider(
        api_key,
        base_url=config.base_url,
        capabilities=profile.capabilities,
        structured_output=config.structured_output,
        timeout_seconds=config.timeout_seconds,
        max_retries=config.max_retries,
        extra_headers=extra_headers,
    )
