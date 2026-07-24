"""Tests for conservative boilerplate detection and its CLI override."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import patch

import fitz
from click.testing import CliRunner

from halfblood.boilerplate import BOILERPLATE_THRESHOLD, classify
from halfblood.cli import main as cli_main
from halfblood.config import ResolvedConfig, resolve_generation_config
from halfblood.generation.providers.base import (
    GenerationResult,
    GenerationUsage,
    LLMProvider,
    ProviderCapabilities,
)
from halfblood.generation.schema import RecordAnnotations

PG_FRONT_MATTER = (
    "The Project Gutenberg eBook of\n"
    "The strange case of Dr. Jekyll and Mr. Hyde\n"
    "This eBook is for the use of anyone anywhere in the United States and most other "
    "parts of the world at no cost and with almost no restrictions whatsoever. You may "
    "copy it, give it away or re-use it under the terms of the Project Gutenberg License "
    "included with this eBook or online at www.gutenberg.org."
)

PG_LICENSE_APPENDIX = (
    "*** END OF THE PROJECT GUTENBERG EBOOK THE STRANGE CASE OF DR. JEKYLL AND MR. HYDE ***\n"
    "Updated editions will replace the previous one—the old editions will be renamed. "
    "Creating the works from print editions not protected by U.S. copyright law means "
    "that no one owns a United States copyright in these works, so the Foundation (and "
    "you!) can copy and distribute it in the United States without permission and without "
    "paying copyright royalties."
)

REAL_PROSE = (
    "STORY OF THE DOOR\n"
    "Mr. Utterson the lawyer was a man of a rugged countenance that was never lighted "
    "by a smile; cold, scanty and embarrassed in discourse; backward in sentiment; lean, "
    "long, dusty, dreary and yet somehow lovable."
)

LITERARY_WEAK_MARKERS = """
Mara found the old reading room at the end of a rain-darkened arcade, where the lamps
made islands on the carpet and every shelf leaned toward its neighbor like a conspirator.
Her uncle had left her a notebook filled with arguments about copyright law, but the
arguments were personal rather than legal: he remembered the authors by their tempers,
their tea orders, and the way they crossed out a sentence when embarrassed by its beauty.
Mara read until the windows turned black, listening to the caretaker wheel a cart through
the distant stacks. Nothing in those pages sounded like a notice or a command. It was the
record of a life spent wondering who may keep a story and who must let it travel.

At supper, Professor Vale spoke warmly of the public domain. He described it as a common
garden where neglected tales grew wild again, not as a category in a lawyer's cabinet.
Across the table, the novelist Orin objected that gardens still required gardeners. Their
debate wandered through memory, envy, and the strange gratitude of discovering that a
dead poet had already expressed one's most private fear. The candles shortened while the
guests invented histories for the portraits. Mara noticed that no one tried to settle the
question; each answer merely opened another door in the house.

The next morning brought news of a trademark dispute between two village theatres, both
of which used a silver fox on their playbills. Their directors arrived in matching green
coats and refused to look at one another. Mara expected anger, but the quarrel soon became
a comedy of childhood recollections. Each director claimed to have seen the same fox on
the same snowy hill twenty years earlier. By noon they were sketching tails and ears on
scraps of paper, competing less for ownership than for the right to remember most vividly.
The magistrate postponed his decision and invited them both to lunch.

Later, in the archive, Mara helped a student prepare a study of scholarly redistribution.
He traced how a sailor's diary had passed from a sea chest to a schoolroom, then into a
biographer's footnotes and a play performed in a cellar. They talked about transmission
as if following footprints along a shore. Every copy had changed something: a misspelled
name corrected, a storm made fiercer, a silence interpreted as courage. The student was
not drafting terms of use. He wanted to understand why readers carry certain sentences
forward while allowing others to vanish.

Before Mara left, the caretaker showed her a ledger of donations. Beside each modest sum
someone had written a reason: in memory of a sister, for the warmth of the western room,
because a book once made a winter bearable. These notes moved her more than the amounts.
She imagined the donors pausing over the blank line, surprised to find that generosity
also asked for a story. Outside, rain polished the stone lions at the entrance, and buses
sent pale fans of water across the street.

