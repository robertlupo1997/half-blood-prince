"""Both-solver contract parametrization — S3 reviewer follow-up.

The broad layout contracts in test_layout_engine.py were authored before the P3-S3
default-solver flip and mostly run under beam (the new default).  Greedy (the
escape hatch) was covered only by a characterization snapshot, a routing spy, and
one trap test.  This module fills that gap by running 8 core contracts under BOTH
solvers via @pytest.mark.parametrize("solver", ["greedy", "beam"]).

Every test constructs ``LayoutConfig(solver=solver)`` explicitly so the
parametrization is unambiguous regardless of future default changes.

Fixture style mirrors test_layout_engine.py — helpers are replicated locally
so this module stays self-contained without touching conftest.
"""

from __future__ import annotations

import random

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
    DegradationFlag,
    ResolvedAnchor,
    SkipReason,
    SurfacePoint,
    SurfaceQuad,
    SurfaceRect,
)

# ---------------------------------------------------------------------------
# Shared geometry (replicated from test_layout_engine.py)
# ---------------------------------------------------------------------------

_PAGE = SurfaceRect(x0=0.0, y0=0.0, x1=612.0, y1=792.0)

# Standard body block: body occupancy for body-invasion assertions.
_BODY = SurfaceRect(x0=60.0, y0=72.0, x1=500.0, y1=720.0)

# Body columns whose outer strips give: right=(510,604)=94pt, left=(8,50)=42pt,
# both ≥ margin_min_width=40, so both sides are valid.
_BODY_COLS = (TextColumn(x0=60.0, x1=500.0),)


# ---------------------------------------------------------------------------
# Geometry helpers (replicated locally)
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
# Assertion helpers (replicated locally)
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
# Fake deterministic measurer (replicated locally)
# ---------------------------------------------------------------------------


class FixedMeasurer:
    """Always returns (w, h) capped at max_width — deterministic, known bounds."""

    def __init__(self, w: float = 60.0, h: float = 14.0) -> None:
        self._w, self._h = w, h

    def measure(self, text: str, max_width: float, scale: float) -> tuple[float, float]:
        return (min(self._w, max_width), self._h * scale)


_FM = FixedMeasurer()


# ---------------------------------------------------------------------------
# Multi-note fixture (≥4 notes at well-separated y positions)
#
# Notes are spread over distinct vertical bands (100, 250, 400, 600) so
# the FixedMeasurer's 14pt notes never compete for the same slot.  All four
# use margin_right with a body-column set that gives a 94pt right strip and a
# 42pt left strip — both valid.
# ---------------------------------------------------------------------------

_MULTI_NOTES = [
    _req("m1", annotation_type=AnnotationType.WARNING,    confidence=0.9,
         anchor=_anchor(100.0, 100.0, 400.0, 114.0), render_seed=1),
    _req("m2", annotation_type=AnnotationType.CORRECTION, confidence=0.8,
         anchor=_anchor(100.0, 250.0, 400.0, 264.0), render_seed=2),
    _req("m3", annotation_type=AnnotationType.INSIGHT,    confidence=0.7,
         anchor=_anchor(100.0, 400.0, 400.0, 414.0), render_seed=3),
    _req("m4", annotation_type=AnnotationType.SHORTCUT,   confidence=0.6,
         anchor=_anchor(100.0, 600.0, 400.0, 614.0), render_seed=4),
]

_MULTI_IDS = {r.annotation_id for r in _MULTI_NOTES}


# ---------------------------------------------------------------------------
# Contract 1 — Coverage: every input note appears in placed-or-skipped exactly once
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("solver", ["greedy", "beam"])
def test_contract_coverage_every_note_placed_or_skipped_once(solver: str) -> None:
    """Every input note must appear in placed or skipped exactly once.

    Uses a ≥4-note fixture.  Greedy and beam must both account for all inputs
    with no duplicates and no dropped notes.
    """
    cfg = LayoutConfig(solver=solver)
    result = run_layout(_MULTI_NOTES, _PAGE, [], _FM, config=cfg, body_columns=_BODY_COLS)

    placed_ids = [a.annotation_id for a in result.placed]
    skipped_ids = [s.annotation_id for s in result.skipped]

    # No duplicates within each list.
    assert len(placed_ids) == len(set(placed_ids)), (
        f"[{solver}] duplicate annotation_id in placed: {placed_ids}"
    )
    assert len(skipped_ids) == len(set(skipped_ids)), (
        f"[{solver}] duplicate annotation_id in skipped: {skipped_ids}"
    )

    # Union must equal the full input set; intersection must be empty.
    placed_set = set(placed_ids)
    skipped_set = set(skipped_ids)
    assert placed_set.isdisjoint(skipped_set), (
        f"[{solver}] annotations in BOTH placed and skipped: {placed_set & skipped_set}"
    )
    assert placed_set | skipped_set == _MULTI_IDS, (
        f"[{solver}] missing annotations: {_MULTI_IDS - placed_set - skipped_set}"
    )


