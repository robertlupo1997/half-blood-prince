"""F1 — explicit PDF handwriting-font selection at the CLI boundary."""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

import halfblood.cli as cli_module
from halfblood.document_processor import PageContent
from halfblood.models import AnnotatedPage, AnnotationPlan

_PDF_BYTES = b"%PDF-1.4\n%%EOF\n"
_ZIP_BYTES = b"PK\x03\x04" + b"\x00" * 32


class _RecordingPdfProcessor:
    constructor_kwargs: list[dict[str, object]] = []

    def __init__(self, **kwargs: object) -> None:
        type(self).constructor_kwargs.append(kwargs)

    def load(self, path: str) -> list[PageContent]:
        return [PageContent(page_number=1, text="page", width=612.0, height=792.0)]

    def annotations_from_plan(self, plan: AnnotationPlan) -> list[object]:
        return []

    def render_annotations(
        self, input_path: str, annotations: list[object], output_path: str
    ) -> None:
        Path(output_path).write_bytes(b"pdf")


class _RecordingEpubProcessor:
    constructor_calls = 0

    def __init__(self) -> None:
        type(self).constructor_calls += 1

    def load(self, path: str) -> list[PageContent]:
        return [PageContent(page_number=1, text="chapter", width=600.0, height=800.0)]

    def render_annotations(
        self, input_path: str, annotations: list[object], output_path: str
    ) -> None:
        Path(output_path).write_bytes(b"epub")


class _FakeGenerator:
    calls = 0

    def __init__(
        self,
        persona: str | None = None,
        model: str | None = None,
        provider: object | None = None,
    ) -> None:
        # No **kwargs — any unexpected keyword from cli.py raises TypeError, surfacing a
        # signature mismatch rather than hiding it.  `provider=` arrived with the P1-T9a
        # seam: annotate/preview now build a provider and inject it here.
        self.failed_pages: list[int] = []

    def generate_for_document(
        self, pages: list[PageContent], max_annotations_per_page: int = 5
    ) -> AnnotationPlan:
        type(self).calls += 1
        return AnnotationPlan(
            title="test",
            prince_persona="test",
            pages=[
                AnnotatedPage(page_number=page.page_number, original_text=page.text)
                for page in pages
            ],
        )


@pytest.fixture()
def pipeline_fakes(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _RecordingPdfProcessor.constructor_kwargs = []
    _RecordingEpubProcessor.constructor_calls = 0
    _FakeGenerator.calls = 0
    monkeypatch.setattr(cli_module, "DocumentProcessor", _RecordingPdfProcessor)
    monkeypatch.setattr(cli_module, "EpubProcessor", _RecordingEpubProcessor)
    monkeypatch.setattr(cli_module, "AnnotationGenerator", _FakeGenerator)
    # The P1-T9a seam makes annotate/preview resolve config and build a provider BEFORE
    # constructing the (faked) generator, so the merged "hosted providers require a key
    # env var" contract (config.py) now fires ahead of the fake.  These tests are about
    # font plumbing, not provider resolution: give the REAL resolver a throwaway key so it
    # reaches DocumentProcessor.  No model is set — the anthropic preset supplies it — and
    # the built provider is never called, because the generator itself is faked.
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-not-a-real-key")
    # Hermeticity.  These tests reach the REAL resolver through CliRunner and cannot pass
    # it the `project_config_path`/`user_config_path` kwargs the seam tests use, so it
    # falls back to `Path.cwd()/halfblood.toml` and the platformdirs user config dir.
    # Both are real machine paths.  Point them at an empty tmp dir: arch §4.4 ships an
    # example `halfblood.toml` (with `concurrency = 3`), so a developer trying that example
    # at the repo root would otherwise silently steer these font tests.
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg-empty"))


def _invoke_annotate(
    tmp_path: Path, suffix: str, font: str, *, runner: CliRunner | None = None
):
    source = tmp_path / f"book{suffix}"
    source.write_bytes(_PDF_BYTES if suffix == ".pdf" else _ZIP_BYTES)
    return (runner or CliRunner()).invoke(
        cli_module.main,
        ["annotate", str(source), "-o", str(tmp_path / f"out{suffix}"), "--font", font],
    )


def test_resolve_registered_font_with_injected_fonts_dir(tmp_path: Path) -> None:
    expected = tmp_path / "JustMeAgainDownHere.ttf"
    expected.write_bytes(b"font")

    assert cli_module._resolve_font_option("just-me-again-down-here", tmp_path) == expected


def test_font_path_is_passed_to_pdf_processor(
    tmp_path: Path, pipeline_fakes: None
) -> None:
    font = tmp_path / "custom.ttf"
    font.write_bytes(b"font")

    result = _invoke_annotate(tmp_path, ".pdf", str(font))

    assert result.exit_code == 0, result.output
    assert _RecordingPdfProcessor.constructor_kwargs == [{"font_path": str(font)}]


def test_registered_font_is_resolved_and_passed_to_pdf_processor(
    tmp_path: Path, pipeline_fakes: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    fonts_dir = tmp_path / "fonts"
    fonts_dir.mkdir()
    expected = fonts_dir / "CaveatBrush-Regular.ttf"
    expected.write_bytes(b"font")
    monkeypatch.setattr(cli_module, "_FONTS_DIR", fonts_dir)

    result = _invoke_annotate(tmp_path, ".pdf", "caveat-brush")

    assert result.exit_code == 0, result.output
    assert _RecordingPdfProcessor.constructor_kwargs == [{"font_path": str(expected)}]


def test_missing_registered_font_has_actionable_error(
    tmp_path: Path, pipeline_fakes: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    fonts_dir = tmp_path / "fonts"
    monkeypatch.setattr(cli_module, "_FONTS_DIR", fonts_dir)

    result = _invoke_annotate(tmp_path, ".pdf", "homemade-apple")

    assert result.exit_code != 0
    assert "Homemade Apple" in result.output
    assert str(fonts_dir / "HomemadeApple-Regular.ttf") in result.output
    assert "https://fonts.google.com/specimen/Homemade+Apple" in result.output
    assert _FakeGenerator.calls == 0


def test_unknown_font_lists_registered_names(
    tmp_path: Path, pipeline_fakes: None
) -> None:
    result = _invoke_annotate(tmp_path, ".pdf", "professor-scrawl")

    assert result.exit_code != 0
    for name in cli_module.REGISTERED_FONTS:
        assert name in result.output
    assert _FakeGenerator.calls == 0


def test_missing_explicit_font_path_fails_before_generation(
    tmp_path: Path, pipeline_fakes: None
) -> None:
    missing = tmp_path / "missing.ttf"

    result = _invoke_annotate(tmp_path, ".pdf", str(missing))

    assert result.exit_code != 0
    assert str(missing) in result.output
    assert _FakeGenerator.calls == 0


def test_epub_warns_and_ignores_font(
    tmp_path: Path, pipeline_fakes: None
) -> None:
    result = _invoke_annotate(tmp_path, ".epub", "mrs-saint-delafield")

    assert result.exit_code == 0, result.output
    assert "EPUB" in result.output
    assert "ignored" in result.output
    assert "reader/CSS" in result.output
    assert _RecordingEpubProcessor.constructor_calls == 1
    assert _FakeGenerator.calls == 1


def test_annotate_help_lists_font_names() -> None:
    result = CliRunner().invoke(cli_module.main, ["annotate", "--help"])

    assert result.exit_code == 0
    assert "--font" in result.output
    for name in cli_module.REGISTERED_FONTS:
        assert name in result.output
