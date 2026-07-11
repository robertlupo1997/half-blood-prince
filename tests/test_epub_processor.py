"""P0-T8 — EPUB pipeline coverage + symmetric smart-punctuation matching.

AUD-24: the EPUB pipeline (a whole shipping format) has zero tests — spine
ordering, nav handling, target location, rendering, and the write round-trip
can all regress silently.

AUD-18: ``_normalize_search_text`` folds smart quotes/dashes in the *target*
but node text is only whitespace-collapsed, so a book that itself uses
typographic punctuation defeats exact matching in BOTH directions (even a
curly target against curly node text fails, because only the target is
normalized). The single-word fallback then silently anchors the wrong,
shorter slice — or nothing at all for apostrophes.

Also pinned here (found while building this coverage): EbookLib's
``EpubHtml.get_content()`` regenerates each chapter's ``<head>`` at write
time from its ``metas``/``title``/``links`` only, so a ``<style>`` tag
injected into the soup's head is silently dropped from the written EPUB.
Every class-based rule (target underline/highlight/strikethrough, cursive
note font, float-right sidenote) never reaches a reader; only inline
``style=`` attributes survive. The annotation CSS must therefore reach the
output through a mechanism EbookLib preserves.

No network calls are made anywhere in this file.
"""

from __future__ import annotations

import logging
import posixpath
import zipfile
from pathlib import Path

import pytest
from bs4 import BeautifulSoup
from ebooklib import epub
from lxml import etree

from halfblood.epub_processor import EpubProcessor
from halfblood.models import Annotation, AnnotationType

FIXTURE = Path(__file__).parent / "fixtures" / "sample_book.epub"

_XHTML_NS = {"x": "http://www.w3.org/1999/xhtml"}

# The fixture's reading order as `load()` reports it today: EbookLib writes
# the nav document into the spine with linear="yes", so it counts as page 1
# and the three chapters are pages 2-4.
_NAV_PAGE = 1
_COMBUSTION_PAGE = 2
_ACIDS_PAGE = 3
_DISTILLATION_PAGE = 4


def _ann(
    page: int,
    target: str,
    content: str = "Obvious.",
    atype: AnnotationType = AnnotationType.INSIGHT,
    confidence: float = 0.9,
) -> Annotation:
    return Annotation(
        page=page,
        target_text=target,
        annotation_type=atype,
        content=content,
        confidence=confidence,
        position="margin_right",
    )


def _render(tmp_path: Path, annotations: list[Annotation]) -> Path:
    out = tmp_path / "annotated.epub"
    EpubProcessor(seed=7).render_annotations(str(FIXTURE), annotations, str(out))
    return out


def _chapter_bytes(zf: zipfile.ZipFile, basename: str) -> bytes:
    name = next(n for n in zf.namelist() if n.endswith(basename))
    return zf.read(name)


def _hbp_css_sources(zf: zipfile.ZipFile, basename: str) -> list[str]:
    """Every CSS text reachable from a chapter that styles the annotations:
    inline ``<style>`` tags plus ``<link rel="stylesheet">`` files resolved
    inside the archive. A source counts if it contains the ``.hbp-note``
    rules. This is implementation-neutral: inline or linked both satisfy it,
    but the CSS must actually be reachable from the written chapter.
    """
    chapter_name = next(n for n in zf.namelist() if n.endswith(basename))
    root = etree.fromstring(zf.read(chapter_name))
    sources: list[str] = []
    for style in root.findall(".//x:style", _XHTML_NS):
        text = style.text or ""
        if ".hbp-note" in text:
            sources.append(text)
    base = posixpath.dirname(chapter_name)
    for link in root.findall(".//x:link", _XHTML_NS):
        if (link.get("rel") or "").lower() != "stylesheet":
            continue
        href = link.get("href")
        if not href:
            continue
        target = posixpath.normpath(posixpath.join(base, href))
        if target in zf.namelist():
            css = zf.read(target).decode("utf-8", errors="replace")
            if ".hbp-note" in css:
                sources.append(css)
    return sources


