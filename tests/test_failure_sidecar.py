"""End-to-end tests for the ``<output>.report.json`` failure sidecar.

Uses the real offline ``stub`` provider (no network, no API key) plus the
``--fail-pages`` injection knob, mirroring the roadmap completion test:

    halfblood annotate book.pdf -o out.pdf --provider stub --fail-pages 7,13 --force

The committed fixture ``tests/fixtures/report-sidecar.example.json`` pins the
public sidecar schema; test 4 validates it round-trips through ``RunReport``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

from click.testing import CliRunner

from halfblood.cli import main as cli_main
from halfblood.config import resolve_generation_config
from halfblood.generation.run_report import RunReport, sidecar_path_for

_TESTS_DIR = Path(__file__).resolve().parent
_PDF_FIXTURE = _TESTS_DIR / "fixtures" / "potions_textbook.pdf"
_SIDECAR_FIXTURE = _TESTS_DIR / "fixtures" / "report-sidecar.example.json"


def _hermetic_resolve(cli_overrides: Any = None, **kwargs: Any) -> Any:
    """Resolve config without touching real machine or user config files."""
    return resolve_generation_config(
        cli_overrides,
        environ={},
        project_config_path=Path("/nonexistent/halfblood.toml"),
        user_config_path=Path("/nonexistent/user-config.toml"),
    )


def _invoke_annotate(tmp_path: Path, args: list[str]) -> tuple[Any, Path]:
    """Run ``annotate`` against the fixture PDF with the real stub provider."""
    out_path = tmp_path / "out.pdf"
    full_args = [
        "annotate",
        str(_PDF_FIXTURE),
        "-o",
        str(out_path),
        "--provider",
        "stub",
        "--force",
        *args,
    ]
    runner = CliRunner()
    with patch("halfblood.cli.resolve_generation_config", _hermetic_resolve):
        result = runner.invoke(cli_main, full_args)
    return result, out_path


class TestFailureSidecarRendered:
    def test_failed_pages_named_in_sidecar(self, tmp_path: Path) -> None:
        result, out_path = _invoke_annotate(
            tmp_path,
            ["--fail-pages", "2,4"],
        )
        assert result.exit_code == 0, f"exit={result.exit_code}\n{result.output}"
        sidecar = sidecar_path_for(out_path)
        assert sidecar.exists(), "sidecar was not written next to the artifact"
        report = json.loads(sidecar.read_text(encoding="utf-8"))
        assert report["failed_pages"] == [2, 4]
        assert report["pages_annotated"] == 3
        assert report["render"] is not None
        errors = {
            s["page_number"]: s["error"]
            for s in report["page_statuses"]
            if s["status"] == "failed"
        }
        assert set(errors) == {2, 4}
        assert all("simulated" in e for e in errors.values())

    def test_clean_run_sidecar_has_no_failures(self, tmp_path: Path) -> None:
        result, out_path = _invoke_annotate(tmp_path, [])
        assert result.exit_code == 0, f"exit={result.exit_code}\n{result.output}"
        report = json.loads(sidecar_path_for(out_path).read_text(encoding="utf-8"))
        assert report["failed_pages"] == []
        assert report["skipped_pages"] == []
        assert report["pages_annotated"] == 5
        assert report["total_annotations"] == 5


class TestFailureSidecarDryRun:
    def test_dry_run_writes_sidecar_without_render(self, tmp_path: Path) -> None:
        result, out_path = _invoke_annotate(tmp_path, ["--dry-run"])
        assert result.exit_code == 0, f"exit={result.exit_code}\n{result.output}"
        report = json.loads(sidecar_path_for(out_path).read_text(encoding="utf-8"))
        assert out_path.exists()  # the dry-run plan JSON
        assert report["render"] is None
        assert report["pages_annotated"] == 5


class TestAllPagesFailed:
    def test_all_failed_writes_sidecar_and_exits_nonzero(self, tmp_path: Path) -> None:
        result, out_path = _invoke_annotate(
            tmp_path,
            ["--fail-pages", "1,2,3,4,5"],
        )
        assert result.exit_code != 0, "all-failed run must exit nonzero"
        assert not out_path.exists(), "no artifact should ship when every page failed"
        report = json.loads(sidecar_path_for(out_path).read_text(encoding="utf-8"))
        assert report["failed_pages"] == [1, 2, 3, 4, 5]
        assert report["render"] is None


class TestSidecarSchemaContract:
    def test_committed_fixture_validates_against_run_report(self) -> None:
        data = json.loads(_SIDECAR_FIXTURE.read_text(encoding="utf-8"))
        report = RunReport.model_validate(data)
        assert report.failed_pages == (2, 4)
        assert report.render is not None and report.render["rendered"]
