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
from halfblood.documents import PdfPageIndex, resolve_pdf_anchor
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


# ---------------------------------------------------------------------------
# P2-T4 — find_text_rect is the compatibility adapter: it returns the union of
# the chosen anchor's per-line quads (from resolve_pdf_anchor), never a union
# across distinct occurrences.
# ---------------------------------------------------------------------------


def test_find_text_rect_returns_union_of_chosen_anchor_quads(
    dp: DocumentProcessor, page: fitz.Page
) -> None:
    # "silver dagger" wraps across two lines (y~300 / y~316). The adapter's rect
    # must equal the union of the resolver's two per-line quads for that passage.
    rect = dp.find_text_rect(page, "silver dagger")
    assert rect is not None

    index = PdfPageIndex(page)
    start = index.text.index("silver")
    end = index.text.index("dagger") + len("dagger")
    anchor = resolve_pdf_anchor(index, start, end)
    assert anchor is not None
    assert anchor.line_count == 2  # genuinely two touched lines, not one union

    expected = anchor.bounding_rect()
    for a, b in zip(tuple(rect), tuple(expected), strict=True):
        assert abs(a - b) <= 2.0, f"adapter rect {tuple(rect)} != anchor union {tuple(expected)}"


# ---------------------------------------------------------------------------
# P2-T8 fold-in #2 — whitespace-run normalization: occurrence selection
# ---------------------------------------------------------------------------


def test_score_candidates_finds_target_through_whitespace_run_normalization() -> None:
    """score_candidates must locate a target whose source text has whitespace runs.

    PDF text extraction often produces runs of multiple spaces.  NormalizedText
    collapses each whitespace run to a single space, so a selector with single
    spaces must still match the normalized form.

    This test constructs a NormalizedText directly from text with double spaces
    and asserts that score_candidates returns a MatchResult pointing to the
    correct passage.
    """
    from halfblood.documents.matching import MatchResult, NormalizedText, score_candidates
    from halfblood.models.annotations import TargetSelector

    raw_with_runs = "Begin  by  warming  the  cauldron  over  a  low  flame."
    text = NormalizedText(raw_with_runs)
    # Normalized form must collapse every run.
    assert "  " not in text.text, "whitespace runs must be collapsed in normalized text"
    assert "cauldron" in text.text

    selector = TargetSelector(exact="warming the cauldron over a low flame")
    outcome = score_candidates(selector, text)
    assert isinstance(outcome, MatchResult), (
        f"expected MatchResult after whitespace normalization; got {outcome}"
    )
    # raw_span must fall inside the original text.
    raw = outcome.candidate.raw_span
    assert raw_with_runs[raw.start : raw.end].replace(" ", "").startswith("warmingthe")


def test_normalized_text_raw_span_covers_whitespace_run_char_positions() -> None:
    """NormalizedText.raw_span must map back to cover the original whitespace run.

    When two raw spaces normalize to one, the raw_span for the single normalized
    space character must cover BOTH original space characters (start to end
    spans the whole run).
    """
    from halfblood.documents.matching import NormalizedText

    raw = "hello  world"  # two spaces
    text = NormalizedText(raw)
    assert text.text == "hello world"  # normalized to one space

    # The normalized text is:  h e l l o   w o r l d
    # indices:                  0 1 2 3 4 5 6 7 8 9 10
    # The space at normalized index 5 must map back to the run [5, 7) in raw.
    span = text.raw_span(5, 6)  # the single normalized space character
    assert span.start == 5, f"expected run start 5, got {span.start}"
    assert span.end == 7, f"expected run end 7 (covers both raw spaces), got {span.end}"


# ---------------------------------------------------------------------------
# P2-T8 fold-in #3 — score_candidates → raw_span → resolve_pdf_anchor chain
# ---------------------------------------------------------------------------


def test_score_candidates_raw_span_resolve_pdf_anchor_chain(
    page: fitz.Page,
) -> None:
    """Full chain: score_candidates → raw_span → resolve_pdf_anchor.

    The passage 'silver dagger before pressing it flat' spans two lines on
    the fixture page (y~300 and y~316).  This integration test verifies that
    chaining the three functions produces a PdfAnchor with line_count == 2,
    i.e., that the raw_span from score_candidates maps correctly into
    PdfPageIndex's char positions.
    """
    from halfblood.documents.matching import MatchResult, NormalizedText, score_candidates
    from halfblood.models.annotations import TargetSelector

    index = PdfPageIndex(page)
    text = NormalizedText(index.text)
    selector = TargetSelector(exact="silver dagger before pressing it flat")

    outcome = score_candidates(selector, text)
    assert isinstance(outcome, MatchResult), (
        f"score_candidates failed to find the target: {outcome}"
    )

    raw = outcome.candidate.raw_span
    anchor = resolve_pdf_anchor(index, raw.start, raw.end)
    assert anchor is not None, (
        "resolve_pdf_anchor returned None for a span from score_candidates"
    )
    # The passage wraps two lines so the anchor must carry two quads.
    assert anchor.line_count == 2, (
        f"expected line_count=2 for a two-line wrapped passage; got {anchor.line_count}"
    )
    assert len(anchor.quads) == 2

