"""Lane-B CLI hardening tests — five defects proven red at base, green after fix.

DEFECT 1 — same-file output destroys the source:
    ``annotate -o INPUT --force`` must refuse even with --force.

DEFECT 2 — malformed ``--pages`` emits a raw Python traceback:
    Non-integer or incomplete tokens must produce a clean BadParameter message,
    not a ValueError traceback.

DEFECT 3 — out-of-range ``--pages`` exits 0 with no output:
    ``annotate --pages 999`` on a 5-page book must exit 1, matching preview's
    existing behaviour.

DEFECT 4 — ``halfblood eval`` is broken in every pip-installed wheel:
    The command must detect that it is not running from a source checkout and
    fail with an actionable message — not "Eval harness not found at
    /usr/lib/python3.12/eval/eval_harness.py".

DEFECT 5 — dead ``hasattr`` branch hides which render path is live:
    Both real processors define ``render_plan``; the ``else`` / render_annotations
    fallback was unreachable in production and has been removed.  The evidence is
    behavioural (all annotate tests pass without it) rather than a contrived red.

No real API calls are made anywhere in this file.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner

import halfblood.cli as cli_module
from halfblood.cli import main as cli_main
from halfblood.config import ResolvedConfig
from halfblood.document_processor import PageContent
from halfblood.models import AnnotatedPage, AnnotationPlan
from halfblood.models.rendering import RenderReport

# ---------------------------------------------------------------------------
# Shared byte literals
# ---------------------------------------------------------------------------

_PDF_BYTES = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n%%EOF\n"
_ZIP_BYTES = b"PK\x03\x04" + b"\x00" * 32

# ---------------------------------------------------------------------------
# Shared fake infrastructure (mirrors test_cli.py conventions)
# ---------------------------------------------------------------------------

_FAKE_CLI_SOURCES: dict[str, str] = {
    "provider": "default",
    "model": "cli",
    "base_url": "preset",
    "api_key_env": "preset",
    "structured_output": "preset",
    "timeout_seconds": "default",
    "max_retries": "default",
    "concurrency": "default",
    "allow_insecure_http": "default",
}

_FAKE_CLI_CONFIG = ResolvedConfig(
    provider="anthropic",
    model="claude-sonnet-5",
    base_url="https://api.anthropic.com",
    api_key_env="ANTHROPIC_API_KEY",
    structured_output="tool",
    timeout_seconds=60.0,
    max_retries=0,
    concurrency=3,
    allow_insecure_http=False,
    sources=_FAKE_CLI_SOURCES,
)


class _FakeCliProvider:
    @property
    def capabilities(self):
        from halfblood.generation.providers.base import ProviderCapabilities

        return ProviderCapabilities(
            supports_tool_calling=True,
            supports_json_schema=False,
            supports_strict_json_schema=False,
        )

    def complete(self, request):
        raise AssertionError("provider.complete() must not be called in these tests")


class _FakePdfProcessor:
    """PDF processor double with render_plan (matching the live interface)."""

    load_calls: list[str] = []
    render_calls: list[str] = []

    def load(self, path: str) -> list[PageContent]:
        type(self).load_calls.append(path)
        return [PageContent(page_number=1, text="some page text", width=612.0, height=792.0)]

    def render_plan(self, input_path: str, plan: object, output_path: str) -> RenderReport:
        type(self).render_calls.append(output_path)
        Path(output_path).write_bytes(_PDF_BYTES)
        return RenderReport(rendered=("ann-1",))

    def annotations_from_plan(self, plan: AnnotationPlan) -> list:
        return [a for page in plan.pages for a in page.annotations]


class _FakeEpubProcessor:
    """EPUB processor double with render_plan."""

    load_calls: list[str] = []
    render_calls: list[str] = []

    def load(self, path: str) -> list[PageContent]:
        type(self).load_calls.append(path)
        return [PageContent(page_number=1, text="chapter text", width=600.0, height=800.0)]

    def render_plan(self, input_path: str, plan: object, output_path: str) -> RenderReport:
        type(self).render_calls.append(output_path)
        Path(output_path).write_bytes(_ZIP_BYTES)
        return RenderReport(rendered=("ann-1",))


class _FakeGenerator:
    calls: int = 0

    def __init__(
        self,
        persona: str | None = None,
        model: str | None = None,
        provider: object | None = None,
        concurrency: int = 3,
    ) -> None:
        self.failed_pages: list[int] = []

    def generate_for_document(
        self,
        pages: list[PageContent],
        max_annotations_per_page: int = 5,
        **kwargs: Any,
    ) -> AnnotationPlan:
        type(self).calls += 1
        return AnnotationPlan(
            title="fake plan",
            prince_persona="p",
            pages=[
                AnnotatedPage(page_number=p.page_number, original_text=p.text, annotations=[])
                for p in pages
            ],
        )


@pytest.fixture()
def fakes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Wire all CLI seam points with hermetic fakes."""
    _FakePdfProcessor.load_calls = []
    _FakePdfProcessor.render_calls = []
    _FakeEpubProcessor.load_calls = []
    _FakeEpubProcessor.render_calls = []
    _FakeGenerator.calls = 0
    monkeypatch.setattr(cli_module, "DocumentProcessor", _FakePdfProcessor)
    monkeypatch.setattr(cli_module, "EpubProcessor", _FakeEpubProcessor)
    monkeypatch.setattr(cli_module, "AnnotationGenerator", _FakeGenerator)
    monkeypatch.setattr(cli_module, "resolve_generation_config", lambda *a, **k: _FAKE_CLI_CONFIG)
    monkeypatch.setattr(cli_module, "build_provider", lambda *a, **k: _FakeCliProvider())


