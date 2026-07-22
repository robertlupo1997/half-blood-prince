"""Surface-neutral, fitz-free occupancy-based layout engine."""

from __future__ import annotations

import math
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from functools import partial
from typing import Literal, Protocol

import halfblood.layout.page_solver as _page_solver
from halfblood.layout.occupancy import TextColumn
from halfblood.models.annotations import Placement
from halfblood.models.legacy import AnnotationType
from halfblood.models.rendering import (
    AnchorWarning,
    AnchorWarningCode,
    DegradationFlag,
    ResolvedAnchor,
    ResolvedAnnotation,
    SkipReason,
    SkipRecord,
    SurfaceRect,
)

ANNOTATION_TYPE_PRIORITY: dict[AnnotationType, int] = {
    AnnotationType.WARNING: 0,
    AnnotationType.CORRECTION: 1,
    AnnotationType.INVENTION: 2,
    AnnotationType.IMPROVEMENT: 3,
    AnnotationType.SHORTCUT: 4,
    AnnotationType.CROSSED_OUT: 5,
    AnnotationType.INSIGHT: 6,
    AnnotationType.DOODLE_NOTE: 7,
}

_MarginSide = Literal["margin_right", "margin_left"]


class NoteMeasurer(Protocol):
    """Return the (width, height) of note text at the given max_width and scale."""

    def measure(self, text: str, max_width: float, scale: float) -> tuple[float, float]: ...


@dataclass(frozen=True)
class NoteRequest:
    annotation_id: str
    source_locator: str
    annotation_type: AnnotationType
    confidence: float
    content: str
    requested_placement: Placement
    anchor: ResolvedAnchor | None
    render_seed: int = 0


@dataclass(frozen=True)
class LayoutConfig:
    min_scale: float = 0.7
    attempt_budget: int = 8
    overlap_tolerance: float = 2.0
    margin_min_width: float = 40.0
    margin_gap: float = 10.0
    page_edge_pad: float = 8.0
    solver: Literal["greedy", "beam"] = "greedy"
    beam_width: int = 128


@dataclass(frozen=True)
class LayoutResult:
    placed: tuple[ResolvedAnnotation, ...]
    skipped: tuple[SkipRecord, ...]
    degradation_flags: tuple[DegradationFlag, ...]

    @property
    def warnings(self) -> tuple[AnchorWarning, ...]:
        """Aggregate all per-annotation warnings from placed annotations."""
        return tuple(warning for annotation in self.placed for warning in annotation.warnings)


def _target_rect(request: NoteRequest, page_rect: SurfaceRect) -> SurfaceRect:
    """Return the union of anchor corners, or a neutral center-column fallback."""
    if request.anchor is None or not request.anchor.quads:
        midpoint = (page_rect.x0 + page_rect.x1) / 2.0
        return SurfaceRect(
            x0=max(page_rect.x0, midpoint - 10.0),
            y0=page_rect.y0,
            x1=min(page_rect.x1, midpoint + 10.0),
            y1=page_rect.y1,
        )

    points = [
        point for quad in request.anchor.quads for point in (quad.ul, quad.ur, quad.lr, quad.ll)
    ]
    return SurfaceRect(
        x0=min(point.x for point in points),
        y0=min(point.y for point in points),
        x1=max(point.x for point in points),
        y1=max(point.y for point in points),
    )


def _rectangles_overlap(a: SurfaceRect, b: SurfaceRect, tolerance: float) -> bool:
    """Return whether both overlap dimensions exceed the allowed tolerance."""
    horizontal = min(a.x1, b.x1) - max(a.x0, b.x0)
    vertical = min(a.y1, b.y1) - max(a.y0, b.y0)
    return horizontal > tolerance and vertical > tolerance


def _interval_overlaps(
    candidate: tuple[float, float],
    occupied: Sequence[tuple[float, float]],
    tolerance: float,
) -> bool:
    """Return whether a vertical interval overlaps an occupied interval too far."""
    y0, y1 = candidate
    return any(min(y1, other_y1) - max(y0, other_y0) > tolerance for other_y0, other_y1 in occupied)


