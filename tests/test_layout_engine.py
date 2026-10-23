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

import sys
from pathlib import Path

import pytest

from halfblood.layout.engine import (
    LayoutConfig,
    LayoutResult,
    NoteRequest,
    run_layout,
)
from halfblood.layout.occupancy import TextColumn
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

# Body columns matching _BODY. Since MP1c the engine fails closed for margin
# placement unless real column geometry is supplied: right strip = (510, 604)
# → width 94; left strip = (8, 50) → width 42; both ≥ margin_min_width (40).
_BODY_COLS = (TextColumn(x0=60.0, x1=500.0),)

# Columns on _NARROW_PAGE where BOTH column-derived strips are degenerate
# (right = (105, 92), left = (8, -5), both < 40) → both-margins-degenerate skip.
_NARROW_COLS = (TextColumn(x0=5.0, x1=95.0),)

# Columns on _SHIFTED_PAGE (x0=50..x1=550): right strip = (410, 542) → width 132.
_SHIFTED_COLS = (TextColumn(x0=100.0, x1=400.0),)

# Columns whose RIGHT strip is degenerate on _PAGE (col.x1=560 → right strip
# = (570, 604) → width 34 < 40, not a candidate) while the left strip
# = (8, 50) → width 42 remains usable → forces a column-driven side switch.
_SWITCH_COLS = (TextColumn(x0=60.0, x1=560.0),)

# Mirror: LEFT strip degenerate on _PAGE (col.x0=40 → left strip = (8, 30) →
# width 22 < 40) while the right strip = (510, 604) → width 94 is usable.
_SWITCH_COLS_LEFT = (TextColumn(x0=40.0, x1=500.0),)

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
# 1b. Fail-closed when body columns can't be inferred (MP1c)
#
# Without inferred columns the engine cannot know where the true outer margin
# is, so margin placement must SKIP rather than fall back to a target-relative
# margin. Inline placement is target-local and is exempt from this rule.
# ---------------------------------------------------------------------------


def test_margin_request_without_columns_fails_closed() -> None:
    req = _req("a1", placement="margin_right")
    result = run_layout([req], _PAGE, [], _FM)  # no body_columns
    assert "a1" not in _placed_ids(result), "margin note must not be placed without columns"
    assert "a1" in _skipped_ids(result), "margin note must be skipped without columns"
    skip = {r.annotation_id: r for r in result.skipped}["a1"]
    assert skip.reason == SkipReason.UNPLACEABLE
    assert DegradationFlag.NOTE_SKIPPED_UNFITTABLE in result.degradation_flags


def test_inline_request_without_columns_still_places_inline() -> None:
    # The fail-closed rule is margin-only: inline/between_lines placement is
    # target-local and does not depend on column geometry, so it must still place.
    req = _req("inline-ok", placement="inline", anchor=_anchor(100.0, 350.0, 400.0, 364.0))
    result = run_layout([req], _PAGE, [], _FM)  # no body_columns
    assert "inline-ok" in _placed_ids(result), "inline placement must survive without columns"
    ann = next(a for a in result.placed if a.annotation_id == "inline-ok")
    assert ann.resolved_placement == "inline"


def test_inline_request_fails_then_no_columns_skips_unplaceable() -> None:
    # When the inline slot itself is unavailable (anchor near the top of the page
    # means the note box would fall above y=0) AND no body_columns are supplied,
    # the fail-closed guard must skip the note UNPLACEABLE rather than silently
    # falling back to a target-relative margin.
    req = _req("inline-fail", placement="inline", anchor=_anchor(100.0, 10.0, 400.0, 24.0))
    result = run_layout([req], _PAGE, [], _FM)  # no body_columns; inline slot off-page
    assert "inline-fail" not in _placed_ids(result), "inline must not be placed when slot is off-page"
    assert "inline-fail" in _skipped_ids(result), "must be skipped after inline fails + no columns"
    skip = {r.annotation_id: r for r in result.skipped}["inline-fail"]
    assert skip.reason == SkipReason.UNPLACEABLE
    assert DegradationFlag.NOTE_SKIPPED_UNFITTABLE in result.degradation_flags


# ---------------------------------------------------------------------------
# 2. Layout result structure
# ---------------------------------------------------------------------------


def test_placed_annotation_has_note_box() -> None:
    result = run_layout([_req("a1")], _PAGE, [_BODY], _FM, body_columns=_BODY_COLS)
    assert result.placed, "Expected at least one placed annotation"
    for ann in result.placed:
        assert ann.note_box is not None, f"{ann.annotation_id} placed but note_box is None"
        assert isinstance(ann.note_box, SurfaceRect)


def test_all_annotations_either_placed_or_skipped() -> None:
    reqs = [_req(f"n{i}") for i in range(5)]
    result = run_layout(reqs, _PAGE, [], _FM, body_columns=_BODY_COLS)
    placed = set(_placed_ids(result))
    skipped = set(_skipped_ids(result))
    assert placed.isdisjoint(skipped), "IDs must not appear in both placed and skipped"
    assert placed | skipped == {r.annotation_id for r in reqs}, (
        "Every annotation must be placed or skipped"
    )


def test_placed_annotation_preserves_annotation_id_and_source_locator() -> None:
    req = _req("xyz", source_locator="ch:3/p:7")
    result = run_layout([req], _PAGE, [], _FM, body_columns=_BODY_COLS)
    placed_map = {a.annotation_id: a for a in result.placed}
    assert "xyz" in placed_map, "a single note with usable margins must be placed"
    assert placed_map["xyz"].source_locator == "ch:3/p:7"


