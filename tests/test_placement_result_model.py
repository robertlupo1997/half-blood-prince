"""Serialized placement records cannot contradict their outcome."""
import pytest
from pydantic import ValidationError

from halfblood.models.placement import PlacementResult


@pytest.mark.parametrize("payload", [
    {"status": "resolved", "renderer": "pdf", "reason": "unique_verified_quote"},
    {"status": "unresolved", "renderer": "pdf", "reason": "quote_not_found", "raw_span": [0, 3]},
    {"status": "ambiguous", "renderer": "epub", "reason": "ambiguous_quote", "candidate_count": 1},
    {"status": "resolved", "renderer": "epub", "reason": "unique_verified_quote",
     "raw_span": [-1, 2], "matched_text": "bad", "candidate_count": 1},
    {"status": "unresolved", "renderer": "epub", "reason": "invented_reason"},
])
def test_reject_contradictory_result(payload):
    with pytest.raises(ValidationError):
        PlacementResult.model_validate(payload)


def test_refusal_round_trip_and_version():
    result = PlacementResult(status="unresolved", renderer="pdf", reason="quote_not_found")
    assert PlacementResult.model_validate_json(result.model_dump_json()) == result
    assert result.schema_version == "1.0"


def test_report_cannot_render_a_refusal():
    from halfblood.models.rendering import PlacementRecord, RenderReport
    record = PlacementRecord(annotation_id="a", source_locator="page:1", result=PlacementResult(
        renderer="pdf", status="unresolved", reason="quote_not_found",
    ))
    with pytest.raises(ValidationError):
        RenderReport(rendered=("a",), placements=(record,))


def test_report_requires_complete_unique_placement_partition_when_present():
    from halfblood.models.rendering import PlacementRecord, RenderReport, SkipReason, SkipRecord
    record = PlacementRecord(annotation_id="a", source_locator="page:1", result=PlacementResult(
        renderer="pdf", status="unresolved", reason="quote_not_found",
    ))
    skip = SkipRecord(annotation_id="a", reason=SkipReason.MISSING_TARGET)
    with pytest.raises(ValidationError):
        RenderReport(skipped=(skip,), placements=(record, record))
    with pytest.raises(ValidationError):
        RenderReport(rendered=("b",), skipped=(skip,), placements=(record,))