@pytest.fixture()
def runner() -> CliRunner:
    return CliRunner()


def _no_traceback(result: Any) -> bool:
    return result.exception is None or isinstance(result.exception, SystemExit)


# ===========================================================================
# DEFECT 1 — same-file output destroys the source
# ===========================================================================


def test_annotate_refuses_when_output_is_same_file_as_input(
    runner: CliRunner, fakes: None, tmp_path: Path
) -> None:
    """Refuses when -o and input point at the same file; source bytes unchanged."""
    src = tmp_path / "book.pdf"
    src.write_bytes(_PDF_BYTES)
    original_bytes = src.read_bytes()

    result = runner.invoke(cli_main, ["annotate", str(src), "-o", str(src)])
    assert result.exit_code == 1, result.output
    assert _no_traceback(result), f"raw exception leaked: {result.exception!r}"
    # Source must not be touched
    assert src.read_bytes() == original_bytes, "source bytes were modified"
    assert _FakeGenerator.calls == 0, "generator must not run when source would be overwritten"
    assert _FakePdfProcessor.render_calls == []


def test_annotate_refuses_same_file_even_with_force(
    runner: CliRunner, fakes: None, tmp_path: Path
) -> None:
    """--force does NOT override the same-file refusal — it means 'overwrite a different file'."""
    src = tmp_path / "book.pdf"
    src.write_bytes(_PDF_BYTES)
    original_bytes = src.read_bytes()

    result = runner.invoke(cli_main, ["annotate", str(src), "-o", str(src), "--force"])
    assert result.exit_code == 1, result.output
    assert _no_traceback(result), f"raw exception leaked: {result.exception!r}"
    assert src.read_bytes() == original_bytes, "source bytes were modified despite --force"
    assert _FakeGenerator.calls == 0


