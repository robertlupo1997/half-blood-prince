"""Versioned semantic document plans and deterministic v1 migration."""

from __future__ import annotations

import hashlib
import json
import uuid
from copy import deepcopy
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from halfblood.models import legacy
from halfblood.models.annotations import Annotation, MarkIntent, TargetSelector

_ID_NAMESPACE = uuid.UUID("2a95ef2e-b21d-5a18-a0d8-3d8dca23a465")
_CONTEXT_LENGTH = 32

_MARK_INTENTS: dict[legacy.AnnotationType, MarkIntent] = {
    legacy.AnnotationType.CORRECTION: MarkIntent.UNDERLINE,
    legacy.AnnotationType.IMPROVEMENT: MarkIntent.UNDERLINE,
    legacy.AnnotationType.SHORTCUT: MarkIntent.UNDERLINE,
    legacy.AnnotationType.INSIGHT: MarkIntent.CIRCLE,
    legacy.AnnotationType.INVENTION: MarkIntent.CIRCLE,
    legacy.AnnotationType.DOODLE_NOTE: MarkIntent.CIRCLE,
    legacy.AnnotationType.WARNING: MarkIntent.HIGHLIGHT,
    legacy.AnnotationType.CROSSED_OUT: MarkIntent.STRIKE,
}


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SourceInfo(_StrictModel):
    fingerprint: str
    media_type: str
    unit_count: int = Field(ge=0)


class GenerationProvenance(_StrictModel):
    provider: str | None = None
    base_url_origin: str | None = None
    model: str | None = None
    prompt_version: str | None = None
    schema_hash: str | None = None
    structured_output_mode: str | None = None
    timestamp: str | None = None
    usage: dict[str, Any] | None = None


class Unit(_StrictModel):
    unit_id: str
    ordinal: int
    label: str
    original_text: str
    source_locator: str
    status: str = "ok"
    annotations: list[Annotation] = Field(default_factory=list)


class CompatibilityEnvelope(_StrictModel):
    """Unknown same-major fields retained explicitly by their object path."""

    source_schema_version: str
    unknown_fields: dict[str, dict[str, Any]] = Field(default_factory=dict)


class AnnotationPlan(_StrictModel):
    schema_version: str = "2.0"
    id: str
    title: str
    persona: str
    source: SourceInfo
    generation: GenerationProvenance
    document_seed: int = Field(ge=0, le=2**64 - 1)
    units: list[Unit] = Field(default_factory=list)
    compatibility: CompatibilityEnvelope | None = None


class UnsupportedSchemaVersionError(ValueError):
    """Raised when a saved annotation plan uses an unsupported major version."""


def canonical_json(value: BaseModel | dict[str, Any]) -> str:
    """Serialize a model or mapping deterministically for hashing and persistence."""

    payload = value.model_dump(mode="json") if isinstance(value, BaseModel) else value
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _selector(exact: str, original_text: str) -> TargetSelector:
    start = original_text.find(exact)
    if start < 0:
        return TargetSelector(exact=exact)

    end = start + len(exact)
    prefix = original_text[max(0, start - _CONTEXT_LENGTH) : start] or None
    suffix = original_text[end : end + _CONTEXT_LENGTH] or None
    return TargetSelector(
        exact=exact,
        prefix=prefix,
        suffix=suffix,
        start_offset=start,
        end_offset=end,
    )


