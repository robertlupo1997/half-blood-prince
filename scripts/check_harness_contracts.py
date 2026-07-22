#!/usr/bin/env python3
"""Read-only conformance checks for the repository's agent harness surface."""

from __future__ import annotations

import argparse
import ast
import re
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Finding:
    check: int
    severity: str
    message: str
    file: str
    claim: str
    expected: str
    action: str

    def render(self) -> str:
        return f"[CHECK-{self.check}] {self.severity}: {self.message}"


@dataclass(frozen=True)
class Frontmatter:
    lines: list[str]
    values: dict[str, str]


_TOP_LEVEL_FIELD = re.compile(r"^([A-Za-z][A-Za-z0-9_-]*):(?:\s*(.*))?$")
_COMMAND_FIELD = re.compile(r"^\s+command:\s*(.*?)\s*$")
_PYTHON_PATH = re.compile(r"(?P<path>(?:[A-Za-z]:)?[^\s\"'`;&|<>]+\.py)\b")
_RAW_CODEX = re.compile(r"\bcodex\s+exec\b", re.IGNORECASE)
_NEGATIVE_WORD = re.compile(r"\b(?:not|never|raw)\b", re.IGNORECASE)
_NEGATIVE_EXAMPLE = re.compile(
    r"\b(?:avoid|forbid(?:den)?|instead|negative\s+example|do\s+not|must\s+not)\b",
    re.IGNORECASE,
)


def _relative(path: Path, repo: Path) -> str:
    try:
        return path.relative_to(repo).as_posix()
    except ValueError:
        return str(path)


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1].strip()
    return value


def _read_frontmatter(path: Path) -> tuple[Frontmatter | None, str | None]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        return None, f"cannot read file: {exc}"

    if not lines or lines[0].strip() != "---":
        return None, "missing opening frontmatter delimiter"

    try:
        closing_index = next(
            index for index, line in enumerate(lines[1:], start=1) if line.strip() == "---"
        )
    except StopIteration:
        return None, "missing closing frontmatter delimiter"

    frontmatter_lines = lines[1:closing_index]
    values: dict[str, str] = {}
    for line in frontmatter_lines:
        if not line or line.isspace() or line.lstrip().startswith("#"):
            continue
        if line[0].isspace():
            continue
        match = _TOP_LEVEL_FIELD.fullmatch(line)
        if match is None:
            return None, f"unparseable frontmatter line: {line!r}"
        key, value = match.groups()
        if key in values:
            return None, f"duplicate frontmatter field: {key}"
        values[key] = _unquote(value or "")

    return Frontmatter(frontmatter_lines, values), None


def _frontmatter_finding(path: Path, repo: Path, problem: str) -> Finding:
    relative = _relative(path, repo)
    return Finding(
        check=1,
        severity="DIVERGENCE",
        message=f"{relative}: {problem}",
        file=relative,
        claim=problem,
        expected="YAML-subset frontmatter with non-empty name and description",
        action="owner decision",
    )


def _hook_commands(frontmatter: Frontmatter) -> list[str]:
    commands: list[str] = []
    under_hooks = False
    for line in frontmatter.lines:
        if line and not line[0].isspace():
            field = _TOP_LEVEL_FIELD.fullmatch(line)
            under_hooks = bool(field and field.group(1) == "hooks")
            continue
        if not under_hooks:
            continue
        match = _COMMAND_FIELD.fullmatch(line)
        if match is not None:
            commands.append(_unquote(match.group(1)))
    return commands


def _hook_findings(path: Path, repo: Path, frontmatter: Frontmatter) -> list[Finding]:
    findings: list[Finding] = []
    seen: set[str] = set()
    for command in _hook_commands(frontmatter):
        for match in _PYTHON_PATH.finditer(command):
            reference = match.group("path")
            if reference in seen:
                continue
            seen.add(reference)
            hook_path = Path(reference)
            if not hook_path.is_absolute():
                hook_path = repo / hook_path
            agent_name = _relative(path, repo)
            if not hook_path.is_file():
                findings.append(
                    Finding(
                        check=2,
                        severity="ERROR",
                        message=f"{agent_name}: hook file does not exist: {reference}",
                        file=agent_name,
                        claim=f"hook command references {reference}",
                        expected="referenced Python hook exists and parses",
                        action="owner decision",
                    )
                )
                continue
            try:
                source = hook_path.read_text(encoding="utf-8")
                ast.parse(source, filename=str(hook_path))
            except SyntaxError as exc:
                location = f"line {exc.lineno}" if exc.lineno is not None else "unknown line"
                findings.append(
                    Finding(
                        check=2,
                        severity="ERROR",
                        message=(
                            f"{agent_name}: hook file has invalid Python syntax "
                            f"({reference}, {location}): {exc.msg}"
                        ),
                        file=agent_name,
                        claim=f"hook command references syntactically invalid {reference}",
                        expected="referenced Python hook exists and parses",
                        action="owner decision",
                    )
                )
            except (OSError, UnicodeError) as exc:
                findings.append(
                    Finding(
                        check=2,
                        severity="ERROR",
                        message=f"{agent_name}: cannot parse hook file {reference}: {exc}",
                        file=agent_name,
                        claim=f"hook command references unreadable {reference}",
                        expected="referenced Python hook exists and parses",
                        action="owner decision",
                    )
                )
    return findings


