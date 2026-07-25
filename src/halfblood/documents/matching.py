"""Bounded, reversible normalized-text matching.

Normalization is deliberately surface-neutral and happens in this order:

1. Curly single and double quotes are folded to their ASCII forms.
2. En and em dashes are folded to an ASCII hyphen.
3. Each run of Unicode whitespace is collapsed to one ASCII space.
4. The result is normalized to Unicode NFC.

The shared normalization does not strip surrounding whitespace and does not
repair PDF-specific middle-dot extraction artifacts.

Reversibility (``raw_span``/``find_all``) is exact for all realistic text: precomposed
accents and words carrying up to two distinct combining marks (Latin, Vietnamese, polytonic
Greek) round-trip exactly at any position, and the whole-string span always round-trips.
Known limitation (deferred to P2-T3, which owns grapheme-cluster-aware match precision): a
normalized cluster whose NFC form retains 3+ combining marks, or contains duplicate marks,
may return a *covering* rather than exact span. Such clusters do not occur in normal book
text. A slice that cuts a canonically-reordered cluster where NFC composes a base with a mark
across an intervening mark (e.g. ``o`` + U+0301 + U+0323) has no contiguous raw counterpart at
all and necessarily returns the smallest covering span.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Union

if TYPE_CHECKING:
    from halfblood.models.annotations import TargetSelector

MAX_INPUT_CHARS = 50_000
MAX_NEEDLE_CHARS = 5_000
MAX_CANDIDATES = 500

MIN_CONTEXT_SCORE: float = 0.0
# Minimum context_score for a MatchResult candidate. 0.0 = never reject on score alone
# (callers inspect context_score themselves). Named so callers can tune it.

AMBIGUITY_MARGIN: float = 0.15
# Dual role — both thresholds use the same value:
# (1) Context-score near-tie: when two or more candidates in the winning tier have
#     a context_score difference <= AMBIGUITY_MARGIN, the outcome is AmbiguousResult
#     instead of a guessed MatchResult.  Covers exact ties (diff == 0).
# (2) Offset-score tiebreaker: when two candidates are already within AMBIGUITY_MARGIN
#     of each other on context_score, their offset_score difference must exceed
#     AMBIGUITY_MARGIN to break the tie; otherwise offset_score is treated as negligible.

class MatchTolerance(StrEnum):
    """How loosely the full-quote tier is compared to source text.

    The tolerance changes *how* a needle is compared, not *which* needles are
    tried. The exactness-tier ladder (full -> 8-word -> 5-word -> 3-word ->
    longest word) is orthogonal to tolerance.

    ``EXACT``
        Byte-identical to today's behaviour; the default. The shortened-tier
        fallback does not fire when the full quote would have matched under a
        looser tolerance -- that signals surface drift, not genuine absence.
    ``CASE_INSENSITIVE``
        Fold case on both needle and text before comparison. Tier-0 (the
        complete quote) is searched; shorter tiers are not tried. Folding is
        length-preserving: ss/fi/dotted-I are left alone so raw spans
        stay aligned.
    ``PUNCTUATION_ELASTIC``
        Optional straight quote characters at word boundaries.
        Implies case-insensitivity. Tier-0 only.
    """

    EXACT = "exact"
    CASE_INSENSITIVE = "case_insensitive"
    PUNCTUATION_ELASTIC = "punctuation_elastic"


_PUNCTUATION_FOLDS = {
    "‘": "'",
    "’": "'",
    "“": '"',
    "”": '"',
    "–": "-",
    "—": "-",
}


@dataclass(frozen=True)
class RawSpan:
    """A half-open span in the original, unmodified text."""

    start: int
    end: int


@dataclass
class ScoredCandidate:
    """A single located candidate with its scoring evidence."""

    raw_span: RawSpan
    context_score: float
    offset_score: float
    exactness_tier: int
    reason: str


@dataclass
class MatchResult:
    """A single confident candidate from the winning exactness tier."""

    candidate: ScoredCandidate


@dataclass
class AmbiguousResult:
    """Two or more near-tie candidates in ascending source order."""

    candidates: list[ScoredCandidate]


@dataclass
class NoMatchResult:
    """No candidate in any tier, or a top candidate below the score threshold."""

    reason: str


ScoringOutcome = Union[MatchResult, AmbiguousResult, NoMatchResult]  # noqa: UP007


def normalize(text: str) -> str:
    """Return the surface-neutral normalized form of ``text``.

    Surrounding whitespace is retained (subject to run collapsing), making
    the operation idempotent and allowing every indexed character to retain
    a source span.
    """
    folded: list[str] = []
    in_whitespace = False
    for char in text:
        if char.isspace():
            if not in_whitespace:
                folded.append(" ")
                in_whitespace = True
            continue
        folded.append(_PUNCTUATION_FOLDS.get(char, char))
        in_whitespace = False
    return unicodedata.normalize("NFC", "".join(folded))


def _canonical_decomposition_with_spans(
    characters: list[tuple[str, RawSpan]], raw: str,
) -> tuple[str, list[RawSpan]]:
    """Normalize starter segments and align their output to raw prefixes."""
    normalized_parts: list[str] = []
    normalized_spans: list[RawSpan] = []
    segment_start = 0

    while segment_start < len(characters):
        segment_end = segment_start + 1
        while segment_end < len(characters):
            char = characters[segment_end][0]
            if unicodedata.combining(char) == 0:
                current = "".join(
                    item for item, _span in characters[segment_start:segment_end]
                )
                # Ordinarily a starter begins a new independent segment.  The
                # equality check retains Hangul Jamo (also class zero) when NFC
                # can compose them across that apparent boundary.
                if unicodedata.normalize("NFC", current + char) == (
                    unicodedata.normalize("NFC", current)
                    + unicodedata.normalize("NFC", char)
                ):
                    break
            segment_end += 1

        segment = characters[segment_start:segment_end]
        segment_text = unicodedata.normalize(
            "NFC", "".join(char for char, _span in segment)
        )
        normalized_parts.append(segment_text)

        raw_start = segment[0][1].start
        raw_end = segment[-1][1].end
        boundaries = [raw_start]
        prefix_index = 0
        for normalized_end in range(1, len(segment_text) + 1):
            while prefix_index < len(segment):
                candidate_end = segment[prefix_index][1].end
                prefix_index += 1
                if normalize(raw[raw_start:candidate_end]) == segment_text[:normalized_end]:
                    boundaries.append(candidate_end)
                    break
            else:
                break

        if len(boundaries) == len(segment_text) + 1:
            normalized_spans.extend(
                RawSpan(boundaries[index], boundaries[index + 1])
                for index in range(len(segment_text))
            )
        else:
            # Some canonically reordered decompositions have no raw prefix for
            # an intermediate NFC prefix.  Preserve exact single-character
            # slices wherever one exists and conservatively cover the segment
            # otherwise; no contiguous RawSpan can represent the latter case.
            for normalized_char in segment_text:
                candidates: list[RawSpan] = []
                for candidate_start in range(len(segment)):
                    for candidate_end in range(candidate_start, len(segment)):
                        span = RawSpan(
                            segment[candidate_start][1].start,
                            segment[candidate_end][1].end,
                        )
                        if normalize(raw[span.start : span.end]) == normalized_char:
                            candidates.append(span)
                normalized_spans.append(
                    min(
                        candidates,
                        key=lambda span: (span.end - span.start, span.start),
                        default=RawSpan(raw_start, raw_end),
                    )
                )

        segment_start = segment_end

    return "".join(normalized_parts), normalized_spans


def _normalize_with_spans(raw: str) -> tuple[str, list[RawSpan]]:
    """Normalize ``raw`` while retaining a span for every output character."""
    folded: list[tuple[str, RawSpan]] = []
    index = 0
    while index < len(raw):
        char = raw[index]
        if char.isspace():
            end = index + 1
            while end < len(raw) and raw[end].isspace():
                end += 1
            folded.append((" ", RawSpan(index, end)))
            index = end
            continue
        folded.append((_PUNCTUATION_FOLDS.get(char, char), RawSpan(index, index + 1)))
        index += 1

    folded_text = "".join(char for char, _span in folded)
    normalized = unicodedata.normalize("NFC", folded_text)
    aligned, normalized_spans = _canonical_decomposition_with_spans(folded, raw)
    if aligned != normalized:
        raise RuntimeError("normalized text could not be aligned with its source")
    return normalized, normalized_spans


class NormalizedText:
    """A bounded normalized string with reversible raw offsets."""

    def __init__(self, raw: str) -> None:
        if len(raw) > MAX_INPUT_CHARS:
            raise ValueError(f"input exceeds MAX_INPUT_CHARS ({MAX_INPUT_CHARS})")
        self._raw = raw
        self._text, self._spans = _normalize_with_spans(raw)

    @property
    def text(self) -> str:
        """The normalized text."""
        return self._text

    @property
    def raw(self) -> str:
        """The original, unmodified text."""
        return self._raw

    def raw_span(self, start: int, end: int) -> RawSpan:
        """Return the smallest raw half-open span covering ``[start, end)``."""
        if start < 0 or end < start or end > len(self._text):
            raise ValueError("normalized span is out of bounds")
        if start == end:
            if start < len(self._spans):
                offset = self._spans[start].start
            elif self._spans:
                offset = self._spans[-1].end
            else:
                offset = 0
            return RawSpan(offset, offset)

        selected = self._spans[start:end]
        return RawSpan(
            min(span.start for span in selected),
            max(span.end for span in selected),
        )

    def find_all(self, needle: str) -> list[RawSpan]:
        """Find non-overlapping literal matches, earliest first.

        The needle is normalized before searching. More than
        :data:`MAX_CANDIDATES` matches is rejected rather than truncated.
        """
        if len(needle) > MAX_NEEDLE_CHARS:
            raise ValueError(f"needle exceeds MAX_NEEDLE_CHARS ({MAX_NEEDLE_CHARS})")
        normalized_needle = normalize(needle)
        if not normalized_needle.strip():
            raise ValueError("needle must contain a non-whitespace character")

        matches: list[RawSpan] = []
        search_from = 0
        while True:
            start = self._text.find(normalized_needle, search_from)
            if start < 0:
                return matches
            if len(matches) == MAX_CANDIDATES:
                raise ValueError(f"match count exceeds MAX_CANDIDATES ({MAX_CANDIDATES})")
            end = start + len(normalized_needle)
            matches.append(self.raw_span(start, end))
            search_from = end


def _exactness_tiers(normalized_exact: str) -> list[str]:
    """Build the ordered, de-duplicated legacy exactness ladder."""
    words = normalized_exact.split(" ")
    variants = [normalized_exact]
    if len(words) > 8:
        variants.append(" ".join(words[:8]))
    if len(words) > 5:
        variants.append(" ".join(words[:5]))
    if len(words) > 3:
        variants.append(" ".join(words[:3]))

    longest = max(
        (word.strip(".,;:!?\"'()") for word in words),
        key=len,
        default="",
    )
    if len(longest) >= 4:
        variants.append(longest)

    seen: set[str] = set()
    tiers: list[str] = []
    for variant in variants:
        if variant and variant not in seen:
            seen.add(variant)
            tiers.append(variant)
    return tiers


def _find_normalized_occurrences(
    text: NormalizedText,
    needle: str,
) -> list[tuple[int, int, RawSpan]]:
    """Return bounded non-overlapping normalized and raw occurrence spans."""
    if len(needle) > MAX_NEEDLE_CHARS:
        raise ValueError(f"needle exceeds MAX_NEEDLE_CHARS ({MAX_NEEDLE_CHARS})")
    if not needle.strip():
        raise ValueError("needle must contain a non-whitespace character")

    matches: list[tuple[int, int, RawSpan]] = []
    search_from = 0
    while True:
        start = text.text.find(needle, search_from)
        if start < 0:
            return matches
        if len(matches) == MAX_CANDIDATES:
            raise ValueError(f"match count exceeds MAX_CANDIDATES ({MAX_CANDIDATES})")
        end = start + len(needle)
        matches.append((start, end, text.raw_span(start, end)))
        search_from = end


def _fold_case(text: str) -> str:
    """Length-preserving case fold for use on span-aligned text.

    Only lowers a character when the result is a single code point.
    ``str.casefold()`` maps ``ß``→``ss`` and ``İ``→two code points, which
    would desynchronise every ``RawSpan`` after the folded character.
    Those characters are deliberately left unfolded here.
    """
    return "".join((low if len(low := c.lower()) == 1 else c) for c in text)


def _build_elastic_pattern(normalized_needle: str) -> re.Pattern[str] | None:
    """Build a PUNCTUATION_ELASTIC regex, or ``None`` for empty needles.

    Semantics: straight quote characters (``'`` / ``"``) at token edges are
    optional on both sides. Interior apostrophes (``don't``) and all other
    punctuation are literal. Matching is case-insensitive.

    Adjacent ``["']*`` groups are always separated by a literal space (the
    token joiner), so catastrophic backtracking cannot occur. Quote-only
    tokens contribute exactly one group, never an empty alternation.
    """
    tokens = normalized_needle.split(" ")
    parts: list[str] = []
    for token in tokens:
        core = token.strip("\"'")
        if core:
            # Normal token: optional quotes at both edges, literal interior.
            parts.append('["\']*' + re.escape(core) + '["\']*')
        else:
            # Quote-only token: one optional-quote group. Groups are always
            # separated by the literal space joiner, so no two unbounded
            # groups are ever directly adjacent.
            parts.append('["\']*')
    if not parts:
        return None
    return re.compile(" ".join(parts), re.IGNORECASE)


def _find_occurrences_ci(
    text: NormalizedText,
    needle: str,
) -> list[tuple[int, int, RawSpan]]:
    """Return bounded non-overlapping case-insensitive occurrences.

    Uses ``_fold_case`` (length-preserving) so normalized indices remain
    aligned to ``text.raw_span``.
    """
    if len(needle) > MAX_NEEDLE_CHARS:
        raise ValueError(f"needle exceeds MAX_NEEDLE_CHARS ({MAX_NEEDLE_CHARS})")
    if not needle.strip():
        raise ValueError("needle must contain a non-whitespace character")

    folded_text = _fold_case(text.text)
    folded_needle = _fold_case(needle)
    if not folded_needle.strip():
        raise ValueError("folded needle is empty or whitespace-only")

    matches: list[tuple[int, int, RawSpan]] = []
    search_from = 0
    while True:
        start = folded_text.find(folded_needle, search_from)
        if start < 0:
            return matches
        if len(matches) == MAX_CANDIDATES:
            raise ValueError(f"match count exceeds MAX_CANDIDATES ({MAX_CANDIDATES})")
        end = start + len(folded_needle)
        matches.append((start, end, text.raw_span(start, end)))
        search_from = end


def _find_occurrences_elastic(
    text: NormalizedText,
    needle: str,
) -> list[tuple[int, int, RawSpan]]:
    """Return bounded non-overlapping punctuation-elastic occurrences.

    Zero-length matches (from quote-only patterns) are filtered out.
    Honouring ``MAX_CANDIDATES`` exactly as ``_find_normalized_occurrences``
    does: raises ``ValueError`` when a (MAX_CANDIDATES+1)-th match is found.
    """
    if len(needle) > MAX_NEEDLE_CHARS:
        raise ValueError(f"needle exceeds MAX_NEEDLE_CHARS ({MAX_NEEDLE_CHARS})")
    if not needle.strip():
        raise ValueError("needle must contain a non-whitespace character")

    pattern = _build_elastic_pattern(needle)
    if pattern is None:
        return []

    matches: list[tuple[int, int, RawSpan]] = []
    for m in pattern.finditer(text.text):
        start, end = m.start(), m.end()
        if start == end:
            # Zero-length match from a quote-only pattern — discard.
            continue
        if len(matches) == MAX_CANDIDATES:
            raise ValueError(f"match count exceeds MAX_CANDIDATES ({MAX_CANDIDATES})")
        matches.append((start, end, text.raw_span(start, end)))
    return matches


def _context_score(
    norm_text: str,
    n_start: int,
    n_end: int,
    selector: TargetSelector,
) -> float:
    """Return the fraction of provided context fields that agree."""
    checks = 0
    agreements = 0
    if selector.normalized_prefix is not None:
        checks += 1
        prefix = selector.normalized_prefix
        if norm_text[max(0, n_start - len(prefix)) : n_start].endswith(prefix):
            agreements += 1
    if selector.normalized_suffix is not None:
        checks += 1
        suffix = selector.normalized_suffix
        if norm_text[n_end : n_end + len(suffix)].startswith(suffix):
            agreements += 1
    return 1.0 if checks == 0 else agreements / checks


def _offset_score(n_start: int, start_offset: int | None, norm_text_len: int) -> float:
    """Return normalized proximity to start_offset, or zero when unavailable.

    ``start_offset`` is a **normalized-text** character position — specifically
    the output index from ``_normalize_with_spans``, NOT a raw byte offset or
    a character position in the original un-normalized document text.
    """
    if start_offset is None or norm_text_len == 0:
        return 0.0
    return max(0.0, 1.0 - abs(n_start - start_offset) / norm_text_len)


def _candidate(
    selector: TargetSelector,
    text: NormalizedText,
    exactness_tier: int,
    occurrence: tuple[int, int, RawSpan],
) -> ScoredCandidate:
    """Score one occurrence without including selector or source text in diagnostics."""
    n_start, n_end, span = occurrence
    context_score = _context_score(text.text, n_start, n_end, selector)
    offset_score = _offset_score(n_start, selector.start_offset, len(text.text))
    reason = (
        f"tier={exactness_tier} context={context_score:.2f} "
        f"offset={offset_score:.2f} pos={span.start}"
    )
    return ScoredCandidate(
        raw_span=span,
        context_score=context_score,
        offset_score=offset_score,
        exactness_tier=exactness_tier,
        reason=reason,
    )


def _score_occurrences(
    selector: TargetSelector,
    text: NormalizedText,
    tier_idx: int,
    occurrences: list[tuple[int, int, RawSpan]],
) -> ScoringOutcome:
    """Score and rank occurrences, returning the shared MatchResult/AmbiguousResult/NoMatchResult.

    All tolerance modes use the same scoring logic; this helper avoids repetition.
    """
    candidates = [
        _candidate(selector, text, tier_idx, occurrence)
        for occurrence in occurrences
    ]
    max_context = max(candidate.context_score for candidate in candidates)
    if max_context < MIN_CONTEXT_SCORE:
        top = max(
            candidates,
            key=lambda candidate: (
                candidate.context_score,
                candidate.offset_score,
                -candidate.raw_span.start,
            ),
        )
        return NoMatchResult(
            reason=(
                f"tier={tier_idx} context={top.context_score:.2f} "
                f"threshold={MIN_CONTEXT_SCORE:.2f} pos={top.raw_span.start}"
            )
        )

    contention = [
        candidate
        for candidate in candidates
        if max_context - candidate.context_score <= AMBIGUITY_MARGIN
    ]
    contention.sort(
        key=lambda candidate: (-candidate.offset_score, candidate.raw_span.start)
    )
    if len(contention) == 1:
        return MatchResult(contention[0])

    top, runner = contention[0], contention[1]
    if top.offset_score - runner.offset_score > AMBIGUITY_MARGIN:
        return MatchResult(top)

    pool = [
        candidate
        for candidate in contention
        if top.offset_score - candidate.offset_score <= AMBIGUITY_MARGIN
    ]
    pool.sort(key=lambda candidate: candidate.raw_span.start)
    return AmbiguousResult(pool)


def score_candidates(
    selector: TargetSelector,
    text: NormalizedText,
    *,
    legacy_exact_only: bool = False,
    tolerance: MatchTolerance = MatchTolerance.EXACT,
) -> ScoringOutcome:
    """Rank candidates across exactness tiers and reject ambiguous targets.

    ``EXACT`` mode (the default) searches the full quote followed by
    progressively shorter legacy fallbacks, stopping at the first tier with
    occurrences. Candidates in that tier are ranked by context agreement,
    offset proximity, and source position. This is unchanged by the tolerance
    ladder: adding a looser tolerance must never alter what an existing caller
    already receives.

    ``CASE_INSENSITIVE`` and ``PUNCTUATION_ELASTIC`` modes search tier 0 only
    using the appropriate fold or regex. A dropped word is a genuine miss at
    any tolerance; the shortened tiers are not tried.

    Legacy mode ignores ``tolerance`` entirely and searches only the full
    normalized quote, returning its first occurrence without scoring.
    """
    tiers = _exactness_tiers(selector.normalized_exact)
    if not tiers:
        return NoMatchResult(reason="tiers=0 candidates=0")

    if legacy_exact_only:
        try:
            occurrences = _find_normalized_occurrences(text, tiers[0])
        except ValueError:
            return NoMatchResult(reason="legacy=1 tier=0 bounded=0")
        if not occurrences:
            return NoMatchResult(reason="legacy=1 tier=0 candidates=0")
        _n_start, _n_end, span = occurrences[0]
        return MatchResult(
            ScoredCandidate(
                raw_span=span,
                context_score=1.0,
                offset_score=0.0,
                exactness_tier=0,
                reason="legacy: first occurrence tier=0",
            )
        )

    if tolerance in (MatchTolerance.CASE_INSENSITIVE, MatchTolerance.PUNCTUATION_ELASTIC):
        # Looser tolerances: search tier-0 only with the appropriate finder.
        # Shorter exactness tiers are not tried — a dropped word is a miss,
        # not a match on the longest remaining word.
        tier0_needle = tiers[0]
        try:
            if tolerance is MatchTolerance.CASE_INSENSITIVE:
                occurrences = _find_occurrences_ci(text, tier0_needle)
            else:
                occurrences = _find_occurrences_elastic(text, tier0_needle)
        except ValueError:
            return NoMatchResult(reason="tier=0 bounded=0")
        if not occurrences:
            return NoMatchResult(reason="tier=0 candidates=0")
        return _score_occurrences(selector, text, 0, occurrences)

    # EXACT mode: original tier loop with an elastic pre-check guard.
    winning_tier: int | None = None
    winning_occurrences: list[tuple[int, int, RawSpan]] = []
    for tier, needle in enumerate(tiers):
        try:
            occurrences = _find_normalized_occurrences(text, needle)
        except ValueError:
            return NoMatchResult(reason=f"tier={tier} bounded=0")
        if occurrences:
            winning_tier = tier
            winning_occurrences = occurrences
            break

    if winning_tier is None:
        return NoMatchResult(reason=f"tiers={len(tiers)} candidates=0")

    return _score_occurrences(selector, text, winning_tier, winning_occurrences)
