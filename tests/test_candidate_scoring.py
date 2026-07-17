"""P2-T3 — Score all target candidates and reject ambiguity.

Architecture §5.5, §9 Phase 2. The scorer (`halfblood.documents.matching.score_candidates`)
replaces the silent first-hit selection in `document_processor._search_variants /
find_text_rect` with explicit, ranked candidate evaluation. It returns a typed outcome
(`MatchResult`, `AmbiguousResult`, or `NoMatchResult`) — never raises on ambiguity and
never guesses when evidence is insufficient.

Design constraints pinned by these tests (each is a place a naive build goes wrong):

1. **First-hit is wrong for repeated text.** If a quote appears twice and no context
   is provided, there is no evidence to prefer the first occurrence — both score equally
   → AmbiguousResult. A scorer that returns MatchResult(first) violates this.

2. **Context outranks proximity.** If a prefix matches occurrence A but not B, A wins
   even when B is closer to `start_offset`. A proximity-primary scorer returns B; that
   is wrong.

3. **Ambiguity is a return value, not an exception.** Any implementation that raises on
   ambiguity will cause callers to crash silently (the caller only contracts on
   `ScoringOutcome`).

4. **Legacy mode is exact-only, no single-word fallback.** `_search_variants` promotes
   a repeated single word as a fallback. Legacy mode must never do this — absent full
   quote → NoMatchResult.

5. **Candidates are distinct and source-ordered.** Collapsing repeated candidates or
   returning them in sort order (rather than source order) corrupts the caller's ability
   to map spans back to render positions.

All fixtures are constructed in-memory. No file I/O, no real PDF or EPUB, no LLM calls,
no machine config, no real resolver.
"""

from __future__ import annotations

from halfblood.documents import (
    AMBIGUITY_MARGIN,
    MIN_CONTEXT_SCORE,
    AmbiguousResult,
    MatchResult,
    NoMatchResult,
    NormalizedText,
    ScoredCandidate,
    score_candidates,
)
from halfblood.models.annotations import TargetSelector

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sel(
    exact: str,
    *,
    prefix: str | None = None,
    suffix: str | None = None,
    start_offset: int | None = None,
) -> TargetSelector:
    """Build a TargetSelector with only the fields the test cares about."""
    return TargetSelector(
        exact=exact,
        prefix=prefix,
        suffix=suffix,
        start_offset=start_offset,
    )


def _text(s: str) -> NormalizedText:
    return NormalizedText(s)


# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------


def test_named_constants_exist_and_are_typed() -> None:
    """MIN_CONTEXT_SCORE and AMBIGUITY_MARGIN must be module-level named floats.

    Kills: implementation that uses magic-number literals instead of constants,
    or forgets to export the constants from halfblood.documents.
    """
    assert isinstance(MIN_CONTEXT_SCORE, float)
    assert isinstance(AMBIGUITY_MARGIN, float)
    assert MIN_CONTEXT_SCORE >= 0.0, "negative threshold makes no sense"
    assert 0.0 < AMBIGUITY_MARGIN < 1.0, "margin must be in (0, 1)"


# ---------------------------------------------------------------------------
# Basic: no candidates / single candidate
# ---------------------------------------------------------------------------


def test_no_match_when_quote_absent() -> None:
    """Quote not in text → NoMatchResult; no exception raised.

    Kills: implementation that raises ValueError/StopIteration on empty candidate
    list instead of returning NoMatchResult.
    """
    text = _text("The sky is blue and clear.")
    sel = _sel("copper cauldron")
    result = score_candidates(sel, text)
    assert isinstance(result, NoMatchResult)


def test_unique_candidate_is_confident_match() -> None:
    """One occurrence, no context hints → MatchResult pointing at the right span.

    Kills: implementation that returns AmbiguousResult for every call regardless
    of candidate count, or returns NoMatchResult when one candidate exists.
    """
    text = _text("The quick brown fox jumps over the lazy dog.")
    sel = _sel("quick brown fox")
    result = score_candidates(sel, text)
    assert isinstance(result, MatchResult)
    raw = result.candidate.raw_span
    assert text.raw[raw.start : raw.end] == "quick brown fox"


