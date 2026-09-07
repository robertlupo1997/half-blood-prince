"""Real offline CLI regressions: every input survives every output write/delete.

These use the real processors, generator, config resolver, and stub provider.
No machine credentials or remote requests are needed.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from click.testing import CliRunner

from halfblood.cli import _checkpoint_path_for, main
from halfblood.generation.run_report import sidecar_path_for
from halfblood.models import AnnotatedPage, AnnotationPlan

_FIXTURE = Path(__file__).parent / "fixtures" / "potions_textbook.pdf"
_FONT = Path(__file__).parents[1] / "src/halfblood/fonts/CaveatBrush-Regular.ttf"


@pytest.fixture()
def book(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    # Real resolver, but no implicit project settings or provider env overrides.
    import os

    for name in tuple(os.environ):
        if name.startswith("HALFBLOOD_"):
            monkeypatch.delenv(name)
    monkeypatch.chdir(tmp_path)
    path = tmp_path / "book.pdf"
    shutil.copyfile(_FIXTURE, path)
    return path


def _resume_bytes() -> bytes:
    return AnnotationPlan(
        title="saved work",
        prince_persona="An exacting editor",
        pages=[AnnotatedPage(page_number=1, original_text="saved text", annotations=[])],
    ).model_dump_json().encode()


def _source(tmp_path: Path, book: Path, kind: str) -> tuple[Path, list[str]]:
    if kind == "book":
        return book, []
    source = tmp_path / {"persona": "persona.txt", "config": "config.toml",
                         "font": "custom.ttf", "resume": "resume.json"}[kind]
    content = {"persona": b"An exacting editor", "config": b"[generation]\nprovider = 'stub'\n",
               "font": _FONT.read_bytes(), "resume": _resume_bytes()}[kind]
    source.write_bytes(content)
    flag = {"persona": "--persona-file", "config": "--config",
            "font": "--font", "resume": "--resume-from"}[kind]
    return source, [flag, str(source)]


def _alias(path: Path, source: Path, kind: str) -> None:
    if kind == "symlink":
        path.symlink_to(source)
    else:
        path.hardlink_to(source)


def _annotate(book: Path, output: Path, *args: str):
    return CliRunner().invoke(main, [
        "annotate", str(book), "-o", str(output), "--provider", "stub",
        "--dry-run", "--pages", "1", "--force", *args,
    ])


@pytest.mark.parametrize("source_kind", ["book", "persona", "config", "font", "resume"])
@pytest.mark.parametrize("alias_kind", ["symlink", "hardlink"])
@pytest.mark.parametrize("write_kind", ["artifact", "checkpoint", "report"])
def test_all_output_aliases_preserve_inputs(
    tmp_path: Path, book: Path, source_kind: str, alias_kind: str, write_kind: str
) -> None:
    source, args = _source(tmp_path, book, source_kind)
    original = source.read_bytes()
    output = tmp_path / "out.pdf"
    destination = {"artifact": output, "checkpoint": _checkpoint_path_for(output),
                   "report": sidecar_path_for(output)}[write_kind]
    _alias(destination, source, alias_kind)
    result = _annotate(book, output, *args)
    assert source.exists(), "an output cleanup deleted an input"
    assert source.read_bytes() == original, "an output write modified an input"
    if source_kind == "resume" and write_kind == "checkpoint":
        # Resume files are read-only. Continue checkpointing at a different path.
        assert result.exit_code == 0, result.output
        assert destination.exists(), "supplied resume alias must not be deleted"
        assert destination.read_bytes() == original
    else:
        assert result.exit_code == 1, result.output
        assert isinstance(result.exception, SystemExit), repr(result.exception)
        assert "same file" in result.output


@pytest.mark.parametrize("source_kind", ["persona", "config", "resume"])
@pytest.mark.parametrize("write_kind", ["checkpoint", "report"])
def test_derived_output_direct_input_path(
    tmp_path: Path, book: Path, source_kind: str, write_kind: str
) -> None:
    source, args = _source(tmp_path, book, source_kind)
    output = tmp_path / "out.pdf"
    destination = (_checkpoint_path_for(output) if write_kind == "checkpoint"
                   else sidecar_path_for(output))
    source.rename(destination)
    original = destination.read_bytes()
    args[1] = str(destination)
    result = _annotate(book, output, *args)
    assert destination.exists(), "supplied input must never be consumed"
    assert destination.read_bytes() == original
    expected = 0 if source_kind == "resume" and write_kind == "checkpoint" else 1
    assert result.exit_code == expected, result.output


@pytest.mark.parametrize("source_kind", ["book", "persona", "config", "font", "resume"])
@pytest.mark.parametrize("alias_kind", ["symlink", "hardlink"])
def test_legacy_fixed_temporary_path_is_untouched(
    tmp_path: Path, book: Path, source_kind: str, alias_kind: str
) -> None:
    source, args = _source(tmp_path, book, source_kind)
    original = source.read_bytes()
    output = tmp_path / "out.pdf"
    old_temp = Path(str(_checkpoint_path_for(output)) + ".tmp")
    _alias(old_temp, source, alias_kind)
    result = _annotate(book, output, *args)
    assert source.read_bytes() == original, "fixed .tmp write corrupted an input"
    assert old_temp.exists(), "fixed .tmp rename consumed an input alias"
    assert old_temp.read_bytes() == original
    assert result.exit_code == 0, result.output


@pytest.mark.parametrize("pair", [("artifact", "checkpoint"), ("artifact", "report"),
                                  ("checkpoint", "report")])
@pytest.mark.parametrize("alias_kind", ["symlink", "hardlink"])
def test_outputs_must_not_alias_each_other(
    tmp_path: Path, book: Path, pair: tuple[str, str], alias_kind: str
) -> None:
    output = tmp_path / "out.pdf"
    paths = {"artifact": output, "checkpoint": _checkpoint_path_for(output),
             "report": sidecar_path_for(output)}
    first, second = (paths[name] for name in pair)
    first.write_bytes(b"existing output")
    _alias(second, first, alias_kind)
    original_book = book.read_bytes()
    result = _annotate(book, output)
    assert first.exists() and second.exists(), "cleanup consumed another output"
    assert first.read_bytes() == second.read_bytes() == b"existing output"
    assert book.read_bytes() == original_book
    assert result.exit_code == 1, result.output
    assert isinstance(result.exception, SystemExit), repr(result.exception)


@pytest.mark.parametrize("write_kind", ["checkpoint", "report"])
def test_existing_sidecars_require_force(
    tmp_path: Path, book: Path, write_kind: str
) -> None:
    output = tmp_path / "out.pdf"
    path = _checkpoint_path_for(output) if write_kind == "checkpoint" else sidecar_path_for(output)
    path.write_bytes(b"previous work")
    result = CliRunner().invoke(main, ["annotate", str(book), "-o", str(output),
                                      "--provider", "stub", "--dry-run", "--pages", "1"])
    assert path.exists() and path.read_bytes() == b"previous work"
    assert not output.exists()
    assert result.exit_code == 1, result.output
    assert "--force" in result.output


def test_failure_report_cannot_overwrite_persona(tmp_path: Path, book: Path) -> None:
    output = tmp_path / "out.pdf"
    source = sidecar_path_for(output)
    source.write_text("An exacting editor", encoding="utf-8")
    original = source.read_bytes()
    result = _annotate(book, output, "--persona-file", str(source), "--fail-pages", "1")
    assert source.read_bytes() == original
    assert result.exit_code == 1
    assert "same file" in result.output


def test_pdf_and_epub_checkpoint_names_are_distinct(tmp_path: Path) -> None:
    assert _checkpoint_path_for(tmp_path / "alice.pdf") != _checkpoint_path_for(
        tmp_path / "alice.epub"
    )


def test_resume_input_is_preserved_on_render_success(tmp_path: Path, book: Path) -> None:
    output = tmp_path / "out.pdf"
    resume = _checkpoint_path_for(output)
    original = _resume_bytes()
    resume.write_bytes(original)
    result = CliRunner().invoke(main, ["annotate", str(book), "-o", str(output),
                                      "--provider", "stub", "--pages", "1",
                                      "--resume-from", str(resume)])
    assert resume.exists() and resume.read_bytes() == original
    assert result.exit_code == 0, result.output
    report = json.loads(sidecar_path_for(output).read_text())
    assert report["page_statuses"][0]["status"] == "resumed"
    assert output.read_bytes().startswith(b"%PDF")
