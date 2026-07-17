"""P2-T6 — ResolvedPlan contract (architecture §6.1, §3.2, §5.5).

§6.1 separates the semantic ``AnnotationPlan`` (portable, provider-derived) from a *render
manifest* that records resolution decisions:

    ResolvedPlan
      semantic_plan_hash, source_fingerprint, layout_version, style_id/version
      annotations[]: resolved source ranges/quads, note box, resolved placement,
                     render_seed, warnings

Key invariants pinned here:
- resolution does not mutate the semantic plan (the plan is referenced by hash + ids, never
  embedded);
- resolved records link to the *real* Phase-1 identifiers (``Annotation.id`` /
  ``Unit.source_locator``), not parallel substitutes;
- the requested placement is preserved verbatim even when the resolved placement differs;
- anchors carry a character range plus ordered surface geometry but no provider data;
- geometry is renderer-neutral and serializable (no ``fitz`` types);
- unknown major versions are rejected; empty plans are valid; JSON round-trips deterministically.

Contract-only: nothing renders. No network, no provider, no filesystem.
"""

from __future__ import annotations

import copy
import inspect
import json
import re
from typing import get_args

import pytest
from pydantic import ValidationError

from halfblood.models import annotations as annotations_module
from halfblood.models import rendering as rendering_module
from halfblood.models.annotations import Annotation, Placement
from halfblood.models.documents import (
    AnnotationPlan,
    UnsupportedSchemaVersionError,
    canonical_json,
    migrate_v1_to_v2,
)
from halfblood.models.rendering import (
    ResolvedAnchor,
    ResolvedAnnotation,
    ResolvedPlan,
    SurfacePoint,
    SurfaceQuad,
    SurfaceRect,
    load_resolved_plan,
)

_HASH = "c" * 64

_LEGACY_PLAN = {
    "title": "Advanced Potion-Making",
    "prince_persona": "A brilliant, sardonic expert.",
    "pages": [
        {
            "page_number": 1,
            "original_text": "Add the wormwood slowly, stirring twice.",
            "annotations": [
                {
                    "page": 1,
                    "target_text": "wormwood slowly",
                    "annotation_type": "correction",
                    "content": "No -- crush it first, fool.",
                    "confidence": 0.8,
                    "position": "margin_right",
                }
            ],
        }
    ],
}


def _real_plan() -> AnnotationPlan:
    return migrate_v1_to_v2(copy.deepcopy(_LEGACY_PLAN))


# ---------------------------------------------------------------------------
# ACCEPTANCE-CRITICAL: contracts reuse Phase-1's real Placement type, not a parallel Literal
# ---------------------------------------------------------------------------


def test_placement_alias_has_exactly_the_four_canonical_values() -> None:
    assert get_args(Placement) == (
        "margin_right",
        "margin_left",
        "inline",
        "between_lines",
    )


def test_annotation_still_uses_the_shared_placement_alias() -> None:
    """Extracting the alias must not change Annotation's accepted values (behavior-identical)."""
    assert Annotation.model_fields["requested_placement"].annotation == Placement


def test_rendering_uses_the_shared_placement_alias_not_a_parallel_literal() -> None:
    """Guard the acceptance-critical "real types, not parallel substitutes" invariant.

    A runtime identity check (``rendering.Placement is annotations.Placement``) is vacuous:
    CPython interns identical ``Literal`` aliases, so a forbidden parallel
    ``Placement = Literal[...]`` defined in rendering.py would be the *same object* and pass.
    The only way to catch the parallel-substitution antipattern in a test is to inspect the
    source — rendering.py must IMPORT the alias from annotations.py and never redefine it.
    """
    source = inspect.getsource(rendering_module)
    assert "from halfblood.models.annotations import Placement" in source, (
        "rendering.py must import the shared Placement alias from annotations.py"
    )
    assert not re.search(r"(?m)^\s*Placement\s*=", source), (
        "rendering.py must not define its own Placement alias — that is a parallel substitute"
    )
    # Belt-and-suspenders: the alias rendering.py exposes carries the canonical values/order.
    assert get_args(rendering_module.Placement) == get_args(annotations_module.Placement)


def test_resolved_annotation_placement_fields_accept_only_canonical_values() -> None:
    ann = ResolvedAnnotation(
        annotation_id="x",
        source_locator="page:1",
        requested_placement="margin_right",
        resolved_placement="inline",
        render_seed=0,
    )
    assert ann.requested_placement == "margin_right"
    with pytest.raises(ValidationError):
        ResolvedAnnotation(
            annotation_id="x",
            source_locator="page:1",
            requested_placement="not-a-side",
            resolved_placement="inline",
            render_seed=0,
        )


# ---------------------------------------------------------------------------
# requested placement is preserved when resolved placement differs
# ---------------------------------------------------------------------------


def test_requested_placement_is_unchanged_when_resolved_differs() -> None:
    ann = ResolvedAnnotation(
        annotation_id="ann-1",
        source_locator="page:1",
        requested_placement="margin_right",
        resolved_placement="margin_left",
        render_seed=7,
    )
    assert ann.requested_placement == "margin_right"
    assert ann.resolved_placement == "margin_left"


# ---------------------------------------------------------------------------
# neutral, serializable geometry (no fitz)
# ---------------------------------------------------------------------------


def _quad() -> SurfaceQuad:
    return SurfaceQuad(
        ul=SurfacePoint(x=1.0, y=2.0),
        ur=SurfacePoint(x=3.0, y=2.0),
        lr=SurfacePoint(x=3.0, y=4.0),
        ll=SurfacePoint(x=1.0, y=4.0),
    )


