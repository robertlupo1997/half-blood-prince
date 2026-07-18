"""Document processing for the Half-Blood Prince annotator.

This module is responsible for everything that touches the actual PDF
bytes: pulling text out of a book, locating the exact passages an
annotation plan refers to, and burning handwritten-style margin notes
back onto the page.

The "handwriting" is produced with `PyMuPDF <https://pymupdf.readthedocs.io/>`_
(imported as ``fitz``). Text is drawn through a :class:`fitz.Shape`, which
lets us apply an arbitrary rotation matrix (``morph``) to each line so the
notes look organically scrawled rather than typeset. Target passages are
marked using PyMuPDF's native annotation types (underline, strikeout,
highlight, circle) so the marks remain first-class, editable PDF
annotations rather than baked-in ink.

Font note
---------
By default this module looks for a handwriting font at
``<project_root>/fonts/CaveatBrush-Regular.ttf``. That file is **not**
bundled with the repo (font licensing). Download "Caveat Brush" (or
plain "Caveat") from Google Fonts::

    https://fonts.google.com/specimen/Caveat+Brush
    https://fonts.google.com/specimen/Caveat

and drop the ``.ttf`` file at ``fonts/CaveatBrush-Regular.ttf`` relative
to the project root. If no font is found, this module transparently
falls back to the PDF standard font ``Helvetica-Oblique`` so the
pipeline never breaks -- it will just look less handwritten.
"""

from __future__ import annotations

import logging
import math
import os
import random
import re
import tempfile
from collections.abc import Sequence
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import fitz  # PyMuPDF

from halfblood.documents import (
    PdfAlignmentError,
    PdfPageIndex,
    normalize,
    resolve_pdf_anchor,
)
from halfblood.layout.engine import (
    LayoutConfig,
    LayoutResult,
    NoteMeasurer,
    NoteRequest,
)
from halfblood.models import (
    AnnotatedPage,
    Annotation,
    AnnotationPlan,
    AnnotationType,
)

if TYPE_CHECKING:
    from halfblood.documents.pdf import PdfAnchor
    from halfblood.models.annotations import Annotation as V2Annotation
    from halfblood.models.documents import AnnotationPlan as V2AnnotationPlan
    from halfblood.models.rendering import RenderReport, ResolvedAnnotation

logger = logging.getLogger(__name__)

# An absent auto-discovered font is an expected fallback, so avoid repeating
# the same informational notice for every processor created in a batch.
_missing_font_notice_logged = False


# --------------------------------------------------------------------------
# Data types
# --------------------------------------------------------------------------


@dataclass
class PageContent:
    """Plain-text extraction of a single PDF page."""

    page_number: int  # 1-indexed, matches Annotation.page / AnnotatedPage.page_number
    text: str
    width: float
    height: float


# --------------------------------------------------------------------------
# Styling constants
# --------------------------------------------------------------------------

#: "Old ink" palette per annotation type, as (r, g, b) floats in [0, 1].
#: Everything defaults to an iron-gall blue-black; a couple of types get a
#: rustier, more agitated brown-red to read as more urgent.
_INK_PALETTE: dict[AnnotationType, tuple[float, float, float]] = {
    AnnotationType.CORRECTION: (0.14, 0.13, 0.42),
    AnnotationType.IMPROVEMENT: (0.11, 0.16, 0.38),
    AnnotationType.INSIGHT: (0.16, 0.12, 0.40),
    AnnotationType.INVENTION: (0.20, 0.10, 0.35),
    AnnotationType.WARNING: (0.46, 0.07, 0.07),
    AnnotationType.SHORTCUT: (0.13, 0.18, 0.36),
    AnnotationType.CROSSED_OUT: (0.50, 0.14, 0.06),
    AnnotationType.DOODLE_NOTE: (0.18, 0.15, 0.38),
}
_DEFAULT_INK = (0.13, 0.13, 0.40)

#: Base font size per annotation type, in points.
_FONT_SIZE_BY_TYPE: dict[AnnotationType, float] = {
    AnnotationType.CORRECTION: 9.5,
    AnnotationType.IMPROVEMENT: 9.5,
    AnnotationType.INSIGHT: 9.0,
    AnnotationType.INVENTION: 9.5,
    AnnotationType.WARNING: 10.0,
    AnnotationType.SHORTCUT: 9.0,
    AnnotationType.CROSSED_OUT: 8.5,
    AnnotationType.DOODLE_NOTE: 8.0,
}

_VALID_POSITIONS = {"margin_right", "margin_left", "inline", "between_lines"}

_MARGIN_GAP = 10.0  # points between target text and margin note
_MAX_MARGIN_WIDTH = 150.0
_MIN_MARGIN_WIDTH = 40.0
_PAGE_EDGE_PAD = 12.0