def _within_page(rect: SurfaceRect, page_rect: SurfaceRect) -> bool:
    """Return whether a rectangle is fully contained in the page."""
    return (
        rect.x0 >= page_rect.x0
        and rect.y0 >= page_rect.y0
        and rect.x1 <= page_rect.x1
        and rect.y1 <= page_rect.y1
    )


def _shift_multiplier(attempt: int) -> int:
    """Map attempts to 0, +1, -1, +2, -2, ... vertical offsets."""
    if attempt == 0:
        return 0
    magnitude = (attempt + 1) // 2
    return magnitude if attempt % 2 else -magnitude


def _margin_geometry(
    side: _MarginSide,
    target_rect: SurfaceRect,
    page_rect: SurfaceRect,
    margin_width: float,
    margin_gap: float,
) -> tuple[float, float]:
    """Return the horizontal bounds available to a note on one side."""
    if side == "margin_right":
        note_x0 = target_rect.x1 + margin_gap
        note_x1 = min(note_x0 + margin_width, page_rect.x1 - 1.0)
        return note_x0, note_x1

    note_x1 = target_rect.x0 - margin_gap
    note_x0 = max(note_x1 - margin_width, page_rect.x0 + 1.0)
    return note_x0, note_x1


def _try_inline(
    request: NoteRequest,
    target_rect: SurfaceRect,
    page_rect: SurfaceRect,
    forbidden_rects: Sequence[SurfaceRect],
    measurer: NoteMeasurer,
    tolerance: float,
) -> SurfaceRect | None:
    """Try the interline slot immediately above the target at full scale."""
    max_width = target_rect.x1 - target_rect.x0
    if max_width <= 0.0:
        return None

    width, height = measurer.measure(request.content, max_width, 1.0)
    if (
        not math.isfinite(width)
        or not math.isfinite(height)
        or width <= 0.0
        or height <= 0.0
        or width > max_width
    ):
        return None

    gap = SurfaceRect(
        x0=target_rect.x0,
        y0=target_rect.y0 - height,
        x1=target_rect.x1,
        y1=target_rect.y0,
    )
    note_box = SurfaceRect(
        x0=target_rect.x0,
        y0=target_rect.y0 - height,
        x1=target_rect.x0 + width,
        y1=target_rect.y0,
    )
    if not _within_page(note_box, page_rect):
        return None
    if any(_rectangles_overlap(gap, occupied, tolerance) for occupied in forbidden_rects):
        return None
    return note_box


def _iter_margin_side_candidates(
    request: NoteRequest,
    side: _MarginSide,
    target_rect: SurfaceRect,
    page_rect: SurfaceRect,
    margin_width: float,
    scale: float,
    side_occupancy: Sequence[tuple[float, float]],
    forbidden_rects: Sequence[SurfaceRect],
    measurer: NoteMeasurer,
    config: LayoutConfig,
    note_x_bounds: tuple[float, float] | None = None,
) -> Iterator[tuple[int, SurfaceRect, bool]]:
    """Yield every legal vertical position on one margin at one scale."""
    if note_x_bounds is None:
        note_x0, note_x1 = _margin_geometry(
            side, target_rect, page_rect, margin_width, config.margin_gap
        )
    else:
        note_x0, note_x1 = note_x_bounds
    note_width = note_x1 - note_x0
    if note_width <= 0.0:
        return

    width, height = measurer.measure(request.content, note_width, scale)
    if (
        not math.isfinite(width)
        or not math.isfinite(height)
        or width <= 0.0
        or height <= 0.0
        or width > note_width
        or height > page_rect.y1 - page_rect.y0
    ):
        return

    target_center_y = (target_rect.y0 + target_rect.y1) / 2.0
    centered_y0 = target_center_y - height / 2.0
    for attempt in range(max(0, config.attempt_budget) + 1):
        proposed_y0 = centered_y0 + _shift_multiplier(attempt) * height
        y0 = max(page_rect.y0, min(proposed_y0, page_rect.y1 - height))
        if y0 >= page_rect.y1 - height * 0.5:
            continue

        note_box = SurfaceRect(
            x0=note_x0,
            y0=y0,
            x1=note_x0 + width,
            y1=y0 + height,
        )
        if not _within_page(note_box, page_rect):
            continue
        if _interval_overlaps((note_box.y0, note_box.y1), side_occupancy, config.overlap_tolerance):
            continue
        if any(
            _rectangles_overlap(note_box, occupied, config.overlap_tolerance)
            for occupied in forbidden_rects
        ):
            continue
        yield attempt, note_box, not math.isclose(y0, centered_y0, abs_tol=1e-9)


