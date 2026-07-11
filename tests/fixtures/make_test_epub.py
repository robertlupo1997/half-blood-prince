"""One-off generator script for tests/fixtures/sample_book.epub.

Not part of the test suite itself (no test_*.py naming) -- it's the
recipe used to build the fixture. Re-run this file directly if the
fixture ever needs to be regenerated:

    python tests/fixtures/make_test_epub.py
"""

from __future__ import annotations

from pathlib import Path

from ebooklib import epub

OUT_PATH = Path(__file__).resolve().parent / "sample_book.epub"

CHAPTERS = [
    (
        "On Combustion",
        "<h1>On Combustion</h1><p>When a candle burns, the wax "
        "combines with oxygen from the air. The flame's <em>luminous</em> zone "
        "contains unburnt carbon particles heated to incandescence. Complete "
        "combustion yields carbonic acid and water vapour.</p>",
    ),
    (
        "On Acids",
        "<h1>On Acids</h1><p>An acid turns blue litmus red. The "
        "mineral acids — sulphuric, nitric, and muriatic — must be diluted by "
        "pouring acid into water, never water into acid, lest the vessel crack "
        "from sudden heat.</p>",
    ),
    (
        "On Distillation",
        "<h1>On Distillation</h1><p>Distillation separates "
        "liquids by their boiling points. The retort is heated gently; the "
        "vapour condenses in the worm. Impatient heating spoils the spirit and "
        "risks bursting the apparatus.</p>",
    ),
]


def main() -> None:
    book = epub.EpubBook()
    book.set_identifier("halfblood-test-epub")
    book.set_title("Elements of Practical Chemistry")
    book.set_language("en")
    book.add_author("A Public-Domain Chemist")

    items = []
    for i, (title, html) in enumerate(CHAPTERS, 1):
        ch = epub.EpubHtml(title=title, file_name=f"ch{i}.xhtml", lang="en")
        ch.content = html
        book.add_item(ch)
        items.append(ch)

    book.toc = items
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav", *items]

    epub.write_epub(str(OUT_PATH), book)
    print(f"wrote {OUT_PATH}")


if __name__ == "__main__":
    main()
