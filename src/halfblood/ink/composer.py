"""Pure composition of resolved annotations into immutable ink scenes."""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from enum import Enum
from typing import Literal, Protocol, TypeAlias

from halfblood.ink.connector_route import (
    ConnectorRoute,
    make_routed_connector,
    plan_connector_route,
)
from halfblood.ink.geometry import BudgetExceededError, simplify_commands
from halfblood.ink.model import (
    CubicTo,
    InkGroup,
    InkRole,
    InkScene,
    LineTo,
    LocalPoint,
    LocalRect,
    MoveTo,
    StrokePath,
)
from halfblood.ink.rough import (
    ConnectorDegradation,
    DoodleKind,
    make_caret,
    make_circle,
    make_connector,
    make_doodle,
    make_highlight,
    make_strike,
    make_underline,
)
from halfblood.ink.seeding import derive_seed
from halfblood.ink.style import InkStyleProfile
from halfblood.models.annotations import Annotation, MarkIntent
from halfblood.models.legacy import AnnotationType
from halfblood.models.rendering import ResolvedAnnotation, SurfaceQuad, SurfaceRect

HandwritingMode: TypeAlias = Literal["typeset", "procedural"]


class RoughRole(str, Enum):  # noqa: UP042 - preserve the pinned string-enum API.
    """Independent rough-generation roles used by the composer."""

    UNDERLINE = "underline"
    CIRCLE = "circle"
    STRIKE = "strike"
    HIGHLIGHT = "highlight"
    CARET = "caret"
    CONNECTOR = "connector"
    DOODLE = "doodle"


@dataclass(frozen=True)
class ComposeRequest:
    """Semantic annotation joined to its resolved page geometry."""

    annotation: Annotation
    resolved: ResolvedAnnotation
    document_seed: int
    page_bounds: SurfaceRect
    obstacles: tuple[SurfaceRect, ...] = ()
    #: Every note box placed on the page. Marks must not draw over them.
    note_boxes: tuple[SurfaceRect, ...] = ()
    #: Tight glyph ink boxes for the page (``PageOccupancy.glyphs``). When
    #: present, a margin note's connector is routed through the leading to the
    #: quote's near end instead of by the generic obstacle router.
    glyphs: tuple[SurfaceRect, ...] = ()


@dataclass(frozen=True)
class RoughRequest:
    """Page-local generator input for one isolated rough role."""

    role: RoughRole
    composition: ComposeRequest
    local_bounds: LocalRect
    local_target_quads: tuple[LocalRect, ...]
    local_note_box: LocalRect | None
    note_edge: LocalPoint | None = None
    target_edge: LocalPoint | None = None
    doodle_kind: DoodleKind | None = None
    interline_gap: float | None = None
    connector_route: ConnectorRoute | None = None


@dataclass(frozen=True)
class InkDegradation:
    """Typed, bounded explanation of omitted or degraded composition geometry."""

    annotation_id: str
    role: RoughRole | InkRole | None
    code: str
    detail: str = ""


@dataclass(frozen=True)
class RoughResult:
    groups: tuple[InkGroup, ...]
    degradations: tuple[InkDegradation, ...] = ()


class RoughInkEngine(Protocol):
    def generate(
        self,
        request: RoughRequest,
        *,
        style: InkStyleProfile,
        seed: int,
    ) -> RoughResult: ...


@dataclass(frozen=True)
class HandwritingRequest:
    annotation_id: str
    text: str
    box: LocalRect


@dataclass(frozen=True)
class HandwritingReady:
    group: InkGroup
    degradations: tuple[InkDegradation, ...] = ()


@dataclass(frozen=True)
class HandwritingUnavailable:
    engine: Literal["procedural"] = "procedural"
    code: Literal["p3_t5_no_go"] = "p3_t5_no_go"
    detail: str = "Procedural letterforms unavailable — P3-T5 NO-GO."


HandwritingResult: TypeAlias = HandwritingReady | HandwritingUnavailable


class HandwritingEngine(Protocol):
    def synthesize(
        self,
        request: HandwritingRequest,
        *,
        style: InkStyleProfile,
        seed: int,
    ) -> HandwritingResult: ...


