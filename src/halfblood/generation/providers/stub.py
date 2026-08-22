"""Deterministic offline stub provider and failure-injection wrapper.

``StubProvider`` makes the full annotate pipeline runnable without network
access or API credentials: it parses the page number and page text out of the
prompt ``AnnotationGenerator`` builds, then returns one well-formed annotation
whose target is an exact substring of that page text (so anchor resolution
succeeds against any input document).

``FailPagesProvider`` wraps any provider and raises a non-retryable
:class:`ProviderError` for selected page numbers. Together with
``--fail-pages`` this lets failure visibility (the ``<output>.report.json``
sidecar) be demonstrated deterministically end to end.
"""

from __future__ import annotations

import re
import threading

from halfblood.generation.errors import ProviderError, StructuredOutputError
from halfblood.generation.providers.base import (
    GenerationRequest,
    GenerationResult,
    GenerationUsage,
    LLMProvider,
    ProviderCapabilities,
)
from halfblood.generation.schema import AnnotationDraft, RecordAnnotations
from halfblood.models.legacy import AnnotationType

_PAGE_NUMBER_RE = re.compile(r"^PAGE NUMBER:\s*(\d+)\s*$", re.MULTILINE)
_PAGE_TEXT_MARKER = 'PAGE TEXT TO ANNOTATE:\n"""\n'
_PAGE_TEXT_END = '\n"""'

_MIN_TARGET_CHARS = 12
_MAX_TARGET_CHARS = 80


def page_number_from_request(request: GenerationRequest) -> int | None:
    """Extract the 1-indexed page number from a generator-built prompt."""
    match = _PAGE_NUMBER_RE.search(request.user_prompt)
    return int(match.group(1)) if match else None


def page_text_from_request(request: GenerationRequest) -> str:
    """Extract the raw page-text block from a generator-built prompt."""
    prompt = request.user_prompt
    start = prompt.find(_PAGE_TEXT_MARKER)
    if start < 0:
        raise ProviderError("stub provider: no PAGE TEXT block found in prompt")
    start += len(_PAGE_TEXT_MARKER)
    end = prompt.find(_PAGE_TEXT_END, start)
    if end < 0:
        raise ProviderError("stub provider: unterminated PAGE TEXT block in prompt")
    return prompt[start:end]


def _pick_target(page_text: str) -> str:
    """Pick an exact substring of ``page_text`` to use as an anchor target.

    The first line with enough prose wins; it is truncated on a word boundary
    so the target stays an exact contiguous substring of the page.
    """
    for raw_line in page_text.splitlines():
        line = " ".join(raw_line.split())
        if len(line) < _MIN_TARGET_CHARS or not any(c.isalpha() for c in line):
            continue
        if len(line) <= _MAX_TARGET_CHARS:
            return line
        cut = line[:_MAX_TARGET_CHARS].rsplit(" ", 1)[0]
        return cut if len(cut) >= _MIN_TARGET_CHARS else line[:_MAX_TARGET_CHARS]
    # Degenerate page (no usable prose line): fall back to a squeezed excerpt.
    squeezed = " ".join(page_text.split())
    return squeezed[:_MAX_TARGET_CHARS]


class StubProvider:
    """Deterministic :class:`LLMProvider` returning one annotation per page."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.call_count = 0

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            supports_tool_calling=True,
            supports_json_schema=True,
            supports_strict_json_schema=True,
        )

    def complete(self, request: GenerationRequest) -> GenerationResult:
        page_number = page_number_from_request(request)
        if page_number is None:
            raise ProviderError("stub provider: no PAGE NUMBER line found in prompt")
        with self._lock:
            self.call_count += 1
        target = _pick_target(page_text_from_request(request))
        parsed = RecordAnnotations(
            annotations=[
                AnnotationDraft(
                    target_text=target,
                    annotation_type=AnnotationType.CORRECTION,
                    content=f"Stub correction — page {page_number}.",
                    confidence=0.9,
                    position="margin_right",
                )
            ]
        )
        return GenerationResult(
            parsed=parsed,
            request_id=f"stub-req-pg{page_number}",
            finish_reason="stop",
            usage=GenerationUsage(input_tokens=120, output_tokens=60),
            latency_seconds=0.001,
            structured_output_mode="tool",
        )


class FailPagesProvider:
    """Wrap a provider and fail selected pages with a non-retryable error.

    Keyed by page identity (parsed from the prompt), so it is race-free under
    concurrent wave execution.
    """

    def __init__(self, inner: LLMProvider, fail_pages: frozenset[int]) -> None:
        self._inner = inner
        self._fail_pages = fail_pages

    @property
    def capabilities(self) -> ProviderCapabilities:
        return self._inner.capabilities

    def complete(self, request: GenerationRequest) -> GenerationResult:
        page_number = page_number_from_request(request)
        if page_number is not None and page_number in self._fail_pages:
            raise StructuredOutputError(
                f"simulated --fail-pages failure for page {page_number}"
            )
        return self._inner.complete(request)
