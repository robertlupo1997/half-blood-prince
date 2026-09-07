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


def test_direct_web_preview_refuses_input_alias(tmp_path):
    import json

    from halfblood.web_preview import generate_preview
    source = tmp_path / "plan.json"
    source.write_text(json.dumps({"title": "Owned", "prince_persona": "Test", "pages": []}))
    before = source.read_bytes()
    with pytest.raises(ValueError, match="same file"):
        generate_preview(source, source)
    assert source.read_bytes() == before


@pytest.mark.parametrize(("global_fixed", "override", "expected"), [
    (False, "rendition:layout-pre-paginated", "unsupported_renderer"),
    (True, "", "unsupported_renderer"),
    (True, "rendition:layout-reflowable", "resolved"),
])
def test_epub_spine_rendition_override(tmp_path, global_fixed, override, expected):
    import zipfile
    from xml.etree import ElementTree as ET

    original = make_source(tmp_path, "epub", "Uniquely supported quotation.")
    fixed = tmp_path / "rendition.epub"
    ns = "{http://www.idpf.org/2007/opf}"
    with zipfile.ZipFile(original) as archive, zipfile.ZipFile(fixed, "w") as output:
        for member in archive.infolist():
            data = archive.read(member)
            if member.filename.endswith(".opf"):
                package = ET.fromstring(data)
                if global_fixed:
                    meta = ET.SubElement(package.find(ns + "metadata"), ns + "meta",
                                         {"property": "rendition:layout"})
                    meta.text = "pre-paginated"
                if override:
                    package.find(ns + "spine/" + ns + "itemref").set("properties", override)
                data = ET.tostring(package, encoding="utf-8", xml_declaration=True)
            output.writestr(member, data)
    report = EpubProcessor().render_plan(
        str(fixed), make_plan("Uniquely supported quotation."), str(tmp_path / "out.epub"),
    )
    assert report.placements[0].result.status.value == expected
    if expected == "unsupported_renderer":
        assert not report.rendered and not report.marks_only
        assert report.skipped[0].reason.value == expected