def test_annotate_refuses_same_file_path_variation(
    runner: CliRunner, fakes: None, tmp_path: Path
) -> None:
    """./book.pdf and book.pdf are the same file and must both be caught."""
    src = tmp_path / "book.pdf"
    src.write_bytes(_PDF_BYTES)
    original_bytes = src.read_bytes()

    # Construct a path string that contains ./ so the two path strings differ.
    # pathlib collapses components at construction, so we must use a raw string.
    dotslash_path = f"{tmp_path}/./book.pdf"

    result = runner.invoke(cli_main, ["annotate", str(src), "-o", dotslash_path, "--force"])
    assert result.exit_code == 1, result.output
    assert _no_traceback(result), f"raw exception leaked: {result.exception!r}"
    assert src.read_bytes() == original_bytes
    assert _FakeGenerator.calls == 0


def test_annotate_same_file_refusal_epub(
    runner: CliRunner, fakes: None, tmp_path: Path
) -> None:
    """EPUB case: the render-zero-annotations-but-overwrite-anyway scenario from the bug report."""
    src = tmp_path / "book.epub"
    src.write_bytes(_ZIP_BYTES)
    original_bytes = src.read_bytes()

    result = runner.invoke(cli_main, ["annotate", str(src), "-o", str(src), "--force"])
    assert result.exit_code == 1, result.output
    assert _no_traceback(result), f"raw exception leaked: {result.exception!r}"
    assert src.read_bytes() == original_bytes
    assert _FakeEpubProcessor.render_calls == []


def test_annotate_force_still_works_for_different_output_file(
    runner: CliRunner, fakes: None, tmp_path: Path
) -> None:
    """--force must still work for overwriting a *different* existing output file."""
    src = tmp_path / "book.pdf"
    src.write_bytes(_PDF_BYTES)
    out = tmp_path / "out.pdf"
    out.write_bytes(b"old bytes")

    result = runner.invoke(cli_main, ["annotate", str(src), "-o", str(out), "--force"])
    assert result.exit_code == 0, result.output
    assert _FakeGenerator.calls == 1


def test_same_file_error_message_is_actionable(
    runner: CliRunner, fakes: None, tmp_path: Path
) -> None:
    """The error message must explain the problem without mentioning a confusing path."""
    src = tmp_path / "my_book.pdf"
    src.write_bytes(_PDF_BYTES)

    result = runner.invoke(cli_main, ["annotate", str(src), "-o", str(src), "--force"])
    assert result.exit_code == 1
    # Must mention the input file so users understand what happened
    output = result.output
    assert "same file" in output.lower() or "input" in output.lower(), (
        f"error message is not actionable:\n{output}"
    )


# ===========================================================================
# DEFECT 2 — malformed --pages emits raw ValueError traceback
# ===========================================================================


def test_pages_non_integer_token_exits_2(
    runner: CliRunner, fakes: None, tmp_path: Path
) -> None:
    """'foo' in --pages must produce a clean BadParameter error, not a traceback."""
    src = tmp_path / "book.pdf"
    src.write_bytes(_PDF_BYTES)

    result = runner.invoke(cli_main, ["annotate", str(src), "-o", str(tmp_path / "out.pdf"),
                                      "--pages", "foo"])
    assert result.exit_code == 2, (
        f"expected exit 2 (UsageError), got {result.exit_code}.\n{result.output}"
    )
    assert _no_traceback(result), f"raw exception leaked: {result.exception!r}"
    # Must not mention Python internals
    assert "ValueError" not in result.output
    assert "Traceback" not in result.output


def test_pages_trailing_dash_exits_2(
    runner: CliRunner, fakes: None, tmp_path: Path
) -> None:
    """'3-' (missing end of range) must exit 2 with a clean message."""
    src = tmp_path / "book.pdf"
    src.write_bytes(_PDF_BYTES)

    result = runner.invoke(cli_main, ["annotate", str(src), "-o", str(tmp_path / "out.pdf"),
                                      "--pages", "3-"])
    assert result.exit_code == 2, (
        f"expected exit 2 (UsageError), got {result.exit_code}.\n{result.output}"
    )
    assert _no_traceback(result), f"raw exception leaked: {result.exception!r}"
    assert "ValueError" not in result.output


