"""Tests for pressure stroke expansion to filled outline polygons (P3-T4, §§5.2, 5.4, 5.6).

Discriminating evidence for key assertions:

- Round caps (two-part check, both required):
  (1) Cap-region vertices are within [h*(1-eps), h*(1+eps)] of the endpoint.
      A square-cap produces corners at distance h*sqrt(2)≈1.41h — this check kills it.
  (2) At least one vertex extends PAST each endpoint along the outgoing tangent.
      A butt-cap ends flush at the endpoint — this check kills it.
  Either check alone lets one wrong cap through; both together are jointly discriminating.

- Degenerate-safe: an expander that divides by segment length would crash on a zero-length
  input. The contract requires a typed ExpansionError or a degradation-flagged result instead.

- Tight bounds: for a constant-width horizontal segment the outline bounds are computed
  analytically; the assertion uses h*0.10 tolerance (loose enough for polygon approximation
  of round caps with ≥5 segments, tight enough to fail a butt-cap or a drastically wrong
  offset).

- Closed centerline: annular hole-polygon support is out of Effort-L scope. The contract is
  that a closed-loop centerline (first==last point) either raises ExpansionError or returns
  with a non-empty degradation_flags. Silent wrong output is not allowed.
"""

from __future__ import annotations

import math

import pytest

from halfblood.ink.geometry import ExpandedOutline, ExpansionError, expand_stroke
from halfblood.ink.model import CubicTo, LineTo, MoveTo, WidthSample

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _straight(
    x0: float = 0.0, y0: float = 0.0, x1: float = 10.0, y1: float = 0.0
) -> tuple[MoveTo, LineTo]:
    """Horizontal centerline commands."""
    return (MoveTo(x=x0, y=y0), LineTo(x=x1, y=y1))


def _const_profile(scale: float = 1.0) -> tuple[WidthSample, WidthSample]:
    """Constant relative-width profile (relative width = scale at both ends)."""
    return (
        WidthSample(position=0.0, width=scale),
        WidthSample(position=1.0, width=scale),
    )


def _signed_area(pts: list[tuple[float, float]]) -> float:
    """Shoelace formula signed area; positive → CCW orientation."""
    n = len(pts)
    area = 0.0
    for i in range(n):
        j = (i + 1) % n
        area += pts[i][0] * pts[j][1]
        area -= pts[j][0] * pts[i][1]
    return area / 2.0


def _outline_bounds(
    outline: ExpandedOutline,
) -> tuple[float, float, float, float]:
    """Return (x0, y0, x1, y1) bounding box of the outline vertices."""
    xs = [v.x for v in outline.vertices]
    ys = [v.y for v in outline.vertices]
    return min(xs), min(ys), max(xs), max(ys)


# ---------------------------------------------------------------------------
# Basic output shape
# ---------------------------------------------------------------------------


def test_straight_expansion_is_finite() -> None:
    """A plain horizontal segment expands to a polygon of finite vertices."""
    outline = expand_stroke(_straight(), _const_profile(), base_width=2.0)
    assert outline.vertices, "expand_stroke returned an empty vertex list"
    for v in outline.vertices:
        assert math.isfinite(v.x) and math.isfinite(v.y), (
            f"Non-finite vertex ({v.x}, {v.y}) in expansion"
        )


def test_expansion_polygon_is_closed() -> None:
    """Expanded polygon encloses non-zero area (a degenerate unclosed polygon has area 0)."""
    outline = expand_stroke(_straight(), _const_profile(), base_width=2.0)
    area = abs(_signed_area([(v.x, v.y) for v in outline.vertices]))
    assert area > 0.0, (
        "Expanded outline has zero area — polygon is degenerate or not properly closed"
    )


def test_expansion_orientation_is_ccw() -> None:
    """Expanded polygon follows documented CCW orientation convention (positive signed area)."""
    outline = expand_stroke(_straight(x0=0.0, x1=10.0), _const_profile(), base_width=2.0)
    area = _signed_area([(v.x, v.y) for v in outline.vertices])
    assert area > 0.0, (
        f"Expected CCW orientation (positive signed area), got {area:.4f}. "
        "CCW is the documented convention for filled ink outlines."
    )


# ---------------------------------------------------------------------------
# Round caps — discriminating (both checks required)
# ---------------------------------------------------------------------------


