"""Subprocess coverage for the read-only harness conformance checker."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
CHECKER = REPO_ROOT / "scripts/check_harness_contracts.py"


def run_checker(repo: Path, *, strict: bool = False) -> subprocess.CompletedProcess[str]:
    command = [sys.executable, str(CHECKER), "--repo", str(repo)]
    if strict:
        command.append("--strict")
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run(
        command,
        text=True,
        capture_output=True,
        cwd=repo,
        env=env,
        check=False,
    )


def make_repo(tmp_path: Path, *, skill_text: str = "Use codex-safe.sh.\n") -> Path:
    (tmp_path / ".claude/agents").mkdir(parents=True)
    skill = tmp_path / ".claude/skills/goal/SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text(skill_text, encoding="utf-8")
    return tmp_path


def finding_lines(output: str) -> list[str]:
    return [line for line in output.splitlines() if line.startswith("[CHECK-")]


@pytest.mark.parametrize("strict", [False, True])
def test_real_repo_has_only_current_advisory_findings(strict: bool) -> None:
    result = run_checker(REPO_ROOT, strict=strict)

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert finding_lines(result.stdout) == [
        "[CHECK-1] DIVERGENCE: .claude/agents/codebase-analyzer.md: "
        "missing opening frontmatter delimiter",
        "[CHECK-1] DIVERGENCE: .claude/agents/web-search-researcher.md: "
        "missing opening frontmatter delimiter",
        "[CHECK-4] DIVERGENCE: "
        "docs/superpowers/specs/2026-07-19-codex-usage-audit.md: historical claim says "
        "/goal uses raw Codex; .claude/skills/goal/SKILL.md is the current source of truth",
    ]
    assert "codebase-locator.md" not in result.stdout
    assert "codebase-pattern-finder.md" not in result.stdout
    assert "sdd-driver.md" not in result.stdout
    assert result.stdout.count("| owner decision |") == 2
    assert result.stdout.count("| historical-doc label |") == 1


def test_valid_agent_frontmatter_passes(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    (repo / ".claude/agents/valid.md").write_text(
        "---\nname: valid\ndescription: A valid test agent.\n---\n\nBody.\n",
        encoding="utf-8",
    )

    result = run_checker(repo, strict=True)

    assert result.returncode == 0
    assert finding_lines(result.stdout) == []


def test_missing_agent_name_is_divergence(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    (repo / ".claude/agents/missing-name.md").write_text(
        "---\ndescription: Missing its name.\n---\n",
        encoding="utf-8",
    )

    result = run_checker(repo)

    assert result.returncode == 0
    assert finding_lines(result.stdout) == [
        "[CHECK-1] DIVERGENCE: .claude/agents/missing-name.md: "
        "missing non-empty required frontmatter field(s): name"
    ]
    assert "| owner decision |" in result.stdout


def test_missing_hook_is_error_and_only_strict_fails(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    (repo / ".claude/agents/hooked.md").write_text(
        """---
name: hooked
description: References a missing hook.
hooks:
  PreToolUse:
    - hooks:
        - type: command
          command: "python3 .claude/hooks/missing.py"
---
""",
        encoding="utf-8",
    )

    plain = run_checker(repo)
    strict = run_checker(repo, strict=True)

    expected = (
        "[CHECK-2] ERROR: .claude/agents/hooked.md: hook file does not exist: "
        ".claude/hooks/missing.py"
    )
    assert plain.returncode == 0
    assert strict.returncode != 0
    assert finding_lines(plain.stdout) == [expected]
    assert finding_lines(strict.stdout) == [expected]
    assert "| .claude/agents/hooked.md |" not in strict.stdout


def test_hook_with_syntax_error_is_error(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    hook = repo / ".claude/hooks/broken.py"
    hook.parent.mkdir(parents=True)
    hook.write_text("def broken(:\n", encoding="utf-8")
    (repo / ".claude/agents/hooked.md").write_text(
        """---
name: hooked
description: References an invalid hook.
hooks:
  Stop:
    - hooks:
        - type: command
          command: "python3 .claude/hooks/broken.py"
---
""",
        encoding="utf-8",
    )

    result = run_checker(repo, strict=True)

    assert result.returncode != 0
    assert len(finding_lines(result.stdout)) == 1
    assert finding_lines(result.stdout)[0].startswith(
        "[CHECK-2] ERROR: .claude/agents/hooked.md: hook file has invalid Python syntax "
        "(.claude/hooks/broken.py, line 1):"
    )


def test_affirmative_raw_codex_invocation_is_divergence(tmp_path: Path) -> None:
    raw_invocation = "Run codex " + "exec --sandbox workspace-write now.\n"
    repo = make_repo(tmp_path, skill_text="Use codex-safe.sh.\n" + raw_invocation)

    result = run_checker(repo, strict=True)

    assert result.returncode == 0
    assert finding_lines(result.stdout) == [
        "[CHECK-3] DIVERGENCE: .claude/skills/goal/SKILL.md:2: "
        "affirmative raw codex exec invocation"
    ]
    assert "line 2 invokes raw codex exec" in result.stdout


def test_checker_does_not_change_git_status() -> None:
    before = subprocess.run(
        ["git", "status", "--porcelain"],
        text=True,
        capture_output=True,
        cwd=REPO_ROOT,
        check=True,
    ).stdout

    result = run_checker(REPO_ROOT, strict=True)

    after = subprocess.run(
        ["git", "status", "--porcelain"],
        text=True,
        capture_output=True,
        cwd=REPO_ROOT,
        check=True,
    ).stdout
    assert result.returncode == 0
    assert after == before