def _try_margin_side(
    request: NoteRequest,
    side: _MarginSide,
    target_rect: SurfaceRect,
    page_rect: SurfaceRect,
    margin_width: float,
    scale: float,
    side_occupancy: Sequence[tuple[float, float]],
    forbidden_rects: Sequence[SurfaceRect],
    measurer: NoteMeasurer,
    config: LayoutConfig,
    note_x_bounds: tuple[float, float] | None = None,
) -> tuple[SurfaceRect, bool] | None:
    """Return the first legal margin-side candidate in greedy preference order."""
    candidate = next(
        _iter_margin_side_candidates(
            request=request,
            side=side,
            target_rect=target_rect,
            page_rect=page_rect,
            margin_width=margin_width,
            scale=scale,
            side_occupancy=side_occupancy,
            forbidden_rects=forbidden_rects,
            measurer=measurer,
            config=config,
            note_x_bounds=note_x_bounds,
        ),
        None,
    )
    if candidate is None:
        return None
    _, note_box, shifted = candidate
    return note_box, shifted


def _scale_reduced_warning(annotation_id: str, scale: float) -> AnchorWarning:
    return AnchorWarning(
        annotation_id=annotation_id,
        code=AnchorWarningCode.SCALE_REDUCED,
        detail=f"Reduced note scale to {scale:.2f} after larger geometry did not fit.",
    )


def _skip_unplaceable(annotation_id: str, detail: str) -> SkipRecord:
    return SkipRecord(
        annotation_id=annotation_id,
        reason=SkipReason.UNPLACEABLE,
        detail=detail,
    )