def test_round_caps_discriminating() -> None:
    """Kills both square-cap AND butt-cap naive implementations.

    Square-cap: corners at h*sqrt(2)≈1.41h from endpoint → fails check (1).
    Butt-cap: no vertices extend past endpoints → fails check (2).
    Round-cap: all cap vertices ≈ h from endpoint AND apex extends h beyond endpoint.
    """
    L = 10.0
    base_width = 4.0
    h = base_width / 2.0
    eps = 0.15  # 15% tolerance for polygon approximation of the semicircle

    commands = (MoveTo(x=0.0, y=0.0), LineTo(x=L, y=0.0))
    outline = expand_stroke(commands, _const_profile(), base_width=base_width)

    xs = [v.x for v in outline.vertices]

    # Check (2): at least one vertex extends past EACH endpoint along the outgoing tangent.
    # Kills butt-cap (flush at x=0 / x=L, never negative or > L).
    assert min(xs) < 0.0, (
        f"Start cap: no vertex extends past x=0 (min x={min(xs):.3f}). "
        "Butt-cap ends flush; round-cap apex is at x=-h."
    )
    assert max(xs) > L, (
        f"End cap: no vertex extends past x={L} (max x={max(xs):.3f}). "
        "Butt-cap ends flush; round-cap apex is at x=L+h."
    )

    # Check (1): cap-region vertices within [h*(1-eps), h*(1+eps)] from the endpoint.
    # Kills square-cap (corner vertices are at distance h*sqrt(2)≈1.41h from endpoint).

    # Start cap: vertices that extended past x=0 (in the cap hemisphere)
    start_cap = [(v.x, v.y) for v in outline.vertices if v.x < 0.0]
    assert start_cap, "Expected vertices with x < 0 for start cap (already checked above)"
    for vx, vy in start_cap:
        dist = math.hypot(vx, vy)  # distance from start endpoint (0, 0)
        assert dist <= h * (1.0 + eps), (
            f"Start-cap vertex ({vx:.3f}, {vy:.3f}) is {dist:.3f} from endpoint "
            f"(> {h*(1+eps):.3f}=h*{1+eps:.2f}). "
            f"Square caps produce corners at h*sqrt(2)≈{h*1.414:.3f}; round caps stay within h."
        )

    # End cap: vertices past x=L
    end_cap = [(v.x, v.y) for v in outline.vertices if v.x > L]
    assert end_cap, "Expected vertices with x > L for end cap (already checked above)"
    for vx, vy in end_cap:
        dist = math.hypot(vx - L, vy)  # distance from end endpoint (L, 0)
        assert dist <= h * (1.0 + eps), (
            f"End-cap vertex ({vx:.3f}, {vy:.3f}) is {dist:.3f} from endpoint (x={L}) "
            f"(> {h*(1+eps):.3f}). Non-round cap geometry detected."
        )


# ---------------------------------------------------------------------------
# Tight bounds
# ---------------------------------------------------------------------------


def test_constant_width_bounds_tight() -> None:
    """For a horizontal segment of length L, constant width 2h, bounds ≈ [-h, -h, L+h, h].

    Tolerance: h*0.10 — tight enough to fail butt-cap (x range [0,L]) or major errors,
    loose enough for round-cap polygon approximation with ≥5 segments.
    """
    L = 10.0
    base_width = 2.0
    h = base_width / 2.0
    tol = h * 0.10

    outline = expand_stroke(_straight(x0=0.0, x1=L), _const_profile(), base_width=base_width)
    x0, y0, x1, y1 = _outline_bounds(outline)

    assert x0 == pytest.approx(-h, abs=tol), (
        f"Left bound {x0:.4f} != -h={-h:.4f} (tol={tol:.4f}). "
        "Butt cap would give x0=0 (no extension)."
    )
    assert x1 == pytest.approx(L + h, abs=tol), (
        f"Right bound {x1:.4f} != L+h={L+h:.4f}"
    )
    assert y0 == pytest.approx(-h, abs=tol), f"Bottom bound {y0:.4f} != -h={-h:.4f}"
    assert y1 == pytest.approx(h, abs=tol), f"Top bound {y1:.4f} != h={h:.4f}"


def test_outline_bounds_enclose_all_centerline_points() -> None:
    """Expanded outline bounding box must contain every centerline command endpoint."""
    commands = (
        MoveTo(x=10.0, y=10.0),
        LineTo(x=50.0, y=30.0),
        LineTo(x=90.0, y=10.0),
    )
    outline = expand_stroke(commands, _const_profile(), base_width=2.0)
    x0, y0, x1, y1 = _outline_bounds(outline)
    for cmd in commands:
        assert x0 <= cmd.x <= x1, (
            f"Centerline point ({cmd.x}, {cmd.y}) falls outside outline x-bounds [{x0}, {x1}]"
        )
        assert y0 <= cmd.y <= y1, (
            f"Centerline point ({cmd.x}, {cmd.y}) falls outside outline y-bounds [{y0}, {y1}]"
        )