def test_placed_annotation_preserves_requested_placement() -> None:
    req = _req("a1", placement="margin_right")
    result = run_layout([req], _PAGE, [], _FM, body_columns=_BODY_COLS)
    assert result.placed
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
    result = run_layout(reqs, _PAGE, [], _FM, body_columns=_BODY_COLS)
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
    result = run_layout(reqs, _PAGE, [], _FM, body_columns=_BODY_COLS)
    ids = _placed_ids(result)
    assert "high-c" in ids and "low-c" in ids
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
    result = run_layout(reqs, _PAGE, [], _FM, body_columns=_BODY_COLS)
    ids = _placed_ids(result)
    placed_subset = [i for i in ids if i in {"a-note", "m-note", "z-note"}]
    assert placed_subset, "the tiebreak notes must actually place"
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
    result = run_layout(reqs, _PAGE, [], _FM, body_columns=_BODY_COLS)
    assert result.placed, "edge-anchored notes must place within the page"
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
    result = run_layout([req], _SHIFTED_PAGE, [], _FM, body_columns=_SHIFTED_COLS)
    assert result.placed, "note must place in the shifted-page right margin"
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
    result = run_layout(reqs, _PAGE, [], _FM, body_columns=_BODY_COLS)
    right_boxes = [
        ann.note_box
        for ann in result.placed
        if ann.note_box is not None and ann.resolved_placement == "margin_right"
    ]
    assert len(right_boxes) >= 2, "need multiple right-margin notes to test non-overlap"
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
    result = run_layout([req], _PAGE, [], _FM, body_columns=_BODY_COLS)
    assert result.placed
    ann = result.placed[0]
    assert ann.resolved_placement == "margin_right", (
        "Preferred right side must be retained when the right margin is wide"
    )
    assert not any(w.code == AnchorWarningCode.SIDE_SWITCHED for w in ann.warnings)


def test_narrow_preferred_right_margin_switches_to_left() -> None:
    # MP1c: side switching is driven by the COLUMN-derived margin, not the target
    # position. _SWITCH_COLS makes the right strip degenerate (width 34 < 40) while
    # the left strip (width 42) is usable, so a margin_right request switches left.
    req = _req("a1", placement="margin_right", anchor=_anchor(100.0, 350.0, 400.0, 364.0))
    result = run_layout([req], _PAGE, [_BODY], _FM, body_columns=_SWITCH_COLS)
    assert "a1" in _placed_ids(result), "note must place on the usable left side"
    ann = {a.annotation_id: a for a in result.placed}["a1"]
    assert ann.resolved_placement == "margin_left", (
        "Must switch to left when the right column margin is too narrow"
    )
    assert any(w.code == AnchorWarningCode.SIDE_SWITCHED for w in ann.warnings), (
        "SIDE_SWITCHED warning required"
    )


def test_narrow_preferred_left_margin_switches_to_right() -> None:
    # Mirror: _SWITCH_COLS_LEFT makes the left strip degenerate (width 22 < 40)
    # while the right strip (width 94) is usable, so a margin_left request switches.
    req = _req("a1", placement="margin_left", anchor=_anchor(100.0, 350.0, 400.0, 364.0))
    result = run_layout([req], _PAGE, [_BODY], _FM, body_columns=_SWITCH_COLS_LEFT)
    assert "a1" in _placed_ids(result), "note must place on the usable right side"
    ann = {a.annotation_id: a for a in result.placed}["a1"]
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
    result = run_layout([req_second, req_first], _PAGE, [], _FM, body_columns=_BODY_COLS)
    placed_map = {a.annotation_id: a for a in result.placed}
    assert "second" in placed_map, "the second (shifted) note must place"
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
    run_layout([_req("big")], _PAGE, [], tracker, config=cfg, body_columns=_BODY_COLS)
    assert tracker.min_seen < float("inf"), "the measurer must run during margin placement"
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

    result = run_layout([_req("a1")], _PAGE, [], TwoPassMeasurer(), body_columns=_BODY_COLS)
    assert result.placed
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
    result = run_layout([req], _PAGE, body, _FM, body_columns=_BODY_COLS)
    placed_map = {a.annotation_id: a for a in result.placed}
    assert "a1" in placed_map, "inline must fall back to a margin when the gap is blocked"
    ann = placed_map["a1"]
    assert ann.resolved_placement in ("margin_left", "margin_right"), (
        f"inline must fall back to a margin, got {ann.resolved_placement!r}"
    )
    assert ann.requested_placement == "inline", "requested_placement must be preserved"


def test_between_lines_request_falls_back_to_margin_when_no_gap() -> None:
    # Body occupancy from y=72 to y=720 covers the interline region around the target.
    body = [SurfaceRect(x0=60.0, y0=72.0, x1=500.0, y1=720.0)]
    req = _req("a1", placement="between_lines", anchor=_anchor(100.0, 350.0, 400.0, 364.0))
    result = run_layout([req], _PAGE, body, _FM, body_columns=_BODY_COLS)
    placed_map = {a.annotation_id: a for a in result.placed}
    assert "a1" in placed_map, "between_lines must fall back to a margin when no gap"
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
    result = run_layout([req], _PAGE, [_BODY], _FM, body_columns=_BODY_COLS)
    assert result.placed, "note must place (in the margin, outside the body) to test non-invasion"
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
    result = run_layout([req], _NARROW_PAGE, [_NARROW_BODY], _FM, body_columns=_NARROW_COLS)

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
    result = run_layout([req], _NARROW_PAGE, [_NARROW_BODY], _FM, body_columns=_NARROW_COLS)
    skip_map = {r.annotation_id: r for r in result.skipped}
    assert "a1" in skip_map, "both-margins-degenerate note must be skipped"
    assert skip_map["a1"].reason == SkipReason.UNPLACEABLE