def _run_greedy(
    request_targets: Sequence[tuple[NoteRequest, SurfaceRect]],
    page_rect: SurfaceRect,
    body_occupancy: Sequence[SurfaceRect],
    target_occupancy: tuple[SurfaceRect, ...],
    measurer: NoteMeasurer,
    config: LayoutConfig,
    margin_strips: dict[_MarginSide, tuple[float, float]] | None,
) -> LayoutResult:
    placed: list[ResolvedAnnotation] = []
    skipped: list[SkipRecord] = []
    degradation_flags: list[DegradationFlag] = []
    side_intervals: dict[_MarginSide, list[tuple[float, float]]] = {
        "margin_right": [],
        "margin_left": [],
    }
    note_boxes: list[SurfaceRect] = []

    for request, target_rect in request_targets:
        common_forbidden = tuple(body_occupancy) + target_occupancy + tuple(note_boxes)

        if request.requested_placement in ("inline", "between_lines"):
            inline_forbidden = tuple(body_occupancy) + tuple(note_boxes)
            inline_box = _try_inline(
                request,
                target_rect,
                page_rect,
                inline_forbidden,
                measurer,
                config.overlap_tolerance,
            )
            if inline_box is not None:
                note_boxes.append(inline_box)
                placed.append(
                    ResolvedAnnotation(
                        annotation_id=request.annotation_id,
                        source_locator=request.source_locator,
                        requested_placement=request.requested_placement,
                        resolved_placement=request.requested_placement,
                        anchor=request.anchor,
                        note_box=inline_box,
                        note_scale=1.0,
                        render_seed=request.render_seed,
                        warnings=(),
                    )
                )
                continue

        # Fail closed: without inferred body columns there is no reliable outer
        # margin to place into, so skip rather than fall back to a target-relative
        # margin (which could land a note over the opposite column or off-page).
        # Inline/between_lines placement above is target-local and is exempt.
        if margin_strips is None:
            skipped.append(
                _skip_unplaceable(
                    request.annotation_id,
                    "No body columns were inferred; failing closed rather than "
                    "placing relative to the target.",
                )
            )
            if DegradationFlag.NOTE_SKIPPED_UNFITTABLE not in degradation_flags:
                degradation_flags.append(DegradationFlag.NOTE_SKIPPED_UNFITTABLE)
            continue

        preferred: _MarginSide = (
            "margin_left" if request.requested_placement == "margin_left" else "margin_right"
        )
        opposite: _MarginSide = "margin_left" if preferred == "margin_right" else "margin_right"
        margin_widths = {side: strip[1] - strip[0] for side, strip in margin_strips.items()}
        candidate_sides = [
            side for side in (preferred, opposite) if margin_widths[side] >= config.margin_min_width
        ]
        if not candidate_sides:
            skipped.append(
                _skip_unplaceable(
                    request.annotation_id,
                    "Both page margins are narrower than the configured minimum width.",
                )
            )
            if DegradationFlag.NOTE_SKIPPED_UNFITTABLE not in degradation_flags:
                degradation_flags.append(DegradationFlag.NOTE_SKIPPED_UNFITTABLE)
            continue

        scale = 1.0
        scale_warnings: list[AnchorWarning] = []
        resolved: tuple[_MarginSide, SurfaceRect, bool] | None = None
        while True:
            for side in candidate_sides:
                candidate = _try_margin_side(
                    request=request,
                    side=side,
                    target_rect=target_rect,
                    page_rect=page_rect,
                    margin_width=margin_widths[side],
                    scale=scale,
                    side_occupancy=side_intervals[side],
                    forbidden_rects=common_forbidden,
                    measurer=measurer,
                    config=config,
                    note_x_bounds=(margin_strips or {}).get(side),
                )
                if candidate is not None:
                    note_box, shifted = candidate
                    resolved = side, note_box, shifted
                    break
            if resolved is not None:
                break

            if scale <= config.min_scale + 1e-9:
                break
            next_scale = max(config.min_scale, round(scale - 0.1, 10))
            if next_scale >= scale:
                break
            scale = next_scale
            scale_warnings.append(_scale_reduced_warning(request.annotation_id, scale))

        if resolved is None:
            skipped.append(
                _skip_unplaceable(
                    request.annotation_id,
                    f"No collision-free position fit at or above scale {config.min_scale:.2f}.",
                )
            )
            if DegradationFlag.NOTE_SKIPPED_UNFITTABLE not in degradation_flags:
                degradation_flags.append(DegradationFlag.NOTE_SKIPPED_UNFITTABLE)
            continue

        side, note_box, shifted = resolved
        warnings = list(scale_warnings)
        if side != preferred:
            warnings.append(
                AnchorWarning(
                    annotation_id=request.annotation_id,
                    code=AnchorWarningCode.SIDE_SWITCHED,
                    detail=f"Switched from {preferred} to {side} to find usable space.",
                )
            )
        if shifted:
            warnings.append(
                AnchorWarning(
                    annotation_id=request.annotation_id,
                    code=AnchorWarningCode.SHIFTED,
                    detail=(
                        f"Shifted note top from y={target_rect.y0:.2f} "
                        f"to y={note_box.y0:.2f} to avoid occupied space."
                    ),
                )
            )

        side_intervals[side].append((note_box.y0, note_box.y1))
        note_boxes.append(note_box)
        placed.append(
            ResolvedAnnotation(
                annotation_id=request.annotation_id,
                source_locator=request.source_locator,
                requested_placement=request.requested_placement,
                resolved_placement=side,
                anchor=request.anchor,
                note_box=note_box,
                note_scale=scale,
                render_seed=request.render_seed,
                warnings=tuple(warnings),
            )
        )

    return LayoutResult(
        placed=tuple(placed),
        skipped=tuple(skipped),
        degradation_flags=tuple(degradation_flags),
    )


