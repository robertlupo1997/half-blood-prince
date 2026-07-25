"""Pure DOM-range location for EPUB text split across inline elements."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from bs4 import Comment, NavigableString, Tag

from halfblood.documents.matching import (
    AmbiguousResult,
    MatchResult,
    MatchTolerance,
    NoMatchResult,
    NormalizedText,
    RawSpan,
    score_candidates,
)

if TYPE_CHECKING:
    from halfblood.models.annotations import TargetSelector


# A match may span arbitrary inline markup, but it must never cross one of
# these elements (or the supplied chapter root).
_BLOCK_TAGS = frozenset(
    {
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
        "li",
        "ul",
        "ol",
        "dl",
        "dt",
        "dd",
        "table",
        "thead",
        "tbody",
        "tfoot",
        "tr",
        "td",
        "th",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "br",
        "hr",
        "html",
        "body",
    }
)


@dataclass(frozen=True)
class CrossNodeSegment:
    """A half-open raw-text slice within one DOM text node."""

    node: NavigableString
    start: int
    end: int


@dataclass(frozen=True)
class CrossNodeMatch:
    """An ordered set of DOM text slices representing one confident quote."""

    segments: tuple[CrossNodeSegment, ...]
    reason: str


def _is_own_markup(node: NavigableString) -> bool:
    """Return whether ``node`` is inside markup previously inserted by us."""
    for ancestor in node.parents:
        if not isinstance(ancestor, Tag):
            continue
        classes = cast(list[str], ancestor.get("class") or [])
        if any(token.startswith("hbp-") for token in classes):
            return True
    return False


def _can_join_run(node: NavigableString) -> bool:
    """Return whether a text node may participate positionally in a run."""
    if isinstance(node, Comment) or node.parent is None:
        return False
    if node.parent.name in {"script", "style"}:
        return False
    return not _is_own_markup(node)


def _append_anchored_run(
    runs: list[list[NavigableString]], candidate: list[NavigableString]
) -> None:
    """Append a run while dropping non-anchoring whitespace at its edges."""
    start = 0
    while start < len(candidate) and not str(candidate[start]).strip():
        start += 1
    end = len(candidate)
    while end > start and not str(candidate[end - 1]).strip():
        end -= 1
    if start < end:
        runs.append(candidate[start:end])


def iter_inline_runs(root: Tag) -> list[list[NavigableString]]:
    """Return maximal text-node runs that do not cross block boundaries.

    Whitespace-only nodes cannot anchor a run, but nodes between two text
    anchors are retained so normalization sees the same positional spacing as
    the DOM. Comments, script/style content, and existing ``hbp-*`` markup are
    excluded.
    """
    runs: list[list[NavigableString]] = []

    def walk(container: Tag, current: list[NavigableString]) -> list[NavigableString]:
        for child in container.children:
            if isinstance(child, NavigableString):
                if _can_join_run(child):
                    current.append(child)
                continue
            if not isinstance(child, Tag):
                continue

            if child.name.lower() in _BLOCK_TAGS:
                _append_anchored_run(runs, current)
                block_run = walk(child, [])
                _append_anchored_run(runs, block_run)
                current = []
            else:
                current = walk(child, current)
        return current

    _append_anchored_run(runs, walk(root, []))
    return runs


def _owner_map(run: list[NavigableString]) -> tuple[str, list[tuple[int, int]]]:
    """Concatenate a run and map every raw character to its source node."""
    raw_parts: list[str] = []
    owner: list[tuple[int, int]] = []
    for node_index, node in enumerate(run):
        raw = str(node)
        raw_parts.append(raw)
        owner.extend((node_index, offset) for offset in range(len(raw)))
    return "".join(raw_parts), owner


def _segments_for_span(
    run: list[NavigableString], owner: list[tuple[int, int]], span: RawSpan
) -> tuple[CrossNodeSegment, ...]:
    """Map one concatenated raw span back to maximal per-node slices."""
    segments: list[CrossNodeSegment] = []
    position = span.start
    while position < span.end:
        node_index, start = owner[position]
        position += 1
        end = start + 1
        while position < span.end and owner[position][0] == node_index:
            end = owner[position][1] + 1
            position += 1

        segments.append(
            CrossNodeSegment(node=run[node_index], start=start, end=end)
        )
    return tuple(segments)


def _has_overlapping_exact(text: str, needle: str) -> bool:
    """Return whether exact occurrences overlap, a case the scorer omits."""
    first = text.find(needle)
    while first >= 0:
        following = text.find(needle, first + 1)
        if following < 0:
            return False
        if following < first + len(needle):
            return True
        first = following
    return False


# Strictest-first tolerance ladder used by locate_across_nodes and
# _epub_miss_reason. Both must walk the same sequence so their answers
# stay consistent.
_MATCH_LADDER: tuple[MatchTolerance, ...] = (
    MatchTolerance.EXACT,
    MatchTolerance.CASE_INSENSITIVE,
    MatchTolerance.PUNCTUATION_ELASTIC,
)

_HitList = list[tuple[list[NavigableString], list[tuple[int, int]], RawSpan, str]]


def _scan_with_tolerance(
    root: Tag,
    selector: TargetSelector,
    tolerance: MatchTolerance,
) -> tuple[bool, _HitList]:
    """Scan all inline runs for tier-0 hits at one tolerance level.

    Returns ``(ambiguous, hits)`` where ``ambiguous`` is ``True`` if any run
    contained overlapping exact occurrences or produced an ``AmbiguousResult``
    at tier 0.  The caller decides whether to halt or advance based on these.
    """
    hits: _HitList = []
    ambiguous = False
    for run in iter_inline_runs(root):
        concat_raw, owner = _owner_map(run)
        normalized = NormalizedText(concat_raw)
        if _has_overlapping_exact(normalized.text, selector.normalized_exact):
            ambiguous = True
            continue
        outcome = score_candidates(selector, normalized, tolerance=tolerance)
        if isinstance(outcome, NoMatchResult):
            continue
        if isinstance(outcome, AmbiguousResult):
            if outcome.candidates and outcome.candidates[0].exactness_tier == 0:
                ambiguous = True
            continue
        if isinstance(outcome, MatchResult) and outcome.candidate.exactness_tier == 0:
            hits.append(
                (run, owner, outcome.candidate.raw_span, outcome.candidate.reason)
            )
    return ambiguous, hits


def locate_across_nodes(root: Tag, selector: TargetSelector) -> CrossNodeMatch | None:
    """Locate one unambiguous full quote within a single inline DOM run.

    Walks a strictest-first tolerance ladder: EXACT → CASE_INSENSITIVE →
    PUNCTUATION_ELASTIC.  Each rung is scanned independently across all inline
    runs; hits from different rungs are never pooled.  The ladder advances only
    on a clean zero (no hits, no ambiguity at the current rung); ambiguity at
    any rung halts immediately and returns ``None``.

    Only tier-0 (complete-quote) candidates are accepted so returned segments
    always represent the selector's full normalized exact quote.
    """
    for tolerance in _MATCH_LADDER:
        ambiguous, hits = _scan_with_tolerance(root, selector, tolerance)
        if ambiguous or len(hits) > 1:
            return None  # halt — never loosen past ambiguity or multi-hit
        if len(hits) == 1:
            run, owner, raw_span, scorer_reason = hits[0]
            segments = _segments_for_span(run, owner, raw_span)
            if not segments:
                return None
            return CrossNodeMatch(
                segments=segments, reason=f"match: {scorer_reason}"
            )
        # clean zero at this rung → advance to the next
    return None


def selector_for(target_text: str) -> TargetSelector:
    """Build an exact-only selector for a legacy EPUB target string."""
    from halfblood.models.annotations import TargetSelector

    return TargetSelector(exact=target_text)
