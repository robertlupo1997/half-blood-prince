"""MP1b — margin discipline: true outer-column placement, zero body-word overlaps.

These tests drive the implementation from the outside:

  - Unit tests (no fitz) verify that ``run_layout`` uses true outer margins derived
    from ``body_columns`` rather than target-relative margins.
  - Integration tests verify that the PDF occupancy provider extracts body geometry
    and that the end-to-end layout produces zero note/body-word intersections on the
    7-note demo page.

All tests fail on HEAD: either because the new modules do not yet exist (ImportError)
or because ``run_layout`` does not yet accept ``body_columns``. They are intended to
be green only after the MP1b implementation is complete.

Non-tautology contract
----------------------
The zero-overlap test is paired with a minimum-placement floor (all 7 notes must be
placed) so that Codex cannot satisfy it by skipping every annotation.

The true-margin test is paired with a body-edge check (note_box.x0 >= body_col.x1)
so that a note placed at target.x1 + gap — the current HEAD behavior — fails even if
the engine happens to place it without overlap (which it wouldn't on a real page, but
a synthetic test must also guard against that shortcut).
"""

from __future__ import annotations

from pathlib import Path

import fitz
import pytest

from halfblood.documents.pdf_occupancy import (
    PdfTextLayerOccupancyProvider,
    _body_candidates,
    _infer_columns,
    _LineRun,
)
from halfblood.layout.engine import (
    LayoutConfig,
    NoteRequest,
    run_layout,
)
from halfblood.layout.occupancy import PageOccupancy, TextColumn
from halfblood.models.annotations import Placement
from halfblood.models.legacy import AnnotationType
from halfblood.models.rendering import (
    ResolvedAnchor,
    SurfacePoint,
    SurfaceQuad,
    SurfaceRect,
)

# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------

FIXTURES = Path(__file__).resolve().parent / "fixtures"
POTIONS_PDF = FIXTURES / "potions_textbook.pdf"

# Standard 8.5×11 page matching the potions fixture.
_PAGE = SurfaceRect(x0=0.0, y0=0.0, x1=612.0, y1=792.0)

# Body column observed in potions_textbook.pdf page 2 via get_text("words").
# Body runs from x≈72 to x≈538; right margin is ~74pt before the page edge.
_BODY_COL = TextColumn(x0=72.0, x1=538.0)

# Default config.
_CFG = LayoutConfig()


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------


def _q(x0: float, y0: float, x1: float, y1: float) -> SurfaceQuad:
    return SurfaceQuad(
        ul=SurfacePoint(x=x0, y=y0),
        ur=SurfacePoint(x=x1, y=y0),
        lr=SurfacePoint(x=x1, y=y1),
        ll=SurfacePoint(x=x0, y=y1),
    )


def _anchor(x0: float, y0: float, x1: float, y1: float) -> ResolvedAnchor:
    return ResolvedAnchor(char_range=(0, 10), quads=(_q(x0, y0, x1, y1),))


def _req(
    aid: str,
    *,
    annotation_type: AnnotationType = AnnotationType.CORRECTION,
    confidence: float = 0.9,
    content: str = "A test note.",
    placement: Placement = "margin_right",
    anchor: ResolvedAnchor | None = None,
    source_locator: str = "p:2",
) -> NoteRequest:
    if anchor is None:
        # Default: mid-line target ending at x=300, well inside the body column.
        anchor = _anchor(100.0, 350.0, 300.0, 364.0)
    return NoteRequest(
        annotation_id=aid,
        annotation_type=annotation_type,
        confidence=confidence,
        content=content,
        requested_placement=placement,
        anchor=anchor,
        render_seed=0,
        source_locator=source_locator,
    )


def _rects_overlap(a: SurfaceRect, b: SurfaceRect, tol: float = 2.0) -> bool:
    """Return True if a and b overlap beyond the tolerance on BOTH axes."""
    return (
        a.x0 < b.x1 - tol
        and b.x0 < a.x1 - tol
        and a.y0 < b.y1 - tol
        and b.y0 < a.y1 - tol
    )


