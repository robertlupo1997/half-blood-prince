"""Document text normalization and matching contracts."""

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

__all__ = [
    "AMBIGUITY_MARGIN",
    "MAX_CANDIDATES",
    "MAX_INPUT_CHARS",
    "MAX_NEEDLE_CHARS",
    "MIN_CONTEXT_SCORE",
    "AmbiguousResult",
    "MatchResult",
    "NoMatchResult",
    "NormalizedText",
    "RawSpan",
    "ScoredCandidate",
    "ScoringOutcome",
    "normalize",
    "score_candidates",
]
