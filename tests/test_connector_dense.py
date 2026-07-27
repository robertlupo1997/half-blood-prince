"""Regression tests: make_connector and render_plan must degrade, not crash, with many obstacles.

Bug: src/halfblood/ink/rough.py previously raised ValueError("too many obstacles") when the
obstacle count exceeded 100. Densely-typeset books routinely produce 100+ line-run obstacles
per page, causing render_plan to crash entirely.

Fix contract:
  - make_connector must never raise ValueError for any obstacle count.
  - When capping, it must record ConnectorDegradation.OBSTACLE_CAP_USED (not ROUTING_FALLBACK).
  - ROUTING_FALLBACK is reserved for genuine routing failure (all waypoints exhausted).
  - Both flags may appear together when cap fires AND routing also fails.
  - render_plan must complete (returning a RenderReport) on a page with 120 text-line obstacles.
  - Connectors must NOT cross obstacles that are outside the pruned corridor but on a detour path.

These tests fail at base commit dcea9f2 and pass after the fix.
"""

from __future__ import annotations

import math
import random
import uuid
from pathlib import Path

import fitz
import pytest

from halfblood.document_processor import DocumentProcessor
from halfblood.ink.model import CubicTo, InkRole, LocalPoint, LocalRect
from halfblood.ink.rough import (
    _CONNECTOR_OBSTACLE_LIMIT,
    ConnectorDegradation,
    ConnectorResult,
    make_connector,
)
from halfblood.ink.seeding import make_stream
from halfblood.ink.style import load_builtin_style
from halfblood.models.annotations import Annotation, MarkIntent, TargetSelector
from halfblood.models.documents import (
    AnnotationPlan,
    GenerationProvenance,
    SourceInfo,
    Unit,
)
from halfblood.models.legacy import AnnotationType
from halfblood.models.rendering import RenderReport

# ---------------------------------------------------------------------------
# Shared geometry for unit-level tests
# ---------------------------------------------------------------------------

# Tall bounds to accommodate vertical connector routing tests.
_BOUNDS = LocalRect(x0=0.0, y0=0.0, x1=612.0, y1=2000.0)
_DOC_SEED = 77
_ANN_ID = "dense-obs-test"
_ALGO_VER = "test-v1"

# Horizontal connector across most of the page width.
_NOTE_EDGE = LocalPoint(x=15.0, y=50.0)
_TARGET_EDGE = LocalPoint(x=560.0, y=50.0)
_CLEARANCE = 3.0

# Corridor (with clearance expansion): x ≈ [12, 563], y ≈ [47, 53].
# Obstacles placed within this band will NOT be pruned by the geographic filter.


def _rng(label: str) -> random.Random:
    return make_stream(_DOC_SEED, _ANN_ID, InkRole.CONNECTOR, _ALGO_VER, label)


def _in_corridor_obstacles(n: int) -> list[LocalRect]:
    """Return *n* small rects that all lie inside the connector corridor.

    Each rect is a 2×6-point sliver at y=[48,54] — overlapping the corridor y-band
    [47,53] after clearance expansion — stacked side-by-side across the x-axis.
    With n>100 these force the obstacle cap to fire.
    """
    return [
        LocalRect(x0=50.0 + i * 3.0, y0=48.0, x1=52.0 + i * 3.0, y1=54.0)
        for i in range(n)
    ]


def _out_of_corridor_obstacles(n: int) -> list[LocalRect]:
    """Return *n* rects that are entirely below the connector corridor.

    Placed at y=[700,710], well below the corridor y-upper-bound (~53).
    After clearance expansion (y=[697,713]) they still do not reach y=47,
    so every obstacle is pruned by the geographic filter.
    """
    return [
        LocalRect(x0=50.0 + i * 3.0, y0=700.0, x1=52.0 + i * 3.0, y1=710.0)
        for i in range(n)
    ]


