"""P0-T6 — PDF target selection and crossed-out placement.

AUD-26 (inherited #10, mechanism corrected): ``find_text_rect`` returns
``_union_rects(hits)`` over ALL occurrences of a matched variant. A repeated
fallback word therefore produces one rect spanning every occurrence —
measured 415pt tall on the probe page — which is worse than anchoring any
single occurrence. Unioning is only correct across the quads of ONE passage
wrapping lines.

AUD-39: ``_search_variants`` yields no usable fallback for short targets, so
common typographic drift (straight quotes in the LLM target vs curly ones in
the book) makes short quotes unrecoverable: today they return ``None``.

AUD-19: CROSSED_OUT always writes its replacement via
``_write_replacement_above`` in addition to the requested-position writer,
duplicating the note for margin positions. The replacement must route through
the position dispatcher exactly once, while the strikeout mark still lands.

No network calls are made anywhere in this file.
"""

from __future__ import annotations

from pathlib import Path

import fitz
import pytest

from halfblood.document_processor import DocumentProcessor
from halfblood.models import AnnotationType

_LINE_HEIGHT_BOUND = 20.0  # one 11pt text line is ~15pt tall


@pytest.fixture()
def dp(tmp_path: Path) -> DocumentProcessor:
    return DocumentProcessor(project_root=str(tmp_path), seed=7)


@pytest.fixture()
def page() -> fitz.Page:
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text(fitz.Point(72, 100), "Begin by warming the copper cauldron over a low flame.", fontsize=11)
    page.insert_text(fitz.Point(72, 116), "Never let the mixture boil while the valerian steeps.", fontsize=11)
    page.insert_text(fitz.Point(72, 300), "Slice the bean with a silver", fontsize=11)
    page.insert_text(fitz.Point(72, 316), "dagger before pressing it flat.", fontsize=11)
    page.insert_text(fitz.Point(72, 400), "Yes — it’s hot in here, mind the flame.", fontsize=11)
    page.insert_text(fitz.Point(72, 500), "A spare pewter cauldron sits unused in the corner.", fontsize=11)
    return page


# ---------------------------------------------------------------------------
# AUD-26 — one candidate, never a union across distinct occurrences
# ---------------------------------------------------------------------------


def test_repeated_fallback_word_anchors_one_occurrence_not_a_union(
    dp: DocumentProcessor, page: fitz.Page
) -> None:
    # Exact phrase absent -> falls back to the longest word "cauldron",
    # which appears at y~100 and y~500. The anchor must be ONE of them.
    rect = dp.find_text_rect(page, "cauldron warble zzz")
    assert rect is not None
    assert rect.height < _LINE_HEIGHT_BOUND, (
        f"rect spans multiple distinct occurrences: height={rect.height:.1f}"
    )
    occurrences = page.search_for("cauldron")
    assert any(rect.intersects(hit) for hit in occurrences)


def test_repeated_word_anchor_choice_is_deterministic(
    dp: DocumentProcessor, page: fitz.Page
) -> None:
    first = dp.find_text_rect(page, "cauldron warble zzz")
    second = dp.find_text_rect(page, "cauldron warble zzz")
    assert first is not None and second is not None
    assert tuple(first) == tuple(second)


def test_wrapped_passage_still_unions_its_own_lines(
    dp: DocumentProcessor, page: fitz.Page
) -> None:
    # "silver dagger" wraps across two lines — that union IS one passage and
    # must keep covering both line fragments.
    rect = dp.find_text_rect(page, "silver dagger")
    assert rect is not None
    assert rect.height > _LINE_HEIGHT_BOUND  # spans both wrapped lines
    assert rect.y0 < 305 < rect.y1


def test_unique_exact_phrase_is_preferred_over_fallback(
    dp: DocumentProcessor, page: fitz.Page
) -> None:
    rect = dp.find_text_rect(page, "spare pewter cauldron")
    assert rect is not None
    assert 488 < rect.y0 < 492  # the unique phrase's own line, not the first "cauldron"


# ---------------------------------------------------------------------------
# AUD-39 — short targets survive typographic drift
# ---------------------------------------------------------------------------


def test_short_target_with_straight_apostrophe_finds_curly_text(
    dp: DocumentProcessor, page: fitz.Page
) -> None:
    # The page says "it’s hot" (curly); the LLM quotes "it's hot" (straight).
    # Exact search fails and there is no usable word fallback — today: None.
    rect = dp.find_text_rect(page, "it's hot")
    assert rect is not None, "short target lost to smart-punctuation drift"
    assert 388 < rect.y0 < 392, f"anchored the wrong line: {rect}"
    assert rect.height < _LINE_HEIGHT_BOUND


def test_absent_short_target_is_still_not_found(
    dp: DocumentProcessor, page: fitz.Page
) -> None:
    # The recovery fallback must not manufacture matches.
    assert dp.find_text_rect(page, "cut it up") is None


# ---------------------------------------------------------------------------
# AUD-19 — crossed-out replacement routes through the position dispatcher
# ---------------------------------------------------------------------------

_WRITERS = (
    "_write_margin_text",
    "_write_inline_text",
    "_write_between_lines_text",
    "_write_replacement_above",
)


def _spy_writers(
    monkeypatch: pytest.MonkeyPatch,
) -> list[tuple[str, tuple]]:
    calls: list[tuple[str, tuple]] = []
    for name in _WRITERS:
        real = getattr(DocumentProcessor, name)

        def wrapper(self, *args, _name=name, _real=real, **kwargs):  # type: ignore[no-untyped-def]
            calls.append((_name, args))
            return _real(self, *args, **kwargs)

        monkeypatch.setattr(DocumentProcessor, name, wrapper)
    return calls


@pytest.mark.parametrize(
    ("position", "expected_writers"),
    [
        ("margin_right", {"_write_margin_text"}),
        ("margin_left", {"_write_margin_text"}),
        ("inline", {"_write_inline_text"}),
        # For between_lines, either interline writer is a faithful dispatch.
        ("between_lines", {"_write_between_lines_text", "_write_replacement_above"}),
    ],
)
def test_crossed_out_replacement_uses_requested_position_once(
    dp: DocumentProcessor,
    page: fitz.Page,
    monkeypatch: pytest.MonkeyPatch,
    position: str,
    expected_writers: set[str],
) -> None:
    calls = _spy_writers(monkeypatch)
    rect = dp.find_text_rect(page, "spare pewter cauldron")
    assert rect is not None
    dp.add_margin_note(
        page, rect, "pewter is wrong; use brass", AnnotationType.CROSSED_OUT,
        confidence=0.9, position=position,
    )
    assert len(calls) == 1, (
        f"replacement text must be written exactly once, got {[c[0] for c in calls]}"
    )
    assert calls[0][0] in expected_writers
    if position == "margin_left":
        assert calls[0][1][-1] == "left" or calls[0][1] == ()  # side arg when present

    strike_annots = [a for a in page.annots() or [] if a.type[1] == "StrikeOut"]
    assert len(strike_annots) == 1, "the strikeout mark itself must still be applied"
