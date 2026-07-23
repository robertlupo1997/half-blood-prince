"""Regression tests for AUD-16: surface API failures instead of silently
producing empty annotated books.

Before this fix, ``AnnotationGenerator.generate_for_page`` caught
``anthropic.APIError`` and returned ``[]`` with no user-visible signal, so a
dead model (or a bad key) produced an empty book with exit code 0. These tests
pin the new contract:

    * ``generate_for_document`` records per-page failures on ``failed_pages``.
    * If *every* page that was sent to the provider failed, it raises
      ``AllPagesFailedError`` (so the CLI can exit non-zero) carrying a real
      per-page ``GenerationReport``.
    * A partial failure does NOT raise -- surviving pages still get
      annotations.
    * The public ``generate_for_page`` still returns ``[]`` on error (its
      documented contract is unchanged).
    * The CLI turns ``AllPagesFailedError`` into a clean non-zero exit, not a
      raw traceback.

As of P1-T5 (provider-seam parity cutover), ``AnnotationGenerator`` no longer
talks to the ``anthropic`` SDK directly -- it goes through an injectable
``LLMProvider`` (see ``halfblood.generation.providers.base``). These tests
inject a fake provider instead of monkeypatching an SDK client, per the P1-T5
plan's explicit permission to update this file "for compatibility wiring."
The pinned failure/report *behavior* is otherwise unchanged from before the
cutover.

No real network calls are made anywhere in this file.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from halfblood.annotation_generator import AllPagesFailedError, AnnotationGenerator
from halfblood.cli import main as cli_main
from halfblood.document_processor import PageContent
from halfblood.generation.errors import IncompleteResponseError, ProviderTransientError
from halfblood.generation.providers.base import (
    GenerationResult,
    GenerationUsage,
    ProviderCapabilities,
)
from halfblood.generation.schema import AnnotationDraft, RecordAnnotations

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
SAMPLE_PDF = FIXTURES_DIR / "potions_textbook.pdf"


class _FakeProvider:
    """A minimal, protocol-compatible ``LLMProvider`` test double.

    Each ``complete()`` call consumes the next scripted item: an exception
    instance is raised, a list of annotation dicts becomes a successful
    ``GenerationResult``.
    """

    def __init__(self, script: list) -> None:
        self._script = list(script)
        self._i = 0

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            supports_tool_calling=True,
            supports_json_schema=False,
            supports_strict_json_schema=False,
        )

    def complete(self, request: object) -> GenerationResult:
        item = self._script[self._i]
        self._i += 1
        if isinstance(item, BaseException):
            raise item
        parsed = RecordAnnotations(
            annotations=[AnnotationDraft(**annotation) for annotation in item]
        )
        return GenerationResult(
            parsed=parsed,
            request_id="req_fake",
            finish_reason="tool_use",
            usage=GenerationUsage(input_tokens=10, output_tokens=10),
            latency_seconds=0.01,
            structured_output_mode="tool",
        )


def _generator_with(script: list) -> AnnotationGenerator:
    return AnnotationGenerator(provider=_FakeProvider(script))


def _page(n: int, text: str) -> PageContent:
    return PageContent(page_number=n, text=text, width=612.0, height=792.0)


GOOD_ANNOTATION = {
    "target_text": "Real page text two.",
    "annotation_type": "doodle_note",
    "content": "Obviously.",
    "confidence": 0.9,
    "position": "margin_right",
}


def test_all_pages_failing_raises() -> None:
    gen = _generator_with([ProviderTransientError("boom"), ProviderTransientError("boom")])
    pages = [_page(1, "Real page text one."), _page(2, "Real page text two.")]
    with pytest.raises(AllPagesFailedError):
        gen.generate_for_document(pages, concurrency=1)


def test_all_pages_failing_report_has_per_page_statuses() -> None:
    gen = _generator_with([ProviderTransientError("boom"), ProviderTransientError("boom")])
    pages = [_page(1, "Real page text one."), _page(2, "Real page text two.")]
    with pytest.raises(AllPagesFailedError) as excinfo:
        gen.generate_for_document(pages, concurrency=1)

    report = excinfo.value.report
    assert report is not None
    assert len(report.statuses) == 2
    assert all(status.status == "failed" for status in report.statuses)
    assert sorted(status.ordinal for status in report.statuses) == [1, 2]
    assert all(status.error is not None for status in report.statuses)
    assert report.failed_pages == [1, 2]
    assert report.all_attempted_failed is True


def test_partial_failure_records_and_continues() -> None:
    # page 1 fails; page 2 succeeds with one annotation.
    gen = _generator_with([ProviderTransientError("boom"), [GOOD_ANNOTATION]])
    pages = [_page(1, "Real page text one."), _page(2, "Real page text two.")]

    # Pin to k=1: _FakeProvider uses a sequential index counter (_i) that is
    # not thread-safe; these tests exercise failure-handling semantics, not
    # concurrency.  See test_async_generation.py for k>1 failure injection tests.
    plan = gen.generate_for_document(pages, concurrency=1)

    assert gen.failed_pages == [1]
    assert plan.pages[0].annotations == []
    assert len(plan.pages[1].annotations) == 1


def test_partial_incomplete_response_records_failure_and_continues() -> None:
    """A different ProviderError subclass must be caught too -- the except
    clause is on the base ProviderError, not one specific subclass."""
    gen = _generator_with([IncompleteResponseError("truncated"), [GOOD_ANNOTATION]])
    pages = [_page(1, "Real page text one."), _page(2, "Real page text two.")]

    plan = gen.generate_for_document(pages, concurrency=1)

    assert gen.failed_pages == [1]
    assert len(plan.pages[1].annotations) == 1


def test_all_empty_pages_do_not_raise() -> None:
    # No provider call is made for blank pages, so nothing "failed".
    gen = _generator_with([])  # complete() would IndexError if ever called
    pages = [_page(1, "   \n\t "), _page(2, "")]
    plan = gen.generate_for_document(pages, concurrency=1)
    assert gen.failed_pages == []
    assert all(p.annotations == [] for p in plan.pages)


def test_generate_for_page_still_returns_empty_on_error() -> None:
    """Public single-page contract is unchanged: returns [] on ProviderError."""
    gen = _generator_with([ProviderTransientError("boom")])
    assert gen.generate_for_page("Real page text.", page_number=1) == []


def test_generate_for_page_still_returns_empty_on_incomplete_response() -> None:
    gen = _generator_with([IncompleteResponseError("truncated")])
    assert gen.generate_for_page("Real page text.", page_number=1) == []


def test_cli_annotate_exits_nonzero_when_all_pages_fail(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-fake-key-not-real")

    def _boom(self: AnnotationGenerator, pages: list[PageContent], **_kw: object) -> None:
        raise AllPagesFailedError("all 3 page(s) sent to the API failed")

    monkeypatch.setattr(AnnotationGenerator, "generate_for_document", _boom)

    out = tmp_path / "out.pdf"
    result = CliRunner().invoke(cli_main, ["annotate", str(SAMPLE_PDF), "-o", str(out)])

    assert result.exit_code != 0
    assert "Traceback" not in result.output  # clean ClickException, not a crash


def test_no_type_ignore_suppressions_in_migrated_modules() -> None:
    """AUD hygiene item, retargeted to the P1-T5 migration: no ``# type:
    ignore`` suppression should be needed in the rewritten generator or the
    new Anthropic provider module. A green mypy gate does not by itself
    prove this -- ``warn_unused_ignores`` only flags *unnecessary* ignores,
    never load-bearing ones that hide a real type error."""
    targets = [
        Path("src/halfblood/annotation_generator.py"),
        Path("src/halfblood/generation/providers/anthropic.py"),
    ]
    offenders = [str(f) for f in targets if "# type: ignore" in f.read_text(encoding="utf-8")]
    assert not offenders, f"type: ignore suppressions present in: {offenders}"
