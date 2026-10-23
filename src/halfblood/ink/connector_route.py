"""Route a margin note's connector the way a pen would: through the leading.

A person drawing an arrow from a margin note to a passage keeps the pen in the
white space. It runs along the margin, turns into the gap between two lines of
type (the leading above or below the quote's line), and stops at the quote's
near end: the left end for a note in the left margin, the right end for one in
the right margin. It never cuts across a line of print to get there.

:func:`plan_connector_route` finds that route from the page's glyph ink boxes
(``PageOccupancy.glyphs``), never from line boxes: on a book page the line
boxes touch, so only glyph outlines show where the leading is. When no clean
route exists it settles for a short arrow that stops at the text column's edge,
level with the quote's line. :func:`make_routed_connector` draws a planned
route with bounded hand wobble and reports ``ROUTING_FALLBACK`` whenever any
drawn stroke (body or arrowhead) still touches a glyph that is not part of the
quote, or another note. Nothing near the endpoints is exempt from that check.

Routes are planned for a note on the left and mirrored for a note on the
right, so both sides share one implementation.
"""

from __future__ import annotations

import math
import random
from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum

from halfblood.ink.model import CubicTo, InkGroup, InkRole, LineTo, LocalRect, MoveTo, StrokePath
from halfblood.ink.rough import (
    ConnectorDegradation,
    ConnectorResult,
    _can_add,
    _point,
    _stroke,
)
from halfblood.ink.style import InkStyleProfile

Rect = tuple[float, float, float, float]
Point = tuple[float, float]

#: Distance (pt) the arrow tip keeps from the quote's first glyph.
TIP_GAP = 1.0
#: Distance (pt) from the text column edge at which a connector turns into the
#: leading, and at which a short fallback arrow stops.
COLUMN_STANDOFF = 3.0
#: How far before the quote (pt) the lane leg ends and the pen bends toward it.
#: The bend stays above the line's ascenders (see ``_leading_route``), so it
#: can start over the preceding word.
TURN_RUN = 14.0
#: Smallest leading (pt, glyph to glyph) the router will use as a lane.
MIN_LANE = 3.0
#: Leading assumed above a quote line with no text above it (paragraph start,
#: top of the column).
OPEN_LANE = 9.0
#: Longest arrowhead barb (pt); barbs shrink until they clear every glyph.
BARB_MAX = 8.0
BARB_MIN = 2.5
#: Samples per cubic when testing a stroke against glyph boxes.
SAMPLES = 24


class RouteKind(str, Enum):  # noqa: UP042 - string enum, like the other ink enums.
    """How a connector reaches its quote."""

    OPEN = "open"
    """The quote's near end faces the margin directly; the arrow runs level into it."""
    LEADING_ABOVE = "leading_above"
    """The arrow runs in the leading above the quote's line and drops onto its near end."""
    LEADING_BELOW = "leading_below"
    """The arrow runs in the leading below the quote's line and rises onto its near end."""
    SHORT = "short"
    """No clean route: the arrow stops at the text column's edge, level with the line."""


@dataclass(frozen=True)
class Leg:
    """One cubic segment of a planned route, with its ideal control points."""

    start: Point
    c1: Point
    c2: Point
    end: Point
    #: Largest perpendicular hand-wobble (pt) the drawn control points may take.
    jitter: float


@dataclass(frozen=True)
class ConnectorRoute:
    """A planned connector: legs from the note's edge to the arrow tip."""

    kind: RouteKind
    legs: tuple[Leg, ...]
    #: Glyph ink boxes not in the quote, plus other notes' boxes, each grown by
    #: half the stroke width. The drawn connector must touch none of them.
    obstacles: tuple[Rect, ...]
    #: True when the ideal (unwobbled) route touches no obstacle.
    clean: bool

    @property
    def start(self) -> Point:
        return self.legs[0].start

    @property
    def tip(self) -> Point:
        return self.legs[-1].end


# --------------------------------------------------------------------------- #
# Geometry helpers (plain tuples: a page holds thousands of glyphs)
# --------------------------------------------------------------------------- #


def _rect(r: LocalRect) -> Rect:
    return (r.x0, r.y0, r.x1, r.y1)


def _grow(r: Rect, d: float) -> Rect:
    return (r[0] - d, r[1] - d, r[2] + d, r[3] + d)


def _mirror_rect(r: Rect, axis: float) -> Rect:
    return (axis - r[2], r[1], axis - r[0], r[3])


def _mirror_point(p: Point, axis: float) -> Point:
    return (axis - p[0], p[1])


def _cy(r: Rect) -> float:
    return (r[1] + r[3]) / 2.0


