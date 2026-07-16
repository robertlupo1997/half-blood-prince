"""P1-T9b — eval routes generation through the provider seam; judge independence (AUD-34).

Scope boundary (spec §9): Phase 1 gives the generator and judge INDEPENDENT CONFIGURATION
and stops the generator grading itself.  Phase 1 does NOT move the judge's transport onto
the provider layer — spec §9 Phase 5 (line 632) assigns "Move judge generation through the
provider layer, separate generator and judge families" to Phase 5, and the code agrees:
`GenerationResult.parsed` is hard-typed to `RecordAnnotations`, so the judge's own tool
schema cannot round-trip through `LLMProvider.complete()` without generalizing
`structured_output.py` + both providers (4 merged src files under 161 merged tests).

Why the rule lives in `src/halfblood/config.py` and not in `eval/eval_harness.py`:
`eval/` is not an importable package, which is precisely why it has ~zero coverage today
(tests can only reach it via importlib).  Putting judge independence in the config layer
makes AUD-34 directly testable, and mirrors the P1-T9a rule that the config layer owns all
validation while callers stay pure plumbing.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from halfblood.generation.errors import ProviderConfigurationError

_REPO_ROOT = Path(__file__).resolve().parents[1]
_EVAL_HARNESS = _REPO_ROOT / "eval" / "eval_harness.py"

# A throwaway key so the merged "hosted providers require a key env var" contract
# (config.py) does not fire before the judge-independence check under test.
_KEYS = {
    "ANTHROPIC_API_KEY": "sk-ant-test-not-a-real-key",
    "OPENAI_API_KEY": "sk-openai-test-not-a-real-key",
}


def _resolve(**kwargs: Any) -> Any:
    """Drive the REAL resolver hermetically: injected environ, nonexistent config paths.

    Never falls back to os.environ / Path.cwd() / the user config dir, so no machine-local
    file can influence the result.

    Imported lazily and deliberately: a module-level `from halfblood.config import
    resolve_eval_configs` fails COLLECTION before Codex builds, which masks the
    eval_harness structural tests below and makes it impossible to confirm each test fails
    for its own intended reason.
    """
    from halfblood.config import resolve_eval_configs

    tmp = kwargs.pop("tmp_path")
    kwargs.setdefault("environ", dict(_KEYS))
    kwargs.setdefault("project_config_path", tmp / "nonexistent_project.toml")
    kwargs.setdefault("user_config_path", tmp / "nonexistent_user.toml")
    return resolve_eval_configs(**kwargs)


# ---------------------------------------------------------------------------
# AUD-34 — the generator must not grade itself
# ---------------------------------------------------------------------------


def test_identical_provider_and_model_raises(tmp_path: Path) -> None:
    """Same provider AND same model for generator and judge must raise (AUD-34).

    This is the core of AUD-34: "duplicated Anthropic clients ... let the generator grade
    itself" (plan P1-T9 goal).  INTENDED FAILURE before Codex builds: resolve_eval_configs
    does not exist.
    """
    with pytest.raises(ProviderConfigurationError) as exc:
        _resolve(
            tmp_path=tmp_path,
            generator_overrides={"provider": "anthropic", "model": "claude-sonnet-5"},
            judge_overrides={"provider": "anthropic", "model": "claude-sonnet-5"},
        )

    message = str(exc.value).lower()
    assert "judge" in message, (
        f"the self-judge error must name the judge so the operator knows which knob to "
        f"turn; got {str(exc.value)!r}"
    )


def test_default_invocation_raises_self_judge(tmp_path: Path) -> None:
    """With NO overrides at all, generator and judge both resolve to the anthropic preset
    default -- which collides, and must therefore raise (AUD-34).

    This is the test that matters most.  A green-seeking implementer will be tempted to make
    the bare `python eval/eval_harness.py` invocation "just work" by exempting the default
    from the collision check.  That would silently reopen AUD-34 for the single most common
    invocation.  Forcing the operator to choose IS the closure: we cannot default the judge
    to a different family without inventing a model id, which the loop forbids.
    """
    with pytest.raises(ProviderConfigurationError):
        _resolve(tmp_path=tmp_path, generator_overrides={}, judge_overrides={})


def test_identical_provider_and_model_permitted_with_allow_self_judge(tmp_path: Path) -> None:
    """The explicit development override must permit self-judging (plan P1-T9 test-first:
    "reject identical provider+model unless an explicit development override is supplied").
    """
    generator, judge = _resolve(
        tmp_path=tmp_path,
        generator_overrides={"provider": "anthropic", "model": "claude-sonnet-5"},
        judge_overrides={"provider": "anthropic", "model": "claude-sonnet-5"},
        allow_self_judge=True,
    )

    assert generator.model == judge.model == "claude-sonnet-5"
    assert generator.provider == judge.provider == "anthropic"


def test_same_provider_different_model_is_allowed(tmp_path: Path) -> None:
    """Judge independence is provider+model, not provider alone.

    Phase 1 cannot separate judge *families* (that is Phase 5 per spec §9:632, and the judge
    transport is still the Anthropic SDK), so a different model within the same family is the
    practical Phase-1 closure -- spec §7.1:527 says "where practical".  If this raised, the
    only compliant configuration would be one Phase 1 cannot actually run.
    """
    generator, judge = _resolve(
        tmp_path=tmp_path,
        generator_overrides={"provider": "anthropic", "model": "claude-sonnet-5"},
        judge_overrides={"provider": "anthropic", "model": "claude-opus-4-8"},
    )

    assert generator.model != judge.model
    assert generator.provider == judge.provider == "anthropic"


def test_different_provider_is_allowed(tmp_path: Path) -> None:
    """Distinct providers must resolve independently (plan P1-T9 test-first: "provide
    distinct generator and judge provider/model settings").
    """
    generator, judge = _resolve(
        tmp_path=tmp_path,
        generator_overrides={"provider": "openai", "model": "gpt-4o"},
        judge_overrides={"provider": "anthropic", "model": "claude-sonnet-5"},
    )

    assert generator.provider == "openai"
    assert judge.provider == "anthropic"


def test_generator_and_judge_resolve_independently(tmp_path: Path) -> None:
    """Every resolved field must be independently derived, not copied from the generator."""
    generator, judge = _resolve(
        tmp_path=tmp_path,
        generator_overrides={"provider": "anthropic", "model": "claude-sonnet-5", "timeout_seconds": 11.0},
        judge_overrides={"provider": "anthropic", "model": "claude-opus-4-8", "timeout_seconds": 22.0},
    )

    assert generator.timeout_seconds == 11.0
    assert judge.timeout_seconds == 22.0, (
        "judge settings must resolve independently; a judge that inherits the generator's "
        "timeout means the two configs are not actually separate"
    )


def test_allow_self_judge_does_not_disable_other_validation(tmp_path: Path) -> None:
    """--allow-self-judge relaxes ONLY the judge-independence rule.

    Regression guard: it must not become a blanket "skip config validation" escape hatch.
    An unknown provider must still raise even with the override set.
    """
    with pytest.raises(ProviderConfigurationError) as exc:
        _resolve(
            tmp_path=tmp_path,
            generator_overrides={"provider": "not-a-real-provider", "model": "m"},
            judge_overrides={"provider": "anthropic", "model": "claude-sonnet-5"},
            allow_self_judge=True,
        )

    assert "judge" not in str(exc.value).lower(), (
        "an unknown-provider error must not be reported as a judge-independence failure"
    )


# ---------------------------------------------------------------------------
# HALFBLOOD_EVAL_MODEL — documented compatibility mapping
# ---------------------------------------------------------------------------


def test_halfblood_eval_model_maps_to_generator_model(tmp_path: Path) -> None:
    """HALFBLOOD_EVAL_MODEL is retained "only through a documented compatibility mapping"
    (plan P1-T9 test-first).  It maps to the GENERATOR's model.
    """
    generator, judge = _resolve(
        tmp_path=tmp_path,
        generator_overrides={"provider": "anthropic"},
        judge_overrides={"provider": "anthropic", "model": "claude-opus-4-8"},
        environ={**_KEYS, "HALFBLOOD_EVAL_MODEL": "legacy-eval-model"},
    )

    assert generator.model == "legacy-eval-model"


def test_halfblood_eval_model_does_not_leak_into_judge(tmp_path: Path) -> None:
    """The legacy env var is a GENERATOR compatibility mapping only.

    If it set both, it would force a self-judge collision on every legacy invocation -- and
    silently re-create the exact AUD-34 shape the task exists to close.
    """
    generator, judge = _resolve(
        tmp_path=tmp_path,
        generator_overrides={"provider": "anthropic"},
        judge_overrides={"provider": "anthropic", "model": "claude-opus-4-8"},
        environ={**_KEYS, "HALFBLOOD_EVAL_MODEL": "legacy-eval-model"},
    )

    assert generator.model == "legacy-eval-model"
    assert judge.model == "claude-opus-4-8", (
        "HALFBLOOD_EVAL_MODEL must not set the judge's model; it is a generator-side "
        "compatibility mapping"
    )


def test_explicit_generator_model_beats_legacy_env_var(tmp_path: Path) -> None:
    """An explicit override must win over the legacy compatibility env var."""
    generator, _judge = _resolve(
        tmp_path=tmp_path,
        generator_overrides={"provider": "anthropic", "model": "explicit-model"},
        judge_overrides={"provider": "anthropic", "model": "claude-opus-4-8"},
        environ={**_KEYS, "HALFBLOOD_EVAL_MODEL": "legacy-eval-model"},
    )

    assert generator.model == "explicit-model"


# ---------------------------------------------------------------------------
# eval/eval_harness.py — the inline Anthropic fallback is DELETED (spec §2:88, §7.1:527)
# ---------------------------------------------------------------------------


def _load_eval_harness() -> ModuleType:
    """Import eval/eval_harness.py by path.

    eval/ is not an importable package, which is why it has ~zero coverage: `pytest tests/`
    stays green while eval/ is completely broken.
    """
    spec = importlib.util.spec_from_file_location("_eval_harness_under_test", _EVAL_HARNESS)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(spec.name, None)
    return module


def test_eval_harness_does_not_import_the_anthropic_sdk_for_generation() -> None:
    """The inline Anthropic fallback generator must be deleted (spec §2:88, §7.1:527).

    Spec §2:88 -- "The fallback undermines a single provider seam and should be removed once
    the package is installable" (it is: `pip install -e .`).  Spec §7.1:527 -- "delete its
    inline Anthropic fallback".  Plan P1-T9 acceptance -- "One generation seam serves product
    and eval"; the inline fallback IS a second seam.

    NOTE the Phase-1 boundary: `from anthropic import Anthropic` legitimately SURVIVES for
    the JUDGE's transport (spec §9:632 moves that in Phase 5).  This test therefore pins the
    deletion of the generation-side duplicate, NOT the absence of the import.
    """
    module = _load_eval_harness()

    assert not hasattr(module, "_fallback_generate"), (
        "_fallback_generate is the inline duplicate generation seam; spec §7.1:527 says "
        "delete it"
    )
    assert not hasattr(module, "GENERATION_TOOL"), (
        "GENERATION_TOOL is the inline fallback's duplicate tool schema; it dies with "
        "_fallback_generate"
    )


def test_eval_harness_imports_annotation_generator_unconditionally() -> None:
    """The try/except ImportError scaffolding must be gone.

    It exists because the package was "not implemented yet" (eval_harness.py:65 comment) --
    a premise that is now false (`pip install -e .`).  While it stands, a broken
    AnnotationGenerator import degrades silently to the built-in fallback instead of failing
    loudly, so the harness can score its own fallback and report a passing eval.

    This asserts on SOURCE TEXT deliberately.  The obvious behavioral form --
    `assert module.AnnotationGenerator is RealGenerator` -- passes RIGHT NOW, because the
    guarded import currently succeeds; it would be vacuous and could never go red.  Only the
    absence of the guard itself distinguishes built from unbuilt.
    """
    source = _EVAL_HARNESS.read_text(encoding="utf-8")

    assert "except ImportError" not in source, (
        "the try/except ImportError scaffolding around the AnnotationGenerator/PageContent "
        "imports must be deleted: the package is installable, so a failed import is a real "
        "error and must not degrade silently to the built-in fallback"
    )

    module = _load_eval_harness()
    from halfblood.annotation_generator import AnnotationGenerator as RealGenerator

    assert getattr(module, "AnnotationGenerator", None) is RealGenerator, (
        "eval_harness.AnnotationGenerator must be the real class, not a None sentinel"
    )


def test_generation_routes_to_the_injected_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    """Generation must route through the injected provider (plan P1-T9 test-first: "prove
    calls route to the correct fake") and must NOT fall back to a built-in generator.
    """
    module = _load_eval_harness()
    sentinel_provider = object()
    captured: dict[str, Any] = {}

    class _FakeGenerator:
        def __init__(self, persona: str | None = None, model: str | None = None, provider: Any = None) -> None:
            captured["provider"] = provider
            captured["model"] = model

        def generate_for_page(self, page_text: str, page_number: int, book_context: str) -> list[Any]:
            return []

    monkeypatch.setattr(module, "AnnotationGenerator", _FakeGenerator)
    test_case = module.TEST_CASES[0]

    module.generate_annotations(
        test_case,
        generator_provider=sentinel_provider,
        generator_model="model-under-test",
        console=module.Console(),
    )

    assert captured["provider"] is sentinel_provider, (
        "generate_annotations must inject the provider it was given into AnnotationGenerator"
    )
    assert captured["model"] == "model-under-test"


def test_generation_failure_raises_instead_of_silently_falling_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failing generator must propagate, not degrade to a built-in fallback.

    Today eval_harness.py:518 catches bare `Exception` and falls back to _fallback_generate,
    so the harness can silently grade its OWN fallback output instead of the product and
    still report a score.  With the fallback deleted there is nothing to fall back to, and
    the failure must surface.
    """
    module = _load_eval_harness()

    class _ExplodingGenerator:
        def __init__(self, **_kwargs: Any) -> None:
            pass

        def generate_for_page(self, **_kwargs: Any) -> list[Any]:
            raise RuntimeError("provider exploded")

    monkeypatch.setattr(module, "AnnotationGenerator", _ExplodingGenerator)
    test_case = module.TEST_CASES[0]

    with pytest.raises(Exception, match="provider exploded"):
        module.generate_annotations(
            test_case,
            generator_provider=object(),
            generator_model="model-under-test",
            console=module.Console(),
        )