class _FixedMeasurer:
    """Deterministic measurer: always 60×14 pt (capped at max_width)."""

    def measure(self, text: str, max_width: float, scale: float) -> tuple[float, float]:
        return (min(60.0, max_width), 14.0 * scale)


_FM = _FixedMeasurer()


# ---------------------------------------------------------------------------
# 1. TextColumn and PageOccupancy are importable
# ---------------------------------------------------------------------------


def test_textcolumn_has_x0_and_x1() -> None:
    col = TextColumn(x0=72.0, x1=538.0)
    assert col.x0 == 72.0
    assert col.x1 == 538.0


def test_pageoccupancy_fields() -> None:
    col = TextColumn(x0=72.0, x1=538.0)
    word = SurfaceRect(x0=100.0, y0=90.0, x1=160.0, y1=107.0)
    obs = SurfaceRect(x0=72.0, y0=50.0, x1=538.0, y1=60.0)
    occ = PageOccupancy(
        obstacles=(obs,),
        words=(word,),
        body_columns=(col,),
    )
    assert len(occ.obstacles) == 1
    assert len(occ.words) == 1
    assert len(occ.body_columns) == 1
    assert occ.confidence >= 0.0


# ---------------------------------------------------------------------------
# 2. True right-margin placement — note starts at body column edge, not target edge
#
# Discriminating: on HEAD, _margin_geometry returns note_x0 = target.x1 + gap = 310,
# so note_box.x0 == 310 < 538 → assertion fails.  After the fix, note_box.x0 >= 538.
# ---------------------------------------------------------------------------


def test_true_right_margin_starts_at_body_column_edge() -> None:
    # Target ends at x=300; body column right edge = 538.
    # Right-margin note must start at ≥538, NOT at 300+gap=310.
    anchor = _anchor(100.0, 350.0, 300.0, 364.0)
    req = _req("mid-right", placement="margin_right", anchor=anchor)
    result = run_layout(
        [req],
        _PAGE,
        [],
        _FM,
        config=_CFG,
        body_columns=(_BODY_COL,),
    )
    placed = {a.annotation_id: a for a in result.placed}
    skipped = {r.annotation_id for r in result.skipped}

    # The note must be placed (not skipped), and the right margin has ~74pt.
    assert "mid-right" in placed, (
        f"Note must be placed; margin has ~74pt.  skipped={skipped}"
    )
    note_box = placed["mid-right"].note_box
    assert note_box is not None
    assert note_box.x0 >= _BODY_COL.x1 - 1.0, (
        f"Right-margin note must start at or past body column edge "
        f"x1={_BODY_COL.x1}, got note_box.x0={note_box.x0:.2f}.  "
        f"(HEAD behavior would give ~310, i.e. target.x1+gap.)"
    )


def test_true_left_margin_ends_at_body_column_edge() -> None:
    # Target starts at x=300; body column left edge = 72.
    # Left-margin note must end at ≤72, NOT at 300-gap=290.
    anchor = _anchor(300.0, 350.0, 500.0, 364.0)
    req = _req("mid-left", placement="margin_left", anchor=anchor)
    result = run_layout(
        [req],
        _PAGE,
        [],
        _FM,
        config=_CFG,
        body_columns=(_BODY_COL,),
    )
    placed = {a.annotation_id: a for a in result.placed}
    skipped = {r.annotation_id for r in result.skipped}

    assert "mid-left" in placed, (
        f"Note must be placed; left margin has ~72pt.  skipped={skipped}"
    )
    note_box = placed["mid-left"].note_box
    assert note_box is not None
    assert note_box.x1 <= _BODY_COL.x0 + 1.0, (
        f"Left-margin note must end at or before body column edge "
        f"x0={_BODY_COL.x0}, got note_box.x1={note_box.x1:.2f}.  "
        f"(HEAD behavior would give ~290, i.e. target.x0-gap.)"
    )


# ---------------------------------------------------------------------------
# 3. Two-column page — outer margins only, never the gutter
#
# A two-column page has two body columns.  Notes should land in the outer
# margins (before left column or after right column), NOT in the inter-column
# gutter.  On HEAD, the engine uses target-relative margins and may place the
# note in the gutter; after the fix it must use the global body envelope.
# ---------------------------------------------------------------------------


