"""Margin notes must stay on the sheet.

The layout engine clamps a note's box inside the page, but two things happen
*after* that, when the text is actually drawn, and neither is visible to the
layout engine:

* the glyph **ascent** rises above the baseline, and
* each line is drawn with a ``morph`` rotation pivoting about the box's
  horizontal centre, so the line's left end rises by ``(width/2) * sin(angle)``.

The renderer placed the first baseline at ``note_rect.y0 + fontsize``, which
leaves only ``(1 - ascender) * fontsize`` of headroom -- about 0.38pt for the
handwriting faces. The rotation lift alone reaches ~3.9pt. So any note the
layout placed flush with the top of the page had its first line sheared off.

Observed on a real render before the fix: glyph top at y = -0.39 on a 792pt
page, for two separate notes.

No network calls; no API key required.
"""

from __future__ import annotations

import math

import fitz
import pytest

from halfblood.document_processor import _MAX_MARGIN_WIDTH, DocumentProcessor

#: The widest excursion ``_organic_angle`` can return, in degrees.
_MAX_ANGLE = 3.0


def _page() -> tuple[fitz.Document, fitz.Page]:
    doc = fitz.open()
    return doc, doc.new_page(width=612, height=792)


class TestFirstBaselineKeepsGlyphsOnThePage:
    @pytest.mark.parametrize("angle", [0.0, 1.0, -1.7, 3.0, -3.0])
    @pytest.mark.parametrize("fontsize", [8.0, 9.5, 10.0])
    def test_glyph_top_never_leaves_the_sheet(self, angle: float, fontsize: float) -> None:
        doc, page = _page()
        try:
            dp = DocumentProcessor()
            # The worst case: a full-width note box flush with the top of the page.
            note_rect = fitz.Rect(440.0, 0.0, 440.0 + _MAX_MARGIN_WIDTH, 300.0)
            baseline = dp._first_baseline(page, note_rect, fontsize, angle)

            ascent = abs(dp._measure_font.ascender) * fontsize
            lift = (note_rect.width / 2.0) * math.sin(math.radians(abs(angle)))
            glyph_top = baseline - ascent - lift

            assert glyph_top >= page.rect.y0 - 1e-6, (
                f"glyph top {glyph_top:.2f} is above the page at angle={angle}, "
                f"fontsize={fontsize}"
            )
        finally:
            doc.close()

    def test_a_note_lower_down_is_not_pushed_around(self) -> None:
        """The clamp must only bite at the top edge, not reposition normal notes."""
        doc, page = _page()
        try:
            dp = DocumentProcessor()
            note_rect = fitz.Rect(440.0, 400.0, 560.0, 600.0)
            baseline = dp._first_baseline(page, note_rect, 9.5, 2.0)
            assert baseline == pytest.approx(note_rect.y0 + 9.5)
        finally:
            doc.close()

    def test_the_unrotated_untouched_case_matches_the_old_formula(self) -> None:
        """With no rotation and room to spare, placement is unchanged."""
        doc, page = _page()
        try:
            dp = DocumentProcessor()
            note_rect = fitz.Rect(440.0, 120.0, 560.0, 300.0)
            assert dp._first_baseline(page, note_rect, 9.0, 0.0) == pytest.approx(
                note_rect.y0 + 9.0
            )
        finally:
            doc.close()


def test_organic_angle_stays_within_the_assumed_bound() -> None:
    """``_first_baseline``'s headroom is sized against this bound."""
    dp = DocumentProcessor()
    for seed in [f"note text {i}" for i in range(300)]:
        assert abs(dp._organic_angle(seed)) <= _MAX_ANGLE + 1e-9
