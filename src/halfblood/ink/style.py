"""Validated, immutable style profiles for generated ink."""

from __future__ import annotations

import hashlib
import json
import re
from importlib.resources import files
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from halfblood.models.documents import UnsupportedSchemaVersionError, canonical_json

_STYLE_MAJOR = "1"
_HEX_COLOR_RE = re.compile(r"\A#[0-9a-fA-F]{6}\Z")


class _StyleBase(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class InkPalette(_StyleBase):
    ink_color: str
    highlight_color: str
    shadow_color: str
    base_opacity: float = Field(ge=0.0, le=1.0)

    @field_validator("ink_color", "highlight_color", "shadow_color", mode="after")
    @classmethod
    def _validate_hex_color(cls, value: str) -> str:
        if not _HEX_COLOR_RE.match(value):
            raise ValueError(f"color must be '#RRGGBB' hex, got {value!r}")
        return value


class NibProfile(_StyleBase):
    base_width: float = Field(gt=0.0)
    min_width: float = Field(gt=0.0)
    max_width: float = Field(gt=0.0)

    @model_validator(mode="after")
    def _validate_ordering(self) -> Self:
        if not (self.min_width <= self.base_width <= self.max_width):
            raise ValueError(
                f"nib widths must satisfy min_width <= base_width <= max_width, "
                f"got min={self.min_width}, base={self.base_width}, max={self.max_width}"
            )
        return self


class VariationProfile(_StyleBase):
    slant_noise: float = Field(ge=0.0, le=1.0)
    width_noise: float = Field(ge=0.0, le=1.0)


class ReadabilityProfile(_StyleBase):
    min_scale: float = Field(gt=0.0, le=1.0)


class BudgetProfile(_StyleBase):
    max_points: int = Field(gt=0)
    max_paths: int = Field(gt=0)


class InkStyleProfile(_StyleBase):
    style_version: str = "1.0"
    palette: InkPalette
    nib: NibProfile
    variation: VariationProfile
    readability: ReadabilityProfile
    budget: BudgetProfile


def load_ink_style_profile(data: dict[str, Any]) -> InkStyleProfile:
    """Load and validate an InkStyleProfile, rejecting unsupported major versions."""

    version_text = str(data.get("style_version", "1.0"))
    if version_text.split(".", maxsplit=1)[0] != _STYLE_MAJOR:
        raise UnsupportedSchemaVersionError(f"Unsupported style version: {version_text!r}")
    return InkStyleProfile.model_validate(data)


def load_builtin_style() -> InkStyleProfile:
    """Load the default built-in style from the package resource.

    Uses importlib.resources so the asset loads from an installed wheel
    without any repository path on sys.path.
    """

    resource = files("halfblood.ink") / "styles" / "default.json"
    data = json.loads(resource.read_text(encoding="utf-8"))
    return load_ink_style_profile(data)


def canonical_style_hash(profile: InkStyleProfile) -> str:
    """Return a deterministic SHA-256 hex digest of the style profile.

    Uses canonical_json (sort_keys=True) so serialization field-ordering
    does not affect the output — two profiles with identical values but
    different dict insertion orders hash identically.
    """

    payload = canonical_json(profile)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


__all__ = [
    "BudgetProfile",
    "InkPalette",
    "InkStyleProfile",
    "NibProfile",
    "ReadabilityProfile",
    "VariationProfile",
    "canonical_style_hash",
    "load_builtin_style",
    "load_ink_style_profile",
]