def _route_crosses_obstacle(
    result: ConnectorResult, obstacle: LocalRect, clearance: float
) -> bool:
    """Return True if any sampled point on the connector path is inside the expanded obstacle.

    Samples 21 points on each Bézier segment to approximate the full curve.
    Returns False if there are no path commands.
    """
    expanded = LocalRect(
        x0=obstacle.x0 - clearance,
        y0=obstacle.y0 - clearance,
        x1=obstacle.x1 + clearance,
        y1=obstacle.y1 + clearance,
    )

    def _inside(px: float, py: float) -> bool:
        return expanded.x0 <= px <= expanded.x1 and expanded.y0 <= py <= expanded.y1

    def _bezier_samples(
        p0x: float, p0y: float, cmd: CubicTo, n: int = 20
    ) -> list[tuple[float, float]]:
        pts = []
        for i in range(1, n):
            t = i / n
            mt = 1.0 - t
            bx = (
                mt**3 * p0x
                + 3 * mt**2 * t * cmd.x1
                + 3 * mt * t**2 * cmd.x2
                + t**3 * cmd.x
            )
            by = (
                mt**3 * p0y
                + 3 * mt**2 * t * cmd.y1
                + 3 * mt * t**2 * cmd.y2
                + t**3 * cmd.y
            )
            pts.append((bx, by))
        return pts

    for path in result.group.paths:
        prev_x = path.commands[0].x
        prev_y = path.commands[0].y
        for cmd in path.commands:
            if _inside(cmd.x, cmd.y):
                return True
            if isinstance(cmd, CubicTo):
                if _inside(cmd.x1, cmd.y1) or _inside(cmd.x2, cmd.y2):
                    return True
                for bx, by in _bezier_samples(prev_x, prev_y, cmd):
                    if _inside(bx, by):
                        return True
            prev_x, prev_y = cmd.x, cmd.y
    return False


# ---------------------------------------------------------------------------
# Regression tests: detour-obstacle counterexamples
# ---------------------------------------------------------------------------


class TestConnectorDetourObstacleCounterexamples:
    """Prove that pruned obstacles on detour paths do NOT cause crossings.

    These two cases were identified by adversarial review as regressions introduced
    by an earlier (strict-inequality, pruned-set-validation) pruning implementation.
    """

    def test_counterexample_detour_blocker_outside_direct_corridor(self) -> None:
        """Counterexample 1: detour-blocker at y=70 is outside the direct corridor.

        Geometry:
          start (10,50) → target (110,50), clearance=10
          blocker        [49,49,51,51]  — on the direct y=50 path
          detour_blocker [47,70,49,72] — below the direct corridor; on the perpendicular detour

        With the buggy strict < corridor filter, detour_blocker was pruned.
        The router then chose a perpendicular waypoint that went through detour_blocker.
        After the fix (inclusive filter + full-set validation), the emitted connector
        must not cross the detour_blocker's expanded zone.
        """
        bounds = LocalRect(x0=0.0, y0=0.0, x1=200.0, y1=200.0)
        note_edge = LocalPoint(x=10.0, y=50.0)
        target_edge = LocalPoint(x=110.0, y=50.0)
        clearance = 10.0
        blocker = LocalRect(x0=49.0, y0=49.0, x1=51.0, y1=51.0)
        detour_blocker = LocalRect(x0=47.0, y0=70.0, x1=49.0, y1=72.0)
        obstacles = [blocker, detour_blocker]

        result = make_connector(
            _rng("detour-1"),
            note_edge,
            target_edge,
            obstacles,
            clearance,
            load_builtin_style(),
            bounds,
            "cn-detour1",
        )

        assert not _route_crosses_obstacle(result, detour_blocker, clearance), (
            "Connector crosses the detour_blocker obstacle — "
            "detour validation used only the pruned set instead of the full set"
        )

    def test_counterexample_boundary_obstacle_zero_clearance(self) -> None:
        """Counterexample 2: zero-clearance boundary obstacle pruned by strict inequality.

        Geometry:
          horizontal connector at y=50, clearance=0
          boundary_obstacle [59,50,61,55] — touches the corridor upper boundary at y0=50 exactly

        With strict < the old filter had (y0 - 0) < cy1 → (50 < 50) → False → pruned.
        With inclusive <= it is retained and the router avoids it (or degrades if blocked).
        Either way, the connector must not cross the boundary_obstacle's expanded zone.
        """
        bounds = LocalRect(x0=0.0, y0=0.0, x1=200.0, y1=200.0)
        note_edge = LocalPoint(x=10.0, y=50.0)
        target_edge = LocalPoint(x=180.0, y=50.0)
        clearance = 0.0
        boundary_obstacle = LocalRect(x0=59.0, y0=50.0, x1=61.0, y1=55.0)

        result = make_connector(
            _rng("boundary-0clr"),
            note_edge,
            target_edge,
            [boundary_obstacle],
            clearance,
            load_builtin_style(),
            bounds,
            "cn-boundary",
        )

        assert not _route_crosses_obstacle(result, boundary_obstacle, clearance), (
            "Connector crosses a boundary obstacle that was incorrectly pruned — "
            "corridor filter must use inclusive bounds (>= / <=)"
        )


# ---------------------------------------------------------------------------
# Unit tests: make_connector with many obstacles
# ---------------------------------------------------------------------------


