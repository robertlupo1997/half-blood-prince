"""Deterministic rough-ink marks in local document coordinates."""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from enum import Enum
from typing import Sequence  # noqa: UP035  # Public API pins typing.Sequence.

from halfblood.ink.model import (
    CubicTo,
    InkGroup,
    InkRole,
    LineTo,
    LocalPoint,
    LocalRect,
    MoveTo,
    StrokePath,
    StrokeStyle,
)
from halfblood.ink.style import InkStyleProfile


class DoodleKind(str, Enum):  # noqa: UP042  # Preserve the pinned string-enum API.
    """Finite, semantic doodle vocabulary from architecture section 5.4."""

    STAR = "star"
    CAULDRON = "cauldron"
    ARROW = "arrow"
    QUESTION_MARK = "question_mark"
    POTION_BUBBLE = "potion_bubble"


class ConnectorDegradation(str, Enum):  # noqa: UP042  # Preserve the pinned string-enum API.
    """Routing-specific degradation signals for scene assembly."""

    ROUTING_FALLBACK = "connector_routing_fallback"
    #: Emitted when the obstacle set was capped before routing (distinct from ROUTING_FALLBACK,
    #: which means routing itself exhausted all waypoint attempts).
    OBSTACLE_CAP_USED = "connector_obstacle_cap"


@dataclass(frozen=True)
class ConnectorResult:
    """A connector group and any routing degradation it incurred."""

    group: InkGroup
    degradation: tuple[ConnectorDegradation, ...]


def _clamp(value: float, low: float, high: float) -> float:
    return min(max(value, low), high)


def _point(x: float, y: float, bounds: LocalRect) -> tuple[float, float]:
    return (_clamp(x, bounds.x0, bounds.x1), _clamp(y, bounds.y0, bounds.y1))


def _limited_point(
    x: float,
    y: float,
    bounds: LocalRect,
    center: LocalPoint,
    radius: float,
) -> tuple[float, float]:
    return (
        _clamp(x, max(bounds.x0, center.x - radius), min(bounds.x1, center.x + radius)),
        _clamp(y, max(bounds.y0, center.y - radius), min(bounds.y1, center.y + radius)),
    )


def _stroke(style: InkStyleProfile) -> StrokeStyle:
    return StrokeStyle(
        color=style.palette.ink_color,
        base_width=style.nib.base_width,
        opacity=style.palette.base_opacity,
    )


def _can_add(
    paths: list[StrokePath],
    command_count: int,
    new_commands: int,
    style: InkStyleProfile,
) -> bool:
    return (
        len(paths) < style.budget.max_paths
        and command_count + new_commands <= style.budget.max_points
    )


def _rough_linear_commands(
    rng: random.Random,
    start: tuple[float, float],
    end: tuple[float, float],
    jitter: float,
    bounds: LocalRect,
) -> tuple[MoveTo, CubicTo]:
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    c1 = _point(
        start[0] + dx / 3.0,
        start[1] + dy / 3.0 + rng.uniform(-jitter, jitter),
        bounds,
    )
    c2 = _point(
        start[0] + 2.0 * dx / 3.0,
        start[1] + 2.0 * dy / 3.0 + rng.uniform(-jitter, jitter),
        bounds,
    )
    return (
        MoveTo(x=start[0], y=start[1]),
        CubicTo(x1=c1[0], y1=c1[1], x2=c2[0], y2=c2[1], x=end[0], y=end[1]),
    )


def _linear_mark_endpoints(
    rng: random.Random,
    quad: LocalRect,
    y: float,
    style: InkStyleProfile,
    bounds: LocalRect,
) -> tuple[tuple[float, float], tuple[float, float]]:
    width = quad.x1 - quad.x0
    left = rng.uniform(0.3, 1.0) * style.rough.overshoot_ratio * width
    right = rng.uniform(0.3, 1.0) * style.rough.overshoot_ratio * width
    start = _point(quad.x0 - left, y, bounds)
    end = _point(quad.x1 + right, y, bounds)
    return start, end


def make_underline(
    rng: random.Random,
    line_quads: Sequence[LocalRect],
    style: InkStyleProfile,
    bounds: LocalRect,
    group_id: str = "underline",
) -> InkGroup:
    """Generate one loosely wobbling baseline stroke per line quad."""

    if not line_quads:
        raise ValueError("line_quads must not be empty")

    paths: list[StrokePath] = []
    command_count = 0
    for quad in line_quads:
        if not _can_add(paths, command_count, 2, style):
            break
        height = max(quad.y1 - quad.y0, style.nib.base_width)
        baseline = quad.y1 + rng.uniform(-0.18, 0.18) * height
        start, end = _linear_mark_endpoints(rng, quad, baseline, style, bounds)
        commands = _rough_linear_commands(rng, start, end, height * 0.16, bounds)
        paths.append(StrokePath(commands=commands, stroke=_stroke(style)))
        command_count += len(commands)
    return InkGroup(group_id=group_id, role=InkRole.UNDERLINE, paths=tuple(paths))


