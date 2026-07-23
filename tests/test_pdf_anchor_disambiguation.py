"""Lane D — PDF anchor disambiguation: wire score_candidates into _resolve_annotation_to_anchor.

Known issue #13: the v2 anchor path (_resolve_annotation_to_anchor) is first-hit-wins;
score_candidates' disambiguation machinery exists but is unwired. These tests pin the
required behavior BEFORE the fix is applied.

RED on HEAD (before the fix):
  (a)  test_prefix_suffix_context_selects_second_occurrence
  (b)  test_repeated_passage_no_context_returns_none
  (e2e-b)  test_ambiguous_repeated_target_no_context_is_skipped

GREEN on HEAD (regression guards):
  (c)  test_unique_passage_still_resolves
  (d)  test_no_match_from_scorer_falls_through_to_legacy
  (e2e-a)  test_context_disambiguates_second_occurrence_is_rendered

No network calls; no API key required.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from unittest.mock import patch

import fitz
import pytest

import halfblood.documents.matching as _matching
from halfblood.document_processor import DocumentProcessor
from halfblood.documents import NoMatchResult, PdfPageIndex
from halfblood.models.annotations import Annotation, MarkIntent, TargetSelector
from halfblood.models.documents import (
    AnnotationPlan,
    GenerationProvenance,
    SourceInfo,
    Unit,
)
from halfblood.models.legacy import AnnotationType
from halfblood.models.rendering import RenderReport, SkipReason


# ---------------------------------------------------------------------------
# Page / annotation / plan helpers
# ---------------------------------------------------------------------------


def _make_two_occurrence_doc() -> fitz.Document:
    """One-page doc with 'cauldron' on two distinct lines.

    Line y~100: "The copper cauldron sits on the shelf."
    Line y~200: "The iron cauldron stands unused."

    Boundary y=150 reliably separates the two occurrences in bounding_rect().y0.
    """
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text(
        fitz.Point(72, 100),
        "The copper cauldron sits on the shelf.",
        fontsize=11,
    )
    page.insert_text(
        fitz.Point(72, 200),
        "The iron cauldron stands unused.",
        fontsize=11,
    )
    return doc


def _v2ann(
    ann_id: str,
    exact: str,
    *,
    prefix: str | None = None,
    suffix: str | None = None,
) -> Annotation:
    return Annotation(
        id=ann_id,
        target=TargetSelector(exact=exact, prefix=prefix, suffix=suffix),
        annotation_type=AnnotationType.CORRECTION,
        content="A test margin note.",
        confidence=0.9,
        requested_placement="margin_right",
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
            fingerprint="test" * 16,
            media_type="application/test",
            unit_count=len(units),
        ),
        generation=GenerationProvenance(),
        document_seed=0,
        units=units,
    )


# ---------------------------------------------------------------------------
# Unit tests for _resolve_annotation_to_anchor (v2 anchor path)
# ---------------------------------------------------------------------------


@pytest.fixture()
def dp() -> DocumentProcessor:
    return DocumentProcessor()


class TestResolveAnchorDisambiguation:
    """Unit tests for _resolve_annotation_to_anchor (known issue #13).

    Tests (a) and (b) are RED on HEAD; (c) and (d) are regression guards.
    """

    # ------------------------------------------------------------------
    # (a) prefix/suffix context selects the SECOND occurrence — RED on HEAD
    # ------------------------------------------------------------------
    def test_prefix_suffix_context_selects_second_occurrence(
        self, dp: DocumentProcessor
    ) -> None:
        """score_candidates + prefix/suffix context selects the second 'cauldron'.

        HEAD behaviour: first-hit-wins always returns the first occurrence (y0~91).
        Required: TargetSelector(prefix='iron ', suffix=' stands')
                  → MatchResult for second occurrence (y0~191).
        RED on HEAD.
        """
        doc = _make_two_occurrence_doc()
        page = doc[0]
        index = PdfPageIndex(page)

        ann = _v2ann("a1", "cauldron", prefix="iron ", suffix=" stands")
        anchor = dp._resolve_annotation_to_anchor(page, index, ann)

        assert anchor is not None, (
            "expected an anchor for the unambiguously-contextualised second occurrence"
        )
        br = anchor.bounding_rect()
        assert br.y0 > 150, (
            f"expected y0 > 150 (second 'cauldron' at y~191); got {br.y0:.1f}. "
            "first-hit-wins is still active — score_candidates not yet wired."
        )

    # ------------------------------------------------------------------
    # (b) repeated passage, NO context → AmbiguousResult → None — RED on HEAD
    # ------------------------------------------------------------------
    def test_repeated_passage_no_context_returns_none(
        self, dp: DocumentProcessor
    ) -> None:
        """score_candidates returns AmbiguousResult → fail-closed (return None).

        HEAD behaviour: first-hit-wins, returns an anchor (not None).
        Required: no-context repeated target → return None; do NOT guess first hit.
        RED on HEAD.
        """
        doc = _make_two_occurrence_doc()
        page = doc[0]
        index = PdfPageIndex(page)

        ann = _v2ann("a1", "cauldron")  # no prefix, no suffix
        anchor = dp._resolve_annotation_to_anchor(page, index, ann)

        assert anchor is None, (
            "expected None for ambiguous target with no context; "
            "first-hit-wins must be suppressed when score_candidates returns AmbiguousResult"
        )

    # ------------------------------------------------------------------
    # (c) unique passage → same anchor as before (regression guard — GREEN on HEAD)
    # ------------------------------------------------------------------
    def test_unique_passage_still_resolves(self, dp: DocumentProcessor) -> None:
        """Unique target → MatchResult → anchor resolves to first (only) line.

        Regression guard: MatchResult path must not break unique targets.
        GREEN on HEAD and after fix.
        """
        doc = _make_two_occurrence_doc()
        page = doc[0]
        index = PdfPageIndex(page)

        ann = _v2ann("a1", "copper cauldron sits on the shelf")
        anchor = dp._resolve_annotation_to_anchor(page, index, ann)

        assert anchor is not None, "unique target must still resolve"
        br = anchor.bounding_rect()
        assert br.y0 < 150, (
            f"unique target 'copper cauldron…' must anchor near y=91 (first line); "
            f"got {br.y0:.1f}"
        )

    # ------------------------------------------------------------------
    # (d) NoMatchResult from scorer → legacy _search_variants fallback — GREEN on HEAD
    # ------------------------------------------------------------------
    def test_no_match_from_scorer_falls_through_to_legacy(
        self, dp: DocumentProcessor
    ) -> None:
        """NoMatchResult from score_candidates → legacy ladder still anchors the target.

        Monkeypatches score_candidates in the document_processor namespace to return
        NoMatchResult; the target 'copper cauldron' is findable by page.search_for.
        Pins routing: NoMatch → legacy chain, NOT skip.

        On HEAD (scorer not yet wired): the patch has no effect on _resolve_annotation_to_anchor
        (score_candidates is not called there) so the legacy chain runs unconditionally.
        After fix: patch intercepts the score_candidates call, forces NoMatchResult,
        legacy chain takes over and anchors the target.

        Uses create=True so the patch succeeds on HEAD where the name does not yet
        exist in halfblood.document_processor's namespace.
        """
        doc = _make_two_occurrence_doc()
        page = doc[0]
        index = PdfPageIndex(page)

        ann = _v2ann("a1", "copper cauldron")

        with patch(
            "halfblood.document_processor.score_candidates",
            return_value=NoMatchResult(reason="test-forced no-match"),
            create=True,
        ):
            anchor = dp._resolve_annotation_to_anchor(page, index, ann)

        assert anchor is not None, (
            "legacy fallback must anchor the target even when score_candidates "
            "returns NoMatchResult"
        )
        br = anchor.bounding_rect()
        assert br.y0 < 150, (
            f"legacy fallback must anchor to y~91 for 'copper cauldron'; got {br.y0:.1f}"
        )


# ---------------------------------------------------------------------------
# End-to-end tests through render_plan (cases (a) and (b))
# ---------------------------------------------------------------------------


class TestRenderPlanDisambiguationE2E:
    """End-to-end disambiguation through DocumentProcessor.render_plan."""

    def _make_pdf(self, tmp_path: Path) -> Path:
        """Save a two-occurrence page to tmp_path/two_occ.pdf and return the path."""
        doc = _make_two_occurrence_doc()
        src = tmp_path / "two_occ.pdf"
        doc.save(str(src))
        doc.close()
        return src

    # ------------------------------------------------------------------
    # (e2e-a) context → target found (regression guard — GREEN on HEAD)
    # ------------------------------------------------------------------
    def test_context_disambiguates_second_occurrence_is_rendered(
        self, tmp_path: Path
    ) -> None:
        """With prefix/suffix context, the annotation target is found (not MISSING_TARGET).

        Regression guard: unambiguous context must keep the target found both on HEAD
        (first-hit-wins finds it) and after fix (second occurrence correctly selected).
        The test page is sparse, so UNPLACEABLE is acceptable — only MISSING_TARGET
        would indicate the disambiguation broke a valid target.
        GREEN on HEAD and after fix.
        """
        src = self._make_pdf(tmp_path)
        processor = DocumentProcessor()

        ann = _v2ann("ctx-ann", "cauldron", prefix="iron ", suffix=" stands")
        plan = _plan((1, [ann]))
        report = processor.render_plan(str(src), plan, str(tmp_path / "out.pdf"))

        assert isinstance(report, RenderReport)
        skip_reasons = {s.annotation_id: s.reason for s in report.skipped}
        ctx_reason = skip_reasons.get("ctx-ann")
        # Target must be found (rendered or skipped for layout reasons, never MISSING_TARGET)
        assert "ctx-ann" in report.rendered or ctx_reason != SkipReason.MISSING_TARGET, (
            f"annotation with unambiguous context must have its target found; "
            f"got skip reason={ctx_reason}"
        )

    # ------------------------------------------------------------------
    # (e2e-b) no context on repeated passage → MISSING_TARGET — RED on HEAD
    # ------------------------------------------------------------------
    def test_ambiguous_repeated_target_no_context_is_skipped(
        self, tmp_path: Path
    ) -> None:
        """Without context, repeated target → AmbiguousResult → None → MISSING_TARGET.

        HEAD behaviour: first-hit-wins finds the first occurrence, annotation is
        skipped as UNPLACEABLE (layout fails on sparse page) — NOT MISSING_TARGET.
        Required: score_candidates(AmbiguousResult) → return None → MISSING_TARGET.
        RED on HEAD (UNPLACEABLE != MISSING_TARGET).
        """
        src = self._make_pdf(tmp_path)
        processor = DocumentProcessor()

        ann = _v2ann("ambig-ann", "cauldron")  # no context
        plan = _plan((1, [ann]))
        report = processor.render_plan(str(src), plan, str(tmp_path / "out.pdf"))

        assert isinstance(report, RenderReport)
        assert "ambig-ann" not in report.rendered, (
            "ambiguous target with no context must NOT be rendered"
        )
        skip_reasons = {s.annotation_id: s.reason for s in report.skipped}
        assert skip_reasons.get("ambig-ann") == SkipReason.MISSING_TARGET, (
            f"ambiguous target (no context) must be skipped as MISSING_TARGET "
            f"(from _resolve_annotation_to_anchor returning None); "
            f"got {skip_reasons.get('ambig-ann')}"
        )
