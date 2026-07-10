"""Pydantic models for structured annotation data."""

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


class AnnotationType(StrEnum):
    CORRECTION = "correction"       # "No, no, no — you crush it, don't cut it"
    IMPROVEMENT = "improvement"     # "Add a clockwise stir after step 3"
    INSIGHT = "insight"             # "This is why most get it wrong"
    INVENTION = "invention"         # "Try Sectumsempra instead"
    WARNING = "warning"             # "DO NOT attempt without a bezoar nearby"
    SHORTCUT = "shortcut"           # "Skip steps 4-6. Just add the root directly."
    CROSSED_OUT = "crossed_out"     # Strike-through with replacement text
    DOODLE_NOTE = "doodle_note"     # Small marginal commentary


class Annotation(BaseModel):
    """A single margin annotation in the style of the Half-Blood Prince."""

    page: int = Field(description="Page number this annotation belongs to")
    target_text: str = Field(description="The specific text passage being annotated")
    annotation_type: AnnotationType
    content: str = Field(description="The handwritten margin note text")
    confidence: float = Field(
        ge=0.0, le=1.0, default=0.8,
        description="How confident the annotator is (affects ink boldness)"
    )
    position: Literal["margin_right", "margin_left", "inline", "between_lines"] = Field(
        default="margin_right",
        description="Where to place the annotation relative to the target text"
    )


class AnnotatedPage(BaseModel):
    """All annotations for a single page."""

    page_number: int
    original_text: str
    annotations: list[Annotation] = []


class AnnotationPlan(BaseModel):
    """Complete annotation plan for a document."""

    title: str
    prince_persona: str = Field(
        default="A brilliant, sardonic expert who has mastered this subject "
                "and can't help scrawling corrections and improvements. "
                "Terse. Impatient with mediocrity. Occasionally shows "
                "flashes of dark humor."
    )
    pages: list[AnnotatedPage] = []

    @property
    def total_annotations(self) -> int:
        return sum(len(p.annotations) for p in self.pages)
