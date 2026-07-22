"""Hermetic subprocess tests for the shadow sdd-driver policy hooks."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
ACTION_HOOK = REPO_ROOT / ".claude/hooks/sdd-driver/check_action.py"
STOP_HOOK = REPO_ROOT / ".claude/hooks/sdd-driver/check_stop.py"
AGENT_DEFINITION = REPO_ROOT / ".claude/agents/sdd-driver.md"


def run_hook(
    script: Path,
    payload: str,
    *,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    hook_env = os.environ.copy()
    hook_env["PYTHONDONTWRITEBYTECODE"] = "1"
    if env is not None:
        hook_env.update(env)
    return subprocess.run(
        [sys.executable, str(script)],
        input=payload,
        text=True,
        capture_output=True,
        cwd=REPO_ROOT,
        env=hook_env,
        check=False,
    )


ACTION_CASES = [
    pytest.param("Bash", {"command": "git stash"}, False, id="git-stash"),
    pytest.param("Bash", {"command": "git reset --hard"}, False, id="git-reset-hard"),
    pytest.param(
        "Bash", {"command": "git merge --no-ff feature"}, False, id="git-merge-no-ff"
    ),
    pytest.param("Bash", {"command": "git checkout main"}, False, id="checkout-existing"),
    pytest.param("Bash", {"command": "git checkout -b feature"}, True, id="checkout-new"),
    pytest.param("Bash", {"command": "git push origin feature"}, False, id="git-push"),
    pytest.param(
        "Bash",
        {"command": "git add -f .superpowers/sdd/x"},
        False,
        id="git-force-add",
    ),
    pytest.param(
        "Bash", {"command": "git commit --amend -m fixed"}, False, id="git-amend"
    ),
    pytest.param("Bash", {"command": "git commit -m done"}, True, id="git-commit"),
    pytest.param("Bash", {"command": "codex exec 'fix it'"}, False, id="raw-codex"),
    pytest.param(
        "Bash",
        {"command": "~/dev-harness/scripts/codex-receipts.sh 'fix it'"},
        True,
        id="codex-receipts",
    ),
    pytest.param("Bash", {"command": "pkill python"}, False, id="pkill"),
    pytest.param("Bash", {"command": "kill 1234"}, True, id="kill-by-pid"),
    pytest.param("Bash", {"command": "pytest -q"}, True, id="pytest"),
    pytest.param(
        "Bash",
        {"command": "pytest tests/test_git_stash.py"},
        True,
        id="git-name-in-test-path",
    ),
    pytest.param(
        "Bash",
        {"command": "git status && git reset --hard"},
        False,
        id="compound-denied-segment",
    ),
    pytest.param("Edit", {"file_path": "src/halfblood/cli.py"}, False, id="edit-src"),
    pytest.param("Edit", {"file_path": "tests/test_feature.py"}, True, id="edit-tests"),
    pytest.param("Write", {"file_path": "CLAUDE.md"}, False, id="write-claude-md"),
    pytest.param(
        "Write",
        {"file_path": ".superpowers/sdd/x"},
        True,
        id="write-task-artifact",
    ),
    pytest.param(
        "Write", {"file_path": ".claude/agents/other.md"}, False, id="write-claude-dir"
    ),
    pytest.param("Write", {"file_path": "README.md"}, False, id="write-outside-scope"),
    pytest.param("Read", {"file_path": "src/halfblood/cli.py"}, True, id="read-anything"),
]


@pytest.mark.parametrize(("tool_name", "tool_input", "allowed"), ACTION_CASES)
def test_action_policy(tool_name: str, tool_input: dict[str, Any], allowed: bool) -> None:
    payload = json.dumps({"tool_name": tool_name, "tool_input": tool_input})
    result = run_hook(ACTION_HOOK, payload)

    assert result.returncode == (0 if allowed else 2), result.stderr
    assert bool(result.stderr.strip()) is not allowed


def test_action_policy_denies_malformed_json() -> None:
    result = run_hook(ACTION_HOOK, '{"tool_name": "Bash"')

    assert result.returncode == 2
    assert result.stderr.strip() == "malformed hook JSON; refusing to act blind"


def test_action_policy_fails_open_for_missing_fields() -> None:
    result = run_hook(ACTION_HOOK, json.dumps({"unexpected": "value"}))

    assert result.returncode == 0
    assert result.stderr == ""


def test_stop_allows_nonempty_report(tmp_path: Path) -> None:
    report = tmp_path / "driver-report.md"
    report.write_text("Task complete.\n", encoding="utf-8")

    result = run_hook(STOP_HOOK, "{}", env={"SDD_DRIVER_REPORT": str(report)})

    assert result.returncode == 0
    assert result.stderr == ""
    assert not (tmp_path / "driver-report.stop-refusals").exists()


@pytest.mark.parametrize("create_empty_marker", [False, True])
def test_stop_refuses_once_then_allows_with_warning(
    tmp_path: Path, create_empty_marker: bool
) -> None:
    report = tmp_path / "driver-report.md"
    if create_empty_marker:
        report.touch()
    env = {"SDD_DRIVER_REPORT": str(report)}

    first = run_hook(STOP_HOOK, "{}", env=env)
    second = run_hook(STOP_HOOK, "{}", env=env)

    assert first.returncode == 2
    assert first.stderr.strip() == (
        "write your final report to .superpowers/sdd/driver-report.md before stopping"
    )
    assert (tmp_path / "driver-report.stop-refusals").read_text(encoding="utf-8") == "1\n"
    assert second.returncode == 0
    assert second.stderr.strip() == (
        "allowing stop after repeated refusal — parent must treat this driver as blocked"
    )


def _frontmatter(text: str) -> str:
    match = re.match(r"\A---\n(.*?)\n---(?:\n|\Z)", text, flags=re.DOTALL)
    assert match is not None, "agent definition must start with YAML frontmatter"
    return match.group(1)


def _scalar(frontmatter: str, key: str) -> str | None:
    match = re.search(rf"(?m)^{re.escape(key)}:\s*(.+)$", frontmatter)
    return match.group(1).strip() if match is not None else None


def test_agent_frontmatter_references_installed_policy_hooks() -> None:
    frontmatter = _frontmatter(AGENT_DEFINITION.read_text(encoding="utf-8"))

    assert _scalar(frontmatter, "name") == "sdd-driver"
    assert _scalar(frontmatter, "description")
    assert _scalar(frontmatter, "model") == "sonnet"
    assert "Agent" in (_scalar(frontmatter, "disallowedTools") or "").split(", ")

    commands = re.findall(r'^\s*command:\s*"([^"]+)"\s*$', frontmatter, flags=re.MULTILINE)
    assert commands == [
        "python3 .claude/hooks/sdd-driver/check_action.py",
        "python3 .claude/hooks/sdd-driver/check_stop.py",
    ]
    for command in commands:
        script = command.removeprefix("python3 ")
        assert (REPO_ROOT / script).is_file()
