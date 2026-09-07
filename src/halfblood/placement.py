"""Strict evidence-to-anchor placement for PDF and reflowable EPUB.

Public entry points return JSON-safe ``PlacementResult`` records. Resolution
requires one complete normalized quotation and agreement with every supplied
hint. There are no prefix tiers, fuzzy matches, case folds, proximity scores,
or first-hit fallbacks. Overlapping occurrences count as distinct candidates.

Normalization is shared with ``documents.matching.normalize``: NFC, collapsed
Unicode whitespace, typographic quote folding, and en/em dash folding only.
Offsets are **raw character offsets**, never normalized offsets. For EPUB they
are local to an inline run, so offsets alone cannot identify a chapter run.

PDF coordinates are displayed page points after rotation. EPUB results are DOM
text references only; no browser geometry is inferred. Fixed-layout EPUB is
explicitly unsupported. Text/quote/candidate bounds fail closed. Error reasons
are fixed machine codes and never include source text or exception messages.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Literal

import fitz
from bs4 import NavigableString, Tag

from halfblood.documents.epub import CrossNodeMatch, CrossNodeSegment, iter_inline_runs
from halfblood.documents.matching import (
    MAX_CANDIDATES,
    MAX_INPUT_CHARS,
    MAX_NEEDLE_CHARS,
    NormalizedText,
    normalize,
)
from halfblood.documents.pdf import PdfAlignmentError, PdfPageIndex, resolve_pdf_anchor
from halfblood.models.annotations import TargetSelector
from halfblood.models.placement import (
    EpubSegmentRef,
    PlacementPoint,
    PlacementQuad,
    PlacementReason,
    PlacementResult,
    PlacementStatus,
)

_Renderer = Literal["pdf", "epub"]


@dataclass(frozen=True)
class _Occurrence:
    run_index: int
    start: int
    end: int
    matched_text: str
    hints_agree: bool


class _PlacementBoundError(ValueError):
    """A deliberate work bound was exceeded."""

    def __init__(self, reason: PlacementReason) -> None:
        self.reason = reason
        super().__init__(reason)


def _refusal(
    renderer: _Renderer,
    reason: PlacementReason,
    *,
    status: PlacementStatus = PlacementStatus.UNRESOLVED,
    candidate_count: int = 0,
) -> PlacementResult:
    return PlacementResult(
        renderer=renderer, status=status, reason=reason,
        candidate_count=candidate_count,
    )


def _selector_error(selector: TargetSelector) -> PlacementReason | None:
    if not isinstance(selector, TargetSelector):
        return "invalid_selector"
    if any(
        len(value) > MAX_NEEDLE_CHARS
        for value in (selector.exact, selector.prefix, selector.suffix)
        if value is not None
    ):
        return "quote_limit_exceeded"
    if not selector.normalized_exact.strip():
        return "invalid_selector"
    return None


def _occurrences(
    raw: str, selector: TargetSelector, run_index: int,
) -> list[_Occurrence]:
    """Enumerate all overlapping starts and verify exact source/hint evidence."""
    text = NormalizedText(raw)
    needle = selector.normalized_exact
    prefix = selector.normalized_prefix
    suffix = selector.normalized_suffix
    hits: list[_Occurrence] = []
    search_from = 0
    starts_seen = 0
    while True:
        start = text.text.find(needle, search_from)
        if start < 0:
            return hits
        starts_seen += 1
        if starts_seen > MAX_CANDIDATES:
            raise _PlacementBoundError("candidate_limit_exceeded")
        end = start + len(needle)
        search_from = start + 1
        span = text.raw_span(start, end)
        matched_text = raw[span.start:span.end]
        # Some combining-mark slices have only a covering raw span. Such a
        # span is not quotation evidence unless its whole normalization agrees.
        if normalize(matched_text) != needle:
            continue
        hints_agree = (
            (prefix is None or text.text[:start].endswith(prefix))
            and (suffix is None or text.text[end:].startswith(suffix))
            and (selector.start_offset is None or selector.start_offset == span.start)
            and (selector.end_offset is None or selector.end_offset == span.end)
        )
        hits.append(_Occurrence(run_index, span.start, span.end, matched_text, hints_agree))


def _choose(
    renderer: _Renderer, occurrences: list[_Occurrence],
) -> _Occurrence | PlacementResult:
    if not occurrences:
        return _refusal(renderer, "quote_not_found")
    verified = [hit for hit in occurrences if hit.hints_agree]
    if not verified:
        return _refusal(
            renderer, "selector_hints_mismatch", candidate_count=len(occurrences),
        )
    if len(verified) > 1:
        return _refusal(
            renderer, "ambiguous_quote", status=PlacementStatus.AMBIGUOUS,
            candidate_count=len(occurrences),
        )
    return verified[0]


def _pdf_quad(quad: fitz.Quad) -> PlacementQuad:
    return PlacementQuad(
        ul=PlacementPoint(x=quad.ul.x, y=quad.ul.y),
        ur=PlacementPoint(x=quad.ur.x, y=quad.ur.y),
        lr=PlacementPoint(x=quad.lr.x, y=quad.lr.y),
        ll=PlacementPoint(x=quad.ll.x, y=quad.ll.y),
    )


def resolve_pdf_quote(page: fitz.Page, selector: TargetSelector) -> PlacementResult:
    """Resolve complete text evidence to PDF display-space line quads.

    A character index is mandatory. If extraction cannot align with geometry,
    the result is ``unresolved``; rectangle search never substitutes a guess.
    ``raw_span`` uses this page's default ``get_text("text")`` character order.
    """
    selector_error = _selector_error(selector)
    if selector_error:
        return _refusal("pdf", selector_error)
    try:
        raw = page.get_text("text")
    except (RuntimeError, ValueError, TypeError, AttributeError):
        return _refusal("pdf", "source_unavailable")
    if not isinstance(raw, str):
        return _refusal("pdf", "source_unavailable")
    if len(raw) > MAX_INPUT_CHARS:
        return _refusal("pdf", "input_limit_exceeded")
    try:
        hits = _occurrences(raw, selector, 0)
    except _PlacementBoundError:
        return _refusal("pdf", "candidate_limit_exceeded")
    choice = _choose("pdf", hits)
    if isinstance(choice, PlacementResult):
        return choice

    try:
        index = PdfPageIndex(page)
        if index.text != raw:
            return _refusal("pdf", "geometry_unavailable", candidate_count=len(hits))
        anchor = resolve_pdf_anchor(index, choice.start, choice.end)
        if (
            anchor is None
            or anchor.char_range != (choice.start, choice.end)
            or not anchor.quads
            or any(not q.is_convex or q.rect.is_empty or q.rect.is_infinite for q in anchor.quads)
        ):
            return _refusal("pdf", "geometry_unavailable", candidate_count=len(hits))
        quads = tuple(_pdf_quad(quad) for quad in anchor.quads)
    except (PdfAlignmentError, RuntimeError, ValueError, TypeError, AttributeError):
        return _refusal("pdf", "geometry_unavailable", candidate_count=len(hits))

    return PlacementResult(
        renderer="pdf", status=PlacementStatus.RESOLVED, reason="unique_verified_quote",
        raw_span=(choice.start, choice.end), matched_text=choice.matched_text,
        candidate_count=len(hits), coordinate_space="pdf_display_points", quads=quads,
        source_digest=hashlib.sha256(raw.encode("utf-8")).hexdigest(),
    )


def _epub_runs(root: Tag) -> list[list[NavigableString]]:
    # Bound all descendant text, including excluded script/style/own markup,
    # before building run maps or normalizing any text.
    text_length = 0
    for node in root.descendants:
        if isinstance(node, NavigableString):
            text_length += len(node)
            if text_length > MAX_INPUT_CHARS:
                raise _PlacementBoundError("input_limit_exceeded")
    return iter_inline_runs(root)


def _runs_digest(runs: list[list[NavigableString]]) -> str:
    payload = json.dumps([[str(node) for node in run] for run in runs], ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _epub_refs(
    runs: list[list[NavigableString]], choice: _Occurrence,
) -> tuple[EpubSegmentRef, ...]:
    refs: list[EpubSegmentRef] = []
    offset = 0
    for node_index, node in enumerate(runs[choice.run_index]):
        node_end = offset + len(node)
        start, end = max(choice.start, offset), min(choice.end, node_end)
        if start < end:
            refs.append(EpubSegmentRef(
                run_index=choice.run_index, node_index=node_index,
                start=start - offset, end=end - offset,
            ))
        offset = node_end
    return tuple(refs)


def resolve_epub_quote(
    root: Tag, selector: TargetSelector, *, fixed_layout: bool = False,
) -> PlacementResult:
    """Resolve a complete quote within one reflowable EPUB inline DOM run.

    Block boundaries are not crossed. References contain no live DOM objects.
    CSS layout is not evaluated: callers must pass ``fixed_layout=True`` for
    pre-paginated content, which produces ``unsupported_renderer``.
    """
    if fixed_layout:
        return _refusal(
            "epub", "fixed_layout_unsupported", status=PlacementStatus.UNSUPPORTED_RENDERER,
        )
    selector_error = _selector_error(selector)
    if selector_error:
        return _refusal("epub", selector_error)
    if not isinstance(root, Tag):
        return _refusal("epub", "source_unavailable")
    try:
        runs = _epub_runs(root)
        hits: list[_Occurrence] = []
        for run_index, run in enumerate(runs):
            hits.extend(_occurrences("".join(str(node) for node in run), selector, run_index))
            if len(hits) > MAX_CANDIDATES:
                return _refusal("epub", "candidate_limit_exceeded")
    except _PlacementBoundError as exc:
        return _refusal("epub", exc.reason)
    except RecursionError:
        return _refusal("epub", "source_unavailable")
    choice = _choose("epub", hits)
    if isinstance(choice, PlacementResult):
        return choice
    refs = _epub_refs(runs, choice)
    if not refs:
        return _refusal("epub", "source_unavailable", candidate_count=len(hits))
    return PlacementResult(
        renderer="epub", status=PlacementStatus.RESOLVED, reason="unique_verified_quote",
        raw_span=(choice.start, choice.end), matched_text=choice.matched_text,
        candidate_count=len(hits), coordinate_space="epub_dom_text", epub_segments=refs,
        source_digest=_runs_digest(runs),
    )


def epub_match_from_placement(root: Tag, result: PlacementResult) -> CrossNodeMatch | None:
    """Rehydrate text segments against the same DOM text structure, or refuse.

    Resolve again after any wrapping/splitting mutation. The digest and source
    slice checks prevent stale serialized references from selecting new text.
    The returned legacy match is only an adapter for existing markup writers;
    the public placement record remains live-object-free.
    """
    if (
        result.renderer != "epub"
        or result.status is not PlacementStatus.RESOLVED
        or not result.epub_segments
        or result.raw_span is None
        or not isinstance(root, Tag)
    ):
        return None
    try:
        runs = _epub_runs(root)
    except (_PlacementBoundError, RecursionError):
        return None
    if _runs_digest(runs) != result.source_digest:
        return None
    segments: list[CrossNodeSegment] = []
    previous_end: int | None = None
    selected_run = result.epub_segments[0].run_index
    for ref in result.epub_segments:
        if ref.run_index != selected_run or ref.run_index >= len(runs):
            return None
        run = runs[ref.run_index]
        if ref.node_index >= len(run):
            return None
        node = run[ref.node_index]
        if not 0 <= ref.start < ref.end <= len(node):
            return None
        offset = sum(len(item) for item in run[:ref.node_index])
        if previous_end is not None and offset + ref.start != previous_end:
            return None
        if previous_end is None and offset + ref.start != result.raw_span[0]:
            return None
        previous_end = offset + ref.end
        segments.append(CrossNodeSegment(node=node, start=ref.start, end=ref.end))
    if previous_end != result.raw_span[1]:
        return None
    if "".join(str(seg.node)[seg.start:seg.end] for seg in segments) != result.matched_text:
        return None
    return CrossNodeMatch(segments=tuple(segments), reason="strict-placement: unique_verified_quote")


__all__ = [
    "EpubSegmentRef",
    "PlacementPoint",
    "PlacementQuad",
    "PlacementResult",
    "PlacementStatus",
    "epub_match_from_placement",
    "resolve_epub_quote",
    "resolve_pdf_quote",
]
