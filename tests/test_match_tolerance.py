"""P1 — Recover EPUB annotations lost to non-verbatim model quoting.

Measured on the real Jekyll & Hyde run: 6 of 50 annotations (12%) were skipped, all
``SkipReason.MISSING_TARGET``, zero ambiguous. Raw character diffs against the source
chapters attribute them as:

===========================  ==================================================
diff class                   count / example
===========================  ==================================================
case only                    1 — model wrote ``the death of Sir Danvers``,
                                 book has ``The death of Sir Danvers``
internal quote dropped       2 — model wrote ``post; and only``,
                                 book has ``post; "and only``
leading quote *added*        1 — model wrote ``"I have brought``,
                                 book has `` I have brought``
word dropped                 1 — model wrote ``the radiance``,
                                 book has ``the mere radiance``
dialogue attribution dropped 1 — model wrote ``to God, I swear``,
                                 book has ``to God," cried the doctor, "I swear``
===========================  ==================================================

The first four are surface drift and are recovered here by a **tolerance ladder** with
exact semantics — no edit distance, no similarity threshold, no ratio to defend at n=4.
The last two are genuine paraphrases: the model produced text the book does not contain.
They are deliberately NOT recovered. A fuzzy matcher would anchor the ``radiance`` note
to a span beginning in the middle of the word ``mere``; a note anchored to the wrong
words is worse than a missing note because the reader cannot detect it (the lane-D
fail-closed precedent). Prompt hardening, not matching, is the lever for those two.

Design constraints pinned by these tests — each is a place a naive build goes wrong:

1. **``MatchTolerance.EXACT`` is the default and is byte-identical to today.** Every
   existing caller keeps its current behaviour; the ladder is strictly additive.
2. **Looser tolerances are opt-in per call, tried strictest-first by the caller.** The
   exactness-tier ladder inside a single call is unchanged and still means "shortened
   fallback quote", so ``exactness_tier == 0`` keeps meaning "the complete quote" and
   the EPUB DOM-range contract keeps working untouched.
3. **Case folding must be length-preserving.** ``str.casefold()`` turns ``ß`` into
   ``ss`` and ``İ`` into two code points, which desynchronises every raw span after it.
   Characters whose lowering changes length are left alone on purpose.
4. **Elastic means quotes only, and only at word boundaries.** ``'`` inside a word
   (``don't``) stays literal; other punctuation (``;`` vs ``:``) stays literal.
5. **Ambiguity is still fail-closed.** A looser tolerance that finds two candidates
   returns ``AmbiguousResult``; it never guesses the first.

All fixtures are in-memory. No file I/O, no EPUB, no LLM calls.
"""

from __future__ import annotations

import pytest

from halfblood.documents import (
    AmbiguousResult,
    MatchResult,
    MatchTolerance,
    NoMatchResult,
    NormalizedText,
    score_candidates,
)
from halfblood.models.annotations import TargetSelector


def _sel(exact: str) -> TargetSelector:
    return TargetSelector(exact=exact)


def _matched(text: str, outcome: object) -> str:
    """Return the raw source substring a MatchResult selected."""
    assert isinstance(outcome, MatchResult), outcome
    span = outcome.candidate.raw_span
    return text[span.start : span.end]


# ---------------------------------------------------------------------------
# 1. The default is unchanged
# ---------------------------------------------------------------------------


class TestDefaultToleranceIsExact:
    """The ladder is additive: omitting ``tolerance`` must not change anything."""

    def test_default_matches_explicit_exact(self) -> None:
        text = NormalizedText("The death of Sir Danvers was avenged.")
        selector = _sel("death of Sir Danvers")
        assert isinstance(score_candidates(selector, text), MatchResult)
        assert isinstance(
            score_candidates(selector, text, tolerance=MatchTolerance.EXACT),
            MatchResult,
        )

    def test_default_gains_no_case_tolerance(self) -> None:
        """A case-drifted quote must not produce a tier-0 (complete-quote) match.

        Asserted as "no tier 0" rather than "NoMatchResult" on purpose: under
        ``EXACT`` the shortened-tier ladder still fires and anchors to the word
        ``death`` (tier 2). That is pre-existing, PDF-only behaviour — see
        :class:`TestShortenedTierFallbackIsUnchanged`. What must not happen is
        the *full quote* silently matching across a case difference, because
        ``locate_across_nodes`` accepts tier 0 and would then render it.
        """
        text = NormalizedText("The death of Sir Danvers was avenged.")
        outcome = score_candidates(_sel("the death of Sir"), text)
        assert not (
            isinstance(outcome, MatchResult) and outcome.candidate.exactness_tier == 0
        )

    def test_default_gains_no_quote_tolerance(self) -> None:
        text = NormalizedText('by post; "and only circulars by that," he added.')
        outcome = score_candidates(
            _sel("by post; and only circulars by that, he added."), text
        )
        assert not (
            isinstance(outcome, MatchResult) and outcome.candidate.exactness_tier == 0
        )

    def test_default_still_misses_entirely_when_no_tier_matches(self) -> None:
        """With every tier case-drifted, the default still returns NoMatchResult."""
        text = NormalizedText("The Bezoar Stone Works Reliably.")
        assert isinstance(
            score_candidates(_sel("the bezoar stone works"), text), NoMatchResult
        )

    def test_legacy_exact_only_ignores_tolerance(self) -> None:
        """Legacy mode is a separate contract and stays exact regardless."""
        text = NormalizedText("The death of Sir Danvers was avenged.")
        outcome = score_candidates(
            _sel("the death of Sir"),
            text,
            legacy_exact_only=True,
            tolerance=MatchTolerance.PUNCTUATION_ELASTIC,
        )
        assert isinstance(outcome, NoMatchResult)