def make_circle(
    rng: random.Random,
    cluster_quads: Sequence[LocalRect],
    style: InkStyleProfile,
    bounds: LocalRect,
    group_id: str = "circle",
) -> InkGroup:
    """Draw an irregular, deliberately open loop around a quad cluster."""

    if not cluster_quads:
        raise ValueError("cluster_quads must not be empty")

    x0 = min(quad.x0 for quad in cluster_quads)
    y0 = min(quad.y0 for quad in cluster_quads)
    x1 = max(quad.x1 for quad in cluster_quads)
    y1 = max(quad.y1 for quad in cluster_quads)
    width = x1 - x0
    height = y1 - y0
    pad_x = max(0.5, width * 0.06)
    pad_y = max(0.5, height * 0.12)
    left = max(bounds.x0, x0 - pad_x)
    right = min(bounds.x1, x1 + pad_x)
    top = max(bounds.y0, y0 - pad_y)
    bottom = min(bounds.y1, y1 + pad_y)
    cx = (left + right) / 2.0
    cy = (top + bottom) / 2.0
    rx = max((right - left) / 2.0, 1e-6)
    ry = max((bottom - top) / 2.0, 1e-6)
    gap_angle = rng.uniform(0.10, 0.18)
    angles = (0.0, math.pi / 2.0, math.pi, 3.0 * math.pi / 2.0, 2.0 * math.pi - gap_angle)
    endpoints = [(cx + rx * math.cos(a), cy + ry * math.sin(a)) for a in angles]
    commands: list[MoveTo | CubicTo] = [MoveTo(x=endpoints[0][0], y=endpoints[0][1])]
    noise = min(rx, ry) * 0.08
    for angle0, angle1, start, end in zip(
        angles, angles[1:], endpoints, endpoints[1:], strict=False
    ):
        span = angle1 - angle0
        factor = 4.0 / 3.0 * math.tan(span / 4.0)
        c1 = _point(
            start[0] - factor * rx * math.sin(angle0) + rng.uniform(-noise, noise),
            start[1] + factor * ry * math.cos(angle0) + rng.uniform(-noise, noise),
            bounds,
        )
        c2 = _point(
            end[0] + factor * rx * math.sin(angle1) + rng.uniform(-noise, noise),
            end[1] - factor * ry * math.cos(angle1) + rng.uniform(-noise, noise),
            bounds,
        )
        commands.append(
            CubicTo(x1=c1[0], y1=c1[1], x2=c2[0], y2=c2[1], x=end[0], y=end[1])
        )

    path = StrokePath(commands=tuple(commands), stroke=_stroke(style))
    return InkGroup(group_id=group_id, role=InkRole.CIRCLE, paths=(path,))


def make_strike(
    rng: random.Random,
    line_quads: Sequence[LocalRect],
    style: InkStyleProfile,
    bounds: LocalRect,
    group_id: str = "strike",
) -> InkGroup:
    """Generate one decisive or two agitated passes through each line."""

    if not line_quads:
        raise ValueError("line_quads must not be empty")

    paths: list[StrokePath] = []
    command_count = 0
    for quad in line_quads:
        passes = 2 if rng.random() < 0.38 else 1
        for pass_index in range(passes):
            if not _can_add(paths, command_count, 2, style):
                return InkGroup(group_id=group_id, role=InkRole.STRIKE, paths=tuple(paths))
            height = max(quad.y1 - quad.y0, style.nib.base_width)
            mid_y = (quad.y0 + quad.y1) / 2.0
            offset = (pass_index - (passes - 1) / 2.0) * height * 0.18
            start_y = mid_y + offset + rng.uniform(-0.12, 0.12) * height
            end_y = mid_y + offset + rng.uniform(-0.12, 0.12) * height
            start, _ = _linear_mark_endpoints(rng, quad, start_y, style, bounds)
            _, end = _linear_mark_endpoints(rng, quad, end_y, style, bounds)
            commands = _rough_linear_commands(rng, start, end, height * 0.14, bounds)
            paths.append(StrokePath(commands=commands, stroke=_stroke(style)))
            command_count += len(commands)
    return InkGroup(group_id=group_id, role=InkRole.STRIKE, paths=tuple(paths))


