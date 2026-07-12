"""End-to-end and unit tests for the Half-Blood Prince pipeline.

Covers:
    - DocumentProcessor.load() against a real multi-page PDF fixture
    - PageContent field correctness
    - DocumentProcessor.find_text_rect() against known passages
    - DocumentProcessor.render_annotations() with synthetic annotations
    - AnnotationGenerator.generate_for_page()'s blank-page short-circuit
    - The CLI's --help surface via Click's CliRunner
    - A grab-bag of edge cases: empty text, very long content, special
      characters, and invalid annotations that should be dropped rather
      than raising.

As of P1-T5, response parsing (tool-block extraction, per-item validation
drop, malformed-input handling) lives entirely in
``AnthropicProvider``/``AnnotationDraft`` and is covered by
tests/test_anthropic_provider.py against raw HTTP JSON fixtures -- this file
no longer tests ``AnnotationGenerator._parse_response()``, which P1-T5
deleted along with the direct Anthropic SDK call it parsed.
"""

from __future__ import annotations

from pathlib import Path

import fitz
import pytest
from click.testing import CliRunner
from pydantic import ValidationError

from halfblood.annotation_generator import AnnotationGenerator
from halfblood.cli import main as cli_main
from halfblood.document_processor import DocumentProcessor, PageContent
from halfblood.models import Annotation, AnnotationType

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
SAMPLE_PDF = FIXTURES_DIR / "potions_textbook.pdf"

