"""Atomic save/load for AnnotationPlan v2 + optional GenerationReport."""

from __future__ import annotations

import json
import os
import tempfile
from contextlib import suppress
from pathlib import Path

from halfblood.generation.errors import redact_secrets
from halfblood.generation.report import GenerationReport, PageGenerationStatus
from halfblood.models.documents import AnnotationPlan, load_annotation_plan

# Container format version -- pinned so future migrations stay backward-compatible.
_HBP_VERSION = "1.0"


def _serialize_report(report: GenerationReport) -> dict:
    return {
        "statuses": [
            {
                "unit_id": status.unit_id,
                "ordinal": status.ordinal,
                "status": status.status,
                "attempts": status.attempts,
                "error_type": type(status.error).__name__ if status.error is not None else None,
                "error_message": (
                    redact_secrets(str(status.error)) if status.error is not None else None
                ),
                "warnings": list(status.warnings),
            }
            for status in report.statuses
        ]
    }


def _deserialize_report(data: dict) -> GenerationReport:
    statuses = tuple(
        PageGenerationStatus(
            unit_id=status["unit_id"],
            ordinal=status["ordinal"],
            status=status["status"],
            attempts=status.get("attempts", 0),
            error=None,
            warnings=tuple(status.get("warnings", [])),
        )
        for status in data["statuses"]
    )
    return GenerationReport(statuses=statuses)


def save_plan(
    plan: AnnotationPlan,
    dest: Path | str,
    *,
    report: GenerationReport | None = None,
    force: bool = False,
) -> None:
    """Atomically save a v2 AnnotationPlan (+ optional GenerationReport) to ``dest``.

    Raises:
        FileExistsError: if ``dest`` already exists and ``force`` is False
        OSError: if writing fails (any existing ``dest`` is left byte-for-byte intact)
    """
    dest = Path(dest)
    if dest.exists() and not force:
        raise FileExistsError(f"{dest} already exists; use force=True to overwrite it")

    payload = {
        "_hbp": _HBP_VERSION,
        "plan": json.loads(plan.model_dump_json()),
        "report": _serialize_report(report) if report is not None else None,
    }

    # Write to a temp file in the same directory, then atomically replace.
    tmp_fd, tmp_path = tempfile.mkstemp(dir=dest.parent, suffix=".tmp")
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as file_handle:
            json.dump(payload, file_handle, ensure_ascii=False, sort_keys=True)
        os.replace(tmp_path, dest)
    except Exception:
        with suppress(OSError):
            Path(tmp_path).unlink(missing_ok=True)
        raise


def load_plan(
    path: Path | str,
) -> tuple[AnnotationPlan, GenerationReport | None]:
    """Load a plan from ``path``, migrating v1 to v2 via ``load_annotation_plan``.

    Raises:
        FileNotFoundError: if ``path`` does not exist
        UnsupportedSchemaVersionError: for unknown major schema versions
    """
    path = Path(path)
    data = json.loads(path.read_text(encoding="utf-8"))

    if "_hbp" in data:
        plan_dict = data["plan"]
        report_dict = data.get("report")
    else:
        plan_dict = data
        report_dict = None

    plan = load_annotation_plan(plan_dict)
    report = _deserialize_report(report_dict) if report_dict is not None else None
    return plan, report
