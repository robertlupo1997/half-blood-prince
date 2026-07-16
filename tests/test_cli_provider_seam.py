"""Controller-authored failing tests for P1-T9a — provider seam on annotate + preview.

Ground truth:
  docs/superpowers/specs/2026-07-11-full-project-architecture.md §2.6, §4.4, §9
  .superpowers/sdd/p1-t9a-brief.md
  .superpowers/sdd/p1-t9a-subdriver-spec.md

These tests pin the 10 acceptance criteria for the provider seam.  They were
authored by the controller (Sonnet sub-driver) and are FROZEN — Codex must
never edit, delete, or create files under tests/.

Injection strategy [INFER]:
  cli.py must import ``resolve_generation_config`` and ``build_provider`` at
  module top level (already present).  Tests monkeypatch
  ``halfblood.cli.resolve_generation_config`` and ``halfblood.cli.build_provider``
  so each test can supply a hermetic config and a fake provider without touching
  real env vars or real config files.

No network calls anywhere in this file.
"""

from __future__ import annotations

import warnings
from pathlib import Path

import pytest
from click.testing import CliRunner

import halfblood.cli as cli_module
from halfblood.annotation_generator import AllPagesFailedError, AnnotationGenerator
from halfblood.config import ResolvedConfig, resolve_generation_config
from halfblood.document_processor import PageContent
from halfblood.generation.errors import ProviderConfigurationError
from halfblood.generation.providers.base import ProviderCapabilities
from halfblood.models import AnnotatedPage, AnnotationPlan
from halfblood.web_preview import PreviewResult

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Sentinel key — must NEVER appear in any command output.
_SENTINEL_KEY = "sk-ant-sentinel-p1-t9a-not-real"

_FAKE_SOURCES: dict[str, str] = {
    "provider": "cli",
    "model": "cli",
    "base_url": "preset",
    "api_key_env": "preset",
    "structured_output": "preset",
    "timeout_seconds": "default",
    "max_retries": "default",
    "concurrency": "phase1",
    "allow_insecure_http": "default",
}

_FAKE_CONFIG = ResolvedConfig(
    provider="anthropic",
    model="claude-sonnet-5",
    base_url="https://api.anthropic.com",
    api_key_env="ANTHROPIC_API_KEY",
    structured_output="tool",
    timeout_seconds=60.0,
    max_retries=0,
    concurrency=1,
    allow_insecure_http=False,
    sources=_FAKE_SOURCES,
)

#: Minimal valid PDF magic bytes — accepted by the magic-byte check in cli.py.
_PDF_BYTES = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n%%EOF\n"

# ---------------------------------------------------------------------------
# Fakes and doubles
# ---------------------------------------------------------------------------


class _FakePdfProcessor:
    """Minimal DocumentProcessor double."""

    load_calls: list[str] = []

    def load(self, path: str) -> list[PageContent]:
        type(self).load_calls.append(path)
        return [PageContent(page_number=1, text="Bezoar. Remember that.", width=612.0, height=792.0)]

    def render_annotations(self, input_path: str, annotations: list, output_path: str) -> None:
        Path(output_path).write_text("rendered-pdf", encoding="utf-8")

    def annotations_from_plan(self, plan: AnnotationPlan) -> list:
        return [a for page in plan.pages for a in page.annotations]


class _SentinelProvider:
    """Provider double that raises on .complete() — proves the command never touches it."""

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            supports_tool_calling=True,
            supports_json_schema=False,
            supports_strict_json_schema=False,
        )

    def complete(self, request):
        raise AssertionError(
            "provider.complete() was called — this command must not invoke the LLM provider"
        )


class _CapturingGenerator:
    """Fake AnnotationGenerator that records the provider= kwarg it received.

    Class-level attributes are reset by the seam_fakes fixture before each test.
    """

    last_provider: object | None = None
    last_model: str | None = None
    calls: int = 0
    _inject_failed_pages: list[int] = []
    _raise_all_failed: bool = False

    def __init__(
        self,
        *,
        provider: object | None = None,
        persona: str | None = None,
        model: str | None = None,
        api_key: str | None = None,
    ) -> None:
        # Exact keyword surface of AnnotationGenerator.__init__ — no **kwargs so an
        # unexpected keyword from cli.py raises TypeError instead of hiding the mismatch.
        # api_key= is kept because test_annotation_generator_api_key_kwarg_emits_deprecation_warning
        # invokes the REAL AnnotationGenerator, not this fake; it's listed for documentation.
        type(self).last_provider = provider
        type(self).last_model = model
        self.failed_pages: list[int] = list(type(self)._inject_failed_pages)

    def generate_for_document(
        self, pages: list[PageContent], max_annotations_per_page: int = 5
    ) -> AnnotationPlan:
        type(self).calls += 1
        if type(self)._raise_all_failed:
            raise AllPagesFailedError("all pages failed — injected by test")
        return AnnotationPlan(
            title="seam-test plan",
            prince_persona="p",
            pages=[
                AnnotatedPage(page_number=p.page_number, original_text=p.text, annotations=[])
                for p in pages
            ],
        )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture()
def seam_fakes(monkeypatch: pytest.MonkeyPatch) -> _SentinelProvider:
    """Wire all CLI seam points with hermetic fakes.

    Returns the sentinel provider so AC 4 tests can verify identity.
    """
    _FakePdfProcessor.load_calls = []
    _CapturingGenerator.last_provider = None
    _CapturingGenerator.last_model = None
    _CapturingGenerator.calls = 0
    _CapturingGenerator._inject_failed_pages = []
    _CapturingGenerator._raise_all_failed = False

    sentinel = _SentinelProvider()
    monkeypatch.setattr(cli_module, "resolve_generation_config", lambda *a, **k: _FAKE_CONFIG)
    monkeypatch.setattr(cli_module, "build_provider", lambda *a, **k: sentinel)
    monkeypatch.setattr(cli_module, "AnnotationGenerator", _CapturingGenerator)
    monkeypatch.setattr(cli_module, "DocumentProcessor", _FakePdfProcessor)
    monkeypatch.setattr(cli_module, "EpubProcessor", _FakePdfProcessor)
    return sentinel


