"""Controller-authored, test-first contract for P1-T3 (provider configuration).

Ground truth: docs/superpowers/specs/2026-07-11-full-project-architecture.md SS4.4-4.6;
.superpowers/sdd/p1-t3-brief.md "Pinned interface" (authored from scratch -- no
pre-draft existed for this task, unlike P1-T1/T2). These tests are the frozen
interface Codex builds against -- do not edit them to make an implementation pass.

No network calls anywhere in this file.
"""

import logging

import pytest

from halfblood.config import (
    PROVIDER_PRESETS,
    ProviderConfigurationError,
    resolve_generation_config,
)

_MISSING = "does-not-exist.toml"


def _resolve(
    tmp_path,
    cli_overrides=None,
    environ=None,
    project_toml=None,
    user_toml=None,
    **extra_cli,
):
    """Wrapper reducing boilerplate: writes TOML content (if given) to files
    under tmp_path, defaults model to a harmless value unless the caller's
    cli_overrides already sets one, and defaults both config paths to
    nonexistent files unless TOML content is supplied."""
    overrides = dict(cli_overrides or {})
    overrides.setdefault("model", "test-model")
    overrides.update(extra_cli)

    project_path = tmp_path / "project.toml"
    if project_toml is not None:
        project_path.write_text(project_toml, encoding="utf-8")
    else:
        project_path = tmp_path / _MISSING

    user_path = tmp_path / "user.toml"
    if user_toml is not None:
        user_path.write_text(user_toml, encoding="utf-8")
    else:
        user_path = tmp_path / ("user_" + _MISSING)

    return resolve_generation_config(
        overrides,
        environ=environ or {},
        project_config_path=project_path,
        user_config_path=user_path,
    )


# --- provider preset table sanity -----------------------------------------


def test_provider_presets_match_architecture_table():
    assert PROVIDER_PRESETS["anthropic"].default_base_url == "https://api.anthropic.com"
    assert PROVIDER_PRESETS["anthropic"].default_key_env == "ANTHROPIC_API_KEY"
    assert PROVIDER_PRESETS["anthropic"].default_structured_output == "tool"

    assert PROVIDER_PRESETS["openai"].default_base_url == "https://api.openai.com/v1"
    assert PROVIDER_PRESETS["openai"].default_key_env == "OPENAI_API_KEY"

    assert PROVIDER_PRESETS["openrouter"].default_base_url == "https://openrouter.ai/api/v1"
    assert PROVIDER_PRESETS["openrouter"].default_key_env == "OPENROUTER_API_KEY"

    assert PROVIDER_PRESETS["ollama"].default_base_url == "http://127.0.0.1:11434/v1"
    assert PROVIDER_PRESETS["ollama"].default_key_env is None

    assert PROVIDER_PRESETS["lmstudio"].default_base_url == "http://127.0.0.1:1234/v1"
    assert PROVIDER_PRESETS["lmstudio"].default_key_env is None

    assert PROVIDER_PRESETS["openai-compatible"].default_base_url is None
    assert PROVIDER_PRESETS["openai-compatible"].default_key_env == "HALFBLOOD_API_KEY"


# --- 1/2. full precedence chain: provider, model, base_url ----------------


def test_provider_precedence_full_chain(tmp_path):
    """Every step resolves to a real, fully-satisfiable provider (its required
    API key, if any, is present in environ) -- this test exercises precedence
    ordering ONLY, not the missing-key path (see test_hosted_provider_missing_key_raises
    for that). A provider resolved via ANY layer with its key absent must still
    raise, unconditionally -- do not special-case project/user-sourced providers."""
    project_toml = "[generation]\nprovider = \"openrouter\"\n"
    user_toml = "[generation]\nprovider = \"openai\"\n"

    # user only -> user wins (nothing above it)
    result = _resolve(
        tmp_path,
        user_toml=user_toml,
        provider=None,
        environ={"OPENAI_API_KEY": "sk-fake"},
    )
    assert result.provider == "openai"
    assert result.sources["provider"] == "user_config"

    # project + user -> project wins
    result = _resolve(
        tmp_path,
        project_toml=project_toml,
        user_toml=user_toml,
        environ={"OPENROUTER_API_KEY": "sk-fake"},
    )
    assert result.provider == "openrouter"
    assert result.sources["provider"] == "project_config"

    # + environment -> environment wins (ollama needs no key)
    result = _resolve(
        tmp_path,
        project_toml=project_toml,
        user_toml=user_toml,
        environ={"HALFBLOOD_PROVIDER": "ollama"},
    )
    assert result.provider == "ollama"
    assert result.sources["provider"] == "environment"

    # + CLI -> CLI wins (lmstudio needs no key)
    result = _resolve(
        tmp_path,
        project_toml=project_toml,
        user_toml=user_toml,
        environ={"HALFBLOOD_PROVIDER": "ollama"},
        provider="lmstudio",
    )
    assert result.provider == "lmstudio"
    assert result.sources["provider"] == "cli"


