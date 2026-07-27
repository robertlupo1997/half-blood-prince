"""P0-T11 — public docs must describe the code that actually ships.

Covers AUD-11 (web-preview absent from README), AUD-12/AUD-13 (README
contributing section and ARCHITECTURE extension-points both describe EPUB as
future work although EpubProcessor ships), AUD-27 (README usage shows
INPUT_PDF; the argument is INPUT_FILE taking .pdf or .epub), AUD-28 (intro is
PDF-only), AUD-29/AUD-30 (module list and CLI command list omit
epub_processor.py / web_preview.py / web-preview), AUD-33 (CLAUDE.md claims
retries are absent; the SDK already retries — Phase 1's provider transport is
the sole retry owner), AUD-44 (font docs name only the exact
CaveatBrush-Regular.ttf filename; the resolver accepts any *aveat* variant),
plus the retired model string still shown as the README default.

These are deliberate string contracts: cheap, exact, and they fail loudly the
next time the docs drift from the CLI/modules they describe.

No network calls are made anywhere in this file.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from click.testing import CliRunner

from halfblood.annotation_generator import DEFAULT_MODEL
from halfblood.cli import main as cli_main

_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def readme() -> str:
    return (_ROOT / "README.md").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def arch() -> str:
    return (_ROOT / "docs" / "ARCHITECTURE.md").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def claude_md() -> str:
    return (_ROOT / "CLAUDE.md").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# README
# ---------------------------------------------------------------------------


def test_readme_usage_names_input_file_not_input_pdf(readme: str) -> None:
    assert "INPUT_FILE" in readme  # AUD-27
    assert "INPUT_PDF" not in readme


def test_readme_shows_epub_as_shipping_not_future(readme: str) -> None:
    assert ".epub" in readme, "no EPUB usage example"  # AUD-28
    assert "Adding a new document format (e.g. EPUB)" not in readme  # AUD-12


def test_readme_documents_web_preview_with_runnable_example(readme: str) -> None:
    assert re.search(r"halfblood web-preview\s+\S", readme), (  # AUD-11
        "README needs a runnable `halfblood web-preview <plan.json>` example"
    )


def test_readme_shows_the_current_model_default(readme: str) -> None:
    assert "claude-sonnet-4-20250514" not in readme, "retired model still shown"
    assert DEFAULT_MODEL in readme, f"README should show the real default {DEFAULT_MODEL!r}"


def test_readme_mentions_font_glob_not_just_exact_filename(readme: str) -> None:
    assert "*aveat*" in readme  # AUD-44


def test_readme_documents_overwrite_and_parent_creation(readme: str) -> None:
    assert "--force" in readme  # guard, added in P0-T7
    assert re.search(r"parent director", readme, re.IGNORECASE), (
        "README should say missing output parent directories are created"
    )


# ---------------------------------------------------------------------------
# docs/ARCHITECTURE.md
# ---------------------------------------------------------------------------


def test_architecture_lists_the_shipping_modules(arch: str) -> None:
    assert "epub_processor.py" in arch  # AUD-29
    assert "web_preview.py" in arch


def test_architecture_lists_all_four_cli_commands(arch: str) -> None:
    assert "web-preview" in arch  # AUD-30
    for command in ("annotate", "preview", "eval"):
        assert command in arch


def test_architecture_extension_section_reflects_implemented_epub(arch: str) -> None:
    # AUD-13: the extension-points section recommended building EPUB support
    # "option (a) convert to PDF" although the codebase ships option (b),
    # EpubProcessor. The recommendation must be gone and the real class named.
    assert "Option (a) is the much smaller lift" not in arch
    assert "EpubProcessor" in arch


# ---------------------------------------------------------------------------
# CLAUDE.md
# ---------------------------------------------------------------------------


def test_claude_md_states_the_true_retry_story(claude_md: str) -> None:
    # AUD-33: the SDK already retries 429/408/409/5xx; the stale "pipeline
    # crashes" claim prescribes duplicate work. Phase 1's provider transport
    # is the sole retry owner going forward.
    assert "If Claude returns 429 or 500, the pipeline crashes" not in claude_md
    assert re.search(r"sole retry owner", claude_md, re.IGNORECASE)


# ---------------------------------------------------------------------------
# The documented commands actually exist
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("command", ["annotate", "preview", "web-preview", "eval"])
def test_documented_cli_commands_exist(command: str) -> None:
    result = CliRunner().invoke(cli_main, [command, "--help"])
    assert result.exit_code == 0


# ---------------------------------------------------------------------------
# README claims that were FALSE at HEAD until 2026-07-27.
#
# The tests above assert that keywords are PRESENT, which is why the README
# drifted for so long: it kept describing Claude-only generation, native PDF
# annotation marks, an unbundled font, `models.py`, and `render_annotations()`
# long after every one of those stopped being true, and the suite stayed green
# throughout. These assert the ABSENCE of specific refuted claims, which is the
# direction that actually catches drift.
# ---------------------------------------------------------------------------


def test_readme_does_not_claim_the_font_is_unbundled(readme: str) -> None:
    """Four fonts ship inside the package (`git ls-files src/halfblood/fonts/`)."""
    assert "isn't bundled" not in readme
    assert "is not bundled" not in readme


def test_readme_does_not_claim_native_pdf_annotation_marks(readme: str) -> None:
    """The shipped render_plan path emits vector ink, not native annotations.

    Measured on a real render: 230 vector drawings, 0 native annotation objects.
    `_mark_target`'s add_*_annot calls belong to the legacy render_annotations
    path, which the CLI no longer reaches.
    """
    assert "marked with a native PDF annotation" not in readme


def test_readme_does_not_describe_models_as_a_single_module(readme: str) -> None:
    """`src/halfblood/models/` is a package, not `models.py`."""
    assert "**`models.py`**" not in readme


def test_readme_pipeline_diagram_names_the_live_render_entry_point(readme: str) -> None:
    """The CLI calls render_plan; render_annotations is the legacy v1 path."""
    assert "render_plan()" in readme


def test_readme_does_not_present_the_tool_as_claude_only(readme: str) -> None:
    """Five providers are registered: anthropic, openai, openrouter, ollama, lmstudio."""
    assert "hands it to Claude" not in readme
    for provider in ("openai", "openrouter", "ollama", "lmstudio"):
        assert provider in readme, f"README never mentions the {provider} provider"


def test_readme_does_not_claim_the_judge_is_anthropic_only(readme: str) -> None:
    """The eval judge moved onto the shared provider seam."""
    assert "transport still supports only Anthropic" not in readme
