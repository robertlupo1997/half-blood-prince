"""Controller-authored, test-first contract for P1-T8 (halfblood providers doctor).

Ground truth: docs/superpowers/specs/2026-07-11-full-project-architecture.md §§4.4, 9;
.superpowers/sdd/p1-t8-subdriver-spec.md. These tests are the frozen interface
Codex builds against -- do not edit them to make an implementation pass.

Injection strategy [INFER]:
  cli.py must import ``resolve_generation_config`` and ``build_provider`` at
  module TOP LEVEL (not inside the Click command body).  Tests monkeypatch
  ``halfblood.cli.resolve_generation_config`` and ``halfblood.cli.build_provider``
  so each test can supply a hermetic config and a MockTransport-backed provider
  without touching real env vars or real config files.

No network calls anywhere in this file.
"""

from __future__ import annotations

import httpx
import pytest
from click.testing import CliRunner

import halfblood.cli as cli_module
from halfblood.config import ResolvedConfig
from halfblood.generation.errors import ProviderConfigurationError
from halfblood.generation.providers.anthropic import AnthropicProvider

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Sentinel key value — must NEVER appear in any command output.
_SENTINEL_KEY = "sk-ant-sentinel-xyzzy-not-real"
_FAKE_API_KEY_ENV = "ANTHROPIC_API_KEY"
_FAKE_PROVIDER = "anthropic"
_FAKE_MODEL = "claude-sonnet-5"
_FAKE_BASE_URL = "https://api.anthropic.com"

_FAKE_SOURCES: dict[str, str] = {
    "provider": "cli",
    "model": "cli",
    "base_url": "preset",
    "api_key_env": "preset",
    "structured_output": "preset",
    "timeout_seconds": "default",
    "max_retries": "default",
    "concurrency": "default",
    "allow_insecure_http": "default",
    "max_per_page": "default",
    "font": "default",
}
# Every field in ResolvedConfig.safe_repr()'s tuple must appear above. The real resolver
# always records a source for each, so safe_repr indexes this dict strictly -- a missing
# key is a bug in provenance tracking, and a diagnostics function that quietly prints
# "source=unknown" hides exactly what `providers doctor` exists to reveal.