def test_pages_leading_dash_exits_2(
    runner: CliRunner, fakes: None, tmp_path: Path
) -> None:
    """'-3' (missing start of range) must exit 2 with a clean message."""
    src = tmp_path / "book.pdf"
    src.write_bytes(_PDF_BYTES)

    result = runner.invoke(cli_main, ["annotate", str(src), "-o", str(tmp_path / "out.pdf"),
                                      "--pages", "-3"])
    assert result.exit_code == 2, (
        f"expected exit 2 (UsageError), got {result.exit_code}.\n{result.output}"
    )
    assert _no_traceback(result), f"raw exception leaked: {result.exception!r}"
    assert "ValueError" not in result.output


def test_pages_message_names_pages_option(
    runner: CliRunner, fakes: None, tmp_path: Path
) -> None:
    """The BadParameter message must mention --pages so users know which option to fix."""
    src = tmp_path / "book.pdf"
    src.write_bytes(_PDF_BYTES)

    result = runner.invoke(cli_main, ["annotate", str(src), "-o", str(tmp_path / "out.pdf"),
                                      "--pages", "abc"])
    assert result.exit_code == 2
    # Click formats BadParameter as: "Error: Invalid value for '--pages': ..."
    assert "--pages" in result.output or "pages" in result.output.lower()


def test_pages_valid_range_still_works(
    runner: CliRunner, fakes: None, tmp_path: Path
) -> None:
    """Sanity: '1' on a 1-page book must still succeed after input validation is added."""
    src = tmp_path / "book.pdf"
    src.write_bytes(_PDF_BYTES)

    result = runner.invoke(cli_main, ["annotate", str(src), "-o", str(tmp_path / "out.pdf"),
                                      "--pages", "1"])
    assert result.exit_code == 0, result.output


# ===========================================================================
# DEFECT 3 — out-of-range --pages exits 0 and does nothing
# ===========================================================================


def test_annotate_out_of_range_pages_exits_1(
    runner: CliRunner, fakes: None, tmp_path: Path
) -> None:
    """annotate --pages 999 on a 1-page book exits 1, no output file written."""
    src = tmp_path / "book.pdf"
    src.write_bytes(_PDF_BYTES)
    out = tmp_path / "out.pdf"

    result = runner.invoke(cli_main, ["annotate", str(src), "-o", str(out), "--pages", "999"])
    assert result.exit_code == 1, (
        f"expected exit 1 for out-of-range pages, got {result.exit_code}.\n{result.output}"
    )
    assert _no_traceback(result), f"raw exception leaked: {result.exception!r}"
    assert not out.exists(), "output file must not be created when no pages matched"
    assert _FakeGenerator.calls == 0, "generator must not run when no pages matched"


def test_annotate_out_of_range_pages_message(
    runner: CliRunner, fakes: None, tmp_path: Path
) -> None:
    """The 'no pages matched' message must appear, matching preview's wording."""
    src = tmp_path / "book.pdf"
    src.write_bytes(_PDF_BYTES)
    out = tmp_path / "out.pdf"

    result = runner.invoke(cli_main, ["annotate", str(src), "-o", str(out), "--pages", "999"])
    assert result.exit_code == 1
    assert "No pages matched" in result.output, (
        f"expected 'No pages matched' in output:\n{result.output}"
    )


def test_annotate_in_range_pages_succeeds(
    runner: CliRunner, fakes: None, tmp_path: Path
) -> None:
    """Sanity: page 1 on a 1-page book must still succeed after the guard is added."""
    src = tmp_path / "book.pdf"
    src.write_bytes(_PDF_BYTES)
    out = tmp_path / "out.pdf"

    result = runner.invoke(cli_main, ["annotate", str(src), "-o", str(out), "--pages", "1"])
    assert result.exit_code == 0, result.output
    assert _FakeGenerator.calls == 1


# ===========================================================================
# DEFECT 4 — halfblood eval broken in every pip-installed wheel
# ===========================================================================