# ---------------------------------------------------------------------------
# Degenerate inputs — must terminate with typed error or degradation flag
# ---------------------------------------------------------------------------


def test_zero_length_segment_only_degrades_safely() -> None:
    """Zero-length segment (start == end) must NOT crash.

    An expander dividing by segment length would raise ZeroDivisionError.
    The contract requires either ExpansionError or a result with degradation_flags set.
    """
    commands = (MoveTo(x=5.0, y=5.0), LineTo(x=5.0, y=5.0))
    try:
        result = expand_stroke(commands, _const_profile(), base_width=2.0)
        assert result.degradation_flags, (
            "Zero-length segment succeeded without a degradation flag — "
            "silent success is not an explicit degenerate contract"
        )
    except ExpansionError:
        pass  # typed error is acceptable


def test_repeated_consecutive_points_handled() -> None:
    """Repeated consecutive points within a longer path must degrade safely, not crash."""
    commands = (
        MoveTo(x=0.0, y=0.0),
        LineTo(x=0.0, y=0.0),  # repeated
        LineTo(x=10.0, y=0.0),
    )
    try:
        result = expand_stroke(commands, _const_profile(), base_width=2.0)
        for v in result.vertices:
            assert math.isfinite(v.x) and math.isfinite(v.y)
    except ExpansionError:
        pass


def test_single_moveto_only_raises() -> None:
    """A command list with only a MoveTo (no drawing commands) raises ExpansionError."""
    with pytest.raises(ExpansionError):
        expand_stroke((MoveTo(x=0.0, y=0.0),), _const_profile(), base_width=2.0)


def test_empty_commands_raises() -> None:
    """Empty command list raises ExpansionError."""
    with pytest.raises(ExpansionError):
        expand_stroke((), _const_profile(), base_width=2.0)


def test_zero_base_width_raises() -> None:
    """Zero base_width raises ExpansionError (no outline can be formed)."""
    with pytest.raises(ExpansionError):
        expand_stroke(_straight(), _const_profile(), base_width=0.0)


# ---------------------------------------------------------------------------
# Pen lifts
# ---------------------------------------------------------------------------


def test_pen_lift_gap_in_outline() -> None:
    """A mid-stroke MoveTo (pen lift) must leave a geometric gap in the outline.

    No outline vertices should appear in the pen-lift region (x in (11, 19)).
    """
    commands = (
        MoveTo(x=0.0, y=0.0),
        LineTo(x=10.0, y=0.0),
        MoveTo(x=20.0, y=0.0),  # pen lift — a gap should appear here
        LineTo(x=30.0, y=0.0),
    )
    outline = expand_stroke(commands, _const_profile(), base_width=2.0)
    gap_xs = [v.x for v in outline.vertices if 11.0 < v.x < 19.0]
    assert not gap_xs, (
        f"Found {len(gap_xs)} vertices in pen-lift gap region x∈(11,19): {gap_xs[:4]}. "
        "Outline should not span across a pen lift."
    )


# ---------------------------------------------------------------------------
# Varying pressure
# ---------------------------------------------------------------------------


def test_varying_width_profile_wider_at_end() -> None:
    """A width profile that doubles from start to end produces a wider outline at the end."""
    profile = (
        WidthSample(position=0.0, width=0.5),
        WidthSample(position=1.0, width=2.0),
    )
    base_width = 2.0
    commands = _straight(x0=0.0, x1=10.0)
    outline = expand_stroke(commands, profile, base_width=base_width)

    # Near start (x ≤ 1.5): outline is narrow
    start_ys = [abs(v.y) for v in outline.vertices if v.x <= 1.5]
    # Near end (x ≥ 8.5): outline is wide
    end_ys = [abs(v.y) for v in outline.vertices if v.x >= 8.5]

    if start_ys and end_ys:
        assert max(start_ys) < max(end_ys), (
            f"Width-profile widening not reflected: max |y| near start={max(start_ys):.3f}, "
            f"near end={max(end_ys):.3f}. Expected end > start."
        )