def test_skip_produces_note_skipped_unfittable_degradation_flag() -> None:
    req = _req("a1", anchor=_anchor(5.0, 350.0, 95.0, 364.0))
    result = run_layout([req], _NARROW_PAGE, [_NARROW_BODY], _FM, body_columns=_NARROW_COLS)
    assert "a1" in _skipped_ids(result)
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
    r1 = run_layout(reqs, _PAGE, [_BODY], _FM, body_columns=_BODY_COLS)
    r2 = run_layout(reqs, _PAGE, [_BODY], _FM, body_columns=_BODY_COLS)
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
    result = run_layout(reqs, _PAGE, [], _FM, config=cfg, body_columns=_BODY_COLS)
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
    result = run_layout([req], _PAGE, [], _FM, body_columns=_BODY_COLS)
    placed_ids = _placed_ids(result)
    # With usable columns the multi-quad target places deterministically.
    assert "multi" in placed_ids, "multi-quad annotation must place with usable columns"
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


# ---------------------------------------------------------------------------
# 17. P3-S1 — Greedy-seam characterization (drift-detectors, PASS before & after)
# ---------------------------------------------------------------------------
#
# These tests pin the EXACT output of ``run_layout`` on a dense 6-note, two-column
# fixture.  They are characterization tests (drift-detectors) that MUST PASS on
# current HEAD *and* after the P3-S1 greedy-seam extraction refactor.  They are
# intentionally NOT red tests; the "confirm they fail" step is waived for this task
# because the refactor is zero-behavior-change (noted in the P3-S1 report).
#
# Expectation built by running commit 65c3752 (HEAD at time of authoring) on
# 2026-07-21 and pinning the output verbatim.  See capture script in
# .superpowers/sdd/p3s1-codex-out.md for reproducer.
#
# Two-column page: min(x0)=60, max(x1)=500 — outer strip geometry identical to
# the single-column _BODY_COLS; two columns are used to match the brief's wording.
# ---------------------------------------------------------------------------

_CHAR_COLS = (TextColumn(x0=60.0, x1=280.0), TextColumn(x0=320.0, x1=500.0))


class DenseMeasurer:
    """Content-keyed measurer for the P3-S1 characterization fixture.

    * Text containing "SCALE_REDUCE" → height 900*scale (fits only at scale≤0.8).
    * Text containing "SKIP"         → height 1200*scale (never fits, even at min_scale=0.7).
    * Otherwise                      → height 14*scale   (always fits comfortably).
    Width is always min(60.0, max_width).
    """

    def measure(self, text: str, max_width: float, scale: float) -> tuple[float, float]:
        if "SCALE_REDUCE" in text:
            return (min(60.0, max_width), 900.0 * scale)
        if "SKIP" in text:
            return (min(60.0, max_width), 1200.0 * scale)
        return (min(60.0, max_width), 14.0 * scale)


_CHAR_NOTES = [
    # n1: WARNING, conf=0.9 → highest priority (WARNING beats CORRECTION/etc.)
    NoteRequest(
        annotation_id="n1",
        source_locator="p:1",
        annotation_type=AnnotationType.WARNING,
        confidence=0.9,
        content="Dangerous shortcut here.",
        requested_placement="margin_right",
        anchor=_anchor(100.0, 200.0, 400.0, 214.0),
        render_seed=1,
    ),
    # n2: CORRECTION, conf=0.8 → sort slot 2
    NoteRequest(
        annotation_id="n2",
        source_locator="p:1",
        annotation_type=AnnotationType.CORRECTION,
        confidence=0.8,
        content="Wrong formula.",
        requested_placement="margin_right",
        anchor=_anchor(100.0, 250.0, 400.0, 264.0),
        render_seed=2,
    ),
    # n3: CORRECTION, conf=0.7 → sort slot 3
    NoteRequest(
        annotation_id="n3",
        source_locator="p:1",
        annotation_type=AnnotationType.CORRECTION,
        confidence=0.7,
        content="See corrected method.",
        requested_placement="margin_right",
        anchor=_anchor(100.0, 400.0, 400.0, 414.0),
        render_seed=3,
    ),
    # n4: INSIGHT, conf=0.9 → sort slot 5 (INSIGHT lower priority than CORRECTION)
    NoteRequest(
        annotation_id="n4",
        source_locator="p:1",
        annotation_type=AnnotationType.INSIGHT,
        confidence=0.9,
        content="Novel approach possible.",
        requested_placement="margin_right",
        anchor=_anchor(100.0, 600.0, 400.0, 614.0),
        render_seed=4,
    ),
    # n5: CORRECTION, conf=0.5 → sort slot 4 (CORRECTION, lower conf than n2/n3)
    #     DenseMeasurer returns 900*scale — too tall at scale=1.0 and 0.9, fits at 0.8.
    #     → two SCALE_REDUCED warnings, then a SHIFTED warning (page-top clamp).
    NoteRequest(
        annotation_id="n5",
        source_locator="p:1",
        annotation_type=AnnotationType.CORRECTION,
        confidence=0.5,
        content="SCALE_REDUCE: elaborate explanation",
        requested_placement="margin_left",
        anchor=_anchor(100.0, 450.0, 400.0, 464.0),
        render_seed=5,
    ),
    # n6: SHORTCUT, conf=0.6 → sort slot last (lowest-priority type in the fixture)
    #     DenseMeasurer returns 1200*scale — never fits even at min_scale=0.7 (840>792).
    #     → UNPLACEABLE / skipped; NOTE_SKIPPED_UNFITTABLE degradation flag emitted.
    NoteRequest(
        annotation_id="n6",
        source_locator="p:1",
        annotation_type=AnnotationType.SHORTCUT,
        confidence=0.6,
        content="SKIP: very long note",
        requested_placement="margin_left",
        anchor=_anchor(100.0, 600.0, 400.0, 614.0),
        render_seed=6,
    ),
]


