"""Renderer-independent v2 annotation models."""

from enum import Enum
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from halfblood.documents.matching import normalize
from halfblood.models.legacy import AnnotationType

Placement = Literal["margin_right", "margin_left", "inline", "between_lines"]


class MarkIntent(str, Enum):  # noqa: UP042  # Keep the enum behavior aligned with v1.
    """Semantic mark requested for an annotation target."""

    UNDERLINE = "underline"
    CIRCLE = "circle"
    STRIKE = "strike"
    HIGHLIGHT = "highlight"
    CARET = "caret"
    NONE = "none"


class TargetSelector(BaseModel):
    """A text quote selector with optional local context and offsets."""

    model_config = ConfigDict(extra="forbid")

    exact: str = Field(min_length=1)
    prefix: str | None = None
    suffix: str | None = None
    start_offset: int | None = Field(default=None, ge=0)
    end_offset: int | None = Field(default=None, ge=0)

    @field_validator("exact", mode="before")
    @classmethod
    def _strip_exact(cls, value: object) -> object:
        """Normalize the quote without altering whitespace-significant context."""

        return value.strip() if isinstance(value, str) else value

    @model_validator(mode="after")
    def _validate_offset_order(self) -> Self:
        """Require a nondecreasing offset range when both bounds are present."""
        if (
            self.start_offset is not None
            and self.end_offset is not None
            and self.start_offset > self.end_offset
        ):
            raise ValueError("start_offset must be <= end_offset")
        return self

    @property
    def normalized_exact(self) -> str:
        """Return the surface-neutral normalized exact quote."""
        return normalize(self.exact)

    @property
    def normalized_prefix(self) -> str | None:
        """Return the surface-neutral normalized prefix, when present."""
        return normalize(self.prefix) if self.prefix is not None else None

    @property
    def normalized_suffix(self) -> str | None:
        """Return the surface-neutral normalized suffix, when present."""
        return normalize(self.suffix) if self.suffix is not None else None


class Annotation(BaseModel):
    """A renderer-neutral v2 annotation."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    id: str
    target: TargetSelector
    annotation_type: AnnotationType
    content: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)
    requested_placement: Placement
    mark_intent: MarkIntent
    doodle_kind: str | None = None


__all__ = ["Annotation", "MarkIntent", "Placement", "TargetSelector"]
