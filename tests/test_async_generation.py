"""Lane A — async/concurrent page generation tests.

Covers:
- k=1 sequential-equivalence (same prompts, same running_notes, deterministic)
- Wave semantics: intra-wave pages do not see each other's running_notes
- Wave semantics: next wave sees prior wave notes in page order
- Results assembled in page order regardless of completion order
- Concurrency actually happens (threading.Barrier proof)
- k=3 determinism (two independent runs → identical plans)
- Failure injection under k=3 (failing page does not poison siblings)
- failed_pages is always page-ordered
- AnnotationGenerator.concurrency default is 3

No network calls are made anywhere in this file.
"""

from __future__ import annotations

import threading
import types

from halfblood.annotation_generator import AnnotationGenerator
from halfblood.document_processor import PageContent
from halfblood.generation.errors import ProviderTransientError
from halfblood.generation.providers.base import (
    GenerationResult,
    GenerationUsage,
    ProviderCapabilities,
)
from halfblood.generation.schema import AnnotationDraft, RecordAnnotations

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _page(n: int, text: str = "") -> PageContent:
    return PageContent(
        page_number=n,
        text=text or f"Page {n} content here.",
        width=612.0,
        height=792.0,
    )


def _result(
    target: str = "t",
    content: str = "note",
    atype: str = "doodle_note",
) -> GenerationResult:
    """Build a minimal successful GenerationResult with one annotation."""
    parsed = RecordAnnotations(
        annotations=[
            AnnotationDraft(
                target_text=target,
                annotation_type=atype,
                content=content,
                confidence=0.8,
                position="margin_right",
            )
        ]
    )
    return GenerationResult(
        parsed=parsed,
        request_id="fake",
        finish_reason="tool_use",
        usage=GenerationUsage(input_tokens=10, output_tokens=10),
        latency_seconds=0.01,
        structured_output_mode="tool",
    )


def _empty_result() -> GenerationResult:
    """Build a successful GenerationResult with zero annotations."""
    return GenerationResult(
        parsed=RecordAnnotations(annotations=[]),
        request_id="fake",
        finish_reason="tool_use",
        usage=GenerationUsage(input_tokens=5, output_tokens=5),
        latency_seconds=0.01,
        structured_output_mode="tool",
    )


class ScriptedProvider:
    """An LLMProvider test double that scripts per-page responses.

    Maps ``page_number`` → ``GenerationResult`` (success) or exception instance
    (raised from ``complete()``).  Extracts the page number from the
    ``PAGE NUMBER: N`` line that ``AnnotationGenerator._build_user_prompt``
    always emits at the top of the user prompt.

    Thread-safe: all shared state is protected by ``_lock``.
    """

    def __init__(self, responses: dict[int, GenerationResult | BaseException]) -> None:
        self._responses = responses
        self._lock = threading.Lock()
        # Each element is a SimpleNamespace with .page_num and .user_prompt
        self.requests: list[types.SimpleNamespace] = []

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            supports_tool_calling=True,
            supports_json_schema=False,
            supports_strict_json_schema=False,
        )

    def complete(self, request: object) -> GenerationResult:
        page_num = None
        user_prompt = getattr(request, "user_prompt", "")
        for line in user_prompt.splitlines():
            if line.startswith("PAGE NUMBER:"):
                page_num = int(line.split(":", 1)[1].strip())
                break

        with self._lock:
            self.requests.append(
                types.SimpleNamespace(page_num=page_num, user_prompt=user_prompt)
            )

        item = self._responses[page_num]
        if isinstance(item, BaseException):
            raise item
        return item


class BarrierProvider:
    """LLMProvider that uses a ``threading.Barrier`` to prove k threads are
    in-flight simultaneously.

    Each ``complete()`` call blocks at the barrier until ``n_parties`` callers
    have all arrived.  If the calls are sequential (not concurrent) the barrier
    will never collect enough parties and ``barrier.wait()`` will time out,
    raising ``threading.BrokenBarrierError``.
    """

    def __init__(self, n_parties: int, timeout: float = 5.0) -> None:
        self._barrier = threading.Barrier(n_parties, timeout=timeout)
        self._lock = threading.Lock()
        self.call_count = 0

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            supports_tool_calling=True,
            supports_json_schema=False,
            supports_strict_json_schema=False,
        )

    def complete(self, request: object) -> GenerationResult:
        with self._lock:
            self.call_count += 1
        # All k threads must arrive here before any can proceed.
        # A sequential caller will wait forever (→ BrokenBarrierError on timeout).
        self._barrier.wait()
        return _empty_result()


# ---------------------------------------------------------------------------
# k=1 sequential-equivalence
# ---------------------------------------------------------------------------


