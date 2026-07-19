"""P3-T12a — the PDF vector renderer translates an InkScene to fitz.Shape draws.

Controller-owned test file (SDD lean loop). Codex must NOT modify this file.

Scope: `src/halfblood/renderers/pdf.py` as a PURE unit — it takes a validated
`InkScene` and a `fitz.Page`, and emits vector draws through an injectable
``ShapeFactory`` (a ``ShapeLike``). Nothing in the live render path calls it yet
(that is P3-T12b integration). These tests spy on the shape via an injected
recording factory — the repository's established ``fitz.Shape``-spy style
(cf. ``tests/test_pdf_geometry.py``), but without touching PyMuPDF globals.

Design + assertion-to-contract map: `.superpowers/sdd/p3-t12-design.md`.
No network calls are made anywhere in this file.
"""

from __future__ import annotations

from typing import Any

import fitz
import pytest

from halfblood.ink.model import (
    AffineTransform,
    CubicTo,
    InkGroup,
    InkRole,
    InkScene,
    LineTo,
    LocalRect,
    MoveTo,
    StrokePath,
    StrokeStyle,
    WidthSample,
)
from halfblood.models.rendering import SkipReason
from halfblood.renderers import (
    PdfRenderer,
    PdfRenderLimits,
    PdfSceneRenderResult,
)

# --------------------------------------------------------------------------- #
# Recording shape + factory (injected instead of a real fitz.Shape)
# --------------------------------------------------------------------------- #


def _pt(p: Any) -> tuple[float, float]:
    """Normalize a fitz.Point (or (x, y)) to a rounded float pair."""
    x, y = (p.x, p.y) if hasattr(p, "x") else (p[0], p[1])
    return (round(float(x), 3), round(float(y), 3))


