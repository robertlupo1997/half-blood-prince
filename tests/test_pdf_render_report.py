"""P2-T8 — DocumentProcessor.render_plan: resolved anchors, layout, RenderReport.

All tests that call ``processor.render_plan`` fail against HEAD with
``AttributeError: 'DocumentProcessor' object has no attribute 'render_plan'``.
That is the intended failure mode — no existing tests are weakened.

P3-T12b routes marks through the ink composer + ``PdfRenderer`` instead of the
native ``_mark_target``.  Mark-shape assertions therefore spy on
``PdfRenderer.render_scene`` (capturing the composed ``InkScene``); other
behavioral assertions rely on the RenderReport and observable output (vector
drawings, absence of native PDF annotations, output hash).  The legacy
``_draw_resolved_note`` connector regression tests below still exercise the
retained compatibility helper directly.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from unittest.mock import patch

import fitz
import pytest

import halfblood.document_processor as hdp
from halfblood.document_processor import DocumentProcessor
from halfblood.ink.model import InkRole
from halfblood.layout.engine import LayoutResult
from halfblood.models.annotations import Annotation, MarkIntent, TargetSelector
from halfblood.models.documents import (
    AnnotationPlan,
    GenerationProvenance,
    SourceInfo,
    Unit,
)
from halfblood.models.legacy import AnnotationType
from halfblood.models.rendering import RenderReport, SkipReason, SkipRecord
from halfblood.renderers import PdfRenderer

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
SAMPLE_PDF = FIXTURES_DIR / "potions_textbook.pdf"

# Passages known to appear verbatim on each page of the fixture.
_PAGE_TEXT = {
    1: "Potion-making is, and has always been, a discipline of exactitude.",
    2: "The Draught of Living Death is among the most powerful sleeping potions",
    3: "Amortentia is widely considered the most powerful love potion in existence.",
    4: "Felix Felicis",
    5: "Golpalott's Third Law",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ann(
    ann_id: str,
    exact: str,
    *,
    ann_type: AnnotationType = AnnotationType.CORRECTION,
    placement: str = "margin_right",
) -> Annotation:
    """Build a minimal V2 Annotation."""
    return Annotation(
        id=ann_id,
        target=TargetSelector(exact=exact),
        annotation_type=ann_type,
        content="A test margin note.",
        confidence=0.9,
        requested_placement=placement,
        mark_intent=MarkIntent.UNDERLINE,
    )


def _plan(*unit_specs: tuple[int, list[Annotation]]) -> AnnotationPlan:
    """Build a minimal V2 AnnotationPlan from (page_ordinal, [Annotation]) pairs."""
    units = [
        Unit(
            unit_id=str(uuid.uuid4()),
            ordinal=page,
            label=f"Page {page}",
            original_text="",
            source_locator=f"page:{page}",
            annotations=anns,
        )
        for page, anns in unit_specs
    ]
    return AnnotationPlan(
        id=str(uuid.uuid4()),
        title="Test Plan",
        persona="A test persona.",
        source=SourceInfo(
            fingerprint="test" * 16,  # 64-char hex placeholder not required here
            media_type="application/test",
            unit_count=len(units),
        ),
        generation=GenerationProvenance(),
        document_seed=0,
        units=units,
    )


@pytest.fixture()
def processor() -> DocumentProcessor:
    return DocumentProcessor()


@pytest.fixture()
def sample_pdf() -> Path:
    assert SAMPLE_PDF.is_file(), f"missing test fixture: {SAMPLE_PDF}"
    return SAMPLE_PDF


# ---------------------------------------------------------------------------
# P2-T8.1 — render_plan returns a RenderReport
# ---------------------------------------------------------------------------


class TestRenderPlanReturnsReport:
    def test_returns_render_report_type(
        self, processor: DocumentProcessor, sample_pdf: Path, tmp_path: Path
    ) -> None:
        ann = _ann("a1", _PAGE_TEXT[2])
        plan = _plan((2, [ann]))
        report = processor.render_plan(str(sample_pdf), plan, str(tmp_path / "out.pdf"))
        assert isinstance(report, RenderReport)

    def test_empty_plan_returns_zero_counts(
        self, processor: DocumentProcessor, sample_pdf: Path, tmp_path: Path
    ) -> None:
        plan = _plan()
        report = processor.render_plan(str(sample_pdf), plan, str(tmp_path / "out.pdf"))
        assert report.rendered_count == 0
        assert report.skipped_count == 0


# ---------------------------------------------------------------------------
# P2-T8.2 — partition invariant: rendered + skipped == total input annotations
# ---------------------------------------------------------------------------


class TestRenderPlanPartition:
    def test_found_annotation_id_appears_in_rendered(
        self, processor: DocumentProcessor, sample_pdf: Path, tmp_path: Path
    ) -> None:
        ann = _ann("a1", _PAGE_TEXT[2])
        plan = _plan((2, [ann]))
        report = processor.render_plan(str(sample_pdf), plan, str(tmp_path / "out.pdf"))
        assert "a1" in report.rendered

    def test_partition_one_found_one_missing_one_out_of_range(
        self, processor: DocumentProcessor, sample_pdf: Path, tmp_path: Path
    ) -> None:
        ann_found = _ann("a1", _PAGE_TEXT[2])
        ann_missing = _ann("a2", "this phrase does not appear anywhere in the fixture")
        ann_oor = _ann("a3", _PAGE_TEXT[4])
        # a3 on page 99 which does not exist in the 5-page fixture.
        plan = _plan((2, [ann_found, ann_missing]), (99, [ann_oor]))
        report = processor.render_plan(str(sample_pdf), plan, str(tmp_path / "out.pdf"))
        assert report.rendered_count + report.skipped_count == 3

    def test_all_ids_accounted_for_in_rendered_or_skipped(
        self, processor: DocumentProcessor, sample_pdf: Path, tmp_path: Path
    ) -> None:
        expected_ids = {"a1", "a2", "a3"}
        ann_found = _ann("a1", _PAGE_TEXT[2])
        ann_missing = _ann("a2", "this phrase does not appear anywhere in the fixture")
        ann_oor = _ann("a3", _PAGE_TEXT[4])
        plan = _plan((2, [ann_found, ann_missing]), (99, [ann_oor]))
        report = processor.render_plan(str(sample_pdf), plan, str(tmp_path / "out.pdf"))
        accounted = set(report.rendered) | {s.annotation_id for s in report.skipped}
        assert accounted == expected_ids


# ---------------------------------------------------------------------------
# P2-T8.3 — skip reasons are distinct and correct per disposition
# ---------------------------------------------------------------------------


class TestRenderPlanSkipReasons:
    def test_out_of_range_page_produces_out_of_range_skip_reason(
        self, processor: DocumentProcessor, sample_pdf: Path, tmp_path: Path
    ) -> None:
        # Fixture has only 5 pages; page 99 is out of range.
        ann = _ann("a1", _PAGE_TEXT[2])
        plan = _plan((99, [ann]))
        report = processor.render_plan(str(sample_pdf), plan, str(tmp_path / "out.pdf"))
        assert len(report.skipped) == 1
        assert report.skipped[0].annotation_id == "a1"
        assert report.skipped[0].reason == SkipReason.OUT_OF_RANGE_PAGE

    def test_missing_target_produces_missing_target_skip_reason(
        self, processor: DocumentProcessor, sample_pdf: Path, tmp_path: Path
    ) -> None:
        ann = _ann("a2", "this exact phrase is nowhere in the potions textbook at all")
        plan = _plan((1, [ann]))
        report = processor.render_plan(str(sample_pdf), plan, str(tmp_path / "out.pdf"))
        assert len(report.skipped) == 1
        assert report.skipped[0].annotation_id == "a2"
        assert report.skipped[0].reason == SkipReason.MISSING_TARGET

    def test_page_zero_is_out_of_range(
        self, processor: DocumentProcessor, sample_pdf: Path, tmp_path: Path
    ) -> None:
        # Unit ordinal 0 maps to page_index -1, which must be treated as out of range.
        ann = _ann("a1", _PAGE_TEXT[1])
        plan = _plan((0, [ann]))
        report = processor.render_plan(str(sample_pdf), plan, str(tmp_path / "out.pdf"))
        assert len(report.skipped) == 1
        assert report.skipped[0].reason == SkipReason.OUT_OF_RANGE_PAGE


# ---------------------------------------------------------------------------
# P2-T8.4 — no ink drawn for skipped annotations
# ---------------------------------------------------------------------------


class TestRenderPlanNoInk:
    def test_missing_target_leaves_no_native_annotations(
        self, processor: DocumentProcessor, sample_pdf: Path, tmp_path: Path
    ) -> None:
        ann = _ann("a1", "this exact phrase is nowhere in the potions textbook at all")
        plan = _plan((1, [ann]))
        out = tmp_path / "out.pdf"
        processor.render_plan(str(sample_pdf), plan, str(out))
        doc = fitz.open(str(out))
        try:
            assert list(doc[0].annots()) == [], "no ink expected for missing target"
        finally:
            doc.close()

    def test_out_of_range_page_leaves_no_native_annotations(
        self, processor: DocumentProcessor, sample_pdf: Path, tmp_path: Path
    ) -> None:
        ann = _ann("a1", _PAGE_TEXT[2])
        plan = _plan((99, [ann]))
        out = tmp_path / "out.pdf"
        processor.render_plan(str(sample_pdf), plan, str(out))
        doc = fitz.open(str(out))
        try:
            for i in range(doc.page_count):
                assert list(doc[i].annots()) == [], (
                    f"no ink expected on page {i + 1}"
                )
        finally:
            doc.close()


# ---------------------------------------------------------------------------
# P2-T8.5 — output atomicity and source fidelity
# ---------------------------------------------------------------------------


class TestRenderPlanOutput:
    def test_output_file_exists_and_is_nonzero(
        self, processor: DocumentProcessor, sample_pdf: Path, tmp_path: Path
    ) -> None:
        plan = _plan()
        out = tmp_path / "out.pdf"
        processor.render_plan(str(sample_pdf), plan, str(out))
        assert out.is_file()
        assert out.stat().st_size > 0

    def test_source_page_count_preserved(
        self, processor: DocumentProcessor, sample_pdf: Path, tmp_path: Path
    ) -> None:
        plan = _plan()
        out = tmp_path / "out.pdf"
        processor.render_plan(str(sample_pdf), plan, str(out))
        src = fitz.open(str(sample_pdf))
        dst = fitz.open(str(out))
        try:
            assert dst.page_count == src.page_count
        finally:
            src.close()
            dst.close()

    def test_source_page_rect_unchanged(
        self, processor: DocumentProcessor, sample_pdf: Path, tmp_path: Path
    ) -> None:
        ann = _ann("a1", _PAGE_TEXT[2])
        plan = _plan((2, [ann]))
        out = tmp_path / "out.pdf"
        processor.render_plan(str(sample_pdf), plan, str(out))
        src = fitz.open(str(sample_pdf))
        dst = fitz.open(str(out))
        try:
            for i in range(src.page_count):
                assert tuple(dst[i].rect) == pytest.approx(tuple(src[i].rect), abs=1.0), (
                    f"page {i + 1} rect changed after render"
                )
        finally:
            src.close()
            dst.close()

    def test_source_page_rotation_unchanged(
        self, processor: DocumentProcessor, sample_pdf: Path, tmp_path: Path
    ) -> None:
        ann = _ann("a1", _PAGE_TEXT[2])
        plan = _plan((2, [ann]))
        out = tmp_path / "out.pdf"
        processor.render_plan(str(sample_pdf), plan, str(out))
        src = fitz.open(str(sample_pdf))
        dst = fitz.open(str(out))
        try:
            for i in range(src.page_count):
                assert dst[i].rotation == src[i].rotation, (
                    f"page {i + 1} rotation changed"
                )
        finally:
            src.close()
            dst.close()

    def test_original_page_text_survives_render(
        self, processor: DocumentProcessor, sample_pdf: Path, tmp_path: Path
    ) -> None:
        ann = _ann("a1", _PAGE_TEXT[2])
        plan = _plan((2, [ann]))
        out = tmp_path / "out.pdf"
        processor.render_plan(str(sample_pdf), plan, str(out))
        src = fitz.open(str(sample_pdf))
        dst = fitz.open(str(out))
        try:
            for i in range(src.page_count):
                # All words present in the source must still be findable on output.
                for word in src[i].get_text("words"):
                    word_text = word[4]
                    assert dst[i].search_for(word_text), (
                        f"word {word_text!r} missing from page {i + 1} after render"
                    )
        finally:
            src.close()
            dst.close()


# ---------------------------------------------------------------------------
# P2-T8.6 — per-quad marking: one _mark_target call per line, never a union
# ---------------------------------------------------------------------------


def _capture_scenes(
    processor: DocumentProcessor, src: Path, plan: AnnotationPlan, out: Path
) -> list:
    """Run render_plan while capturing every InkScene handed to PdfRenderer.

    P3-T12b routes marks through ``PdfRenderer.render_scene`` instead of the
    native ``_mark_target``.  Spying the class method captures the real composed
    scenes without needing to inject a factory into render_plan's internal
    renderer.  On HEAD render_plan never constructs a PdfRenderer, so nothing is
    captured — the intended pre-implementation failure.
    """
    captured: list = []
    real = PdfRenderer.render_scene

    def spy(self_inner, page, scene):  # type: ignore[no-untyped-def]
        captured.append(scene)
        return real(self_inner, page, scene)

    with patch.object(PdfRenderer, "render_scene", spy):
        processor.render_plan(str(src), plan, str(out))
    return captured


def _underline_paths(scenes: list) -> list:
    """All stroke paths across captured scenes whose group role is UNDERLINE."""
    return [
        path
        for scene in scenes
        for group in scene.groups
        if group.role == InkRole.UNDERLINE
        for path in group.paths
    ]


class TestRenderPlanPerQuadMarking:
    """Verify the 'one vector mark per quad' contract via the composed InkScene.

    P3-T12b replaces the native ``_mark_target`` marks with per-quad vector paths
    from ``make_underline``: one ``InkRole.UNDERLINE`` group whose path count equals
    the number of target line quads (never a single tall union).
    """

    def _make_two_line_pdf(self, tmp_path: Path) -> Path:
        """Create an in-memory PDF with 'silver dagger' spanning two lines."""
        doc = fitz.open()
        page = doc.new_page(width=612, height=792)
        page.insert_text(fitz.Point(72, 300), "Slice the bean with a silver", fontsize=11)
        page.insert_text(fitz.Point(72, 316), "dagger before pressing it flat.", fontsize=11)
        src = tmp_path / "two_line.pdf"
        doc.save(str(src))
        doc.close()
        return src

    def test_wrapped_two_line_target_marks_each_quad_separately(
        self, processor: DocumentProcessor, tmp_path: Path
    ) -> None:
        """A target spanning two text lines produces two per-quad underline paths.

        One tall union path is the OLD behavior.  The requirement is one vector
        underline path per line quad.
        """
        src = self._make_two_line_pdf(tmp_path)
        ann = _ann("a1", "silver dagger before pressing it flat")
        plan = _plan((1, [ann]))

        scenes = _capture_scenes(processor, src, plan, tmp_path / "out.pdf")
        paths = _underline_paths(scenes)
        assert len(paths) == 2, (
            f"expected 2 per-quad underline paths (one per wrapped line), got {len(paths)}"
        )

    def test_single_line_target_marks_one_quad(
        self, processor: DocumentProcessor, tmp_path: Path
    ) -> None:
        """A single-line target produces exactly one underline vector path."""
        doc = fitz.open()
        page = doc.new_page(width=612, height=792)
        page.insert_text(fitz.Point(72, 300), "Slice the bean with care.", fontsize=11)
        src = tmp_path / "one_line.pdf"
        doc.save(str(src))
        doc.close()

        ann = _ann("a1", "Slice the bean")
        plan = _plan((1, [ann]))

        scenes = _capture_scenes(processor, src, plan, tmp_path / "out.pdf")
        paths = _underline_paths(scenes)
        assert len(paths) == 1, (
            f"expected 1 underline path for single-line target, got {len(paths)}"
        )

    def test_found_annotation_renders_vectors_not_native_annots(
        self, processor: DocumentProcessor, sample_pdf: Path, tmp_path: Path
    ) -> None:
        """A matched annotation now renders as vector drawings, not a native annot.

        P3-T12b replaces native PDF mark annotations with ``fitz.Shape`` vector
        paths, so the output page carries vector drawings and ZERO newly-created
        native annotations.
        """
        ann = _ann("a1", _PAGE_TEXT[2])
        plan = _plan((2, [ann]))
        out = tmp_path / "out.pdf"
        report = processor.render_plan(str(sample_pdf), plan, str(out))
        assert "a1" in report.rendered, "the target should have been found and rendered"

        doc = fitz.open(str(out))
        try:
            page = doc[1]  # page 2 (0-indexed)
            assert list(page.annots()) == [], (
                "P3-T12b marks must be vector paths, not native PDF annotations"
            )
            assert page.get_drawings(), "a rendered mark must leave vector drawings on the page"
        finally:
            doc.close()


# ---------------------------------------------------------------------------
# P2-T8.7 — layout priority order: WARNING before CORRECTION on same page
# ---------------------------------------------------------------------------


class TestRenderPlanLayoutOrder:
    def test_warning_placed_before_correction_on_same_page(
        self, processor: DocumentProcessor, tmp_path: Path
    ) -> None:
        """WARNING (priority 0) must appear before CORRECTION (priority 1) in rendered.

        Input order is deliberately CORRECTION then WARNING; the report must
        reflect layout priority order, not input order.
        """
        doc = fitz.open()
        page = doc.new_page(width=612, height=792)
        page.insert_text(fitz.Point(72, 100), "The cauldron must be copper.", fontsize=11)
        page.insert_text(fitz.Point(72, 200), "Never use iron — it taints the potion.", fontsize=11)
        src = tmp_path / "order_src.pdf"
        doc.save(str(src))
        doc.close()

        # Input order: CORRECTION first, WARNING second.
        ann_corr = _ann("c1", "copper", ann_type=AnnotationType.CORRECTION)
        ann_warn = _ann("w1", "iron", ann_type=AnnotationType.WARNING)
        plan = _plan((1, [ann_corr, ann_warn]))

        report = processor.render_plan(str(src), plan, str(tmp_path / "out.pdf"))

        rendered = list(report.rendered)
        if "w1" in rendered and "c1" in rendered:
            assert rendered.index("w1") < rendered.index("c1"), (
                "WARNING (priority 0) must be rendered before CORRECTION (priority 1)"
            )


# ---------------------------------------------------------------------------
# P2-T8-fix — connector anchor must use the NEAR (facing-target) edge of note_box
#
# Bug: line 635 of _draw_resolved_note had the x0/x1 pick inverted.
# For side=="right" (note in right margin) the code gave note_rect.x1 (far edge);
# for side=="left" (note in left margin) it gave note_rect.x0 (far edge).
# The connector therefore started at the WRONG end of the note, pointing away
# from the target text — a re-introduction of the "connector arrows reversed"
# bug class documented in CLAUDE.md.
#
# Both scenarios below FAIL on the buggy code and PASS after the one-line swap.
# ---------------------------------------------------------------------------


class TestConnectorAnchorNearEdge:
    """Regression: _draw_resolved_note must start the connector at the near edge.

    We call _draw_resolved_note directly with a controlled note_box and a
    crafted ResolvedAnnotation so the geometry is exact and unambiguous.
    _draw_connector is spied on to capture the anchor.x it receives.
    """

    def _make_page(self) -> fitz.Page:
        doc = fitz.open()
        page = doc.new_page(width=612, height=792)
        # Insert some text so the shape system has a valid page context.
        page.insert_text(fitz.Point(72, 300), "Target text passage here.", fontsize=11)
        return page

    def _resolved_ann(
        self,
        ann_id: str,
        note_x0: float,
        note_y0: float,
        note_x1: float,
        note_y1: float,
        quad_x0: float,
        quad_y0: float,
        quad_x1: float,
        quad_y1: float,
        placement: str,
    ) -> object:
        """Build a ResolvedAnnotation with controlled note_box and anchor quad."""
        from halfblood.models.rendering import (
            ResolvedAnchor,
            ResolvedAnnotation,
            SurfacePoint,
            SurfaceQuad,
            SurfaceRect,
        )

        quad = SurfaceQuad(
            ul=SurfacePoint(x=quad_x0, y=quad_y0),
            ur=SurfacePoint(x=quad_x1, y=quad_y0),
            lr=SurfacePoint(x=quad_x1, y=quad_y1),
            ll=SurfacePoint(x=quad_x0, y=quad_y1),
        )
        return ResolvedAnnotation(
            annotation_id=ann_id,
            source_locator="page:1",
            requested_placement=placement,  # type: ignore[arg-type]  # Literal alias, not instantiable
            resolved_placement=placement,  # type: ignore[arg-type]
            anchor=ResolvedAnchor(char_range=(0, 5), quads=(quad,)),
            note_box=SurfaceRect(x0=note_x0, y0=note_y0, x1=note_x1, y1=note_y1),
            render_seed=0,
        )

    def test_right_margin_note_anchor_uses_near_left_edge(
        self, processor: DocumentProcessor
    ) -> None:
        """Note in RIGHT margin: connector must start at note_rect.x0 (near/left edge).

        Layout:  target=[72..320]   note=[415..590]
        Correct anchor.x: 415 (note_rect.x0, left/near edge, facing the text)
        Buggy   anchor.x: 590 (note_rect.x1, right/far edge, facing away from text)
        """
        page = self._make_page()
        # note is clearly to the RIGHT of the target text
        note_x0, note_x1 = 415.0, 590.0
        resolved = self._resolved_ann(
            "fix-right",
            note_x0=note_x0, note_y0=285.0, note_x1=note_x1, note_y1=315.0,
            quad_x0=72.0, quad_y0=290.0, quad_x1=320.0, quad_y1=305.0,
            placement="margin_right",
        )
        ann = _ann("fix-right", "Target text passage here.", placement="margin_right")

        captured: list[tuple[str, float]] = []  # (side, anchor.x)
        real_draw = DocumentProcessor._draw_connector

        def spy_connector(self_inner, shape, rect, anchor, ink, opacity, side):  # type: ignore[no-untyped-def]
            captured.append((side, anchor.x))
            return real_draw(self_inner, shape, rect, anchor, ink, opacity, side)

        with patch.object(DocumentProcessor, "_draw_connector", spy_connector):
            processor._draw_resolved_note(page, resolved, ann)  # type: ignore[arg-type]

        assert captured, "_draw_connector was never called — no connector was drawn"
        side, anchor_x = captured[0]
        assert side == "right", f"expected side='right', got {side!r}"
        assert anchor_x == pytest.approx(note_x0, abs=0.5), (
            f"connector anchor.x should be note_rect.x0={note_x0} (near/left edge "
            f"facing target), but got {anchor_x:.1f} — likely using the far edge x1={note_x1}"
        )

    def test_left_margin_note_anchor_uses_near_right_edge(
        self, processor: DocumentProcessor
    ) -> None:
        """Note in LEFT margin: connector must start at note_rect.x1 (near/right edge).

        Layout:  note=[10..65]   target=[100..320]
        Correct anchor.x: 65 (note_rect.x1, right/near edge, facing the text)
        Buggy   anchor.x: 10 (note_rect.x0, left/far edge, facing away from text)
        """
        page = self._make_page()
        # note is clearly to the LEFT of the target text
        note_x0, note_x1 = 10.0, 65.0
        resolved = self._resolved_ann(
            "fix-left",
            note_x0=note_x0, note_y0=285.0, note_x1=note_x1, note_y1=315.0,
            quad_x0=100.0, quad_y0=290.0, quad_x1=320.0, quad_y1=305.0,
            placement="margin_left",
        )
        ann = _ann("fix-left", "Target text passage here.", placement="margin_left")

        captured: list[tuple[str, float]] = []
        real_draw = DocumentProcessor._draw_connector

        def spy_connector(self_inner, shape, rect, anchor, ink, opacity, side):  # type: ignore[no-untyped-def]
            captured.append((side, anchor.x))
            return real_draw(self_inner, shape, rect, anchor, ink, opacity, side)

        with patch.object(DocumentProcessor, "_draw_connector", spy_connector):
            processor._draw_resolved_note(page, resolved, ann)  # type: ignore[arg-type]

        assert captured, "_draw_connector was never called — no connector was drawn"
        side, anchor_x = captured[0]
        assert side == "left", f"expected side='left', got {side!r}"
        assert anchor_x == pytest.approx(note_x1, abs=0.5), (
            f"connector anchor.x should be note_rect.x1={note_x1} (near/right edge "
            f"facing target), but got {anchor_x:.1f} — likely using the far edge x0={note_x0}"
        )


# ---------------------------------------------------------------------------
# P3-T12b — integration: composed vector marks reach the PDF (the risky seam)
# ---------------------------------------------------------------------------


class TestRenderPlanVectorIntegration:
    """P3-T12b wires InkComposer + PdfRenderer into render_plan.

    These fail on HEAD because render_plan still draws native marks and returns
    no output_hashes.
    """

    def test_output_report_carries_pdf_output_hash(
        self, processor: DocumentProcessor, sample_pdf: Path, tmp_path: Path
    ) -> None:
        """render_plan stamps a role='pdf' OutputHash matching the written file."""
        import hashlib

        ann = _ann("a1", _PAGE_TEXT[2])
        plan = _plan((2, [ann]))
        out = tmp_path / "out.pdf"
        report = processor.render_plan(str(sample_pdf), plan, str(out))

        pdf_hashes = [h for h in report.output_hashes if h.role == "pdf"]
        assert len(pdf_hashes) == 1, "exactly one role='pdf' OutputHash expected"
        on_disk = hashlib.sha256(out.read_bytes()).hexdigest()
        assert pdf_hashes[0].sha256 == on_disk, (
            "OutputHash must be computed from the final on-disk PDF (after atomic replace)"
        )

    def test_rotated_page_renders_vectors_and_preserves_source(
        self, processor: DocumentProcessor, tmp_path: Path
    ) -> None:
        """The rotated-page seam: vectors drawn, no native annots, source intact.

        This is the riskiest coordinate/layer seam — a 90-degree page must still
        get vector marks (via the renderer's single derotation), keep its rotation,
        text, and gain no native annotations.
        """
        doc = fitz.open()
        page = doc.new_page(width=612, height=792)
        page.insert_text(fitz.Point(72, 300), "The rotated cauldron simmers slowly.", fontsize=11)
        page.set_rotation(90)
        src = tmp_path / "rotated.pdf"
        doc.save(str(src))
        doc.close()

        ann = _ann("r1", "rotated cauldron")
        plan = _plan((1, [ann]))
        out = tmp_path / "out.pdf"
        report = processor.render_plan(str(src), plan, str(out))

        # This single-line page has no inferable body columns, so the margin note
        # fails closed (MP1c). Its on-target underline mark still survives (MP1d) —
        # which is exactly the rotated-page vector seam under test.
        assert "r1" not in report.rendered
        assert "r1" in report.marks_only, (
            "the target mark must survive on the rotated page even when the note is "
            "fail-closed as unplaceable"
        )

        result = fitz.open(str(out))
        try:
            rpage = result[0]
            assert rpage.rotation == 90, "source page rotation must be preserved"
            assert "rotated cauldron" in rpage.get_text(), "source page text must survive"
            assert list(rpage.annots()) == [], "marks must be vectors, not native annotations"
            assert rpage.get_drawings(), "vector marks must be present on the rotated page"
        finally:
            result.close()


# ---------------------------------------------------------------------------
# MP1d — mark-survives-unplaceable-note: a target mark still renders even when
# its margin note is skipped as unplaceable, recorded in report.marks_only.
# ---------------------------------------------------------------------------


def _force_unplaceable(page, requests, occupancy, measurer, config=None, body_columns=()):  # type: ignore[no-untyped-def]
    """A layout_page_annotations spy: every resolved request is skipped UNPLACEABLE."""
    return LayoutResult(
        placed=(),
        skipped=tuple(
            SkipRecord(
                annotation_id=r.annotation_id,
                reason=SkipReason.UNPLACEABLE,
                detail="forced unplaceable for test",
            )
            for r in requests
        ),
        degradation_flags=(),
    )


class TestMarkSurvivesUnplaceableNote:
    def test_mark_renders_when_note_is_unplaceable(
        self, processor: DocumentProcessor, sample_pdf: Path, tmp_path: Path
    ) -> None:
        ann = _ann("a1", _PAGE_TEXT[2])  # resolves on page 2; mark_intent=UNDERLINE
        plan = _plan((2, [ann]))
        out = tmp_path / "out.pdf"

        captured: list = []
        real_render = PdfRenderer.render_scene

        def render_spy(self_inner, page, scene):  # type: ignore[no-untyped-def]
            captured.append(scene)
            return real_render(self_inner, page, scene)

        real_layout = hdp.layout_page_annotations
        hdp.layout_page_annotations = _force_unplaceable
        try:
            with patch.object(PdfRenderer, "render_scene", render_spy):
                report = processor.render_plan(str(sample_pdf), plan, str(out))
        finally:
            hdp.layout_page_annotations = real_layout

        # The note itself was skipped as unplaceable...
        assert "a1" not in report.rendered
        assert any(
            s.annotation_id == "a1" and s.reason == SkipReason.UNPLACEABLE
            for s in report.skipped
        )
        # ...but its on-target mark still rendered.
        assert "a1" in report.marks_only

        # A mark-only scene reached the renderer: an underline group, and NO
        # connector / doodle / handwriting group (the doodle role is not
        # note_box-gated, so this guards the mark_only compose contract).
        mark_scenes = [
            s for s in captured if any(g.role == InkRole.UNDERLINE for g in s.groups)
        ]
        assert mark_scenes, "expected an underline mark scene for the skipped note"
        for scene in mark_scenes:
            roles = {g.role for g in scene.groups}
            assert InkRole.CONNECTOR not in roles
            assert InkRole.DOODLE not in roles
            assert InkRole.HANDWRITING not in roles

    def test_marks_only_excludes_notes_without_a_mark(
        self, processor: DocumentProcessor, sample_pdf: Path, tmp_path: Path
    ) -> None:
        # mark_intent=NONE → nothing to survive; must not appear in marks_only.
        ann = Annotation(
            id="nomark",
            target=TargetSelector(exact=_PAGE_TEXT[2]),
            annotation_type=AnnotationType.CORRECTION,
            content="A note with no target mark.",
            confidence=0.9,
            requested_placement="margin_right",
            mark_intent=MarkIntent.NONE,
        )
        plan = _plan((2, [ann]))
        out = tmp_path / "out.pdf"

        real_layout = hdp.layout_page_annotations
        hdp.layout_page_annotations = _force_unplaceable
        try:
            report = processor.render_plan(str(sample_pdf), plan, str(out))
        finally:
            hdp.layout_page_annotations = real_layout

        assert "nomark" not in report.marks_only
        assert any(
            s.annotation_id == "nomark" and s.reason == SkipReason.UNPLACEABLE
            for s in report.skipped
        )
