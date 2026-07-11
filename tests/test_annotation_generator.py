"""P0-T1 — harden Anthropic response handling on the real Message path.

Covers AUD-05, AUD-10, AUD-14, AUD-21, AUD-23 and lint findings L-1/L-3.

Production calls ``client.messages.create(...)`` with a forced ``tool_use`` and
reads a real ``anthropic.types.Message``. The old suite exercised the JSON
*string* fallback that production never uses (AUD-10), so a broken Message
branch could stay green while every real call returned ``[]``. These tests
drive the production Message path with **real SDK block types** and pin:

    * truncated responses (``stop_reason="max_tokens"``) are a page FAILURE,
      not a silent empty page (AUD-05 / AUD-21);
    * a ``record_annotations`` block whose ``input`` is ``None`` / ``{}`` / a
      non-object is malformed -> page failure, never a successful empty
      result (AUD-14);
    * a well-formed ``{"annotations": []}`` with a clean finish is SUCCESS
      (a valid empty array is not a failure);
    * an unrelated text block alongside exactly one tool block still parses,
      and logs a protocol warning;
    * no matching tool block (or a wrongly-named one) is an explicit page
      failure;
    * ``anthropic.APIError`` still flows to the merged failed-page path and an
      all-failed document raises ``AllPagesFailedError`` (AUD-23 / AUD-16);
    * a well-formed response whose individual items fail validation is an
      empty SUCCESS (item drops), distinct from a malformed transport
      response (page failure);
    * non-tool content blocks are narrowed by ``isinstance`` and never
      accessed through ``.input`` (L-3);
    * the L-1/L-3 ``# type: ignore`` suppressions are gone from the source
      (mypy enforces the rest through the gate).

The public single-page contract is unchanged: ``generate_for_page`` returns
``[]`` on any failure. Failures are observable through ``failed_pages`` /
``AllPagesFailedError`` on ``generate_for_document``.

No network calls are made anywhere in this file.
"""

from __future__ import annotations

import logging
import types

import anthropic
import httpx
import pytest
from anthropic.types import Message, TextBlock, ToolUseBlock, Usage

import halfblood.annotation_generator as ag_module
from halfblood.annotation_generator import AllPagesFailedError, AnnotationGenerator
from halfblood.document_processor import PageContent
from halfblood.models import AnnotationType

# A valid annotation payload whose target appears in the page text used below.
_VALID_ANNOTATION = {
    "target_text": "Sopophorous bean",
    "annotation_type": "correction",
    "content": "Crush it, don't cut it.",
    "confidence": 0.9,
    "position": "margin_right",
}
_PAGE_TEXT = "The Sopophorous bean is best crushed with the flat of a silver dagger."


# ---------------------------------------------------------------------------
# Fixtures: real SDK Message/blocks + a scripted client boundary
# ---------------------------------------------------------------------------


def _message(content: list[object], stop_reason: str = "tool_use") -> Message:
    """A real ``anthropic.types.Message`` wrapping the given content blocks."""
    return Message(
        id="msg_test",
        content=content,  # type: ignore[arg-type]  # mixed real blocks by design
        model="claude-sonnet-5",
        role="assistant",
        stop_reason=stop_reason,  # type: ignore[arg-type]  # test uses literal strings
        stop_sequence=None,
        type="message",
        usage=Usage(input_tokens=1, output_tokens=1),
    )


def _tool_block(payload: object, name: str = "record_annotations") -> ToolUseBlock:
    """A real ``ToolUseBlock``. Uses ``model_construct`` so malformed/truncated
    ``input`` values (``None``, ``{}``, non-objects) can be simulated on a
    genuine SDK instance, exactly as a bad API payload would arrive."""
    return ToolUseBlock.model_construct(
        id="toolu_test", input=payload, name=name, type="tool_use"
    )


def _text_block(text: str = "Here are my notes:") -> TextBlock:
    return TextBlock(text=text, type="text")


class _ScriptedMessages:
    """Stand-in for ``client.messages``: each ``create()`` returns the next
    scripted Message, or raises it if it is an exception."""

    def __init__(self, script: list[object]) -> None:
        self._script = list(script)
        self._i = 0

    def create(self, **_kwargs: object) -> Message:
        item = self._script[self._i]
        self._i += 1
        if isinstance(item, BaseException):
            raise item
        assert isinstance(item, Message)
        return item


