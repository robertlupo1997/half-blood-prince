"""Rendered marks hug the resolved quote; connectors do not cross its line.

Regression for two defects seen on page 6 of the committed Alice example
(``examples/src/alice.pdf`` through ``--provider stub``), where the quote is the
first 75 characters of a 415pt body line and ends mid-line at "she", followed
by "opened it,":

1. The underline began ~33pt left of the first glyph and ran ~23pt past the
   last one. Overshoot was ``overshoot_ratio * quad width``, so it grew with the
   line: 0.12 of a full body line is up to ~50pt.
2. The connector from the right-margin note landed on the quad's right edge at
   mid-height, so it ran back across "opened it," to get there. The text-run
   obstacle holding that endpoint is exempt from routing checks, so nothing
   flagged the crossing.

Assertions are geometry on the drawn PDF paths, not image diffs.
"""

from __future__ import annotations

import random
from pathlib import Path

import fitz
import pytest

from halfblood.document_processor import DocumentProcessor
from halfblood.ink.composer import (
    BuiltinRoughInkEngine,
    ComposeRequest,
    DefaultPathPostprocessor,
    InkComposer,
    P3T5NoGoHandwritingEngine,
)
from halfblood.ink.model import CubicTo, InkRole, LineTo, LocalRect, MoveTo
from halfblood.ink.rough import make_highlight, make_strike, make_underline
from halfblood.ink.style import load_builtin_style
from halfblood.models.annotations import Annotation, MarkIntent, TargetSelector
from halfblood.models.documents import AnnotationPlan, GenerationProvenance, SourceInfo, Unit
from halfblood.models.legacy import AnnotationType
from halfblood.models.rendering import (
    ResolvedAnchor,
    ResolvedAnnotation,
    SurfacePoint,
    SurfaceQuad,
    SurfaceRect,
)

# Geometry measured from page 6 of the Alice example (letter page, 54pt margins).
_PAGE = SurfaceRect(x0=0.0, y0=0.0, x1=612.0, y1=792.0)
_TARGET = (67.0, 53.337, 481.804, 72.434)  # "Soon her eye ... the table: she"
_LINE_1 = SurfaceRect(x0=65.5, y0=51.837, x1=544.612, y1=73.934)  # padded run, incl. "opened it,"
_LINE_2 = SurfaceRect(x0=65.5, y0=73.937, x1=539.126, y1=96.034)
_FOLLOWING = LocalRect(x0=484.5, y0=53.337, x1=543.1, y1=72.434)  # "opened it,"
_NOTE = SurfaceRect(x0=553.554, y0=44.0, x1=600.0, y1=82.0)

#: A pen's flick past the text, in points: the most a linear mark may overshoot.
_CAP = 4.0


def _quad(x0: float, y0: float, x1: float, y1: float) -> SurfaceQuad:
    return SurfaceQuad(
        ul=SurfacePoint(x=x0, y=y0),
        ur=SurfacePoint(x=x1, y=y0),
        lr=SurfacePoint(x=x1, y=y1),
        ll=SurfacePoint(x=x0, y=y1),
    )


def _bezier_points(p0: tuple[float, float], cmd: CubicTo, n: int = 32) -> list[tuple[float, float]]:
    out = []
    for i in range(1, n + 1):
        t = i / n
        mt = 1.0 - t
        out.append((
            mt**3 * p0[0] + 3 * mt**2 * t * cmd.x1 + 3 * mt * t**2 * cmd.x2 + t**3 * cmd.x,
            mt**3 * p0[1] + 3 * mt**2 * t * cmd.y1 + 3 * mt * t**2 * cmd.y2 + t**3 * cmd.y,
        ))
    return out


def _flatten(commands: tuple[MoveTo | LineTo | CubicTo, ...]) -> list[tuple[float, float]]:
    points: list[tuple[float, float]] = []
    cur = (0.0, 0.0)
    for cmd in commands:
        if isinstance(cmd, CubicTo):
            points.extend(_bezier_points(cur, cmd))
        else:
            points.append((cmd.x, cmd.y))
        cur = (cmd.x, cmd.y)
    return points


