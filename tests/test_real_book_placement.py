"""A real book, not a fixture.

Every EPUB fixture in this repository has a chapter well under the 50,000-character
`MAX_INPUT_CHARS` bound. A real book does not: *The Elements of Style*'s main document is
83,063 characters across 869 inline runs, the largest of which is 1,248 characters.

`resolve_epub_quote` is contracted to resolve "within one reflowable EPUB inline DOM run"
and `docs/placement-contract.md` bounds source text at 50,000 characters counting **all**
descendant text. `EpubProcessor.render_plan` passed a whole chapter, so on a real book every
annotation was refused on the bound before matching was attempted — and the refusal was
reported as `missing_target`, the reason code for a model that quoted loosely.

These tests pin the two properties that failure violated. They use a frozen annotation plan,
so they need no model, no network, and no API key.
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from halfblood.documents.epub import iter_inline_runs
from halfblood.documents.matching import MAX_INPUT_CHARS
from halfblood.models.annotations import TargetSelector
from halfblood.placement import PlacementStatus, resolve_epub_quote

CORPUS = Path(__file__).parent / "corpora" / "real"
BOOK = CORPUS / "elements-of-style.epub"
PLAN = CORPUS / "plan-snape.json"

pytestmark = pytest.mark.skipif(
    not BOOK.exists(), reason="real-book corpus not present"
)


def _documents() -> list[BeautifulSoup]:
    with zipfile.ZipFile(BOOK) as archive:
        return [
            BeautifulSoup(archive.read(name), "lxml")
            for name in archive.namelist()
            if name.endswith((".xhtml", ".html"))
        ]


def _frozen_quotes() -> list[str]:
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    return [
        annotation["target_text"]
        for page in plan["pages"]
        for annotation in (page.get("annotations") or [])
    ]


def test_the_corpus_actually_exceeds_the_bound() -> None:
    """Guard the guard: if this book stops being oversized, these tests prove nothing."""
    totals = [
        sum(len(text) for text in (doc.body or doc).strings) for doc in _documents()
    ]
    assert max(totals) > MAX_INPUT_CHARS, (
        f"largest document is {max(totals):,} chars, which no longer exceeds the "
        f"{MAX_INPUT_CHARS:,} bound — this corpus can no longer reproduce the defect"
    )


def test_no_single_inline_run_is_anywhere_near_the_bound() -> None:
    """The unit that matching operates on is small; only the aggregate is large.

    This is the whole defect: the bound was applied to the sum of every run in a
    chapter rather than to the run a quote is resolved within.
    """
    largest_run = 0
    for doc in _documents():
        for run in iter_inline_runs(doc.body or doc):
            largest_run = max(largest_run, sum(len(node) for node in run))
    assert largest_run < MAX_INPUT_CHARS, (
        f"largest single run is {largest_run:,}"
    )


def test_frozen_quotes_resolve_against_their_own_block() -> None:
    """The engine can place these quotes. Something above it was throwing them away.

    Not every quote is expected to resolve: three of the eight were generated from
    extractor output that injects newlines at inline-tag boundaries, so the model quoted
    a string that is not contiguous document text. That is a separate defect. This test
    pins that a majority resolve, which is what the shipping path returned zero of.
    """
    blocks = [
        block
        for doc in _documents()
        for block in (doc.body or doc).find_all(
            ["p", "li", "h1", "h2", "h3", "h4", "blockquote", "div", "td"]
        )
    ]
    quotes = _frozen_quotes()
    assert quotes, "frozen plan carried no annotations"

    resolved = 0
    for quote in quotes:
        selector = TargetSelector(exact=" ".join(quote.split()))
        if any(
            resolve_epub_quote(block, selector).status is PlacementStatus.RESOLVED
            for block in blocks
        ):
            resolved += 1

    assert resolved >= 5, (
        f"only {resolved}/{len(quotes)} frozen quotes resolved against a block-level "
        "root; the engine could place 5 of 8 when this was measured"
    )


def test_a_chapter_root_refuses_every_quote_on_the_bound() -> None:
    """Characterisation: this is what the shipping path did, and why.

    Kept as a test rather than a comment so that if the caller is ever fixed to pass a
    bounded root, this test fails loudly and tells the next reader the behaviour changed
    deliberately rather than by accident.
    """
    oversized = [
        doc
        for doc in _documents()
        if sum(len(t) for t in (doc.body or doc).strings) > MAX_INPUT_CHARS
    ]
    assert oversized, "no oversized document in the corpus"

    root = oversized[0].body or oversized[0]
    for quote in _frozen_quotes():
        result = resolve_epub_quote(root, TargetSelector(exact=" ".join(quote.split())))
        assert result.status is PlacementStatus.UNRESOLVED
        assert result.reason == "input_limit_exceeded", (
            f"expected the bound to refuse, got {result.reason!r} — if this changed, "
            "the contract in docs/placement-contract.md changed with it"
        )


def test_the_processor_places_notes_on_a_real_book(tmp_path: Path) -> None:
    """End to end: a real book, a frozen plan, and a rendered file that is not empty.

    This is the test the shipping path fails. Running `halfblood annotate` on this book
    reported `Rendered 0 / Skipped 8`, every skip `missing_target`, while the engine could
    place five of the eight. A book with no annotations in it is not the product.

    Threshold set by the owner 2026-09-07: at least 60% of generated annotations placed on
    a real book, with no silent drops. Eight annotations, so at least five.
    """
    from halfblood.epub_processor import EpubProcessor
    from halfblood.models.documents import migrate_v1_to_v2

    plan = migrate_v1_to_v2(json.loads(PLAN.read_text(encoding="utf-8")))
    output = tmp_path / "annotated.epub"

    report = EpubProcessor().render_plan(str(BOOK), plan, str(output))

    total = len(report.rendered) + len(report.skipped)
    assert total, "the frozen plan carried no annotations"

    reasons = sorted({record.reason.value for record in report.skipped})
    assert len(report.rendered) >= 5, (
        f"placed {len(report.rendered)}/{total}; skip reasons were {reasons}. "
        "If every skip is `missing_target`, check whether the caller is handing a whole "
        "chapter to a resolver bounded at 50,000 characters — see "
        "docs/evidence/2026-09-07-real-book-placement-failure.md"
    )


def test_a_bound_refusal_is_never_reported_as_a_missing_target(tmp_path: Path) -> None:
    """The mislabel cost six weeks, so it gets its own test.

    `input_limit_exceeded` means the input was too large to search. `missing_target` means
    the model quoted something that is not in the document. Reporting the first as the
    second sent a diagnosis at the model and kept it there — a handoff in this repository
    records the wrong conclusion it produced.
    """
    from halfblood.epub_processor import EpubProcessor
    from halfblood.models.documents import migrate_v1_to_v2

    plan = migrate_v1_to_v2(json.loads(PLAN.read_text(encoding="utf-8")))
    report = EpubProcessor().render_plan(
        str(BOOK), plan, str(tmp_path / "annotated.epub")
    )

    bound_refusals = [
        record
        for record in report.placements
        if record.result.reason == "input_limit_exceeded"
    ]
    mislabelled = [
        record.annotation_id
        for record in bound_refusals
        if any(
            skip.annotation_id == record.annotation_id
            and skip.reason.value == "missing_target"
            for skip in report.skipped
        )
    ]
    assert not mislabelled, (
        f"{len(mislabelled)} annotation(s) refused on the input bound were reported to the "
        "user as `missing_target`, which names a different cause entirely"
    )


# ---------------------------------------------------------------------------
# G6 — the cost of block-scoped resolution
#
# `_resolve_bounded` falls back from one chapter-scoped search to many
# leaf-block searches. It fails closed, returning `AMBIGUOUS` rather than a
# first hit, so it cannot place a note in the wrong spot. What was never
# measured is the *price* of that safety: a quote that was unique inside one
# large chapter root can match several small blocks, and every such collision
# is a note the reader does not get.
#
# `GATES.md` recorded this as the risk the ledger does not retire. It is no
# longer untested. Measured 2026-09-08 against both frozen plans:
#
#     plan-snape.json   rendered 5/8   skipped 3   all `missing_target`
#     plan-editor.json  rendered 6/8   skipped 2   both `ambiguous_target`
#
# So real books *do* surface collisions the chapter-scoped call never had to
# disambiguate — two of sixteen annotations, 12.5%. The number is a ceiling,
# not a target: these tests fail if ambiguity climbs above what was measured,
# and they fail just as loudly if placement drops, so a future change cannot
# buy a lower ambiguity count by refusing more quotes for some other reason.
# ---------------------------------------------------------------------------

EDITOR_PLAN = CORPUS / "plan-editor.json"

#: Per plan: (rendered floor, ambiguous_target ceiling). Both measured, not chosen.
AMBIGUITY_BASELINE: dict[str, tuple[int, int]] = {
    "plan-snape.json": (5, 0),
    "plan-editor.json": (6, 2),
}


def _render_frozen_plan(plan_path: Path, output: Path):
    from halfblood.epub_processor import EpubProcessor
    from halfblood.models.documents import migrate_v1_to_v2

    plan = migrate_v1_to_v2(json.loads(plan_path.read_text(encoding="utf-8")))
    return EpubProcessor().render_plan(str(BOOK), plan, str(output))


@pytest.mark.skipif(not EDITOR_PLAN.exists(), reason="second frozen plan not present")
@pytest.mark.parametrize("plan_name", sorted(AMBIGUITY_BASELINE))
def test_block_scoped_resolution_does_not_lose_more_notes_to_ambiguity(
    plan_name: str, tmp_path: Path
) -> None:
    """Count `ambiguous_target` skips on a real book, and pin placement with them.

    Two assertions, deliberately. A gate that counted only ambiguity would pass
    vacuously the day every quote starts failing for a different reason.
    """
    rendered_floor, ambiguous_ceiling = AMBIGUITY_BASELINE[plan_name]
    report = _render_frozen_plan(CORPUS / plan_name, tmp_path / "annotated.epub")

    ambiguous = [
        record.annotation_id
        for record in report.skipped
        if record.reason.value == "ambiguous_target"
    ]
    total = len(report.rendered) + len(report.skipped)

    assert len(ambiguous) <= ambiguous_ceiling, (
        f"{plan_name}: {len(ambiguous)} of {total} annotations were refused as "
        f"`ambiguous_target`, above the measured ceiling of {ambiguous_ceiling}. "
        "Block-scoped resolution searches many leaf blocks where there was one "
        "chapter search, so a quote unique in a chapter can collide across blocks. "
        f"Ambiguous ids: {ambiguous}"
    )
    assert len(report.rendered) >= rendered_floor, (
        f"{plan_name}: placed {len(report.rendered)}/{total}, below the measured "
        f"floor of {rendered_floor}. Ambiguity did not rise, so this is a "
        "different regression — read the skip reasons: "
        f"{sorted(record.reason.value for record in report.skipped)}"
    )


@pytest.mark.skipif(not EDITOR_PLAN.exists(), reason="second frozen plan not present")
def test_an_ambiguous_refusal_is_never_reported_as_a_missing_target(
    tmp_path: Path,
) -> None:
    """The G2 mislabel, checked on the other reason code.

    `ambiguous_target` means the quote matched several places and the resolver
    refused rather than guessed. `missing_target` means the quote is not in the
    document at all. Collapsing the first into the second would aim the next
    diagnosis at the model, which is exactly the six-week detour G2 records.
    """
    report = _render_frozen_plan(EDITOR_PLAN, tmp_path / "annotated.epub")

    ambiguous_placements = {
        record.annotation_id
        for record in report.placements
        if record.result.reason == "ambiguous_quote"
    }
    assert ambiguous_placements, (
        "plan-editor.json no longer produces an ambiguous placement, so this test "
        "proves nothing — re-measure the baseline in AMBIGUITY_BASELINE"
    )

    mislabelled = sorted(
        record.annotation_id
        for record in report.skipped
        if record.annotation_id in ambiguous_placements
        and record.reason.value != "ambiguous_target"
    )
    assert not mislabelled, (
        f"{len(mislabelled)} annotation(s) refused as ambiguous were reported to the "
        f"user under a different reason code: {mislabelled}"
    )