def make_highlight(
    rng: random.Random,
    line_quads: Sequence[LocalRect],
    style: InkStyleProfile,
    bounds: LocalRect,
    group_id: str = "highlight",
) -> InkGroup:
    """Generate broad, translucent, ragged strokes across line quads."""

    if not line_quads:
        raise ValueError("line_quads must not be empty")

    paths: list[StrokePath] = []
    command_count = 0
    for quad in line_quads:
        if not _can_add(paths, command_count, 2, style):
            break
        height = max(quad.y1 - quad.y0, style.nib.base_width)
        line_y = (quad.y0 + quad.y1) / 2.0 + rng.uniform(-0.08, 0.08) * height
        start, end = _linear_mark_endpoints(rng, quad, line_y, style, bounds)
        commands = _rough_linear_commands(rng, start, end, height * 0.12, bounds)
        highlight_style = StrokeStyle(
            color=style.palette.highlight_color,
            base_width=style.nib.base_width * rng.uniform(2.5, 4.0),
            opacity=style.palette.base_opacity * rng.uniform(0.35, 0.55),
        )
        paths.append(StrokePath(commands=commands, stroke=highlight_style, z_index=-1))
        command_count += len(commands)
    return InkGroup(group_id=group_id, role=InkRole.UNDERLINE, paths=tuple(paths))


def make_caret(
    rng: random.Random,
    insertion_point: LocalPoint,
    interline_gap: float,
    style: InkStyleProfile,
    bounds: LocalRect,
    group_id: str = "caret",
) -> InkGroup:
    """Generate a small two-stroke caret and an optional insertion stem."""

    if interline_gap <= 0.0:
        raise ValueError("interline_gap must be positive")

    apex = _point(
        insertion_point.x + rng.uniform(-0.03, 0.03) * interline_gap,
        insertion_point.y - interline_gap * rng.uniform(0.36, 0.44),
        bounds,
    )
    rise = interline_gap * rng.uniform(0.38, 0.48)
    angle = math.radians(rng.uniform(30.0, 60.0))
    spread = min(interline_gap, rise * math.tan(angle))
    left = _point(apex[0] - spread, apex[1] + rise, bounds)
    right = _point(apex[0] + spread, apex[1] + rise, bounds)
    paths = [
        StrokePath(
            commands=(MoveTo(x=left[0], y=left[1]), LineTo(x=apex[0], y=apex[1])),
            stroke=_stroke(style),
        ),
        StrokePath(
            commands=(MoveTo(x=apex[0], y=apex[1]), LineTo(x=right[0], y=right[1])),
            stroke=_stroke(style),
        ),
    ]
    if rng.random() < 0.48:
        stem_end = _point(apex[0], apex[1] - interline_gap * rng.uniform(0.16, 0.28), bounds)
        paths.append(
            StrokePath(
                commands=(
                    MoveTo(x=apex[0], y=apex[1]),
                    LineTo(x=stem_end[0], y=stem_end[1]),
                ),
                stroke=_stroke(style),
            )
        )
    return InkGroup(group_id=group_id, role=InkRole.CARET, paths=tuple(paths))


def _expanded(rect: LocalRect, clearance: float) -> LocalRect:
    return LocalRect(
        x0=rect.x0 - clearance,
        y0=rect.y0 - clearance,
        x1=rect.x1 + clearance,
        y1=rect.y1 + clearance,
    )


def _inside(point: tuple[float, float], rect: LocalRect) -> bool:
    return rect.x0 <= point[0] <= rect.x1 and rect.y0 <= point[1] <= rect.y1


def _segment_hits(
    start: tuple[float, float],
    end: tuple[float, float],
    obstacles: Sequence[LocalRect],
) -> bool:
    for sample_index in range(21):
        fraction = sample_index / 20.0
        point = (
            start[0] + fraction * (end[0] - start[0]),
            start[1] + fraction * (end[1] - start[1]),
        )
        if any(_inside(point, obstacle) for obstacle in obstacles):
            return True
    return False


def _pinched_midpoint(
    midpoint: tuple[float, float],
    obstacles: Sequence[LocalRect],
    clearance: float,
) -> bool:
    above = [rect.y1 for rect in obstacles if rect.x0 <= midpoint[0] <= rect.x1 and rect.y1 < midpoint[1]]
    below = [rect.y0 for rect in obstacles if rect.x0 <= midpoint[0] <= rect.x1 and rect.y0 > midpoint[1]]
    return bool(above and below and min(below) - max(above) <= 2.0 * clearance)


#: Maximum obstacles used to GENERATE bypass-Y waypoint candidates per
#: ``make_connector`` call.
#:
#: It bounds candidate generation only. It does NOT bound hit-testing: every
#: ``_segment_hits`` / ``_inside`` / ``_pinched_midpoint`` call validates against
#: ``full_expanded``, the complete unpruned obstacle list. That separation is
#: deliberate and load-bearing — an earlier version validated against the pruned
#: set and drew connectors straight through text on a two-obstacle page, because
#: detour waypoints leave the direct-segment corridor the pruning was computed
#: from. Correctness must never depend on the pruned set.
#:
#: (This comment previously claimed the constant bounded ``_segment_hits``. That
#: was true when written and stopped being true when validation moved to the full
#: set; measured cost is ~0.083s median at 10 000 obstacles, so the O(n)
#: validation is affordable and the bound is not needed there.)
#:
#: Pages with more obstacles (e.g. densely-typeset Internet Archive scans) are
#: reduced by corridor pruning first; this is the final safety cap after pruning.
_CONNECTOR_OBSTACLE_LIMIT: int = 100

