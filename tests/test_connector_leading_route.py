"""A margin note's connector travels in the leading and never crosses print.

Regression for the real-model Alice showcase (``examples/real/``, 2026-10-23):
connectors ran straight through body text. On page 8 the top-left note's arrow
cut through "such"; on page 6 one struck through "(with Alice's love)". 20 of 60
connectors on the twelve pages crossed glyphs, and none of those raised
``connector_routing_fallback``: the router exempted every text line within 2pt
of the arrow's endpoint from its collision check, so the line beside the tip
(the one the curve actually crossed) was never tested.

The router now plans the route a pen takes (margin, then the inter-line gap,
then the quote's near end) from tight glyph ink boxes, and its honesty check
covers every glyph outside the quote. These tests read the drawn connector
paths back out of a ``render_plan`` PDF and test them against the source
page's glyph boxes.
"""

from __future__ import annotations

import random
from pathlib import Path

import fitz
import pytest

from halfblood.document_processor import DocumentProcessor
from halfblood.ink.connector_route import (
    ConnectorRoute,
    Leg,
    RouteKind,
    make_routed_connector,
    plan_connector_route,
)
from halfblood.ink.model import LocalRect
from halfblood.ink.rough import ConnectorDegradation
from halfblood.ink.style import load_builtin_style
from halfblood.models.annotations import Annotation, MarkIntent, TargetSelector
from halfblood.models.documents import AnnotationPlan, GenerationProvenance, SourceInfo, Unit
from halfblood.models.legacy import AnnotationType
from halfblood.models.rendering import DegradationFlag

# Letter page, 72pt left edge, 22pt pitch at 12.2pt: the Alice example's geometry,
# where glyph line boxes nearly touch and only glyph outlines show the leading.
_LINES = [
    "things, and she, oh! she knows such a very little! Besides, she is she, and I",
    "am I, and oh dear, how puzzling it all is! I will try if I know all the things",
    "I used to know. Let me see: four times five is twelve, and four times six is",
    "thirteen, and four times seven is oh dear! I shall never get to twenty at that",
    "rate! However, the Multiplication Table does not signify: let us try Geography.",
    "London is the capital of Paris, and Paris is the capital of Rome, and Rome, no,",
    "that is all wrong, I am certain! I must have been changed for Mabel! I will try",
    "and say How doth the little, and she crossed her hands on her lap as if she were",
    "saying lessons, and began to repeat it, but her voice sounded hoarse and strange,",
    "and the words did not come the same as they used to do. How doth the crocodile",
    "improve his shining tail, and pour the waters of the Nile on every golden scale!",
    "How cheerfully he seems to grin, how neatly spread his claws, and welcome fishes",
    "in with gently smiling jaws! I am sure those are not the right words, said poor",
    "Alice, and her eyes filled with tears again as she went on, I must be Mabel after",
    "all, and I shall have to go and live in that poky little house, and have next to",
    "no toys to play with, and oh! ever so many lessons to learn! No, I have made up",
    "my mind about it; if I am Mabel, I will stay down here! It will be no use their",
    "putting their heads down and saying Come up again, dear! I shall only look up and",
    "say Who am I then? Tell me that first, and then, if I like being that person, I",
    "will come up: if not, I will stay down here till I am somebody else, but oh dear!",
]

#: Single-line quotes that start or end mid-line, so a naive arrow to the near
#: end has to cross the words beside it.
_QUOTES = [
    ("try if I know all the things", "margin_left"),
    ("four times five is twelve", "margin_right"),
    ("the capital of Paris", "margin_left"),
    ("crossed her hands on her lap", "margin_right"),
    ("pour the waters of the Nile", "margin_left"),
    ("seems to grin, how neatly", "margin_right"),
    ("live in that poky little house", "margin_left"),
    ("Tell me that first", "margin_right"),
]


def _source(tmp_path: Path) -> Path:
    path = tmp_path / "leading.pdf"
    with fitz.open() as doc:
        page = doc.new_page(width=612, height=792)
        for row, text in enumerate(_LINES):
            page.insert_text((72, 90 + 22 * row), text, fontsize=12.2, fontname="tiro")
        doc.save(path)
    return path


def _plan() -> AnnotationPlan:
    annotations = [
        Annotation(
            id=f"q{index}",
            target=TargetSelector(exact=quote),
            annotation_type=AnnotationType.CORRECTION,
            content="Short note.",
            confidence=1,
            requested_placement=side,
            mark_intent=MarkIntent.NONE,
        )
        for index, (quote, side) in enumerate(_QUOTES)
    ]
    return AnnotationPlan(
        id="leading", title="Connector leading fixture", persona="Test", document_seed=11,
        generation=GenerationProvenance(),
        source=SourceInfo(fingerprint="test", media_type="test", unit_count=1),
        units=[Unit(unit_id="one", ordinal=1, label="One", original_text="",
                    source_locator="page:1", annotations=annotations)],
    )


