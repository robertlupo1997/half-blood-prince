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

from halfblood.documents import (
    CrossNodeMatch,
    iter_inline_runs,
    locate_across_nodes,
    selector_for,
)
from halfblood.documents.matching import normalize
from halfblood.epub_processor import EpubProcessor
from halfblood.models import Annotation, AnnotationType
from halfblood.models.annotations import Annotation as V2Annotation

# P2-T9 fold-in #1: V2 imports for render_plan / render_annotations parity test.
from halfblood.models.annotations import MarkIntent, TargetSelector
from halfblood.models.documents import AnnotationPlan as V2Plan
from halfblood.models.documents import GenerationProvenance, SourceInfo, Unit

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


# ---------------------------------------------------------------------------
# P2-T5 — cross-node range resolution + markup-preserving wrap (§5.8)
#
# The single-node `_locate_text` misses targets split across inline tags
# (<em>/<strong>/<span>) — it can only fall back to a degraded single-word
# fragment. `locate_across_nodes` resolves the full quote across adjacent
# text nodes within one block, using the P2-T3 scorer to reject repeats, and
# `wrap_cross_node_segments` wraps exactly that range without DOM corruption.
# render_annotations is deliberately NOT rewired here (that is P2-T9).
# ---------------------------------------------------------------------------

# One target straddling plain text + <em> + plain text + <strong>.
_ONE_BLOCK_XHTML = (
    '<html xmlns="http://www.w3.org/1999/xhtml"><body>'
    '<p id="a">Begin: the <em>sopophorous</em> bean must be '
    '<strong>crushed</strong>, not cut.</p>'
    '</body></html>'
)
# Same quote in TWO separate <p> blocks -> repeated -> must be rejected as ambiguous.
_CROSS_XHTML = (
    '<html xmlns="http://www.w3.org/1999/xhtml"><body>'
    '<p id="a">Begin: the <em>sopophorous</em> bean must be '
    '<strong>crushed</strong>, not cut.</p>'
    '<p id="b">Later the <em>sopophorous</em> bean must be '
    '<strong>crushed</strong> again.</p>'
    '</body></html>'
)
_CROSS_TARGET = "the sopophorous bean must be crushed"


def _soup(xhtml: str) -> BeautifulSoup:
    return BeautifulSoup(xhtml, "lxml")


def test_single_node_locator_cannot_cover_the_cross_node_quote() -> None:
    # Non-vacuity guard for the cross-node capability: whether the single-node path
    # returns None or (as today) a degraded fragment, it must NEVER cover the full
    # cross-node phrase. Asserted unconditionally so the guard can't silently evaporate.
    soup = _soup(_ONE_BLOCK_XHTML)
    located = EpubProcessor(seed=1)._locate_text(soup.find("p", id="a"), _CROSS_TARGET)
    covers_full_quote = located is not None and (
        normalize(str(located[0])[located[1] : located[2]]) == normalize(_CROSS_TARGET)
    )
    assert not covers_full_quote, "single-node path must not cover the full cross-node quote"


def test_locate_across_nodes_spans_inline_tags() -> None:
    match = locate_across_nodes(_soup(_ONE_BLOCK_XHTML).body, selector_for(_CROSS_TARGET))
    assert isinstance(match, CrossNodeMatch)
    # more than one node touched, in document order
    assert len({id(seg.node) for seg in match.segments}) >= 2
    concat = "".join(str(seg.node)[seg.start : seg.end] for seg in match.segments)
    assert normalize(concat) == normalize(_CROSS_TARGET)


def test_locate_across_nodes_never_crosses_a_block_boundary() -> None:
    # A phrase that would only exist by spanning the two <p> blocks must not match.
    xhtml = (
        '<html xmlns="http://www.w3.org/1999/xhtml"><body>'
        '<p>the sopophorous bean must be</p>'
        '<p>crushed without delay</p>'
        '</body></html>'
    )
    match = locate_across_nodes(_soup(xhtml).body, selector_for(_CROSS_TARGET))
    assert match is None


def test_repeated_cross_node_quote_across_blocks_is_rejected_as_ambiguous() -> None:
    # The quote appears in BOTH <p> blocks -> ambiguous -> no guess.
    match = locate_across_nodes(_soup(_CROSS_XHTML).body, selector_for(_CROSS_TARGET))
    assert match is None


