"""Safe, deterministic provider configuration resolution.

Provider settings are resolved without reading dotenv files or retaining API key
values.  Configuration contains only the *name* of the environment variable that
holds a provider credential.
"""

from __future__ import annotations

import logging
import math
import os
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlsplit

from platformdirs import user_config_dir

logger = logging.getLogger(__name__)

_SOURCE_CLI = "cli"
_SOURCE_ENVIRONMENT = "environment"
_SOURCE_PROJECT = "project_config"
_SOURCE_USER = "user_config"
_SOURCE_PRESET = "provider_preset"
_SOURCE_DEFAULT = "default"
_SOURCE_PHASE1 = "phase1_enforced"

_ENVIRONMENT_FIELDS = {
    "provider": "HALFBLOOD_PROVIDER",
    "model": "HALFBLOOD_MODEL",
    "base_url": "HALFBLOOD_BASE_URL",
    "api_key_env": "HALFBLOOD_API_KEY_ENV",
    "structured_output": "HALFBLOOD_STRUCTURED_OUTPUT",
    "timeout_seconds": "HALFBLOOD_TIMEOUT_SECONDS",
    "max_retries": "HALFBLOOD_MAX_RETRIES",
    "concurrency": "HALFBLOOD_CONCURRENCY",
    "allow_insecure_http": "HALFBLOOD_ALLOW_INSECURE_HTTP",
}

_GENERATION_FIELDS = {
    "provider",
    "model",
    "structured_output",
    "max_retries",
    "concurrency",
    "allow_insecure_http",
}

_PROVIDER_FIELDS = {"base_url", "api_key_env", "timeout_seconds"}
_SECRET_QUERY_NAMES = {"key", "api_key", "apikey", "token", "secret", "access_token"}
_STRUCTURED_OUTPUT_MODES = {"auto", "tool", "function", "json-schema", "prompt"}


class ProviderConfigurationError(ValueError):
    """An unsafe or unresolvable provider configuration.

    Configuration errors are never retryable.
    """


@dataclass(frozen=True)
class ProviderPreset:
    """Static defaults for a named provider profile."""

    name: str
    default_base_url: str | None
    default_key_env: str | None
    default_structured_output: str


PROVIDER_PRESETS: dict[str, ProviderPreset] = {
    "anthropic": ProviderPreset(
        "anthropic", "https://api.anthropic.com", "ANTHROPIC_API_KEY", "tool"
    ),
    "openai": ProviderPreset(
        "openai", "https://api.openai.com/v1", "OPENAI_API_KEY", "function"
    ),
    "openrouter": ProviderPreset(
        "openrouter",
        "https://openrouter.ai/api/v1",
        "OPENROUTER_API_KEY",
        "function",
    ),
    "ollama": ProviderPreset("ollama", "http://127.0.0.1:11434/v1", None, "auto"),
    "lmstudio": ProviderPreset("lmstudio", "http://127.0.0.1:1234/v1", None, "auto"),
    "openai-compatible": ProviderPreset(
        "openai-compatible", None, "HALFBLOOD_API_KEY", "auto"
    ),
}


@dataclass(frozen=True)
class ResolvedConfig:
    """Effective nonsecret generation/provider settings and their origins."""

    provider: str
    model: str
    base_url: str
    api_key_env: str | None
    structured_output: str
    timeout_seconds: float
    max_retries: int
    concurrency: int
    allow_insecure_http: bool
    sources: dict[str, str]

    def safe_repr(self) -> str:
        """Return diagnostics containing settings and sources, but no key values."""
        fields = (
            "provider",
            "model",
            "base_url",
            "api_key_env",
            "structured_output",
            "timeout_seconds",
            "max_retries",
            "concurrency",
            "allow_insecure_http",
        )
        details = ", ".join(
            f"{field}={getattr(self, field)!r} (source={self.sources[field]})"
            for field in fields
        )
        return f"ResolvedConfig({details})"


def _load_toml(path: Path) -> dict[str, Any]:
    """Load one optional TOML file and reject literal provider secrets."""
    if not path.exists():
        return {}
    if not path.is_file():
        raise ProviderConfigurationError(f"Configuration path is not a file: {path}")

    try:
        with path.open("rb") as config_file:
            data = tomllib.load(config_file)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ProviderConfigurationError(f"Could not load configuration file {path}") from exc

    providers = data.get("providers", {})
    if providers is None:
        providers = {}
    if not isinstance(providers, dict):
        raise ProviderConfigurationError(f"[providers] must be a table in {path}")

    def reject_literal_secrets(table: Mapping[str, Any], table_name: str) -> None:
        for key, value in table.items():
            normalized_key = str(key).casefold()
            is_literal_secret = normalized_key == "api_key" or normalized_key.endswith(
                ("_key", "_token", "_secret")
            )
            if is_literal_secret and isinstance(value, str):
                raise ProviderConfigurationError(
                    f"Literal secrets are forbidden in {path}, table [{table_name}]"
                )
            if isinstance(value, dict):
                reject_literal_secrets(value, f"{table_name}.{key}")

    for table_name, table in providers.items():
        if not isinstance(table, dict):
            raise ProviderConfigurationError(
                f"[providers.{table_name}] must be a table in {path}"
            )
        reject_literal_secrets(table, f"providers.{table_name}")

    return data


