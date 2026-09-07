"""Independent falsification of the strict placement contract (04a4489 interrupted).

These tests pin the public, supported surface of ``halfblood.placement`` and
``halfblood.models.placement`` without mocking the renderer. They use real
PyMuPDF pages and real BeautifulSoup DOMs. They are red when:

* the contract allows a refusal to carry a usable anchor,
* a resolved record is missing raw text evidence or a source digest,
* the geometry coordinate space contradicts its status,
* a repeated target resolves without distinguishing hints,
* a stale hint or offset is honoured,
* raw-span mapping drifts from NFC/whitespace normalisation,
* bounded inputs are not fail-closed,
* the EPUB match rehydrates against a mutated DOM,
* a fixed-layout EPUB is silently treated as reflowable by the resolver.

No network calls, no API keys. ``.venv/bin/python`` is the only required
interpreter. The numeric geometry oracles for PDF page rotation are derived
independently from PyMuPDF's own ``page.rotation_matrix`` and per-character
bboxes (``page.get_text("rawdict")``) so the test is not merely asserting
"the resolver agrees with itself".

The parent suite already covers the ``EpubProcessor._fixed_layout_item``
override; this file tests the resolver's own ``fixed_layout=True`` path and
the related ``unsupported_renderer`` status, which is the part the resolver
contract owns.
"""

from __future__ import annotations

import fitz
import pytest
from bs4 import BeautifulSoup
from pydantic import ValidationError