# ---------------------------------------------------------------------------
# Loading: spine order, nav handling, metadata (AUD-24 guards)
# ---------------------------------------------------------------------------


def test_load_returns_linear_spine_documents_in_reading_order() -> None:
    pages = EpubProcessor().load(str(FIXTURE))
    assert [p.page_number for p in pages] == [1, 2, 3, 4]
    assert pages[_COMBUSTION_PAGE - 1].text.startswith("On Combustion")
    assert pages[_ACIDS_PAGE - 1].text.startswith("On Acids")
    assert pages[_DISTILLATION_PAGE - 1].text.startswith("On Distillation")


def test_nav_document_with_linear_yes_counts_as_a_page() -> None:
    # PINS CURRENT BEHAVIOR: only linear="no" spine items are excluded.
    # EbookLib writes the nav document with linear="yes", so it is page 1
    # and every chapter index is shifted by one. `load()` and
    # `render_annotations()` agree on this numbering (both walk the same
    # spine), so generation and rendering stay consistent end to end.
    pages = EpubProcessor().load(str(FIXTURE))
    assert len(pages) == 4
    assert pages[_NAV_PAGE - 1].text.startswith("Elements of Practical Chemistry")


def test_iter_spine_documents_skips_linear_no_missing_and_non_documents() -> None:
    book = epub.EpubBook()
    ch1 = epub.EpubHtml(uid="c1", file_name="c1.xhtml")
    ch1.content = b"<html><body><p>one</p></body></html>"
    ch2 = epub.EpubHtml(uid="c2", file_name="c2.xhtml")
    ch2.content = b"<html><body><p>two</p></body></html>"
    aux = epub.EpubHtml(uid="aux", file_name="aux.xhtml")
    aux.content = b"<html><body><p>aux</p></body></html>"
    ncx = epub.EpubNcx()
    for item in (ch1, ch2, aux, ncx):
        book.add_item(item)
    # Read-back spine shape: (idref, linear) pairs.
    book.spine = [("aux", "no"), ("c1", "yes"), ("ghost", "yes"), ("ncx", "yes"), ("c2", "yes")]

    docs = EpubProcessor._iter_spine_documents(book)
    assert [(index, item.id) for index, item in docs] == [(1, "c1"), (2, "c2")]


def test_pages_carry_nominal_reflowable_dimensions() -> None:
    pages = EpubProcessor().load(str(FIXTURE))
    assert all(p.width == 600.0 and p.height == 800.0 for p in pages)


# ---------------------------------------------------------------------------
# AUD-18 — smart punctuation must match symmetrically
# ---------------------------------------------------------------------------

_CURLY_SENTENCE = "He observed the “luminous” zone with care. It’s hot — very hot."
_STRAIGHT_SENTENCE = "He observed the \"luminous\" zone with care. It's hot - very hot."


@pytest.mark.parametrize(
    ("node_text", "target", "expected_slice"),
    [
        # Book text curly, LLM target straight — the common real-book case.
        (_CURLY_SENTENCE, 'the "luminous" zone', "the “luminous” zone"),
        # Both curly: still broken today because only the target is folded.
        (_CURLY_SENTENCE, "the “luminous” zone", "the “luminous” zone"),
        # Book text straight, target curly — already works; keep as guard.
        (_STRAIGHT_SENTENCE, "the “luminous” zone", 'the "luminous" zone'),
        (_STRAIGHT_SENTENCE, 'the "luminous" zone', 'the "luminous" zone'),
        # Apostrophes both directions.
        (_CURLY_SENTENCE, "It's hot", "It’s hot"),
        (_STRAIGHT_SENTENCE, "It’s hot", "It's hot"),
        # Dashes both directions.
        (_CURLY_SENTENCE, "hot - very hot", "hot — very hot"),
        (_STRAIGHT_SENTENCE, "hot — very hot", "hot - very hot"),
    ],
    ids=[
        "double-quotes:straight-target/curly-node",
        "double-quotes:curly-target/curly-node",
        "double-quotes:curly-target/straight-node",
        "double-quotes:straight-target/straight-node",
        "apostrophe:straight-target/curly-node",
        "apostrophe:curly-target/straight-node",
        "dash:hyphen-target/em-dash-node",
        "dash:em-dash-target/hyphen-node",
    ],
)
def test_smart_punctuation_matching_is_symmetric(
    node_text: str, target: str, expected_slice: str
) -> None:
    soup = BeautifulSoup(f"<html><body><p>{node_text}</p></body></html>", "lxml")
    located = EpubProcessor()._locate_text(soup, target)
    assert located is not None, f"target {target!r} was not located at all"
    node, start, end = located
    # The FULL phrase must be anchored — a single-word fallback slice means
    # the exact match failed and the annotation lands on the wrong text.
    assert str(node)[start:end] == expected_slice


