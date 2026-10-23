"""Long pages are generated in windows (hermetic, no network).

A reflowable EPUB chapter is one "page" and can run past 80,000 characters.
Asked about all of it in one call, a model returned 3 notes for the whole
83,063-character Elements of Style chapter (2026-10-19). These tests pin that
a long page is split into exact slices, each slice gets its own call, and the
per-page cap scales with the number of windows.
"""

from __future__ import annotations

import threading

from halfblood.annotation_generator import (
    PAGE_WINDOW_CHARS,
    AnnotationGenerator,
    _split_page_text,
)
from halfblood.document_processor import PageContent
from halfblood.generation.errors import ProviderTransientError
from halfblood.generation.providers.base import (
    GenerationRequest,
    GenerationResult,
    GenerationUsage,
    ProviderCapabilities,
)
from halfblood.generation.schema import AnnotationDraft, RecordAnnotations


def _paragraphs(count: int, size: int = 900) -> str:
    return "\n".join(f"Paragraph {i} " + "x" * (size - 14) for i in range(count))


class _WindowProvider:
    """Returns ``per_call`` notes per request, each quoting the window it was sent."""

    def __init__(self, per_call: int = 2, fail_on_call: int | None = None) -> None:
        self.per_call = per_call
        self.fail_on_call = fail_on_call
        self.windows: list[str] = []
        self._lock = threading.Lock()

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            supports_tool_calling=True,
            supports_json_schema=False,
            supports_strict_json_schema=False,
        )

    def complete(self, request: GenerationRequest) -> GenerationResult:
        window = request.user_prompt.split('"""\n', 1)[1].rsplit('\n"""', 1)[0]
        with self._lock:
            self.windows.append(window)
            call = len(self.windows)
        if call == self.fail_on_call:
            raise ProviderTransientError("simulated outage")
        drafts = [
            AnnotationDraft(
                target_text=window.split("\n")[0][:30],
                annotation_type="correction",
                content=f"note {call}.{i}",
                confidence=0.5,
                position="margin_right",
            )
            for i in range(self.per_call)
        ]
        return GenerationResult(
            parsed=RecordAnnotations(annotations=drafts),
            request_id=f"r{call}",
            finish_reason="tool_use",
            usage=GenerationUsage(input_tokens=100, output_tokens=10),
            latency_seconds=0.0,
            structured_output_mode="tool",
        )


def test_short_text_is_one_window() -> None:
    assert _split_page_text("short page") == ["short page"]


def test_windows_are_exact_bounded_slices() -> None:
    text = _paragraphs(60)
    windows = _split_page_text(text)
    assert len(windows) > 1
    assert "".join(windows) == text
    assert all(len(w) <= PAGE_WINDOW_CHARS for w in windows)
    # Cuts land just after a newline, so no paragraph is split mid-line.
    assert all(w.endswith("\n") for w in windows[:-1])


def test_unbroken_text_is_hard_split_without_loss() -> None:
    text = "y" * (PAGE_WINDOW_CHARS * 2 + 5)
    windows = _split_page_text(text)
    assert "".join(windows) == text
    assert [len(w) for w in windows] == [PAGE_WINDOW_CHARS, PAGE_WINDOW_CHARS, 5]


def test_long_page_gets_one_call_per_window_and_a_scaled_cap() -> None:
    text = _paragraphs(60)
    window_count = len(_split_page_text(text))
    provider = _WindowProvider(per_call=2)
    generator = AnnotationGenerator(provider=provider, concurrency=1)

    plan = generator.generate_for_document(
        [PageContent(page_number=1, text=text, width=0.0, height=0.0)],
        max_annotations_per_page=1,
    )

    assert len(provider.windows) == window_count
    notes = plan.pages[0].annotations
    # One note per window survives a cap of 1, not one note for the chapter.
    assert len(notes) == window_count
    assert all(note.target_text in text for note in notes)
    assert generator.usage_totals.input_tokens == 100 * window_count


def test_a_failed_window_fails_the_whole_page() -> None:
    text = _paragraphs(60)
    provider = _WindowProvider(per_call=1, fail_on_call=2)
    generator = AnnotationGenerator(provider=provider, concurrency=1)

    annotations, attempted, failed, error, usage = generator._generate_for_page_tracked(
        text, 1, ""
    )

    assert (annotations, attempted, failed, usage) == ([], True, True, None)
    assert isinstance(error, ProviderTransientError)
