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


# ===========================================================================
# DEFECT 1 (follow-up) — web-preview overwrites its own inputs
# ===========================================================================


def test_web_preview_refuses_when_output_is_plan_file(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """web-preview PLAN -o PLAN --force: the plan file must be unchanged."""
    from halfblood.models import AnnotationPlan

    plan_file = tmp_path / "plan.json"
    plan_file.write_text(
        AnnotationPlan(title="t", prince_persona="p", pages=[]).model_dump_json(),
        encoding="utf-8",
    )
    original_bytes = plan_file.read_bytes()

    # Do NOT patch generate_preview — if the guard fires before the renderer is
    # called, the original bytes are unchanged; if it fails to fire, the renderer
    # overwrites and the assertion below catches the data loss.
    monkeypatch.setattr(
        cli_module,
        "generate_preview",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("renderer must not be called")),
    )

    result = runner.invoke(cli_main, ["web-preview", str(plan_file), "-o", str(plan_file), "--force"])
    assert result.exit_code == 1, (
        f"expected exit 1 when output=plan, got {result.exit_code}.\n{result.output}"
    )
    assert _no_traceback(result), f"raw exception leaked: {result.exception!r}"
    assert plan_file.read_bytes() == original_bytes, "plan file bytes were modified"


def test_web_preview_refuses_when_output_is_book_file(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """web-preview PLAN --book BOOK -o BOOK --force: the book text must be unchanged."""
    from halfblood.models import AnnotationPlan

    plan_file = tmp_path / "plan.json"
    plan_file.write_text(
        AnnotationPlan(title="t", prince_persona="p", pages=[]).model_dump_json(),
        encoding="utf-8",
    )
    book_file = tmp_path / "book.txt"
    book_file.write_text("Chapter One. It was a dark and stormy night.", encoding="utf-8")
    original_bytes = book_file.read_bytes()

    monkeypatch.setattr(
        cli_module,
        "generate_preview",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("renderer must not be called")),
    )

    result = runner.invoke(
        cli_main,
        ["web-preview", str(plan_file), "--book", str(book_file), "-o", str(book_file), "--force"],
    )
    assert result.exit_code == 1, (
        f"expected exit 1 when output=book, got {result.exit_code}.\n{result.output}"
    )
    assert _no_traceback(result), f"raw exception leaked: {result.exception!r}"
    assert book_file.read_bytes() == original_bytes, "book file bytes were modified"