#: Chord subdivisions per CubicTo command when validating the emitted Bézier
#: curve against in-transit obstacles.  Matches ``connector_crossing.py``'s
#: ``flatten`` resolution (16 steps per cubic) so the in-code
#: ``ROUTING_FALLBACK`` flag fires whenever the measurement rig counts a
#: crossing.
_BEZIER_VALIDATION_SAMPLES: int = 16


def _rect_min_dist_sq_to_segment(
    rect: LocalRect,
    start: tuple[float, float],
    target: tuple[float, float],
) -> float:
    """Return the minimum squared distance from *rect* to 21 sampled points on *start*→*target*.

    Uses the same 21-point grid as ``_segment_hits``, so an obstacle that would
    register a hit there has distance zero here and sorts first when the cap
    selects the most relevant obstacles.
    """
    min_d2 = math.inf
    for i in range(21):
        t = i / 20.0
        px = start[0] + t * (target[0] - start[0])
        py = start[1] + t * (target[1] - start[1])
        dx = max(rect.x0 - px, 0.0, px - rect.x1)
        dy = max(rect.y0 - py, 0.0, py - rect.y1)
        d2 = dx * dx + dy * dy
        if d2 < min_d2:
            min_d2 = d2
    return min_d2


def _seg_hits_rect(
    p: tuple[float, float],
    q: tuple[float, float],
    r: LocalRect,
) -> bool:
    """Liang-Barsky parametric slab test: True if segment p→q intersects the closed rect r.

    Identical algorithm to ``connector_crossing.py``'s ``seg_hits_rect`` so the
    in-code validator and the measurement rig agree on what constitutes a crossing.
    """
    dx, dy = q[0] - p[0], q[1] - p[1]
    t0, t1 = 0.0, 1.0
    for pp, qq in (
        (-dx, p[0] - r.x0),
        (dx, r.x1 - p[0]),
        (-dy, p[1] - r.y0),
        (dy, r.y1 - p[1]),
    ):
        if pp == 0:
            if qq < 0:
                return False
        else:
            t = qq / pp
            if pp < 0:
                if t > t1:
                    return False
                t0 = max(t0, t)
            else:
                if t < t0:
                    return False
                t1 = min(t1, t)
    return t0 <= t1


def _curve_hits_obstacles(
    commands: Sequence[MoveTo | LineTo | CubicTo],
    obstacles: Sequence[LocalRect],
    n: int,
) -> bool:
    """Return True if any stroke command in *commands* clips an obstacle.

    * ``LineTo`` — tested as a single chord segment via :func:`_seg_hits_rect`.
    * ``CubicTo`` — subdivided at *n* steps (generating *n* chord segments), each
      tested with :func:`_seg_hits_rect`.

    The subdivision resolution matches ``connector_crossing.py``'s ``flatten``
    (n=16 per cubic), so the in-code ``ROUTING_FALLBACK`` flag fires whenever the
    rig would count a crossing.  Point-sampling alone cannot catch corner crossings
    between samples; chord testing with Liang-Barsky closes that gap.

    Both the body stroke and arrowhead strokes are tested by passing all paths to
    this function — arrowhead barbs that clip in-transit obstacles are flagged
    identically to body-stroke crossings.
    """
    if not obstacles:
        return False
    cur: tuple[float, float] = (0.0, 0.0)
    for cmd in commands:
        if isinstance(cmd, MoveTo):
            cur = (cmd.x, cmd.y)
        elif isinstance(cmd, LineTo):
            pt = (cmd.x, cmd.y)
            if any(_seg_hits_rect(cur, pt, obs) for obs in obstacles):
                return True
            cur = pt
        elif isinstance(cmd, CubicTo):
            p0 = cur
            prev_pt = p0
            for i in range(1, n + 1):
                t = i / n
                mt = 1.0 - t
                x = mt**3 * p0[0] + 3.0 * mt**2 * t * cmd.x1 + 3.0 * mt * t**2 * cmd.x2 + t**3 * cmd.x
                y = mt**3 * p0[1] + 3.0 * mt**2 * t * cmd.y1 + 3.0 * mt * t**2 * cmd.y2 + t**3 * cmd.y
                pt = (x, y)
                if any(_seg_hits_rect(prev_pt, pt, obs) for obs in obstacles):
                    return True
                prev_pt = pt
            cur = (cmd.x, cmd.y)
    return False


