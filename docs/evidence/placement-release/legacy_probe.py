import fitz
from bs4 import BeautifulSoup

from halfblood.document_processor import DocumentProcessor
from halfblood.documents.epub import locate_across_nodes
from halfblood.documents.pdf import PdfPageIndex
from halfblood.models.annotations import Annotation, TargetSelector


def ann(target, **kwargs):
    return Annotation(
        id="probe",
        target=TargetSelector(exact=target, **kwargs),
        annotation_type="warning",
        content="Fifty milligrams can be fatal.",
        confidence=1,
        requested_placement="margin_right",
        mark_intent="underline",
    )


def pdf_probe(name, lines, annotation, indexed=True):
    doc = fitz.open()
    page = doc.new_page(width=650, height=800)
    for i, line in enumerate(lines):
        page.insert_text((72, 72 + 60 * i), line, fontsize=11)
    idx = PdfPageIndex(page)
    result = DocumentProcessor()._resolve_annotation_to_anchor(
        page, idx if indexed else None, annotation
    )
    print(
        name,
        "source=" + repr(idx.text),
        "target=" + repr(annotation.target.model_dump(exclude_none=True)),
    )
    print(
        "  result=",
        None
        if result is None
        else {
            "range": result.char_range,
            "anchored": idx.text[slice(*result.char_range)],
            "rects": [tuple(round(v, 2) for v in q.rect) for q in result.quads],
        },
    )
    if result is not None and not indexed:
        print("  geometry_text=", repr(" ".join(page.get_textbox(q.rect) for q in result.quads)))
    doc.close()


def epub_probe(name, markup, selector):
    soup = BeautifulSoup(markup, "lxml")
    root = soup.body or soup
    result = locate_across_nodes(root, selector)
    print(name, "markup=" + repr(markup), "target=" + repr(selector.model_dump(exclude_none=True)))
    print(
        "  result=",
        None
        if result is None
        else {
            "text": "".join(str(s.node)[s.start : s.end] for s in result.segments),
            "segments": [
                (s.node.parent.get("id"), str(s.node)[s.start : s.end]) for s in result.segments
            ],
            "reason": result.reason,
        },
    )


quote = "The correct dose of this medicine is fifty milligrams."
wrong = "The correct dose of this medicine is five milligrams."
intended = "The correct dose 0f this medicine is fifty milligrams."
pdf_probe("PDF prefix decoy", [wrong, intended], ann(quote))
epub_probe(
    "EPUB prefix decoy",
    f'<p id="wrong">{wrong}</p><p id="intended">{intended}</p>',
    TargetSelector(exact=quote),
)
pdf_probe(
    "PDF overlap exact",
    ["alpha alpha alpha alpha"],
    ann("alpha alpha alpha", prefix="alpha ", start_offset=6, end_offset=23),
)
epub_probe(
    "EPUB overlap exact",
    "<p>alpha alpha alpha alpha</p>",
    TargetSelector(exact="alpha alpha alpha", prefix="alpha ", start_offset=6, end_offset=23),
)
pdf_probe(
    "PDF overlap CI",
    ["ALPHA alpha ALPHA alpha"],
    ann("Alpha Alpha Alpha", prefix="ALPHA ", start_offset=6, end_offset=23),
)
epub_probe(
    "EPUB overlap CI",
    "<p>ALPHA alpha ALPHA alpha</p>",
    TargetSelector(exact="Alpha Alpha Alpha", prefix="ALPHA ", start_offset=6, end_offset=23),
)
pdf_probe(
    "PDF no-index ambiguity",
    ["Never heat the vessel.", "Never heat the vessel."],
    ann("Never heat the vessel."),
    indexed=False,
)
pdf_probe(
    "PDF no-index explicit second",
    ["Never heat the vessel.", "Never heat the vessel."],
    ann("Never heat the vessel.", start_offset=22),
    indexed=False,
)
pdf_probe(
    "PDF no-index mixed-case union",
    ["Never heat the vessel.", "NEVER HEAT THE VESSEL."],
    ann("Never heat the vessel.", start_offset=0),
    indexed=False,
)
epub_probe(
    "EPUB CSS-separated fixed layout",
    '<div><span id="wrong" style="position:absolute;top:20px;left:20px">Never heat </span><span id="unrelated" style="position:absolute;top:600px;left:400px">the vessel.</span></div>',
    TargetSelector(exact="Never heat the vessel."),
)
epub_probe(
    "EPUB inline control",
    "<p>Never <em>heat</em> the <strong>vessel.</strong></p>",
    TargetSelector(exact="Never heat the vessel."),
)
