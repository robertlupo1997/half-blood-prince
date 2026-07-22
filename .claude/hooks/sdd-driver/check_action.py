#!/usr/bin/env python3
"""Enforce the sdd-driver's write and shell-command policy."""

from __future__ import annotations

import json
import re
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
COMMAND_SEPARATORS = {";", "&&", "&", "|", "||"}
SHELL_LAUNCHERS = {"bash", "sh", "zsh", "dash"}
ARGUMENT_LAUNCHERS = {"eval", "exec"}
REDIRECT_RE = re.compile(r"^(?:\d*)?(>>?)(.*)$")


def _deny(reason: str) -> int:
    print(reason, file=sys.stderr)
    return 2


def _is_under(path: Path, directory: Path) -> bool:
    try:
        path.relative_to(directory)
    except ValueError:
        return False
    return True


def _protected_path_reason(path: Path, workspace: Path) -> str | None:
    if path.name == "CLAUDE.md":
        return "CLAUDE.md is outside driver scope"
    if _is_under(path, workspace / "src"):
        return "src/ is outside driver scope"
    if _is_under(path, workspace / ".claude"):
        return ".claude/ is outside driver scope"
    return None


def _resolved_path(raw_path: Any) -> Path | None:
    if not isinstance(raw_path, str) or not raw_path:
        return None
    return Path(raw_path).expanduser().resolve(strict=False)


def _check_path(raw_path: Any) -> str | None:
    path = _resolved_path(raw_path)
    if path is None:
        return None

    workspace = Path.cwd().resolve()
    protected_reason = _protected_path_reason(path, workspace)
    if protected_reason is not None:
        return protected_reason

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


def _check_protected_output_path(raw_path: str) -> str | None:
    path = _resolved_path(raw_path)
    if path is None:
        return None
    return _protected_path_reason(path, Path.cwd().resolve())


def _shell_tokens(command: str) -> list[str] | None:
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|")
        lexer.whitespace_split = True
        lexer.commenters = ""
        return list(lexer)
    except ValueError:
        return None


def _git_subcommand(tokens: list[str], git_index: int) -> tuple[str | None, list[str]]:
    index = git_index + 1
    while index < len(tokens):
        token = tokens[index]
        if token in COMMAND_SEPARATORS:
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

    if index >= len(tokens) or tokens[index] in COMMAND_SEPARATORS:
        return None, []

    subcommand = tokens[index]
    arguments: list[str] = []
    for token in tokens[index + 1 :]:
        if token in COMMAND_SEPARATORS:
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


def _command_name(token: str) -> str:
    return token.rsplit("/", 1)[-1]


def _command_arguments(tokens: list[str], command_index: int) -> list[str]:
    arguments: list[str] = []
    for token in tokens[command_index + 1 :]:
        if token in COMMAND_SEPARATORS:
            break
        arguments.append(token)
    return arguments


def _redirect_target(tokens: list[str], index: int) -> tuple[str | None, int]:
    match = REDIRECT_RE.fullmatch(tokens[index])
    if match is None:
        return None, 1

    attached_target = match.group(2)
    if attached_target:
        if attached_target.startswith("&"):
            return None, 1
        return attached_target, 1

    if index + 1 >= len(tokens):
        return None, 1
    target = tokens[index + 1]
    if target == "&":
        return None, min(3, len(tokens) - index)
    return target, 2


def _check_tee_arguments(arguments: list[str]) -> str | None:
    options = True
    index = 0
    while index < len(arguments):
        argument = arguments[index]
        _, consumed = _redirect_target(arguments, index)
        if consumed > 1 or REDIRECT_RE.fullmatch(argument) is not None:
            index += consumed
            continue
        if options and argument == "--":
            options = False
        elif options and argument.startswith("-"):
            pass
        else:
            reason = _check_protected_output_path(argument)
            if reason is not None:
                return reason
        index += 1
    return None


def _check_output_paths(tokens: list[str]) -> str | None:
    index = 0
    while index < len(tokens):
        target, consumed = _redirect_target(tokens, index)
        if target is not None:
            reason = _check_protected_output_path(target)
            if reason is not None:
                return reason
        index += consumed

    for index, token in enumerate(tokens):
        command_name = _command_name(token)
        arguments = _command_arguments(tokens, index)
        if command_name == "tee":
            reason = _check_tee_arguments(arguments)
            if reason is not None:
                return reason
        elif command_name == "dd":
            for argument in arguments:
                if argument.startswith("of="):
                    reason = _check_protected_output_path(argument.removeprefix("of="))
                    if reason is not None:
                        return reason
    return None


def _check_launchers(tokens: list[str], depth: int) -> str | None:
    for index, token in enumerate(tokens):
        command_name = _command_name(token)
        arguments = _command_arguments(tokens, index)
        payload: str | None = None
        if command_name in SHELL_LAUNCHERS:
            for flag_index, argument in enumerate(arguments):
                if (
                    argument.startswith("-")
                    and not argument.startswith("--")
                    and "c" in argument[1:]
                ):
                    for candidate in arguments[flag_index + 1 :]:
                        if not candidate.startswith("-"):
                            payload = candidate
                            break
                    break
        elif command_name in ARGUMENT_LAUNCHERS and arguments:
            payload = " ".join(arguments)

        if payload is not None:
            reason = _check_command(payload, deny_parse_error=True, depth=depth + 1)
            if reason is not None:
                return reason
    return None


def _check_command(
    raw_command: Any, *, deny_parse_error: bool = False, depth: int = 0
) -> str | None:
    if not isinstance(raw_command, str) or not raw_command:
        return None
    if "--dangerously" in raw_command:
        return "--dangerously is forbidden by the dangerous-mode rule"
    if "settings.json" in raw_command:
        return "settings.json is forbidden by the settings rule"

    tokens = _shell_tokens(raw_command)
    if tokens is None:
        if deny_parse_error:
            return "malformed launcher payload; refusing to act blind"
        # A malformed top-level shell command will fail at execution. Preserve the
        # hook's existing fail-open behavior for text not extracted from a launcher.
        tokens = raw_command.split()
    if any(token in {"pkill", "killall"} for token in tokens):
        return "pkill and killall are forbidden by the process-kill rule"

    git_reason = _check_git(tokens)
    if git_reason is not None:
        return git_reason

    for index, token in enumerate(tokens[:-1]):
        if token == "codex" and tokens[index + 1] == "exec":
            return "raw codex exec is forbidden by the receipt-wrapper rule"

    output_reason = _check_output_paths(tokens)
    if output_reason is not None:
        return output_reason

    if depth >= 32:
        return "launcher nesting is too deep; refusing to act blind"
    return _check_launchers(tokens, depth)


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
