#!/usr/bin/env python3
"""Require an sdd-driver report, with a bounded stop-refusal loop."""

from __future__ import annotations

import os
import sys
from pathlib import Path

DEFAULT_REPORT = ".superpowers/sdd/driver-report.md"
REFUSAL_MESSAGE = (
    "write your final report to .superpowers/sdd/driver-report.md before stopping"
)
REPEATED_MESSAGE = (
    "allowing stop after repeated refusal — parent must treat this driver as blocked"
)


def _prior_refusals(state_path: Path) -> int:
    try:
        return max(0, int(state_path.read_text(encoding="utf-8").strip()))
    except (FileNotFoundError, OSError, ValueError):
        return 0


def main() -> int:
    # Consume the hook payload even though stop authorization depends only on the marker.
    sys.stdin.read()

    report_path = Path(os.environ.get("SDD_DRIVER_REPORT", DEFAULT_REPORT))
    try:
        if report_path.is_file() and report_path.stat().st_size > 0:
            return 0
    except OSError:
        pass

    state_path = report_path.with_name("driver-report.stop-refusals")
    if _prior_refusals(state_path) >= 1:
        print(REPEATED_MESSAGE, file=sys.stderr)
        return 0

    try:
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text("1\n", encoding="utf-8")
    except OSError:
        # Still refuse this attempt; a later unwritable-state attempt may refuse again.
        pass
    print(REFUSAL_MESSAGE, file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
