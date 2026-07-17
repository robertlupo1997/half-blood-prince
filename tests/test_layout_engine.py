"""P2-T7 — Measured occupancy-based layout engine.

Architecture §§5.3, 5.5, 5.9, 7.2.

Contract: ``run_layout`` sorts requests by (type_priority, -confidence, annotation_id),
places notes using per-side vertical occupancy, bounded shifting, side switching, scale
reduction, and safe skip. Every fallback/skip uses P2-T6 contract types only.

Test style: all tests use FixedMeasurer (deterministic, known bounds) and SurfaceRect
geometry — no fitz, no network, no real measurer. Per-annotation warnings live on
``ResolvedAnnotation.warnings``; result-level flags are on ``LayoutResult.degradation_flags``.

Discriminating check: see _NAIVE_PLACER and the inline discriminating-check comments for
proof that invariant tests are non-vacuous — they would fail against a naive center-at-target
implementation with no occupancy tracking, no priority sort, no skip logic.
"""

from __future__ import annotations

from halfblood.layout.engine import (
    LayoutConfig,
    LayoutResult,
    NoteRequest,
    run_layout,
)
from halfblood.models.annotations import Placement
from halfblood.models.legacy import AnnotationType
from halfblood.models.rendering import (
    AnchorWarningCode,
    DegradationFlag,
    ResolvedAnchor,
    SkipReason,
    SurfacePoint,
    SurfaceQuad,
    SurfaceRect,
)

# ---------------------------------------------------------------------------
# Shared geometry
# ---------------------------------------------------------------------------

_PAGE = SurfaceRect(x0=0.0, y0=0.0, x1=612.0, y1=792.0)

# Non-origin page: simulates a cropped/rotated page box where (0,0) is NOT top-left.
_SHIFTED_PAGE = SurfaceRect(x0=50.0, y0=100.0, x1=550.0, y1=700.0)

# Narrow page: both margins are < 40 pt (degenerate — body fills almost all width).
_NARROW_PAGE = SurfaceRect(x0=0.0, y0=0.0, x1=100.0, y1=792.0)
_NARROW_BODY = SurfaceRect(x0=5.0, y0=50.0, x1=95.0, y1=742.0)

# Standard body block used when we want to assert notes don't invade body text.
_BODY = SurfaceRect(x0=60.0, y0=72.0, x1=500.0, y1=720.0)

_DEFAULT_CFG = LayoutConfig()


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
    content: str = "A note.",
    placement: Placement = "margin_right",
    anchor: ResolvedAnchor | None = None,
    render_seed: int = 0,
    source_locator: str = "p:1",
) -> NoteRequest:
    if anchor is None:
        anchor = _anchor(100.0, 350.0, 400.0, 364.0)
    return NoteRequest(
        annotation_id=aid,
        annotation_type=annotation_type,
        confidence=confidence,
        content=content,
        requested_placement=placement,
        anchor=anchor,
        render_seed=render_seed,
        source_locator=source_locator,
    )


# ---------------------------------------------------------------------------
# Fake deterministic measurer
# ---------------------------------------------------------------------------

class FixedMeasurer:
    """Always returns (w, h) capped at max_width — deterministic, known bounds."""

    def __init__(self, w: float = 60.0, h: float = 14.0) -> None:
        self._w, self._h = w, h

    def measure(self, text: str, max_width: float, scale: float) -> tuple[float, float]:
        return (min(self._w, max_width), self._h * scale)


_FM = FixedMeasurer()


# ---------------------------------------------------------------------------
# Assertion helpers
# ---------------------------------------------------------------------------

def _placed_ids(result: LayoutResult) -> list[str]:
    return [a.annotation_id for a in result.placed]


def _skipped_ids(result: LayoutResult) -> list[str]:
    return [r.annotation_id for r in result.skipped]


