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
    notes = soup.find_all("span", class_=lambda c: c and "hbp-note" in c)
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
    notes = soup.find_all("span", class_=lambda c: c and "hbp-note" in c)
    # No target span — NONE intent leaves the matched text node untouched.
    assert len(targets) == 0, "NONE intent must not emit any hbp-target span"
    # Exactly one note span still inserted.
    assert len(notes) == 1, "NONE intent must still insert exactly one hbp-note span"
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
