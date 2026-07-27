"""P1 — the EPUB locator walks the tolerance ladder strictest-first.

``locate_across_nodes`` is the only door into EPUB anchoring: ``render_plan`` calls it
for pre-resolution (phase 1) and again for re-resolution on the mutated DOM (phase 4),
and ``_epub_miss_reason`` classifies whatever it rejected. Putting the ladder inside the
locator is what keeps all three consistent; a ladder bolted onto one call site would let
phase 1 resolve an annotation that phase 4 then drops.

The rules these tests pin, in order of how badly a naive build gets them wrong:

1. **Strictest tolerance that produces a unique hit wins.** An exact match anywhere in
   the chapter must beat a looser match elsewhere — otherwise a note migrates to a
   different sentence the moment the ladder is switched on.

2. **Ambiguity halts the ladder; it does not fall through.** If the exact pass finds the
   quote twice, the answer is "skip", not "try again with a looser matcher". A quote
   that is ambiguous exactly is *more* ambiguous under case- and quote-elasticity, and
   falling through is precisely how a note lands on the wrong occurrence.

3. **Hits from different tolerances are never pooled.** Each rung is evaluated across
   every inline run on its own; one exact hit plus one elastic hit is one answer (the
   exact one), not two candidates.

4. **Complete-quote (tier 0) always beats a prefix tier.**  The locator runs a
   complete-quote phase (EXACT → CASE_INSENSITIVE → PUNCTUATION_ELASTIC) before
   falling back to prefix tiers.  A PUNCTUATION_ELASTIC full-quote match therefore
   always wins over an EXACT prefix match — the phases are never pooled.

5. **Multi-word prefix tiers are accepted; the lone-word tier is rejected.**  When
   every tier-0 rung finds nothing, the locator tries shortened prefix tiers
   (8-word → 5-word → 3-word) under EXACT matching.  The lone-word tier (which
   can land anywhere inside the passage) is always rejected.  A prefix anchor
   underlines less than the note's full quote but starts at the right position, so
   the reader is still directed to the correct words.

Real-book grounding: with the tolerance ladder plus prefix tiers, the scanned
Jekyll & Hyde run goes from 53 rendered / 35 skipped (baseline) to 84 / 4.  The
clean corpus goes from 44 / 6 (tolerance ladder only) to 48 / 2 — see
``tests/test_match_tolerance.py`` for the raw diff attribution of those six.
"""

from __future__ import annotations

from bs4 import BeautifulSoup, Tag

from halfblood.documents import CrossNodeMatch, locate_across_nodes, selector_for


def _body(xhtml: str) -> Tag:
    body = BeautifulSoup(
        f'<html xmlns="http://www.w3.org/1999/xhtml"><body>{xhtml}</body></html>', "lxml"
    ).body
    assert body is not None
    return body


def _text_of(match: CrossNodeMatch) -> str:
    return "".join(str(seg.node)[seg.start : seg.end] for seg in match.segments)


class TestLadderRecoversRealFailures:
    def test_case_drift_resolves(self) -> None:
        """Real ch8 skip: model wrote ``the death``, book has ``The death``."""
        body = _body("<p>The death of Sir Danvers was more than paid for.</p>")
        match = locate_across_nodes(body, selector_for("the death of Sir Danvers"))
        assert isinstance(match, CrossNodeMatch)
        assert _text_of(match) == "The death of Sir Danvers"

    def test_dropped_internal_quote_resolves(self) -> None:
        """Real ch7 skip: model dropped the quote marks around the dialogue."""
        body = _body(
            '<p>Poole was positive nothing had come except by post; '
            '"and only circulars by that," he added.</p>'
        )
        match = locate_across_nodes(
            body,
            selector_for(
                "except by post; and only circulars by that, he added."
            ),
        )
        assert isinstance(match, CrossNodeMatch)
        assert _text_of(match) == (
            'except by post; "and only circulars by that," he added.'
        )

    def test_recovery_still_spans_inline_tags(self) -> None:
        """The ladder must compose with cross-node runs, not bypass them."""
        body = _body(
            '<p>Begin: The <em>sopophorous</em> bean must be '
            '<strong>crushed</strong>, not cut.</p>'
        )
        match = locate_across_nodes(
            body, selector_for("the sopophorous bean must be crushed")
        )
        assert isinstance(match, CrossNodeMatch)
        assert len({id(segment.node) for segment in match.segments}) >= 2
        assert _text_of(match) == "The sopophorous bean must be crushed"


