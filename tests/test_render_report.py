"""P2-T6 — RenderReport contract (architecture §3.2, §5.9).

The render report is the renderer-neutral record of what happened when a resolved plan is
drawn: which annotations produced ink, which were skipped (and why), anchor/layout warnings,
degradation flags, and output identity hashes. §3.2: *"RenderReport includes rendered/skipped
annotations, anchor/layout warnings, output hashes, and degradation flags. Secrets never
appear."* §5.9: *"Degradation is explicit in RenderReport."*

Contract-only task: nothing here renders; these tests pin the data model's invariants. The
report is distinct from the generation-phase ``GenerationReport`` (which records which pages the
LLM annotated) — this one records the *render* phase.

No network, no provider, no filesystem: pure model construction/validation.
"""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from halfblood.models.documents import UnsupportedSchemaVersionError, canonical_json
from halfblood.models.rendering import (
    AnchorWarning,
    AnchorWarningCode,
    DegradationFlag,
    OutputHash,
    RenderReport,
    SkipReason,
    SkipRecord,
    load_render_report,
)

_HASH_A = "a" * 64


# ---------------------------------------------------------------------------
# empty report is valid — "old current-shape rendering can return/ignore the report"
# ---------------------------------------------------------------------------


def test_empty_report_is_valid_and_means_nothing_rendered() -> None:
    report = RenderReport()
    assert report.rendered == ()
    assert report.skipped == ()
    assert report.warnings == ()
    assert report.degradation_flags == ()
    assert report.output_hashes == ()
    assert report.rendered_count == 0
    assert report.skipped_count == 0
    assert report.attempted_count == 0


# ---------------------------------------------------------------------------
# rendered/skipped partition attempted annotations EXACTLY
# ---------------------------------------------------------------------------


def test_counts_partition_attempted_into_rendered_and_skipped() -> None:
    report = RenderReport(
        rendered=("ann-a", "ann-b"),
        skipped=(SkipRecord(annotation_id="ann-c", reason=SkipReason.MISSING_TARGET),),
    )
    assert report.rendered_count == 2
    assert report.skipped_count == 1
    # attempted = rendered + skipped, and the two are disjoint by construction.
    assert report.attempted_count == 3


def test_same_id_rendered_and_skipped_is_rejected() -> None:
    """An annotation cannot be both drawn and skipped — the partition must be exact."""
    with pytest.raises(ValidationError):
        RenderReport(
            rendered=("ann-a",),
            skipped=(SkipRecord(annotation_id="ann-a", reason=SkipReason.UNPLACEABLE),),
        )


def test_duplicate_rendered_id_is_rejected() -> None:
    with pytest.raises(ValidationError):
        RenderReport(rendered=("ann-a", "ann-a"))


def test_duplicate_skipped_id_is_rejected() -> None:
    with pytest.raises(ValidationError):
        RenderReport(
            skipped=(
                SkipRecord(annotation_id="ann-a", reason=SkipReason.MISSING_TARGET),
                SkipRecord(annotation_id="ann-a", reason=SkipReason.UNPLACEABLE),
            )
        )


# ---------------------------------------------------------------------------
# degradation flags deduplicate STABLY (dupes normalized, not an error)
# ---------------------------------------------------------------------------


def test_degradation_flags_dedupe_preserving_first_seen_order() -> None:
    report = RenderReport(
        degradation_flags=(
            DegradationFlag.GLYPH_FALLBACK,
            DegradationFlag.PROCEDURAL_STROKE_FALLBACK,
            DegradationFlag.GLYPH_FALLBACK,
            DegradationFlag.PROCEDURAL_STROKE_FALLBACK,
        )
    )
    assert report.degradation_flags == (
        DegradationFlag.GLYPH_FALLBACK,
        DegradationFlag.PROCEDURAL_STROKE_FALLBACK,
    )


# ---------------------------------------------------------------------------
# output hashes are validated (64-char lowercase hex)
# ---------------------------------------------------------------------------


def test_valid_output_hash_accepted() -> None:
    oh = OutputHash(role="pdf", sha256=_HASH_A)
    assert oh.sha256 == _HASH_A