def _no_traceback(result) -> bool:
    return result.exception is None or isinstance(result.exception, SystemExit)


# ---------------------------------------------------------------------------
# AC 1 — Shared provider flags on annotate and preview
# ---------------------------------------------------------------------------

_PROVIDER_FLAGS = [
    "--provider",
    "--model",
    "--base-url",
    "--api-key-env",
    "--structured-output",
    "--timeout",
    "--max-retries",
    "--concurrency",
    "--allow-insecure-http",
    "--config",
]


@pytest.mark.parametrize("command", ["annotate", "preview"])
@pytest.mark.parametrize("flag", _PROVIDER_FLAGS)
def test_provider_flag_appears_in_help(runner: CliRunner, command: str, flag: str) -> None:
    """All 10 provider flags must appear in both annotate and preview --help output (AC 1).

    INTENDED FAILURE (before Codex builds): flags other than --model are absent from the
    current annotate/preview Click decorators, so they will not appear in --help output.
    The assertion `flag in result.output` will fail for each missing flag.
    """
    result = runner.invoke(cli_module.main, [command, "--help"])
    assert result.exit_code == 0, result.output
    assert flag in result.output, (
        f"Flag {flag!r} is missing from `halfblood {command} --help`.\n"
        f"All 10 provider flags from arch §4.4 must be declared on both commands."
    )


# ---------------------------------------------------------------------------
# AC 2 — Identical resolution across both commands
# ---------------------------------------------------------------------------


