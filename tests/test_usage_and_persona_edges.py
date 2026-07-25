"""Two long-standing review advisories, closed.

1. ``UsageTotals`` was a mutable dataclass. It is only ever constructed whole and
   reassigned, so nothing needed the mutability -- but a caller could adjust one field
   and leave it unreconcilable with the run it describes (tokens moved without
   ``pages_with_usage`` moving). Freezing removes the possibility.

2. A blank persona was accepted verbatim. ``persona or DEFAULT_PERSONA`` catches ``""``
   but not ``"   \\n"``, so a persona file that is empty apart from whitespace -- the
   normal result of ``touch personas/mine.txt``, or of a file whose contents were
   accidentally cleared -- produced a system prompt stripped of every voice
   instruction. Nothing in the output indicated the persona had not loaded; the notes
   would simply come out flat and off-character.
"""

from __future__ import annotations

import dataclasses

import pytest

from halfblood.annotation_generator import DEFAULT_PERSONA, AnnotationGenerator, UsageTotals
from halfblood.generation.providers.base import (
    GenerationRequest,
    GenerationResult,
    ProviderCapabilities,
)


class _UnusedProvider:
    """A provider that fails loudly if a test accidentally makes a network call."""

    @property
    def capabilities(self) -> ProviderCapabilities:  # pragma: no cover
        raise AssertionError("no provider capability lookup expected in these tests")

    def complete(self, request: GenerationRequest) -> GenerationResult:  # pragma: no cover
        raise AssertionError("no provider call expected in these tests")


def _generator(persona: str | None) -> AnnotationGenerator:
    return AnnotationGenerator(provider=_UnusedProvider(), persona=persona)


class TestUsageTotalsIsFrozen:
    def test_totals_cannot_be_mutated_in_place(self) -> None:
        totals = UsageTotals(
            input_tokens=10, output_tokens=5, pages_with_usage=1, pages_missing_usage=0
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            totals.input_tokens = 999  # type: ignore[misc]

    def test_totals_are_still_replaceable_as_a_whole(self) -> None:
        """Freezing must not break the construct-and-reassign pattern in use."""
        totals = UsageTotals(
            input_tokens=10, output_tokens=5, pages_with_usage=1, pages_missing_usage=0
        )
        updated = dataclasses.replace(totals, input_tokens=20, pages_with_usage=2)
        assert updated.input_tokens == 20
        assert updated.output_tokens == 5
        assert totals.input_tokens == 10

    def test_a_fresh_generator_starts_at_zero(self) -> None:
        totals = _generator(None).usage_totals
        assert (totals.input_tokens, totals.output_tokens) == (0, 0)
        assert (totals.pages_with_usage, totals.pages_missing_usage) == (0, 0)


class TestBlankPersonaFallsBackToDefault:
    @pytest.mark.parametrize("persona", [None, "", "   ", "\n", "\t \n  \r\n"])
    def test_blank_personas_use_the_default(self, persona: str | None) -> None:
        assert _generator(persona).persona == DEFAULT_PERSONA

    def test_a_real_persona_is_used_verbatim(self) -> None:
        persona = "You are a bored 19th-century chemist."
        assert _generator(persona).persona == persona

    def test_surrounding_whitespace_is_preserved_on_a_real_persona(self) -> None:
        """Only *entirely* blank personas fall back; real ones are passed through as-is.

        Persona files routinely end with a trailing newline, and stripping it would
        silently differ from what the author wrote.
        """
        persona = "\nYou are a bored 19th-century chemist.\n"
        assert _generator(persona).persona == persona

    def test_the_default_persona_reaches_the_system_prompt(self) -> None:
        """Non-vacuity guard: the fallback must actually be used, not just stored."""
        prompt = _generator("   ")._build_system_prompt()
        assert DEFAULT_PERSONA in prompt
