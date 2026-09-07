"""Rebuild small placement inputs, not the checked-in expected answers.

Run with `.venv/bin/python benchmarks/build_fixtures.py` from the repository root.
No network, model, placement resolver, or renderer is used.
"""
from __future__ import annotations

import html
import zipfile
from pathlib import Path

import fitz

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def write_pdf(text: str, path: Path) -> None:
    """Write known-position Courier lines. Fixed bytes under one PyMuPDF version."""
    with fitz.open() as doc:
        page = doc.new_page(width=612, height=792)
        for index, line in enumerate(text.splitlines()):
            page.insert_text((72, 96 + index * 18), line, fontname="cour", fontsize=10)
        doc.save(path, no_new_id=True)


def write_epub(text: str, path: Path, *, inline_tags: bool = False) -> None:
    """Write a reproducible, minimal reflowable EPUB with split inline nodes."""
    body = html.escape(text)
    if inline_tags:
        body = body.replace("that Alice had not", "that <em>Alice</em> had <strong>not</strong>")
        body = body.replace("herself before she found", "herself <em>before she</em> found")
    chapter = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<html xmlns="http://www.w3.org/1999/xhtml"><head><title>Placement fixture</title>'
        '</head><body><p>' + body + '</p></body></html>'
    )
    files = {
        "mimetype": "application/epub+zip",
        "META-INF/container.xml": (
            '<?xml version="1.0"?>'
            '<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
            '<rootfiles><rootfile full-path="EPUB/package.opf" '
            'media-type="application/oebps-package+xml"/></rootfiles></container>'
        ),
        "EPUB/package.opf": (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="id">'
            '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
            '<dc:identifier id="id">halfblood-placement-fixture</dc:identifier>'
            '<dc:title>Offline placement fixture</dc:title><dc:language>en</dc:language>'
            '<meta property="dcterms:modified">2026-01-01T00:00:00Z</meta></metadata>'
            '<manifest><item id="chapter" href="chapter.xhtml" '
            'media-type="application/xhtml+xml"/><item id="nav" href="nav.xhtml" '
            'media-type="application/xhtml+xml" properties="nav"/></manifest>'
            '<spine><itemref idref="chapter"/></spine></package>'
        ),
        "EPUB/chapter.xhtml": chapter,
        "EPUB/nav.xhtml": (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<html xmlns="http://www.w3.org/1999/xhtml" '
            'xmlns:epub="http://www.idpf.org/2007/ops"><head><title>Contents</title></head>'
            '<body><nav epub:type="toc"><ol><li><a href="chapter.xhtml">Excerpt</a>'
            '</li></ol></nav></body></html>'
        ),
    }
    with zipfile.ZipFile(path, "w") as archive:
        for name, content in files.items():
            info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_STORED
            info.external_attr = 0o644 << 16
            archive.writestr(info, content)


def main() -> None:
    for stem in ("alice-excerpt", "overlap", "duplicate", "candidate-limit"):
        text = (FIXTURES / f"{stem}.txt").read_text(encoding="utf-8")
        write_pdf(text, FIXTURES / f"{stem}.pdf")
        write_epub(text, FIXTURES / f"{stem}.epub", inline_tags=stem == "alice-excerpt")
    write_pdf("", FIXTURES / "no-text-layer.pdf")
    write_epub(
        (FIXTURES / "source-limit.txt").read_text(encoding="utf-8"),
        FIXTURES / "source-limit.epub",
    )


if __name__ == "__main__":
    main()