class RecordingShape:
    """A ShapeLike that records every draw/finish/commit call."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []
        self.commits: list[bool] = []

    def draw_line(self, p1: Any, p2: Any) -> Any:
        self.calls.append(("draw_line", (_pt(p1), _pt(p2))))
        return p2

    def draw_bezier(self, p1: Any, p2: Any, p3: Any, p4: Any) -> Any:
        self.calls.append(("draw_bezier", (_pt(p1), _pt(p2), _pt(p3), _pt(p4))))
        return p4

    def draw_polyline(self, points: Any) -> Any:
        self.calls.append(("draw_polyline", tuple(_pt(p) for p in points)))
        return points[-1]

    def finish(self, **kwargs: Any) -> None:
        self.calls.append(("finish", kwargs))

    def commit(self, overlay: bool = True) -> None:
        self.commits.append(overlay)


class RecordingShapeFactory:
    def __init__(self) -> None:
        self.shapes: list[RecordingShape] = []

    def __call__(self, page: fitz.Page) -> RecordingShape:
        shape = RecordingShape()
        self.shapes.append(shape)
        return shape

    @property
    def all_calls(self) -> list[tuple[str, Any]]:
        return [c for s in self.shapes for c in s.calls]

    def ops(self, name: str) -> list[Any]:
        return [payload for op, payload in self.all_calls if op == name]


# --------------------------------------------------------------------------- #
# Builders
# --------------------------------------------------------------------------- #

_BOUNDS = LocalRect(x0=0.0, y0=0.0, x1=200.0, y1=300.0)


def _style(color: str = "#804000", width: float = 1.0, opacity: float = 0.9) -> StrokeStyle:
    return StrokeStyle(color=color, base_width=width, opacity=opacity, cap="round", join="round")


def _path(
    commands: tuple[Any, ...],
    *,
    width_profile: tuple[WidthSample, ...] = (),
    transform: AffineTransform | None = None,
    z_index: int = 0,
    stroke: StrokeStyle | None = None,
) -> StrokePath:
    return StrokePath(
        commands=commands,
        stroke=stroke or _style(),
        width_profile=width_profile,
        transform=transform or AffineTransform(),
        z_index=z_index,
    )


def _scene(*groups: InkGroup, ann: str = "ann-1", seed: int = 42) -> InkScene:
    return InkScene(
        ink_algorithm_version="ink-1.0",
        annotation_id=ann,
        seed=seed,
        bounds=_BOUNDS,
        groups=tuple(groups),
    )


def _group(role: InkRole, *paths: StrokePath, gid: str | None = None) -> InkGroup:
    return InkGroup(group_id=gid or role.value, role=role, paths=tuple(paths))


@pytest.fixture()
def page() -> fitz.Page:
    return fitz.open().new_page(width=200.0, height=300.0)


@pytest.fixture()
def factory() -> RecordingShapeFactory:
    return RecordingShapeFactory()


def _render(page: fitz.Page, factory: RecordingShapeFactory, scene: InkScene, **kw: Any) -> PdfSceneRenderResult:
    return PdfRenderer(shape_factory=factory, **kw).render_scene(page, scene)


# --------------------------------------------------------------------------- #
# Translation: constant-width strokes -> lines / beziers with round finish
# --------------------------------------------------------------------------- #


def test_line_path_draws_line_with_round_finish(page: fitz.Page, factory: RecordingShapeFactory) -> None:
    scene = _scene(_group(InkRole.UNDERLINE, _path((MoveTo(x=10, y=10), LineTo(x=50, y=10)))))
    result = _render(page, factory, scene)
    assert result.rendered is True
    assert factory.ops("draw_line") == [((10.0, 10.0), (50.0, 10.0))]
    finishes = factory.ops("finish")
    assert finishes, "constant-width path must be finished"
    kw = finishes[-1]
    assert kw.get("lineCap") == 1 and kw.get("lineJoin") == 1, "round cap/join expected"
    assert kw.get("closePath") is False
    color = kw.get("color")
    assert isinstance(color, tuple) and len(color) == 3 and all(0.0 <= c <= 1.0 for c in color)


def test_cubic_uses_draw_bezier_not_draw_curve(page: fitz.Page, factory: RecordingShapeFactory) -> None:
    scene = _scene(
        _group(InkRole.CIRCLE, _path((MoveTo(x=10, y=20), CubicTo(x1=20, y1=15, x2=40, y2=25, x=50, y=20))))
    )
    _render(page, factory, scene)
    assert factory.ops("draw_bezier") == [((10.0, 20.0), (20.0, 15.0), (40.0, 25.0), (50.0, 20.0))]
    assert factory.ops("draw_line") == [], "a cubic must not be flattened to draw_line"


# --------------------------------------------------------------------------- #
# Width-profile strokes -> filled outline (via expand_stroke), no centerline
# --------------------------------------------------------------------------- #


def test_width_profile_path_fills_outline_and_omits_centerline(
    page: fitz.Page, factory: RecordingShapeFactory
) -> None:
    scene = _scene(
        _group(
            InkRole.UNDERLINE,
            _path(
                (MoveTo(x=10, y=40), LineTo(x=90, y=40)),
                width_profile=(WidthSample(position=0.0, width=0.6), WidthSample(position=1.0, width=2.0)),
            ),
        )
    )
    _render(page, factory, scene)
    polylines = factory.ops("draw_polyline")
    assert polylines, "pressure/width-profile path must draw a filled outline polygon"
    assert len(polylines[0]) >= 4
    assert factory.ops("draw_line") == [], "filled outline must not also stroke a centerline"
    fills = [kw for kw in factory.ops("finish") if kw.get("fill") is not None]
    assert fills, "outline must be finished with a fill color"


# --------------------------------------------------------------------------- #
# Determinism / no jitter / transforms applied once
# --------------------------------------------------------------------------- #


def test_renderer_adds_no_jitter(page: fitz.Page, factory: RecordingShapeFactory) -> None:
    scene = _scene(_group(InkRole.STRIKE, _path((MoveTo(x=12, y=70), LineTo(x=88, y=70)))))
    _render(page, factory, scene)
    # output geometry equals input geometry exactly — the renderer invents nothing.
    assert factory.ops("draw_line") == [((12.0, 70.0), (88.0, 70.0))]


def test_path_transform_applied_exactly_once(page: fitz.Page, factory: RecordingShapeFactory) -> None:
    translate = AffineTransform(matrix=(1.0, 0.0, 0.0, 1.0, 100.0, 0.0))
    scene = _scene(
        _group(InkRole.UNDERLINE, _path((MoveTo(x=10, y=110), LineTo(x=50, y=110)), transform=translate))
    )
    _render(page, factory, scene)
    # shifted by +100 in x ONCE (twice would be 210/250); page rotation is 0 => identity derotation.
    assert factory.ops("draw_line") == [((110.0, 110.0), (150.0, 110.0))]


# --------------------------------------------------------------------------- #
# Multi-path separation and z-order
# --------------------------------------------------------------------------- #


def test_multi_path_marks_stay_separate(page: fitz.Page, factory: RecordingShapeFactory) -> None:
    # two per-quad underline paths must remain two distinct draws, never merged.
    scene = _scene(
        _group(
            InkRole.UNDERLINE,
            _path((MoveTo(x=10, y=130), LineTo(x=40, y=130))),
            _path((MoveTo(x=10, y=150), LineTo(x=35, y=150))),
        )
    )
    result = _render(page, factory, scene)
    assert factory.ops("draw_line") == [((10.0, 130.0), (40.0, 130.0)), ((10.0, 150.0), (35.0, 150.0))]
    assert result.path_count == 2


def test_paths_drawn_in_z_index_order(page: fitz.Page, factory: RecordingShapeFactory) -> None:
    # a highlight (z=-100) must be drawn before the mark (z=0), regardless of group order.
    mark = _group(InkRole.STRIKE, _path((MoveTo(x=10, y=170), LineTo(x=60, y=170)), z_index=0))
    highlight = _group(
        InkRole.UNDERLINE, _path((MoveTo(x=11, y=171), LineTo(x=61, y=171)), z_index=-100), gid="hl"
    )
    scene = _scene(mark, highlight)  # mark listed first, but highlight z is lower
    _render(page, factory, scene)
    assert factory.ops("draw_line") == [
        ((11.0, 171.0), (61.0, 171.0)),  # highlight (z=-100) first
        ((10.0, 170.0), (60.0, 170.0)),  # mark (z=0) second
    ], "paths must flatten in ascending z_index order"


# --------------------------------------------------------------------------- #
# Budget preflight: over-budget scene draws NOTHING and reports a skip
# --------------------------------------------------------------------------- #


def test_over_budget_scene_skips_with_zero_shape_calls(page: fitz.Page, factory: RecordingShapeFactory) -> None:
    scene = _scene(
        _group(
            InkRole.UNDERLINE,
            _path((MoveTo(x=10, y=200), LineTo(x=40, y=200))),
            _path((MoveTo(x=10, y=220), LineTo(x=40, y=220))),
        )
    )
    result = _render(page, factory, scene, limits=PdfRenderLimits(max_paths_per_scene=1))
    assert result.rendered is False
    assert result.skip_reason == SkipReason.INK_PATH_BUDGET_EXCEEDED
    # preflight: NOTHING is drawn or committed (no partial output)
    assert factory.all_calls == []
    assert all(s.commits == [] for s in factory.shapes)


def test_result_reports_annotation_and_counts(page: fitz.Page, factory: RecordingShapeFactory) -> None:
    scene = _scene(
        _group(InkRole.UNDERLINE, _path((MoveTo(x=10, y=240), LineTo(x=40, y=240)))),
        ann="ann-xyz",
    )
    result = _render(page, factory, scene)
    assert result.annotation_id == "ann-xyz"
    assert result.rendered is True
    assert result.path_count == 1
    assert result.command_count == 2


# --------------------------------------------------------------------------- #
# P3-T12b — underlay/overlay commit split: highlights behind, marks in front
# --------------------------------------------------------------------------- #


def test_highlight_commits_underlay_and_marks_commit_overlay(
    page: fitz.Page, factory: RecordingShapeFactory
) -> None:
    """Negative-z (highlight) paths commit overlay=False; the rest overlay=True.

    This places the original page content BETWEEN the highlight wash and the
    visible marks.  On HEAD render_scene uses a single shape committed
    overlay=True — the intended pre-implementation failure.
    """
    mark = _group(InkRole.STRIKE, _path((MoveTo(x=10, y=170), LineTo(x=60, y=170)), z_index=0))
    highlight = _group(
        InkRole.UNDERLINE, _path((MoveTo(x=11, y=171), LineTo(x=61, y=171)), z_index=-100), gid="hl"
    )
    scene = _scene(mark, highlight)
    result = _render(page, factory, scene)

    assert result.rendered is True
    assert len(factory.shapes) == 2, "expected a separate underlay and overlay shape"
    underlay, overlay = factory.shapes
    assert underlay.commits == [False], "highlight (z<0) must commit as underlay (overlay=False)"
    assert overlay.commits == [True], "visible marks must commit as overlay (overlay=True)"
    underlay_lines = [payload for op, payload in underlay.calls if op == "draw_line"]
    overlay_lines = [payload for op, payload in overlay.calls if op == "draw_line"]
    assert underlay_lines == [((11.0, 171.0), (61.0, 171.0))], "underlay draws only the highlight"
    assert overlay_lines == [((10.0, 170.0), (60.0, 170.0))], "overlay draws only the mark"


def test_scene_without_highlight_uses_single_overlay_commit(
    page: fitz.Page, factory: RecordingShapeFactory
) -> None:
    """The common case (no z<0 path) still creates ONE shape committed overlay=True."""
    scene = _scene(_group(InkRole.STRIKE, _path((MoveTo(x=10, y=180), LineTo(x=60, y=180)), z_index=0)))
    _render(page, factory, scene)
    assert len(factory.shapes) == 1, "no underlay shape when there is nothing behind"
    assert factory.shapes[0].commits == [True]


def test_all_highlight_scene_uses_single_underlay_commit(
    page: fitz.Page, factory: RecordingShapeFactory
) -> None:
    """A scene of only highlights creates ONE shape committed overlay=False."""
    scene = _scene(
        _group(
            InkRole.UNDERLINE,
            _path((MoveTo(x=10, y=190), LineTo(x=60, y=190)), z_index=-100),
            gid="hl",
        )
    )
    _render(page, factory, scene)
    assert len(factory.shapes) == 1, "no overlay shape when everything is an underlay"
    assert factory.shapes[0].commits == [False]
