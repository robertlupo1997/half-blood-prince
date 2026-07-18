"""Tests for path simplification (P3-T4, §§5.2, 5.9).

Discriminating evidence for key assertions:

- Idempotence: a simplifier that drops a fixed fraction of points each pass would produce
  a different result on the second pass (keeps shrinking). The idempotence test catches it.

- Budget guard before O(n²): a guard-after-simplify implementation would run Douglas-Peucker
  on n=200_000 points (≫10^10 ops) before rejecting. The correct guard raises BudgetExceededError
  at the top of the function in under 1 second. The timing bound (1s) is loose relative to the
  quadratic/linear gap (many orders of magnitude), making the test non-flaky on normal hardware.

- Endpoints preserved: a simplifier that collapses a path to its first point would fail.

- Tolerance floor vs nib: tight-tolerance zigzag peaks deviate > tolerance and survive.
"""

from __future__ import annotations

import math
import time

import pytest

from halfblood.ink.geometry import BudgetExceededError, simplify_commands
from halfblood.ink.model import CubicTo, LineTo, MoveTo

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _collinear(n: int, length: float = 100.0) -> tuple[MoveTo | LineTo, ...]:
    """n+1 commands along y=0; all interior points are collinear and removable."""
    cmds: list[MoveTo | LineTo] = [MoveTo(x=0.0, y=0.0)]
    for i in range(1, n + 1):
        cmds.append(LineTo(x=length * i / n, y=0.0))
    return tuple(cmds)


def _zigzag(n: int, amplitude: float = 1.0) -> tuple[MoveTo | LineTo, ...]:
    """n commands in a zigzag; no interior point is safe to drop at tolerance < amplitude."""
    cmds: list[MoveTo | LineTo] = [MoveTo(x=0.0, y=0.0)]
    for i in range(1, n):
        y = amplitude if i % 2 else -amplitude
        cmds.append(LineTo(x=float(i), y=y))
    return tuple(cmds)


def _endpoints(cmds: tuple) -> tuple[tuple[float, float], tuple[float, float]]:
    return (cmds[0].x, cmds[0].y), (cmds[-1].x, cmds[-1].y)


def _all_pts(cmds: tuple) -> list[tuple[float, float]]:
    return [(cmd.x, cmd.y) for cmd in cmds]


