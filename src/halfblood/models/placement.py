"""Serializable outcomes for strict whole-quote placement.

These records contain no PyMuPDF or BeautifulSoup objects. A resolved EPUB
record describes DOM text, not reader coordinates. PDF quads use displayed
page points after page rotation, with explicitly named corners.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


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

    status: PlacementStatus
    renderer: Literal["pdf", "epub"]
    reason: str
    normalization: Literal["nfc-whitespace-typographic-v1"] = "nfc-whitespace-typographic-v1"
    raw_span: tuple[int, int] | None = None
    matched_text: str | None = None
    candidate_count: int = Field(default=0, ge=0)
    coordinate_space: Literal["pdf_display_points", "epub_dom_text"] | None = None
    quads: tuple[PlacementQuad, ...] = ()
    epub_segments: tuple[EpubSegmentRef, ...] = ()
    source_digest: str | None = None


__all__ = [
    "EpubSegmentRef",
    "PlacementPoint",
    "PlacementQuad",
    "PlacementResult",
    "PlacementStatus",
]