def test_eval_command_body_fails_gracefully_outside_source_checkout(
    runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When run from a wheel install (no pyproject.toml or eval/ adjacent), eval
    must fail with exit 1 and an actionable message about source checkouts — NOT
    a message naming a nonsense path like /usr/lib/python3.12/eval/eval_harness.py.

    This is NOT the --help test that already exists and passes for the wrong
    reason (Click intercepts --help before the command body runs).
    """
    # Point _EVAL_REPO_ROOT at an empty tmp directory (simulates a wheel install
    # where __file__'s parents[2] is something like site-packages).
    monkeypatch.setattr(cli_module, "_EVAL_REPO_ROOT", tmp_path)

    result = runner.invoke(cli_main, ["eval"])
    assert result.exit_code == 1, (
        f"expected exit 1 from eval in wheel context, got {result.exit_code}.\n{result.output}"
    )
    assert _no_traceback(result), f"raw exception leaked: {result.exception!r}"

    output = result.output
    # Must give actionable guidance
    assert "source checkout" in output.lower() or "source" in output.lower(), (
        f"missing 'source checkout' guidance in:\n{output}"
    )
    # Must NOT mention site-packages or any __file__-derived nonsense path
    assert "site-packages" not in output, f"leaked internal path in:\n{output}"
    # The error should not say the path to a nonexistent harness file
    assert "eval_harness.py" not in output or "not found" not in output, (
        f"leaked confusing file path in:\n{output}"
    )


def test_eval_command_body_runs_harness_from_source_checkout(
    runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When run from a source checkout (pyproject.toml + eval/eval_harness.py present),
    the command should attempt to invoke the harness.
    """
    # Set up a minimal source-checkout structure
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'fake'", encoding="utf-8")
    eval_dir = tmp_path / "eval"
    eval_dir.mkdir()
    harness = eval_dir / "eval_harness.py"
    harness.write_text("# fake harness\n", encoding="utf-8")

    monkeypatch.setattr(cli_module, "_EVAL_REPO_ROOT", tmp_path)

    # Mock subprocess.run to capture what the command would invoke and return 0
    captured: list[list[str]] = []

    def _fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess:  # type: ignore[type-arg]
        captured.append(cmd)
        return subprocess.CompletedProcess(cmd, returncode=0)

    monkeypatch.setattr(cli_module.subprocess, "run", _fake_run)

    result = runner.invoke(cli_main, ["eval"])
    # Click wraps SystemExit from `raise SystemExit(0)` — exit_code 0 is success
    assert result.exit_code == 0, (
        f"expected exit 0 when harness exists, got {result.exit_code}.\n{result.output}"
    )
    assert len(captured) == 1, f"expected subprocess.run to be called once: {captured}"
    assert str(harness) in captured[0], (
        f"expected harness path {harness} in command {captured[0]}"
    )


# ===========================================================================
# DEFECT 5 — dead hasattr branch
# ===========================================================================


def test_both_real_processors_define_render_plan() -> None:
    """Both real processors define render_plan — the hasattr guard and
    render_annotations fallback were dead in production.

    This is a documentation-style assertion, not a behavioral regression test
    (the dead code produced no observable difference for the real processors).
    The evidence that the else-branch was test-double-only: removing it and
    updating all fake processors to add render_plan leaves all 1750 tests green.
    """
    from halfblood.document_processor import DocumentProcessor
    from halfblood.epub_processor import EpubProcessor

    assert hasattr(DocumentProcessor, "render_plan"), (
        "DocumentProcessor must define render_plan (used unconditionally by annotate)"
    )
    assert hasattr(EpubProcessor, "render_plan"), (
        "EpubProcessor must define render_plan (used unconditionally by annotate)"
    )
    assert not hasattr(DocumentProcessor, "_hasattr_guard_present"), (
        "unexpected guard attribute — this test needs updating"
    )
