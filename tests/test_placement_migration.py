"""Legacy quotes do not carry occurrence-selection evidence."""

from halfblood.models.documents import migrate_v1_to_v2


def test_migration_does_not_invent_first_occurrence_evidence():
    plan = migrate_v1_to_v2({
        "title": "Own fixture", "prince_persona": "Test",
        "pages": [{"page_number": 1, "original_text": "same quote. same quote.",
                   "annotations": [{"page": 1, "target_text": "same quote",
                                    "content": "Note", "annotation_type": "correction"}]}],
    })
    target = plan.units[0].annotations[0].target
    assert target.prefix is None
    assert target.suffix is None
    assert target.start_offset is None
    assert target.end_offset is None


def test_duplicate_unit_ordinals_cannot_silently_drop_annotations():
    import pytest
    from pydantic import ValidationError
    from test_placement_rendering import make_plan

    from halfblood.models.documents import AnnotationPlan
    payload = make_plan("A quote").model_dump()
    extra = dict(payload["units"][0], unit_id="second")
    extra["annotations"] = [dict(extra["annotations"][0], id="second-annotation")]
    payload["units"].append(extra)
    with pytest.raises(ValidationError):
        AnnotationPlan.model_validate(payload)