# A handful of passages known to appear verbatim (aside from PDF line-wrap
# whitespace, which find_text_rect normalizes) on specific pages of
# potions_textbook.pdf. Used across several test classes below.
KNOWN_PASSAGES = {
    1: "Potion-making is, and has always been, a discipline of exactitude.",
    2: "Sopophorous bean",
    3: "Amortentia is widely considered the most powerful love potion in existence.",
    4: "Felix Felicis",
    5: "Golpalott's Third Law",
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def sample_pdf_path() -> Path:
    assert SAMPLE_PDF.is_file(), f"missing test fixture: {SAMPLE_PDF}"
    return SAMPLE_PDF


@pytest.fixture()
def processor() -> DocumentProcessor:
    return DocumentProcessor()


@pytest.fixture()
def pages(processor: DocumentProcessor, sample_pdf_path: Path) -> list[PageContent]:
    return processor.load(str(sample_pdf_path))


@pytest.fixture()
def generator() -> AnnotationGenerator:
    # A syntactically valid but fake key is enough: none of the tests in
    # this file trigger a real network call, since we exercise
    # generate_for_page("") directly rather than generate_for_page() with
    # real page text.
    return AnnotationGenerator(api_key="sk-ant-test-fake-key-not-real")


# ---------------------------------------------------------------------------
# DocumentProcessor.load()
# ---------------------------------------------------------------------------


class TestDocumentProcessorLoad:
    def test_returns_one_pagecontent_per_page(self, pages: list[PageContent]) -> None:
        assert len(pages) == 5

    def test_page_numbers_are_1_indexed_and_sequential(self, pages: list[PageContent]) -> None:
        assert [p.page_number for p in pages] == [1, 2, 3, 4, 5]

    def test_page_dimensions_are_us_letter(self, pages: list[PageContent]) -> None:
        for page in pages:
            assert page.width == pytest.approx(612, abs=1)
            assert page.height == pytest.approx(792, abs=1)

    def test_expected_chapter_text_present_on_each_page(self, pages: list[PageContent]) -> None:
        expectations = {
            1: "ADVANCED POTION-MAKING",
            2: "Draught of Living Death",
            3: "Amortentia",
            4: "Felix Felicis",
            5: "Golpalott's Third Law",
        }
        for page_number, needle in expectations.items():
            page = pages[page_number - 1]
            assert needle in page.text

    def test_load_raises_for_missing_file(self, processor: DocumentProcessor) -> None:
        # AUD-41: pin the actual exception type (PyMuPDF's FileNotFoundError,
        # a RuntimeError subclass) so an unrelated crash cannot pass as green.
        with pytest.raises(fitz.FileNotFoundError):
            processor.load(str(FIXTURES_DIR / "does_not_exist.pdf"))


# ---------------------------------------------------------------------------
# PageContent field correctness
# ---------------------------------------------------------------------------


class TestPageContentFields:
    def test_fields_have_expected_types(self, pages: list[PageContent]) -> None:
        page = pages[0]
        assert isinstance(page.page_number, int)
        assert isinstance(page.text, str)
        assert isinstance(page.width, float)
        assert isinstance(page.height, float)

    def test_text_is_non_empty_for_content_pages(self, pages: list[PageContent]) -> None:
        for page in pages:
            assert page.text.strip() != ""

    def test_manual_construction(self) -> None:
        pc = PageContent(page_number=3, text="hello", width=612.0, height=792.0)
        assert pc.page_number == 3
        assert pc.text == "hello"
        assert pc.width == 612.0
        assert pc.height == 792.0


# ---------------------------------------------------------------------------
# DocumentProcessor.find_text_rect()
# ---------------------------------------------------------------------------


class TestFindTextRect:
    def test_finds_known_passage_on_correct_page(
        self, processor: DocumentProcessor, sample_pdf_path: Path
    ) -> None:
        doc = fitz.open(str(sample_pdf_path))
        try:
            for page_number, needle in KNOWN_PASSAGES.items():
                page = doc[page_number - 1]
                rect = processor.find_text_rect(page, needle)
                assert rect is not None, f"expected to find {needle!r} on page {page_number}"
                assert rect.width > 0
                assert rect.height > 0
                # sanity: rect must lie within the page bounds
                assert page.rect.contains(rect)
        finally:
            doc.close()

    def test_passage_not_found_on_wrong_page(
        self, processor: DocumentProcessor, sample_pdf_path: Path
    ) -> None:
        doc = fitz.open(str(sample_pdf_path))
        try:
            page2 = doc[1]  # Draught of Living Death
            rect = processor.find_text_rect(page2, "Golpalott's Third Law")
            assert rect is None
        finally:
            doc.close()

    def test_falls_back_to_shorter_variant_for_long_passage(
        self, processor: DocumentProcessor, sample_pdf_path: Path
    ) -> None:
        # A long, slightly-off passage (extra trailing words the model
        # "hallucinated" that don't actually appear) should still resolve
        # via the shorter-prefix fallback in _search_variants.
        doc = fitz.open(str(sample_pdf_path))
        try:
            page = doc[3]  # Felix Felicis
            mangled = (
                "Felix Felicis, known colloquially as Liquid Luck, is a potion of "
                "extraordinary complexity and a truly staggering amount of paperwork"
            )
            rect = processor.find_text_rect(page, mangled)
            assert rect is not None
        finally:
            doc.close()

    def test_empty_text_returns_none(
        self, processor: DocumentProcessor, sample_pdf_path: Path
    ) -> None:
        doc = fitz.open(str(sample_pdf_path))
        try:
            page = doc[0]
            assert processor.find_text_rect(page, "") is None
            assert processor.find_text_rect(page, "   ") is None
        finally:
            doc.close()

    def test_smart_punctuation_is_normalized(
        self, processor: DocumentProcessor, sample_pdf_path: Path
    ) -> None:
        doc = fitz.open(str(sample_pdf_path))
        try:
            page = doc[4]  # Antidotes page, has "Golpalott's" with a straight apostrophe
            # Feed a curly-quote variant; normalization should still match.
            rect = processor.find_text_rect(page, "Golpalott’s Third Law")
            assert rect is not None
        finally:
            doc.close()


# ---------------------------------------------------------------------------
# DocumentProcessor.render_annotations()
# ---------------------------------------------------------------------------


class TestRenderAnnotations:
    def _synthetic_annotations(self) -> list[Annotation]:
        return [
            Annotation(
                page=2,
                target_text="Sopophorous bean",
                annotation_type=AnnotationType.CORRECTION,
                content="Crush it, don't cut it. Releases twice the juice.",
                confidence=0.95,
                position="margin_right",
            ),
            Annotation(
                page=2,
                target_text="stir the potion seven times clockwise",
                annotation_type=AnnotationType.SHORTCUT,
                content="Five is plenty. Nobody's counting.",
                confidence=0.7,
                position="margin_left",
            ),
            Annotation(
                page=3,
                target_text="It is generally considered prudent, though not strictly necessary",
                annotation_type=AnnotationType.WARNING,
                content="DO NOT breathe these fumes for 'largely temporary' anything.",
                confidence=1.0,
                position="inline",
            ),
            Annotation(
                page=4,
                target_text="Brewing it correctly takes six months",
                annotation_type=AnnotationType.INVENTION,
                content="Mine takes eleven days. Told no one.",
                confidence=0.6,
                position="margin_right",
            ),
            Annotation(
                page=5,
                target_text="brew a separate antidote for each one individually",
                annotation_type=AnnotationType.CROSSED_OUT,
                content="Wrong -- treat the blend as one compound. Golpalott, obviously.",
                confidence=0.85,
                position="between_lines",
            ),
        ]

    def test_writes_output_pdf_with_same_page_count(
        self, processor: DocumentProcessor, sample_pdf_path: Path, tmp_path: Path
    ) -> None:
        output_path = tmp_path / "annotated_potions_textbook.pdf"
        processor.render_annotations(
            str(sample_pdf_path), self._synthetic_annotations(), str(output_path)
        )

        assert output_path.is_file()
        assert output_path.stat().st_size > 0

        src = fitz.open(str(sample_pdf_path))
        out = fitz.open(str(output_path))
        try:
            assert out.page_count == src.page_count
        finally:
            src.close()
            out.close()

    def test_annotated_pages_gain_native_pdf_annotations(
        self, processor: DocumentProcessor, sample_pdf_path: Path, tmp_path: Path
    ) -> None:
        output_path = tmp_path / "annotated_potions_textbook_2.pdf"
        processor.render_annotations(
            str(sample_pdf_path), self._synthetic_annotations(), str(output_path)
        )

        out = fitz.open(str(output_path))
        try:
            # Pages 2, 3, 4, 5 each received at least one annotation
            # (underline/highlight/circle/strikeout) via _mark_target.
            for page_number in (2, 3, 4, 5):
                page = out[page_number - 1]
                annots = list(page.annots())
                assert len(annots) >= 1, f"page {page_number} has no native PDF annotations"
        finally:
            out.close()

    def test_unmatched_target_text_is_skipped_not_raised(
        self, processor: DocumentProcessor, sample_pdf_path: Path, tmp_path: Path
    ) -> None:
        output_path = tmp_path / "annotated_with_miss.pdf"
        bogus = Annotation(
            page=2,
            target_text="This exact sentence does not appear anywhere in the book.",
            annotation_type=AnnotationType.DOODLE_NOTE,
            content="Ghost note.",
        )
        # Should not raise even though the target text can't be located.
        processor.render_annotations(str(sample_pdf_path), [bogus], str(output_path))
        assert output_path.is_file()

    def test_out_of_range_page_is_skipped_not_raised(
        self, processor: DocumentProcessor, sample_pdf_path: Path, tmp_path: Path
    ) -> None:
        output_path = tmp_path / "annotated_out_of_range.pdf"
        bogus = Annotation(
            page=99,
            target_text="Sopophorous bean",
            annotation_type=AnnotationType.INSIGHT,
            content="Never reached.",
        )
        processor.render_annotations(str(sample_pdf_path), [bogus], str(output_path))
        assert output_path.is_file()

    def test_empty_annotation_list_produces_valid_pdf(
        self, processor: DocumentProcessor, sample_pdf_path: Path, tmp_path: Path
    ) -> None:
        output_path = tmp_path / "annotated_empty.pdf"
        processor.render_annotations(str(sample_pdf_path), [], str(output_path))
        assert output_path.is_file()
        out = fitz.open(str(output_path))
        try:
            assert out.page_count == 5
        finally:
            out.close()


# ---------------------------------------------------------------------------
# AnnotationGenerator.generate_for_page() blank-page short-circuit
# ---------------------------------------------------------------------------
#
# NOTE: this section previously held a `TestParseResponse` class exercising
# `AnnotationGenerator._parse_response()` -- a plain-JSON-string parsing
# fallback (with markdown-fence stripping, bare-array support, etc.) plus a
# fake-SDK-Message parsing path. P1-T5 deleted `_parse_response` entirely:
# all response parsing now happens inside `AnthropicProvider` against real
# HTTP JSON, and no caller in the new architecture ever hands it a
# pre-extracted string (the fallback's original purpose). The parsing
# guarantees those tests pinned -- tool-block extraction, per-item
# validation drop (including non-dict items and out-of-range fields),
# invalid-enum drop, fence-stripping was httpx/JSON-body-only and has no
# equivalent -- now live in tests/test_anthropic_provider.py, tested against
# raw HTTP JSON fixtures instead of hand-built SDK-shaped doubles. Only the
# blank-page short-circuit below survived unchanged, since it never touched
# `_parse_response` at all.


def test_generate_for_page_short_circuits_on_empty_text(generator: AnnotationGenerator) -> None:
    # No provider call should occur: the empty/whitespace-only guard in
    # generate_for_page() returns before touching self._provider.
    assert generator.generate_for_page("", page_number=1) == []
    assert generator.generate_for_page("   \n\t  ", page_number=1) == []


# ---------------------------------------------------------------------------
# CLI --help surface
# ---------------------------------------------------------------------------


class TestCli:
    def test_main_help(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli_main, ["--help"])
        assert result.exit_code == 0
        assert "annotate" in result.output
        assert "preview" in result.output
        assert "eval" in result.output

    def test_annotate_help(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli_main, ["annotate", "--help"])
        assert result.exit_code == 0
        assert "--output" in result.output
        assert "--persona" in result.output
        assert "--pages" in result.output
        assert "--model" in result.output
        assert "--max-per-page" in result.output

    def test_preview_help(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli_main, ["preview", "--help"])
        assert result.exit_code == 0
        assert "--pages" in result.output
        assert "--persona" in result.output

    def test_eval_help(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli_main, ["eval", "--help"])
        assert result.exit_code == 0
        assert "--model" in result.output
        assert "--json-out" in result.output
        assert "--list" in result.output

    def test_version_flag(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # AUD-43: pin the exact Click-formatted version line against a known
        # metadata value, instead of a loose match that absorbed unrelated
        # RuntimeErrors as green.
        import importlib.metadata as _metadata

        monkeypatch.setattr(_metadata, "version", lambda _name: "9.9.9")
        runner = CliRunner()
        result = runner.invoke(cli_main, ["--version"])
        assert result.exit_code == 0
        assert result.output == "main, version 9.9.9\n"

    def test_annotate_requires_output_option(self, sample_pdf_path: Path) -> None:
        runner = CliRunner()
        # -o/--output is required; omitting it should fail fast via Click's
        # own validation, before any PDF processing happens.
        result = runner.invoke(cli_main, ["annotate", str(sample_pdf_path)])
        assert result.exit_code != 0
        assert "output" in result.output.lower() or "Missing option" in result.output

    def test_annotate_missing_input_file(self, tmp_path: Path) -> None:
        runner = CliRunner()
        missing = tmp_path / "nope.pdf"
        result = runner.invoke(
            cli_main, ["annotate", str(missing), "-o", str(tmp_path / "out.pdf")]
        )
        assert result.exit_code != 0


# ---------------------------------------------------------------------------
# Edge cases: empty text, very long annotations, special characters
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_wrap_text_on_empty_string(self, processor: DocumentProcessor) -> None:
        lines = processor._wrap_text("", max_width=100, fontsize=9)
        assert lines == [""]

    def test_wrap_text_on_very_long_single_word(self, processor: DocumentProcessor) -> None:
        # CONTRACT UPDATED for AUD-40 (P0-T5): a word wider than the column is
        # split into nonempty chunks that each fit, instead of coming back as
        # one over-wide line that renders off the page. Characters must be
        # preserved in order.
        long_word = "supercalifragilisticexpialidocious" * 4
        lines = processor._wrap_text(long_word, max_width=50, fontsize=9)
        assert len(lines) > 1
        assert all(line for line in lines)
        assert "".join(lines) == long_word
        for line in lines:
            assert processor._measure_font.text_length(line, fontsize=9) <= 50.5

    def test_render_very_long_annotation_content(
        self, processor: DocumentProcessor, sample_pdf_path: Path, tmp_path: Path
    ) -> None:
        huge_content = (
            "This is an absurdly long margin note that goes on and on, "
            "far longer than any sane annotator would ever scrawl in a "
            "textbook margin, testing that word-wrap and vertical layout "
            "hold up under stress. "
        ) * 20
        ann = Annotation(
            page=2,
            target_text="Sopophorous bean",
            annotation_type=AnnotationType.IMPROVEMENT,
            content=huge_content,
            confidence=0.5,
            position="margin_right",
        )
        output_path = tmp_path / "annotated_huge_note.pdf"
        # Must not raise, even though the note is absurdly long relative
        # to the margin width available.
        processor.render_annotations(str(sample_pdf_path), [ann], str(output_path))
        assert output_path.is_file()

    def test_render_special_characters_in_content(
        self, processor: DocumentProcessor, sample_pdf_path: Path, tmp_path: Path
    ) -> None:
        tricky_content = (
            "—Wrong.— ‘Curdles’ if you don't; — "
            "éèüñ ☃ — 100% guaranteed — \"quoted\" & <tagged>\n"
            "second line via embedded newline\ttab-in-content"
        )
        ann = Annotation(
            page=3,
            target_text="Amortentia is widely considered the most powerful love potion in existence.",
            annotation_type=AnnotationType.DOODLE_NOTE,
            content=tricky_content,
            confidence=0.4,
            position="inline",
        )
        output_path = tmp_path / "annotated_special_chars.pdf"
        processor.render_annotations(str(sample_pdf_path), [ann], str(output_path))
        assert output_path.is_file()

    def test_all_annotation_types_and_positions_render_without_error(
        self, processor: DocumentProcessor, sample_pdf_path: Path, tmp_path: Path
    ) -> None:
        # Cartesian-ish sweep: every AnnotationType against every valid
        # position, all anchored to a passage that actually exists, to
        # smoke-test add_margin_note()'s per-type/per-position branches.
        positions = ["margin_right", "margin_left", "inline", "between_lines"]
        annotations = []
        for i, (atype, position) in enumerate(zip(list(AnnotationType), positions * 2, strict=False)):
            annotations.append(
                Annotation(
                    page=2,
                    target_text="Sopophorous bean",
                    annotation_type=atype,
                    content=f"note #{i}",
                    confidence=0.5 + 0.05 * i,
                    position=position,
                )
            )
        output_path = tmp_path / "annotated_sweep.pdf"
        processor.render_annotations(str(sample_pdf_path), annotations, str(output_path))
        assert output_path.is_file()

    def test_invalid_position_defaults_to_margin_right(
        self,
        processor: DocumentProcessor,
        sample_pdf_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # AUD-42: the test's own name promises margin_right dispatch — spy on
        # the margin writer (delegating to the real one) and assert the
        # out-of-vocabulary position actually routes there, exactly once.
        requested_sides: list[str] = []
        real_write = DocumentProcessor._write_margin_text

        def spy(self, shape, page, rect, text, ink, angle, fontsize, opacity, side):  # type: ignore[no-untyped-def]
            requested_sides.append(side)
            return real_write(self, shape, page, rect, text, ink, angle, fontsize, opacity, side)

        monkeypatch.setattr(DocumentProcessor, "_write_margin_text", spy)
        doc = fitz.open(str(sample_pdf_path))
        try:
            page = doc[1]
            rect = processor.find_text_rect(page, "Sopophorous bean")
            assert rect is not None
            processor.add_margin_note(
                page,
                rect,
                "test note",
                AnnotationType.CORRECTION,
                confidence=0.5,
                position="somewhere_weird",
            )
        finally:
            doc.close()
        assert requested_sides == ["right"]

    def test_confidence_out_of_bounds_rejected_by_model(self) -> None:
        # AUD-41: the rejection must be Pydantic validation AND locate the
        # confidence field — any other exception is a different bug.
        with pytest.raises(ValidationError) as excinfo:
            Annotation(
                page=1,
                target_text="x",
                annotation_type=AnnotationType.DOODLE_NOTE,
                content="y",
                confidence=1.5,
            )
        assert any(err["loc"] == ("confidence",) for err in excinfo.value.errors())

    def test_annotations_from_plan_flattens_and_fixes_page_mismatch(self) -> None:
        from halfblood.models import AnnotatedPage, AnnotationPlan

        mismatched = Annotation(
            page=99,  # deliberately wrong; should be corrected to page 2
            target_text="x",
            annotation_type=AnnotationType.DOODLE_NOTE,
            content="y",
        )
        plan = AnnotationPlan(
            title="t",
            pages=[AnnotatedPage(page_number=2, original_text="...", annotations=[mismatched])],
        )
        flattened = DocumentProcessor.annotations_from_plan(plan)
        assert len(flattened) == 1
        assert flattened[0].page == 2