def _table(config: Mapping[str, Any], name: str, path: Path) -> Mapping[str, Any]:
    value = config.get(name, {})
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ProviderConfigurationError(f"[{name}] must be a table in {path}")
    return value


def _provider_table(
    config: Mapping[str, Any], provider: str, path: Path
) -> Mapping[str, Any]:
    providers = _table(config, "providers", path)
    value = providers.get(provider, {})
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ProviderConfigurationError(
            f"[providers.{provider}] must be a table in {path}"
        )
    return value


def _explicit_value(
    field: str,
    cli: Mapping[str, Any],
    environ: Mapping[str, str],
    project_generation: Mapping[str, Any],
    user_generation: Mapping[str, Any],
    project_provider: Mapping[str, Any],
    user_provider: Mapping[str, Any],
) -> tuple[Any, str] | None:
    """Return the highest-precedence non-None explicit setting."""
    if field in cli and cli[field] is not None:
        return cli[field], _SOURCE_CLI

    env_name = _ENVIRONMENT_FIELDS[field]
    if env_name in environ:
        raw_value: Any = environ[env_name]
        if field == "allow_insecure_http":
            raw_value = raw_value.casefold() in {"1", "true", "yes"}
        return raw_value, _SOURCE_ENVIRONMENT

    project = project_generation if field in _GENERATION_FIELDS else project_provider
    user = user_generation if field in _GENERATION_FIELDS else user_provider
    if field in project and project[field] is not None:
        return project[field], _SOURCE_PROJECT
    if field in user and user[field] is not None:
        return user[field], _SOURCE_USER
    return None


def _require_nonempty_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ProviderConfigurationError(f"{field} must be a non-empty string")
    return value


def _as_float(value: Any, field: str) -> float:
    if isinstance(value, bool):
        raise ProviderConfigurationError(f"{field} must be a number")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ProviderConfigurationError(f"{field} must be a number") from exc
    if not math.isfinite(result) or result <= 0:
        raise ProviderConfigurationError(f"{field} must be greater than zero")
    return result


def _as_nonnegative_int(value: Any, field: str) -> int:
    if isinstance(value, bool):
        raise ProviderConfigurationError(f"{field} must be a non-negative integer")
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise ProviderConfigurationError(f"{field} must be a non-negative integer") from exc
    if result < 0 or isinstance(value, float) and not value.is_integer():
        raise ProviderConfigurationError(f"{field} must be a non-negative integer")
    if isinstance(value, str) and str(result) != value.strip():
        raise ProviderConfigurationError(f"{field} must be a non-negative integer")
    return result


def _as_bool(value: Any, field: str) -> bool:
    if isinstance(value, bool):
        return value
    raise ProviderConfigurationError(f"{field} must be a boolean")


def _validate_base_url(base_url: str, allow_insecure_http: bool) -> None:
    try:
        parsed = urlsplit(base_url)
        host = parsed.hostname
    except ValueError as exc:
        raise ProviderConfigurationError("base_url is invalid") from exc

    if parsed.scheme.casefold() not in {"http", "https"}:
        raise ProviderConfigurationError("base_url scheme must be http or https")
    if host is None:
        raise ProviderConfigurationError("base_url must include a host")
    if parsed.username is not None or parsed.password is not None:
        raise ProviderConfigurationError("base_url must not contain embedded credentials")

    query_names = {name.casefold() for name, _ in parse_qsl(parsed.query, keep_blank_values=True)}
    if query_names & _SECRET_QUERY_NAMES:
        raise ProviderConfigurationError("base_url must not contain secret query parameters")

    loopback_hosts = {"localhost", "127.0.0.1", "::1"}
    if (
        parsed.scheme.casefold() == "http"
        and host.casefold() not in loopback_hosts
        and not allow_insecure_http
    ):
        raise ProviderConfigurationError(
            "Hosted base_url values must use https unless allow_insecure_http is enabled"
        )


