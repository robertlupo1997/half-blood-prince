"""Checkpoint/resume: crash-safe long runs via ``<output>.plan.json``.

Every ``annotate`` run streams its partial annotation plan to
``<output>.plan.json`` after each page completes (failed pages excluded, so a
resume retries them). ``--resume-from`` reloads that checkpoint and generates
only the missing pages. This mirrors HBP-ROADMAP-OX.md Phase 1 completion
test #1:

    halfblood annotate book.pdf -o out.pdf --max-pages 20 &
    kill %1   # after several pages complete
    halfblood annotate book.pdf -o out.pdf --resume-from out.plan.json --force

The interruption itself is simulated deterministically: either by injecting
provider failures (all remaining pages fail -> nonzero exit, checkpoint kept),
or by truncating a completed dry-run plan down to its already-finished pages.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

from click.testing import CliRunner

from halfblood.annotation_generator import AnnotationGenerator
from halfblood.cli import main as cli_main
from halfblood.config import resolve_generation_config
from halfblood.document_processor import PageContent
from halfblood.generation.providers.stub import FailPagesProvider, StubProvider
from halfblood.models.legacy import AnnotationPlan

_TESTS_DIR = Path(__file__).resolve().parent
_PDF_FIXTURE = _TESTS_DIR / "fixtures" / "potions_textbook.pdf"


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _pages(count: int) -> list[PageContent]:
    """Build synthetic pages with enough prose for the stub provider's anchor."""
    return [
        PageContent(
            page_number=i + 1,
            text=(
                f"Page {i + 1}: The draught must simmer for exactly seven "
                "minutes before the crushed moonstone is added."
            ),
            width=612.0,
            height=792.0,
        )
        for i in range(count)
    ]


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


# ---------------------------------------------------------------------------
# Generator level: streaming checkpoint semantics
# ---------------------------------------------------------------------------


class TestCheckpointStreaming:
    def test_checkpoint_contains_finished_pages_but_not_failed_ones(
        self, tmp_path: Path
    ) -> None:
        stub = StubProvider()
        generator = AnnotationGenerator(
            provider=FailPagesProvider(stub, {2}), concurrency=2
        )
        checkpoint = tmp_path / "out.plan.json"
        plan = generator.generate_for_document(_pages(5), checkpoint_path=checkpoint)

        assert checkpoint.exists(), "checkpoint was never written"
        payload = json.loads(checkpoint.read_text(encoding="utf-8"))
        numbers = [page["page_number"] for page in payload["pages"]]
        assert set(numbers) == {1, 3, 4, 5}, (
            "checkpoint must exclude failed pages so a resume retries them"
        )

        # The in-memory plan still records every page (failed ones empty).
        assert [page.page_number for page in plan.pages] == [1, 2, 3, 4, 5]
        assert plan.pages[1].annotations == []

    def test_no_checkpoint_without_checkpoint_path(self, tmp_path: Path) -> None:
        generator = AnnotationGenerator(provider=StubProvider(), concurrency=2)
        plan = generator.generate_for_document(_pages(2))
        assert len(plan.pages) == 2


class TestResumeMerge:
    def test_resumed_pages_skip_provider_and_merge_in_order(self, tmp_path: Path) -> None:
        first_stub = StubProvider()
        first_gen = AnnotationGenerator(
            provider=FailPagesProvider(first_stub, {2}), concurrency=2
        )
        checkpoint = tmp_path / "out.plan.json"
        first_gen.generate_for_document(_pages(5), checkpoint_path=checkpoint)

        resume_plan = AnnotationPlan.model_validate_json(
            checkpoint.read_text(encoding="utf-8")
        )
        resume_map = {page.page_number: page for page in resume_plan.pages}
        assert set(resume_map) == {1, 3, 4, 5}

        second_stub = StubProvider()
        second_gen = AnnotationGenerator(provider=second_stub, concurrency=2)
        merged = second_gen.generate_for_document(_pages(5), resume_pages=resume_map)

        # Only the missing page hit the provider.
        assert second_stub.call_count == 1
        assert [page.page_number for page in merged.pages] == [1, 2, 3, 4, 5]
        assert merged.total_annotations == 5

        statuses = {
            status.ordinal: status.status for status in second_gen.generation_statuses
        }
        assert statuses[2] == "success", "the missing page was generated fresh"
        assert all(
            statuses[number] == "resumed" for number in (1, 3, 4, 5)
        ), f"resumed statuses wrong: {statuses}"