def _rects_overlap(a: SurfaceRect, b: SurfaceRect, tol: float = 0.0) -> bool:
    return (
        a.x0 < b.x1 - tol
        and b.x0 < a.x1 - tol
        and a.y0 < b.y1 - tol
        and b.y0 < a.y1 - tol
    )


def _within(rect: SurfaceRect, page: SurfaceRect, tol: float = 0.5) -> bool:
    return (
        rect.x0 >= page.x0 - tol
        and rect.y0 >= page.y0 - tol
        and rect.x1 <= page.x1 + tol
        and rect.y1 <= page.y1 + tol
    )


# ---------------------------------------------------------------------------
# 1. Empty input
# ---------------------------------------------------------------------------


def test_empty_requests_produce_empty_result() -> None:
    result = run_layout([], _PAGE, [], _FM)
    assert result.placed == ()
    assert result.skipped == ()
    assert result.degradation_flags == ()


# ---------------------------------------------------------------------------
# 2. Layout result structure
# ---------------------------------------------------------------------------


def test_placed_annotation_has_note_box() -> None:
    result = run_layout([_req("a1")], _PAGE, [_BODY], _FM)
    assert result.placed, "Expected at least one placed annotation"
    for ann in result.placed:
        assert ann.note_box is not None, f"{ann.annotation_id} placed but note_box is None"
        assert isinstance(ann.note_box, SurfaceRect)


def test_all_annotations_either_placed_or_skipped() -> None:
    reqs = [_req(f"n{i}") for i in range(5)]
    result = run_layout(reqs, _PAGE, [], _FM)
    placed = set(_placed_ids(result))
    skipped = set(_skipped_ids(result))
    assert placed.isdisjoint(skipped), "IDs must not appear in both placed and skipped"
    assert placed | skipped == {r.annotation_id for r in reqs}, (
        "Every annotation must be placed or skipped"
    )


def test_placed_annotation_preserves_annotation_id_and_source_locator() -> None:
    req = _req("xyz", source_locator="ch:3/p:7")
    result = run_layout([req], _PAGE, [], _FM)
    placed_map = {a.annotation_id: a for a in result.placed}
    skipped_ids = _skipped_ids(result)
    assert "xyz" in placed_map or "xyz" in skipped_ids, "Annotation must appear in placed or skipped"
    if "xyz" in placed_map:
        assert placed_map["xyz"].source_locator == "ch:3/p:7"


def test_placed_annotation_preserves_requested_placement() -> None:
    req = _req("a1", placement="margin_right")
    result = run_layout([req], _PAGE, [], _FM)
    if result.placed:
        assert result.placed[0].requested_placement == "margin_right", (
            "requested_placement must be preserved even when resolved_placement differs"
        )


def test_layout_result_has_degradation_flags_field() -> None:
    result = run_layout([], _PAGE, [], _FM)
    assert hasattr(result, "degradation_flags")
    assert isinstance(result.degradation_flags, tuple)


# ---------------------------------------------------------------------------
# 3. Priority ordering
#
# NAIVE DISCRIMINATING CHECK: a naive placer preserving input order would place
# "correction-1" (listed first) before "warning-1", failing the ordering assertion.
# ---------------------------------------------------------------------------


def test_warning_placed_before_correction_regardless_of_input_order() -> None:
    reqs = [
        _req("correction-1", annotation_type=AnnotationType.CORRECTION, confidence=0.9),
        _req("warning-1", annotation_type=AnnotationType.WARNING, confidence=0.5),
    ]
    result = run_layout(reqs, _PAGE, [], _FM)
    ids = _placed_ids(result)
    assert "warning-1" in ids and "correction-1" in ids
    assert ids.index("warning-1") < ids.index("correction-1"), (
        "WARNING must be placed before CORRECTION regardless of input order and confidence"
    )


