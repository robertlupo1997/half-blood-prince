"""Lane C — ``--dry-run`` flag and streaming per-page progress callback.

Covers (hermetic, deterministic, no network calls):

Callback tests (test the core generate_for_document contract):
  1. k=1: callback fires exactly N times, monotonically, from the main thread
  2. k=3: callback fires exactly N times, in page order, from the main thread
  3. Blank/skipped pages still trigger the callback (one fire per input page)
  4. done_count runs 1..N; total always equals len(pages)

``--dry-run`` flag tests (CLI-level via CliRunner):
  5. Plan JSON written to output; ``render_plan`` / ``render_annotations`` never called
  6. Dry-run JSON round-trips through web_preview.generate_preview (schema valid, counts match)
  7. Summary output contains ``"dry run"`` and ``"no artifact rendered"`` (case-insensitive)
  8. ``--force`` allows overwriting an existing output file
  9. Without ``--force``, dry-run rejects an existing output file (non-zero exit)

CLI progress-wiring tests:
  10. ``annotate`` passes a non-None on_page_done callback to generate_for_document
  11. ``preview`` passes a non-None on_page_done callback to generate_for_document
"""

from __future__ import annotations

import json
import threading
import types
from collections.abc import Callable
from pathlib import Path

import pytest
from click.testing import CliRunner

import halfblood.cli as cli_module
from halfblood.annotation_generator import AnnotationGenerator
from halfblood.config import ResolvedConfig
from halfblood.document_processor import PageContent
from halfblood.generation.providers.base import (  # noqa: F401
    GenerationResult,
    GenerationUsage,
    ProviderCapabilities,
)
from halfblood.generation.schema import AnnotationDraft, RecordAnnotations
from halfblood.models import AnnotatedPage, Annotation, AnnotationPlan, AnnotationType
from halfblood.web_preview import PreviewResult, generate_preview

# ---------------------------------------------------------------------------
# Minimal PDF magic bytes accepted by the CLI's file-type guard
# ---------------------------------------------------------------------------
_PDF_BYTES = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n%%EOF\n"


# ---------------------------------------------------------------------------
# Provider / generator test doubles
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
    """Minimal successful GenerationResult with one annotation."""
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


class ScriptedProvider:
    """LLMProvider test double: maps page_number → result or exception."""

    def __init__(self, responses: dict[int, GenerationResult | BaseException]) -> None:
        self._responses = responses
        self._lock = threading.Lock()
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


# ---------------------------------------------------------------------------
# Fake config / providers for CLI tests
# ---------------------------------------------------------------------------

_FAKE_SOURCES: dict[str, str] = {
    "provider": "cli",
    "model": "cli",
    "base_url": "preset",
    "api_key_env": "preset",
    "structured_output": "preset",
    "timeout_seconds": "default",
    "max_retries": "default",
    "concurrency": "default",
    "allow_insecure_http": "default",
}

_FAKE_CONFIG = ResolvedConfig(
    provider="anthropic",
    model="claude-sonnet-5",
    base_url="https://api.anthropic.com",
    api_key_env="ANTHROPIC_API_KEY",
    structured_output="tool",
    timeout_seconds=60.0,
    max_retries=0,
    concurrency=1,
    allow_insecure_http=False,
    sources=_FAKE_SOURCES,
)


class _SentinelProvider:
    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            supports_tool_calling=True,
            supports_json_schema=False,
            supports_strict_json_schema=False,
        )

    def complete(self, request: object) -> GenerationResult:
        raise AssertionError("provider.complete() must not be called in this test")


