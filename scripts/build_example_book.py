"""Build the committed example book (Alice's Adventures in Wonderland) from
Project Gutenberg sources.

Produces:
  examples/src/alice.pdf   -- typeset from pg11.txt with a real text layer (~60 pages)
  examples/src/alice.epub  -- verbatim Project Gutenberg EPUB (ebook #11)

Usage: python scripts/build_example_book.py [--gutenberg-txt PATH] [--epub PATH]

The PDF is deterministic given the same PyMuPDF version, so anyone can verify
the committed example was produced by this tree.
"""
from __future__ import annotations

import argparse
import html
import re
import sys
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TXT_URL = "https://www.gutenberg.org/cache/epub/11/pg11.txt"
EPUB_URL = "https://www.gutenberg.org/ebooks/11.epub3.images"

START_MARK = re.compile(r"\*\*\*\s*START OF (?:THE|THIS) PROJECT GUTENBERG.*?\*\*\*")
END_MARK = re.compile(r"\*\*\*\s*END OF (?:THE|THIS) PROJECT GUTENBERG.*?\*\*\*")

CHAPTER_HEADING = re.compile(r"^(CHAPTER [IVX]+\.)$")
TITLE_LINE = re.compile(r"^([A-Z][A-Z '\u2019-]+)$")


def strip_gutenberg_boilerplate(text: str) -> str:
    start = START_MARK.search(text)
    end = END_MARK.search(text)
    if not start or not end or end.start() < start.end():
        raise SystemExit("could not locate Gutenberg START/END markers")
    return text[start.end() : end.start()].strip()


def paragraphs(body: str) -> list[str]:
    out: list[str] = []
    for block in re.split(r"\n\s*\n", body):
        clean = " ".join(block.split())
        if len(clean) >= 40:  # drop headings/orphan lines; keep real prose
            out.append(clean)
    return out


def to_html(paras: list[str]) -> str:
    parts = [
        "<html><head><style>",
        "body { font-family: serif; font-size: 13pt; line-height: 1.7; }",
        "p { margin: 0 0 9pt 0; }",
        "</style></head><body>",
    ]
    parts.extend(f"<p>{html.escape(p)}</p>" for p in paras)
    parts.append("</body></html>")
    return "\n".join(parts)


def build_pdf(txt_path: Path, out_pdf: Path, page_w: float, page_h: float) -> int:
    import fitz

    raw = txt_path.read_text(encoding="utf-8-sig", errors="replace")
    paras = paragraphs(strip_gutenberg_boilerplate(raw))
    story = fitz.Story(html=to_html(paras))
    writer = fitz.DocumentWriter(str(out_pdf))
    mediabox = fitz.paper_rect("letter")
    margin = 54  # 0.75in margins
    where = mediabox + (margin, margin, -margin, -margin)
    n_pages = 0
    more = True
    while more:
        device = writer.begin_page(mediabox)
        more, _filled = story.place(where)
        story.draw(device)
        writer.end_page()
        n_pages += 1
    writer.close()
    return n_pages


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--gutenberg-txt", type=Path, default=None,
                    help="cached pg11.txt (downloaded if missing)")
    ap.add_argument("--epub", type=Path, default=None,
                    help="cached pg11 epub (downloaded if missing)")
    ap.add_argument("--out-dir", type=Path, default=REPO / "examples" / "src")
    args = ap.parse_args(argv)

    cache = args.out_dir
    cache.mkdir(parents=True, exist_ok=True)
    txt_path = args.gutenberg_txt or cache / "pg11.txt"
    epub_out = args.epub or cache / "alice.epub"
    pdf_out = cache / "alice.pdf"

    if not txt_path.exists():
        print(f"downloading {TXT_URL}")
        urllib.request.urlretrieve(TXT_URL, txt_path)
    if not epub_out.exists():
        print(f"downloading {EPUB_URL}")
        urllib.request.urlretrieve(EPUB_URL, epub_out)

    import fitz
    n_pages = build_pdf(txt_path, pdf_out, fitz.paper_rect("letter").width, fitz.paper_rect("letter").height)
    size_kb = pdf_out.stat().st_size // 1024
    print(f"wrote {pdf_out} ({n_pages} pages, {size_kb} KB)")
    print(f"kept  {epub_out} ({epub_out.stat().st_size // 1024} KB)")

    target_lo, target_hi = 40, 80
    if not (target_lo <= n_pages <= target_hi):
        print(f"WARNING: page count {n_pages} outside roadmap range {target_lo}-{target_hi}",
              file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