@dataclass(frozen=True)
class TypesetBody:
    text: str


BodyResult: TypeAlias = TypesetBody | HandwritingReady | HandwritingUnavailable


@dataclass(frozen=True)
class CompositionResult:
    scene: InkScene
    body: BodyResult
    degradations: tuple[InkDegradation, ...]


class PathPostprocessor(Protocol):
    def process(
        self,
        path: StrokePath,
        *,
        bounds: LocalRect,
        tolerance: float,
        input_budget: int,
    ) -> StrokePath | None: ...


def _in_bounds(value: float, low: float, high: float) -> bool:
    return math.isfinite(value) and low <= value <= high


def _path_geometry_is_valid(path: StrokePath, bounds: LocalRect) -> bool:
    """Validate raw and transformed endpoints/control points against scene bounds."""

    a, b, c, d, e, f = path.transform.matrix

    def valid_point(x: float, y: float) -> bool:
        if not (_in_bounds(x, bounds.x0, bounds.x1) and _in_bounds(y, bounds.y0, bounds.y1)):
            return False
        transformed_x = a * x + c * y + e
        transformed_y = b * x + d * y + f
        return _in_bounds(transformed_x, bounds.x0, bounds.x1) and _in_bounds(
            transformed_y, bounds.y0, bounds.y1
        )

    for command in path.commands:
        if not valid_point(command.x, command.y):
            return False
        if isinstance(command, CubicTo) and not (
            valid_point(command.x1, command.y1) and valid_point(command.x2, command.y2)
        ):
            return False
    return all(valid_point(sample.x, sample.y) for sample in path.samples)


def _clamp(value: float, low: float, high: float) -> float:
    return min(max(value, low), high)


def _clip_commands(
    path: StrokePath,
    bounds: LocalRect,
) -> tuple[MoveTo | LineTo | CubicTo, ...] | None:
    """Clip command coordinates to the local surface rectangle.

    Rough generators already constrain paths to the surface. This defensive pass
    clamps occasional numeric overshoot, including Bézier controls, before the
    stricter transformed-geometry validation below.
    """

    commands: list[MoveTo | LineTo | CubicTo] = []
    for command in path.commands:
        coordinates = [command.x, command.y]
        if isinstance(command, CubicTo):
            coordinates.extend((command.x1, command.y1, command.x2, command.y2))
        if not all(math.isfinite(value) for value in coordinates):
            return None
        x = _clamp(command.x, bounds.x0, bounds.x1)
        y = _clamp(command.y, bounds.y0, bounds.y1)
        if isinstance(command, MoveTo):
            commands.append(MoveTo(x=x, y=y))
        elif isinstance(command, LineTo):
            commands.append(LineTo(x=x, y=y))
        else:
            commands.append(
                CubicTo(
                    x1=_clamp(command.x1, bounds.x0, bounds.x1),
                    y1=_clamp(command.y1, bounds.y0, bounds.y1),
                    x2=_clamp(command.x2, bounds.x0, bounds.x1),
                    y2=_clamp(command.y2, bounds.y0, bounds.y1),
                    x=x,
                    y=y,
                )
            )
    return tuple(commands)


class DefaultPathPostprocessor:
    """Clip, simplify safe polylines, and validate a generated path once."""

    def process(
        self,
        path: StrokePath,
        *,
        bounds: LocalRect,
        tolerance: float,
        input_budget: int,
    ) -> StrokePath | None:
        if input_budget <= 0 or len(path.commands) > input_budget:
            return None
        clipped = _clip_commands(path, bounds)
        if clipped is None:
            return None

        commands = clipped
        if not any(isinstance(command, CubicTo) for command in commands):
            try:
                commands = simplify_commands(
                    commands,
                    tolerance=tolerance,
                    budget=input_budget,
                )
            except (BudgetExceededError, ValueError):
                return None

        try:
            processed = path.model_copy(update={"commands": commands})
        except ValueError:
            return None
        return processed if _path_geometry_is_valid(processed, bounds) else None


