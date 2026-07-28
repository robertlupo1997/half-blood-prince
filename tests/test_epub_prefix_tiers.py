"""Tests for EPUB prefix-tier matching in ``locate_across_nodes``.

These tests were written after the policy change that added prefix-tier
acceptance to ``locate_across_nodes`` (EPUB locator).  Before the change
(tier-0-only), the first class of tests would return ``None``.  They were
confirmed RED at baseline by stashing the ``epub.py`` change, running only
this file, and observing failures.

Policy summary (see also ``docs/decisions/verbatim-quoting-prompt-vs-matcher.md``):

* When every tier-0 rung (EXACT → CASE_INSENSITIVE → PUNCTUATION_ELASTIC) finds
  nothing, the locator falls back to multi-word prefix tiers (8-word → 5-word →
  3-word) under EXACT matching.
* The lone-word tier is always rejected: it can land anywhere inside a passage,
  which the reader cannot interpret.
* A prefix anchor starts where the passage starts, so the underline is shorter than
  the note's full quote but still directs the reader to the right words.
* A complete-quote match at ANY tolerance rung always beats a prefix match.
* Ambiguity or multiple hits at the prefix level halts and returns ``None`` — never
  loosens further.

Governing principle: a wrong anchor is worse than no annotation.
"""

from __future__ import annotations

from bs4 import BeautifulSoup, Tag

from halfblood.documents import CrossNodeMatch, locate_across_nodes, selector_for
from halfblood.documents.epub import _scan_prefix_tiers
from halfblood.models.annotations import TargetSelector


def _body(xhtml: str) -> Tag:
    body = BeautifulSoup(
        f'<html xmlns="http://www.w3.org/1999/xhtml"><body>{xhtml}</body></html>',
        "lxml",
    ).body
    assert body is not None
    return body


def _text_of(match: CrossNodeMatch) -> str:
    return "".join(str(seg.node)[seg.start : seg.end] for seg in match.segments)


def _sel(exact: str) -> TargetSelector:
    return TargetSelector(exact=exact)


# ---------------------------------------------------------------------------
# 1. Prefix tiers are accepted when the complete quote is absent
# ---------------------------------------------------------------------------


class TestPrefixAccepted:
    """A multi-word prefix found in the source resolves even when the full quote does not."""

    def test_5_word_prefix_resolves_when_full_quote_drops_interior_words(self) -> None:
        """Classic OCR-paraphrase case: model dropped an interior attribution.

        The model wrote ``Utterson, I swear to God, I swear to God…`` while the
        source has ``Utterson, I swear to God," cried the doctor, "I swear to God…``.
        The full quote never matches; the 5-word prefix (tier 2) does, and it starts
        at position 0 of the source passage.

        RED at baseline (tier-0 only): returns ``None``.
        GREEN after prefix-tier change: returns a ``CrossNodeMatch``.
        """
        body = _body(
            '<p>Utterson, I swear to God," cried the doctor, "I swear to God I '
            "will never set eyes on him again.</p>"
        )
        match = locate_across_nodes(
            body,
            selector_for(
                "Utterson, I swear to God, I swear to God I will never set "
                "eyes on him again."
            ),
        )
        assert isinstance(match, CrossNodeMatch)

    def test_prefix_anchor_starts_at_passage_start(self) -> None:
        """A prefix anchor must start at the passage's beginning (position 0 in node)."""
        body = _body("<p>The quick brown fox jumps over the lazy dog entirely.</p>")
        # Full quote has a trailing word that isn't in the source; prefix should match.
        match = locate_across_nodes(
            body,
            selector_for("The quick brown fox jumps over the lazy dog entirely and away"),
        )
        assert isinstance(match, CrossNodeMatch)
        assert match.segments[0].start == 0

    def test_8_word_prefix_resolves(self) -> None:
        """8-word prefix tier (tier 1) is accepted."""
        source = "One two three four five six seven eight and then some more words."
        body = _body(f"<p>{source}</p>")
        # Selector has an extra word not in source; 8-word prefix must match.
        match = locate_across_nodes(
            body,
            selector_for("One two three four five six seven eight MISSING"),
        )
        assert isinstance(match, CrossNodeMatch)
        assert _text_of(match) == "One two three four five six seven eight"

    def test_3_word_prefix_resolves(self) -> None:
        """3-word prefix tier (tier 3) is accepted when shorter tiers also fail."""
        source = "Alpha beta gamma and then very different words follow."
        body = _body(f"<p>{source}</p>")
        # Selector's 5-word and 8-word prefixes are absent; 3-word prefix is present.
        match = locate_across_nodes(
            body,
            selector_for("Alpha beta gamma MISSING MISSING MISSING MISSING MISSING MISSING"),
        )
        assert isinstance(match, CrossNodeMatch)
        assert _text_of(match) == "Alpha beta gamma"

    def test_prefix_resolves_across_inline_tags(self) -> None:
        """Prefix matching composes with cross-node run collection."""
        body = _body(
            "<p>The <em>sopophorous</em> bean must be crushed, <strong>not cut</strong>.</p>"
        )
        # Full quote has a wrong ending; the 3-word prefix spans inline boundaries.
        match = locate_across_nodes(
            body,
            selector_for(
                "The sopophorous bean must be TOTALLY WRONG ENDING HERE NOW"
            ),
        )
        assert isinstance(match, CrossNodeMatch)
        assert len({id(seg.node) for seg in match.segments}) >= 2


