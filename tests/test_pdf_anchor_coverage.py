"""The PDF anchor must cover the passage the note claims, or be skipped.

Two linked behaviours are pinned here:

1. **Tolerance ladder on the complete quote.** The EPUB locator already walks
   EXACT -> CASE_INSENSITIVE -> PUNCTUATION_ELASTIC (``documents/epub.py``).
   The PDF path passed ``EXACT`` only, so a quote that differed from the page
   by nothing more than letter case or curly-vs-straight quotes skipped past
   tier 0 and anchored to a shortened tier -- in the worst case a single word.

2. **Coverage floor on shortened tiers.** The shortened tiers are retained for
   genuinely messy text layers, but an anchor covering less than
   ``_MIN_ANCHOR_COVERAGE`` of the target is a guess: the note claims a
   sentence while the underline sits on one word, and the reader cannot tell.
   Those are now skipped, which is what the EPUB path already does.

Measured on a real book (Jekyll & Hyde, 50 real annotations): 5 stub anchors
before, 0 after; 48/50 rendered, exactly matching the EPUB path, with the same
2 genuine paraphrases skipped.

No network calls; no API key required.
"""

from __future__ import annotations

import importlib.resources as resources
import uuid
from pathlib import Path

import fitz
import pytest
from pydantic import ValidationError

from halfblood.document_processor import _MIN_ANCHOR_COVERAGE, DocumentProcessor
from halfblood.documents import PdfPageIndex
from halfblood.documents.matching import normalize
from halfblood.models.annotations import Annotation, MarkIntent, TargetSelector
from halfblood.models.legacy import AnnotationType

#: A Unicode-capable face. PyMuPDF's base-14 fonts are Latin-1 and silently
#: mangle curly quotes, which would fake the very drift these tests measure.
_UNICODE_FONT = Path(str(resources.files("halfblood").joinpath("fonts")))/ "CaveatBrush-Regular.ttf"


def _page_with(text: str, width: float = 468.0) -> tuple[fitz.Document, fitz.Page]:
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.insert_textbox(
        fitz.Rect(72, 72, 72 + width, 720),
        text,
        fontsize=11,
        fontname="uni",
        fontfile=str(_UNICODE_FONT),
    )
    return doc, page


def _ann(exact: str) -> Annotation:
    return Annotation(
        id=str(uuid.uuid4()),
        target=TargetSelector(exact=exact),
        annotation_type=AnnotationType.CORRECTION,
        content="A test margin note.",
        confidence=0.9,
        requested_placement="margin_right",
        mark_intent=MarkIntent.UNDERLINE,
    )


def _resolve(page_text: str, target: str):
    """Resolve `target` against a page containing `page_text`, returning
    (anchor, coverage-of-the-target) with the anchor's real char span.
    """
    doc, page = _page_with(page_text)
    try:
        index = PdfPageIndex(page)
        anchor = DocumentProcessor()._resolve_annotation_to_anchor(page, index, _ann(target))
        if anchor is None:
            return None, 0.0
        lo, hi = anchor.char_range
        return anchor, (hi - lo) / max(1, len(normalize(target).strip()))
    finally:
        doc.close()


def _resolve_unindexed(page_text: str, target: str, width: float = 468.0):
    """Same, but with ``index=None`` — the path taken when PdfPageIndex fails.

    There is no char index here, so the anchor is judged by its rect: a correct
    anchor spans most of the passage, a stub sits on a word or two.
    """
    doc, page = _page_with(page_text, width=width)
    try:
        anchor = DocumentProcessor()._resolve_annotation_to_anchor(page, None, _ann(target))
        if anchor is None:
            return None, None
        return anchor, anchor.bounding_rect()
    finally:
        doc.close()


# ---------------------------------------------------------------------------
# 1. The tolerance ladder rescues surface drift into a full-quote anchor
# ---------------------------------------------------------------------------


class TestToleranceLadderOnThePdfPath:
    def test_case_drift_anchors_to_the_whole_quote(self) -> None:
        """Previously anchored to the single word 'death'."""
        anchor, coverage = _resolve(
            "The death of Sir Danvers was avenged.", "the death of Sir Danvers"
        )
        assert anchor is not None
        assert coverage > 0.9, f"case-drifted quote only covered {coverage:.2f} of itself"

    def test_quote_drift_anchors_to_the_whole_quote(self) -> None:
        """The page quotes the dialogue; the model's target omits the quote marks.

        Curly-vs-straight alone is already handled by ``normalize``. The drift
        that actually reached the shortened tiers is *interior quote characters
        the model dropped* -- which is what PUNCTUATION_ELASTIC exists for.
        Previously this anchored to the single word 'circulars'.
        """
        anchor, coverage = _resolve(
            'by post; “and only circulars by that,” he added.',
            "by post; and only circulars by that, he added.",
        )
        assert anchor is not None
        assert coverage > 0.9, f"quote-drifted quote only covered {coverage:.2f} of itself"

    def test_an_exact_quote_is_unaffected(self) -> None:
        anchor, coverage = _resolve(
            "Crush the sopophorous bean with the flat of a silver dagger.",
            "Crush the sopophorous bean",
        )
        assert anchor is not None
        assert coverage > 0.9


# ---------------------------------------------------------------------------
# 2. The coverage floor drops guesses but keeps substantial prefix anchors
# ---------------------------------------------------------------------------


