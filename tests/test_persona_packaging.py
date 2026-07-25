"""The persona library must survive `pip install` — it currently does not.

`pyproject.toml` ships only `src/halfblood`, so the `personas/*.txt` files added in
`97f345e` live at the repo root and are absent from the wheel. `--persona-file
personas/chemist.txt` works from a git checkout and silently does not exist for anyone
who installed the tool. Shipping a library that only resolves in the development tree is
half a feature.

This mirrors the solution already proven for fonts (P3-T11,
`tests/test_font_packaging.py`): the assets live *inside* the package and resolve through
`importlib.resources`, with a registry-name flag and a directory argument that tests can
inject so nothing reaches the developer's real machine.

Design constraints pinned here:

1. **The packaged copy is the single source of truth.** Fonts deliberately keep a second
   copy at the repo root because `fonts/README.md` documents it as a download target under
   licence constraints. Personas have no such reason, so duplicating them would just create
   two files that drift.
2. **Resolution must not require a repo checkout.** Asserted by resolving with an injected
   empty directory standing in for an installed wheel — the same installed-wheel simulation
   `test_default_font_resolves_from_package_not_helvetica` uses.
3. **The directory is injectable.** `_resolve_persona_name(name, personas_dir=None)` mirrors
   `_resolve_font_option(value, fonts_dir=None)`. Without this a test reaches whatever the
   real machine happens to hold, passes here, and fails everywhere else.
4. **An unknown name lists the real options.** A persona registry whose error message does
   not name the available personas is undiscoverable, which is the whole problem this
   change exists to solve.
5. **The three persona flags are mutually exclusive**, and the existing precedence
   (`--persona` > `--persona-file` > config) is extended, not reordered.
"""

from __future__ import annotations

import importlib.resources as resources
from pathlib import Path

import click
import pytest
from click.testing import CliRunner

from halfblood import cli as cli_module
from halfblood.annotation_generator import AnnotationGenerator
from halfblood.generation.providers.base import (
    GenerationRequest,
    GenerationResult,
    ProviderCapabilities,
)

EXPECTED_PERSONAS = ("chemist", "detective", "editor", "philosopher")

ANNOTATION_TYPES = (
    "CORRECTIONS",
    "IMPROVEMENTS",
    "INSIGHTS",
    "INVENTIONS",
    "WARNINGS",
    "SHORTCUTS",
    "CROSSED_OUT",
    "DOODLE_NOTE",
)


def _pkg_personas_dir() -> Path:
    """The personas directory that ships inside the installed `halfblood` package."""
    return Path(str(resources.files("halfblood").joinpath("personas")))


class _UnusedProvider:
    @property
    def capabilities(self) -> ProviderCapabilities:  # pragma: no cover
        raise AssertionError("no capability lookup expected")

    def complete(self, request: GenerationRequest) -> GenerationResult:  # pragma: no cover
        raise AssertionError("no provider call expected")


# --- packaging: personas live inside the installed package ----------------------------


def test_bundled_personas_dir_exists() -> None:
    assert _pkg_personas_dir().is_dir(), (
        f"expected packaged personas at {_pkg_personas_dir()} so the wheel ships them"
    )


@pytest.mark.parametrize("name", EXPECTED_PERSONAS)
def test_every_persona_is_packaged(name: str) -> None:
    assert (_pkg_personas_dir() / f"{name}.txt").is_file(), (
        f"persona not packaged inside halfblood: {name}"
    )


@pytest.mark.parametrize("name", EXPECTED_PERSONAS)
def test_each_packaged_persona_is_substantive(name: str) -> None:
    text = (_pkg_personas_dir() / f"{name}.txt").read_text(encoding="utf-8")
    assert text.strip(), f"{name} is blank"
    assert len(text) > 300, f"{name} is too thin to shape a voice"
    assert "VOICE AND TEMPERAMENT" in text
    assert "WHAT YOUR ANNOTATIONS DO" not in text, (
        f"{name} restates the shared craft block and will go stale"
    )


def test_the_library_is_not_duplicated_at_the_repo_root() -> None:
    """A second copy would drift from the packaged one. README may stay."""
    stray = sorted((Path(__file__).resolve().parents[1] / "personas").glob("*.txt"))
    assert not stray, (
        f"personas duplicated outside the package: {[p.name for p in stray]}"
    )


def test_packaged_personas_are_documented() -> None:
    readme = (_pkg_personas_dir() / "README.md").read_text(encoding="utf-8")
    for name in EXPECTED_PERSONAS:
        assert f"{name}.txt" in readme, f"{name}.txt is missing from personas/README.md"


