"""Regression tests: make_connector and render_plan must degrade, not crash, with many obstacles.

Bug: src/halfblood/ink/rough.py:408 raises ValueError("too many obstacles") when the obstacle
count exceeds 100. Densely-typeset books routinely produce 100+ line-run obstacles per page,
causing render_plan to crash entirely.

Fix contract:
  - make_connector must never raise ValueError for any obstacle count.
  - When capping, it must record ConnectorDegradation.ROUTING_FALLBACK.
  - render_plan must complete (returning a RenderReport) on a page with 120 text-line obstacles.

These tests fail at base commit dcea9f2 and pass after the fix.
"""

from __future__ import annotations

import random
import uuid
from pathlib import Path

import fitz
import pytest

from halfblood.document_processor import DocumentProcessor
from halfblood.ink.model import InkRole, LocalPoint, LocalRect
from halfblood.ink.rough import (
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

    def test_over_limit_records_routing_fallback(self) -> None:
        """Capping > 100 in-corridor obstacles must set ROUTING_FALLBACK degradation."""
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
        assert ConnectorDegradation.ROUTING_FALLBACK in result.degradation, (
            f"Expected ROUTING_FALLBACK when > 100 obstacles are capped; got {result.degradation}"
        )

    def test_no_duplicate_routing_fallback_in_degradation(self) -> None:
        """ROUTING_FALLBACK appears at most once even when both the cap and routing fire."""
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
        flag_count = result.degradation.count(ConnectorDegradation.ROUTING_FALLBACK)
        assert flag_count <= 1, (
            f"ROUTING_FALLBACK appears {flag_count} times; expected at most 1"
        )

    def test_exactly_at_limit_does_not_raise(self) -> None:
        """Exactly _CONNECTOR_OBSTACLE_LIMIT in-corridor obstacles must not raise."""
        from halfblood.ink.rough import _CONNECTOR_OBSTACLE_LIMIT

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

    def test_out_of_corridor_obstacles_do_not_trigger_cap(self) -> None:
        """150 obstacles entirely outside the corridor are pruned — cap does not fire."""
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
        # All obstacles pruned → clear path → no ROUTING_FALLBACK from the cap.
        # (routing may still succeed cleanly or fall back for other reasons, but the
        # cap path is not taken, so the result should have no cap-induced flag.)
        assert isinstance(result, ConnectorResult)
        # With zero surviving obstacles the midpoint is unblocked → routing succeeds.
        assert result.degradation == (), (
            f"Expected no degradation with all obstacles out of corridor; got {result.degradation}"
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