class TestShortenedTierCoverageFloor:
    def test_a_single_word_anchor_for_a_long_target_is_skipped(self) -> None:
        """A paraphrase sharing only one long word must NOT be mis-anchored.

        This is the defect: the margin note refers to a whole sentence while the
        underline sits on one word, and nothing tells the reader.
        """
        anchor, _ = _resolve(
            "the radiance of a foul soul that transfigures its clay continent.",
            "the radiance of a foul soul that thus transpires through, and "
            "wholly alters, the moulded flesh of its earthly prison",
        )
        assert anchor is None, "a one-word anchor for a 20-word target was rendered"

    def test_a_substantial_prefix_anchor_is_still_used(self) -> None:
        """The shortened tiers are gated, not deleted.

        Real PDFs have messy text layers; a prefix covering most of the target is
        the honest best available and must still render.
        """
        anchor, coverage = _resolve(
            "Add the powdered root of asphodel to an infusion of wormwood now.",
            "Add the powdered root of asphodel to an infusion of QQQZZZ",
        )
        assert anchor is not None, "a substantial prefix anchor was dropped"
        assert coverage >= _MIN_ANCHOR_COVERAGE

    def test_the_floor_is_a_named_constant_in_the_documented_range(self) -> None:
        assert 0.0 < _MIN_ANCHOR_COVERAGE < 1.0


# ---------------------------------------------------------------------------
# 3. The un-indexed path — reached when PdfPageIndex raises PdfAlignmentError
# ---------------------------------------------------------------------------


class TestUnindexedPathHoldsTheSameLine:
    """`index is None` must not be a way around the ladder or the floor.

    Rare in practice (0 of 77 pages across three real PDFs failed to index) but
    live, and a messy real-world text layer is exactly what drives resolution
    here. Measured on the real book with `index=None` forced: 10 stub anchors of
    50 before, 0 after.
    """

    def test_a_single_word_anchor_for_a_long_target_is_skipped(self) -> None:
        anchor, _ = _resolve_unindexed(
            "the radiance of a foul soul that transfigures its clay continent.",
            "the radiance of a foul soul that thus transpires through, and "
            "wholly alters, the moulded flesh of its earthly prison",
        )
        assert anchor is None, "a one-word anchor for a 20-word target was rendered"

    def test_dropped_quote_marks_still_find_the_whole_quote(self) -> None:
        """`page.search_for` is already case-insensitive, so punctuation is the
        drift it cannot absorb on its own — the target omits the quote marks the
        page carries."""
        anchor, rect = _resolve_unindexed(
            'He said, “and only circulars by that,” he added. Nothing else occurred.',
            "He said, and only circulars by that, he added.",
        )
        assert anchor is not None, "dropped quote marks lost the annotation entirely"
        assert rect is not None and rect.width > 150, (
            f"anchored to a fragment, rect width {rect.width:.0f}"
        )

    def test_a_quote_spanning_a_line_break_unions_every_line(self) -> None:
        """The regression that made this test necessary.

        A passage crossing a line break returns one rect per line. Treating those
        as competing occurrences keeps only the first, which collapsed
        "Mr.\\nHyde has a key." onto a 15pt anchor over "Mr.".
        """
        # A narrow column forces the passage to wrap.
        anchor, rect = _resolve_unindexed(
            "Utterson remarked that Mr. Hyde has a key. Nobody disputed the claim.",
            "Mr. Hyde has a key.",
            width=120.0,
        )
        assert anchor is not None
        assert rect is not None
        # The passage occupies two lines here: "…that Mr." / "Hyde has a key.".
        # Unioned that is ~108x27; keeping only the first fragment gives ~13x14,
        # so both dimensions have to be asserted -- a single line clears any
        # height threshold set at one line-height.
        assert rect.height > 20.0, (
            f"anchor covers only one line, so the union was dropped: {rect}"
        )
        assert rect.width > 60.0, (
            f"anchor collapsed onto the first fragment: {rect}"
        )

    def test_an_exact_single_line_quote_is_unaffected(self) -> None:
        anchor, rect = _resolve_unindexed(
            "Crush the sopophorous bean with the flat of a silver dagger.",
            "Crush the sopophorous bean",
        )
        assert anchor is not None
        assert rect is not None and rect.width > 60

    def test_a_substantial_prefix_anchor_is_still_used(self) -> None:
        anchor, _ = _resolve_unindexed(
            "Add the powdered root of asphodel to an infusion of wormwood now.",
            "Add the powdered root of asphodel to an infusion of QQQZZZ",
        )
        assert anchor is not None, "a substantial prefix anchor was dropped"


# ---------------------------------------------------------------------------
# 4. The EPUB path must not have moved
# ---------------------------------------------------------------------------


def test_score_candidates_exact_contract_is_unchanged() -> None:
    """The ladder is applied by the PDF *caller*, not by score_candidates.

    The EPUB locator and every other caller must see byte-identical behaviour,
    so the tolerance work here must not have leaked into the scorer's default.
    """
    from halfblood.documents.matching import (
        MatchResult,
        NormalizedText,
        score_candidates,
    )

    text = NormalizedText("The death of Sir Danvers was avenged.")
    outcome = score_candidates(TargetSelector(exact="the death of Sir"), text)
    assert isinstance(outcome, MatchResult)
    assert outcome.candidate.exactness_tier > 0, (
        "score_candidates' EXACT default changed; the EPUB path depends on it"
    )


@pytest.mark.parametrize("target", ["", "   "])
def test_empty_targets_are_rejected_by_the_model(target: str) -> None:
    """The empty-target guard lives in TargetSelector, before the anchor path."""
    with pytest.raises(ValidationError):
        TargetSelector(exact=target)