class _CapturingGenerator:
    """Fake AnnotationGenerator that captures the on_page_done callback."""

    on_page_done_received: Callable | None = None
    calls: int = 0
    _n_pages: int = 1

    def __init__(
        self,
        *,
        provider: object | None = None,
        persona: str | None = None,
        model: str | None = None,
        api_key: str | None = None,
        concurrency: int = 3,
    ) -> None:
        self.failed_pages: list[int] = []

    def generate_for_document(
        self,
        pages: list[PageContent],
        max_annotations_per_page: int = 5,
        *,
        on_page_done: Callable | None = None,
    ) -> AnnotationPlan:
        type(self).calls += 1
        type(self).on_page_done_received = on_page_done
        type(self)._n_pages = len(pages)
        # Call the callback once per page so the progress bar actually advances
        if on_page_done is not None:
            for i in range(len(pages)):
                on_page_done(i + 1, len(pages))
        return AnnotationPlan(
            title="lane-c-test plan",
            prince_persona="p",
            pages=[
                AnnotatedPage(
                    page_number=p.page_number,
                    original_text=p.text,
                    annotations=[
                        Annotation(
                            page=p.page_number,
                            target_text=p.text[:10] if p.text else "t",
                            annotation_type=AnnotationType.DOODLE_NOTE,
                            content="test note",
                            confidence=0.8,
                            position="margin_right",
                        )
                    ],
                )
                for p in pages
            ],
        )


class _SpyPdfProcessor:
    """DocumentProcessor double that records render calls."""

    render_called: bool = False

    def load(self, path: str) -> list[PageContent]:
        return [
            PageContent(
                page_number=1,
                text="Bezoar. Remember that.",
                width=612.0,
                height=792.0,
            )
        ]

    def render_annotations(
        self, input_path: str, annotations: list, output_path: str
    ) -> None:
        type(self).render_called = True
        raise AssertionError("render_annotations must not be called in dry-run mode")

    def render_plan(self, input_path: str, plan: object, output_path: str) -> None:
        type(self).render_called = True
        raise AssertionError("render_plan must not be called in dry-run mode")

    def annotations_from_plan(self, plan: AnnotationPlan) -> list:
        return [a for page in plan.pages for a in page.annotations]


