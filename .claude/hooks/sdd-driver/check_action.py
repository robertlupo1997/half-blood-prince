#!/usr/bin/env python3
"""Enforce the sdd-driver's write and shell-command policy."""

from __future__ import annotations

import json
import shlex
import sys
from pathlib import Path
from typing import Any

DENIED_GIT_SUBCOMMANDS = {"stash", "reset", "merge", "rebase", "push", "revert"}
GIT_OPTIONS_WITH_VALUES = {
    "-C",
    "-c",
    "--config-env",
    "--exec-path",
    "--git-dir",
    "--namespace",
    "--super-prefix",
    "--work-tree",
}


def _deny(reason: str) -> int:
    print(reason, file=sys.stderr)
    return 2


def _is_under(path: Path, directory: Path) -> bool:
    try:
        path.relative_to(directory)
    except ValueError:
        return False
    return True


def _check_path(raw_path: Any) -> str | None:
    if not isinstance(raw_path, str) or not raw_path:
        return None

    path = Path(raw_path).expanduser().resolve(strict=False)
    workspace = Path.cwd().resolve()

    if path.name == "CLAUDE.md":
        return "CLAUDE.md is outside driver scope"
    if _is_under(path, workspace / "src"):
        return "src/ is outside driver scope"
    if _is_under(path, workspace / ".claude"):
        return ".claude/ is outside driver scope"

    allowed_roots = (
        workspace / "tests",
        workspace / ".superpowers",
        workspace / "docs",
        workspace / "thoughts",
        Path("/tmp").resolve(),
    )
    if any(_is_under(path, root) for root in allowed_roots):
        return None
    return "path outside driver scope"


def _shell_tokens(command: str) -> list[str]:
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|")
        lexer.whitespace_split = True
        lexer.commenters = ""
        return list(lexer)
    except ValueError:
        # A malformed shell command will fail at execution. Keep this guard fail-open.
        return command.split()


def _git_subcommand(tokens: list[str], git_index: int) -> tuple[str | None, list[str]]:
    index = git_index + 1
    while index < len(tokens):
        token = tokens[index]
        if token in {";", "&&", "&", "|", "||"}:
            return None, []
        if token == "--":
            index += 1
            break
        option_name = token.split("=", 1)[0]
        if token.startswith("-"):
            if option_name in GIT_OPTIONS_WITH_VALUES and "=" not in token:
                index += 2
            else:
                index += 1
            continue
        break

    if index >= len(tokens) or tokens[index] in {";", "&&", "&", "|", "||"}:
        return None, []

    subcommand = tokens[index]
    arguments: list[str] = []
    for token in tokens[index + 1 :]:
        if token in {";", "&&", "&", "|", "||"}:
            break
        arguments.append(token)
    return subcommand, arguments


def _check_git(tokens: list[str]) -> str | None:
    for index, token in enumerate(tokens):
        if token != "git":
            continue
        subcommand, arguments = _git_subcommand(tokens, index)
        if subcommand in DENIED_GIT_SUBCOMMANDS:
            return f"git {subcommand} is forbidden by the ref-moving git rule"
        if subcommand == "checkout" and "-b" not in arguments:
            return "git checkout is forbidden unless used with -b"
        if subcommand == "commit" and _has_amend(arguments):
            return "git commit --amend is forbidden by the amend rule"
        if subcommand == "add" and any(arg in {"-f", "--force"} for arg in arguments):
            return "git add --force is forbidden by the force-add rule"
        if subcommand == "branch" and any(arg in {"-d", "-D"} for arg in arguments):
            return "git branch deletion is forbidden by the branch-delete rule"
    return None


def _has_amend(arguments: list[str]) -> bool:
    return any(arg == "--amend" or arg.startswith("--amend=") for arg in arguments)


def _check_command(raw_command: Any) -> str | None:
    if not isinstance(raw_command, str) or not raw_command:
        return None
    if "--dangerously" in raw_command:
        return "--dangerously is forbidden by the dangerous-mode rule"
    if "settings.json" in raw_command:
        return "settings.json is forbidden by the settings rule"

    tokens = _shell_tokens(raw_command)
    if any(token in {"pkill", "killall"} for token in tokens):
        return "pkill and killall are forbidden by the process-kill rule"

    git_reason = _check_git(tokens)
    if git_reason is not None:
        return git_reason

    for index, token in enumerate(tokens[:-1]):
        if token == "codex" and tokens[index + 1] == "exec":
            return "raw codex exec is forbidden by the receipt-wrapper rule"
    return None


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return _deny("malformed hook JSON; refusing to act blind")

    if not isinstance(payload, dict):
        return 0
    tool_name = payload.get("tool_name")
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return 0

    reason: str | None = None
    if tool_name in {"Edit", "Write"}:
        reason = _check_path(tool_input.get("file_path"))
    elif tool_name == "Bash":
        reason = _check_command(tool_input.get("command"))

    return _deny(reason) if reason is not None else 0


if __name__ == "__main__":
    raise SystemExit(main())
