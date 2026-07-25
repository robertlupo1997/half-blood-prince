"""Phase 5 — the eval judge moves onto the provider seam.

`eval/eval_harness.py` is the last place in the repo that imports the `anthropic` SDK,
and it raises outright for any judge provider other than `anthropic`:

    "The Phase 1 eval judge transport supports only the anthropic provider;
     provider-layer judge transport is planned for Phase 5"

That is not merely untidy. The quality gate is **unrunnable** for anyone without Anthropic
credit, which currently includes this project — every quality claim to date rests on
eyeballing output rather than on the harness. Putting the judge on the seam makes the eval
runnable against any configured provider, including free ones.

The blocker was never the transport; it was that `structured_output.py` hardcoded
`RecordAnnotations` as the validation target. Everything else in that module — bounded
decoding, mode negotiation (tool → json-schema → prompt), fenced-block recovery, and the
retry loop — is already model-agnostic and schema-driven. So this is a parameterisation,
not a rewrite.

The overriding constraint, and the reason these tests lead with it:

**The annotation path must be provably unchanged.** `structured_output.py` and the two
httpx providers own retry for the entire project (root `CLAUDE.md`, architecture §4.6).
The generation path is the part with measured results behind it — 48/50 annotations on a
real book. A judge migration that perturbs it is a bad trade at any price, so the output
model is threaded through as an *optional parameter defaulting to `RecordAnnotations`*,
leaving every existing call site byte-identical in behaviour.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel, ConfigDict, Field

from halfblood.generation.schema import RecordAnnotations
from halfblood.generation.structured_output import parse_tool_mode

_EVAL_HARNESS = Path(__file__).resolve().parents[1] / "eval" / "eval_harness.py"


def _load_eval_harness() -> Any:
    """Import eval/eval_harness.py by path; eval/ is not an importable package.

    ``sys.modules`` must be populated *before* ``exec_module`` or dataclass field
    resolution fails with a bare AttributeError on ``NoneType.__dict__``.
    """
    spec = importlib.util.spec_from_file_location("_judge_seam_harness", _EVAL_HARNESS)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(spec.name, None)
    return module


class _ScoreEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    score: int = Field(ge=1, le=5)
    justification: str


class _RecordScores(BaseModel):
    """Stand-in for the judge's output model — deliberately not annotation-shaped."""

    model_config = ConfigDict(extra="forbid", title="record_scores")
    voice: _ScoreEntry


def _tool_message(name: str, arguments: str) -> dict[str, Any]:
    return {
        "role": "assistant",
        "tool_calls": [{"type": "function", "function": {"name": name, "arguments": arguments}}],
    }


# ---------------------------------------------------------------------------
# 1. The annotation path does not move
# ---------------------------------------------------------------------------


class TestAnnotationPathUnchanged:
    """Retry and structured-output parsing are shared with production generation."""

    def test_parse_tool_mode_still_defaults_to_record_annotations(self) -> None:
        message = _tool_message(
            "record_annotations",
            '{"annotations": [{"target_text": "Crush the bean", '
            '"annotation_type": "correction", "content": "Crush, do not cut.", '
            '"confidence": 0.9, "position": "margin_right"}]}',
        )
        parsed = parse_tool_mode(message)
        assert isinstance(parsed, RecordAnnotations)
        assert parsed.annotations[0].target_text == "Crush the bean"

    def test_an_annotation_payload_still_validates_strictly(self) -> None:
        """A bad annotation payload must still be rejected, not waved through."""
        from halfblood.generation.errors import AnnotationValidationError

        message = _tool_message("record_annotations", '{"annotations": [{"bogus": 1}]}')
        with pytest.raises(AnnotationValidationError):
            parse_tool_mode(message)


# ---------------------------------------------------------------------------
# 2. The parser accepts a different output model
# ---------------------------------------------------------------------------