# ---------------------------------------------------------------------------
# Common fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture()
def cli_fakes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Wire hermetic fakes into the CLI for dry-run / progress tests."""
    _CapturingGenerator.on_page_done_received = None
    _CapturingGenerator.calls = 0
    _CapturingGenerator._n_pages = 1
    _SpyPdfProcessor.render_called = False

    monkeypatch.setattr(cli_module, "resolve_generation_config", lambda *a, **k: _FAKE_CONFIG)
    monkeypatch.setattr(cli_module, "build_provider", lambda *a, **k: _SentinelProvider())
    monkeypatch.setattr(cli_module, "AnnotationGenerator", _CapturingGenerator)
    monkeypatch.setattr(cli_module, "DocumentProcessor", _SpyPdfProcessor)
    monkeypatch.setattr(cli_module, "EpubProcessor", _SpyPdfProcessor)


# ===========================================================================
# 1. k=1: callback fires N times, monotonically, from main thread
# ===========================================================================


def test_callback_k1_fires_n_times_in_order_from_main_thread() -> None:
    """With concurrency=1, on_page_done fires exactly len(pages) times, in page
    order (done_count 1..N), and always from the same thread that called
    generate_for_document (the "main" / orchestrating thread).
    """
    pages = [_page(n) for n in range(1, 5)]
    responses = {n: _result(f"Page {n} content here.", f"note-{n}") for n in range(1, 5)}
    provider = ScriptedProvider(responses)
    gen = AnnotationGenerator(provider=provider)

    call_log: list[tuple[int, int, int]] = []  # (done, total, thread_id)
    caller_thread_id = threading.current_thread().ident

    def spy(done: int, total: int) -> None:
        call_log.append((done, total, threading.current_thread().ident))

    # INTENDED FAILURE: generate_for_document does not yet accept on_page_done
    gen.generate_for_document(pages, concurrency=1, on_page_done=spy)

    assert len(call_log) == 4, (
        f"Expected 4 callback invocations (one per page); got {len(call_log)}"
    )
    done_values = [e[0] for e in call_log]
    assert done_values == [1, 2, 3, 4], (
        f"done_count must be monotonically increasing 1..N; got {done_values}"
    )
    for _done, total, tid in call_log:
        assert total == 4, f"total must equal len(pages)=4; got {total}"
        assert tid == caller_thread_id, (
            f"Callback invoked from thread {tid}, expected caller thread {caller_thread_id}. "
            "The callback must be fired from the orchestrating thread only, never from workers."
        )


# ===========================================================================
# 2. k=3: callback fires N times in page order from main thread (wave bursts)
# ===========================================================================


def test_callback_k3_fires_n_times_in_order_from_main_thread() -> None:
    """With concurrency=3, on_page_done fires exactly len(pages) times total,
    with done_count running 1..N in page order, all from the calling thread.
    Callbacks arrive in wave-completion bursts (3 at a time), not smoothly —
    that is the correct and expected behavior.
    """
    pages = [_page(n) for n in range(1, 7)]
    responses = {n: _result(f"Page {n} content here.", f"note-{n}") for n in range(1, 7)}
    provider = ScriptedProvider(responses)
    gen = AnnotationGenerator(provider=provider)

    call_log: list[tuple[int, int, int]] = []
    caller_thread_id = threading.current_thread().ident

    def spy(done: int, total: int) -> None:
        call_log.append((done, total, threading.current_thread().ident))

    # INTENDED FAILURE: generate_for_document does not yet accept on_page_done
    gen.generate_for_document(pages, concurrency=3, on_page_done=spy)

    assert len(call_log) == 6, (
        f"Expected 6 callback invocations (one per page); got {len(call_log)}"
    )
    done_values = [e[0] for e in call_log]
    assert done_values == [1, 2, 3, 4, 5, 6], (
        f"done_count must be monotonically increasing 1..N; got {done_values}"
    )
    for _done, total, tid in call_log:
        assert total == 6, f"total must equal len(pages)=6; got {total}"
        assert tid == caller_thread_id, (
            f"Callback invoked from thread {tid}, expected caller thread {caller_thread_id}. "
            "Worker threads must not fire the callback."
        )


# ===========================================================================
# 3. Blank/skipped pages still fire the callback
# ===========================================================================


def test_callback_blank_pages_still_fire() -> None:
    """Blank pages are skipped (no API call), but they still appear in plan.pages
    and must still trigger the callback — one fire per input page, no exceptions.
    """
    pages = [
        _page(1, ""),           # blank — will be skipped
        _page(2),               # has content
        _page(3, "   \n  "),    # whitespace-only — also blank
        _page(4),               # has content
    ]
    responses = {
        2: _result("Page 2 content here.", "note-2"),
        4: _result("Page 4 content here.", "note-4"),
    }
    provider = ScriptedProvider(responses)
    gen = AnnotationGenerator(provider=provider)

    call_log: list[int] = []

    def spy(done: int, total: int) -> None:
        call_log.append(done)

    # INTENDED FAILURE: on_page_done not accepted yet
    gen.generate_for_document(pages, concurrency=1, on_page_done=spy)

    assert len(call_log) == 4, (
        f"Blank pages must still fire the callback; expected 4 calls, got {len(call_log)}"
    )
    assert call_log == [1, 2, 3, 4], f"done_count sequence must be 1..4; got {call_log}"


# ===========================================================================
# 4. total param is always correct; done_count is monotonic
# ===========================================================================


def test_callback_total_correct_and_done_monotonic() -> None:
    """total in every callback invocation equals len(pages); done_count is strictly
    increasing (1, 2, ..., N).
    """
    n = 5
    pages = [_page(i) for i in range(1, n + 1)]
    responses = {i: _result(f"Page {i} content here.", f"n{i}") for i in range(1, n + 1)}
    provider = ScriptedProvider(responses)
    gen = AnnotationGenerator(provider=provider)

    totals: list[int] = []
    dones: list[int] = []

    def spy(done: int, total: int) -> None:
        dones.append(done)
        totals.append(total)

    # INTENDED FAILURE: on_page_done not accepted yet
    gen.generate_for_document(pages, concurrency=1, on_page_done=spy)

    assert all(t == n for t in totals), f"All totals must be {n}; got {totals}"
    assert dones == list(range(1, n + 1)), f"done must be 1..{n}; got {dones}"


# ===========================================================================
# 5. dry-run: JSON written, renderer never called
# ===========================================================================


def test_dry_run_writes_json_and_does_not_render(
    runner: CliRunner,
    cli_fakes: None,
    tmp_path: Path,
) -> None:
    """``--dry-run`` must write the annotation plan as JSON to -o, and must NOT
    invoke render_plan or render_annotations on the processor.
    """
    src = tmp_path / "book.pdf"
    src.write_bytes(_PDF_BYTES)
    out = tmp_path / "plan.json"

    # INTENDED FAILURE: --dry-run flag not yet accepted by annotate
    result = runner.invoke(
        cli_module.main,
        [
            "annotate",
            str(src),
            "-o",
            str(out),
            "--dry-run",
        ],
    )

    assert result.exit_code == 0, (
        f"--dry-run must exit 0; got {result.exit_code}.\n{result.output}"
    )
    assert out.exists(), "--dry-run must write the plan JSON to -o"
    assert not _SpyPdfProcessor.render_called, (
        "render_plan / render_annotations must NOT be called in dry-run mode"
    )
    # Output must be parseable JSON containing an AnnotationPlan
    data = json.loads(out.read_text(encoding="utf-8"))
    assert "pages" in data, f"JSON output missing 'pages' key; got keys: {list(data)}"
    assert "title" in data, f"JSON output missing 'title' key; got keys: {list(data)}"


# ===========================================================================
# 6. dry-run round-trip: JSON loadable by web_preview.generate_preview
# ===========================================================================


def test_dry_run_json_round_trips_through_web_preview(
    runner: CliRunner,
    cli_fakes: None,
    tmp_path: Path,
) -> None:
    """The JSON file produced by ``--dry-run`` must round-trip through
    ``web_preview.generate_preview`` without error. This confirms the dry-run
    output format matches the schema web-preview expects.
    """
    src = tmp_path / "book.pdf"
    src.write_bytes(_PDF_BYTES)
    plan_out = tmp_path / "plan.json"
    html_out = tmp_path / "preview.html"

    # INTENDED FAILURE: --dry-run flag not yet accepted
    result = runner.invoke(
        cli_module.main,
        ["annotate", str(src), "-o", str(plan_out), "--dry-run"],
    )
    assert result.exit_code == 0, (
        f"dry-run must succeed before round-trip test can run.\n{result.output}"
    )
    assert plan_out.exists(), "dry-run must write plan JSON"

    # generate_preview must succeed on the dry-run JSON output
    preview_result = generate_preview(plan_out, html_out)

    assert isinstance(preview_result, PreviewResult), (
        "generate_preview must return a PreviewResult"
    )
    assert preview_result.page_count >= 1, (
        "Round-tripped plan must have at least 1 page"
    )
    assert html_out.exists(), "generate_preview must write an HTML file"


# ===========================================================================
# 7. dry-run summary contains expected phrases
# ===========================================================================


def test_dry_run_summary_mentions_dry_run_and_no_artifact(
    runner: CliRunner,
    cli_fakes: None,
    tmp_path: Path,
) -> None:
    """``--dry-run`` output must include the phrases ``"dry run"`` and
    ``"no artifact rendered"`` (case-insensitive) so the user knows no output
    document was written.
    """
    src = tmp_path / "book.pdf"
    src.write_bytes(_PDF_BYTES)
    out = tmp_path / "plan.json"

    # INTENDED FAILURE: --dry-run not yet a flag
    result = runner.invoke(
        cli_module.main,
        ["annotate", str(src), "-o", str(out), "--dry-run"],
    )

    assert result.exit_code == 0, result.output
    output_lower = result.output.lower()
    assert "dry run" in output_lower, (
        f"Summary must contain 'dry run'; output was:\n{result.output}"
    )
    assert "no artifact rendered" in output_lower, (
        f"Summary must contain 'no artifact rendered'; output was:\n{result.output}"
    )


# ===========================================================================
# 8. --dry-run --force overwrites an existing output file
# ===========================================================================


def test_dry_run_force_overwrites_existing_file(
    runner: CliRunner,
    cli_fakes: None,
    tmp_path: Path,
) -> None:
    """With ``--force``, ``--dry-run`` must overwrite an existing output file."""
    src = tmp_path / "book.pdf"
    src.write_bytes(_PDF_BYTES)
    out = tmp_path / "plan.json"
    out.write_text('{"title": "old", "pages": []}', encoding="utf-8")

    # INTENDED FAILURE: --dry-run not yet a flag
    result = runner.invoke(
        cli_module.main,
        ["annotate", str(src), "-o", str(out), "--dry-run", "--force"],
    )

    assert result.exit_code == 0, (
        f"--dry-run --force must exit 0 on an existing output file; got {result.exit_code}.\n"
        f"{result.output}"
    )
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data.get("title") != "old", (
        "Output file must have been overwritten by --dry-run --force; "
        f"still contains old content: {data}"
    )


# ===========================================================================
# 9. --dry-run without --force rejects an existing output file
# ===========================================================================


def test_dry_run_rejects_existing_output_without_force(
    runner: CliRunner,
    cli_fakes: None,
    tmp_path: Path,
) -> None:
    """Without ``--force``, ``--dry-run`` must refuse to overwrite an existing file."""
    src = tmp_path / "book.pdf"
    src.write_bytes(_PDF_BYTES)
    out = tmp_path / "plan.json"
    out.write_text('{"title": "old", "pages": []}', encoding="utf-8")

    # INTENDED FAILURE: --dry-run not yet a flag
    result = runner.invoke(
        cli_module.main,
        ["annotate", str(src), "-o", str(out), "--dry-run"],
    )

    assert result.exit_code != 0, (
        "--dry-run without --force must reject an existing output file (non-zero exit); "
        f"got exit_code=0. Output:\n{result.output}"
    )


# ===========================================================================
# 10. annotate: on_page_done callback wired (non-None passed to generator)
# ===========================================================================


def test_annotate_wires_progress_callback(
    runner: CliRunner,
    cli_fakes: None,
    tmp_path: Path,
) -> None:
    """``annotate --dry-run`` must pass a non-None ``on_page_done`` callback to
    ``AnnotationGenerator.generate_for_document`` so the Rich progress bar
    can advance per page during generation.

    We use ``--dry-run`` to avoid invoking the renderer (which is a spy that
    raises on call), letting us isolate the callback-wiring assertion cleanly.
    """
    src = tmp_path / "book.pdf"
    src.write_bytes(_PDF_BYTES)
    out = tmp_path / "plan.json"

    # INTENDED FAILURE: (a) --dry-run not yet a flag OR
    #                   (b) on_page_done callback not yet wired in annotate
    result = runner.invoke(
        cli_module.main,
        ["annotate", str(src), "-o", str(out), "--dry-run"],
    )

    assert result.exit_code == 0, (
        f"annotate --dry-run must exit 0; got {result.exit_code}.\n{result.output}"
    )
    assert _CapturingGenerator.on_page_done_received is not None, (
        "annotate must pass a non-None on_page_done callback to generate_for_document. "
        "The Rich progress bar will not advance per-page without this wiring."
    )


# ===========================================================================
# 11. preview: on_page_done callback wired (non-None passed to generator)
# ===========================================================================


def test_preview_wires_progress_callback(
    runner: CliRunner,
    cli_fakes: None,
    tmp_path: Path,
) -> None:
    """``preview`` must pass a non-None ``on_page_done`` callback to
    ``AnnotationGenerator.generate_for_document`` so the Rich progress bar
    advances per page.
    """
    src = tmp_path / "book.pdf"
    src.write_bytes(_PDF_BYTES)

    result = runner.invoke(
        cli_module.main,
        ["preview", str(src)],
    )

    # INTENDED FAILURE: on_page_done callback not yet wired in preview
    assert result.exit_code == 0, (
        f"preview must exit 0; got {result.exit_code}.\n{result.output}"
    )
    assert _CapturingGenerator.on_page_done_received is not None, (
        "preview must pass a non-None on_page_done callback to generate_for_document. "
        "The Rich progress bar will not advance per-page without this wiring."
    )
