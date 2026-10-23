"""A ``circle`` mark rings each line of its quote and stays inside the text column.

Regression for page 2 of the real-model Alice showcase (``examples/real/``,
2026-10-22): the quote "say anything about it, even if I fell off the top of
the house!" (Which was very likely true.)" wraps onto a second line. The old
``make_circle`` drew one ellipse around the union of both lines, padded by 6% of
its width (~25pt on a body line), so the loop ran out of the text column into
the left margin and across two handwritten notes beside it.

Now each line fragment gets its own loop, bounded by its glyph box plus
``CIRCLE_PAD_X`` / ``CIRCLE_PAD_Y``, and a loop gives up its pad on any side
where it would touch a placed note box. Assertions are on drawn geometry.
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
from halfblood.ink.rough import CIRCLE_PAD_X, CIRCLE_PAD_Y, make_circle
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

# Letter page, 54pt margins, ~22pt line pitch: the Alice example's geometry.
_PAGE = SurfaceRect(x0=0.0, y0=0.0, x1=612.0, y1=792.0)
_COLUMN_X0, _COLUMN_X1 = 67.0, 545.0
# The wrapped quote: from mid-line 1 to the column's right edge, then the start of line 2.
_LINE_A = LocalRect(x0=67.0, y0=310.0, x1=544.0, y1=329.0)
_LINE_B = LocalRect(x0=67.0, y0=332.0, x1=137.0, y1=351.0)
# A handwritten note in the left margin beside the quote (as on page 2).
_LEFT_NOTE = LocalRect(x0=6.0, y0=270.0, x1=60.0, y1=380.0)
# A note in the right margin beside line A, close to the column.
_RIGHT_NOTE = LocalRect(x0=546.0, y0=300.0, x1=600.0, y1=340.0)


def _bezier(p0: tuple[float, float], cmd: CubicTo, n: int = 32) -> list[tuple[float, float]]:
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
            points.extend(_bezier(cur, cmd))
        else:
            points.append((cmd.x, cmd.y))
        cur = (cmd.x, cmd.y)
    return points


def _core(rect: LocalRect, fraction: float = 0.35) -> LocalRect:
    inset = (rect.y1 - rect.y0) * fraction
    return LocalRect(x0=rect.x0, y0=rect.y0 + inset, x1=rect.x1, y1=rect.y1 - inset)


def _inside(point: tuple[float, float], rect: LocalRect) -> bool:
    return rect.x0 < point[0] < rect.x1 and rect.y0 < point[1] < rect.y1


def _overlaps(a: LocalRect, b: LocalRect) -> bool:
    return a.x0 < b.x1 and b.x0 < a.x1 and a.y0 < b.y1 and b.y0 < a.y1


_BOUNDS = LocalRect(x0=0.0, y0=0.0, x1=612.0, y1=792.0)


@pytest.mark.parametrize("seed", range(30))
def test_wrapped_quote_gets_one_tight_loop_per_line(seed: int) -> None:
    group = make_circle(
        random.Random(seed), [_LINE_A, _LINE_B], load_builtin_style(), _BOUNDS, "c"
    )
    assert group.role is InkRole.CIRCLE
    assert len(group.paths) == 2, "a quote on two lines is ringed line by line"

    for path, line in zip(group.paths, (_LINE_A, _LINE_B), strict=True):
        points = _flatten(path.commands)
        xs = [x for x, _ in points]
        ys = [y for _, y in points]
        # Never further from the glyph box than a pen's pad.
        assert min(xs) >= line.x0 - CIRCLE_PAD_X - 1e-6
        assert max(xs) <= line.x1 + CIRCLE_PAD_X + 1e-6
        assert min(ys) >= line.y0 - CIRCLE_PAD_Y - 1e-6
        assert max(ys) <= line.y1 + CIRCLE_PAD_Y + 1e-6
        # Still a ring around the words: it reaches past both ends of the line
        # and never strokes through the glyph band.
        assert min(xs) < line.x0 + 1.0 and max(xs) > line.x1 - 1.0
        core = _core(line)
        assert not [p for p in points if _inside(p, core)], "loop crosses its own words"
        # Open, like a pen's loop, not a closed vector ellipse.
        first, last = path.commands[0], path.commands[-1]
        assert (first.x, first.y) != (last.x, last.y)


@pytest.mark.parametrize("seed", range(30))
def test_loop_stays_inside_text_column_and_off_note_boxes(seed: int) -> None:
    group = make_circle(
        random.Random(seed),
        [_LINE_A, _LINE_B],
        load_builtin_style(),
        _BOUNDS,
        "c",
        avoid=(_LEFT_NOTE, _RIGHT_NOTE),
    )
    for path in group.paths:
        for x, y in _flatten(path.commands):
            assert _COLUMN_X0 - CIRCLE_PAD_X - 1e-6 <= x <= _COLUMN_X1 + CIRCLE_PAD_X + 1e-6
            for note in (_LEFT_NOTE, _RIGHT_NOTE):
                assert not _inside((x, y), note), f"circle ink at ({x:.1f},{y:.1f}) is on a note"


def _compose() -> list[tuple[float, float]]:
    annotation = Annotation(
        id="page-2",
        target=TargetSelector(exact="say anything about it, even if I fell off the top"),
        annotation_type=AnnotationType.CORRECTION,
        content="Read it twice.",
        confidence=0.9,
        requested_placement="margin_left",
        mark_intent=MarkIntent.CIRCLE,
    )

    def quad(r: LocalRect) -> SurfaceQuad:
        return SurfaceQuad(
            ul=SurfacePoint(x=r.x0, y=r.y0),
            ur=SurfacePoint(x=r.x1, y=r.y0),
            lr=SurfacePoint(x=r.x1, y=r.y1),
            ll=SurfacePoint(x=r.x0, y=r.y1),
        )

    def surf(r: LocalRect) -> SurfaceRect:
        return SurfaceRect(x0=r.x0, y0=r.y0, x1=r.x1, y1=r.y1)

    resolved = ResolvedAnnotation(
        annotation_id="page-2",
        source_locator="page:2",
        requested_placement="margin_left",
        resolved_placement="margin_left",
        anchor=ResolvedAnchor(char_range=(0, 90), quads=(quad(_LINE_A), quad(_LINE_B))),
        note_box=surf(_LEFT_NOTE),
        render_seed=5,
    )
    composer = InkComposer(
        BuiltinRoughInkEngine(),
        P3T5NoGoHandwritingEngine(),
        path_postprocessor=DefaultPathPostprocessor(),
        algorithm_version="ink-1.0",
    )
    result = composer.compose(
        ComposeRequest(
            annotation=annotation,
            resolved=resolved,
            document_seed=3,
            page_bounds=_PAGE,
            note_boxes=(surf(_LEFT_NOTE), surf(_RIGHT_NOTE)),
        ),
        load_builtin_style(),
    )
    circles = [g for g in result.scene.groups if g.role is InkRole.CIRCLE]
    assert len(circles) == 1
    return [p for path in circles[0].paths for p in _flatten(path.commands)]


def test_composer_passes_placed_note_boxes_to_the_circle() -> None:
    points = _compose()
    assert points
    for point in points:
        assert not _inside(point, _LEFT_NOTE)
        assert not _inside(point, _RIGHT_NOTE)


# --------------------------------------------------------------------------- #
# End to end through render_plan: the drawn PDF paths, read back
# --------------------------------------------------------------------------- #

_LINES = [
    "tumbling down stairs! How brave they will all think me at home! Why, I would not",
    "say anything about it, even if I fell off the top of the house! (Which was very",
    "likely true.) Down, down, down. Would the fall never come to an end? I wonder",
]
_QUOTE = "say anything about it, even if I fell off the top of the house! (Which was very likely true.)"


def _source(tmp_path: Path) -> Path:
    path = tmp_path / "page2.pdf"
    with fitz.open() as doc:
        page = doc.new_page(width=612, height=792)
        rows = list(_LINES) + [
            f"and filler line {row} of the body column so the layout can infer it here."
            for row in range(20)
        ]
        for row, text in enumerate(rows):
            page.insert_text((72, 80 + 22 * row), text, fontsize=12.2, fontname="tiro")
        doc.save(path)
    return path


def _plan() -> AnnotationPlan:
    return AnnotationPlan(
        id="page2", title="Circle geometry fixture", persona="Test", document_seed=3,
        generation=GenerationProvenance(),
        source=SourceInfo(fingerprint="test", media_type="test", unit_count=1),
        units=[Unit(unit_id="one", ordinal=1, label="One", original_text="",
                    source_locator="page:1", annotations=[
                        Annotation(id="ann-2", target=TargetSelector(exact=_QUOTE),
                                   annotation_type=AnnotationType.CORRECTION,
                                   content="Read it twice. She would not mention it.",
                                   confidence=1,
                                   requested_placement="margin_left",
                                   mark_intent=MarkIntent.CIRCLE),
                    ])],
    )


def test_render_plan_circle_on_a_wrapped_quote_stays_in_the_column(tmp_path: Path) -> None:
    out = tmp_path / "out.pdf"
    report = DocumentProcessor().render_plan(str(_source(tmp_path)), _plan(), str(out))
    assert report.rendered_count == 1
    quads = report.placements[0].result.quads
    assert len({round(q.ul.y) for q in quads}) == 2, "fixture quote must wrap onto two lines"
    x0 = min(q.ul.x for q in quads)
    x1 = max(q.ur.x for q in quads)

    nib = load_builtin_style().nib.max_width
    with fitz.open(out) as doc:
        page = doc[0]
        loops = 0
        for drawing in page.get_drawings():
            items = drawing["items"]
            curves = [item for item in items if item[0] == "c"]
            if len(curves) < 6:
                continue  # connectors and arrowheads are short; loops have six curves
            loops += 1
            for item in curves:
                for p in item[1:5]:
                    assert x0 - CIRCLE_PAD_X - nib <= p.x <= x1 + CIRCLE_PAD_X + nib, (
                        f"circle ink at x={p.x:.1f} leaves the column [{x0:.1f}, {x1:.1f}]"
                    )
    assert loops == 2, f"expected one loop per line of the quote, found {loops}"