def _glyphs(page: fitz.Page) -> list[fitz.Rect]:
    rects = []
    raw = page.get_text("rawdict", flags=fitz.TEXT_ACCURATE_BBOXES)
    for block in raw["blocks"]:
        for line in block.get("lines", []):
            for span in line["spans"]:
                for char in span["chars"]:
                    if not char["c"].isspace():
                        rects.append(fitz.Rect(char["bbox"]))
    return rects


def _segments(drawing: dict) -> list[tuple[fitz.Point, fitz.Point]]:
    segments = []
    for item in drawing["items"]:
        if item[0] == "l":
            segments.append((item[1], item[2]))
        elif item[0] == "c":
            p0, c1, c2, p3 = item[1:5]
            prev = p0
            for i in range(1, 33):
                t = i / 32
                mt = 1 - t
                point = fitz.Point(
                    mt**3 * p0.x + 3 * mt**2 * t * c1.x + 3 * mt * t**2 * c2.x + t**3 * p3.x,
                    mt**3 * p0.y + 3 * mt**2 * t * c1.y + 3 * mt * t**2 * c2.y + t**3 * p3.y,
                )
                segments.append((prev, point))
                prev = point
    return segments


def _hits(a: fitz.Point, b: fitz.Point, r: fitz.Rect) -> bool:
    """Liang-Barsky: does segment a-b touch rectangle r?"""
    dx, dy = b.x - a.x, b.y - a.y
    t0, t1 = 0.0, 1.0
    for p, q in ((-dx, a.x - r.x0), (dx, r.x1 - a.x), (-dy, a.y - r.y0), (dy, r.y1 - a.y)):
        if p == 0:
            if q < 0:
                return False
        else:
            t = q / p
            if p < 0:
                if t > t1:
                    return False
                t0 = max(t0, t)
            elif t < t0:
                return False
            else:
                t1 = min(t1, t)
    return t0 <= t1


@pytest.fixture(scope="module")
def rendered(tmp_path_factory: pytest.TempPathFactory):
    tmp_path = tmp_path_factory.mktemp("leading")
    source = _source(tmp_path)
    out = tmp_path / "out.pdf"
    report = DocumentProcessor().render_plan(str(source), _plan(), str(out))
    with fitz.open(source) as doc:
        glyphs = _glyphs(doc[0])
    with fitz.open(out) as doc:
        drawings = doc[0].get_drawings()
    return report, glyphs, drawings


def _own_rects(report) -> list[fitz.Rect]:
    rects = []
    for placement in report.placements:
        for quad in placement.result.quads:
            rects.append(fitz.Rect(quad.ul.x, quad.ul.y, quad.lr.x, quad.lr.y))
    return rects


def _own_quads(report, annotation_id: str) -> list[fitz.Rect]:
    placement = next(p for p in report.placements if p.annotation_id == annotation_id)
    return [fitz.Rect(q.ul.x, q.ul.y, q.lr.x, q.lr.y) for q in placement.result.quads]


def test_fixture_quotes_sit_mid_line_and_all_render(rendered) -> None:
    report, glyphs, drawings = rendered
    assert len(report.rendered) == len(_QUOTES)
    for index, (_, side) in enumerate(_QUOTES):
        (quad,) = _own_quads(report, f"q{index}")
        line = [g for g in glyphs if abs((g.y0 + g.y1) / 2 - (quad.y0 + quad.y1) / 2) < 6]
        if side == "margin_left":
            assert any(g.x1 < quad.x0 - 1 for g in line), "words must precede the quote"
        else:
            assert any(g.x0 > quad.x1 + 1 for g in line), "words must follow the quote"
    assert drawings, "connectors must be drawn"


def test_no_connector_path_crosses_a_glyph_outside_its_quote(rendered) -> None:
    report, glyphs, drawings = rendered
    own = _own_rects(report)

    def is_own(glyph: fitz.Rect) -> bool:
        centre = fitz.Point((glyph.x0 + glyph.x1) / 2, (glyph.y0 + glyph.y1) / 2)
        return any(fitz.Rect(r.x0 - 0.5, r.y0 - 0.5, r.x1 + 0.5, r.y1 + 0.5).contains(centre)
                   for r in own)

    foreign = [g for g in glyphs if not is_own(g)]
    crossings = [
        (round(a.x), round(a.y))
        for drawing in drawings
        for a, b in _segments(drawing)
        if any(_hits(a, b, g) for g in foreign)
    ]
    assert not crossings, f"connector ink crosses body glyphs at {crossings[:5]}"
    assert DegradationFlag.CONNECTOR_ROUTING_FALLBACK not in report.degradation_flags