class TestMakeConnectorWithManyObstacles:
    """make_connector must degrade gracefully, never raise, at any obstacle count."""

    def test_over_limit_returns_connector_result(self) -> None:
        """150 in-corridor obstacles must not raise ValueError — returns ConnectorResult."""
        obstacles = _in_corridor_obstacles(150)
        # At base this raises: ValueError("too many obstacles")
        result = make_connector(
            _rng("dense-150"),
            _NOTE_EDGE,
            _TARGET_EDGE,
            obstacles,
            _CLEARANCE,
            load_builtin_style(),
            _BOUNDS,
            "cn-dense",
        )
        assert isinstance(result, ConnectorResult)
        assert isinstance(result.group.paths, tuple)
        assert len(result.group.paths) >= 1

    def test_over_limit_records_obstacle_cap_used(self) -> None:
        """Capping > 100 in-corridor obstacles must set OBSTACLE_CAP_USED, not ROUTING_FALLBACK."""
        obstacles = _in_corridor_obstacles(150)
        result = make_connector(
            _rng("dense-fallback"),
            _NOTE_EDGE,
            _TARGET_EDGE,
            obstacles,
            _CLEARANCE,
            load_builtin_style(),
            _BOUNDS,
            "cn-df",
        )
        assert ConnectorDegradation.OBSTACLE_CAP_USED in result.degradation, (
            f"Expected OBSTACLE_CAP_USED when > 100 obstacles are capped; "
            f"got {result.degradation}"
        )

    def test_routing_fallback_and_obstacle_cap_are_distinct_flags(self) -> None:
        """OBSTACLE_CAP_USED and ROUTING_FALLBACK are separate flags and never confused.

        When 150 in-corridor obstacles block the path, both cap AND routing failure may
        occur.  OBSTACLE_CAP_USED records the cap; ROUTING_FALLBACK records routing
        exhaustion.  Neither flag duplicates the other in the output tuple.
        """
        obstacles = _in_corridor_obstacles(150)
        result = make_connector(
            _rng("dense-dedup"),
            _NOTE_EDGE,
            _TARGET_EDGE,
            obstacles,
            _CLEARANCE,
            load_builtin_style(),
            _BOUNDS,
            "cn-dd",
        )
        # Cap must be recorded.
        assert ConnectorDegradation.OBSTACLE_CAP_USED in result.degradation
        # Neither flag appears more than once.
        assert result.degradation.count(ConnectorDegradation.OBSTACLE_CAP_USED) == 1
        assert result.degradation.count(ConnectorDegradation.ROUTING_FALLBACK) <= 1

    def test_exactly_at_limit_does_not_raise(self) -> None:
        """Exactly _CONNECTOR_OBSTACLE_LIMIT in-corridor obstacles must not raise."""
        obstacles = _in_corridor_obstacles(_CONNECTOR_OBSTACLE_LIMIT)
        result = make_connector(
            _rng("at-limit"),
            _NOTE_EDGE,
            _TARGET_EDGE,
            obstacles,
            _CLEARANCE,
            load_builtin_style(),
            _BOUNDS,
            "cn-at",
        )
        assert isinstance(result, ConnectorResult)
        # Cap must not fire at exactly the limit.
        assert ConnectorDegradation.OBSTACLE_CAP_USED not in result.degradation

    def test_out_of_corridor_obstacles_do_not_trigger_cap_or_degradation(self) -> None:
        """150 obstacles entirely outside the corridor are pruned — no cap, no blocking."""
        obstacles = _out_of_corridor_obstacles(150)
        result = make_connector(
            _rng("oob-150"),
            _NOTE_EDGE,
            _TARGET_EDGE,
            obstacles,
            _CLEARANCE,
            load_builtin_style(),
            _BOUNDS,
            "cn-oob",
        )
        # All obstacles are out-of-corridor → corridor is clear → no degradation.
        assert result.degradation == (), (
            f"Expected no degradation with all obstacles out of corridor; "
            f"got {result.degradation}"
        )

    def test_non_finite_clearance_does_not_raise(self) -> None:
        """Non-finite clearance must not raise or produce infinite/NaN coordinates."""
        obstacles = [LocalRect(x0=30.0, y0=30.0, x1=50.0, y1=70.0)]
        result = make_connector(
            _rng("inf-clr"),
            _NOTE_EDGE,
            _TARGET_EDGE,
            obstacles,
            float("inf"),
            load_builtin_style(),
            _BOUNDS,
            "cn-inf",
        )
        assert isinstance(result, ConnectorResult)
        # All path coordinates must be finite.
        for path in result.group.paths:
            for cmd in path.commands:
                assert math.isfinite(cmd.x) and math.isfinite(cmd.y), (
                    f"Non-finite coordinate in connector output: ({cmd.x}, {cmd.y})"
                )

    def test_determinism_preserved_with_many_obstacles(self) -> None:
        """Same seed + same obstacle list → identical structural result."""
        from halfblood.ink.model import InkScene, scene_structural_hash

        obstacles = _in_corridor_obstacles(150)
        style = load_builtin_style()

        def _do() -> ConnectorResult:
            return make_connector(
                _rng("det-dense"),
                _NOTE_EDGE,
                _TARGET_EDGE,
                obstacles,
                _CLEARANCE,
                style,
                _BOUNDS,
                "cn-det",
            )

        def _hash(r: ConnectorResult) -> str:
            xs = [c.x for p in r.group.paths for c in p.commands]
            ys = [c.y for p in r.group.paths for c in p.commands]
            scene = InkScene(
                ink_algorithm_version=_ALGO_VER,
                annotation_id=_ANN_ID,
                seed=_DOC_SEED,
                bounds=LocalRect(
                    x0=min(xs) - 1.0,
                    y0=min(ys) - 1.0,
                    x1=max(xs) + 1.0,
                    y1=max(ys) + 1.0,
                ),
                groups=(r.group,),
            )
            return scene_structural_hash(scene)

        assert _hash(_do()) == _hash(_do()), (
            "make_connector is not deterministic with many obstacles"
        )


