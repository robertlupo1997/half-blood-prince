"""P2-T1 — one bounded, surface-neutral normalized-text index with reversible offsets.

Architecture §§3.1-3.2, 5.5, 7.2. The index (`halfblood.documents.matching`) replaces the
two divergent, copy-pasted normalization helpers in `document_processor.py` and
`epub_processor.py` with a single typed owner of normalization, reversible offset mapping,
and bounded literal search.

Design constraints these tests pin (each is a place a naive build goes wrong):

1. **NFC is length-changing.** A decomposed "e" + combining acute (2 code points) composes to
   "é" (1). The offset map therefore CANNOT be the old `list[int]` of per-char raw *starts*
   (`epub_processor._normalize_with_map`, whose docstring only holds "because every
   punctuation replacement is one character"). Each normalized char must map to a raw
   half-open span, so `raw_span` recovers the combining mark too. This is the tightest
   constraint in the task — see `test_reversible_*` (the accent params).
2. **The shared core is surface-neutral.** Middle-dot folding (`·` → apostrophe/hyphen) is a
   PDF text-extraction repair, NOT a normalization principle: on EPUB, `·` is a legitimate
   character. It stays in the PDF delegate, never in the shared core. See
   `test_shared_normalize_does_not_touch_middle_dot`.
3. **Delegates stay byte-identical on today's inputs.** "Existing tests remain green" means
   the PDF/EPUB `_normalize_search_text` outputs must not drift for any input the current
   suite exercises. See `test_*_delegate_is_byte_identical` (golden values captured from the
   pre-refactor code).
"""

from __future__ import annotations

import unicodedata

import pytest

from halfblood.documents.matching import (
    MAX_INPUT_CHARS,
    MAX_NEEDLE_CHARS,
    NormalizedText,
    RawSpan,
    normalize,
)

# Decomposed (NFD) and composed (NFC) forms of the same visible strings.
_CAFE_NFD = unicodedata.normalize("NFD", "café")
_CAFE_NFC = unicodedata.normalize("NFC", "café")
assert _CAFE_NFD != _CAFE_NFC and len(_CAFE_NFD) == 5 and len(_CAFE_NFC) == 4


# ---------------------------------------------------------------------------
# normalize() — the surface-neutral shared core
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("plain text", "plain text"),
        ("curly ‘quotes’", "curly 'quotes'"),
        ("smart “doubles”", 'smart "doubles"'),
        ("en–dash em—dash", "en-dash em-dash"),
        ("tabs\tand\r\nCRLF", "tabs and CRLF"),
        ("multiple     spaces", "multiple spaces"),
        ("", ""),
        ("   ", " "),  # pure whitespace collapses to one space (NOT stripped — see below)
    ],
)
def test_normalize_folds_punctuation_and_whitespace(raw: str, expected: str) -> None:
    assert normalize(raw) == expected


def test_normalize_does_not_strip() -> None:
    """The shared core must NOT strip: reversibility of interior slices depends on every
    normalized character (including a leading/trailing collapsed space) having a raw span.
    Stripping is a target-prep concern owned by the callers, not the index.
    """
    assert normalize("  a  ") == " a "


def test_normalize_is_idempotent() -> None:
    """Documented + symmetric: normalizing an already-normalized string is a no-op."""
    for raw in ["a b", "it's a \"quote\" - dash", " a ", _CAFE_NFC]:
        assert normalize(normalize(raw)) == normalize(raw)


def test_normalize_composes_to_nfc() -> None:
    """Composed and decomposed accents must both collapse to NFC (the matching default)."""
    assert normalize(_CAFE_NFD) == _CAFE_NFC
    assert normalize(_CAFE_NFC) == _CAFE_NFC
    assert unicodedata.is_normalized("NFC", normalize(_CAFE_NFD))


def test_shared_normalize_does_not_touch_middle_dot() -> None:
    """Middle-dot folding is PDF-delegate-only. The surface-neutral core leaves `·` alone;
    folding it here would silently loosen EPUB matching on legitimate `·` content.
    """
    assert normalize("o·clock") == "o·clock"


# ---------------------------------------------------------------------------
# NormalizedText — reversible offset mapping
# ---------------------------------------------------------------------------