def _core(rect: LocalRect, fraction: float = 0.35) -> LocalRect:
    """The glyph band of a text box: its middle, where letters actually are."""
    inset = (rect.y1 - rect.y0) * fraction
    return LocalRect(x0=rect.x0, y0=rect.y0 + inset, x1=rect.x1, y1=rect.y1 - inset)


def _inside(point: tuple[float, float], rect: LocalRect) -> bool:
    return rect.x0 < point[0] < rect.x1 and rect.y0 < point[1] < rect.y1


# --------------------------------------------------------------------------- #
# 1. Linear marks: overshoot is bounded in points, not as a fraction of width
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("maker", [make_underline, make_strike, make_highlight])
@pytest.mark.parametrize("seed", range(25))
def test_linear_mark_overshoot_is_capped_on_a_full_body_line(maker, seed: int) -> None:
    style = load_builtin_style()
    quad = LocalRect(x0=_TARGET[0], y0=_TARGET[1], x1=_TARGET[2], y1=_TARGET[3])
    bounds = LocalRect(x0=0.0, y0=0.0, x1=_PAGE.x1, y1=_PAGE.y1)
    group = maker(random.Random(seed), [quad], style, bounds, "mark")

    cap = _CAP
    for path in group.paths:
        xs = [x for x, _ in _flatten(path.commands)]
        assert min(xs) >= quad.x0 - cap - 1e-6, (
            f"mark starts {quad.x0 - min(xs):.1f}pt before the first glyph (cap {cap}pt)"
        )
        assert max(xs) <= quad.x1 + cap + 1e-6, (
            f"mark ends {max(xs) - quad.x1:.1f}pt past the last glyph (cap {cap}pt)"
        )


def test_short_quad_keeps_ratio_overshoot_below_the_cap() -> None:
    """The cap only trims long lines; a one-word quad still overshoots a little."""
    style = load_builtin_style()
    quad = LocalRect(x0=100.0, y0=50.0, x1=120.0, y1=62.0)
    bounds = LocalRect(x0=0.0, y0=0.0, x1=612.0, y1=792.0)
    path = make_underline(random.Random(7), [quad], style, bounds, "ul").paths[0]
    xs = [cmd.x for cmd in path.commands]
    assert min(xs) < quad.x0 and max(xs) > quad.x1
    assert quad.x0 - min(xs) <= style.rough.overshoot_ratio * 20.0 + 1e-9


# --------------------------------------------------------------------------- #
# 2. Connector: land where it does not cross the words after the quote
# --------------------------------------------------------------------------- #


def _compose(obstacles: tuple[SurfaceRect, ...]):
    annotation = Annotation(
        id="page-6",
        target=TargetSelector(exact="Soon her eye fell on a little glass box"),
        annotation_type=AnnotationType.CORRECTION,
        content="Stub correction - page 6.",
        confidence=0.9,
        requested_placement="margin_right",
        mark_intent=MarkIntent.UNDERLINE,
    )
    resolved = ResolvedAnnotation(
        annotation_id="page-6",
        source_locator="page:6",
        requested_placement="margin_right",
        resolved_placement="margin_right",
        anchor=ResolvedAnchor(char_range=(0, 75), quads=(_quad(*_TARGET),)),
        note_box=_NOTE,
        render_seed=11,
    )
    composer = InkComposer(
        BuiltinRoughInkEngine(),
        P3T5NoGoHandwritingEngine(),
        path_postprocessor=DefaultPathPostprocessor(),
        algorithm_version="ink-1.0",
    )
    return composer.compose(
        ComposeRequest(
            annotation=annotation,
            resolved=resolved,
            document_seed=3,
            page_bounds=_PAGE,
            obstacles=obstacles,
        ),
        load_builtin_style(),
    )


def test_connector_does_not_cross_text_following_a_mid_line_quote() -> None:
    composition = _compose((_LINE_1, _LINE_2))
    connectors = [g for g in composition.scene.groups if g.role is InkRole.CONNECTOR]
    assert connectors, "a connector must still be drawn"

    band = _core(_FOLLOWING)
    for path in connectors[0].paths:
        crossing = [p for p in _flatten(path.commands) if _inside(p, band)]
        assert not crossing, (
            f"connector crosses 'opened it,' at {crossing[0]}; it must land on the "
            "target's top/bottom edge instead of running back through the line"
        )

    tip = connectors[0].paths[0].commands[-1]
    assert _TARGET[0] <= tip.x <= _TARGET[2], "the arrow must still land on the quote"
    assert tip.y == pytest.approx(_TARGET[1]), "lands on the quad's top edge, facing the note"