def test_two_column_page_places_notes_in_outer_margins_not_gutter() -> None:
    # Two columns: left [60, 260], right [310, 510].  Gutter: [260, 310].
    # Page: 0-612, so left outer margin [0, 60] and right outer margin [510, 612].
    left_col = TextColumn(x0=60.0, x1=260.0)
    right_col = TextColumn(x0=310.0, x1=510.0)
    page = SurfaceRect(x0=0.0, y0=0.0, x1=612.0, y1=792.0)

    # Target is in the right body column.
    anchor = _anchor(350.0, 200.0, 450.0, 215.0)
    req = _req("col-right", placement="margin_right", anchor=anchor)

    result = run_layout(
        [req],
        page,
        [],
        _FM,
        config=_CFG,
        body_columns=(left_col, right_col),
    )
    placed = {a.annotation_id: a for a in result.placed}
    skipped = {r.annotation_id for r in result.skipped}

    if "col-right" in placed:
        nb = placed["col-right"].note_box
        assert nb is not None
        # Must be in the right outer margin (>=510) or left outer margin (<=60).
        # NOT in the gutter [260..310] and NOT in either body column.
        in_right_outer = nb.x0 >= right_col.x1 - 1.0
        in_left_outer = nb.x1 <= left_col.x0 + 1.0
        assert in_right_outer or in_left_outer, (
            f"Two-column note must land in an outer margin, not the gutter.  "
            f"note_box={nb}, right_col.x1={right_col.x1}, left_col.x0={left_col.x0}"
        )
    else:
        # If skipped, the outer margins must genuinely be too narrow.
        assert "col-right" in skipped


# ---------------------------------------------------------------------------
# 4. Narrow outer margin — shrink or skip, never overlap body
#
# When the outer margin is narrower than margin_min_width, the engine must
# either shrink the note (if it fits at min_scale) or skip it.  In neither
# case may the note_box overlap the body_occupancy.
# ---------------------------------------------------------------------------


def test_narrow_outer_margin_shrinks_or_skips_never_overlaps_body() -> None:
    # Body column fills almost the full width; right outer margin is only 15pt.
    # min_margin_width defaults to 40pt, so right margin is too narrow.
    narrow_col = TextColumn(x0=60.0, x1=597.0)  # 15pt right, 60pt left
    page = SurfaceRect(x0=0.0, y0=0.0, x1=612.0, y1=792.0)
    body_occ = [SurfaceRect(x0=60.0, y0=72.0, x1=597.0, y1=720.0)]
    anchor = _anchor(200.0, 350.0, 400.0, 364.0)
    req = _req("narrow-right", placement="margin_right", anchor=anchor)

    result = run_layout(
        [req],
        page,
        body_occ,
        _FM,
        config=_CFG,
        body_columns=(narrow_col,),
    )

    placed = {a.annotation_id: a for a in result.placed}
    if "narrow-right" in placed:
        nb = placed["narrow-right"].note_box
        assert nb is not None
        # Must not overlap the body occupancy rectangle.
        for bo in body_occ:
            assert not _rects_overlap(nb, bo, tol=1.0), (
                f"Placed note {nb} overlaps body occupancy {bo} in narrow-margin case"
            )
    # If skipped, that is also acceptable (shrink-or-skip policy).


# ---------------------------------------------------------------------------
# 5. Headers and footers are NOT body columns but ARE obstacles
#
# The occupancy provider must exclude isolated top/bottom lines and recurring
# headers/footers from column estimation while still reporting them as obstacles.
# We test this indirectly: if a page's only wide block is a header/footer, the
# resulting occupancy should report zero body_columns or low confidence, and the
# engine should fail-closed (skip) rather than misuse the header as a column.
# ---------------------------------------------------------------------------


def test_pageoccupancy_accepts_zero_body_columns_with_low_confidence() -> None:
    # A PageOccupancy with no body_columns and low confidence should be constructable.
    # The engine must fail-closed for such pages: notes should be skipped, not placed
    # in a wrong margin derived from header/footer geometry.
    occ = PageOccupancy(
        obstacles=(SurfaceRect(x0=72.0, y0=30.0, x1=540.0, y1=50.0),),
        words=(SurfaceRect(x0=100.0, y0=30.0, x1=200.0, y1=50.0),),
        body_columns=(),
        confidence=0.0,
    )
    assert occ.body_columns == ()
    assert occ.confidence == 0.0