class TestShortenedTierFallbackIsUnchanged:
    """Pin the pre-existing ``EXACT`` shortened-tier behaviour against drive-by "fixes".

    When the full quote misses, ``EXACT`` walks 8-word → 5-word → 3-word → longest
    single word and anchors to the first tier that hits. On a case- or quote-drifted
    target that means anchoring to one word: ``death``, ``circulars``.

    That is a poor anchor, and it is tempting to "fix" it while implementing the
    tolerance ladder — an earlier build of this feature did exactly that. It is out of
    scope here for two reasons. It only affects the PDF path (``document_processor``
    passes ``EXACT``; the EPUB locator rejects every tier but 0), and narrowing it
    changes which PDF annotations render, which needs its own measurement on a real
    PDF. Recorded in the roadmap as a separate item. These tests exist so that change
    is deliberate rather than a side effect.
    """

    def test_case_drift_still_falls_back_to_the_longest_word(self) -> None:
        source = "The death of Sir Danvers was avenged."
        outcome = score_candidates(_sel("the death of Sir"), NormalizedText(source))
        assert isinstance(outcome, MatchResult)
        assert outcome.candidate.exactness_tier > 0
        assert _matched(source, outcome) == "death"

    def test_quote_drift_still_falls_back_to_the_longest_word(self) -> None:
        source = 'by post; "and only circulars by that," he added.'
        outcome = score_candidates(
            _sel("by post; and only circulars by that, he added."),
            NormalizedText(source),
        )
        assert isinstance(outcome, MatchResult)
        assert outcome.candidate.exactness_tier > 0
        assert _matched(source, outcome) == "circulars"

    def test_a_genuinely_absent_quote_still_uses_the_prefix_tier(self) -> None:
        source = "Crush the sopophorous bean thoroughly before adding the root."
        outcome = score_candidates(
            _sel("Crush the sopophorous bean thoroughly before adding a wholly other thing"),
            NormalizedText(source),
        )
        assert isinstance(outcome, MatchResult)
        assert outcome.candidate.exactness_tier > 0


# ---------------------------------------------------------------------------
# 2. Case-insensitive tolerance — the real ch8 failure
# ---------------------------------------------------------------------------


class TestCaseInsensitiveTolerance:
    REAL_CHAPTER = (
        "The death of Sir Danvers was, to his way of thinking, more than paid "
        "for by the disappearance of Mr. Hyde."
    )
    REAL_TARGET = (
        "the death of Sir Danvers was, to his way of thinking, more than paid "
        "for by the disappearance of Mr. Hyde"
    )

    def test_recovers_the_real_ch8_skip(self) -> None:
        text = NormalizedText(self.REAL_CHAPTER)
        outcome = score_candidates(
            _sel(self.REAL_TARGET), text, tolerance=MatchTolerance.CASE_INSENSITIVE
        )
        assert _matched(self.REAL_CHAPTER, outcome).startswith("The death of Sir Danvers")

    def test_span_covers_the_source_casing_exactly(self) -> None:
        """The returned span must be the book's text, not the model's casing."""
        text = NormalizedText(self.REAL_CHAPTER)
        outcome = score_candidates(
            _sel(self.REAL_TARGET), text, tolerance=MatchTolerance.CASE_INSENSITIVE
        )
        assert _matched(self.REAL_CHAPTER, outcome) == self.REAL_CHAPTER[:-1]

    def test_is_still_the_full_quote_tier(self) -> None:
        """EPUB's DOM contract accepts tier 0 only; a recovered full quote must be 0."""
        text = NormalizedText(self.REAL_CHAPTER)
        outcome = score_candidates(
            _sel(self.REAL_TARGET), text, tolerance=MatchTolerance.CASE_INSENSITIVE
        )
        assert isinstance(outcome, MatchResult)
        assert outcome.candidate.exactness_tier == 0

    def test_does_not_recover_a_dropped_word(self) -> None:
        """Case tolerance is not similarity: missing words still miss."""
        text = NormalizedText("is it the mere radiance of a foul soul")
        outcome = score_candidates(
            _sel("the radiance of a foul soul"),
            text,
            tolerance=MatchTolerance.CASE_INSENSITIVE,
        )
        assert isinstance(outcome, NoMatchResult)

    def test_ambiguity_is_still_fail_closed(self) -> None:
        """Two case-variant occurrences and no context: skip, never guess the first."""
        text = NormalizedText("The bezoar is here. Later, the bezoar is there.")
        outcome = score_candidates(
            _sel("The Bezoar"), text, tolerance=MatchTolerance.CASE_INSENSITIVE
        )
        assert isinstance(outcome, AmbiguousResult)
        assert len(outcome.candidates) == 2