class TestParserIsModelAgnostic:
    def test_a_non_annotation_model_round_trips(self) -> None:
        message = _tool_message(
            "record_scores", '{"voice": {"score": 4, "justification": "Terse and dry."}}'
        )
        parsed = parse_tool_mode(message, tool_name="record_scores", output_model=_RecordScores)
        assert isinstance(parsed, _RecordScores)
        assert parsed.voice.score == 4

    def test_a_bad_payload_for_the_new_model_is_rejected(self) -> None:
        """Validation must be applied to the supplied model, not skipped for non-annotations."""
        from halfblood.generation.errors import AnnotationValidationError

        message = _tool_message("record_scores", '{"voice": {"score": 99}}')
        with pytest.raises(AnnotationValidationError):
            parse_tool_mode(message, tool_name="record_scores", output_model=_RecordScores)

    def test_bounded_decoding_still_applies_to_a_custom_model(self) -> None:
        """The parse limits are a denial-of-service guard; they are not model-specific.

        Asserts the *specific* error type on purpose: `pytest.raises(Exception)` here would
        also swallow the TypeError from an unimplemented `output_model` kwarg and pass
        before the feature exists.
        """
        from halfblood.generation.errors import StructuredOutputError

        message = _tool_message("record_scores", "[" * 200 + "]" * 200)
        with pytest.raises(StructuredOutputError):
            parse_tool_mode(message, tool_name="record_scores", output_model=_RecordScores)


# ---------------------------------------------------------------------------
# 3. The harness no longer needs the vendor SDK
# ---------------------------------------------------------------------------


class TestJudgeRunsOnTheSeam:
    def test_the_harness_source_no_longer_imports_the_anthropic_sdk(self) -> None:
        """Asserted on source text: the import is what makes `anthropic` a dependency.

        A behavioural form would pass while the import still sits at module scope.
        """
        source = _EVAL_HARNESS.read_text(encoding="utf-8")
        assert "from anthropic import" not in source
        assert "import anthropic" not in source

    def test_the_phase_one_judge_provider_restriction_is_gone(self) -> None:
        source = _EVAL_HARNESS.read_text(encoding="utf-8")
        assert "supports only the anthropic provider" not in source

    def test_the_judge_builds_its_transport_through_the_registry(self) -> None:
        source = _EVAL_HARNESS.read_text(encoding="utf-8")
        assert "build_provider" in source

    def test_the_harness_still_imports(self) -> None:
        """Non-vacuity: the assertions above are about source text, so prove it loads."""
        module = _load_eval_harness()
        assert hasattr(module, "judge_annotations")

    def test_the_generation_seam_guards_still_hold(self) -> None:
        """The Phase-1 deletions must not be reintroduced by this migration."""
        module = _load_eval_harness()
        assert not hasattr(module, "_fallback_generate")
        assert not hasattr(module, "GENERATION_TOOL")


# ---------------------------------------------------------------------------
# 4. BOTH providers must honour the output model
# ---------------------------------------------------------------------------