def test_absent_target_is_not_located() -> None:
    soup = BeautifulSoup(f"<html><body><p>{_STRAIGHT_SENTENCE}</p></body></html>", "lxml")
    assert EpubProcessor()._locate_text(soup, "entirely absent phrasing") is None


def test_curly_quoted_book_gets_full_phrase_wrapped_end_to_end(tmp_path: Path) -> None:
    # The AUD-18 fix must reach the shipping render path, not just the
    # locator: a book set with typographic quotes, annotated with a
    # straight-quoted target, wraps the complete phrase.
    book = epub.EpubBook()
    book.set_identifier("hbp-curly-test")
    book.set_title("Curly")
    book.set_language("en")
    ch = epub.EpubHtml(uid="c1", file_name="c1.xhtml", lang="en")
    ch.content = (
        "<h1>C</h1><p>Stir until the mixture turns “pale green”, then rest.</p>"
    )
    book.add_item(ch)
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.toc = [ch]
    book.spine = ["nav", ch]
    src = tmp_path / "curly.epub"
    epub.write_epub(str(src), book)

    out = tmp_path / "curly-annotated.epub"
    ann = _ann(page=2, target='turns "pale green", then')  # nav is page 1
    EpubProcessor().render_annotations(str(src), [ann], str(out))

    with zipfile.ZipFile(out) as zf:
        root = etree.fromstring(_chapter_bytes(zf, "c1.xhtml"))
    targets = [
        el
        for el in root.findall(".//x:span", _XHTML_NS)
        if "hbp-target" in (el.get("class") or "")
    ]
    assert len(targets) == 1
    assert targets[0].text == "turns “pale green”, then"


# ---------------------------------------------------------------------------
# Render round-trip: unzip and inspect the written artifact (AUD-24)
# ---------------------------------------------------------------------------


def test_render_wraps_target_and_note_in_intended_chapter_only(tmp_path: Path) -> None:
    out = _render(
        tmp_path,
        [_ann(_COMBUSTION_PAGE, "unburnt carbon particles", content="Soot, plainly.")],
    )
    with zipfile.ZipFile(out) as zf:
        ch1 = _chapter_bytes(zf, "ch1.xhtml")
        untouched = [
            _chapter_bytes(zf, name) for name in ("ch2.xhtml", "ch3.xhtml", "nav.xhtml")
        ]
    assert b"hbp-target" in ch1 and b"hbp-note" in ch1
    assert b"Soot, plainly." in ch1
    for data in untouched:
        assert b"hbp-target" not in data and b"hbp-note" not in data


def test_rendered_chapters_are_valid_xhtml(tmp_path: Path) -> None:
    out = _render(
        tmp_path,
        [
            _ann(_COMBUSTION_PAGE, "unburnt carbon particles"),
            _ann(_ACIDS_PAGE, "pouring acid into water", atype=AnnotationType.WARNING),
        ],
    )
    with zipfile.ZipFile(out) as zf:
        for name in zf.namelist():
            if name.endswith(".xhtml"):
                etree.fromstring(zf.read(name))  # raises XMLSyntaxError if broken


