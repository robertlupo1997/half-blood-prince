"""Pure, deterministic page-level candidate solver.

The layout engine owns candidate generation and hard geometry checks.  This module only
scores already-quantized candidates and searches for a compatible assignment.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Literal, TypeAlias

PointMpt: TypeAlias = tuple[int, int]
BoxMpt: TypeAlias = tuple[int, int, int, int]
Score: TypeAlias = tuple[int, int, int, tuple[int, ...]]


@dataclass(frozen=True)
class Candidate:
    """One fully prepared placement choice for a note."""

    note_id: str
    ordinal: int
    kind: Literal["inline", "margin", "skip"]
    box_mpt: BoxMpt | None
    scale_bp: int
    side: Literal["left", "right", ""]
    importance: int
    displacement_bp: int
    side_switched: bool
    connector_a_mpt: PointMpt | None
    connector_b_mpt: PointMpt | None
    height_mpt: int


@dataclass(frozen=True, kw_only=True)
class SolverConfig:
    """Integer-only constants controlling scoring and beam retention."""

    beam_width: int = 128
    min_scale_bp: int
    page_diag_mpt: int
    page_height_mpt: int

    def __post_init__(self) -> None:
        if self.beam_width <= 0:
            raise ValueError("beam_width must be positive")
        if not 0 <= self.min_scale_bp <= 10_000:
            raise ValueError("min_scale_bp must be between 0 and 10000")
        if self.page_diag_mpt <= 0:
            raise ValueError("page_diag_mpt must be positive")
        if self.page_height_mpt <= 0:
            raise ValueError("page_height_mpt must be positive")


@dataclass(frozen=True)
class SolverResult:
    """The winning choice for every input note, in input order."""

    chosen: tuple[Candidate, ...]


@dataclass(frozen=True)
class _State:
    """Incremental integer scoring state for one partial assignment."""

    chosen: tuple[Candidate, ...] = ()
    omitted_count: int = 0
    omitted_importance: int = 0
    local_soft_cost: int = 0
    connectors: tuple[Candidate, ...] = ()
    crossing_importance: int = 0
    left_load_mpt: int = 0
    right_load_mpt: int = 0
    margin_count: int = 0
    margin_importance: int = 0
    assignment_key: tuple[int, ...] = ()


def _quantize(value: float, units: int) -> int:
    """Apply Python's half-even rounding after scaling by ``units``."""

    if not math.isfinite(value):
        raise ValueError("cannot quantize a non-finite value")
    scaled = value * units
    if not math.isfinite(scaled):
        raise ValueError("quantized value is outside the finite range")
    return round(scaled)


def q_pt(value: float) -> int:
    """Quantize points to integer millipoints using half-even rounding."""

    return _quantize(value, 1_000)


def q_scale(value: float) -> int:
    """Quantize a scale to integer basis points using half-even rounding."""

    return _quantize(value, 10_000)


def q_conf(value: float) -> int:
    """Quantize confidence to integer thousandths using half-even rounding."""

    return _quantize(value, 1_000)


