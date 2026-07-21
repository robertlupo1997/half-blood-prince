"""P0-T7 — CLI input-signature validation and output-overwrite protection.

AUD-17: a mislabeled input (non-PDF bytes named ``.pdf``, non-ZIP bytes named
``.epub``) currently reaches the processing library and dies with a raw
parser traceback. The CLI must check magic bytes BEFORE dispatching to any
processor and fail with an actionable Click error.

AUD-37: an existing output file is silently replaced. Overwrites must be
opt-in via ``--force``; without it the command refuses, preserves the
existing bytes, and never invokes generation or rendering. Missing output
parent directories are created.

The processors and generator are replaced with fakes patched into the
``halfblood.cli`` namespace, so these tests pin the ORDER of operations
(validation before processing) rather than library error behavior — with the
fakes in place, a CLI that skips validation "succeeds", which is exactly the
regression these tests must catch.

No network calls are made anywhere in this file.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from click.testing import CliRunner
from rich.console import Console

import halfblood.cli as cli_module
from halfblood.config import ResolvedConfig
from halfblood.document_processor import PageContent
from halfblood.models import AnnotatedPage, AnnotationPlan
from halfblood.models.rendering import RenderReport, SkipReason, SkipRecord
from halfblood.web_preview import PreviewResult

_PDF_BYTES = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n%%EOF\n"
_ZIP_BYTES = b"PK\x03\x04" + b"\x00" * 32

# ---------------------------------------------------------------------------
# Fake config + provider injected by the `fakes` fixture so that after Codex
# wires the provider seam, existing tests keep passing without needing a real
# API key or model env var.
# ---------------------------------------------------------------------------

_FAKE_CLI_SOURCES: dict[str, str] = {
    "provider": "default",
    "model": "cli",
    "base_url": "preset",
    "api_key_env": "preset",
    "structured_output": "preset",
    "timeout_seconds": "default",
    "max_retries": "default",
    "concurrency": "phase1",
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
    concurrency=1,
    allow_insecure_http=False,
    sources=_FAKE_CLI_SOURCES,
)


class _FakeCliProvider:
    """Minimal LLMProvider double for the fakes fixture.

    .complete() raises immediately — if it is ever called, the test fails because
    the full AnnotationGenerator is also faked, so no provider call should occur.
    """

    @property
    def capabilities(self):
        from halfblood.generation.providers.base import ProviderCapabilities

        return ProviderCapabilities(
            supports_tool_calling=True,
            supports_json_schema=False,
            supports_strict_json_schema=False,
        )

    def complete(self, request):
        raise AssertionError(
            "direct provider.complete() called — AnnotationGenerator should be faked"
        )


class _FakePdfProcessor:
    load_calls: list[str] = []
    render_calls: list[str] = []

    def load(self, path: str) -> list[PageContent]:
        type(self).load_calls.append(path)
        return [PageContent(page_number=1, text="some page text", width=612.0, height=792.0)]

    def render_annotations(self, input_path: str, annotations: list, output_path: str) -> None:
        type(self).render_calls.append(output_path)
        Path(output_path).write_text("rendered-pdf", encoding="utf-8")

    def annotations_from_plan(self, plan: AnnotationPlan) -> list:
        return [a for page in plan.pages for a in page.annotations]


class _FakeEpubProcessor:
    load_calls: list[str] = []
    render_calls: list[str] = []

    def load(self, path: str) -> list[PageContent]:
        type(self).load_calls.append(path)
        return [PageContent(page_number=1, text="chapter text", width=600.0, height=800.0)]

    def render_annotations(self, input_path: str, annotations: list, output_path: str) -> None:
        type(self).render_calls.append(output_path)
        Path(output_path).write_text("rendered-epub", encoding="utf-8")


class _FakeGenerator:
    calls: int = 0

    def __init__(
        self,
        persona: str | None = None,
        model: str | None = None,
        provider: object | None = None,
    ) -> None:
        # No **kwargs — any unexpected keyword from cli.py will raise TypeError,
        # surfacing a signature mismatch rather than hiding it.
        self.failed_pages: list[int] = []

    def generate_for_document(
        self, pages: list[PageContent], max_annotations_per_page: int = 5
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
    _FakePdfProcessor.load_calls = []
    _FakePdfProcessor.render_calls = []
    _FakeEpubProcessor.load_calls = []
    _FakeEpubProcessor.render_calls = []
    _FakeGenerator.calls = 0
    monkeypatch.setattr(cli_module, "DocumentProcessor", _FakePdfProcessor)
    monkeypatch.setattr(cli_module, "EpubProcessor", _FakeEpubProcessor)
    monkeypatch.setattr(cli_module, "AnnotationGenerator", _FakeGenerator)
    # After Codex wires the provider seam, annotate and preview will call
    # resolve_generation_config and build_provider.  Patch them here so the
    # existing tests keep passing without a real API key or model env var.
    monkeypatch.setattr(cli_module, "resolve_generation_config", lambda *a, **k: _FAKE_CLI_CONFIG)
    monkeypatch.setattr(cli_module, "build_provider", lambda *a, **k: _FakeCliProvider())


@pytest.fixture()
def runner() -> CliRunner:
    return CliRunner()


def _no_traceback(result) -> bool:
    return result.exception is None or isinstance(result.exception, SystemExit)


# ---------------------------------------------------------------------------
# AUD-17 — magic bytes are checked before any processor sees the file
# ---------------------------------------------------------------------------


def test_nonpdf_bytes_named_pdf_rejected_before_processing(
    runner: CliRunner, fakes: None, tmp_path: Path
) -> None:
    bogus = tmp_path / "book.pdf"
    bogus.write_bytes(b"<html>this is not a pdf</html>")
    result = runner.invoke(
        cli_module.main, ["annotate", str(bogus), "-o", str(tmp_path / "out.pdf")]
    )
    assert result.exit_code != 0
    assert _no_traceback(result), f"raw exception leaked: {result.exception!r}"
    assert "book.pdf" in result.output
    assert _FakePdfProcessor.load_calls == []
    assert _FakeGenerator.calls == 0


def test_nonzip_bytes_named_epub_rejected_before_processing(
    runner: CliRunner, fakes: None, tmp_path: Path
) -> None:
    bogus = tmp_path / "book.epub"
    bogus.write_bytes(b"just some text, not a zip container")
    result = runner.invoke(
        cli_module.main, ["annotate", str(bogus), "-o", str(tmp_path / "out.epub")]
    )
    assert result.exit_code != 0
    assert _no_traceback(result)
    assert "book.epub" in result.output
    assert _FakeEpubProcessor.load_calls == []
    assert _FakeGenerator.calls == 0


def test_empty_pdf_file_rejected(runner: CliRunner, fakes: None, tmp_path: Path) -> None:
    empty = tmp_path / "empty.pdf"
    empty.write_bytes(b"")
    result = runner.invoke(
        cli_module.main, ["annotate", str(empty), "-o", str(tmp_path / "out.pdf")]
    )
    assert result.exit_code != 0
    assert _no_traceback(result)
    assert _FakePdfProcessor.load_calls == []


def test_preview_rejects_invalid_pdf_bytes(
    runner: CliRunner, fakes: None, tmp_path: Path
) -> None:
    bogus = tmp_path / "book.pdf"
    bogus.write_bytes(b"nope")
    result = runner.invoke(cli_module.main, ["preview", str(bogus)])
    assert result.exit_code != 0
    assert _no_traceback(result)
    assert _FakePdfProcessor.load_calls == []
    assert _FakeGenerator.calls == 0


def test_valid_pdf_signature_dispatches_to_pipeline(
    runner: CliRunner, fakes: None, tmp_path: Path
) -> None:
    src = tmp_path / "book.pdf"
    src.write_bytes(_PDF_BYTES)
    out = tmp_path / "out.pdf"
    result = runner.invoke(cli_module.main, ["annotate", str(src), "-o", str(out)])
    assert result.exit_code == 0, result.output
    assert _FakePdfProcessor.load_calls == [str(src)]
    assert _FakeGenerator.calls == 1
    assert out.read_text(encoding="utf-8") == "rendered-pdf"


def test_valid_epub_signature_dispatches_to_pipeline(
    runner: CliRunner, fakes: None, tmp_path: Path
) -> None:
    src = tmp_path / "book.epub"
    src.write_bytes(_ZIP_BYTES)
    out = tmp_path / "out.epub"
    result = runner.invoke(cli_module.main, ["annotate", str(src), "-o", str(out)])
    assert result.exit_code == 0, result.output
    assert _FakeEpubProcessor.load_calls == [str(src)]
    assert out.read_text(encoding="utf-8") == "rendered-epub"


def test_unsupported_suffix_lists_supported_types(
    runner: CliRunner, fakes: None, tmp_path: Path
) -> None:
    src = tmp_path / "book.txt"
    src.write_text("plain text")
    result = runner.invoke(
        cli_module.main, ["annotate", str(src), "-o", str(tmp_path / "out.pdf")]
    )
    assert result.exit_code != 0
    assert _no_traceback(result)
    assert ".pdf" in result.output and ".epub" in result.output


# ---------------------------------------------------------------------------
# AUD-37 — overwrites are opt-in; parents are created
# ---------------------------------------------------------------------------


def test_annotate_refuses_existing_output_without_force(
    runner: CliRunner, fakes: None, tmp_path: Path
) -> None:
    src = tmp_path / "book.pdf"
    src.write_bytes(_PDF_BYTES)
    out = tmp_path / "out.pdf"
    out.write_bytes(b"precious bytes")
    result = runner.invoke(cli_module.main, ["annotate", str(src), "-o", str(out)])
    assert result.exit_code != 0
    assert _no_traceback(result)
    assert "--force" in result.output
    assert out.read_bytes() == b"precious bytes"
    assert _FakeGenerator.calls == 0
    assert _FakePdfProcessor.render_calls == []


def test_annotate_force_overwrites_existing_output(
    runner: CliRunner, fakes: None, tmp_path: Path
) -> None:
    src = tmp_path / "book.pdf"
    src.write_bytes(_PDF_BYTES)
    out = tmp_path / "out.pdf"
    out.write_bytes(b"old bytes")
    result = runner.invoke(
        cli_module.main, ["annotate", str(src), "-o", str(out), "--force"]
    )
    assert result.exit_code == 0, result.output
    assert _FakeGenerator.calls == 1
    assert out.read_text(encoding="utf-8") == "rendered-pdf"


def test_annotate_creates_missing_output_parents(
    runner: CliRunner, fakes: None, tmp_path: Path
) -> None:
    src = tmp_path / "book.pdf"
    src.write_bytes(_PDF_BYTES)
    out = tmp_path / "brand" / "new" / "dir" / "out.pdf"
    result = runner.invoke(cli_module.main, ["annotate", str(src), "-o", str(out)])
    assert result.exit_code == 0, result.output
    assert out.read_text(encoding="utf-8") == "rendered-pdf"


def test_web_preview_refuses_existing_output_without_force(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[str] = []

    def _fake_generate_preview(plan, output_path, book_text=None):
        calls.append(str(output_path))
        Path(output_path).write_text("preview", encoding="utf-8")
        return PreviewResult(Path(output_path), 1, 0, 0)

    monkeypatch.setattr(cli_module, "generate_preview", _fake_generate_preview)
    plan_file = tmp_path / "plan.json"
    plan_file.write_text(
        AnnotationPlan(title="t", prince_persona="p", pages=[]).model_dump_json(),
        encoding="utf-8",
    )
    out = tmp_path / "preview.html"
    out.write_bytes(b"precious html")
    result = runner.invoke(
        cli_module.main, ["web-preview", str(plan_file), "-o", str(out)]
    )
    assert result.exit_code != 0
    assert _no_traceback(result)
    assert "--force" in result.output
    assert out.read_bytes() == b"precious html"
    assert calls == []


def test_web_preview_force_overwrites(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def _fake_generate_preview(plan, output_path, book_text=None):
        Path(output_path).write_text("preview", encoding="utf-8")
        return PreviewResult(Path(output_path), 1, 0, 0)

    monkeypatch.setattr(cli_module, "generate_preview", _fake_generate_preview)
    plan_file = tmp_path / "plan.json"
    plan_file.write_text(
        AnnotationPlan(title="t", prince_persona="p", pages=[]).model_dump_json(),
        encoding="utf-8",
    )
    out = tmp_path / "preview.html"
    out.write_bytes(b"old html")
    result = runner.invoke(
        cli_module.main, ["web-preview", str(plan_file), "-o", str(out), "--force"]
    )
    assert result.exit_code == 0, result.output
    assert out.read_text(encoding="utf-8") == "preview"


# ---------------------------------------------------------------------------
# The behavior is documented where users look for it
# ---------------------------------------------------------------------------


def test_annotate_help_documents_force(runner: CliRunner) -> None:
    result = runner.invoke(cli_module.main, ["annotate", "--help"])
    assert result.exit_code == 0
    assert "--force" in result.output


def test_readme_documents_force() -> None:
    readme = Path(__file__).resolve().parents[1] / "README.md"
    assert "--force" in readme.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# P3-T12b — --handwriting-engine: typeset default; procedural is a P3-T5 NO-GO
# ---------------------------------------------------------------------------


def test_annotate_help_lists_handwriting_engine(runner: CliRunner) -> None:
    result = runner.invoke(cli_module.main, ["annotate", "--help"])
    assert result.exit_code == 0
    assert "--handwriting-engine" in result.output


def test_annotate_typeset_engine_dispatches_normally(
    runner: CliRunner, fakes: None, tmp_path: Path
) -> None:
    """The default/explicit typeset engine runs the pipeline to completion."""
    src = tmp_path / "book.pdf"
    src.write_bytes(_PDF_BYTES)
    out = tmp_path / "out.pdf"
    result = runner.invoke(
        cli_module.main,
        ["annotate", str(src), "-o", str(out), "--handwriting-engine", "typeset"],
    )
    assert result.exit_code == 0, result.output
    assert _no_traceback(result), f"raw exception leaked: {result.exception!r}"


def test_procedural_engine_rejected_before_provider_and_generator(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`procedural` must fail with p3_t5_no_go before any heavy construction.

    Neither the processor, provider config, provider, nor generator may be built
    — each is patched to explode, so the clean p3_t5_no_go ClickException proves
    the gate fired first (a leaked AssertionError would fail _no_traceback).
    """
    src = tmp_path / "book.pdf"
    src.write_bytes(_PDF_BYTES)
    out = tmp_path / "out.pdf"

    def _boom(*args: object, **kwargs: object):
        raise AssertionError(
            "procedural must be rejected before processor/provider/generator construction"
        )

    monkeypatch.setattr(cli_module, "DocumentProcessor", _boom)
    monkeypatch.setattr(cli_module, "resolve_generation_config", _boom)
    monkeypatch.setattr(cli_module, "build_provider", _boom)
    monkeypatch.setattr(cli_module, "AnnotationGenerator", _boom)

    result = runner.invoke(
        cli_module.main,
        ["annotate", str(src), "-o", str(out), "--handwriting-engine", "procedural"],
    )
    assert result.exit_code != 0
    assert _no_traceback(result), f"raw exception leaked: {result.exception!r}"
    assert "p3_t5_no_go" in result.output