def test_script_style_and_own_markup_are_excluded_from_runs() -> None:
    xhtml = (
        '<html xmlns="http://www.w3.org/1999/xhtml"><body>'
        '<p><span class="hbp-target">the sopophorous</span> bean</p>'
        '<script>the sopophorous bean must be crushed</script>'
        '<style>the sopophorous bean must be crushed</style>'
        '</body></html>'
    )
    runs = iter_inline_runs(_soup(xhtml).body)
    all_text = "".join(str(n) for run in runs for n in run)
    assert "crushed" not in all_text  # lived only in <script>/<style> -> excluded
    assert "sopophorous" not in all_text  # inside hbp-target markup -> excluded
    assert "bean" in all_text  # a plain text node is retained


def test_wrap_cross_node_segments_preserves_markup_and_text() -> None:
    soup = _soup(_ONE_BLOCK_XHTML)
    # Compare against the whole body's ORIGINAL text: the sidenote is *added* content,
    # so the integrity check must exclude hbp-note text (asserting the block's raw
    # get_text() is unchanged would be wrong — it counts the added note — and would
    # force the note out of the block; note placement is finalized in P2-T9).
    before_body_text = normalize(soup.body.get_text())
    match = locate_across_nodes(soup.body, selector_for(_CROSS_TARGET))
    assert match is not None

    EpubProcessor(seed=3).wrap_cross_node_segments(
        soup, match.segments, _ann(1, _CROSS_TARGET)
    )

    block = soup.find("p")
    # inline tags survive
    assert block.find("em") is not None and block.find("strong") is not None
    # exactly one note; the marked slices concatenate to the quote
    notes = soup.find_all("span", class_=lambda c: c and "hbp-note" in c)
    assert len(notes) == 1
    marks = soup.find_all("span", class_=lambda c: c and "hbp-target" in c)
    assert normalize("".join(m.get_text() for m in marks)) == normalize(_CROSS_TARGET)
    # result is valid XHTML
    etree.fromstring(str(soup).encode("utf-8"))
    # original book text preserved once the added note is removed (no dup/loss)
    for note in notes:
        note.extract()
    assert normalize(soup.body.get_text()) == before_body_text


def test_selector_for_builds_an_exact_selector() -> None:
    sel = selector_for("The Sopophorous Bean")
    assert sel.normalized_exact == normalize("The Sopophorous Bean")
    assert sel.normalized_prefix is None and sel.normalized_suffix is None


# ---------------------------------------------------------------------------
# MP2a — wrap_cross_node_segments derives mark-intent class from legacy V1 type
#
# wrap_cross_node_segments is public API; tests call it directly with a legacy
# Annotation (no mark_intent field).  After MP2a the function must derive the
# effective intent from the _MARK_INTENTS migration mapping and attach the
# corresponding hbp-mark-{intent} class to every mark span it emits.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("atype", "expected_intent_class"),
    [
        (AnnotationType.CROSSED_OUT, "hbp-mark-strike"),
        (AnnotationType.INSIGHT, "hbp-mark-circle"),
    ],
    ids=["crossed_out->strike", "insight->circle"],
)
def test_wrap_cross_node_segments_derives_intent_from_legacy_annotation(
    atype: AnnotationType, expected_intent_class: str
) -> None:
    """Legacy Annotation (no mark_intent) must yield the V1-mapped intent class on mark spans."""
    soup = _soup(_ONE_BLOCK_XHTML)
    match = locate_across_nodes(soup.body, selector_for(_CROSS_TARGET))
    assert match is not None

    EpubProcessor(seed=3).wrap_cross_node_segments(
        soup, match.segments, _ann(1, _CROSS_TARGET, atype=atype)
    )

    marks = soup.find_all("span", class_=lambda c: c and "hbp-target" in c)
    assert marks, f"{atype.value} annotation must produce at least one mark span"
    for mark in marks:
        assert expected_intent_class in mark["class"], (
            f"mark span for {atype.value} must carry {expected_intent_class}; got {mark['class']!r}"
        )


# ---------------------------------------------------------------------------
# P2-T9 fold-in #1 — render_plan / render_annotations markup-structure parity
#
# render_annotations routes through the single-node _locate_text fallback path.
# render_plan (added in P2-T9) must route through locate_across_nodes with the
# shared scorer.  For a simple unique target fully inside one text node both
# paths must produce the same hbp-target / hbp-note span structure.
# ---------------------------------------------------------------------------