# ---------------------------------------------------------------------------
# 6. Priority preserved with body_columns
#
# WARNING must still be placed before CORRECTION when body_columns are supplied.
# ---------------------------------------------------------------------------


def test_priority_preserved_with_body_columns() -> None:
    reqs = [
        _req("correction-1", annotation_type=AnnotationType.CORRECTION, confidence=0.9),
        _req("warning-1", annotation_type=AnnotationType.WARNING, confidence=0.5),
    ]
    result = run_layout(reqs, _PAGE, [], _FM, config=_CFG, body_columns=(_BODY_COL,))
    placed_ids = [a.annotation_id for a in result.placed]
    assert "warning-1" in placed_ids and "correction-1" in placed_ids
    assert placed_ids.index("warning-1") < placed_ids.index("correction-1"), (
        "WARNING must be placed before CORRECTION regardless of confidence when columns provided"
    )


# ---------------------------------------------------------------------------
# 7. Determinism with body_columns
#
# Two identical calls must produce identical results.
# ---------------------------------------------------------------------------


def test_determinism_with_body_columns() -> None:
    reqs = [
        _req(f"n{i}", confidence=0.5 + i * 0.05)
        for i in range(4)
    ]
    r1 = run_layout(reqs, _PAGE, [], _FM, config=_CFG, body_columns=(_BODY_COL,))
    r2 = run_layout(reqs, _PAGE, [], _FM, config=_CFG, body_columns=(_BODY_COL,))
    assert [a.annotation_id for a in r1.placed] == [a.annotation_id for a in r2.placed]
    assert [a.annotation_id for a in r1.skipped] == [a.annotation_id for a in r2.skipped]
    for a1, a2 in zip(r1.placed, r2.placed, strict=True):
        assert a1.note_box == a2.note_box


# ---------------------------------------------------------------------------
# 8. PdfTextLayerOccupancyProvider is importable and extracts sane geometry
# ---------------------------------------------------------------------------


def test_pdf_occupancy_provider_extracts_body_columns() -> None:
    """Provider must identify at least one body column on a normal content page."""
    doc = fitz.open(str(POTIONS_PDF))
    try:
        page = doc[1]  # page 2, rich body text
        provider = PdfTextLayerOccupancyProvider()
        occ = provider.extract(page)
    finally:
        doc.close()

    assert len(occ.body_columns) >= 1, (
        "Provider must detect at least one body column on a normal content page"
    )
    assert len(occ.obstacles) > 0, "Provider must emit at least some obstacles"
    assert occ.confidence > 0.0, "Provider must report positive confidence for this page"

    # The detected column must encompass the known body region on this fixture.
    all_x1 = max(col.x1 for col in occ.body_columns)
    all_x0 = min(col.x0 for col in occ.body_columns)
    # Body text on page 2 runs from ~72 to ~538.
    assert all_x0 <= 80.0, f"Expected leftmost column edge near 72, got {all_x0}"
    assert all_x1 >= 520.0, f"Expected rightmost column edge near 538, got {all_x1}"


def test_pdf_occupancy_provider_right_margin_is_past_body_column() -> None:
    """Right outer margin must be on the other side of the body column."""
    doc = fitz.open(str(POTIONS_PDF))
    try:
        page = doc[1]
        # Capture page geometry before closing the document.
        page_x1 = float(page.rect.x1)
        provider = PdfTextLayerOccupancyProvider()
        occ = provider.extract(page)
    finally:
        doc.close()

    if not occ.body_columns:
        pytest.skip("No body columns detected — separate test")

    rightmost = max(col.x1 for col in occ.body_columns)
    right_margin = page_x1 - rightmost
    assert right_margin >= 40.0, (
        f"Right outer margin must be at least 40pt (min_margin_width); "
        f"body right={rightmost:.1f}, page right={page_x1:.1f}, margin={right_margin:.1f}"
    )