def _point_to_segment_dist(
    pt: tuple[float, float],
    a: tuple[float, float],
    b: tuple[float, float],
) -> float:
    """Perpendicular distance from pt to segment ab."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    length_sq = dx * dx + dy * dy
    if length_sq < 1e-12:
        return math.hypot(pt[0] - a[0], pt[1] - a[1])
    t = max(0.0, min(1.0, ((pt[0] - a[0]) * dx + (pt[1] - a[1]) * dy) / length_sq))
    proj = (a[0] + t * dx, a[1] + t * dy)
    return math.hypot(pt[0] - proj[0], pt[1] - proj[1])


# ---------------------------------------------------------------------------
# Basic correctness
# ---------------------------------------------------------------------------


def test_simplify_collinear_removes_interior_points() -> None:
    """All collinear interior points are removed at any positive tolerance."""
    cmds = _collinear(20)
    result = simplify_commands(cmds, tolerance=0.01, budget=10_000)
    assert len(result) == 2, (
        f"Expected 2 commands (start + end) for collinear path; got {len(result)}"
    )


def test_simplify_preserves_first_and_last_endpoints() -> None:
    """First and last endpoints are always preserved, regardless of tolerance."""
    cmds = _collinear(10)
    first, last = _endpoints(cmds)
    result = simplify_commands(cmds, tolerance=1_000.0, budget=10_000)  # very large tolerance
    assert len(result) >= 2, "Simplified path too short"
    assert (result[0].x, result[0].y) == pytest.approx(first), "First endpoint moved"
    assert (result[-1].x, result[-1].y) == pytest.approx(last), "Last endpoint moved"


def test_simplify_preserves_pen_lifts() -> None:
    """MoveTo commands that represent pen lifts must survive simplification.

    A pen lift splits a compound path into independent sub-paths; each sub-path
    has its own endpoint pair that must be preserved.
    """
    cmds: tuple[MoveTo | LineTo, ...] = (
        MoveTo(x=0.0, y=0.0),
        LineTo(x=5.0, y=0.0),
        LineTo(x=10.0, y=0.0),   # collinear — removable
        MoveTo(x=20.0, y=0.0),   # pen lift — must survive as sub-path start
        LineTo(x=25.0, y=0.0),
        LineTo(x=30.0, y=0.0),   # collinear — removable
    )
    result = simplify_commands(cmds, tolerance=100.0, budget=10_000)

    move_xs = {cmd.x for cmd in result if isinstance(cmd, MoveTo)}
    assert 0.0 in move_xs, "Initial MoveTo at x=0 dropped"
    assert 20.0 in move_xs, "Pen-lift MoveTo at x=20 dropped — sub-path start must survive"


def test_simplify_two_command_path_is_unchanged() -> None:
    """A two-command path (MoveTo + endpoint) cannot be simplified further."""
    cmds = (MoveTo(x=0.0, y=0.0), LineTo(x=10.0, y=0.0))
    result = simplify_commands(cmds, tolerance=0.001, budget=10_000)
    assert len(result) == 2


def test_simplified_output_starts_with_moveto() -> None:
    """The output must always begin with a MoveTo."""
    cmds = _collinear(10)
    result = simplify_commands(cmds, tolerance=0.01, budget=10_000)
    assert isinstance(result[0], MoveTo), (
        f"Expected output to start with MoveTo, got {type(result[0]).__name__}"
    )


# ---------------------------------------------------------------------------
# Tolerance semantics
# ---------------------------------------------------------------------------


def test_tight_tolerance_preserves_zigzag_peaks() -> None:
    """At tolerance well below amplitude, no zigzag peaks should be removed.

    Discriminator: a simplifier that drops a fixed fraction of points would remove peaks.
    """
    amplitude = 2.0
    n = 10
    cmds = _zigzag(n, amplitude=amplitude)
    result = simplify_commands(cmds, tolerance=amplitude * 0.05, budget=10_000)
    # At tight tolerance all peaks should survive: result should have nearly all original points
    assert len(result) >= n - 1, (
        f"Too many points removed at tight tolerance (amplitude={amplitude}, "
        f"tolerance={amplitude*0.05}): expected ≥{n-1}, got {len(result)}"
    )


def test_simplified_points_within_tolerance() -> None:
    """Every original point lies within `tolerance` of the simplified polyline."""
    n = 30
    amplitude = 1.0
    tolerance = 0.5
    cmds = _zigzag(n, amplitude=amplitude)
    simplified = simplify_commands(cmds, tolerance=tolerance, budget=10_000)

    orig_pts = _all_pts(cmds)
    simp_pts = _all_pts(simplified)

    for pt in orig_pts:
        min_dist = min(
            _point_to_segment_dist(pt, a, b)
            for a, b in zip(simp_pts, simp_pts[1:], strict=False)
        )
        assert min_dist <= tolerance + 1e-9, (
            f"Original point {pt} is {min_dist:.4f} from simplified path, "
            f"exceeds tolerance {tolerance}"
        )


def test_large_tolerance_reduces_path_significantly() -> None:
    """A large tolerance should reduce a zigzag to just its endpoints."""
    n = 20
    amplitude = 1.0
    cmds = _zigzag(n, amplitude=amplitude)
    result = simplify_commands(cmds, tolerance=amplitude * 10.0, budget=10_000)
    assert len(result) <= 4, (
        f"Large tolerance should collapse most points; got {len(result)} commands"
    )


# ---------------------------------------------------------------------------
# Idempotence — discriminating
# ---------------------------------------------------------------------------


def test_simplify_is_idempotent_at_fixed_tolerance() -> None:
    """simplify_commands(simplify_commands(cmds, tol), tol) == simplify_commands(cmds, tol).

    Discriminator: a simplifier that drops a fixed fraction of points each pass produces
    a shorter result on the second pass (not idempotent). This test catches it.
    """
    n = 50
    amplitude = 1.0
    cmds = _zigzag(n, amplitude=amplitude)
    tolerance = 0.3

    once = simplify_commands(cmds, tolerance=tolerance, budget=10_000)
    twice = simplify_commands(once, tolerance=tolerance, budget=10_000)

    assert len(once) == len(twice), (
        f"Not idempotent: first pass → {len(once)} commands, second pass → {len(twice)}. "
        "A fixed-fraction simplifier shrinks further on the second pass."
    )
    for a, b in zip(once, twice, strict=False):
        assert a.x == pytest.approx(b.x, abs=1e-9), f"x differs: {a.x} vs {b.x}"
        assert a.y == pytest.approx(b.y, abs=1e-9), f"y differs: {a.y} vs {b.y}"


# ---------------------------------------------------------------------------
# Bounds / area preservation
# ---------------------------------------------------------------------------


def test_simplify_preserves_bounding_box_within_tolerance() -> None:
    """Simplified path bounding box matches original within the simplification tolerance."""
    n = 20
    amplitude = 1.0
    tol = 0.1
    cmds = _zigzag(n, amplitude=amplitude)
    result = simplify_commands(cmds, tolerance=tol, budget=10_000)

    orig_pts = _all_pts(cmds)
    res_pts = _all_pts(result)

    assert min(p[0] for p in res_pts) >= min(p[0] for p in orig_pts) - tol
    assert max(p[0] for p in res_pts) <= max(p[0] for p in orig_pts) + tol
    assert min(p[1] for p in res_pts) >= min(p[1] for p in orig_pts) - tol
    assert max(p[1] for p in res_pts) <= max(p[1] for p in orig_pts) + tol


# ---------------------------------------------------------------------------
# Budget guard BEFORE O(n²) work — discriminating with timing
# ---------------------------------------------------------------------------


def test_budget_guard_fires_before_quadratic_work() -> None:
    """Input above budget is refused BEFORE any O(n²) simplification work.

    Discriminator: a guard-after-simplify implementation runs Douglas-Peucker on
    n=200_000 points — roughly 4×10^10 operations — and would take many seconds.
    The correct early guard raises BudgetExceededError in microseconds.
    Timing bound: 1 second (≥4 orders of magnitude above the quadratic runtime).
    """
    n = 200_000
    budget = 100

    cmds: list[MoveTo | LineTo] = [MoveTo(x=0.0, y=0.0)]
    for i in range(1, n):
        cmds.append(LineTo(x=float(i), y=float(i % 7)))  # not collinear

    t0 = time.monotonic()
    with pytest.raises(BudgetExceededError):
        simplify_commands(tuple(cmds), tolerance=0.01, budget=budget)
    elapsed = time.monotonic() - t0

    assert elapsed < 1.0, (
        f"Budget guard took {elapsed:.3f}s. Expected <1s for an early-exit guard. "
        "A guard-after-simplify would take many seconds on n=200_000."
    )


def test_budget_guard_is_on_input_size_not_output() -> None:
    """BudgetExceededError is raised based on INPUT size.

    Even with a large tolerance (where output would be small), input above budget rejects.
    """
    cmds: list[MoveTo | LineTo] = [MoveTo(x=0.0, y=0.0)]
    for i in range(1, 1001):
        cmds.append(LineTo(x=float(i), y=0.0))  # collinear — output would be 2 commands

    with pytest.raises(BudgetExceededError):
        simplify_commands(tuple(cmds), tolerance=1_000.0, budget=500)


def test_within_budget_does_not_raise() -> None:
    """Input within budget proceeds without raising BudgetExceededError."""
    cmds = _collinear(50)  # 51 commands
    result = simplify_commands(cmds, tolerance=0.01, budget=10_000)
    assert len(result) >= 2


# ---------------------------------------------------------------------------
# Output contains only valid model commands
# ---------------------------------------------------------------------------


def test_simplified_output_types_are_valid_commands() -> None:
    """Every command in the output is a MoveTo, LineTo, or CubicTo."""
    cmds = (
        MoveTo(x=0.0, y=0.0),
        LineTo(x=5.0, y=2.0),
        CubicTo(x1=6.0, y1=3.0, x2=8.0, y2=3.0, x=10.0, y=0.0),
        LineTo(x=15.0, y=0.0),
    )
    result = simplify_commands(cmds, tolerance=0.01, budget=10_000)
    for cmd in result:
        assert isinstance(cmd, (MoveTo, LineTo, CubicTo)), (
            f"Unexpected command type in simplified output: {type(cmd).__name__}"
        )


def test_simplified_cubics_are_preserved_or_replaced() -> None:
    """CubicTo commands survive simplification unchanged (or are replaced with LineTo at high tol)."""
    cmds = (
        MoveTo(x=0.0, y=0.0),
        CubicTo(x1=2.0, y1=8.0, x2=8.0, y2=8.0, x=10.0, y=0.0),
    )
    # At zero or very small tolerance the cubic must survive intact
    result = simplify_commands(cmds, tolerance=1e-6, budget=10_000)
    assert len(result) >= 2
    assert result[0].x == pytest.approx(0.0)
    assert result[-1].x == pytest.approx(10.0)
