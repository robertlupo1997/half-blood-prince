"""Offline stub-judge support for the eval harness.

Phase 2 pre-staging: the quality gate (``eval/eval_harness.py``) was only
runnable with live provider credentials because ``StubProvider`` refused any
prompt without a PAGE NUMBER line -- which every judge prompt lacks, so the
judge call died into the "(judge returned no tool call)" all-zero fallback.

``StubProvider`` now fabricates deterministic neutral payloads for any
structured request whose output model is not annotation-shaped. This makes
generator->judge runnable end to end offline, so the one paid eval run is
literally a flag swap (--provider/--judge-provider + keys), not new code.

Honesty rule enforced here: stub scores are mid-range noise with an explicit
"no quality signal" justification, they fail most thresholds (harness exit 1),
and they must never be published as a quality result.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel, ConfigDict, Field

from halfblood.generation.providers.base import GenerationRequest
from halfblood.generation.providers.stub import StubProvider
from halfblood.generation.schema import RecordAnnotations

_EVAL_HARNESS = Path(__file__).resolve().parents[1] / "eval" / "eval_harness.py"


def _load_eval_harness() -> Any:
    """Import eval/eval_harness.py by path; eval/ is not an importable package."""
    spec = importlib.util.spec_from_file_location("_stub_judge_harness", _EVAL_HARNESS)
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
    """Judge-shaped output model: not annotation-shaped on purpose."""

    model_config = ConfigDict(extra="forbid")

    voice_consistency: _ScoreEntry
    relevance: _ScoreEntry


def _judge_request(output_model: type[BaseModel]) -> GenerationRequest:
    return GenerationRequest(
        system_prompt="grade strictly",
        user_prompt="BOOK: x\n\nGENERATED ANNOTATIONS: ...",
        schema=output_model.model_json_schema(),
        model="stub-deterministic",
        max_tokens=64,
        output_model=output_model,
        tool_name="record_scores",
    )


def test_stub_provider_fabricates_neutral_scores_for_judge_requests() -> None:
    result = StubProvider().complete(_judge_request(_RecordScores))

    parsed = result.parsed
    assert isinstance(parsed, _RecordScores)
    for entry_name in ("voice_consistency", "relevance"):
        entry = getattr(parsed, entry_name)
        assert entry.score == 3
        assert "no quality signal" in entry.justification
    assert result.finish_reason == "stop"


def test_stub_provider_annotation_path_still_works() -> None:
    request = GenerationRequest(
        system_prompt="s",
        user_prompt=(
            'PAGE TEXT TO ANNOTATE:\n"""\nThe potion shimmered an acid green.\n'
            '"""\n\nPAGE NUMBER: 4\n'
        ),
        schema=RecordAnnotations.model_json_schema(),
        model="stub-deterministic",
        max_tokens=64,
    )
    result = StubProvider().complete(request)

    assert isinstance(result.parsed, RecordAnnotations)
    assert len(result.parsed.annotations) == 1
    assert result.parsed.annotations[0].target_text in (
        "The potion shimmered an acid green."
    )


def test_harness_judge_annotations_accepts_stub_provider() -> None:
    module = _load_eval_harness()
    tc = module.TEST_CASES[0]
    scores = module.judge_annotations(tc, [], StubProvider(), "stub-deterministic")

    assert [s.metric_key for s in scores] == [m.key for m in module.METRICS]
    assert all(s.score == 3.0 for s in scores)
    assert all("no quality signal" in s.justification for s in scores)


def test_harness_main_runs_offline_and_fails_thresholds(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    module = _load_eval_harness()
    json_out = tmp_path / "results.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "eval_harness.py",
            "--provider",
            "stub",
            "--judge-provider",
            "stub",
            "--allow-self-judge",
            "--json-out",
            str(json_out),
        ],
    )

    with pytest.raises(SystemExit) as excinfo:
        module.main()

    # Stub neutral scores sit below most thresholds: exit 1 is the honest outcome.
    assert excinfo.value.code == 1
    data = __import__("json").loads(json_out.read_text())
    assert len(data) == len(module.TEST_CASES)
    assert all(case["generation_error"] is None for case in data)
    out = capsys.readouterr().out
    assert "Overall average score" in out