def _char_row(ann: object) -> tuple:
    """Extract a pinnable (id, placement, box_coords×4, scale, warnings) tuple."""
    b = ann.note_box
    return (
        ann.annotation_id,
        ann.resolved_placement,
        round(b.x0, 2),
        round(b.y0, 2),
        round(b.x1, 2),
        round(b.y1, 2),
        round(ann.note_scale, 2),
        tuple((w.code, w.detail) for w in ann.warnings),
    )


def test_p3s1_dense_characterization_snapshot() -> None:
    """Pin exact greedy output on the 6-note two-column fixture.

    Expectation built by running HEAD commit 65c3752 on 2026-07-21.
    This test is a drift-detector: it PASSES before and after the P3-S1 extraction.
    P3-S3 flipped the default solver to beam, so the greedy contract is now pinned
    via an explicit ``solver="greedy"``.
    """
    result = run_layout(
        _CHAR_NOTES,
        _PAGE,
        [],
        DenseMeasurer(),
        config=LayoutConfig(solver="greedy"),
        body_columns=_CHAR_COLS,
    )

    # Placed notes in result order (sort produces: n1, n2, n3, n5, n4).
    # n5 gets two SCALE_REDUCED warnings followed by one SHIFTED warning — ORDER MATTERS.
    expected_placed = [
        (
            "n1", "margin_right",
            510.0, 200.0, 570.0, 214.0,
            1.0,
            (),
        ),
        (
            "n2", "margin_right",
            510.0, 250.0, 570.0, 264.0,
            1.0,
            (),
        ),
        (
            "n3", "margin_right",
            510.0, 400.0, 570.0, 414.0,
            1.0,
            (),
        ),
        (
            "n5", "margin_left",
            # Was 72-792: the note ran to the page's bottom trim. Notes now keep
            # page_edge_pad (8pt) from the top and bottom edges too (2026-10-23).
            8.0, 64.0, 50.0, 784.0,
            0.8,
            (
                (AnchorWarningCode.SCALE_REDUCED, "Reduced note scale to 0.90 after larger geometry did not fit."),
                (AnchorWarningCode.SCALE_REDUCED, "Reduced note scale to 0.80 after larger geometry did not fit."),
                (AnchorWarningCode.SHIFTED,        "Shifted note top from y=450.00 to y=64.00 to avoid occupied space."),
            ),
        ),
        (
            "n4", "margin_right",
            510.0, 600.0, 570.0, 614.0,
            1.0,
            (),
        ),
    ]
    expected_skipped = [("n6", SkipReason.UNPLACEABLE)]
    expected_flags = (DegradationFlag.NOTE_SKIPPED_UNFITTABLE,)

    actual_placed = [_char_row(a) for a in result.placed]
    actual_skipped = [(s.annotation_id, s.reason) for s in result.skipped]
    actual_flags = tuple(result.degradation_flags)

    assert actual_placed == expected_placed, (
        f"placed rows mismatch:\n  got={actual_placed}\n  want={expected_placed}"
    )
    assert actual_skipped == expected_skipped, (
        f"skipped mismatch: got={actual_skipped} want={expected_skipped}"
    )
    assert actual_flags == expected_flags, (
        f"degradation_flags mismatch: got={actual_flags} want={expected_flags}"
    )


def test_p3s1_determinism_repeat() -> None:
    """Same fixture twice → identical LayoutResult (default solver is deterministic).

    Authored against greedy; since the P3-S3 flip the default routes to beam, so this
    now pins beam determinism (beam has its own dedicated determinism tests in 18h too).
    """
    cfg = LayoutConfig()
    r1 = run_layout(_CHAR_NOTES, _PAGE, [], DenseMeasurer(), config=cfg, body_columns=_CHAR_COLS)
    r2 = run_layout(_CHAR_NOTES, _PAGE, [], DenseMeasurer(), config=cfg, body_columns=_CHAR_COLS)
    assert r1 == r2, "run_layout must be deterministic: two identical calls must return equal results"


def test_p3s1_permutation_guard() -> None:
    """Shuffled input order → identical LayoutResult (priority sort canonicalizes).

    The sort at engine.py:282-291 orders by (type_priority, -confidence, annotation_id)
    before any placement logic runs.  Shuffling the input must not change the output.
    """
    import random as _random  # local import — only needed here

    shuffled = list(_CHAR_NOTES)
    _random.seed(42)
    _random.shuffle(shuffled)

    cfg = LayoutConfig()
    original = run_layout(_CHAR_NOTES, _PAGE, [], DenseMeasurer(), config=cfg, body_columns=_CHAR_COLS)
    permuted = run_layout(shuffled, _PAGE, [], DenseMeasurer(), config=cfg, body_columns=_CHAR_COLS)
    assert original == permuted, (
        "run_layout must be permutation-invariant: the priority sort canonicalizes input order"
    )


