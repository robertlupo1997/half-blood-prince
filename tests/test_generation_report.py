"""Controller-authored tests for ``GenerationReport``/``PageGenerationStatus``
and the evolved ``AllPagesFailedError`` (architecture §4.6; plan P1-T4).

This module is deliberately independent of ``annotation_generator.py`` — P1-T4
does not touch that module, and ``tests/test_failure_handling.py`` pins its
existing, untouched ``AllPagesFailedError`` contract unchanged. The two
``AllPagesFailedError`` classes are distinct siblings until a later phase's
cutover unifies them (see ``halfblood/generation/report.py``'s module
docstring).

No real network calls anywhere in this file.
"""

from __future__ import annotations

from halfblood.generation.errors import ProviderAuthenticationError, ProviderTransientError
from halfblood.generation.report import (
    AllPagesFailedError,
    GenerationReport,
    PageGenerationStatus,
)


def _status(ordinal: int, status: str, **kw: object) -> PageGenerationStatus:
    return PageGenerationStatus(
        unit_id=f"unit-{ordinal}", ordinal=ordinal, status=status, **kw  # type: ignore[arg-type]
    )


# ---------------------------------------------------------------------------
# GenerationReport
# ---------------------------------------------------------------------------


def test_report_has_a_status_for_every_unit() -> None:
    report = GenerationReport(statuses=(_status(1, "success"), _status(2, "failed")))
    assert len(report.statuses) == 2
    assert {s.ordinal for s in report.statuses} == {1, 2}


def test_skipped_blank_units_are_not_failures() -> None:
    report = GenerationReport(statuses=(_status(1, "skipped"), _status(2, "skipped")))
    assert report.failed_pages == []
    assert report.all_attempted_failed is False


def test_partial_failure_report_exposes_compatibility_failed_pages() -> None:
    report = GenerationReport(
        statuses=(_status(1, "failed"), _status(2, "success"), _status(3, "skipped"))
    )
    assert report.failed_pages == [1]
    assert report.all_attempted_failed is False


def test_failed_pages_is_sorted_regardless_of_status_order() -> None:
    report = GenerationReport(
        statuses=(_status(3, "failed"), _status(1, "failed"), _status(2, "success"))
    )
    assert report.failed_pages == [1, 3]


def test_all_attempted_units_failing_requires_at_least_one_attempt() -> None:
    empty = GenerationReport(statuses=())
    assert empty.all_attempted_failed is False

    all_skipped = GenerationReport(statuses=(_status(1, "skipped"), _status(2, "skipped")))
    assert all_skipped.all_attempted_failed is False

    all_failed = GenerationReport(statuses=(_status(1, "failed"), _status(2, "failed")))
    assert all_failed.all_attempted_failed is True


def test_mixed_skipped_and_failed_counts_as_all_attempted_failed() -> None:
    # Skipped units are excluded from "attempted"; if every ATTEMPTED unit
    # failed, this is still an all-failed report even with skips present.
    report = GenerationReport(statuses=(_status(1, "skipped"), _status(2, "failed")))
    assert report.all_attempted_failed is True


def test_valid_empty_annotations_is_success_not_failure() -> None:
    # A page whose provider call succeeded but returned zero annotations is
    # a "success" status — distinct from AnnotationValidationError, which is
    # reserved for a WHOLLY invalid parsed response.
    report = GenerationReport(statuses=(_status(1, "success"),))
    assert report.failed_pages == []
    assert report.all_attempted_failed is False


def test_attempted_excludes_skipped_statuses() -> None:
    report = GenerationReport(
        statuses=(_status(1, "skipped"), _status(2, "success"), _status(3, "failed"))
    )
    assert {s.ordinal for s in report.attempted} == {2, 3}


# ---------------------------------------------------------------------------
# PageGenerationStatus
# ---------------------------------------------------------------------------


def test_page_generation_status_exposes_attempts_and_error() -> None:
    error = ProviderTransientError("upstream 503", status_code=503)
    status = PageGenerationStatus(
        unit_id="unit-1", ordinal=1, status="failed", attempts=3, error=error
    )
    assert status.attempts == 3
    assert status.error is error


def test_page_generation_status_defaults() -> None:
    status = PageGenerationStatus(unit_id="unit-1", ordinal=1, status="success")
    assert status.attempts == 0
    assert status.error is None
    assert status.warnings == ()


def test_page_generation_status_carries_warnings() -> None:
    status = PageGenerationStatus(
        unit_id="unit-1",
        ordinal=1,
        status="success",
        warnings=("structured_output_mode downgraded to json-schema",),
    )
    assert status.warnings == ("structured_output_mode downgraded to json-schema",)


# ---------------------------------------------------------------------------
# AllPagesFailedError (evolved) — carries the report, distinct from the
# legacy annotation_generator.AllPagesFailedError
# ---------------------------------------------------------------------------


def test_all_pages_failed_error_carries_the_report() -> None:
    report = GenerationReport(statuses=(_status(1, "failed"), _status(2, "failed")))
    err = AllPagesFailedError(report)
    assert err.report is report
    assert "2" in str(err)


def test_all_pages_failed_error_accepts_custom_message() -> None:
    report = GenerationReport(statuses=(_status(1, "failed"),))
    err = AllPagesFailedError(report, "custom message")
    assert str(err) == "custom message"


def test_all_pages_failed_error_is_a_runtime_error() -> None:
    report = GenerationReport(statuses=(_status(1, "failed"),))
    assert isinstance(AllPagesFailedError(report), RuntimeError)


def test_generation_report_all_pages_failed_error_is_reconciled_with_legacy() -> None:
    """P1-T4 pinned these two classes as unrelated siblings, with the module
    docstring noting they'd be "unified during a later phase's cutover when
    AnnotationGenerator migrates onto this report." That cutover is P1-T5:
    the legacy class is now a real subclass (not a lookalike copy), so a
    caller catching either type sees the same event and gets a real
    ``.report`` -- while remaining a distinct, more specific type with its
    own message-first constructor contract (see the test directly below)."""
    from halfblood.annotation_generator import AllPagesFailedError as LegacyError

    assert AllPagesFailedError is not LegacyError
    assert not issubclass(AllPagesFailedError, LegacyError)
    assert issubclass(LegacyError, AllPagesFailedError)


def test_legacy_all_pages_failed_error_still_takes_a_plain_message() -> None:
    # Pins that P1-T4 did not touch the legacy class's constructor contract.
    from halfblood.annotation_generator import AllPagesFailedError as LegacyError

    legacy_err = LegacyError("all 3 page(s) sent to the API failed")
    assert str(legacy_err) == "all 3 page(s) sent to the API failed"


# ---------------------------------------------------------------------------
# Redaction end-to-end: a secret embedded in a per-unit error must never
# survive into the report's repr.
# ---------------------------------------------------------------------------


def test_report_repr_never_leaks_a_secret_embedded_in_an_error() -> None:
    error = ProviderAuthenticationError(
        "rejected: Authorization: Bearer sk-ant-fake424242", status_code=401
    )
    report = GenerationReport(statuses=(_status(1, "failed", error=error),))
    assert "sk-ant-fake424242" not in repr(report)
