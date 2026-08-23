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


def test_boilerplate_pages_recorded_as_skipped_in_sidecar(tmp_path: Path) -> None:
    """A boilerplate-filtered page must stay visible in the sidecar."""
    from halfblood.boilerplate import BoilerplateVerdict

    clean = BoilerplateVerdict(is_boilerplate=False, score=0.0,
                               matched_markers=())
    boiler = BoilerplateVerdict(is_boilerplate=True, score=99.0,
                                matched_markers=("test",))

    def fake_classify(text: str) -> BoilerplateVerdict:
        return boiler if text.strip().startswith("Chapter") else clean

    out_path = tmp_path / "out.pdf"
    full_args = [
        "annotate", str(_PDF_FIXTURE), "-o", str(out_path),
        "--provider", "stub", "--force",
    ]
    runner = CliRunner()
    with patch("halfblood.cli.resolve_generation_config", _hermetic_resolve), \
            patch("halfblood.boilerplate.classify", side_effect=fake_classify):
        result = runner.invoke(cli_main, full_args)
    assert result.exit_code == 0, f"exit={result.exit_code}\n{result.output}"
    report = json.loads(sidecar_path_for(out_path).read_text(encoding="utf-8"))
    skipped = {
        s["page_number"]: s["error"]
        for s in report["page_statuses"]
        if s["status"] == "skipped"
    }
    assert skipped, "boilerplate page missing from page_statuses"
    assert all(err == "boilerplate" for err in skipped.values())
    numbers = [s["page_number"] for s in report["page_statuses"]]
    assert len(numbers) == len(set(numbers)), "duplicate page records"
    assert report["pages_total"] == len(numbers)


class TestBuildRunReportBoilerplateAccounting:
    @staticmethod
    def _statuses() -> list[Any]:
        from collections import namedtuple

        status = namedtuple("S", "ordinal status attempts error")
        return [
            status(1, "success", 1, None),
            status(3, "failed", 2, Exception("simulated")),
        ]

    def test_boilerplate_pages_merged_and_sorted(self) -> None:
        from halfblood.generation.run_report import build_run_report

        report = build_run_report(
            output_file=Path("/tmp/out.pdf"),
            plan=None,
            statuses=self._statuses(),
            boilerplate_pages=[2],
            pages_selected=5,
        )
        assert [s.page_number for s in report.page_statuses] == [1, 2, 3]
        assert report.skipped_pages == (2,)
        assert report.failed_pages == (3,)
        assert report.pages_total == 5
        assert report.page_statuses[1].error == "boilerplate"

    def test_no_boilerplate_keeps_legacy_shape(self) -> None:
        from halfblood.generation.run_report import build_run_report

        report = build_run_report(
            output_file=Path("/tmp/out.pdf"),
            plan=None,
            statuses=self._statuses(),
        )
        assert [s.page_number for s in report.page_statuses] == [1, 3]
        assert report.pages_total == 0  # plan=None, no pages_selected


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
