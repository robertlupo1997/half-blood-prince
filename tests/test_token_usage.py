"""Lane E — token usage aggregation + CLI reporting (Session 30).

Covers (hermetic, deterministic, no network calls):

Aggregation tests (exercise generate_for_document via the _generate_for_page_tracked seam):
  1. k=1 wave-path: scripted provider emitting known per-page usage → exact totals
  2. k=3 wave-path: same but concurrent; deterministic across two independent runs
  3. None-usage provider (some pages): totals over non-None pages + correct pages_missing_usage
  4. All-None usage: pages_with_usage==0, pages_missing_usage==non-blank count, line omitted
  5. Failed page contributes no usage and does not corrupt totals
  6. Blank page contributes neither usage nor pages_missing_usage (no call was made)

CLI tests (CliRunner with generator fake wired at the AnnotationGenerator seam):
  7. annotate: "Tokens: N in / M out" line present when usage is available
  8. annotate --dry-run: same token line present in dry-run path
  9. preview: token line present
  10. annotate: token line absent when no page reported usage (pages_with_usage==0)
  11. annotate: unavailability suffix appended when pages_missing_usage > 0
"""

from __future__ import annotations

import threading
import types
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pytest
from click.testing import CliRunner

import halfblood.cli as cli_module
from halfblood.annotation_generator import AnnotationGenerator
from halfblood.config import ResolvedConfig
from halfblood.document_processor import PageContent
from halfblood.generation.errors import ProviderTransientError
from halfblood.generation.providers.base import (
    GenerationResult,
    GenerationUsage,
    ProviderCapabilities,
)
from halfblood.generation.schema import AnnotationDraft, RecordAnnotations
from halfblood.models import AnnotatedPage, Annotation, AnnotationPlan, AnnotationType

# ---------------------------------------------------------------------------
# Minimal PDF magic bytes accepted by the CLI's file-type guard
# ---------------------------------------------------------------------------
_PDF_BYTES = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n%%EOF\n"

# ---------------------------------------------------------------------------
# Common helpers
# ---------------------------------------------------------------------------


def _page(n: int, text: str = "") -> PageContent:
    return PageContent(
        page_number=n,
        text=text or f"Page {n} content here.",
        width=612.0,
        height=792.0,
    )


def _ann(
    target: str = "t",
    atype: AnnotationType = AnnotationType.DOODLE_NOTE,
    content: str = "note",
    confidence: float = 0.8,
) -> Annotation:
    return Annotation(
        page=0,
        target_text=target,
        annotation_type=atype,
        content=content,
        confidence=confidence,
        position="margin_right",  # type: ignore[arg-type]
    )


def _result(
    target: str = "t",
    content: str = "note",
    atype: str = "doodle_note",
    input_tokens: int = 10,
    output_tokens: int = 5,
) -> GenerationResult:
    """Minimal successful GenerationResult with one annotation and known token counts."""
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
        usage=GenerationUsage(input_tokens=input_tokens, output_tokens=output_tokens),
        latency_seconds=0.01,
        structured_output_mode="tool",
    )


class ScriptedProvider:
    """LLMProvider double: maps page_number → GenerationResult or exception."""

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


class NoneUsageRecorder:
    """Replaces _generate_for_page_tracked to inject None usage for specified pages.

    For pages in ``usage_map`` with None, returns the 5-tuple with usage=None (simulating
    a provider that omits usage data). For other pages with text, returns a scripted
    annotation list with a real GenerationUsage.

    Always returns the full 5-tuple expected by generate_for_document after Lane E's
    change: (annotations, attempted, failed, error, usage).
    """

    def __init__(
        self,
        results: dict[int, tuple[list[Annotation], bool, bool]],
        usage_map: dict[int, GenerationUsage | None],
    ) -> None:
        self.results = results
        self.usage_map = usage_map
        self.calls: list[types.SimpleNamespace] = []

    def __call__(
        self, page_text: str, page_number: int, book_context: str
    ) -> tuple[list[Annotation], bool, bool, None, GenerationUsage | None]:
        self.calls.append(
            types.SimpleNamespace(text=page_text, number=page_number, context=book_context)
        )
        if not page_text or not page_text.strip():
            return [], False, False, None, None
        annotations, attempted, failed = self.results.get(page_number, ([], True, False))
        usage = self.usage_map.get(page_number, GenerationUsage(input_tokens=10, output_tokens=5))
        return annotations, attempted, failed, None, usage


