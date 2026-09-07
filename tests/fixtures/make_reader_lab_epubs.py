"""Generate the advisory EPUB 2/3 reader-lab fixtures.

The books are deliberately generated through the production EPUB pipeline:

    python tests/fixtures/make_reader_lab_epubs.py

Pass ``--output-dir`` to generate a comparison set elsewhere (the fixture tests
use this to render into ``tmp_path``).
"""

from __future__ import annotations

import argparse
import hashlib
import re
import tempfile
import zipfile
from pathlib import Path

from ebooklib import epub

from halfblood.epub_processor import EpubProcessor
from halfblood.models import AnnotationType
from halfblood.models.annotations import Annotation, MarkIntent, TargetSelector
from halfblood.models.documents import AnnotationPlan, GenerationProvenance, SourceInfo, Unit
from halfblood.models.rendering import DegradationFlag

OUT_DIR = Path(__file__).resolve().parent / "reader_lab"
SEED = 29
FIXED_ZIP_TIME = (1980, 1, 1, 0, 0, 0)
FIXED_MODIFIED = "2026-07-20T00:00:00Z"
LONG_TOKEN = "FLoccinaucinihilipilificationAntidoteBatch_" + "X" * 72

ARTIFACT_NAMES = {
    "epub3": "reader_lab_epub3.epub",
    "epub2": "reader_lab_epub2.epub",
}

CHAPTERS = (
    (
        "Marks and Single Notes",
        """<section epub:type="chapter">
<h1>Marks and Single Notes</h1>
<p>A bezoar can arrest many common poisons before they reach the heart.</p>
<p>The silver knife should slice sopophorous beans into even pieces.</p>
<p>Discard the cracked moonstone before grinding the remaining fragments.</p>
<p>Heat the tincture rapidly until scarlet sparks leap from the cauldron.</p>
<p>Add one drop of hellebore after the surface becomes perfectly still.</p>
<p>Keep the pewter ladle beside the cooling rack for the final transfer.</p>
</section>""",
    ),
    (
        "Three-Note Cluster",
        """<section epub:type="chapter">
<h1>Three-Note Cluster</h1>
<p>Crush the valerian root, fold in the powdered horn, then stir the blue infusion once.</p>
</section>""",
    ),
    (
        "Dense Eight-Note Block",
        f"""<section epub:type="chapter">
<h1>Dense Eight-Note Block</h1>
<div class="source-float" style="float:left; width:25%;">Source float: brass scales must stay dry.</div>
<p>Warm the brass cauldron; measure the salamander blood; sieve the pearl dust; bruise the nettle stems; add the knotgrass sprigs; lower the flame twice; count seven silver bubbles; bottle the violet residue. The batch code is {LONG_TOKEN}.</p>
</section>""",
    ),
    (
        "Cross-Node Target",
        """<section epub:type="chapter">
<h1>Cross-Node Target</h1>
<p>The <em>asphodel</em> root dissolves into <strong>fine powder</strong> at moonrise.</p>
</section>""",
    ),
)


def _annotation(
    annotation_id: str,
    exact: str,
    content: str,
    mark_intent: MarkIntent,
    annotation_type: AnnotationType = AnnotationType.INSIGHT,
) -> Annotation:
    return Annotation(
        id=annotation_id,
        target=TargetSelector(exact=exact),
        annotation_type=annotation_type,
        content=content,
        confidence=0.93,
        requested_placement="margin_right",
        mark_intent=mark_intent,
    )