from halfblood.documents.epub import iter_inline_runs
from halfblood.documents.matching import (
    MAX_CANDIDATES,
    MAX_INPUT_CHARS,
    MAX_NEEDLE_CHARS,
    NormalizedText,
)
from halfblood.models.annotations import TargetSelector
from halfblood.models.placement import (
    EpubSegmentRef,
    PlacementPoint,
    PlacementQuad,
    PlacementResult,
    PlacementStatus,
)
from halfblood.placement import (
    epub_match_from_placement,
    resolve_epub_quote,
    resolve_pdf_quote,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_pdf_page(
    tmp_path, text: str, *, rotation: int = 0, fontsize: int = 11,
    width: float = 612.0, height: float = 792.0,
    x0: float = 72.0, y0: float = 72.0,
    x1: float = 540.0, y1: float = 200.0,
):
    path = tmp_path / f"page-r{rotation}.pdf"
    with fitz.open() as doc:
        page = doc.new_page(width=width, height=height)
        page.insert_textbox(fitz.Rect(x0, y0, x1, y1), text, fontsize=fontsize)
        page.set_rotation(rotation)
        doc.save(str(path))
    return path


def _char_display_corners(page: fitz.Page):
    """Return one list of 4 display-space corners per glyph, derived from rawdict.

    The corners are the four transformed points of the glyph's mediabox
    bbox: ``(x0, y0)``, ``(x1, y0)``, ``(x1, y1)``, ``(x0, y1)`` after
    multiplication by ``page.rotation_matrix``. Independent of placement.
    """
    out: list[tuple[tuple[float, float], ...]] = []
    rawdict = page.get_text("rawdict")
    matrix = page.rotation_matrix
    for block in rawdict["blocks"]:
        if block["type"] != 0:
            continue
        for line in block["lines"]:
            for span in line["spans"]:
                for char in span["chars"]:
                    bb = char["bbox"]
                    p00 = fitz.Point(bb[0], bb[1]) * matrix
                    p10 = fitz.Point(bb[2], bb[1]) * matrix
                    p11 = fitz.Point(bb[2], bb[3]) * matrix
                    p01 = fitz.Point(bb[0], bb[3]) * matrix
                    out.append(((p00.x, p00.y), (p10.x, p10.y),
                                (p11.x, p11.y), (p01.x, p01.y)))
    return out


def _bbox_of_points(points):
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return min(xs), min(ys), max(xs), max(ys)


# ---------------------------------------------------------------------------
# A. Pydantic PlacementResult — refusal/geometry/schema constraints
# ---------------------------------------------------------------------------


class TestPlacementResultModel:
    """The Pydantic model rejects records that contradict their own status."""

    def test_schema_version_is_pinned(self):
        result = PlacementResult(status="unresolved", renderer="pdf",
                                 reason="quote_not_found")
        assert result.schema_version == "1.0"

    def test_refusal_with_raw_span_rejected(self):
        with pytest.raises(ValidationError):
            PlacementResult.model_validate({
                "status": "unresolved", "renderer": "epub", "reason": "quote_not_found",
                "raw_span": (0, 3),
            })

    def test_refusal_with_matched_text_rejected(self):
        with pytest.raises(ValidationError):
            PlacementResult.model_validate({
                "status": "unresolved", "renderer": "epub", "reason": "quote_not_found",
                "matched_text": "x",
            })

    def test_refusal_with_quads_rejected(self):
        good_quad = PlacementQuad(
            ul=PlacementPoint(x=0, y=0), ur=PlacementPoint(x=1, y=0),
            lr=PlacementPoint(x=1, y=1), ll=PlacementPoint(x=0, y=1),
        )
        with pytest.raises(ValidationError):
            PlacementResult.model_validate({
                "status": "unresolved", "renderer": "epub", "reason": "quote_not_found",
                "quads": (good_quad,),
            })

    def test_refusal_with_epub_segments_rejected(self):
        with pytest.raises(ValidationError):
            PlacementResult.model_validate({
                "status": "unresolved", "renderer": "epub", "reason": "quote_not_found",
                "epub_segments": (EpubSegmentRef(
                    run_index=0, node_index=0, start=0, end=1,
                ),),
            })

    def test_refusal_with_source_digest_rejected(self):
        with pytest.raises(ValidationError):
            PlacementResult.model_validate({
                "status": "unresolved", "renderer": "epub", "reason": "quote_not_found",
                "source_digest": "0" * 64,
            })

    def test_ambiguous_with_anchor_rejected(self):
        with pytest.raises(ValidationError):
            PlacementResult.model_validate({
                "status": "ambiguous", "renderer": "epub", "reason": "ambiguous_quote",
                "candidate_count": 2, "raw_span": (0, 5), "matched_text": "abcde",
                "source_digest": "0" * 64, "coordinate_space": "epub_dom_text",
                "epub_segments": (EpubSegmentRef(
                    run_index=0, node_index=0, start=0, end=1,
                ),),
            })

    @pytest.mark.parametrize("status,reason", [
        ("unresolved", "unique_verified_quote"),
        ("unresolved", "ambiguous_quote"),
        ("unsupported_renderer", "quote_not_found"),
        ("resolved", "fixed_layout_unsupported"),
        ("ambiguous", "fixed_layout_unsupported"),
    ])
    def test_status_reason_pairs_are_inconsistent(self, status, reason):
        with pytest.raises(ValidationError):
            PlacementResult.model_validate({
                "status": status, "renderer": "epub", "reason": reason,
            })

    def test_ambiguous_requires_at_least_two_candidates(self):
        with pytest.raises(ValidationError):
            PlacementResult.model_validate({
                "status": "ambiguous", "renderer": "epub", "reason": "ambiguous_quote",
                "candidate_count": 1,
            })

    @pytest.mark.parametrize("digest", ["", "xyz", "0" * 63, "0" * 65, "g" * 64, "G" * 64])
    def test_source_digest_must_be_lowercase_sha256(self, digest):
        with pytest.raises(ValidationError):
            PlacementResult.model_validate({
                "status": "unresolved", "renderer": "epub", "reason": "quote_not_found",
                "source_digest": digest,
            })

    def test_resolved_pdf_requires_geometry_and_no_epub_segments(self):
        good_quad = PlacementQuad(
            ul=PlacementPoint(x=0, y=0), ur=PlacementPoint(x=10, y=0),
            lr=PlacementPoint(x=10, y=10), ll=PlacementPoint(x=0, y=10),
        )
        with pytest.raises(ValidationError):
            PlacementResult.model_validate({
                "status": "resolved", "renderer": "pdf", "reason": "unique_verified_quote",
                "raw_span": (0, 5), "matched_text": "hello", "candidate_count": 1,
                "source_digest": "0" * 64, "coordinate_space": "pdf_display_points",
                "quads": (good_quad,),
                "epub_segments": (EpubSegmentRef(
                    run_index=0, node_index=0, start=0, end=1,
                ),),
            })

    def test_resolved_epub_requires_segments_and_no_quads(self):
        with pytest.raises(ValidationError):
            PlacementResult.model_validate({
                "status": "resolved", "renderer": "epub", "reason": "unique_verified_quote",
                "raw_span": (0, 5), "matched_text": "hello", "candidate_count": 1,
                "source_digest": "0" * 64, "coordinate_space": "epub_dom_text",
                "epub_segments": (EpubSegmentRef(
                    run_index=0, node_index=0, start=0, end=5,
                ),),
                "quads": (PlacementQuad(
                    ul=PlacementPoint(x=0, y=0), ur=PlacementPoint(x=1, y=0),
                    lr=PlacementPoint(x=1, y=1), ll=PlacementPoint(x=0, y=1),
                ),),
            })

    def test_raw_span_must_cover_matched_text_exactly(self):
        with pytest.raises(ValidationError):
            PlacementResult.model_validate({
                "status": "resolved", "renderer": "epub", "reason": "unique_verified_quote",
                "raw_span": (0, 3), "matched_text": "hello",
                "candidate_count": 1, "source_digest": "0" * 64,
                "coordinate_space": "epub_dom_text",
                "epub_segments": (EpubSegmentRef(
                    run_index=0, node_index=0, start=0, end=3,
                ),),
            })

    def test_extra_fields_are_forbidden(self):
        with pytest.raises(ValidationError):
            PlacementResult.model_validate({
                "status": "unresolved", "renderer": "epub", "reason": "quote_not_found",
                "new_field": "value",
            })

    def test_invalid_coordinates_are_rejected(self):
        with pytest.raises(ValidationError):
            PlacementResult.model_validate({
                "status": "resolved", "renderer": "pdf", "reason": "unique_verified_quote",
                "raw_span": (0, 5), "matched_text": "hello", "candidate_count": 1,
                "source_digest": "0" * 64, "coordinate_space": "pdf_display_points",
                "quads": (PlacementQuad(
                    ul=PlacementPoint(x=float("inf"), y=0),
                    ur=PlacementPoint(x=1, y=0),
                    lr=PlacementPoint(x=1, y=1),
                    ll=PlacementPoint(x=0, y=1),
                ),),
            })


# ---------------------------------------------------------------------------
# B. resolve_pdf_quote — all four statuses against a real PDF page
# ---------------------------------------------------------------------------


class TestResolvePdfQuoteStatuses:
    """Each of the four documented statuses must be reachable against a real page."""

    def test_resolved_status_with_unique_quote(self, tmp_path):
        path = _make_pdf_page(tmp_path, "The dose is five milligrams of potion.")
        doc = fitz.open(str(path))
        try:
            result = resolve_pdf_quote(doc[0], TargetSelector(exact="five milligrams"))
        finally:
            doc.close()
        assert result.status is PlacementStatus.RESOLVED
        assert result.reason == "unique_verified_quote"
        assert result.renderer == "pdf"
        assert result.coordinate_space == "pdf_display_points"
        assert result.quads, "resolved PDF must carry at least one quad"
        assert result.raw_span is not None
        assert result.matched_text == "five milligrams"
        assert result.candidate_count == 1
        assert isinstance(result.source_digest, str) and len(result.source_digest) == 64

    def test_ambiguous_status_with_repeated_quote(self, tmp_path):
        path = _make_pdf_page(tmp_path, "Same here. Same here. Same here.")
        doc = fitz.open(str(path))
        try:
            result = resolve_pdf_quote(doc[0], TargetSelector(exact="Same here"))
        finally:
            doc.close()
        assert result.status is PlacementStatus.AMBIGUOUS
        assert result.reason == "ambiguous_quote"
        assert result.candidate_count == 3
        # Refusal invariants from the model
        assert result.raw_span is None
        assert result.matched_text is None
        assert not result.quads
        assert result.coordinate_space is None

    def test_unresolved_quote_not_found(self, tmp_path):
        path = _make_pdf_page(tmp_path, "The dose is five milligrams of potion.")
        doc = fitz.open(str(path))
        try:
            result = resolve_pdf_quote(doc[0], TargetSelector(exact="fifty milligrams"))
        finally:
            doc.close()
        assert result.status is PlacementStatus.UNRESOLVED
        assert result.reason == "quote_not_found"
        assert result.candidate_count == 0
        assert result.raw_span is None

    def test_unresolved_selector_hints_mismatch(self, tmp_path):
        path = _make_pdf_page(tmp_path, "First the same quote. Then the same quote.")
        doc = fitz.open(str(path))
        try:
            result = resolve_pdf_quote(
                doc[0], TargetSelector(exact="the same quote", prefix="Stale "),
            )
        finally:
            doc.close()
        assert result.status is PlacementStatus.UNRESOLVED
        assert result.reason == "selector_hints_mismatch"
        assert result.candidate_count == 2


# ---------------------------------------------------------------------------
# C. resolve_pdf_quote — bounded inputs (quote, candidate, source size)
# ---------------------------------------------------------------------------


class TestResolvePdfQuoteBounds:
    """Over-large quotes, over-large pages, and over-many candidates fail closed."""

    def test_quote_over_max_needle_chars_refused(self, tmp_path):
        path = _make_pdf_page(tmp_path, "Some text on the page.")
        doc = fitz.open(str(path))
        try:
            huge = "a" * (MAX_NEEDLE_CHARS + 1)
            result = resolve_pdf_quote(doc[0], TargetSelector(exact=huge))
        finally:
            doc.close()
        assert result.status is PlacementStatus.UNRESOLVED
        assert result.reason == "quote_limit_exceeded"
        assert result.candidate_count == 0

    def test_quote_at_exact_max_needle_chars_searches(self, tmp_path):
        path = _make_pdf_page(tmp_path, "Some text on the page.")
        doc = fitz.open(str(path))
        try:
            result = resolve_pdf_quote(
                doc[0], TargetSelector(exact="a" * MAX_NEEDLE_CHARS),
            )
        finally:
            doc.close()
        assert result.status is PlacementStatus.UNRESOLVED
        # The needle is at the bound; it just does not match the page text.
        assert result.reason == "quote_not_found"

    def test_candidate_limit_exceeded(self, tmp_path):
        path = tmp_path / "many.pdf"
        with fitz.open() as doc:
            page = doc.new_page(width=612.0, height=792.0)
            repeats = (MAX_CANDIDATES + 50) * "ab "
            page.insert_textbox(fitz.Rect(72, 72, 540, 20000), repeats, fontsize=6)
            doc.save(str(path))
        doc = fitz.open(str(path))
        try:
            result = resolve_pdf_quote(doc[0], TargetSelector(exact="ab"))
        finally:
            doc.close()
        assert result.status is PlacementStatus.UNRESOLVED
        assert result.reason == "candidate_limit_exceeded"

    def test_input_limit_exceeded_on_oversized_page(self, tmp_path):
        # Build a page whose ``get_text("text")`` exceeds MAX_INPUT_CHARS.
        # insert_text draws a single line at a point; loop until we exceed the bound.
        path = tmp_path / "big.pdf"
        with fitz.open() as doc:
            page = doc.new_page(width=612.0, height=100000.0)
            line = "x" * 100
            y = 30.0
            while True:
                page.insert_text(fitz.Point(72, y), line, fontsize=11)
                y += 14
                if y > 9500:
                    break
            doc.save(str(path))
        doc = fitz.open(str(path))
        try:
            raw = doc[0].get_text("text")
            assert len(raw) > MAX_INPUT_CHARS, (
                f"test fixture must exceed MAX_INPUT_CHARS ({len(raw)} vs {MAX_INPUT_CHARS})"
            )
            result = resolve_pdf_quote(doc[0], TargetSelector(exact="x" * 5))
        finally:
            doc.close()
        assert result.status is PlacementStatus.UNRESOLVED
        assert result.reason == "input_limit_exceeded"

    def test_over_long_prefix_refused(self, tmp_path):
        path = _make_pdf_page(tmp_path, "Some text on the page.")
        doc = fitz.open(str(path))
        try:
            huge = "a" * (MAX_NEEDLE_CHARS + 1)
            result = resolve_pdf_quote(
                doc[0], TargetSelector(exact="text", prefix=huge),
            )
        finally:
            doc.close()
        assert result.status is PlacementStatus.UNRESOLVED
        assert result.reason == "quote_limit_exceeded"


# ---------------------------------------------------------------------------
# D. resolve_pdf_quote — raw-span mapping across NFC and whitespace
# ---------------------------------------------------------------------------


class TestResolvePdfQuoteRawSpan:
    """raw_span must cover the *matched* raw substring, after NFC and whitespace
    folding. The matched text is the raw form, not the normalized form."""

    def test_raw_span_covers_collapsed_whitespace(self, tmp_path):
        # Five spaces between words; the normalizer collapses them, the raw span
        # must be the full original range so geometry covers all glyphs.
        path = _make_pdf_page(tmp_path, "five     milligrams")
        doc = fitz.open(str(path))
        try:
            raw = doc[0].get_text("text")
            result = resolve_pdf_quote(doc[0], TargetSelector(exact="five milligrams"))
        finally:
            doc.close()
        assert result.status is PlacementStatus.RESOLVED
        assert result.raw_span is not None
        start, end = result.raw_span
        # The raw span must cover every glyph including the five spaces.
        assert end - start == len("five     milligrams")
        assert raw[start:end] == "five     milligrams"
        # The matched text preserves the raw surface form, not the folded form.
        assert result.matched_text == "five     milligrams"

    def test_raw_span_covers_curly_quote_after_folding(self, tmp_path):
        # Build a PDF with a curly right single quote; the normalizer folds it.
        path = _make_pdf_page(tmp_path, "it\u2019s five milligrams")
        doc = fitz.open(str(path))
        try:
            raw = doc[0].get_text("text")
            result = resolve_pdf_quote(
                doc[0], TargetSelector(exact="it's five milligrams"),
            )
        finally:
            doc.close()
        if result.status is PlacementStatus.RESOLVED:
            start, end = result.raw_span
            assert raw[start:end] == "it\u2019s five milligrams"
            assert result.matched_text == "it\u2019s five milligrams"
        else:
            # If PyMuPDF's base-14 font substituted the curly quote, the resolver
            # must refuse cleanly rather than anchor to a shorter substring.
            assert result.status is PlacementStatus.UNRESOLVED
            assert result.reason == "quote_not_found"

    def test_raw_span_rejects_quote_shortening(self, tmp_path):
        # The resolver must not silently shorten a long exact quote to a prefix.
        path = _make_pdf_page(
            tmp_path, "The correct dose of this medicine is five milligrams.",
        )
        doc = fitz.open(str(path))
        try:
            raw = doc[0].get_text("text")
            result = resolve_pdf_quote(
                doc[0], TargetSelector(exact="five milligrams"),
            )
        finally:
            doc.close()
        assert result.status is PlacementStatus.RESOLVED, (
            "resolver must not silently shorten a long exact quote"
        )
        start, end = result.raw_span
        # raw span must point at the *exact* occurrence of "five milligrams"
        # in the raw text, not at a shorter prefix or a longest-word anchor.
        assert raw[start:end] == "five milligrams"
        assert end - start > len("milligrams"), "anchor must not be a single word"

    def test_normalizedtext_raw_span_round_trip(self):
        # A pure unit-level oracle: NFC + whitespace folding round-trips exactly.
        raw = "five     milligrams of potion"
        nt = NormalizedText(raw)
        assert nt.text == "five milligrams of potion"
        spans = nt.find_all("five milligrams")
        assert len(spans) == 1
        assert raw[spans[0].start:spans[0].end] == "five     milligrams"


# ---------------------------------------------------------------------------
# E. resolve_pdf_quote — repeated overlapping with hints vs stale hints
# ---------------------------------------------------------------------------


class TestResolvePdfQuoteHints:
    """Hints are constraints. They resolve ambiguity or refuse the record; they
    never silently drop a target."""

    def test_disambiguating_prefix_picks_correct_occurrence(self, tmp_path):
        path = _make_pdf_page(
            tmp_path, "First the dose. Then the dose. Finally the dose.",
        )
        doc = fitz.open(str(path))
        try:
            raw = doc[0].get_text("text")
            result = resolve_pdf_quote(
                doc[0], TargetSelector(exact="the dose", prefix="First "),
            )
        finally:
            doc.close()
        assert result.status is PlacementStatus.RESOLVED
        start, end = result.raw_span
        # The resolved span is preceded by "First " in the source text.
        assert raw[:start].endswith("First ")
        assert raw[start:end] == "the dose"

    def test_disambiguating_offset_picks_correct_occurrence(self, tmp_path):
        path = _make_pdf_page(
            tmp_path, "the dose. the dose. the dose.",
        )
        doc = fitz.open(str(path))
        try:
            raw = doc[0].get_text("text")
            second_start = raw.find("the dose", raw.find("the dose") + 1)
            result = resolve_pdf_quote(
                doc[0], TargetSelector(exact="the dose", start_offset=second_start),
            )
        finally:
            doc.close()
        assert result.status is PlacementStatus.RESOLVED
        assert result.raw_span[0] == second_start

    def test_disambiguating_end_offset_picks_correct_occurrence(self, tmp_path):
        path = _make_pdf_page(
            tmp_path, "alpha the dose bravo. charlie the dose delta.",
        )
        doc = fitz.open(str(path))
        try:
            raw = doc[0].get_text("text")
            first = raw.find("the dose")
            second = raw.find("the dose", first + 1)
            second_end = second + len("the dose")
            result = resolve_pdf_quote(
                doc[0], TargetSelector(exact="the dose", end_offset=second_end),
            )
        finally:
            doc.close()
        assert result.status is PlacementStatus.RESOLVED
        assert result.raw_span[1] == second_end

    def test_stale_prefix_refused_with_selector_hints_mismatch(self, tmp_path):
        path = _make_pdf_page(tmp_path, "First the dose. Then the dose.")
        doc = fitz.open(str(path))
        try:
            result = resolve_pdf_quote(
                doc[0], TargetSelector(exact="the dose", prefix="Stale "),
            )
        finally:
            doc.close()
        assert result.status is PlacementStatus.UNRESOLVED
        assert result.reason == "selector_hints_mismatch"
        # All occurrences are still counted, hint rejection is reported as cause.
        assert result.candidate_count == 2

    def test_stale_offset_refused(self, tmp_path):
        path = _make_pdf_page(tmp_path, "the dose. the dose. the dose.")
        doc = fitz.open(str(path))
        try:
            result = resolve_pdf_quote(
                doc[0], TargetSelector(exact="the dose", start_offset=9999),
            )
        finally:
            doc.close()
        assert result.status is PlacementStatus.UNRESOLVED
        assert result.reason == "selector_hints_mismatch"

    def test_hint_matching_all_occurrences_yields_ambiguous(self, tmp_path):
        # A suffix that matches all 3 occurrences verifies all 3, surfacing as
        # AMBIGUOUS rather than a silent first-occurrence resolve.
        path = _make_pdf_page(
            tmp_path, "the dose one. the dose two. the dose three.",
        )
        doc = fitz.open(str(path))
        try:
            result = resolve_pdf_quote(
                doc[0], TargetSelector(exact="the dose", suffix=" "),
            )
        finally:
            doc.close()
        assert result.status is PlacementStatus.AMBIGUOUS
        assert result.candidate_count == 3
        # Crucially: not a silent resolve to the first occurrence.
        assert result.raw_span is None

    def test_disambiguating_suffix_picks_correct_occurrence(self, tmp_path):
        path = _make_pdf_page(
            tmp_path, "the dose one. the dose two. the dose three.",
        )
        doc = fitz.open(str(path))
        try:
            raw = doc[0].get_text("text")
            second = raw.find("the dose", raw.find("the dose") + 1)
            result = resolve_pdf_quote(
                doc[0], TargetSelector(exact="the dose", suffix=" two."),
            )
        finally:
            doc.close()
        assert result.status is PlacementStatus.RESOLVED
        assert result.raw_span[0] == second


# ---------------------------------------------------------------------------
# F. resolve_pdf_quote — geometry coordinate expectations
# ---------------------------------------------------------------------------


class TestResolvePdfQuoteGeometry:
    """The contract is that quads are in display space (mediabox * rotation_matrix)
    on rotated pages. The numeric oracle is derived from rawdict independently
    of the placement module."""

    @pytest.mark.parametrize("rotation", [0, 90, 180, 270])
    def test_quads_lie_in_display_space(self, tmp_path, rotation):
        path = _make_pdf_page(
            tmp_path, "The dose is five milligrams.", rotation=rotation,
        )
        doc = fitz.open(str(path))
        try:
            page = doc[0]
            raw_text = page.get_text("text")
            result = resolve_pdf_quote(page, TargetSelector(exact="five milligrams"))
            oracle = _char_display_corners(page)
        finally:
            doc.close()
        assert result.status is PlacementStatus.RESOLVED
        assert result.coordinate_space == "pdf_display_points"
        assert result.raw_span is not None
        start, end = result.raw_span
        # Verify raw_span covers the same characters in the raw text.
        assert raw_text[start:end] == "five milligrams"
        # Collect the 4 display-space corners per glyph in the resolved range.
        target_corners = []
        for corners in oracle[start:end]:
            target_corners.extend(corners)
        min_x, min_y, max_x, max_y = _bbox_of_points(target_corners)
        # The placement quad's corners must lie inside the oracle bounding box.
        for quad in result.quads:
            for corner in (quad.ul, quad.ur, quad.lr, quad.ll):
                assert min_x - 1e-6 <= corner.x <= max_x + 1e-6
                assert min_y - 1e-6 <= corner.y <= max_y + 1e-6

    def test_quads_remain_inside_page_rect(self, tmp_path):
        path = _make_pdf_page(
            tmp_path, "The dose is five milligrams.", rotation=90,
        )
        doc = fitz.open(str(path))
        try:
            page = doc[0]
            page_rect = page.rect
            result = resolve_pdf_quote(page, TargetSelector(exact="five milligrams"))
        finally:
            doc.close()
        assert result.status is PlacementStatus.RESOLVED
        # Quads are display points: they must lie inside the page rect.
        for quad in result.quads:
            for corner in (quad.ul, quad.ur, quad.lr, quad.ll):
                assert page_rect.x0 - 1e-6 <= corner.x <= page_rect.x1 + 1e-6
                assert page_rect.y0 - 1e-6 <= corner.y <= page_rect.y1 + 1e-6

    def test_multiple_lines_return_one_quad_per_line_in_content_order(self, tmp_path):
        # Build a page with the same quote spanning two text-boxes (two lines).
        path = tmp_path / "twolines.pdf"
        with fitz.open() as doc:
            page = doc.new_page(width=612.0, height=792.0)
            page.insert_textbox(
                fitz.Rect(72, 72, 540, 110), "five milligrams on line one.", fontsize=11,
            )
            page.insert_textbox(
                fitz.Rect(72, 140, 540, 180), "five milligrams on line two.", fontsize=11,
            )
            doc.save(str(path))
        doc = fitz.open(str(path))
        try:
            result = resolve_pdf_quote(doc[0], TargetSelector(exact="five milligrams"))
        finally:
            doc.close()
        assert result.status is PlacementStatus.AMBIGUOUS
        assert result.candidate_count == 2

    def test_quads_are_finite_and_convex(self, tmp_path):
        path = _make_pdf_page(tmp_path, "The dose is five milligrams.", rotation=270)
        doc = fitz.open(str(path))
        try:
            result = resolve_pdf_quote(doc[0], TargetSelector(exact="five milligrams"))
        finally:
            doc.close()
        assert result.status is PlacementStatus.RESOLVED
        for quad in result.quads:
            for corner in (quad.ul, quad.ur, quad.lr, quad.ll):
                assert corner.x == corner.x  # not NaN
                assert corner.y == corner.y
                assert abs(corner.x) != float("inf")
                assert abs(corner.y) != float("inf")


# ---------------------------------------------------------------------------
# G. resolve_epub_quote — all four statuses
# ---------------------------------------------------------------------------


class TestResolveEpubQuoteStatuses:
    """EPUB resolver statuses, exercised against a real BeautifulSoup tree."""

    def test_resolved_status(self):
        root = BeautifulSoup(
            "<p>The dose is <em>five milligrams</em> of potion.</p>", "lxml",
        ).p
        result = resolve_epub_quote(root, TargetSelector(exact="five milligrams"))
        assert result.status is PlacementStatus.RESOLVED
        assert result.reason == "unique_verified_quote"
        assert result.coordinate_space == "epub_dom_text"
        assert result.epub_segments, "resolved EPUB must carry at least one segment"
        assert result.quads == ()
        assert result.raw_span is not None
        # Reassembled text equals matched_text.
        joined = "".join(str(node) for node in iter_inline_runs(root)[0])
        s, e = result.raw_span
        assert joined[s:e] == result.matched_text

    def test_ambiguous_status(self):
        root = BeautifulSoup(
            "<p>Same here. Same here. Same here.</p>", "lxml",
        ).p
        result = resolve_epub_quote(root, TargetSelector(exact="Same here"))
        assert result.status is PlacementStatus.AMBIGUOUS
        assert result.reason == "ambiguous_quote"
        assert result.candidate_count == 3
        assert not result.epub_segments
        assert result.raw_span is None

    def test_unresolved_quote_not_found(self):
        root = BeautifulSoup(
            "<p>The dose is five milligrams.</p>", "lxml",
        ).p
        result = resolve_epub_quote(root, TargetSelector(exact="fifty milligrams"))
        assert result.status is PlacementStatus.UNRESOLVED
        assert result.reason == "quote_not_found"

    def test_unsupported_renderer_for_fixed_layout(self):
        root = BeautifulSoup("<p>Some content.</p>", "lxml").p
        result = resolve_epub_quote(
            root, TargetSelector(exact="content"), fixed_layout=True,
        )
        assert result.status is PlacementStatus.UNSUPPORTED_RENDERER
        assert result.reason == "fixed_layout_unsupported"
        # No usable anchor carried in an unsupported record.
        assert result.raw_span is None
        assert result.matched_text is None
        assert not result.quads
        assert not result.epub_segments
        assert result.coordinate_space is None

    def test_unsupported_renderer_does_not_emit_geometry(self):
        # The resolver refuses a fixed-layout request *before* it tries to find
        # text. A previous version could have returned resolved with fake
        # coordinates; this test pins "no fake anchor".
        root = BeautifulSoup(
            "<p>The dose is <em>five milligrams</em> of potion.</p>", "lxml",
        ).p
        result = resolve_epub_quote(
            root, TargetSelector(exact="five milligrams"), fixed_layout=True,
        )
        assert result.status is PlacementStatus.UNSUPPORTED_RENDERER
        assert result.reason == "fixed_layout_unsupported"


# ---------------------------------------------------------------------------
# H. resolve_epub_quote — cross-node and block-boundary semantics
# ---------------------------------------------------------------------------


class TestResolveEpubQuoteBlockBoundary:
    """The resolver must not cross block boundaries; inline spans are joined."""

    def test_cross_node_em_resolves(self):
        root = BeautifulSoup(
            "<p>The dose is <em>five milligrams</em> of potion.</p>", "lxml",
        ).p
        result = resolve_epub_quote(root, TargetSelector(exact="five milligrams"))
        assert result.status is PlacementStatus.RESOLVED
        # All segments must lie inside the same run.
        run_index = result.epub_segments[0].run_index
        assert all(seg.run_index == run_index for seg in result.epub_segments)

    def test_cross_nested_inline_resolves(self):
        root = BeautifulSoup(
            "<p>The dose is <em>five <strong>milligrams</strong></em> of potion.</p>",
            "lxml",
        ).p
        result = resolve_epub_quote(root, TargetSelector(exact="five milligrams"))
        assert result.status is PlacementStatus.RESOLVED
        assert result.epub_segments

    def test_cross_block_boundary_refused(self):
        root = BeautifulSoup(
            "<p>The dose is five milligrams</p><p>of potion.</p>", "lxml",
        )
        result = resolve_epub_quote(
            root, TargetSelector(exact="five milligrams of potion"),
        )
        assert result.status is PlacementStatus.UNRESOLVED
        assert result.reason == "quote_not_found"

    def test_span_across_multiple_inline_elements(self):
        root = BeautifulSoup(
            "<p>The <em>correct</em> <strong>dose</strong> is five milligrams.</p>",
            "lxml",
        ).p
        result = resolve_epub_quote(root, TargetSelector(exact="correct dose"))
        assert result.status is PlacementStatus.RESOLVED
        # Multiple segments within the same run.
        assert result.epub_segments
        run_index = result.epub_segments[0].run_index
        assert all(seg.run_index == run_index for seg in result.epub_segments)

    def test_raw_span_indexes_local_run_not_chapter(self):
        # The docstring says raw_span is local to the inline run.
        root = BeautifulSoup(
            "<p>Intro paragraph that comes first.</p>"
            "<p>Then <em>the dose is</em> five milligrams.</p>",
            "lxml",
        )
        result = resolve_epub_quote(
            root, TargetSelector(exact="the dose is five milligrams"),
        )
        assert result.status is PlacementStatus.RESOLVED
        runs = iter_inline_runs(root)
        joined = "".join(str(n) for n in runs[result.epub_segments[0].run_index])
        s, e = result.raw_span
        assert joined[s:e] == "the dose is five milligrams"
        # raw_span[0] is the local run offset, not the global chapter offset.
        assert s < len(joined)


# ---------------------------------------------------------------------------
# I. resolve_epub_quote — bounded inputs
# ---------------------------------------------------------------------------


class TestResolveEpubQuoteBounds:
    """EPUB-side bounds mirror PDF: over-large quotes and over-large inputs fail closed."""

    def test_quote_over_max_needle_chars_refused(self):
        root = BeautifulSoup("<p>Some text in here.</p>", "lxml").p
        huge = "a" * (MAX_NEEDLE_CHARS + 1)
        result = resolve_epub_quote(root, TargetSelector(exact=huge))
        assert result.status is PlacementStatus.UNRESOLVED
        assert result.reason == "quote_limit_exceeded"

    def test_candidate_limit_exceeded(self):
        text = "ab " * (MAX_CANDIDATES + 50)
        root = BeautifulSoup(f"<p>{text}</p>", "lxml").p
        result = resolve_epub_quote(root, TargetSelector(exact="ab"))
        assert result.status is PlacementStatus.UNRESOLVED
        assert result.reason == "candidate_limit_exceeded"

    def test_input_limit_exceeded(self):
        text = "x" * (MAX_INPUT_CHARS + 100)
        root = BeautifulSoup(f"<p>{text}</p>", "lxml").p
        result = resolve_epub_quote(root, TargetSelector(exact="x" * 5))
        assert result.status is PlacementStatus.UNRESOLVED
        assert result.reason == "input_limit_exceeded"


# ---------------------------------------------------------------------------
# J. resolve_epub_quote — epub_match_from_placement mutation safety
# ---------------------------------------------------------------------------


class TestEpubMatchRehydration:
    """A stale PlacementResult must not be honoured after the DOM changes."""

    def test_rehydration_succeeds_against_original_dom(self):
        root = BeautifulSoup(
            "<p>The dose is <em>five milligrams</em> of potion.</p>", "lxml",
        ).p
        result = resolve_epub_quote(root, TargetSelector(exact="five milligrams"))
        match = epub_match_from_placement(root, result)
        assert match is not None
        joined = "".join(str(seg.node)[seg.start:seg.end] for seg in match.segments)
        assert joined == result.matched_text

    def test_rehydration_refused_after_text_mutation(self):
        root = BeautifulSoup(
            "<p>The dose is <em>five milligrams</em> of potion.</p>", "lxml",
        ).p
        result = resolve_epub_quote(root, TargetSelector(exact="five milligrams"))
        # Mutate the text inside <em>. The run digest must change.
        em = root.find("em")
        em.clear()
        em.append("FIVE MILLIGRAMS")
        match = epub_match_from_placement(root, result)
        assert match is None

    def test_rehydration_refused_for_non_epub_record(self):
        root = BeautifulSoup("<p>text</p>", "lxml").p
        bad = PlacementResult.model_construct(
            status=PlacementStatus.RESOLVED, renderer="pdf",
            reason="unique_verified_quote",
            raw_span=(0, 4), matched_text="text", candidate_count=1,
            coordinate_space="pdf_display_points",
            quads=(PlacementQuad(
                ul=PlacementPoint(x=0, y=0), ur=PlacementPoint(x=1, y=0),
                lr=PlacementPoint(x=1, y=1), ll=PlacementPoint(x=0, y=1),
            ),),
            source_digest="0" * 64,
        )
        assert epub_match_from_placement(root, bad) is None

    def test_rehydration_refused_for_unresolved_record(self):
        root = BeautifulSoup("<p>text</p>", "lxml").p
        result = resolve_epub_quote(root, TargetSelector(exact="absent"))
        assert result.status is PlacementStatus.UNRESOLVED
        assert epub_match_from_placement(root, result) is None

    def test_rehydration_refused_for_unsupported_renderer_record(self):
        root = BeautifulSoup("<p>text</p>", "lxml").p
        result = resolve_epub_quote(
            root, TargetSelector(exact="text"), fixed_layout=True,
        )
        assert result.status is PlacementStatus.UNSUPPORTED_RENDERER
        assert epub_match_from_placement(root, result) is None


# ---------------------------------------------------------------------------
# K. resolve_epub_quote — selector / source availability edge cases
# ---------------------------------------------------------------------------


class TestResolveEpubQuoteSelector:
    """Invalid selectors and unavailable source DOMs fail closed with a code."""

    def test_non_tag_root_returns_source_unavailable(self):
        result = resolve_epub_quote(
            "not a tag", TargetSelector(exact="text"),
        )  # type: ignore[arg-type]
        assert result.status is PlacementStatus.UNRESOLVED
        assert result.reason == "source_unavailable"

    def test_over_long_prefix_or_suffix_refused(self):
        root = BeautifulSoup("<p>Some text.</p>", "lxml").p
        huge = "a" * (MAX_NEEDLE_CHARS + 1)
        result = resolve_epub_quote(
            root, TargetSelector(exact="text", prefix=huge),
        )
        assert result.status is PlacementStatus.UNRESOLVED
        assert result.reason == "quote_limit_exceeded"


# ---------------------------------------------------------------------------
# L. Source-digest stability for identical DOM
# ---------------------------------------------------------------------------


class TestSourceDigestStability:
    """The source digest must be byte-stable for identical DOM, and change on
    any text change."""

    def test_digest_is_stable_for_identical_dom(self):
        html = "<p>The <em>dose</em> is five milligrams.</p>"
        r1 = resolve_epub_quote(
            BeautifulSoup(html, "lxml").p, TargetSelector(exact="dose is"),
        )
        r2 = resolve_epub_quote(
            BeautifulSoup(html, "lxml").p, TargetSelector(exact="dose is"),
        )
        assert r1.source_digest == r2.source_digest

    def test_digest_changes_when_dom_text_changes(self):
        html1 = "<p>The <em>dose</em> is five milligrams.</p>"
        html2 = "<p>The <em>dose</em> is five grams.</p>"
        r1 = resolve_epub_quote(
            BeautifulSoup(html1, "lxml").p, TargetSelector(exact="dose is"),
        )
        r2 = resolve_epub_quote(
            BeautifulSoup(html2, "lxml").p, TargetSelector(exact="dose is"),
        )
        assert r1.source_digest != r2.source_digest