# ===========================================================================
# 1. k=1 wave-path: scripted provider → exact totals
# ===========================================================================


def test_usage_totals_k1_exact_sums() -> None:
    """k=1: usage_totals after generate_for_document has exact input/output sums
    and correct pages_with_usage count.

    Pages 1, 2, 3 each emit known token counts; the aggregator must sum them
    precisely.
    """
    pages = [_page(n) for n in range(1, 4)]
    responses = {
        1: _result("Page 1 content here.", "n1", input_tokens=100, output_tokens=50),
        2: _result("Page 2 content here.", "n2", input_tokens=200, output_tokens=80),
        3: _result("Page 3 content here.", "n3", input_tokens=150, output_tokens=60),
    }
    provider = ScriptedProvider(responses)
    gen = AnnotationGenerator(provider=provider)
    gen.generate_for_document(pages, concurrency=1)

    # INTENDED FAILURE: usage_totals attribute does not exist yet
    assert hasattr(gen, "usage_totals"), (
        "AnnotationGenerator must expose usage_totals after generate_for_document"
    )
    ut = gen.usage_totals
    assert ut.input_tokens == 450, f"Expected 450 input tokens; got {ut.input_tokens}"
    assert ut.output_tokens == 190, f"Expected 190 output tokens; got {ut.output_tokens}"
    assert ut.pages_with_usage == 3, f"Expected 3 pages_with_usage; got {ut.pages_with_usage}"
    assert ut.pages_missing_usage == 0, (
        f"Expected 0 pages_missing_usage; got {ut.pages_missing_usage}"
    )


# ===========================================================================
# 2. k=3 wave-path: concurrent, deterministic across two runs
# ===========================================================================


def test_usage_totals_k3_exact_sums_and_deterministic() -> None:
    """k=3: usage_totals are the same across two independent runs (deterministic)."""
    pages = [_page(n) for n in range(1, 7)]
    responses = {
        n: _result(f"Page {n} content here.", f"n{n}",
                   input_tokens=n * 10, output_tokens=n * 5)
        for n in range(1, 7)
    }
    # Expected: sum(n*10 for n in 1..6) = 210; sum(n*5 for n in 1..6) = 105
    expected_input = sum(n * 10 for n in range(1, 7))   # 210
    expected_output = sum(n * 5 for n in range(1, 7))   # 105

    provider1 = ScriptedProvider(responses)
    gen1 = AnnotationGenerator(provider=provider1)
    gen1.generate_for_document(pages, concurrency=3)

    provider2 = ScriptedProvider(responses)
    gen2 = AnnotationGenerator(provider=provider2)
    gen2.generate_for_document(pages, concurrency=3)

    # INTENDED FAILURE: usage_totals does not exist yet
    assert hasattr(gen1, "usage_totals"), "usage_totals missing after k=3 run"
    assert hasattr(gen2, "usage_totals"), "usage_totals missing after second k=3 run"

    ut1 = gen1.usage_totals
    ut2 = gen2.usage_totals

    assert ut1.input_tokens == expected_input, (
        f"Run 1: expected {expected_input} input; got {ut1.input_tokens}"
    )
    assert ut1.output_tokens == expected_output, (
        f"Run 1: expected {expected_output} output; got {ut1.output_tokens}"
    )
    assert ut1.pages_with_usage == 6, (
        f"Run 1: expected 6 pages_with_usage; got {ut1.pages_with_usage}"
    )

    # Determinism
    assert ut2.input_tokens == ut1.input_tokens, (
        f"Run 2 input differs from run 1: {ut2.input_tokens} vs {ut1.input_tokens}"
    )
    assert ut2.output_tokens == ut1.output_tokens, (
        f"Run 2 output differs from run 1: {ut2.output_tokens} vs {ut1.output_tokens}"
    )
    assert ut2.pages_with_usage == ut1.pages_with_usage