def test_surface_quad_round_trips_through_json() -> None:
    quad = _quad()
    restored = SurfaceQuad.model_validate(json.loads(quad.model_dump_json()))
    assert restored == quad


def test_surface_rect_requires_nondecreasing_bounds() -> None:
    SurfaceRect(x0=0.0, y0=0.0, x1=10.0, y1=10.0)
    with pytest.raises(ValidationError):
        SurfaceRect(x0=10.0, y0=0.0, x1=0.0, y1=10.0)
    with pytest.raises(ValidationError):
        SurfaceRect(x0=0.0, y0=10.0, x1=10.0, y1=0.0)


# ---------------------------------------------------------------------------
# resolved anchor: char range + ordered surface geometry, NO provider data
# ---------------------------------------------------------------------------


def test_resolved_anchor_preserves_quad_order() -> None:
    first, second = _quad(), SurfaceQuad(
        ul=SurfacePoint(x=1.0, y=6.0),
        ur=SurfacePoint(x=3.0, y=6.0),
        lr=SurfacePoint(x=3.0, y=8.0),
        ll=SurfacePoint(x=1.0, y=8.0),
    )
    anchor = ResolvedAnchor(char_range=(4, 20), quads=(first, second))
    assert anchor.quads == (first, second)


def test_resolved_anchor_empty_quads_is_valid() -> None:
    """EPUB anchors have no reliable geometry at build time — empty quads is legal."""
    anchor = ResolvedAnchor(char_range=(0, 15))
    assert anchor.quads == ()


@pytest.mark.parametrize("bad_range", [(5, 3), (-1, 4)])
def test_resolved_anchor_rejects_invalid_char_range(bad_range: tuple[int, int]) -> None:
    with pytest.raises(ValidationError):
        ResolvedAnchor(char_range=bad_range)


def test_resolved_anchor_forbids_provider_data() -> None:
    with pytest.raises(ValidationError):
        ResolvedAnchor(char_range=(0, 5), usage={"input_tokens": 10})


# ---------------------------------------------------------------------------
# resolution links real ids and does NOT mutate the semantic plan
# ---------------------------------------------------------------------------


def test_resolved_annotation_links_real_semantic_ids() -> None:
    plan = _real_plan()
    unit = plan.units[0]
    annotation = unit.annotations[0]
    resolved = ResolvedAnnotation(
        annotation_id=annotation.id,
        source_locator=unit.source_locator,
        requested_placement=annotation.requested_placement,
        resolved_placement=annotation.requested_placement,
        render_seed=plan.document_seed % (2**64),
    )
    assert resolved.annotation_id == annotation.id
    assert resolved.source_locator == unit.source_locator == "page:1"


def test_building_a_resolved_plan_does_not_mutate_the_semantic_plan() -> None:
    plan = _real_plan()
    before = plan.model_dump()
    resolved = ResolvedPlan(
        semantic_plan_hash=_HASH,
        source_fingerprint=plan.source.fingerprint,
        style_id="prince",
        style_version="1.0",
        annotations=(
            ResolvedAnnotation(
                annotation_id=plan.units[0].annotations[0].id,
                source_locator=plan.units[0].source_locator,
                requested_placement="margin_right",
                resolved_placement="margin_right",
                render_seed=0,
            ),
        ),
    )
    # The resolved plan holds only the hash + ids, never the plan object.
    assert resolved.source_fingerprint == plan.source.fingerprint
    assert plan.model_dump() == before


# ---------------------------------------------------------------------------
# hash validation, empty plan, versioning, deterministic round-trip
# ---------------------------------------------------------------------------


def test_semantic_plan_hash_must_be_64_hex() -> None:
    ResolvedPlan(
        semantic_plan_hash=_HASH,
        source_fingerprint="fp",
        style_id="prince",
        style_version="1.0",
    )
    with pytest.raises(ValidationError):
        ResolvedPlan(
            semantic_plan_hash="not-hex",
            source_fingerprint="fp",
            style_id="prince",
            style_version="1.0",
        )


def test_empty_resolved_plan_is_valid() -> None:
    plan = ResolvedPlan(
        semantic_plan_hash=_HASH,
        source_fingerprint="fp",
        style_id="prince",
        style_version="1.0",
    )
    assert plan.annotations == ()


def _sample_resolved_plan() -> ResolvedPlan:
    return ResolvedPlan(
        semantic_plan_hash=_HASH,
        source_fingerprint="fp-1",
        style_id="prince",
        style_version="1.0",
        annotations=(
            ResolvedAnnotation(
                annotation_id="ann-1",
                source_locator="page:1",
                requested_placement="inline",
                resolved_placement="margin_right",
                anchor=ResolvedAnchor(char_range=(4, 20), quads=(_quad(),)),
                note_box=SurfaceRect(x0=0.0, y0=0.0, x1=100.0, y1=40.0),
                render_seed=1729,
            ),
        ),
    )


def test_resolved_plan_round_trip_is_deterministic_and_equal() -> None:
    plan = _sample_resolved_plan()
    assert canonical_json(plan) == canonical_json(plan)
    restored = load_resolved_plan(json.loads(canonical_json(plan)))
    assert restored == plan


def test_unknown_major_layout_version_is_rejected() -> None:
    payload = json.loads(canonical_json(_sample_resolved_plan()))
    payload["layout_version"] = "2.0"
    with pytest.raises(UnsupportedSchemaVersionError):
        load_resolved_plan(payload)


def test_same_major_newer_minor_layout_version_is_accepted() -> None:
    payload = json.loads(canonical_json(_sample_resolved_plan()))
    payload["layout_version"] = "1.9"
    restored = load_resolved_plan(payload)
    assert restored.style_id == "prince"
