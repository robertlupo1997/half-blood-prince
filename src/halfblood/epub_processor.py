"""EPUB processing for the Half-Blood Prince annotator.

This module mirrors :class:`halfblood.document_processor.DocumentProcessor`'s
public interface (``load`` / ``render_annotations``) but operates on EPUB
files instead of PDFs. Parsing and container rewriting is done with
`EbookLib <https://github.com/aerkalov/ebooklib>`_; each chapter's XHTML is
manipulated with `BeautifulSoup <https://www.crummy.com/software/BeautifulSoup/>`_.

EPUBs have no fixed page geometry -- content reflows to whatever the
reading device decides. So this module treats each *spine item* (roughly:
one chapter / section file) as one "page": :attr:`PageContent.page_number`
is the 1-indexed position of that document within the book's reading
order, and callers are expected to populate ``Annotation.page`` /
``AnnotatedPage.page_number`` with that same chapter index -- exactly as
they would with a PDF page number.

Because e-reader apps vary wildly in their CSS support (many ignore
``float``, some ignore ``position`` entirely), annotations are rendered
as linked HTML/CSS rather than absolutely positioned margin notes:

* The target passage is wrapped in a ``<span class="hbp-target ...">``
  that gets an ink-colored underline/highlight/strikethrough depending on
  its mark intent.
* A linked noteref follows the target, while the Prince's commentary is
  appended to a per-block ``hbp-note-cluster`` immediately after the owning
  block. EPUB 3 notes use semantic footnote asides; EPUB 2 notes use linked
  divs. Existing note styling still supplies the cursive "handwriting",
  rotation, ink color, and opacity.

Font note
---------
Unlike the PDF pipeline, this module does not embed a font file -- EPUB
readers apply their own fonts, and ``font-family: cursive`` (with a few
named fallbacks) is used as a hint. Readers that honor embedded fonts
and want a closer match to the PDF's "Caveat Brush" look can add that
family to the CSS fallback list in :data:`_ANNOTATION_CSS`.
"""

from __future__ import annotations

import logging
import posixpath
import random
import warnings
from collections.abc import Sequence
from typing import Any, cast

import ebooklib
from bs4 import BeautifulSoup, Comment, NavigableString, Tag, XMLParsedAsHTMLWarning
from ebooklib import epub

from halfblood.document_processor import PageContent
from halfblood.documents import (
    AmbiguousResult,
    CrossNodeMatch,
    CrossNodeSegment,
    MatchResult,
    NormalizedText,
    iter_inline_runs,
    locate_across_nodes,
    normalize,
    score_candidates,
)
from halfblood.documents.epub import _has_overlapping_exact, _owner_map
from halfblood.models import Annotation, AnnotationPlan, AnnotationType
from halfblood.models.annotations import Annotation as V2Annotation
from halfblood.models.annotations import MarkIntent, TargetSelector
from halfblood.models.documents import _MARK_INTENTS
from halfblood.models.documents import AnnotationPlan as V2AnnotationPlan
from halfblood.models.rendering import DegradationFlag, RenderReport, SkipReason, SkipRecord

logger = logging.getLogger(__name__)


# Chapter XHTML is technically XML, but real-world EPUBs frequently bend
# the rules (unescaped entities, unclosed void elements, etc.). We
# deliberately parse with BeautifulSoup's lenient HTML parser rather than
# an XML parser so a slightly malformed chapter doesn't blow up the whole
# render; this is the expected, intentional tradeoff, so silence the
# warning bs4 raises about it.
warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)


# --------------------------------------------------------------------------
# Styling constants
# --------------------------------------------------------------------------

#: "Old ink" palette per annotation type, as (r, g, b) floats in [0, 1].
#: Kept in sync with ``halfblood.document_processor._INK_PALETTE`` so the
#: EPUB and PDF outputs read as the same annotator's handwriting.
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

#: Small glyph prefixed to certain note types so the intent reads at a
#: glance even before the reader's eye reaches the styled text.
_NOTE_PREFIX_BY_TYPE: dict[AnnotationType, str] = {
    AnnotationType.WARNING: "⚠ ",  # warning sign
    AnnotationType.CROSSED_OUT: "→ ",  # right arrow, "replace with..."
}

#: EPUBs are reflowable and have no fixed page size. These nominal
#: dimensions exist only so `PageContent` (shared with the PDF pipeline)
#: has *something* sane in `width` / `height`; nothing in this module
#: relies on them for layout.
_NOMINAL_PAGE_WIDTH = 600.0
_NOMINAL_PAGE_HEIGHT = 800.0

_ANNOTATION_STYLESHEET_PATH = "style/hbp-annotations.css"