def _generator(script: list[object]) -> AnnotationGenerator:
    gen = AnnotationGenerator(api_key="sk-ant-test-fake-key-not-real")
    gen.client = types.SimpleNamespace(messages=_ScriptedMessages(script))  # type: ignore[assignment]
    return gen


def _page(n: int, text: str) -> PageContent:
    return PageContent(page_number=n, text=text, width=612.0, height=792.0)


def _api_error() -> anthropic.APIError:
    return anthropic.APIConnectionError(
        request=httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    )


# ---------------------------------------------------------------------------
# Success paths (guards — these must stay green)
# ---------------------------------------------------------------------------


def test_valid_empty_annotations_is_success() -> None:
    gen = _generator([_message([_tool_block({"annotations": []})])])
    plan = gen.generate_for_document([_page(1, _PAGE_TEXT)])
    assert gen.failed_pages == []
    assert plan.pages[0].annotations == []


def test_tool_use_message_parses_fields() -> None:
    gen = _generator([_message([_tool_block({"annotations": [_VALID_ANNOTATION]})])])
    result = gen.generate_for_page(_PAGE_TEXT, page_number=2)
    assert len(result) == 1
    ann = result[0]
    assert ann.page == 2
    assert ann.annotation_type == AnnotationType.CORRECTION
    assert ann.target_text == "Sopophorous bean"
    assert ann.confidence == pytest.approx(0.9)
    assert ann.position == "margin_right"


def test_defaults_applied_for_omitted_optional_fields() -> None:
    anno = {"target_text": "silver dagger", "annotation_type": "doodle_note", "content": "Obviously."}
    gen = _generator([_message([_tool_block({"annotations": [anno]})])])
    result = gen.generate_for_page(_PAGE_TEXT, page_number=1)
    assert len(result) == 1
    assert result[0].confidence == pytest.approx(0.8)
    assert result[0].position == "margin_right"


def test_invalid_individual_annotation_is_dropped_not_fatal() -> None:
    good = {"target_text": "Sopophorous bean", "annotation_type": "warning", "content": "Careful.", "confidence": 0.5}
    bad = {"target_text": "silver dagger", "annotation_type": "warning", "content": "Drop me.", "confidence": 42.0}
    gen = _generator([_message([_tool_block({"annotations": [good, bad, "not-a-dict"]})])])
    result = gen.generate_for_page(_PAGE_TEXT, page_number=7)
    assert len(result) == 1
    assert result[0].content == "Careful."


def test_all_items_invalid_is_empty_success_not_page_failure() -> None:
    # A well-formed response whose only item is invalid drops to empty, but the
    # transport response itself is valid -> success, NOT a page failure.
    anno = {"target_text": "Sopophorous bean", "annotation_type": "not_a_real_type", "content": "N/A"}
    gen = _generator([_message([_tool_block({"annotations": [anno]})])])
    plan = gen.generate_for_document([_page(1, _PAGE_TEXT)])
    assert gen.failed_pages == []
    assert plan.pages[0].annotations == []


def test_api_error_is_a_page_failure_and_all_failed_raises() -> None:
    gen = _generator([_api_error()])
    with pytest.raises(AllPagesFailedError):
        gen.generate_for_document([_page(1, _PAGE_TEXT)])
    assert gen.failed_pages == [1]


# ---------------------------------------------------------------------------
# Failure paths (RED — must not silently succeed)
# ---------------------------------------------------------------------------


def test_truncated_response_is_a_page_failure() -> None:
    # stop_reason="max_tokens" with an empty tool input is truncation, which
    # currently looks identical to a legitimately empty page (AUD-05/AUD-21).
    gen = _generator([_message([_tool_block({})], stop_reason="max_tokens")])
    with pytest.raises(AllPagesFailedError):
        gen.generate_for_document([_page(1, _PAGE_TEXT)])
    assert gen.failed_pages == [1]