# ---------------------------------------------------------------------------
# 2. Lone-word tier is always rejected
# ---------------------------------------------------------------------------


class TestLoneWordRejected:
    """The lone-word tier is the only tier that can land anywhere in a passage.

    It is structurally rejected regardless of whether a prefix tier succeeds.
    """

    def test_lone_word_is_rejected_when_no_prefix_matches(self) -> None:
        """When only the longest single word matches, the result is None.

        RED at baseline (tier-0 only): also ``None``, but for the wrong reason
        (tier-0 absent).  GREEN after the prefix change: still ``None``, correctly
        because the lone-word tier is rejected.
        """
        # Source contains "bezoar" but not "the bezoar stone works" or any prefix.
        body = _body("<p>The bezoar saved his life.</p>")
        # Selector has prefix words absent from source; only "bezoar" remains.
        assert (
            locate_across_nodes(
                body,
                selector_for("the bezoar stone works perfectly well in every case"),
            )
            is None
        )

    def test_lone_word_rejected_via_public_api_when_guard_fires(self) -> None:
        """The lone-word guard fires through ``locate_across_nodes``.

        Source: ``A remarkable day indeed.`` — only the longest word
        ``remarkable`` (last tier in the exactness ladder) is present; all
        multi-word prefix tiers (``the remarkable stone``, etc.) are absent.

        In ``_scan_prefix_tiers`` the tier loop checks ``len(needle.split()) < 2``
        before searching.  When the needle is ``remarkable`` (1 word) the loop
        breaks without ever doing an overlapping scan.  Removing that guard would
        allow the lone-word search to run: one occurrence of ``remarkable`` would
        be found and a ``CrossNodeMatch`` would be returned.  With the guard the
        result is ``None``.

        Mutation test: comment out ``if len(needle.split()) < 2: break`` in
        ``_scan_prefix_tiers`` — this test fails.
        """
        body = _body("<p>A remarkable day indeed.</p>")
        # Selector: prefix tiers ("the remarkable stone", etc.) are all absent
        # from the source ("A remarkable"), so only "remarkable" (lone word) fires.
        match = locate_across_nodes(
            body,
            selector_for("the remarkable stone works perfectly"),
        )
        assert match is None

    def test_returns_none_when_only_lone_word_remains_in_source(self) -> None:
        """When no multi-word prefix exists in source the result is None.

        Source: ``The bezoar helped. Later the bezoar saved him.``
        Selector: ``the bezoar stone works well every time you try it``

        Multi-word prefix tiers (``the bezoar stone works well``,
        ``the bezoar stone``) are absent (source has ``the bezoar``, not
        ``the bezoar stone``).  The lone-word tier (``bezoar``) is then
        structurally rejected before it is ever searched — the ``break`` in the
        tier loop fires.  The fact that ``bezoar`` appears twice in the source
        is irrelevant; the code never reaches an overlapping scan for it.
        """
        body = _body(
            "<p>The bezoar helped. Later the bezoar saved him.</p>"
        )
        assert (
            locate_across_nodes(
                body,
                selector_for("the bezoar stone works well every time you try it"),
            )
            is None
        )

    def test_two_word_prefix_is_accepted_lone_word_is_not(self) -> None:
        """The lone-word rejection predicate boundary: ``len(matched.split()) < 2``.

        Direct unit-test via ``_scan_prefix_tiers``: a run whose only tier with
        a hit is the lone-word tier must produce zero hits from the scan.
        """
        # A run containing only the word "bezoar".  The selector has "bezoar" as
        # its longest single word (lone-word tier); all multi-word prefix tiers are
        # absent.  The scan must reject it and return an empty hit list.
        body_lone = _body("<p>bezoar</p>")
        sel_lone = _sel("bezoar is the answer to every poison")
        _, hits = _scan_prefix_tiers(body_lone, sel_lone)
        assert hits == []  # lone word "bezoar" must be rejected