_BLOCK_TAGS = (
    "p",
    "div",
    "section",
    "article",
    "aside",
    "header",
    "footer",
    "nav",
    "figure",
    "figcaption",
    "blockquote",
    "pre",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
)

_EPUB_NAMESPACE = "http://www.idpf.org/2007/ops"

_ANNOTATION_CSS = """
.hbp-target {
    position: relative;
}
.hbp-mark-underline {
    border-bottom: 2px solid currentColor;
}
.hbp-mark-circle {
    border: 1.5px solid currentColor;
    border-radius: 0.6em;
    padding: 0 0.15em;
    -webkit-box-decoration-break: clone;
    box-decoration-break: clone;
}
.hbp-mark-strike {
    text-decoration: line-through;
    text-decoration-color: currentColor;
    text-decoration-thickness: 2px;
}
.hbp-mark-highlight {
    background: rgba(216, 62, 27, 0.20);
}
.hbp-mark-caret::after {
    content: "\\2038";
    font-weight: bold;
}
.hbp-target-warning {
    font-weight: bold;
}

.hbp-note {
    font-family: "Caveat", "Bradley Hand", "Segoe Print", "Comic Sans MS", cursive;
    display: inline-block;
    margin: 0 0.4em;
    line-height: 1.2;
    white-space: normal;
    vertical-align: baseline;
}
@supports (float: right) {
    .hbp-note {
        float: right;
        clear: right;
        width: 9em;
        margin: 0.2em 0 0.6em 0.9em;
        text-align: left;
    }
}
.hbp-note-correction {
    font-size: 1.05em;
}
.hbp-note-warning {
    font-weight: bold;
    font-size: 1.1em;
}
.hbp-note-crossed_out {
    font-style: normal;
}
.hbp-note-doodle_note {
    font-size: 0.85em;
    font-style: italic;
}
.hbp-note-improvement,
.hbp-note-insight,
.hbp-note-invention,
.hbp-note-shortcut {
    font-size: 1em;
}
""".strip()


def _rgb_to_hex(rgb: tuple[float, float, float]) -> str:
    """Convert an (r, g, b) triple of floats in [0, 1] to a ``#rrggbb`` string."""
    r, g, b = (max(0.0, min(1.0, c)) for c in rgb)
    return f"#{round(r * 255):02x}{round(g * 255):02x}{round(b * 255):02x}"


