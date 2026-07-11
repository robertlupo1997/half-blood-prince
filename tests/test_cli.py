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

from pathlib import Path

import pytest
from click.testing import CliRunner

import halfblood.cli as cli_module
from halfblood.document_processor import PageContent
from halfblood.models import AnnotatedPage, AnnotationPlan
from halfblood.web_preview import PreviewResult

_PDF_BYTES = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n%%EOF\n"
_ZIP_BYTES = b"PK\x03\x04" + b"\x00" * 32


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

    def __init__(self, persona: str | None = None, model: str | None = None) -> None:
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