# ===========================================================================
# 3. None-usage for some pages: totals over non-None only + correct missing count
# ===========================================================================


def test_usage_totals_partial_none_usage() -> None:
    """Pages returning usage=None are counted in pages_missing_usage, not in totals.

    Pages 1 and 3 return real usage; page 2 returns None (provider omitted it).
    Total tokens must only include pages 1 and 3. pages_missing_usage must be 1.
    """
    pages = [_page(n) for n in range(1, 4)]
    results = {
        1: ([_ann()], True, False),
        2: ([_ann()], True, False),
        3: ([_ann()], True, False),
    }
    usage_map: dict[int, GenerationUsage | None] = {
        1: GenerationUsage(input_tokens=100, output_tokens=40),
        2: None,   # provider omitted usage for this page
        3: GenerationUsage(input_tokens=120, output_tokens=50),
    }
    gen = AnnotationGenerator(api_key="sk-ant-test-fake-key-not-real")
    rec = NoneUsageRecorder(results, usage_map)
    gen._generate_for_page_tracked = rec  # type: ignore[method-assign,assignment]

    # INTENDED FAILURE: generate_for_document does not yet unpack a 5-tuple
    gen.generate_for_document(pages, concurrency=1)

    assert hasattr(gen, "usage_totals"), "usage_totals missing"
    ut = gen.usage_totals
    assert ut.input_tokens == 220, f"Expected 220 input; got {ut.input_tokens}"
    assert ut.output_tokens == 90, f"Expected 90 output; got {ut.output_tokens}"
    assert ut.pages_with_usage == 2, f"Expected 2 pages_with_usage; got {ut.pages_with_usage}"
    assert ut.pages_missing_usage == 1, (
        f"Expected 1 pages_missing_usage; got {ut.pages_missing_usage}"
    )


# ===========================================================================
# 4. All pages return None usage → pages_with_usage==0, missing count == N
# ===========================================================================


def test_usage_totals_all_none_usage() -> None:
    """When every page returns usage=None, pages_with_usage==0 and
    pages_missing_usage equals the number of non-blank pages attempted.
    """
    n_pages = 3
    pages = [_page(i) for i in range(1, n_pages + 1)]
    results = {i: ([_ann()], True, False) for i in range(1, n_pages + 1)}
    usage_map: dict[int, GenerationUsage | None] = {i: None for i in range(1, n_pages + 1)}

    gen = AnnotationGenerator(api_key="sk-ant-test-fake-key-not-real")
    rec = NoneUsageRecorder(results, usage_map)
    gen._generate_for_page_tracked = rec  # type: ignore[method-assign,assignment]

    # INTENDED FAILURE: 5-tuple not yet unpacked
    gen.generate_for_document(pages, concurrency=1)

    assert hasattr(gen, "usage_totals"), "usage_totals missing"
    ut = gen.usage_totals
    assert ut.input_tokens == 0, f"Expected 0 input tokens; got {ut.input_tokens}"
    assert ut.output_tokens == 0, f"Expected 0 output tokens; got {ut.output_tokens}"
    assert ut.pages_with_usage == 0, (
        f"Expected 0 pages_with_usage; got {ut.pages_with_usage}"
    )
    assert ut.pages_missing_usage == n_pages, (
        f"Expected {n_pages} pages_missing_usage; got {ut.pages_missing_usage}"
    )


# ===========================================================================
# 5. Failed page contributes no usage and does not corrupt totals
# ===========================================================================


