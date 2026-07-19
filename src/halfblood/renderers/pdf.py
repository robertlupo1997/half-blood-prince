"""Translate validated ink scenes into PyMuPDF vector shape operations."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

import fitz

from halfblood.ink.geometry import ExpandedOutline, ExpansionError, expand_stroke
from halfblood.ink.model import CubicTo, InkScene, MoveTo, StrokePath
from halfblood.models.rendering import SkipReason


class ShapeLike(Protocol):
    """The subset of ``fitz.Shape`` used by the ink renderer."""

    def draw_line(self, p1: fitz.Point, p2: fitz.Point) -> fitz.Point: ...

    def draw_bezier(
        self,
        p1: fitz.Point,
        p2: fitz.Point,
        p3: fitz.Point,
        p4: fitz.Point,
    ) -> fitz.Point: ...

    def draw_polyline(self, points: list[fitz.Point]) -> fitz.Point: ...

    def finish(self, **kwargs: object) -> None: ...

    def commit(self, overlay: bool = True) -> None: ...


ShapeFactory = Callable[[fitz.Page], ShapeLike]


@dataclass(frozen=True)
class PdfRenderLimits:
    """Aggregate scene limits enforced before any shape is created."""

    max_paths_per_scene: int = 400
    max_commands_per_scene: int = 8_000
    max_outline_points_per_scene: int = 32_000


@dataclass(frozen=True)
class PdfSceneRenderResult:
    """Result of translating one scene to a PDF page."""

    annotation_id: str
    rendered: bool
    path_count: int
    command_count: int
    skip_reason: SkipReason | None = None
    degradations: tuple[object, ...] = ()


def _default_shape_factory(page: fitz.Page) -> ShapeLike:
    return page.new_shape()


def _skip_result(
    scene: InkScene,
    path_count: int,
    command_count: int,
    reason: SkipReason,
) -> PdfSceneRenderResult:
    return PdfSceneRenderResult(
        annotation_id=scene.annotation_id,
        rendered=False,
        path_count=path_count,
        command_count=command_count,
        skip_reason=reason,
    )


def _rgb(color: str) -> tuple[float, float, float]:
    """Convert a ``#RRGGBB`` color to PyMuPDF's normalized RGB tuple."""

    if len(color) != 7 or not color.startswith("#"):
        raise ValueError(f"expected #RRGGBB color, got {color!r}")
    try:
        channels = (int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16))
    except ValueError as exc:
        raise ValueError(f"expected #RRGGBB color, got {color!r}") from exc
    red, green, blue = channels
    return (red / 255.0, green / 255.0, blue / 255.0)


_CAP_CODES = {"butt": 0, "round": 1, "square": 2}
_JOIN_CODES = {"miter": 0, "round": 1, "bevel": 2}


class PdfRenderer:
    """Render an ``InkScene`` through one injected or real PyMuPDF shape."""

    def __init__(
        self,
        *,
        shape_factory: ShapeFactory | None = None,
        limits: PdfRenderLimits = PdfRenderLimits(),  # noqa: B008  # Pinned public API.
    ) -> None:
        self._shape_factory = _default_shape_factory if shape_factory is None else shape_factory
        self._limits = limits

    def render_scene(self, page: fitz.Page, scene: InkScene) -> PdfSceneRenderResult:
        """Preflight and draw every scene path in stable ascending z-order."""

        paths = sorted(
            (path for group in scene.groups for path in group.paths),
            key=lambda path: path.z_index,
        )
        path_count = len(paths)
        command_count = sum(len(path.commands) for path in paths)

        if (
            path_count > self._limits.max_paths_per_scene
            or command_count > self._limits.max_commands_per_scene
        ):
            return _skip_result(
                scene,
                path_count,
                command_count,
                SkipReason.INK_PATH_BUDGET_EXCEEDED,
            )

        outlines: list[ExpandedOutline | None] = []
        outline_point_count = 0
        for path in paths:
            if path.samples and not path.width_profile:
                return _skip_result(
                    scene,
                    path_count,
                    command_count,
                    SkipReason.INK_GEOMETRY_INVALID,
                )
            if not path.width_profile:
                outlines.append(None)
                continue
            try:
                expanded_outline = expand_stroke(
                    path.commands,
                    path.width_profile,
                    base_width=path.stroke.base_width,
                )
            except ExpansionError:
                return _skip_result(
                    scene,
                    path_count,
                    command_count,
                    SkipReason.INK_GEOMETRY_INVALID,
                )
            if expanded_outline.degradation_flags:
                return _skip_result(
                    scene,
                    path_count,
                    command_count,
                    SkipReason.INK_GEOMETRY_INVALID,
                )
            outlines.append(expanded_outline)
            outline_point_count += len(expanded_outline.vertices)
            if outline_point_count > self._limits.max_outline_points_per_scene:
                return _skip_result(
                    scene,
                    path_count,
                    command_count,
                    SkipReason.INK_PATH_BUDGET_EXCEEDED,
                )

        colors: list[tuple[float, float, float]] = []
        try:
            for path in paths:
                colors.append(_rgb(path.stroke.color))
        except ValueError:
            return _skip_result(
                scene,
                path_count,
                command_count,
                SkipReason.INK_GEOMETRY_INVALID,
            )

        shape = self._shape_factory(page)
        for path, cached_outline, color in zip(paths, outlines, colors, strict=True):
            if cached_outline is None:
                self._draw_centerline(shape, page, path)
                shape.finish(
                    color=color,
                    width=path.stroke.base_width,
                    closePath=False,
                    stroke_opacity=path.stroke.opacity,
                    lineCap=_CAP_CODES[path.stroke.cap],
                    lineJoin=_JOIN_CODES[path.stroke.join],
                )
            else:
                points = [
                    self._transform_point(page, path, vertex.x, vertex.y)
                    for vertex in cached_outline.vertices
                ]
                shape.draw_polyline(points)
                shape.finish(
                    fill=color,
                    color=None,
                    fill_opacity=path.stroke.opacity,
                    closePath=True,
                )

        shape.commit(overlay=True)
        return PdfSceneRenderResult(
            annotation_id=scene.annotation_id,
            rendered=True,
            path_count=path_count,
            command_count=command_count,
        )

    @staticmethod
    def _transform_point(
        page: fitz.Page,
        path: StrokePath,
        x: float,
        y: float,
    ) -> fitz.Point:
        path_matrix = fitz.Matrix(*path.transform.matrix)
        return fitz.Point(x, y) * path_matrix * page.derotation_matrix

    def _draw_centerline(
        self,
        shape: ShapeLike,
        page: fitz.Page,
        path: StrokePath,
    ) -> None:
        current: fitz.Point | None = None
        for command in path.commands:
            end = self._transform_point(page, path, command.x, command.y)
            if isinstance(command, MoveTo):
                current = end
            elif isinstance(command, CubicTo):
                if current is None:
                    raise ValueError("path does not begin with MoveTo")
                control1 = self._transform_point(page, path, command.x1, command.y1)
                control2 = self._transform_point(page, path, command.x2, command.y2)
                shape.draw_bezier(current, control1, control2, end)
                current = end
            else:
                if current is None:
                    raise ValueError("path does not begin with MoveTo")
                shape.draw_line(current, end)
                current = end


__all__ = [
    "PdfRenderer",
    "PdfRenderLimits",
    "PdfSceneRenderResult",
    "ShapeFactory",
    "ShapeLike",
]