def _scale_candidates(min_scale: float) -> tuple[float, ...]:
    """Return the greedy scale sequence, including the exact configured minimum."""
    scales: list[float] = []
    scale = 1.0
    while True:
        scales.append(scale)
        if scale <= min_scale + 1e-9:
            break
        next_scale = max(min_scale, round(scale - 0.1, 10))
        if next_scale >= scale:
            break
        scale = next_scale
    return tuple(scales)


def _box_mpt(box: SurfaceRect) -> _page_solver.BoxMpt:
    return (
        _page_solver.q_pt(box.x0),
        _page_solver.q_pt(box.y0),
        _page_solver.q_pt(box.x1),
        _page_solver.q_pt(box.y1),
    )


def _surface_box(box_mpt: _page_solver.BoxMpt) -> SurfaceRect:
    return SurfaceRect(
        x0=box_mpt[0] / 1_000,
        y0=box_mpt[1] / 1_000,
        x1=box_mpt[2] / 1_000,
        y1=box_mpt[3] / 1_000,
    )


def _closest_rect_points(
    first: SurfaceRect, second: SurfaceRect
) -> tuple[tuple[float, float], tuple[float, float]]:
    """Mirror the composer's deterministic closest-edge geometry."""
    first_center_x = (first.x0 + first.x1) / 2.0
    first_center_y = (first.y0 + first.y1) / 2.0
    second_center_x = (second.x0 + second.x1) / 2.0
    second_center_y = (second.y0 + second.y1) / 2.0

    if first.x1 < second.x0:
        first_x, second_x = first.x1, second.x0
    elif second.x1 < first.x0:
        first_x, second_x = first.x0, second.x1
    else:
        shared_x = max(
            max(first.x0, second.x0),
            min(
                (first_center_x + second_center_x) / 2.0,
                min(first.x1, second.x1),
            ),
        )
        first_x = second_x = shared_x

    if first.y1 < second.y0:
        first_y, second_y = first.y1, second.y0
    elif second.y1 < first.y0:
        first_y, second_y = first.y0, second.y1
    else:
        shared_y = max(
            max(first.y0, second.y0),
            min(
                (first_center_y + second_center_y) / 2.0,
                min(first.y1, second.y1),
            ),
        )
        first_y = second_y = shared_y

    return (first_x, first_y), (second_x, second_y)


def _connector_endpoints_mpt(
    note_box: SurfaceRect, request: NoteRequest
) -> tuple[_page_solver.PointMpt | None, _page_solver.PointMpt | None]:
    if request.anchor is None or not request.anchor.quads:
        return None, None

    candidates: list[tuple[float, int, tuple[float, float], tuple[float, float]]] = []
    for index, quad in enumerate(request.anchor.quads):
        points = (quad.ul, quad.ur, quad.lr, quad.ll)
        target_box = SurfaceRect(
            x0=min(point.x for point in points),
            y0=min(point.y for point in points),
            x1=max(point.x for point in points),
            y1=max(point.y for point in points),
        )
        note_point, target_point = _closest_rect_points(note_box, target_box)
        distance = math.hypot(note_point[0] - target_point[0], note_point[1] - target_point[1])
        candidates.append((distance, index, note_point, target_point))

    _, _, note_point, target_point = min(candidates, key=lambda candidate: candidate[:2])
    return (
        (_page_solver.q_pt(note_point[0]), _page_solver.q_pt(note_point[1])),
        (_page_solver.q_pt(target_point[0]), _page_solver.q_pt(target_point[1])),
    )


def _importance(request: NoteRequest) -> int:
    return (8 - ANNOTATION_TYPE_PRIORITY[request.annotation_type]) * 1_001 + _page_solver.q_conf(
        request.confidence
    )


