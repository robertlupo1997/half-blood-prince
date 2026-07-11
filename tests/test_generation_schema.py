"""Controller-authored, test-first contract for P1-T2 (canonical provider schema).

Ground truth: docs/superpowers/specs/2026-07-11-full-project-architecture.md SS4.2-4.3;
.superpowers/sdd/p1-t2-brief.md "Pinned interface". These tests are the frozen interface
Codex builds against -- do not edit them to make an implementation pass.

Field-name decision: AnnotationDraft keeps the wire/Python field named ``position``
(NOT v2's ``requested_placement``) -- see the brief's "Pinned interface" section for
the full rationale. This preserves annotation_generator.py's existing parse path
unchanged, which the safety-net test below exercises directly.
"""

import hashlib
import json
from copy import deepcopy

import pytest
from halfblood.generation.schema import (
    AnnotationDraft,
    RecordAnnotations,
    generate_annotation_schema,
    schema_hash,
)
from pydantic import ValidationError

import halfblood.annotation_generator as ag_module
from halfblood.annotation_generator import AnnotationGenerator
from halfblood.models import AnnotationType
from halfblood.models.documents import canonical_json


def _walk(node):
    """Yield every dict found anywhere in a JSON-schema-shaped structure."""
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _walk(value)
    elif isinstance(node, list):
        for item in node:
            yield from _walk(item)


# --- 1. stable name/title -----------------------------------------------


def test_schema_has_stable_title():
    schema = generate_annotation_schema()
    assert schema["title"] == "record_annotations"


# --- 2. no $ref/$defs; additionalProperties:false recurses; all required --


def test_schema_has_no_refs_or_defs():
    schema = generate_annotation_schema()

    assert "$defs" not in schema
    for node in _walk(schema):
        assert "$ref" not in node


def test_schema_additional_properties_false_recursively():
    schema = generate_annotation_schema()

    assert schema["additionalProperties"] is False
    item_schema = schema["properties"]["annotations"]["items"]
    assert item_schema["additionalProperties"] is False


def test_schema_top_level_shape():
    schema = generate_annotation_schema()

    assert schema["type"] == "object"
    assert schema["required"] == ["annotations"]
    assert schema["properties"]["annotations"]["type"] == "array"


def test_schema_every_annotation_field_is_required():
    schema = generate_annotation_schema()
    item_schema = schema["properties"]["annotations"]["items"]

    assert set(item_schema["required"]) == {
        "target_text",
        "annotation_type",
        "content",
        "confidence",
        "position",
    }
    for prop_name in ("confidence", "position"):
        assert "default" not in item_schema["properties"][prop_name]


# --- 3. enum / bounds / minLength preserved ------------------------------


def test_schema_preserves_enum_bounds_and_min_length():
    schema = generate_annotation_schema()
    props = schema["properties"]["annotations"]["items"]["properties"]

    assert set(props["annotation_type"]["enum"]) == {t.value for t in AnnotationType}
    assert props["position"]["enum"] == [
        "margin_right",
        "margin_left",
        "inline",
        "between_lines",
    ]
    assert props["confidence"]["minimum"] == 0.0
    assert props["confidence"]["maximum"] == 1.0
    assert props["target_text"]["minLength"] == 1
    assert props["content"]["minLength"] == 1


# --- 4. server-owned fields absent ---------------------------------------


def test_schema_excludes_server_owned_fields():
    schema = generate_annotation_schema()
    item_props = set(schema["properties"]["annotations"]["items"]["properties"])

    forbidden = {
        "id", "mark_intent", "doodle_kind", "target", "source_locator",
        "unit_id", "ordinal", "page", "provenance", "style", "seed",
        "document_seed", "render_seed",
    }
    assert forbidden.isdisjoint(item_props)


# --- 5. canonical JSON + stable, repeatable, sensitive hash --------------


def test_schema_hash_reuses_p1_t1_canonical_json():
    schema = generate_annotation_schema()
    expected = hashlib.sha256(canonical_json(schema).encode("utf-8")).hexdigest()

    assert schema_hash(schema) == expected


def test_schema_hash_is_repeatable():
    schema_a = generate_annotation_schema()
    schema_b = generate_annotation_schema()

    assert schema_hash(schema_a) == schema_hash(schema_b)


def test_schema_hash_changes_when_contract_changes():
    schema = generate_annotation_schema()
    original_hash = schema_hash(schema)

    mutated = deepcopy(schema)
    mutated["properties"]["annotations"]["items"]["properties"]["target_text"][
        "minLength"
    ] = 2

    assert schema_hash(mutated) != original_hash


# --- 6. representative payloads validate/reject appropriately -----------


def test_record_annotations_accepts_a_valid_payload():
    payload = {
        "annotations": [
            {
                "target_text": "wormwood",
                "annotation_type": "correction",
                "content": "Crush it.",
                "confidence": 0.9,
                "position": "margin_right",
            }
        ]
    }
    parsed = RecordAnnotations.model_validate(payload)
    assert len(parsed.annotations) == 1
    assert parsed.annotations[0].target_text == "wormwood"


@pytest.mark.parametrize(
    "override",
    [
        {"target_text": ""},
        {"content": ""},
        {"confidence": 1.5},
        {"confidence": -0.1},
        {"annotation_type": "not_a_real_type"},
        {"extra_unexpected_field": "surprise"},
    ],
)
def test_annotation_draft_rejects_invalid_payloads(override):
    base = {
        "target_text": "wormwood",
        "annotation_type": "correction",
        "content": "Crush it.",
        "confidence": 0.9,
        "position": "margin_right",
    }
    base.update(override)

    with pytest.raises(ValidationError):
        AnnotationDraft.model_validate(base)


# --- 7. single source of truth; forced-tool path unaffected --------------


def test_legacy_tool_schema_is_generated_not_hand_maintained():
    assert ag_module._ANNOTATION_TOOL_SCHEMA["input_schema"] == generate_annotation_schema()


def test_parse_response_still_reads_position_key_unchanged():
    """Safety net for the field-name decision above: the wire key stays
    ``position``, so the existing parse path (annotation_generator.py:526)
    needs no change. A non-default value must survive parsing, not be
    silently reset to the "margin_right" fallback."""
    gen = AnnotationGenerator(api_key="sk-ant-test-fake-key-not-real")
    raw = json.dumps(
        {
            "annotations": [
                {
                    "target_text": "hello",
                    "annotation_type": "warning",
                    "content": "careful",
                    "confidence": 0.9,
                    "position": "between_lines",
                }
            ]
        }
    )

    result = gen._parse_response(raw, page_number=1, page_text="hello world")

    assert len(result) == 1
    assert result[0].position == "between_lines"
