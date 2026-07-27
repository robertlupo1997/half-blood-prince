"""Config keys for the two render settings that still had no config support.

`halfblood.toml` already covers provider, model, base_url, api_key_env,
structured_output, timeout, max_retries, concurrency, allow_insecure_http and persona.
The two settings a user changes most often for *output* rather than *transport* --
how many notes land on a page, and which handwriting font draws them -- were CLI-only,
so there was no way to set them once for a machine or a project.

Two design decisions, stated because neither is forced:

1. **One `font` key, not `font_path`.** The `--font` flag takes a registered name *or*
   a path (`NAME|PATH`), and a config key that accepted only paths would be strictly
   less capable than the flag it mirrors -- a user who set `font = "caveat-brush"`
   would get a confusing failure. The key accepts exactly what the flag accepts.

2. **A relative `font` that names an existing file is resolved against the config file's
   directory**, matching the `persona_file` precedent. A project config saying
   `font = "assets/hand.ttf"` must not depend on the directory the user happens to run
   from. Values that are not existing relative files (registered names, absolute paths,
   typos) pass through untouched, so `_resolve_font_option` keeps producing its own
   errors and the name/path heuristic is not duplicated into `config.py`.

Hermeticity: every test here goes through `_resolve_config`, which passes `environ`,
`project_config_path` and `user_config_path` explicitly. The autouse fixture in
conftest.py additionally neutralises the default user-config lookup. Both matter -- a
hostile `$XDG_CONFIG_HOME/halfblood/config.toml` turned two other tests red before that
fixture existed.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from halfblood import cli as cli_module
from halfblood.config import resolve_generation_config
from halfblood.document_processor import PageContent
from halfblood.generation.errors import ProviderConfigurationError
from halfblood.models import AnnotationPlan


def _resolve_config(
    tmp_path: Path,
    cli_overrides: dict | None = None,
    environ: dict | None = None,
    project_toml: str | None = None,
    user_toml: str | None = None,
):
    """Fully injected resolver call: no cwd, no real user config, no ambient env."""
    env: dict[str, str] = {"ANTHROPIC_API_KEY": "test-key"}
    env.update(environ or {})

    overrides = dict(cli_overrides or {})
    overrides.setdefault("model", "test-model")

    project_path = tmp_path / "project.toml"
    if project_toml is not None:
        project_path.write_text(project_toml, encoding="utf-8")

    user_path = tmp_path / "user.toml"
    if user_toml is not None:
        user_path.write_text(user_toml, encoding="utf-8")

    return resolve_generation_config(
        overrides,
        environ=env,
        project_config_path=project_path,
        user_config_path=user_path,
    )


# ---------------------------------------------------------------------------
# max_per_page
# ---------------------------------------------------------------------------


class TestMaxPerPage:
    def test_defaults_to_five_when_unset(self, tmp_path: Path) -> None:
        """Must match the CLI's long-standing --max-per-page default."""
        assert _resolve_config(tmp_path).max_per_page == 5

    def test_from_project_toml(self, tmp_path: Path) -> None:
        result = _resolve_config(tmp_path, project_toml="[generation]\nmax_per_page = 3\n")
        assert result.max_per_page == 3
        assert result.sources.get("max_per_page") == "project_config"

    def test_from_user_toml(self, tmp_path: Path) -> None:
        result = _resolve_config(tmp_path, user_toml="[generation]\nmax_per_page = 2\n")
        assert result.max_per_page == 2
        assert result.sources.get("max_per_page") == "user_config"

    def test_project_outranks_user(self, tmp_path: Path) -> None:
        result = _resolve_config(
            tmp_path,
            project_toml="[generation]\nmax_per_page = 3\n",
            user_toml="[generation]\nmax_per_page = 9\n",
        )
        assert result.max_per_page == 3

    def test_environment_outranks_project(self, tmp_path: Path) -> None:
        result = _resolve_config(
            tmp_path,
            environ={"HALFBLOOD_MAX_PER_PAGE": "4"},
            project_toml="[generation]\nmax_per_page = 3\n",
        )
        assert result.max_per_page == 4
        assert result.sources.get("max_per_page") == "environment"

    def test_cli_outranks_everything(self, tmp_path: Path) -> None:
        result = _resolve_config(
            tmp_path,
            cli_overrides={"max_per_page": 1},
            environ={"HALFBLOOD_MAX_PER_PAGE": "4"},
            project_toml="[generation]\nmax_per_page = 3\n",
        )
        assert result.max_per_page == 1
        assert result.sources.get("max_per_page") == "cli"

    @pytest.mark.parametrize("bad", ["nonsense", "3.5.1", "five"])
    def test_a_non_integer_is_rejected(self, tmp_path: Path, bad: str) -> None:
        with pytest.raises(ProviderConfigurationError):
            _resolve_config(tmp_path, environ={"HALFBLOOD_MAX_PER_PAGE": bad})

    def test_an_empty_environment_value_means_unset(self, tmp_path: Path) -> None:
        """Matches the persona precedent: an empty env var is absence, not an error.

        ``HALFBLOOD_MAX_PER_PAGE=`` is the ordinary shell idiom for "not set", and
        raising on it would make an exported-but-blank variable fail every run.
        """
        assert _resolve_config(tmp_path, environ={"HALFBLOOD_MAX_PER_PAGE": ""}).max_per_page == 5

    @pytest.mark.parametrize("bad", [0, -1])
    def test_a_non_positive_value_is_rejected(self, tmp_path: Path, bad: int) -> None:
        """Zero would silently annotate nothing, which is never what a user meant."""
        with pytest.raises(ProviderConfigurationError):
            _resolve_config(tmp_path, project_toml=f"[generation]\nmax_per_page = {bad}\n")

    def test_the_error_names_the_setting(self, tmp_path: Path) -> None:
        with pytest.raises(ProviderConfigurationError) as excinfo:
            _resolve_config(tmp_path, project_toml="[generation]\nmax_per_page = 0\n")
        assert "max_per_page" in str(excinfo.value)