def test_high_confidence_placed_before_low_confidence_same_type() -> None:
    reqs = [
        _req("low-c", annotation_type=AnnotationType.INSIGHT, confidence=0.3),
        _req("high-c", annotation_type=AnnotationType.INSIGHT, confidence=0.9),
    ]
    result = run_layout(reqs, _PAGE, [], _FM)
    ids = _placed_ids(result)
    if "high-c" in ids and "low-c" in ids:
        assert ids.index("high-c") < ids.index("low-c"), (
            "Higher confidence must be placed first within the same annotation type"
        )


def test_stable_id_tiebreak_same_type_and_confidence() -> None:
    # Same type, same confidence → alphabetical annotation_id order must be stable.
    reqs = [
        _req("z-note", annotation_type=AnnotationType.INSIGHT, confidence=0.7),
        _req("a-note", annotation_type=AnnotationType.INSIGHT, confidence=0.7),
        _req("m-note", annotation_type=AnnotationType.INSIGHT, confidence=0.7),
    ]
    result = run_layout(reqs, _PAGE, [], _FM)
    ids = _placed_ids(result)
    placed_subset = [i for i in ids if i in {"a-note", "m-note", "z-note"}]
    assert placed_subset == sorted(placed_subset), (
        "Annotation IDs must be sorted ascending as the stable tiebreak"
    )


# ---------------------------------------------------------------------------
# 4. Page-bounds containment
#
# NAIVE DISCRIMINATING CHECK: naive centers note at target midpoint. Targets at
# y=0.0..1.0 or y=791.0..792.0 produce boxes outside the page (y=-6 or y=799);
# these assertions fail against naive.
# ---------------------------------------------------------------------------


def test_placed_notes_stay_within_page_bounds() -> None:
    reqs = [
        _req("top", anchor=_anchor(200.0, 0.0, 400.0, 1.0)),    # target AT top edge
        _req("bot", anchor=_anchor(200.0, 791.0, 400.0, 792.0)), # target AT bottom edge
        _req("mid", anchor=_anchor(100.0, 400.0, 400.0, 412.0)), # safe mid-page
    ]
    result = run_layout(reqs, _PAGE, [], _FM)
    for ann in result.placed:
        assert ann.note_box is not None
        assert _within(ann.note_box, _PAGE), (
            f"{ann.annotation_id}: note_box {ann.note_box} leaves page {_PAGE}"
        )


def test_non_origin_page_box_note_placed_right_of_target() -> None:
    # On a page starting at x=50, target at x=[100, 200]. The right margin is
    # x=(200, 550). A naive engine that assumes x0=0 may miscompute the margin.
    anchor = _anchor(100.0, 300.0, 200.0, 314.0)
    req = _req("a1", placement="margin_right", anchor=anchor)
    result = run_layout([req], _SHIFTED_PAGE, [], _FM)
    for ann in result.placed:
        assert ann.note_box is not None
        assert _within(ann.note_box, _SHIFTED_PAGE), (
            f"note_box {ann.note_box} leaves non-origin page {_SHIFTED_PAGE}"
        )
        if ann.resolved_placement == "margin_right":
            assert ann.note_box.x0 >= 200.0, (
                f"Right-margin note must start right of target x1=200, got x0={ann.note_box.x0}"
            )
            assert ann.note_box.x1 <= _SHIFTED_PAGE.x1 + 0.5, (
                f"Right-margin note must not exceed page x1={_SHIFTED_PAGE.x1}"
            )


# ---------------------------------------------------------------------------
# 5. Vertical non-overlap
#
# NAIVE DISCRIMINATING CHECK: naive centers all 5 notes at y≈357 (same target),
# all note_boxes are SurfaceRect(x=250..310, y=350..364), so all pairs overlap.
# The assertion below would fail for all i<j pairs.
# ---------------------------------------------------------------------------