def test_procedural_engine_gate_precedes_font_resolution(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A bogus --font must NOT mask the p3_t5_no_go rejection (gate is earlier)."""
    src = tmp_path / "book.pdf"
    src.write_bytes(_PDF_BYTES)
    out = tmp_path / "out.pdf"

    def _boom(*args: object, **kwargs: object):
        raise AssertionError("nothing past the procedural gate may run")

    monkeypatch.setattr(cli_module, "DocumentProcessor", _boom)
    monkeypatch.setattr(cli_module, "resolve_generation_config", _boom)
    monkeypatch.setattr(cli_module, "build_provider", _boom)
    monkeypatch.setattr(cli_module, "AnnotationGenerator", _boom)

    result = runner.invoke(
        cli_module.main,
        [
            "annotate", str(src), "-o", str(out),
            "--handwriting-engine", "procedural",
            "--font", "/nonexistent/bogus.ttf",
        ],
    )
    assert result.exit_code != 0
    assert _no_traceback(result), f"raw exception leaked: {result.exception!r}"
    assert "p3_t5_no_go" in result.output
    assert "bogus.ttf" not in result.output, (
        "font resolution ran before the procedural gate — the NO-GO was masked"
    )


# ---------------------------------------------------------------------------
# MP2b — render summary surfaces marks_only count
#
# The CLI prints "Rendered N / Skipped M" after render_plan returns.  When
# report.marks_only is non-empty, it must append " (K mark-only)" so users
# know how many skipped annotations still produced a visible target mark.
# ---------------------------------------------------------------------------


def _plan_processor_factory(report: RenderReport) -> type:
    """Return a fake PDF processor class whose render_plan returns `report`."""

    class _FakePlanProcessor:
        def load(self, path: str) -> list[PageContent]:
            return [PageContent(page_number=1, text="t", width=612.0, height=792.0)]

        def render_plan(self, input_path: str, plan: object, output_path: str) -> RenderReport:
            Path(output_path).write_text("pdf", encoding="utf-8")
            return report

        def annotations_from_plan(self, plan: object) -> list:
            return []

    return _FakePlanProcessor


def _annotate_with_report(
    runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    report: RenderReport,
) -> tuple[object, str]:
    """Invoke `halfblood annotate` backed by a plan-processor returning `report`.

    Returns (CliRunner result, text printed to the Rich console).
    """
    _FakeGenerator.calls = 0
    buf = io.StringIO()
    # width=200 prevents Rich from wrapping the summary line at 80 chars.
    fake_console = Console(file=buf, markup=False, highlight=False, width=200)
    monkeypatch.setattr(cli_module, "DocumentProcessor", _plan_processor_factory(report))
    monkeypatch.setattr(cli_module, "EpubProcessor", _FakeEpubProcessor)
    monkeypatch.setattr(cli_module, "AnnotationGenerator", _FakeGenerator)
    monkeypatch.setattr(cli_module, "resolve_generation_config", lambda *a, **k: _FAKE_CLI_CONFIG)
    monkeypatch.setattr(cli_module, "build_provider", lambda *a, **k: _FakeCliProvider())
    monkeypatch.setattr(cli_module, "console", fake_console)
    src = tmp_path / "book.pdf"
    src.write_bytes(_PDF_BYTES)
    out = tmp_path / "out.pdf"
    result = runner.invoke(cli_module.main, ["annotate", str(src), "-o", str(out)])
    return result, buf.getvalue()


def test_render_summary_empty_marks_only_omits_qualifier(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Empty marks_only → summary is 'Rendered N / Skipped M' with no qualifier.

    Pins current behavior — must pass both before and after MP2b.
    """
    report = RenderReport(
        rendered=("a1",),
        skipped=(SkipRecord(annotation_id="s1", reason=SkipReason.MISSING_TARGET),),
        # marks_only defaults to () — already a subset of {"s1"}
    )
    result, printed = _annotate_with_report(runner, monkeypatch, tmp_path, report)
    assert result.exit_code == 0, result.output
    summary_lines = [line.strip() for line in printed.splitlines()]
    assert "Rendered 1 / Skipped 1" in summary_lines, (
        f"expected exact summary line; got lines: {summary_lines!r}"
    )
    assert "mark-only" not in printed


def test_render_summary_nonempty_marks_only_appends_qualifier(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Non-empty marks_only → '(K mark-only)' appended after the skipped count.

    Fails before MP2b because cli.py does not yet include the qualifier.
    """
    report = RenderReport(
        rendered=("a1",),
        skipped=(
            SkipRecord(annotation_id="m1", reason=SkipReason.UNPLACEABLE),
            SkipRecord(annotation_id="m2", reason=SkipReason.UNPLACEABLE),
        ),
        marks_only=("m1", "m2"),  # valid: subset of skipped ids {"m1", "m2"}
    )
    result, printed = _annotate_with_report(runner, monkeypatch, tmp_path, report)
    assert result.exit_code == 0, result.output
    assert "Rendered 1 / Skipped 2 (2 mark-only)" in printed