def test_usage_totals_failed_page_not_counted() -> None:
    """A failing page contributes neither to usage totals nor to pages_missing_usage.

    Page 1 fails, pages 2 and 3 succeed with real usage.
    """
    pages = [_page(n) for n in range(1, 4)]
    responses: dict[int, GenerationResult | BaseException] = {
        1: ProviderTransientError("boom"),
        2: _result("Page 2 content here.", "n2", input_tokens=200, output_tokens=80),
        3: _result("Page 3 content here.", "n3", input_tokens=150, output_tokens=60),
    }
    provider = ScriptedProvider(responses)
    gen = AnnotationGenerator(provider=provider)

    # INTENDED FAILURE: usage_totals does not exist yet
    gen.generate_for_document(pages, concurrency=1)

    assert hasattr(gen, "usage_totals"), "usage_totals missing"
    ut = gen.usage_totals
    # Failed page must not add to usage totals
    assert ut.input_tokens == 350, (
        f"Expected 350 input (pages 2+3 only); got {ut.input_tokens}"
    )
    assert ut.output_tokens == 140, (
        f"Expected 140 output (pages 2+3 only); got {ut.output_tokens}"
    )
    assert ut.pages_with_usage == 2, (
        f"Expected 2 pages_with_usage; got {ut.pages_with_usage}"
    )
    # Failed pages are NOT counted in pages_missing_usage (they appear in failed_pages instead)
    assert ut.pages_missing_usage == 0, (
        f"Failed page must not increment pages_missing_usage; got {ut.pages_missing_usage}"
    )


# ===========================================================================
# 6. Blank page contributes neither usage nor pages_missing_usage
# ===========================================================================


def test_usage_totals_blank_page_not_counted() -> None:
    """Blank pages are skipped (no API call), so they contribute to neither counter."""
    pages = [_page(1, ""), _page(2), _page(3, "   ")]
    responses = {
        2: _result("Page 2 content here.", "n2", input_tokens=100, output_tokens=40),
    }
    provider = ScriptedProvider(responses)
    gen = AnnotationGenerator(provider=provider)

    # INTENDED FAILURE: usage_totals does not exist yet
    gen.generate_for_document(pages, concurrency=1)

    assert hasattr(gen, "usage_totals"), "usage_totals missing"
    ut = gen.usage_totals
    assert ut.input_tokens == 100, f"Expected 100 input; got {ut.input_tokens}"
    assert ut.output_tokens == 40, f"Expected 40 output; got {ut.output_tokens}"
    assert ut.pages_with_usage == 1, f"Expected 1 pages_with_usage; got {ut.pages_with_usage}"
    assert ut.pages_missing_usage == 0, (
        f"Blank pages must not increment pages_missing_usage; got {ut.pages_missing_usage}"
    )


# ===========================================================================
# CLI fakes
# ===========================================================================

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


@dataclass
class _FakeUsageTotals:
    input_tokens: int
    output_tokens: int
    pages_with_usage: int
    pages_missing_usage: int