On the train home she reopened her uncle's notebook. Its final pages contained no verdict,
only scenes: a printer washing ink from his hands, children rehearsing beneath a leaking
roof, an old woman returning a borrowed volume with lavender between its leaves. Mara saw
that his subject had never truly been rules. He had been writing about the uneasy passage
from possession to remembrance, and about the affection that survives every argument over
names. Fields slipped past the glass in long green measures. By dusk she had begun, in the
margin, a story of her own.
""".strip()


class _StubProvider:
    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            supports_tool_calling=True,
            supports_json_schema=True,
            supports_strict_json_schema=True,
        )

    def complete(self, request: Any) -> GenerationResult:
        return GenerationResult(
            parsed=RecordAnnotations(annotations=[]),
            request_id="stub-request",
            finish_reason="stop",
            usage=GenerationUsage(input_tokens=1, output_tokens=1),
            latency_seconds=0.001,
            structured_output_mode="tool",
        )


def _build_fake_resolve(tmp_path: Path) -> Any:
    nonexistent = tmp_path / "nonexistent_config.toml"
    nonexistent_user = tmp_path / "nonexistent_user.toml"

    def _hermetic_resolve(
        cli_overrides: Any = None,
        *,
        project_config_path: Path | None = None,
        **kwargs: Any,
    ) -> ResolvedConfig:
        return resolve_generation_config(
            cli_overrides,
            environ={"ANTHROPIC_API_KEY": "stub-fake-key-for-testing"},
            project_config_path=nonexistent,
            user_config_path=nonexistent_user,
        )

    return _hermetic_resolve


def test_pg_front_matter_is_boilerplate() -> None:
    assert classify(PG_FRONT_MATTER).is_boilerplate


def test_pg_license_appendix_is_boilerplate() -> None:
    assert classify(PG_LICENSE_APPENDIX).is_boilerplate


def test_real_prose_is_not_boilerplate() -> None:
    assert not classify(REAL_PROSE).is_boilerplate


def test_empty_text_is_not_boilerplate() -> None:
    verdict = classify("")
    assert not verdict.is_boilerplate
    assert verdict.score == 0.0
    assert verdict.matched_markers == ()


def test_whitespace_only_text_is_not_boilerplate() -> None:
    verdict = classify("   \n\t  ")
    assert not verdict.is_boilerplate
    assert verdict.score == 0.0
    assert verdict.matched_markers == ()


def test_weak_markers_in_literary_context_do_not_trigger_false_positive() -> None:
    assert len(LITERARY_WEAK_MARKERS) >= 1500
    verdict = classify(LITERARY_WEAK_MARKERS)
    assert not verdict.is_boilerplate
    assert verdict.score < 2.0


def test_matched_markers_are_populated_sorted_and_deduplicated() -> None:
    markers = classify(PG_FRONT_MATTER).matched_markers
    assert isinstance(markers, tuple)
    assert markers
    assert markers == tuple(sorted(set(markers)))
    assert "project gutenberg" in markers


def test_annotate_boilerplate_flag_threads_through_cli(tmp_path: Path) -> None:
    input_path = tmp_path / "boilerplate.pdf"
    output_path = tmp_path / "plan.json"
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), PG_FRONT_MATTER)
    document.save(input_path)
    document.close()

    stub = _StubProvider()
    fake_resolve = _build_fake_resolve(tmp_path)

    def _fake_build(config: Any, *, api_key: Any = None) -> LLMProvider:
        return stub

    runner = CliRunner()
    with (
        patch("halfblood.cli.build_provider", _fake_build),
        patch("halfblood.cli.resolve_generation_config", fake_resolve),
    ):
        result = runner.invoke(
            cli_main,
            [
                "annotate",
                str(input_path),
                "-o",
                str(output_path),
                "--dry-run",
                "--force",
                "--annotate-boilerplate",
            ],
            catch_exceptions=False,
        )

    assert result.exit_code == 0, result.output


# ---------------------------------------------------------------------------
# Regression: long boilerplate must not dilute itself below the threshold.
#
# The first implementation scored DISTINCT markers present rather than their
# OCCURRENCES. Short samples still scored high, so the unit tests above passed --
# but the real 18k-char Project Gutenberg licence appendix scored 1.43 against a
# 2.0 threshold and was silently annotated as if it were prose. Length must not
# be a way to hide from the classifier.
# ---------------------------------------------------------------------------


def _long_pg_licence(target_chars: int = 18_000) -> str:
    """Build a realistically long PG licence: markers repeat, spread over bulk text."""
    para = (
        "Section 1. General Terms of Use and Redistributing Project Gutenberg "
        "electronic works. If you do not agree to abide by all the terms of this "
        "agreement, you must cease using and return or destroy all copies. "
        "The Project Gutenberg Literary Archive Foundation makes no representation "
        "concerning the copyright status of any work in any country other than the "
        "United States. Donations are accepted in a number of other ways including "
        "checks, online payments and credit card donations. To donate, please visit "
        "www.gutenberg.org/donate. Nearly all the individual works in the collection "
        "are in the public domain in the United States. "
    )
    text = para
    while len(text) < target_chars:
        text += para
    return text


def test_long_licence_appendix_is_still_detected() -> None:
    """A long licence must stay above the threshold — length is not camouflage."""
    text = _long_pg_licence()
    verdict = classify(text)
    assert len(text) >= 18_000, "fixture must be realistically long to exercise dilution"
    assert verdict.is_boilerplate, (
        f"an {len(text)}-char Project Gutenberg licence scored {verdict.score:.2f}, "
        f"below the {BOILERPLATE_THRESHOLD} threshold — long boilerplate is diluting "
        "itself out of detection"
    )


def test_long_real_prose_stays_content_at_the_same_length() -> None:
    """The length control: equally long genuine prose must remain content."""
    text = (REAL_PROSE + " ") * 80
    assert len(text) >= 18_000, "control must match the boilerplate fixture's scale"
    assert not classify(text).is_boilerplate


def test_short_passage_with_weak_markers_alone_is_never_boilerplate() -> None:
    """Weak markers must not convict on their own.

    Below 1000 chars the length divisor bottoms out at 1.0, so two weak markers
    reach the threshold on raw score. Generic legal words are ordinary English --
    a short real page that happens to use them must survive.
    """
    short_prose = (
        "The auctioneer explained that the manuscript had fallen into the public "
        "domain, and that no trademark attached to the family crest embossed on its "
        "cover. Utterson listened without comment."
    )
    assert len(short_prose) < 1000, "fixture must sit under the length-divisor floor"

    verdict = classify(short_prose)
    assert verdict.score >= BOILERPLATE_THRESHOLD, (
        "fixture must actually reach the raw threshold, otherwise this test proves nothing "
        f"(scored {verdict.score:.2f})"
    )
    assert not verdict.is_boilerplate, (
        f"short prose scoring {verdict.score:.2f} on weak markers alone was flagged as "
        "boilerplate — weak markers must never convict without publisher-specific evidence"
    )