# ---------------------------------------------------------------------------
# font
# ---------------------------------------------------------------------------


class TestFont:
    def test_defaults_to_none_when_unset(self, tmp_path: Path) -> None:
        assert _resolve_config(tmp_path).font is None

    def test_a_registered_name_passes_through_unchanged(self, tmp_path: Path) -> None:
        """`--font` accepts NAME|PATH; the key must accept a name, not only a path."""
        result = _resolve_config(tmp_path, project_toml='[generation]\nfont = "caveat-brush"\n')
        assert result.font == "caveat-brush"
        assert result.sources.get("font") == "project_config"

    def test_an_existing_relative_path_resolves_against_the_config_dir(
        self, tmp_path: Path
    ) -> None:
        """A project config must not depend on the directory the user runs from."""
        assets = tmp_path / "assets"
        assets.mkdir()
        font = assets / "hand.ttf"
        font.write_bytes(b"\x00\x01\x00\x00")

        result = _resolve_config(
            tmp_path, project_toml='[generation]\nfont = "assets/hand.ttf"\n'
        )
        assert Path(result.font).is_absolute()
        assert Path(result.font) == font.resolve()

    def test_an_absolute_path_is_left_alone(self, tmp_path: Path) -> None:
        font = tmp_path / "hand.ttf"
        font.write_bytes(b"\x00\x01\x00\x00")
        result = _resolve_config(
            tmp_path, project_toml=f'[generation]\nfont = "{font.as_posix()}"\n'
        )
        assert Path(result.font) == font

    def test_an_unresolvable_value_passes_through_for_the_cli_to_report(
        self, tmp_path: Path
    ) -> None:
        """config.py must not duplicate the name/path heuristic or invent its own error."""
        result = _resolve_config(tmp_path, project_toml='[generation]\nfont = "no-such-font"\n')
        assert result.font == "no-such-font"

    def test_environment_outranks_project(self, tmp_path: Path) -> None:
        result = _resolve_config(
            tmp_path,
            environ={"HALFBLOOD_FONT": "homemade-apple"},
            project_toml='[generation]\nfont = "caveat-brush"\n',
        )
        assert result.font == "homemade-apple"
        assert result.sources.get("font") == "environment"

    def test_cli_outranks_everything(self, tmp_path: Path) -> None:
        result = _resolve_config(
            tmp_path,
            cli_overrides={"font": "mrs-saint-delafield"},
            environ={"HALFBLOOD_FONT": "homemade-apple"},
            project_toml='[generation]\nfont = "caveat-brush"\n',
        )
        assert result.font == "mrs-saint-delafield"
        assert result.sources.get("font") == "cli"

    def test_project_outranks_user(self, tmp_path: Path) -> None:
        result = _resolve_config(
            tmp_path,
            project_toml='[generation]\nfont = "caveat-brush"\n',
            user_toml='[generation]\nfont = "homemade-apple"\n',
        )
        assert result.font == "caveat-brush"

    def test_a_non_string_is_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(ProviderConfigurationError):
            _resolve_config(tmp_path, project_toml="[generation]\nfont = 42\n")


# ---------------------------------------------------------------------------
# Nothing else moves
# ---------------------------------------------------------------------------


