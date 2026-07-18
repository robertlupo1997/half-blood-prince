"""P0-T5 — PDF margin and interline geometry must stay on the page.

AUD-07: a right-margin note for a target near the right edge gets
``max(_MIN_MARGIN_WIDTH, available)`` width and starts at ``rect.x1 + gap``
with no page clamp — the note renders off the page edge (visually confirmed
in the font-trial renders).
AUD-08: the note block is vertically centered on its target with no top or
bottom clamp — long notes near the page top/bottom run off the page.
AUD-09/AUD-20: ``_write_between_lines_text`` (and the crossed-out
replacement) clamp ``top_y`` with ``max(small_size, ...)`` — near the page
top this pushes later lines DOWN onto or below the annotated line itself.
AUD-40: ``_wrap_text`` is a greedy word-wrap; a single token wider than the
column is emitted as one over-wide line invading the body text.

Contract style: these tests spy on ``fitz.Shape.insert_text`` /
``insert_textbox`` (recording, then delegating to the real call) and assert
observable geometry — every drawn note line lies inside ``page.rect``, notes
land in an actual margin when their preferred margin has no room (the
implementation may switch sides and/or reduce size), vertical shifting
preserves line order, and interline text stays above its target. They do not
prescribe the internal mechanism.

No network calls are made anywhere in this file.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import fitz
import pytest

from halfblood.document_processor import DocumentProcessor
from halfblood.models import AnnotationType

_PAGE_W, _PAGE_H = 612.0, 792.0

_LONG_NOTE = (
    "This potion is brewed incorrectly in every edition of this book. "
    "Crush the bean with the flat of a silver dagger, add the wormwood "
    "in two turns not one, and stir counter-clockwise on the seventh "
    "turn only, or the draught will be worthless sludge."
)


@pytest.fixture()
def dp(tmp_path: Path) -> DocumentProcessor:
    # No fonts under tmp_path -> deterministic Helvetica-Oblique fallback,
    # whose measuring font is fitz.Font("helv").
    return DocumentProcessor(project_root=str(tmp_path), seed=7)


@pytest.fixture()
def page() -> fitz.Page:
    doc = fitz.open()
    return doc.new_page(width=_PAGE_W, height=_PAGE_H)


@pytest.fixture()
def drawn(monkeypatch: pytest.MonkeyPatch) -> list[SimpleNamespace]:
    calls: list[SimpleNamespace] = []
    real_text = fitz.Shape.insert_text
    real_box = fitz.Shape.insert_textbox

    def rec_text(self: fitz.Shape, point, buffer_, *args, **kwargs):  # type: ignore[no-untyped-def]
        calls.append(
            SimpleNamespace(
                kind="text",
                point=fitz.Point(point),
                text=str(buffer_),
                fontsize=float(kwargs.get("fontsize", 11.0)),
            )
        )
        return real_text(self, point, buffer_, *args, **kwargs)

    def rec_box(self: fitz.Shape, rect, buffer_, *args, **kwargs):  # type: ignore[no-untyped-def]
        calls.append(
            SimpleNamespace(
                kind="box",
                rect=fitz.Rect(rect),
                text=str(buffer_),
                fontsize=float(kwargs.get("fontsize", 11.0)),
            )
        )
        return real_box(self, rect, buffer_, *args, **kwargs)

    monkeypatch.setattr(fitz.Shape, "insert_text", rec_text)
    monkeypatch.setattr(fitz.Shape, "insert_textbox", rec_box)
    return calls


def _assert_all_on_page(
    calls: list[SimpleNamespace], dp: DocumentProcessor, tol: float = 0.5
) -> None:
    assert calls, "expected at least one drawn note line"
    page_rect = fitz.Rect(0, 0, _PAGE_W, _PAGE_H)
    for c in calls:
        if c.kind == "text":
            width = dp._measure_font.text_length(c.text, fontsize=c.fontsize)
            assert c.point.x >= page_rect.x0 - tol, f"line starts off-page left: {c}"
            assert c.point.x + width <= page_rect.x1 + tol, (
                f"line ends off-page right: {c.text!r} x={c.point.x:.1f} w={width:.1f}"
            )
            assert c.point.y - c.fontsize >= page_rect.y0 - tol, f"line above page top: {c}"
            assert c.point.y <= page_rect.y1 + tol, f"baseline below page bottom: {c}"
        else:
            assert page_rect.contains(c.rect), f"textbox outside page: {c.rect}"


def _text_calls(calls: list[SimpleNamespace]) -> list[SimpleNamespace]:
    return [c for c in calls if c.kind == "text"]


# ---------------------------------------------------------------------------
# AUD-07 — horizontal bounds and margin selection
# ---------------------------------------------------------------------------


def test_right_margin_note_with_target_hugging_right_edge_stays_on_page(
    dp: DocumentProcessor, page: fitz.Page, drawn: list[SimpleNamespace]
) -> None:
    target = fitz.Rect(500, 300, 590, 312)  # 22pt of right margin: below minimum
    dp.add_margin_note(page, target, "Crush it, don't cut it.", AnnotationType.CORRECTION,
                       confidence=0.9, position="margin_right")
    _assert_all_on_page(drawn, dp)
    # No usable right margin: the note must land in an actual margin, i.e.
    # entirely clear of the target's horizontal span (left side here).
    for c in _text_calls(drawn):
        width = dp._measure_font.text_length(c.text, fontsize=c.fontsize)
        assert c.point.x + width <= target.x0 - 2 or c.point.x >= target.x1 + 2, (
            f"note line overlaps the target's column: {c.text!r}"
        )


def test_left_margin_note_with_target_hugging_left_edge_stays_on_page(
    dp: DocumentProcessor, page: fitz.Page, drawn: list[SimpleNamespace]
) -> None:
    target = fitz.Rect(14, 300, 90, 312)  # 14pt of left margin: below minimum
    dp.add_margin_note(page, target, "Obvious to anyone with eyes.", AnnotationType.INSIGHT,
                       confidence=0.8, position="margin_left")
    _assert_all_on_page(drawn, dp)
    for c in _text_calls(drawn):
        width = dp._measure_font.text_length(c.text, fontsize=c.fontsize)
        assert c.point.x + width <= target.x0 - 2 or c.point.x >= target.x1 + 2, (
            f"note line overlaps the target's column: {c.text!r}"
        )


def test_normal_right_margin_note_renders_beside_target(
    dp: DocumentProcessor, page: fitz.Page, drawn: list[SimpleNamespace]
) -> None:
    # Guard: the happy path keeps working — note right of the target, on-page.
    target = fitz.Rect(100, 400, 300, 412)
    dp.add_margin_note(page, target, "Predictable.", AnnotationType.INSIGHT,
                       confidence=0.8, position="margin_right")
    _assert_all_on_page(drawn, dp)
    for c in _text_calls(drawn):
        assert c.point.x >= target.x1 + 2


# ---------------------------------------------------------------------------
# AUD-08 — vertical bounds; shifting preserves line order
# ---------------------------------------------------------------------------


def test_long_note_near_page_top_stays_on_page_in_order(
    dp: DocumentProcessor, page: fitz.Page, drawn: list[SimpleNamespace]
) -> None:
    target = fitz.Rect(100, 30, 300, 42)
    dp.add_margin_note(page, target, _LONG_NOTE, AnnotationType.IMPROVEMENT,
                       confidence=0.9, position="margin_right")
    _assert_all_on_page(drawn, dp)
    ys = [c.point.y for c in _text_calls(drawn)]
    assert ys == sorted(ys), "vertical shifting must preserve line order"


def test_long_note_near_page_bottom_stays_on_page_in_order(
    dp: DocumentProcessor, page: fitz.Page, drawn: list[SimpleNamespace]
) -> None:
    target = fitz.Rect(100, 760, 300, 772)
    dp.add_margin_note(page, target, _LONG_NOTE, AnnotationType.IMPROVEMENT,
                       confidence=0.9, position="margin_left")
    _assert_all_on_page(drawn, dp)
    ys = [c.point.y for c in _text_calls(drawn)]
    assert ys == sorted(ys), "vertical shifting must preserve line order"


# ---------------------------------------------------------------------------
# AUD-40 — a token wider than the column is split, not emitted over-wide
# ---------------------------------------------------------------------------


def test_giant_token_in_margin_note_is_split_to_fit(
    dp: DocumentProcessor, page: fitz.Page, drawn: list[SimpleNamespace]
) -> None:
    note = "Sectumsempra" + "x" * 90 + " for enemies."
    target = fitz.Rect(100, 400, 300, 412)
    dp.add_margin_note(page, target, note, AnnotationType.INVENTION,
                       confidence=0.9, position="margin_right")
    _assert_all_on_page(drawn, dp)
    assert all(c.text.strip() for c in _text_calls(drawn)), "no empty chunks"


def test_wrap_text_splits_long_tokens_and_preserves_characters(
    dp: DocumentProcessor,
) -> None:
    token = "Levicorpus" + "y" * 120
    lines = dp._wrap_text(f"try {token} now", max_width=60.0, fontsize=9.0)
    assert all(line.strip() for line in lines)
    for line in lines:
        assert dp._measure_font.text_length(line, fontsize=9.0) <= 60.0 + 0.5, (
            f"wrapped line still wider than the column: {line!r}"
        )
    rejoined = "".join("".join(line.split()) for line in lines)
    assert rejoined == "try".replace(" ", "") + token + "now", (
        "wrapping must not lose or reorder characters"
    )


def test_wrap_text_single_glyph_wider_than_bound_terminates(
    dp: DocumentProcessor,
) -> None:
    # A glyph that can never fit must terminate safely, not loop or vanish.
    lines = dp._wrap_text("W", max_width=1.0, fontsize=60.0)
    assert lines == ["W"]


# ---------------------------------------------------------------------------
# AUD-09 / AUD-20 — interline text stays above its target and on-page
# ---------------------------------------------------------------------------


def test_between_lines_near_top_stays_above_target(
    dp: DocumentProcessor, page: fitz.Page, drawn: list[SimpleNamespace]
) -> None:
    target = fitz.Rect(100, 14, 300, 24)
    dp.add_margin_note(
        page, target,
        "add sopophorous juice first, always, then the wormwood infusion in "
        "two slow turns before anything else touches the cauldron",
        AnnotationType.SHORTCUT, confidence=0.8, position="between_lines",
    )
    _assert_all_on_page(drawn, dp)
    for c in _text_calls(drawn):
        assert c.point.y <= target.y0 - 1, (
            f"interline note baseline {c.point.y:.1f} not above target top {target.y0}"
        )


def test_crossed_out_replacement_near_top_stays_above_target(
    dp: DocumentProcessor, page: fitz.Page, drawn: list[SimpleNamespace]
) -> None:
    target = fitz.Rect(100, 14, 300, 24)
    dp.add_margin_note(
        page, target,
        "half-counter-clockwise turn after each seventh stir, and a pinch of "
        "powdered asphodel scattered across the surface at the very end",
        AnnotationType.CROSSED_OUT, confidence=0.9, position="margin_right",
    )
    interline = [c for c in _text_calls(drawn) if c.point.x < target.x1 and c.point.x >= target.x0 - 1]
    for c in interline:
        assert c.point.y <= target.y0 - 1, (
            f"replacement baseline {c.point.y:.1f} overlaps the struck line at {target.y0}"
        )
    _assert_all_on_page(drawn, dp)


# ---------------------------------------------------------------------------
# P2-T7 — layout/anchors.py adapter bridge
#
# Inline imports guard existing tests from collection failure while the
# halfblood.layout package does not yet exist.
# ---------------------------------------------------------------------------


def test_surf_rect_from_fitz_converts_bounds() -> None:
    from halfblood.layout.anchors import surf_rect_from_fitz
    from halfblood.models.rendering import SurfaceRect

    r = fitz.Rect(10.5, 20.0, 300.0, 400.5)
    s = surf_rect_from_fitz(r)
    assert isinstance(s, SurfaceRect)
    assert s.x0 == pytest.approx(10.5)
    assert s.y0 == pytest.approx(20.0)
    assert s.x1 == pytest.approx(300.0)
    assert s.y1 == pytest.approx(400.5)


def test_surf_quad_from_fitz_converts_corners() -> None:
    from halfblood.layout.anchors import surf_quad_from_fitz
    from halfblood.models.rendering import SurfaceQuad

    q = fitz.Rect(10.0, 20.0, 200.0, 32.0).quad
    s = surf_quad_from_fitz(q)
    assert isinstance(s, SurfaceQuad)
    assert s.ul.x == pytest.approx(10.0)
    assert s.ul.y == pytest.approx(20.0)
    assert s.lr.x == pytest.approx(200.0)
    assert s.lr.y == pytest.approx(32.0)


def test_pdf_anchor_to_resolved_anchor_maps_char_range_and_quads() -> None:
    from halfblood.documents.pdf import PdfAnchor
    from halfblood.layout.anchors import pdf_anchor_to_resolved_anchor
    from halfblood.models.rendering import ResolvedAnchor

    q1 = fitz.Rect(100.0, 300.0, 400.0, 312.0).quad
    q2 = fitz.Rect(100.0, 316.0, 300.0, 328.0).quad
    anchor = PdfAnchor(quads=(q1, q2), char_range=(5, 25), line_count=2, page_rotation=0)
    ra = pdf_anchor_to_resolved_anchor(anchor)
    assert isinstance(ra, ResolvedAnchor)
    assert ra.char_range == (5, 25)
    assert len(ra.quads) == 2


def test_layout_page_annotations_adapter_returns_layout_result() -> None:
    from halfblood.document_processor import layout_page_annotations
    from halfblood.layout.engine import LayoutResult, NoteRequest
    from halfblood.models.legacy import AnnotationType
    from halfblood.models.rendering import ResolvedAnchor, SurfacePoint, SurfaceQuad

    class _FM:
        def measure(self, text: str, max_width: float, scale: float) -> tuple[float, float]:
            return (min(60.0, max_width), 14.0 * scale)

    anchor = ResolvedAnchor(
        char_range=(0, 10),
        quads=(
            SurfaceQuad(
                ul=SurfacePoint(x=100.0, y=350.0),
                ur=SurfacePoint(x=400.0, y=350.0),
                lr=SurfacePoint(x=400.0, y=364.0),
                ll=SurfacePoint(x=100.0, y=364.0),
            ),
        ),
    )
    req = NoteRequest(
        annotation_id="t1",
        source_locator="p:1",
        annotation_type=AnnotationType.CORRECTION,
        confidence=0.9,
        content="A note.",
        requested_placement="margin_right",
        anchor=anchor,
        render_seed=0,
    )
    doc = fitz.open()
    page = doc.new_page(width=_PAGE_W, height=_PAGE_H)
    result = layout_page_annotations(page, [req], [], _FM())
    assert isinstance(result, LayoutResult)


# ---------------------------------------------------------------------------
# P2-T8 fold-in — fitz_rect_from_surf inverse converter
# ---------------------------------------------------------------------------


def test_fitz_rect_from_surf_roundtrips_through_surf_rect_from_fitz() -> None:
    """fitz_rect_from_surf must be the exact inverse of surf_rect_from_fitz.

    This test fails against HEAD because fitz_rect_from_surf does not exist
    in halfblood.layout.anchors yet (P2-T8 adds it).
    """
    from halfblood.layout.anchors import fitz_rect_from_surf, surf_rect_from_fitz
    from halfblood.models.rendering import SurfaceRect

    original = fitz.Rect(10.5, 20.0, 300.0, 400.5)
    surf = surf_rect_from_fitz(original)
    assert isinstance(surf, SurfaceRect)

    recovered = fitz_rect_from_surf(surf)
    assert isinstance(recovered, fitz.Rect)
    assert recovered.x0 == pytest.approx(original.x0)
    assert recovered.y0 == pytest.approx(original.y0)
    assert recovered.x1 == pytest.approx(original.x1)
    assert recovered.y1 == pytest.approx(original.y1)


def test_fitz_rect_from_surf_quad_returns_bounding_rect() -> None:
    """fitz_rect_from_surf_quad must return the axis-aligned bounding box.

    This test fails against HEAD because fitz_rect_from_surf_quad does not
    exist in halfblood.layout.anchors yet (P2-T8 adds it).
    """
    from halfblood.layout.anchors import fitz_rect_from_surf_quad
    from halfblood.models.rendering import SurfacePoint, SurfaceQuad

    # An axis-aligned quad at (100, 300) to (400, 312).
    q = SurfaceQuad(
        ul=SurfacePoint(x=100.0, y=300.0),
        ur=SurfacePoint(x=400.0, y=300.0),
        lr=SurfacePoint(x=400.0, y=312.0),
        ll=SurfacePoint(x=100.0, y=312.0),
    )
    rect = fitz_rect_from_surf_quad(q)
    assert isinstance(rect, fitz.Rect)
    assert rect.x0 == pytest.approx(100.0)
    assert rect.y0 == pytest.approx(300.0)
    assert rect.x1 == pytest.approx(400.0)
    assert rect.y1 == pytest.approx(312.0)
