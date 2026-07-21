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
    for intent_slug in ("underline", "circle", "strike", "highlight", "caret"):
        assert f".hbp-mark-{intent_slug}" in css_text, (
            f"stylesheet must contain a .hbp-mark-{intent_slug} rule"
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