@pytest.mark.parametrize("bad_input", [None, {}, "not-an-object", 42, ["a", "list"]])
def test_malformed_tool_input_is_a_page_failure(bad_input: object) -> None:
    # A record_annotations block whose input is missing/None/non-object is a
    # malformed response, not a successful empty page (AUD-14).
    gen = _generator([_message([_tool_block(bad_input)])])
    with pytest.raises(AllPagesFailedError):
        gen.generate_for_document([_page(1, _PAGE_TEXT)])
    assert gen.failed_pages == [1]


def test_annotations_not_a_list_is_a_page_failure() -> None:
    gen = _generator([_message([_tool_block({"annotations": {"nope": 1}})])])
    with pytest.raises(AllPagesFailedError):
        gen.generate_for_document([_page(1, _PAGE_TEXT)])
    assert gen.failed_pages == [1]


def test_no_matching_tool_block_is_a_page_failure() -> None:
    # Forced tool_choice must yield a tool block; only a text block means the
    # response is unusable and must fail explicitly, not return [].
    gen = _generator([_message([_text_block("I refuse.")], stop_reason="end_turn")])
    with pytest.raises(AllPagesFailedError):
        gen.generate_for_document([_page(1, _PAGE_TEXT)])
    assert gen.failed_pages == [1]


def test_wrongly_named_tool_block_is_a_page_failure() -> None:
    gen = _generator([_message([_tool_block({"annotations": []}, name="something_else")])])
    with pytest.raises(AllPagesFailedError):
        gen.generate_for_document([_page(1, _PAGE_TEXT)])
    assert gen.failed_pages == [1]


def test_generate_for_page_still_returns_empty_on_truncation() -> None:
    # Public single-page contract unchanged: failure surfaces as [], the record
    # of failure lives on the document-level path.
    gen = _generator([_message([_tool_block({})], stop_reason="max_tokens")])
    assert gen.generate_for_page(_PAGE_TEXT, page_number=1) == []


def test_partial_truncation_records_failure_and_continues() -> None:
    # Page 1 truncates; page 2 is a valid single annotation. Not all pages
    # failed, so no raise; the truncated page is recorded.
    gen = _generator(
        [
            _message([_tool_block({})], stop_reason="max_tokens"),
            _message([_tool_block({"annotations": [_VALID_ANNOTATION]})]),
        ]
    )
    plan = gen.generate_for_document([_page(1, _PAGE_TEXT), _page(2, _PAGE_TEXT)])
    assert gen.failed_pages == [1]
    assert plan.pages[0].annotations == []
    assert len(plan.pages[1].annotations) == 1


# ---------------------------------------------------------------------------
# Protocol warning + block narrowing (L-3)
# ---------------------------------------------------------------------------


def test_text_block_alongside_tool_block_parses_with_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    gen = _generator(
        [_message([_text_block("Preamble."), _tool_block({"annotations": [_VALID_ANNOTATION]})])]
    )
    with caplog.at_level(logging.WARNING, logger="halfblood.annotation_generator"):
        result = gen.generate_for_page(_PAGE_TEXT, page_number=1)
    assert len(result) == 1
    assert any(r.levelno == logging.WARNING for r in caplog.records), (
        "an unexpected extra content block should be recorded as a protocol warning"
    )


def test_non_tool_block_is_never_accessed_via_input() -> None:
    # A real TextBlock has no `.input`; production must narrow with isinstance
    # and skip it without AttributeError, still extracting from the tool block.
    gen = _generator([_message([_text_block("prose"), _tool_block({"annotations": [_VALID_ANNOTATION]})])])
    result = gen.generate_for_page(_PAGE_TEXT, page_number=1)
    assert len(result) == 1


def test_real_textblock_has_no_input_attribute() -> None:
    # Documents WHY isinstance narrowing matters: the union member we must not
    # touch genuinely lacks `.input`.
    assert not hasattr(_text_block(), "input")


# ---------------------------------------------------------------------------
# L-1 / L-3 acceptance: the type: ignore suppressions are gone
# ---------------------------------------------------------------------------


def test_no_type_ignore_suppressions_remain_in_generator() -> None:
    assert ag_module.__file__ is not None
    with open(ag_module.__file__, encoding="utf-8") as fh:
        source = fh.read()
    assert "type: ignore[call-overload]" not in source, "L-1: SDK call args must be typed"
    assert "type: ignore[union-attr]" not in source, "L-3: block.input access must be narrowed"