#: Pre-built hermetic ResolvedConfig.  Tests that need it monkeypatch
#: ``cli_module.resolve_generation_config`` to return this object directly,
#: bypassing all real env/file reads.
_FAKE_CONFIG = ResolvedConfig(
    provider=_FAKE_PROVIDER,
    model=_FAKE_MODEL,
    base_url=_FAKE_BASE_URL,
    api_key_env=_FAKE_API_KEY_ENV,
    structured_output="tool",
    timeout_seconds=60.0,
    max_retries=0,
    concurrency=3,
    allow_insecure_http=False,
    sources=_FAKE_SOURCES,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _tool_use_body(annotations: list[dict]) -> dict:
    """Minimal valid Anthropic tool-use response body."""
    return {
        "id": "msg_01doctor",
        "type": "message",
        "role": "assistant",
        "content": [
            {
                "type": "tool_use",
                "id": "toolu_01doctor",
                "name": "record_annotations",
                "input": {"annotations": annotations},
            }
        ],
        "model": _FAKE_MODEL,
        "stop_reason": "tool_use",
        "usage": {"input_tokens": 5, "output_tokens": 3},
    }


def _make_provider(handler) -> AnthropicProvider:
    """Return an AnthropicProvider with an injected MockTransport and no retries."""
    return AnthropicProvider(
        api_key=_SENTINEL_KEY,
        base_url=_FAKE_BASE_URL,
        transport=httpx.MockTransport(handler),
        sleep_fn=lambda _seconds: None,
        rand_fn=lambda: 0.5,
        max_retries=0,
    )


def _no_traceback(result) -> bool:
    """True when the CliRunner result carries no raw exception (ClickException or clean exit)."""
    return result.exception is None or isinstance(result.exception, SystemExit)


@pytest.fixture()
def runner() -> CliRunner:
    return CliRunner()


# ---------------------------------------------------------------------------
# Offline doctor
# ---------------------------------------------------------------------------


def test_offline_prints_provider_model_and_sources(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    """--offline prints provider, model, endpoint, mode, and sources; never calls build_provider."""
    monkeypatch.setattr(cli_module, "resolve_generation_config", lambda *a, **k: _FAKE_CONFIG)

    transport_call_count = [0]

    def _should_not_build(*a, **k) -> None:
        transport_call_count[0] += 1
        raise AssertionError("build_provider must not be called in --offline mode")

    monkeypatch.setattr(cli_module, "build_provider", _should_not_build)

    result = runner.invoke(
        cli_module.main,
        ["providers", "doctor", "--offline"],
        env={_FAKE_API_KEY_ENV: _SENTINEL_KEY},
    )

    assert result.exit_code == 0, result.output
    # Provider name appears in output (from config.safe_repr() or formatted line)
    assert _FAKE_PROVIDER in result.output
    # Model name appears
    assert _FAKE_MODEL in result.output
    # Endpoint (base URL) appears — safe_repr() shows base_url=... without embedding a key
    assert "api.anthropic.com" in result.output
    # The env-var NAME (not its value) appears — proves redaction, not absence
    assert _FAKE_API_KEY_ENV in result.output
    # Config source info appears (safe_repr format: "(source=preset)")
    assert "source=" in result.output or "preset" in result.output
    # Structured output mode appears
    assert "tool" in result.output
    # Confirmed: build_provider was never invoked
    assert transport_call_count[0] == 0


def test_offline_no_api_key_in_output(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The actual API key value must never appear in --offline output."""
    monkeypatch.setattr(cli_module, "resolve_generation_config", lambda *a, **k: _FAKE_CONFIG)
    monkeypatch.setattr(cli_module, "build_provider", lambda *a, **k: None)

    result = runner.invoke(
        cli_module.main,
        ["providers", "doctor", "--offline"],
        env={_FAKE_API_KEY_ENV: _SENTINEL_KEY},
    )

    assert result.exit_code == 0, result.output
    assert _SENTINEL_KEY not in result.output


def test_offline_missing_config_exits_nonzero_no_traceback(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A ProviderConfigurationError (e.g. missing API key) produces a clean error, no traceback."""

    def _raise_config_error(*a, **k) -> None:
        raise ProviderConfigurationError(
            f"Environment variable {_FAKE_API_KEY_ENV} is required for provider {_FAKE_PROVIDER}"
        )

    monkeypatch.setattr(cli_module, "resolve_generation_config", _raise_config_error)

    result = runner.invoke(
        cli_module.main,
        ["providers", "doctor", "--offline"],
    )

    assert result.exit_code != 0
    assert _no_traceback(result), f"unexpected traceback: {result.exception!r}"
    # Error message references the missing variable name
    assert _FAKE_API_KEY_ENV in result.output
    # Sentinel value does not leak
    assert _SENTINEL_KEY not in result.output


# ---------------------------------------------------------------------------
# Online doctor (injected MockTransport — no real network calls)
# ---------------------------------------------------------------------------


def test_online_valid_response_reports_latency_and_request_id(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Online doctor with a valid tool response exits 0 and reports latency + request_id."""
    monkeypatch.setattr(cli_module, "resolve_generation_config", lambda *a, **k: _FAKE_CONFIG)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_tool_use_body([]))

    monkeypatch.setattr(
        cli_module,
        "build_provider",
        lambda *a, **k: _make_provider(handler),
    )

    result = runner.invoke(
        cli_module.main,
        ["providers", "doctor"],
        env={_FAKE_API_KEY_ENV: _SENTINEL_KEY},
    )

    assert result.exit_code == 0, result.output
    assert _no_traceback(result), f"unexpected traceback: {result.exception!r}"
    # Latency is reported
    assert "latency" in result.output.lower()
    # The response's message id is surfaced as request_id
    assert "msg_01doctor" in result.output or "request_id" in result.output.lower()


def test_online_exactly_one_request(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The online doctor makes EXACTLY ONE request — never silently probes multiple modes."""
    monkeypatch.setattr(cli_module, "resolve_generation_config", lambda *a, **k: _FAKE_CONFIG)

    call_count = [0]

    def handler(request: httpx.Request) -> httpx.Response:
        call_count[0] += 1
        return httpx.Response(200, json=_tool_use_body([]))

    monkeypatch.setattr(
        cli_module,
        "build_provider",
        lambda *a, **k: _make_provider(handler),
    )

    runner.invoke(
        cli_module.main,
        ["providers", "doctor"],
        env={_FAKE_API_KEY_ENV: _SENTINEL_KEY},
    )

    assert call_count[0] == 1


def test_online_error_maps_taxonomy_no_traceback(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A 401 authentication error is mapped to the taxonomy label — no raw traceback, no key leak."""
    monkeypatch.setattr(cli_module, "resolve_generation_config", lambda *a, **k: _FAKE_CONFIG)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            401,
            json={
                "type": "error",
                "error": {"type": "authentication_error", "message": "Invalid API key"},
            },
        )

    monkeypatch.setattr(
        cli_module,
        "build_provider",
        lambda *a, **k: _make_provider(handler),
    )

    result = runner.invoke(
        cli_module.main,
        ["providers", "doctor"],
        env={_FAKE_API_KEY_ENV: _SENTINEL_KEY},
    )

    # The doctor must surface the error category, not swallow it
    assert "authentication" in result.output.lower() or "401" in result.output
    # No raw Python traceback
    assert _no_traceback(result), f"unexpected traceback: {result.exception!r}"
    # Sentinel key must not leak into output
    assert _SENTINEL_KEY not in result.output