class P3T5NoGoHandwritingEngine:
    """Typed adapter for the P3-T5 procedural-letterform NO-GO decision."""

    def synthesize(
        self,
        request: HandwritingRequest,
        *,
        style: InkStyleProfile,
        seed: int,
    ) -> HandwritingUnavailable:
        del request, style, seed
        return HandwritingUnavailable()


def _degradation(
    request: RoughRequest,
    code: str,
    detail: str,
) -> RoughResult:
    return RoughResult(
        groups=(),
        degradations=(
            InkDegradation(
                annotation_id=request.composition.annotation.id,
                role=request.role,
                code=code,
                detail=detail,
            ),
        ),
    )


class BuiltinRoughInkEngine:
    """Adapter from composer roles to the built-in deterministic rough generators."""

    def generate(
        self,
        request: RoughRequest,
        *,
        style: InkStyleProfile,
        seed: int,
    ) -> RoughResult:
        rng = random.Random(seed)
        role = request.role
        group_id = f"{role.value}-{request.composition.annotation.id}"

        if role in {
            RoughRole.UNDERLINE,
            RoughRole.CIRCLE,
            RoughRole.STRIKE,
            RoughRole.HIGHLIGHT,
        } and not request.local_target_quads:
            return _degradation(request, "missing_target_geometry", "No target quads were resolved.")

        if role is RoughRole.UNDERLINE:
            group = make_underline(
                rng, request.local_target_quads, style, request.local_bounds, group_id
            )
        elif role is RoughRole.CIRCLE:
            page = request.composition.page_bounds
            avoid = tuple(
                _surface_rect_to_local(rect, page) for rect in request.composition.note_boxes
            )
            if request.local_note_box is not None:
                avoid = (*avoid, request.local_note_box)
            group = make_circle(
                rng,
                request.local_target_quads,
                style,
                request.local_bounds,
                group_id,
                avoid=avoid,
            )
        elif role is RoughRole.STRIKE:
            group = make_strike(
                rng, request.local_target_quads, style, request.local_bounds, group_id
            )
        elif role is RoughRole.HIGHLIGHT:
            group = make_highlight(
                rng, request.local_target_quads, style, request.local_bounds, group_id
            )
        elif role is RoughRole.CARET:
            if request.target_edge is None or request.interline_gap is None:
                return _degradation(
                    request,
                    "caret_interline_gap_unavailable",
                    "Resolved geometry does not supply a real interline gap.",
                )
            group = make_caret(
                rng,
                request.target_edge,
                request.interline_gap,
                style,
                request.local_bounds,
                group_id,
            )
        elif role is RoughRole.CONNECTOR:
            if request.note_edge is None or request.target_edge is None:
                return _degradation(
                    request,
                    "connector_geometry_unavailable",
                    "A note edge and target edge are required for connector generation.",
                )
            if request.connector_route is not None:
                connector = make_routed_connector(
                    rng, request.connector_route, style, request.local_bounds, group_id
                )
                return RoughResult(
                    groups=(connector.group,),
                    degradations=tuple(
                        InkDegradation(
                            annotation_id=request.composition.annotation.id,
                            role=role,
                            code=value.value,
                            detail=(
                                "Connector still touches body text or another note "
                                f"({request.connector_route.kind.value} route)."
                            ),
                        )
                        for value in connector.degradation
                    ),
                )
            obstacles = tuple(
                _surface_rect_to_local(rect, request.composition.page_bounds)
                for rect in request.composition.obstacles
            )
            connector = make_connector(
                rng,
                request.note_edge,
                request.target_edge,
                obstacles,
                max(style.nib.base_width * 2.0, 1.0),
                style,
                request.local_bounds,
                group_id,
            )
            _connector_details: dict[ConnectorDegradation, str] = {
                ConnectorDegradation.ROUTING_FALLBACK: (
                    "Connector routing exhausted all waypoint attempts; "
                    "direct path used as fallback."
                ),
                ConnectorDegradation.OBSTACLE_CAP_USED: (
                    "Obstacle set was capped before routing; "
                    "distant obstacles were dropped."
                ),
            }
            degradations = tuple(
                InkDegradation(
                    annotation_id=request.composition.annotation.id,
                    role=role,
                    code=value.value,
                    detail=_connector_details.get(value, value.value),
                )
                for value in connector.degradation
            )
            return RoughResult(groups=(connector.group,), degradations=degradations)
        else:
            if request.doodle_kind is None:
                return _degradation(
                    request,
                    "doodle_kind_unavailable",
                    "No valid semantic doodle kind was supplied.",
                )
            box = request.local_note_box
            if box is None and request.local_target_quads:
                box = _rect_union(request.local_target_quads)
            if box is None:
                return _degradation(
                    request,
                    "doodle_geometry_unavailable",
                    "No note or target geometry was resolved for doodle placement.",
                )
            # The doodle sits just above the note's top-left corner, not on the
            # box centre: centred, it was drawn straight across the note's own
            # handwriting (observed on real-model renders of Alice, 2026-10-22).
            # Small and capped so it fits the gap between stacked notes.
            size = max(1.0, min(5.5, min(box.x1 - box.x0, box.y1 - box.y0) * 0.12))
            center = LocalPoint(x=box.x0 + size * 1.2, y=box.y0 - size * 1.3)
            group = make_doodle(
                rng,
                request.doodle_kind,
                center,
                size,
                style,
                request.local_bounds,
                group_id,
            )
        return RoughResult(groups=(group,))


