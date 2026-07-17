"""P2-T4 — Resolve PDF targets to ordered multi-quad anchors.

Architecture §5.5 line 420: *"Represent source targets as character ranges plus one or
more line quads, not a single union rectangle."* Plus §5.6 (preserve page boxes/rotations)
and §7.3 (multi-quad anchors; rotated/cropped pages).

The resolver maps a **selected character range** into ``page.get_text("text")`` to
**ordered per-line quads** in the page's *displayed* coordinate space (rotation applied,
so every quad lies within ``page.rect``). It never unions separate lines into one rect and
never bridges two occurrences — a fixed character range cannot span two occurrences.

Scope note: this is geometry only. Occurrence *selection* (the P2-T3 scorer) is wired in
P2-T8/T9; here the char range is the input. No drawing/rendering is exercised.

Mechanism validated by the controller against PyMuPDF 1.28.0 / MuPDF 1.29.0 before these
tests were written (rawdict-walk reconstructs ``get_text("text")`` byte-for-byte;
``get_text``/``rawdict`` coords are un-derotated; ``page.rotation_matrix`` maps them into
``page.rect``). No network calls are made anywhere in this file.
"""

from __future__ import annotations

import math
from pathlib import Path

import fitz
import pytest

from halfblood.documents import (
    PdfAlignmentError,
    PdfAnchor,
    PdfPageIndex,
    resolve_pdf_anchor,
)

_FIXTURE_PDF = Path(__file__).parent / "fixtures" / "potions_textbook.pdf"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _span(index: PdfPageIndex, substring: str, occurrence: int = 0) -> tuple[int, int]:
    """Half-open char range of the ``occurrence``-th literal ``substring`` in index.text."""
    text = index.text
    pos = -1
    for _ in range(occurrence + 1):
        pos = text.find(substring, pos + 1)
        assert pos >= 0, f"{substring!r} (occurrence {occurrence}) not present in page text"
    return pos, pos + len(substring)


def _finite_rect(rect: fitz.Rect) -> bool:
    return all(math.isfinite(v) for v in (rect.x0, rect.y0, rect.x1, rect.y1))


def _one_liner(*lines: str, width: int = 612, height: int = 792) -> fitz.Page:
    doc = fitz.open()
    page = doc.new_page(width=width, height=height)
    y = 100
    for line in lines:
        page.insert_text(fitz.Point(72, y), line, fontsize=11)
        y += 16
    return page


# ---------------------------------------------------------------------------
# alignment invariant — the foundation
# ---------------------------------------------------------------------------


def test_page_index_text_equals_get_text_on_real_fixture() -> None:
    """PdfPageIndex.text must reconstruct page.get_text('text') byte-for-byte, so a char
    range selected against get_text('text') indexes the same string the resolver walks.
    Silent misalignment would map every offset to the wrong glyph."""
    doc = fitz.open(str(_FIXTURE_PDF))
    try:
        assert doc.page_count >= 1
        for i in range(doc.page_count):
            page = doc[i]
            assert PdfPageIndex(page).text == page.get_text("text"), f"misaligned on page {i}"
    finally:
        doc.close()


def test_page_index_text_equals_get_text_on_wrapped_textbox() -> None:
    doc = fitz.open()
    try:
        page = doc.new_page(width=612, height=792)
        page.insert_textbox(
            fitz.Rect(72, 72, 400, 300),
            "First paragraph wraps across several lines here indeed it does for sure.\n\n"
            "Second paragraph also wraps a little bit further down the column.",
            fontsize=11,
        )
        assert PdfPageIndex(page).text == page.get_text("text")
    finally:
        doc.close()


def test_alignment_error_is_a_runtime_error() -> None:
    assert issubclass(PdfAlignmentError, RuntimeError)


