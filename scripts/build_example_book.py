"""Build the committed example book (Alice's Adventures in Wonderland) from
Project Gutenberg sources.

Produces:
  examples/src/alice.pdf   -- typeset from pg11.txt with a real text layer (80 pages)
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



def strip_gutenberg_boilerplate(text: str) -> str:
    start = START_MARK.search(text)
    end = END_MARK.search(text)
    if not start or not end or end.start() < start.end():
        raise SystemExit("could not locate Gutenberg START/END markers")
    return text[start.end() : end.start()].strip()


#: A chapter heading block: "CHAPTER I." on its own line, then the title.
CHAPTER_BLOCK = re.compile(r"^CHAPTER [IVXLC]+\.(?:\s.*)?$", re.DOTALL)
#: Gutenberg's placeholder for an illustration the plain text cannot carry.
ILLUSTRATION = re.compile(r"^\[Illustration[^\]]*\]$")


def paragraphs(body: str) -> list[str]:
    """Every paragraph of the book's text, without front matter or headings.

    Dropped: everything before the first chapter heading (illustration
    placeholder, title, byline, edition line and the table of contents), the
    chapter heading blocks themselves, and ``[Illustration]`` placeholders.
    Nothing else is filtered: a one-line reply such as "Not I!" said the Lory
    hastily. is text of the book. (A former length filter, "drop anything under
    40 characters", removed 74 such paragraphs while keeping the table of
    contents and the three chapter headings that happened to be longer.)
    """
    blocks = [" ".join(block.split()) for block in re.split(r"\n\s*\n", body)]
    blocks = [block for block in blocks if block]
    first_chapter = next(
        (i for i, block in enumerate(blocks) if CHAPTER_BLOCK.match(block)), None
    )
    if first_chapter is None:
        raise SystemExit("could not locate the first chapter heading")
    return [
        block
        for block in blocks[first_chapter:]
        if not CHAPTER_BLOCK.match(block) and not ILLUSTRATION.match(block)
    ]


#: Project Gutenberg plain text marks italics as ``_word_``. The closing marker
#: may sit inside a word (``_Un_important``), so only the opening one is
#: required to start a word.
GUTENBERG_ITALIC = re.compile(r"(?<![\w_])_(?=\S)([^_]+?)(?<=\S)_")


def italicize(escaped: str) -> str:
    """Turn Gutenberg ``_..._`` italic markers into ``<i>`` on escaped text."""
    return GUTENBERG_ITALIC.sub(r"<i>\1</i>", escaped)


def to_html(paras: list[str]) -> str:
    parts = [
        "<html><head><style>",
        "body { font-family: serif; font-size: 13pt; line-height: 1.7; }",
        "p { margin: 0 0 9pt 0; }",
        "</style></head><body>",
    ]
    parts.extend(f"<p>{italicize(html.escape(p))}</p>" for p in paras)
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
