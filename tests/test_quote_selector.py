"""Controller-authored, test-first contract for P2-T2 (re-scoped).

P1-T1 already built ``TargetSelector`` (exact/prefix/suffix/start_offset/end_offset),
the plan-level ``schema_version`` dispatch, and ``extra="forbid"``. P2-T2 adds exactly
two behaviors to that existing selector and pins the surrounding contract:

  * normalized read-time views of the selector's text (``normalized_exact`` /
    ``normalized_prefix`` / ``normalized_suffix``), delegating to the shared
    ``halfblood.documents.matching.normalize`` — a *view*, never stored, never
    serialized, raw values preserved byte-for-byte; and
  * cross-field validation ``start_offset <= end_offset``.

Ground truth: docs/superpowers/specs/2026-07-11-full-project-architecture.md SS5.5, 6.1;
.superpowers/sdd/p2-t2-brief.md. These tests are the frozen interface Codex builds
against -- do not edit them to make an implementation pass.

The four "already delivered by P1-T1" clauses (nonblank exact, extra=forbid,
geometry-free round-trip, exact-only-no-context) are pinned here as coverage and MUST
stay green; the two new-behavior clauses fail against pre-P2-T2 code.

No network calls are made anywhere in this file.
"""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from halfblood.documents.matching import normalize
from halfblood.models.annotations import TargetSelector

_BLANKS = ["", " ", "   ", "\n", "\t", "  \n\t "]
_SELECTOR_FIELDS = {"exact", "prefix", "suffix", "start_offset", "end_offset"}


# ---------------------------------------------------------------------------
# Clause 1 (coverage): a selector requires a nonblank exact quote
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("blank", _BLANKS)
def test_blank_exact_is_rejected(blank: str) -> None:
    with pytest.raises(ValidationError):
        TargetSelector(exact=blank)


def test_exact_surrounding_whitespace_stripped_interior_preserved() -> None:
    sel = TargetSelector(exact="  wormwood  slowly  ")
    # surrounding stripped, interior run preserved verbatim on the raw field
    assert sel.exact == "wormwood  slowly"


# ---------------------------------------------------------------------------
# Clause 2 (coverage): unknown keys fail; no per-selector version field exists.
# Forward compatibility is owned by the plan-level schema_version, not here.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "extra",
    [{"bogus": 1}, {"version": "9"}, {"schema_version": "2.1"}, {"geometry": {}}],
)
def test_unknown_selector_keys_are_rejected(extra: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        TargetSelector(exact="x", **extra)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Clause 3 (coverage): selector serializes without geometry and round-trips,
# preserving raw prefix/suffix byte-for-byte.
# ---------------------------------------------------------------------------


def test_selector_round_trips_without_geometry_and_preserves_raw() -> None:
    raw_prefix = "“Add” the\t"  # curly quotes + trailing tab, intentionally unnormalized
    raw_suffix = "  , stirring—twice"  # leading spaces + em dash
    sel = TargetSelector(
        exact="wormwood slowly",
        prefix=raw_prefix,
        suffix=raw_suffix,
        start_offset=8,
        end_offset=23,
    )
    data = json.loads(sel.model_dump_json())

    geometry = {
        "x", "y", "rect", "bbox", "coordinates", "svg", "rotation", "angle", "quads",
    }
    assert geometry.isdisjoint(data)
    # raw values survive serialization unchanged
    assert data["prefix"] == raw_prefix
    assert data["suffix"] == raw_suffix
    assert TargetSelector.model_validate_json(sel.model_dump_json()) == sel


# ---------------------------------------------------------------------------
# Clause 4 (coverage): an exact-only selector is valid with no invented context.
# ---------------------------------------------------------------------------


def test_exact_only_selector_has_no_invented_context() -> None:
    sel = TargetSelector(exact="wormwood")
    assert sel.prefix is None
    assert sel.suffix is None
    assert sel.start_offset is None
    assert sel.end_offset is None


# ---------------------------------------------------------------------------
# Clause 5 (NEW): normalized read-time views delegate to matching.normalize,
# are None-safe, and never alter or enter the serialized representation.
# ---------------------------------------------------------------------------


def test_normalized_views_delegate_to_shared_normalizer() -> None:
    raw_exact = "wormwood  slowly"
    raw_prefix = "“Add” the\t"
    raw_suffix = "  , stirring—twice"
    sel = TargetSelector(exact=raw_exact, prefix=raw_prefix, suffix=raw_suffix)

    assert sel.normalized_exact == normalize(raw_exact)
    assert sel.normalized_prefix == normalize(raw_prefix)
    assert sel.normalized_suffix == normalize(raw_suffix)
    # the folded form actually differs from raw here (proves it is doing work):
    # raw_exact has a double interior space that normalize() collapses, so a
    # ``return self.exact`` stub would fail this; the curly quotes/tab do the same
    # for the prefix. Explicit inequalities keep these non-vacuous under later edits.
    assert sel.normalized_exact != raw_exact
    assert sel.normalized_prefix != raw_prefix
    assert sel.normalized_prefix == '"Add" the '


def test_normalized_prefix_suffix_are_none_when_absent() -> None:
    sel = TargetSelector(exact="wormwood")
    assert sel.normalized_prefix is None
    assert sel.normalized_suffix is None
    # exact is always present, so its normalized view is always a str
    assert sel.normalized_exact == normalize("wormwood")


def test_normalized_views_do_not_change_stored_or_serialized_values() -> None:
    raw_prefix = "“Add” the\t"
    sel = TargetSelector(exact="wormwood", prefix=raw_prefix)
    # touching the view must not mutate the raw field
    _ = sel.normalized_prefix
    assert sel.prefix == raw_prefix

    data = json.loads(sel.model_dump_json())
    assert data["prefix"] == raw_prefix
    for leaked in ("normalized_exact", "normalized_prefix", "normalized_suffix"):
        assert leaked not in data


# ---------------------------------------------------------------------------
# Clause 6 (NEW): start_offset <= end_offset; ge=0 still enforced.
# ---------------------------------------------------------------------------


def test_offsets_in_order_and_equal_are_valid() -> None:
    assert TargetSelector(exact="x", start_offset=2, end_offset=5).end_offset == 5
    # equal offsets describe a zero-width anchor and are allowed
    assert TargetSelector(exact="x", start_offset=5, end_offset=5).start_offset == 5


def test_start_after_end_is_rejected() -> None:
    with pytest.raises(ValidationError):
        TargetSelector(exact="x", start_offset=6, end_offset=2)


def test_a_single_offset_side_is_allowed() -> None:
    assert TargetSelector(exact="x", start_offset=3).end_offset is None
    assert TargetSelector(exact="x", end_offset=3).start_offset is None


@pytest.mark.parametrize("bad", [-1, -100])
def test_negative_offsets_still_rejected(bad: int) -> None:
    with pytest.raises(ValidationError):
        TargetSelector(exact="x", start_offset=bad)
    with pytest.raises(ValidationError):
        TargetSelector(exact="x", end_offset=bad)


# ---------------------------------------------------------------------------
# Structural guard: the additions must not introduce stored or computed fields.
# This pins that the normalized views are plain properties (never @computed_field),
# so serialization is untouched.
# ---------------------------------------------------------------------------


def test_selector_gains_no_stored_or_computed_fields() -> None:
    assert set(TargetSelector.model_fields) == _SELECTOR_FIELDS
    assert dict(TargetSelector.model_computed_fields) == {}
