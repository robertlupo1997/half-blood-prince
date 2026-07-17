"""Document text normalization and matching contracts."""

from halfblood.documents.epub import (
    CrossNodeMatch,
    CrossNodeSegment,
    iter_inline_runs,
    locate_across_nodes,
    selector_for,
)
from halfblood.documents.matching import (
    AMBIGUITY_MARGIN,
    MAX_CANDIDATES,
    MAX_INPUT_CHARS,
    MAX_NEEDLE_CHARS,
    MIN_CONTEXT_SCORE,
    AmbiguousResult,
    MatchResult,
    NoMatchResult,
    NormalizedText,
    RawSpan,
    ScoredCandidate,
    ScoringOutcome,
    normalize,
    score_candidates,
)
from halfblood.documents.pdf import (
    PdfAlignmentError,
    PdfAnchor,
    PdfPageIndex,
    resolve_pdf_anchor,
)

__all__ = [
    "AMBIGUITY_MARGIN",
    "MAX_CANDIDATES",
    "MAX_INPUT_CHARS",
    "MAX_NEEDLE_CHARS",
    "MIN_CONTEXT_SCORE",
    "AmbiguousResult",
    "CrossNodeMatch",
    "CrossNodeSegment",
    "MatchResult",
    "NoMatchResult",
    "NormalizedText",
    "PdfAlignmentError",
    "PdfAnchor",
    "PdfPageIndex",
    "RawSpan",
    "ScoredCandidate",
    "ScoringOutcome",
    "iter_inline_runs",
    "locate_across_nodes",
    "normalize",
    "resolve_pdf_anchor",
    "score_candidates",
    "selector_for",
]
