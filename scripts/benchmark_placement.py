#!/usr/bin/env python3
"""Run the offline placement benchmark. JSON stdout; exit 1 for any mismatch."""
from __future__ import annotations

import argparse
import contextlib
import json
import sys
from pathlib import Path

# The benchmark is a source-tree tool, deliberately not part of the wheel.
REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

# This script's contract is "JSON on stdout, nothing else", and an import can break
# it: PyMuPDF's `fitz` shim prints its deprecation notice to STDOUT, not stderr, on
# any version newer than the dev lock's 1.28.0. CI resolves pymupdf from the
# pyproject range and got one, which corrupted both this test and the workflow's
# `> placement-benchmark.json` artifact. Any import chatter now lands on stderr.
with contextlib.redirect_stdout(sys.stderr):
    from benchmarks.placement import run_benchmark  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    """Run the benchmark and stream the JSON report to stdout.

    The benchmark writes nothing to disk. To capture the report, redirect stdout
    with the shell (e.g. ``> report.json``). Do NOT pass a path that could overwrite
    a benchmark input fixture.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)
    report = run_benchmark()
    payload = json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    sys.stdout.write(payload)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
