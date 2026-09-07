"""Exercise the supported processor seam with deliberately misleading evidence."""
from pathlib import Path

import fitz
import pytest
from bs4 import BeautifulSoup
from ebooklib import epub

from halfblood.document_processor import DocumentProcessor
from halfblood.epub_processor import EpubProcessor
from halfblood.models.annotations import Annotation, MarkIntent, TargetSelector
from halfblood.models.documents import AnnotationPlan, GenerationProvenance, SourceInfo, Unit
from halfblood.models.legacy import AnnotationType


def make_plan(*quotes: str) -> AnnotationPlan:
    return AnnotationPlan(
        id="evidence-test", title="Original test fixture", persona="Test", document_seed=3,
        generation=GenerationProvenance(),
        source=SourceInfo(fingerprint="test", media_type="test", unit_count=1),
        units=[Unit(unit_id="one", ordinal=1, label="One", original_text="",
                    source_locator="unit:1", annotations=[
                        Annotation(id=f"ann-{i}", target=TargetSelector(exact=quote),
                                   annotation_type=AnnotationType.CORRECTION, content="Check this.",
                                   confidence=1, requested_placement="margin_right",
                                   mark_intent=MarkIntent.UNDERLINE)
                        for i, quote in enumerate(quotes)
                    ])],
    )


def make_source(tmp_path: Path, format: str, text: str, *, fixed: bool = False) -> Path:
    path = tmp_path / f"source.{format}"
    if format == "pdf":
        with fitz.open() as doc:
            page = doc.new_page()
            page.insert_textbox(fitz.Rect(72, 72, 460, 600), text, fontsize=11)
            doc.save(path)
    else:
        book = epub.EpubBook()
        book.set_identifier("owned-test")
        book.set_title("Original test fixture")
        book.set_language("en")
        if fixed:
            book.add_metadata(None, "meta", "pre-paginated", {"property": "rendition:layout"})
        chapter = epub.EpubHtml(uid="chapter", file_name="chapter.xhtml", lang="en")
        chapter.content = f"<p>{text}</p>"
        book.add_item(chapter)
        book.spine = [chapter]
        book.add_item(epub.EpubNcx())
        book.add_item(epub.EpubNav())
        book.toc = [chapter]
        epub.write_epub(str(path), book)
    return path


@pytest.mark.parametrize("format", ["pdf", "epub"])
def test_render_plan_refuses_false_complete_quote(tmp_path: Path, format: str):
    source = make_source(tmp_path, format, "The correct dose of this medicine is five milligrams.")
    plan = make_plan("The correct dose of this medicine is fifty milligrams.")
    processor = DocumentProcessor() if format == "pdf" else EpubProcessor()
    report = processor.render_plan(str(source), plan, str(tmp_path / f"out.{format}"))
    assert report.rendered_count == 0
    assert report.skipped_count == 1
    assert not report.marks_only


@pytest.mark.parametrize("format", ["pdf", "epub"])
def test_render_plan_refuses_duplicate_quote(tmp_path: Path, format: str):
    source = make_source(tmp_path, format, "The same quote. The same quote.")
    plan = make_plan("The same quote")
    processor = DocumentProcessor() if format == "pdf" else EpubProcessor()
    report = processor.render_plan(str(source), plan, str(tmp_path / f"out.{format}"))
    assert report.rendered_count == 0
    assert report.skipped[0].reason.value == "ambiguous_target"


def test_epub_keeps_initial_resolution_after_prior_dom_mutation(tmp_path: Path):
    source = make_source(tmp_path, "epub", "First evidence. Second evidence. Third evidence.")
    report = EpubProcessor().render_plan(
        str(source), make_plan("First evidence", "Second evidence", "Third evidence"),
        str(tmp_path / "out.epub"),
    )
    assert report.rendered_count == 3
    output = epub.read_epub(str(tmp_path / "out.epub"))
    soup = BeautifulSoup(output.get_item_with_id("chapter").get_content(), "lxml")
    assert [node.get_text() for node in soup.select(".hbp-target")] == [
        "First evidence", "Second evidence", "Third evidence",
    ]