def resolve_generation_config(
    cli_overrides: Mapping[str, Any] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    project_config_path: Path | None = None,
    user_config_path: Path | None = None,
) -> ResolvedConfig:
    """Resolve provider settings or raise for any unsafe/unresolvable state."""
    cli = cli_overrides or {}
    environment = os.environ if environ is None else environ
    project_path = project_config_path or Path.cwd() / "halfblood.toml"
    user_path = user_config_path or Path(user_config_dir("halfblood")) / "config.toml"

    project_config = _load_toml(project_path)
    user_config = _load_toml(user_path)
    project_generation = _table(project_config, "generation", project_path)
    user_generation = _table(user_config, "generation", user_path)

    # Provider is needed before selecting the active [providers.<name>] tables.
    provider_setting = _explicit_value(
        "provider",
        cli,
        environment,
        project_generation,
        user_generation,
        {},
        {},
    )
    if provider_setting is None:
        provider, provider_source = "anthropic", _SOURCE_DEFAULT
    else:
        provider = _require_nonempty_string(provider_setting[0], "provider")
        provider_source = provider_setting[1]
    if provider not in PROVIDER_PRESETS:
        raise ProviderConfigurationError(f"Unknown provider: {provider}")
    preset = PROVIDER_PRESETS[provider]

    project_provider = _provider_table(project_config, provider, project_path)
    user_provider = _provider_table(user_config, provider, user_path)

    def explicit(field: str) -> tuple[Any, str] | None:
        return _explicit_value(
            field,
            cli,
            environment,
            project_generation,
            user_generation,
            project_provider,
            user_provider,
        )

    sources: dict[str, str] = {"provider": provider_source}

    model_setting = explicit("model")
    if model_setting is None:
        raise ProviderConfigurationError("model must be explicitly configured")
    model = _require_nonempty_string(model_setting[0], "model")
    sources["model"] = model_setting[1]

    allow_setting = explicit("allow_insecure_http")
    if allow_setting is None:
        allow_insecure_http = False
        sources["allow_insecure_http"] = _SOURCE_DEFAULT
    else:
        allow_insecure_http = _as_bool(allow_setting[0], "allow_insecure_http")
        sources["allow_insecure_http"] = allow_setting[1]

    base_url_setting = explicit("base_url")
    if base_url_setting is None:
        if preset.default_base_url is None:
            raise ProviderConfigurationError(f"base_url is required for provider {provider}")
        base_url = preset.default_base_url
        sources["base_url"] = _SOURCE_PRESET
    else:
        base_url = _require_nonempty_string(base_url_setting[0], "base_url")
        sources["base_url"] = base_url_setting[1]
    _validate_base_url(base_url, allow_insecure_http)

    api_key_setting = explicit("api_key_env")
    if api_key_setting is None:
        api_key_env = preset.default_key_env
        sources["api_key_env"] = _SOURCE_PRESET
    else:
        api_key_env = _require_nonempty_string(api_key_setting[0], "api_key_env")
        sources["api_key_env"] = api_key_setting[1]
    if api_key_env is not None and not environment.get(api_key_env):
        raise ProviderConfigurationError(
            f"Environment variable {api_key_env} is required for provider {provider}"
        )

    structured_setting = explicit("structured_output")
    if structured_setting is None:
        structured_output = preset.default_structured_output
        sources["structured_output"] = _SOURCE_PRESET
    else:
        structured_output = _require_nonempty_string(
            structured_setting[0], "structured_output"
        )
        sources["structured_output"] = structured_setting[1]
    if structured_output not in _STRUCTURED_OUTPUT_MODES:
        raise ProviderConfigurationError(
            f"Unknown structured_output mode: {structured_output}"
        )

    timeout_setting = explicit("timeout_seconds")
    if timeout_setting is None:
        timeout_seconds = 60.0
        sources["timeout_seconds"] = _SOURCE_DEFAULT
    else:
        timeout_seconds = _as_float(timeout_setting[0], "timeout_seconds")
        sources["timeout_seconds"] = timeout_setting[1]

    retries_setting = explicit("max_retries")
    if retries_setting is None:
        max_retries = 2
        sources["max_retries"] = _SOURCE_DEFAULT
    else:
        max_retries = _as_nonnegative_int(retries_setting[0], "max_retries")
        sources["max_retries"] = retries_setting[1]

    concurrency_setting = explicit("concurrency")
    if concurrency_setting is not None:
        requested_concurrency = concurrency_setting[0]
        try:
            requests_one = (
                not isinstance(requested_concurrency, bool)
                and float(requested_concurrency) == 1.0
            )
        except (TypeError, ValueError):
            requests_one = False
        if not requests_one:
            logger.warning(
                "Requested concurrency %r from %s is being held at 1 for Phase 1",
                requested_concurrency,
                concurrency_setting[1],
            )
    concurrency = 1
    sources["concurrency"] = _SOURCE_PHASE1

    return ResolvedConfig(
        provider=provider,
        model=model,
        base_url=base_url,
        api_key_env=api_key_env,
        structured_output=structured_output,
        timeout_seconds=timeout_seconds,
        max_retries=max_retries,
        concurrency=concurrency,
        allow_insecure_http=allow_insecure_http,
        sources=sources,
    )