def _prepared_candidate(
    *,
    request: NoteRequest,
    ordinal: int,
    kind: Literal["inline", "margin"],
    note_box: SurfaceRect,
    scale: float,
    side: Literal["left", "right", ""],
    side_switched: bool,
    target_rect: SurfaceRect,
    page_height_mpt: int,
) -> _page_solver.Candidate:
    box_mpt = _box_mpt(note_box)
    connector_a_mpt, connector_b_mpt = _connector_endpoints_mpt(note_box, request)
    displacement_bp = 0
    if kind == "margin":
        ideal_y0 = (target_rect.y0 + target_rect.y1) / 2.0 - (note_box.y1 - note_box.y0) / 2.0
        displacement_bp = _page_solver.ratio(
            abs(box_mpt[1] - _page_solver.q_pt(ideal_y0)), page_height_mpt
        )
    return _page_solver.Candidate(
        note_id=request.annotation_id,
        ordinal=ordinal,
        kind=kind,
        box_mpt=box_mpt,
        scale_bp=_page_solver.q_scale(scale),
        side=side,
        importance=_importance(request),
        displacement_bp=displacement_bp,
        side_switched=side_switched,
        connector_a_mpt=connector_a_mpt,
        connector_b_mpt=connector_b_mpt,
        height_mpt=_page_solver.q_pt(note_box.y1 - note_box.y0),
    )


def _candidates_for_note(
    request: NoteRequest,
    target_rect: SurfaceRect,
    page_rect: SurfaceRect,
    body_occupancy: Sequence[SurfaceRect],
    target_occupancy: tuple[SurfaceRect, ...],
    measurer: NoteMeasurer,
    config: LayoutConfig,
    margin_strips: dict[_MarginSide, tuple[float, float]] | None,
    page_height_mpt: int,
) -> tuple[_page_solver.Candidate, ...]:
    candidates: list[_page_solver.Candidate] = []
    seen: set[tuple[str, int, _page_solver.BoxMpt]] = set()

    if request.requested_placement in ("inline", "between_lines"):
        inline_box = _try_inline(
            request,
            target_rect,
            page_rect,
            body_occupancy,
            measurer,
            config.overlap_tolerance,
        )
        if inline_box is not None:
            inline = _prepared_candidate(
                request=request,
                ordinal=0,
                kind="inline",
                note_box=inline_box,
                scale=1.0,
                side="",
                side_switched=False,
                target_rect=target_rect,
                page_height_mpt=page_height_mpt,
            )
            assert inline.box_mpt is not None
            seen.add((request.requested_placement, inline.scale_bp, inline.box_mpt))
            candidates.append(inline)

    scales = _scale_candidates(config.min_scale)
    candidate_sides: list[_MarginSide] = []
    margin_widths: dict[_MarginSide, float] = {}
    if margin_strips is not None:
        preferred: _MarginSide = (
            "margin_left" if request.requested_placement == "margin_left" else "margin_right"
        )
        opposite: _MarginSide = "margin_left" if preferred == "margin_right" else "margin_right"
        margin_widths = {side: strip[1] - strip[0] for side, strip in margin_strips.items()}
        candidate_sides = [
            side for side in (preferred, opposite) if margin_widths[side] >= config.margin_min_width
        ]

        n_sides = len(candidate_sides)
        n_attempts = max(0, config.attempt_budget) + 1
        static_forbidden = tuple(body_occupancy) + target_occupancy
        for scale_idx, scale in enumerate(scales):
            for side_idx, side in enumerate(candidate_sides):
                for attempt_idx, note_box, _ in _iter_margin_side_candidates(
                    request=request,
                    side=side,
                    target_rect=target_rect,
                    page_rect=page_rect,
                    margin_width=margin_widths[side],
                    scale=scale,
                    side_occupancy=(),
                    forbidden_rects=static_forbidden,
                    measurer=measurer,
                    config=config,
                    note_x_bounds=margin_strips[side],
                ):
                    ordinal = 1 + (
                        scale_idx * n_sides * n_attempts + side_idx * n_attempts + attempt_idx
                    )
                    side_name: Literal["left", "right"] = (
                        "left" if side == "margin_left" else "right"
                    )
                    candidate = _prepared_candidate(
                        request=request,
                        ordinal=ordinal,
                        kind="margin",
                        note_box=note_box,
                        scale=scale,
                        side=side_name,
                        side_switched=side != preferred,
                        target_rect=target_rect,
                        page_height_mpt=page_height_mpt,
                    )
                    assert candidate.box_mpt is not None
                    key = (side, candidate.scale_bp, candidate.box_mpt)
                    if key in seen:
                        continue
                    seen.add(key)
                    candidates.append(candidate)

    skip_ordinal = 1 + len(scales) * len(candidate_sides) * (max(0, config.attempt_budget) + 1)
    candidates.append(
        _page_solver.Candidate(
            note_id=request.annotation_id,
            ordinal=skip_ordinal,
            kind="skip",
            box_mpt=None,
            scale_bp=10_000,
            side="",
            importance=_importance(request),
            displacement_bp=0,
            side_switched=False,
            connector_a_mpt=None,
            connector_b_mpt=None,
            height_mpt=0,
        )
    )
    return tuple(candidates)


