"""Document text normalization and matching contracts."""

from halfblood.documents.matching import (
    MAX_CANDIDATES,
    MAX_INPUT_CHARS,
    MAX_NEEDLE_CHARS,
    NormalizedText,
    RawSpan,
    normalize,
)

__all__ = [
    "MAX_CANDIDATES",
    "MAX_INPUT_CHARS",
    "MAX_NEEDLE_CHARS",
    "NormalizedText",
    "RawSpan",
    "normalize",
]
