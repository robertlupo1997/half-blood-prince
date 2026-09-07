"""Versioned, renderer-neutral resolution and render-report contracts.

These models keep the portable semantic plan separate from layout and rendering state:
resolved plans reference the semantic plan by hash and annotations by their existing ids.
Geometry uses serializable surface coordinates and never renderer-specific objects.

Deferred extension points:

* EPUB ``CrossNodeSegment`` values contain live Beautiful Soup nodes and are intentionally
  excluded from this portable contract. For now, EPUB resolved anchors use ``char_range``
  with empty ``quads`` because reflow prevents exact build-time geometry. A serializable EPUB
  range representation is reserved for a future minor-version extension wired in P2-T9.
* A minor-version forward-compatibility envelope like ``AnnotationPlan``'s
  ``CompatibilityEnvelope`` is deferred. These loaders reject unknown major versions only.

Provider payloads, model metadata, usage records, and secrets have no representation here.
"""

from __future__ import annotations

import re
from enum import Enum
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from halfblood.models.annotations import Placement
from halfblood.models.documents import UnsupportedSchemaVersionError
from halfblood.models.placement import PlacementResult, PlacementStatus

_HEX64 = re.compile(r"\A[0-9a-f]{64}\Z")
_RESOLVED_PLAN_MAJOR = "1"
_RENDER_REPORT_MAJOR = "1"


def _validate_sha256_hex(value: str) -> str:
    if not _HEX64.match(value):
        raise ValueError("expected a 64-character lowercase hex sha256 digest")
    return value


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SurfacePoint(_StrictModel):
    """A point in renderer-neutral surface coordinates."""

    x: float
    y: float


class SurfaceQuad(_StrictModel):
    """A quadrilateral whose corner names correspond to ``fitz.Quad`` attributes."""

    ul: SurfacePoint
    ur: SurfacePoint
    lr: SurfacePoint
    ll: SurfacePoint


class SurfaceRect(_StrictModel):
    """An axis-aligned rectangle in renderer-neutral surface coordinates."""

    x0: float
    y0: float
    x1: float
    y1: float

    @model_validator(mode="after")
    def _validate_bounds(self) -> Self:
        if self.x0 > self.x1:
            raise ValueError("x0 must be <= x1")
        if self.y0 > self.y1:
            raise ValueError("y0 must be <= y1")
        return self


class ResolvedAnchor(_StrictModel):
    """A half-open raw source-text range and its ordered per-line geometry."""

    char_range: tuple[int, int]
    quads: tuple[SurfaceQuad, ...] = ()

    @model_validator(mode="after")
    def _validate_char_range(self) -> Self:
        start, end = self.char_range
        if start < 0:
            raise ValueError("char_range start must be >= 0")
        if start > end:
            raise ValueError("char_range start must be <= end")
        return self


class SkipReason(str, Enum):  # noqa: UP042  # Preserve the pinned string-enum contract.
    """Finite reasons why an attempted annotation produced no ink."""

    AMBIGUOUS_TARGET = "ambiguous_target"
    MISSING_TARGET = "missing_target"
    UNSUPPORTED_RENDERER = "unsupported_renderer"
    OVERLAPPING_TARGET = "overlapping_target"
    FORBIDDEN_BOUNDARY = "forbidden_boundary"
    UNPLACEABLE = "unplaceable"
    OUT_OF_RANGE_PAGE = "out_of_range_page"
    INK_PATH_BUDGET_EXCEEDED = "ink_path_budget_exceeded"
    INK_GEOMETRY_INVALID = "ink_geometry_invalid"


class AnchorWarningCode(str, Enum):  # noqa: UP042  # Preserve the pinned string-enum contract.
    """Finite non-fatal anchor and placement warning codes."""

    SIDE_SWITCHED = "side_switched"
    SHIFTED = "shifted"
    SCALE_REDUCED = "scale_reduced"
    CONNECTOR_OMITTED = "connector_omitted"


class DegradationFlag(str, Enum):  # noqa: UP042  # Preserve the pinned string-enum contract.
    """Finite renderer degradation modes defined by architecture section 5.9."""

    PROCEDURAL_STROKE_FALLBACK = "procedural_stroke_fallback"
    GLYPH_FALLBACK = "glyph_fallback"
    EPUB_NO_TARGET_GEOMETRY = "epub_no_target_geometry"
    EPUB_DENSE_NOTES_BLOCK_FALLBACK = "epub_dense_notes_block_fallback"
    SVG_UNSUPPORTED_TEXT_NOTE = "svg_unsupported_text_note"
    NOTE_SKIPPED_UNFITTABLE = "note_skipped_unfittable"
    CONNECTOR_ROUTING_FALLBACK = "connector_routing_fallback"
    CONNECTOR_OBSTACLE_CAP = "connector_obstacle_cap"
    INK_PATH_BUDGET_EXCEEDED = "ink_path_budget_exceeded"


class AnchorWarning(_StrictModel):
    """A bounded, non-fatal warning associated with resolution or layout."""

    annotation_id: str | None = None
    code: AnchorWarningCode
    detail: str = Field(default="", max_length=500)


class SkipRecord(_StrictModel):
    """A bounded explanation for an annotation that produced no ink."""

    annotation_id: str
    reason: SkipReason
    detail: str = Field(default="", max_length=500)


class OutputHash(_StrictModel):
    """The content identity of one renderer output role."""

    role: str
    sha256: str

    _validate_sha256 = field_validator("sha256")(_validate_sha256_hex)