def ratio(a: int, b: int) -> int:
    """Return ``a / b`` in basis points, rounded with integer arithmetic."""

    if b <= 0:
        raise ValueError("ratio denominator must be positive")
    return (10_000 * a + b // 2) // b


def _orientation(a: PointMpt, b: PointMpt, c: PointMpt) -> int:
    """Return the signed twice-area of triangle ``a``, ``b``, ``c``."""

    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def segments_cross(a1: PointMpt, a2: PointMpt, b1: PointMpt, b2: PointMpt) -> bool:
    """Return whether two integer segments have a proper interior intersection."""

    ab1 = _orientation(a1, a2, b1)
    ab2 = _orientation(a1, a2, b2)
    ba1 = _orientation(b1, b2, a1)
    ba2 = _orientation(b1, b2, a2)
    return ((ab1 > 0 and ab2 < 0) or (ab1 < 0 and ab2 > 0)) and (
        (ba1 > 0 and ba2 < 0) or (ba1 < 0 and ba2 > 0)
    )


def _clamp_bp(value: int) -> int:
    return min(10_000, max(0, value))


def _scale_cost_bp(scale_bp: int, min_scale_bp: int) -> int:
    loss = max(0, 10_000 - scale_bp)
    maximum_loss = 10_000 - min_scale_bp
    if maximum_loss == 0:
        return 0 if loss == 0 else 10_000
    return _clamp_bp(ratio(loss * loss, maximum_loss * maximum_loss))


def _connector_length_cost_bp(candidate: Candidate, page_diag_mpt: int) -> int:
    if candidate.connector_a_mpt is None or candidate.connector_b_mpt is None:
        return 0
    dx = candidate.connector_b_mpt[0] - candidate.connector_a_mpt[0]
    dy = candidate.connector_b_mpt[1] - candidate.connector_a_mpt[1]
    length_mpt = math.isqrt(dx * dx + dy * dy)
    return _clamp_bp(ratio(length_mpt, page_diag_mpt))


def _candidate_local_soft_cost(candidate: Candidate, cfg: SolverConfig) -> int:
    """Return the candidate-local weighted soft cost before importance."""

    scale_cost = _scale_cost_bp(candidate.scale_bp, cfg.min_scale_bp)
    connector_length_cost = _connector_length_cost_bp(candidate, cfg.page_diag_mpt)
    displacement_cost = _clamp_bp(candidate.displacement_bp)
    side_switch_cost = 10_000 if candidate.side_switched else 0
    return (
        1_000 * scale_cost
        + 50 * connector_length_cost
        + 100 * displacement_cost
        + 150 * side_switch_cost
    )


def _has_connector(candidate: Candidate) -> bool:
    return candidate.connector_a_mpt is not None and candidate.connector_b_mpt is not None


def _connectors_cross(first: Candidate, second: Candidate) -> bool:
    if (
        first.connector_a_mpt is None
        or first.connector_b_mpt is None
        or second.connector_a_mpt is None
        or second.connector_b_mpt is None
    ):
        return False
    return segments_cross(
        first.connector_a_mpt,
        first.connector_b_mpt,
        second.connector_a_mpt,
        second.connector_b_mpt,
    )


def _extend_state(state: _State, candidate: Candidate, cfg: SolverConfig) -> _State:
    chosen = state.chosen + (candidate,)
    assignment_key = state.assignment_key + (candidate.ordinal,)
    if candidate.kind == "skip":
        return _State(
            chosen=chosen,
            omitted_count=state.omitted_count + 1,
            omitted_importance=state.omitted_importance + candidate.importance,
            local_soft_cost=state.local_soft_cost,
            connectors=state.connectors,
            crossing_importance=state.crossing_importance,
            left_load_mpt=state.left_load_mpt,
            right_load_mpt=state.right_load_mpt,
            margin_count=state.margin_count,
            margin_importance=state.margin_importance,
            assignment_key=assignment_key,
        )

    local_soft_cost = state.local_soft_cost + candidate.importance * _candidate_local_soft_cost(
        candidate, cfg
    )

    connectors = state.connectors
    crossing_importance = state.crossing_importance
    if _has_connector(candidate):
        for prior in connectors:
            if _connectors_cross(candidate, prior):
                crossing_importance += candidate.importance + prior.importance
        connectors += (candidate,)

    left_load_mpt = state.left_load_mpt
    right_load_mpt = state.right_load_mpt
    margin_count = state.margin_count
    margin_importance = state.margin_importance
    if candidate.kind == "margin":
        if candidate.side == "left":
            left_load_mpt += candidate.height_mpt
        elif candidate.side == "right":
            right_load_mpt += candidate.height_mpt
        margin_count += 1
        margin_importance += candidate.importance

    return _State(
        chosen=chosen,
        omitted_count=state.omitted_count,
        omitted_importance=state.omitted_importance,
        local_soft_cost=local_soft_cost,
        connectors=connectors,
        crossing_importance=crossing_importance,
        left_load_mpt=left_load_mpt,
        right_load_mpt=right_load_mpt,
        margin_count=margin_count,
        margin_importance=margin_importance,
        assignment_key=assignment_key,
    )


def _state_score(state: _State) -> Score:
    connector_count = len(state.connectors)
    crossing_cost = 0
    if connector_count > 1:
        # Each crossing contributes the importance of both endpoints. Dividing by the
        # number of possible partners gives every connector a 0..10000 crossing fraction.
        crossing_cost = 500 * ratio(state.crossing_importance, connector_count - 1)

    lane_cost = 0
    total_lane_load = state.left_load_mpt + state.right_load_mpt
    if state.margin_count > 1 and total_lane_load > 0:
        unevenness_bp = ratio(
            abs(state.left_load_mpt - state.right_load_mpt), total_lane_load
        )
        lane_cost = 25 * unevenness_bp * state.margin_importance

    return (
        state.omitted_count,
        state.omitted_importance,
        state.local_soft_cost + crossing_cost + lane_cost,
        state.assignment_key,
    )


def score_assignment(chosen: Sequence[Candidate], cfg: SolverConfig) -> Score:
    """Return the deterministic lexicographic score for an assignment."""

    state = _State()
    for candidate in chosen:
        state = _extend_state(state, candidate, cfg)
    return _state_score(state)


def _candidate_conflicts(
    candidate: Candidate,
    chosen: tuple[Candidate, ...],
    conflict: Callable[[Candidate, Candidate], bool],
) -> bool:
    if candidate.kind == "skip":
        return False
    return any(
        prior.kind != "skip" and conflict(candidate, prior)
        for prior in chosen
    )


def solve(
    candidates_per_note: Sequence[Sequence[Candidate]],
    cfg: SolverConfig,
    conflict: Callable[[Candidate, Candidate], bool],
) -> SolverResult:
    """Choose one candidate per note with a bounded deterministic beam search."""

    for candidates in candidates_per_note:
        if not any(candidate.kind == "skip" for candidate in candidates):
            raise ValueError("every note must provide a skip candidate")

    states: tuple[_State, ...] = (_State(),)
    for candidates in candidates_per_note:
        expanded: list[_State] = []
        for state in states:
            for candidate in candidates:
                if _candidate_conflicts(candidate, state.chosen, conflict):
                    continue
                expanded.append(_extend_state(state, candidate, cfg))

        # A prevalidated skip candidate makes this non-empty for every retained state.
        expanded.sort(key=lambda state: (_state_score(state), state.assignment_key))
        states = tuple(expanded[: cfg.beam_width])

    if not states:
        # Only reachable for an invalid non-positive beam width, guarded by SolverConfig.
        raise ValueError("solver produced no feasible assignment")
    return SolverResult(chosen=states[0].chosen)


__all__ = [
    "Candidate",
    "SolverConfig",
    "SolverResult",
    "q_conf",
    "q_pt",
    "q_scale",
    "ratio",
    "score_assignment",
    "segments_cross",
    "solve",
]