def test_vertical_intervals_on_same_side_never_overlap() -> None:
    # Five notes all requesting right margin at the same vertical target.
    reqs = [
        _req(f"n{i}", anchor=_anchor(100.0, 360.0, 400.0, 374.0))
        for i in range(5)
    ]
    result = run_layout(reqs, _PAGE, [], _FM)
    right_boxes = [
        ann.note_box
        for ann in result.placed
        if ann.note_box is not None and ann.resolved_placement == "margin_right"
    ]
    tol = _DEFAULT_CFG.overlap_tolerance
    for i, a in enumerate(right_boxes):
        for j, b in enumerate(right_boxes):
            if i >= j:
                continue
            assert not _rects_overlap(a, b, tol=tol), (
                f"Vertical overlap between boxes {a} and {b} (tolerance={tol})"
            )


# ---------------------------------------------------------------------------
# 6. Side switching
# ---------------------------------------------------------------------------


def test_preferred_side_retained_when_right_margin_is_wide() -> None:
    # Target ends at x=300 on a 612-wide page → 302pt right margin, clearly usable.
    req = _req("a1", placement="margin_right", anchor=_anchor(100.0, 350.0, 300.0, 364.0))
    result = run_layout([req], _PAGE, [], _FM)
    if result.placed:
        ann = result.placed[0]
        assert ann.resolved_placement == "margin_right", (
            "Preferred right side must be retained when the right margin is wide"
        )
        assert not any(w.code == AnchorWarningCode.SIDE_SWITCHED for w in ann.warnings)


def test_target_hugging_right_edge_switches_to_left() -> None:
    # Target at x=[570, 610] on 612-wide page → right margin = 2pt (degenerate).
    # NAIVE: keeps requested placement even though it's off-page.
    req = _req("a1", placement="margin_right", anchor=_anchor(570.0, 350.0, 610.0, 364.0))
    result = run_layout([req], _PAGE, [_BODY], _FM)
    placed_map = {a.annotation_id: a for a in result.placed}
    if "a1" in placed_map:
        ann = placed_map["a1"]
        assert ann.resolved_placement == "margin_left", (
            "Must switch to left when right margin is degenerate"
        )
        assert any(w.code == AnchorWarningCode.SIDE_SWITCHED for w in ann.warnings), (
            "SIDE_SWITCHED warning required"
        )


def test_target_hugging_left_edge_switches_to_right() -> None:
    # Target at x=[2, 30] → left margin = 2pt (degenerate).
    req = _req("a1", placement="margin_left", anchor=_anchor(2.0, 350.0, 30.0, 364.0))
    result = run_layout([req], _PAGE, [_BODY], _FM)
    placed_map = {a.annotation_id: a for a in result.placed}
    if "a1" in placed_map:
        ann = placed_map["a1"]
        assert ann.resolved_placement == "margin_right"
        assert any(w.code == AnchorWarningCode.SIDE_SWITCHED for w in ann.warnings)


# ---------------------------------------------------------------------------
# 7. Shifting with SHIFTED warning
# ---------------------------------------------------------------------------


def test_note_shifted_from_preferred_slot_gets_warning() -> None:
    # Two notes with the same anchor. The second must shift; SHIFTED (or SIDE_SWITCHED)
    # warning must be attached to the second annotation.
    req_first = _req("first", anchor=_anchor(100.0, 350.0, 400.0, 364.0))
    req_second = _req("second", annotation_type=AnnotationType.INSIGHT,
                      anchor=_anchor(100.0, 352.0, 400.0, 366.0))
    # CORRECTION > INSIGHT in priority, so "first" is placed first.
    result = run_layout([req_second, req_first], _PAGE, [], _FM)
    placed_map = {a.annotation_id: a for a in result.placed}
    if "second" in placed_map:
        warning_codes = {w.code for w in placed_map["second"].warnings}
        assert warning_codes & {AnchorWarningCode.SHIFTED, AnchorWarningCode.SIDE_SWITCHED}, (
            "The shifted/second note must carry SHIFTED or SIDE_SWITCHED"
        )


# ---------------------------------------------------------------------------
# 8. Scale reduction
# ---------------------------------------------------------------------------


