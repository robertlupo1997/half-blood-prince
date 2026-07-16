"""Bounded, reversible normalized-text matching.

Normalization is deliberately surface-neutral and happens in this order:

1. Curly single and double quotes are folded to their ASCII forms.
2. En and em dashes are folded to an ASCII hyphen.
3. Each run of Unicode whitespace is collapsed to one ASCII space.
4. The result is normalized to Unicode NFC.

The shared normalization does not strip surrounding whitespace and does not
repair PDF-specific middle-dot extraction artifacts.
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
    characters: list[tuple[str, RawSpan]],
) -> tuple[str, list[RawSpan]]:
    """Return canonical decomposition tokens and their source spans.

    Canonical ordering is reproduced alongside the spans so the tokens align
    with ``NFD(NFC(text))`` even when combining marks need to be reordered.
    """
    tokens: list[str] = []
    spans: list[RawSpan] = []
    for char, span in characters:
        for token in unicodedata.normalize("NFD", char):
            tokens.append(token)
            spans.append(span)
            combining_class = unicodedata.combining(token)
            if combining_class == 0:
                continue
            position = len(tokens) - 1
            while position > 0:
                previous_class = unicodedata.combining(tokens[position - 1])
                if previous_class == 0 or previous_class <= combining_class:
                    break
                tokens[position - 1], tokens[position] = (
                    tokens[position],
                    tokens[position - 1],
                )
                spans[position - 1], spans[position] = (
                    spans[position],
                    spans[position - 1],
                )
                position -= 1
    return "".join(tokens), spans


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
    decomposed, token_spans = _canonical_decomposition_with_spans(folded)
    expected_decomposition = unicodedata.normalize("NFD", normalized)
    if decomposed != expected_decomposition:
        raise RuntimeError("normalized text could not be aligned with its source")

    normalized_spans: list[RawSpan] = []
    token_index = 0
    for char in normalized:
        token_count = len(unicodedata.normalize("NFD", char))
        contributing = token_spans[token_index : token_index + token_count]
        normalized_spans.append(
            RawSpan(
                min(span.start for span in contributing),
                max(span.end for span in contributing),
            )
        )
        token_index += token_count
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