# ---------------------------------------------------------------------------
# 3. Complete-quote match beats prefix
# ---------------------------------------------------------------------------


class TestCompleteQuoteBeatPrefix:
    """A full-quote match at any tolerance rung must win over an available prefix.

    The two phases (complete-quote, then prefix) are ordered and never pooled.
    """

    def test_exact_full_quote_beats_prefix(self) -> None:
        """When the exact full quote is present, the prefix phase is not reached."""
        source = "The bezoar stone works perfectly well."
        body = _body(f"<p>{source}</p>")
        match = locate_across_nodes(body, selector_for("The bezoar stone works"))
        assert isinstance(match, CrossNodeMatch)
        assert _text_of(match) == "The bezoar stone works"

    def test_ci_full_quote_beats_prefix(self) -> None:
        """A CASE_INSENSITIVE full-quote match wins over an EXACT prefix match.

        If the implementation nests phases wrong (outer=tolerance, inner=tier),
        an EXACT prefix match would beat a CI full-quote match.  This test proves
        the outer loop is exactness-phase, not tolerance.
        """
        # Source has "The Bezoar Stone Works" (capitalised).
        # Selector: "the bezoar stone works" — fails EXACT (tier 0), but matches
        # CASE_INSENSITIVE (tier 0).  A wrong nesting would return the EXACT prefix
        # "the bezoar stone" instead.
        body = _body(
            "<p>The Bezoar Stone Works perfectly well.</p>"
        )
        # The complete selector "the bezoar stone works" is 4 words.
        # Tier 0 under CI should match "The Bezoar Stone Works".
        match = locate_across_nodes(body, selector_for("the bezoar stone works"))
        assert isinstance(match, CrossNodeMatch)
        # The CI full-quote match covers all 4 words (tier 0), not just a prefix.
        assert len(_text_of(match).split()) == 4

    def test_ci_full_quote_beats_exact_prefix_discriminating(self) -> None:
        """CI full-quote must win even when an EXACT prefix hit is also present.

        Source:   ``the bezoar stone works Perfectly well.``  (capital P)
        Selector: ``the bezoar stone works perfectly``        (lowercase p)

        What each phase sees:

        *   Phase 1, EXACT — ``score_candidates(EXACT)`` finds ``the bezoar
            stone`` (tier 1, 3-word prefix) but ``_scan_with_tolerance`` discards
            it because ``exactness_tier != 0``.  Clean zero.
        *   Phase 1, CI — ``score_candidates(CI)`` finds ``the bezoar stone works
            Perfectly`` (tier 0, full quote, 5 words).  This match is recorded and
            returned.

        A wrong nesting that scans all tiers under EXACT tolerance would find the
        3-word prefix and return it, never reaching the CI scan.  The assertion
        checks that the result contains ``works`` (word 4), which is absent in any
        3-word prefix — so a wrong implementation fails this test.
        """
        body = _body("<p>the bezoar stone works Perfectly well.</p>")
        match = locate_across_nodes(
            body,
            selector_for("the bezoar stone works perfectly"),
        )
        assert isinstance(match, CrossNodeMatch)
        matched = _text_of(match)
        assert "works" in matched, (
            f"Expected full CI quote (≥4 words including 'works') but got {matched!r}; "
            "phase ordering may be wrong (EXACT prefix winning over CI full-quote)"
        )

    def test_punctuation_elastic_full_quote_beats_prefix(self) -> None:
        """A PUNCTUATION_ELASTIC full-quote match wins over an EXACT prefix.

        Proves phase ordering: PE complete-quote must win even though an EXACT
        prefix would be found in phase 2 if phase 1 were skipped.
        """
        source = 'He said, "the bezoar stone works perfectly," and left.'
        body = _body(f"<p>{source}</p>")
        # Model dropped quotes: selector is ``the bezoar stone works perfectly,``
        # EXACT tier 0: no match (source has surrounding quotes).
        # CI tier 0: no match (still has the extra quotes).
        # PE tier 0: matches because quotes at word boundaries are optional.
        # If we fell to phase 2 instead, the prefix "the bezoar stone works" (4 words)
        # would be found — but PE tier 0 must win first.
        match = locate_across_nodes(
            body,
            selector_for("the bezoar stone works perfectly,"),
        )
        assert isinstance(match, CrossNodeMatch)
        # PE match is full-quote (covers all words), not just 4-word prefix.
        anchor = _text_of(match)
        assert "bezoar stone works perfectly" in anchor