class _TokenAwareGenerator:
    """AnnotationGenerator fake that exposes a scripted usage_totals attribute.

    usage_totals_to_inject controls what the CLI sees after generate_for_document.
    Set to None to simulate a generator with no usage attribute (old fake behaviour).
    """

    usage_totals_to_inject: _FakeUsageTotals | None = None

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
        if type(self).usage_totals_to_inject is not None:
            self.usage_totals = type(self).usage_totals_to_inject

    def generate_for_document(
        self,
        pages: list[PageContent],
        max_annotations_per_page: int = 5,
        *,
        on_page_done: Callable | None = None,
    ) -> AnnotationPlan:
        if on_page_done is not None:
            for i in range(len(pages)):
                on_page_done(i + 1, len(pages))
        return AnnotationPlan(
            title="token-test plan",
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


class _SpyPdfProcessor:
    render_called: bool = False

    def load(self, path: str) -> list[PageContent]:
        return [
            PageContent(page_number=1, text="Bezoar. Remember that.", width=612.0, height=792.0)
        ]

    def render_annotations(self, input_path: str, annotations: list, output_path: str) -> None:
        type(self).render_called = True
        Path(output_path).write_text("rendered", encoding="utf-8")

    def render_plan(self, input_path: str, plan: object, output_path: str) -> None:
        """Write a placeholder output file (non-dry-run render path)."""
        type(self).render_called = True
        Path(output_path).write_text("rendered", encoding="utf-8")

    def annotations_from_plan(self, plan: AnnotationPlan) -> list:
        return [a for page in plan.pages for a in page.annotations]


@pytest.fixture()
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture()
def cli_usage_fakes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Wire hermetic CLI fakes with a scripted usage_totals for token-line tests."""
    _SpyPdfProcessor.render_called = False
    monkeypatch.setattr(cli_module, "resolve_generation_config", lambda *a, **k: _FAKE_CONFIG)
    monkeypatch.setattr(cli_module, "build_provider", lambda *a, **k: _SentinelProvider())
    monkeypatch.setattr(cli_module, "DocumentProcessor", _SpyPdfProcessor)
    monkeypatch.setattr(cli_module, "EpubProcessor", _SpyPdfProcessor)
    monkeypatch.setattr(cli_module, "AnnotationGenerator", _TokenAwareGenerator)


# ===========================================================================
# 7. annotate: token line present when usage is available
# ===========================================================================


def test_annotate_prints_token_line_when_usage_available(
    runner: CliRunner,
    cli_usage_fakes: None,
    tmp_path: Path,
) -> None:
    """annotate must print ``Tokens: N in / M out`` after generation when
    usage_totals is available and pages_with_usage > 0.
    """
    _TokenAwareGenerator.usage_totals_to_inject = _FakeUsageTotals(
        input_tokens=450, output_tokens=190, pages_with_usage=3, pages_missing_usage=0
    )
    src = tmp_path / "book.pdf"
    src.write_bytes(_PDF_BYTES)
    out = tmp_path / "out.pdf"

    # INTENDED FAILURE: CLI does not yet read usage_totals or print the token line
    result = runner.invoke(cli_module.main, ["annotate", str(src), "-o", str(out)])

    assert result.exit_code == 0, (
        f"annotate must exit 0; got {result.exit_code}.\n{result.output}"
    )
    assert "tokens:" in result.output.lower(), (
        f"CLI output must contain token line 'Tokens: ...' but got:\n{result.output}"
    )
    assert "450" in result.output, (
        f"Input token count (450) must appear in output; got:\n{result.output}"
    )
    assert "190" in result.output, (
        f"Output token count (190) must appear in output; got:\n{result.output}"
    )


# ===========================================================================
# 8. annotate --dry-run: token line present
# ===========================================================================


def test_dry_run_prints_token_line(
    runner: CliRunner,
    cli_usage_fakes: None,
    tmp_path: Path,
) -> None:
    """The --dry-run path in annotate must also print the token line."""
    _TokenAwareGenerator.usage_totals_to_inject = _FakeUsageTotals(
        input_tokens=300, output_tokens=120, pages_with_usage=2, pages_missing_usage=0
    )
    src = tmp_path / "book.pdf"
    src.write_bytes(_PDF_BYTES)
    out = tmp_path / "plan.json"

    # INTENDED FAILURE: --dry-run path does not yet print the token line
    result = runner.invoke(
        cli_module.main, ["annotate", str(src), "-o", str(out), "--dry-run"]
    )

    assert result.exit_code == 0, (
        f"--dry-run must exit 0; got {result.exit_code}.\n{result.output}"
    )
    assert "tokens:" in result.output.lower(), (
        f"--dry-run output must contain token line; got:\n{result.output}"
    )
    assert "300" in result.output, (
        f"Input count (300) must appear in --dry-run output; got:\n{result.output}"
    )
    assert "120" in result.output, (
        f"Output count (120) must appear in --dry-run output; got:\n{result.output}"
    )


# ===========================================================================
# 9. preview: token line present
# ===========================================================================


def test_preview_prints_token_line(
    runner: CliRunner,
    cli_usage_fakes: None,
    tmp_path: Path,
) -> None:
    """preview must print the token line when usage_totals is available."""
    _TokenAwareGenerator.usage_totals_to_inject = _FakeUsageTotals(
        input_tokens=800, output_tokens=300, pages_with_usage=5, pages_missing_usage=0
    )
    src = tmp_path / "book.pdf"
    src.write_bytes(_PDF_BYTES)

    # INTENDED FAILURE: preview does not yet print the token line
    result = runner.invoke(cli_module.main, ["preview", str(src)])

    assert result.exit_code == 0, (
        f"preview must exit 0; got {result.exit_code}.\n{result.output}"
    )
    assert "tokens:" in result.output.lower(), (
        f"preview output must contain token line; got:\n{result.output}"
    )
    assert "800" in result.output, (
        f"Input count (800) must appear in preview output; got:\n{result.output}"
    )
    assert "300" in result.output, (
        f"Output count (300) must appear in preview output; got:\n{result.output}"
    )


# ===========================================================================
# 10. annotate: token line absent when no page reported usage
# ===========================================================================


def test_annotate_omits_token_line_when_no_usage(
    runner: CliRunner,
    cli_usage_fakes: None,
    tmp_path: Path,
) -> None:
    """When pages_with_usage==0, the token line must be completely absent from output.

    This covers: all-None provider AND old fakes that don't set usage_totals.
    """
    # Simulate all-None usage (pages_with_usage == 0)
    _TokenAwareGenerator.usage_totals_to_inject = _FakeUsageTotals(
        input_tokens=0, output_tokens=0, pages_with_usage=0, pages_missing_usage=3
    )
    src = tmp_path / "book.pdf"
    src.write_bytes(_PDF_BYTES)
    out = tmp_path / "out.pdf"

    result = runner.invoke(cli_module.main, ["annotate", str(src), "-o", str(out)])

    assert result.exit_code == 0, (
        f"annotate must exit 0; got {result.exit_code}.\n{result.output}"
    )
    # INTENDED FAILURE: token line currently not suppressed (it doesn't exist yet,
    # so this may pass trivially — but will regress if the suppression logic is wrong)
    assert "tokens:" not in result.output.lower(), (
        f"Token line must be absent when pages_with_usage==0; got:\n{result.output}"
    )


# ===========================================================================
# 11. annotate: unavailability suffix when pages_missing_usage > 0
# ===========================================================================


def test_annotate_prints_unavailability_suffix(
    runner: CliRunner,
    cli_usage_fakes: None,
    tmp_path: Path,
) -> None:
    """When pages_missing_usage > 0, the token line must include the
    'usage unavailable for N page(s)' suffix.
    """
    _TokenAwareGenerator.usage_totals_to_inject = _FakeUsageTotals(
        input_tokens=250, output_tokens=100, pages_with_usage=2, pages_missing_usage=1
    )
    src = tmp_path / "book.pdf"
    src.write_bytes(_PDF_BYTES)
    out = tmp_path / "out.pdf"

    # INTENDED FAILURE: suffix not yet implemented
    result = runner.invoke(cli_module.main, ["annotate", str(src), "-o", str(out)])

    assert result.exit_code == 0, (
        f"annotate must exit 0; got {result.exit_code}.\n{result.output}"
    )
    assert "tokens:" in result.output.lower(), (
        f"Token line must be present; got:\n{result.output}"
    )
    assert "unavailable" in result.output.lower(), (
        f"Unavailability suffix must appear in output when pages_missing_usage>0; "
        f"got:\n{result.output}"
    )
    assert "1" in result.output, (
        f"The count '1' must appear in the unavailability suffix; got:\n{result.output}"
    )
