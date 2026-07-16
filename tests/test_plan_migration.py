"""Controller-authored, test-first contract for P1-T1 (semantic plan v2 + v1->v2 migration).

Ground truth: docs/superpowers/specs/2026-07-11-full-project-architecture.md SS3.2, 4.2,
6.1, 6.2; .superpowers/sdd/p1-t1-brief.md "Pinned interface". These tests are the frozen
interface Codex builds against -- do not edit them to make an implementation pass.
"""

import json
import uuid
from copy import deepcopy

import pytest
from pydantic import ValidationError

# --- v1 (must keep working, byte-for-byte, unchanged) ----------------------
from halfblood.models import (
    AnnotatedPage,
    Annotation,
    AnnotationPlan,
    AnnotationType,
)

# --- v2 (new, this task) ----------------------------------------------------
from halfblood.models.annotations import (
    Annotation as AnnotationV2,
)
from halfblood.models.annotations import (
    MarkIntent,
    TargetSelector,
)
from halfblood.models.documents import (
    AnnotationPlan as AnnotationPlanV2,
)
from halfblood.models.documents import (
    GenerationProvenance,
    SourceInfo,
    Unit,
    UnsupportedSchemaVersionError,
    load_annotation_plan,
    migrate_v1_to_v2,
)

TYPE_TO_MARK_INTENT = {
    "correction": "underline",
    "improvement": "underline",
    "shortcut": "underline",
    "insight": "circle",
    "invention": "circle",
    "doodle_note": "circle",
    "warning": "highlight",
    "crossed_out": "strike",
}

ALL_POSITIONS = ["margin_right", "margin_left", "inline", "between_lines"]

