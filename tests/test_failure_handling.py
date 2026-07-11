"""Regression tests for AUD-16: surface API failures instead of silently
producing empty annotated books.

Before this fix, ``AnnotationGenerator.generate_for_page`` caught
``anthropic.APIError`` and returned ``[]`` with no user-visible signal, so a
dead model (or a bad key) produced an empty book with exit code 0. These tests
pin the new contract:

    * ``generate_for_document`` records per-page failures on ``failed_pages``.
    * If *every* page that was sent to the API failed, it raises
      ``AllPagesFailedError`` (so the CLI can exit non-zero).
    * A partial failure does NOT raise — surviving pages still get annotations.
    * The public ``generate_for_page`` still returns ``[]`` on error (its
      documented contract is unchanged).
    * The CLI turns ``AllPagesFailedError`` into a clean non-zero exit, not a
      raw traceback.

No real network calls are made anywhere in this file.
"""

from __future__ import annotations

import types
from pathlib import Path

import anthropic
import httpx
import pytest
from click.testing import CliRunner

from halfblood.annotation_generator import AllPagesFailedError, AnnotationGenerator
from halfblood.cli import main as cli_main
from halfblood.document_processor import PageContent

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
SAMPLE_PDF = FIXTURES_DIR / "potions_textbook.pdf"


def _api_error() -> anthropic.APIError:
    """A real ``anthropic.APIError`` subclass instance the generator will catch."""
    return anthropic.APIConnectionError(
        request=httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    )


def _tool_use_message(annotations: list[dict]) -> types.SimpleNamespace:
    """Minimal fake ``anthropic.types.Message`` carrying a record_annotations block."""
    block = types.SimpleNamespace(
        type="tool_use", name="record_annotations", input={"annotations": annotations}
    )
    return types.SimpleNamespace(content=[block])


class _ScriptedMessages:
    """Stand-in for ``client.messages``: each ``create()`` consumes the next
    scripted item — an exception is raised, a list becomes a tool_use message."""

    def __init__(self, script: list) -> None:
        self._script = list(script)
        self._i = 0

    def create(self, **_kwargs: object) -> types.SimpleNamespace:
        item = self._script[self._i]
        self._i += 1
        if isinstance(item, BaseException):
            raise item
        return _tool_use_message(item)


def _generator_with(script: list) -> AnnotationGenerator:
    gen = AnnotationGenerator(api_key="sk-ant-test-fake-key-not-real")
    gen.client = types.SimpleNamespace(messages=_ScriptedMessages(script))  # type: ignore[assignment]
    return gen


def _page(n: int, text: str) -> PageContent:
    return PageContent(page_number=n, text=text, width=612.0, height=792.0)


def test_all_pages_failing_raises() -> None:
    gen = _generator_with([_api_error(), _api_error()])
    pages = [_page(1, "Real page text one."), _page(2, "Real page text two.")]
    with pytest.raises(AllPagesFailedError):
        gen.generate_for_document(pages)


def test_partial_failure_records_and_continues() -> None:
    # page 1 fails; page 2 succeeds with one annotation.
    good = [{"target_text": "Real page text two.", "annotation_type": "doodle_note",
             "content": "Obviously.", "confidence": 0.9, "position": "margin_right"}]
    gen = _generator_with([_api_error(), good])
    pages = [_page(1, "Real page text one."), _page(2, "Real page text two.")]

    plan = gen.generate_for_document(pages)

    assert gen.failed_pages == [1]
    assert plan.pages[0].annotations == []
    assert len(plan.pages[1].annotations) == 1


def test_all_empty_pages_do_not_raise() -> None:
    # No API call is made for blank pages, so nothing "failed".
    gen = _generator_with([])  # create() would IndexError if ever called
    pages = [_page(1, "   \n\t "), _page(2, "")]
    plan = gen.generate_for_document(pages)
    assert gen.failed_pages == []
    assert all(p.annotations == [] for p in plan.pages)


def test_generate_for_page_still_returns_empty_on_error() -> None:
    """Public single-page contract is unchanged: returns [] on APIError."""
    gen = _generator_with([_api_error()])
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
