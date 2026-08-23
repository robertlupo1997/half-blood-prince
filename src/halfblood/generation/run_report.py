"""The ``<output>.report.json`` run sidecar: per-page outcomes as data.

Every ``annotate`` run writes a sidecar next to its artifact so a run with
failed pages still ships the artifact, but never silently. The sidecar
records, per page: success, failure (with the provider error text), or skip
(blank page / boilerplate), plus the renderer's own report when an artifact
was rendered.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from halfblood.generation.report import PageStatusValue
from halfblood.models.rendering import RenderReport

REPORT_VERSION = "1.0"


class PageStatusRecord(BaseModel):
    """Outcome of one page's annotation attempt."""

    model_config = ConfigDict(extra="forbid")

    page_number: int
    status: PageStatusValue
    attempts: int = 0
    error: str = ""


class RunReport(BaseModel):
    """Machine-readable summary of one annotate run, written as a sidecar."""

    model_config = ConfigDict(extra="forbid")

    report_version: str = REPORT_VERSION
    output: str
    pages_total: int
    pages_attempted: int
    pages_annotated: int
    total_annotations: int
    failed_pages: tuple[int, ...] = ()
    skipped_pages: tuple[int, ...] = ()
    page_statuses: tuple[PageStatusRecord, ...] = ()
    render: dict[str, Any] | None = None


def sidecar_path_for(output_file: Path) -> Path:
    """Return the ``<output>.report.json`` path for an artifact path."""
    return Path(str(output_file) + ".report.json")


def build_run_report(
    *,
    output_file: Path,
    plan: Any,
    statuses: Sequence[Any],
    render_report: RenderReport | None = None,
    boilerplate_pages: Sequence[int] = (),
    pages_selected: int | None = None,
) -> RunReport:
    """Build a :class:`RunReport` from a finished (or failed) generation run.

    ``statuses`` are the :class:`PageGenerationStatus` records retained by the
    generator (including the all-pages-failed path, which sets them before
    raising). ``plan`` may be ``None`` when generation produced no plan.
    ``boilerplate_pages`` are page numbers dropped by boilerplate filtering
    before generation; they are recorded as skipped so every selected page is
    accounted for in ``page_statuses``. ``pages_selected`` overrides
    ``pages_total`` with the pre-filter selection size when given.
    """
    page_status_records = [
        PageStatusRecord(
            page_number=status.ordinal,
            status=status.status,
            attempts=status.attempts,
            error=str(status.error) if status.error is not None else "",
        )
        for status in statuses
    ]
    seen = {record.page_number for record in page_status_records}
    for number in boilerplate_pages:
        if number not in seen:
            page_status_records.append(
                PageStatusRecord(
                    page_number=number,
                    status="skipped",
                    attempts=0,
                    error="boilerplate",
                )
            )
    page_status_records.sort(key=lambda record: record.page_number)
    pages = list(plan.pages) if plan is not None else []
    return RunReport(
        output=str(output_file),
        pages_total=(
            pages_selected if pages_selected is not None else len(pages)
        ),
        pages_attempted=sum(
            1 for s in page_status_records if s.status not in ("skipped", "resumed")
        ),
        pages_annotated=sum(1 for page in pages if page.annotations),
        total_annotations=plan.total_annotations if plan is not None else 0,
        failed_pages=tuple(
            s.page_number for s in page_status_records if s.status == "failed"
        ),
        skipped_pages=tuple(
            s.page_number for s in page_status_records if s.status == "skipped"
        ),
        page_statuses=tuple(page_status_records),
        render=render_report.model_dump() if render_report is not None else None,
    )


def write_run_report(report: RunReport, output_file: Path) -> Path:
    """Write the sidecar next to ``output_file`` and return its path."""
    path = sidecar_path_for(output_file)
    path.write_text(
        json.dumps(report.model_dump(mode="json"), indent=2) + "\n",
        encoding="utf-8",
    )
    return path