def test_scored_candidate_fields_are_valid() -> None:
    """ScoredCandidate has bounded float scores and a non-empty reason string.

    Kills: implementation that leaves scores as sentinel values or omits reason.
    """
    text = _text("add salt to the water.")
    sel = _sel("salt")
    result = score_candidates(sel, text)
    assert isinstance(result, MatchResult)
    c = result.candidate
    assert 0.0 <= c.context_score <= 1.0
    assert 0.0 <= c.offset_score <= 1.0
    assert isinstance(c.reason, str)
    assert len(c.reason) > 0


# ---------------------------------------------------------------------------
# Repeated quotes: first-hit is wrong
# ---------------------------------------------------------------------------


def test_repeated_quote_no_context_is_ambiguous() -> None:
    """Same quote twice, no prefix/suffix, no offset → AmbiguousResult with both.

    Kills: first-hit scorer that returns MatchResult(first occurrence) when
    no evidence distinguishes the two candidates.
    """
    text = _text("boil the cauldron. boil the cauldron. Do not forget.")
    sel = _sel("boil the cauldron")
    result = score_candidates(sel, text)
    assert isinstance(result, AmbiguousResult), (
        "two equal-context candidates must produce AmbiguousResult, not a guessed MatchResult"
    )
    assert len(result.candidates) == 2


def test_suffix_selects_second_occurrence() -> None:
    """Suffix matches only the second occurrence → MatchResult pointing to the second.

    Kills: first-hit scorer (picks occurrence 1) and context-ignoring scorer
    (ignores the suffix evidence that singles out occurrence 2).
    """
    # "valerian root" appears twice; only the second is followed by " to the cauldron"
    text = _text("valerian root. Add valerian root to the cauldron. Continue.")
    sel = _sel("valerian root", suffix=" to the cauldron")
    result = score_candidates(sel, text)
    assert isinstance(result, MatchResult)
    raw = result.candidate.raw_span
    first_pos = text.raw.index("valerian root")
    assert raw.start > first_pos, "should return the second occurrence (suffix match), not the first"


def test_prefix_selects_second_occurrence() -> None:
    """Prefix matches only the second occurrence → MatchResult pointing to the second.

    Kills: first-hit scorer (picks occurrence 1 regardless of context).
    """
    # "root" appears twice; only the second is preceded by "pound the "
    text = _text("slice the root carefully. Then pound the root gently.")
    sel = _sel("root", prefix="pound the ")
    result = score_candidates(sel, text)
    assert isinstance(result, MatchResult)
    raw = result.candidate.raw_span
    second_pos = text.raw.rindex("root")
    assert raw.start == second_pos


# ---------------------------------------------------------------------------
# Context outranks proximity
# ---------------------------------------------------------------------------


def test_context_outranks_offset_proximity() -> None:
    """Prefix matches only the first occurrence; start_offset is closer to the second.
    The first occurrence must win — context dominates proximity.

    Kills: proximity-primary scorer that returns the offset-closest candidate when
    prefix already unambiguously identifies a different occurrence.

    Text layout (normalized positions):
      'After heating: moonstone dust. Add moonstone dust carefully.'
       0              15              30  35
    start_offset=50 is closer to the second 'moonstone dust' (pos 35) than the first (pos 15).
    But only the first is preceded by 'After heating: '.
    """
    text = _text("After heating: moonstone dust. Add moonstone dust carefully.")
    sel = _sel("moonstone dust", prefix="After heating: ", start_offset=50)
    result = score_candidates(sel, text)
    assert isinstance(result, MatchResult)
    raw = result.candidate.raw_span
    # First occurrence of "moonstone dust" in raw text
    first_pos = text.raw.index("moonstone dust")
    assert raw.start == first_pos, (
        "context (prefix match) must outrank offset proximity; "
        "expected first occurrence, got a different one"
    )


