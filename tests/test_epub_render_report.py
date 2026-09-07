"""P2-T9 — EpubProcessor.render_plan contract and RenderReport outcome codes.

Verifies that the new ``render_plan`` method on ``EpubProcessor``:

* Routes annotation placement through ``locate_across_nodes`` and the shared
  scorer so cross-node targets, context disambiguation, ambiguity detection,
  and overlap detection all work.
* Returns a ``RenderReport`` with the correct rendered/skipped partition.
* Emits ``DegradationFlag.EPUB_NO_TARGET_GEOMETRY`` because reflowable EPUB
  content has no fixed geometry.
* Preserves XHTML validity, original text, metadata, spine, and TOC across
  the round-trip.
* Injects the annotation stylesheet exactly once per rendered chapter.

No network calls are made anywhere in this file.
"""

from __future__ import annotations

import posixpath
import re
import zipfile
from pathlib import Path

import pytest
from bs4 import BeautifulSoup
from ebooklib import epub
from lxml import etree

from halfblood.epub_processor import EpubProcessor
from halfblood.models import AnnotationType
from halfblood.models.annotations import Annotation, MarkIntent, TargetSelector
from halfblood.models.documents import AnnotationPlan, GenerationProvenance, SourceInfo, Unit
from halfblood.models.rendering import DegradationFlag, RenderReport, SkipReason

# Silence XMLParsedAsHTMLWarning: BeautifulSoup emits this when parsing EPUB
# XHTML chapters with the lxml HTML parser, which is intentional in the
# epub_processor (it handles malformed XHTML). Suppressing keeps the test
# output clean without masking real regressions.
pytestmark = pytest.mark.filterwarnings("ignore::bs4.XMLParsedAsHTMLWarning")

_XHTML_NS = {"x": "http://www.w3.org/1999/xhtml"}
_FINGERPRINT = "a" * 64  # placeholder matching sha256 hex format


# ---------------------------------------------------------------------------
# Fixture EPUB content
# ---------------------------------------------------------------------------

# Chapter 1: unique target, repeated phrase (same block), cross-node target,
# and two non-overlapping annotations in one text node.
_CH1_CONTENT = (
    "<h1>Chapter One</h1>"
    "<p>The bezoar is a stone taken from the stomach of a goat.</p>"
    "<p>Stir clockwise three times. Rest one minute."
    " Stir clockwise three times to finish.</p>"
    "<p>The <em>asphodel</em> root dissolves to"
    " <strong>fine powder</strong> on heating.</p>"
    "<p>First heat the flask, then add powdered brimstone while stirring gently.</p>"
)

# Chapter 2: overlapping pair, cross-block target (spans two <p> tags),
# and a target that does not exist.
_CH2_CONTENT = (
    "<h1>Chapter Two</h1>"
    "<p>The ancient potion requires careful stirring at dawn.</p>"
    "<p>Never mix acids</p>"
    "<p>with volatile reagents in glass.</p>"
    "<p>Normal text here without annotations.</p>"
)


# ---------------------------------------------------------------------------
# Annotation IDs used across tests
# ---------------------------------------------------------------------------

_ANN_UNIQUE = "ann-unique"
_ANN_CTX_SECOND = "ann-ctx-second"
_ANN_AMBIGUOUS = "ann-ambiguous"
_ANN_CROSS_NODE = "ann-cross-node"
_ANN_NONOVERLAP_1 = "ann-nonoverlap-1"
_ANN_NONOVERLAP_2 = "ann-nonoverlap-2"
_ANN_OVERLAP_A = "ann-overlap-a"
_ANN_OVERLAP_B = "ann-overlap-b"
_ANN_CROSS_BLOCK = "ann-cross-block"
_ANN_MISSING = "ann-missing"
_ANN_OOR = "ann-oor"


# ---------------------------------------------------------------------------
# Helpers for building V2 Annotations and Plans
# ---------------------------------------------------------------------------


def _ann(
    ann_id: str,
    exact: str,
    *,
    prefix: str | None = None,
    suffix: str | None = None,
    ann_type: AnnotationType = AnnotationType.INSIGHT,
    mark_intent: MarkIntent = MarkIntent.CIRCLE,
) -> Annotation:
    return Annotation(
        id=ann_id,
        target=TargetSelector(exact=exact, prefix=prefix, suffix=suffix),
        annotation_type=ann_type,
        content="Snape's commentary.",
        confidence=0.9,
        requested_placement="margin_right",
        mark_intent=mark_intent,
    )


def _unit(ordinal: int, anns: list[Annotation]) -> Unit:
    return Unit(
        unit_id=f"unit-{ordinal}",
        ordinal=ordinal,
        label=f"Page {ordinal}",
        original_text="",
        source_locator=f"page:{ordinal}",
        annotations=anns,
    )


def _plan(units: list[Unit]) -> AnnotationPlan:
    return AnnotationPlan(
        id="test-plan-id-00000001",
        title="Test Potions Text",
        persona="Snape",
        source=SourceInfo(
            fingerprint=_FINGERPRINT,
            media_type="application/epub+zip",
            unit_count=len(units),
        ),
        generation=GenerationProvenance(),
        document_seed=7,
        units=units,
    )


# ---------------------------------------------------------------------------
# Spine ordinals
#
# EbookLib writes the nav document with linear="yes" (a known library bug),
# so _iter_spine_documents counts it as page 1.  The real chapters follow.
# ---------------------------------------------------------------------------

_CH1_ORDINAL = 2
_CH2_ORDINAL = 3
_OOR_ORDINAL = 999


# ---------------------------------------------------------------------------
# EPUB input fixture (module-scoped — built once, read by all tests)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def epub_src(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Two-chapter test EPUB saved to a module-scoped temp directory."""
    tmp = tmp_path_factory.mktemp("epub_rr_src")
    book = epub.EpubBook()
    book.set_identifier("hbp-p2t9-render-report-test")
    book.set_title("Render Report Test Book")
    book.set_language("en")

    ch1 = epub.EpubHtml(uid="ch1", file_name="ch1.xhtml", lang="en")
    ch1.content = _CH1_CONTENT
    ch2 = epub.EpubHtml(uid="ch2", file_name="ch2.xhtml", lang="en")
    ch2.content = _CH2_CONTENT

    for item in (ch1, ch2, epub.EpubNcx(), epub.EpubNav()):
        book.add_item(item)
    book.toc = [ch1, ch2]
    book.spine = ["nav", ch1, ch2]

    path = tmp / "src.epub"
    epub.write_epub(str(path), book)
    return path


# ---------------------------------------------------------------------------
# Shared helper: call render_plan and return (report, output_path)
# ---------------------------------------------------------------------------


def _render(epub_src: Path, plan: AnnotationPlan, tmp_path: Path) -> tuple[RenderReport, Path]:
    out = tmp_path / "annotated.epub"
    processor = EpubProcessor(seed=3)
    report = processor.render_plan(str(epub_src), plan, str(out))
    return report, out


def _chapter_bytes(zf: zipfile.ZipFile, basename: str) -> bytes:
    name = next(n for n in zf.namelist() if n.endswith(basename))
    return zf.read(name)


def _hbp_css_count(zf: zipfile.ZipFile, basename: str) -> int:
    """Count distinct stylesheet sources that mention ``.hbp-note`` rules."""
    chapter_name = next(n for n in zf.namelist() if n.endswith(basename))
    root = etree.fromstring(zf.read(chapter_name))
    count = 0
    for style in root.findall(".//x:style", _XHTML_NS):
        if ".hbp-note" in (style.text or ""):
            count += 1
    base = posixpath.dirname(chapter_name)
    for link in root.findall(".//x:link", _XHTML_NS):
        if (link.get("rel") or "").lower() != "stylesheet":
            continue
        href = link.get("href") or ""
        target = posixpath.normpath(posixpath.join(base, href))
        if target in zf.namelist():
            css = zf.read(target).decode("utf-8", errors="replace")
            if ".hbp-note" in css:
                count += 1
    return count


# ---------------------------------------------------------------------------
# Basic contract: render_plan returns RenderReport
# ---------------------------------------------------------------------------


def test_render_plan_returns_render_report(epub_src: Path, tmp_path: Path) -> None:
    plan = _plan([_unit(_CH1_ORDINAL, [_ann(_ANN_UNIQUE, "bezoar is a stone taken from")])])
    report, _ = _render(epub_src, plan, tmp_path)
    assert isinstance(report, RenderReport)


# ---------------------------------------------------------------------------
# Rendered dispositions
# ---------------------------------------------------------------------------


def test_unique_target_is_rendered(epub_src: Path, tmp_path: Path) -> None:
    plan = _plan([_unit(_CH1_ORDINAL, [_ann(_ANN_UNIQUE, "bezoar is a stone taken from")])])
    report, _ = _render(epub_src, plan, tmp_path)
    assert _ANN_UNIQUE in report.rendered
    assert report.rendered_count == 1
    assert report.skipped_count == 0


