from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel

from halfblood.generation.schema import RecordAnnotations

StructuredOutputMode = Literal["tool", "function", "json-schema", "prompt"]


@dataclass(frozen=True)
class ProviderCapabilities:
    supports_tool_calling: bool
    supports_json_schema: bool
    supports_strict_json_schema: bool
    supports_prompt_fallback: bool = True
    max_output_tokens: int | None = None


@dataclass(frozen=True)
class GenerationUsage:
    input_tokens: int
    output_tokens: int

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass(frozen=True)
class GenerationRequest:
    system_prompt: str
    user_prompt: str
    schema: Mapping[str, Any]
    model: str
    max_tokens: int
    structured_output_mode: StructuredOutputMode = "tool"
    temperature: float | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    output_model: type[BaseModel] = RecordAnnotations
    tool_name: str = "record_annotations"


@dataclass(frozen=True)
class GenerationResult:
    parsed: BaseModel
    request_id: str | None
    finish_reason: str
    usage: GenerationUsage
    latency_seconds: float
    structured_output_mode: StructuredOutputMode
    warnings: tuple[str, ...] = ()
    attempts: int = 1


@runtime_checkable
class LLMProvider(Protocol):
    @property
    def capabilities(self) -> ProviderCapabilities: ...

    def complete(self, request: GenerationRequest) -> GenerationResult: ...
