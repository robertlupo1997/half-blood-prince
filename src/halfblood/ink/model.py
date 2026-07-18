"""Immutable, versioned, surface-neutral ink scene contracts."""

from __future__ import annotations

import hashlib
from enum import Enum
from typing import Annotated, Any, Literal, Self, Union, cast

from pydantic import BaseModel, ConfigDict, Field, model_validator

from halfblood.models.documents import UnsupportedSchemaVersionError, canonical_json
from halfblood.models.rendering import DegradationFlag

_INK_SCENE_MAJOR = "1"  # Current major version; load_ink_scene rejects others.
_BOUNDS_TOLERANCE = 1e-9  # Local units; within-tolerance boundary overshoot is accepted.
_HASH_DECIMALS = 6  # Rounding decimals for scene_structural_hash.


class _InkBase(BaseModel):
    """Frozen, strict base for all ink model types.

    ``frozen=True`` makes every instance immutable, ``extra="forbid"`` rejects
    unknown fields, and ``allow_inf_nan=False`` rejects non-finite float values.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)


class LocalPoint(_InkBase):
    """A point in normalized local ink coordinates (not PDF points / CSS pixels)."""

    x: float
    y: float


class LocalRect(_InkBase):
    """Axis-aligned bounding box in normalized local coordinates."""

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


class MoveTo(_InkBase):
    kind: Literal["M"] = "M"
    x: float
    y: float


class LineTo(_InkBase):
    kind: Literal["L"] = "L"
    x: float
    y: float


class CubicTo(_InkBase):
    """Cubic Bézier to endpoint (x, y) with two control points."""

    kind: Literal["C"] = "C"
    x1: float
    y1: float
    x2: float
    y2: float
    x: float
    y: float


Command = Annotated[
    Union[MoveTo, LineTo, CubicTo],  # noqa: UP007  # Specified discriminated union.
    Field(discriminator="kind"),
]


class PressureSample(_InkBase):
    """Raw digitizer sample for pen replay and width synthesis."""

    x: float
    y: float
    pressure: float = Field(ge=0.0, le=1.0)
    time: float = Field(ge=0.0)
    pen_down: bool


class WidthSample(_InkBase):
    """One (arc-length-fraction, relative-width) pair in a width profile."""

    position: float = Field(ge=0.0, le=1.0)
    width: float = Field(gt=0.0)


class StrokeStyle(_InkBase):
    color: str
    base_width: float = Field(gt=0.0)
    opacity: float = Field(ge=0.0, le=1.0)
    cap: Literal["round", "butt", "square"] = "round"
    join: Literal["round", "bevel", "miter"] = "round"


class AffineTransform(_InkBase):
    """A 2D affine transform represented by ``(a, b, c, d, e, f)``.

    It maps ``(x, y)`` to ``(a*x + c*y + e, b*x + d*y + f)``.
    """

    matrix: tuple[float, float, float, float, float, float] = (
        1.0,
        0.0,
        0.0,
        1.0,
        0.0,
        0.0,
    )


class StrokePath(_InkBase):
    """One styled drawing path in normalized local coordinates."""

    commands: tuple[Command, ...]
    samples: tuple[PressureSample, ...] = ()
    stroke: StrokeStyle
    width_profile: tuple[WidthSample, ...] = ()
    transform: AffineTransform = Field(default_factory=AffineTransform)
    z_index: int = 0
    accessibility_label: str = ""

    @model_validator(mode="after")
    def _validate_commands_structure(self) -> Self:
        if not self.commands:
            raise ValueError("commands must be non-empty")
        if not isinstance(self.commands[0], MoveTo):
            raise ValueError("commands must begin with MoveTo")
        if not any(isinstance(command, (LineTo, CubicTo)) for command in self.commands):
            raise ValueError("commands must contain at least one LineTo or CubicTo")
        return self

    @model_validator(mode="after")
    def _validate_width_profile_monotone(self) -> Self:
        positions = tuple(sample.position for sample in self.width_profile)
        if any(
            current < previous for previous, current in zip(positions, positions[1:], strict=False)
        ):
            raise ValueError("width_profile positions must be non-decreasing")
        return self


class InkRole(str, Enum):  # noqa: UP042  # Preserve the pinned string-enum contract.
    """Mark roles produced by InkComposer (architecture §5.2)."""

    HANDWRITING = "handwriting"
    UNDERLINE = "underline"
    CIRCLE = "circle"
    STRIKE = "strike"
    CARET = "caret"
    CONNECTOR = "connector"
    DOODLE = "doodle"


class InkGroup(_InkBase):
    group_id: str
    role: InkRole
    paths: tuple[StrokePath, ...]


class InkScene(_InkBase):
    """Versioned, surface-neutral, immutable scene of grouped stroke paths (§5.2)."""

    scene_version: str = "1.0"
    ink_algorithm_version: str
    annotation_id: str
    seed: int = Field(ge=0, le=2**64 - 1)
    bounds: LocalRect
    degradation_flags: tuple[DegradationFlag, ...] = ()
    groups: tuple[InkGroup, ...] = ()

    @model_validator(mode="after")
    def _validate_no_duplicate_group_ids(self) -> Self:
        group_ids = [group.group_id for group in self.groups]
        if len(set(group_ids)) != len(group_ids):
            raise ValueError("InkScene has duplicate group_ids")
        return self

    @model_validator(mode="after")
    def _validate_bounds_containment(self) -> Self:
        for group in self.groups:
            for path in group.paths:
                for command in path.commands:
                    if (
                        command.x < self.bounds.x0 - _BOUNDS_TOLERANCE
                        or command.x > self.bounds.x1 + _BOUNDS_TOLERANCE
                        or command.y < self.bounds.y0 - _BOUNDS_TOLERANCE
                        or command.y > self.bounds.y1 + _BOUNDS_TOLERANCE
                    ):
                        raise ValueError("InkScene command endpoint lies outside bounds")
        return self


def scene_structural_hash(scene: InkScene) -> str:
    """Return a deterministic SHA-256 hash of all rounded command geometry."""

    commands: list[dict[str, str | float]] = []
    for group in scene.groups:
        for path in group.paths:
            for command in path.commands:
                if isinstance(command, CubicTo):
                    commands.append(
                        {
                            "k": "C",
                            "x1": round(command.x1, _HASH_DECIMALS),
                            "y1": round(command.y1, _HASH_DECIMALS),
                            "x2": round(command.x2, _HASH_DECIMALS),
                            "y2": round(command.y2, _HASH_DECIMALS),
                            "x": round(command.x, _HASH_DECIMALS),
                            "y": round(command.y, _HASH_DECIMALS),
                        }
                    )
                else:
                    commands.append(
                        {
                            "k": command.kind,
                            "x": round(command.x, _HASH_DECIMALS),
                            "y": round(command.y, _HASH_DECIMALS),
                        }
                    )

    payload = canonical_json(cast(Any, commands))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def load_ink_scene(data: dict[str, Any]) -> InkScene:
    """Load an InkScene, rejecting unsupported major scene versions."""

    version_text = str(data.get("scene_version", "1.0"))
    if version_text.split(".", maxsplit=1)[0] != _INK_SCENE_MAJOR:
        raise UnsupportedSchemaVersionError(f"Unsupported InkScene version: {version_text}")
    return InkScene.model_validate(data)


__all__ = [
    "AffineTransform",
    "Command",
    "CubicTo",
    "InkGroup",
    "InkRole",
    "InkScene",
    "LineTo",
    "LocalPoint",
    "LocalRect",
    "MoveTo",
    "PressureSample",
    "StrokePath",
    "StrokeStyle",
    "WidthSample",
    "load_ink_scene",
    "scene_structural_hash",
]