# --- resolution: works with no repo checkout ------------------------------------------


@pytest.mark.parametrize("name", EXPECTED_PERSONAS)
def test_persona_name_resolves_from_the_package(name: str) -> None:
    text = cli_module._resolve_persona_name(name)
    assert text.strip()
    assert "VOICE AND TEMPERAMENT" in text


@pytest.mark.parametrize("name", EXPECTED_PERSONAS)
def test_persona_name_resolves_in_an_installed_wheel_simulation(
    name: str, tmp_path: Path
) -> None:
    """With an empty injected directory — as in a wheel with no repo `personas/` — the
    name must still resolve, proving the package resource is what answers."""
    text = cli_module._resolve_persona_name(name, personas_dir=tmp_path)
    assert text.strip()
    assert "VOICE AND TEMPERAMENT" in text


def test_available_personas_lists_every_packaged_persona() -> None:
    assert set(EXPECTED_PERSONAS) <= set(cli_module.available_personas())


def test_unknown_persona_name_is_a_click_exception_listing_the_options() -> None:
    with pytest.raises(click.ClickException) as excinfo:
        cli_module._resolve_persona_name("nosuchpersona")
    message = str(excinfo.value)
    assert "nosuchpersona" in message
    for name in EXPECTED_PERSONAS:
        assert name in message, "the error must name the available personas"


def test_a_resolved_persona_produces_a_complete_system_prompt() -> None:
    """End-to-end guard: a named persona must carry the shared craft block."""
    persona = cli_module._resolve_persona_name("detective")
    prompt = AnnotationGenerator(
        provider=_UnusedProvider(), persona=persona
    )._build_system_prompt()
    assert all(kind in prompt for kind in ANNOTATION_TYPES)
    assert "Half-Blood Prince" not in prompt, "the named persona did not replace the default"


# --- flag interaction: precedence extended, not reordered -----------------------------


def test_persona_name_is_used_when_it_is_the_only_flag() -> None:
    resolved = cli_module._resolve_persona(None, None, "chemist", None)
    assert resolved is not None
    assert "chemist" in resolved.lower() or "VOICE AND TEMPERAMENT" in resolved


def test_persona_flag_outranks_config() -> None:
    assert (
        cli_module._resolve_persona("inline voice", None, None, "config voice")
        == "inline voice"
    )


def test_persona_file_outranks_config(tmp_path: Path) -> None:
    path = tmp_path / "p.txt"
    path.write_text("file voice", encoding="utf-8")
    assert cli_module._resolve_persona(None, path, None, "config voice") == "file voice"


def test_persona_name_outranks_config() -> None:
    resolved = cli_module._resolve_persona(None, None, "chemist", "config voice")
    assert resolved != "config voice"
    assert "VOICE AND TEMPERAMENT" in (resolved or "")


def test_config_is_still_used_when_no_flag_is_given() -> None:
    assert cli_module._resolve_persona(None, None, None, "config voice") == "config voice"


def test_no_persona_anywhere_still_resolves_to_none() -> None:
    assert cli_module._resolve_persona(None, None, None, None) is None


def test_persona_and_persona_name_together_is_a_usage_error() -> None:
    with pytest.raises(click.UsageError):
        cli_module._resolve_persona("inline voice", None, "chemist", None)


def test_persona_file_and_persona_name_together_is_a_usage_error(tmp_path: Path) -> None:
    path = tmp_path / "p.txt"
    path.write_text("a voice", encoding="utf-8")
    with pytest.raises(click.UsageError):
        cli_module._resolve_persona(None, path, "chemist", None)


def test_all_three_persona_flags_together_is_a_usage_error(tmp_path: Path) -> None:
    path = tmp_path / "p.txt"
    path.write_text("a voice", encoding="utf-8")
    with pytest.raises(click.UsageError):
        cli_module._resolve_persona("inline voice", path, "chemist", None)


def test_the_exclusion_error_names_all_three_flags() -> None:
    """The message must say which flags conflict, not just that something did."""
    with pytest.raises(click.UsageError) as excinfo:
        cli_module._resolve_persona("inline voice", None, "chemist", None)
    message = str(excinfo.value)
    for flag in ("--persona", "--persona-file", "--persona-name"):
        assert flag in message


# --- discoverability ------------------------------------------------------------------


@pytest.mark.parametrize("command", ["annotate", "preview"])
def test_persona_name_flag_appears_in_help(command: str) -> None:
    result = CliRunner().invoke(cli_module.main, [command, "--help"])
    assert result.exit_code == 0, result.output
    assert "--persona-name" in result.output
    assert "chemist" in result.output, "help must name at least one bundled persona"
