"""Backward-compatible exports for the original annotation models."""

from halfblood.models.legacy import (
    AnnotatedPage,
    Annotation,
    AnnotationPlan,
    AnnotationType,
)

__all__ = ["Annotation", "AnnotatedPage", "AnnotationPlan", "AnnotationType"]