def test_k1_produces_page_ordered_results() -> None:
    """k=1 assembles plan.pages in input page order."""
    pages = [_page(n) for n in range(1, 5)]
    responses = {n: _result(f"Page {n} content here.", f"note-{n}") for n in range(1, 5)}
    provider = ScriptedProvider(responses)
    gen = AnnotationGenerator(provider=provider)
    plan = gen.generate_for_document(pages, concurrency=1)

    assert [p.page_number for p in plan.pages] == [1, 2, 3, 4]
    assert [p.annotations[0].content for p in plan.pages] == [
        f"note-{n}" for n in range(1, 5)
    ]


def test_k1_carries_invention_and_warning_notes_forward() -> None:
    """k=1: INVENTION/WARNING notes from earlier pages reach later pages' context."""
    pages = [_page(n) for n in range(1, 5)]
    responses = {
        1: _result("Page 1 content here.", "My invention", "invention"),
        2: _result("Page 2 content here.", "My warning", "warning"),
        3: _result("Page 3 content here.", "An insight", "insight"),
        4: _empty_result(),
    }
    provider = ScriptedProvider(responses)
    gen = AnnotationGenerator(provider=provider)
    gen.generate_for_document(pages, concurrency=1)

    # Page 3 must see INVENTION from p1 and WARNING from p2
    req3 = next(r for r in provider.requests if r.page_num == 3)
    assert "My invention" in req3.user_prompt
    assert "My warning" in req3.user_prompt
    # INSIGHT is not a carry-forward type
    req4 = next(r for r in provider.requests if r.page_num == 4)
    assert "My invention" in req4.user_prompt
    assert "My warning" in req4.user_prompt
    assert "An insight" not in req4.user_prompt


def test_k1_two_runs_produce_identical_plans() -> None:
    """k=1 is deterministic: independent runs on the same input give the same plan."""
    pages = [_page(n) for n in range(1, 4)]
    responses = {n: _result(f"Page {n} content here.", f"note-{n}") for n in range(1, 4)}

    provider1 = ScriptedProvider(responses)
    gen1 = AnnotationGenerator(provider=provider1)
    plan1 = gen1.generate_for_document(pages, concurrency=1)

    provider2 = ScriptedProvider(responses)
    gen2 = AnnotationGenerator(provider=provider2)
    plan2 = gen2.generate_for_document(pages, concurrency=1)

    for p1, p2 in zip(plan1.pages, plan2.pages, strict=True):
        assert p1.page_number == p2.page_number
        assert [a.content for a in p1.annotations] == [a.content for a in p2.annotations]


# ---------------------------------------------------------------------------
# Wave semantics: running_notes isolation
# ---------------------------------------------------------------------------


def test_wave_intrawave_pages_do_not_see_each_others_notes() -> None:
    """Pages in the same wave are dispatched before any wave results land.

    With k=3, pages 1+2+3 form wave 1.  Their prompts are all built from the
    same ``running_notes`` snapshot (empty for the first wave).  Page 3 must NOT
    see INVENTION notes from pages 1 or 2 even though those pages produced them.
    """
    pages = [_page(n) for n in range(1, 7)]
    responses = {
        1: _result("Page 1 content here.", "inv-1", "invention"),
        2: _result("Page 2 content here.", "warn-2", "warning"),
        # page 3 is in the same wave as 1+2; its context must not mention inv-1/warn-2
        3: _empty_result(),
        4: _empty_result(),
        5: _empty_result(),
        6: _empty_result(),
    }
    provider = ScriptedProvider(responses)
    gen = AnnotationGenerator(provider=provider)
    gen.generate_for_document(pages, concurrency=3)

    req3 = next(r for r in provider.requests if r.page_num == 3)
    assert "inv-1" not in req3.user_prompt, (
        "Page 3 saw notes from page 1 (same wave); wave context isolation violated"
    )
    assert "warn-2" not in req3.user_prompt, (
        "Page 3 saw notes from page 2 (same wave); wave context isolation violated"
    )


def test_wave_next_wave_sees_all_prior_wave_notes_in_page_order() -> None:
    """After wave 1 completes, its INVENTION/WARNING notes (in page order) are
    visible to every page in wave 2.
    """
    pages = [_page(n) for n in range(1, 7)]
    responses = {
        1: _result("Page 1 content here.", "inv-1", "invention"),
        2: _result("Page 2 content here.", "warn-2", "warning"),
        3: _result("Page 3 content here.", "inv-3", "invention"),
        4: _empty_result(),
        5: _empty_result(),
        6: _empty_result(),
    }
    provider = ScriptedProvider(responses)
    gen = AnnotationGenerator(provider=provider)
    gen.generate_for_document(pages, concurrency=3)

    # Page 4 is first of wave 2; it must see all three notes from wave 1
    req4 = next(r for r in provider.requests if r.page_num == 4)
    assert "inv-1" in req4.user_prompt
    assert "warn-2" in req4.user_prompt
    assert "inv-3" in req4.user_prompt