def _annotations_by_chapter() -> tuple[tuple[Annotation, ...], ...]:
    return (
        (
            _annotation(
                "lab-single-underline",
                "bezoar can arrest many common poisons",
                "Useful, but prevention would be less embarrassing.",
                MarkIntent.UNDERLINE,
                AnnotationType.IMPROVEMENT,
            ),
            _annotation(
                "lab-invention-circle",
                "slice sopophorous beans into even pieces",
                "Invent a press: crushed beans surrender more juice.",
                MarkIntent.CIRCLE,
                AnnotationType.INVENTION,
            ),
            _annotation(
                "lab-strike",
                "Discard the cracked moonstone",
                "Keep it for calibration.",
                MarkIntent.STRIKE,
                AnnotationType.CROSSED_OUT,
            ),
            _annotation(
                "lab-warning-highlight",
                "Heat the tincture rapidly",
                "Never. It becomes violently unstable.",
                MarkIntent.HIGHLIGHT,
                AnnotationType.WARNING,
            ),
            # EPUB has no marks_only outcome: the renderer always places a note.
            # U+2060 satisfies the plan's non-empty content contract but paints no
            # visible note body, giving the reader lab a visual mark-only probe.
            _annotation(
                "lab-mark-only-caret",
                "Add one drop of hellebore",
                "\u2060",
                MarkIntent.CARET,
                AnnotationType.INSIGHT,
            ),
            # The production contract defines NONE as note-only: the target stays
            # unwrapped while its linked note is still emitted.
            _annotation(
                "lab-none-note-only",
                "pewter ladle beside the cooling rack",
                "The glass rod is less reactive.",
                MarkIntent.NONE,
                AnnotationType.SHORTCUT,
            ),
        ),
        (
            _annotation(
                "lab-cluster-1",
                "Crush the valerian root",
                "First in plan order.",
                MarkIntent.UNDERLINE,
            ),
            _annotation(
                "lab-cluster-2",
                "fold in the powdered horn",
                "Second in plan order.",
                MarkIntent.CIRCLE,
            ),
            _annotation(
                "lab-cluster-3",
                "stir the blue infusion once",
                "Third in plan order.",
                MarkIntent.HIGHLIGHT,
            ),
        ),
        tuple(
            _annotation(
                f"lab-dense-{index}",
                exact,
                (
                    f"Dense note {index}: {LONG_TOKEN}"
                    if index == 8
                    else f"Dense note {index}."
                ),
                (
                    MarkIntent.UNDERLINE
                    if index % 2
                    else MarkIntent.CIRCLE
                ),
                AnnotationType.WARNING if index == 8 else AnnotationType.INSIGHT,
            )
            for index, exact in enumerate(
                (
                    "Warm the brass cauldron",
                    "measure the salamander blood",
                    "sieve the pearl dust",
                    "bruise the nettle stems",
                    "add the knotgrass sprigs",
                    "lower the flame twice",
                    "count seven silver bubbles",
                    "bottle the violet residue",
                ),
                1,
            )
        ),
        (
            _annotation(
                "lab-cross-node-caret",
                "asphodel root dissolves into fine powder at moonrise",
                "One selector crossing em and strong nodes.",
                MarkIntent.CARET,
                AnnotationType.INVENTION,
            ),
        ),
    )


def _build_book(*, epub3: bool) -> epub.EpubBook:
    book = epub.EpubBook()
    book.set_identifier(f"halfblood-reader-lab-{'epub3' if epub3 else 'epub2'}")
    book.set_title(f"Half-Blood Prince Reader Lab ({'EPUB 3' if epub3 else 'EPUB 2'})")
    book.set_language("en")
    book.add_author("Half-Blood Prince fixture generator")

    items: list[epub.EpubHtml] = []
    for index, (title, content) in enumerate(CHAPTERS, 1):
        chapter = epub.EpubHtml(
            uid=f"chapter-{index}",
            title=title,
            file_name=f"chapter-{index}.xhtml",
            lang="en",
        )
        chapter.content = content if epub3 else content.replace(' epub:type="chapter"', "")
        book.add_item(chapter)
        items.append(chapter)

    book.toc = items
    book.add_item(epub.EpubNcx())
    if epub3:
        book.add_item(epub.EpubNav())
        book.spine = [("nav", "no"), *items]
    else:
        # EpubProcessor selects its EPUB 2 linked-div branch when the package
        # version read from the OPF does not start with "3". EbookLib writes
        # 3.0 packages only, so _rewrite_archive changes this source OPF to 2.0
        # before render_plan reads it. The source uses the EPUB 2 NCX/spine path
        # and intentionally has no EPUB 3 navigation document.
        book.spine = items
    return book