# ---------------------------------------------------------------------------
# 9. 7-note demo — all 7 placed AND zero body-word overlaps
#
# This is the headline acceptance criterion: notes must land in the true
# outer right margin (~74pt strip on the potions fixture), never over body text.
#
# Discriminating (advisor criterion §2):
#   - "all 7 placed" floor prevents Codex from satisfying zero-overlap by skipping.
#   - "zero body-word overlap" prevents Codex from satisfying the floor by placing
#     notes anywhere (including over text).
#   - On HEAD: engine uses target-relative placement → notes land mid-body → assertion
#     fails (or ImportError if new modules don't exist yet).
#
# The 7 targets are mid-line words on page 2 of potions_textbook.pdf (0-indexed page 1).
# Their x1 values (200–430) are all well inside the body column (x1≈538), so the current
# target-relative right-margin note (starting at x1+10) would overlap subsequent words.
# ---------------------------------------------------------------------------

# Hardcoded mid-line word positions on page 2 (potions_textbook.pdf, 0-indexed page 1).
# Measured via page.get_text("words").  These are stable across the committed fixture.
_DEMO_TARGETS: list[tuple[str, float, float, float, float]] = [
    # (label,      x0,    y0,     x1,    y1)
    ("powerful",   305.6, 92.2,  347.1, 107.3),
    ("sleeping",   350.2, 92.2,  391.1, 107.3),
    ("profound",   248.7, 107.2, 292.1, 122.3),
    ("examination",342.8, 122.2, 402.1, 137.3),
    ("simmer",     233.4, 265.2, 269.4, 280.3),
    ("measures",   275.6, 337.2, 326.9, 352.3),
    ("exactly",    184.5, 352.2, 218.7, 367.3),
]

assert len(_DEMO_TARGETS) == 7, "Demo must have exactly 7 targets"


def test_7_note_demo_all_placed() -> None:
    """All 7 demo notes must be placed — failing this means the engine skipped instead of fixed."""
    doc = fitz.open(str(POTIONS_PDF))
    try:
        page = doc[1]
        provider = PdfTextLayerOccupancyProvider()
        occ = provider.extract(page)

        page_surf = SurfaceRect(
            x0=float(page.rect.x0),
            y0=float(page.rect.y0),
            x1=float(page.rect.x1),
            y1=float(page.rect.y1),
        )
        requests = [
            NoteRequest(
                annotation_id=label,
                source_locator="p:2",
                annotation_type=AnnotationType.WARNING,
                confidence=0.9,
                content=f"Note about {label}.",
                requested_placement="margin_right",
                anchor=_anchor(x0, y0, x1, y1),
                render_seed=0,
            )
            for (label, x0, y0, x1, y1) in _DEMO_TARGETS
        ]

        result = run_layout(
            requests,
            page_surf,
            list(occ.obstacles),
            _FM,
            config=_CFG,
            body_columns=occ.body_columns,
        )
    finally:
        doc.close()

    placed_ids = {a.annotation_id for a in result.placed}
    skipped_ids = {r.annotation_id for r in result.skipped}
    assert len(result.placed) == 7, (
        f"All 7 demo notes must be placed; placed={placed_ids}, skipped={skipped_ids}"
    )