class TestLadderStaysFailClosed:
    def test_exact_ambiguity_does_not_fall_through(self) -> None:
        """Two exact occurrences: skip. Never retry looser and pick one.

        The halt rule is "advance only on a clean zero" — a rung that produces
        ambiguity *or* more than one hit ends the ladder immediately.
        """
        body = _body(
            "<p>the bezoar is here.</p><p>Later the bezoar is there.</p>"
        )
        assert locate_across_nodes(body, selector_for("the bezoar is")) is None

    def test_ambiguity_at_a_loose_rung_also_skips(self) -> None:
        """No exact hit, but two case-variant hits: still skip."""
        body = _body("<p>The Bezoar Stone works.</p><p>the bezoar stone works.</p>")
        assert locate_across_nodes(body, selector_for("THE BEZOAR STONE works")) is None

    def test_dropped_word_is_not_recovered(self) -> None:
        """Real ch4 skip. Fuzzy would anchor inside ``mere``; the ladder must not."""
        body = _body(
            "<p>or is it the mere radiance of a foul soul that thus transpires?</p>"
        )
        assert (
            locate_across_nodes(
                body, selector_for("the radiance of a foul soul that thus transpires")
            )
            is None
        )

    def test_dropped_interior_words_without_a_prefix_match_are_not_recovered(self) -> None:
        """When the model dropped a word from the interior AND the prefix also fails, skip.

        Old test name: ``test_paraphrase_is_not_recovered``.  The former fixture
        (Utterson / cried the doctor) is now recovered via prefix tier, because
        the first five words of the model's quote appear verbatim at the start of the
        source passage.  That IS a correct anchor.  This test uses a case where even
        the 3-word prefix is absent from the source: the model wrote "radiance" but
        the source has "mere radiance", so no prefix tier matches.
        """
        body = _body(
            "<p>or is it the mere radiance of a foul soul that thus transpires?</p>"
        )
        assert (
            locate_across_nodes(
                body,
                selector_for("the radiance of a foul soul that thus transpires"),
            )
            is None
        )

    def test_partial_prefix_recovered_even_when_full_quote_drops_interior_words(self) -> None:
        """Real ch7 case: model dropped attribution mid-quote; prefix still anchors.

        The model wrote ``Utterson, I swear to God, I swear to God…`` while the
        source has ``Utterson, I swear to God," cried the doctor, "I swear to God…``.
        The first five words of the model's quote appear verbatim at position 0 of the
        source paragraph, so the 5-word prefix is a valid anchor: it points the reader
        to the right words even though the underline is shorter than the note's quote.

        This test was previously ``test_paraphrase_is_not_recovered``; the old
        assertion of ``None`` pinned the tier-0-only policy.  That policy changed.
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
        # The anchor must start where the passage starts (position 0 in the node).
        assert match.segments[0].start == 0
        # The anchor must be a multi-word prefix, not a lone word.
        anchor_text = _text_of(match)
        assert len(anchor_text.split()) >= 2

    def test_still_never_crosses_a_block_boundary(self) -> None:
        """Block-boundary rule: the locator can find a prefix *within* a block but
        never assembles a match by collecting text from two separate block elements.

        When the full quote spans two blocks, the locator falls to the prefix phase
        and finds the prefix within the *first* block — which is correct and is NOT
        crossing a boundary.  A test case where no prefix exists in any single block
        confirms the true cross-boundary case still returns None.
        """
        # Case 1: prefix exists in the first block → prefix is found (no crossing).
        body_with_prefix = _body(
            "<p>the sopophorous bean must be</p><p>crushed without delay</p>"
        )
        match = locate_across_nodes(
            body_with_prefix, selector_for("the sopophorous bean must be crushed")
        )
        assert isinstance(match, CrossNodeMatch)
        assert match.segments[0].start == 0  # anchored at passage start

        # Case 2: quote spans two blocks AND no prefix exists in any single block.
        # "must be" alone never completes to a 3-word prefix; "crushed not cut…"
        # in the second block doesn't start the quote. The longest single word
        # ("crushed") is rejected by the lone-word rule. Result: None.
        body_no_prefix = _body(
            "<p>must be</p><p>crushed not cut without delay</p>"
        )
        assert (
            locate_across_nodes(
                body_no_prefix, selector_for("must be crushed not cut without delay")
            )
            is None
        )


class TestStrictestRungWins:
    def test_exact_hit_beats_a_loose_hit_elsewhere(self) -> None:
        """An exact occurrence and a case-variant occurrence: the exact one wins.

        If the implementation pooled hits across rungs it would see two candidates
        and skip; if it ran only the loosest rung it would see two and skip. Either
        way this annotation would be lost, so a returned match proves rung isolation.
        """
        body = _body(
            "<p>The Bezoar Stone works.</p><p>the bezoar stone works.</p>"
        )
        match = locate_across_nodes(body, selector_for("the bezoar stone works"))
        assert isinstance(match, CrossNodeMatch)
        assert _text_of(match) == "the bezoar stone works"

    def test_exact_hit_is_unaffected_by_a_quote_variant_elsewhere(self) -> None:
        body = _body(
            '<p>He said stir it now.</p><p>He said "stir it" now.</p>'
        )
        match = locate_across_nodes(body, selector_for("He said stir it now."))
        assert isinstance(match, CrossNodeMatch)
        assert _text_of(match) == "He said stir it now."