# ---------------------------------------------------------------------------
# Ambiguity margin
# ---------------------------------------------------------------------------


def test_equal_context_triggers_ambiguity() -> None:
    """Both occurrences preceded by the same prefix → both score ctx=1.0,
    diff=0 ≤ AMBIGUITY_MARGIN → AmbiguousResult.

    Kills: always-return-best scorer that picks the first sorted candidate
    and returns MatchResult even when two candidates are indistinguishable.
    """
    # Both "moonstone" occurrences are preceded by "add "
    text = _text("add moonstone to the brew. Then add moonstone again.")
    sel = _sel("moonstone", prefix="add ")
    result = score_candidates(sel, text)
    assert isinstance(result, AmbiguousResult), (
        "two candidates with identical context scores (diff=0 ≤ AMBIGUITY_MARGIN) "
        "must produce AmbiguousResult, not a MatchResult"
    )
    assert len(result.candidates) == 2


def test_clear_context_winner_is_not_ambiguous() -> None:
    """Only one occurrence matches the prefix (ctx=1.0 vs 0.0, diff=1.0 >> AMBIGUITY_MARGIN)
    → MatchResult, not AmbiguousResult.

    Kills: scorer that always returns AmbiguousResult when ≥2 candidates exist,
    ignoring the margin threshold.
    """
    text = _text("slice the root. Then pound the root.")
    # Only "pound the root" matches prefix "pound the "
    sel = _sel("root", prefix="pound the ")
    result = score_candidates(sel, text)
    assert isinstance(result, MatchResult), (
        "context difference of 1.0 >> AMBIGUITY_MARGIN must produce a confident MatchResult"
    )


def test_ambiguous_result_is_a_value_not_raised() -> None:
    """AmbiguousResult is returned, never raised as an exception.

    Kills: implementation that does 'raise AmbiguousResult(...)' or raises any
    exception when candidates are indistinguishable.
    """
    text = _text("stir clockwise. stir clockwise.")
    sel = _sel("stir clockwise")
    # Must not raise; call must complete and return AmbiguousResult
    result = score_candidates(sel, text)
    assert isinstance(result, AmbiguousResult)


# ---------------------------------------------------------------------------
# Ambiguous result shape and ordering
# ---------------------------------------------------------------------------


def test_ambiguous_candidates_are_source_ordered() -> None:
    """AmbiguousResult.candidates must be in ascending source order (raw_span.start).

    Kills: implementation that returns candidates in sort-score order rather than
    source position order, breaking the caller's ability to map spans to render positions.
    """
    text = _text("cat sat mat cat sat mat cat")
    sel = _sel("cat")  # appears 3 times with identical context scores
    result = score_candidates(sel, text)
    assert isinstance(result, AmbiguousResult)
    starts = [c.raw_span.start for c in result.candidates]
    assert starts == sorted(starts), "AmbiguousResult candidates must be in source order"


def test_ambiguous_candidates_have_valid_scores() -> None:
    """Every candidate in AmbiguousResult has scores in [0.0, 1.0] and a reason.

    Kills: implementation that populates AmbiguousResult candidates without scoring them,
    leaving scores as default sentinel values or reason as an empty string.
    """
    text = _text("add salt. add salt.")
    sel = _sel("add salt")
    result = score_candidates(sel, text)
    assert isinstance(result, AmbiguousResult)
    for c in result.candidates:
        assert isinstance(c, ScoredCandidate)
        assert 0.0 <= c.context_score <= 1.0
        assert 0.0 <= c.offset_score <= 1.0
        assert len(c.reason) > 0


