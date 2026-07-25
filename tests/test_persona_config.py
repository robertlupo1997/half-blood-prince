"""Lane F — persona unification + --persona-file + config support.

All tests in this file are authored by the Lane F driver and were committed
RED (failing on main HEAD) before implementation.  Each docstring states
exactly why the test fails pre-impl and what change makes it green.

No network calls anywhere in this file.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

import halfblood.cli as cli_module
from halfblood.annotation_generator import DEFAULT_PERSONA, AnnotationGenerator
from halfblood.config import (
    ProviderConfigurationError,
    ResolvedConfig,
    resolve_generation_config,
)
from halfblood.document_processor import PageContent
from halfblood.generation.providers.base import ProviderCapabilities
from halfblood.models import AnnotatedPage, AnnotationPlan

# ---------------------------------------------------------------------------
# Shared test helpers
# ---------------------------------------------------------------------------

#: Minimal valid PDF magic bytes accepted by the magic-byte check in cli.py.
_PDF_BYTES = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n%%EOF\n"

_MISSING_TOML = "does-not-exist.toml"


class _FakeProvider:
    """Minimal LLMProvider double; .complete() is never called in these tests."""

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            supports_tool_calling=True,
            supports_json_schema=False,
            supports_strict_json_schema=False,
        )

    def complete(self, request):  # type: ignore[no-untyped-def]
        raise AssertionError(
            "provider.complete() called — AnnotationGenerator must be faked"
        )


class _FakePdfProcessor:
    """Minimal DocumentProcessor double for CLI-seam tests."""

    load_calls: list[str] = []

    def load(self, path: str) -> list[PageContent]:
        type(self).load_calls.append(path)
        return [PageContent(page_number=1, text="Bezoar.", width=612.0, height=792.0)]

    def render_annotations(self, input_path: str, annotations: list, output_path: str) -> None:
        Path(output_path).write_text("rendered-pdf", encoding="utf-8")

    def annotations_from_plan(self, plan: AnnotationPlan) -> list:
        return [a for page in plan.pages for a in page.annotations]


class _PersonaCapturingGenerator:
    """Fake AnnotationGenerator that records the persona= kwarg it received.

    Mirrors the real constructor signature exactly so cli.py gets a TypeError
    if it passes an unexpected keyword, rather than silently absorbing it.
    """

    last_persona: str | None = "UNSET"
    calls: int = 0

    def __init__(
        self,
        *,
        provider: object | None = None,
        persona: str | None = None,
        model: str | None = None,
        api_key: str | None = None,
        concurrency: int = 3,
    ) -> None:
        type(self).last_persona = persona
        self.failed_pages: list[int] = []

    def generate_for_document(
        self,
        pages: list[PageContent],
        max_annotations_per_page: int = 5,
        *,
        on_page_done: object = None,
    ) -> AnnotationPlan:
        type(self).calls += 1
        return AnnotationPlan(
            title="persona-test plan",
            prince_persona="x",
            pages=[
                AnnotatedPage(page_number=p.page_number, original_text=p.text, annotations=[])
                for p in pages
            ],
        )


def _fake_config(persona: str | None = None) -> ResolvedConfig:
    """Build a ResolvedConfig for CLI-seam tests.

    api_key_env=None avoids the key-presence check in cli.py.
    persona= carries whatever the config layer resolved.

    This was a hand-maintained ``SimpleNamespace`` mimicking ``ResolvedConfig``, and it
    went stale the moment ``max_per_page``/``font`` were added: nine CLI tests died with
    ``'types.SimpleNamespace' object has no attribute 'font'``. Using the real dataclass
    means a new field with a default is picked up automatically, and a new *required*
    field fails loudly right here instead of scattering AttributeErrors across the suite.
    """
    return ResolvedConfig(
        provider="anthropic",
        model="claude-sonnet-5",
        base_url="https://api.anthropic.com",
        api_key_env=None,
        structured_output="tool",
        timeout_seconds=60.0,
        max_retries=0,
        concurrency=3,
        allow_insecure_http=False,
        persona=persona,
        sources={},
    )


@pytest.fixture()
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture()
def persona_fakes(monkeypatch: pytest.MonkeyPatch) -> _FakeProvider:
    """Patch all CLI seam points with hermetic fakes. Returns the fake provider."""
    _FakePdfProcessor.load_calls = []
    _PersonaCapturingGenerator.last_persona = "UNSET"
    _PersonaCapturingGenerator.calls = 0

    provider = _FakeProvider()
    monkeypatch.setattr(cli_module, "resolve_generation_config", lambda *a, **k: _fake_config())
    monkeypatch.setattr(cli_module, "build_provider", lambda *a, **k: provider)
    monkeypatch.setattr(cli_module, "AnnotationGenerator", _PersonaCapturingGenerator)
    monkeypatch.setattr(cli_module, "DocumentProcessor", _FakePdfProcessor)
    monkeypatch.setattr(cli_module, "EpubProcessor", _FakePdfProcessor)
    return provider


def _resolve_config(
    tmp_path: Path,
    cli_overrides: dict | None = None,
    environ: dict | None = None,
    project_toml: str | None = None,
    user_toml: str | None = None,
) -> object:
    """Helper: write TOML files to tmp_path and call resolve_generation_config.

    Always includes ANTHROPIC_API_KEY in environ so the default anthropic
    provider doesn't raise before reaching persona resolution.
    """
    env: dict[str, str] = {"ANTHROPIC_API_KEY": "test-key"}
    env.update(environ or {})

    overrides = dict(cli_overrides or {})
    overrides.setdefault("model", "test-model")

    project_path = tmp_path / "project.toml"
    if project_toml is not None:
        project_path.write_text(project_toml, encoding="utf-8")
    else:
        project_path = tmp_path / _MISSING_TOML

    user_path = tmp_path / "user.toml"
    if user_toml is not None:
        user_path.write_text(user_toml, encoding="utf-8")
    else:
        user_path = tmp_path / ("user_" + _MISSING_TOML)

    return resolve_generation_config(
        overrides,
        environ=env,
        project_config_path=project_path,
        user_config_path=user_path,
    )


# ===========================================================================
# Group 1: Generator default persona (mostly green today; establishes baseline)
# ===========================================================================


def test_generator_default_persona_contains_snape_signature() -> None:
    """DEFAULT_PERSONA is the full Half-Blood Prince persona, not the short generic text.

    GREEN today: DEFAULT_PERSONA in annotation_generator.py is already the full Snape block.
    This test is the baseline that 'the Snape persona is reachable at the generator level'.
    """
    assert "Half-Blood Prince" in DEFAULT_PERSONA, (
        "DEFAULT_PERSONA must start with the Half-Blood Prince identity, not a generic one."
    )
    assert "Severus Snape" in DEFAULT_PERSONA, (
        "DEFAULT_PERSONA must reference Severus Snape."
    )


def test_generator_none_persona_uses_snape_default() -> None:
    """AnnotationGenerator(persona=None) resolves to the full DEFAULT_PERSONA at self.persona.

    GREEN today: annotation_generator.py already does `self.persona = persona or DEFAULT_PERSONA`.
    """
    # Use a fake provider so no API key is needed.
    gen = AnnotationGenerator(persona=None, provider=_FakeProvider())
    assert gen.persona == DEFAULT_PERSONA, (
        "AnnotationGenerator(persona=None) must use DEFAULT_PERSONA (the full Snape text)."
    )


def test_generator_explicit_persona_overrides_default() -> None:
    """AnnotationGenerator(persona='custom') uses the custom persona, not Snape.

    GREEN today.
    """
    gen = AnnotationGenerator(persona="A custom annotator.", provider=_FakeProvider())
    assert gen.persona == "A custom annotator."


# ===========================================================================
# Group 2: CLI default passes None to generator
# ===========================================================================


def test_cli_annotate_bare_passes_none_to_generator(
    runner: CliRunner, persona_fakes: _FakeProvider, tmp_path: Path
) -> None:
    """Bare `halfblood annotate` (no --persona flag) passes persona=None to AnnotationGenerator.

    RED today: cli.py has `@click.option("--persona", default=DEFAULT_PERSONA, ...)` which
    always supplies the short generic string.  After the fix, the default must be None so
    the generator falls back to its own Snape persona.

    The fix: change `default=DEFAULT_PERSONA` to `default=None` on annotate's --persona option,
    and thread the resolved persona (CLI > config > None) instead of the flag value directly.
    """
    src = tmp_path / "book.pdf"
    src.write_bytes(_PDF_BYTES)
    out = tmp_path / "out.pdf"

    result = runner.invoke(cli_module.main, ["annotate", str(src), "-o", str(out)])

    assert result.exit_code == 0, f"annotate failed: {result.output}"
    assert _PersonaCapturingGenerator.last_persona is None, (
        f"Expected persona=None (generator uses Snape default); "
        f"got {_PersonaCapturingGenerator.last_persona!r}.  "
        "The CLI must pass None when --persona is not given."
    )


def test_cli_preview_bare_passes_none_to_generator(
    runner: CliRunner, persona_fakes: _FakeProvider, tmp_path: Path
) -> None:
    """Bare `halfblood preview` (no --persona flag) passes persona=None to AnnotationGenerator.

    RED today: same root cause as annotate — `default=DEFAULT_PERSONA` on preview's --persona.
    """
    src = tmp_path / "book.pdf"
    src.write_bytes(_PDF_BYTES)

    result = runner.invoke(cli_module.main, ["preview", str(src)])

    assert result.exit_code == 0, f"preview failed: {result.output}"
    assert _PersonaCapturingGenerator.last_persona is None, (
        f"Expected persona=None (generator uses Snape default); "
        f"got {_PersonaCapturingGenerator.last_persona!r}."
    )


def test_cli_explicit_persona_flag_passes_text_to_generator(
    runner: CliRunner, persona_fakes: _FakeProvider, tmp_path: Path
) -> None:
    """Explicit `--persona 'custom text'` is passed verbatim to AnnotationGenerator.

    GREEN after the fix (the flag still works; only the default changes).
    Also passes today IF persona fakes already return persona=None from config.
    This test is a regression guard: the --persona flag must not be silently dropped.
    """
    src = tmp_path / "book.pdf"
    src.write_bytes(_PDF_BYTES)
    out = tmp_path / "out.pdf"

    result = runner.invoke(
        cli_module.main,
        ["annotate", str(src), "-o", str(out), "--persona", "Custom annotator voice."],
    )

    assert result.exit_code == 0, f"annotate failed: {result.output}"
    assert _PersonaCapturingGenerator.last_persona == "Custom annotator voice.", (
        f"Expected explicit persona passed through; "
        f"got {_PersonaCapturingGenerator.last_persona!r}."
    )


# ===========================================================================
# Group 3: --persona-file flag
# ===========================================================================


def test_persona_file_flag_appears_in_annotate_help(runner: CliRunner) -> None:
    """--persona-file must appear in `halfblood annotate --help`.

    RED today: the flag does not exist.
    """
    result = runner.invoke(cli_module.main, ["annotate", "--help"])
    assert result.exit_code == 0, result.output
    assert "--persona-file" in result.output, (
        "--persona-file is missing from `halfblood annotate --help`."
    )


def test_persona_file_flag_appears_in_preview_help(runner: CliRunner) -> None:
    """--persona-file must appear in `halfblood preview --help`.

    RED today: the flag does not exist.
    """
    result = runner.invoke(cli_module.main, ["preview", "--help"])
    assert result.exit_code == 0, result.output
    assert "--persona-file" in result.output, (
        "--persona-file is missing from `halfblood preview --help`."
    )


def test_persona_file_reads_file_content_as_persona(
    runner: CliRunner, persona_fakes: _FakeProvider, tmp_path: Path
) -> None:
    """--persona-file PATH reads the file's UTF-8 text and passes it as the persona.

    RED today: the flag does not exist, so the CLI exits with 'No such option'.
    """
    persona_text = "A meticulous chemist who annotates with cold precision."
    persona_path = tmp_path / "custom_persona.txt"
    persona_path.write_text(persona_text, encoding="utf-8")

    src = tmp_path / "book.pdf"
    src.write_bytes(_PDF_BYTES)
    out = tmp_path / "out.pdf"

    result = runner.invoke(
        cli_module.main,
        ["annotate", str(src), "-o", str(out), "--persona-file", str(persona_path)],
    )

    assert result.exit_code == 0, f"annotate failed: {result.output}"
    assert _PersonaCapturingGenerator.last_persona == persona_text, (
        f"Expected persona from file; got {_PersonaCapturingGenerator.last_persona!r}."
    )


def test_persona_file_preview_reads_file_content(
    runner: CliRunner, persona_fakes: _FakeProvider, tmp_path: Path
) -> None:
    """--persona-file also works on the preview command.

    RED today: the flag does not exist on preview.
    """
    persona_text = "A dry medieval scholar with no patience for errors."
    persona_path = tmp_path / "scholar.txt"
    persona_path.write_text(persona_text, encoding="utf-8")

    src = tmp_path / "book.pdf"
    src.write_bytes(_PDF_BYTES)

    result = runner.invoke(
        cli_module.main,
        ["preview", str(src), "--persona-file", str(persona_path)],
    )

    assert result.exit_code == 0, f"preview failed: {result.output}"
    assert _PersonaCapturingGenerator.last_persona == persona_text


def test_persona_file_missing_raises_click_exception(
    runner: CliRunner, persona_fakes: _FakeProvider, tmp_path: Path
) -> None:
    """--persona-file pointing to a non-existent path emits a ClickException, not a traceback.

    RED today: flag doesn't exist — exits with 'No such option' (exit_code 2).
    After the fix: exit_code 1, output mentions the missing file path.
    """
    src = tmp_path / "book.pdf"
    src.write_bytes(_PDF_BYTES)
    out = tmp_path / "out.pdf"
    missing = tmp_path / "no_such_persona.txt"

    result = runner.invoke(
        cli_module.main,
        ["annotate", str(src), "-o", str(out), "--persona-file", str(missing)],
    )

    # A Click error (UsageError or ClickException) exits with 1 or 2.
    assert result.exit_code != 0, "Should fail when persona-file is missing."
    assert str(missing) in result.output or "no_such_persona" in result.output, (
        f"Error output must mention the missing file path. Got: {result.output!r}"
    )
    assert result.exception is None or isinstance(result.exception, SystemExit), (
        f"Must not produce a raw traceback. Exception: {result.exception!r}"
    )


def test_persona_and_persona_file_both_given_is_usage_error(
    runner: CliRunner, persona_fakes: _FakeProvider, tmp_path: Path
) -> None:
    """Giving both --persona and --persona-file on the same command is a usage error.

    RED today: --persona-file doesn't exist → "No such option" (exit_code 2, wrong error).
    After the fix: exit_code != 0, error specifically about mutually exclusive / conflicting
    persona options (NOT a "No such option" message).
    """
    persona_path = tmp_path / "persona.txt"
    persona_path.write_text("Some persona.", encoding="utf-8")

    src = tmp_path / "book.pdf"
    src.write_bytes(_PDF_BYTES)
    out = tmp_path / "out.pdf"

    result = runner.invoke(
        cli_module.main,
        [
            "annotate", str(src), "-o", str(out),
            "--persona", "Inline persona.",
            "--persona-file", str(persona_path),
        ],
    )

    assert result.exit_code != 0, (
        "Giving both --persona and --persona-file must fail."
    )
    output_lower = result.output.lower()
    # Must NOT be a "no such option" error — that would mean --persona-file still doesn't exist.
    assert "no such option" not in output_lower, (
        f"Error must not be 'no such option' — --persona-file must exist. Got: {result.output!r}"
    )
    assert any(word in output_lower for word in ("mutually exclusive", "conflict", "cannot")), (
        f"Error message must describe the persona/persona-file conflict. Got: {result.output!r}"
    )


# ===========================================================================
# Group 4: Config persona resolution (resolve_generation_config)
# ===========================================================================


def test_config_persona_from_project_toml(tmp_path: Path) -> None:
    """[generation].persona in the project TOML is resolved into ResolvedConfig.persona.

    RED today: resolve_generation_config ignores [generation].persona; ResolvedConfig has
    no persona field.
    """
    project_toml = '[generation]\npersona = "A clinical historian."\n'
    result = _resolve_config(tmp_path, project_toml=project_toml)

    assert hasattr(result, "persona"), "ResolvedConfig must have a persona field."
    assert result.persona == "A clinical historian.", (
        f"Expected persona from project toml; got {result.persona!r}."
    )
    assert result.sources.get("persona") == "project_config", (
        f"persona source must be 'project_config'; got {result.sources.get('persona')!r}."
    )


def test_config_persona_from_user_toml(tmp_path: Path) -> None:
    """[generation].persona in the user TOML is resolved when no project/CLI value exists.

    RED today: same root cause as project_toml test.
    """
    user_toml = '[generation]\npersona = "A sardonic librarian."\n'
    result = _resolve_config(tmp_path, user_toml=user_toml)

    assert hasattr(result, "persona"), "ResolvedConfig must have a persona field."
    assert result.persona == "A sardonic librarian."
    assert result.sources.get("persona") == "user_config"


def test_config_persona_from_halfblood_persona_env(tmp_path: Path) -> None:
    """HALFBLOOD_PERSONA env var is resolved into ResolvedConfig.persona.

    RED today: HALFBLOOD_PERSONA is not in _ENVIRONMENT_FIELDS.
    """
    result = _resolve_config(
        tmp_path,
        environ={"HALFBLOOD_PERSONA": "An impatient physicist."},
    )

    assert hasattr(result, "persona"), "ResolvedConfig must have a persona field."
    assert result.persona == "An impatient physicist."
    assert result.sources.get("persona") == "environment"


def test_config_persona_from_halfblood_persona_file_env(tmp_path: Path) -> None:
    """HALFBLOOD_PERSONA_FILE env var (absolute path) is read and resolved as the persona.

    RED today: the env var doesn't exist; also no file-reading logic in config.
    Uses an absolute path because the env-relative-to-cwd base is unspecified.
    """
    persona_text = "A blunt Russian chemist from the Soviet era."
    persona_file = tmp_path / "env_persona.txt"
    persona_file.write_text(persona_text, encoding="utf-8")

    result = _resolve_config(
        tmp_path,
        environ={"HALFBLOOD_PERSONA_FILE": str(persona_file)},
    )

    assert hasattr(result, "persona"), "ResolvedConfig must have a persona field."
    assert result.persona == persona_text, (
        f"Expected persona from HALFBLOOD_PERSONA_FILE; got {result.persona!r}."
    )
    assert result.sources.get("persona") == "environment"


def test_config_persona_file_relative_to_config_dir(tmp_path: Path) -> None:
    """[generation].persona_file in TOML is resolved relative to the TOML file's directory.

    RED today: persona_file key is not recognized; path resolution doesn't exist.
    """
    persona_text = "A mordant Enlightenment-era natural philosopher."
    persona_file = tmp_path / "snape_voice.txt"
    persona_file.write_text(persona_text, encoding="utf-8")

    # Relative path (relative to the project toml's directory = tmp_path)
    project_toml = '[generation]\npersona_file = "snape_voice.txt"\n'
    result = _resolve_config(tmp_path, project_toml=project_toml)

    assert hasattr(result, "persona"), "ResolvedConfig must have a persona field."
    assert result.persona == persona_text, (
        f"Expected persona file content; got {result.persona!r}."
    )
    assert result.sources.get("persona") == "project_config"


def test_config_persona_precedence_cli_over_env_over_project_over_user(tmp_path: Path) -> None:
    """Precedence chain: CLI > env > project toml > user toml > None (generator default).

    RED today: ResolvedConfig doesn't carry persona.

    Also covers the cross-level-no-false-conflict case: CLI persona overrides project
    persona_file at a lower level — this must NOT raise a conflict error.
    """
    # user toml: lowest priority
    user_toml = '[generation]\npersona = "User-level persona."\n'
    # project toml: should lose to env
    project_toml = '[generation]\npersona = "Project-level persona."\n'
    # env: should lose to CLI
    env = {"HALFBLOOD_PERSONA": "Env-level persona."}

    # env wins over project and user
    result_env = _resolve_config(tmp_path, environ=env, project_toml=project_toml, user_toml=user_toml)
    assert result_env.persona == "Env-level persona.", (
        f"Env must beat project and user toml; got {result_env.persona!r}."
    )

    # CLI (via cli_overrides) wins over env
    result_cli = _resolve_config(
        tmp_path,
        cli_overrides={"persona": "CLI-level persona."},
        environ=env,
        project_toml=project_toml,
        user_toml=user_toml,
    )
    assert result_cli.persona == "CLI-level persona.", (
        f"CLI must beat env; got {result_cli.persona!r}."
    )

    # Cross-level: CLI persona overrides project persona_file — no conflict error
    persona_file = tmp_path / "voice.txt"
    persona_file.write_text("File persona.", encoding="utf-8")
    project_with_file = '[generation]\npersona_file = "voice.txt"\n'
    result_cross = _resolve_config(
        tmp_path,
        cli_overrides={"persona": "CLI overrides file."},
        project_toml=project_with_file,
    )
    assert result_cross.persona == "CLI overrides file.", (
        "CLI --persona must override project persona_file without raising a conflict. "
        f"Got: {result_cross.persona!r}."
    )

    # User toml wins over None
    result_user = _resolve_config(tmp_path, user_toml=user_toml)
    assert result_user.persona == "User-level persona."


def test_config_project_toml_same_level_persona_and_persona_file_is_error(tmp_path: Path) -> None:
    """[generation] with BOTH persona and persona_file in the same TOML → ProviderConfigurationError.

    RED today: neither key is recognized, so no conflict is detected.
    After the fix: raises ProviderConfigurationError with a meaningful message.
    """
    persona_file = tmp_path / "voice.txt"
    persona_file.write_text("File content.", encoding="utf-8")

    project_toml = (
        '[generation]\n'
        'persona = "Inline persona."\n'
        'persona_file = "voice.txt"\n'
    )

    with pytest.raises(ProviderConfigurationError, match="persona"):
        _resolve_config(tmp_path, project_toml=project_toml)


def test_config_user_toml_same_level_persona_and_persona_file_is_error(tmp_path: Path) -> None:
    """[generation] with BOTH persona and persona_file in the same USER toml → error.

    RED today: same root cause.
    """
    persona_file = tmp_path / "voice.txt"
    persona_file.write_text("File content.", encoding="utf-8")

    user_toml = (
        '[generation]\n'
        'persona = "Inline persona."\n'
        'persona_file = "voice.txt"\n'
    )

    with pytest.raises(ProviderConfigurationError, match="persona"):
        _resolve_config(tmp_path, user_toml=user_toml)


def test_config_no_persona_resolves_to_none(tmp_path: Path) -> None:
    """When no persona is configured at any layer, ResolvedConfig.persona is None.

    RED today: ResolvedConfig has no persona attribute at all.
    After the fix: persona=None (generator uses Snape fallback).
    """
    result = _resolve_config(tmp_path)

    assert hasattr(result, "persona"), "ResolvedConfig must have a persona field."
    assert result.persona is None, (
        f"No persona configured → persona must be None; got {result.persona!r}."
    )


def test_config_persona_file_missing_raises_configuration_error(tmp_path: Path) -> None:
    """[generation].persona_file pointing to a non-existent file → ProviderConfigurationError.

    RED today: persona_file key is not recognized so this passes silently.
    After the fix: config layer raises before CLI touches it.
    """
    project_toml = '[generation]\npersona_file = "does_not_exist.txt"\n'

    with pytest.raises(ProviderConfigurationError):
        _resolve_config(tmp_path, project_toml=project_toml)


# ===========================================================================
# Group 5: CLI threads resolved persona from config to AnnotationGenerator
# ===========================================================================


def test_cli_threads_config_persona_to_generator_when_no_flag(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """When --persona is absent, the CLI reads config.persona and passes it to the generator.

    RED today: cli.py ignores config.persona entirely. With --persona default=None (after
    the first fix), the generator receives None, not the config-resolved value.

    After both fixes: resolved persona travels from config layer → cli.py → AnnotationGenerator.
    """
    _FakePdfProcessor.load_calls = []
    _PersonaCapturingGenerator.last_persona = "UNSET"
    _PersonaCapturingGenerator.calls = 0

    fake_provider = _FakeProvider()
    monkeypatch.setattr(
        cli_module,
        "resolve_generation_config",
        lambda *a, **k: _fake_config(persona="config-resolved-persona"),
    )
    monkeypatch.setattr(cli_module, "build_provider", lambda *a, **k: fake_provider)
    monkeypatch.setattr(cli_module, "AnnotationGenerator", _PersonaCapturingGenerator)
    monkeypatch.setattr(cli_module, "DocumentProcessor", _FakePdfProcessor)
    monkeypatch.setattr(cli_module, "EpubProcessor", _FakePdfProcessor)

    src = tmp_path / "book.pdf"
    src.write_bytes(_PDF_BYTES)
    out = tmp_path / "out.pdf"

    result = runner.invoke(cli_module.main, ["annotate", str(src), "-o", str(out)])

    assert result.exit_code == 0, f"annotate failed: {result.output}"
    assert _PersonaCapturingGenerator.last_persona == "config-resolved-persona", (
        f"Expected persona from config; got {_PersonaCapturingGenerator.last_persona!r}. "
        "cli.py must read config.persona and pass it when --persona is not given."
    )


def test_cli_explicit_persona_flag_overrides_config_persona(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Explicit --persona flag overrides whatever config.persona contains.

    RED today: config.persona doesn't exist on ResolvedConfig; also cli.py ignores it.
    After the fix: CLI flag wins and the generator receives the flag value.
    """
    _FakePdfProcessor.load_calls = []
    _PersonaCapturingGenerator.last_persona = "UNSET"
    _PersonaCapturingGenerator.calls = 0

    fake_provider = _FakeProvider()
    monkeypatch.setattr(
        cli_module,
        "resolve_generation_config",
        lambda *a, **k: _fake_config(persona="config-level-persona"),
    )
    monkeypatch.setattr(cli_module, "build_provider", lambda *a, **k: fake_provider)
    monkeypatch.setattr(cli_module, "AnnotationGenerator", _PersonaCapturingGenerator)
    monkeypatch.setattr(cli_module, "DocumentProcessor", _FakePdfProcessor)
    monkeypatch.setattr(cli_module, "EpubProcessor", _FakePdfProcessor)

    src = tmp_path / "book.pdf"
    src.write_bytes(_PDF_BYTES)
    out = tmp_path / "out.pdf"

    result = runner.invoke(
        cli_module.main,
        ["annotate", str(src), "-o", str(out), "--persona", "CLI flag persona."],
    )

    assert result.exit_code == 0, f"annotate failed: {result.output}"
    assert _PersonaCapturingGenerator.last_persona == "CLI flag persona.", (
        f"CLI --persona must override config.persona; got {_PersonaCapturingGenerator.last_persona!r}."
    )