class DocumentProcessor:
    """Extracts text from PDFs and renders Half-Blood-Prince-style
    handwritten margin annotations back onto them.
    """

    class _LayoutMeasurer:
        """NoteMeasurer adapter wrapping the processor's handwriting font metric.

        Satisfies layout.engine.NoteMeasurer without importing the protocol.
        """

        def __init__(self, font: Any, base_fontsize: float = 9.0) -> None:
            self._font = font
            self._base_fontsize = base_fontsize

        def measure(self, text: str, max_width: float, scale: float) -> tuple[float, float]:
            fontsize = self._base_fontsize * scale
            # Clamp width to the column; approximate line height as fontsize * 1.3.
            width = min(max_width, self._font.text_length(text, fontsize=fontsize))
            return (width, fontsize * 1.3)

    def __init__(
        self,
        font_path: str | None = None,
        project_root: str | None = None,
        seed: int | None = None,
    ) -> None:
        """
        Args:
            font_path: Explicit path to a handwriting TTF/OTF. If given,
                this always wins over auto-discovery.
            project_root: Root directory to search for ``fonts/CaveatBrush-Regular.ttf``.
                Defaults to the repo root inferred from this file's location.
            seed: Optional seed for the "organic" rotation jitter, so
                renders are reproducible in tests. Defaults to a
                per-annotation deterministic seed derived from its text.
        """
        self._project_root = (
            Path(project_root) if project_root else Path(__file__).resolve().parents[2]
        )
        self._seed = seed
        self._fontfile, self._fontname, self._is_custom_font = self._resolve_handwriting_font(
            font_path
        )
        self._measure_font = self._load_measure_font()

    # ----------------------------------------------------------------
    # Font resolution
    # ----------------------------------------------------------------

    def _resolve_handwriting_font(
        self, explicit_font_path: str | None
    ) -> tuple[str | None, str, bool]:
        """Locate a handwriting font on disk.

        Resolution order:
            1. ``explicit_font_path`` if it exists.
            2. ``<project_root>/fonts/CaveatBrush-Regular.ttf``
            3. Any ``<project_root>/fonts/*aveat*.tt[fc]`` (Caveat / Caveat Brush,
               any weight/case).
            4. A short list of common system font install locations.
            5. Fallback: PDF standard font ``Helvetica-Oblique`` (no file
               needed). An informational notice is logged once per process.

        Returns:
            (fontfile_path_or_None, fontname_alias, is_custom_font)
        """
        if explicit_font_path:
            explicit_path = Path(explicit_font_path)
            if explicit_path.is_file():
                logger.debug("Using handwriting font: %s", explicit_path)
                return str(explicit_path), "HBProseHand", True
            logger.warning(
                "Configured handwriting font does not exist: %s; "
                "continuing with auto-discovery.",
                explicit_font_path,
            )

        candidates: list[Path] = []

        fonts_dir = self._project_root / "fonts"
        candidates.append(fonts_dir / "CaveatBrush-Regular.ttf")

        if fonts_dir.is_dir():
            candidates.extend(sorted(fonts_dir.glob("*aveat*.ttf")))
            candidates.extend(sorted(fonts_dir.glob("*aveat*.otf")))

        system_candidates = [
            Path("C:/Windows/Fonts/Caveat-Regular.ttf"),
            Path("C:/Windows/Fonts/CaveatBrush-Regular.ttf"),
            Path("/Library/Fonts/Caveat-Regular.ttf"),
            Path.home() / "Library/Fonts/Caveat-Regular.ttf",
            Path("/usr/share/fonts/truetype/caveat/Caveat-Regular.ttf"),
        ]
        candidates.extend(system_candidates)

        for path in candidates:
            if path.is_file():
                logger.debug("Using handwriting font: %s", path)
                return str(path), "HBProseHand", True

        global _missing_font_notice_logged
        if not _missing_font_notice_logged:
            logger.info(
                "No handwriting font found (looked for %s and system Caveat installs). "
                "Falling back to Helvetica-Oblique.",
                fonts_dir / "CaveatBrush-Regular.ttf",
            )
            _missing_font_notice_logged = True
        return None, "Helvetica-Oblique", False

    def _load_measure_font(self) -> fitz.Font:
        """A `fitz.Font` used purely for measuring text width when wrapping."""
        if self._fontfile:
            return fitz.Font(fontfile=self._fontfile)
        return fitz.Font("helv")  # metrics stand-in for Helvetica-Oblique

    # ----------------------------------------------------------------
    # Extraction
    # ----------------------------------------------------------------

    def load(self, path: str) -> list[PageContent]:
        """Extract text from every page of a PDF.

        Args:
            path: Path to the source PDF.

        Returns:
            One `PageContent` per page, 1-indexed via `page_number`.
        """
        pages: list[PageContent] = []
        doc = fitz.open(path)
        try:
            for index in range(doc.page_count):
                page = doc[index]
                pages.append(
                    PageContent(
                        page_number=index + 1,
                        text=page.get_text("text"),
                        width=page.rect.width,
                        height=page.rect.height,
                    )
                )
        finally:
            doc.close()
        return pages

    # ----------------------------------------------------------------
    # Locating annotation targets
    # ----------------------------------------------------------------

    @staticmethod
    def _normalize_search_text(text: str) -> str:
        """Collapse whitespace/newlines and normalize "smart" punctuation
        so that LLM-generated `target_text` matches the PDF's text layer.
        """
        # Standard PDF fonts can expose unsupported smart punctuation as a
        # middle dot. Its position still distinguishes an apostrophe inside a
        # word from a standalone dash.
        text = re.sub(r"(?<=\w)·(?=\w)", "'", text)
        text = text.replace("·", "-")
        return normalize(text).strip()

    @staticmethod
    def _union_rects(rects: Sequence[fitz.Rect]) -> fitz.Rect:
        union = fitz.Rect(rects[0])
        for rect in rects[1:]:
            union |= rect
        return union

    @classmethod
    def _first_contiguous_hit_group_rects(
        cls, hits: Sequence[fitz.Rect]
    ) -> list[fitz.Rect]:
        """Return the first deterministic group of contiguous hit rectangles.

        ``Page.search_for`` returns one rectangle per occurrence, except that
        a phrase wrapping onto the next line is returned as consecutive line
        fragments. Keep those adjacent fragments together without spanning
        later, distinct occurrences elsewhere on the page.
        """
        first_group = [hits[0]]
        previous = hits[0]
        for hit in hits[1:]:
            same_line = hit.y0 < previous.y1 and previous.y0 < hit.y1
            line_height = max(previous.height, hit.height)
            vertical_gap = hit.y0 - previous.y1
            if same_line or vertical_gap > line_height * 1.5:
                break
            first_group.append(hit)
            previous = hit
        return first_group

    @classmethod
    def _first_contiguous_hit_group(cls, hits: Sequence[fitz.Rect]) -> fitz.Rect:
        """Return the union of the first deterministic contiguous hit group."""
        return cls._union_rects(cls._first_contiguous_hit_group_rects(hits))

    def _find_normalized_word_rect(
        self, page: fitz.Page, normalized_target: str
    ) -> fitz.Rect | None:
        """Find one punctuation-normalized substring in the page's words."""
        words = page.get_text("words", sort=True)
        if not words:
            return None

        normalized_words = [self._normalize_search_text(str(word[4])) for word in words]
        page_text = " ".join(normalized_words)
        start = page_text.find(normalized_target)
        if start < 0:
            return None

        end = start + len(normalized_target)
        matched_rects: list[fitz.Rect] = []
        offset = 0
        for word, normalized_word in zip(words, normalized_words, strict=True):
            word_end = offset + len(normalized_word)
            if word_end > start and offset < end:
                matched_rects.append(fitz.Rect(word[:4]))
            if offset >= end:
                break
            offset = word_end + 1

        if not matched_rects:
            return None
        return self._union_rects(matched_rects)

    def _search_variants(self, text: str) -> list[str]:
        """Generate progressively looser variants of `text` to try against
        `page.search_for`, since PDF text extraction can reflow whitespace
        and LLM output rarely matches the source byte-for-byte.
        """
        words = text.split(" ")
        variants: list[str] = [text]
        if len(words) > 8:
            variants.append(" ".join(words[:8]))
        if len(words) > 5:
            variants.append(" ".join(words[:5]))
        if len(words) > 3:
            variants.append(" ".join(words[:3]))
        # Last resort: the single longest word, as a rough anchor point.
        longest = max((w.strip(".,;:!?\"'()") for w in words), key=len, default="")
        if len(longest) >= 4:
            variants.append(longest)
        # De-dupe while preserving order.
        seen: set[str] = set()
        unique: list[str] = []
        for variant in variants:
            if variant and variant not in seen:
                seen.add(variant)
                unique.append(variant)
        return unique

    def find_text_rect(self, page: fitz.Page, text: str) -> fitz.Rect | None:
        """Locate `text` on `page` and return its bounding rectangle.

        Tries an exact (whitespace-normalized) match first, then falls
        back to shorter prefixes / the longest single word so that minor
        transcription drift from an LLM-generated `target_text` doesn't
        cause the whole annotation to be dropped.

        Returns:
            A `fitz.Rect` spanning all matched hits (unioned across lines
            if the passage wraps), or `None` if nothing could be found.
        """
        normalized = self._normalize_search_text(text)
        if not normalized:
            return None

        try:
            index = PdfPageIndex(page)
        except PdfAlignmentError:
            index = None

        for variant in self._search_variants(normalized):
            hits = page.search_for(variant)
            if hits:
                if len(variant) < len(normalized):
                    logger.debug(
                        "Exact match for %r not found; used fallback anchor %r",
                        text,
                        variant,
                    )
                group = self._first_contiguous_hit_group_rects(hits)
                if index is None:
                    return self._union_rects(group)
                span = index.char_span_for_rects(group)
                if span is None:
                    return self._union_rects(group)
                anchor = resolve_pdf_anchor(index, *span)
                if anchor is None:
                    return self._union_rects(group)
                return anchor.bounding_rect()

        normalized_rect = self._find_normalized_word_rect(page, normalized)
        if normalized_rect is not None:
            logger.debug(
                "Native search for %r failed; used normalized page-text match",
                text,
            )
            return normalized_rect

        logger.warning("Could not locate target_text %r on page", text)
        return None

    def _render_seed_for(self, annotation_id: str, document_seed: int) -> int:
        """Derive a stable per-annotation render seed from document seed + annotation id."""
        import hashlib

        digest = hashlib.sha256(f"render:{document_seed}:{annotation_id}".encode()).digest()
        return int.from_bytes(digest[:8], byteorder="big", signed=False)

    def _resolve_annotation_to_anchor(
        self,
        page: fitz.Page,
        index: PdfPageIndex | None,
        annotation: V2Annotation,
    ) -> PdfAnchor | None:
        """Resolve a V2 annotation target to per-line quads, or None if not found.

        Uses the same _search_variants + page.search_for chain as find_text_rect
        but returns the PdfAnchor with individual per-line quads intact — it does
        NOT call bounding_rect().

        When index is None (PdfAlignmentError on this page), synthesizes a single-quad
        anchor from the search hit's union rect so the page still renders.

        Args:
            page: The fitz.Page to search.
            index: The pre-built PdfPageIndex for this page, or None.
            annotation: A V2 Annotation whose target.exact is the search string.

        Returns:
            PdfAnchor with per-line quads, or None if the target cannot be found.
        """
        from halfblood.documents.pdf import PdfAnchor

        normalized = self._normalize_search_text(annotation.target.exact)
        if not normalized:
            return None

        def _fallback_anchor(rect: fitz.Rect) -> PdfAnchor:
            return PdfAnchor(
                quads=(rect.quad,),
                char_range=(0, 0),
                line_count=1,
                page_rotation=page.rotation,
            )

        for variant in self._search_variants(normalized):
            hits = page.search_for(variant)
            if not hits:
                continue

            group = self._first_contiguous_hit_group_rects(hits)
            if index is None:
                return _fallback_anchor(self._union_rects(group))

            span = index.char_span_for_rects(group)
            if span is None:
                return _fallback_anchor(self._union_rects(group))

            anchor = resolve_pdf_anchor(index, *span)
            if anchor is not None:
                return anchor
            return _fallback_anchor(self._union_rects(group))

        # Last resort: word-normalized fallback
        normalized_rect = self._find_normalized_word_rect(page, normalized)
        if normalized_rect is not None:
            if index is not None:
                span = index.char_span_for_rects([normalized_rect])
                if span is not None:
                    anchor = resolve_pdf_anchor(index, *span)
                    if anchor is not None:
                        return anchor
            return _fallback_anchor(normalized_rect)

        return None

    # ----------------------------------------------------------------
    # Rendering
    # ----------------------------------------------------------------

    def render_annotations(
        self, input_path: str, annotations: list[Annotation], output_path: str
    ) -> None:
        """Render a full set of annotations onto a PDF and save the result.

        Args:
            input_path: Source PDF path.
            annotations: Annotations to render. `Annotation.page` is
                1-indexed, matching `PageContent.page_number`.
            output_path: Where to write the annotated PDF.
        """
        doc = fitz.open(input_path)
        try:
            by_page: dict[int, list[Annotation]] = {}
            for annotation in annotations:
                by_page.setdefault(annotation.page, []).append(annotation)

            rendered = 0
            skipped = 0
            for page_number in sorted(by_page):
                page_index = page_number - 1
                if page_index < 0 or page_index >= doc.page_count:
                    logger.warning(
                        "Annotation references page %s but document only has %s pages; skipping",
                        page_number,
                        doc.page_count,
                    )
                    skipped += len(by_page[page_number])
                    continue

                page = doc[page_index]
                for annotation in by_page[page_number]:
                    rect = self.find_text_rect(page, annotation.target_text)
                    if rect is None:
                        skipped += 1
                        continue
                    self.add_margin_note(
                        page,
                        rect,
                        annotation.content,
                        annotation.annotation_type,
                        annotation.confidence,
                        position=annotation.position,
                    )
                    rendered += 1

            logger.info(
                "Rendered %s annotation(s), skipped %s (target text not found or "
                "page out of range)",
                rendered,
                skipped,
            )
            doc.save(output_path, garbage=4, deflate=True)
        finally:
            doc.close()

    def _draw_resolved_note(
        self,
        page: fitz.Page,
        resolved_ann: ResolvedAnnotation,
        annotation: V2Annotation,
    ) -> None:
        """Draw the annotation note at the layout-resolved note_box.

        This is the resolved-plan counterpart to the _write_margin_text family:
        it BYPASSES _write_margin_text (which recomputes placement from scratch)
        and writes directly into the pre-resolved note_box rect.

        Args:
            page: The fitz.Page to draw on.
            resolved_ann: The placed ResolvedAnnotation from LayoutResult; its
                note_box and anchor carry the resolver's geometry.
            annotation: The original V2 Annotation for content, type, confidence.
        """
        from halfblood.layout.anchors import fitz_rect_from_surf, fitz_rect_from_surf_quad

        if resolved_ann.note_box is None:
            return

        note_rect = fitz_rect_from_surf(resolved_ann.note_box)
        ink = self._ink_color(annotation.annotation_type)
        opacity = self._opacity(annotation.confidence)
        angle = self._organic_angle(annotation.content)
        fontsize = _FONT_SIZE_BY_TYPE.get(annotation.annotation_type, 9.0)

        shape = page.new_shape()

        # Write text lines inside the note_box.
        note_width = max(1.0, note_rect.width)
        lines = self._wrap_text(annotation.content, note_width, fontsize)
        line_gap = fontsize * 1.3
        y = note_rect.y0 + fontsize

        for line in lines:
            if y > note_rect.y1 + line_gap:
                break
            pivot = fitz.Point((note_rect.x0 + note_rect.x1) / 2.0, y)
            morph = (pivot, fitz.Matrix(angle))
            shape.insert_text(
                fitz.Point(note_rect.x0, y),
                line,
                fontfile=self._fontfile,
                fontname=self._fontname,
                fontsize=fontsize,
                color=ink,
                morph=morph,
            )
            y += line_gap

        # Connector: from note_box anchor point to the first target quad's rect.
        if resolved_ann.anchor and resolved_ann.anchor.quads:
            target_rect = fitz_rect_from_surf_quad(resolved_ann.anchor.quads[0])
            # Determine which side the note is on relative to the target.
            note_cx = (note_rect.x0 + note_rect.x1) / 2.0
            target_cx = (target_rect.x0 + target_rect.x1) / 2.0
            connector_side = "right" if note_cx > target_cx else "left"
            connector_anchor = fitz.Point(
                note_rect.x1 if connector_side == "left" else note_rect.x0,
                (note_rect.y0 + note_rect.y1) / 2.0,
            )
            self._draw_connector(
                shape,
                target_rect,
                connector_anchor,
                ink,
                opacity,
                side=connector_side,
            )

        shape.commit(overlay=True)

    def render_plan(
        self,
        input_path: str,
        plan: V2AnnotationPlan,
        output_path: str,
    ) -> RenderReport:
        """Render a V2 AnnotationPlan onto a PDF using resolved anchors and layout.

        Pipeline per page:
          1. Build PdfPageIndex for per-char geometry.
          2. _resolve_annotation_to_anchor: each annotation → PdfAnchor or MISSING.
          3. layout_page_annotations: assigns note_box and placement to each request.
          4. For placed annotations: _mark_target per quad; _draw_resolved_note.
          5. Accumulate rendered IDs and SkipRecords into a RenderReport.

        Output is written atomically: fitz saves to a temp file in the same directory,
        then os.replace to output_path.

        This method does NOT touch render_annotations or add_margin_note.

        Args:
            input_path: Source PDF path.
            plan: A validated V2 AnnotationPlan (halfblood.models.documents.AnnotationPlan).
            output_path: Destination PDF path (created or overwritten atomically).

        Returns:
            RenderReport with rendered/skipped partition covering all input annotations.
        """
        from halfblood.layout.anchors import (
            fitz_rect_from_surf_quad,
            pdf_anchor_to_resolved_anchor,
        )
        from halfblood.models.documents import Unit
        from halfblood.models.rendering import RenderReport, SkipReason, SkipRecord

        # Build per-page lookup: ordinal -> (unit, [V2Annotation])
        # and per-id lookup for the draw phase.
        by_page: dict[int, tuple[Unit, list[V2Annotation]]] = {}
        ann_by_id: dict[str, tuple[Unit, V2Annotation]] = {}
        for unit in plan.units:
            by_page[unit.ordinal] = (unit, list(unit.annotations))
            for ann in unit.annotations:
                ann_by_id[ann.id] = (unit, ann)

        rendered_ids: list[str] = []
        skip_records: list[SkipRecord] = []
        measurer = self._LayoutMeasurer(self._measure_font)

        doc = fitz.open(input_path)
        try:
            for page_ordinal in sorted(by_page):
                unit, annotations = by_page[page_ordinal]
                page_index = page_ordinal - 1

                # Out-of-range page: skip all annotations on this unit.
                if page_index < 0 or page_index >= doc.page_count:
                    for ann in annotations:
                        skip_records.append(
                            SkipRecord(
                                annotation_id=ann.id,
                                reason=SkipReason.OUT_OF_RANGE_PAGE,
                                detail=(
                                    f"page {page_ordinal} is out of range "
                                    f"[1, {doc.page_count}]"
                                ),
                            )
                        )
                    continue

                page = doc[page_index]
                try:
                    index: PdfPageIndex | None = PdfPageIndex(page)
                except PdfAlignmentError:
                    index = None

                # --- Resolution phase ---
                requests: list[NoteRequest] = []
                resolution_miss_ids: list[str] = []

                for ann in annotations:
                    pdf_anchor = self._resolve_annotation_to_anchor(page, index, ann)
                    if pdf_anchor is None:
                        resolution_miss_ids.append(ann.id)
                    else:
                        resolved_anchor = pdf_anchor_to_resolved_anchor(pdf_anchor)
                        requests.append(
                            NoteRequest(
                                annotation_id=ann.id,
                                source_locator=unit.source_locator,
                                annotation_type=ann.annotation_type,
                                confidence=ann.confidence,
                                content=ann.content,
                                requested_placement=ann.requested_placement,
                                anchor=resolved_anchor,
                                render_seed=self._render_seed_for(ann.id, plan.document_seed),
                            )
                        )

                # --- Layout phase ---
                if requests:
                    layout_result = layout_page_annotations(page, requests, [], measurer)
                else:
                    layout_result = LayoutResult(
                        placed=(),
                        skipped=(),
                        degradation_flags=(),
                    )

                # --- Drawing phase ---
                for resolved_ann in layout_result.placed:
                    _, ann = ann_by_id[resolved_ann.annotation_id]
                    ink = self._ink_color(ann.annotation_type)
                    opacity = self._opacity(ann.confidence)

                    # Mark each quad separately — NOT a union.
                    if resolved_ann.anchor:
                        for quad in resolved_ann.anchor.quads:
                            quad_rect = fitz_rect_from_surf_quad(quad)
                            self._mark_target(
                                page,
                                quad_rect,
                                ann.annotation_type,
                                ink,
                                opacity,
                            )

                    self._draw_resolved_note(page, resolved_ann, ann)
                    rendered_ids.append(resolved_ann.annotation_id)

                # Layout skips (UNPLACEABLE etc.)
                for skip in layout_result.skipped:
                    skip_records.append(skip)

                # Resolution misses (MISSING_TARGET)
                for ann_id in resolution_miss_ids:
                    skip_records.append(
                        SkipRecord(
                            annotation_id=ann_id,
                            reason=SkipReason.MISSING_TARGET,
                            detail="target text not found on page",
                        )
                    )

            # Atomic output: temp file in same dir → rename.
            out_path = Path(output_path)
            fd, tmp_str = tempfile.mkstemp(dir=out_path.parent, suffix=".pdf.tmp")
            os.close(fd)
            try:
                doc.save(tmp_str, garbage=4, deflate=True)
                os.replace(tmp_str, output_path)
            except Exception:
                with suppress(OSError):
                    os.unlink(tmp_str)
                raise

        finally:
            doc.close()

        return RenderReport(
            rendered=tuple(rendered_ids),
            skipped=tuple(skip_records),
        )

    def add_margin_note(
        self,
        page: fitz.Page,
        rect: fitz.Rect | None,
        text: str,
        annotation_type: AnnotationType,
        confidence: float = 0.8,
        position: str = "margin_right",
    ) -> None:
        """Render a single handwritten-style annotation onto `page`.

        This both marks the target passage (underline / circle / strikeout
        / highlight, chosen by `annotation_type`) and writes the margin
        note itself in a rotated, ink-colored handwriting font, connected
        to the target with a small hand-drawn arrow when it sits in a
        margin.

        Args:
            page: The `fitz.Page` to draw on.
            rect: Bounding rect of the target passage (from `find_text_rect`).
                If `None`, a small placeholder rect near the top of the
                page is used so the note still renders somewhere sane.
            text: The margin note text (the "Prince's" commentary).
            annotation_type: Determines ink color, marking style, and size.
            confidence: 0..1. Higher confidence renders bolder, more
                opaque ink; lower confidence renders lighter, as if
                dashed off uncertainly.
            position: One of "margin_right", "margin_left", "inline",
                "between_lines".
        """
        if rect is None:
            logger.warning(
                "add_margin_note called without a target rect; placing near page top"
            )
            rect = fitz.Rect(
                page.rect.x0 + 36, page.rect.y0 + 36, page.rect.x0 + 220, page.rect.y0 + 50
            )

        if position not in _VALID_POSITIONS:
            logger.warning("Unknown position %r; defaulting to margin_right", position)
            position = "margin_right"

        ink = self._ink_color(annotation_type)
        opacity = self._opacity(confidence)
        angle = self._organic_angle(text)
        fontsize = _FONT_SIZE_BY_TYPE.get(annotation_type, 9.0)

        shape = page.new_shape()

        self._mark_target(page, rect, annotation_type, ink, opacity)

        if position == "margin_right":
            anchor, resolved_side = self._write_margin_text(
                shape, page, rect, text, ink, angle, fontsize, opacity, "right"
            )
            self._draw_connector(shape, rect, anchor, ink, opacity, side=resolved_side)
        elif position == "margin_left":
            anchor, resolved_side = self._write_margin_text(
                shape, page, rect, text, ink, angle, fontsize, opacity, "left"
            )
            self._draw_connector(shape, rect, anchor, ink, opacity, side=resolved_side)
        elif position == "inline":
            self._write_inline_text(shape, page, rect, text, ink, angle, fontsize, opacity)
        elif annotation_type == AnnotationType.CROSSED_OUT:  # between_lines
            self._write_replacement_above(shape, rect, text, ink, angle, fontsize, opacity)
        else:  # between_lines
            self._write_between_lines_text(shape, rect, text, ink, angle, fontsize, opacity)

        shape.commit(overlay=True)

    # ------------------------------------------------------------
    # Marking the target passage
    # ------------------------------------------------------------

    def _mark_target(
        self,
        page: fitz.Page,
        rect: fitz.Rect,
        annotation_type: AnnotationType,
        ink: tuple[float, float, float],
        opacity: float,
    ) -> None:
        """Mark `rect` using a native PDF annotation matching `annotation_type`."""
        if annotation_type == AnnotationType.CROSSED_OUT:
            annot = page.add_strikeout_annot(rect)
        elif annotation_type == AnnotationType.WARNING:
            annot = page.add_highlight_annot(rect)
        elif annotation_type in (
            AnnotationType.INSIGHT,
            AnnotationType.INVENTION,
            AnnotationType.DOODLE_NOTE,
        ):
            padded = fitz.Rect(rect.x0 - 3, rect.y0 - 2, rect.x1 + 3, rect.y1 + 2)
            annot = page.add_circle_annot(padded)
        else:  # CORRECTION, IMPROVEMENT, SHORTCUT
            annot = page.add_underline_annot(rect)

        annot.set_colors(stroke=ink)
        annot.set_opacity(min(1.0, opacity + 0.05))
        annot.update()

    # ------------------------------------------------------------
    # Margin text (right / left)
    # ------------------------------------------------------------

    def _write_margin_text(
        self,
        shape: fitz.Shape,
        page: fitz.Page,
        rect: fitz.Rect,
        text: str,
        ink: tuple[float, float, float],
        angle: float,
        fontsize: float,
        opacity: float,
        side: str,
    ) -> tuple[fitz.Point, str]:
        """Write wrapped margin text to the left or right of `rect`.

        Returns the anchor point nearest the target text, used to draw
        the connecting arrow.
        """
        available_by_side = {
            "right": page.rect.x1 - _PAGE_EDGE_PAD - (rect.x1 + _MARGIN_GAP),
            "left": rect.x0 - _MARGIN_GAP - (page.rect.x0 + _PAGE_EDGE_PAD),
        }
        other_side = "left" if side == "right" else "right"
        if available_by_side[side] < _MIN_MARGIN_WIDTH:
            side = other_side
        if available_by_side[side] <= 0:
            side = max(available_by_side, key=available_by_side.__getitem__)

        width = min(available_by_side[side], _MAX_MARGIN_WIDTH)
        # Extremely narrow pages / unusually wide targets can leave less than
        # one glyph of margin. Scale just enough that character wrapping can
        # still keep every emitted line within the real margin.
        widest_glyph = max(
            (self._measure_font.text_length(char, fontsize=fontsize) for char in text),
            default=0.0,
        )
        if 0 < width < widest_glyph:
            fontsize *= width / widest_glyph

        lines = self._wrap_text(text, width, fontsize)
        line_gap = fontsize * 1.3

        # There must be room for the font ascent above the first baseline and
        # for the final baseline itself. Drop trailing lines when a block is
        # taller than the page; the remaining lines retain their order.
        usable_height = max(0.0, page.rect.height - fontsize)
        max_lines = max(1, math.floor(usable_height / line_gap) + 1)
        lines = lines[:max_lines]

        # Vertically center the note block on the target passage.
        block_height = line_gap * len(lines)
        start_y = rect.y0 + (rect.height / 2) - (block_height / 2) + fontsize
        first_baseline = page.rect.y0 + fontsize
        last_start = page.rect.y1 - line_gap * (len(lines) - 1)
        start_y = min(max(start_y, first_baseline), last_start)

        if side == "right":
            x = rect.x1 + _MARGIN_GAP
        else:
            x = max(page.rect.x0 + _PAGE_EDGE_PAD, rect.x0 - _MARGIN_GAP - width)

        for i, line in enumerate(lines):
            point = fitz.Point(x, start_y + i * line_gap)
            shape.insert_text(
                point,
                line,
                fontsize=fontsize,
                fontname=self._fontname,
                fontfile=self._fontfile,
                color=ink,
                stroke_opacity=opacity,
                fill_opacity=opacity,
                morph=(point, fitz.Matrix(angle)),
            )

        anchor_x = x if side == "right" else x + width
        anchor_y = rect.y0 + rect.height / 2
        return fitz.Point(anchor_x, anchor_y), side

    # ------------------------------------------------------------
    # Inline / between-lines text
    # ------------------------------------------------------------

    def _write_inline_text(
        self,
        shape: fitz.Shape,
        page: fitz.Page,
        rect: fitz.Rect,
        text: str,
        ink: tuple[float, float, float],
        angle: float,
        fontsize: float,
        opacity: float,
    ) -> None:
        """Squeeze a short note in right after the target text, like a
        caret insertion, falling back to the space just below it if the
        page is too narrow.
        """
        small_size = max(6.5, fontsize - 1.0)
        room_to_right = page.rect.x1 - rect.x1 - _PAGE_EDGE_PAD
        max_width = 110.0

        if room_to_right >= 30:
            width = min(room_to_right, max_width)
            point = fitz.Point(rect.x1 + 4, rect.y1 - 1)
        else:
            width = min(page.rect.width - 2 * _PAGE_EDGE_PAD, max_width)
            point = fitz.Point(rect.x0, rect.y1 + small_size + 2)

        lines = self._wrap_text(text, width, small_size)
        line_gap = small_size * 1.25
        for i, line in enumerate(lines[:2]):  # keep inline notes terse
            line_point = fitz.Point(point.x, point.y + i * line_gap)
            shape.insert_text(
                line_point,
                line,
                fontsize=small_size,
                fontname=self._fontname,
                fontfile=self._fontfile,
                color=ink,
                stroke_opacity=opacity,
                fill_opacity=opacity,
                morph=(line_point, fitz.Matrix(angle)),
            )

    def _write_between_lines_text(
        self,
        shape: fitz.Shape,
        rect: fitz.Rect,
        text: str,
        ink: tuple[float, float, float],
        angle: float,
        fontsize: float,
        opacity: float,
    ) -> None:
        """Write a short note squeezed into the interline gap directly
        above the target passage, in a small, tight hand.
        """
        small_size = max(6.0, fontsize - 1.5)
        width = max(rect.width, _MIN_MARGIN_WIDTH)
        lines = self._wrap_text(text, width, small_size)
        # Only the top line or two actually fit between two lines of body
        # text without colliding with the line above.
        line_gap = small_size * 1.05
        last_baseline = rect.y0 - 2
        available_lines = max(
            0, math.floor((last_baseline - small_size) / line_gap) + 1
        )
        lines = lines[: min(2, available_lines)]
        if not lines:
            return
        top_y = last_baseline - line_gap * (len(lines) - 1)

        for i, line in enumerate(lines):
            point = fitz.Point(rect.x0, top_y + i * line_gap)
            shape.insert_text(
                point,
                line,
                fontsize=small_size,
                fontname=self._fontname,
                fontfile=self._fontfile,
                color=ink,
                stroke_opacity=opacity,
                fill_opacity=opacity,
                morph=(point, fitz.Matrix(angle)),
            )

    def _write_replacement_above(
        self,
        shape: fitz.Shape,
        rect: fitz.Rect,
        replacement_text: str,
        ink: tuple[float, float, float],
        angle: float,
        fontsize: float,
        opacity: float,
    ) -> None:
        """For CROSSED_OUT annotations, write the replacement text hovering
        just above the struck-through passage.
        """
        small_size = max(6.5, fontsize - 0.5)
        width = max(rect.width, _MIN_MARGIN_WIDTH)
        lines = self._wrap_text(replacement_text, width, small_size)
        line_gap = small_size * 1.1
        last_baseline = rect.y0 - 3
        available_lines = max(
            0, math.floor((last_baseline - small_size) / line_gap) + 1
        )
        lines = lines[: min(2, available_lines)]
        if not lines:
            return
        top_y = last_baseline - line_gap * (len(lines) - 1)

        for i, line in enumerate(lines):
            point = fitz.Point(rect.x0, top_y + i * line_gap)
            shape.insert_text(
                point,
                line,
                fontsize=small_size,
                fontname=self._fontname,
                fontfile=self._fontfile,
                color=ink,
                stroke_opacity=opacity,
                fill_opacity=opacity,
                morph=(point, fitz.Matrix(angle)),
            )

    # ------------------------------------------------------------
    # Connector arrow
    # ------------------------------------------------------------

    def _draw_connector(
        self,
        shape: fitz.Shape,
        rect: fitz.Rect,
        anchor: fitz.Point,
        ink: tuple[float, float, float],
        opacity: float,
        side: str,
    ) -> None:
        """Draw a small, slightly bowed hand-drawn arrow from the margin
        note's anchor point to the edge of the target passage.
        """
        end = fitz.Point(rect.x0, rect.y0 + rect.height / 2) if side == "left" else fitz.Point(
            rect.x1, rect.y0 + rect.height / 2
        )
        # Swap so the arrow always starts at the margin and ends at the text.
        start = anchor
        bow = -4 if side == "right" else 4
        mid = fitz.Point((start.x + end.x) / 2, (start.y + end.y) / 2 + bow)

        shape.draw_curve(start, mid, end)
        shape.finish(
            color=ink, width=0.6, closePath=False, stroke_opacity=opacity * 0.75
        )

        # Small arrowhead at the text end.
        dx, dy = end.x - mid.x, end.y - mid.y
        length = math.hypot(dx, dy) or 1.0
        ux, uy = dx / length, dy / length
        px, py = -uy, ux
        head_len = 4.0
        head_spread = 2.0
        tip = end
        wing1 = fitz.Point(
            tip.x - ux * head_len + px * head_spread, tip.y - uy * head_len + py * head_spread
        )
        wing2 = fitz.Point(
            tip.x - ux * head_len - px * head_spread, tip.y - uy * head_len - py * head_spread
        )
        shape.draw_line(tip, wing1)
        shape.draw_line(tip, wing2)
        shape.finish(color=ink, width=0.6, closePath=False, stroke_opacity=opacity * 0.75)

    # ------------------------------------------------------------
    # Small helpers
    # ------------------------------------------------------------

    def _ink_color(self, annotation_type: AnnotationType) -> tuple[float, float, float]:
        return _INK_PALETTE.get(annotation_type, _DEFAULT_INK)

    @staticmethod
    def _opacity(confidence: float) -> float:
        """Map confidence [0, 1] to an ink opacity, so uncertain notes
        look lighter/fainter and confident ones look bold.
        """
        confidence = max(0.0, min(1.0, confidence))
        return 0.55 + 0.4 * confidence

    def _organic_angle(self, seed_text: str) -> float:
        """Deterministic-but-varied rotation angle in degrees, roughly
        1-3 degrees in either direction, so repeated renders of the same
        annotation look stable (useful for tests/diffs) while different
        notes on a page don't all lean the same way.
        """
        rnd = random.Random(self._seed if self._seed is not None else seed_text)
        magnitude = rnd.uniform(1.0, 3.0)
        sign = rnd.choice((-1, 1))
        return magnitude * sign

    def _wrap_text(self, text: str, max_width: float, fontsize: float) -> list[str]:
        """Greedy word-wrap `text` to fit within `max_width` points at
        `fontsize`, using the resolved handwriting font's real metrics
        (or Helvetica's, as a stand-in for Helvetica-Oblique).
        """
        words = text.split()
        if not words:
            return [""]

        def split_word(word: str) -> list[str]:
            chunks: list[str] = []
            current_chunk = ""
            for char in word:
                candidate = current_chunk + char
                if (
                    current_chunk
                    and self._measure_font.text_length(candidate, fontsize=fontsize)
                    > max_width
                ):
                    chunks.append(current_chunk)
                    current_chunk = char
                else:
                    current_chunk = candidate
            if current_chunk:
                chunks.append(current_chunk)
            return chunks

        wrapped_words = [chunk for word in words for chunk in split_word(word)]
        lines: list[str] = []
        current = wrapped_words[0]
        for word in wrapped_words[1:]:
            candidate = f"{current} {word}"
            if self._measure_font.text_length(candidate, fontsize=fontsize) <= max_width:
                current = candidate
            else:
                lines.append(current)
                current = word
        lines.append(current)
        return lines

    # ------------------------------------------------------------
    # Convenience: flatten an AnnotationPlan
    # ------------------------------------------------------------

    @staticmethod
    def annotations_from_plan(plan: AnnotationPlan) -> list[Annotation]:
        """Flatten an `AnnotationPlan` (grouped by `AnnotatedPage`) into a
        single ordered list of `Annotation` objects suitable for
        `render_annotations`.

        Guards against an `Annotation.page` that disagrees with the
        `AnnotatedPage.page_number` it lives under by trusting the
        latter, since that's the grouping the plan was assembled with.
        """
        flattened: list[Annotation] = []
        page: AnnotatedPage
        for page in plan.pages:
            for annotation in page.annotations:
                if annotation.page != page.page_number:
                    annotation = annotation.model_copy(update={"page": page.page_number})
                flattened.append(annotation)
        return flattened


def layout_page_annotations(
    page: fitz.Page,
    requests: Sequence[NoteRequest],
    body_occupancy: Sequence[fitz.Rect],
    measurer: NoteMeasurer,
    config: LayoutConfig | None = None,
) -> LayoutResult:
    """Bridge fitz page geometry to the surface-neutral layout engine.

    This is the sole P2-T7 modification to document_processor.py.
    It converts fitz.Page.rect and fitz.Rect body occupancy into SurfaceRect
    values, then delegates to run_layout. Does NOT modify add_margin_note.

    Args:
        page: A fitz.Page; its .rect provides the surface bounds.
        requests: NoteRequest list (annotation_ids, anchors, placements, etc.).
        body_occupancy: fitz.Rect list of regions that contain body text.
        measurer: NoteMeasurer protocol implementation.
        config: LayoutConfig; defaults to LayoutConfig() if None.
    """
    from halfblood.layout.anchors import surf_rect_from_fitz
    from halfblood.layout.engine import run_layout

    cfg = config if config is not None else LayoutConfig()
    page_rect = surf_rect_from_fitz(page.rect)
    body_surf = [surf_rect_from_fitz(rect) for rect in body_occupancy]
    return run_layout(requests, page_rect, body_surf, measurer, config=cfg)
