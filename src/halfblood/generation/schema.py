"""Canonical provider schema for generated page annotations.

The provider schema is derived from the Pydantic models below.  Provider-side
validation is only an aid; callers must still validate returned payloads with
``RecordAnnotations`` before using them.
"""

from __future__ import annotations

import hashlib
from copy import deepcopy
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from halfblood.models.documents import canonical_json
from halfblood.models.legacy import AnnotationType


class AnnotationDraft(BaseModel):
    """The provider-facing subset of an annotation for one source unit."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    target_text: str = Field(
        min_length=1,
        description="The exact, verbatim passage from the page text that this annotation is attached to.",
    )
    annotation_type: AnnotationType = Field(
        description="The category of this annotation."
    )
    content: str = Field(
        min_length=1,
        description="The handwritten margin note itself, written in character.",
    )
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        default=0.8,
        description="How certain the annotator is about this note, from 0.0 to 1.0.",
    )
    position: Literal["margin_right", "margin_left", "inline", "between_lines"] = (
        Field(
            default="margin_right",
            description=(
                "Where the note is placed relative to the text: ``margin_right`` "
                "puts it in the right margin, ``margin_left`` in the left margin, "
                "``inline`` within the paragraph, and ``between_lines`` in the "
                "space between existing lines."
            ),
        )
    )


class RecordAnnotations(BaseModel):
    """Structured output returned by the annotation-generation provider."""

    model_config = ConfigDict(extra="forbid", title="record_annotations")

    annotations: list[AnnotationDraft]


def _inline_references(value: Any, definitions: dict[str, Any]) -> Any:
    """Recursively replace local JSON Schema references with their definitions."""

    if isinstance(value, list):
        return [_inline_references(item, definitions) for item in value]
    if not isinstance(value, dict):
        return value

    if "$ref" in value:
        reference = value["$ref"]
        prefix = "#/$defs/"
        if not isinstance(reference, str) or not reference.startswith(prefix):
            raise ValueError(f"Unsupported schema reference: {reference!r}")
        name = reference.removeprefix(prefix)
        if name not in definitions:
            raise ValueError(f"Unknown schema definition: {name!r}")
        # A reference may have sibling constraints. Keep them if Pydantic emits any.
        resolved = _inline_references(deepcopy(definitions[name]), definitions)
        siblings = {key: item for key, item in value.items() if key != "$ref"}
        if siblings:
            if not isinstance(resolved, dict):
                raise ValueError("Cannot merge reference siblings into a non-object schema")
            resolved.update(_inline_references(siblings, definitions))
        return resolved

    return {key: _inline_references(item, definitions) for key, item in value.items()}


def _normalize_objects(value: Any) -> None:
    """Make object wire contracts strict and require every advertised field."""

    if isinstance(value, list):
        for item in value:
            _normalize_objects(item)
        return
    if not isinstance(value, dict):
        return

    properties = value.get("properties")
    if isinstance(properties, dict):
        value["required"] = list(properties)
        for property_schema in properties.values():
            if isinstance(property_schema, dict):
                property_schema.pop("default", None)

    if value.get("type") == "object" or isinstance(properties, dict):
        value["additionalProperties"] = False

    for child in value.values():
        _normalize_objects(child)


def generate_annotation_schema() -> dict[str, Any]:
    """Return the normalized Draft 2020-12 provider schema for annotations."""

    raw_schema = RecordAnnotations.model_json_schema()
    definitions = raw_schema.pop("$defs", {})
    if not isinstance(definitions, dict):
        raise ValueError("Pydantic emitted non-mapping $defs")

    schema = _inline_references(raw_schema, definitions)
    if not isinstance(schema, dict):  # Defensive: the root model is an object schema.
        raise ValueError("Pydantic emitted a non-mapping root schema")
    _normalize_objects(schema)
    schema["title"] = "record_annotations"
    return schema


def schema_hash(schema: dict[str, Any]) -> str:
    """Return the SHA-256 digest of P1-T1's canonical JSON serialization."""

    return hashlib.sha256(canonical_json(schema).encode("utf-8")).hexdigest()
