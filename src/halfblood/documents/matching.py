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

import unicodedata
from dataclasses import dataclass

MAX_INPUT_CHARS = 50_000
MAX_NEEDLE_CHARS = 5_000
MAX_CANDIDATES = 500

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
