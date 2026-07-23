"""P0-T3 — document-level orchestration coverage + bounded running context.

AUD-22: ``generate_for_document`` is entirely untested — page ordering, the
500-char previous/next context window, INVENTION/WARNING running notes, the
confidence-based per-page cap, blank-page handling, and plan assembly can all
regress silently. AUD-31: ``running_notes`` grows unbounded though only the last
eight are ever used.

These tests mock the per-page seam (``_generate_for_page_tracked``) so the
orchestration logic in ``generate_for_document`` — context building, note
folding, trimming, and plan assembly — is exercised directly, with no network.
"""

from __future__ import annotations

import types

import pytest

from halfblood.annotation_generator import AllPagesFailedError, AnnotationGenerator
from halfblood.document_processor import PageContent
from halfblood.models import Annotation, AnnotationPlan, AnnotationType


def _page(n: int, text: str) -> PageContent:
    return PageContent(page_number=n, text=text, width=612.0, height=792.0)


def _ann(
    target: str,
    atype: AnnotationType,
    content: str,
    confidence: float = 0.8,
    position: str = "margin_right",
) -> Annotation:
    return Annotation(
        page=0, target_text=target, annotation_type=atype, content=content,
        confidence=confidence, position=position,  # type: ignore[arg-type]
    )


class _Recorder:
    """Replaces ``_generate_for_page_tracked``: records each call and returns a
    scripted ``(annotations, attempted, failed)``. Blank pages are skipped
    exactly as the real helper does, so blank handling stays faithful.

    The real helper returns a 5-tuple whose trailing elements are the
    ``ProviderError | None`` and ``GenerationUsage | None``. None of the
    orchestration behavior this file exercises (context windowing,
    running-notes folding, the confidence cap, blank-page handling) depends
    on those values, so this double always synthesizes ``None`` for both.
    """

    def __init__(self, results: dict[int, tuple[list[Annotation], bool, bool]]) -> None:
        self.results = results
        self.calls: list[types.SimpleNamespace] = []

    def __call__(
        self, page_text: str, page_number: int, book_context: str
    ) -> tuple[list[Annotation], bool, bool, None, None]:
        self.calls.append(
            types.SimpleNamespace(text=page_text, number=page_number, context=book_context)
        )
        if not page_text or not page_text.strip():
            return [], False, False, None, None
        annotations, attempted, failed = self.results.get(page_number, ([], True, False))
        return annotations, attempted, failed, None, None


def _generator() -> AnnotationGenerator:
    return AnnotationGenerator(api_key="sk-ant-test-fake-key-not-real")


def _run(
    gen: AnnotationGenerator,
    pages: list[PageContent],
    results: dict[int, tuple[list[Annotation], bool, bool]],
    **kwargs: object,
) -> tuple[AnnotationPlan, _Recorder]:
    rec = _Recorder(results)
    gen._generate_for_page_tracked = rec  # type: ignore[method-assign,assignment]
    # Pin to sequential (k=1) so call order and note carry-forward are deterministic.
    # These tests exercise orchestration logic, not concurrency — see test_async_generation.py
    # for concurrency tests.  Allow explicit override for tests that deliberately test k>1.
    kwargs.setdefault("concurrency", 1)
    plan = gen.generate_for_document(pages, **kwargs)  # type: ignore[arg-type]
    return plan, rec


def test_pages_processed_in_order_and_plan_assembled() -> None:
    gen = _generator()
    pages = [_page(1, "One."), _page(2, "Two."), _page(3, "Three.")]
    results = {
        1: ([_ann("One.", AnnotationType.INSIGHT, "a", 0.9)], True, False),
        2: ([], True, False),
        3: ([_ann("Three.", AnnotationType.DOODLE_NOTE, "c", 0.7)], True, False),
    }
    plan, rec = _run(gen, pages, results)
    assert [c.number for c in rec.calls] == [1, 2, 3]
    assert [c.text for c in rec.calls] == ["One.", "Two.", "Three."]
    assert [p.page_number for p in plan.pages] == [1, 2, 3]
    assert [p.original_text for p in plan.pages] == ["One.", "Two.", "Three."]
    assert plan.pages[0].annotations[0].content == "a"
    assert plan.pages[1].annotations == []
    assert plan.total_annotations == 2
    assert plan.prince_persona == gen.persona
    assert "3 pages" in plan.title
    assert gen.failed_pages == []


