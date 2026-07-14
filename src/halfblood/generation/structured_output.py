"""Deterministic structured-output negotiation and bounded response parsing."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import ValidationError

from halfblood.generation.errors import (
    AnnotationValidationError,
    IncompleteResponseError,
    ProviderCapabilityError,
    ProviderError,
    ProviderSafetyRefusal,
    StructuredOutputError,
)
from halfblood.generation.providers.base import ProviderCapabilities
from halfblood.generation.schema import RecordAnnotations

TOOL_NAME = "record_annotations"

StructuredOutputPin = Literal["auto", "tool", "json-schema", "prompt"]
CanonicalMode = Literal["tool", "json-schema", "prompt"]

# Auto-order per architecture section 4.3: forced tool/function, strict JSON
# Schema, then prompt JSON.
AUTO_ORDER: tuple[CanonicalMode, ...] = ("tool", "json-schema", "prompt")

INCOMPLETE_FINISH_REASONS: frozenset[str] = frozenset({"length", "max_tokens"})
REFUSAL_FINISH_REASONS: frozenset[str] = frozenset({"content_filter"})


@dataclass(frozen=True)
class ParseLimits:
    """Explicit bounds applied before and after decoding a JSON response."""

    max_response_bytes: int = 262_144
    max_depth: int = 64
    max_items: int = 1_000
    max_string_length: int = 100_000


DEFAULT_PARSE_LIMITS = ParseLimits()


@dataclass(frozen=True)
class StructuredOutputPolicy:
    """Select structured-output modes deterministically from declared support."""

    pin: StructuredOutputPin = "auto"
    strict: bool = False

    def _supported(self, mode: CanonicalMode, capabilities: ProviderCapabilities) -> bool:
        if mode == "tool":
            return capabilities.supports_tool_calling
        if mode == "json-schema":
            return capabilities.supports_json_schema
        return capabilities.supports_prompt_fallback and not self.strict

    def candidate_chain(
        self, capabilities: ProviderCapabilities
    ) -> tuple[CanonicalMode, ...]:
        """Return the ordered supported modes allowed by this policy."""

        if self.pin == "auto":
            return tuple(mode for mode in AUTO_ORDER if self._supported(mode, capabilities))

        pinned_mode: CanonicalMode = self.pin
        if self._supported(pinned_mode, capabilities):
            return (pinned_mode,)
        return ()

    def select(self, capabilities: ProviderCapabilities) -> CanonicalMode:
        """Return the first candidate or raise when the requested policy is unsupported."""

        chain = self.candidate_chain(capabilities)
        if not chain:
            raise ProviderCapabilityError(
                f"Structured-output mode {self.pin!r} is not supported",
                requested_mode=self.pin,
            )
        return chain[0]

    def next_mode(
        self, current: CanonicalMode, capabilities: ProviderCapabilities
    ) -> CanonicalMode | None:
        """Return the next auto-mode candidate after ``current``, if present."""

        if self.pin != "auto":
            return None
        chain = self.candidate_chain(capabilities)
        try:
            current_index = chain.index(current)
        except ValueError:
            return None
        next_index = current_index + 1
        if next_index >= len(chain):
            return None
        return chain[next_index]

    def allows_downgrade(self, error: ProviderError, *, already_downgraded: bool) -> bool:
        """Return whether one capability-related auto downgrade remains available."""

        return (
            self.pin == "auto"
            and not already_downgraded
            and isinstance(error, ProviderCapabilityError)
        )


def _check_decoded_limits(value: Any, limits: ParseLimits, *, container_depth: int = 0) -> None:
    if isinstance(value, str):
        if len(value) > limits.max_string_length:
            raise StructuredOutputError("JSON string exceeds the configured length limit")
        return

    if isinstance(value, Mapping):
        depth = container_depth + 1
        if depth > limits.max_depth:
            raise StructuredOutputError("JSON nesting exceeds the configured depth limit")
        if len(value) > limits.max_items:
            raise StructuredOutputError("JSON object exceeds the configured item limit")
        for key, item in value.items():
            if isinstance(key, str) and len(key) > limits.max_string_length:
                raise StructuredOutputError("JSON object key exceeds the configured length limit")
            _check_decoded_limits(item, limits, container_depth=depth)
        return

    if isinstance(value, list):
        depth = container_depth + 1
        if depth > limits.max_depth:
            raise StructuredOutputError("JSON nesting exceeds the configured depth limit")
        if len(value) > limits.max_items:
            raise StructuredOutputError("JSON array exceeds the configured item limit")
        for item in value:
            _check_decoded_limits(item, limits, container_depth=depth)


def bounded_json_decode(raw: str, *, limits: ParseLimits = DEFAULT_PARSE_LIMITS) -> Any:
    """Decode JSON while enforcing byte-size, nesting, item, and string bounds."""

    try:
        raw_size = len(raw.encode("utf-8"))
    except (AttributeError, UnicodeError) as exc:
        raise StructuredOutputError("JSON input is not valid UTF-8 text") from exc
    if raw_size > limits.max_response_bytes:
        raise StructuredOutputError("JSON response exceeds the configured byte limit")

    try:
        decoded = json.loads(raw)
        _check_decoded_limits(decoded, limits)
    except StructuredOutputError:
        raise
    except (RecursionError, ValueError) as exc:
        raise StructuredOutputError("Response was not valid bounded JSON") from exc
    return decoded


def _validate_record(value: Any) -> RecordAnnotations:
    if not isinstance(value, Mapping):
        raise StructuredOutputError("Structured-output root was not a JSON object")
    try:
        return RecordAnnotations.model_validate(value)
    except ValidationError as exc:
        raise AnnotationValidationError("Structured output failed annotation validation") from exc


def _decode_record(raw: str, limits: ParseLimits) -> RecordAnnotations:
    return _validate_record(bounded_json_decode(raw, limits=limits))


def parse_tool_mode(
    message: Mapping[str, Any],
    *,
    tool_name: str = TOOL_NAME,
    limits: ParseLimits = DEFAULT_PARSE_LIMITS,
) -> RecordAnnotations:
    """Parse an OpenAI-compatible assistant message in forced-tool mode."""

    matches: list[Any] = []
    tool_calls = message.get("tool_calls")
    if isinstance(tool_calls, list):
        for entry in tool_calls:
            if not isinstance(entry, Mapping):
                continue
            function = entry.get("function")
            if isinstance(function, Mapping) and function.get("name") == tool_name:
                matches.append(function.get("arguments"))
    else:
        function_call = message.get("function_call")
        if isinstance(function_call, Mapping) and function_call.get("name") == tool_name:
            matches.append(function_call.get("arguments"))

    if not matches:
        raise StructuredOutputError(f"No call to the required tool {tool_name!r} was returned")
    if len(matches) > 1:
        raise StructuredOutputError(f"Multiple calls to the required tool {tool_name!r} were returned")

    arguments = matches[0]
    if not isinstance(arguments, str):
        raise StructuredOutputError("Tool-call arguments were not a JSON string")
    return _decode_record(arguments, limits)


def parse_json_schema_mode(
    message: Mapping[str, Any],
    *,
    finish_reason: str | None = None,
    limits: ParseLimits = DEFAULT_PARSE_LIMITS,
) -> RecordAnnotations:
    """Parse one OpenAI-compatible strict JSON Schema response document."""

    if message.get("refusal"):
        raise ProviderSafetyRefusal("Provider refused the structured-output request")
    if finish_reason in REFUSAL_FINISH_REASONS:
        raise ProviderSafetyRefusal("Provider stopped for content safety")
    if finish_reason in INCOMPLETE_FINISH_REASONS:
        raise IncompleteResponseError("Provider response was incomplete")

    content = message.get("content")
    if not isinstance(content, str):
        raise StructuredOutputError("JSON Schema response content was not a string")
    return _decode_record(content, limits)


def _fenced_blocks(text: str) -> list[str]:
    """Return complete Markdown-style triple-backtick blocks without rewriting them."""

    blocks: list[str] = []
    cursor = 0
    while True:
        opening = text.find("```", cursor)
        if opening < 0:
            return blocks

        opening_line_end = text.find("\n", opening + 3)
        if opening_line_end < 0:
            opening_line_end = len(text)
        opening_marker = text[opening + 3 : opening_line_end].strip()
        if opening_marker not in ("", "json"):
            content_start = min(opening_line_end + 1, len(text))
            closing_cursor = content_start
            while True:
                possible_closing = text.find("```", closing_cursor)
                if possible_closing < 0:
                    cursor = len(text)
                    break
                possible_line_end = text.find("\n", possible_closing + 3)
                if possible_line_end < 0:
                    possible_line_end = len(text)
                if not text[possible_closing + 3 : possible_line_end].strip():
                    cursor = min(possible_line_end + 1, len(text))
                    break
                closing_cursor = possible_closing + 3
            continue

        content_start = min(opening_line_end + 1, len(text))
        closing_cursor = content_start
        closing = -1
        closing_line_end = -1
        while True:
            possible_closing = text.find("```", closing_cursor)
            if possible_closing < 0:
                break
            possible_line_end = text.find("\n", possible_closing + 3)
            if possible_line_end < 0:
                possible_line_end = len(text)
            if not text[possible_closing + 3 : possible_line_end].strip():
                closing = possible_closing
                closing_line_end = possible_line_end
                break
            closing_cursor = possible_closing + 3

        if closing < 0:
            cursor = opening + 3
            continue

        blocks.append(text[content_start:closing])
        cursor = min(closing_line_end + 1, len(text))


def _balanced_top_level_objects(text: str) -> list[str]:
    """Collect balanced top-level objects with quote- and escape-aware scanning."""

    objects: list[str] = []
    stack: list[str] = []
    object_start: int | None = None
    in_string = False
    escaped = False

    for index, character in enumerate(text):
        if in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
            continue

        if character == '"':
            in_string = True
            continue

        if character == "{":
            if not stack:
                object_start = index
            stack.append("}")
            continue
        if character == "[":
            if not stack:
                object_start = None
            stack.append("]")
            continue
        if character not in ("}", "]") or not stack:
            continue

        if character != stack[-1]:
            stack.clear()
            object_start = None
            continue

        stack.pop()
        if not stack and object_start is not None:
            objects.append(text[object_start : index + 1])
            object_start = None

    return objects


def parse_prompt_mode(
    text: str,
    *,
    limits: ParseLimits = DEFAULT_PARSE_LIMITS,
) -> RecordAnnotations:
    """Conservatively extract and validate one JSON object from free-form text."""

    try:
        text_size = len(text.encode("utf-8"))
    except (AttributeError, UnicodeError) as exc:
        raise StructuredOutputError("Prompt response is not valid UTF-8 text") from exc
    if text_size > limits.max_response_bytes:
        raise StructuredOutputError("Prompt response exceeds the configured byte limit")

    cleaned = text.strip().removeprefix("\ufeff").strip()
    try:
        whole_value = json.loads(cleaned)
    except (RecursionError, ValueError):
        pass
    else:
        if not isinstance(whole_value, Mapping):
            raise StructuredOutputError("Structured-output root was not a JSON object")
        return _decode_record(cleaned, limits)

    blocks = _fenced_blocks(cleaned)
    if len(blocks) > 1:
        raise StructuredOutputError("Prompt response contained multiple fenced blocks")
    search_space = blocks[0] if blocks else cleaned

    objects = _balanced_top_level_objects(search_space)
    if not objects:
        raise StructuredOutputError("Prompt response contained no JSON object")
    if len(objects) > 1:
        raise StructuredOutputError("Prompt response contained multiple JSON objects")
    return _decode_record(objects[0], limits)