def test_text_property_equals_normalize() -> None:
    nt = NormalizedText("curly ‘q’  x")
    assert nt.text == normalize("curly ‘q’  x") == "curly 'q' x"
    assert nt.raw == "curly ‘q’  x"


# A base letter carrying a combining mark of a LOWER canonical class than the mark already
# baked into its precomposed form.  NFC reorders the marks into canonical order, which makes
# the source positions of one output character's code points NON-CONTIGUOUS — the case a
# decompose-then-re-chunk offset map gets wrong.  "â" (U+00E2 = a + U+0302, class 230) + U+0324
# (class 220) is the canonical trigger; these stay precomposed under NFC (verified below).
_REORDER_NFD = "â̤"  # â + combining diaeresis-below
_REORDER_NFD_2 = "ọ́"  # o + acute (230) + dot-below (220): NFC reorders + composes
assert unicodedata.is_normalized("NFC", _REORDER_NFD)


@pytest.mark.parametrize(
    "raw",
    [
        "plain text",
        "a  b   c",  # collapsed whitespace runs
        "it’s an en–dash",  # folded punctuation (1:1)
        "  leading and trailing  ",
        _CAFE_NFD + " x",  # THE landmine: length-changing NFC
        _CAFE_NFC + " x",
        "déjà—vu with ‘quotes’",  # decomposed accents + folds together
        _REORDER_NFD,  # combining-mark canonical REORDERING across source positions
        _REORDER_NFD_2,
        "x " + _REORDER_NFD + " y",  # reordering not at the string boundary
    ],
)
def test_reversible_every_slice_renormalizes_to_indexed_text(raw: str) -> None:
    """The core contract: for every normalized [s, e), slicing the raw span and renormalizing
    yields exactly the indexed substring.  This holds for length-changing NFC only if each
    normalized char maps to a raw half-open span (not a bare start index), AND holds under
    canonical combining-mark reordering only if the map is computed by prefix alignment rather
    than by re-chunking a reordered decomposition (which mis-attributes marks across source
    positions — see the _REORDER_NFD cases).
    """
    nt = NormalizedText(raw)
    t = nt.text
    for s in range(len(t) + 1):
        for e in range(s, len(t) + 1):
            span = nt.raw_span(s, e)
            assert isinstance(span, RawSpan)
            assert 0 <= span.start <= span.end <= len(raw)
            assert normalize(raw[span.start : span.end]) == t[s:e], (
                f"raw_span({s},{e}) = {span} over raw={raw!r}: "
                f"raw slice {raw[span.start:span.end]!r} renormalizes to "
                f"{normalize(raw[span.start:span.end])!r}, expected {t[s:e]!r}"
            )


def test_raw_span_survives_combining_mark_reordering() -> None:
    """Focused regression for the canonical-reordering defect (P2-T1 Opus review B1).

    'â' (precomposed) followed by a lower-class combining mark stays two NFC characters that
    map 1:1 to their two source code points.  A map that decomposes 'â' into a + U+0302, canon-
    ically reorders the intervening U+0324, then re-chunks by NFD length attributes the wrong
    source span to each output character.
    """
    raw = _REORDER_NFD  # â + U+0324, already NFC, 2 code points
    nt = NormalizedText(raw)
    assert nt.text == raw  # NFC leaves it unchanged: still two characters
    assert nt.raw_span(0, 1) == RawSpan(0, 1)  # 'â' -> just the precomposed code point
    assert nt.raw_span(1, 2) == RawSpan(1, 2)  # U+0324 -> just the mark
    assert normalize(raw[0:1]) == nt.text[0:1]
    assert normalize(raw[1:2]) == nt.text[1:2]


def test_raw_span_is_smallest_covering_for_collapsed_whitespace() -> None:
    """'a  b' -> 'a b'; the raw span for the whole normalized string covers both spaces."""
    nt = NormalizedText("a  b")
    assert nt.text == "a b"
    assert nt.raw_span(0, 3) == RawSpan(0, 4)


