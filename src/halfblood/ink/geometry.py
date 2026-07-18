"""Surface-neutral geometry operations for ink paths."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from halfblood.ink.model import Command, CubicTo, LocalPoint, MoveTo, WidthSample

_EPSILON = 1e-12
_CUBIC_SEGMENTS = 20
_CAP_SEGMENTS = 8
_JOIN_ANGLE_STEP = math.pi / 8.0
_MITER_LIMIT = 4.0

_Point = tuple[float, float]


class ExpansionError(Exception):
    """Raised when ``expand_stroke`` cannot produce a valid outline."""


class BudgetExceededError(Exception):
    """Raised when a command sequence exceeds the simplification budget."""


@dataclass(frozen=True)
class ExpandedOutline:
    """A counter-clockwise filled polygon expanded from a centerline."""

    vertices: tuple[LocalPoint, ...]
    degradation_flags: tuple[str, ...]


def _same_point(first: _Point, second: _Point) -> bool:
    return math.hypot(first[0] - second[0], first[1] - second[1]) <= _EPSILON


def _cubic_point(start: _Point, command: CubicTo, fraction: float) -> _Point:
    inverse = 1.0 - fraction
    x = (
        inverse**3 * start[0]
        + 3.0 * inverse**2 * fraction * command.x1
        + 3.0 * inverse * fraction**2 * command.x2
        + fraction**3 * command.x
    )
    y = (
        inverse**3 * start[1]
        + 3.0 * inverse**2 * fraction * command.y1
        + 3.0 * inverse * fraction**2 * command.y2
        + fraction**3 * command.y
    )
    return (x, y)


def _tessellate_subpaths(commands: Sequence[Command]) -> tuple[list[list[_Point]], bool]:
    subpaths: list[list[_Point]] = []
    current: list[_Point] | None = None
    current_point: _Point | None = None
    zero_length_encountered = False

    for command in commands:
        if isinstance(command, MoveTo):
            current_point = (float(command.x), float(command.y))
            current = [current_point]
            subpaths.append(current)
            continue
        if current is None or current_point is None:
            raise ExpansionError("Commands must begin with MoveTo")

        if isinstance(command, CubicTo):
            candidates = [
                _cubic_point(current_point, command, step / _CUBIC_SEGMENTS)
                for step in range(1, _CUBIC_SEGMENTS + 1)
            ]
        else:
            candidates = [(float(command.x), float(command.y))]

        for candidate in candidates:
            if _same_point(current[-1], candidate):
                zero_length_encountered = True
                continue
            current.append(candidate)
        current_point = (float(command.x), float(command.y))

    return ([subpath for subpath in subpaths if len(subpath) > 1], zero_length_encountered)


def _polyline_lengths(points: Sequence[_Point]) -> tuple[list[float], float]:
    cumulative = [0.0]
    for first, second in zip(points, points[1:], strict=False):
        cumulative.append(
            cumulative[-1] + math.hypot(second[0] - first[0], second[1] - first[1])
        )
    return cumulative, cumulative[-1]


def _profile_width(width_profile: Sequence[WidthSample], position: float) -> float:
    if not width_profile:
        return 1.0

    samples = sorted(width_profile, key=lambda sample: sample.position)
    if position <= samples[0].position:
        return float(samples[0].width)
    if position >= samples[-1].position:
        return float(samples[-1].width)

    for first, second in zip(samples, samples[1:], strict=False):
        if position <= second.position:
            span = second.position - first.position
            if span <= _EPSILON:
                return float(second.width)
            fraction = (position - first.position) / span
            return float(first.width + fraction * (second.width - first.width))
    return float(samples[-1].width)


def _unit_tangent(first: _Point, second: _Point) -> _Point:
    dx = second[0] - first[0]
    dy = second[1] - first[1]
    length = math.hypot(dx, dy)
    if length <= _EPSILON:
        raise ExpansionError("Cannot determine a tangent for a zero-length segment")
    return (dx / length, dy / length)


def _offset(point: _Point, direction: _Point, distance: float) -> _Point:
    return (point[0] + direction[0] * distance, point[1] + direction[1] * distance)


def _arc_points(
    center: _Point,
    radius: float,
    start_angle: float,
    delta: float,
    segments: int,
) -> list[_Point]:
    return [
        (
            center[0] + radius * math.cos(start_angle + delta * step / segments),
            center[1] + radius * math.sin(start_angle + delta * step / segments),
        )
        for step in range(segments + 1)
    ]


def _inner_join(
    point: _Point,
    incoming_normal: _Point,
    outgoing_normal: _Point,
    half_width: float,
) -> _Point:
    bisector = (
        incoming_normal[0] + outgoing_normal[0],
        incoming_normal[1] + outgoing_normal[1],
    )
    bisector_length = math.hypot(*bisector)
    if bisector_length <= _EPSILON:
        return _offset(point, outgoing_normal, half_width)

    unit_bisector = (bisector[0] / bisector_length, bisector[1] / bisector_length)
    projection = unit_bisector[0] * outgoing_normal[0] + unit_bisector[1] * outgoing_normal[1]
    if abs(projection) <= _EPSILON:
        miter_length = half_width
    else:
        miter_length = min(half_width / abs(projection), half_width * _MITER_LIMIT)
    return _offset(point, unit_bisector, miter_length)


def _outside_join(
    point: _Point,
    incoming_normal: _Point,
    outgoing_normal: _Point,
    half_width: float,
    turn: float,
) -> list[_Point]:
    start_angle = math.atan2(incoming_normal[1], incoming_normal[0])
    end_angle = math.atan2(outgoing_normal[1], outgoing_normal[0])
    if turn > 0.0:
        delta = (end_angle - start_angle) % math.tau
    else:
        delta = -((start_angle - end_angle) % math.tau)
    segments = max(1, math.ceil(abs(delta) / _JOIN_ANGLE_STEP))
    return _arc_points(point, half_width, start_angle, delta, segments)


def _side_vertices(
    points: Sequence[_Point],
    tangents: Sequence[_Point],
    half_widths: Sequence[float],
    *,
    side: float,
) -> list[_Point]:
    first_normal = (-tangents[0][1] * side, tangents[0][0] * side)
    vertices = [_offset(points[0], first_normal, half_widths[0])]

    for index in range(1, len(points) - 1):
        incoming = tangents[index - 1]
        outgoing = tangents[index]
        incoming_normal = (-incoming[1] * side, incoming[0] * side)
        outgoing_normal = (-outgoing[1] * side, outgoing[0] * side)
        turn = incoming[0] * outgoing[1] - incoming[1] * outgoing[0]
        outside = turn * side < -_EPSILON

        if outside:
            join = _outside_join(
                points[index],
                incoming_normal,
                outgoing_normal,
                half_widths[index],
                turn,
            )
            vertices.extend(join)
        else:
            vertices.append(
                _inner_join(
                    points[index], incoming_normal, outgoing_normal, half_widths[index]
                )
            )

    last_normal = (-tangents[-1][1] * side, tangents[-1][0] * side)
    vertices.append(_offset(points[-1], last_normal, half_widths[-1]))
    return vertices


def _signed_area(vertices: Sequence[_Point]) -> float:
    area = 0.0
    for first, second in zip(vertices, (*vertices[1:], vertices[0]), strict=True):
        area += first[0] * second[1] - second[0] * first[1]
    return area / 2.0


def _expand_polyline(points: Sequence[_Point], half_widths: Sequence[float]) -> list[_Point]:
    tangents = [_unit_tangent(first, second) for first, second in zip(points, points[1:], strict=False)]
    left = _side_vertices(points, tangents, half_widths, side=1.0)
    right = _side_vertices(points, tangents, half_widths, side=-1.0)

    end_tangent = tangents[-1]
    end_normal_angle = math.atan2(end_tangent[0], -end_tangent[1])
    end_cap = _arc_points(
        points[-1], half_widths[-1], end_normal_angle, -math.pi, _CAP_SEGMENTS
    )

    start_tangent = tangents[0]
    start_right_angle = math.atan2(-start_tangent[0], start_tangent[1])
    start_cap = _arc_points(
        points[0], half_widths[0], start_right_angle, -math.pi, _CAP_SEGMENTS
    )

    polygon = left + end_cap[1:-1] + list(reversed(right)) + start_cap[1:-1]
    if _signed_area(polygon) < 0.0:
        polygon.reverse()
    return polygon


def _limit_points(vertices: list[_Point], max_points: int) -> list[_Point]:
    if len(vertices) <= max_points:
        return vertices
    count = len(vertices)
    return [vertices[index * count // max_points] for index in range(max_points)]


def expand_stroke(
    commands: Sequence[Command],
    width_profile: Sequence[WidthSample],
    base_width: float,
    *,
    max_points: int = 512,
) -> ExpandedOutline:
    """Expand a centerline and width profile into a CCW filled outline polygon."""

    if not commands:
        raise ExpansionError("Cannot expand an empty command sequence")
    if not math.isfinite(base_width) or base_width <= 0.0:
        raise ExpansionError("base_width must be a finite positive number")
    if max_points < 3:
        raise ExpansionError("max_points must allow at least three polygon vertices")
    if not any(not isinstance(command, MoveTo) for command in commands):
        raise ExpansionError("Cannot expand a path without drawing commands")

    subpaths, had_zero_length = _tessellate_subpaths(commands)
    if not subpaths:
        raise ExpansionError("The path contains no non-zero drawing segments")
    if any(_same_point(subpath[0], subpath[-1]) for subpath in subpaths):
        raise ExpansionError("Closed centerlines require annular outline support")

    length_data = [_polyline_lengths(subpath) for subpath in subpaths]
    total_length = sum(length for _, length in length_data)
    if total_length <= _EPSILON:
        raise ExpansionError("The path has zero total length")

    polygons: list[list[_Point]] = []
    length_before = 0.0
    for subpath, (cumulative, subpath_length) in zip(subpaths, length_data, strict=True):
        half_widths = [
            base_width
            * _profile_width(width_profile, (length_before + distance) / total_length)
            / 2.0
            for distance in cumulative
        ]
        polygons.append(_expand_polyline(subpath, half_widths))
        length_before += subpath_length

    vertices = _limit_points([vertex for polygon in polygons for vertex in polygon], max_points)
    if len(vertices) < 3 or abs(_signed_area(vertices)) <= _EPSILON:
        raise ExpansionError("Expansion produced a degenerate outline")
    if _signed_area(vertices) < 0.0:
        vertices.reverse()
    if not all(math.isfinite(coordinate) for vertex in vertices for coordinate in vertex):
        raise ExpansionError("Expansion produced non-finite coordinates")

    flags = ("zero_length_segment",) if had_zero_length else ()
    return ExpandedOutline(
        vertices=tuple(LocalPoint(x=float(x), y=float(y)) for x, y in vertices),
        degradation_flags=flags,
    )


def _point_segment_distance(point: _Point, start: _Point, end: _Point) -> float:
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    length_squared = dx * dx + dy * dy
    if length_squared <= _EPSILON:
        return math.hypot(point[0] - start[0], point[1] - start[1])
    fraction = ((point[0] - start[0]) * dx + (point[1] - start[1]) * dy) / length_squared
    fraction = min(1.0, max(0.0, fraction))
    nearest = (start[0] + fraction * dx, start[1] + fraction * dy)
    return math.hypot(point[0] - nearest[0], point[1] - nearest[1])


def _douglas_peucker(commands: Sequence[Command], tolerance: float) -> list[Command]:
    if len(commands) <= 2:
        return list(commands)

    points = [(float(command.x), float(command.y)) for command in commands]
    keep = [False] * len(commands)
    keep[0] = True
    keep[-1] = True
    pending = [(0, len(commands) - 1)]

    while pending:
        start_index, end_index = pending.pop()
        farthest_index = -1
        farthest_distance = -1.0
        for index in range(start_index + 1, end_index):
            distance = _point_segment_distance(
                points[index], points[start_index], points[end_index]
            )
            if distance > farthest_distance:
                farthest_distance = distance
                farthest_index = index
        if farthest_index >= 0 and farthest_distance > tolerance:
            keep[farthest_index] = True
            pending.append((start_index, farthest_index))
            pending.append((farthest_index, end_index))

    return [command for index, command in enumerate(commands) if keep[index]]


def simplify_commands(
    commands: Sequence[Command],
    *,
    tolerance: float,
    budget: int,
) -> tuple[Command, ...]:
    """Simplify each pen-down subpath using Douglas-Peucker reduction."""
    if len(commands) > budget:
        raise BudgetExceededError(f"Input has {len(commands)} commands, budget is {budget}")

    if not commands:
        raise ValueError("commands must be non-empty")
    if not isinstance(commands[0], MoveTo):
        raise ValueError("commands must begin with MoveTo")
    if not math.isfinite(tolerance) or tolerance < 0.0:
        raise ValueError("tolerance must be a finite non-negative number")

    subpaths: list[list[Command]] = []
    for command in commands:
        if isinstance(command, MoveTo):
            subpaths.append([command])
        elif not subpaths:
            raise ValueError("commands must begin with MoveTo")
        else:
            subpaths[-1].append(command)

    result: list[Command] = []
    for subpath in subpaths:
        result.extend(_douglas_peucker(subpath, tolerance))
    if len(result) < 2:
        raise ValueError("commands must contain a drawing endpoint")
    return tuple(result)


__all__ = [
    "BudgetExceededError",
    "ExpandedOutline",
    "ExpansionError",
    "expand_stroke",
    "simplify_commands",
]