def test_scale_never_falls_below_configured_minimum() -> None:
    # A measurer that always returns a very tall note — forces the engine to
    # reduce scale, but never below min_scale.
    class ScaleTracker:
        def __init__(self) -> None:
            self.min_seen: float = float("inf")

        def measure(self, text: str, max_width: float, scale: float) -> tuple[float, float]:
            self.min_seen = min(self.min_seen, scale)
            return (min(60.0, max_width), 900.0 * scale)  # always too tall at scale=1

    tracker = ScaleTracker()
    cfg = LayoutConfig(min_scale=0.7)
    run_layout([_req("big")], _PAGE, [], tracker, config=cfg)
    if tracker.min_seen < float("inf"):
        assert tracker.min_seen >= cfg.min_scale - 1e-9, (
            f"Scale went to {tracker.min_seen}, below min_scale={cfg.min_scale}"
        )


def test_scale_reduction_produces_scale_reduced_warning() -> None:
    # Note too large at scale=1.0 but fits at reduced scale.
    class TwoPassMeasurer:
        def measure(self, text: str, max_width: float, scale: float) -> tuple[float, float]:
            if scale >= 1.0 - 1e-9:
                return (min(60.0, max_width), 900.0)  # too tall at full scale
            return (min(60.0, max_width), 14.0)         # fits at reduced scale

    result = run_layout([_req("a1")], _PAGE, [], TwoPassMeasurer())
    if result.placed:
        ann = result.placed[0]
        assert any(w.code == AnchorWarningCode.SCALE_REDUCED for w in ann.warnings), (
            "A note that required scale reduction must carry SCALE_REDUCED warning"
        )


# ---------------------------------------------------------------------------
# 9. inline / between_lines fallback
#
# NAIVE DISCRIMINATING CHECK: naive returns requested_placement unchanged, so
# resolved_placement == "inline"/"between_lines" — but a valid margin placement
# must be in ("margin_left", "margin_right").
# ---------------------------------------------------------------------------


def test_inline_request_falls_back_to_margin() -> None:
    # Dense body_occupancy blocks the inline slot → fallback to a margin.
    body = [SurfaceRect(x0=60.0, y0=72.0, x1=500.0, y1=720.0)]
    req = _req("a1", placement="inline", anchor=_anchor(100.0, 350.0, 400.0, 364.0))
    result = run_layout([req], _PAGE, body, _FM)
    placed_map = {a.annotation_id: a for a in result.placed}
    if "a1" in placed_map:
        ann = placed_map["a1"]
        assert ann.resolved_placement in ("margin_left", "margin_right"), (
            f"inline must fall back to a margin, got {ann.resolved_placement!r}"
        )
        assert ann.requested_placement == "inline", "requested_placement must be preserved"


def test_between_lines_request_falls_back_to_margin_when_no_gap() -> None:
    # Body occupancy from y=72 to y=720 covers the interline region around the target.
    body = [SurfaceRect(x0=60.0, y0=72.0, x1=500.0, y1=720.0)]
    req = _req("a1", placement="between_lines", anchor=_anchor(100.0, 350.0, 400.0, 364.0))
    result = run_layout([req], _PAGE, body, _FM)
    placed_map = {a.annotation_id: a for a in result.placed}
    if "a1" in placed_map:
        ann = placed_map["a1"]
        assert ann.resolved_placement in ("margin_left", "margin_right"), (
            f"between_lines must fall back to margin when no gap, got {ann.resolved_placement!r}"
        )
        assert ann.requested_placement == "between_lines"


# ---------------------------------------------------------------------------
# 10. Body occupancy respected
# ---------------------------------------------------------------------------


def test_note_does_not_invade_body_occupancy() -> None:
    req = _req("a1", anchor=_anchor(100.0, 350.0, 400.0, 364.0))
    result = run_layout([req], _PAGE, [_BODY], _FM)
    tol = _DEFAULT_CFG.overlap_tolerance
    for ann in result.placed:
        if ann.note_box is not None:
            assert not _rects_overlap(ann.note_box, _BODY, tol=tol), (
                f"Placed note {ann.note_box} overlaps body occupancy {_BODY}"
            )


