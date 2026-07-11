"""P0-T2 — model validation + enum-compatibility contract.

AUD-15: ``target_text`` (and ``content``) have no ``min_length``; an empty
string validates today, and an empty ``target_text`` reaches
``fitz.search_for("")`` — undefined placement. Blank/whitespace-only semantic
fields must be rejected, and surrounding whitespace on valid values stripped.

L-2: ``AnnotationType`` is deliberately ``str, Enum`` (not ``StrEnum``) with a
documented ``# noqa: UP042`` in models.py, because migrating would change
``str()`` output. These tests pin ``.value``, JSON serialization, and ``str()``
so that choice is explicit and any accidental migration is a loud, deliberate
break rather than a silent behavior change.

No network calls are made anywhere in this file.
"""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from halfblood.models import Annotation, AnnotationType

_BLANKS = ["", " ", "   ", "\n", "\t", "  \n\t "]


def _annotation(**overrides: object) -> Annotation:
    base: dict[str, object] = dict(
        page=1,
        target_text="Sopophorous bean",
        annotation_type=AnnotationType.CORRECTION,
        content="Crush it, don't cut it.",
    )
    base.update(overrides)
    return Annotation(**base)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# AUD-15 — blank semantic fields rejected; surrounding whitespace stripped
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("blank", _BLANKS)
def test_blank_target_text_is_rejected(blank: str) -> None:
    with pytest.raises(ValidationError):
        _annotation(target_text=blank)


@pytest.mark.parametrize("blank", _BLANKS)
def test_blank_content_is_rejected(blank: str) -> None:
    with pytest.raises(ValidationError):
        _annotation(content=blank)


def test_surrounding_whitespace_is_stripped_from_valid_values() -> None:
    ann = _annotation(target_text="  Sopophorous bean  ", content="\t Crush it. \n")
    assert ann.target_text == "Sopophorous bean"
    assert ann.content == "Crush it."


def test_interior_whitespace_is_preserved() -> None:
    # Only *surrounding* whitespace is stripped; newlines/tabs inside a note
    # are meaningful and must survive.
    ann = _annotation(content="line one\nline two\ttabbed")
    assert ann.content == "line one\nline two\ttabbed"


def test_minimal_nonblank_values_still_construct() -> None:
    ann = _annotation(target_text="x", content="y")
    assert ann.target_text == "x"
    assert ann.content == "y"


# ---------------------------------------------------------------------------
# L-2 — AnnotationType string-behavior contract (deliberate str, Enum)
# ---------------------------------------------------------------------------


def test_annotation_type_values_are_stable() -> None:
    assert AnnotationType.CORRECTION.value == "correction"
    assert [t.value for t in AnnotationType] == [
        "correction",
        "improvement",
        "insight",
        "invention",
        "warning",
        "shortcut",
        "crossed_out",
        "doodle_note",
    ]


def test_annotation_type_json_serializes_to_value() -> None:
    ann = _annotation(annotation_type=AnnotationType.WARNING)
    assert json.loads(ann.model_dump_json())["annotation_type"] == "warning"


def test_annotation_type_str_is_member_repr_not_value() -> None:
    # DELIBERATE: as `str, Enum`, str() yields the member repr, not the value.
    # A StrEnum migration would change this to "correction" — this assertion
    # makes that a conscious, breaking change (see the noqa in models.py).
    assert str(AnnotationType.CORRECTION) == "AnnotationType.CORRECTION"
