#!/usr/bin/env python3
"""PreToolUse guard for Bash. Deterministic: no model call, same answer every time.

Reads the hook JSON on stdin. Exit 0 allows the command. Exit 2 denies this one command and
sends the reason on stderr to the agent, which carries on with the session.

It replaces a prompt-type hook. That hook asked a model to judge every command; it denied
commands that only read or mentioned `.env`, and in headless runs a denial ended the whole
session (`terminal_reason: hook_stopped`).

Denied:
  1. deleting `.env` or the `secrets` directory
  2. `git reset --hard` while on main or master
  3. a recursive `rm` of the project root, the home directory, or a parent of either
  4. a literal API key or token in the command text
"""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

LITERAL_SECRET = re.compile(
    r"sk-[A-Za-z0-9_-]{20,}|ghp_[A-Za-z0-9]{36}|github_pat_[A-Za-z0-9_]{40,}|AKIA[0-9A-Z]{16}|xox[baprs]-[A-Za-z0-9-]{20,}"
)
SEPARATORS = re.compile(r"\|\||&&|[;|\n&]")
DELETERS = {"rm", "unlink", "shred"}
WRAPPERS = {"sudo", "command", "env", "time", "nohup", "exec"}


def words(segment: str) -> list[str]:
    try:
        return shlex.split(segment)
    except ValueError:  # unbalanced quotes: fall back to whitespace
        return segment.split()


def strip_wrappers(argv: list[str]) -> list[str]:
    while argv and (argv[0] in WRAPPERS or re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", argv[0])):
        argv = argv[1:]
    return argv


def resolve(arg: str, cwd: Path) -> Path:
    expanded = os.path.expandvars(os.path.expanduser(arg))
    return (cwd / expanded).resolve() if not os.path.isabs(expanded) else Path(expanded).resolve()


def current_branch(cwd: Path) -> str:
    done = subprocess.run(
        ["git", "symbolic-ref", "--short", "-q", "HEAD"], cwd=cwd, capture_output=True, text=True
    )
    return done.stdout.strip()


def verdict(command: str, cwd: Path, project: Path, home: Path) -> str | None:
    """The reason to deny `command`, or None to allow it."""
    if LITERAL_SECRET.search(command):
        return "the command text contains what looks like a literal API key or token; read it from the environment instead"
    for segment in SEPARATORS.split(command):
        argv = strip_wrappers(words(segment))
        if not argv:
            continue
        name = Path(argv[0]).name
        if name == "git" and "reset" in argv and "--hard" in argv:
            branch = current_branch(cwd)
            if branch in ("main", "master"):
                return f"git reset --hard on {branch} is not allowed here"
        if name in DELETERS:
            flags = "".join(
                arg.lstrip("-")
                for arg in argv[1:]
                if arg.startswith("-") and not arg.startswith("--")
            )
            recursive = "r" in flags or "R" in flags or "--recursive" in argv
            for arg in (a for a in argv[1:] if not a.startswith("-")):
                target = resolve(arg, cwd)
                if target.name == ".env" or target == project / "secrets":
                    return f"deleting {arg} is not allowed"
                if recursive and (
                    target in (project, home) or target in project.parents or target in home.parents
                ):
                    return f"a recursive delete of {arg} would remove the project root or the home directory"
    return None


def main() -> int:
    try:
        event = json.load(sys.stdin)
    except ValueError:
        return 0  # not a hook payload: do not get in the way
    command = str((event.get("tool_input") or {}).get("command") or "")
    cwd = Path(event.get("cwd") or os.getcwd())
    project = Path(os.environ.get("CLAUDE_PROJECT_DIR") or cwd).resolve()
    reason = verdict(command, cwd, project, Path.home().resolve())
    if reason:
        print(f"Blocked by .claude/hooks/guard_bash.py: {reason}.", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