def test_wave_results_assembled_in_page_order() -> None:
    """plan.pages is always in input page order, even if completions arrive
    in a different order (k>1)."""
    pages = [_page(n) for n in range(1, 6)]
    responses = {n: _result(f"Page {n} content here.", f"note-{n}") for n in range(1, 6)}
    provider = ScriptedProvider(responses)
    gen = AnnotationGenerator(provider=provider)
    plan = gen.generate_for_document(pages, concurrency=3)

    assert [p.page_number for p in plan.pages] == [1, 2, 3, 4, 5]


# ---------------------------------------------------------------------------
# Concurrency actually happens
# ---------------------------------------------------------------------------


def test_concurrency_actually_concurrent_k3() -> None:
    """Proves that k=3 dispatches at least 3 threads simultaneously.

    The Barrier requires exactly ``k`` threads to call ``barrier.wait()``
    before any can proceed.  If pages are processed sequentially (1 thread),
    the barrier will never fill and ``BrokenBarrierError`` is raised on timeout.
    The test passes only if k threads overlap.
    """
    k = 3
    pages = [_page(n) for n in range(1, k + 1)]  # exactly one full wave
    provider = BarrierProvider(n_parties=k, timeout=10.0)
    gen = AnnotationGenerator(provider=provider)
    plan = gen.generate_for_document(pages, concurrency=k)

    assert provider.call_count == k
    assert len(plan.pages) == k


# ---------------------------------------------------------------------------
# k=3 determinism
# ---------------------------------------------------------------------------


def test_k3_determinism_two_runs_identical() -> None:
    """Two independent k=3 runs on the same inputs produce identical plans."""
    pages = [_page(n) for n in range(1, 7)]
    responses = {n: _result(f"Page {n} content here.", f"note-{n}") for n in range(1, 7)}

    provider1 = ScriptedProvider(responses)
    gen1 = AnnotationGenerator(provider=provider1)
    plan1 = gen1.generate_for_document(pages, concurrency=3)

    provider2 = ScriptedProvider(responses)
    gen2 = AnnotationGenerator(provider=provider2)
    plan2 = gen2.generate_for_document(pages, concurrency=3)

    for p1, p2 in zip(plan1.pages, plan2.pages, strict=True):
        assert p1.page_number == p2.page_number
        assert [a.content for a in p1.annotations] == [a.content for a in p2.annotations]


# ---------------------------------------------------------------------------
# Failure injection under k=3
# ---------------------------------------------------------------------------


def test_failure_injection_k3_failing_page_does_not_poison_siblings() -> None:
    """A single failing page in a wave does not affect sibling pages."""
    pages = [_page(n) for n in range(1, 4)]  # exactly one wave of k=3
    responses: dict[int, GenerationResult | BaseException] = {
        1: ProviderTransientError("boom"),          # page 1 fails
        2: _result("Page 2 content here.", "note-2"),   # page 2 succeeds
        3: _result("Page 3 content here.", "note-3"),   # page 3 succeeds
    }
    provider = ScriptedProvider(responses)
    gen = AnnotationGenerator(provider=provider)
    plan = gen.generate_for_document(pages, concurrency=3)

    assert gen.failed_pages == [1], (
        f"Expected [1] in failed_pages; got {gen.failed_pages}"
    )
    assert plan.pages[0].annotations == []
    assert len(plan.pages[1].annotations) == 1
    assert len(plan.pages[2].annotations) == 1


def test_failure_injection_k3_failed_pages_are_page_ordered() -> None:
    """failed_pages is always sorted in ascending page order."""
    pages = [_page(n) for n in range(1, 7)]
    responses: dict[int, GenerationResult | BaseException] = {
        1: ProviderTransientError("boom"),
        2: _result("Page 2 content here.", "note-2"),
        3: ProviderTransientError("boom"),
        4: _result("Page 4 content here.", "note-4"),
        5: ProviderTransientError("boom"),
        6: _result("Page 6 content here.", "note-6"),
    }
    provider = ScriptedProvider(responses)
    gen = AnnotationGenerator(provider=provider)
    gen.generate_for_document(pages, concurrency=3)

    assert gen.failed_pages == [1, 3, 5]


# ---------------------------------------------------------------------------
# Constructor default
# ---------------------------------------------------------------------------


def test_generator_default_concurrency_is_three() -> None:
    """AnnotationGenerator.concurrency defaults to 3 (owner-endorsed 3–5)."""
    gen = AnnotationGenerator(provider=ScriptedProvider({}))
    assert gen.concurrency == 3