def test_annotate_and_preview_resolve_config_identically(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """annotate and preview must build identical cli_overrides from identical flags (AC 2).

    INTENDED FAILURE (before Codex builds): --provider is not yet a flag on either
    command, so the runner invocations exit with "No such option: --provider" (exit_code 2)
    and resolve_generation_config is never called.  The assertion ``len(captured) == 2``
    will fail.
    """
    captured: list[dict] = []

    def _capturing_resolver(cli_overrides=None, **kwargs):
        captured.append(dict(cli_overrides) if cli_overrides is not None else {})
        return _FAKE_CONFIG

    monkeypatch.setattr(cli_module, "resolve_generation_config", _capturing_resolver)
    monkeypatch.setattr(cli_module, "build_provider", lambda *a, **k: _SentinelProvider())
    monkeypatch.setattr(cli_module, "AnnotationGenerator", _CapturingGenerator)
    monkeypatch.setattr(cli_module, "DocumentProcessor", _FakePdfProcessor)
    monkeypatch.setattr(cli_module, "EpubProcessor", _FakePdfProcessor)
    _CapturingGenerator._inject_failed_pages = []
    _CapturingGenerator._raise_all_failed = False

    src = tmp_path / "book.pdf"
    src.write_bytes(_PDF_BYTES)

    annotate_result = runner.invoke(
        cli_module.main,
        [
            "annotate",
            str(src),
            "-o",
            str(tmp_path / "out.pdf"),
            "--provider",
            "anthropic",
            "--model",
            "claude-sonnet-5",
        ],
    )
    preview_result = runner.invoke(
        cli_module.main,
        [
            "preview",
            str(src),
            "--provider",
            "anthropic",
            "--model",
            "claude-sonnet-5",
        ],
    )

    assert annotate_result.exit_code == 0, (
        f"annotate failed: {annotate_result.output}"
    )
    assert preview_result.exit_code == 0, (
        f"preview failed: {preview_result.output}"
    )
    assert len(captured) == 2, (
        f"resolve_generation_config was called {len(captured)} time(s), expected 2 "
        f"(once for annotate, once for preview)"
    )
    assert captured[0] == captured[1], (
        f"annotate and preview passed different cli_overrides to resolve_generation_config:\n"
        f"  annotate: {captured[0]}\n"
        f"  preview:  {captured[1]}"
    )


# ---------------------------------------------------------------------------
# AC 3 — --config PATH feeds project_config_path
# ---------------------------------------------------------------------------


def test_config_flag_feeds_project_config_path(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """--config PATH must be forwarded as project_config_path= to resolve_generation_config (AC 3).

    INTENDED FAILURE (before Codex builds): --config is not yet a flag on annotate, so
    the runner invocation exits with "No such option: --config" and the captured kwarg
    remains unset.  The assertion on project_config_path will fail.
    """
    captured_kwargs: dict = {}

    def _capturing_resolver(cli_overrides=None, *, project_config_path=None, **kwargs):
        captured_kwargs["project_config_path"] = project_config_path
        return _FAKE_CONFIG

    monkeypatch.setattr(cli_module, "resolve_generation_config", _capturing_resolver)
    monkeypatch.setattr(cli_module, "build_provider", lambda *a, **k: _SentinelProvider())
    monkeypatch.setattr(cli_module, "AnnotationGenerator", _CapturingGenerator)
    monkeypatch.setattr(cli_module, "DocumentProcessor", _FakePdfProcessor)
    _CapturingGenerator._inject_failed_pages = []
    _CapturingGenerator._raise_all_failed = False

    src = tmp_path / "book.pdf"
    src.write_bytes(_PDF_BYTES)
    config_file = tmp_path / "halfblood.toml"
    config_file.write_text("[generation]\n", encoding="utf-8")

    result = runner.invoke(
        cli_module.main,
        [
            "annotate",
            str(src),
            "-o",
            str(tmp_path / "out.pdf"),
            "--provider",
            "anthropic",
            "--model",
            "claude-sonnet-5",
            "--config",
            str(config_file),
        ],
    )

    assert result.exit_code == 0, result.output
    assert captured_kwargs.get("project_config_path") == config_file, (
        f"--config PATH was not forwarded as project_config_path= to resolve_generation_config.\n"
        f"Got: {captured_kwargs.get('project_config_path')!r}\n"
        f"Expected: {config_file!r}"
    )


# ---------------------------------------------------------------------------
# AC 4 — No direct AnthropicProvider construction; provider identity check
# ---------------------------------------------------------------------------


def test_annotate_passes_provider_from_build_provider_to_generator(
    runner: CliRunner, seam_fakes: _SentinelProvider, tmp_path: Path
) -> None:
    """annotate must forward the provider object from build_provider to AnnotationGenerator (AC 4).

    The identity check (``is sentinel``) catches any path that constructs a NEW provider
    instead of forwarding the one that build_provider returned.

    INTENDED FAILURE (before Codex builds): --provider is not yet a flag on annotate, so
    the runner invocation exits with exit_code 2 and _CapturingGenerator is never
    instantiated.  The assertion ``_CapturingGenerator.calls == 1`` will fail.
    """
    sentinel = seam_fakes

    src = tmp_path / "book.pdf"
    src.write_bytes(_PDF_BYTES)

    result = runner.invoke(
        cli_module.main,
        [
            "annotate",
            str(src),
            "-o",
            str(tmp_path / "out.pdf"),
            "--provider",
            "anthropic",
            "--model",
            "claude-sonnet-5",
        ],
        env={"ANTHROPIC_API_KEY": _SENTINEL_KEY},
    )

    assert result.exit_code == 0, result.output
    assert _CapturingGenerator.calls == 1, (
        f"AnnotationGenerator.generate_for_document was not called (calls={_CapturingGenerator.calls})"
    )
    assert _CapturingGenerator.last_provider is sentinel, (
        f"AnnotationGenerator was not given the provider from build_provider.\n"
        f"Expected: {sentinel!r}\n"
        f"Got:      {_CapturingGenerator.last_provider!r}\n"
        "This means the CLI is still constructing AnthropicProvider directly "
        "instead of passing the result of build_provider."
    )


def test_preview_passes_provider_from_build_provider_to_generator(
    runner: CliRunner, seam_fakes: _SentinelProvider, tmp_path: Path
) -> None:
    """preview must forward the provider object from build_provider to AnnotationGenerator (AC 4).

    INTENDED FAILURE (before Codex builds): --provider is not yet a flag on preview, so
    the runner invocation exits with exit_code 2 and _CapturingGenerator is never called.
    """
    sentinel = seam_fakes

    src = tmp_path / "book.pdf"
    src.write_bytes(_PDF_BYTES)

    result = runner.invoke(
        cli_module.main,
        [
            "preview",
            str(src),
            "--provider",
            "anthropic",
            "--model",
            "claude-sonnet-5",
        ],
        env={"ANTHROPIC_API_KEY": _SENTINEL_KEY},
    )

    assert result.exit_code == 0, result.output
    assert _CapturingGenerator.calls == 1
    assert _CapturingGenerator.last_provider is sentinel, (
        f"preview did not pass the build_provider result to AnnotationGenerator.\n"
        f"Expected: {sentinel!r}\nGot: {_CapturingGenerator.last_provider!r}"
    )


# ---------------------------------------------------------------------------
# AC 5 — No universal model default; missing model surfaces as ClickException
# ---------------------------------------------------------------------------


def test_no_model_flag_omits_model_from_cli_overrides(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """When --model is omitted, the CLI must NOT inject DEFAULT_MODEL into cli_overrides (AC 5).

    The universal model default must be removed from the CLI.  Model resolution is
    entirely the config layer's responsibility.  If the CLI injects a default, it
    defeats the no-universal-default guarantee (arch §4.4).

    INTENDED FAILURE (before Codex builds): --provider is not yet a flag, so the
    invocation exits with "No such option" and resolve_generation_config is never called.
    The assertion ``len(captured) >= 1`` will fail.

    After Codex builds (incorrect implementation): if the CLI still passes model=DEFAULT_MODEL
    when --model is absent, the assertion ``overrides.get("model") is None`` will fail.
    """
    captured: list[dict] = []

    def _capturing_resolver(cli_overrides=None, **kwargs):
        captured.append(dict(cli_overrides) if cli_overrides is not None else {})
        return _FAKE_CONFIG

    monkeypatch.setattr(cli_module, "resolve_generation_config", _capturing_resolver)
    monkeypatch.setattr(cli_module, "build_provider", lambda *a, **k: _SentinelProvider())
    monkeypatch.setattr(cli_module, "AnnotationGenerator", _CapturingGenerator)
    monkeypatch.setattr(cli_module, "DocumentProcessor", _FakePdfProcessor)
    _CapturingGenerator._inject_failed_pages = []
    _CapturingGenerator._raise_all_failed = False

    src = tmp_path / "book.pdf"
    src.write_bytes(_PDF_BYTES)

    runner.invoke(
        cli_module.main,
        [
            "annotate",
            str(src),
            "-o",
            str(tmp_path / "out.pdf"),
            "--provider",
            "anthropic",
            # intentionally omit --model
        ],
    )

    assert len(captured) >= 1, (
        "resolve_generation_config was never called — either the CLI rejected "
        "--provider as an unknown flag, or it failed before resolving config."
    )
    overrides = captured[0]
    assert overrides.get("model") is None, (
        f"CLI injected a default model into cli_overrides: {overrides.get('model')!r}.\n"
        "The universal model default must be removed from the CLI.  When --model is not "
        "passed, 'model' must be absent or None in cli_overrides so the config layer "
        "raises ProviderConfigurationError."
    )


def test_non_anthropic_missing_model_surfaces_as_click_exception(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """For a non-anthropic profile, a missing model must surface as a click.ClickException
    with 'model' in the output (AC 5).

    Uses a mock resolver so the test is hermetic — we are testing CLI error-surfacing
    behavior (does ProviderConfigurationError become a ClickException?), not resolver
    behavior.  The hermetic resolver tests below test the resolver directly.

    INTENDED FAILURE (before Codex builds): --provider is not yet a flag, so the
    invocation fails with "No such option: --provider" which does not contain 'model'.
    The assertion ``'model' in result.output.lower()`` will fail.
    """

    def _reject_missing_model(cli_overrides=None, **kwargs):
        if not (cli_overrides or {}).get("model"):
            raise ProviderConfigurationError("model must be explicitly configured")
        return _FAKE_CONFIG

    monkeypatch.setattr(cli_module, "resolve_generation_config", _reject_missing_model)
    monkeypatch.setattr(cli_module, "build_provider", lambda *a, **k: _SentinelProvider())
    monkeypatch.setattr(cli_module, "AnnotationGenerator", _CapturingGenerator)
    monkeypatch.setattr(cli_module, "DocumentProcessor", _FakePdfProcessor)

    src = tmp_path / "book.pdf"
    src.write_bytes(_PDF_BYTES)

    result = runner.invoke(
        cli_module.main,
        [
            "annotate",
            str(src),
            "-o",
            str(tmp_path / "out.pdf"),
            "--provider",
            "openai",  # non-anthropic: no preset model default
            # intentionally omit --model
        ],
    )

    assert result.exit_code != 0
    assert _no_traceback(result), f"raw exception leaked: {result.exception!r}"
    assert "model" in result.output.lower(), (
        f"Expected the error to reference 'model' (ProviderConfigurationError); "
        f"got: {result.output!r}"
    )


# ---------------------------------------------------------------------------
# AC 5 (continued) — hermetic resolver tests and CLI test for anthropic default
#
# These three tests exercise the REAL resolve_generation_config so the preset-
# fallback path in config.py is genuinely exercised rather than mocked away.
# ---------------------------------------------------------------------------


def test_anthropic_preset_provides_default_model(tmp_path: Path) -> None:
    """With provider=anthropic and no model from any source, resolve_generation_config must
    return model='claude-sonnet-5' from the preset (AC 5 — provider-specific default).

    INTENDED FAILURE (before Codex builds): config.py does not yet have
    ProviderPreset.default_model or the fallback logic at the raise site; the current
    code raises ProviderConfigurationError("model must be explicitly configured") for
    every provider including anthropic.

    Uses a hermetic real resolver: injected environ, nonexistent config paths, so no
    machine-local file can influence the result. The environ carries ONLY the API key the
    merged contract requires for hosted providers (config.py raises "Environment variable
    ANTHROPIC_API_KEY is required" downstream of the model tier) — it deliberately carries
    no model, so the model must still come from the preset for this test to pass.
    """
    config = resolve_generation_config(
        {"provider": "anthropic"},
        environ={"ANTHROPIC_API_KEY": "sk-ant-test-not-a-real-key"},
        project_config_path=tmp_path / "nonexistent_project.toml",
        user_config_path=tmp_path / "nonexistent_user.toml",
    )

    assert config.model == "claude-sonnet-5", (
        f"anthropic preset must supply model='claude-sonnet-5' when no --model is given; "
        f"got {config.model!r}"
    )
    assert config.sources.get("model") == "preset", (
        f"sources['model'] must be 'preset' for the anthropic default fallback; "
        f"got {config.sources.get('model')!r}"
    )


def test_non_anthropic_providers_require_explicit_model(tmp_path: Path) -> None:
    """Every non-anthropic provider with no model from any source must raise
    ProviderConfigurationError mentioning 'model' (AC 5 — no carve-out for non-anthropic).

    This test is expected to PASS before Codex builds (config.py already raises for all
    providers) AND continue passing after (the anthropic carve-out must not bleed over).
    It is a regression guard against Codex accidentally extending the default to all profiles.

    Uses a hermetic real resolver: empty environ, nonexistent config paths.
    """
    non_anthropic = ["openai", "openrouter", "ollama", "lmstudio", "openai-compatible"]

    for profile in non_anthropic:
        with pytest.raises(ProviderConfigurationError) as exc_info:
            resolve_generation_config(
                {"provider": profile},
                environ={},
                project_config_path=tmp_path / "nonexistent_project.toml",
                user_config_path=tmp_path / "nonexistent_user.toml",
            )
        assert "model" in str(exc_info.value).lower(), (
            f"ProviderConfigurationError for provider={profile!r} must mention 'model'; "
            f"got: {exc_info.value!r}"
        )


def test_annotate_with_anthropic_and_no_model_uses_preset_default(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """annotate --provider anthropic (no --model) must exit 0 using the preset default (AC 5).

    Uses the REAL resolve_generation_config — NOT the seam_fakes-patched lambda — so the
    preset-fallback path in config.py is genuinely exercised.  Patching only build_provider
    and AnnotationGenerator so no real HTTP or API calls are made.

    INTENDED FAILURE (before Codex builds):
    (a) --provider is not yet a flag → exit_code 2 ("No such option"), OR
    (b) preset fallback not yet in config.py → ProviderConfigurationError → exit_code != 0.

    Note on hermeticity: the real resolver also reads user_config_path
    (~/.config/halfblood/config.toml by default).  We pass an empty project config
    via --config and use env={"ANTHROPIC_API_KEY": _SENTINEL_KEY} so only the preset
    default can supply the model.  If the test machine has a user config that sets model,
    the test still passes (model is set from user config, not preset).  The hermetic unit
    test above (test_anthropic_preset_provides_default_model) is the authoritative guard.
    """
    monkeypatch.setattr(cli_module, "build_provider", lambda *a, **k: _SentinelProvider())
    monkeypatch.setattr(cli_module, "AnnotationGenerator", _CapturingGenerator)
    monkeypatch.setattr(cli_module, "DocumentProcessor", _FakePdfProcessor)
    monkeypatch.setattr(cli_module, "EpubProcessor", _FakePdfProcessor)
    _CapturingGenerator.last_model = None
    _CapturingGenerator.last_provider = None
    _CapturingGenerator.calls = 0
    _CapturingGenerator._inject_failed_pages = []
    _CapturingGenerator._raise_all_failed = False

    src = tmp_path / "book.pdf"
    src.write_bytes(_PDF_BYTES)

    empty_config = tmp_path / "empty.toml"
    empty_config.write_text("", encoding="utf-8")

    result = runner.invoke(
        cli_module.main,
        [
            "annotate",
            str(src),
            "-o",
            str(tmp_path / "out.pdf"),
            "--provider",
            "anthropic",
            "--config",
            str(empty_config),
            # intentionally omit --model — anthropic preset must supply it
        ],
        env={"ANTHROPIC_API_KEY": _SENTINEL_KEY},
    )

    assert result.exit_code == 0, (
        f"annotate --provider anthropic with no --model must exit 0 via preset default.\n"
        f"exit_code={result.exit_code}: {result.output}"
    )
    assert _CapturingGenerator.last_model == "claude-sonnet-5", (
        f"AnnotationGenerator must receive model='claude-sonnet-5' (from anthropic preset); "
        f"got {_CapturingGenerator.last_model!r}"
    )


# ---------------------------------------------------------------------------
# AC 5c — eval/ regression guards: DEFAULT_MODEL stays importable AND
#         eval_harness.py itself stays importable after T9a changes.
#
# Both tests are expected to PASS before Codex builds AND continue passing
# afterwards. They are permanent regression guards, NOT red-first tests.
# ---------------------------------------------------------------------------


def test_annotation_generator_exports_default_model_constant() -> None:
    """DEFAULT_MODEL must remain an importable module-level constant (AC 5c).

    eval/eval_harness.py:60 imports DEFAULT_MODEL at module level.  Removing the
    universal default means the *parameter* stops defaulting to DEFAULT_MODEL, but
    the *module constant* itself must remain.  tests/ does not import eval_harness, so
    the gate can go green while eval/ is broken — this test is a permanent guard.

    EXPECTED TO PASS before Codex builds and after (regression guard, not red-first).
    """
    from halfblood.annotation_generator import DEFAULT_MODEL

    assert isinstance(DEFAULT_MODEL, str) and DEFAULT_MODEL, (
        "DEFAULT_MODEL must be a non-empty string constant; eval/eval_harness.py "
        "imports it at module level and will break if it is removed."
    )


def test_eval_harness_imports_without_error() -> None:
    """eval/eval_harness.py must remain importable after T9a changes (AC 5c).

    tests/ does not normally import eval_harness, so pytest can return green while
    eval/ is completely import-broken.  This test closes that gap.

    What it catches:
    - Codex removes DEFAULT_MODEL from annotation_generator.py (line 60 import fails)
    - Codex renames or removes the AnnotationGenerator class (line 65 import fails)
    - Any other top-level dependency of eval_harness that breaks on import

    We load via importlib so that the ``if __name__ == "__main__"`` guard at
    eval_harness.py:861 prevents the main() function from running.  sys.path is
    restored after the test.  No API calls are made.

    EXPECTED TO PASS before Codex builds and after (permanent regression guard).
    """
    import importlib.util
    import sys
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[1]
    harness_path = repo_root / "eval" / "eval_harness.py"
    assert harness_path.exists(), (
        f"eval/eval_harness.py not found at {harness_path!r}; "
        "update this path if eval/ was moved."
    )

    _MODULE_NAME = "_eval_harness_smoke"
    spec = importlib.util.spec_from_file_location(_MODULE_NAME, harness_path)
    assert spec is not None and spec.loader is not None, (
        f"importlib could not build a ModuleSpec for {harness_path!r}"
    )
    module = importlib.util.module_from_spec(spec)

    original_path = list(sys.path)
    # Register in sys.modules BEFORE exec so dataclasses can resolve its module
    # globals when processing string type annotations (dataclasses.py:749 does
    # sys.modules[cls.__module__].__dict__ to look up annotation names).
    sys.modules[_MODULE_NAME] = module
    try:
        spec.loader.exec_module(module)  # type: ignore[union-attr]
    except Exception as exc:
        raise AssertionError(
            f"eval/eval_harness.py raised {type(exc).__name__} on import: {exc}\n\n"
            "This is the gate guard for T9b's base.  Common causes after T9a:\n"
            "  - DEFAULT_MODEL was removed from annotation_generator.py\n"
            "  - AnnotationGenerator class was renamed or removed\n"
            "  - Another top-level dependency of eval_harness broke on import"
        ) from exc
    finally:
        sys.modules.pop(_MODULE_NAME, None)
        sys.path[:] = original_path

    assert isinstance(getattr(module, "_PIPELINE_DEFAULT_MODEL", None), str), (
        "eval_harness._PIPELINE_DEFAULT_MODEL is not a str after import — "
        "DEFAULT_MODEL was likely removed from annotation_generator.py"
    )


# ---------------------------------------------------------------------------
# AC 6 — Concurrency: CLI plumbs the flag through; resolver CLAMPS to 1.
#
# All five tests drive the REAL resolve_generation_config (resolver NOT patched)
# so the merged clamp in config.py is actually exercised.
#
# The capturing_build_provider helper records the ResolvedConfig that the CLI
# produced, letting us assert concurrency==1 and sources["concurrency"]==
# "phase1_enforced" without patching the resolver.
#
# INTENDED FAILURES (before Codex builds):
#   tests 1-4: --concurrency or --provider is not yet a flag → exit_code 2
#   test 5: --config is not yet a flag → exit_code 2
# ---------------------------------------------------------------------------


def _make_concurrency_fakes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> tuple[list, Path, Path]:
    """Patch build_provider + generator + processors; leave the REAL resolver in place.

    Returns (captured_configs, src_pdf, empty_config_path).
    """
    captured: list = []

    def _capturing_build_provider(config, *, api_key=None, attribution=None):
        captured.append(config)
        return _SentinelProvider()

    monkeypatch.setattr(cli_module, "build_provider", _capturing_build_provider)
    monkeypatch.setattr(cli_module, "AnnotationGenerator", _CapturingGenerator)
    monkeypatch.setattr(cli_module, "DocumentProcessor", _FakePdfProcessor)
    monkeypatch.setattr(cli_module, "EpubProcessor", _FakePdfProcessor)
    _CapturingGenerator.last_provider = None
    _CapturingGenerator.last_model = None
    _CapturingGenerator.calls = 0
    _CapturingGenerator._inject_failed_pages = []
    _CapturingGenerator._raise_all_failed = False

    src = tmp_path / "book.pdf"
    src.write_bytes(_PDF_BYTES)
    empty_cfg = tmp_path / "empty.toml"
    empty_cfg.write_text("", encoding="utf-8")
    return captured, src, empty_cfg


def test_explicit_concurrency_three_is_clamped_not_rejected(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog
) -> None:
    """--concurrency 3 must be ACCEPTED (exit 0); the resolver clamps it to 1 (AC 6).

    The CLI must NOT raise a UsageError or ClickException for out-of-range concurrency —
    that is the resolver's job.  Asserts: exit 0, resolved concurrency == 1,
    sources["concurrency"] == "phase1_enforced", and a warning was logged.

    INTENDED FAILURE (before Codex builds): --concurrency is not yet a flag, so Click
    exits with "No such option: --concurrency" (exit_code 2).
    The assertion ``result.exit_code == 0`` will fail.
    """
    import logging

    captured, src, empty_cfg = _make_concurrency_fakes(monkeypatch, tmp_path)

    with caplog.at_level(logging.WARNING):
        result = runner.invoke(
            cli_module.main,
            [
                "annotate",
                str(src),
                "-o",
                str(tmp_path / "out.pdf"),
                "--provider",
                "anthropic",
                "--model",
                "claude-sonnet-5",
                "--concurrency",
                "3",
                "--config",
                str(empty_cfg),
            ],
            env={"ANTHROPIC_API_KEY": _SENTINEL_KEY},
        )

    assert result.exit_code == 0, (
        f"--concurrency 3 must be accepted (CLI has no rejection logic; resolver clamps).\n"
        f"exit_code={result.exit_code}: {result.output}"
    )
    assert captured, "build_provider was never called — resolver may have raised"
    resolved = captured[0]
    assert resolved.concurrency == 1, (
        f"Resolved concurrency must be 1 (clamped from 3); got {resolved.concurrency}"
    )
    assert resolved.sources.get("concurrency") == "phase1_enforced", (
        f"sources['concurrency'] must be 'phase1_enforced'; got {resolved.sources.get('concurrency')!r}"
    )
    assert any("concurrency" in r.message.lower() for r in caplog.records), (
        f"Expected a log warning about concurrency being clamped; got: {caplog.records}"
    )


def test_explicit_concurrency_one_is_accepted(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """--concurrency 1 must be accepted (exit 0); resolver keeps it at 1 (AC 6).

    INTENDED FAILURE (before Codex builds): --concurrency is not yet a flag → exit_code 2.
    """
    captured, src, empty_cfg = _make_concurrency_fakes(monkeypatch, tmp_path)

    result = runner.invoke(
        cli_module.main,
        [
            "annotate",
            str(src),
            "-o",
            str(tmp_path / "out.pdf"),
            "--provider",
            "anthropic",
            "--model",
            "claude-sonnet-5",
            "--concurrency",
            "1",
            "--config",
            str(empty_cfg),
        ],
        env={"ANTHROPIC_API_KEY": _SENTINEL_KEY},
    )

    assert result.exit_code == 0, (
        f"--concurrency 1 must be accepted (matches Phase 1).\n"
        f"exit_code={result.exit_code}: {result.output}"
    )
    assert captured
    assert captured[0].concurrency == 1
    assert captured[0].sources.get("concurrency") == "phase1_enforced"


def test_no_concurrency_flag_accepted(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Omitting --concurrency must succeed; resolver defaults to 1 (AC 6).

    INTENDED FAILURE (before Codex builds): --provider is not yet a flag → exit_code 2.
    """
    captured, src, empty_cfg = _make_concurrency_fakes(monkeypatch, tmp_path)

    result = runner.invoke(
        cli_module.main,
        [
            "annotate",
            str(src),
            "-o",
            str(tmp_path / "out.pdf"),
            "--provider",
            "anthropic",
            "--model",
            "claude-sonnet-5",
            "--config",
            str(empty_cfg),
        ],
        env={"ANTHROPIC_API_KEY": _SENTINEL_KEY},
    )

    assert result.exit_code == 0, (
        f"Omitting --concurrency must succeed.\n"
        f"exit_code={result.exit_code}: {result.output}"
    )
    assert captured
    assert captured[0].concurrency == 1


def test_concurrency_via_config_file_is_clamped(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog
) -> None:
    """concurrency=3 in a --config TOML is clamped to 1 via the real resolver (AC 6).

    This is the config-file path test — it proves the clamp is not only a CLI-flag
    behavior but is enforced at the resolver level for any source.  Mirrors the merged
    test_concurrency_always_one_regardless_of_request in test_provider_config.py.

    INTENDED FAILURE (before Codex builds): --config is not yet a flag → exit_code 2.
    """
    import logging

    captured, src, _ = _make_concurrency_fakes(monkeypatch, tmp_path)

    project_toml = tmp_path / "halfblood.toml"
    project_toml.write_text(
        "[generation]\nconcurrency = 3\nprovider = \"anthropic\"\nmodel = \"claude-sonnet-5\"\n",
        encoding="utf-8",
    )

    with caplog.at_level(logging.WARNING):
        result = runner.invoke(
            cli_module.main,
            [
                "annotate",
                str(src),
                "-o",
                str(tmp_path / "out.pdf"),
                "--config",
                str(project_toml),
            ],
            env={"ANTHROPIC_API_KEY": _SENTINEL_KEY},
        )

    assert result.exit_code == 0, (
        f"concurrency=3 in TOML must succeed (resolver clamps it).\n"
        f"exit_code={result.exit_code}: {result.output}"
    )
    assert captured, "build_provider was never called"
    resolved = captured[0]
    assert resolved.concurrency == 1, (
        f"Resolved concurrency must be 1 (clamped from config-file value 3); got {resolved.concurrency}"
    )
    assert resolved.sources.get("concurrency") == "phase1_enforced", (
        f"sources['concurrency'] must be 'phase1_enforced'; got {resolved.sources.get('concurrency')!r}"
    )
    assert any("concurrency" in r.message.lower() for r in caplog.records), (
        f"Expected a log warning about concurrency being clamped; got: {caplog.records}"
    )


# ---------------------------------------------------------------------------
# AC 1 (continued) — --allow-insecure-http flag (10th shared flag)
#
# Both tests drive the REAL resolve_generation_config so the URL validation
# logic in config.py is genuinely exercised.
#
# INTENDED FAILURES (before Codex builds): --allow-insecure-http is not yet
# a flag; test 1 fails because the flag is rejected; test 2 may also fail.
# ---------------------------------------------------------------------------


def test_allow_insecure_http_flag_permits_hosted_http_base_url(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """--base-url http://hosted.example.com --allow-insecure-http must exit 0 (AC 1).

    Without the flag the resolver raises ProviderConfigurationError for a hosted HTTP
    URL.  With the flag it must succeed.  Tests the CLI-flag path through the real
    resolver so we confirm the flag is plumbed into cli_overrides correctly.

    INTENDED FAILURE (before Codex builds): --allow-insecure-http is not yet a flag
    → "No such option: --allow-insecure-http" → exit_code 2.
    """
    captured, src, empty_cfg = _make_concurrency_fakes(monkeypatch, tmp_path)

    result = runner.invoke(
        cli_module.main,
        [
            "annotate",
            str(src),
            "-o",
            str(tmp_path / "out.pdf"),
            "--provider",
            "openai",
            "--model",
            "gpt-4o",
            "--base-url",
            "http://hosted.example.com",
            "--allow-insecure-http",
            "--config",
            str(empty_cfg),
        ],
        env={"OPENAI_API_KEY": _SENTINEL_KEY},
    )

    assert result.exit_code == 0, (
        f"--allow-insecure-http must permit a hosted HTTP base_url.\n"
        f"exit_code={result.exit_code}: {result.output}"
    )
    assert captured, "build_provider was never called"


def test_hosted_http_base_url_without_flag_raises_click_exception(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """http:// non-loopback base_url without --allow-insecure-http → ClickException (AC 1).

    Mirrors merged test_base_url_hosted_http_rejected_without_allow_insecure in
    test_provider_config.py, but exercises the CLI error-surfacing path.

    INTENDED FAILURE (before Codex builds): --base-url is not yet a flag → "No such
    option: --base-url" → exit_code 2, but the error output won't mention "http" or
    "insecure" in the expected way.
    The assertion ``'http' in result.output.lower() or 'insecure' in result.output.lower()``
    may still pass on the Click error message, but the ``result.exit_code != 0`` assertion
    holds both ways; the discriminating assertion is that the error references the URL
    constraint, not just a CLI flag typo.
    """
    captured, src, empty_cfg = _make_concurrency_fakes(monkeypatch, tmp_path)

    result = runner.invoke(
        cli_module.main,
        [
            "annotate",
            str(src),
            "-o",
            str(tmp_path / "out.pdf"),
            "--provider",
            "openai",
            "--model",
            "gpt-4o",
            "--base-url",
            "http://hosted.example.com",
            # intentionally omit --allow-insecure-http
            "--config",
            str(empty_cfg),
        ],
        env={"OPENAI_API_KEY": _SENTINEL_KEY},
    )

    assert result.exit_code != 0, (
        f"Hosted HTTP base_url without --allow-insecure-http must fail.\n"
        f"Got exit_code=0: {result.output}"
    )
    assert _no_traceback(result), f"raw exception leaked: {result.exception!r}"
    output_lower = result.output.lower()
    assert "https" in output_lower or "insecure" in output_lower or "http" in output_lower, (
        f"Error must reference the URL/HTTPS constraint; got: {result.output!r}"
    )


# ---------------------------------------------------------------------------
# AC 7 — Banner shows provider/model/mode before calls; key never printed
# ---------------------------------------------------------------------------


def test_banner_shows_provider_model_and_mode(
    runner: CliRunner, seam_fakes: _SentinelProvider, tmp_path: Path
) -> None:
    """Before any provider calls, annotate must print the selected provider, model, and
    structured-output mode (AC 7).

    INTENDED FAILURE (before Codex builds): --provider is not yet a flag, so the
    invocation fails with exit_code 2; the assertion exit_code == 0 will fail.
    """
    src = tmp_path / "book.pdf"
    src.write_bytes(_PDF_BYTES)

    result = runner.invoke(
        cli_module.main,
        [
            "annotate",
            str(src),
            "-o",
            str(tmp_path / "out.pdf"),
            "--provider",
            "anthropic",
            "--model",
            "claude-sonnet-5",
        ],
        env={"ANTHROPIC_API_KEY": _SENTINEL_KEY},
    )

    assert result.exit_code == 0, result.output
    output_lower = result.output.lower()
    assert "anthropic" in output_lower, (
        f"Provider name 'anthropic' not found in output: {result.output!r}"
    )
    assert "claude-sonnet-5" in result.output, (
        f"Model 'claude-sonnet-5' not found in output: {result.output!r}"
    )
    assert "tool" in output_lower, (
        f"Structured-output mode 'tool' not found in output: {result.output!r}"
    )


def test_banner_does_not_leak_api_key(
    runner: CliRunner, seam_fakes: _SentinelProvider, tmp_path: Path
) -> None:
    """The API key value must never appear in annotate output (AC 7).

    INTENDED FAILURE (before Codex builds): --provider is not yet a flag, so the
    invocation fails with exit_code 2; the assertion exit_code == 0 will fail before
    the key-leak check is even reached.
    """
    src = tmp_path / "book.pdf"
    src.write_bytes(_PDF_BYTES)

    result = runner.invoke(
        cli_module.main,
        [
            "annotate",
            str(src),
            "-o",
            str(tmp_path / "out.pdf"),
            "--provider",
            "anthropic",
            "--model",
            "claude-sonnet-5",
        ],
        env={"ANTHROPIC_API_KEY": _SENTINEL_KEY},
    )

    assert result.exit_code == 0, result.output
    assert _SENTINEL_KEY not in result.output, (
        f"API key sentinel leaked into command output: {result.output!r}"
    )


# ---------------------------------------------------------------------------
# AC 8 — Partial failure / all-failed exit semantics preserved
# ---------------------------------------------------------------------------


def test_partial_failure_exits_0_with_warning(
    runner: CliRunner, seam_fakes: _SentinelProvider, tmp_path: Path
) -> None:
    """When some pages fail but not all, exit code must be 0 with a yellow warning (AC 8).

    INTENDED FAILURE (before Codex builds): --provider is not yet a flag, so the
    invocation fails with exit_code 2; the assertion exit_code == 0 will fail.
    """
    _CapturingGenerator._inject_failed_pages = [1]

    src = tmp_path / "book.pdf"
    src.write_bytes(_PDF_BYTES)

    result = runner.invoke(
        cli_module.main,
        [
            "annotate",
            str(src),
            "-o",
            str(tmp_path / "out.pdf"),
            "--provider",
            "anthropic",
            "--model",
            "claude-sonnet-5",
        ],
        env={"ANTHROPIC_API_KEY": _SENTINEL_KEY},
    )

    assert result.exit_code == 0, result.output
    assert "warning" in result.output.lower(), (
        f"Expected a warning about failed pages; got: {result.output!r}"
    )


def test_all_pages_failed_exits_nonzero_no_traceback(
    runner: CliRunner, seam_fakes: _SentinelProvider, tmp_path: Path
) -> None:
    """When AllPagesFailedError is raised, exit code must be non-zero with no traceback (AC 8).

    INTENDED FAILURE (before Codex builds): --provider is not yet a flag, so the
    invocation fails with exit_code 2 but _CapturingGenerator is never invoked;
    the assertion ``_CapturingGenerator.calls >= 1`` will fail.
    """
    _CapturingGenerator._raise_all_failed = True

    src = tmp_path / "book.pdf"
    src.write_bytes(_PDF_BYTES)

    result = runner.invoke(
        cli_module.main,
        [
            "annotate",
            str(src),
            "-o",
            str(tmp_path / "out.pdf"),
            "--provider",
            "anthropic",
            "--model",
            "claude-sonnet-5",
        ],
        env={"ANTHROPIC_API_KEY": _SENTINEL_KEY},
    )

    # Generator must have been invoked before the error (distinguishes from Click parse error)
    assert _CapturingGenerator.calls >= 1, (
        f"AnnotationGenerator was never called (calls={_CapturingGenerator.calls}); "
        "the command likely failed at flag parsing before reaching generation."
    )
    assert result.exit_code != 0
    assert _no_traceback(result), f"raw exception leaked: {result.exception!r}"


# ---------------------------------------------------------------------------
# AC 9 — web-preview is provider-free (zero LLM calls, no --provider flag)
# ---------------------------------------------------------------------------


def test_web_preview_makes_zero_provider_calls(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """web-preview must complete successfully even when the provider double raises on .complete().

    This is the zero-provider-calls regression guard (AC 9).  If web-preview ever
    invokes the LLM provider, _SentinelProvider.complete() will raise AssertionError,
    which the runner captures as result.exception — a non-SystemExit exception fails
    the _no_traceback check.

    This test is expected to PASS before Codex builds (web-preview is already provider-
    free) and continue passing afterwards.
    """
    sentinel = _SentinelProvider()
    monkeypatch.setattr(cli_module, "build_provider", lambda *a, **k: sentinel)

    def _fake_generate_preview(plan_path, output_path, book_text=None):
        Path(str(output_path)).write_text("preview-html", encoding="utf-8")
        return PreviewResult(Path(str(output_path)), 1, 0, 1)

    monkeypatch.setattr(cli_module, "generate_preview", _fake_generate_preview)

    plan_file = tmp_path / "plan.json"
    plan_file.write_text(
        AnnotationPlan(title="t", prince_persona="p", pages=[]).model_dump_json(),
        encoding="utf-8",
    )
    out = tmp_path / "preview.html"

    result = runner.invoke(
        cli_module.main,
        ["web-preview", str(plan_file), "-o", str(out), "--force"],
    )

    assert result.exit_code == 0, result.output
    assert _no_traceback(result), (
        f"provider.complete() was called by web-preview: {result.exception!r}\n"
        f"web-preview must read a saved plan and render HTML with zero LLM calls."
    )


def test_web_preview_rejects_provider_flag(runner: CliRunner) -> None:
    """web-preview must not accept --provider (it is provider-free; the flag would mislead) (AC 9).

    This test is expected to PASS before Codex builds (web-preview has no --provider).
    It guards against Codex accidentally adding provider flags to web-preview.
    """
    result = runner.invoke(cli_module.main, ["web-preview", "--help"])
    assert result.exit_code == 0, result.output
    assert "--provider" not in result.output, (
        f"web-preview --help shows --provider, but web-preview must be provider-free.\n"
        f"Output: {result.output!r}"
    )


# ---------------------------------------------------------------------------
# AC 10 — AnnotationGenerator(api_key=...) compatibility API emits DeprecationWarning
# ---------------------------------------------------------------------------


def test_annotation_generator_api_key_kwarg_emits_deprecation_warning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AnnotationGenerator(api_key=...) must emit a DeprecationWarning (AC 10).

    The api_key= path is the backward-compatibility API preserved for one minor release.
    It must still work (no error) but signal to callers that they should migrate to the
    provider= injection pattern.

    We monkeypatch AnthropicProvider to avoid real key validation.

    INTENDED FAILURE (before Codex builds): AnnotationGenerator.__init__ currently does
    not call warnings.warn(); no DeprecationWarning is emitted and the assertion that
    ``deprecation_warnings`` is non-empty will fail.
    """
    constructed: list[str] = []

    class _FakeAnthropicProvider:
        def __init__(self, api_key: str, **kwargs: object) -> None:
            constructed.append(api_key)

        @property
        def capabilities(self) -> ProviderCapabilities:
            return ProviderCapabilities(
                supports_tool_calling=True,
                supports_json_schema=False,
                supports_strict_json_schema=False,
            )

        def complete(self, request):
            raise RuntimeError("should not be called in this test")

    import halfblood.annotation_generator as ag_module

    monkeypatch.setattr(ag_module, "AnthropicProvider", _FakeAnthropicProvider)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        AnnotationGenerator(api_key="sk-fake-key-for-deprecation-test")

    deprecation_warnings = [w for w in caught if issubclass(w.category, DeprecationWarning)]
    assert deprecation_warnings, (
        "AnnotationGenerator(api_key=...) must emit a DeprecationWarning; none was captured.\n"
        "Add ``warnings.warn('api_key= is deprecated; pass provider= instead', "
        "DeprecationWarning, stacklevel=2)`` to the api_key path in __init__."
    )
    assert "api_key" in str(deprecation_warnings[0].message).lower(), (
        f"DeprecationWarning message should mention 'api_key'; "
        f"got: {deprecation_warnings[0].message!r}"
    )
    # Backward compat: must still actually construct the provider
    assert constructed == ["sk-fake-key-for-deprecation-test"], (
        f"AnthropicProvider was not constructed with the api_key; got: {constructed!r}"
    )