class TestExistingKeysAreUnaffected:
    def test_safe_repr_still_leaks_no_secrets(self, tmp_path: Path) -> None:
        result = _resolve_config(
            tmp_path,
            project_toml='[generation]\nmax_per_page = 3\nfont = "caveat-brush"\n',
        )
        assert "test-key" not in result.safe_repr()

    def test_the_new_keys_appear_in_diagnostics(self, tmp_path: Path) -> None:
        """`providers doctor` prints safe_repr; a setting it omits is undebuggable."""
        result = _resolve_config(
            tmp_path,
            project_toml='[generation]\nmax_per_page = 3\nfont = "caveat-brush"\n',
        )
        text = result.safe_repr()
        assert "max_per_page" in text
        assert "font" in text

    def test_unrelated_settings_still_resolve(self, tmp_path: Path) -> None:
        result = _resolve_config(
            tmp_path,
            project_toml=(
                "[generation]\n"
                "max_per_page = 3\n"
                'font = "caveat-brush"\n'
                "concurrency = 2\n"
                'persona = "A clinical historian."\n'
            ),
        )
        assert result.concurrency == 2
        assert result.persona == "A clinical historian."
        assert result.max_per_page == 3
        assert result.font == "caveat-brush"


# ---------------------------------------------------------------------------
# CLI wiring — a config key nothing reads is not a feature
# ---------------------------------------------------------------------------

_PDF_BYTES = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n"


class _FakeProcessor:
    """Minimal processor double; records the font path it was constructed with."""

    last_font_path: str | None = None

    def __init__(self, *args: object, **kwargs: object) -> None:
        type(self).last_font_path = kwargs.get("font_path")  # type: ignore[assignment]

    def load(self, path: str) -> list[PageContent]:
        return [PageContent(page_number=1, text="Bezoar. Remember that.", width=612.0, height=792.0)]

    def render_plan(self, input_path: str, plan: object, output_path: str) -> object:
        from halfblood.models.rendering import RenderReport

        Path(output_path).write_text("rendered", encoding="utf-8")
        return RenderReport(rendered=("ann-1",))

    def annotations_from_plan(self, plan: AnnotationPlan) -> list:
        return [a for page in plan.pages for a in page.annotations]


class _CapturingGenerator:
    """Records the max_annotations_per_page it is asked for."""

    last_max: int | None = None

    def __init__(self, **kwargs: object) -> None:
        self.failed_pages: list[int] = []

    def generate_for_document(
        self, pages: list, max_annotations_per_page: int = 5, **kwargs: object
    ) -> AnnotationPlan:
        type(self).last_max = max_annotations_per_page
        return AnnotationPlan(title="t", prince_persona="p", pages=[])


@pytest.fixture
def wired(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli_module, "build_provider", lambda *a, **k: object())
    monkeypatch.setattr(cli_module, "AnnotationGenerator", _CapturingGenerator)
    monkeypatch.setattr(cli_module, "DocumentProcessor", _FakeProcessor)
    monkeypatch.setattr(cli_module, "EpubProcessor", _FakeProcessor)
    _CapturingGenerator.last_max = None
    _FakeProcessor.last_font_path = None


def _run(tmp_path: Path, config_body: str, *extra: str) -> object:
    src = tmp_path / "book.pdf"
    src.write_bytes(_PDF_BYTES)
    cfg = tmp_path / "hb.toml"
    cfg.write_text(config_body, encoding="utf-8")
    return CliRunner().invoke(
        cli_module.main,
        [
            "annotate", str(src), "-o", str(tmp_path / "out.pdf"),
            "--config", str(cfg), "--provider", "anthropic", "--model", "m",
            *extra,
        ],
        env={"ANTHROPIC_API_KEY": "test-key"},
    )


class TestCliHonoursTheConfigKeys:
    def test_max_per_page_comes_from_config_when_the_flag_is_absent(
        self, tmp_path: Path, wired: None
    ) -> None:
        result = _run(tmp_path, "[generation]\nmax_per_page = 2\n")
        assert result.exit_code == 0, result.output
        assert _CapturingGenerator.last_max == 2

    def test_an_explicit_flag_still_beats_config(self, tmp_path: Path, wired: None) -> None:
        result = _run(tmp_path, "[generation]\nmax_per_page = 2\n", "--max-per-page", "1")
        assert result.exit_code == 0, result.output
        assert _CapturingGenerator.last_max == 1

    def test_the_default_is_unchanged_with_neither_flag_nor_config(
        self, tmp_path: Path, wired: None
    ) -> None:
        result = _run(tmp_path, "[generation]\n")
        assert result.exit_code == 0, result.output
        assert _CapturingGenerator.last_max == 5

    def test_font_comes_from_config_when_the_flag_is_absent(
        self, tmp_path: Path, wired: None
    ) -> None:
        result = _run(tmp_path, '[generation]\nfont = "caveat-brush"\n')
        assert result.exit_code == 0, result.output
        assert _FakeProcessor.last_font_path is not None
        assert "CaveatBrush" in str(_FakeProcessor.last_font_path)

    def test_an_unknown_font_in_config_reports_the_registered_names(
        self, tmp_path: Path, wired: None
    ) -> None:
        """The config path must reuse the flag's error, not fail obscurely."""
        result = _run(tmp_path, '[generation]\nfont = "no-such-font"\n')
        assert result.exit_code != 0
        assert "no-such-font" in result.output
        assert "caveat-brush" in result.output