# ---------------------------------------------------------------------------
# 18. P3-S2b: beam solver dispatch
# ---------------------------------------------------------------------------
#
# These tests are RED before P3-S2b is implemented (AttributeError on the
# missing LayoutConfig.solver / .beam_width fields) and go GREEN after.
# The P3-S1 characterization suite (Section 17) pins the greedy contract where
# it passes solver="greedy" explicitly; its default-config tests (determinism
# repeat, permutation guard) run on beam since the P3-S3 flip. These tests
# cover beam dispatch wiring and shared invariants only.
#
# Spy tests patch halfblood.layout.page_solver (the module object).  This
# requires the engine to call page_solver.solve via module attribute —
# ``import halfblood.layout.page_solver as _ps; _ps.solve(...)`` — NOT via a
# bare ``from ... import solve`` which would create a local name that the spy
# cannot intercept.  The brief pins this import style on Codex.
# ---------------------------------------------------------------------------


# 18a. Config fields --------------------------------------------------------


def test_p3s3_config_solver_default_beam() -> None:
    """LayoutConfig.solver defaults to 'beam' (P3-S3 flip); beam_width defaults to 128.

    Rollout gate 2026-07-22: quality PASS (byte-identical corpus), determinism PASS
    (hash-seed subprocess identical), perf PASS at the owner-revised 50ms budget
    (8-note p95 ≈ 45-47ms after the S2c hot-path optimization).
    """
    cfg = LayoutConfig()
    assert cfg.solver == "beam"
    assert cfg.beam_width == 128


def test_p3s2b_config_solver_beam_accepted() -> None:
    """LayoutConfig(solver='beam') must construct without error."""
    cfg = LayoutConfig(solver="beam")
    assert cfg.solver == "beam"


def test_p3s2b_config_beam_width_configurable() -> None:
    """beam_width must be a plain configurable integer field."""
    cfg = LayoutConfig(solver="beam", beam_width=16)
    assert cfg.beam_width == 16


# 18b. Dispatch wiring (spy) ------------------------------------------------


