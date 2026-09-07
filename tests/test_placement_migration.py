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