class ResolvedAnnotation(_StrictModel):
    """One semantic annotation's resolved anchor and placement decisions."""

    annotation_id: str
    source_locator: str
    requested_placement: Placement
    resolved_placement: Placement
    anchor: ResolvedAnchor | None = None
    note_box: SurfaceRect | None = None
    note_scale: float = Field(default=1.0, gt=0)
    render_seed: int = Field(ge=0, le=2**64 - 1)
    warnings: tuple[AnchorWarning, ...] = ()


class ResolvedPlan(_StrictModel):
    """A versioned render manifest referencing, but never embedding, its semantic plan."""

    layout_version: str = "1.0"
    semantic_plan_hash: str
    source_fingerprint: str
    style_id: str
    style_version: str
    annotations: tuple[ResolvedAnnotation, ...] = ()

    _validate_semantic_plan_hash = field_validator("semantic_plan_hash")(
        _validate_sha256_hex
    )


class PlacementRecord(_StrictModel):
    """Evidence outcome before note layout, bound to one annotation and unit."""

    annotation_id: str
    source_locator: str
    result: PlacementResult


class CompositionDegradation(_StrictModel):
    """Lossless composer diagnostic, including codes not mapped to summary flags."""

    annotation_id: str
    code: str = Field(min_length=1, max_length=100)
    detail: str = Field(default="", max_length=500)


class RenderReport(_StrictModel):
    """A versioned record of render outcomes, warnings, degradations, and output identity."""

    report_version: str = "1.1"
    placements: tuple[PlacementRecord, ...] = ()
    composition_degradations: tuple[CompositionDegradation, ...] = ()
    rendered: tuple[str, ...] = ()
    skipped: tuple[SkipRecord, ...] = ()
    marks_only: tuple[str, ...] = ()
    warnings: tuple[AnchorWarning, ...] = ()
    degradation_flags: tuple[DegradationFlag, ...] = ()
    output_hashes: tuple[OutputHash, ...] = ()

    @model_validator(mode="after")
    def _validate_partition_and_normalize_degradations(self) -> Self:
        if len(set(self.rendered)) != len(self.rendered):
            raise ValueError("rendered annotation ids must be unique")

        skipped_ids = tuple(record.annotation_id for record in self.skipped)
        if len(set(skipped_ids)) != len(skipped_ids):
            raise ValueError("skipped annotation ids must be unique")
        if set(self.rendered).intersection(skipped_ids):
            raise ValueError("rendered and skipped annotation ids must be disjoint")

        if len(set(self.marks_only)) != len(self.marks_only):
            raise ValueError("marks_only annotation ids must be unique")
        if not set(self.marks_only).issubset(skipped_ids):
            raise ValueError("marks_only ids must be a subset of skipped ids")

        if self.placements:
            placement_ids = [record.annotation_id for record in self.placements]
            if len(set(placement_ids)) != len(placement_ids):
                raise ValueError("placement annotation ids must be unique")
            if set(placement_ids) != set(self.rendered).union(skipped_ids):
                raise ValueError("placements must cover rendered and skipped annotations")
            visible_ids = set(self.rendered).union(self.marks_only)
            if any(record.annotation_id in visible_ids
                   and record.result.status is not PlacementStatus.RESOLVED
                   for record in self.placements):
                raise ValueError("refused placements must not produce ink")
        self.degradation_flags = tuple(dict.fromkeys(self.degradation_flags))
        return self

    @property
    def rendered_count(self) -> int:
        return len(self.rendered)

    @property
    def skipped_count(self) -> int:
        return len(self.skipped)

    @property
    def attempted_count(self) -> int:
        """Total notes attempted: fully rendered plus skipped.

        A mark-only note (its id in ``marks_only``, always a subset of ``skipped``)
        counts as skipped here even though its target mark DID render — so
        ``attempted_count`` alone understates visible output. Pair it with
        ``len(self.marks_only)`` when reporting what actually reached the page.
        """
        return self.rendered_count + self.skipped_count


def load_resolved_plan(data: dict[str, Any]) -> ResolvedPlan:
    """Load a resolved plan while rejecting unsupported major layout versions."""

    version_text = str(data.get("layout_version", "1.0"))
    if version_text.split(".", maxsplit=1)[0] != _RESOLVED_PLAN_MAJOR:
        raise UnsupportedSchemaVersionError(
            f"Unsupported resolved plan layout version: {version_text}"
        )
    return ResolvedPlan.model_validate(data)


def load_render_report(data: dict[str, Any]) -> RenderReport:
    """Load a render report while rejecting unsupported major report versions."""

    version_text = str(data.get("report_version", "1.0"))
    if version_text.split(".", maxsplit=1)[0] != _RENDER_REPORT_MAJOR:
        raise UnsupportedSchemaVersionError(
            f"Unsupported render report version: {version_text}"
        )
    return RenderReport.model_validate(data)


__all__ = [
    "AnchorWarning",
    "AnchorWarningCode",
    "DegradationFlag",
    "OutputHash",
    "Placement",
    "RenderReport",
    "ResolvedAnchor",
    "ResolvedAnnotation",
    "ResolvedPlan",
    "SkipReason",
    "SkipRecord",
    "SurfacePoint",
    "SurfaceQuad",
    "SurfaceRect",
    "UnsupportedSchemaVersionError",
    "load_render_report",
    "load_resolved_plan",
]