def _cubic_points(p0: Point, c1: Point, c2: Point, p3: Point, n: int = SAMPLES) -> list[Point]:
    out = [p0]
    for i in range(1, n + 1):
        t = i / n
        mt = 1.0 - t
        out.append((
            mt**3 * p0[0] + 3 * mt**2 * t * c1[0] + 3 * mt * t**2 * c2[0] + t**3 * p3[0],
            mt**3 * p0[1] + 3 * mt**2 * t * c1[1] + 3 * mt * t**2 * c2[1] + t**3 * p3[1],
        ))
    return out


def _polyline_hits(points: Sequence[Point], obstacles: Sequence[Rect]) -> int:
    """Number of obstacles any chord of *points* intersects."""
    if len(points) < 2 or not obstacles:
        return 0
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    bx0, bx1, by0, by1 = min(xs), max(xs), min(ys), max(ys)
    near = [
        r for r in obstacles if r[2] >= bx0 and r[0] <= bx1 and r[3] >= by0 and r[1] <= by1
    ]
    if not near:
        return 0
    chords = list(zip(points, points[1:], strict=False))
    return sum(1 for r in near if any(_chord_hits(a, b, r) for a, b in chords))


def _chord_hits(p: Point, q: Point, r: Rect) -> bool:
    """Liang-Barsky segment/rectangle test, as ``rough._seg_hits_rect`` on tuples."""
    dx, dy = q[0] - p[0], q[1] - p[1]
    t0, t1 = 0.0, 1.0
    for pp, qq in ((-dx, p[0] - r[0]), (dx, r[2] - p[0]), (-dy, p[1] - r[1]), (dy, r[3] - p[1])):
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


def _leg_points(leg: Leg) -> list[Point]:
    return _cubic_points(leg.start, leg.c1, leg.c2, leg.end)


def _route_hits(legs: Sequence[Leg], obstacles: Sequence[Rect]) -> int:
    points: list[Point] = []
    for leg in legs:
        points.extend(_leg_points(leg) if not points else _leg_points(leg)[1:])
    return _polyline_hits(points, obstacles)


def _length(legs: Sequence[Leg]) -> float:
    total = 0.0
    for leg in legs:
        pts = _leg_points(leg)
        total += sum(math.dist(a, b) for a, b in zip(pts, pts[1:], strict=False))
    return total


def _straight(a: Point, b: Point, jitter: float = 0.0) -> Leg:
    dx, dy = b[0] - a[0], b[1] - a[1]
    return Leg(a, (a[0] + dx / 3.0, a[1] + dy / 3.0), (a[0] + 2 * dx / 3.0, a[1] + 2 * dy / 3.0), b, jitter)


def _margin_leg(start: Point, end: Point, jitter: float) -> Leg:
    """Leave the note level, arrive level: an S-curve kept inside the margin.

    Both control points lie between ``start.x`` and ``end.x``, so the whole
    curve does too (convex hull), and ``end`` sits short of the text column.
    """
    run = end[0] - start[0]
    if run <= 0.5:
        return _straight(start, end, jitter)
    reach = run * 0.6
    return Leg(start, (start[0] + reach, start[1]), (end[0] - reach, end[1]), end, jitter)


# --------------------------------------------------------------------------- #
# Planning (note on the left; the right side is mirrored into this case)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class _Page:
    note: Rect
    glyphs: tuple[Rect, ...]  # every glyph, quote included
    foreign: tuple[Rect, ...]  # glyphs outside the quote, grown by the clearance
    avoid: tuple[Rect, ...]  # other notes, grown by the clearance
    clearance: float

    def column_left(self, y_lo: float, y_hi: float) -> float | None:
        """Leftmost glyph edge right of the note between two heights."""
        xs = [
            g[0]
            for g in self.glyphs
            if g[3] >= y_lo and g[1] <= y_hi and g[0] >= self.note[2] - 0.5
        ]
        return min(xs) if xs else None

    @property
    def obstacles(self) -> tuple[Rect, ...]:
        return self.foreign + self.avoid


def _note_y(note: Rect, y: float) -> float:
    inset = min(3.0, (note[3] - note[1]) / 2.0)
    return min(max(y, note[1] + inset), note[3] - inset)


def _entry(page: _Page, start: Point, y: float, limit: float) -> float:
    """x where the pen turns into the text block at height *y*."""
    left = page.column_left(min(start[1], y) - 1.0, max(start[1], y) + 1.0)
    edge = limit if left is None else min(left, limit)
    return max(edge - COLUMN_STANDOFF, start[0])