def test_web_preview_force_overwrites_different_output(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """web-preview must still succeed with --force when output is a different file."""
    from halfblood.models import AnnotationPlan
    from halfblood.web_preview import PreviewResult

    plan_file = tmp_path / "plan.json"
    plan_file.write_text(
        AnnotationPlan(title="t", prince_persona="p", pages=[]).model_dump_json(),
        encoding="utf-8",
    )
    out = tmp_path / "preview.html"
    out.write_bytes(b"old html")

    monkeypatch.setattr(
        cli_module,
        "generate_preview",
        lambda plan, output_path, book_text=None: (
            Path(output_path).write_text("new html", encoding="utf-8"),
            PreviewResult(Path(output_path), 0, 0, 0),
        )[1],
    )

    result = runner.invoke(
        cli_main, ["web-preview", str(plan_file), "-o", str(out), "--force"]
    )
    assert result.exit_code == 0, result.output
    assert out.read_text(encoding="utf-8") == "new html"


def test_refuse_existing_output_takes_collection_not_single_path() -> None:
    """_refuse_existing_output takes source_paths (plural, a tuple) not source_path
    (singular).  This is the structural guarantee that a future command with multiple
    inputs cannot accidentally guard only one of them via a single-valued kwarg.

    Verify the API at the call level so a refactor that reverts to a single optional
    kwarg fails here.
    """
    import inspect
    import tempfile

    from halfblood.cli import _refuse_existing_output

    sig = inspect.signature(_refuse_existing_output)
    assert "source_paths" in sig.parameters, (
        "_refuse_existing_output must accept source_paths= (plural) not source_path="
    )
    assert "source_path" not in sig.parameters, (
        "_refuse_existing_output must not accept the singular source_path= kwarg; "
        "a single-valued optional is how web-preview's second input got missed"
    )
    # Verify it accepts a tuple and accepts an empty tuple (web-preview default)
    from pathlib import Path as _Path

    with tempfile.TemporaryDirectory() as d:
        out = _Path(d) / "out.txt"
        # Should not raise when no sources provided and file absent
        _refuse_existing_output(out, force=False, source_paths=())


# ===========================================================================
# DEFECT 2 (follow-up) — additional --pages holes
# ===========================================================================


def test_pages_reversed_range_exits_2(
    runner: CliRunner, fakes: None, tmp_path: Path
) -> None:
    """'5-1' (reversed range) must exit 2 with BadParameter, not annotate the whole book."""
    src = tmp_path / "book.pdf"
    src.write_bytes(_PDF_BYTES)

    result = runner.invoke(
        cli_main,
        ["annotate", str(src), "-o", str(tmp_path / "out.pdf"), "--pages", "5-1"],
    )
    assert result.exit_code == 2, (
        f"expected exit 2 for reversed range '5-1', got {result.exit_code}.\n{result.output}"
    )
    assert _no_traceback(result), f"raw exception leaked: {result.exception!r}"
    assert _FakeGenerator.calls == 0, "generator must not run on a reversed range"


def test_pages_zero_exits_2(
    runner: CliRunner, fakes: None, tmp_path: Path
) -> None:
    """'0' must exit 2 — pages are 1-based, so 0 is an invalid page number."""
    src = tmp_path / "book.pdf"
    src.write_bytes(_PDF_BYTES)

    result = runner.invoke(
        cli_main,
        ["annotate", str(src), "-o", str(tmp_path / "out.pdf"), "--pages", "0"],
    )
    assert result.exit_code == 2, (
        f"expected exit 2 for page '0', got {result.exit_code}.\n{result.output}"
    )
    assert _no_traceback(result), f"raw exception leaked: {result.exception!r}"
    assert _FakeGenerator.calls == 0


def test_pages_zero_range_exits_2(
    runner: CliRunner, fakes: None, tmp_path: Path
) -> None:
    """'0-3' must also exit 2 (consistent with '0' being rejected, not silently clamped)."""
    src = tmp_path / "book.pdf"
    src.write_bytes(_PDF_BYTES)

    result = runner.invoke(
        cli_main,
        ["annotate", str(src), "-o", str(tmp_path / "out.pdf"), "--pages", "0-3"],
    )
    assert result.exit_code == 2, (
        f"expected exit 2 for range '0-3', got {result.exit_code}.\n{result.output}"
    )
    assert _no_traceback(result), f"raw exception leaked: {result.exception!r}"


def test_pages_unicode_digits_rejected(
    runner: CliRunner, fakes: None, tmp_path: Path
) -> None:
    """Unicode decimal digits (e.g. Arabic-Indic '١٢٣') must be rejected with BadParameter.

    re.compile(r'\\d+') accepts them; re.compile(r'[0-9]+') does not.  The
    validator must use ASCII-only digit matching so the accepted set is consistent
    with what int() would parse for a valid ASCII spec.
    """
    src = tmp_path / "book.pdf"
    src.write_bytes(_PDF_BYTES)

    result = runner.invoke(
        cli_main,
        ["annotate", str(src), "-o", str(tmp_path / "out.pdf"), "--pages", "١٢٣"],  # ١٢٣
    )
    assert result.exit_code == 2, (
        f"expected exit 2 for Arabic-Indic '١٢٣', got {result.exit_code}.\n{result.output}"
    )
    assert _no_traceback(result), f"raw exception leaked: {result.exception!r}"


def test_pages_superscript_digits_still_rejected(
    runner: CliRunner, fakes: None, tmp_path: Path
) -> None:
    """'²' must still be rejected (it was already rejected before — verifying no regression)."""
    src = tmp_path / "book.pdf"
    src.write_bytes(_PDF_BYTES)

    result = runner.invoke(
        cli_main,
        ["annotate", str(src), "-o", str(tmp_path / "out.pdf"), "--pages", "²"],  # ²
    )
    assert result.exit_code == 2, (
        f"expected exit 2 for superscript '²', got {result.exit_code}.\n{result.output}"
    )