class EpubProcessor:
    """Extracts text from EPUBs and renders Half-Blood-Prince-style
    handwritten margin annotations back into them as styled HTML.

    Mirrors the public shape of `halfblood.document_processor.DocumentProcessor`
    (`load` / `render_annotations`) so the CLI can treat PDFs and EPUBs
    interchangeably.
    """

    def __init__(self, seed: int | None = None) -> None:
        """
        Args:
            seed: Optional seed for the "organic" rotation jitter applied
                to each note, so renders are reproducible in tests.
                Defaults to a per-annotation deterministic seed derived
                from its text (same behavior as `DocumentProcessor`).
        """
        self._seed = seed

    # ----------------------------------------------------------------
    # Extraction
    # ----------------------------------------------------------------

    def load(self, path: str) -> list[PageContent]:
        """Extract plain text from every chapter of an EPUB.

        Args:
            path: Path to the source EPUB.

        Returns:
            One `PageContent` per spine document, 1-indexed via
            `page_number` in reading order. `width` / `height` are
            nominal placeholders (EPUBs are reflowable).
        """
        book = epub.read_epub(path)
        pages: list[PageContent] = []
        for index, item in self._iter_spine_documents(book):
            text = self._html_to_text(item.get_content())
            pages.append(
                PageContent(
                    page_number=index,
                    text=text,
                    width=_NOMINAL_PAGE_WIDTH,
                    height=_NOMINAL_PAGE_HEIGHT,
                )
            )
        return pages

    @staticmethod
    def _iter_spine_documents(book: epub.EpubBook) -> list[tuple[int, epub.EpubHtml]]:
        """Walk `book.spine` in reading order, returning `(index, item)`
        pairs for each document item (1-indexed).

        Skips anything in the spine that isn't an XHTML document (e.g. a
        stray NCX ref), and skips items marked ``linear="no"`` -- the
        standard EPUB3 convention for excluding supplementary content
        (most commonly the generated navigation/TOC document) from the
        book's linear reading order. Without this, a nav document placed
        in the spine would count as "chapter 1".
        """
        docs: list[tuple[int, epub.EpubHtml]] = []
        index = 0
        for idref, linear in book.spine:
            if linear == "no":
                continue
            item = book.get_item_with_id(idref)
            if item is None or item.get_type() != ebooklib.ITEM_DOCUMENT:
                continue
            index += 1
            docs.append((index, item))
        return docs

    @staticmethod
    def _html_to_text(html: bytes | str) -> str:
        """Strip tags from a chapter's HTML, returning clean, one-line-per-block text."""
        soup = BeautifulSoup(html, "lxml")
        for tag in soup(["script", "style"]):
            tag.decompose()
        raw = soup.get_text(separator="\n")
        lines = [line.strip() for line in raw.splitlines()]
        lines = [line for line in lines if line]
        return "\n".join(lines)

    # ----------------------------------------------------------------
    # Locating annotation targets
    # ----------------------------------------------------------------

    @staticmethod
    def _normalize_search_text(text: str) -> str:
        """Collapse whitespace/newlines and normalize "smart" punctuation
        so LLM-generated `target_text` matches the chapter's rendered text.
        """
        return normalize(text).strip()

    @staticmethod
    def _search_variants(text: str) -> list[str]:
        """Generate progressively looser variants of `text`, since LLM
        output rarely matches the source byte-for-byte (same strategy as
        `DocumentProcessor._search_variants`).
        """
        words = text.split(" ")
        variants: list[str] = [text]
        if len(words) > 8:
            variants.append(" ".join(words[:8]))
        if len(words) > 5:
            variants.append(" ".join(words[:5]))
        if len(words) > 3:
            variants.append(" ".join(words[:3]))
        longest = max((w.strip(".,;:!?\"'()") for w in words), key=len, default="")
        if len(longest) >= 4:
            variants.append(longest)
        seen: set[str] = set()
        unique: list[str] = []
        for variant in variants:
            if variant and variant not in seen:
                seen.add(variant)
                unique.append(variant)
        return unique

    @staticmethod
    def _normalize_with_map(raw: str) -> tuple[str, list[int]]:
        """Fold smart punctuation and collapse whitespace runs in `raw`.

        Returns the normalized string plus a list mapping each normalized-
        string index back to its original index in `raw`. Every punctuation
        replacement is one character, so the map continues to identify the
        raw slice exactly and preserves the book's original typography.
        """
        out_chars: list[str] = []
        index_map: list[int] = []
        i = 0
        n = len(raw)
        while i < n:
            ch = raw[i]
            if ch.isspace():
                out_chars.append(" ")
                index_map.append(i)
                while i < n and raw[i].isspace():
                    i += 1
            else:
                if ch in "‘’":
                    ch = "'"
                elif ch in "“”":
                    ch = '"'
                elif ch in "–—":
                    ch = "-"
                out_chars.append(ch)
                index_map.append(i)
                i += 1
        return "".join(out_chars), index_map

    @staticmethod
    def _is_own_markup(node: NavigableString) -> bool:
        """True if `node` lives inside HTML this module already inserted
        (an `hbp-*` span), so a later annotation's search doesn't
        accidentally match text from an earlier note.
        """
        for ancestor in node.parents:
            if isinstance(ancestor, Tag):
                classes = cast(list[str], ancestor.get("class") or [])  # HTML parser always returns list for multi-valued attrs
                if any(c.startswith("hbp-") for c in classes):
                    return True
        return False

    def _locate_text(
        self, soup: BeautifulSoup, target_text: str
    ) -> tuple[NavigableString, int, int] | None:
        """Locate `target_text` among `soup`'s text nodes.

        Tries an exact (whitespace-normalized) match first, then falls
        back to shorter prefixes / the longest single word, mirroring
        `DocumentProcessor.find_text_rect`. The match must lie entirely
        within a single text node -- passages split across nested tags
        (e.g. italics mid-sentence) won't be found; this is a deliberate
        simplification, and such misses are logged and skipped rather
        than crashing the render.

        Returns:
            `(node, start, end)` -- the `NavigableString` containing the
            match and the `[start, end)` character offsets of the match
            within that node's raw text -- or `None` if nothing matched.
        """
        normalized_target = self._normalize_search_text(target_text)
        if not normalized_target:
            return None

        candidates = [
            node
            for node in soup.find_all(string=True)
            if (
                not isinstance(node, Comment)
                and node.parent is not None
                and node.parent.name not in ("script", "style")
                and node.strip()
                and not self._is_own_markup(node)
            )
        ]

        for variant in self._search_variants(normalized_target):
            for node in candidates:
                raw = str(node)
                normalized_node, index_map = self._normalize_with_map(raw)
                pos = normalized_node.find(variant)
                if pos == -1:
                    pos = normalized_node.lower().find(variant.lower())
                if pos == -1:
                    continue
                if len(variant) < len(normalized_target):
                    logger.debug(
                        "Exact match for %r not found; used fallback anchor %r",
                        target_text,
                        variant,
                    )
                start = index_map[pos]
                end = index_map[pos + len(variant) - 1] + 1
                return node, start, end

        logger.warning("Could not locate target_text %r in chapter", target_text)
        return None

    # ----------------------------------------------------------------
    # Rendering
    # ----------------------------------------------------------------

    @staticmethod
    def _epub_miss_reason(root: Tag, selector: TargetSelector) -> SkipReason:
        """Classify a ``locate_across_nodes`` miss as ambiguous or missing.

        Inspects every inline run to distinguish between a target that truly does
        not appear in the chapter and one that appears multiple times without
        enough context to pick a single occurrence.
        """
        tier0_hit_count = 0
        for run in iter_inline_runs(root):
            raw, _ = _owner_map(run)
            norm = NormalizedText(raw)
            if _has_overlapping_exact(norm.text, selector.normalized_exact):
                return SkipReason.AMBIGUOUS_TARGET
            outcome = score_candidates(selector, norm)
            if isinstance(outcome, AmbiguousResult):
                if outcome.candidates and outcome.candidates[0].exactness_tier == 0:
                    return SkipReason.AMBIGUOUS_TARGET
            elif isinstance(outcome, MatchResult) and outcome.candidate.exactness_tier == 0:
                tier0_hit_count += 1
        return (
            SkipReason.AMBIGUOUS_TARGET
            if tier0_hit_count > 1
            else SkipReason.MISSING_TARGET
        )

    @staticmethod
    def _epub_spans_overlap(match_a: CrossNodeMatch, match_b: CrossNodeMatch) -> bool:
        """Return whether two matches overlap within any shared DOM text node."""
        for seg_a in match_a.segments:
            for seg_b in match_b.segments:
                if (
                    seg_a.node is seg_b.node
                    and max(seg_a.start, seg_b.start) < min(seg_a.end, seg_b.end)
                ):
                    return True
        return False

    def render_plan(
        self,
        input_path: str,
        plan: V2AnnotationPlan,
        output_path: str,
    ) -> RenderReport:
        """Render a V2 AnnotationPlan into an EPUB using the shared cross-node path.

        Routing:
          1. Each annotation's ``TargetSelector`` is resolved via
             ``locate_across_nodes`` before any DOM mutation (pre-resolve pass).
          2. ``None`` returns are classified as AMBIGUOUS_TARGET or MISSING_TARGET
             via ``_epub_miss_reason``.
          3. Resolved pairs whose char intervals overlap on any shared DOM node are
             classified OVERLAPPING_TARGET (the later annotation in plan order).
          4. Surviving annotations are applied sequentially with fresh
             ``locate_across_nodes`` calls (re-resolve after each DOM mutation),
             so non-overlapping annotations that share a text node each find their
             target correctly after the first wrapping splits the node.
          5. ``DegradationFlag.EPUB_NO_TARGET_GEOMETRY`` is always set: reflowable
             EPUB content has no fixed geometry.

        Args:
            input_path: Source EPUB path.
            plan: A validated V2 AnnotationPlan (halfblood.models.documents.AnnotationPlan).
            output_path: Destination EPUB path (created or overwritten).

        Returns:
            RenderReport with a complete rendered/skipped partition covering every
            annotation in the plan.
        """
        book = epub.read_epub(input_path)
        self._ensure_toc_uids(book.toc)
        is_epub3 = str(book.version).startswith("3")
        spine_docs: dict[int, epub.EpubHtml] = dict(self._iter_spine_documents(book))

        rendered_ids: list[str] = []
        skip_records: list[SkipRecord] = []
        stylesheet: epub.EpubItem | None = None

        for unit in plan.units:
            annotations: list[V2Annotation] = unit.annotations
            item = spine_docs.get(unit.ordinal)
            if item is None:
                for ann in annotations:
                    skip_records.append(
                        SkipRecord(annotation_id=ann.id, reason=SkipReason.OUT_OF_RANGE_PAGE)
                    )
                continue

            soup = BeautifulSoup(item.get_content(), "lxml")
            chapter_root: Tag = soup.body or soup

            # Phase 1: pre-resolve all annotations on the initial DOM.
            pre_resolved: list[CrossNodeMatch | None] = []
            for ann in annotations:
                pre_resolved.append(locate_across_nodes(chapter_root, ann.target))

            # Phase 2: classify unresolved annotations.
            skip_reason_for: dict[int, SkipReason] = {}
            for idx, (ann, match) in enumerate(
                zip(annotations, pre_resolved, strict=True)
            ):
                if match is None:
                    skip_reason_for[idx] = self._epub_miss_reason(chapter_root, ann.target)

            # Phase 3: mark the later annotation in each overlapping pair.
            resolved_indices: list[int] = [
                i for i, match in enumerate(pre_resolved) if match is not None
            ]
            overlapping: set[int] = set()
            for i, idx_i in enumerate(resolved_indices):
                if idx_i in overlapping:
                    continue
                for idx_j in resolved_indices[i + 1 :]:
                    if idx_j in overlapping:
                        continue
                    match_i = pre_resolved[idx_i]
                    match_j = pre_resolved[idx_j]
                    assert match_i is not None
                    assert match_j is not None
                    if self._epub_spans_overlap(match_i, match_j):
                        overlapping.add(idx_j)

            for idx in overlapping:
                skip_reason_for[idx] = SkipReason.OVERLAPPING_TARGET

            # Phase 4: re-resolve and apply sequentially on the mutated DOM.
            chapter_rendered = 0
            for idx, ann in enumerate(annotations):
                if idx in skip_reason_for:
                    skip_records.append(
                        SkipRecord(annotation_id=ann.id, reason=skip_reason_for[idx])
                    )
                    continue

                fresh_match = locate_across_nodes(chapter_root, ann.target)
                if fresh_match is None:
                    skip_records.append(
                        SkipRecord(annotation_id=ann.id, reason=SkipReason.MISSING_TARGET)
                    )
                    continue

                note_number = chapter_rendered + 1
                self.wrap_cross_node_segments(
                    soup,
                    fresh_match.segments,
                    ann,
                    annotation_id=ann.id,
                    note_number=note_number,
                    is_epub3=is_epub3,
                )
                rendered_ids.append(ann.id)
                chapter_rendered += 1

            item.set_content(str(soup).encode("utf-8"))
            if chapter_rendered:
                if stylesheet is None:
                    stylesheet = self._ensure_annotation_stylesheet(book)
                self._link_annotation_stylesheet(item, stylesheet)

        logger.info(
            "render_plan: rendered %s, skipped %s",
            len(rendered_ids),
            len(skip_records),
        )
        # EbookLib treats every element carrying both ``epub:type`` and ``id``
        # as a page-break marker when regenerating the navigation document.
        # Semantic footnotes therefore become a bogus page list unless that
        # optional regeneration is disabled.
        write_options = {"epub3_pages": False} if rendered_ids and is_epub3 else None
        epub.write_epub(output_path, book, write_options)
        return RenderReport(
            rendered=tuple(rendered_ids),
            skipped=tuple(skip_records),
            degradation_flags=(DegradationFlag.EPUB_NO_TARGET_GEOMETRY,),
        )

    def render_annotations(
        self, input_path: str, annotations: list[Annotation], output_path: str
    ) -> None:
        """Render a full set of annotations into an EPUB and save the result.

        Args:
            input_path: Source EPUB path.
            annotations: Annotations to render. `Annotation.page` is
                1-indexed and refers to the spine-document ("chapter")
                index, matching `PageContent.page_number` from `load`.
            output_path: Where to write the annotated EPUB.
        """
        book = epub.read_epub(input_path)
        self._ensure_toc_uids(book.toc)
        is_epub3 = str(book.version).startswith("3")
        spine_docs = dict(self._iter_spine_documents(book))

        by_page: dict[int, list[Annotation]] = {}
        for annotation in annotations:
            by_page.setdefault(annotation.page, []).append(annotation)

        rendered = 0
        skipped = 0
        stylesheet: epub.EpubItem | None = None
        for page_number in sorted(by_page):
            item = spine_docs.get(page_number)
            if item is None:
                logger.warning(
                    "Annotation references chapter %s but the EPUB spine only "
                    "has %s document(s); skipping",
                    page_number,
                    len(spine_docs),
                )
                skipped += len(by_page[page_number])
                continue

            soup = BeautifulSoup(item.get_content(), "lxml")
            chapter_rendered = 0

            for annotation in by_page[page_number]:
                located = self._locate_text(soup, annotation.target_text)
                if located is None:
                    skipped += 1
                    continue
                node, start, end = located
                note_number = chapter_rendered + 1
                self._wrap_and_annotate(
                    soup,
                    node,
                    start,
                    end,
                    annotation,
                    annotation_id=f"p{page_number}-n{note_number}",
                    note_number=note_number,
                    is_epub3=is_epub3,
                )
                rendered += 1
                chapter_rendered += 1

            item.set_content(str(soup).encode("utf-8"))
            if chapter_rendered:
                if stylesheet is None:
                    stylesheet = self._ensure_annotation_stylesheet(book)
                self._link_annotation_stylesheet(item, stylesheet)

        logger.info(
            "Rendered %s annotation(s), skipped %s (target text not found or "
            "chapter out of range)",
            rendered,
            skipped,
        )
        # See ``render_plan``: semantic note ids are not pagination markers.
        write_options = {"epub3_pages": False} if rendered and is_epub3 else None
        epub.write_epub(output_path, book, write_options)

    def _ensure_toc_uids(self, toc: Any) -> None:
        """Backfill missing `uid` attributes on a book's table of contents.

        Works around an EbookLib quirk (observed in ebooklib 0.20) where
        `Link`/`Section` entries parsed back out of an EPUB's NCX can
        come back with ``uid=None`` -- which then crashes
        `ebooklib.epub.write_epub` with a ``TypeError`` deep inside its
        NCX serializer (``etree.SubElement`` refusing a `None` attribute
        value). This is unrelated to annotation rendering: it reproduces
        on a bare `read_epub` -> `write_epub` roundtrip with no
        modifications at all, so we defensively patch it up here rather
        than let a perfectly valid annotation render fail at the last
        step. `toc` is mutated in place.
        """
        counter = 0
        stack = list(toc)
        while stack:
            node = stack.pop()
            if isinstance(node, tuple):
                # (Section, children) pairs, per EbookLib's TOC structure.
                section, children = node
                if getattr(section, "uid", None) is None:
                    counter += 1
                    section.uid = f"hbp-toc-{counter}"
                stack.extend(children)
            elif getattr(node, "uid", None) is None:
                counter += 1
                node.uid = f"hbp-toc-{counter}"

    @staticmethod
    def _ensure_annotation_stylesheet(book: epub.EpubBook) -> epub.EpubItem:
        """Add the annotation CSS to the EPUB manifest once and return it."""
        existing = book.get_item_with_href(_ANNOTATION_STYLESHEET_PATH)
        if existing is not None:
            existing.content = _ANNOTATION_CSS.encode("utf-8")
            return existing

        stylesheet = epub.EpubItem(
            uid="hbp-annotation-style",
            file_name=_ANNOTATION_STYLESHEET_PATH,
            media_type="text/css",
            content=_ANNOTATION_CSS.encode("utf-8"),
        )
        book.add_item(stylesheet)
        return stylesheet

    @staticmethod
    def _link_annotation_stylesheet(
        chapter: epub.EpubHtml, stylesheet: epub.EpubItem
    ) -> None:
        """Link `stylesheet` once from a chapter using a relative EPUB path."""
        chapter_dir = posixpath.dirname(chapter.get_name()) or "."
        href = posixpath.relpath(stylesheet.get_name(), chapter_dir)
        for link in chapter.get_links():
            if link.get("rel") == "stylesheet" and link.get("href") == href:
                return
        chapter.add_link(href=href, rel="stylesheet", type="text/css")

    def _wrap_and_annotate(
        self,
        soup: BeautifulSoup,
        node: NavigableString,
        start: int,
        end: int,
        annotation: Annotation,
        *,
        annotation_id: str | None = None,
        note_number: int | None = None,
        is_epub3: bool = True,
    ) -> None:
        """Split `node` around `[start, end)`, wrap the matched slice in a
        styled `hbp-target` span, then insert a linked semantic note through
        the shared block-note helper.
        """
        raw = str(node)
        before, matched, after = raw[:start], raw[start:end], raw[end:]
        block_anchor = node.find_parent(_BLOCK_TAGS)

        type_slug = annotation.annotation_type.value
        mark_intent = self._effective_mark_intent(annotation)

        # NONE guard: a NONE intent means no visible mark on the target text.
        # Omit the hbp-mark-* class entirely rather than emitting hbp-mark-none,
        # which has no CSS rule and would leave the intent silently un-rendered.
        _mark_classes = f"hbp-target hbp-target-{type_slug}"
        if mark_intent is not MarkIntent.NONE:
            _mark_classes += f" hbp-mark-{mark_intent.value}"

        mark_tag = soup.new_tag(
            "span",
            attrs={"class": _mark_classes},
        )
        mark_tag.string = matched
        mark_tag["style"] = f"color:{self._ink_hex(annotation.annotation_type)};"

        replacements: list[NavigableString | Tag] = []
        if before:
            replacements.append(NavigableString(before))
        replacements.append(mark_tag)
        if after:
            replacements.append(NavigableString(after))

        node.replace_with(*replacements)
        resolved_number = (
            note_number if note_number is not None else self._next_note_number(soup)
        )
        resolved_id = annotation_id or f"p{annotation.page}-n{resolved_number}"
        self._insert_block_note(
            soup,
            block_anchor or mark_tag,
            mark_tag,
            annotation,
            annotation_id=resolved_id,
            note_number=resolved_number,
            is_epub3=is_epub3,
        )

    def wrap_cross_node_segments(
        self,
        soup: BeautifulSoup,
        segments: Sequence[CrossNodeSegment],
        annotation: Annotation | V2Annotation,
        *,
        annotation_id: str | None = None,
        note_number: int | None = None,
        is_epub3: bool = True,
    ) -> None:
        """Apply an optional mark and one note to ordered DOM text slices."""
        mark_intent = self._effective_mark_intent(annotation)
        last_segment = next(
            (
                segment
                for segment in reversed(segments)
                if segment.start < segment.end
                and str(segment.node)[segment.start : segment.end].strip()
            ),
            None,
        )
        if last_segment is None:
            return

        block_anchor = last_segment.node.find_parent(_BLOCK_TAGS)

        last_mark: Tag | None = None
        if mark_intent is not MarkIntent.NONE:
            last_mark = self._wrap_mark_segments(
                soup, segments, annotation, mark_intent
            )

        resolved_number = (
            note_number if note_number is not None else self._next_note_number(soup)
        )
        if annotation_id is not None:
            resolved_id = annotation_id
        elif isinstance(annotation, V2Annotation):
            resolved_id = annotation.id
        else:
            resolved_id = f"p{annotation.page}-n{resolved_number}"

        note_anchor: Tag | NavigableString = block_anchor or last_mark or last_segment.node
        noteref_anchor: Tag | NavigableString = last_mark or last_segment.node
        self._insert_block_note(
            soup,
            note_anchor,
            noteref_anchor,
            annotation,
            annotation_id=resolved_id,
            note_number=resolved_number,
            is_epub3=is_epub3,
            text_end_offset=(last_segment.end if last_mark is None else None),
        )

    def _wrap_mark_segments(
        self,
        soup: BeautifulSoup,
        segments: Sequence[CrossNodeSegment],
        annotation: Annotation | V2Annotation,
        mark_intent: MarkIntent,
    ) -> Tag | None:
        """Wrap every non-whitespace target segment with intent-aware markup."""
        type_slug = annotation.annotation_type.value
        last_mark: Tag | None = None

        for segment_index in range(len(segments) - 1, -1, -1):
            segment = segments[segment_index]
            if segment.start >= segment.end:
                continue

            raw = str(segment.node)
            before = raw[: segment.start]
            matched = raw[segment.start : segment.end]
            after = raw[segment.end :]
            if not matched.strip():
                continue

            mark_tag = soup.new_tag(
                "span",
                attrs={
                    "class": (
                        f"hbp-target hbp-target-{type_slug} "
                        f"hbp-mark-{mark_intent.value}"
                    )
                },
            )
            mark_tag.string = matched
            mark_tag["style"] = f"color:{self._ink_hex(annotation.annotation_type)};"

            replacements: list[NavigableString | Tag] = []
            if before:
                replacements.append(NavigableString(before))
            replacements.append(mark_tag)
            if after:
                replacements.append(NavigableString(after))

            segment.node.replace_with(*replacements)
            if last_mark is None:
                last_mark = mark_tag

        return last_mark

    @staticmethod
    def _next_note_number(soup: BeautifulSoup) -> int:
        """Return the next visible noteref number for a standalone chapter DOM."""
        return len(soup.select("a.hbp-noteref")) + 1

    @staticmethod
    def _outermost_enclosing_anchor(node: Tag | NavigableString) -> Tag | None:
        """Return the outermost ``a`` containing ``node``, if one exists."""
        anchors = node.find_parents("a")
        return anchors[-1] if anchors else None

    def _insert_block_note(
        self,
        soup: BeautifulSoup,
        block_anchor: Tag | NavigableString,
        noteref_anchor: Tag | NavigableString,
        annotation: Annotation | V2Annotation,
        *,
        annotation_id: str,
        note_number: int,
        is_epub3: bool,
        text_end_offset: int | None = None,
    ) -> None:
        """Insert a target-adjacent noteref and append its note to a block cluster."""
        type_slug = annotation.annotation_type.value

        noteref_attrs = {
            "class": "hbp-noteref",
            "id": f"hbp-ref-{annotation_id}",
            "href": f"#hbp-note-{annotation_id}",
        }
        if is_epub3:
            noteref_attrs["epub:type"] = "noteref"
            noteref_attrs["xmlns:epub"] = _EPUB_NAMESPACE
        noteref = soup.new_tag("a", attrs=noteref_attrs)
        noteref.string = str(note_number)

        enclosing_anchor = self._outermost_enclosing_anchor(noteref_anchor)
        if enclosing_anchor is not None:
            enclosing_anchor.insert_after(noteref)
        elif text_end_offset is None:
            noteref_anchor.insert_after(noteref)
        else:
            raw = str(noteref_anchor)
            before = raw[:text_end_offset]
            after = raw[text_end_offset:]
            replacements: list[NavigableString | Tag] = []
            if before:
                replacements.append(NavigableString(before))
            replacements.append(noteref)
            if after:
                replacements.append(NavigableString(after))
            noteref_anchor.replace_with(*replacements)

        # Normally the cluster belongs directly after the owning block. If a
        # malformed/source-tolerated document wraps that block in a link, use
        # the same outer-anchor escape boundary as the noteref so the note's
        # backlink cannot become a nested anchor either.
        cluster_anchor = self._outermost_enclosing_anchor(block_anchor) or block_anchor
        cluster: Tag | None = None
        next_sibling = cluster_anchor.find_next_sibling()
        if isinstance(next_sibling, Tag):
            sibling_classes = cast(list[str], next_sibling.get("class") or [])
            if "hbp-note-cluster" in sibling_classes:
                cluster = next_sibling
        if cluster is None:
            cluster = soup.new_tag("div", attrs={"class": "hbp-note-cluster"})
            cluster_anchor.insert_after(cluster)

        note_attrs = {
            "id": f"hbp-note-{annotation_id}",
            "class": f"hbp-note hbp-note-{type_slug}",
            "style": self._note_style(annotation),
            "title": f"{type_slug} (confidence {annotation.confidence:.2f})",
        }
        note_name = "aside" if is_epub3 else "div"
        if is_epub3:
            note_attrs["epub:type"] = "footnote"
            note_attrs["xmlns:epub"] = _EPUB_NAMESPACE
        note_tag = soup.new_tag(
            note_name,
            attrs=note_attrs,
        )
        backlink = soup.new_tag(
            "a",
            attrs={
                "class": "hbp-note-backlink",
                "href": f"#hbp-ref-{annotation_id}",
            },
        )
        backlink.string = f"{note_number}."
        note_tag.append(backlink)
        note_tag.append(NavigableString(self._format_note_text(annotation)))
        cluster.append(note_tag)

    # ------------------------------------------------------------
    # Small helpers
    # ------------------------------------------------------------

    @staticmethod
    def _ink_hex(annotation_type: AnnotationType) -> str:
        return _rgb_to_hex(_INK_PALETTE.get(annotation_type, _DEFAULT_INK))

    @staticmethod
    def _effective_mark_intent(
        annotation: Annotation | V2Annotation,
    ) -> MarkIntent:
        """Return the explicit V2 intent or the pinned legacy migration intent."""
        if isinstance(annotation, V2Annotation):
            return annotation.mark_intent
        return _MARK_INTENTS[annotation.annotation_type]

    @staticmethod
    def _opacity(confidence: float) -> float:
        """Map confidence [0, 1] to an ink opacity, so uncertain notes
        look lighter/fainter and confident ones look bold (same curve as
        `DocumentProcessor._opacity`).
        """
        confidence = max(0.0, min(1.0, confidence))
        return 0.55 + 0.4 * confidence

    def _organic_angle(self, seed_text: str) -> float:
        """Deterministic-but-varied rotation angle in degrees for the
        note's CSS ``transform: rotate(...)``, so notes look organically
        scrawled rather than perfectly upright.
        """
        rnd = random.Random(self._seed if self._seed is not None else seed_text)
        magnitude = rnd.uniform(1.0, 4.0)
        sign = rnd.choice((-1, 1))
        return magnitude * sign

    def _note_style(self, annotation: Annotation | V2Annotation) -> str:
        ink_hex = self._ink_hex(annotation.annotation_type)
        opacity = self._opacity(annotation.confidence)
        angle = self._organic_angle(annotation.content)
        return f"color:{ink_hex}; opacity:{opacity:.2f}; transform:rotate({angle:.1f}deg);"

    @staticmethod
    def _format_note_text(annotation: Annotation | V2Annotation) -> str:
        prefix = _NOTE_PREFIX_BY_TYPE.get(annotation.annotation_type, "")
        return f"{prefix}{annotation.content}"

    # ------------------------------------------------------------
    # Convenience: flatten an AnnotationPlan
    # ------------------------------------------------------------

    @staticmethod
    def annotations_from_plan(plan: AnnotationPlan) -> list[Annotation]:
        """Flatten an `AnnotationPlan` into a single ordered list of
        `Annotation` objects suitable for `render_annotations`.

        Identical behavior to `DocumentProcessor.annotations_from_plan`;
        provided here too so callers don't need to reach into the PDF
        module just to flatten a plan when working with EPUBs.
        """
        flattened: list[Annotation] = []
        for page in plan.pages:
            for annotation in page.annotations:
                if annotation.page != page.page_number:
                    annotation = annotation.model_copy(update={"page": page.page_number})
                flattened.append(annotation)
        return flattened