class TestLengthPreservingCaseFolding:
    """``str.casefold()`` would desynchronise every span after a folding character."""

    @pytest.mark.parametrize(
        ("source", "needle"),
        [
            ("Die Straße war leer und still.", "die straße war leer"),
            ("Der ﬁnal draft was rejected outright.", "der ﬁnal draft was"),
            ("İstanbul was the meeting point.", "İstanbul was the meeting"),
        ],
    )
    def test_spans_stay_aligned_around_length_changing_characters(
        self, source: str, needle: str
    ) -> None:
        outcome = score_candidates(
            _sel(needle),
            NormalizedText(source),
            tolerance=MatchTolerance.CASE_INSENSITIVE,
        )
        if isinstance(outcome, MatchResult):
            span = outcome.candidate.raw_span
            assert source[span.start : span.end].lower() == needle.lower()

    def test_sharp_s_does_not_fold_to_ss(self) -> None:
        """``ß``/``ss`` equivalence would change length; it is deliberately not applied."""
        outcome = score_candidates(
            _sel("strasse"),
            NormalizedText("Die Straße war leer."),
            tolerance=MatchTolerance.CASE_INSENSITIVE,
        )
        assert isinstance(outcome, NoMatchResult)


# ---------------------------------------------------------------------------
# 3. Punctuation-elastic tolerance — the three real quote-drift failures
# ---------------------------------------------------------------------------


class TestPunctuationElasticTolerance:
    def test_recovers_dropped_internal_quotes_ch7_poole(self) -> None:
        source = (
            'Poole was positive nothing had come except by post; "and only '
            'circulars by that," he added.'
        )
        target = (
            "Poole was positive nothing had come except by post; and only "
            "circulars by that, he added."
        )
        outcome = score_candidates(
            _sel(target),
            NormalizedText(source),
            tolerance=MatchTolerance.PUNCTUATION_ELASTIC,
        )
        assert _matched(source, outcome) == source

    def test_recovers_dropped_closing_quote_ch7_jekyll(self) -> None:
        source = 'Henry Jekyll forge for a murderer!" And his blood ran cold in his veins.'
        target = "Henry Jekyll forge for a murderer! And his blood ran cold in his veins."
        outcome = score_candidates(
            _sel(target),
            NormalizedText(source),
            tolerance=MatchTolerance.PUNCTUATION_ELASTIC,
        )
        assert _matched(source, outcome) == source

    def test_recovers_an_added_leading_quote_ch8(self) -> None:
        """The model *added* a quote the book does not have; elasticity is two-way."""
        source = "He wrote: I have brought on myself a punishment and a danger."
        target = '"I have brought on myself a punishment and a danger.'
        outcome = score_candidates(
            _sel(target),
            NormalizedText(source),
            tolerance=MatchTolerance.PUNCTUATION_ELASTIC,
        )
        assert _matched(source, outcome) == (
            "I have brought on myself a punishment and a danger."
        )

    def test_implies_case_insensitivity(self) -> None:
        source = 'The doctor said, "and only that," plainly.'
        outcome = score_candidates(
            _sel("the doctor said, and only that, plainly."),
            NormalizedText(source),
            tolerance=MatchTolerance.PUNCTUATION_ELASTIC,
        )
        assert _matched(source, outcome) == source

    def test_is_still_the_full_quote_tier(self) -> None:
        source = 'Henry Jekyll forge for a murderer!" And his blood ran cold.'
        outcome = score_candidates(
            _sel("Henry Jekyll forge for a murderer! And his blood ran cold."),
            NormalizedText(source),
            tolerance=MatchTolerance.PUNCTUATION_ELASTIC,
        )
        assert isinstance(outcome, MatchResult)
        assert outcome.candidate.exactness_tier == 0