def test_connector_keeps_side_edge_when_quote_ends_its_line() -> None:
    """No text between quote and note: the nearest side edge is still right."""
    flush_line = SurfaceRect(x0=65.5, y0=51.837, x1=_TARGET[2] + 1.5, y1=73.934)
    composition = _compose((flush_line, _LINE_2))
    connector = next(g for g in composition.scene.groups if g.role is InkRole.CONNECTOR)
    tip = connector.paths[0].commands[-1]
    assert tip.x == pytest.approx(_TARGET[2])
    assert _TARGET[1] < tip.y < _TARGET[3]


# --------------------------------------------------------------------------- #
# 3. End to end through render_plan: the drawn PDF paths, read back
# --------------------------------------------------------------------------- #


_LINE_TEXT = "Soon her eye fell on a little glass box that was lying under the table: she opened it,"
_QUOTE = "Soon her eye fell on a little glass box that was lying under the table: she"


def _source(tmp_path: Path) -> Path:
    path = tmp_path / "page6.pdf"
    with fitz.open() as doc:
        page = doc.new_page(width=612, height=792)
        page.insert_text((67, 70), _LINE_TEXT, fontsize=12.2, fontname="tiro")
        # A body column needs more than one line for the layout to infer it.
        for row in range(1, 24):
            page.insert_text(
                (67, 70 + 22 * row),
                f"and found in it a very small cake, line {row}, on which the words were",
                fontsize=12.2,
                fontname="tiro",
            )
        doc.save(path)
    return path


def _plan() -> AnnotationPlan:
    return AnnotationPlan(
        id="page6", title="Render geometry fixture", persona="Test", document_seed=3,
        generation=GenerationProvenance(),
        source=SourceInfo(fingerprint="test", media_type="test", unit_count=1),
        units=[Unit(unit_id="one", ordinal=1, label="One", original_text="",
                    source_locator="page:1", annotations=[
                        Annotation(id="ann-6", target=TargetSelector(exact=_QUOTE),
                                   annotation_type=AnnotationType.CORRECTION,
                                   content="Stub correction - page 6.", confidence=1,
                                   requested_placement="margin_right",
                                   mark_intent=MarkIntent.UNDERLINE),
                    ])],
    )


def _drawn_points(page: fitz.Page) -> list[tuple[float, float]]:
    points: list[tuple[float, float]] = []
    for drawing in page.get_drawings():
        for item in drawing["items"]:
            if item[0] == "l":
                points.extend((p.x, p.y) for p in item[1:3])
            elif item[0] == "c":
                p0, c1, c2, p3 = item[1:5]
                cmd = CubicTo(x1=c1.x, y1=c1.y, x2=c2.x, y2=c2.y, x=p3.x, y=p3.y)
                points.extend(_bezier_points((p0.x, p0.y), cmd))
    return points


def test_render_plan_marks_hug_quote_and_connector_skips_following_words(tmp_path: Path) -> None:
    out = tmp_path / "out.pdf"
    report = DocumentProcessor().render_plan(str(_source(tmp_path)), _plan(), str(out))
    assert report.rendered_count == 1

    quads = report.placements[0].result.quads
    x0 = min(q.ul.x for q in quads)
    with fitz.open(out) as doc:
        page = doc[0]
        words = page.get_text("words")
        following = [w for w in words if w[4] in ("opened", "it,") and w[1] < 72]
        assert len(following) == 2
        points = _drawn_points(page)

    assert points, "the mark and connector must be drawn as vector paths"
    cap = _CAP
    nib = load_builtin_style().nib.max_width
    assert min(x for x, _ in points) >= x0 - cap - nib, (
        f"ink starts {x0 - min(x for x, _ in points):.1f}pt left of the quote's first glyph"
    )

    for word in following:
        band = _core(LocalRect(x0=word[0], y0=word[1], x1=word[2], y1=word[3]))
        crossing = [p for p in points if _inside(p, band)]
        assert not crossing, f"ink crosses {word[4]!r} at {crossing[0]}"