def test_provider_from_project_config_still_requires_its_key(tmp_path):
    """The missing-key check must apply unconditionally, regardless of which
    layer selected the provider -- project/user TOML is not a special case."""
    project_toml = "[generation]\nprovider = \"openai\"\n"
    with pytest.raises(ProviderConfigurationError):
        _resolve(tmp_path, project_toml=project_toml, environ={})


def test_provider_defaults_to_anthropic_when_unset(tmp_path):
    result = _resolve(
        tmp_path,
        environ={"ANTHROPIC_API_KEY": "sk-fake"},
    )
    assert result.provider == "anthropic"
    assert result.sources["provider"] == "default"


def test_model_precedence_full_chain(tmp_path):
    project_toml = '[generation]\nmodel = "project/model"\n'
    user_toml = '[generation]\nmodel = "user/model"\n'

    result = _resolve(
        tmp_path,
        cli_overrides={"model": None, "provider": "ollama"},
        user_toml=user_toml,
    )
    assert result.model == "user/model"
    assert result.sources["model"] == "user_config"

    result = _resolve(
        tmp_path,
        cli_overrides={"model": None, "provider": "ollama"},
        project_toml=project_toml,
        user_toml=user_toml,
    )
    assert result.model == "project/model"
    assert result.sources["model"] == "project_config"

    result = _resolve(
        tmp_path,
        cli_overrides={"model": None, "provider": "ollama"},
        project_toml=project_toml,
        user_toml=user_toml,
        environ={"HALFBLOOD_MODEL": "env/model"},
    )
    assert result.model == "env/model"
    assert result.sources["model"] == "environment"

    result = _resolve(
        tmp_path,
        provider="ollama",
        project_toml=project_toml,
        user_toml=user_toml,
        environ={"HALFBLOOD_MODEL": "env/model"},
        model="cli/model",
    )
    assert result.model == "cli/model"
    assert result.sources["model"] == "cli"


def test_model_missing_everywhere_raises(tmp_path):
    with pytest.raises(ProviderConfigurationError):
        _resolve(tmp_path, cli_overrides={"model": None, "provider": "ollama"})


def test_base_url_precedence_and_provider_preset_fallback(tmp_path):
    project_toml = (
        "[providers.openrouter]\nbase_url = \"https://project.example.test\"\n"
    )
    user_toml = "[providers.openrouter]\nbase_url = \"https://user.example.test\"\n"

    # nothing set -> provider preset default
    result = _resolve(tmp_path, provider="openrouter", environ={"OPENROUTER_API_KEY": "x"})
    assert result.base_url == "https://openrouter.ai/api/v1"
    assert result.sources["base_url"] == "provider_preset"

    # user only
    result = _resolve(
        tmp_path,
        provider="openrouter",
        user_toml=user_toml,
        environ={"OPENROUTER_API_KEY": "x"},
    )
    assert result.base_url == "https://user.example.test"
    assert result.sources["base_url"] == "user_config"

    # project beats user
    result = _resolve(
        tmp_path,
        provider="openrouter",
        project_toml=project_toml,
        user_toml=user_toml,
        environ={"OPENROUTER_API_KEY": "x"},
    )
    assert result.base_url == "https://project.example.test"
    assert result.sources["base_url"] == "project_config"

    # env beats project
    result = _resolve(
        tmp_path,
        provider="openrouter",
        project_toml=project_toml,
        user_toml=user_toml,
        environ={
            "OPENROUTER_API_KEY": "x",
            "HALFBLOOD_BASE_URL": "https://env.example.test",
        },
    )
    assert result.base_url == "https://env.example.test"
    assert result.sources["base_url"] == "environment"

    # cli beats env
    result = _resolve(
        tmp_path,
        provider="openrouter",
        project_toml=project_toml,
        user_toml=user_toml,
        environ={
            "OPENROUTER_API_KEY": "x",
            "HALFBLOOD_BASE_URL": "https://env.example.test",
        },
        base_url="https://cli.example.test",
    )
    assert result.base_url == "https://cli.example.test"
    assert result.sources["base_url"] == "cli"


