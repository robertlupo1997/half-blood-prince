"""The codex-cli adapter (hermetic: subprocess is faked, no CLI is run)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from halfblood.config import resolve_eval_configs
from halfblood.generation.errors import ProviderTransientError, StructuredOutputError
from halfblood.generation.providers import codex_cli
from halfblood.generation.providers.base import GenerationRequest
from halfblood.generation.providers.codex_cli import CodexCliProvider
from halfblood.generation.schema import RecordAnnotations

_NOTE = {
    "target_text": "Stir clockwise",
    "annotation_type": "correction",
    "content": "Anticlockwise. Obviously.",
    "confidence": 0.9,
    "position": "margin_right",
}


def _request(model: str = "default") -> GenerationRequest:
    return GenerationRequest(
        system_prompt="system",
        user_prompt="page text",
        schema={"type": "object", "additionalProperties": False},
        model=model,
        max_tokens=1000,
        structured_output_mode="json-schema",
    )


def _fake_run(messages: list[str | None], calls: list[dict[str, Any]]) -> Any:
    def run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        last = Path(cmd[cmd.index("--output-last-message") + 1])
        schema = Path(cmd[cmd.index("--output-schema") + 1])
        calls.append({"cmd": cmd, "schema": json.loads(schema.read_text()), **kwargs})
        message = messages.pop(0)
        if message is not None:
            last.write_text(message)
        events = json.dumps(
            {"type": "turn.completed", "usage": {"input_tokens": 70, "output_tokens": 30}}
        )
        code = 0 if message is not None else 1
        return subprocess.CompletedProcess(cmd, code, stdout=events, stderr="boom")

    return run


@pytest.fixture
def provider(monkeypatch: pytest.MonkeyPatch) -> CodexCliProvider:
    monkeypatch.setattr(codex_cli.shutil, "which", lambda _: "/usr/bin/codex")
    return CodexCliProvider(max_retries=1)


def test_parses_last_message_read_only_with_closed_stdin(
    provider: CodexCliProvider, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[dict[str, Any]] = []
    message = json.dumps({"annotations": [_NOTE]})
    monkeypatch.setattr(codex_cli.subprocess, "run", _fake_run([message], calls))

    result = provider.complete(_request())

    assert isinstance(result.parsed, RecordAnnotations)
    assert (result.usage.input_tokens, result.usage.output_tokens) == (70, 30)
    cmd = calls[0]["cmd"]
    assert cmd[cmd.index("-s") + 1] == "read-only"
    assert "-m" not in cmd  # "default" defers to the user's Codex config
    assert calls[0]["stdin"] is subprocess.DEVNULL
    assert calls[0]["schema"] == {"type": "object", "additionalProperties": False}
    assert cmd[-1] == "system\n\npage text"


def test_explicit_model_is_passed(
    provider: CodexCliProvider, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[dict[str, Any]] = []
    message = json.dumps({"annotations": []})
    monkeypatch.setattr(codex_cli.subprocess, "run", _fake_run([message], calls))

    provider.complete(_request(model="gpt-test"))

    cmd = calls[0]["cmd"]
    assert cmd[cmd.index("-m") + 1] == "gpt-test"


def test_missing_message_is_retried_once_then_raised(
    provider: CodexCliProvider, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(codex_cli.subprocess, "run", _fake_run([None, None], calls))

    with pytest.raises(ProviderTransientError, match="boom"):
        provider.complete(_request())
    assert len(calls) == 2


def test_invalid_payload_fails_local_validation(
    provider: CodexCliProvider, monkeypatch: pytest.MonkeyPatch
) -> None:
    bad = json.dumps({"annotations": [{"content": "x"}]})
    monkeypatch.setattr(codex_cli.subprocess, "run", _fake_run([bad], []))

    with pytest.raises(StructuredOutputError):
        provider.complete(_request())


def test_claude_generator_with_codex_judge_is_independent(tmp_path: Path) -> None:
    generator, judge = resolve_eval_configs(
        {"provider": "claude-cli"},
        {"provider": "codex-cli"},
        environ={},
        project_config_path=tmp_path / "none.toml",
        user_config_path=tmp_path / "none-user.toml",
    )
    assert (generator.provider, generator.model) == ("claude-cli", "opus")
    assert (judge.provider, judge.model) == ("codex-cli", "default")