def _connector_commands(
    rng: random.Random,
    anchors: Sequence[tuple[float, float]],
    wobble: float,
    bounds: LocalRect,
) -> tuple[MoveTo | CubicTo, ...]:
    commands: list[MoveTo | CubicTo] = [MoveTo(x=anchors[0][0], y=anchors[0][1])]
    for start, end in zip(anchors, anchors[1:], strict=False):
        dx = end[0] - start[0]
        dy = end[1] - start[1]
        length = math.hypot(dx, dy)
        if length > 0.0:
            nx = -dy / length
            ny = dx / length
        else:
            nx = 0.0
            ny = 0.0
        deviation1 = rng.gauss(0.0, wobble)
        deviation2 = rng.gauss(0.0, wobble)
        c1 = _point(
            start[0] + dx / 3.0 + nx * deviation1,
            start[1] + dy / 3.0 + ny * deviation1,
            bounds,
        )
        c2 = _point(
            start[0] + 2.0 * dx / 3.0 + nx * deviation2,
            start[1] + 2.0 * dy / 3.0 + ny * deviation2,
            bounds,
        )
        commands.append(
            CubicTo(x1=c1[0], y1=c1[1], x2=c2[0], y2=c2[1], x=end[0], y=end[1])
        )
    return tuple(commands)


