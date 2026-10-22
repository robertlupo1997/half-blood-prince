"""The claude-cli adapter (hermetic: subprocess is faked, no CLI is run)."""

from __future__ import annotations

import json
import subprocess
from typing import Any

import pytest

from halfblood.generation.errors import ProviderTransientError, StructuredOutputError
from halfblood.generation.providers import claude_cli
from halfblood.generation.providers.base import GenerationRequest
from halfblood.generation.providers.claude_cli import ClaudeCliProvider
from halfblood.generation.schema import RecordAnnotations

_NOTE = {
    "target_text": "Stir clockwise",
    "annotation_type": "correction",
    "content": "Anticlockwise. Obviously.",
    "confidence": 0.9,
    "position": "margin_right",
}


def _request() -> GenerationRequest:
    return GenerationRequest(
        system_prompt="system",
        user_prompt="page text",
        schema={"type": "object"},
        model="opus",
        max_tokens=1000,
        structured_output_mode="json-schema",
    )


def _fake_run(outputs: list[str], calls: list[dict[str, Any]]) -> Any:
    def run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append({"cmd": cmd, **kwargs})
        return subprocess.CompletedProcess(cmd, 0, stdout=outputs.pop(0), stderr="")

    return run


@pytest.fixture
def provider(monkeypatch: pytest.MonkeyPatch) -> ClaudeCliProvider:
    monkeypatch.setattr(claude_cli.shutil, "which", lambda _: "/usr/bin/claude")
    return ClaudeCliProvider(max_retries=1)


def test_parses_structured_output_and_runs_stateless(
    provider: ClaudeCliProvider, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[dict[str, Any]] = []
    payload = {
        "structured_output": {"annotations": [_NOTE]},
        "usage": {"input_tokens": 5, "cache_read_input_tokens": 95, "output_tokens": 40},
        "stop_reason": "tool_use",
    }
    monkeypatch.setattr(claude_cli.subprocess, "run", _fake_run([json.dumps(payload)], calls))

    result = provider.complete(_request())

    assert isinstance(result.parsed, RecordAnnotations)
    assert result.parsed.annotations[0].content == "Anticlockwise. Obviously."
    assert (result.usage.input_tokens, result.usage.output_tokens) == (100, 40)
    cmd = calls[0]["cmd"]
    assert calls[0]["input"] == "page text"
    assert cmd[cmd.index("--tools") + 1] == ""
    assert "--no-session-persistence" in cmd and "--strict-mcp-config" in cmd


def test_error_result_is_retried_once_then_raised(
    provider: ClaudeCliProvider, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[dict[str, Any]] = []
    error = json.dumps({"is_error": True, "result": "rate limited"})
    monkeypatch.setattr(claude_cli.subprocess, "run", _fake_run([error, error], calls))

    with pytest.raises(ProviderTransientError, match="rate limited"):
        provider.complete(_request())
    assert len(calls) == 2


def test_invalid_payload_fails_local_validation(
    provider: ClaudeCliProvider, monkeypatch: pytest.MonkeyPatch
) -> None:
    bad = json.dumps({"structured_output": {"annotations": [{"content": "x"}]}})
    monkeypatch.setattr(claude_cli.subprocess, "run", _fake_run([bad], []))

    with pytest.raises(StructuredOutputError):
        provider.complete(_request())