def test_context_selects_second_occurrence(epub_src: Path, tmp_path: Path) -> None:
    # "Stir clockwise three times" appears twice in CH1 within the same <p>.
    # A prefix drawn from the text between the two occurrences picks the second.
    plan = _plan(
        [
            _unit(
                _CH1_ORDINAL,
                [
                    _ann(
                        _ANN_CTX_SECOND,
                        "Stir clockwise three times",
                        prefix="Rest one minute. ",
                    )
                ],
            )
        ]
    )
    report, out = _render(epub_src, plan, tmp_path)
    assert _ANN_CTX_SECOND in report.rendered, "context-selected second occurrence must render"
    with zipfile.ZipFile(out) as zf:
        ch1 = _chapter_bytes(zf, "ch1.xhtml").decode("utf-8", errors="replace")
    # Only ONE hbp-target span for the phrase — the second occurrence.
    assert ch1.count("Stir clockwise three times") >= 2  # original text intact
    # class="hbp-target hbp-target-insight" contains "hbp-target" twice as a substring;
    # count the opening-tag pattern to get exactly the number of target spans.
    target_spans = ch1.count('class="hbp-target ')
    assert target_spans == 1, "exactly one span wrapping the second occurrence"


def test_cross_node_target_is_rendered(epub_src: Path, tmp_path: Path) -> None:
    # "asphodel root dissolves to fine powder on heating" spans <em>/<strong>.
    plan = _plan(
        [
            _unit(
                _CH1_ORDINAL,
                [_ann(_ANN_CROSS_NODE, "asphodel root dissolves to fine powder on heating")],
            )
        ]
    )
    report, out = _render(epub_src, plan, tmp_path)
    assert _ANN_CROSS_NODE in report.rendered
    with zipfile.ZipFile(out) as zf:
        ch1_bytes = _chapter_bytes(zf, "ch1.xhtml")
    assert b"hbp-target" in ch1_bytes


def test_two_nonoverlapping_in_same_node_both_render(epub_src: Path, tmp_path: Path) -> None:
    # Two targets within the same <p> text node that do not overlap — both
    # should render.
    plan = _plan(
        [
            _unit(
                _CH1_ORDINAL,
                [
                    _ann(_ANN_NONOVERLAP_1, "heat the flask"),
                    _ann(_ANN_NONOVERLAP_2, "powdered brimstone while stirring gently"),
                ],
            )
        ]
    )
    report, _ = _render(epub_src, plan, tmp_path)
    assert _ANN_NONOVERLAP_1 in report.rendered
    assert _ANN_NONOVERLAP_2 in report.rendered
    assert report.rendered_count == 2
    assert report.skipped_count == 0


# ---------------------------------------------------------------------------
# Skipped dispositions
# ---------------------------------------------------------------------------


def test_repeated_without_context_is_ambiguous(epub_src: Path, tmp_path: Path) -> None:
    # No prefix/suffix — two occurrences of same phrase in one block → ambiguous.
    plan = _plan(
        [_unit(_CH1_ORDINAL, [_ann(_ANN_AMBIGUOUS, "Stir clockwise three times")])]
    )
    report, _ = _render(epub_src, plan, tmp_path)
    assert report.skipped_count == 1
    (skipped,) = report.skipped
    assert skipped.annotation_id == _ANN_AMBIGUOUS
    assert skipped.reason == SkipReason.AMBIGUOUS_TARGET


def test_overlapping_pair_first_renders_second_skipped(epub_src: Path, tmp_path: Path) -> None:
    # Both targets are unique individually but share an overlapping char range.
    # The first resolves and renders; the second is detected as OVERLAPPING_TARGET.
    plan = _plan(
        [
            _unit(
                _CH2_ORDINAL,
                [
                    _ann(_ANN_OVERLAP_A, "ancient potion requires careful"),
                    _ann(_ANN_OVERLAP_B, "potion requires careful stirring"),
                ],
            )
        ]
    )
    report, _ = _render(epub_src, plan, tmp_path)
    assert _ANN_OVERLAP_A in report.rendered
    assert any(s.annotation_id == _ANN_OVERLAP_B for s in report.skipped)
    overlap_skip = next(s for s in report.skipped if s.annotation_id == _ANN_OVERLAP_B)
    assert overlap_skip.reason == SkipReason.OVERLAPPING_TARGET


def test_cross_block_target_is_skipped(epub_src: Path, tmp_path: Path) -> None:
    # "mix acids" is in one <p> and "with volatile reagents" in the next; no
    # single inline run spans the block boundary → MISSING_TARGET.
    plan = _plan(
        [_unit(_CH2_ORDINAL, [_ann(_ANN_CROSS_BLOCK, "mix acids with volatile reagents")])]
    )
    report, _ = _render(epub_src, plan, tmp_path)
    assert report.skipped_count == 1
    (skipped,) = report.skipped
    assert skipped.annotation_id == _ANN_CROSS_BLOCK
    assert skipped.reason == SkipReason.MISSING_TARGET


def test_missing_target_is_skipped(epub_src: Path, tmp_path: Path) -> None:
    plan = _plan(
        [_unit(_CH2_ORDINAL, [_ann(_ANN_MISSING, "a phrase that simply does not exist")])]
    )
    report, _ = _render(epub_src, plan, tmp_path)
    assert report.skipped_count == 1
    (skipped,) = report.skipped
    assert skipped.annotation_id == _ANN_MISSING
    assert skipped.reason == SkipReason.MISSING_TARGET


def test_out_of_range_page_is_skipped(epub_src: Path, tmp_path: Path) -> None:
    plan = _plan([_unit(_OOR_ORDINAL, [_ann(_ANN_OOR, "anything at all")])])
    report, _ = _render(epub_src, plan, tmp_path)
    assert report.skipped_count == 1
    (skipped,) = report.skipped
    assert skipped.annotation_id == _ANN_OOR
    assert skipped.reason == SkipReason.OUT_OF_RANGE_PAGE


# ---------------------------------------------------------------------------
# Partition completeness
# ---------------------------------------------------------------------------


def test_all_annotation_ids_accounted_for(epub_src: Path, tmp_path: Path) -> None:
    """Every annotation ID in the plan appears in exactly one of rendered/skipped."""
    all_anns = [
        _ann(_ANN_UNIQUE, "bezoar is a stone taken from"),
        _ann(_ANN_CTX_SECOND, "Stir clockwise three times", prefix="Rest one minute. "),
        _ann(_ANN_AMBIGUOUS, "Stir clockwise three times"),
        _ann(_ANN_CROSS_NODE, "asphodel root dissolves to fine powder on heating"),
        _ann(_ANN_NONOVERLAP_1, "heat the flask"),
        _ann(_ANN_NONOVERLAP_2, "powdered brimstone while stirring gently"),
    ]
    ch2_anns = [
        _ann(_ANN_OVERLAP_A, "ancient potion requires careful"),
        _ann(_ANN_OVERLAP_B, "potion requires careful stirring"),
        _ann(_ANN_CROSS_BLOCK, "mix acids with volatile reagents"),
        _ann(_ANN_MISSING, "a phrase that simply does not exist"),
    ]
    oor_anns = [_ann(_ANN_OOR, "anything at all")]

    plan = _plan(
        [
            _unit(_CH1_ORDINAL, all_anns),
            _unit(_CH2_ORDINAL, ch2_anns),
            _unit(_OOR_ORDINAL, oor_anns),
        ]
    )
    report, _ = _render(epub_src, plan, tmp_path)
    expected_ids = {a.id for a in all_anns + ch2_anns + oor_anns}
    reported_ids = set(report.rendered) | {s.annotation_id for s in report.skipped}
    assert reported_ids == expected_ids, "every annotation ID must appear in the report"
    assert report.attempted_count == len(expected_ids)


# ---------------------------------------------------------------------------
# Degradation flag
# ---------------------------------------------------------------------------


def test_epub_no_target_geometry_flag_set(epub_src: Path, tmp_path: Path) -> None:
    """Reflowable EPUBs cannot carry fixed geometry: flag must be set."""
    plan = _plan([_unit(_CH1_ORDINAL, [_ann(_ANN_UNIQUE, "bezoar is a stone taken from")])])
    report, _ = _render(epub_src, plan, tmp_path)
    assert DegradationFlag.EPUB_NO_TARGET_GEOMETRY in report.degradation_flags


# ---------------------------------------------------------------------------
# Output XHTML and text integrity
# ---------------------------------------------------------------------------


def test_xhtml_is_parseable_after_render_plan(epub_src: Path, tmp_path: Path) -> None:
    """Modified chapters must remain valid-enough XHTML for lxml to parse."""
    plan = _plan(
        [
            _unit(_CH1_ORDINAL, [_ann(_ANN_CROSS_NODE, "asphodel root dissolves to fine powder on heating")]),
            _unit(_CH2_ORDINAL, [_ann(_ANN_OVERLAP_A, "ancient potion requires careful")]),
        ]
    )
    _, out = _render(epub_src, plan, tmp_path)
    with zipfile.ZipFile(out) as zf:
        for chapter in ("ch1.xhtml", "ch2.xhtml"):
            data = _chapter_bytes(zf, chapter)
            etree.fromstring(data)  # raises on malformed XML