# ---------------------------------------------------------------------------
# render_plan integration test: dense PDF must not raise
# ---------------------------------------------------------------------------

_DENSE_TARGET = "The annotated passage on this dense page."


@pytest.fixture()
def dense_pdf(tmp_path: Path) -> Path:
    """Create a PDF page with 120 text-line obstacles (one insert_text per line).

    PyMuPDF assigns a distinct block_no to each insert_text call, so the
    occupancy extractor produces one line-run per call — 120 obstacles total.
    A known target passage is embedded at line 60 so annotation resolution succeeds.
    """
    doc = fitz.open()
    # Wide, tall page: generous left/right margins for note placement.
    page = doc.new_page(width=842, height=2200)
    fontsize = 13.0
    leading = fontsize * 1.5  # ~19.5pt per line; 120 lines → ~2340pt total

    # Use a margin of 170pt on each side so the layout engine can place notes.
    x_start = 170.0

    lines = [
        f"Dense body text line {i:03d} with sufficient words to fill the column."
        for i in range(120)
    ]
    lines[60] = _DENSE_TARGET  # known target text

    y = 30.0
    for line_text in lines:
        page.insert_text(fitz.Point(x_start, y), line_text, fontsize=fontsize)
        y += leading

    path = tmp_path / "dense.pdf"
    doc.save(str(path))
    doc.close()
    return path


def _dense_plan(target_text: str) -> AnnotationPlan:
    ann = Annotation(
        id="ann-dense-1",
        target=TargetSelector(exact=target_text),
        annotation_type=AnnotationType.CORRECTION,
        content="Snape scrawls here.",
        confidence=0.9,
        requested_placement="margin_left",
        mark_intent=MarkIntent.UNDERLINE,
    )
    unit = Unit(
        unit_id=str(uuid.uuid4()),
        ordinal=1,
        label="Page 1",
        original_text="",
        source_locator="page:1",
        annotations=[ann],
    )
    return AnnotationPlan(
        id=str(uuid.uuid4()),
        title="Dense Page Test Plan",
        persona="A terse annotator.",
        source=SourceInfo(
            fingerprint="test" * 16,
            media_type="application/pdf",
            unit_count=1,
        ),
        generation=GenerationProvenance(),
        document_seed=0,
        units=[unit],
    )


class TestRenderPlanWithDensePage:
    """render_plan must complete without raising on a page with 120+ obstacles."""

    def test_render_plan_dense_page_does_not_raise(
        self, dense_pdf: Path, tmp_path: Path
    ) -> None:
        """render_plan returns a RenderReport — never ValueError — on a dense page.

        At base commit this crashes with ValueError("too many obstacles") propagated
        from make_connector via InkComposer.compose → _rough_engine.generate.
        """
        processor = DocumentProcessor()
        plan = _dense_plan(_DENSE_TARGET)
        out = tmp_path / "dense_out.pdf"

        # Must not raise any exception (specifically not ValueError).
        report = processor.render_plan(str(dense_pdf), plan, str(out))

        assert isinstance(report, RenderReport), (
            f"Expected RenderReport, got {type(report)}"
        )
        # The annotation was either rendered or skipped — both are valid outcomes.
        total = len(report.rendered) + len(report.skipped)
        assert total >= 1, "RenderReport accounts for zero annotations — unexpected"