class TestPunctuationElasticStaysNarrow:
    """Elastic must mean *quotes at word boundaries*, not "punctuation doesn't matter"."""

    def test_apostrophe_inside_a_word_is_literal(self) -> None:
        outcome = score_candidates(
            _sel("he dont care at all"),
            NormalizedText("he don't care at all about it"),
            tolerance=MatchTolerance.PUNCTUATION_ELASTIC,
        )
        assert isinstance(outcome, NoMatchResult)

    def test_contraction_still_matches_itself(self) -> None:
        source = "he don't care at all about it"
        outcome = score_candidates(
            _sel("he don't care at all"),
            NormalizedText(source),
            tolerance=MatchTolerance.PUNCTUATION_ELASTIC,
        )
        assert _matched(source, outcome) == "he don't care at all"

    def test_non_quote_punctuation_is_literal(self) -> None:
        outcome = score_candidates(
            _sel("by post: and only circulars"),
            NormalizedText("by post; and only circulars by that"),
            tolerance=MatchTolerance.PUNCTUATION_ELASTIC,
        )
        assert isinstance(outcome, NoMatchResult)

    def test_does_not_recover_a_dropped_word_ch4(self) -> None:
        """The real ch4 skip. Fuzzy would anchor inside the word ``mere``; we skip."""
        outcome = score_candidates(
            _sel(
                "the radiance of a foul soul that thus transpires through, and "
                "transfigures, its clay continent"
            ),
            NormalizedText(
                "or is it the mere radiance of a foul soul that thus transpires "
                "through, and transfigures, its clay continent?"
            ),
            tolerance=MatchTolerance.PUNCTUATION_ELASTIC,
        )
        assert isinstance(outcome, NoMatchResult)

    def test_does_not_recover_a_paraphrase_ch7(self) -> None:
        """The real ch7 skip: the model dropped a dialogue attribution."""
        outcome = score_candidates(
            _sel(
                "Utterson, I swear to God, I swear to God I will never set eyes "
                "on him again."
            ),
            NormalizedText(
                'Utterson, I swear to God," cried the doctor, "I swear to God I '
                "will never set eyes on him again."
            ),
            tolerance=MatchTolerance.PUNCTUATION_ELASTIC,
        )
        assert isinstance(outcome, NoMatchResult)

    def test_ambiguity_is_still_fail_closed(self) -> None:
        source = 'He said "stir it" once, then he said stir it twice.'
        outcome = score_candidates(
            _sel("he said stir it"),
            NormalizedText(source),
            tolerance=MatchTolerance.PUNCTUATION_ELASTIC,
        )
        assert isinstance(outcome, AmbiguousResult)

    def test_quote_only_needle_is_rejected_not_matched_everywhere(self) -> None:
        """A needle that is nothing but elastic characters must not match anything."""
        outcome = score_candidates(
            _sel('"'),
            NormalizedText('a "quoted" word and another "quoted" word'),
            tolerance=MatchTolerance.PUNCTUATION_ELASTIC,
        )
        assert isinstance(outcome, (NoMatchResult, AmbiguousResult))


class TestElasticBounds:
    """The elastic pattern is built from untrusted model output; it must stay bounded."""

    def test_oversize_needle_does_not_match(self) -> None:
        outcome = score_candidates(
            _sel("word " * 3000),
            NormalizedText("word word word"),
            tolerance=MatchTolerance.PUNCTUATION_ELASTIC,
        )
        assert isinstance(outcome, NoMatchResult)

    def test_regex_metacharacters_in_the_target_are_literal(self) -> None:
        source = "compute a.*b (or not) [maybe] +1"
        outcome = score_candidates(
            _sel("a.*b (or not) [maybe] +1"),
            NormalizedText(source),
            tolerance=MatchTolerance.PUNCTUATION_ELASTIC,
        )
        assert _matched(source, outcome) == "a.*b (or not) [maybe] +1"

    def test_metacharacters_do_not_match_arbitrary_text(self) -> None:
        outcome = score_candidates(
            _sel("a.*b"),
            NormalizedText("axxxxb is not a regex match"),
            tolerance=MatchTolerance.PUNCTUATION_ELASTIC,
        )
        assert isinstance(outcome, NoMatchResult)

    def test_quote_dense_needle_completes_promptly(self) -> None:
        """Guards against catastrophic backtracking from adjacent elastic groups."""
        source = 'x' + ('" ' * 200) + "tail"
        outcome = score_candidates(
            _sel(('" ' * 200) + "nomatch"),
            NormalizedText(source),
            tolerance=MatchTolerance.PUNCTUATION_ELASTIC,
        )
        assert isinstance(outcome, (NoMatchResult, AmbiguousResult, MatchResult))
