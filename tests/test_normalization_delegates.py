"""P2-T1 — the PDF/EPUB `_normalize_search_text` helpers must stay byte-identical.

These are REGRESSION GUARDS, not red-first tests: they pin the CURRENT behavior of the two
divergent normalization copies, captured from the pre-refactor code (Session 18). They pass
BEFORE Codex builds and must keep passing AFTER the two copies become thin delegates over the
shared `halfblood.documents.matching` core.

"Existing Phase 0 smart-punctuation and target tests remain green" (P2-T1 acceptance) means
exactly this: the delegate output must not drift for any input the current suite exercises.
The two goldens differ ONLY at the middle-dot row — that fold is a PDF text-extraction repair
and must stay PDF-scoped, never migrating into the shared core (where it would silently loosen
EPUB matching on legitimate `·` content).

This file imports only the processors, never `halfblood.documents.matching`, so it runs
independently of the not-yet-built module.
"""

from __future__ import annotations

import pytest

from halfblood.document_processor import DocumentProcessor
from halfblood.epub_processor import EpubProcessor

# Inputs both delegates normalize identically (no middle-dot present).
_SHARED_GOLDENS = [
    ("plain text", "plain text"),
    ("  leading and trailing  ", "leading and trailing"),
    ("curly ‘quotes’ and “doubles”", "curly 'quotes' and \"doubles\""),
    ("en–dash and em—dash", "en-dash and em-dash"),
    ("tabs\tand\r\nCRLF\nnewlines", "tabs and CRLF newlines"),
    ("multiple     spaces", "multiple spaces"),
]


@pytest.mark.parametrize(("raw", "expected"), _SHARED_GOLDENS)
def test_pdf_delegate_is_byte_identical(raw: str, expected: str) -> None:
    assert DocumentProcessor._normalize_search_text(raw) == expected


@pytest.mark.parametrize(("raw", "expected"), _SHARED_GOLDENS)
def test_epub_delegate_is_byte_identical(raw: str, expected: str) -> None:
    assert EpubProcessor._normalize_search_text(raw) == expected


def test_pdf_delegate_keeps_its_middle_dot_repair() -> None:
    """The PDF delegate keeps its extraction-artifact repair verbatim: `·` between word chars
    becomes an apostrophe, otherwise a hyphen.
    """
    assert (
        DocumentProcessor._normalize_search_text("middot·here and o·clock")
        == "middot'here and o'clock"
    )


def test_epub_delegate_does_not_gain_middle_dot_folding() -> None:
    """EPUB has no middle-dot repair today; delegating to the shared core must not add one."""
    assert (
        EpubProcessor._normalize_search_text("middot·here and o·clock")
        == "middot·here and o·clock"
    )