_MARK_ROLES: dict[MarkIntent, RoughRole] = {
    MarkIntent.UNDERLINE: RoughRole.UNDERLINE,
    MarkIntent.CIRCLE: RoughRole.CIRCLE,
    MarkIntent.STRIKE: RoughRole.STRIKE,
    MarkIntent.HIGHLIGHT: RoughRole.HIGHLIGHT,
    MarkIntent.CARET: RoughRole.CARET,
}

_Z_INDEX: dict[RoughRole, int] = {
    RoughRole.HIGHLIGHT: -100,
    RoughRole.UNDERLINE: 0,
    RoughRole.CIRCLE: 0,
    RoughRole.STRIKE: 0,
    RoughRole.CARET: 0,
    RoughRole.CONNECTOR: 100,
    RoughRole.DOODLE: 200,
}


def _surface_quad_to_local(quad: SurfaceQuad, page: SurfaceRect) -> LocalRect:
    points = (quad.ul, quad.ur, quad.lr, quad.ll)
    return LocalRect(
        x0=min(point.x for point in points) - page.x0,
        y0=min(point.y for point in points) - page.y0,
        x1=max(point.x for point in points) - page.x0,
        y1=max(point.y for point in points) - page.y0,
    )


def _surface_rect_to_local(rect: SurfaceRect, page: SurfaceRect) -> LocalRect:
    return LocalRect(
        x0=rect.x0 - page.x0,
        y0=rect.y0 - page.y0,
        x1=rect.x1 - page.x0,
        y1=rect.y1 - page.y0,
    )


def _rect_union(rects: tuple[LocalRect, ...]) -> LocalRect:
    return LocalRect(
        x0=min(rect.x0 for rect in rects),
        y0=min(rect.y0 for rect in rects),
        x1=max(rect.x1 for rect in rects),
        y1=max(rect.y1 for rect in rects),
    )


def _closest_rect_points(first: LocalRect, second: LocalRect) -> tuple[LocalPoint, LocalPoint]:
    """Return deterministic nearest perimeter points for two axis-aligned rectangles."""

    first_center_x = (first.x0 + first.x1) / 2.0
    first_center_y = (first.y0 + first.y1) / 2.0
    second_center_x = (second.x0 + second.x1) / 2.0
    second_center_y = (second.y0 + second.y1) / 2.0

    if first.x1 < second.x0:
        first_x, second_x = first.x1, second.x0
    elif second.x1 < first.x0:
        first_x, second_x = first.x0, second.x1
    else:
        shared_x = _clamp(
            (first_center_x + second_center_x) / 2.0,
            max(first.x0, second.x0),
            min(first.x1, second.x1),
        )
        first_x = second_x = shared_x

    if first.y1 < second.y0:
        first_y, second_y = first.y1, second.y0
    elif second.y1 < first.y0:
        first_y, second_y = first.y0, second.y1
    else:
        shared_y = _clamp(
            (first_center_y + second_center_y) / 2.0,
            max(first.y0, second.y0),
            min(first.y1, second.y1),
        )
        first_y = second_y = shared_y

    return LocalPoint(x=first_x, y=first_y), LocalPoint(x=second_x, y=second_y)