def test_raw_span_recovers_the_combining_mark() -> None:
    """The accent case made concrete: the single composed 'é' maps back to BOTH raw code
    points (base 'e' + combining acute), so the recovered source keeps the book's typography.
    """
    raw = _CAFE_NFD  # c a f e ´  (5 code points)
    nt = NormalizedText(raw)
    assert nt.text == _CAFE_NFC  # c a f é  (4 code points)
    e_span = nt.raw_span(3, 4)  # the 'é'
    assert raw[e_span.start : e_span.end] == raw[3:5]  # 'e' + combining acute


def test_empty_and_boundary_spans() -> None:
    nt = NormalizedText("abc")
    assert nt.text == "abc"
    empty = nt.raw_span(1, 1)
    assert empty.start == empty.end
    assert nt.raw_span(0, 3) == RawSpan(0, 3)


def test_empty_input() -> None:
    nt = NormalizedText("")
    assert nt.text == ""
    assert nt.find_all("x") == []


# ---------------------------------------------------------------------------
# find_all — bounded literal candidate search; occurrence identity
# ---------------------------------------------------------------------------


def test_find_all_returns_every_occurrence_ordered_and_distinct() -> None:
    """Repeated occurrences are NOT collapsed (the AUD/#13 root cause).  They come back as
    distinct raw spans in source order.
    """
    nt = NormalizedText("cauldron here and cauldron there")
    spans = nt.find_all("cauldron")
    assert len(spans) == 2
    assert spans[0].start < spans[1].start
    for span in spans:
        assert nt.raw[span.start : span.end] == "cauldron"


def test_find_all_needle_is_normalized_before_search() -> None:
    """A straight-quote needle finds curly source, and vice versa (smart-quote symmetry)."""
    nt = NormalizedText("the potion’s color")  # curly apostrophe in source
    spans = nt.find_all("potion's")  # straight apostrophe in needle
    assert len(spans) == 1
    assert nt.raw[spans[0].start : spans[0].end] == "potion’s"


def test_find_all_across_collapsed_whitespace() -> None:
    """A needle matches source whose whitespace was collapsed; the raw span spans the run."""
    nt = NormalizedText("draught  of   living death")
    spans = nt.find_all("draught of living")
    assert len(spans) == 1
    assert normalize(nt.raw[spans[0].start : spans[0].end]) == "draught of living"


def test_find_all_matches_the_composed_accent() -> None:
    nt = NormalizedText("a " + _CAFE_NFD + " b")  # decomposed source
    spans = nt.find_all(_CAFE_NFC)  # composed needle
    assert len(spans) == 1


def test_find_all_is_literal_not_regex() -> None:
    """No regex construction: metacharacters in the needle are matched literally."""
    nt = NormalizedText("abc axc a.c")
    spans = nt.find_all("a.c")
    assert len(spans) == 1
    assert nt.raw[spans[0].start : spans[0].end] == "a.c"


def test_find_all_overlapping_rule_is_non_overlapping_earliest_first() -> None:
    """One documented rule: non-overlapping, earliest-first.  'aa' in 'aaaa' -> 2 matches
    at 0 and 2, not 3 overlapping ones.
    """
    nt = NormalizedText("aaaa")
    spans = nt.find_all("aa")
    assert [(s.start, s.end) for s in spans] == [(0, 2), (2, 4)]


def test_find_all_rejects_blank_needle() -> None:
    nt = NormalizedText("some text")
    for blank in ["", "   ", "\t"]:
        with pytest.raises(ValueError):
            nt.find_all(blank)


def test_find_all_rejects_over_limit_needle() -> None:
    nt = NormalizedText("some text")
    with pytest.raises(ValueError):
        nt.find_all("x" * (MAX_NEEDLE_CHARS + 1))


def test_constructor_rejects_over_limit_input() -> None:
    with pytest.raises(ValueError):
        NormalizedText("x" * (MAX_INPUT_CHARS + 1))


def test_limits_are_explicit_positive_ints() -> None:
    assert isinstance(MAX_INPUT_CHARS, int) and MAX_INPUT_CHARS > 0
    assert isinstance(MAX_NEEDLE_CHARS, int) and MAX_NEEDLE_CHARS > 0
    assert MAX_NEEDLE_CHARS <= MAX_INPUT_CHARS


# The compatibility-delegate byte-identity guards live in tests/test_normalization_delegates.py
# so they can run (green) independently of this module, which does not exist until Codex builds.