FIXTURE_DEFAULTS = {
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

FIXTURE_ALL_TYPES_POSITIONS = {
    "title": "Every Type and Position",
    "prince_persona": "A brilliant, sardonic expert.",
    "pages": [
        {
            "page_number": 1,
            "original_text": "A page with one annotation of every kind.",
            "annotations": [
                {
                    "page": 1,
                    "target_text": f"passage {i}",
                    "annotation_type": t.value,
                    "content": f"note for {t.value}",
                    "confidence": 0.5,
                    "position": ALL_POSITIONS[i % len(ALL_POSITIONS)],
                }
                for i, t in enumerate(AnnotationType)
            ],
        }
    ],
}

FIXTURE_EMPTY_PAGES = {
    "title": "Nothing Here Yet",
    "prince_persona": "A brilliant, sardonic expert.",
    "pages": [],
}

FIXTURE_MISMATCHED_PAGE_NUMBERS = {
    "title": "Mismatched Nesting",
    "prince_persona": "A brilliant, sardonic expert.",
    "pages": [
        {
            "page_number": 5,
            "original_text": "The outer page says five.",
            "annotations": [
                {
                    "page": 7,
                    "target_text": "outer page",
                    "annotation_type": "warning",
                    "content": "The nested page lies. Trust the caller.",
                    "confidence": 0.9,
                    "position": "inline",
                }
            ],
        }
    ],
}


# --- 9. v1 compatibility imports still construct/serialize as expected -----


def test_v1_compat_imports_still_construct_and_validate():
    page = AnnotatedPage(
        page_number=1,
        original_text="text",
        annotations=[
            Annotation(
                page=1,
                target_text="text",
                annotation_type=AnnotationType.CORRECTION,
                content="fix it",
            )
        ],
    )
    plan = AnnotationPlan(title="T", pages=[page])

    assert plan.pages[0].annotations[0].position == "margin_right"
    assert plan.pages[0].annotations[0].confidence == 0.8
    assert plan.total_annotations == 1

    with pytest.raises(ValidationError):
        Annotation(
            page=1,
            target_text="x",
            annotation_type=AnnotationType.CORRECTION,
            content="y",
            confidence=1.5,
        )


# --- 1. v1 fixtures migrate with no semantic loss ---------------------------


def test_migrate_defaults_preserves_title_persona_and_content():
    v2 = migrate_v1_to_v2(deepcopy(FIXTURE_DEFAULTS))

    assert isinstance(v2, AnnotationPlanV2)
    assert v2.schema_version == "2.0"
    assert v2.title == FIXTURE_DEFAULTS["title"]
    assert v2.persona == FIXTURE_DEFAULTS["prince_persona"]
    assert len(v2.units) == 1

    unit = v2.units[0]
    assert unit.original_text == FIXTURE_DEFAULTS["pages"][0]["original_text"]
    assert len(unit.annotations) == 1

    ann = unit.annotations[0]
    src_ann = FIXTURE_DEFAULTS["pages"][0]["annotations"][0]
    assert ann.content == src_ann["content"]
    assert ann.confidence == src_ann["confidence"]
    assert ann.target.exact == src_ann["target_text"]
    assert ann.annotation_type == AnnotationType.CORRECTION


def test_migrate_empty_pages():
    v2 = migrate_v1_to_v2(deepcopy(FIXTURE_EMPTY_PAGES))

    assert v2.schema_version == "2.0"
    assert v2.units == []
    assert v2.source.unit_count == 0


# --- 3. position -> requested_placement, and the pinned mark_intent table --


def test_migrate_all_types_maps_position_and_mark_intent():
    v2 = migrate_v1_to_v2(deepcopy(FIXTURE_ALL_TYPES_POSITIONS))
    unit = v2.units[0]
    src_annotations = FIXTURE_ALL_TYPES_POSITIONS["pages"][0]["annotations"]

    assert len(unit.annotations) == len(src_annotations)

    for ann, src in zip(unit.annotations, src_annotations, strict=True):
        assert ann.requested_placement == src["position"]
        expected_mark = TYPE_TO_MARK_INTENT[src["annotation_type"]]
        assert ann.mark_intent == MarkIntent(expected_mark)


# --- 4. provenance placeholders + explicit locator/unit ownership ----------
# caller page numbers win over nested ambiguity


def test_migrate_mismatched_page_numbers_caller_wins():
    v2 = migrate_v1_to_v2(deepcopy(FIXTURE_MISMATCHED_PAGE_NUMBERS))
    unit = v2.units[0]

    assert unit.ordinal == 5
    assert unit.annotations[0].content == "The nested page lies. Trust the caller."


def test_migrated_plan_has_provenance_placeholders_and_locators():
    v2 = migrate_v1_to_v2(deepcopy(FIXTURE_DEFAULTS))

    assert isinstance(v2.generation, GenerationProvenance)
    assert isinstance(v2.source, SourceInfo)
    assert v2.source.unit_count == len(v2.units)
    assert v2.source.fingerprint
    assert v2.source.media_type

    for unit in v2.units:
        assert isinstance(unit.source_locator, str) and unit.source_locator
        assert isinstance(unit.unit_id, str) and unit.unit_id


# --- 2. deterministic IDs + document_seed -----------------------------------


def test_migration_is_deterministic_across_runs():
    v2_a = migrate_v1_to_v2(deepcopy(FIXTURE_ALL_TYPES_POSITIONS))
    v2_b = migrate_v1_to_v2(deepcopy(FIXTURE_ALL_TYPES_POSITIONS))

    assert v2_a.id == v2_b.id
    assert v2_a.document_seed == v2_b.document_seed
    assert len(v2_a.units) == len(v2_b.units)
    for unit_a, unit_b in zip(v2_a.units, v2_b.units, strict=True):
        assert unit_a.unit_id == unit_b.unit_id
        for ann_a, ann_b in zip(unit_a.annotations, unit_b.annotations, strict=True):
            assert ann_a.id == ann_b.id


def test_migration_of_different_inputs_does_not_collide():
    v2_defaults = migrate_v1_to_v2(deepcopy(FIXTURE_DEFAULTS))
    v2_empty = migrate_v1_to_v2(deepcopy(FIXTURE_EMPTY_PAGES))

    assert v2_defaults.id != v2_empty.id
    assert v2_defaults.document_seed != v2_empty.document_seed


def test_ids_are_valid_uuid_strings():
    v2 = migrate_v1_to_v2(deepcopy(FIXTURE_ALL_TYPES_POSITIONS))

    uuid.UUID(v2.id)
    for unit in v2.units:
        for ann in unit.annotations:
            uuid.UUID(ann.id)


def test_document_seed_is_uint64_range():
    v2 = migrate_v1_to_v2(deepcopy(FIXTURE_DEFAULTS))

    assert isinstance(v2.document_seed, int)
    assert 0 <= v2.document_seed <= 2**64 - 1


# --- 5. renderer-neutrality: no color/font/coordinate/render-seed field ----


def test_v2_annotation_is_renderer_neutral():
    forbidden_fields = {
        "color", "colour", "stroke_color", "ink", "font", "font_size", "fontsize",
        "render_seed", "seed", "x", "y", "rect", "bbox", "coordinates", "svg",
        "rotation", "angle", "opacity",
    }
    actual_fields = set(AnnotationV2.model_fields.keys())

    assert forbidden_fields.isdisjoint(actual_fields)


# --- 6. Field(default_factory=list) isolation -------------------------------


def test_unit_annotations_default_is_isolated_per_instance():
    unit_a = Unit(
        unit_id="u-1",
        ordinal=1,
        label="Page 1",
        original_text="a",
        source_locator="loc-1",
    )
    unit_b = Unit(
        unit_id="u-2",
        ordinal=2,
        label="Page 2",
        original_text="b",
        source_locator="loc-2",
    )

    unit_a.annotations.append(
        AnnotationV2(
            id=str(uuid.uuid4()),
            target=TargetSelector(exact="x"),
            annotation_type=AnnotationType.CORRECTION,
            content="c",
            confidence=0.5,
            requested_placement="margin_right",
            mark_intent=MarkIntent.UNDERLINE,
        )
    )

    assert unit_b.annotations == []


def test_plan_units_default_is_isolated_per_instance():
    common = {
        "id": str(uuid.uuid4()),
        "title": "T",
        "persona": "P",
        "source": SourceInfo(fingerprint="f", media_type="m", unit_count=0),
        "generation": GenerationProvenance(),
        "document_seed": 1,
    }
    plan_a = AnnotationPlanV2(**common)
    plan_b = AnnotationPlanV2(**common)

    plan_a.units.append(
        Unit(
            unit_id="u-1",
            ordinal=1,
            label="Page 1",
            original_text="a",
            source_locator="loc-1",
        )
    )

    assert plan_b.units == []


# --- 7. v2 JSON round-trips byte-semantically -------------------------------


def test_v2_json_round_trips_byte_semantically():
    v2 = migrate_v1_to_v2(deepcopy(FIXTURE_ALL_TYPES_POSITIONS))

    json_1 = v2.model_dump_json()
    reloaded = AnnotationPlanV2.model_validate_json(json_1)
    json_2 = reloaded.model_dump_json()

    assert json_1 == json_2


# --- 8. load_annotation_plan version dispatch -------------------------------


def test_load_annotation_plan_migrates_v1_when_schema_version_absent():
    via_loader = load_annotation_plan(deepcopy(FIXTURE_DEFAULTS))
    via_direct = migrate_v1_to_v2(deepcopy(FIXTURE_DEFAULTS))

    assert via_loader.model_dump_json() == via_direct.model_dump_json()


def test_load_annotation_plan_round_trips_v2():
    original = migrate_v1_to_v2(deepcopy(FIXTURE_DEFAULTS))
    data = json.loads(original.model_dump_json())

    loaded = load_annotation_plan(data)

    assert loaded.model_dump_json() == original.model_dump_json()


def test_load_annotation_plan_rejects_unknown_future_major_version():
    original = migrate_v1_to_v2(deepcopy(FIXTURE_DEFAULTS))
    data = json.loads(original.model_dump_json())
    data["schema_version"] = "99.0"

    with pytest.raises(UnsupportedSchemaVersionError):
        load_annotation_plan(data)


# --- P2-T2 (re-scoped): selector additions are read-time views only ---------
# The P2-T2 normalization accessors and the start<=end validator must NOT change
# migration output. These guards pin that: byte-frozen serialization, no
# normalized_* leakage into any migrated selector, ordered offsets, and
# exact-only selectors for targets absent from their source text (no invented
# context). Ground truth: architecture SS5.5/6.1; p2-t2-brief.md.

# Captured byte-for-byte from pre-P2-T2 HEAD (27c70e2). Any drift is a break.
GOLDEN_V2_DEFAULTS_JSON = (
    '{"schema_version":"2.0","id":"4be707ca-6459-587a-8385-ca31d024a9c7",'
    '"title":"Advanced Potion-Making","persona":"A brilliant, sardonic expert.",'
    '"source":{"fingerprint":"df6819cd285f96de4f2c32983fc787218d1a2df254925b982e2e7daa2a274e8c",'
    '"media_type":"application/vnd.halfblood.annotation-plan.v1+json","unit_count":1},'
    '"generation":{"provider":null,"base_url_origin":null,"model":null,'
    '"prompt_version":null,"schema_hash":null,"structured_output_mode":null,'
    '"timestamp":null,"usage":null},"document_seed":3477603537352674097,'
    '"units":[{"unit_id":"a5708c57-10a5-58bd-8a83-b118ebcea250","ordinal":1,'
    '"label":"Page 1","original_text":"Add the wormwood slowly, stirring twice.",'
    '"source_locator":"page:1","status":"ok","annotations":[{'
    '"id":"6ad8c798-3e6e-5bb7-ba9a-30c4da27a9bb","target":{"exact":"wormwood slowly",'
    '"prefix":"Add the ","suffix":", stirring twice.","start_offset":8,"end_offset":23},'
    '"annotation_type":"correction","content":"No -- crush it first, fool.",'
    '"confidence":0.8,"requested_placement":"margin_right","mark_intent":"underline",'
    '"doodle_kind":null}]}],"compatibility":null}'
)

FIXTURE_ABSENT_TARGET = {
    "title": "Absent Target",
    "prince_persona": "A brilliant, sardonic expert.",
    "pages": [
        {
            "page_number": 1,
            "original_text": "Totally unrelated page text.",
            "annotations": [
                {
                    "page": 1,
                    "target_text": "not present here",
                    "annotation_type": "insight",
                    "content": "hmm",
                    "confidence": 0.5,
                    "position": "inline",
                }
            ],
        }
    ],
}

_SELECTOR_FIELDS = {"exact", "prefix", "suffix", "start_offset", "end_offset"}


def test_migration_serialization_is_byte_frozen():
    produced = migrate_v1_to_v2(deepcopy(FIXTURE_DEFAULTS)).model_dump_json()
    assert produced == GOLDEN_V2_DEFAULTS_JSON


def test_migrated_selectors_expose_no_normalized_keys_and_order_offsets():
    v2 = migrate_v1_to_v2(deepcopy(FIXTURE_ALL_TYPES_POSITIONS))
    payload = json.loads(v2.model_dump_json())

    for unit in payload["units"]:
        for annotation in unit["annotations"]:
            target = annotation["target"]
            assert set(target).issubset(_SELECTOR_FIELDS)
            for leaked in ("normalized_exact", "normalized_prefix", "normalized_suffix"):
                assert leaked not in target
            start, end = target.get("start_offset"), target.get("end_offset")
            if start is not None and end is not None:
                assert start <= end


def test_migration_of_absent_target_yields_exact_only_selector():
    v2 = migrate_v1_to_v2(deepcopy(FIXTURE_ABSENT_TARGET))
    selector = v2.units[0].annotations[0].target

    assert selector.exact == "not present here"
    assert selector.prefix is None
    assert selector.suffix is None
    assert selector.start_offset is None
    assert selector.end_offset is None
