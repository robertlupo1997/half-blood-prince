"""Controller-authored tests for P1-T6 structured-output negotiation and
bounded parsing (architecture §4.3; plan P1-T6).

Pins:

* ``StructuredOutputPolicy`` chooses modes deterministically: ``auto`` order
  is forced tool/function -> strict JSON Schema -> prompt JSON, filtered by
  ``ProviderCapabilities``; ``strict`` disables the prompt fallback; a pinned
  unsupported mode raises ``ProviderCapabilityError``; exactly one capability
  downgrade is permitted under ``auto`` and never for content/schema errors.
* The policy vocabulary is canonical ``tool|json-schema|prompt`` and never
  emits ``"function"`` (that wire spelling is the P1-T7 adapter's job).
* ``parse_tool_mode`` reads the OpenAI-compatible shape
  (``message['tool_calls'][*]['function']['arguments']`` as a JSON string,
  plus legacy ``message['function_call']``): exactly one named call, decoded
  and validated.
* ``parse_json_schema_mode`` parses one ``content`` document and distinguishes
  refusal / incomplete / malformed JSON.
* ``parse_prompt_mode`` extracts one JSON object conservatively via a
  quote/escape-aware state machine — a full object, one fenced block, or the
  first balanced top-level object — rejecting greedy extraction, duplicate
  objects, non-object roots, and never altering a value.
* ``bounded_json_decode`` enforces explicit byte/depth/item/string limits.
* Structural failures raise ``StructuredOutputError``; a decoded JSON object
  that fails ``RecordAnnotations`` raises ``AnnotationValidationError``; an
  empty ``annotations`` list is a valid success. (§4.3, NOT §4.6 item-drops.)
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from halfblood.generation.errors import (
    AnnotationValidationError,
    IncompleteResponseError,
    ProviderCapabilityError,
    ProviderSafetyRefusal,
    StructuredOutputError,
)
from halfblood.generation.providers.base import ProviderCapabilities
from halfblood.generation.schema import RecordAnnotations
from halfblood.generation.structured_output import (
    AUTO_ORDER,
    DEFAULT_PARSE_LIMITS,
    TOOL_NAME,
    ParseLimits,
    StructuredOutputPolicy,
    bounded_json_decode,
    parse_json_schema_mode,
    parse_prompt_mode,
    parse_tool_mode,
)

# --------------------------------------------------------------------------- #
# Fixtures / helpers
# --------------------------------------------------------------------------- #


def _draft(target: str = "the mooncalf dung", content: str = "crush, don't cut") -> dict[str, Any]:
    """A minimal valid AnnotationDraft payload (confidence/position default)."""
    return {
        "target_text": target,
        "annotation_type": "correction",
        "content": content,
    }


def _record_obj(*drafts: dict[str, Any]) -> dict[str, Any]:
    return {"annotations": list(drafts)}


def _all_caps(**overrides: bool) -> ProviderCapabilities:
    values: dict[str, Any] = {
        "supports_tool_calling": True,
        "supports_json_schema": True,
        "supports_strict_json_schema": True,
        "supports_prompt_fallback": True,
    }
    values.update(overrides)
    return ProviderCapabilities(**values)


def _openai_tool_message(arguments: str, *, name: str = TOOL_NAME) -> dict[str, Any]:
    return {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {"id": "call_1", "type": "function", "function": {"name": name, "arguments": arguments}}
        ],
    }


# --------------------------------------------------------------------------- #
# StructuredOutputPolicy — mode negotiation
# --------------------------------------------------------------------------- #


def test_auto_order_constant_matches_spec() -> None:
    assert AUTO_ORDER == ("tool", "json-schema", "prompt")


def test_auto_full_capabilities_selects_tool_first() -> None:
    policy = StructuredOutputPolicy(pin="auto")
    caps = _all_caps()
    assert policy.candidate_chain(caps) == ("tool", "json-schema", "prompt")
    assert policy.select(caps) == "tool"


def test_auto_without_tool_support_selects_json_schema() -> None:
    policy = StructuredOutputPolicy(pin="auto")
    caps = _all_caps(supports_tool_calling=False)
    assert policy.select(caps) == "json-schema"
    assert policy.candidate_chain(caps) == ("json-schema", "prompt")


def test_auto_only_prompt_supported_selects_prompt() -> None:
    policy = StructuredOutputPolicy(pin="auto")
    caps = _all_caps(supports_tool_calling=False, supports_json_schema=False)
    assert policy.select(caps) == "prompt"


def test_auto_strict_drops_prompt_from_chain() -> None:
    policy = StructuredOutputPolicy(pin="auto", strict=True)
    caps = _all_caps()
    assert policy.candidate_chain(caps) == ("tool", "json-schema")


def test_strict_with_only_prompt_available_raises() -> None:
    policy = StructuredOutputPolicy(pin="auto", strict=True)
    caps = _all_caps(supports_tool_calling=False, supports_json_schema=False)
    assert policy.candidate_chain(caps) == ()
    with pytest.raises(ProviderCapabilityError):
        policy.select(caps)


def test_pinned_prompt_under_strict_raises() -> None:
    policy = StructuredOutputPolicy(pin="prompt", strict=True)
    with pytest.raises(ProviderCapabilityError):
        policy.select(_all_caps())


@pytest.mark.parametrize(
    ("pin", "cap_override"),
    [
        ("tool", {"supports_tool_calling": False}),
        ("json-schema", {"supports_json_schema": False}),
        ("prompt", {"supports_prompt_fallback": False}),
    ],
)
def test_pinned_unsupported_mode_raises_capability_error(
    pin: str, cap_override: dict[str, bool]
) -> None:
    policy = StructuredOutputPolicy(pin=pin)  # type: ignore[arg-type]
    with pytest.raises(ProviderCapabilityError) as excinfo:
        policy.select(_all_caps(**cap_override))
    assert excinfo.value.requested_mode == pin


def test_pinned_supported_mode_returns_that_mode() -> None:
    for pin in ("tool", "json-schema", "prompt"):
        policy = StructuredOutputPolicy(pin=pin)  # type: ignore[arg-type]
        assert policy.select(_all_caps()) == pin
        assert policy.candidate_chain(_all_caps()) == (pin,)


def test_policy_never_emits_function_mode() -> None:
    # Canonical vocabulary is tool|json-schema|prompt; "function" is a wire
    # spelling the adapter owns, never the policy.
    for pin in ("auto", "tool", "json-schema", "prompt"):
        policy = StructuredOutputPolicy(pin=pin)  # type: ignore[arg-type]
        for mode in policy.candidate_chain(_all_caps()):
            assert mode in ("tool", "json-schema", "prompt")


def test_next_mode_walks_auto_chain_then_stops() -> None:
    policy = StructuredOutputPolicy(pin="auto")
    caps = _all_caps()
    assert policy.next_mode("tool", caps) == "json-schema"
    assert policy.next_mode("json-schema", caps) == "prompt"
    assert policy.next_mode("prompt", caps) is None


def test_next_mode_none_when_pinned() -> None:
    policy = StructuredOutputPolicy(pin="tool")
    assert policy.next_mode("tool", _all_caps()) is None


def test_allows_downgrade_only_for_capability_error_once_under_auto() -> None:
    policy = StructuredOutputPolicy(pin="auto")
    err = ProviderCapabilityError("unsupported", status_code=400, requested_mode="tool")
    assert policy.allows_downgrade(err, already_downgraded=False) is True
    # One total: after a downgrade has happened, no further downgrade.
    assert policy.allows_downgrade(err, already_downgraded=True) is False


def test_allows_downgrade_false_when_pinned() -> None:
    policy = StructuredOutputPolicy(pin="tool")
    err = ProviderCapabilityError("unsupported", status_code=400, requested_mode="tool")
    assert policy.allows_downgrade(err, already_downgraded=False) is False


@pytest.mark.parametrize(
    "error",
    [
        StructuredOutputError("bad json"),
        AnnotationValidationError("invalid item"),
        IncompleteResponseError("truncated"),
        ProviderSafetyRefusal("refused"),
    ],
)
def test_content_and_schema_errors_never_downgrade(error: Exception) -> None:
    policy = StructuredOutputPolicy(pin="auto")
    assert policy.allows_downgrade(error, already_downgraded=False) is False


# --------------------------------------------------------------------------- #
# parse_tool_mode — OpenAI-compatible forced tool/function calling
# --------------------------------------------------------------------------- #


def test_tool_mode_single_named_call_parses() -> None:
    message = _openai_tool_message(json.dumps(_record_obj(_draft())))
    result = parse_tool_mode(message)
    assert isinstance(result, RecordAnnotations)
    assert len(result.annotations) == 1
    assert result.annotations[0].content == "crush, don't cut"


def test_tool_mode_empty_annotations_list_is_success() -> None:
    message = _openai_tool_message(json.dumps({"annotations": []}))
    result = parse_tool_mode(message)
    assert result.annotations == []


def test_tool_mode_legacy_function_call_supported() -> None:
    message = {
        "role": "assistant",
        "content": None,
        "function_call": {"name": TOOL_NAME, "arguments": json.dumps(_record_obj(_draft()))},
    }
    result = parse_tool_mode(message)
    assert len(result.annotations) == 1


def test_tool_mode_no_matching_call_raises() -> None:
    message = _openai_tool_message(json.dumps(_record_obj(_draft())), name="something_else")
    with pytest.raises(StructuredOutputError):
        parse_tool_mode(message)


def test_tool_mode_multiple_matching_calls_raises() -> None:
    args = json.dumps(_record_obj(_draft()))
    message = {
        "role": "assistant",
        "tool_calls": [
            {"id": "a", "type": "function", "function": {"name": TOOL_NAME, "arguments": args}},
            {"id": "b", "type": "function", "function": {"name": TOOL_NAME, "arguments": args}},
        ],
    }
    with pytest.raises(StructuredOutputError):
        parse_tool_mode(message)


def test_tool_mode_arguments_not_a_string_raises() -> None:
    # A dict where the wire contract requires a JSON *string*.
    message = {
        "role": "assistant",
        "tool_calls": [
            {"id": "a", "type": "function", "function": {"name": TOOL_NAME, "arguments": {"annotations": []}}},
        ],
    }
    with pytest.raises(StructuredOutputError):
        parse_tool_mode(message)


def test_tool_mode_malformed_json_arguments_raises_structured() -> None:
    message = _openai_tool_message("{not valid json")
    with pytest.raises(StructuredOutputError):
        parse_tool_mode(message)


def test_tool_mode_non_object_root_raises_structured() -> None:
    message = _openai_tool_message("[]")
    with pytest.raises(StructuredOutputError):
        parse_tool_mode(message)


def test_tool_mode_object_failing_validation_raises_annotation_error() -> None:
    # Blank target_text violates min_length=1 -> whole-object validation fails.
    bad = {"annotations": [{"target_text": "", "annotation_type": "correction", "content": "x"}]}
    message = _openai_tool_message(json.dumps(bad))
    with pytest.raises(AnnotationValidationError):
        parse_tool_mode(message)


# --------------------------------------------------------------------------- #
# parse_json_schema_mode
# --------------------------------------------------------------------------- #


def test_json_schema_mode_valid_content_parses() -> None:
    message = {"role": "assistant", "content": json.dumps(_record_obj(_draft()))}
    result = parse_json_schema_mode(message, finish_reason="stop")
    assert len(result.annotations) == 1


def test_json_schema_mode_refusal_field_raises_safety() -> None:
    message = {"role": "assistant", "content": None, "refusal": "I can't help with that."}
    with pytest.raises(ProviderSafetyRefusal):
        parse_json_schema_mode(message, finish_reason="stop")


def test_json_schema_mode_content_filter_finish_raises_safety() -> None:
    message = {"role": "assistant", "content": json.dumps(_record_obj(_draft()))}
    with pytest.raises(ProviderSafetyRefusal):
        parse_json_schema_mode(message, finish_reason="content_filter")


def test_json_schema_mode_length_finish_raises_incomplete() -> None:
    # Truncated content + length finish -> IncompleteResponseError, not malformed.
    message = {"role": "assistant", "content": '{"annotations": [{"target'}
    with pytest.raises(IncompleteResponseError):
        parse_json_schema_mode(message, finish_reason="length")


def test_json_schema_mode_malformed_content_raises_structured() -> None:
    message = {"role": "assistant", "content": "{not json"}
    with pytest.raises(StructuredOutputError):
        parse_json_schema_mode(message, finish_reason="stop")


def test_json_schema_mode_non_string_content_raises_structured() -> None:
    message = {"role": "assistant", "content": {"annotations": []}}
    with pytest.raises(StructuredOutputError):
        parse_json_schema_mode(message, finish_reason="stop")


# --------------------------------------------------------------------------- #
# parse_prompt_mode — conservative extraction
# --------------------------------------------------------------------------- #


def test_prompt_mode_bare_object_parses() -> None:
    result = parse_prompt_mode(json.dumps(_record_obj(_draft())))
    assert len(result.annotations) == 1


def test_prompt_mode_object_with_bom_and_whitespace_parses() -> None:
    result = parse_prompt_mode("﻿\n  " + json.dumps(_record_obj(_draft())) + "\n")
    assert len(result.annotations) == 1


def test_prompt_mode_single_json_fence_parses() -> None:
    payload = json.dumps(_record_obj(_draft()))
    text = f"Here is the result:\n```json\n{payload}\n```\nThanks!"
    result = parse_prompt_mode(text)
    assert len(result.annotations) == 1


def test_prompt_mode_untagged_fence_parses() -> None:
    payload = json.dumps(_record_obj(_draft()))
    text = f"```\n{payload}\n```"
    result = parse_prompt_mode(text)
    assert len(result.annotations) == 1


def test_prompt_mode_first_balanced_object_amid_trailing_prose() -> None:
    payload = json.dumps(_record_obj(_draft()))
    text = f"{payload}\n\nLet me know if you need anything else."
    result = parse_prompt_mode(text)
    assert len(result.annotations) == 1


def test_prompt_mode_braces_inside_string_value_do_not_truncate() -> None:
    # A content value that itself contains braces and an escaped quote must
    # survive: the state machine must ignore in-string braces.
    tricky = 'use a {curly} brace and a \\"quote\\" — {not json}'
    raw = '{"annotations": [{"target_text": "x", "annotation_type": "correction", '
    raw += '"content": "' + tricky + '"}]}'
    result = parse_prompt_mode("prefix prose " + raw + " suffix prose")
    assert result.annotations[0].content == 'use a {curly} brace and a "quote" — {not json}'


def test_prompt_mode_value_fidelity_backticks_and_json_word_survive() -> None:
    # Value cleanup must be structural only — never rewrite a value.
    content = "wrap in ```json fences``` and keep me exact"
    payload = json.dumps({"annotations": [{"target_text": "t", "annotation_type": "insight", "content": content}]})
    result = parse_prompt_mode(payload)
    assert result.annotations[0].content == content


def test_prompt_mode_duplicate_top_level_objects_rejected() -> None:
    payload = json.dumps(_record_obj(_draft()))
    with pytest.raises(StructuredOutputError):
        parse_prompt_mode(payload + "\n" + payload)


def test_prompt_mode_greedy_span_between_two_objects_rejected() -> None:
    # A greedy `{.*}` regex would merge these into one invalid blob; the
    # state machine must see TWO top-level objects and reject.
    text = '{"annotations": []} garbage {"annotations": []}'
    with pytest.raises(StructuredOutputError):
        parse_prompt_mode(text)


def test_prompt_mode_multiple_fences_rejected() -> None:
    payload = json.dumps(_record_obj(_draft()))
    text = f"```json\n{payload}\n```\nand also\n```json\n{payload}\n```"
    with pytest.raises(StructuredOutputError):
        parse_prompt_mode(text)


def test_prompt_mode_single_non_json_fence_before_json_fence_parses() -> None:
    # A usage example in a non-json code block before the json result must be
    # invisible (§4.3: "one fenced json block"), not counted as a fence.
    payload = json.dumps(_record_obj(_draft()))
    text = f"```python\nexample()\n```\n```json\n{payload}\n```"
    result = parse_prompt_mode(text)
    assert len(result.annotations) == 1
    assert result.annotations[0].content == "crush, don't cut"


def test_prompt_mode_multiple_non_json_fences_before_json_fence_parses() -> None:
    # Two or more non-json fences before the json block must not be miscounted
    # as extra fenced blocks (the json block is the only real one).
    payload = json.dumps(_record_obj(_draft()))
    text = "```python\nfoo\n```\n```bash\nbar\n```\n" + f"```json\n{payload}\n```"
    result = parse_prompt_mode(text)
    assert len(result.annotations) == 1
    assert result.annotations[0].content == "crush, don't cut"


def test_prompt_mode_no_object_raises_structured() -> None:
    with pytest.raises(StructuredOutputError):
        parse_prompt_mode("There are no annotations to report here.")


def test_prompt_mode_top_level_array_root_rejected() -> None:
    # A top-level array is a non-object root -> structural rejection.
    with pytest.raises(StructuredOutputError):
        parse_prompt_mode(json.dumps([_draft()]))


def test_prompt_mode_object_failing_validation_raises_annotation_error() -> None:
    bad = json.dumps({"annotations": [{"target_text": "t", "annotation_type": "not_a_type", "content": "c"}]})
    with pytest.raises(AnnotationValidationError):
        parse_prompt_mode(bad)


# --------------------------------------------------------------------------- #
# bounded_json_decode — explicit limits
# --------------------------------------------------------------------------- #


def test_bounded_decode_accepts_within_limits() -> None:
    assert bounded_json_decode(json.dumps(_record_obj(_draft()))) == _record_obj(_draft())


def test_bounded_decode_rejects_oversized_bytes() -> None:
    limits = ParseLimits(max_response_bytes=64)
    raw = json.dumps({"annotations": [_draft("x" * 200, "y" * 200)]})
    assert len(raw.encode("utf-8")) > 64
    with pytest.raises(StructuredOutputError):
        bounded_json_decode(raw, limits=limits)


def test_bounded_decode_rejects_excessive_depth() -> None:
    limits = ParseLimits(max_depth=3)
    raw = '{"a": {"b": {"c": {"d": {"e": 1}}}}}'
    with pytest.raises(StructuredOutputError):
        bounded_json_decode(raw, limits=limits)


def test_bounded_decode_rejects_excessive_item_count() -> None:
    limits = ParseLimits(max_items=5)
    raw = json.dumps({"items": list(range(50))})
    with pytest.raises(StructuredOutputError):
        bounded_json_decode(raw, limits=limits)


def test_bounded_decode_rejects_excessive_string_length() -> None:
    limits = ParseLimits(max_string_length=10)
    raw = json.dumps({"k": "x" * 100})
    with pytest.raises(StructuredOutputError):
        bounded_json_decode(raw, limits=limits)


def test_bounded_decode_rejects_excessive_key_length() -> None:
    limits = ParseLimits(max_string_length=10)
    raw = json.dumps({"k" * 100: "ok"})
    with pytest.raises(StructuredOutputError):
        bounded_json_decode(raw, limits=limits)


def test_bounded_decode_malformed_json_raises_structured() -> None:
    with pytest.raises(StructuredOutputError):
        bounded_json_decode("{not: valid,,}")


def test_default_parse_limits_are_positive() -> None:
    assert DEFAULT_PARSE_LIMITS.max_response_bytes > 0
    assert DEFAULT_PARSE_LIMITS.max_depth > 0
    assert DEFAULT_PARSE_LIMITS.max_items > 0
    assert DEFAULT_PARSE_LIMITS.max_string_length > 0


def test_custom_limits_are_honored_by_parsers() -> None:
    # Limits flow through parse_prompt_mode, not just bounded_json_decode.
    tiny = ParseLimits(max_items=1)
    two = json.dumps({"annotations": [_draft(), _draft()]})
    with pytest.raises(StructuredOutputError):
        parse_prompt_mode(two, limits=tiny)
