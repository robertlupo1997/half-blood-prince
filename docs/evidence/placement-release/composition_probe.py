import logging
import tempfile

import fitz

from halfblood.document_processor import DocumentProcessor
from halfblood.models.annotations import Annotation, MarkIntent, TargetSelector
from halfblood.models.documents import AnnotationPlan, GenerationProvenance, SourceInfo, Unit
from halfblood.models.legacy import AnnotationType

work = tempfile.mkdtemp(prefix="hbp-composition-evidence-")
logging.basicConfig(level=logging.WARNING)
source = "examples/src/alice.pdf"
with fitz.open(source) as doc:
    text = doc[5].get_text()
for name, opts in [
    ("caret", dict(mark_intent=MarkIntent.CARET)),
    ("bad-doodle", dict(mark_intent=MarkIntent.NONE, doodle_kind="not-a-doodle")),
]:
    annotation = Annotation(
        id=name,
        target=TargetSelector(exact="Soon her eye fell on a little glass box"),
        annotation_type=AnnotationType.CORRECTION,
        content="Observe this gap.",
        confidence=0.9,
        requested_placement="margin_right",
        **opts,
    )
    plan = AnnotationPlan(
        id=name,
        title="Probe",
        persona="Probe",
        source=SourceInfo(fingerprint="probe", media_type="application/pdf", unit_count=78),
        generation=GenerationProvenance(),
        document_seed=1,
        units=[
            Unit(
                unit_id="6",
                ordinal=6,
                label="6",
                original_text=text,
                source_locator="page:6",
                annotations=[annotation],
            )
        ],
    )
    report = DocumentProcessor().render_plan(source, plan, f"{work}/{name}.pdf")
    print(name, report.model_dump_json())