def test_7_note_demo_zero_body_word_overlaps() -> None:
    """No placed note box must intersect a body word on page 2 of the potions fixture.

    This is the headline metric for MP1b.  On HEAD (target-relative placement),
    3 of 7 notes ride over 4-6 body words each.  After the fix, all notes land in
    the true right margin (~74pt) and the overlap count must be 0.
    """
    doc = fitz.open(str(POTIONS_PDF))
    try:
        page = doc[1]
        provider = PdfTextLayerOccupancyProvider()
        occ = provider.extract(page)

        page_surf = SurfaceRect(
            x0=float(page.rect.x0),
            y0=float(page.rect.y0),
            x1=float(page.rect.x1),
            y1=float(page.rect.y1),
        )
        requests = [
            NoteRequest(
                annotation_id=label,
                source_locator="p:2",
                annotation_type=AnnotationType.WARNING,
                confidence=0.9,
                content=f"Note about {label}.",
                requested_placement="margin_right",
                anchor=_anchor(x0, y0, x1, y1),
                render_seed=0,
            )
            for (label, x0, y0, x1, y1) in _DEMO_TARGETS
        ]

        result = run_layout(
            requests,
            page_surf,
            list(occ.obstacles),
            _FM,
            config=_CFG,
            body_columns=occ.body_columns,
        )

        # Collect every body word as a SurfaceRect.
        raw_words = page.get_text("words")
        word_rects = [
            SurfaceRect(x0=float(w[0]), y0=float(w[1]), x1=float(w[2]), y1=float(w[3]))
            for w in raw_words
        ]
    finally:
        doc.close()

    overlapping: list[tuple[str, SurfaceRect, SurfaceRect]] = []
    for ann in result.placed:
        nb = ann.note_box
        if nb is None:
            continue
        for wr in word_rects:
            if _rects_overlap(nb, wr, tol=2.0):
                overlapping.append((ann.annotation_id, nb, wr))

    assert len(overlapping) == 0, (
        f"Expected 0 note/body-word overlaps; found {len(overlapping)}:\n"
        + "\n".join(
            f"  {aid}: note={nb}, word={wr}"
            for aid, nb, wr in overlapping[:10]  # cap output
        )
    )


# ---------------------------------------------------------------------------
# 12. Multi-line running headers/footers must not inflate body columns
#
# White-box tests of the column-inference furniture filter (finding MP1b-4).
# ``_body_candidates`` currently only excludes *single-line* isolated blocks in
# the top/bottom 8% band, so a two-line running header that shares the body's
# left edge but runs wider leaks its right edge into the inferred body column.
# The fix must exclude a block only when the WHOLE block sits inside the band
# (never over-excluding a body block that merely dips into it).
# ---------------------------------------------------------------------------

# Letter page; header band is the top 8% → y-center < 792 * 0.08 ≈ 63.36.
_HF_PAGE = fitz.Rect(0.0, 0.0, 612.0, 792.0)


def _run(x0: float, y0: float, x1: float, y1: float, block: int, line: int) -> _LineRun:
    return _LineRun(
        rect=SurfaceRect(x0=x0, y0=y0, x1=x1, y1=y1),
        block_no=block,
        line_no=line,
    )


def test_multiline_running_header_does_not_inflate_body_column() -> None:
    # Two-line running header (block 0), both lines fully inside the top band,
    # left-aligned with the body (x0=100) but running wider (x1=560).
    header = [
        _run(100.0, 8.0, 560.0, 20.0, block=0, line=0),   # center 14 < 63.36
        _run(100.0, 24.0, 560.0, 36.0, block=0, line=1),  # center 30 < 63.36
    ]
    # Six-line body block (block 1), narrower (x1=400), well below the band.
    body = [
        _run(100.0, 120.0 + i * 20.0, 400.0, 132.0 + i * 20.0, block=1, line=i)
        for i in range(6)
    ]
    columns, _confidence = _infer_columns(
        _body_candidates(header + body, _HF_PAGE), _HF_PAGE
    )
    assert columns, "expected an inferred body column"
    assert max(col.x1 for col in columns) <= 420.0, (
        "multi-line running header leaked its right edge into the body column: "
        f"{columns}"
    )


def test_body_block_dipping_into_header_band_is_not_excluded() -> None:
    # A single body block (block 0) whose first line sits high (center 55, inside
    # the top band) but which continues well into the body. It must NOT be
    # dropped as furniture — only blocks entirely within the band are furniture.
    body = [_run(100.0, 50.0, 400.0, 60.0, block=0, line=0)]  # center 55 < 63.36
    body += [
        _run(100.0, 120.0 + i * 20.0, 400.0, 132.0 + i * 20.0, block=0, line=i + 1)
        for i in range(5)
    ]
    columns, _confidence = _infer_columns(
        _body_candidates(body, _HF_PAGE), _HF_PAGE
    )
    assert columns, "body block dipping into the header band must still yield a column"
    assert any(abs(col.x1 - 400.0) < 5.0 for col in columns), (
        f"expected a body column ending near x1=400; got {columns}"
    )