# ---------------------------------------------------------------------------
# 11. Both-margins-degenerate → UNPLACEABLE skip
#
# NAIVE DISCRIMINATING CHECK: naive places all annotations (never produces a skip),
# so "a1" would be in placed_ids, failing the assert-in-skipped check.
# Also, the naive note_box would be near x=50, which is inside _NARROW_PAGE but
# outside any real margin — the "not off-page" check would pass, but the skip
# check would fail.
# ---------------------------------------------------------------------------


def test_both_margins_degenerate_yields_skip_not_off_page_geometry() -> None:
    req = _req("a1", anchor=_anchor(5.0, 350.0, 95.0, 364.0))
    result = run_layout([req], _NARROW_PAGE, [_NARROW_BODY], _FM)

    assert "a1" not in _placed_ids(result), "Degenerate note must NOT appear in placed"
    assert "a1" in _skipped_ids(result), "Both-margins-degenerate must yield a skip"

    # The placed list (for other annotations) must not contain off-page geometry.
    for ann in result.placed:
        if ann.note_box is not None:
            assert _within(ann.note_box, _NARROW_PAGE), (
                f"Off-page geometry detected: {ann.note_box}"
            )


def test_skip_record_has_unplaceable_reason() -> None:
    req = _req("a1", anchor=_anchor(5.0, 350.0, 95.0, 364.0))
    result = run_layout([req], _NARROW_PAGE, [_NARROW_BODY], _FM)
    skip_map = {r.annotation_id: r for r in result.skipped}
    if "a1" in skip_map:
        assert skip_map["a1"].reason == SkipReason.UNPLACEABLE


def test_skip_produces_note_skipped_unfittable_degradation_flag() -> None:
    req = _req("a1", anchor=_anchor(5.0, 350.0, 95.0, 364.0))
    result = run_layout([req], _NARROW_PAGE, [_NARROW_BODY], _FM)
    if "a1" in _skipped_ids(result):
        assert DegradationFlag.NOTE_SKIPPED_UNFITTABLE in result.degradation_flags, (
            "A skipped-unfittable note must set NOTE_SKIPPED_UNFITTABLE degradation flag"
        )


# ---------------------------------------------------------------------------
# 12. Determinism
# ---------------------------------------------------------------------------


def test_layout_is_deterministic() -> None:
    reqs = [
        _req("a1", anchor=_anchor(100.0, 200.0, 400.0, 214.0)),
        _req("a2", annotation_type=AnnotationType.WARNING,
             anchor=_anchor(100.0, 300.0, 400.0, 314.0)),
        _req("a3", annotation_type=AnnotationType.INSIGHT,
             anchor=_anchor(100.0, 400.0, 400.0, 414.0)),
    ]
    r1 = run_layout(reqs, _PAGE, [_BODY], _FM)
    r2 = run_layout(reqs, _PAGE, [_BODY], _FM)
    assert r1 == r2, "run_layout must return identical results for identical inputs"


# ---------------------------------------------------------------------------
# 13. Attempt-budget termination
# ---------------------------------------------------------------------------


def test_terminates_within_configured_attempt_budget() -> None:
    # Twenty notes at the same vertical anchor — more than 2 × budget.
    # Engine must terminate without looping indefinitely.
    cfg = LayoutConfig(attempt_budget=4)
    reqs = [
        _req(f"n{i}", anchor=_anchor(100.0, 350.0, 400.0, 364.0))
        for i in range(20)
    ]
    result = run_layout(reqs, _PAGE, [], _FM, config=cfg)
    placed = set(_placed_ids(result))
    skipped = set(_skipped_ids(result))
    all_ids = {r.annotation_id for r in reqs}
    assert placed | skipped == all_ids, (
        "All annotations must be accounted for within the attempt budget"
    )


