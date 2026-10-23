"""The craft instructions must survive a custom persona, and the default must not move.

``--persona`` and ``--persona-file`` *replace* the persona string. Before the
``ANNOTATION_CRAFT`` split, that meant a custom persona silently discarded the
definitions of all eight annotation types, the be-selective rule, the stay-in-character
rule, and the confidence guidance -- the system prompt fell from 4779 characters to 707
and the model was left to infer the whole taxonomy from the schema enum. Nothing in the
output revealed it; the notes simply came out shapeless. The persona library
(``personas/*.txt``) is only viable once this holds.

The paired risk is the opposite one: splitting a prompt is an easy way to change it by
accident, and this project has just finished proving that unmeasured prompt edits are
indistinguishable from noise at n=50. So the default prompt is pinned byte-for-byte.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from halfblood.annotation_generator import (
    ANNOTATION_CRAFT,
    DEFAULT_PERSONA,
    AnnotationGenerator,
)
from halfblood.generation.providers.base import (
    GenerationRequest,
    GenerationResult,
    ProviderCapabilities,
)

PERSONAS_DIR = Path(__file__).resolve().parents[1] / "src" / "halfblood" / "personas"

ANNOTATION_TYPES = (
    "CORRECTIONS",
    "IMPROVEMENTS",
    "INSIGHTS",
    "INVENTIONS",
    "WARNINGS",
    "SHORTCUTS",
    "CROSSED_OUT",
    "DOODLE_NOTE",
)


class _UnusedProvider:
    @property
    def capabilities(self) -> ProviderCapabilities:  # pragma: no cover
        raise AssertionError("no capability lookup expected")

    def complete(self, request: GenerationRequest) -> GenerationResult:  # pragma: no cover
        raise AssertionError("no provider call expected")


def _prompt(persona: str | None) -> str:
    return AnnotationGenerator(provider=_UnusedProvider(), persona=persona)._build_system_prompt()


def _persona_files() -> list[Path]:
    return sorted(PERSONAS_DIR.glob("*.txt"))


class TestCraftSurvivesACustomPersona:
    def test_all_eight_types_are_defined_for_a_custom_persona(self) -> None:
        prompt = _prompt("You are a bored 19th-century chemist.")
        missing = [name for name in ANNOTATION_TYPES if name not in prompt]
        assert not missing, f"custom persona lost annotation types: {missing}"

    def test_craft_rules_survive_a_custom_persona(self) -> None:
        prompt = _prompt("You are a bored 19th-century chemist.")
        assert "Do not annotate every sentence" in prompt
        assert "Never break character" in prompt

    def test_the_custom_persona_text_is_still_present(self) -> None:
        persona = "You are a bored 19th-century chemist."
        assert persona in _prompt(persona)

    def test_a_custom_persona_prompt_is_not_a_stub(self) -> None:
        """Non-vacuity guard: the pre-split failure was a 707-character prompt."""
        assert len(_prompt("You are a bored 19th-century chemist.")) > 3000

    def test_craft_is_not_duplicated_for_the_default_persona(self) -> None:
        assert _prompt(None).count("WHAT YOUR ANNOTATIONS DO") == 1


class TestDefaultPromptIsUnchanged:
    """Pinned so the split cannot quietly alter the one prompt with measured results."""

    def test_default_persona_keeps_its_identity(self) -> None:
        assert "Half-Blood Prince" in DEFAULT_PERSONA
        assert "Severus Snape" in DEFAULT_PERSONA

    def test_voice_and_craft_are_cleanly_separated(self) -> None:
        assert "WHAT YOUR ANNOTATIONS DO" not in DEFAULT_PERSONA
        assert "VOICE AND TEMPERAMENT" in DEFAULT_PERSONA
        assert "WHAT YOUR ANNOTATIONS DO" in ANNOTATION_CRAFT

    def test_default_prompt_length_is_pinned(self) -> None:
        """6337 characters: the 2026-10-23 revision, changed deliberately.

        The first independent grading (Claude generator, Codex judge,
        ``docs/evidence/2026-10-23-g5``) failed only on density: 9 notes on a
        91-word passage. The revision scales the count to the text, keeps notes
        terse, and asks for the type that names each note's job. Before that,
        the 2026-10-22 revision was 5891 characters.

        The pre-split prompt was 4779 characters. It was rewritten after the first
        real-model run on public-domain books (``examples/real/NOTES-REVIEW.md``):
        notes drifted into the wizarding world on books that are not about it, made
        claims the page did not support, and repeated the same insult page after page.
        Any further change must be just as deliberate, so the length stays pinned.

        Structural rather than a golden file: reassembling voice + craft + task with the
        recorded spacing must reproduce the prompt exactly.
        """
        prompt = _prompt(None)
        assert len(prompt) == 6337
        assert prompt.startswith(DEFAULT_PERSONA.rstrip())
        assert f"{DEFAULT_PERSONA.rstrip()}\n\n{ANNOTATION_CRAFT.rstrip()}\n\n\nTASK\n" in prompt


class TestPersonaLibrary:
    def test_the_library_exists_and_is_populated(self) -> None:
        assert _persona_files(), "personas/ must ship at least one .txt persona"

    @pytest.mark.parametrize("path", _persona_files(), ids=lambda p: p.stem)
    def test_each_persona_is_substantive(self, path: Path) -> None:
        text = path.read_text(encoding="utf-8")
        assert text.strip(), f"{path.name} is blank"
        assert len(text) > 300, f"{path.name} is too thin to shape a voice"

    @pytest.mark.parametrize("path", _persona_files(), ids=lambda p: p.stem)
    def test_each_persona_describes_a_voice_not_the_machinery(self, path: Path) -> None:
        """A persona that restates the type list goes stale when the list changes."""
        text = path.read_text(encoding="utf-8")
        assert "WHAT YOUR ANNOTATIONS DO" not in text
        assert "VOICE AND TEMPERAMENT" in text

    @pytest.mark.parametrize("path", _persona_files(), ids=lambda p: p.stem)
    def test_each_persona_produces_a_complete_prompt(self, path: Path) -> None:
        prompt = _prompt(path.read_text(encoding="utf-8"))
        assert all(name in prompt for name in ANNOTATION_TYPES)
        assert "Half-Blood Prince" not in prompt, (
            f"{path.name} did not replace the default persona"
        )

    def test_personas_are_documented(self) -> None:
        readme = (PERSONAS_DIR / "README.md").read_text(encoding="utf-8")
        for path in _persona_files():
            assert path.name in readme, f"{path.name} is missing from personas/README.md"