def test_p3s2b_beam_calls_page_solver(monkeypatch: pytest.MonkeyPatch) -> None:
    """page_solver.solve must be called exactly once when solver='beam'."""
    import halfblood.layout.page_solver as _ps

    calls: list[object] = []
    _real = _ps.solve

    def _spy(*args: object, **kwargs: object) -> object:
        calls.append(args)
        return _real(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(_ps, "solve", _spy)
    run_layout(
        [_req("a1")],
        _PAGE,
        [],
        _FM,
        config=LayoutConfig(solver="beam"),
        body_columns=_BODY_COLS,
    )
    assert len(calls) == 1, (
        "page_solver.solve must be called exactly once per beam run_layout call"
    )


def test_p3s2b_greedy_does_not_call_page_solver(monkeypatch: pytest.MonkeyPatch) -> None:
    """page_solver.solve must NOT be called when solver='greedy' (the escape hatch)."""
    import halfblood.layout.page_solver as _ps

    calls: list[object] = []
    _real = _ps.solve

    def _spy(*args: object, **kwargs: object) -> object:  # pragma: no cover
        calls.append(args)
        return _real(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(_ps, "solve", _spy)
    run_layout(
        [_req("a1")],
        _PAGE,
        [],
        _FM,
        config=LayoutConfig(solver="greedy"),
        body_columns=_BODY_COLS,
    )
    assert calls == [], "page_solver.solve must NOT be called when solver='greedy'"


# 18c. Coverage and hard geometry invariants --------------------------------


def test_p3s2b_beam_coverage_invariant() -> None:
    """Every input note must appear in placed or skipped exactly once."""
    reqs = [_req(f"n{i}") for i in range(4)]
    result = run_layout(
        reqs,
        _PAGE,
        [],
        _FM,
        config=LayoutConfig(solver="beam"),
        body_columns=_BODY_COLS,
    )
    placed_ids = {a.annotation_id for a in result.placed}
    skipped_ids = {s.annotation_id for s in result.skipped}
    all_ids = {r.annotation_id for r in reqs}
    assert placed_ids | skipped_ids == all_ids, "all notes must appear in placed or skipped"
    assert placed_ids & skipped_ids == set(), "no note may appear in both placed and skipped"


def test_p3s2b_beam_placed_notes_within_page() -> None:
    """All beam-placed notes must be contained within the page bounds."""
    reqs = [_req(f"n{i}") for i in range(3)]
    result = run_layout(
        reqs,
        _PAGE,
        [],
        _FM,
        config=LayoutConfig(solver="beam"),
        body_columns=_BODY_COLS,
    )
    for ann in result.placed:
        assert _within(ann.note_box, _PAGE), (
            f"{ann.annotation_id}: note_box {ann.note_box} leaves page {_PAGE}"
        )


def test_p3s2b_beam_no_placed_overlap() -> None:
    """No two beam-placed notes may overlap (solver hard constraint)."""
    reqs = [_req(f"n{i}") for i in range(4)]
    result = run_layout(
        reqs,
        _PAGE,
        [],
        _FM,
        config=LayoutConfig(solver="beam"),
        body_columns=_BODY_COLS,
    )
    boxes = [a.note_box for a in result.placed]
    for i, a in enumerate(boxes):
        for b in boxes[i + 1 :]:
            assert not _rects_overlap(a, b, tol=2.0), (
                f"placed notes must not overlap: {a} vs {b}"
            )


# 18d. MP1c fail-closed and inline exemption --------------------------------


def test_p3s2b_beam_mp1c_skips_margin_no_columns() -> None:
    """With no body_columns, beam path must skip margin notes (fail-closed)."""
    result = run_layout(
        [_req("a1")],
        _PAGE,
        [],
        _FM,
        config=LayoutConfig(solver="beam"),
        # no body_columns — MP1c
    )
    assert "a1" not in {a.annotation_id for a in result.placed}, (
        "margin note must not be placed without body_columns under beam"
    )
    assert "a1" in {s.annotation_id for s in result.skipped}, (
        "margin note must be skipped without body_columns under beam"
    )
    skip = next(s for s in result.skipped if s.annotation_id == "a1")
    assert skip.reason == SkipReason.UNPLACEABLE
    assert DegradationFlag.NOTE_SKIPPED_UNFITTABLE in result.degradation_flags


def test_p3s2b_beam_inline_exemption_from_mp1c() -> None:
    """Inline requests must be placed under beam even without body_columns."""
    req = _req("a1", placement="inline", anchor=_anchor(100.0, 350.0, 400.0, 364.0))
    result = run_layout(
        [req],
        _PAGE,
        [],
        _FM,
        config=LayoutConfig(solver="beam"),
        # no body_columns — inline is exempt from MP1c
    )
    assert any(a.annotation_id == "a1" for a in result.placed), (
        "inline note must still be placed under beam even without body_columns"
    )
    placed = next(a for a in result.placed if a.annotation_id == "a1")
    assert placed.resolved_placement == "inline"


# 18e. Determinism and basic placement correctness -------------------------


def test_p3s2b_beam_determinism() -> None:
    """Identical inputs under beam must produce identical LayoutResults."""
    reqs = [_req(f"n{i}") for i in range(3)]
    cfg = LayoutConfig(solver="beam")
    r1 = run_layout(reqs, _PAGE, [], _FM, config=cfg, body_columns=_BODY_COLS)
    r2 = run_layout(reqs, _PAGE, [], _FM, config=cfg, body_columns=_BODY_COLS)
    assert r1 == r2, "beam solver must be deterministic across identical calls"


def test_p3s2b_beam_places_single_note_when_fits() -> None:
    """A single note with adequate margin width must be placed, not skipped."""
    result = run_layout(
        [_req("a1")],
        _PAGE,
        [],
        _FM,
        config=LayoutConfig(solver="beam"),
        body_columns=_BODY_COLS,
    )
    assert any(a.annotation_id == "a1" for a in result.placed), (
        "beam must place a single note when the margin is wide enough"
    )


def test_p3s2b_beam_preferred_side_taken_when_free() -> None:
    """When the preferred side has space, beam must resolve to that side."""
    req = _req("a1", placement="margin_right")
    result = run_layout(
        [req],
        _PAGE,
        [],
        _FM,
        config=LayoutConfig(solver="beam"),
        body_columns=_BODY_COLS,
    )
    placed = [a for a in result.placed if a.annotation_id == "a1"]
    assert len(placed) == 1, "note must be placed when the preferred margin is free"
    assert placed[0].resolved_placement == "margin_right", (
        "preferred side (margin_right) must be chosen when free under beam"
    )


# 18f. Default-path regression -----------------------------------------------
#
# Explicit solver='beam' must produce byte-identical output to the default
# LayoutConfig() (the default routes to beam since P3-S3).  This pins the
# routing logic: the default path must call _run_beam exactly as the explicit
# beam path does.


def test_p3s3_explicit_beam_matches_default() -> None:
    """LayoutConfig(solver='beam') must return a byte-identical LayoutResult to LayoutConfig().

    P3-S3 flipped the default to beam; this pins that the default routing IS the beam
    path.  Uses the P3-S1 characterisation fixture (dense 6-note, two-column page),
    on which beam and greedy demonstrably differ — so this test discriminates the
    default's routing rather than passing vacuously.
    """
    r_default = run_layout(
        _CHAR_NOTES,
        _PAGE,
        [],
        DenseMeasurer(),
        config=LayoutConfig(),
        body_columns=_CHAR_COLS,
    )
    r_explicit = run_layout(
        _CHAR_NOTES,
        _PAGE,
        [],
        DenseMeasurer(),
        config=LayoutConfig(solver="beam"),
        body_columns=_CHAR_COLS,
    )
    assert r_default == r_explicit, (
        "explicit solver='beam' must be byte-identical to LayoutConfig() default"
    )


# 18g. Beam-beats-greedy discriminating trap ----------------------------------
#
# Two notes on a right-only page (left strip degenerate).
# A (WARNING, 400pt tall): greedy places at scale=1.0, attempt=0 → y=57..457.
#   This fills the range [57, 457] and blocks ALL 9 of B's shift-attempts at
#   every scale (B's shifts of ±4×14pt keep it in [144, 270] ⊂ [57, 457]).
# B (CORRECTION, 14pt): no valid right-margin slot while A is at y=57..457.
#   Left is degenerate → B is SKIPPED by greedy.
# Beam: A at scale=0.8, attempt=1 → y=417..737 frees B@y=200..214.
#   Both placed (0 omissions) beats A@best + B@skip (1 omission).
#
# BeamTrapMeasurer keys on 'TALL' substring in note content.
# _TRAP_COLS: TextColumn(x0=0.0, x1=500.0) — left strip x=(8, -10) degenerate;
#   right strip x=(510, 604) = 94pt (valid, ≥ margin_min_width=40).


class BeamTrapMeasurer:
    """Content-keyed measurer for the beam-beats-greedy-trap fixture.

    * Content containing 'TALL' → height = 400.0 × scale.
    * All other content          → height =  14.0 × scale.
    Width is always min(60.0, max_width).
    """

    def measure(self, text: str, max_width: float, scale: float) -> tuple[float, float]:
        h = 400.0 if "TALL" in text else 14.0
        return (min(60.0, max_width), h * scale)


# Right strip (510, 604) = 94pt valid; left strip (8, −10) = −18pt degenerate.
_TRAP_COLS = (TextColumn(x0=0.0, x1=500.0),)

_TRAP_A = NoteRequest(
    annotation_id="trap-A",
    source_locator="p:1",
    annotation_type=AnnotationType.WARNING,
    confidence=0.9,
    content="TALL note — fills right margin at attempt-0",
    requested_placement="margin_right",
    anchor=_anchor(100.0, 250.0, 400.0, 264.0),
    render_seed=0,
)
_TRAP_B = NoteRequest(
    annotation_id="trap-B",
    source_locator="p:1",
    annotation_type=AnnotationType.CORRECTION,
    confidence=0.9,
    content="Short note — only one unblocked slot per side",
    requested_placement="margin_right",
    anchor=_anchor(100.0, 200.0, 400.0, 214.0),
    render_seed=0,
)
_TRAP_M = BeamTrapMeasurer()


def test_p3s2b_beam_beats_greedy_trap() -> None:
    """Beam places both notes; greedy skips B; beam's A uses a higher-ordinal candidate.

    Greedy half: A is placed at its best ordinal (scale=1.0, attempt=0, y=57..457),
    which occupies the only band where B can fit.  B is skipped UNPLACEABLE.

    Beam half: the solver explores A's higher-ordinal candidates and discovers that
    A at scale=0.8, attempt=1 (y=417..737) frees B's attempt=0 (y=200..214).
    0 omissions beats 1 omission → both notes placed.

    A's note_box must differ between the greedy and beam results, confirming that
    beam used a different (higher-ordinal) candidate for A.
    """
    r_greedy = run_layout(
        [_TRAP_A, _TRAP_B],
        _PAGE,
        [],
        _TRAP_M,
        # Explicit greedy escape hatch — the default routes to beam since P3-S3.
        config=LayoutConfig(solver="greedy"),
        body_columns=_TRAP_COLS,
    )
    r_beam = run_layout(
        [_TRAP_A, _TRAP_B],
        _PAGE,
        [],
        _TRAP_M,
        config=LayoutConfig(solver="beam"),
        body_columns=_TRAP_COLS,
    )

    # --- Greedy half: A placed, B skipped ---
    assert "trap-A" in _placed_ids(r_greedy), (
        "greedy must place A (the higher-priority note)"
    )
    assert "trap-B" in _skipped_ids(r_greedy), (
        "greedy must skip B: A's first-choice fills the only band where B can fit"
    )

    # --- Beam half: both placed ---
    assert "trap-A" in _placed_ids(r_beam), "beam must place A"
    assert "trap-B" in _placed_ids(r_beam), (
        "beam must place B by using A's higher-ordinal candidate that frees B's slot"
    )

    # --- A must have moved (used a worse-ordinal candidate) ---
    greedy_a_box = next(a.note_box for a in r_greedy.placed if a.annotation_id == "trap-A")
    beam_a_box = next(a.note_box for a in r_beam.placed if a.annotation_id == "trap-A")
    assert greedy_a_box != beam_a_box, (
        "beam's A must occupy a different position than greedy's A "
        "(beam used a higher-ordinal candidate to free B)"
    )


# 18h. Beam determinism — permuted input and PYTHONHASHSEED ------------------


def test_p3s2b_beam_determinism_permuted_input() -> None:
    """Shuffled input order → byte-identical LayoutResult under beam.

    The priority sort at the start of run_layout canonicalises request order before
    any placement logic runs.  Mirrors test_p3s1_permutation_guard for the beam path.
    """
    import random as _random  # local import — only needed here

    shuffled = list(_CHAR_NOTES)
    _random.seed(7)
    _random.shuffle(shuffled)

    cfg = LayoutConfig(solver="beam")
    r_original = run_layout(
        _CHAR_NOTES, _PAGE, [], DenseMeasurer(), config=cfg, body_columns=_CHAR_COLS
    )
    r_shuffled = run_layout(
        shuffled, _PAGE, [], DenseMeasurer(), config=cfg, body_columns=_CHAR_COLS
    )
    assert r_original == r_shuffled, (
        "beam must be permutation-invariant: priority sort canonicalises input order"
    )


def test_p3s2b_beam_determinism_across_pythonhashseed() -> None:
    """run_layout with solver='beam' gives identical results across PYTHONHASHSEED values.

    Runs the engine in a subprocess with PYTHONHASHSEED forced to two distinct values.
    Identical stdout across seeds confirms that no set/dict iteration order inside the
    beam path affects the placed-note sequence or the score tiebreaker.
    """
    import os
    import subprocess

    # Repo-relative, not absolute: an absolute path from the original author's
    # machine silently broke this subprocess on every other checkout.
    _src = str(Path(__file__).resolve().parents[1] / "src")
    _script = f"""
import sys
sys.path.insert(0, {_src!r})
from halfblood.layout.engine import LayoutConfig, NoteRequest, run_layout
from halfblood.layout.occupancy import TextColumn
from halfblood.models.legacy import AnnotationType
from halfblood.models.rendering import ResolvedAnchor, SurfacePoint, SurfaceQuad, SurfaceRect

def _q(x0, y0, x1, y1):
    return SurfaceQuad(
        ul=SurfacePoint(x=x0, y=y0), ur=SurfacePoint(x=x1, y=y0),
        lr=SurfacePoint(x=x1, y=y1), ll=SurfacePoint(x=x0, y=y1),
    )

page = SurfaceRect(x0=0.0, y0=0.0, x1=612.0, y1=792.0)
cols = (TextColumn(x0=60.0, x1=500.0),)
reqs = [
    NoteRequest(
        annotation_id=f"n{{i}}", source_locator="p:1",
        annotation_type=AnnotationType.CORRECTION,
        confidence=0.9, content=f"note {{i}}",
        requested_placement="margin_right",
        anchor=ResolvedAnchor(char_range=(0, 1), quads=(
            _q(100.0, 100.0 + i * 50, 400.0, 114.0 + i * 50),
        )),
        render_seed=i,
    )
    for i in range(3)
]

class FM:
    def measure(self, t, w, s):
        return (min(60.0, w), 14.0 * s)

result = run_layout(reqs, page, [], FM(), config=LayoutConfig(solver="beam"), body_columns=cols)
placed = ",".join(a.annotation_id for a in result.placed)
skipped = ",".join(s.annotation_id for s in result.skipped)
print(f"placed={{placed}} skipped={{skipped}}")
"""
    outputs: list[str] = []
    for seed in ("0", "42"):
        proc = subprocess.run(
            [sys.executable, "-c", _script],
            capture_output=True,
            text=True,
            env={**os.environ, "PYTHONHASHSEED": seed},
        )
        assert proc.returncode == 0, (
            f"beam subprocess failed (PYTHONHASHSEED={seed}):\n{proc.stderr}"
        )
        outputs.append(proc.stdout.strip())
    assert len(set(outputs)) == 1, (
        f"beam output varies across PYTHONHASHSEED values: {outputs}"
    )


# 18i. Warning semantics on winning geometry ----------------------------------
#
# Warnings must reflect the WINNING beam placement only.
# SCALE_REDUCED: at least one SCALE_REDUCED entry when the chosen scale < 1.0.
# SIDE_SWITCHED: at least one SIDE_SWITCHED entry when the note was placed on the
#   non-preferred side.
# We assert *presence*, not exact count or sequence — beam may emit fewer steps
# than the greedy path's incremental reduction (winning geometry only).


def test_p3s2b_beam_emits_scale_reduced_for_winning_geometry() -> None:
    """SCALE_REDUCED must be present when beam places a note at reduced scale.

    DenseMeasurer returns height=900*scale for content containing 'SCALE_REDUCE'.
    At scale=1.0: 900pt > 792pt page height → no candidate generated.
    At scale=0.9: 810pt > 792pt → no candidate.
    At scale≤0.8: fits → placed with SCALE_REDUCED warning on winning geometry.
    """
    req = _req("a1", content="SCALE_REDUCE this note")
    result = run_layout(
        [req],
        _PAGE,
        [],
        DenseMeasurer(),
        config=LayoutConfig(solver="beam"),
        body_columns=_BODY_COLS,
    )
    assert "a1" in _placed_ids(result), (
        "note must be placed at a reduced scale under beam; got skipped"
    )
    ann = next(a for a in result.placed if a.annotation_id == "a1")
    assert any(w.code == AnchorWarningCode.SCALE_REDUCED for w in ann.warnings), (
        "SCALE_REDUCED must appear on a beam-placed note whose winning scale < 1.0; "
        f"got warnings={ann.warnings}"
    )


def test_p3s2b_beam_emits_side_switched_for_winning_geometry() -> None:
    """SIDE_SWITCHED must be present when beam places a note on the non-preferred side.

    _SWITCH_COLS: right strip (570, 604) = 34pt (degenerate, < margin_min_width=40);
    left strip (8, 50) = 42pt (valid).  A margin_right request has no right candidates
    → must switch to the left side → SIDE_SWITCHED on the winning ResolvedAnnotation.
    """
    req = _req("a1", placement="margin_right", anchor=_anchor(100.0, 350.0, 400.0, 364.0))
    result = run_layout(
        [req],
        _PAGE,
        [],
        _FM,
        config=LayoutConfig(solver="beam"),
        body_columns=_SWITCH_COLS,
    )
    assert "a1" in _placed_ids(result), (
        "note must be placed on the opposite side under beam; got skipped"
    )
    ann = next(a for a in result.placed if a.annotation_id == "a1")
    assert any(w.code == AnchorWarningCode.SIDE_SWITCHED for w in ann.warnings), (
        "SIDE_SWITCHED must appear on a beam-placed note forced to the non-preferred side; "
        f"got warnings={ann.warnings}"
    )


@pytest.mark.parametrize("solver", ["greedy", "beam"])
@pytest.mark.parametrize("anchor_y", [0.0, 2.0, 780.0, 790.0])
def test_note_keeps_page_edge_pad_from_top_and_bottom(solver: str, anchor_y: float) -> None:
    """A note near the page's top or bottom edge stays ``page_edge_pad`` inside it.

    Before 2026-10-23 the pad applied only to the sides: real-model Alice notes
    were shifted to y=0 (first line on the trim) and one ended past y=792.
    """
    config = LayoutConfig(solver=solver)  # type: ignore[arg-type]
    request = NoteRequest(
        annotation_id="edge",
        source_locator="p:1",
        annotation_type=AnnotationType.CORRECTION,
        confidence=0.9,
        content="Near the edge.",
        requested_placement="margin_right",
        anchor=_anchor(100.0, anchor_y, 400.0, min(anchor_y + 14.0, 792.0)),
        render_seed=1,
    )
    result = run_layout([request], _PAGE, [], DenseMeasurer(), config=config,
                        body_columns=_CHAR_COLS)
    assert len(result.placed) == 1
    box = result.placed[0].note_box
    assert box is not None
    assert box.y0 >= _PAGE.y0 + config.page_edge_pad - 1e-6
    assert box.y1 <= _PAGE.y1 - config.page_edge_pad + 1e-6