# ---------------------------------------------------------------------------
# 14. Multi-quad anchor
# ---------------------------------------------------------------------------


def test_multi_quad_anchor_produces_valid_disposition() -> None:
    # Target spanning two lines — two quads. Engine must not crash.
    anchor = ResolvedAnchor(
        char_range=(0, 20),
        quads=(
            _q(100.0, 300.0, 400.0, 312.0),
            _q(100.0, 316.0, 300.0, 328.0),
        ),
    )
    req = _req("multi", anchor=anchor)
    result = run_layout([req], _PAGE, [], _FM)
    placed_ids = _placed_ids(result)
    skipped_ids = _skipped_ids(result)
    assert "multi" in placed_ids or "multi" in skipped_ids, (
        "multi-quad annotation must appear in placed or skipped"
    )
    if "multi" in placed_ids:
        ann = next(a for a in result.placed if a.annotation_id == "multi")
        assert ann.note_box is not None
        assert _within(ann.note_box, _PAGE)


# ---------------------------------------------------------------------------
# 15. Empty anchor (no quads)
# ---------------------------------------------------------------------------


def test_empty_quads_anchor_produces_valid_disposition() -> None:
    # ResolvedAnchor with no quads — EPUB case. Engine must not crash.
    anchor = ResolvedAnchor(char_range=(0, 0), quads=())
    req = _req("no-geom", anchor=anchor)
    result = run_layout([req], _PAGE, [], _FM)
    placed_ids = _placed_ids(result)
    skipped_ids = _skipped_ids(result)
    assert "no-geom" in placed_ids or "no-geom" in skipped_ids


# ---------------------------------------------------------------------------
# 16. Inline / between_lines success path (plan §5.3 "with AND without gaps")
# ---------------------------------------------------------------------------


def test_inline_request_succeeds_when_gap_is_free() -> None:
    # placement='inline', no body_occupancy → _try_inline finds free space above
    # the target and returns a real box; resolved_placement stays 'inline'.
    #
    # Discriminating: if _try_inline always returned None the engine would fall
    # back to margin placement and resolved_placement would be 'margin_right',
    # making the first assertion below fail.
    anchor = _anchor(100.0, 350.0, 400.0, 364.0)  # 300pt wide, y0=350 → 350pt above
    req = _req("inline-ok", placement="inline", anchor=anchor)
    result = run_layout([req], _PAGE, [], _FM)
    assert "inline-ok" in _placed_ids(result), "inline request with free gap must be placed"
    ann = next(a for a in result.placed if a.annotation_id == "inline-ok")
    assert ann.resolved_placement == "inline", (
        f"resolved_placement must be 'inline', got {ann.resolved_placement!r}"
    )
    assert ann.note_box is not None
    assert ann.note_box.y1 <= 350.0 + 1e-6, (
        f"note_box must sit above target y0=350; got note_box.y1={ann.note_box.y1}"
    )


def test_between_lines_request_succeeds_when_gap_is_free() -> None:
    # placement='between_lines', no body_occupancy → same success path as
    # 'inline'; resolved_placement stays 'between_lines'.
    #
    # Discriminating: if _try_inline always returned None the engine would fall
    # back to margin placement and resolved_placement would be 'margin_right'.
    anchor = _anchor(100.0, 350.0, 400.0, 364.0)
    req = _req("btw-ok", placement="between_lines", anchor=anchor)
    result = run_layout([req], _PAGE, [], _FM)
    assert "btw-ok" in _placed_ids(result), "between_lines request with free gap must be placed"
    ann = next(a for a in result.placed if a.annotation_id == "btw-ok")
    assert ann.resolved_placement == "between_lines", (
        f"resolved_placement must be 'between_lines', got {ann.resolved_placement!r}"
    )
    assert ann.note_box is not None
    assert ann.note_box.y1 <= 350.0 + 1e-6, (
        f"note_box must sit above target y0=350; got note_box.y1={ann.note_box.y1}"
    )