#: How far (page points) a same-line text obstacle must extend past the target
#: quad's note-facing edge before it counts as text in the connector's way. The
#: occupancy provider pads each line run by 1.5pt, so a target that ends flush
#: with its line must not register as blocked.
_SAME_LINE_SLACK = 3.0

#: Inset (page points) from the target's note-facing end at which a connector
#: lands when it has to arrive on the quad's top or bottom edge.
_EDGE_LANDING_INSET = 3.0


def _text_continues_toward_note(
    quad: LocalRect,
    note_box: LocalRect,
    obstacles: tuple[LocalRect, ...],
) -> bool:
    """True when body text sits on the quad's own line between it and the note.

    A quote that ends mid-line (``... she`` followed by ``opened it,``) has its
    note-facing side edge pressed against the next word. A connector landing on
    that edge must run back through the rest of the line to reach it.
    """
    mid_y = (quad.y0 + quad.y1) / 2.0
    for obstacle in obstacles:
        if not obstacle.y0 <= mid_y <= obstacle.y1:
            continue
        note_right = note_box.x0 >= quad.x1
        note_left = note_box.x1 <= quad.x0
        if note_right and quad.x1 + _SAME_LINE_SLACK < obstacle.x1 and obstacle.x0 < note_box.x0:
            return True
        if note_left and obstacle.x0 < quad.x0 - _SAME_LINE_SLACK and obstacle.x1 > note_box.x1:
            return True
    return False


def _line_edge_points(note_box: LocalRect, quad: LocalRect) -> tuple[LocalPoint, LocalPoint]:
    """Land on the quad's top or bottom edge near its note-facing end.

    The connector then runs along the gap between lines instead of across the
    words that follow the quote on its line.
    """
    # Top edge unless the note sits wholly below the quote's line.
    target_y = quad.y1 if note_box.y0 >= quad.y1 else quad.y0
    inset = min(_EDGE_LANDING_INSET, (quad.x1 - quad.x0) / 2.0)
    if note_box.x0 >= quad.x1:
        target_x, note_x = quad.x1 - inset, note_box.x0
    else:
        target_x, note_x = quad.x0 + inset, note_box.x1
    note_y = _clamp(target_y, note_box.y0, note_box.y1)
    return LocalPoint(x=note_x, y=note_y), LocalPoint(x=target_x, y=target_y)


def _connector_edges(
    note_box: LocalRect,
    target_quads: tuple[LocalRect, ...],
    obstacles: tuple[LocalRect, ...] = (),
) -> tuple[LocalPoint, LocalPoint]:
    candidates: list[tuple[float, int, LocalPoint, LocalPoint]] = []
    for index, quad in enumerate(target_quads):
        if _text_continues_toward_note(quad, note_box, obstacles):
            note_point, target_point = _line_edge_points(note_box, quad)
        else:
            note_point, target_point = _closest_rect_points(note_box, quad)
        distance = math.hypot(note_point.x - target_point.x, note_point.y - target_point.y)
        candidates.append((distance, index, note_point, target_point))
    _, _, note_edge, target_edge = min(candidates, key=lambda candidate: candidate[:2])
    return note_edge, target_edge