def _open_route(page: _Page, quad: Rect, own: Sequence[Rect]) -> list[Leg]:
    ink_x0 = min(g[0] for g in own)
    y = sorted(_cy(g) for g in own)[len(own) // 2]
    tip = (ink_x0 - TIP_GAP - page.clearance, y)
    start = (page.note[2], _note_y(page.note, y))
    entry_x = _entry(page, start, y, tip[0] + COLUMN_STANDOFF)
    if entry_x >= tip[0] - 0.5:
        return [_margin_leg(start, tip, 0.0)]
    entry = (entry_x, y)
    return [_margin_leg(start, entry, 1.5), _straight(entry, tip)]


def _leading_route(
    page: _Page, quad: Rect, own: Sequence[Rect], above: bool
) -> list[Leg] | None:
    ink_x0 = min(g[0] for g in own)
    line_cy = _cy(quad)
    line_half = (quad[3] - quad[1]) / 2.0
    # The quote's line and the line beside it, over the stretch the lane covers.
    start_guess = (page.note[2], _note_y(page.note, line_cy))
    span_x0 = _entry(page, start_guess, line_cy, ink_x0)
    span_x1 = ink_x0 + 6.0
    in_span = [g for g in page.glyphs if g[2] >= span_x0 and g[0] <= span_x1]
    line = [g for g in in_span if abs(_cy(g) - line_cy) <= line_half]
    if not line:
        return None
    # The tip clears the tallest (or deepest) letter around the quote's first
    # word, so the bend onto it passes over the preceding word's ascenders.
    head = [g for g in line if ink_x0 - 8.0 <= g[0] <= ink_x0 + 12.0] or list(own)
    if above:
        line_edge = min(g[1] for g in line)
        beyond = [g[3] for g in in_span if g[3] <= line_edge + 0.01 and _cy(g) < line_cy - line_half]
        far_edge = max(beyond) if beyond else line_edge - OPEN_LANE
        gap = line_edge - far_edge
        lane_y = (line_edge + far_edge) / 2.0
        tip_y = min(g[1] for g in head) - TIP_GAP - page.clearance
    else:
        line_edge = max(g[3] for g in line)
        beyond = [g[1] for g in in_span if g[1] >= line_edge - 0.01 and _cy(g) > line_cy + line_half]
        far_edge = min(beyond) if beyond else line_edge + OPEN_LANE
        gap = far_edge - line_edge
        lane_y = (line_edge + far_edge) / 2.0
        tip_y = max(g[3] for g in head) + TIP_GAP + page.clearance
    if gap < MIN_LANE + 2.0 * page.clearance:
        return None
    tip = (ink_x0 + 1.2, tip_y)
    start = (page.note[2], _note_y(page.note, lane_y))
    entry_x = _entry(page, start, lane_y, ink_x0)
    turn_x = ink_x0 - TURN_RUN
    entry = (entry_x, lane_y)
    legs = [_margin_leg(start, entry, 1.5)]
    lane_half = max(0.0, gap / 2.0 - page.clearance)
    if turn_x > entry_x + 1.0:
        legs.append(_straight(entry, (turn_x, lane_y), jitter=0.3 * lane_half))
        turn = (turn_x, lane_y)
    else:
        turn = entry
    dx = tip[0] - turn[0]
    dy = tip[1] - turn[1]
    # Run level out of the lane, then bend down (or up) onto the quote's first
    # letter, arriving at about 45 degrees so the arrowhead reads as pointing
    # at the word. Every control point lies between the lane and the tip, so
    # the bend never drops below the tip's height, which clears the line.
    bend = min(abs(dy), dx * 0.5)
    legs.append(Leg(turn, (turn[0] + dx * 0.4, turn[1]), (tip[0] - bend, turn[1]), tip, 0.0))
    return legs


def plan_connector_route(
    note_box: LocalRect,
    target_quads: Sequence[LocalRect],
    glyphs: Sequence[LocalRect],
    *,
    other_notes: Sequence[LocalRect] = (),
    bounds: LocalRect,
    clearance: float,
) -> ConnectorRoute | None:
    """Plan a connector from a margin note to the near end of its quote.

    Returns ``None`` when the note is not beside the quote (above or below it)
    or the quote has no glyphs on the page; the caller then uses the generic
    router. Candidates are every line of the quote, approached level when
    nothing stands between the margin and the quote's near end, otherwise
    through the leading above and below the line. The cleanest, then shortest,
    wins; with no clean candidate, a short arrow to the column edge.
    """
    if not target_quads or not glyphs:
        return None
    quads = [_rect(q) for q in target_quads]
    note = _rect(note_box)
    if note[2] <= min(q[0] for q in quads) + 0.5:
        mirror_axis: float | None = None
    elif note[0] >= max(q[2] for q in quads) - 0.5:
        mirror_axis = bounds.x0 + bounds.x1
    else:
        return None

    all_glyphs = [_rect(g) for g in glyphs]
    notes = [_rect(n) for n in other_notes]
    if mirror_axis is not None:
        axis = mirror_axis
        quads = [_mirror_rect(q, axis) for q in quads]
        note = _mirror_rect(note, axis)
        all_glyphs = [_mirror_rect(g, axis) for g in all_glyphs]
        notes = [_mirror_rect(n, axis) for n in notes]

    def owner(g: Rect) -> int | None:
        cx, cy = (g[0] + g[2]) / 2.0, _cy(g)
        for index, q in enumerate(quads):
            if q[0] - 0.5 <= cx <= q[2] + 0.5 and q[1] - 0.5 <= cy <= q[3] + 0.5:
                return index
        return None

    owned: dict[int, list[Rect]] = {}
    foreign: list[Rect] = []
    for g in all_glyphs:
        index = owner(g)
        if index is None:
            foreign.append(_grow(g, clearance))
        else:
            owned.setdefault(index, []).append(g)
    if not owned:
        return None

    page = _Page(
        note=note,
        glyphs=tuple(all_glyphs),
        foreign=tuple(foreign),
        avoid=tuple(_grow(n, clearance) for n in notes),
        clearance=clearance,
    )
    obstacles = page.obstacles

    candidates: list[tuple[int, float, int, RouteKind, list[Leg]]] = []
    for index, own in sorted(owned.items()):
        quad = quads[index]
        ink_x0 = min(g[0] for g in own)
        line_half = (quad[3] - quad[1]) / 2.0
        before = [
            g
            for g in all_glyphs
            if g[2] <= ink_x0 + 0.5 and g[0] >= note[2] - 0.5 and abs(_cy(g) - _cy(quad)) <= line_half
            and owner(g) is None
        ]
        options: list[tuple[RouteKind, list[Leg] | None]]
        if not before:
            options = [(RouteKind.OPEN, _open_route(page, quad, own))]
        else:
            options = [
                (RouteKind.LEADING_ABOVE, _leading_route(page, quad, own, above=True)),
                (RouteKind.LEADING_BELOW, _leading_route(page, quad, own, above=False)),
            ]
        for kind, legs in options:
            if legs is None:
                continue
            hits = _route_hits(legs, obstacles)
            candidates.append((hits, _length(legs), len(candidates), kind, legs))

    clean = [c for c in candidates if c[0] == 0]
    if clean:
        _, _, _, kind, legs = min(clean, key=lambda c: (c[1], c[2]))
    else:
        # A short arrow to the column edge, level with the quote line nearest the note.
        index, own = min(
            owned.items(),
            key=lambda item: abs(_cy(quads[item[0]]) - _cy(note)),
        )
        y = sorted(_cy(g) for g in own)[len(own) // 2]
        start = (note[2], _note_y(note, y))
        stop_x = _entry(page, start, y, min(g[0] for g in own))
        legs = [_margin_leg(start, (max(stop_x, start[0] + 1.0), y), 1.5)]
        kind = RouteKind.SHORT
        if _route_hits(legs, obstacles) and candidates:
            # Even the margin is blocked: keep whichever route crosses least.
            best = min(candidates, key=lambda c: (c[0], c[1], c[2]))
            if best[0] < _route_hits(legs, obstacles):
                kind, legs = best[3], best[4]

    if mirror_axis is not None:
        axis = mirror_axis
        legs = [
            Leg(
                _mirror_point(leg.start, axis),
                _mirror_point(leg.c1, axis),
                _mirror_point(leg.c2, axis),
                _mirror_point(leg.end, axis),
                leg.jitter,
            )
            for leg in legs
        ]
        obstacles = tuple(_mirror_rect(r, axis) for r in obstacles)

    legs = [
        Leg(
            _point(*leg.start, bounds),
            _point(*leg.c1, bounds),
            _point(*leg.c2, bounds),
            _point(*leg.end, bounds),
            leg.jitter,
        )
        for leg in legs
    ]
    return ConnectorRoute(
        kind=kind,
        legs=tuple(legs),
        obstacles=obstacles,
        clean=_route_hits(legs, obstacles) == 0,
    )


# --------------------------------------------------------------------------- #
# Drawing
# --------------------------------------------------------------------------- #


def _wobbled(rng: random.Random, leg: Leg, scale: float, bounds: LocalRect) -> Leg:
    dx, dy = leg.end[0] - leg.start[0], leg.end[1] - leg.start[1]
    length = math.hypot(dx, dy)
    deviation1 = rng.gauss(0.0, 0.5)
    deviation2 = rng.gauss(0.0, 0.5)
    if length == 0.0 or leg.jitter <= 0.0 or scale <= 0.0:
        return leg
    nx, ny = -dy / length, dx / length
    amp = leg.jitter * scale
    d1 = max(-amp, min(amp, deviation1 * amp))
    d2 = max(-amp, min(amp, deviation2 * amp))
    return Leg(
        leg.start,
        _point(leg.c1[0] + nx * d1, leg.c1[1] + ny * d1, bounds),
        _point(leg.c2[0] + nx * d2, leg.c2[1] + ny * d2, bounds),
        leg.end,
        leg.jitter,
    )


def _commands(legs: Sequence[Leg]) -> tuple[MoveTo | CubicTo, ...]:
    commands: list[MoveTo | CubicTo] = [MoveTo(x=legs[0].start[0], y=legs[0].start[1])]
    for leg in legs:
        commands.append(
            CubicTo(x1=leg.c1[0], y1=leg.c1[1], x2=leg.c2[0], y2=leg.c2[1], x=leg.end[0], y=leg.end[1])
        )
    return tuple(commands)


def make_routed_connector(
    rng: random.Random,
    route: ConnectorRoute,
    style: InkStyleProfile,
    bounds: LocalRect,
    group_id: str = "connector",
) -> ConnectorResult:
    """Draw *route* with hand wobble and an arrowhead that fits its gap.

    The wobble is bounded per leg (zero on the final bend onto the quote) and
    dropped if it would touch a glyph the ideal route clears. Barbs shrink from
    ``BARB_MAX`` toward ``BARB_MIN`` until they clear every glyph. If any drawn
    stroke still touches an obstacle, ``ROUTING_FALLBACK`` is reported; the
    check covers every glyph outside the quote, including the lines on either
    side of the arrow tip.
    """
    obstacles = route.obstacles
    wobble = style.rough.wobble_amplitude / 0.05 if style.rough.wobble_amplitude > 0 else 0.0
    legs = [_wobbled(rng, leg, wobble, bounds) for leg in route.legs]
    if route.clean and _route_hits(legs, obstacles):
        legs = list(route.legs)
    tip = legs[-1].end
    last = legs[-1]
    tangent = (tip[0] - last.c2[0], tip[1] - last.c2[1])
    if math.hypot(*tangent) < 1e-6:
        tangent = (tip[0] - last.start[0], tip[1] - last.start[1])
    angle = math.atan2(tangent[1], tangent[0])
    spreads = (math.radians(rng.uniform(25.0, 45.0)), math.radians(rng.uniform(25.0, 45.0)))

    def barbs(length: float) -> list[tuple[Point, Point]]:
        out = []
        for sign, spread in zip((-1.0, 1.0), spreads, strict=True):
            a = angle + math.pi + sign * spread
            out.append((tip, _point(tip[0] + length * math.cos(a), tip[1] + length * math.sin(a), bounds)))
        return out

    total = _length(legs)
    length = min(BARB_MAX, max(BARB_MIN, total * 0.10))
    chosen = barbs(length)
    while length > BARB_MIN and any(_polyline_hits(b, obstacles) for b in chosen):
        length = max(BARB_MIN, length * 0.8)
        chosen = barbs(length)

    degradation: list[ConnectorDegradation] = []
    body = _commands(legs)
    paths: list[StrokePath] = []
    count = 0
    if _can_add(paths, count, len(body), style):
        paths.append(StrokePath(commands=body, stroke=_stroke(style)))
        count += len(body)
    for start, end in chosen:
        if not _can_add(paths, count, 2, style):
            break
        paths.append(
            StrokePath(
                commands=(MoveTo(x=start[0], y=start[1]), LineTo(x=end[0], y=end[1])),
                stroke=_stroke(style),
            )
        )
        count += 2
    if _route_hits(legs, obstacles) or any(_polyline_hits(b, obstacles) for b in chosen):
        degradation.append(ConnectorDegradation.ROUTING_FALLBACK)
    group = InkGroup(group_id=group_id, role=InkRole.CONNECTOR, paths=tuple(paths))
    return ConnectorResult(group=group, degradation=tuple(degradation))


__all__ = [
    "ConnectorRoute",
    "Leg",
    "RouteKind",
    "make_routed_connector",
    "plan_connector_route",
]
