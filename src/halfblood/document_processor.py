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
import random
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence

import fitz  # PyMuPDF

from halfblood.models import (
    Annotation,
    AnnotatedPage,
    AnnotationPlan,
    AnnotationType,
)

logger = logging.getLogger(__name__)


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

    def __init__(
        self,
        font_path: Optional[str] = None,
        project_root: Optional[str] = None,
        seed: Optional[int] = None,
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
        self, explicit_font_path: Optional[str]
    ) -> tuple[Optional[str], str, bool]:
        """Locate a handwriting font on disk.

        Resolution order:
            1. ``explicit_font_path`` if it exists.
            2. ``<project_root>/fonts/CaveatBrush-Regular.ttf``
            3. Any ``<project_root>/fonts/*aveat*.tt[fc]`` (Caveat / Caveat Brush,
               any weight/case).
            4. A short list of common system font install locations.
            5. Fallback: PDF standard font ``Helvetica-Oblique`` (no file
               needed). A warning is logged with download instructions.

        Returns:
            (fontfile_path_or_None, fontname_alias, is_custom_font)
        """
        candidates: list[Path] = []

        if explicit_font_path:
            candidates.append(Path(explicit_font_path))

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

        logger.warning(
            "No handwriting font found (looked for %s and system Caveat installs). "
            "Falling back to Helvetica-Oblique, which will look typeset rather "
            "than handwritten. To fix this, download 'Caveat Brush' from "
            "https://fonts.google.com/specimen/Caveat+Brush and save it as "
            "%s",
            fonts_dir / "CaveatBrush-Regular.ttf",
            fonts_dir / "CaveatBrush-Regular.ttf",
        )
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
        text = text.strip()
        text = re.sub(r"[‘’]", "'", text)
        text = re.sub(r"[“”]", '"', text)
        text = re.sub(r"[–—]", "-", text)
        text = re.sub(r"\s+", " ", text)
        return text

    @staticmethod
    def _union_rects(rects: Sequence[fitz.Rect]) -> fitz.Rect:
        union = fitz.Rect(rects[0])
        for rect in rects[1:]:
            union |= rect
        return union

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

    def find_text_rect(self, page: fitz.Page, text: str) -> Optional[fitz.Rect]:
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

        for variant in self._search_variants(normalized):
            hits = page.search_for(variant)
            if hits:
                if len(variant) < len(normalized):
                    logger.debug(
                        "Exact match for %r not found; used fallback anchor %r",
                        text,
                        variant,
                    )
                return self._union_rects(hits)

        logger.warning("Could not locate target_text %r on page", text)
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

    def add_margin_note(
        self,
        page: fitz.Page,
        rect: Optional[fitz.Rect],
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
            anchor = self._write_margin_text(
                shape, page, rect, text, ink, angle, fontsize, opacity, side="right"
            )
            self._draw_connector(shape, rect, anchor, ink, opacity, side="right")
        elif position == "margin_left":
            anchor = self._write_margin_text(
                shape, page, rect, text, ink, angle, fontsize, opacity, side="left"
            )
            self._draw_connector(shape, rect, anchor, ink, opacity, side="left")
        elif position == "inline":
            self._write_inline_text(shape, page, rect, text, ink, angle, fontsize, opacity)
        else:  # between_lines
            self._write_between_lines_text(shape, rect, text, ink, angle, fontsize, opacity)

        if annotation_type == AnnotationType.CROSSED_OUT:
            self._write_replacement_above(shape, rect, text, ink, angle, fontsize, opacity)

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
        shape: "fitz.Shape",
        page: fitz.Page,
        rect: fitz.Rect,
        text: str,
        ink: tuple[float, float, float],
        angle: float,
        fontsize: float,
        opacity: float,
        side: str,
    ) -> fitz.Point:
        """Write wrapped margin text to the left or right of `rect`.

        Returns the anchor point nearest the target text, used to draw
        the connecting arrow.
        """
        if side == "right":
            available = page.rect.x1 - rect.x1 - _MARGIN_GAP - _PAGE_EDGE_PAD
        else:
            available = rect.x0 - page.rect.x0 - _MARGIN_GAP - _PAGE_EDGE_PAD

        width = max(_MIN_MARGIN_WIDTH, min(available, _MAX_MARGIN_WIDTH))
        lines = self._wrap_text(text, width, fontsize)
        line_gap = fontsize * 1.3

        # Vertically center the note block on the target passage.
        block_height = line_gap * len(lines)
        start_y = rect.y0 + (rect.height / 2) - (block_height / 2) + fontsize

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
        return fitz.Point(anchor_x, anchor_y)

    # ------------------------------------------------------------
    # Inline / between-lines text
    # ------------------------------------------------------------

    def _write_inline_text(
        self,
        shape: "fitz.Shape",
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
        shape: "fitz.Shape",
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
        lines = lines[:2]
        line_gap = small_size * 1.05
        top_y = max(small_size, rect.y0 - 2 - line_gap * (len(lines) - 1))

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
        shape: "fitz.Shape",
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
        lines = self._wrap_text(replacement_text, width, small_size)[:2]
        line_gap = small_size * 1.1
        top_y = max(small_size, rect.y0 - 3 - line_gap * (len(lines) - 1))

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
        shape: "fitz.Shape",
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

        lines: list[str] = []
        current = words[0]
        for word in words[1:]:
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