def test_original_text_preserved_in_rendered_chapters(epub_src: Path, tmp_path: Path) -> None:
    """The full chapter text must survive annotation wrapping unchanged."""
    plan = _plan(
        [_unit(_CH1_ORDINAL, [_ann(_ANN_UNIQUE, "bezoar is a stone taken from")])]
    )
    _, out = _render(epub_src, plan, tmp_path)
    with zipfile.ZipFile(out) as zf:
        ch1 = _chapter_bytes(zf, "ch1.xhtml").decode("utf-8", errors="replace")
    # The target phrase is wrapped in an hbp-target span, splitting the sentence
    # in raw XHTML — check both the wrapped segment and the trailing plain text.
    assert "bezoar is a stone taken from" in ch1  # inside hbp-target span
    assert "the stomach of a goat" in ch1  # plain text after the span
    assert "Stir clockwise three times" in ch1


def test_only_modified_chapters_contain_hbp_markup(epub_src: Path, tmp_path: Path) -> None:
    """Chapters with no annotations must be written without any hbp-* markup."""
    plan = _plan([_unit(_CH1_ORDINAL, [_ann(_ANN_UNIQUE, "bezoar is a stone taken from")])])
    _, out = _render(epub_src, plan, tmp_path)
    with zipfile.ZipFile(out) as zf:
        ch1 = _chapter_bytes(zf, "ch1.xhtml")
        ch2 = _chapter_bytes(zf, "ch2.xhtml")
    assert b"hbp-target" in ch1
    assert b"hbp-target" not in ch2


def test_stylesheet_injected_once_in_rendered_chapter(epub_src: Path, tmp_path: Path) -> None:
    """Rendering several annotations into the same chapter must inject CSS only once."""
    plan = _plan(
        [
            _unit(
                _CH1_ORDINAL,
                [
                    _ann(_ANN_UNIQUE, "bezoar is a stone taken from"),
                    _ann(_ANN_NONOVERLAP_1, "heat the flask"),
                ],
            )
        ]
    )
    _, out = _render(epub_src, plan, tmp_path)
    with zipfile.ZipFile(out) as zf:
        count = _hbp_css_count(zf, "ch1.xhtml")
    assert count == 1, f"expected exactly one CSS source, found {count}"


# ---------------------------------------------------------------------------
# EPUB container metadata / spine / TOC survive the round-trip
# ---------------------------------------------------------------------------


def test_metadata_and_spine_survive(epub_src: Path, tmp_path: Path) -> None:
    plan = _plan([_unit(_CH1_ORDINAL, [_ann(_ANN_UNIQUE, "bezoar is a stone taken from")])])
    _, out = _render(epub_src, plan, tmp_path)
    pages = EpubProcessor(seed=0).load(str(out))
    # Nav (page 1) + ch1 (page 2) + ch2 (page 3) — same as input.
    assert len(pages) == 3
    # Ch1 should still start with chapter heading or chapter content.
    ch1_text = pages[_CH1_ORDINAL - 1].text
    assert "bezoar" in ch1_text.lower()
    # Unmodified ch2 intact.
    ch2_text = pages[_CH2_ORDINAL - 1].text
    assert "ancient potion" in ch2_text.lower()


# ---------------------------------------------------------------------------
# MP2a — mark-intent parity
#
# render_plan must derive visual mark classes from ann.mark_intent, not from
# annotation_type geometry rules.  MarkIntent.NONE means note-only: no
# hbp-target span is emitted but the annotation is still counted as rendered
# and the stylesheet is still linked to its chapter.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("mark_intent", "intent_slug"),
    [
        (MarkIntent.UNDERLINE, "underline"),
        (MarkIntent.CIRCLE, "circle"),
        (MarkIntent.STRIKE, "strike"),
        (MarkIntent.HIGHLIGHT, "highlight"),
        (MarkIntent.CARET, "caret"),
    ],
    ids=["underline", "circle", "strike", "highlight", "caret"],
)
def test_target_span_class_list_contains_mark_intent(
    epub_src: Path,
    tmp_path: Path,
    mark_intent: MarkIntent,
    intent_slug: str,
) -> None:
    """render_plan target span must carry exactly hbp-target, hbp-target-{type}, hbp-mark-{intent}."""
    plan = _plan(
        [
            _unit(
                _CH1_ORDINAL,
                [_ann(_ANN_UNIQUE, "bezoar is a stone taken from", mark_intent=mark_intent)],
            )
        ]
    )
    _, out = _render(epub_src, plan, tmp_path)
    with zipfile.ZipFile(out) as zf:
        ch1_bytes = _chapter_bytes(zf, "ch1.xhtml")
    soup = BeautifulSoup(ch1_bytes, "lxml")
    targets = soup.find_all("span", class_=lambda c: c and "hbp-target" in c)
    assert len(targets) == 1, "exactly one target span expected for a unique single-node target"
    cls = set(targets[0]["class"])
    expected = {"hbp-target", "hbp-target-insight", f"hbp-mark-{intent_slug}"}
    assert cls == expected, (
        f"target span class set must be exactly {expected!r}; got {cls!r}"
    )


def test_mark_intent_and_annotation_type_are_orthogonal(
    epub_src: Path, tmp_path: Path
) -> None:
    """WARNING type + CIRCLE intent → hbp-target-warning AND hbp-mark-circle on target; hbp-note-warning on note."""
    plan = _plan(
        [
            _unit(
                _CH2_ORDINAL,
                [
                    _ann(
                        "ann-ortho",
                        "ancient potion requires careful",
                        ann_type=AnnotationType.WARNING,
                        mark_intent=MarkIntent.CIRCLE,
                    )
                ],
            )
        ]
    )
    _, out = _render(epub_src, plan, tmp_path)
    with zipfile.ZipFile(out) as zf:
        ch2_bytes = _chapter_bytes(zf, "ch2.xhtml")
    soup = BeautifulSoup(ch2_bytes, "lxml")
    targets = soup.find_all("span", class_=lambda c: c and "hbp-target" in c)
    # NL1: notes are now <aside> elements inside cluster <div>s — search any tag.
    notes = soup.find_all(True, class_="hbp-note")
    assert len(targets) == 1
    assert len(notes) == 1
    target_cls = set(targets[0]["class"])
    assert "hbp-target-warning" in target_cls, "type class must reflect annotation_type"
    assert "hbp-mark-circle" in target_cls, "intent class must reflect mark_intent"
    note_cls = set(notes[0]["class"])
    assert "hbp-note-warning" in note_cls, "note class must reflect annotation_type"


def test_none_intent_creates_note_without_target_span(
    epub_src: Path, tmp_path: Path
) -> None:
    """MarkIntent.NONE: no hbp-target span emitted; exactly one hbp-note; rendered, not skipped; stylesheet linked."""
    ann_id = "ann-none-intent"
    plan = _plan(
        [
            _unit(
                _CH1_ORDINAL,
                [
                    _ann(
                        ann_id,
                        "bezoar is a stone taken from",
                        mark_intent=MarkIntent.NONE,
                    )
                ],
            )
        ]
    )
    report, out = _render(epub_src, plan, tmp_path)
    with zipfile.ZipFile(out) as zf:
        ch1_bytes = _chapter_bytes(zf, "ch1.xhtml")
        css_count = _hbp_css_count(zf, "ch1.xhtml")
    soup = BeautifulSoup(ch1_bytes, "lxml")
    targets = soup.find_all("span", class_=lambda c: c and "hbp-target" in c)
    # NL1: notes are now <aside> elements inside cluster <div>s — search any tag.
    notes = soup.find_all(True, class_="hbp-note")
    # No target span — NONE intent leaves the matched text node untouched.
    assert len(targets) == 0, "NONE intent must not emit any hbp-target span"
    # Exactly one note element still inserted.
    assert len(notes) == 1, "NONE intent must still insert exactly one hbp-note element"
    # Target text is still present in the chapter (text node not split or removed).
    assert b"bezoar is a stone taken from" in ch1_bytes, (
        "target text must remain intact in the chapter when mark_intent is NONE"
    )
    # Annotation is rendered, not skipped.
    assert report.rendered == (ann_id,)
    assert report.skipped == ()
    assert report.marks_only == ()
    # Stylesheet is linked even though no mark was painted.
    assert css_count == 1, "NONE-intent annotation must still trigger stylesheet linking"


def test_cross_node_fragments_all_carry_intent_class(
    epub_src: Path, tmp_path: Path
) -> None:
    """Each hbp-target fragment from a cross-node match must carry hbp-mark-{intent}."""
    # "asphodel root dissolves to fine powder on heating" spans <em> and <strong>.
    plan = _plan(
        [
            _unit(
                _CH1_ORDINAL,
                [
                    _ann(
                        "ann-cross-intent",
                        "asphodel root dissolves to fine powder on heating",
                        mark_intent=MarkIntent.STRIKE,
                    )
                ],
            )
        ]
    )
    _, out = _render(epub_src, plan, tmp_path)
    with zipfile.ZipFile(out) as zf:
        ch1_bytes = _chapter_bytes(zf, "ch1.xhtml")
    soup = BeautifulSoup(ch1_bytes, "lxml")
    targets = soup.find_all("span", class_=lambda c: c and "hbp-target" in c)
    # Cross-node target produces multiple fragment spans.
    assert len(targets) >= 2, (
        "cross-node target must produce multiple hbp-target fragments"
    )
    for frag in targets:
        cls = set(frag["class"])
        assert "hbp-mark-strike" in cls, (
            f"every hbp-target fragment must carry hbp-mark-strike; got {cls!r}"
        )