def migrate_v1_to_v2(data: dict[str, Any]) -> AnnotationPlan:
    """Purely migrate a validated legacy plan to the renderer-neutral v2 contract."""

    v1 = legacy.AnnotationPlan.model_validate(data)
    v1_json = canonical_json(v1)
    fingerprint = _sha256(v1_json)
    plan_id = str(uuid.uuid5(_ID_NAMESPACE, f"plan:{fingerprint}"))
    seed_digest = hashlib.sha256(f"document-seed:{fingerprint}".encode()).digest()
    document_seed = int.from_bytes(seed_digest[:8], byteorder="big", signed=False)

    units: list[Unit] = []
    for page_index, page in enumerate(v1.pages):
        page_json = canonical_json(page)
        unit_id = str(
            uuid.uuid5(
                _ID_NAMESPACE,
                f"unit:{fingerprint}:{page_index}:{page.page_number}:{page_json}",
            )
        )
        annotations: list[Annotation] = []
        for annotation_index, annotation in enumerate(page.annotations):
            annotation_json = canonical_json(annotation)
            annotation_id = str(
                uuid.uuid5(
                    _ID_NAMESPACE,
                    f"annotation:{unit_id}:{annotation_index}:{annotation_json}",
                )
            )
            annotations.append(
                Annotation(
                    id=annotation_id,
                    target=_selector(annotation.target_text, page.original_text),
                    annotation_type=annotation.annotation_type,
                    content=annotation.content,
                    confidence=annotation.confidence,
                    requested_placement=annotation.position,
                    mark_intent=_MARK_INTENTS[annotation.annotation_type],
                )
            )

        units.append(
            Unit(
                unit_id=unit_id,
                ordinal=page.page_number,
                label=f"Page {page.page_number}",
                original_text=page.original_text,
                source_locator=f"page:{page.page_number}",
                annotations=annotations,
            )
        )

    return AnnotationPlan(
        id=plan_id,
        title=v1.title,
        persona=v1.prince_persona,
        source=SourceInfo(
            fingerprint=fingerprint,
            media_type="application/vnd.halfblood.annotation-plan.v1+json",
            unit_count=len(units),
        ),
        generation=GenerationProvenance(),
        document_seed=document_seed,
        units=units,
    )


def _take_unknown_fields(
    value: dict[str, Any], known: set[str], path: str, captured: dict[str, dict[str, Any]]
) -> None:
    unknown = {key: value.pop(key) for key in list(value) if key not in known}
    if unknown:
        captured[path] = unknown


def _capture_newer_minor_fields(data: dict[str, Any]) -> dict[str, Any]:
    clean = deepcopy(data)
    captured: dict[str, dict[str, Any]] = {}
    _take_unknown_fields(clean, set(AnnotationPlan.model_fields), "$", captured)

    source = clean.get("source")
    if isinstance(source, dict):
        _take_unknown_fields(source, set(SourceInfo.model_fields), "$.source", captured)
    generation = clean.get("generation")
    if isinstance(generation, dict):
        _take_unknown_fields(
            generation, set(GenerationProvenance.model_fields), "$.generation", captured
        )
    units = clean.get("units")
    if isinstance(units, list):
        for unit_index, unit in enumerate(units):
            if not isinstance(unit, dict):
                continue
            unit_path = f"$.units[{unit_index}]"
            _take_unknown_fields(unit, set(Unit.model_fields), unit_path, captured)
            annotations = unit.get("annotations")
            if not isinstance(annotations, list):
                continue
            for annotation_index, annotation in enumerate(annotations):
                if not isinstance(annotation, dict):
                    continue
                annotation_path = f"{unit_path}.annotations[{annotation_index}]"
                _take_unknown_fields(
                    annotation, set(Annotation.model_fields), annotation_path, captured
                )
                target = annotation.get("target")
                if isinstance(target, dict):
                    _take_unknown_fields(
                        target,
                        set(TargetSelector.model_fields),
                        f"{annotation_path}.target",
                        captured,
                    )

    if captured:
        existing = clean.get("compatibility")
        if isinstance(existing, dict):
            previous = existing.get("unknown_fields")
            if isinstance(previous, dict):
                captured = {**previous, **captured}
        clean["compatibility"] = {
            "source_schema_version": str(data["schema_version"]),
            "unknown_fields": captured,
        }
    return clean


def load_annotation_plan(data: dict[str, Any]) -> AnnotationPlan:
    """Load v1 or v2 plan data, rejecting unsupported major schema versions."""

    version = data.get("schema_version")
    if version is None:
        return migrate_v1_to_v2(data)

    version_text = str(version)
    if version_text.split(".", maxsplit=1)[0] != "2":
        raise UnsupportedSchemaVersionError(
            f"Unsupported annotation plan schema version: {version_text}"
        )

    if version_text == "2.0":
        return AnnotationPlan.model_validate(data)
    return AnnotationPlan.model_validate(_capture_newer_minor_fields(data))


__all__ = [
    "AnnotationPlan",
    "CompatibilityEnvelope",
    "GenerationProvenance",
    "SourceInfo",
    "Unit",
    "UnsupportedSchemaVersionError",
    "canonical_json",
    "load_annotation_plan",
    "migrate_v1_to_v2",
]
