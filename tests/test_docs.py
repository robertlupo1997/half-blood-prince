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
# CLAUDE.md truth pass (2026-07-27): the same absence-of-refuted-claim pattern
# used for README above, applied to the five stale CLAUDE.md claims catalogued
# in HBP-STATE-OX.md ("All 44 tests", no concurrency, collision detection open,
# Anthropic SDK, native annots). Each asserts a refuted claim stays absent.
# ---------------------------------------------------------------------------


def test_claude_md_does_not_pin_a_stale_test_count(claude_md: str) -> None:
    """Test counts rot on contact (44 → 1,861); the doc now points at the run."""
    assert "All 44 tests should pass" not in claude_md


def test_claude_md_does_not_claim_pages_run_sequentially(claude_md: str) -> None:
    """Waves via ThreadPoolExecutor shipped (`concurrency` default 3, config.py)."""
    assert "No async/concurrent page processing" not in claude_md
    assert "Pages are processed sequentially" not in claude_md
    assert "concurrent waves" in claude_md


def test_claude_md_does_not_list_collision_detection_as_open(claude_md: str) -> None:
    """Solver conflict detection is built (layout/page_solver.py _candidate_conflicts)."""
    assert "Annotation overlap/collision detection." not in claude_md
    assert "collision avoidance" not in claude_md.split("**BUILT**")[-1]


def test_claude_md_does_not_prescribe_an_anthropic_sdk(claude_md: str) -> None:
    """No vendor SDK exists; the httpx seam replaced the tech-stack table row."""
    assert "**Anthropic SDK**" not in claude_md
    assert "anthropic.AsyncAnthropic" not in claude_md


def test_claude_md_diagram_names_the_live_render_entry_point(claude_md: str) -> None:
    """The CLI runs render_plan (vector drawings); native annots are legacy-only."""
    assert "render_plan()" in claude_md
    assert "_mark_target() adds native PDF annotations" not in claude_md


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


def test_every_font_key_the_readme_advertises_actually_resolves(readme: str) -> None:
    """Documented commands must work.

    The README briefly recommended `--font "Caveat Brush"` -- the display name,
    not the registry key -- which the CLI rejects with "Unknown font". A doc
    test that only checks strings are present cannot catch a documented command
    being wrong, so this one executes what the README tells the user to run.
    """
    import re

    from halfblood.cli import _resolve_font_option

    keys = set(re.findall(r"`--font ([a-z][a-z0-9-]+)`", readme))
    assert keys, "README should document at least one --font registry key"
    for key in keys:
        resolved = _resolve_font_option(key)
        assert resolved, f"README advertises --font {key}, which does not resolve"


def test_readme_example_artifacts_exist() -> None:
    """Every example artifact the README's examples table cites must exist.

    Falsifiability guard: the README presents `examples/` as real committed
    output produced by this tree. If an artifact is removed or renamed without
    updating the README, this fails — and if the README stops citing them,
    that is a doc regression too.
    """
    readme = (_ROOT / "README.md").read_text(encoding="utf-8")
    cited = [
        "examples/hbp-example.pdf",
        "examples/hbp-example.pdf.report.json",
        "examples/hbp-example.epub",
        "examples/hbp-example.epub.report.json",
        "examples/screenshot.png",
        "scripts/build_example_book.py",
    ]
    for rel in cited:
        assert rel in readme, f"README no longer cites {rel}"
        assert (_ROOT / rel).is_file(), f"README cites {rel} but it does not exist"
    assert "--provider stub" in readme
    assert "--resume-from" in readme


def test_committed_example_sidecars_report_full_success() -> None:
    """The committed sidecars must match what the README claims about them.

    The README table asserts 78/78 annotated pages with no failures on the PDF
    and a skipped cover page on the EPUB. If the pipeline changes and the
    artifacts are regenerated differently, this test forces the README table
    to be updated in the same commit.
    """
    import json

    pdf_report = json.loads(
        (_ROOT / "examples" / "hbp-example.pdf.report.json").read_text(encoding="utf-8")
    )
    assert pdf_report["pages_total"] == 78
    assert pdf_report["pages_annotated"] == 78
    assert pdf_report["failed_pages"] == []

    epub_report = json.loads(
        (_ROOT / "examples" / "hbp-example.epub.report.json").read_text(encoding="utf-8")
    )
    assert epub_report["pages_total"] == 13
    assert epub_report["pages_annotated"] == 12
    assert epub_report["skipped_pages"] == [1]
    assert epub_report["failed_pages"] == []


def test_readme_does_not_reference_models_py_as_a_file_path(readme: str) -> None:
    """`models` is a package; the type lives in models/annotations.py.

    An earlier fix only forbade the bold spelling ``**`models.py`**``, so a
    second plain-text reference survived in the extension instructions.
    """
    import re

    stray = [
        line.strip()
        for line in readme.splitlines()
        if re.search(r"`models\.py`", line) and "not a single" not in line
    ]
    assert not stray, f"stale models.py reference(s): {stray}"
