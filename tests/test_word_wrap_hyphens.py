"""A word too wide for the margin should break at its own hyphen.

Margin columns are narrow, so long words genuinely have to be divided. Dividing
purely by character produced breaks like "counter-clockw" / "ise", which reads
as a typo rather than a wrap -- and these notes are meant to look like a person
wrote them. A hyphenated word already carries the place it may be divided.

Character splitting is retained for words with no hyphen, and for hyphen pieces
that are still too wide on their own; there is nothing else to do with those.

No network calls; no API key required.
"""

from __future__ import annotations

import importlib.resources as resources
from pathlib import Path

import fitz
import pytest

from halfblood.document_processor import _wrap_text_with_font

_FONT = Path(str(resources.files("halfblood").joinpath("fonts"))) / "CaveatBrush-Regular.ttf"


@pytest.fixture(scope="module")
def font() -> fitz.Font:
    return fitz.Font(fontfile=str(_FONT))


def _wrap(text: str, width: float, font: fitz.Font, size: float = 9.5) -> list[str]:
    return _wrap_text_with_font(text, width, size, font)


class TestHyphenatedWordsBreakAtTheHyphen:
    @pytest.mark.parametrize("width", [40.0, 52.0, 60.0])
    def test_no_line_ends_mid_morpheme(self, width: float, font: fitz.Font) -> None:
        lines = _wrap("three counter-clockwise turns", width, font)
        # The piece may share a line with preceding words; what matters is that
        # the break lands on the hyphen, not inside "clockwise".
        assert any(ln.endswith("counter-") for ln in lines), (
            f"expected a hyphen break, got {lines}"
        )
        assert not any(ln.endswith("clockw") for ln in lines), lines

    def test_the_hyphen_stays_with_the_leading_piece(self, font: fitz.Font) -> None:
        """A trailing hyphen signals continuation; a leading one reads as a dash."""
        lines = _wrap("counter-clockwise", 52.0, font)
        assert lines[0].endswith("-")
        assert not lines[1].startswith("-")

    def test_every_piece_is_recovered_in_order(self, font: fitz.Font) -> None:
        """Wrapping must not lose or reorder characters."""
        text = "three counter-clockwise turns then anti-clockwise once"
        for width in (30.0, 40.0, 52.0, 90.0):
            joined = "".join(_wrap(text, width, font)).replace(" ", "")
            assert joined == text.replace(" ", ""), f"width={width} lost characters"


class TestFallbacksAreUnchanged:
    def test_a_long_word_without_a_hyphen_still_splits_by_character(
        self, font: fitz.Font
    ) -> None:
        lines = _wrap("antidisestablishmentarianism", 30.0, font)
        assert len(lines) > 1
        assert "".join(lines) == "antidisestablishmentarianism"

    def test_a_hyphen_piece_that_is_still_too_wide_splits_by_character(
        self, font: fitz.Font
    ) -> None:
        lines = _wrap("counter-clockwise", 30.0, font)
        assert lines[0] == "counter-"
        assert len(lines) > 2, f"the oversized second piece should split further: {lines}"
        assert "".join(lines) == "counter-clockwise"

    def test_text_that_already_fits_is_untouched(self, font: fitz.Font) -> None:
        assert _wrap("Crush the bean.", 300.0, font) == ["Crush the bean."]

    def test_empty_text_still_yields_one_empty_line(self, font: fitz.Font) -> None:
        assert _wrap("", 100.0, font) == [""]

    @pytest.mark.parametrize("word", ["-", "--", "a-", "-a"])
    def test_degenerate_hyphen_words_do_not_crash_or_vanish(
        self, word: str, font: fitz.Font
    ) -> None:
        lines = _wrap(word, 20.0, font)
        assert "".join(lines) == word

    def test_every_emitted_line_fits_the_margin(self, font: fitz.Font) -> None:
        """The whole point of wrapping: nothing may overflow the column."""
        width = 52.0
        text = "My own pattern: three counter-clockwise turns, one sharp clockwise jerk."
        for line in _wrap(text, width, font):
            assert font.text_length(line, fontsize=9.5) <= width + 1e-6, line