def test_overlapping_skipped_annotation_is_not_in_marks_only(
    epub_src: Path, tmp_path: Path
) -> None:
    """Regression guard: the EPUB render path never populates marks_only (N/A per contract §5)."""
    plan = _plan(
        [
            _unit(
                _CH2_ORDINAL,
                [
                    _ann(_ANN_OVERLAP_A, "ancient potion requires careful"),
                    _ann(_ANN_OVERLAP_B, "potion requires careful stirring"),
                ],
            )
        ]
    )
    report, _ = _render(epub_src, plan, tmp_path)
    assert _ANN_OVERLAP_B not in report.marks_only
    assert report.marks_only == ()


def test_annotation_stylesheet_contains_intent_css_rules(
    epub_src: Path, tmp_path: Path
) -> None:
    """After render_plan the injected stylesheet must define a rule for each visual intent."""
    plan = _plan([_unit(_CH1_ORDINAL, [_ann(_ANN_UNIQUE, "bezoar is a stone taken from")])])
    _, out = _render(epub_src, plan, tmp_path)
    with zipfile.ZipFile(out) as zf:
        css_files = [n for n in zf.namelist() if n.endswith("hbp-annotations.css")]
        assert css_files, "annotation stylesheet must be present in the archive"
        css_text = zf.read(css_files[0]).decode("utf-8")
    # CARET is intentionally excluded here: NL4 removes .hbp-mark-caret::after
    # and replaces it with a real DOM glyph span styled by .hbp-caret-glyph.
    # The class hbp-mark-caret is still applied to the mark span itself (see
    # test_target_span_class_list_contains_mark_intent for that assertion), but
    # no longer needs a CSS rule of its own.
    for intent_slug in ("underline", "circle", "strike", "highlight"):
        assert f".hbp-mark-{intent_slug}" in css_text, (
            f"stylesheet must contain a .hbp-mark-{intent_slug} rule"
        )
    assert ".hbp-caret-glyph" in css_text, (
        "stylesheet must contain a .hbp-caret-glyph rule (NL4 replaces ::after)"
    )


# ---------------------------------------------------------------------------
# EPUB-NL1 — semantic note DOM + stable ordering
#
# These tests are authored by the controller and MUST FAIL on HEAD before
# Codex implements NL1.  They pin the exact contract from
# nl1-semantic-note-dom-brief.md:
#
#   • Same-block ordering: two annotations on one block → one cluster, plan order.
#   • EPUB 3 note shape: <aside> with id, class, epub:type="footnote", back-link.
#   • EPUB 2 fallback: <div> note, no epub:type, bidirectional links still present.
#   • NONE intent noteref: noteref at target end, target text preserved, note in cluster.
#   • Bidirectional invariant: all noteref hrefs and back-link hrefs resolve, ids unique.
#   • Report/text invariants: rendered/skipped semantics unchanged; body text subsequence.
# ---------------------------------------------------------------------------


def test_nl1_same_block_notes_form_one_cluster_in_plan_order(
    epub_src: Path, tmp_path: Path
) -> None:
    """NL1 live defect: two annotations on the same block must share ONE cluster,
    and notes must appear in plan (processing) order.

    The old insert_after approach called insert_after twice, each time inserting
    directly after the <p>, reversing the order (second note ended up first).
    After NL1, notes are appended into a shared cluster in plan order.
    """
    ann1_id = "ann-block-first"
    ann2_id = "ann-block-second"
    plan = _plan(
        [
            _unit(
                _CH2_ORDINAL,
                [
                    _ann(ann1_id, "ancient potion requires careful"),
                    _ann(ann2_id, "stirring at dawn"),
                ],
            )
        ]
    )
    _, out = _render(epub_src, plan, tmp_path)
    with zipfile.ZipFile(out) as zf:
        ch2_bytes = _chapter_bytes(zf, "ch2.xhtml")
    soup = BeautifulSoup(ch2_bytes, "lxml")

    clusters = soup.find_all(True, class_="hbp-note-cluster")
    assert len(clusters) == 1, (
        "two annotations on the same block must share exactly one cluster; "
        f"found {len(clusters)}"
    )
    cluster = clusters[0]
    notes = cluster.find_all(True, class_="hbp-note")
    assert len(notes) == 2, (
        f"cluster must contain both notes; found {len(notes)}"
    )
    # Plan order: ann1 before ann2
    note_ids = [n.get("id") for n in notes]
    assert note_ids == [f"hbp-note-{ann1_id}", f"hbp-note-{ann2_id}"], (
        f"notes must appear in plan order inside the cluster; got {note_ids!r}"
    )
    # Per-chapter noteref counter: ann1 gets '1', ann2 gets '2'
    ref1 = soup.find(id=f"hbp-ref-{ann1_id}")
    ref2 = soup.find(id=f"hbp-ref-{ann2_id}")
    assert ref1 is not None, f"noteref for {ann1_id!r} not found"
    assert ref2 is not None, f"noteref for {ann2_id!r} not found"
    assert ref1.get_text(strip=True) == "1", (
        f"first noteref must display '1'; got {ref1.get_text(strip=True)!r}"
    )
    assert ref2.get_text(strip=True) == "2", (
        f"second noteref must display '2'; got {ref2.get_text(strip=True)!r}"
    )


def test_nl1_epub3_note_is_aside_with_id_and_epub_type(
    epub_src: Path, tmp_path: Path
) -> None:
    """NL1 EPUB 3: note must be rendered as <aside> carrying id, hbp-note class,
    and epub:type='footnote'; noteref must link to it; note back-link must link
    back to the noteref id."""
    ann_id = "ann-epub3-shape"
    plan = _plan([_unit(_CH1_ORDINAL, [_ann(ann_id, "bezoar is a stone taken from")])])
    _, out = _render(epub_src, plan, tmp_path)
    with zipfile.ZipFile(out) as zf:
        ch1_bytes = _chapter_bytes(zf, "ch1.xhtml")
    soup = BeautifulSoup(ch1_bytes, "lxml")

    # Note must be <aside> with correct id and class
    note = soup.find("aside", id=f"hbp-note-{ann_id}")
    assert note is not None, "EPUB 3 note must be rendered as <aside>"
    assert "hbp-note" in (note.get("class") or []), (
        "EPUB 3 <aside> must carry hbp-note class"
    )
    # epub:type="footnote" must appear in the raw chapter bytes (namespace attr)
    assert b'epub:type="footnote"' in ch1_bytes, (
        'EPUB 3 <aside> must carry epub:type="footnote"'
    )
    # Noteref (the inline counter link) must exist and point to the note
    noteref = soup.find(id=f"hbp-ref-{ann_id}")
    assert noteref is not None, f"noteref #hbp-ref-{ann_id} not found"
    assert noteref.get("href") == f"#hbp-note-{ann_id}", (
        "noteref href must point to the note id"
    )
    # Back-link inside the note must point back to the noteref
    backlink = note.find("a", class_="hbp-note-backlink")
    assert backlink is not None, "EPUB 3 note must contain a back-link <a>"
    assert backlink.get("href") == f"#hbp-ref-{ann_id}", (
        "back-link href must point to the noteref id"
    )


