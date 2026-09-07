"""Serializable outcomes for strict whole-quote placement.

These records contain no PyMuPDF or BeautifulSoup objects. A resolved EPUB
record describes DOM text, not reader coordinates. PDF quads use displayed
page points after page rotation, with explicitly named corners.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class PlacementStatus(StrEnum):
    """The four outcomes of evidence-to-anchor resolution."""

    RESOLVED = "resolved"
    AMBIGUOUS = "ambiguous"
    UNRESOLVED = "unresolved"
    UNSUPPORTED_RENDERER = "unsupported_renderer"


class _PlacementModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class PlacementPoint(_PlacementModel):
    """One finite point in the record's coordinate space."""

    x: float = Field(allow_inf_nan=False)
    y: float = Field(allow_inf_nan=False)


class PlacementQuad(_PlacementModel):
    """One line's PDF display-space bounds, with named corners."""

    ul: PlacementPoint
    ur: PlacementPoint
    lr: PlacementPoint
    ll: PlacementPoint


class EpubSegmentRef(_PlacementModel):
    """Raw half-open node offsets in the original inline-run traversal.

    Indices are zero-based. The reference is valid only against the original
    DOM text structure, checked by ``epub_match_from_placement``.
    """

    run_index: int = Field(ge=0)
    node_index: int = Field(ge=0)
    start: int = Field(ge=0)
    end: int = Field(ge=0)

    @model_validator(mode="after")
    def _nonempty_range(self) -> Self:
        if self.end <= self.start:
            raise ValueError("segment range must be nonempty")
        return self


PlacementReason = Literal[
    "unique_verified_quote", "quote_not_found", "ambiguous_quote",
    "selector_hints_mismatch", "input_limit_exceeded", "quote_limit_exceeded",
    "candidate_limit_exceeded", "geometry_unavailable", "source_unavailable",
    "fixed_layout_unsupported", "invalid_selector", "out_of_range_page",
]


class PlacementResult(_PlacementModel):
    """Auditable text evidence plus optional verified renderer geometry.

    ``raw_span`` indexes ``page.get_text("text")`` for PDF. For EPUB it indexes
    the concatenated original text nodes in the selected inline run, not the
    whole chapter. ``candidate_count`` counts complete normalized quotation
    matches *before* supplied context/offset hints are verified.

    The normalizer folds curly quotes and en/em dashes, collapses Unicode
    whitespace, and applies NFC. It does not fold case, drop punctuation, repair
    spelling, or shorten the quotation. Hints are constraints, not scores.
    """

    schema_version: Literal["1.0"] = "1.0"
    status: PlacementStatus
    renderer: Literal["pdf", "epub"]
    reason: PlacementReason
    normalization: Literal["nfc-whitespace-typographic-v1"] = "nfc-whitespace-typographic-v1"
    raw_span: tuple[int, int] | None = None
    matched_text: str | None = None
    candidate_count: int = Field(default=0, ge=0)
    coordinate_space: Literal["pdf_display_points", "epub_dom_text"] | None = None
    quads: tuple[PlacementQuad, ...] = ()
    epub_segments: tuple[EpubSegmentRef, ...] = ()
    source_digest: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _validate_outcome(self) -> Self:
        if self.status is not PlacementStatus.RESOLVED:
            if (self.raw_span is not None or self.matched_text is not None
                    or self.coordinate_space is not None or self.quads
                    or self.epub_segments or self.source_digest is not None):
                raise ValueError("refusals must not contain a usable anchor")
            if self.reason == "unique_verified_quote":
                raise ValueError("refusal reason contradicts status")
            if self.status is PlacementStatus.AMBIGUOUS:
                if self.reason != "ambiguous_quote" or self.candidate_count < 2:
                    raise ValueError("ambiguous requires at least two candidates")
            elif self.reason == "ambiguous_quote":
                raise ValueError("ambiguous_quote requires ambiguous status")
            if (self.status is PlacementStatus.UNSUPPORTED_RENDERER) != (
                self.reason == "fixed_layout_unsupported"
            ):
                raise ValueError("unsupported renderer reason contradicts status")
            return self
        if (self.reason != "unique_verified_quote" or self.raw_span is None
                or not self.matched_text or not self.source_digest or self.candidate_count < 1):
            raise ValueError("resolved requires verified text evidence")
        start, end = self.raw_span
        if start < 0 or end <= start or end - start != len(self.matched_text):
            raise ValueError("raw_span must cover matched_text exactly")
        if self.renderer == "pdf":
            if self.coordinate_space != "pdf_display_points" or not self.quads or self.epub_segments:
                raise ValueError("resolved PDF requires only PDF geometry")
        elif self.coordinate_space != "epub_dom_text" or not self.epub_segments or self.quads:
            raise ValueError("resolved EPUB requires text references, never coordinates")
        return self


__all__ = [
    "EpubSegmentRef",
    "PlacementPoint",
    "PlacementQuad",
    "PlacementResult",
    "PlacementStatus",
]
