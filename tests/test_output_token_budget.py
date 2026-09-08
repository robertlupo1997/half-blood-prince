"""The per-page output-token budget, and why it is not 2048.

A full session concluded that "no free model on this account can generate
annotations," measured across two models and all three structured-output modes.
The measurement was real; the conclusion was wrong. The budget sent for one page
of annotations was hardcoded at 2048, and a reasoning model spends its budget on
reasoning tokens before emitting any payload, so the JSON was cut off mid-object
every time. The provider seam escalates once (2048 -> 4096) and never reaches
its own 8192 ceiling, so a larger ask was never actually tried.

Re-measured 2026-09-08 on `nvidia/nemotron-3.5-lightning:free`, one real page of
*The Elements of Style*, `--structured-output function`, nothing else changed:
2048 raised `IncompleteResponseError`; 16000 returned three schema-valid
annotations in 141 seconds.

These tests are offline. They pin the resolution rule, not the network result.
"""

from __future__ import annotations

import pytest

from halfblood.annotation_generator import (
    DEFAULT_MAX_OUTPUT_TOKENS,
    AnnotationGenerator,
    _max_output_tokens,
)
from halfblood.document_processor import PageContent
from halfblood.generation.providers.base import GenerationRequest
from halfblood.generation.providers.stub import StubProvider


def test_the_default_budget_clears_the_seams_own_escalation_ceiling() -> None:
    """2048 escalates to 4096 and stops. The default must not sit under that.

    If someone lowers this below 8192, the escalation path becomes the only
    thing standing between a reasoning model and a truncated payload — which is
    exactly the configuration that produced the wrong conclusion.
    """
    from halfblood.generation.providers.openai_compat import (
        _INCOMPLETE_RESPONSE_MAX_TOKENS_CEILING,
    )

    assert DEFAULT_MAX_OUTPUT_TOKENS >= _INCOMPLETE_RESPONSE_MAX_TOKENS_CEILING, (
        f"default budget {DEFAULT_MAX_OUTPUT_TOKENS} is at or below the seam's "
        f"escalation ceiling {_INCOMPLETE_RESPONSE_MAX_TOKENS_CEILING}; a reasoning "
        "model will truncate before it emits the payload"
    )


def test_the_budget_is_not_the_old_hardcoded_value() -> None:
    """A regression guard with a real failing state: 2048 shipped and was wrong."""
    assert DEFAULT_MAX_OUTPUT_TOKENS != 2048


@pytest.mark.parametrize("raw", ["", "   ", "not-a-number", "0", "-1"])
def test_an_unusable_override_falls_back_to_the_default(
    raw: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Never send a nonsense budget to a provider because an env var was typo'd."""
    monkeypatch.setenv("HALFBLOOD_MAX_OUTPUT_TOKENS", raw)
    assert _max_output_tokens() == DEFAULT_MAX_OUTPUT_TOKENS


def test_an_unset_override_falls_back_to_the_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("HALFBLOOD_MAX_OUTPUT_TOKENS", raising=False)
    assert _max_output_tokens() == DEFAULT_MAX_OUTPUT_TOKENS


def test_a_valid_override_is_honoured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HALFBLOOD_MAX_OUTPUT_TOKENS", "4321")
    assert _max_output_tokens() == 4321


def test_the_generator_actually_sends_the_resolved_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The constant is worthless if the request still carries the old number.

    This is the assertion that would have caught the original defect: it reads
    the budget off the `GenerationRequest` the provider is handed, not off the
    constant.
    """
    monkeypatch.setenv("HALFBLOOD_MAX_OUTPUT_TOKENS", "12345")

    seen: list[GenerationRequest] = []

    class RecordingProvider(StubProvider):
        def complete(self, request: GenerationRequest):
            seen.append(request)
            return super().complete(request)

    generator = AnnotationGenerator(api_key="unused", provider=RecordingProvider())
    generator.generate_for_document(
        [PageContent(page_number=1, text="Vigorous writing is concise.", width=400.0, height=600.0)]
    )

    assert seen, "the provider was never called"
    assert seen[0].max_tokens == 12345, (
        f"the generator sent max_tokens={seen[0].max_tokens}, not the resolved budget"
    )