def check_agents(repo: Path) -> list[Finding]:
    findings: list[Finding] = []
    agents_dir = repo / ".claude/agents"
    if not agents_dir.is_dir():
        return findings

    for path in sorted(agents_dir.glob("*.md")):
        frontmatter, problem = _read_frontmatter(path)
        if problem is not None:
            findings.append(_frontmatter_finding(path, repo, problem))
            continue

        assert frontmatter is not None
        missing = [
            field for field in ("name", "description") if not frontmatter.values.get(field, "")
        ]
        if missing:
            fields = ", ".join(missing)
            findings.append(
                _frontmatter_finding(
                    path,
                    repo,
                    f"missing non-empty required frontmatter field(s): {fields}",
                )
            )
        findings.extend(_hook_findings(path, repo, frontmatter))
    return findings


def _inside_backticks(line: str, start: int, end: int) -> bool:
    for match in re.finditer(r"`[^`]*`", line):
        if match.start() <= start and end <= match.end():
            return True
    return False


def _negative_raw_codex_reference(line: str, match: re.Match[str]) -> bool:
    if _NEGATIVE_WORD.search(line):
        return True
    return _inside_backticks(line, match.start(), match.end()) and bool(
        _NEGATIVE_EXAMPLE.search(line)
    )


def check_goal_skill(repo: Path) -> list[Finding]:
    skill_path = repo / ".claude/skills/goal/SKILL.md"
    relative = _relative(skill_path, repo)
    if not skill_path.is_file():
        return [
            Finding(
                check=3,
                severity="DIVERGENCE",
                message=f"{relative}: goal skill is missing",
                file=relative,
                claim="goal skill is missing",
                expected="goal skill references codex-safe.sh or codex-receipts.sh",
                action="owner decision",
            )
        ]

    try:
        text = skill_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        return [
            Finding(
                check=3,
                severity="DIVERGENCE",
                message=f"{relative}: cannot read goal skill: {exc}",
                file=relative,
                claim="goal skill cannot be read",
                expected="goal skill references codex-safe.sh or codex-receipts.sh",
                action="owner decision",
            )
        ]

    findings: list[Finding] = []
    if "codex-safe.sh" not in text and "codex-receipts.sh" not in text:
        findings.append(
            Finding(
                check=3,
                severity="DIVERGENCE",
                message=f"{relative}: no approved Codex wrapper reference",
                file=relative,
                claim="no codex-safe.sh or codex-receipts.sh reference",
                expected="goal dispatches Codex through an approved wrapper",
                action="owner decision",
            )
        )

    for line_number, line in enumerate(text.splitlines(), start=1):
        for match in _RAW_CODEX.finditer(line):
            if _negative_raw_codex_reference(line, match):
                continue
            findings.append(
                Finding(
                    check=3,
                    severity="DIVERGENCE",
                    message=f"{relative}:{line_number}: affirmative raw codex exec invocation",
                    file=relative,
                    claim=f"line {line_number} invokes raw codex exec",
                    expected="goal dispatches Codex through codex-safe.sh or codex-receipts.sh",
                    action="owner decision",
                )
            )
    return findings


def check_historical_audit(repo: Path) -> list[Finding]:
    audit_path = repo / "docs/superpowers/specs/2026-07-19-codex-usage-audit.md"
    if not audit_path.is_file():
        return []
    try:
        text = audit_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return []

    claims_raw_goal = any(
        "/goal" in line
        and "raw" in line.lower()
        and ("codex" in line.lower() or "cli" in line.lower())
        for line in text.splitlines()
    )
    if not claims_raw_goal:
        return []

    relative = _relative(audit_path, repo)
    return [
        Finding(
            check=4,
            severity="DIVERGENCE",
            message=(
                f"{relative}: historical claim says /goal uses raw Codex; "
                ".claude/skills/goal/SKILL.md is the current source of truth"
            ),
            file=relative,
            claim="historical audit says /goal uses raw codex exec",
            expected="current .claude/skills/goal/SKILL.md wrapper contract",
            action="historical-doc label",
        )
    ]


def collect_findings(repo: Path) -> list[Finding]:
    return [*check_agents(repo), *check_goal_skill(repo), *check_historical_audit(repo)]


def _table_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def render(findings: list[Finding]) -> str:
    lines = [finding.render() for finding in findings]
    if lines:
        lines.append("")
    lines.extend(
        [
            "DIVERGENCE LEDGER",
            "| file | claim/state | expected | action |",
            "|---|---|---|---|",
        ]
    )
    for finding in findings:
        if finding.severity != "DIVERGENCE":
            continue
        cells = (
            finding.file,
            finding.claim,
            finding.expected,
            finding.action,
        )
        lines.append("| " + " | ".join(_table_cell(cell) for cell in cells) + " |")
    return "\n".join(lines)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--strict",
        action="store_true",
        help="exit nonzero when an ERROR-severity finding is present",
    )
    parser.add_argument(
        "--repo",
        type=Path,
        default=Path.cwd(),
        help="repository root to inspect (default: current working directory)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    repo = args.repo.resolve()
    findings = collect_findings(repo)
    print(render(findings))
    if args.strict and any(finding.severity == "ERROR" for finding in findings):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
