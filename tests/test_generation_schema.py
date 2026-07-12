"""Controller-authored, test-first contract for P1-T2 (canonical provider schema).

Ground truth: docs/superpowers/specs/2026-07-11-full-project-architecture.md SS4.2-4.3;
.superpowers/sdd/p1-t2-brief.md "Pinned interface". These tests are the frozen interface
Codex builds against -- do not edit them to make an implementation pass.

Field-name decision: AnnotationDraft keeps the wire/Python field named ``position``
(NOT v2's ``requested_placement``) -- see the brief's "Pinned interface" section for
the full rationale.
"""

import hashlib
from copy import deepcopy

import pytest
from pydantic import ValidationError

from halfblood.generation.schema import (
    AnnotationDraft,
    RecordAnnotations,
    generate_annotation_schema,
    schema_hash,
)
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


def test_schema_annotations_array_explains_reading_order():
    """The old hand-written schema told the model annotations should be "in
    reading order" -- real guidance (order is preserved through to rendering
    and the running-notes continuity signal unless a page's annotation count
    exceeds the confidence-sorted cap). Nothing else in the prompt says this."""
    schema = generate_annotation_schema()
    description = schema["properties"]["annotations"].get("description", "")

    assert "reading order" in description.lower()


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


def test_schema_preserves_per_field_llm_guidance():
    """The old hand-written schema explained each field to the model in prose
    (e.g. what each ``position`` value means -- guidance that exists nowhere
    else in the system prompt). The Pydantic-generated schema must not lose
    this: every draft field needs a non-empty ``description``."""
    schema = generate_annotation_schema()
    props = schema["properties"]["annotations"]["items"]["properties"]

    for field_name in (
        "target_text", "annotation_type", "content", "confidence", "position",
    ):
        description = props[field_name].get("description", "")
        assert isinstance(description, str) and description.strip(), (
            f"{field_name!r} has no LLM-facing description"
        )


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
#
# NOTE: two tests previously lived here, both exercising annotation_generator
# internals that P1-T5 deleted -- ``_ANNOTATION_TOOL_SCHEMA`` (a module
# constant) and ``_parse_response()`` (a method). Both were removed when
# AnnotationGenerator's SDK call was replaced by the injectable
# AnthropicProvider seam; the schema/tool-shape logic they guarded now lives
# in ``AnthropicProvider._build_body``/``_parse_success``. Their invariants
# are preserved by tests/test_anthropic_provider.py:
#   - test_legacy_tool_schema_is_generated_not_hand_maintained's concern
#     (the wire tool schema IS generate_annotation_schema(), not a hand-
#     maintained copy) -> test_request_url_headers_and_payload_shape.
#   - test_parse_response_still_reads_position_key_unchanged's concern (a
#     non-default ``position`` value survives parsing unchanged) ->
#     test_non_default_position_value_survives_parsing.