def test_original_text_survives_around_the_wrapped_target(tmp_path: Path) -> None:
    out = _render(tmp_path, [_ann(_COMBUSTION_PAGE, "unburnt carbon particles")])
    with zipfile.ZipFile(out) as zf:
        root = etree.fromstring(_chapter_bytes(zf, "ch1.xhtml"))
    text = " ".join("".join(root.itertext()).split())
    for fragment in (
        "zone contains",  # before the target
        "unburnt carbon particles",  # the wrapped slice itself
        "heated to incandescence",  # after the target
    ):
        assert fragment in text


def test_warning_note_carries_its_glyph_prefix(tmp_path: Path) -> None:
    out = _render(
        tmp_path,
        [
            _ann(
                _ACIDS_PAGE,
                "pouring acid into water",
                content="ALWAYS. No exceptions.",
                atype=AnnotationType.WARNING,
                confidence=1.0,
            )
        ],
    )
    with zipfile.ZipFile(out) as zf:
        root = etree.fromstring(_chapter_bytes(zf, "ch2.xhtml"))
    notes = [
        el
        for el in root.findall(".//x:span", _XHTML_NS)
        if "hbp-note" in (el.get("class") or "")
    ]
    assert len(notes) == 1
    assert notes[0].text == "⚠ ALWAYS. No exceptions."


def test_annotation_css_reaches_the_written_chapter_exactly_once(tmp_path: Path) -> None:
    # EbookLib regenerates <head> at write time, dropping soup-injected
    # <style> tags. The .hbp-* rules must survive into the OUTPUT file —
    # inline or linked — exactly once per annotated chapter, or every
    # class-based style silently never reaches a reader.
    out = _render(
        tmp_path,
        [
            _ann(_COMBUSTION_PAGE, "unburnt carbon particles"),
            _ann(_COMBUSTION_PAGE, "carbonic acid", content="Carbon dioxide, in truth."),
        ],
    )
    with zipfile.ZipFile(out) as zf:
        sources = _hbp_css_sources(zf, "ch1.xhtml")
    assert len(sources) == 1, (
        f"expected exactly one reachable .hbp-note CSS source, found {len(sources)}"
    )


def test_two_annotations_in_one_chapter_both_render(tmp_path: Path) -> None:
    out = _render(
        tmp_path,
        [
            _ann(_COMBUSTION_PAGE, "unburnt carbon particles"),
            _ann(_COMBUSTION_PAGE, "carbonic acid", content="Carbon dioxide, in truth."),
        ],
    )
    with zipfile.ZipFile(out) as zf:
        root = etree.fromstring(_chapter_bytes(zf, "ch1.xhtml"))
    targets = [
        el
        for el in root.findall(".//x:span", _XHTML_NS)
        if "hbp-target" in (el.get("class") or "")
    ]
    assert len(targets) == 2


def test_unmatched_target_is_skipped_without_markup(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING, logger="halfblood.epub_processor"):
        out = _render(tmp_path, [_ann(_COMBUSTION_PAGE, "phrase that appears nowhere at all")])
    assert any("Could not locate" in r.message for r in caplog.records)
    with zipfile.ZipFile(out) as zf:
        ch1 = _chapter_bytes(zf, "ch1.xhtml")
    assert b"hbp-target" not in ch1 and b"hbp-note" not in ch1


def test_out_of_range_chapter_is_skipped_with_warning(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING, logger="halfblood.epub_processor"):
        out = _render(tmp_path, [_ann(99, "whatever")])
    assert any("spine only" in r.message for r in caplog.records)
    assert out.exists()


def test_output_reloads_with_spine_and_metadata_intact(tmp_path: Path) -> None:
    out = _render(tmp_path, [_ann(_COMBUSTION_PAGE, "unburnt carbon particles")])

    book = epub.read_epub(str(out))
    assert book.title == "Elements of Practical Chemistry"

    pages = EpubProcessor().load(str(out))
    assert [p.page_number for p in pages] == [1, 2, 3, 4]
    assert pages[_COMBUSTION_PAGE - 1].text.startswith("On Combustion")
    assert pages[_ACIDS_PAGE - 1].text.startswith("On Acids")
    assert pages[_DISTILLATION_PAGE - 1].text.startswith("On Distillation")