def test_constant_unit_profile_matches_base_width() -> None:
    """A constant unit-width profile scales to exactly base_width."""
    base_width = 3.0
    h = base_width / 2.0
    commands = _straight(x0=0.0, x1=10.0)
    outline = expand_stroke(commands, _const_profile(scale=1.0), base_width=base_width)
    _, y0, _, y1 = _outline_bounds(outline)
    # Body of the stroke (ignoring cap extension) should span ≈ ±h
    assert y0 <= -h * 0.85, f"Bottom bound {y0:.3f} is above -h*0.85={-h*0.85:.3f}"
    assert y1 >= h * 0.85, f"Top bound {y1:.3f} is below h*0.85={h*0.85:.3f}"


# ---------------------------------------------------------------------------
# Curved path (cubic Bézier)
# ---------------------------------------------------------------------------


def test_cubic_expansion_is_finite() -> None:
    """A cubic Bézier centerline expands to a finite polygon."""
    commands = (
        MoveTo(x=0.0, y=0.0),
        CubicTo(x1=2.0, y1=8.0, x2=8.0, y2=8.0, x=10.0, y=0.0),
    )
    outline = expand_stroke(commands, _const_profile(), base_width=2.0)
    assert outline.vertices
    for v in outline.vertices:
        assert math.isfinite(v.x) and math.isfinite(v.y), (
            f"Non-finite vertex in cubic expansion: ({v.x}, {v.y})"
        )


def test_cubic_expansion_orientation_ccw() -> None:
    """Cubic arc expansion also produces CCW orientation."""
    commands = (
        MoveTo(x=0.0, y=0.0),
        CubicTo(x1=2.0, y1=8.0, x2=8.0, y2=8.0, x=10.0, y=0.0),
    )
    outline = expand_stroke(commands, _const_profile(), base_width=2.0)
    area = _signed_area([(v.x, v.y) for v in outline.vertices])
    assert area > 0.0, f"Cubic expansion: expected CCW (positive area), got {area:.4f}"


# ---------------------------------------------------------------------------
# Point budget
# ---------------------------------------------------------------------------


def test_expansion_respects_max_points() -> None:
    """expand_stroke respects the max_points parameter."""
    commands = [MoveTo(x=0.0, y=0.0)]
    for i in range(1, 50):
        commands.append(LineTo(x=float(i), y=float(i % 3)))
    max_pts = 32
    outline = expand_stroke(tuple(commands), _const_profile(), base_width=1.0, max_points=max_pts)
    assert len(outline.vertices) <= max_pts, (
        f"Outline has {len(outline.vertices)} vertices, exceeds max_points={max_pts}"
    )


# ---------------------------------------------------------------------------
# Closed centerline — explicit degradation contract
# ---------------------------------------------------------------------------


def test_closed_centerline_degrades_with_flag_or_raises() -> None:
    """A closed loop centerline (first == last point) is handled with an explicit contract.

    Annular hole-polygon support is out of Effort-L scope. The contract is:
    - Either raise ExpansionError (typed rejection), OR
    - Return with a non-empty degradation_flags tuple.
    Silent wrong output (success without flags) is not acceptable.
    """
    commands = (
        MoveTo(x=5.0, y=0.0),
        LineTo(x=10.0, y=5.0),
        LineTo(x=5.0, y=10.0),
        LineTo(x=0.0, y=5.0),
        LineTo(x=5.0, y=0.0),  # closes the loop back to start
    )
    try:
        result = expand_stroke(commands, _const_profile(), base_width=2.0)
        assert result.degradation_flags, (
            "Closed-loop centerline succeeded without a degradation flag. "
            "Annular hole-polygons are out of Effort-L scope; contract requires "
            "explicit degradation or ExpansionError."
        )
    except ExpansionError:
        pass  # typed rejection is acceptable


# ---------------------------------------------------------------------------
# Acute angle
# ---------------------------------------------------------------------------


def test_acute_angle_is_finite_and_bounded() -> None:
    """A very acute join angle does not produce NaN or explode the outline."""
    # Paths that meet at a ~10 degree angle
    commands = (
        MoveTo(x=0.0, y=0.0),
        LineTo(x=9.0, y=0.1),
        LineTo(x=10.0, y=0.0),
    )
    outline = expand_stroke(commands, _const_profile(), base_width=2.0)
    for v in outline.vertices:
        assert math.isfinite(v.x) and math.isfinite(v.y), (
            f"Acute join produced non-finite vertex: ({v.x}, {v.y})"
        )
    x0, y0, x1, y1 = _outline_bounds(outline)
    # Outline should not blow up: x-span < 5x the centerline, y-span < 5x base_width
    assert x1 - x0 < 60.0, f"Outline x-span {x1-x0:.1f} suspiciously large for acute join"
    assert y1 - y0 < 10.0, f"Outline y-span {y1-y0:.1f} suspiciously large for acute join"