def test_base_url_required_for_openai_compatible_with_no_default(tmp_path):
    with pytest.raises(ProviderConfigurationError):
        _resolve(
            tmp_path,
            provider="openai-compatible",
            environ={"HALFBLOOD_API_KEY": "x"},
        )


# --- 3. URL validation ------------------------------------------------------


def test_base_url_loopback_http_is_allowed(tmp_path):
    result = _resolve(
        tmp_path,
        provider="ollama",
        base_url="http://127.0.0.1:11434/v1",
    )
    assert result.base_url == "http://127.0.0.1:11434/v1"


def test_base_url_hosted_http_rejected_without_allow_insecure(tmp_path):
    with pytest.raises(ProviderConfigurationError):
        _resolve(
            tmp_path,
            provider="openai-compatible",
            base_url="http://hosted.example.test/v1",
            environ={"HALFBLOOD_API_KEY": "x"},
        )


def test_base_url_hosted_http_allowed_with_allow_insecure(tmp_path):
    result = _resolve(
        tmp_path,
        provider="openai-compatible",
        base_url="http://hosted.example.test/v1",
        allow_insecure_http=True,
        environ={"HALFBLOOD_API_KEY": "x"},
    )
    assert result.base_url == "http://hosted.example.test/v1"
    assert result.allow_insecure_http is True


def test_base_url_rejects_embedded_credentials(tmp_path):
    with pytest.raises(ProviderConfigurationError):
        _resolve(
            tmp_path,
            provider="openai-compatible",
            base_url="https://user:pass@hosted.example.test/v1",
            environ={"HALFBLOOD_API_KEY": "x"},
        )


def test_base_url_rejects_secret_shaped_query_param(tmp_path):
    with pytest.raises(ProviderConfigurationError):
        _resolve(
            tmp_path,
            provider="openai-compatible",
            base_url="https://hosted.example.test/v1?api_key=sk-shouldnotbehere",
            environ={"HALFBLOOD_API_KEY": "x"},
        )


# --- 4. api_key_env resolution ----------------------------------------------


def test_api_key_env_override_takes_precedence_over_preset(tmp_path):
    result = _resolve(
        tmp_path,
        provider="anthropic",
        api_key_env="MY_CUSTOM_ANTHROPIC_KEY",
        environ={
            "MY_CUSTOM_ANTHROPIC_KEY": "sk-fake",
            "ANTHROPIC_API_KEY": "sk-should-not-be-used",
        },
    )
    assert result.api_key_env == "MY_CUSTOM_ANTHROPIC_KEY"
    assert result.sources["api_key_env"] == "cli"


def test_hosted_provider_missing_key_raises(tmp_path):
    with pytest.raises(ProviderConfigurationError):
        _resolve(tmp_path, provider="anthropic", environ={})


def test_local_provider_requires_no_key(tmp_path):
    result = _resolve(tmp_path, provider="ollama", environ={})
    assert result.api_key_env is None


# --- 5. literal secret in project config ------------------------------------


def test_project_toml_literal_api_key_raises(tmp_path):
    project_toml = (
        "[providers.anthropic]\n"
        "api_key = \"sk-ant-literal-secret-should-be-rejected\"\n"
    )
    with pytest.raises(ProviderConfigurationError):
        _resolve(
            tmp_path,
            provider="anthropic",
            project_toml=project_toml,
            environ={"ANTHROPIC_API_KEY": "sk-fake"},
        )


def test_project_toml_api_key_env_name_is_fine(tmp_path):
    project_toml = (
        "[providers.anthropic]\n"
        "api_key_env = \"CUSTOM_KEY_VAR\"\n"
    )
    result = _resolve(
        tmp_path,
        provider="anthropic",
        project_toml=project_toml,
        environ={"CUSTOM_KEY_VAR": "sk-fake"},
    )
    assert result.api_key_env == "CUSTOM_KEY_VAR"


# --- 6. concurrency unlocked: clamp 1..8, default 3 -------------------------
# Phase-1 hard-lock removed.  Concurrency is now a user-settable parameter
# clamped to the range [1, 8].  Values inside that range pass through without a
# warning; values outside it are clamped and a WARNING is emitted.


def test_concurrency_valid_value_passes_through(tmp_path, caplog):
    """concurrency=3 (inside 1..8) resolves as-is with no warning."""
    project_toml = "[generation]\nconcurrency = 3\n"
    with caplog.at_level(logging.WARNING):
        result = _resolve(
            tmp_path,
            provider="ollama",
            project_toml=project_toml,
        )

    assert result.concurrency == 3
    assert result.sources["concurrency"] == "project_config"
    assert not any("concurrency" in record.message.lower() for record in caplog.records)