def _beam_candidates_conflict(
    first: _page_solver.Candidate,
    second: _page_solver.Candidate,
    tolerance_mpt: int,
) -> bool:
    assert first.box_mpt is not None and second.box_mpt is not None
    first_box = first.box_mpt
    second_box = second.box_mpt
    overlap_x1 = first_box[2] if first_box[2] < second_box[2] else second_box[2]
    overlap_x0 = first_box[0] if first_box[0] > second_box[0] else second_box[0]
    overlap_y1 = first_box[3] if first_box[3] < second_box[3] else second_box[3]
    overlap_y0 = first_box[1] if first_box[1] > second_box[1] else second_box[1]
    horizontal = overlap_x1 - overlap_x0
    vertical = overlap_y1 - overlap_y0
    if horizontal > tolerance_mpt and vertical > tolerance_mpt:
        return True
    return (
        first.kind == "margin"
        and second.kind == "margin"
        and first.side == second.side
        and vertical > tolerance_mpt
    )


def _run_beam(
    request_targets: Sequence[tuple[NoteRequest, SurfaceRect]],
    page_rect: SurfaceRect,
    body_occupancy: Sequence[SurfaceRect],
    target_occupancy: tuple[SurfaceRect, ...],
    measurer: NoteMeasurer,
    config: LayoutConfig,
    margin_strips: dict[_MarginSide, tuple[float, float]] | None,
) -> LayoutResult:
    page_height_mpt = _page_solver.q_pt(page_rect.y1 - page_rect.y0)
    candidates_per_note = tuple(
        _candidates_for_note(
            request=request,
            target_rect=target_rect,
            page_rect=page_rect,
            body_occupancy=body_occupancy,
            target_occupancy=target_occupancy,
            measurer=measurer,
            config=config,
            margin_strips=margin_strips,
            page_height_mpt=page_height_mpt,
        )
        for request, target_rect in request_targets
    )
    solver_config = _page_solver.SolverConfig(
        beam_width=config.beam_width,
        min_scale_bp=_page_solver.q_scale(config.min_scale),
        page_diag_mpt=_page_solver.q_pt(
            math.hypot(page_rect.x1 - page_rect.x0, page_rect.y1 - page_rect.y0)
        ),
        page_height_mpt=page_height_mpt,
    )
    tolerance_mpt = _page_solver.q_pt(config.overlap_tolerance)
    solved = _page_solver.solve(
        candidates_per_note,
        solver_config,
        partial(_beam_candidates_conflict, tolerance_mpt=tolerance_mpt),
    )

    placed: list[ResolvedAnnotation] = []
    skipped: list[SkipRecord] = []
    degradation_flags: list[DegradationFlag] = []
    for (request, target_rect), candidate in zip(request_targets, solved.chosen, strict=True):
        if candidate.kind == "skip":
            if margin_strips is None:
                detail = (
                    "No body columns were inferred; failing closed rather than "
                    "placing relative to the target."
                )
            else:
                margin_widths = {side: strip[1] - strip[0] for side, strip in margin_strips.items()}
                if all(width < config.margin_min_width for width in margin_widths.values()):
                    detail = "Both page margins are narrower than the configured minimum width."
                else:
                    detail = (
                        f"No collision-free position fit at or above scale {config.min_scale:.2f}."
                    )
            skipped.append(_skip_unplaceable(request.annotation_id, detail))
            if DegradationFlag.NOTE_SKIPPED_UNFITTABLE not in degradation_flags:
                degradation_flags.append(DegradationFlag.NOTE_SKIPPED_UNFITTABLE)
            continue

        assert candidate.box_mpt is not None
        note_box = _surface_box(candidate.box_mpt)
        scale = candidate.scale_bp / 10_000
        if candidate.kind == "inline":
            resolved_placement: Placement = request.requested_placement
            warnings: list[AnchorWarning] = []
        else:
            resolved_placement = "margin_left" if candidate.side == "left" else "margin_right"
            warnings = []
            if candidate.scale_bp < 10_000:
                warnings.append(_scale_reduced_warning(request.annotation_id, scale))

            preferred: _MarginSide = (
                "margin_left" if request.requested_placement == "margin_left" else "margin_right"
            )
            if candidate.side_switched:
                warnings.append(
                    AnchorWarning(
                        annotation_id=request.annotation_id,
                        code=AnchorWarningCode.SIDE_SWITCHED,
                        detail=(
                            f"Switched from {preferred} to {resolved_placement} "
                            "to find usable space."
                        ),
                    )
                )

            if candidate.displacement_bp > 0:
                warnings.append(
                    AnchorWarning(
                        annotation_id=request.annotation_id,
                        code=AnchorWarningCode.SHIFTED,
                        detail=(
                            f"Shifted note top from y={target_rect.y0:.2f} "
                            f"to y={note_box.y0:.2f} to avoid occupied space."
                        ),
                    )
                )

        placed.append(
            ResolvedAnnotation(
                annotation_id=request.annotation_id,
                source_locator=request.source_locator,
                requested_placement=request.requested_placement,
                resolved_placement=resolved_placement,
                anchor=request.anchor,
                note_box=note_box,
                note_scale=scale,
                render_seed=request.render_seed,
                warnings=tuple(warnings),
            )
        )

    return LayoutResult(
        placed=tuple(placed),
        skipped=tuple(skipped),
        degradation_flags=tuple(degradation_flags),
    )