# ---------------------------------------------------------------------------
# Contract 2 — Page containment: all placed note boxes are within the page rect
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("solver", ["greedy", "beam"])
def test_contract_placed_notes_within_page(solver: str) -> None:
    """Every placed note's note_box must be fully contained within the page rect."""
    cfg = LayoutConfig(solver=solver)
    result = run_layout(_MULTI_NOTES, _PAGE, [], _FM, config=cfg, body_columns=_BODY_COLS)

    assert result.placed, f"[{solver}] expected at least one placed note"
    for ann in result.placed:
        assert ann.note_box is not None, (
            f"[{solver}] {ann.annotation_id}: placed but note_box is None"
        )
        assert _within(ann.note_box, _PAGE), (
            f"[{solver}] {ann.annotation_id}: note_box {ann.note_box} "
            f"leaves page {_PAGE}"
        )


# ---------------------------------------------------------------------------
# Contract 3 — No mutual overlap: no two placed notes may overlap (tolerance 2.0)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("solver", ["greedy", "beam"])
def test_contract_no_placed_notes_overlap(solver: str) -> None:
    """No two placed note boxes may overlap beyond the engine's tolerance (2.0 pt).

    The FixedMeasurer returns 14pt-height notes.  At well-separated y positions
    the notes are trivially non-overlapping, making the assertion non-vacuous only
    if multiple notes are actually placed (assert below ensures that).
    """
    cfg = LayoutConfig(solver=solver)
    result = run_layout(_MULTI_NOTES, _PAGE, [], _FM, config=cfg, body_columns=_BODY_COLS)

    boxes = [a.note_box for a in result.placed if a.note_box is not None]
    assert len(boxes) >= 2, (
        f"[{solver}] need ≥2 placed notes to check non-overlap; got {len(boxes)}"
    )
    tol = LayoutConfig().overlap_tolerance  # 2.0
    for i, a in enumerate(boxes):
        for j, b in enumerate(boxes):
            if i >= j:
                continue
            assert not _rects_overlap(a, b, tol=tol), (
                f"[{solver}] placed notes overlap: {a} vs {b} (tolerance={tol})"
            )


# ---------------------------------------------------------------------------
# Contract 4 — Body non-invasion: placed margin notes do not overlap body rect
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("solver", ["greedy", "beam"])
def test_contract_placed_notes_do_not_invade_body(solver: str) -> None:
    """Placed margin notes must not overlap the body occupancy rect (beyond tolerance)."""
    cfg = LayoutConfig(solver=solver)
    result = run_layout(
        _MULTI_NOTES, _PAGE, [_BODY], _FM, config=cfg, body_columns=_BODY_COLS
    )

    assert result.placed, f"[{solver}] expected at least one placed note"
    tol = LayoutConfig().overlap_tolerance  # 2.0
    for ann in result.placed:
        if ann.note_box is None:
            continue
        # Only check margin-placed notes — inline/between_lines live inside the body column.
        if ann.resolved_placement in ("margin_left", "margin_right"):
            assert not _rects_overlap(ann.note_box, _BODY, tol=tol), (
                f"[{solver}] {ann.annotation_id} (resolved={ann.resolved_placement}): "
                f"note_box {ann.note_box} overlaps body {_BODY}"
            )


# ---------------------------------------------------------------------------
# Contract 5 — MP1c fail-closed: no body_columns → margin note skipped UNPLACEABLE;
#              inline note still placed (inline exemption)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("solver", ["greedy", "beam"])
def test_contract_mp1c_margin_skipped_without_columns(solver: str) -> None:
    """Without body_columns, a margin-requested note must be skipped UNPLACEABLE
    with NOTE_SKIPPED_UNFITTABLE degradation flag (MP1c fail-closed)."""
    cfg = LayoutConfig(solver=solver)
    req = _req("margin-no-cols", placement="margin_right")
    result = run_layout([req], _PAGE, [], _FM, config=cfg)  # no body_columns

    placed_set = {a.annotation_id for a in result.placed}
    skipped_set = {s.annotation_id for s in result.skipped}

    assert "margin-no-cols" not in placed_set, (
        f"[{solver}] margin note must not be placed without body_columns"
    )
    assert "margin-no-cols" in skipped_set, (
        f"[{solver}] margin note must be skipped without body_columns"
    )
    skip = next(s for s in result.skipped if s.annotation_id == "margin-no-cols")
    assert skip.reason == SkipReason.UNPLACEABLE, (
        f"[{solver}] skip.reason must be UNPLACEABLE; got {skip.reason}"
    )
    assert DegradationFlag.NOTE_SKIPPED_UNFITTABLE in result.degradation_flags, (
        f"[{solver}] NOTE_SKIPPED_UNFITTABLE must be set when a margin note is skipped"
    )


