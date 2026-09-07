#!/usr/bin/env python3
"""Run the offline placement benchmark. JSON stdout; exit 1 for any mismatch."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# The benchmark is a source-tree tool, deliberately not part of the wheel.
REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from benchmarks.placement import run_benchmark  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="Also write the identical JSON report to this file")
    args = parser.parse_args(argv)
    report = run_benchmark()
    payload = json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if args.output:
        args.output.write_text(payload, encoding="utf-8")
    sys.stdout.write(payload)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