def test_alignment_error_raised_when_reconstruction_diverges(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If a future/exotic page makes the rawdict walk disagree with get_text('text'),
    the index must raise rather than emit geometry mapped to the wrong offsets."""
    page = _one_liner("valerian sprig here")
    real_get_text = page.get_text

    def fake_get_text(option: str = "text", *args, **kwargs):  # type: ignore[no-untyped-def]
        result = real_get_text(option, *args, **kwargs)
        if option == "text" and isinstance(result, str):
            return result + "EXTRA-DIVERGENCE"
        return result

    monkeypatch.setattr(page, "get_text", fake_get_text)
    with pytest.raises(PdfAlignmentError):
        PdfPageIndex(page)


# ---------------------------------------------------------------------------
# one quad per touched line, in reading order
# ---------------------------------------------------------------------------


def test_phrase_wrapping_two_lines_yields_one_quad_per_line() -> None:
    page = _one_liner("Add the valerian sprig and", "stir until the potion clears.")
    index = PdfPageIndex(page)
    start = _span(index, "valerian sprig and")[0]
    end = _span(index, "stir until")[1]
    anchor = resolve_pdf_anchor(index, start, end)
    assert anchor is not None
    assert isinstance(anchor, PdfAnchor)
    assert anchor.line_count == 2
    assert len(anchor.quads) == 2
    # reading order: first quad is above the second
    assert anchor.quads[0].rect.y0 < anchor.quads[1].rect.y0
    for quad in anchor.quads:
        assert _finite_rect(quad.rect)
        assert quad.rect in page.rect


def test_phrase_wrapping_three_lines_yields_three_ordered_quads() -> None:
    page = _one_liner("alpha valerian one", "beta valerian two", "gamma valerian three")
    index = PdfPageIndex(page)
    start = _span(index, "alpha valerian one")[0]
    end = _span(index, "gamma valerian three")[1]
    anchor = resolve_pdf_anchor(index, start, end)
    assert anchor is not None
    assert anchor.line_count == 3
    tops = [quad.rect.y0 for quad in anchor.quads]
    assert tops == sorted(tops), "quads must be in top-to-bottom reading order"


def test_single_line_selection_is_one_quad() -> None:
    page = _one_liner("the sopophorous bean releases its juice")
    index = PdfPageIndex(page)
    anchor = resolve_pdf_anchor(index, *_span(index, "sopophorous bean"))
    assert anchor is not None
    assert anchor.line_count == 1


# ---------------------------------------------------------------------------
# repeated occurrences never bridge
# ---------------------------------------------------------------------------


def test_repeated_phrase_two_ranges_resolve_to_distinct_non_bridging_anchors() -> None:
    page = _one_liner(
        "Add the valerian sprig and stir.",
        "",
        "",
        "",
        "",
        "Add the valerian sprig once more.",
    )
    index = PdfPageIndex(page)
    first = resolve_pdf_anchor(index, *_span(index, "valerian sprig", 0))
    second = resolve_pdf_anchor(index, *_span(index, "valerian sprig", 1))
    assert first is not None and second is not None
    assert first.line_count == 1 and second.line_count == 1
    # distinct occurrences, far apart, and the first never reaches the second
    assert first.quads[0].rect.y1 < second.quads[0].rect.y0
    # neither anchor's bounding rect swallows the other occurrence
    assert not first.bounding_rect().intersects(second.quads[0].rect)


# ---------------------------------------------------------------------------
# quads cover only the selected characters (not neighbouring words)
# ---------------------------------------------------------------------------


def test_quad_covers_only_selected_words_not_the_next_word() -> None:
    """Selecting only 'valerian' must not produce a quad that also covers the following
    'sprig'. A whole-line or whole-word-rounded resolver would fail this."""
    page = _one_liner("Add the valerian sprig and stir.")
    index = PdfPageIndex(page)
    anchor = resolve_pdf_anchor(index, *_span(index, "valerian"))
    assert anchor is not None
    sprig_rect = page.search_for("sprig")[0]
    # the 'valerian' quad ends at or before the start of 'sprig' (1pt slack for kerning)
    assert anchor.quads[0].rect.x1 <= sprig_rect.x0 + 1.0


# ---------------------------------------------------------------------------
# page rotation — NON-VACUOUS: bottom-of-page text so un-derotated coords fall
# OUTSIDE the rotated page.rect; a resolver that skips rotation_matrix FAILS this.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("rotation", [90, 180, 270])
def test_rotated_page_quads_stay_within_page_rect(rotation: int) -> None:
    doc = fitz.open()
    try:
        page = doc.new_page(width=612, height=792)
        # near the bottom-right so 90/270 pushes un-derotated coords past page.rect
        page.insert_text(fitz.Point(400, 740), "rotated valerian anchor here", fontsize=11)
        page.set_rotation(rotation)
        index = PdfPageIndex(page)
        anchor = resolve_pdf_anchor(index, *_span(index, "rotated valerian"))
        assert anchor is not None
        assert anchor.page_rotation == rotation
        for quad in anchor.quads:
            assert _finite_rect(quad.rect)
            assert quad.rect in page.rect, (
                f"quad {quad.rect} escaped rotated page.rect {page.rect} — "
                "rotation_matrix not applied?"
            )
    finally:
        doc.close()


@pytest.mark.parametrize("rotation", [90, 180, 270])
def test_rotation_actually_moves_the_quad_off_the_unrotated_position(rotation: int) -> None:
    """Guard against a vacuous rotation fixture: for EVERY rotation the resolved quad must
    move off the un-derotated position (otherwise the fixture proves nothing about rotation).

    This is what makes the rotation coverage non-vacuous for all of 90/180/270 — the plain
    ``quad.rect in page.rect`` assertion above only discriminates at 90/270 (at 180 the
    un-derotated bottom-of-page coords already lie inside the unchanged page.rect)."""
    doc = fitz.open()
    try:
        page = doc.new_page(width=612, height=792)
        page.insert_text(fitz.Point(400, 740), "rotated valerian anchor here", fontsize=11)
        page.set_rotation(rotation)
        index = PdfPageIndex(page)
        anchor = resolve_pdf_anchor(index, *_span(index, "rotated valerian"))
        assert anchor is not None
        # un-derotated search geometry for the same text
        raw_hit = page.search_for("rotated valerian")[0]
        assert not anchor.quads[0].rect.intersects(raw_hit), (
            "resolved quad coincides with the un-derotated position — rotation ignored"
        )
    finally:
        doc.close()


# ---------------------------------------------------------------------------
# crop-box
# ---------------------------------------------------------------------------


def test_cropped_page_quads_stay_within_cropped_page_rect() -> None:
    doc = fitz.open()
    try:
        page = doc.new_page(width=612, height=792)
        page.insert_text(fitz.Point(120, 200), "cropped valerian marker line", fontsize=11)
        page.set_cropbox(fitz.Rect(50, 50, 400, 500))
        index = PdfPageIndex(page)
        anchor = resolve_pdf_anchor(index, *_span(index, "cropped valerian"))
        assert anchor is not None
        for quad in anchor.quads:
            assert quad.rect in page.rect
    finally:
        doc.close()


# ---------------------------------------------------------------------------
# degenerate ranges & bounding rect
# ---------------------------------------------------------------------------


def test_empty_range_returns_none() -> None:
    page = _one_liner("valerian sprig")
    index = PdfPageIndex(page)
    assert resolve_pdf_anchor(index, 5, 5) is None
    assert resolve_pdf_anchor(index, 8, 3) is None


def test_separator_only_range_returns_none() -> None:
    """A range covering only the inter-line '\\n' (no glyphs) has no geometry."""
    page = _one_liner("first valerian line", "second valerian line")
    index = PdfPageIndex(page)
    newline = index.text.index("\n")
    assert resolve_pdf_anchor(index, newline, newline + 1) is None


def test_bounding_rect_is_union_of_quad_rects() -> None:
    page = _one_liner("Add the valerian sprig and", "stir until the potion clears.")
    index = PdfPageIndex(page)
    start = _span(index, "valerian sprig and")[0]
    end = _span(index, "stir until")[1]
    anchor = resolve_pdf_anchor(index, start, end)
    assert anchor is not None
    expected = fitz.Rect(anchor.quads[0].rect)
    for quad in anchor.quads[1:]:
        expected |= quad.rect
    assert anchor.bounding_rect() == expected