# ---------------------------------------------------------------------------
# 4. Ambiguity at prefix level still halts
# ---------------------------------------------------------------------------


class TestPrefixAmbiguityHalts:
    """Ambiguity at the prefix phase must halt immediately and return None."""

    def test_prefix_in_two_runs_is_ambiguous(self) -> None:
        """Two runs both yield the same prefix hit → ambiguous → None.

        If the implementation pooled hits from both runs instead of halting,
        it would return one of two equally valid anchors — the wrong-anchor
        failure this project refuses.

        RED at baseline: also ``None`` (tier-0 only found nothing); the test
        still acts as a specification that ambiguity must halt even at the
        prefix level.
        """
        # Two paragraphs both start with "the bezoar stone" but diverge after.
        # The full quote "the bezoar stone works as expected" is absent from both.
        body = _body(
            "<p>the bezoar stone cures all poisons naturally.</p>"
            "<p>the bezoar stone removes nearly every toxin.</p>"
        )
        assert (
            locate_across_nodes(
                body,
                selector_for("the bezoar stone works as expected"),
            )
            is None
        )

    def test_single_prefix_run_is_not_ambiguous(self) -> None:
        """One run with a prefix hit resolves; ambiguity requires two or more runs."""
        body = _body(
            "<p>the bezoar stone cures all poisons naturally and effectively.</p>"
            "<p>Other herbs may help but never so reliably.</p>"
        )
        match = locate_across_nodes(
            body,
            selector_for("the bezoar stone works as expected everywhere"),
        )
        # Second paragraph has no prefix hit; only the first does → unambiguous.
        assert isinstance(match, CrossNodeMatch)

    def test_overlapping_prefix_positions_are_ambiguous(self) -> None:
        """A prefix that starts at overlapping positions in one run is ambiguous.

        Source: ``alpha alpha alpha alpha elsewhere.``
        Selector prefix (3-word tier): ``alpha alpha alpha``

        Non-overlapping search (``search_from = end``) reports only one
        occurrence starting at position 0 and would wrongly accept it.  The
        overlapping scan (``search_from = start + 1``) finds a second start at
        position 6 and halts: the anchor is ambiguous.

        Regression for BLOCKING 1: the old implementation called
        ``score_candidates`` which uses non-overlapping search internally, so it
        returned the first occurrence as a unique hit and produced a
        ``CrossNodeMatch`` for the wrong position.
        """
        body = _body("<p>alpha alpha alpha alpha elsewhere.</p>")
        match = locate_across_nodes(
            body,
            selector_for("alpha alpha alpha beta gamma delta"),
        )
        assert match is None

    def test_global_tier_unique_tier1_not_discarded_by_tier3_in_other_run(self) -> None:
        """A unique tier-1 hit must not be discarded by a tier-3 hit in a different run.

        Source structure:
          * Run A (first ``<p>``): contains the 8-word prefix of the selector.
          * Run B (second ``<p>``): contains only the 3-word prefix.

        Old pooled-tier code: Run A produced a tier-1 hit; Run B produced a
        tier-3 hit.  Both were added to ``hits``.  ``len(hits) > 1`` → ``None``.
        The valid tier-1 anchor was silently discarded.

        New global-tier code: tier-1 is tried first across ALL runs.  Run A has
        one hit; Run B has zero.  The tier-1 anchor is returned without ever
        looking at tier 3.

        Regression for BLOCKING 2: any code that collects hits per-run (letting
        each run pick its own best tier) will return ``None`` here; the global
        ladder returns the correct ``CrossNodeMatch`` containing ``four`` (word 4,
        present in the 8-word prefix but not in the 3-word prefix).
        """
        # Run A: 8-word prefix is a unique substring.
        # Run B: only the first 3 words of the selector appear.
        body = _body(
            "<p>one two three four five six seven eight ends here.</p>"
            "<p>one two three irrelevant words follow.</p>"
        )
        match = locate_across_nodes(
            body,
            selector_for("one two three four five six seven eight then more words follow"),
        )
        assert isinstance(match, CrossNodeMatch), (
            "Expected CrossNodeMatch — global tier ladder should find unique tier-1 hit "
            "in first paragraph, but pooled-tier code would return None"
        )
        matched = _text_of(match)
        assert "four" in matched, (
            f"Expected tier-1 match (8 words, contains 'four') but got {matched!r}; "
            "tier-3 hit from second paragraph may be interfering"
        )