def make_connector(
    rng: random.Random,
    note_edge: LocalPoint,
    target_edge: LocalPoint,
    obstacles: Sequence[LocalRect],
    clearance: float,
    style: InkStyleProfile,
    bounds: LocalRect,
    group_id: str = "connector",
) -> ConnectorResult:
    """Generate a low-frequency cubic connector with a two-stroke arrowhead.

    Never raises for any finite obstacle count or clearance value.  Obstacle
    handling uses a generate-then-validate pattern:

    1. **Corridor pruning** — obstacles whose expanded bounding box (±clearance)
       does not overlap the connector corridor are excluded from *candidate
       generation* only.  The corridor is the bounding box of start→target
       expanded by clearance, with inclusive bounds so boundary obstacles are
       never silently dropped.

    2. **Cap with** ``OBSTACLE_CAP_USED`` **degradation** — if the pruned set
       still exceeds ``_CONNECTOR_OBSTACLE_LIMIT``, the nearest obstacles (by
       minimum squared distance to the direct segment) are kept and
       ``ConnectorDegradation.OBSTACLE_CAP_USED`` is recorded.

    3. **Interior-set validation** — all routing segment checks use
       ``interior_obstacles``: the full expanded obstacle set minus any obstacle
       whose raw rect is within ``max(clearance, 2.0)`` of either connector
       endpoint.  This exclusion is necessary because the target edge is
       intentionally placed at the boundary of its text-run obstacle; including
       that obstacle in segment checks would make ``_segment_hits(candidate,
       target, …)`` always True and cause every routing attempt to fail.  The
       exclusion matches ``connector_crossing.py``'s ``ep_pad`` logic.

    4. **Post-routing Bézier validation** — after routing, the actual emitted
       cubic curve (not just anchor chords) is flattened at
       ``_BEZIER_VALIDATION_SAMPLES`` steps per cubic and tested against
       ``interior_obstacles`` with Liang-Barsky segment/rect intersection.  If
       the curve still crosses an obstacle, ``ROUTING_FALLBACK`` is recorded
       honestly.  This step adds a flag only — it never changes the drawn
       geometry (no re-routing).

    If routing exhausts all waypoint attempts, ``ConnectorDegradation.ROUTING_FALLBACK``
    is recorded.  The post-routing check may also add it if the emitted curve
    crosses an in-transit obstacle despite routing.  A ``ConnectorResult`` is
    always returned.
    """
    # Clamp clearance: non-finite values would produce inf-expanded LocalRects
    # and turn every point into a hit, so treat them as zero clearance.
    clearance = max(0.0, clearance) if math.isfinite(clearance) else 0.0
    start = _point(note_edge.x, note_edge.y, bounds)
    target = _point(target_edge.x, target_edge.y, bounds)

    # ---- Phase 1: corridor pruning (candidate GENERATION only) ------------------
    # Keep obstacles whose expanded bbox overlaps the connector corridor.
    # Uses inclusive >= / <= to match _inside's inclusive semantics — an obstacle
    # touching the corridor boundary exactly is retained.
    cx0 = min(start[0], target[0]) - clearance
    cy0 = min(start[1], target[1]) - clearance
    cx1 = max(start[0], target[0]) + clearance
    cy1 = max(start[1], target[1]) + clearance
    route_obstacles: tuple[LocalRect, ...] = tuple(
        obs
        for obs in obstacles
        if (obs.x1 + clearance) >= cx0
        and (obs.x0 - clearance) <= cx1
        and (obs.y1 + clearance) >= cy0
        and (obs.y0 - clearance) <= cy1
    )

    # ---- Phase 2: cap with distinct degradation ----------------------------------
    # If the pruned set still exceeds the routing budget, keep the N nearest to the
    # direct segment and record OBSTACLE_CAP_USED (not ROUTING_FALLBACK — the cap
    # is not a routing failure).  Sort key is deterministic for structural-hash
    # stability across identical inputs.
    degradation: list[ConnectorDegradation] = []
    if len(route_obstacles) > _CONNECTOR_OBSTACLE_LIMIT:
        route_obstacles = tuple(
            sorted(
                route_obstacles,
                key=lambda obs: (
                    _rect_min_dist_sq_to_segment(obs, start, target),
                    obs.x0,
                    obs.y0,
                    obs.x1,
                    obs.y1,
                ),
            )[:_CONNECTOR_OBSTACLE_LIMIT]
        )
        degradation.append(ConnectorDegradation.OBSTACLE_CAP_USED)

    # ---- Full-set validation set -------------------------------------------------
    # full_expanded is the complete original obstacle list expanded by clearance.
    # It is used conservatively (midpoint pinch detection) and for bypass-Y candidate
    # generation.  All routing segment/curve checks use interior_obstacles instead —
    # see below.
    full_expanded = tuple(_expanded(obs, clearance) for obs in obstacles)

    # ---- Interior obstacle set for in-transit validation -------------------------
    # The target edge is intentionally placed at the boundary of a text-run rect
    # (the closest point on the target passage to the note box).  That boundary
    # point is INSIDE the clearance-expanded version of its obstacle, so including
    # that obstacle in _segment_hits(candidate, target, …) makes the check always
    # True, causing every routing attempt to fail.  Exclude any raw obstacle whose
    # raw rect is within ep_pad of either connector endpoint.
    #
    # ep_pad = max(clearance, 2.0) matches connector_crossing.py's contains() logic
    # so the in-code validator and the measurement rig agree on which obstacles are
    # "endpoint-owned" vs. in-transit.
    _ep_pad = max(clearance, 2.0)
    interior_obstacles = tuple(
        _expanded(obs, clearance)
        for obs in obstacles
        if not (
            obs.x0 - _ep_pad <= start[0] <= obs.x1 + _ep_pad
            and obs.y0 - _ep_pad <= start[1] <= obs.y1 + _ep_pad
        )
        and not (
            obs.x0 - _ep_pad <= target[0] <= obs.x1 + _ep_pad
            and obs.y0 - _ep_pad <= target[1] <= obs.y1 + _ep_pad
        )
    )

    dx = target[0] - start[0]
    dy = target[1] - start[1]
    distance = math.hypot(dx, dy)
    midpoint = ((start[0] + target[0]) / 2.0, (start[1] + target[1]) / 2.0)
    # Pre-routing: test the FULL direct segment (not just midpoint) against in-transit
    # obstacles.  A midpoint-only gate misses obstacles at t≈0.25 or t≈0.75 that the
    # midpoint clears.  The pinch check uses full_expanded (conservative gap detection
    # against all expanded obstacles including endpoint-owning ones).
    blocked = _segment_hits(start, target, interior_obstacles)
    blocked = blocked or _pinched_midpoint(midpoint, full_expanded, clearance)
    anchors: list[tuple[float, float]] = [start, target]
    connector_wobble = style.rough.wobble_amplitude * distance

    if blocked:
        normal = (-dy / distance, dx / distance) if distance > 0.0 else (0.0, 1.0)
        found_waypoint = False
        for attempt in range(style.rough.connector_max_route_attempts):
            sign = 1.0 if attempt % 2 == 0 else -1.0
            offset = clearance + (attempt + 1) * clearance * 1.5
            candidate = _point(
                midpoint[0] + normal[0] * sign * offset,
                midpoint[1] + normal[1] * sign * offset,
                bounds,
            )
            if (
                not _inside(candidate, LocalRect(x0=bounds.x0, y0=bounds.y0, x1=bounds.x1, y1=bounds.y1))
                or _segment_hits(start, candidate, interior_obstacles)
                or _segment_hits(candidate, target, interior_obstacles)
            ):
                continue
            anchors = [start, candidate, target]
            found_waypoint = True
            break
        if not found_waypoint:
            # Iterate route_obstacles (pruned/capped) for bypass-Y GENERATION only.
            # All hit-tests validate against full_expanded.
            for obstacle in route_obstacles:
                expanded_obstacle = _expanded(obstacle, clearance)
                bypass_levels = (
                    expanded_obstacle.y0 - 1.0,
                    expanded_obstacle.y1 + 1.0,
                )
                for bypass_y in bypass_levels:
                    if bypass_y < bounds.y0 or bypass_y > bounds.y1:
                        continue
                    if _pinched_midpoint((midpoint[0], bypass_y), full_expanded, clearance):
                        continue
                    p1 = _point(start[0], bypass_y, bounds)
                    p2 = _point(target[0], bypass_y, bounds)
                    if (
                        _segment_hits(start, p1, interior_obstacles)
                        or _segment_hits(p1, p2, interior_obstacles)
                        or _segment_hits(p2, target, interior_obstacles)
                    ):
                        continue
                    anchors = [start, p1, p2, target]
                    # Keep the emitted cubic segments on the collision-checked L-path.
                    connector_wobble = 0.0
                    found_waypoint = True
                    break
                if found_waypoint:
                    break
        if not found_waypoint:
            degradation.append(ConnectorDegradation.ROUTING_FALLBACK)

    main_commands = _connector_commands(
        rng,
        anchors,
        connector_wobble,
        bounds,
    )
    paths: list[StrokePath] = []
    command_count = 0
    if _can_add(paths, command_count, len(main_commands), style):
        paths.append(StrokePath(commands=main_commands, stroke=_stroke(style)))
        command_count += len(main_commands)

    final_curve = main_commands[-1]
    if isinstance(final_curve, CubicTo):
        tangent_x = target[0] - final_curve.x2
        tangent_y = target[1] - final_curve.y2
    else:
        tangent_x = dx
        tangent_y = dy
    tangent_angle = math.atan2(tangent_y, tangent_x)
    barb_length = min(12.0, max(3.0, distance * 0.10))
    for sign in (-1.0, 1.0):
        if not _can_add(paths, command_count, 2, style):
            break
        barb_angle = tangent_angle + math.pi + sign * math.radians(rng.uniform(25.0, 45.0))
        barb_end = _point(
            target[0] + barb_length * math.cos(barb_angle),
            target[1] + barb_length * math.sin(barb_angle),
            bounds,
        )
        commands = (
            MoveTo(x=target[0], y=target[1]),
            LineTo(x=barb_end[0], y=barb_end[1]),
        )
        paths.append(StrokePath(commands=commands, stroke=_stroke(style)))
        command_count += len(commands)

    # Post-routing validation (honesty-only — adds flag, never re-routes or changes geometry).
    # Tests ALL emitted strokes (body + arrowhead barbs) against interior_obstacles using the
    # same chord subdivision and Liang-Barsky algorithm as connector_crossing.py.  Catching
    # wobble bow in the body curve and arrowhead barbs over in-transit text both fire here.
    if ConnectorDegradation.ROUTING_FALLBACK not in degradation and any(
        _curve_hits_obstacles(p.commands, interior_obstacles, _BEZIER_VALIDATION_SAMPLES)
        for p in paths
    ):
        degradation.append(ConnectorDegradation.ROUTING_FALLBACK)

    group = InkGroup(group_id=group_id, role=InkRole.CONNECTOR, paths=tuple(paths))
    return ConnectorResult(group=group, degradation=tuple(degradation))