def test_concurrency_default_is_three_when_not_configured(tmp_path, caplog):
    """When no concurrency is set, default is 3 and no warning is emitted."""
    with caplog.at_level(logging.WARNING):
        result = _resolve(tmp_path, provider="ollama")

    assert result.concurrency == 3
    assert result.sources["concurrency"] == "default"
    assert not any("concurrency" in record.message.lower() for record in caplog.records)


def test_concurrency_above_max_clamped_to_eight(tmp_path, caplog):
    """concurrency=9 (> 8) is clamped to 8 with a WARNING."""
    project_toml = "[generation]\nconcurrency = 9\n"
    with caplog.at_level(logging.WARNING):
        result = _resolve(
            tmp_path,
            provider="ollama",
            project_toml=project_toml,
        )

    assert result.concurrency == 8
    assert any("concurrency" in record.message.lower() for record in caplog.records)


def test_concurrency_below_min_clamped_to_one(tmp_path, caplog):
    """concurrency=0 (< 1) is clamped to 1 with a WARNING."""
    project_toml = "[generation]\nconcurrency = 0\n"
    with caplog.at_level(logging.WARNING):
        result = _resolve(
            tmp_path,
            provider="ollama",
            project_toml=project_toml,
        )

    assert result.concurrency == 1
    assert any("concurrency" in record.message.lower() for record in caplog.records)


def test_concurrency_explicit_one_no_warning(tmp_path, caplog):
    """Explicitly requesting concurrency=1 (sequential) is valid and silent."""
    project_toml = "[generation]\nconcurrency = 1\n"
    with caplog.at_level(logging.WARNING):
        result = _resolve(
            tmp_path,
            provider="ollama",
            project_toml=project_toml,
        )

    assert result.concurrency == 1
    assert not any("concurrency" in record.message.lower() for record in caplog.records)


# --- 7. unknown provider -----------------------------------------------------


def test_unknown_provider_raises(tmp_path):
    with pytest.raises(ProviderConfigurationError):
        _resolve(tmp_path, provider="not-a-real-provider")


# --- default project_config_path discovery (cwd) -----------------------------


def test_project_config_path_defaults_to_cwd_halfblood_toml(tmp_path, monkeypatch):
    (tmp_path / "halfblood.toml").write_text(
        '[generation]\nprovider = "openrouter"\n', encoding="utf-8"
    )
    monkeypatch.chdir(tmp_path)

    result = resolve_generation_config(
        {"model": "test-model"},
        environ={"OPENROUTER_API_KEY": "sk-fake"},
        user_config_path=tmp_path / _MISSING,
    )

    assert result.provider == "openrouter"
    assert result.sources["provider"] == "project_config"


# --- 8. .env is never consulted ----------------------------------------------


def test_dotenv_file_never_consulted(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text(
        "ANTHROPIC_API_KEY=sk-from-dotenv-should-never-be-used\n", encoding="utf-8"
    )
    monkeypatch.chdir(tmp_path)

    with pytest.raises(ProviderConfigurationError):
        _resolve(tmp_path, provider="anthropic", environ={})


# --- 9. no secret leakage ----------------------------------------------------


def test_safe_repr_never_contains_secret_value(tmp_path):
    secret_value = "sk-super-secret-value-must-not-leak-anywhere"
    result = _resolve(
        tmp_path,
        provider="anthropic",
        environ={"ANTHROPIC_API_KEY": secret_value},
    )

    assert secret_value not in result.safe_repr()
    assert secret_value not in repr(result)
    assert result.api_key_env == "ANTHROPIC_API_KEY"


def test_resolved_config_has_no_raw_secret_field(tmp_path):
    result = _resolve(
        tmp_path,
        provider="anthropic",
        environ={"ANTHROPIC_API_KEY": "sk-fake"},
    )
    field_names = {f.name for f in __import__("dataclasses").fields(result)}
    assert "api_key" not in field_names
    assert "api_key_value" not in field_names


# --- defaults for the remaining fields ---------------------------------------


def test_remaining_fields_use_documented_defaults(tmp_path):
    result = _resolve(tmp_path, provider="ollama")

    assert result.structured_output == "auto"
    assert result.timeout_seconds == 60.0
    assert result.max_retries == 2
    assert result.allow_insecure_http is False
    assert result.sources["structured_output"] == "provider_preset"
    assert result.sources["timeout_seconds"] == "default"
    assert result.sources["max_retries"] == "default"
    assert result.sources["allow_insecure_http"] == "default"