def _build_plan() -> AnnotationPlan:
    annotations = _annotations_by_chapter()
    return AnnotationPlan(
        id="reader-lab-plan-2026-07-20",
        title="Half-Blood Prince Reader Lab",
        persona="The Half-Blood Prince",
        source=SourceInfo(
            fingerprint=hashlib.sha256(b"reader-lab-source-v1").hexdigest(),
            media_type="application/epub+zip",
            unit_count=len(CHAPTERS),
        ),
        generation=GenerationProvenance(
            provider="fixture",
            model="deterministic-in-code-plan",
            prompt_version="reader-lab-v1",
        ),
        document_seed=SEED,
        units=[
            Unit(
                unit_id=f"reader-lab-chapter-{ordinal}",
                ordinal=ordinal,
                label=title,
                original_text="",
                source_locator=f"chapter-{ordinal}.xhtml",
                annotations=list(chapter_annotations),
            )
            for ordinal, ((title, _), chapter_annotations) in enumerate(
                zip(CHAPTERS, annotations, strict=True),
                1,
            )
        ],
    )


def _rewrite_archive(path: Path, *, package_version: str) -> None:
    """Normalize package metadata and ZIP headers without a temporary file."""
    with zipfile.ZipFile(path) as source:
        entries = [(name, source.read(name)) for name in source.namelist()]

    normalized: list[tuple[str, bytes]] = []
    for name, data in entries:
        if name.endswith(".opf"):
            text = data.decode("utf-8")
            text, count = re.subn(
                r'(<package\b[^>]*\bversion=")[^"]+("[^>]*>)',
                rf"\g<1>{package_version}\g<2>",
                text,
                count=1,
            )
            if count != 1:
                raise RuntimeError(f"could not set package version in {name}")
            text, count = re.subn(
                r'(<meta\s+property="dcterms:modified">)[^<]*(</meta>)',
                rf"\g<1>{FIXED_MODIFIED}\g<2>",
                text,
                count=1,
            )
            if count != 1:
                raise RuntimeError(f"could not normalize modified time in {name}")
            data = text.encode("utf-8")
        normalized.append((name, data))

    by_name = dict(normalized)
    ordered_names = ["mimetype", *(name for name, _ in normalized if name != "mimetype")]
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as target:
        for name in ordered_names:
            info = zipfile.ZipInfo(name, FIXED_ZIP_TIME)
            info.create_system = 0
            info.external_attr = 0
            info.compress_type = (
                zipfile.ZIP_STORED if name == "mimetype" else zipfile.ZIP_DEFLATED
            )
            target.writestr(info, by_name[name], compresslevel=9)


def _generate_artifact(output_path: Path, *, epub3: bool, plan: AnnotationPlan) -> str:
    # Source and output are distinct even for generated fixtures: exercise the
    # same never-overwrite-input rule as a real user's book.
    with tempfile.TemporaryDirectory() as work:
        source = Path(work) / "source.epub"
        epub.write_epub(str(source), _build_book(epub3=epub3))
        if not epub3:
            _rewrite_archive(source, package_version="2.0")
        processor = EpubProcessor(seed=SEED)
        report = processor.render_plan(str(source), plan, str(output_path))
    expected_ids = tuple(
        annotation.id for unit in plan.units for annotation in unit.annotations
    )
    if report.rendered != expected_ids or report.skipped or report.marks_only:
        raise RuntimeError(f"reader-lab plan did not render completely: {report}")
    if DegradationFlag.EPUB_DENSE_NOTES_BLOCK_FALLBACK not in report.degradation_flags:
        raise RuntimeError("dense reader-lab chapter did not select the NL3 fallback")

    # EbookLib always serializes OPF 3.0. Restore 2.0 after rendering the linked-div
    # branch, then normalize every ZIP timestamp/header for byte determinism.
    _rewrite_archive(output_path, package_version="3.0" if epub3 else "2.0")
    digest = hashlib.sha256(output_path.read_bytes()).hexdigest()
    print(f"{output_path.name} sha256 {digest}")
    return digest


def generate(output_dir: Path = OUT_DIR) -> dict[str, str]:
    """Generate both committed reader-lab artifacts and return their SHA-256s."""
    output_dir.mkdir(parents=True, exist_ok=True)
    plan = _build_plan()
    return {
        name: _generate_artifact(
            output_dir / artifact_name,
            epub3=name == "epub3",
            plan=plan,
        )
        for name, artifact_name in ARTIFACT_NAMES.items()
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=OUT_DIR,
        help=f"artifact destination (default: {OUT_DIR})",
    )
    args = parser.parse_args()
    generate(args.output_dir)


if __name__ == "__main__":
    main()
