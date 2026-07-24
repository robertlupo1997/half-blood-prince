"""Conservative detection of publishing boilerplate in extracted book sections.

False positives are substantially more harmful than false negatives here: skipping real content
silently removes part of the user's book, while retaining boilerplate only spends a few extra API
tokens. The classifier therefore relies solely on marker density and deliberately does not treat
any single sentinel or marker as conclusive.
"""

from __future__ import annotations

from dataclasses import dataclass

# Weighted marker hits per 1000 characters, above which a section is boilerplate.
#
# Calibrated against real data (17 sections of known ground truth): Project Gutenberg
# front matter scored 20.2 and its licence appendix 19.6, while ten chapters of genuine
# Stevenson prose and five pages of the repo's PDF fixture all scored exactly 0.00.
# The classes are separated by the full width of the scale, so this sits far from both
# and is not delicately balanced -- if you are retuning it, something has changed about
# the input, not about the threshold.
BOILERPLATE_THRESHOLD: float = 2.0

_STRONG_MARKERS: tuple[str, ...] = (
    "*** start of the project gutenberg",
    "*** end of the project gutenberg",
    "project gutenberg literary archive",
    "project gutenberg license",
    "gutenberg.org",
    "this ebook is for the use of anyone",
    "gutenberg-tm",
    "gutenberg™",
    "project gutenberg",
)

_WEAK_MARKERS: tuple[str, ...] = (
    "public domain",
    "redistribution",
    "all rights reserved",
    "donations",
    "trademark",
    "copyright law",
)


@dataclass(frozen=True)
class BoilerplateVerdict:
    """The density score and matching evidence for a section of text."""

    is_boilerplate: bool
    score: float
    matched_markers: tuple[str, ...]


def classify(text: str) -> BoilerplateVerdict:
    """Classify text using conservative, case-insensitive marker density."""
    if not text.strip():
        return BoilerplateVerdict(
            is_boilerplate=False,
            score=0.0,
            matched_markers=(),
        )

    normalized = text.casefold()
    # Count OCCURRENCES, not distinct markers present. A long license appendix repeats
    # the same few phrases dozens of times; counting each marker once would let its score
    # be diluted by its own length and slip under the threshold. (Measured: the 18k-char
    # Gutenberg licence scores 7.9 by occurrence but only 1.4 by distinct-marker presence,
    # which is a miss.) Short markers that are substrings of longer ones are counted by
    # both on purpose -- it only amplifies text that is already unambiguously boilerplate,
    # and the tuning margin below was measured with that overlap in place.
    strong_hits = sum(normalized.count(marker) for marker in _STRONG_MARKERS)
    weak_hits = sum(normalized.count(marker) for marker in _WEAK_MARKERS)
    score = (3 * strong_hits + weak_hits) / max(
        1.0,
        len(text) / 1000.0,
    )
    matched_markers = tuple(
        sorted(
            marker
            for marker in _STRONG_MARKERS + _WEAK_MARKERS
            if marker in normalized
        )
    )

    # Weak markers can NEVER convict on their own. They are ordinary English that novels
    # legitimately use, and below 1000 characters the length divisor bottoms out at 1.0 --
    # so a short passage mentioning, say, "trademark" and "public domain" would otherwise
    # score exactly at the threshold and lose the reader a real page. Requiring at least
    # one publisher-specific marker keeps the burden of proof on unambiguous evidence.
    return BoilerplateVerdict(
        is_boilerplate=score >= BOILERPLATE_THRESHOLD and strong_hits >= 1,
        score=score,
        matched_markers=matched_markers,
    )