def test_context_window_is_trailing_and_leading_500_chars() -> None:
    gen = _generator()
    pages = [_page(1, "P" * 800), _page(2, "current"), _page(3, "N" * 800)]
    _, rec = _run(gen, pages, {n: ([], True, False) for n in (1, 2, 3)})
    ctx2 = rec.calls[1].context
    assert "P" * 500 in ctx2 and "P" * 501 not in ctx2  # exactly last 500 of prev
    assert "N" * 500 in ctx2 and "N" * 501 not in ctx2  # exactly first 500 of next


def test_only_invention_and_warning_notes_carry_forward() -> None:
    gen = _generator()
    pages = [_page(n, f"page {n} text") for n in range(1, 4)]
    results = {
        1: (
            [
                _ann("page 1 text", AnnotationType.INVENTION, "inv-1", 0.9),
                _ann("page 1 text", AnnotationType.INSIGHT, "insight-1", 0.9),
            ],
            True,
            False,
        ),
        2: ([_ann("page 2 text", AnnotationType.WARNING, "warn-2", 0.9)], True, False),
        3: ([], True, False),
    }
    _, rec = _run(gen, pages, results)
    ctx3 = rec.calls[2].context
    assert "inv-1" in ctx3
    assert "warn-2" in ctx3
    assert "insight-1" not in ctx3  # only INVENTION/WARNING are carried forward


def test_running_notes_consumed_are_capped_at_eight() -> None:
    gen = _generator()
    pages = [_page(n, f"page {n}") for n in range(1, 12)]
    results: dict[int, tuple[list[Annotation], bool, bool]] = {
        n: ([_ann(f"page {n}", AnnotationType.INVENTION, f"note-{n}", 0.9)], True, False)
        for n in range(1, 11)
    }
    results[11] = ([], True, False)
    _, rec = _run(gen, pages, results)
    ctx11 = rec.calls[10].context
    note_lines = [ln for ln in ctx11.splitlines() if ln.strip().startswith("- (p.")]
    assert len(note_lines) == 8  # only the most recent 8 (pages 3..10)
    # Use "(p.N)" markers, not "note-N", to avoid substring collisions
    # (e.g. "note-1" is a substring of "note-10").
    assert "(p.10)" in ctx11 and "(p.3)" in ctx11
    assert "(p.2)" not in ctx11 and "(p.1)" not in ctx11


def test_over_cap_keeps_highest_confidence() -> None:
    gen = _generator()
    anns = [
        _ann("t", AnnotationType.DOODLE_NOTE, "low", 0.1),
        _ann("t", AnnotationType.DOODLE_NOTE, "high", 0.9),
        _ann("t", AnnotationType.DOODLE_NOTE, "mid", 0.5),
    ]
    plan, _ = _run(gen, [_page(1, "t text")], {1: (anns, True, False)}, max_annotations_per_page=2)
    assert [a.content for a in plan.pages[0].annotations] == ["high", "mid"]


def test_over_cap_preserves_original_order_on_ties() -> None:
    gen = _generator()
    anns = [_ann("t", AnnotationType.DOODLE_NOTE, f"n{i}", 0.5) for i in range(5)]
    plan, _ = _run(gen, [_page(1, "t text")], {1: (anns, True, False)}, max_annotations_per_page=3)
    assert [a.content for a in plan.pages[0].annotations] == ["n0", "n1", "n2"]


def test_blank_pages_are_included_but_not_failures() -> None:
    gen = _generator()
    pages = [_page(1, "   \n\t"), _page(2, "real"), _page(3, "")]
    results = {2: ([_ann("real", AnnotationType.INSIGHT, "x", 0.8)], True, False)}
    plan, _ = _run(gen, pages, results)
    assert gen.failed_pages == []
    assert len(plan.pages) == 3
    assert plan.pages[0].annotations == [] and plan.pages[2].annotations == []
    assert plan.pages[0].original_text == "   \n\t"


def test_partial_failure_records_and_continues() -> None:
    gen = _generator()
    pages = [_page(1, "one"), _page(2, "two")]
    results = {
        1: ([], True, True),
        2: ([_ann("two", AnnotationType.INSIGHT, "ok", 0.8)], True, False),
    }
    plan, _ = _run(gen, pages, results)
    assert gen.failed_pages == [1]
    assert plan.pages[0].annotations == []
    assert len(plan.pages[1].annotations) == 1


def test_all_failed_raises() -> None:
    gen = _generator()
    pages = [_page(1, "one"), _page(2, "two")]
    rec = _Recorder({1: ([], True, True), 2: ([], True, True)})
    gen._generate_for_page_tracked = rec  # type: ignore[method-assign,assignment]
    with pytest.raises(AllPagesFailedError):
        gen.generate_for_document(pages, concurrency=1)
    assert gen.failed_pages == [1, 2]