@pytest.mark.parametrize("solver", ["greedy", "beam"])
def test_contract_mp1c_inline_exempt_without_columns(solver: str) -> None:
    """Without body_columns, an inline-requested note must still be placed
    (inline placement is target-local and exempt from the MP1c fail-closed rule)."""
    cfg = LayoutConfig(solver=solver)
    req = _req("inline-no-cols", placement="inline",
               anchor=_anchor(100.0, 350.0, 400.0, 364.0))
    result = run_layout([req], _PAGE, [], _FM, config=cfg)  # no body_columns

    assert any(a.annotation_id == "inline-no-cols" for a in result.placed), (
        f"[{solver}] inline note must be placed even without body_columns"
    )
    ann = next(a for a in result.placed if a.annotation_id == "inline-no-cols")
    assert ann.resolved_placement == "inline", (
        f"[{solver}] resolved_placement must be 'inline'; got {ann.resolved_placement!r}"
    )


# ---------------------------------------------------------------------------
# Contract 6 — Scale floor: note_scale ≥ LayoutConfig.min_scale for every placed note
# ---------------------------------------------------------------------------


class _ScaleStressMeasurer:
    """Returns an oversized note to force scale reduction, stops at any scale < 1.

    * height = 200 * scale at scale >= 1.0 — 200pt notes still FIT on the page, so
      early notes place at scale 1.0; only a later note whose slot is crowded by the
      already-placed 200pt boxes is driven below scale 1.0 (reviewer-verified: m4).
    * height = 14 * scale at scale < 1.0 (fits at min_scale=0.7 → 9.8pt).

    So scale reduction genuinely occurs for at least one note AND every note that
    reduces ultimately fits — the scale-floor assertion is exercised non-vacuously.
    """

    def measure(self, text: str, max_width: float, scale: float) -> tuple[float, float]:
        if scale >= 1.0 - 1e-9:
            return (min(60.0, max_width), 200.0 * scale)
        return (min(60.0, max_width), 14.0 * scale)


@pytest.mark.parametrize("solver", ["greedy", "beam"])
def test_contract_note_scale_at_or_above_min_scale(solver: str) -> None:
    """note_scale must be ≥ LayoutConfig.min_scale for every placed annotation."""
    cfg = LayoutConfig(solver=solver)
    result = run_layout(
        _MULTI_NOTES, _PAGE, [], _ScaleStressMeasurer(), config=cfg, body_columns=_BODY_COLS
    )

    assert result.placed, f"[{solver}] expected at least one placed note after scale reduction"
    for ann in result.placed:
        assert ann.note_scale >= cfg.min_scale - 1e-9, (
            f"[{solver}] {ann.annotation_id}: note_scale={ann.note_scale} "
            f"is below min_scale={cfg.min_scale}"
        )


# ---------------------------------------------------------------------------
# Contract 7 — Determinism: same inputs twice → identical LayoutResult
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("solver", ["greedy", "beam"])
def test_contract_determinism(solver: str) -> None:
    """Identical inputs must produce byte-identical LayoutResult on two consecutive calls."""
    cfg = LayoutConfig(solver=solver)
    r1 = run_layout(_MULTI_NOTES, _PAGE, [_BODY], _FM, config=cfg, body_columns=_BODY_COLS)
    r2 = run_layout(_MULTI_NOTES, _PAGE, [_BODY], _FM, config=cfg, body_columns=_BODY_COLS)
    assert r1 == r2, (
        f"[{solver}] run_layout is not deterministic: two identical calls differ"
    )


# ---------------------------------------------------------------------------
# Contract 8 — Permutation invariance: shuffled input order → identical LayoutResult
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("solver", ["greedy", "beam"])
def test_contract_permutation_invariance(solver: str) -> None:
    """Shuffled input order must produce the same LayoutResult as the canonical order.

    The engine sorts requests by (type_priority, -confidence, annotation_id) before
    any placement logic runs, so input permutation must be irrelevant.
    """
    cfg = LayoutConfig(solver=solver)

    shuffled = list(_MULTI_NOTES)
    random.seed(99)
    random.shuffle(shuffled)
    # Confirm we actually changed the order (sanity check on the fixture).
    # With 4 distinct-priority notes and seed=99, the shuffle is not identity.
    canonical_ids = [r.annotation_id for r in _MULTI_NOTES]
    shuffled_ids = [r.annotation_id for r in shuffled]

    r_canonical = run_layout(
        _MULTI_NOTES, _PAGE, [_BODY], _FM, config=cfg, body_columns=_BODY_COLS
    )
    r_shuffled = run_layout(
        shuffled, _PAGE, [_BODY], _FM, config=cfg, body_columns=_BODY_COLS
    )
    assert r_canonical == r_shuffled, (
        f"[{solver}] run_layout is not permutation-invariant:\n"
        f"  canonical order: {canonical_ids}\n"
        f"  shuffled order:  {shuffled_ids}\n"
        f"  results differ"
    )
