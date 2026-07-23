"""P-MP1a — measure≡render: the layout measurer must predict the wrapped height
and per-type font the renderer actually draws, so note fit / occupancy can be trusted.

Fails on HEAD:
- `_LayoutMeasurer.measure` returns `fontsize * 1.3` (ONE line) regardless of wrapping
  (`document_processor.py:172`), while `_draw_note_body` wraps and uses the per-type font
  size (`document_processor.py:703-708`). A long note is approved a one-line box and then
  overflows / gets truncated.
- `ResolvedAnnotation` has no `note_scale`, so a layout-reduced scale is lost at render time.

No network calls are made anywhere in this file.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

import halfblood.document_processor as dp
from halfblood.document_processor import _FONT_SIZE_BY_TYPE, DocumentProcessor
from halfblood.layout.anchors import fitz_rect_from_surf
from halfblood.models.annotations import Annotation, MarkIntent, TargetSelector
from halfblood.models.documents import (
    AnnotationPlan,
    GenerationProvenance,
    SourceInfo,
    Unit,
)
from halfblood.models.legacy import AnnotationType
from halfblood.models.rendering import ResolvedAnnotation

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "potions_textbook.pdf"

_LONG = (
    "Crush the sopophorous bean with the flat of the silver dagger; it releases far more "
    "juice than cutting, and the potion thickens to the proper consistency in half the time. "
    "Do not cut it. Never cut it."
)


def test_measurer_height_reflects_wrapping() -> None:
    """A note that wraps to several lines must measure taller than one line."""
    proc = DocumentProcessor()
    measurer = proc._LayoutMeasurer(proc._measure_font)  # type: ignore[attr-defined]
    _, single_h = measurer.measure("Crush it.", 120.0, 1.0)
    _, long_h = measurer.measure(_LONG, 120.0, 1.0)
    assert long_h > single_h * 1.9, (
        f"measurer ignores wrapping: long-note height {long_h:.1f}pt ~= "
        f"single-line height {single_h:.1f}pt at width 120"
    )


def test_resolved_annotation_carries_note_scale() -> None:
    """ResolvedAnnotation must carry the layout-resolved note scale (default 1.0)."""
    resolved = ResolvedAnnotation(
        annotation_id="x",
        source_locator="loc",
        requested_placement="margin_right",
        resolved_placement="margin_right",
        render_seed=0,
    )
    assert getattr(resolved, "note_scale", None) == 1.0


def test_long_note_box_fits_wrapped_render(tmp_path: Path) -> None:
    """A placed long note must get a box tall enough for its wrapped rendered text.

    On HEAD the note is placed with a one-line box that the multi-line render overflows.
    After the fix the box either fits the wrapped text or the note is skipped (faithful).
    """
    ann = Annotation(
        id="ln",
        target=TargetSelector(
            exact="Sopophorous bean",
            prefix="Cut the ",
            suffix=" with a silver knife",
        ),
        annotation_type=AnnotationType.CORRECTION,
        content=_LONG,
        confidence=0.9,
        requested_placement="margin_right",
        mark_intent=MarkIntent.UNDERLINE,
    )
    unit = Unit(
        unit_id=str(uuid.uuid4()),
        ordinal=2,
        label="Page 2",
        original_text="",
        source_locator="page:2",
        annotations=[ann],
    )
    plan = AnnotationPlan(
        id=str(uuid.uuid4()),
        title="measure-render",
        persona="x",
        source=SourceInfo(fingerprint="abcd" * 16, media_type="application/pdf", unit_count=1),
        generation=GenerationProvenance(),
        document_seed=1,
        units=[unit],
    )

    captured: dict[str, ResolvedAnnotation] = {}
    real = dp.layout_page_annotations

    def spy(page, requests, occupancy, measurer, config=None, body_columns=()):  # type: ignore[no-untyped-def]
        result = real(page, requests, occupancy, measurer, config, body_columns=body_columns)
        for placed in result.placed:
            captured[placed.annotation_id] = placed
        return result

    dp.layout_page_annotations = spy
    try:
        DocumentProcessor().render_plan(str(FIXTURE), plan, str(tmp_path / "out.pdf"))
    finally:
        dp.layout_page_annotations = real

    if "ln" not in captured:
        pytest.skip("long note was skipped as unplaceable; overflow contract not applicable")

    resolved = captured["ln"]
    assert resolved.note_box is not None
    box = fitz_rect_from_surf(resolved.note_box)
    scale = getattr(resolved, "note_scale", 1.0)
    font_size = _FONT_SIZE_BY_TYPE.get(ann.annotation_type, 9.0) * scale
    proc = DocumentProcessor()
    lines = proc._wrap_text(_LONG, max(1.0, box.width), font_size)  # type: ignore[attr-defined]
    needed_height = len(lines) * font_size * 1.3
    assert box.height + 1e-6 >= needed_height, (
        f"note_box height {box.height:.1f}pt is too short for {len(lines)} wrapped lines "
        f"needing {needed_height:.1f}pt — layout measured fewer lines than render draws"
    )
