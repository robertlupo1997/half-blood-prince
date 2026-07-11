"""P0-T10 — missing-font logging hygiene (Phase 0 noisy-warning item).

Today every `DocumentProcessor` constructed without a handwriting font logs a
multi-line WARNING with download instructions — once per construction, so a
batch run or test suite drowns real warnings in expected noise. The contract
pinned here:

* An AUTO-DISCOVERY miss (no explicit ``font_path``) is expected, supported
  behavior (the pipeline falls back to Helvetica-Oblique by design). It must
  not log at WARNING level, and the informational notice appears at most once
  per process, not per construction.
* An EXPLICITLY configured ``font_path`` that does not exist is a user error
  and must stay loud: one WARNING naming the path the user gave.

No network calls are made anywhere in this file.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from halfblood.document_processor import DocumentProcessor

_LOGGER = "halfblood.document_processor"


def test_autodiscovery_miss_is_quiet_and_not_repeated(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    # No fonts/ dir under this project root -> discovery misses every time.
    with caplog.at_level(logging.DEBUG, logger=_LOGGER):
        for _ in range(3):
            DocumentProcessor(project_root=str(tmp_path))

    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert warnings == [], (
        "expected missing-font fallback (an anticipated, supported state) "
        f"not to WARN; got: {[r.message for r in warnings]}"
    )
    infos = [
        r
        for r in caplog.records
        if r.levelno == logging.INFO and "font" in r.getMessage().lower()
    ]
    assert len(infos) <= 1, "the fallback notice must not repeat per construction"


def test_explicit_missing_font_path_warns_once_with_the_given_path(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    ghost = tmp_path / "GhostScrawl.ttf"
    with caplog.at_level(logging.DEBUG, logger=_LOGGER):
        DocumentProcessor(font_path=str(ghost), project_root=str(tmp_path))

    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert len(warnings) == 1, (
        f"an explicitly configured missing font is a user error and must WARN "
        f"exactly once; got {len(warnings)}"
    )
    assert str(ghost) in warnings[0].getMessage(), (
        "the warning must name the path the user configured"
    )