# ---------------------------------------------------------------------------
# 5. Complete-quote overlapping ambiguity is tolerance-aware
# ---------------------------------------------------------------------------


class TestCompleteQuoteOverlapAware:
    """The overlapping-occurrence guard must use the same comparison semantics as
    the scorer at each tolerance rung.

    Prior to the fix, ``_has_overlapping_exact`` was always called with
    case-sensitive semantics regardless of the active tolerance.  Under
    CASE_INSENSITIVE or PUNCTUATION_ELASTIC a genuinely ambiguous self-overlapping
    quote would slip through the guard, and the scorer's non-overlapping search
    would report a single (wrong) hit.
    """

    def test_ci_overlapping_complete_quote_is_ambiguous(self) -> None:
        """CASE_INSENSITIVE overlapping start positions must halt and return None.

        Source:   ``a a a a``
        Selector: ``A A A``

        The scorer CI-matches ``a a a`` at position 0 (non-overlapping search
        finds only one occurrence).  But with overlapping advance-by-1 the same
        CI pattern starts at position 0 AND position 2 (2 < 0+5 → overlapping).
        The guard must fold both sides with ``_fold_case`` before the check so it
        detects the second start and halts.

        Without the tolerance-aware guard, the call returns a ``CrossNodeMatch``
        for position 0 — a wrong anchor the reader cannot distinguish from a
        correct one (the note discusses some passage, the highlight sits on a
        different one).

        Regression for BLOCKING 3: any code that always checks overlapping
        case-sensitively will return a ``CrossNodeMatch`` here.
        """
        body = _body("<p>a a a a</p>")
        match = locate_across_nodes(body, selector_for("A A A"))
        assert match is None, (
            f"Expected None (overlapping CI positions are ambiguous) but got {match!r}"
        )

    def test_pe_overlapping_complete_quote_is_ambiguous(self) -> None:
        """PUNCTUATION_ELASTIC overlapping start positions must halt and return None.

        Source:   ``foo foo foo.``
        Selector: ``'foo foo'``  (straight apostrophes; PE makes them optional)

        EXACT fails (no apostrophes in source).  CI fails (folded selector still
        has apostrophes the source lacks).  PE builds a regex ``['"]?foo['"]?
        ['"]?foo['"]?`` that matches ``foo foo`` at position 0 (7 chars) AND at
        position 4 (4 < 0+7=7 → overlapping).

        Without the tolerance-aware guard, ``_has_overlapping_exact`` checks
        for the literal ``'foo foo'`` in ``foo foo foo.`` (not found → guard
        passes), and the scorer's ``finditer`` returns the match at position 0
        as a unique hit.

        Regression for BLOCKING 3: any code that does not apply the elastic
        regex for the PE overlap check will return a ``CrossNodeMatch`` here.
        """
        body = _body("<p>foo foo foo.</p>")
        # Selector uses ASCII straight apostrophes (PE normalizes curly quotes).
        match = locate_across_nodes(body, selector_for("'foo foo'"))
        assert match is None, (
            f"Expected None (overlapping PE positions are ambiguous) but got {match!r}"
        )