class TestAnthropicProviderHonoursTheOutputModel:
    """The Anthropic provider parses inline; it never calls structured_output.

    `openai_compat.py` delegates to `parse_tool_mode`, so parameterising that module is
    enough for it. `anthropic.py` does its own parsing and was hardcoded to
    `record_annotations` at every step: the `tool_choice` it sends, the block name it
    requires, the `"annotations"` key it demands, and the `RecordAnnotations(...)` it
    constructs.

    That makes routing the judge through `build_provider` a **regression** for
    `provider = "anthropic"` — the one judge path that worked before the migration. The
    full suite and both linters stay green over it, because nothing else exercises a
    non-annotation model against this provider. Verified by hand first: the provider sent
    `tool_choice={"name": "record_annotations"}` for a RecordScores request and raised
    "no record_annotations tool_use block was present".

    The annotation path keeps its own behaviour, including per-item resilience (one bad
    annotation is dropped with a warning rather than failing the whole page), which the
    generic path must not silently replace.
    """

    @staticmethod
    def _request(output_model: type[BaseModel], schema: dict[str, Any]) -> Any:
        from halfblood.generation.providers.base import GenerationRequest

        return GenerationRequest(
            system_prompt="s",
            user_prompt="u",
            schema=schema,
            model="m",
            max_tokens=256,
            output_model=output_model,
            tool_name=(
                "record_scores" if output_model is not RecordAnnotations
                else "record_annotations"
            ),
        )

    @staticmethod
    def _provider(handler: Any) -> Any:
        import httpx

        from halfblood.generation.providers.anthropic import AnthropicProvider

        return AnthropicProvider(
            api_key="k",
            base_url="https://example.invalid",
            transport=httpx.MockTransport(handler),
            sleep_fn=lambda _s: None,
            rand_fn=lambda: 0.5,
            max_retries=0,
        )

    def test_it_requests_the_tool_named_by_the_output_model(self) -> None:
        import json

        import httpx

        sent: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            sent.update(json.loads(request.content))
            return httpx.Response(
                200,
                json={
                    "stop_reason": "tool_use",
                    "content": [
                        {
                            "type": "tool_use",
                            "name": "record_scores",
                            "input": {"voice": {"score": 4, "justification": "Terse."}},
                        }
                    ],
                    "usage": {"input_tokens": 10, "output_tokens": 5},
                },
                headers={"request-id": "req_1"},
            )

        provider = self._provider(handler)
        provider.complete(self._request(_RecordScores, {"type": "object"}))
        assert sent["tool_choice"]["name"] == "record_scores", (
            "the provider asked for the annotations tool while carrying a judge schema"
        )

    def test_it_validates_against_the_supplied_model(self) -> None:
        import httpx

        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "stop_reason": "tool_use",
                    "content": [
                        {
                            "type": "tool_use",
                            "name": "record_scores",
                            "input": {"voice": {"score": 4, "justification": "Terse."}},
                        }
                    ],
                    "usage": {"input_tokens": 10, "output_tokens": 5},
                },
                headers={"request-id": "req_1"},
            )

        provider = self._provider(handler)
        result = provider.complete(self._request(_RecordScores, {"type": "object"}))
        assert isinstance(result.parsed, _RecordScores)
        assert result.parsed.voice.score == 4

    def test_the_annotation_path_keeps_its_per_item_resilience(self) -> None:
        """One malformed annotation is dropped with a warning; the page still renders.

        A generic `model_validate` on the whole payload would reject the entire page
        instead, losing the good annotations with it.
        """
        import httpx

        from halfblood.generation.schema import RecordAnnotations as _RA

        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "stop_reason": "tool_use",
                    "content": [
                        {
                            "type": "tool_use",
                            "name": "record_annotations",
                            "input": {
                                "annotations": [
                                    {
                                        "target_text": "Crush the bean",
                                        "annotation_type": "correction",
                                        "content": "Crush, do not cut.",
                                        "confidence": 0.9,
                                        "position": "margin_right",
                                    },
                                    {"bogus": "not an annotation"},
                                ]
                            },
                        }
                    ],
                    "usage": {"input_tokens": 10, "output_tokens": 5},
                },
                headers={"request-id": "req_1"},
            )

        provider = self._provider(handler)
        result = provider.complete(self._request(_RA, {"type": "object"}))
        assert isinstance(result.parsed, _RA)
        assert len(result.parsed.annotations) == 1
        assert any("dropped invalid annotation" in w for w in result.warnings)


def test_the_project_declares_no_llm_vendor_sdk_dependency() -> None:
    """The judge was the last thing needing a vendor SDK; the dependency goes with it.

    Generation and judging both run over the httpx provider seam now, so `anthropic`
    was removed from the `[eval]` extra. Left in place it would be an invisible
    dependency nobody imports — and its presence is what made "we have no vendor SDK
    dependency" false while looking true.
    """
    import tomllib

    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))

    declared = [
        requirement
        for group in data["project"].get("optional-dependencies", {}).values()
        for requirement in group
    ] + list(data["project"].get("dependencies", []))

    offenders = [r for r in declared if r.lower().startswith(("anthropic", "openai"))]
    assert not offenders, f"vendor SDK dependency reintroduced: {offenders}"
    assert "eval" in data["project"]["optional-dependencies"], (
        "the [eval] extra must still exist; the README documents installing it"
    )