# ---------------------------------------------------------------------------
# CLI level: checkpoint lifecycle and the end-to-end resume flow
# ---------------------------------------------------------------------------


class TestCliCheckpointLifecycle:
    def test_checkpoint_removed_after_successful_run(self, tmp_path: Path) -> None:
        from halfblood.cli import _checkpoint_path_for
        result, out_path = _invoke_annotate(tmp_path, [])
        assert result.exit_code == 0, f"exit={result.exit_code}\n{result.output}"
        checkpoint = _checkpoint_path_for(out_path)
        assert not checkpoint.exists(), (
            "successful runs must consume their checkpoint"
        )

    def test_checkpoint_kept_when_generation_fails(self, tmp_path: Path) -> None:
        from halfblood.cli import _checkpoint_path_for
        result, out_path = _invoke_annotate(tmp_path, ["--fail-pages", "1,2,3,4,5"])
        assert result.exit_code != 0
        assert not out_path.exists(), "no artifact may ship from a total failure"
        checkpoint = _checkpoint_path_for(out_path)
        assert checkpoint.exists(), "checkpoint must survive the failed run"
        assert "--resume-from" in result.output, (
            "the failure message must point at the resume command"
        )


class TestCliResumeEndToEnd:
    def test_resume_finishes_an_interrupted_run(self, tmp_path: Path) -> None:
        # Simulate the crash: complete a dry run, keep only the first three
        # finished pages, and leave them where a killed run would have.
        result, out_path = _invoke_annotate(tmp_path, ["--dry-run"])
        assert result.exit_code == 0, f"exit={result.exit_code}\n{result.output}"
        full_plan = json.loads(out_path.read_text(encoding="utf-8"))
        assert len(full_plan["pages"]) == 5
        full_plan["pages"] = [
            page for page in full_plan["pages"] if page["page_number"] <= 3
        ]
        checkpoint = tmp_path / "out.plan.json"
        checkpoint.write_text(json.dumps(full_plan), encoding="utf-8")
        out_path.unlink()

        result2, out2 = _invoke_annotate(
            tmp_path, ["--resume-from", str(checkpoint)]
        )
        assert result2.exit_code == 0, f"exit={result2.exit_code}\n{result2.output}"
        assert out2.exists(), "resumed run did not render the artifact"

        report = json.loads(
            (tmp_path / "out.pdf.report.json").read_text(encoding="utf-8")
        )
        resumed = sorted(
            entry["page_number"]
            for entry in report["page_statuses"]
            if entry["status"] == "resumed"
        )
        assert resumed == [1, 2, 3], f"unexpected resumed set: {resumed}"
        assert report["failed_pages"] == []
        assert report["render"] is not None
        assert report["pages_annotated"] == 5
        assert report["total_annotations"] == 5

    def test_resume_preserves_input_and_consumes_its_own_checkpoint_on_success(
        self, tmp_path: Path
    ) -> None:
        from halfblood.cli import _checkpoint_path_for
        result, out_path = _invoke_annotate(tmp_path, ["--dry-run"])
        assert result.exit_code == 0
        partial = json.loads(out_path.read_text(encoding="utf-8"))
        partial["pages"] = partial["pages"][:2]
        supplied_resume = tmp_path / "out.plan.json"
        supplied_resume_bytes = json.dumps(partial).encode("utf-8")
        supplied_resume.write_bytes(supplied_resume_bytes)

        result2, _ = _invoke_annotate(
            tmp_path, ["--dry-run", "--resume-from", str(supplied_resume)]
        )
        assert result2.exit_code == 0, f"exit={result2.exit_code}\n{result2.output}"
        # Supplied resume is an input: it must never be overwritten, deleted,
        # or mutated even with --force.
        assert supplied_resume.exists()
        assert supplied_resume.read_bytes() == supplied_resume_bytes
        # The CLI's own streaming checkpoint is consumed on success.
        own_checkpoint = _checkpoint_path_for(out_path)
        assert not own_checkpoint.exists()