@pytest.mark.parametrize(
    "bad",
    [
        "A" * 64,          # uppercase not allowed
        "a" * 63,          # too short
        "a" * 65,          # too long
        "g" * 64,          # non-hex character
        "",                # empty
    ],
)
def test_invalid_output_hash_rejected(bad: str) -> None:
    with pytest.raises(ValidationError):
        OutputHash(role="pdf", sha256=bad)


# ---------------------------------------------------------------------------
# secrets / raw provider payloads cannot be fields (extra="forbid")
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("secret_field", ["api_key", "usage", "authorization", "raw_response"])
def test_provider_or_secret_field_is_forbidden(secret_field: str) -> None:
    with pytest.raises(ValidationError):
        RenderReport(**{secret_field: "leaked"})


def test_skip_and_warning_detail_is_length_bounded() -> None:
    """Free-text detail is bounded so a report cannot smuggle an unbounded payload."""
    with pytest.raises(ValidationError):
        SkipRecord(annotation_id="x", reason=SkipReason.MISSING_TARGET, detail="z" * 5000)
    with pytest.raises(ValidationError):
        AnchorWarning(code=AnchorWarningCode.SHIFTED, detail="z" * 5000)


def test_skip_reason_and_warning_code_are_finite_enums() -> None:
    with pytest.raises(ValidationError):
        SkipRecord(annotation_id="x", reason="not-a-real-reason")
    with pytest.raises(ValidationError):
        AnchorWarning(code="not-a-real-code")


# ---------------------------------------------------------------------------
# deterministic JSON round-trip + unknown MAJOR version rejected
# ---------------------------------------------------------------------------


def _sample_report() -> RenderReport:
    return RenderReport(
        rendered=("ann-a", "ann-b"),
        skipped=(
            SkipRecord(
                annotation_id="ann-c",
                reason=SkipReason.AMBIGUOUS_TARGET,
                detail="two equally scored candidates",
            ),
        ),
        warnings=(
            AnchorWarning(
                annotation_id="ann-a", code=AnchorWarningCode.SIDE_SWITCHED, detail="right full"
            ),
        ),
        degradation_flags=(DegradationFlag.EPUB_NO_TARGET_GEOMETRY,),
        output_hashes=(OutputHash(role="pdf", sha256=_HASH_A),),
    )


def test_canonical_json_is_deterministic() -> None:
    report = _sample_report()
    assert canonical_json(report) == canonical_json(report)


def test_json_round_trip_equals_original() -> None:
    report = _sample_report()
    restored = load_render_report(json.loads(canonical_json(report)))
    assert restored == report


def test_unknown_major_report_version_is_rejected() -> None:
    payload = json.loads(canonical_json(RenderReport()))
    payload["report_version"] = "2.0"
    with pytest.raises(UnsupportedSchemaVersionError):
        load_render_report(payload)


def test_same_major_newer_minor_report_version_is_accepted() -> None:
    payload = json.loads(canonical_json(RenderReport(rendered=("ann-a",))))
    payload["report_version"] = "1.7"
    restored = load_render_report(payload)
    assert restored.rendered == ("ann-a",)


# ---------------------------------------------------------------------------
# marks_only — a mark that rendered even though its note was skipped (MP1d).
# marks_only is a subset of the skipped ids (the disposition is orthogonal to
# the rendered/skipped partition, never overlapping rendered).
# ---------------------------------------------------------------------------


def test_marks_only_subset_of_skipped_is_accepted() -> None:
    report = RenderReport(
        rendered=(),
        skipped=(SkipRecord(annotation_id="ann-a", reason=SkipReason.UNPLACEABLE),),
        marks_only=("ann-a",),
    )
    assert report.marks_only == ("ann-a",)


def test_marks_only_id_not_in_skipped_is_rejected() -> None:
    with pytest.raises(ValidationError):
        RenderReport(
            skipped=(SkipRecord(annotation_id="ann-a", reason=SkipReason.UNPLACEABLE),),
            marks_only=("ann-b",),
        )


def test_duplicate_marks_only_id_is_rejected() -> None:
    with pytest.raises(ValidationError):
        RenderReport(
            skipped=(SkipRecord(annotation_id="ann-a", reason=SkipReason.UNPLACEABLE),),
            marks_only=("ann-a", "ann-a"),
        )