class InkComposer:
    """Compose one annotation without mutating shared or live renderer state."""

    def __init__(
        self,
        rough_engine: RoughInkEngine,
        handwriting_engine: HandwritingEngine,
        *,
        path_postprocessor: PathPostprocessor,
        algorithm_version: str,
    ) -> None:
        self._rough_engine = rough_engine
        self._handwriting_engine = handwriting_engine
        self._path_postprocessor = path_postprocessor
        self._algorithm_version = algorithm_version

    def compose(
        self,
        request: ComposeRequest,
        style: InkStyleProfile,
        *,
        handwriting_mode: HandwritingMode = "typeset",
        mark_only: bool = False,
    ) -> CompositionResult:
        if request.annotation.id != request.resolved.annotation_id:
            raise ValueError("annotation.id must match resolved.annotation_id")
        if handwriting_mode not in ("typeset", "procedural"):
            raise ValueError(f"unsupported handwriting mode: {handwriting_mode!r}")

        page = request.page_bounds
        bounds = LocalRect(x0=0.0, y0=0.0, x1=page.x1 - page.x0, y1=page.y1 - page.y0)
        anchor = request.resolved.anchor
        target_quads = (
            tuple(_surface_quad_to_local(quad, page) for quad in anchor.quads)
            if anchor is not None
            else ()
        )
        note_box = (
            _surface_rect_to_local(request.resolved.note_box, page)
            if request.resolved.note_box is not None
            else None
        )

        note_edge: LocalPoint | None = None
        target_edge: LocalPoint | None = None
        connector_route: ConnectorRoute | None = None
        if note_box is not None and target_quads and request.glyphs and not mark_only:
            own_box = request.resolved.note_box
            connector_route = plan_connector_route(
                note_box,
                target_quads,
                tuple(_surface_rect_to_local(rect, page) for rect in request.glyphs),
                other_notes=tuple(
                    _surface_rect_to_local(rect, page)
                    for rect in request.note_boxes
                    if rect != own_box
                ),
                bounds=bounds,
                clearance=style.nib.base_width / 2.0,
            )
        if connector_route is not None:
            note_edge = LocalPoint(x=connector_route.start[0], y=connector_route.start[1])
            target_edge = LocalPoint(x=connector_route.tip[0], y=connector_route.tip[1])
        elif note_box is not None and target_quads:
            local_obstacles = tuple(
                _surface_rect_to_local(rect, page) for rect in request.obstacles
            )
            note_edge, target_edge = _connector_edges(note_box, target_quads, local_obstacles)

        degradations: list[InkDegradation] = []
        doodle_kind: DoodleKind | None = None
        if request.annotation.doodle_kind is not None:
            try:
                doodle_kind = DoodleKind(request.annotation.doodle_kind)
            except ValueError:
                degradations.append(
                    InkDegradation(
                        annotation_id=request.annotation.id,
                        role=RoughRole.DOODLE,
                        code="unknown_doodle_kind",
                        detail=f"Unknown semantic doodle kind: {request.annotation.doodle_kind!r}.",
                    )
                )
        elif request.annotation.annotation_type is AnnotationType.DOODLE_NOTE:
            doodle_kind = DoodleKind.STAR

        roles: list[RoughRole] = []
        mark_role = _MARK_ROLES.get(request.annotation.mark_intent)
        if mark_role is not None:
            roles.append(mark_role)
        if not mark_only:
            if note_edge is not None and target_edge is not None:
                roles.append(RoughRole.CONNECTOR)
            if doodle_kind is not None:
                roles.append(RoughRole.DOODLE)

        groups: list[InkGroup] = []
        total_paths = 0
        total_commands = 0
        for role in roles:
            rough_request = RoughRequest(
                role=role,
                composition=request,
                local_bounds=bounds,
                local_target_quads=target_quads,
                local_note_box=note_box,
                note_edge=note_edge,
                target_edge=target_edge,
                doodle_kind=doodle_kind,
                connector_route=connector_route,
            )
            seed = derive_seed(
                request.document_seed,
                request.annotation.id,
                role.value,
                self._algorithm_version,
                "composer",
            )
            rough_result = self._rough_engine.generate(rough_request, style=style, seed=seed)
            degradations.extend(rough_result.degradations)
            processed_groups, total_paths, total_commands = self._process_groups(
                rough_result.groups,
                role=role,
                bounds=bounds,
                style=style,
                total_paths=total_paths,
                total_commands=total_commands,
                degradations=degradations,
                annotation_id=request.annotation.id,
            )
            groups.extend(processed_groups)

        body: BodyResult
        if handwriting_mode == "typeset":
            body = TypesetBody(text=request.annotation.content)
        elif note_box is None:
            body = HandwritingUnavailable(
                detail="Procedural letterforms unavailable because no note box was resolved."
            )
        else:
            handwriting_request = HandwritingRequest(
                annotation_id=request.annotation.id,
                text=request.annotation.content,
                box=note_box,
            )
            handwriting_seed = derive_seed(
                request.document_seed,
                request.annotation.id,
                InkRole.HANDWRITING.value,
                self._algorithm_version,
                "composer",
            )
            body = self._handwriting_engine.synthesize(
                handwriting_request,
                style=style,
                seed=handwriting_seed,
            )
            if isinstance(body, HandwritingReady):
                degradations.extend(body.degradations)
                ready_groups, total_paths, total_commands = self._process_groups(
                    (body.group,),
                    role=InkRole.HANDWRITING,
                    bounds=bounds,
                    style=style,
                    total_paths=total_paths,
                    total_commands=total_commands,
                    degradations=degradations,
                    annotation_id=request.annotation.id,
                )
                groups.extend(ready_groups)

        unique_groups: list[InkGroup] = []
        group_ids: set[str] = set()
        for group in groups:
            if group.group_id in group_ids:
                degradations.append(
                    InkDegradation(
                        annotation_id=request.annotation.id,
                        role=group.role,
                        code="duplicate_group_id",
                        detail=f"Dropped duplicate ink group {group.group_id!r}.",
                    )
                )
                continue
            group_ids.add(group.group_id)
            unique_groups.append(group)

        scene = InkScene(
            ink_algorithm_version=self._algorithm_version,
            annotation_id=request.annotation.id,
            seed=request.resolved.render_seed,
            bounds=bounds,
            groups=tuple(unique_groups),
        )
        return CompositionResult(scene=scene, body=body, degradations=tuple(degradations))

    def _process_groups(
        self,
        generated_groups: tuple[InkGroup, ...],
        *,
        role: RoughRole | InkRole,
        bounds: LocalRect,
        style: InkStyleProfile,
        total_paths: int,
        total_commands: int,
        degradations: list[InkDegradation],
        annotation_id: str,
    ) -> tuple[list[InkGroup], int, int]:
        processed_groups: list[InkGroup] = []
        z_index = 50 if isinstance(role, InkRole) else _Z_INDEX[role]
        for group in generated_groups:
            processed_paths: list[StrokePath] = []
            for path in group.paths:
                try:
                    processed = self._path_postprocessor.process(
                        path,
                        bounds=bounds,
                        tolerance=max(style.nib.base_width * 0.2, 0.01),
                        input_budget=style.budget.max_points,
                    )
                except (TypeError, ValueError, ArithmeticError) as exc:
                    processed = None
                    detail = str(exc)
                else:
                    detail = "Generated path failed clipping or geometry validation."

                if processed is None or not _path_geometry_is_valid(processed, bounds):
                    degradations.append(
                        InkDegradation(
                            annotation_id=annotation_id,
                            role=role,
                            code="ink_geometry_invalid",
                            detail=detail,
                        )
                    )
                    continue
                processed = processed.model_copy(update={"z_index": z_index})
                command_count = len(processed.commands)
                if (
                    total_paths + 1 > style.budget.max_paths
                    or total_commands + command_count > style.budget.max_points
                ):
                    degradations.append(
                        InkDegradation(
                            annotation_id=annotation_id,
                            role=role,
                            code="ink_path_budget_exceeded",
                            detail="The aggregate scene ink budget was exceeded.",
                        )
                    )
                    continue
                processed_paths.append(processed)
                total_paths += 1
                total_commands += command_count
            if processed_paths:
                processed_groups.append(group.model_copy(update={"paths": tuple(processed_paths)}))
        return processed_groups, total_paths, total_commands


__all__ = [
    "BuiltinRoughInkEngine",
    "ComposeRequest",
    "CompositionResult",
    "DefaultPathPostprocessor",
    "HandwritingEngine",
    "HandwritingReady",
    "HandwritingRequest",
    "HandwritingUnavailable",
    "InkComposer",
    "InkDegradation",
    "P3T5NoGoHandwritingEngine",
    "PathPostprocessor",
    "RoughInkEngine",
    "RoughRequest",
    "RoughResult",
    "RoughRole",
    "TypesetBody",
]