def _doodle_path(
    commands: Sequence[MoveTo | LineTo | CubicTo],
    style: InkStyleProfile,
) -> StrokePath:
    return StrokePath(commands=tuple(commands), stroke=_stroke(style))


def make_doodle(
    rng: random.Random,
    kind: DoodleKind,
    center: LocalPoint,
    size: float,
    style: InkStyleProfile,
    bounds: LocalRect,
    group_id: str = "doodle",
) -> InkGroup:
    """Generate one of the finite semantic margin-doodle shapes."""

    try:
        doodle_kind = DoodleKind(kind)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"unknown doodle kind: {kind!r}") from exc
    if size <= 0.0:
        raise ValueError("size must be positive")

    radius = size * 1.5

    def point(x: float, y: float) -> tuple[float, float]:
        return _limited_point(x, y, bounds, center, radius)

    candidates: list[StrokePath] = []
    if doodle_kind is DoodleKind.STAR:
        count = rng.choice((5, 6))
        rotation = rng.uniform(-0.25, 0.25) - math.pi / 2.0
        vertices: list[tuple[float, float]] = []
        for index in range(count * 2):
            vertex_radius = size * (rng.uniform(0.90, 1.08) if index % 2 == 0 else rng.uniform(0.38, 0.50))
            angle = rotation + index * math.pi / count
            vertices.append(point(center.x + vertex_radius * math.cos(angle), center.y + vertex_radius * math.sin(angle)))
        commands: list[MoveTo | LineTo] = [MoveTo(x=vertices[0][0], y=vertices[0][1])]
        commands.extend(LineTo(x=vertex[0], y=vertex[1]) for vertex in vertices[1:])
        commands.append(LineTo(x=vertices[0][0], y=vertices[0][1]))
        candidates.append(_doodle_path(commands, style))
    elif doodle_kind is DoodleKind.CAULDRON:
        left = point(center.x - size * 0.85, center.y - size * 0.20)
        right = point(center.x + size * 0.85, center.y - size * 0.20)
        bottom = point(center.x + rng.uniform(-0.08, 0.08) * size, center.y + size * 0.72)
        c1 = point(center.x - size * 0.82, center.y + size * 0.55)
        c2 = point(center.x - size * 0.35, center.y + size * 0.75)
        c3 = point(center.x + size * 0.35, center.y + size * 0.75)
        c4 = point(center.x + size * 0.82, center.y + size * 0.55)
        candidates.append(
            _doodle_path(
                (
                    MoveTo(x=left[0], y=left[1]),
                    CubicTo(x1=c1[0], y1=c1[1], x2=c2[0], y2=c2[1], x=bottom[0], y=bottom[1]),
                    CubicTo(x1=c3[0], y1=c3[1], x2=c4[0], y2=c4[1], x=right[0], y=right[1]),
                    LineTo(x=left[0], y=left[1]),
                ),
                style,
            )
        )
        for x_sign in (-1.0, 1.0):
            leg_start = point(center.x + x_sign * size * 0.38, center.y + size * 0.58)
            leg_end = point(center.x + x_sign * size * 0.52, center.y + size * 0.98)
            candidates.append(
                _doodle_path(
                    (MoveTo(x=leg_start[0], y=leg_start[1]), LineTo(x=leg_end[0], y=leg_end[1])),
                    style,
                )
            )
    elif doodle_kind is DoodleKind.ARROW:
        start = point(center.x - size * 0.75, center.y + size * 0.65)
        end = point(center.x + size * 0.70, center.y - size * 0.70)
        middle = point(center.x + rng.uniform(-0.08, 0.08) * size, center.y)
        candidates.append(
            _doodle_path(
                (
                    MoveTo(x=start[0], y=start[1]),
                    CubicTo(x1=start[0], y1=middle[1], x2=middle[0], y2=end[1], x=end[0], y=end[1]),
                ),
                style,
            )
        )
        for barb in ((-0.58, -0.02), (-0.02, 0.58)):
            barb_end = point(end[0] + barb[0] * size, end[1] + barb[1] * size)
            candidates.append(
                _doodle_path(
                    (MoveTo(x=end[0], y=end[1]), LineTo(x=barb_end[0], y=barb_end[1])),
                    style,
                )
            )
    elif doodle_kind is DoodleKind.QUESTION_MARK:
        top = point(center.x - size * 0.45, center.y - size * 0.58)
        middle = point(center.x + size * 0.10, center.y + size * 0.22)
        candidates.append(
            _doodle_path(
                (
                    MoveTo(x=top[0], y=top[1]),
                    CubicTo(
                        x1=center.x - size * 0.20,
                        y1=center.y - size * 1.05,
                        x2=center.x + size * 0.85,
                        y2=center.y - size * 0.72,
                        x=center.x + size * 0.48,
                        y=center.y - size * 0.18,
                    ),
                    CubicTo(
                        x1=center.x + size * 0.32,
                        y1=center.y + size * 0.02,
                        x2=middle[0],
                        y2=middle[1] - size * 0.18,
                        x=middle[0],
                        y=middle[1],
                    ),
                ),
                style,
            )
        )
        dot0 = point(center.x + size * 0.08, center.y + size * 0.62)
        dot1 = point(center.x + rng.uniform(0.08, 0.16) * size, center.y + size * 0.72)
        candidates.append(
            _doodle_path((MoveTo(x=dot0[0], y=dot0[1]), LineTo(x=dot1[0], y=dot1[1])), style)
        )
    else:
        rx = size * rng.uniform(0.48, 0.68)
        ry = size * rng.uniform(0.38, 0.58)
        start = point(center.x + rx, center.y)
        end = point(center.x + rx * 0.98, center.y - ry * 0.14)
        candidates.append(
            _doodle_path(
                (
                    MoveTo(x=start[0], y=start[1]),
                    CubicTo(
                        x1=center.x + rx * 1.08,
                        y1=center.y + ry * 0.62,
                        x2=center.x + rx * 0.42,
                        y2=center.y + ry * 1.12,
                        x=center.x,
                        y=center.y + ry,
                    ),
                    CubicTo(
                        x1=center.x - rx * 0.62,
                        y1=center.y + ry * 0.92,
                        x2=center.x - rx * 1.10,
                        y2=center.y + rng.uniform(-0.12, 0.12) * ry,
                        x=center.x - rx,
                        y=center.y,
                    ),
                    CubicTo(
                        x1=center.x - rx * 0.95,
                        y1=center.y - ry * 0.82,
                        x2=center.x + rx * 0.55,
                        y2=center.y - ry * 1.10,
                        x=end[0],
                        y=end[1],
                    ),
                ),
                style,
            )
        )

    paths: list[StrokePath] = []
    command_count = 0
    for candidate in candidates:
        if not _can_add(paths, command_count, len(candidate.commands), style):
            break
        paths.append(candidate)
        command_count += len(candidate.commands)
    return InkGroup(group_id=group_id, role=InkRole.DOODLE, paths=tuple(paths))


__all__ = [
    "ConnectorDegradation",
    "ConnectorResult",
    "DoodleKind",
    "make_caret",
    "make_circle",
    "make_connector",
    "make_doodle",
    "make_highlight",
    "make_strike",
    "make_underline",
]