def run_layout(
    requests: Sequence[NoteRequest],
    page_rect: SurfaceRect,
    body_occupancy: Sequence[SurfaceRect],
    measurer: NoteMeasurer,
    config: LayoutConfig = LayoutConfig(),  # noqa: B008 - pinned public API
    *,
    body_columns: Sequence[TextColumn] = (),
) -> LayoutResult:
    """Place margin annotations by priority using occupancy-based layout."""
    ordered_requests = sorted(
        requests,
        key=lambda request: (
            ANNOTATION_TYPE_PRIORITY[request.annotation_type],
            -request.confidence,
            request.annotation_id,
        ),
    )
    request_targets = tuple(
        (request, _target_rect(request, page_rect)) for request in ordered_requests
    )
    target_occupancy = tuple(target_rect for _, target_rect in request_targets)

    if body_columns:
        right_strip_x0 = max(column.x1 for column in body_columns) + config.margin_gap
        right_strip_x1 = page_rect.x1 - config.page_edge_pad
        left_strip_x1 = min(column.x0 for column in body_columns) - config.margin_gap
        left_strip_x0 = page_rect.x0 + config.page_edge_pad
        margin_strips: dict[_MarginSide, tuple[float, float]] | None = {
            "margin_right": (right_strip_x0, right_strip_x1),
            "margin_left": (left_strip_x0, left_strip_x1),
        }
    else:
        margin_strips = None

    if config.solver == "beam":
        return _run_beam(
            request_targets=request_targets,
            page_rect=page_rect,
            body_occupancy=body_occupancy,
            target_occupancy=target_occupancy,
            measurer=measurer,
            config=config,
            margin_strips=margin_strips,
        )
    return _run_greedy(
        request_targets=request_targets,
        page_rect=page_rect,
        body_occupancy=body_occupancy,
        target_occupancy=target_occupancy,
        measurer=measurer,
        config=config,
        margin_strips=margin_strips,
    )