_ACIDS_TARGET = "turns blue litmus red"  # unique single-node phrase in ch2.xhtml
_ACIDS_ORDINAL = 3  # ch2 == spine page 3 (nav=1, ch1=2, ch2=3)
_ACIDS_CHAPTER = "ch2.xhtml"

_V2_FINGERPRINT = "c" * 64


def _v2_acids_plan(ann_id: str) -> V2Plan:
    return V2Plan(
        id="fold-in-1-plan",
        title="Fold-in 1 Plan",
        persona="Snape",
        source=SourceInfo(
            fingerprint=_V2_FINGERPRINT,
            media_type="application/epub+zip",
            unit_count=1,
        ),
        generation=GenerationProvenance(),
        document_seed=11,
        units=[
            Unit(
                unit_id="unit-acids",
                ordinal=_ACIDS_ORDINAL,
                label="Page 3",
                original_text="",
                source_locator=f"page:{_ACIDS_ORDINAL}",
                annotations=[
                    V2Annotation(
                        id=ann_id,
                        target=TargetSelector(exact=_ACIDS_TARGET),
                        annotation_type=AnnotationType.INSIGHT,
                        content="Snape's note.",
                        confidence=0.9,
                        requested_placement="margin_right",
                        mark_intent=MarkIntent.CIRCLE,
                    )
                ],
            )
        ],
    )


def test_render_plan_and_render_annotations_produce_same_span_count(
    tmp_path: Path,
) -> None:
    """render_plan (locate_across_nodes path) and render_annotations (_locate_text path)
    must produce the same number of hbp-target and hbp-note spans for a simple
    single-node target, proving the two render paths agree on markup structure.

    Fails before P2-T9 because EpubProcessor.render_plan does not yet exist.
    """
    # --- render_annotations (legacy V1 path) ---
    out_v1 = tmp_path / "v1.epub"
    ann_v1 = _ann(page=_ACIDS_ORDINAL, target=_ACIDS_TARGET, content="Note.")
    EpubProcessor(seed=5).render_annotations(str(FIXTURE), [ann_v1], str(out_v1))
    with zipfile.ZipFile(out_v1) as zf:
        v1_bytes = _chapter_bytes(zf, _ACIDS_CHAPTER)

    v1_soup = BeautifulSoup(v1_bytes, "lxml")
    v1_targets = v1_soup.find_all("span", class_=lambda c: c and "hbp-target" in c)
    v1_notes = v1_soup.find_all("span", class_=lambda c: c and "hbp-note" in c)

    # --- render_plan (P2-T9 V2 path) ---
    out_v2 = tmp_path / "v2.epub"
    plan = _v2_acids_plan("acids-ann-1")
    EpubProcessor(seed=5).render_plan(str(FIXTURE), plan, str(out_v2))
    with zipfile.ZipFile(out_v2) as zf:
        v2_bytes = _chapter_bytes(zf, _ACIDS_CHAPTER)

    v2_soup = BeautifulSoup(v2_bytes, "lxml")
    v2_targets = v2_soup.find_all("span", class_=lambda c: c and "hbp-target" in c)
    v2_notes = v2_soup.find_all("span", class_=lambda c: c and "hbp-note" in c)

    # Both paths must produce exactly one target span and one note span.
    assert len(v1_targets) == 1, "render_annotations must produce one hbp-target span"
    assert len(v2_targets) == 1, "render_plan must produce one hbp-target span"
    assert len(v1_notes) == 1, "render_annotations must produce one hbp-note span"
    assert len(v2_notes) == 1, "render_plan must produce one hbp-note span"
    # The wrapped text must be identical regardless of which path placed it.
    assert v1_targets[0].get_text() == v2_targets[0].get_text(), (
        "target span text must be the same from both render paths"
    )
    # MP2a: render_plan (V2 path) must attach the intent-derived mark class.
    # The V2 annotation has mark_intent=CIRCLE (see _v2_acids_plan), so the
    # intent class must be hbp-mark-circle.
    assert "hbp-mark-circle" in v2_targets[0]["class"], (
        "render_plan target span must carry hbp-mark-circle (mark_intent=CIRCLE)"
    )