def test_nl1_epub2_note_is_div_without_epub_type(
    epub_src: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """NL1 EPUB 2: when book.version does not start with '3', notes must be
    rendered as <div> without epub:type or epub namespace — but back-link and
    noteref bidirectional links must still be present."""
    # Intercept epub.read_epub to force the in-memory book to appear as EPUB 2.0.
    # EpubProcessor reads book.version via this call; setting it on the returned
    # object is sufficient since we never round-trip through write_epub for this check.
    _real_read_epub = epub.read_epub

    def _epub2_read(path: str, *args: object, **kwargs: object) -> object:
        book = _real_read_epub(path, *args, **kwargs)
        book.version = "2.0"
        return book

    monkeypatch.setattr(epub, "read_epub", _epub2_read)

    ann_id = "ann-epub2-div"
    plan = _plan([_unit(_CH1_ORDINAL, [_ann(ann_id, "bezoar is a stone taken from")])])
    _, out = _render(epub_src, plan, tmp_path)
    with zipfile.ZipFile(out) as zf:
        ch1_bytes = _chapter_bytes(zf, "ch1.xhtml")
    soup = BeautifulSoup(ch1_bytes, "lxml")

    # Note must be <div>, not <aside>
    note = soup.find("div", id=f"hbp-note-{ann_id}")
    assert note is not None, "EPUB 2 note must be rendered as <div>"
    assert soup.find("aside", id=f"hbp-note-{ann_id}") is None, (
        "EPUB 2 must not use <aside> for notes"
    )
    assert "hbp-note" in (note.get("class") or []), (
        "EPUB 2 <div> note must carry hbp-note class"
    )
    # No epub:type in the chapter bytes (neither on the note nor the noteref)
    assert b"epub:type" not in ch1_bytes, (
        "EPUB 2 output must not contain any epub:type attribute"
    )
    # Noteref still present (links still bidirectional)
    noteref = soup.find(id=f"hbp-ref-{ann_id}")
    assert noteref is not None, "EPUB 2 must still include a noteref"
    assert noteref.get("href") == f"#hbp-note-{ann_id}", (
        "EPUB 2 noteref href must point to the note id"
    )
    # Back-link inside the div note must point back to the noteref
    backlink = note.find("a", class_="hbp-note-backlink")
    assert backlink is not None, "EPUB 2 note must still contain a back-link <a>"
    assert backlink.get("href") == f"#hbp-ref-{ann_id}", (
        "EPUB 2 back-link href must point to the noteref id"
    )


def test_nl1_none_intent_has_noteref_at_target_end_and_note_in_cluster(
    epub_src: Path, tmp_path: Path
) -> None:
    """NL1 NONE intent: no hbp-target mark span; noteref inserted at the end of
    the target text (after the last char, before the rest of the paragraph);
    original target text preserved character-for-character; note still in cluster."""
    ann_id = "ann-none-noteref"
    plan = _plan(
        [
            _unit(
                _CH1_ORDINAL,
                [
                    _ann(
                        ann_id,
                        "bezoar is a stone taken from",
                        mark_intent=MarkIntent.NONE,
                    )
                ],
            )
        ]
    )
    _, out = _render(epub_src, plan, tmp_path)
    with zipfile.ZipFile(out) as zf:
        ch1_bytes = _chapter_bytes(zf, "ch1.xhtml")
    soup = BeautifulSoup(ch1_bytes, "lxml")

    # No mark span (NONE leaves target text unwrapped)
    targets = soup.find_all("span", class_=lambda c: c and "hbp-target" in c)
    assert len(targets) == 0, "NONE intent must not wrap target in hbp-target span"

    # Target text preserved verbatim in the chapter bytes
    assert b"bezoar is a stone taken from" in ch1_bytes, (
        "target text must remain in the chapter even with NONE intent"
    )

    # Noteref must be present and point to the note
    noteref = soup.find(id=f"hbp-ref-{ann_id}")
    assert noteref is not None, "NONE intent must still insert a noteref <a>"
    assert noteref.get("href") == f"#hbp-note-{ann_id}", (
        "NONE noteref href must point to the note id"
    )
    # The noteref's containing block must hold the target text
    # (noteref is split into the text node at the target's end)
    block = noteref.find_parent(lambda t: t.name in ("p", "div", "li", "h1", "h2", "h3"))
    assert block is not None, "noteref must be inside a block element"
    assert "bezoar is a stone taken from" in block.get_text(), (
        "the block containing the noteref must also contain the target text"
    )

    # Note is still placed in a cluster
    cluster = soup.find(True, class_="hbp-note-cluster")
    assert cluster is not None, "NONE intent must still produce a cluster div"
    note = cluster.find(True, class_="hbp-note")
    assert note is not None, "NONE intent must still produce a note inside the cluster"
    assert note.get("id") == f"hbp-note-{ann_id}", (
        f"NONE note id must be hbp-note-{ann_id}"
    )


def test_nl1_bidirectional_links_all_resolve(
    epub_src: Path, tmp_path: Path
) -> None:
    """NL1 bidirectional invariant (3-annotation sweep): every noteref href resolves
    to a note id in the same chapter; every back-link href resolves to a noteref id;
    all hbp- ids are unique per chapter."""
    anns = [
        _ann("ann-bi-1", "bezoar is a stone taken from"),
        _ann("ann-bi-2", "First heat the flask"),  # unique; "Stir clockwise three times" repeats twice
        _ann("ann-bi-3", "fine powder on heating"),
    ]
    plan = _plan([_unit(_CH1_ORDINAL, anns)])
    _, out = _render(epub_src, plan, tmp_path)
    with zipfile.ZipFile(out) as zf:
        ch1_bytes = _chapter_bytes(zf, "ch1.xhtml")
    soup = BeautifulSoup(ch1_bytes, "lxml")

    # Collect all ids in the chapter
    all_ids = {
        tag.get("id")
        for tag in soup.find_all(True)
        if tag.get("id")
    }

    # All noterefs must href-resolve to a note id
    noterefs = soup.find_all(True, class_="hbp-noteref")
    assert len(noterefs) == 3, f"expected 3 noterefs; got {len(noterefs)}"
    for ref in noterefs:
        href = ref.get("href", "")
        assert href.startswith("#"), f"noteref href must be a fragment; got {href!r}"
        target_id = href[1:]
        assert target_id in all_ids, (
            f"noteref href {href!r} does not resolve to any id in the chapter"
        )
        assert target_id.startswith("hbp-note-"), (
            f"noteref must point to a note id; got {target_id!r}"
        )

    # All notes must have a back-link that href-resolves to a noteref id
    notes = soup.find_all(True, class_="hbp-note")
    assert len(notes) == 3, f"expected 3 notes; got {len(notes)}"
    for note in notes:
        backlink = note.find("a", class_="hbp-note-backlink")
        assert backlink is not None, f"note {note.get('id')!r} has no back-link"
        href = backlink.get("href", "")
        assert href.startswith("#"), f"back-link href must be a fragment; got {href!r}"
        target_id = href[1:]
        assert target_id in all_ids, (
            f"back-link href {href!r} does not resolve to any id in the chapter"
        )
        assert target_id.startswith("hbp-ref-"), (
            f"back-link must point to a noteref id; got {target_id!r}"
        )

    # All hbp- ids must be unique
    note_ids = [n.get("id") for n in notes]
    ref_ids = [r.get("id") for r in noterefs]
    all_hbp_ids = note_ids + ref_ids
    assert len(all_hbp_ids) == len(set(all_hbp_ids)), (
        f"all hbp- ids must be unique per chapter; duplicates in {all_hbp_ids!r}"
    )


def test_nl1_body_text_preserved_and_report_semantics_unchanged(
    epub_src: Path, tmp_path: Path
) -> None:
    """NL1 invariants: RenderReport rendered/skipped semantics are unchanged by the
    DOM restructure; original body text is preserved as a subsequence (noteref digits
    and back-link counters are the only additive text — nothing is removed or reordered).
    """
    ann_id = "ann-text-inv"
    plan = _plan(
        [_unit(_CH1_ORDINAL, [_ann(ann_id, "bezoar is a stone taken from")])]
    )
    report, out = _render(epub_src, plan, tmp_path)

    # RenderReport semantics must be unchanged by NL1 DOM restructure
    assert report.rendered == (ann_id,)
    assert report.skipped == ()
    assert report.marks_only == ()
    assert DegradationFlag.EPUB_NO_TARGET_GEOMETRY in report.degradation_flags

    with zipfile.ZipFile(out) as zf:
        ch1_bytes = _chapter_bytes(zf, "ch1.xhtml")
    soup = BeautifulSoup(ch1_bytes, "lxml")

    # NL1 structural invariant: rendered annotations must place notes in cluster divs.
    # This assertion fails on HEAD (no clusters) and passes after NL1 is implemented.
    clusters = soup.find_all(True, class_="hbp-note-cluster")
    assert len(clusters) >= 1, (
        "NL1: rendered annotations must produce at least one hbp-note-cluster div"
    )

    # Remove NL1 additive content: cluster divs (with aside notes + back-links)
    # and noteref anchors (digit-only inline markers).
    for cluster in clusters:
        cluster.extract()
    for noteref in soup.find_all(True, class_="hbp-noteref"):
        noteref.extract()

    remaining = soup.body.get_text() if soup.body else ""
    # Every original phrase from _CH1_CONTENT must survive in the remaining text
    for phrase in (
        "bezoar is a stone taken from the stomach of a goat",
        "Stir clockwise three times",
        "asphodel",
        "fine powder on heating",
        "First heat the flask",
    ):
        assert phrase in remaining, (
            f"original body phrase {phrase!r} missing after removing NL1 additive content"
        )


# ---------------------------------------------------------------------------
# EPUB-NL2 — block-first note CSS + progressive width-gated float
#
# These tests are controller-authored and MUST FAIL on HEAD (NL1 branch) before
# Codex implements NL2.  Contract from nl2-block-first-css-brief.md:
#
#   • Cluster carries hbp-note-cluster-floatable (EPUB 2 + EPUB 3, unconditional).
#   • _ANNOTATION_CSS: block-first base rules for cluster/note/noteref/backlink.
#   • @media (min-width: 40em) replaces @supports; float/width on floatable class.
#   • Negative pins: @supports gone, inline-block gone, no px in hbp rules.
#   • Untouched: .hbp-mark-* rules present; .hbp-note has Caveat font-family.
# ---------------------------------------------------------------------------


def _get_css_text(out: Path) -> str:
    """Extract the injected hbp-annotations.css from a rendered EPUB archive."""
    with zipfile.ZipFile(out) as zf:
        css_files = [n for n in zf.namelist() if n.endswith("hbp-annotations.css")]
        assert css_files, "hbp-annotations.css not found in EPUB archive"
        return zf.read(css_files[0]).decode("utf-8")


def test_nl2_cluster_carries_floatable_class_epub3(
    epub_src: Path, tmp_path: Path
) -> None:
    """NL2 EPUB 3: every hbp-note-cluster must also carry hbp-note-cluster-floatable."""
    plan = _plan([_unit(_CH1_ORDINAL, [_ann(_ANN_UNIQUE, "bezoar is a stone taken from")])])
    _, out = _render(epub_src, plan, tmp_path)
    with zipfile.ZipFile(out) as zf:
        ch1_bytes = _chapter_bytes(zf, "ch1.xhtml")
    soup = BeautifulSoup(ch1_bytes, "lxml")
    clusters = soup.find_all(True, class_="hbp-note-cluster")
    assert len(clusters) >= 1, "must produce at least one cluster"
    for cluster in clusters:
        cls = set(cluster.get("class") or [])
        assert "hbp-note-cluster-floatable" in cls, (
            f"NL2 EPUB 3: every cluster must also carry hbp-note-cluster-floatable; "
            f"got {cls!r}"
        )


def test_nl2_cluster_carries_floatable_class_epub2(
    epub_src: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """NL2 EPUB 2: hbp-note-cluster-floatable must be emitted in the EPUB 2 branch too."""
    _real_read_epub = epub.read_epub

    def _epub2_read(path: str, *args: object, **kwargs: object) -> object:
        book = _real_read_epub(path, *args, **kwargs)
        book.version = "2.0"
        return book

    monkeypatch.setattr(epub, "read_epub", _epub2_read)

    plan = _plan([_unit(_CH1_ORDINAL, [_ann(_ANN_UNIQUE, "bezoar is a stone taken from")])])
    _, out = _render(epub_src, plan, tmp_path)
    with zipfile.ZipFile(out) as zf:
        ch1_bytes = _chapter_bytes(zf, "ch1.xhtml")
    soup = BeautifulSoup(ch1_bytes, "lxml")
    clusters = soup.find_all(True, class_="hbp-note-cluster")
    assert len(clusters) >= 1, "EPUB 2 must still produce a cluster"
    for cluster in clusters:
        cls = set(cluster.get("class") or [])
        assert "hbp-note-cluster-floatable" in cls, (
            f"NL2 EPUB 2: every cluster must carry hbp-note-cluster-floatable; "
            f"got {cls!r}"
        )


def test_nl2_css_block_first_base_rules(
    epub_src: Path, tmp_path: Path
) -> None:
    """NL2 stylesheet must contain the block-first base rules:
    .hbp-note-cluster (display:block), .hbp-note (overflow-wrap:break-word),
    .hbp-noteref (vertical-align:super), .hbp-note-backlink present."""
    plan = _plan([_unit(_CH1_ORDINAL, [_ann(_ANN_UNIQUE, "bezoar is a stone taken from")])])
    _, out = _render(epub_src, plan, tmp_path)
    css_text = _get_css_text(out)

    # .hbp-note-cluster rule: display: block
    cluster_rule = re.search(
        r"\.hbp-note-cluster\s*\{([^}]+)\}", css_text
    )
    assert cluster_rule, "NL2: .hbp-note-cluster rule block not found in stylesheet"
    assert re.search(r"display\s*:\s*block", cluster_rule.group(1)), (
        "NL2: .hbp-note-cluster must have display: block"
    )

    # .hbp-note rule: overflow-wrap: break-word
    note_rule = re.search(r"\.hbp-note\s*\{([^}]+)\}", css_text)
    assert note_rule, "NL2: .hbp-note rule block not found"
    assert re.search(r"overflow-wrap\s*:\s*break-word", note_rule.group(1)), (
        "NL2: .hbp-note must have overflow-wrap: break-word"
    )

    # .hbp-noteref rule: vertical-align: super
    noteref_rule = re.search(r"\.hbp-noteref\s*\{([^}]+)\}", css_text)
    assert noteref_rule, "NL2: .hbp-noteref rule block not found"
    assert re.search(r"vertical-align\s*:\s*super", noteref_rule.group(1)), (
        "NL2: .hbp-noteref must have vertical-align: super"
    )

    # .hbp-note-backlink rule present
    assert ".hbp-note-backlink" in css_text, (
        "NL2: .hbp-note-backlink rule must be present in the stylesheet"
    )


def test_nl2_css_media_float_enhancement(
    epub_src: Path, tmp_path: Path
) -> None:
    """NL2 stylesheet must contain an @media (min-width: 40em) block with
    .hbp-note-cluster-floatable carrying float:right, width:30%, max-width:12em."""
    plan = _plan([_unit(_CH1_ORDINAL, [_ann(_ANN_UNIQUE, "bezoar is a stone taken from")])])
    _, out = _render(epub_src, plan, tmp_path)
    css_text = _get_css_text(out)

    # @media block with 40em width gate
    assert re.search(r"@media[^{]*min-width\s*:\s*40em", css_text), (
        "NL2: stylesheet must contain @media (min-width: 40em)"
    )
    # .hbp-note-cluster-floatable with float: right inside @media
    assert ".hbp-note-cluster-floatable" in css_text, (
        "NL2: .hbp-note-cluster-floatable must appear in the stylesheet"
    )
    # float: right and width: 30% must be present (inside the @media block)
    assert re.search(r"float\s*:\s*right", css_text), (
        "NL2: float: right must appear in the stylesheet (inside @media)"
    )
    assert re.search(r"width\s*:\s*30%", css_text), (
        "NL2: width: 30% must be on .hbp-note-cluster-floatable"
    )
    assert re.search(r"max-width\s*:\s*12em", css_text), (
        "NL2: max-width: 12em must be on .hbp-note-cluster-floatable"
    )


def test_nl2_css_negative_pins(
    epub_src: Path, tmp_path: Path
) -> None:
    """NL2 negative: @supports removed; inline-block removed; no position:absolute;
    no px unit in any hbp rule block."""
    plan = _plan([_unit(_CH1_ORDINAL, [_ann(_ANN_UNIQUE, "bezoar is a stone taken from")])])
    _, out = _render(epub_src, plan, tmp_path)
    css_text = _get_css_text(out)

    assert "@supports" not in css_text, (
        "NL2: @supports must be removed from the stylesheet"
    )
    assert "inline-block" not in css_text, (
        "NL2: display:inline-block must be removed from the stylesheet"
    )
    assert not re.search(r"position\s*:\s*absolute", css_text), (
        "NL2: position:absolute must not appear in the stylesheet"
    )
    # No px units in NL2-owned rule blocks (em/% only).
    # .hbp-mark-* and .hbp-target* rules are exempt — their px borders are
    # pinned by the MP2a contract and NL2 is explicitly forbidden from touching them.
    _nl2_selector_patterns = [
        r"\.hbp-note-cluster\s*\{([^}]+)\}",
        r"\.hbp-note\s*\{([^}]+)\}",
        r"\.hbp-noteref\s*\{([^}]+)\}",
        r"\.hbp-note-backlink\s*\{([^}]+)\}",
        r"\.hbp-note-cluster-floatable\s*\{([^}]+)\}",
    ]
    for pat in _nl2_selector_patterns:
        for block in re.findall(pat, css_text):
            assert "px" not in block, (
                f"NL2: px unit found in a NL2-owned rule block: {block.strip()!r}"
            )


def test_nl2_css_untouched_mark_rules_and_caveat_font(
    epub_src: Path, tmp_path: Path
) -> None:
    """NL2 must not remove .hbp-mark-* rules or the Caveat font-family from .hbp-note."""
    plan = _plan([_unit(_CH1_ORDINAL, [_ann(_ANN_UNIQUE, "bezoar is a stone taken from")])])
    _, out = _render(epub_src, plan, tmp_path)
    css_text = _get_css_text(out)

    # .hbp-mark-* rules untouched (spot-check 4 intents)
    for slug in ("underline", "circle", "strike", "highlight"):
        assert f".hbp-mark-{slug}" in css_text, (
            f"NL2 must not remove .hbp-mark-{slug} from the stylesheet"
        )

    # .hbp-note font-family must still include Caveat (handwriting font)
    note_rule = re.search(r"\.hbp-note\s*\{([^}]+)\}", css_text)
    assert note_rule, ".hbp-note rule block not found"
    assert "Caveat" in note_rule.group(1), (
        "NL2: .hbp-note must still list 'Caveat' in font-family"
    )


# ---------------------------------------------------------------------------
# NL3 — density + degradation
# ---------------------------------------------------------------------------

# Four non-overlapping target phrases, all in a single <p> block (ch1).
_NL3_CH1_CONTENT = (
    "<h1>Chapter One — Dense</h1>"
    "<p>Heat the armadillo bile gently until it shimmers,"
    " then add powdered asphodel root while stirring,"
    " followed by the wormwood infusion clockwise,"
    " and finally seal with essence of Dittany.</p>"
)

# One sparse chapter (fewer than 4 targets in any single block).
_NL3_CH2_CONTENT = (
    "<h1>Chapter Two — Sparse</h1>"
    "<p>The bezoar dissolves slowly in moonwater."
    " Add a single sprig of valerian to complete.</p>"
)

_NL3_CH1_ORDINAL = 2
_NL3_CH2_ORDINAL = 3

_NL3_ANN_1 = "nl3-ann-1"
_NL3_ANN_2 = "nl3-ann-2"
_NL3_ANN_3 = "nl3-ann-3"
_NL3_ANN_4 = "nl3-ann-4"
_NL3_ANN_SPARSE = "nl3-ann-sparse"

# Ordered so zip(ids, targets) aligns correctly.
_NL3_ANN_IDS = [_NL3_ANN_1, _NL3_ANN_2, _NL3_ANN_3, _NL3_ANN_4]
_NL3_TARGETS = [
    "armadillo bile gently until it shimmers",
    "powdered asphodel root while stirring",
    "wormwood infusion clockwise",
    "essence of Dittany",
]


@pytest.fixture(scope="module")
def nl3_epub_src(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Two-chapter EPUB for NL3 density tests.  Chapter 1 holds four unique
    non-overlapping target phrases in a single <p>; Chapter 2 holds one."""
    tmp = tmp_path_factory.mktemp("epub_nl3_src")
    book = epub.EpubBook()
    book.set_identifier("hbp-nl3-density-test")
    book.set_title("NL3 Density Test Book")
    book.set_language("en")

    ch1 = epub.EpubHtml(uid="ch1", file_name="ch1.xhtml", lang="en")
    ch1.content = _NL3_CH1_CONTENT
    ch2 = epub.EpubHtml(uid="ch2", file_name="ch2.xhtml", lang="en")
    ch2.content = _NL3_CH2_CONTENT

    for item in (ch1, ch2, epub.EpubNcx(), epub.EpubNav()):
        book.add_item(item)
    book.toc = [ch1, ch2]
    book.spine = ["nav", ch1, ch2]

    path = tmp / "nl3_src.epub"
    epub.write_epub(str(path), book)
    return path


def test_nl3_three_notes_non_dense(nl3_epub_src: Path, tmp_path: Path) -> None:
    """NL3: a cluster with 3 notes keeps hbp-note-cluster-floatable; dense class
    absent; EPUB_DENSE_NOTES_BLOCK_FALLBACK must NOT appear in degradation_flags.
    Regression guard — this behaviour must survive after the dense threshold is wired."""
    plan = _plan([_unit(_NL3_CH1_ORDINAL, [
        _ann(_NL3_ANN_1, _NL3_TARGETS[0]),
        _ann(_NL3_ANN_2, _NL3_TARGETS[1]),
        _ann(_NL3_ANN_3, _NL3_TARGETS[2]),
    ])])
    report, out = _render(nl3_epub_src, plan, tmp_path)

    with zipfile.ZipFile(out) as zf:
        ch1_bytes = _chapter_bytes(zf, "ch1.xhtml")
    soup = BeautifulSoup(ch1_bytes, "lxml")
    clusters = soup.find_all(True, class_="hbp-note-cluster")
    assert len(clusters) >= 1, "must produce at least one cluster for a 3-note plan"
    for cluster in clusters:
        cls = set(cluster.get("class") or [])
        assert "hbp-note-cluster-floatable" in cls, (
            f"NL3: 3-note cluster must keep hbp-note-cluster-floatable; got {cls!r}"
        )
        assert "hbp-note-cluster-dense" not in cls, (
            f"NL3: 3-note cluster must NOT carry hbp-note-cluster-dense; got {cls!r}"
        )
    assert DegradationFlag.EPUB_DENSE_NOTES_BLOCK_FALLBACK not in report.degradation_flags, (
        "NL3: EPUB_DENSE_NOTES_BLOCK_FALLBACK must NOT be set for a 3-note cluster"
    )


def test_nl3_four_notes_cluster_is_dense_not_floatable(
    nl3_epub_src: Path, tmp_path: Path
) -> None:
    """NL3: the 4th note flips the cluster — hbp-note-cluster-dense added,
    hbp-note-cluster-floatable removed; EPUB_DENSE_NOTES_BLOCK_FALLBACK appears
    after EPUB_NO_TARGET_GEOMETRY in degradation_flags."""
    plan = _plan([_unit(_NL3_CH1_ORDINAL, [
        _ann(ann_id, target)
        for ann_id, target in zip(_NL3_ANN_IDS, _NL3_TARGETS, strict=True)
    ])])
    report, out = _render(nl3_epub_src, plan, tmp_path)

    with zipfile.ZipFile(out) as zf:
        ch1_bytes = _chapter_bytes(zf, "ch1.xhtml")
    soup = BeautifulSoup(ch1_bytes, "lxml")
    clusters = soup.find_all(True, class_="hbp-note-cluster")
    assert len(clusters) >= 1, "must produce at least one cluster for a 4-note plan"
    dense_clusters = [
        c for c in clusters if "hbp-note-cluster-dense" in (c.get("class") or [])
    ]
    assert dense_clusters, (
        "NL3: the 4-note cluster must carry hbp-note-cluster-dense"
    )
    for cluster in dense_clusters:
        cls = set(cluster.get("class") or [])
        assert "hbp-note-cluster-floatable" not in cls, (
            f"NL3: dense cluster must NOT carry hbp-note-cluster-floatable; got {cls!r}"
        )

    flags = list(report.degradation_flags)
    assert DegradationFlag.EPUB_NO_TARGET_GEOMETRY in flags, (
        "NL3: EPUB_NO_TARGET_GEOMETRY must still be present alongside the dense flag"
    )
    assert DegradationFlag.EPUB_DENSE_NOTES_BLOCK_FALLBACK in flags, (
        "NL3: EPUB_DENSE_NOTES_BLOCK_FALLBACK must appear when a 4-note cluster is emitted"
    )
    no_geom_idx = flags.index(DegradationFlag.EPUB_NO_TARGET_GEOMETRY)
    dense_idx = flags.index(DegradationFlag.EPUB_DENSE_NOTES_BLOCK_FALLBACK)
    assert no_geom_idx < dense_idx, (
        "NL3: EPUB_NO_TARGET_GEOMETRY must precede EPUB_DENSE_NOTES_BLOCK_FALLBACK in flags"
    )


def test_nl3_mixed_book_flag_once_sparse_cluster_unaffected(
    nl3_epub_src: Path, tmp_path: Path
) -> None:
    """NL3: a book with one dense and one sparse cluster emits the degradation
    flag exactly once; the sparse cluster keeps hbp-note-cluster-floatable and
    never acquires hbp-note-cluster-dense."""
    plan = _plan([
        _unit(_NL3_CH1_ORDINAL, [
            _ann(ann_id, target)
            for ann_id, target in zip(_NL3_ANN_IDS, _NL3_TARGETS, strict=True)
        ]),
        _unit(_NL3_CH2_ORDINAL, [
            _ann(_NL3_ANN_SPARSE, "bezoar dissolves slowly in moonwater"),
        ]),
    ])
    report, out = _render(nl3_epub_src, plan, tmp_path)

    with zipfile.ZipFile(out) as zf:
        ch1_bytes = _chapter_bytes(zf, "ch1.xhtml")
        ch2_bytes = _chapter_bytes(zf, "ch2.xhtml")

    # Dense chapter: at least one cluster carries hbp-note-cluster-dense
    soup1 = BeautifulSoup(ch1_bytes, "lxml")
    dense_clusters = soup1.find_all(True, class_="hbp-note-cluster-dense")
    assert dense_clusters, "NL3: ch1 must contain at least one dense cluster in mixed book"

    # Sparse chapter: all clusters keep floatable, none are dense
    soup2 = BeautifulSoup(ch2_bytes, "lxml")
    sparse_clusters = soup2.find_all(True, class_="hbp-note-cluster")
    assert sparse_clusters, "NL3: ch2 must contain at least one cluster in mixed book"
    for cluster in sparse_clusters:
        cls = set(cluster.get("class") or [])
        assert "hbp-note-cluster-dense" not in cls, (
            f"NL3: ch2 sparse cluster must not be dense in mixed book; got {cls!r}"
        )
        assert "hbp-note-cluster-floatable" in cls, (
            f"NL3: ch2 sparse cluster must remain floatable in mixed book; got {cls!r}"
        )

    # RenderReport.degradation_flags is de-duped by the model validator, so the
    # count here tests that the production code adds the flag at most once.
    dense_flag_count = sum(
        1 for f in report.degradation_flags
        if f == DegradationFlag.EPUB_DENSE_NOTES_BLOCK_FALLBACK
    )
    assert dense_flag_count == 1, (
        f"NL3: EPUB_DENSE_NOTES_BLOCK_FALLBACK must appear exactly once; "
        f"count={dense_flag_count}"
    )


def test_nl3_dense_annotations_all_in_rendered_not_skipped(
    nl3_epub_src: Path, tmp_path: Path
) -> None:
    """NL3: density is presentation-only.  All 4 annotations targeting a dense
    cluster must appear in report.rendered; none may appear in report.skipped.
    Regression guard — skip semantics must not change after the dense threshold."""
    plan = _plan([_unit(_NL3_CH1_ORDINAL, [
        _ann(ann_id, target)
        for ann_id, target in zip(_NL3_ANN_IDS, _NL3_TARGETS, strict=True)
    ])])
    report, _ = _render(nl3_epub_src, plan, tmp_path)

    rendered_set = set(report.rendered)
    skipped_set = {r.annotation_id for r in report.skipped}
    for ann_id in _NL3_ANN_IDS:
        assert ann_id in rendered_set, (
            f"NL3: dense annotation {ann_id!r} must appear in rendered, not be skipped"
        )
        assert ann_id not in skipped_set, (
            f"NL3: dense annotation {ann_id!r} must not appear in skipped"
        )
    assert not report.marks_only, (
        "NL3: marks_only must be empty — density must not demote annotations to mark-only"
    )


def test_nl3_css_has_dense_cluster_clear_rule(
    nl3_epub_src: Path, tmp_path: Path
) -> None:
    """NL3 stylesheet must add .hbp-note-cluster-dense { clear: both; } and must
    not alter the existing @media float rule for hbp-note-cluster-floatable."""
    plan = _plan([_unit(_NL3_CH1_ORDINAL, [_ann(_NL3_ANN_1, _NL3_TARGETS[0])])])
    _, out = _render(nl3_epub_src, plan, tmp_path)
    css_text = _get_css_text(out)

    dense_rule = re.search(r"\.hbp-note-cluster-dense\s*\{([^}]+)\}", css_text)
    assert dense_rule, "NL3: .hbp-note-cluster-dense rule not found in stylesheet"
    assert re.search(r"clear\s*:\s*both", dense_rule.group(1)), (
        "NL3: .hbp-note-cluster-dense must include 'clear: both'"
    )

    # Existing @media float rule for floatable clusters must remain unchanged.
    assert re.search(r"@media\s*\(\s*min-width\s*:\s*40em\s*\)", css_text), (
        "NL3: @media (min-width: 40em) block must still be present after NL3"
    )
    assert re.search(r"\.hbp-note-cluster-floatable\s*\{", css_text), (
        "NL3: .hbp-note-cluster-floatable rule must remain in the stylesheet"
    )


def test_nl3_model_enum_value_and_report_version() -> None:
    """NL3 model contract: the new enum member has exactly the pinned string value;
    report_version is still '1.0' (no version bump for an additive flag)."""
    assert DegradationFlag.EPUB_DENSE_NOTES_BLOCK_FALLBACK.value == (
        "epub_dense_notes_block_fallback"
    ), (
        "NL3: DegradationFlag.EPUB_DENSE_NOTES_BLOCK_FALLBACK.value must be "
        "'epub_dense_notes_block_fallback'"
    )
    assert RenderReport().report_version == "1.1", (
        "Placement records and lossless composer diagnostics use report version 1.1"
    )


# ---------------------------------------------------------------------------
# NL4 — real-DOM caret glyph
# ---------------------------------------------------------------------------

_NL4_CARET_TARGET = "bezoar is a stone taken from"
_NL4_CROSS_NODE_TARGET = "asphodel root dissolves to fine powder on heating"
_NL4_ANN_CARET = "nl4-ann-caret"
_NL4_ANN_CROSS = "nl4-ann-cross"


def test_nl4_caret_glyph_on_single_node_target(epub_src: Path, tmp_path: Path) -> None:
    """NL4: a CARET annotation on a single text node produces exactly one
    span.hbp-caret-glyph with aria-hidden='true' and text '‸', as the last
    child of the mark span; body text is character-identical outside the glyph."""
    plan = _plan([_unit(_CH1_ORDINAL, [
        _ann(_NL4_ANN_CARET, _NL4_CARET_TARGET, mark_intent=MarkIntent.CARET),
    ])])
    _, out = _render(epub_src, plan, tmp_path)
    with zipfile.ZipFile(out) as zf:
        ch1_bytes = _chapter_bytes(zf, "ch1.xhtml")
    soup = BeautifulSoup(ch1_bytes, "lxml")

    # Exactly one glyph in the chapter
    glyphs = soup.find_all("span", class_="hbp-caret-glyph")
    assert len(glyphs) == 1, (
        f"NL4: exactly one hbp-caret-glyph expected for a single CARET annotation; "
        f"got {len(glyphs)}"
    )
    glyph = glyphs[0]
    assert glyph.get("aria-hidden") == "true", (
        "NL4: hbp-caret-glyph must carry aria-hidden='true'"
    )
    assert glyph.get_text() == "‸", (
        f"NL4: hbp-caret-glyph text must be ‸ (U+2038); got {glyph.get_text()!r}"
    )

    # Glyph must be the last child of its parent mark span
    parent = glyph.parent
    assert parent is not None and "hbp-mark-caret" in (parent.get("class") or []), (
        "NL4: hbp-caret-glyph must be a child of the hbp-mark-caret span"
    )
    assert parent.contents[-1] == glyph, (
        "NL4: hbp-caret-glyph must be the last child of the mark span"
    )

    # Mark span text (excluding glyph) is character-identical to the original target
    text_without_glyph = parent.get_text().replace("‸", "")
    assert text_without_glyph == _NL4_CARET_TARGET, (
        f"NL4: mark span text without glyph must equal the original target; "
        f"got {text_without_glyph!r}"
    )


def test_nl4_caret_glyph_on_final_fragment_only_for_cross_node(
    epub_src: Path, tmp_path: Path
) -> None:
    """NL4: a cross-node CARET target (≥2 mark fragments) gets the glyph on the
    FINAL fragment in document order only; exactly one glyph per annotation."""
    plan = _plan([_unit(_CH1_ORDINAL, [
        _ann(_NL4_ANN_CROSS, _NL4_CROSS_NODE_TARGET, mark_intent=MarkIntent.CARET),
    ])])
    _, out = _render(epub_src, plan, tmp_path)
    with zipfile.ZipFile(out) as zf:
        ch1_bytes = _chapter_bytes(zf, "ch1.xhtml")
    soup = BeautifulSoup(ch1_bytes, "lxml")

    # The target spans <em>asphodel</em> and <strong>fine powder</strong> → ≥2 fragments
    fragments = soup.find_all("span", class_="hbp-mark-caret")
    assert len(fragments) >= 2, (
        f"NL4: cross-node CARET must produce ≥2 hbp-mark-caret fragments; "
        f"got {len(fragments)}"
    )

    # Exactly one glyph total, inside the last fragment in document order
    glyphs = soup.find_all("span", class_="hbp-caret-glyph")
    assert len(glyphs) == 1, (
        f"NL4: exactly one hbp-caret-glyph expected for one cross-node annotation; "
        f"got {len(glyphs)}"
    )
    last_fragment = fragments[-1]
    assert glyphs[0].parent == last_fragment, (
        "NL4: hbp-caret-glyph must be inside the LAST fragment in document order"
    )
    assert last_fragment.contents[-1] == glyphs[0], (
        "NL4: hbp-caret-glyph must be the last child of the final fragment"
    )


@pytest.mark.parametrize(
    "intent",
    [MarkIntent.UNDERLINE, MarkIntent.CIRCLE, MarkIntent.STRIKE, MarkIntent.HIGHLIGHT],
    ids=["underline", "circle", "strike", "highlight"],
)
def test_nl4_no_caret_glyph_for_non_caret_intent(
    epub_src: Path, tmp_path: Path, intent: MarkIntent
) -> None:
    """NL4 regression guard: non-CARET intents must produce zero hbp-caret-glyph
    elements.  Must pass both before and after NL4 is implemented."""
    plan = _plan([_unit(_CH1_ORDINAL, [
        _ann(_NL4_ANN_CARET, _NL4_CARET_TARGET, mark_intent=intent),
    ])])
    _, out = _render(epub_src, plan, tmp_path)
    with zipfile.ZipFile(out) as zf:
        ch1_bytes = _chapter_bytes(zf, "ch1.xhtml")
    soup = BeautifulSoup(ch1_bytes, "lxml")
    glyphs = soup.find_all("span", class_="hbp-caret-glyph")
    assert not glyphs, (
        f"NL4: intent {intent.value!r} must not produce hbp-caret-glyph elements; "
        f"found {len(glyphs)}"
    )


def test_nl4_css_no_after_rule_and_caret_glyph_rule(
    epub_src: Path, tmp_path: Path
) -> None:
    """NL4 stylesheet contract: .hbp-mark-caret::after must be absent (prevents
    double-render on capable engines); .hbp-caret-glyph must be present with
    font-weight: bold."""
    plan = _plan([_unit(_CH1_ORDINAL, [_ann(_NL4_ANN_CARET, _NL4_CARET_TARGET)])])
    _, out = _render(epub_src, plan, tmp_path)
    css_text = _get_css_text(out)

    assert ".hbp-mark-caret::after" not in css_text, (
        "NL4: .hbp-mark-caret::after must be removed from the stylesheet"
    )
    glyph_rule = re.search(r"\.hbp-caret-glyph\s*\{([^}]+)\}", css_text)
    assert glyph_rule, "NL4: .hbp-caret-glyph rule not found in stylesheet"
    assert re.search(r"font-weight\s*:\s*bold", glyph_rule.group(1)), (
        "NL4: .hbp-caret-glyph must include font-weight: bold"
    )