def test_each_arrow_ends_at_its_quotes_near_end(rendered) -> None:
    report, _, drawings = rendered
    ends = [
        drawing["items"][-1][-1]
        for drawing in drawings
        if any(item[0] == "c" for item in drawing["items"])
    ]
    for index, (_, side) in enumerate(_QUOTES):
        (quad,) = _own_quads(report, f"q{index}")
        near_x = quad.x0 if side == "margin_left" else quad.x1
        assert any(
            abs(end.x - near_x) <= 4.0 and quad.y0 - 8.0 <= end.y <= quad.y1 + 8.0
            for end in ends
        ), f"no arrow ends at the {side} end of quote q{index}"


def test_a_straight_arrow_would_have_crossed_text(rendered) -> None:
    """Sanity: the fixture is one where the naive route fails."""
    report, glyphs, _ = rendered
    crossed = 0
    for index, (_, side) in enumerate(_QUOTES):
        (quad,) = _own_quads(report, f"q{index}")
        mid_y = (quad.y0 + quad.y1) / 2
        start = fitz.Point(60.0 if side == "margin_left" else 552.0, mid_y - 22.0)
        end = fitz.Point(quad.x0 if side == "margin_left" else quad.x1, quad.y0)
        if any(_hits(start, end, g) for g in glyphs if not quad.contains(g)):
            crossed += 1
    assert crossed >= len(_QUOTES) // 2


# --------------------------------------------------------------------------- #
# Planner and honesty, without a PDF
# --------------------------------------------------------------------------- #

_BOUNDS = LocalRect(x0=0.0, y0=0.0, x1=612.0, y1=792.0)


def _row(y0: float, y1: float, x0: float = 72.0, x1: float = 540.0, step: float = 7.0):
    return [LocalRect(x0=x, y0=y0, x1=x + step - 1.0, y1=y1) for x in range(int(x0), int(x1), int(step))]


def test_tight_lines_fall_back_to_a_short_arrow_at_the_column_edge() -> None:
    """No leading at all: stop at the column edge instead of crossing a line."""
    glyphs = [g for top in (100.0, 112.0, 124.0) for g in _row(top, top + 12.0)]
    quote = LocalRect(x0=240.0, y0=112.0, x1=330.0, y1=124.0)
    note = LocalRect(x0=10.0, y0=90.0, x1=60.0, y1=140.0)
    route = plan_connector_route(note, [quote], glyphs, bounds=_BOUNDS, clearance=0.75)
    assert route is not None
    assert route.kind is RouteKind.SHORT
    assert route.clean
    assert route.tip[0] < 72.0, "the short arrow stops before the text column"
    result = make_routed_connector(random.Random(1), route, load_builtin_style(), _BOUNDS)
    assert ConnectorDegradation.ROUTING_FALLBACK not in result.degradation


def test_open_leading_routes_to_the_quote_start() -> None:
    glyphs = [g for top in (100.0, 122.0, 144.0) for g in _row(top, top + 12.0)]
    quote = LocalRect(x0=240.0, y0=121.0, x1=330.0, y1=135.0)
    note = LocalRect(x0=10.0, y0=110.0, x1=60.0, y1=150.0)
    route = plan_connector_route(note, [quote], glyphs, bounds=_BOUNDS, clearance=0.75)
    assert route is not None and route.clean
    assert route.kind in (RouteKind.LEADING_ABOVE, RouteKind.LEADING_BELOW)
    assert abs(route.tip[0] - 240.0) <= 3.0


def test_right_margin_route_mirrors_to_the_quote_end() -> None:
    glyphs = [g for top in (100.0, 122.0, 144.0) for g in _row(top, top + 12.0)]
    quote = LocalRect(x0=240.0, y0=121.0, x1=331.0, y1=135.0)
    note = LocalRect(x0=552.0, y0=110.0, x1=600.0, y1=150.0)
    route = plan_connector_route(note, [quote], glyphs, bounds=_BOUNDS, clearance=0.75)
    assert route is not None and route.clean
    assert abs(route.tip[0] - 331.0) <= 3.0
    assert route.start[0] == pytest.approx(552.0)


@pytest.mark.parametrize("seed", range(5))
def test_fallback_fires_when_a_drawn_stroke_touches_a_glyph_beside_the_tip(seed: int) -> None:
    """The line next to the arrow's endpoint is checked, not exempted."""
    neighbour = (200.0, 108.0, 230.0, 118.0)  # the word just above the tip
    leg = Leg((100.0, 125.0), (150.0, 100.0), (200.0, 100.0), (232.0, 120.0), 0.0)
    route = ConnectorRoute(
        kind=RouteKind.LEADING_ABOVE, legs=(leg,), obstacles=(neighbour,), clean=False
    )
    result = make_routed_connector(random.Random(seed), route, load_builtin_style(), _BOUNDS)
    assert ConnectorDegradation.ROUTING_FALLBACK in result.degradation