def test_offset_score_populated_in_genuinely_ambiguous_candidates() -> None:
    """When context AND proximity are both tied, the result stays ambiguous, and each
    candidate still carries a populated (non-zero) offset_score for the caller.

    Two occurrences roughly equidistant from start_offset have offset_scores within the
    ambiguity margin of each other, so proximity cannot break the context tie → still
    AmbiguousResult. (The case where proximity DOES distinguish is
    test_proximity_breaks_context_tie, which must return MatchResult.)

    Kills: implementation that leaves offset_score at 0.0 / unpopulated for
    AmbiguousResult candidates.
    """
    text = _text("aa root bbbbbbbbbbbb root aa")
    first = text.raw.index("root")
    second = text.raw.rindex("root")
    sel = _sel("root", start_offset=(first + second) // 2)  # equidistant → offsets tie
    result = score_candidates(sel, text)
    assert isinstance(result, AmbiguousResult), (
        "context tie with proximity also tied (equidistant) must remain ambiguous"
    )
    assert len(result.candidates) == 2
    for c in result.candidates:
        assert c.offset_score > 0.0, "offset_score must be populated (non-zero) for callers"


def test_proximity_breaks_context_tie() -> None:
    """Context tied, but start_offset clearly nearer ONE occurrence → MatchResult on the
    offset-closest occurrence. Proximity breaks otherwise-equal scores (plan line 60);
    offsets exist to disambiguate repeated phrases (spec §6.1).

    Kills reading A (context-tie → AmbiguousResult regardless of offset), under which
    offset_score is inert and never affects the match-vs-ambiguous outcome.
    """
    text = _text("root appears early here. Much later, root appears once more near the end.")
    second_pos = text.raw.rindex("root")
    # start_offset sits right on the second occurrence → its offset_score is ~1.0, the
    # first occurrence's is far lower (gap well beyond the ambiguity margin).
    sel = _sel("root", start_offset=second_pos)
    result = score_candidates(sel, text)
    assert isinstance(result, MatchResult), (
        "distinguishing proximity must break a context tie into a confident match, "
        "not return AmbiguousResult"
    )
    assert result.candidate.raw_span.start == second_pos, (
        "the occurrence nearest start_offset must win"
    )


# ---------------------------------------------------------------------------
# Repeated candidates are distinct, not collapsed
# ---------------------------------------------------------------------------


def test_repeated_candidates_are_not_collapsed() -> None:
    """Three occurrences of the same phrase → AmbiguousResult with 3 candidates.

    Kills: implementation that deduplicates candidates by span, by score, or by any
    other criterion, losing occurrence count information that the caller needs.
    """
    text = _text("cat dog cat dog cat dog")
    sel = _sel("cat")
    result = score_candidates(sel, text)
    assert isinstance(result, AmbiguousResult)
    assert len(result.candidates) == 3


# ---------------------------------------------------------------------------
# Reason strings must not leak source text
# ---------------------------------------------------------------------------


def test_scored_candidate_reason_contains_no_source_text() -> None:
    """reason must contain only metric names and numeric values — no substrings
    from the source text or the selector fields.

    Kills: implementation that includes context excerpts, matched text, or selector
    field values in the reason string, leaking potentially sensitive content.
    """
    source = "aluphoria burns at extreme temperatures of precisely"
    text = _text(source)
    # "aluphoria" is unique in this text → MatchResult
    sel = _sel("aluphoria", suffix=" burns")
    result = score_candidates(sel, text)
    assert isinstance(result, MatchResult)
    reason = result.candidate.reason
    # No word from the source (beyond bare numbers) should appear in the reason
    for word in ("aluphoria", "burns", "extreme", "temperatures", "precisely"):
        assert word not in reason, (
            f"source word {word!r} must not appear in reason string {reason!r}"
        )


def test_no_match_reason_contains_no_source_text() -> None:
    """NoMatchResult.reason must also not leak source text.

    Kills: implementation that includes the target quote in the no-match reason.
    """
    text = _text("some completely unrelated content about potions.")
    sel = _sel("vanishing cream")  # not in text
    result = score_candidates(sel, text)
    assert isinstance(result, NoMatchResult)
    assert "vanishing cream" not in result.reason
    assert "potions" not in result.reason


# ---------------------------------------------------------------------------
# Normalization: smart quotes and dashes fold before matching
# ---------------------------------------------------------------------------


def test_smart_quotes_in_source_match_straight_quotes_in_selector() -> None:
    """Source text with curly quotes is found by a selector using straight quotes.

    Kills: scorer that does not normalize before searching, requiring byte-identical
    text in the selector to match real book text.
    """
    # Curly quotes in source
    text = _text("She said “hello” to him.")  # "hello" with U+201C/U+201D
    sel = _sel('"hello"')  # straight ASCII double-quotes in selector
    result = score_candidates(sel, text)
    assert isinstance(result, MatchResult), (
        "normalized curly quotes must match straight-quote selector"
    )


# ---------------------------------------------------------------------------
# Legacy exact-only mode
# ---------------------------------------------------------------------------


def test_legacy_exact_only_returns_first_occurrence() -> None:
    """legacy_exact_only=True → MatchResult for the FIRST source occurrence, no scoring.

    Kills: implementation that ignores the legacy_exact_only flag and runs the full
    scoring/ambiguity path, which would return AmbiguousResult for a repeated quote.
    """
    text = _text("add root, then add root more carefully.")
    sel = _sel("root")  # appears twice
    result = score_candidates(sel, text, legacy_exact_only=True)
    assert isinstance(result, MatchResult)
    raw = result.candidate.raw_span
    first_pos = text.raw.index("root")
    assert raw.start == first_pos, "legacy mode must return the first source occurrence"


def test_legacy_mode_does_not_find_absent_quote() -> None:
    """legacy_exact_only=True → NoMatchResult when the full normalized exact quote is absent.

    Kills: _search_variants-style fallback that finds a single-word token ('boils')
    as a substitute for the missing multi-word quote ('mercury boils').
    The scorer must never promote a fallback token in legacy mode.
    """
    text = _text("water boils at one hundred degrees.")
    # "mercury boils" is not in the text — only "boils" is present as a lone word
    sel = _sel("mercury boils")
    result = score_candidates(sel, text, legacy_exact_only=True)
    assert isinstance(result, NoMatchResult), (
        "legacy mode must return NoMatchResult for an absent full quote; "
        "must NOT fall back to matching the single word 'boils'"
    )


def test_legacy_mode_no_exception_on_absent_quote() -> None:
    """legacy_exact_only=True must return NoMatchResult (not raise) when quote is absent.

    Kills: implementation that raises StopIteration or IndexError when no candidates
    are found and legacy_exact_only=True (e.g. candidates[0] on an empty list).
    """
    text = _text("nothing relevant here.")
    sel = _sel("copper cauldron")
    result = score_candidates(sel, text, legacy_exact_only=True)
    assert isinstance(result, NoMatchResult)


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_empty_text_returns_no_match() -> None:
    """Empty source text → NoMatchResult, no exception.

    Kills: implementation that raises IndexError or ZeroDivisionError on
    empty text (e.g. offset_score divides by text length).
    """
    text = _text("")
    sel = _sel("anything")
    result = score_candidates(sel, text)
    assert isinstance(result, NoMatchResult)


def test_single_occurrence_no_context_is_confident_match() -> None:
    """One occurrence with no prefix/suffix/offset → MatchResult with context_score=1.0.

    Kills: implementation that returns ctx=0.0 when no context is provided
    instead of 1.0 (no evidence against → maximum confidence).
    """
    text = _text("The only occurrence of thestrals appears here.")
    sel = _sel("thestrals")
    result = score_candidates(sel, text)
    assert isinstance(result, MatchResult)
    assert result.candidate.context_score == 1.0, (
        "no context provided means no evidence against → context_score must be 1.0"
    )


# ---------------------------------------------------------------------------
# Exactness ladder (P2-T3 core): full quote outranks every shortened candidate
# ---------------------------------------------------------------------------


def test_full_absent_falls_back_to_eight_word_prefix() -> None:
    """Full quote absent but its 8-word prefix matches once → MatchResult on the prefix.

    The scorer builds an exactness ladder (full → 8/5/3-word prefixes → longest word,
    mirroring document_processor._search_variants) and resolves against the highest
    non-empty tier. Here the full quote does not appear, but its first 8 words do (once),
    so the scorer must resolve to that shortened tier.

    Kills interpretation A (scorer searches only the full quote → returns NoMatchResult
    when the full quote is absent, even though an unambiguous 8-word prefix exists).
    """
    # 11-word quote; full form is NOT in the text, but the first 8 words are, once.
    exact = "the copper cauldron must be heated slowly over a low flame"
    text = _text("Note: the copper cauldron must be heated slowly over gentle coals, not a flame.")
    sel = _sel(exact)
    result = score_candidates(sel, text)
    assert isinstance(result, MatchResult), (
        "an unambiguous 8-word-prefix hit must resolve; interpretation A returns NoMatch here"
    )
    raw = result.candidate.raw_span
    assert text.raw[raw.start : raw.end] == "the copper cauldron must be heated slowly over"
    assert result.candidate.exactness_tier > 0, (
        "a shortened-tier match must record a non-zero exactness tier"
    )


def test_full_exact_outranks_present_shortened_candidate() -> None:
    """Full exact appears once AND a shortened form of it appears earlier → full wins.

    'stir the potion' (a 3-word prefix) appears standalone before the full quote
    'stir the potion counterclockwise thrice'. Tier dominance: the full-exact tier is
    non-empty, so the scorer never even considers the shortened tier.

    Kills any scorer that pools candidates across tiers or lets an earlier/looser
    shortened hit win — it must return the FULL span, at exactness tier 0.
    """
    exact = "stir the potion counterclockwise thrice"
    text = _text("First stir the potion. Then stir the potion counterclockwise thrice to finish.")
    sel = _sel(exact)
    result = score_candidates(sel, text)
    assert isinstance(result, MatchResult)
    raw = result.candidate.raw_span
    assert text.raw[raw.start : raw.end] == exact, (
        "the present full-exact quote must outrank the earlier shortened 'stir the potion'"
    )
    assert result.candidate.exactness_tier == 0, "full-quote match must be exactness tier 0"


def test_shortened_tier_repeated_without_context_is_ambiguous() -> None:
    """Full absent; the only matching tier (longest word) repeats with no distinguishing
    context → AmbiguousResult, never a blind first-hit.

    'powdered moonstone' never appears (no 'powdered'), so the ladder descends to its
    longest word 'moonstone', which occurs twice with identical (empty) context. This is
    exactly the repeated-fallback situation _search_variants gets wrong by taking the
    first hit; the scorer must report ambiguity instead.

    Kills interpretation A (NoMatch, since the full quote is absent) AND any blind-first-hit
    fallback (would return MatchResult on the first 'moonstone').
    """
    exact = "powdered moonstone"
    text = _text("The moonstone glowed softly. Another moonstone rested nearby.")
    sel = _sel(exact)
    result = score_candidates(sel, text)
    assert isinstance(result, AmbiguousResult), (
        "a repeated shortened-tier fallback with no distinguishing context must be ambiguous, "
        "not a guessed first-hit"
    )
    assert len(result.candidates) == 2
    starts = [c.raw_span.start for c in result.candidates]
    assert starts == sorted(starts), "ambiguous candidates must be in source order"
    assert all(c.exactness_tier > 0 for c in result.candidates), (
        "these are shortened-tier (longest-word) candidates, tier > 0"
    )
