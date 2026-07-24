"""P3-S2a — layout/page_solver.py: quantizers, segments_cross, score_assignment, solve.

These tests are RED at authoring time: ``halfblood.layout.page_solver`` does not exist yet.
All will fail with ``ModuleNotFoundError`` until Codex implements the module.  This is
expected and correct — the "confirm they fail" step for P3-S2a is waived only for the
failure MODE (import error), not for logic failures: once the module exists every test must
pass byte-identically.

Contract reference: .superpowers/sdd/p3s2a-page-solver-brief.md
Design of record:   docs/superpowers/specs/2026-07-21-phase3-page-solver-design.md

Quantizer pinning note:
  q_pt/q_conf use half-even rounding.  For the specific tie-values the team-lead listed
  (.0005/.0015/.0025), float multiplication is exact (0.0015*1000 == 1.5 in IEEE 754) so
  round() and Decimal-HALF_EVEN agree.  For q_scale(0.00015), float gives 1.4999... so
  float-round disagrees with Decimal-HALF_EVEN; that specific case is intentionally omitted
  to avoid encoding a float-precision artifact.

Soft-cost note (test_soft_* below):
  soft_geometry_cost formula assumed to be Σ_placed(soft_i * importance_i) — plain
  importance-weighted sum, no ratio() at the final reduction step.  Sub-terms (scale,
  connector_length, etc.) use ratio() internally for integer arithmetic.  Exact integers
  are pinned for scale and connector_length; all other terms use relative-ordering assertions
  because their normalization formulas are not fully pinned in the design doc.
  test_importance_scales_soft_geometry_cost verifies the sum vs mean distinction:
  if soft_geometry_cost is a mean, that test will fail (soft2 != 2*soft1).
  Commit 65c3752 / authoring date 2026-07-21.
"""

from __future__ import annotations

import os
import subprocess
import sys

import pytest

from halfblood.layout.page_solver import (
    Candidate,
    SolverConfig,
    SolverResult,  # noqa: F401 — imported for type smoke-test
    q_conf,
    q_pt,
    q_scale,
    ratio,
    score_assignment,
    segments_cross,
    solve,
)

# ---------------------------------------------------------------------------
# Shared config / factories
# ---------------------------------------------------------------------------

# Standard 612×792 page (points).
# page_diag_mpt = round(sqrt(612^2 + 792^2) * 1000) = round(1000.9035... * 1000) = 1000904
_CFG = SolverConfig(
    beam_width=128,
    min_scale_bp=7000,       # 0.7 scale minimum
    page_diag_mpt=1000904,
    page_height_mpt=792000,
)


def _cand(
    note_id: str,
    ordinal: int,
    *,
    kind: str = "margin",
    box_mpt: tuple[int, int, int, int] | None = (500_000, 200_000, 570_000, 214_000),
    scale_bp: int = 10000,
    side: str = "right",
    importance: int = 1000,
    displacement_bp: int = 0,
    side_switched: bool = False,
    connector_a_mpt: tuple[int, int] | None = None,
    connector_b_mpt: tuple[int, int] | None = None,
    height_mpt: int = 14000,
    connector_body_span_bp: int = 0,
) -> Candidate:
    return Candidate(
        note_id=note_id,
        ordinal=ordinal,
        kind=kind,
        box_mpt=box_mpt,
        scale_bp=scale_bp,
        side=side,
        importance=importance,
        displacement_bp=displacement_bp,
        side_switched=side_switched,
        connector_a_mpt=connector_a_mpt,
        connector_b_mpt=connector_b_mpt,
        height_mpt=height_mpt,
        connector_body_span_bp=connector_body_span_bp,
    )


def _skip(note_id: str, ordinal: int = 99, importance: int = 1000) -> Candidate:
    return Candidate(
        note_id=note_id,
        ordinal=ordinal,
        kind="skip",
        box_mpt=None,
        scale_bp=10000,
        side="",
        importance=importance,
        displacement_bp=0,
        side_switched=False,
        connector_a_mpt=None,
        connector_b_mpt=None,
        height_mpt=0,
    )


def _no_conflict(a: Candidate, b: Candidate) -> bool:
    return False


def _box_conflict(a: Candidate, b: Candidate) -> bool:
    """Overlap on box_mpt rectangles (axis-aligned; interior intersection only)."""
    if a.box_mpt is None or b.box_mpt is None:
        return False
    ax0, ay0, ax1, ay1 = a.box_mpt
    bx0, by0, bx1, by1 = b.box_mpt
    return ax0 < bx1 and bx0 < ax1 and ay0 < by1 and by0 < ay1


# ---------------------------------------------------------------------------
# 1. Quantizers
# ---------------------------------------------------------------------------

class TestQPt:
    """q_pt(x) — half-even to 0.001 pt, result in integer millipoints."""

    def test_zero(self) -> None:
        assert q_pt(0.0) == 0

    def test_one_point(self) -> None:
        assert q_pt(1.0) == 1000

    def test_large(self) -> None:
        assert q_pt(612.0) == 612000

    def test_rounds_down(self) -> None:
        # 1.0004 pt → 1000.4 mpt → rounds to 1000
        assert q_pt(1.0004) == 1000

    def test_rounds_up(self) -> None:
        # 1.0006 pt → 1000.6 mpt → rounds to 1001
        assert q_pt(1.0006) == 1001

    def test_half_even_0005(self) -> None:
        # 0.0005 * 1000 == 0.5 exactly in IEEE 754; half-even → 0 (0 is even)
        assert q_pt(0.0005) == 0

    def test_half_even_0015(self) -> None:
        # 0.0015 * 1000 == 1.5 exactly in IEEE 754; half-even → 2 (2 is even)
        assert q_pt(0.0015) == 2

    def test_half_even_0025(self) -> None:
        # 0.0025 * 1000 == 2.5 exactly in IEEE 754; half-even → 2 (2 is even)
        assert q_pt(0.0025) == 2


class TestQScale:
    """q_scale(x) — half-even to 1/10 000, result in integer basis points."""

    def test_zero(self) -> None:
        assert q_scale(0.0) == 0

    def test_one(self) -> None:
        assert q_scale(1.0) == 10000

    def test_standard_values(self) -> None:
        assert q_scale(0.7) == 7000
        assert q_scale(0.8) == 8000
        assert q_scale(0.9) == 9000

    def test_half_even_00005(self) -> None:
        # 5e-5 * 10000 == 0.5 exactly in IEEE 754; half-even → 0
        assert q_scale(5e-5) == 0

    def test_half_even_00025(self) -> None:
        # 0.00025 * 10000 == 2.5 exactly in IEEE 754; half-even → 2
        assert q_scale(0.00025) == 2

    # NOTE: q_scale(0.00015) is intentionally omitted — 0.00015 * 10000 is 1.4999... in
    # float (not exactly 1.5), so float-round gives 1 while Decimal-HALF_EVEN gives 2.
    # Pinning either value would encode a float-precision assumption; we skip it.


class TestQConf:
    """q_conf(x) — half-even to 1/1 000, result in integer milli-confidence."""

    def test_zero(self) -> None:
        assert q_conf(0.0) == 0

    def test_one(self) -> None:
        assert q_conf(1.0) == 1000

    def test_standard(self) -> None:
        assert q_conf(0.9) == 900

    def test_half_even_0005(self) -> None:
        # 0.0005 * 1000 == 0.5 exactly; half-even → 0
        assert q_conf(0.0005) == 0

    def test_half_even_0015(self) -> None:
        # 0.0015 * 1000 == 1.5 exactly; half-even → 2
        assert q_conf(0.0015) == 2

    def test_half_even_0025(self) -> None:
        # 0.0025 * 1000 == 2.5 exactly; half-even → 2
        assert q_conf(0.0025) == 2


class TestRatio:
    """ratio(a, b) = (10_000 * a + b // 2) // b — pure integer, no floats."""

    def test_zero_numerator(self) -> None:
        # ratio(0, 1) = (0 + 0) // 1 = 0
        assert ratio(0, 1) == 0

    def test_equal(self) -> None:
        # ratio(a, a) → 10000 for any a > 0
        # ratio(1, 1) = (10000 + 0) // 1 = 10000
        assert ratio(1, 1) == 10000
        assert ratio(5, 5) == 10000

    def test_half(self) -> None:
        # ratio(1, 2) = (10000 + 1) // 2 = 10001 // 2 = 5000
        assert ratio(1, 2) == 5000

    def test_quarter(self) -> None:
        # ratio(1, 4) = (10000 + 2) // 4 = 10002 // 4 = 2500
        assert ratio(1, 4) == 2500

    def test_three_quarters(self) -> None:
        # ratio(3, 4) = (30000 + 2) // 4 = 30002 // 4 = 7500
        assert ratio(3, 4) == 7500

    def test_two_thirds(self) -> None:
        # ratio(2, 3) = (20000 + 1) // 3 = 20001 // 3 = 6667
        assert ratio(2, 3) == 6667

    def test_one_third(self) -> None:
        # ratio(1, 3) = (10000 + 1) // 3 = 10001 // 3 = 3333
        assert ratio(1, 3) == 3333

    def test_scale_term_08_min_07(self) -> None:
        # The scale term for scale=0.8, min_scale=0.7 is computed as:
        # ratio((10000 - 8000)^2, (10000 - 7000)^2) = ratio(2000^2, 3000^2)
        #   = ratio(4_000_000, 9_000_000)
        #   = (10000*4_000_000 + 4_500_000) // 9_000_000
        #   = 40_004_500_000 // 9_000_000
        #   = 4444
        assert ratio(4_000_000, 9_000_000) == 4444


# ---------------------------------------------------------------------------
# 2. segments_cross — proper interior intersection only
# ---------------------------------------------------------------------------

class TestSegmentsCross:
    """Pure-integer segment-crossing test (proper crossing only; no shared endpoints,
    no collinear overlap, no T-touch)."""

    def test_proper_crossing_x_shape(self) -> None:
        # (0,0)→(10,10) crosses (0,10)→(10,0) at (5,5) — proper interior crossing
        assert segments_cross((0, 0), (10, 10), (0, 10), (10, 0)) is True

    def test_clearly_disjoint(self) -> None:
        # Two horizontal segments at different y levels — clearly no crossing
        assert segments_cross((0, 0), (10, 0), (0, 5), (10, 5)) is False

    def test_shared_endpoint_not_crossing(self) -> None:
        # Segments share endpoint (10, 10) — no proper interior crossing
        assert segments_cross((0, 0), (10, 10), (10, 10), (20, 0)) is False

    def test_collinear_overlap_not_crossing(self) -> None:
        # Both segments on the x-axis, overlapping in [5,10] — collinear, not crossing
        assert segments_cross((0, 0), (10, 0), (5, 0), (20, 0)) is False

    def test_t_touch_not_crossing(self) -> None:
        # Segment B's endpoint (5,0) lands on interior of segment A — T-intersection.
        # DISCRIMINATING: naive "on-segment" implementations erroneously return True.
        assert segments_cross((0, 0), (10, 0), (5, 0), (5, 5)) is False

    def test_vertical_and_horizontal_crossing(self) -> None:
        # Vertical (5,0)→(5,10) and horizontal (0,5)→(10,5) cross at (5,5)
        assert segments_cross((5, 0), (5, 10), (0, 5), (10, 5)) is True

    def test_connector_proxy_crossing(self) -> None:
        # Typical margin-connector pair that crosses — realistic millipoint coords:
        # note1 connector: (510000,200000) → (200000,250000)
        # note2 connector: (510000,300000) → (200000,210000)
        assert segments_cross(
            (510_000, 200_000), (200_000, 250_000),
            (510_000, 300_000), (200_000, 210_000),
        ) is True

    def test_connector_proxy_no_crossing(self) -> None:
        # Connectors run parallel (both horizontal at different y)
        assert segments_cross(
            (510_000, 200_000), (200_000, 200_000),
            (510_000, 300_000), (200_000, 300_000),
        ) is False

    def test_zero_length_segment_no_crossing(self) -> None:
        # Degenerate zero-length segment cannot properly cross anything
        assert segments_cross((5, 5), (5, 5), (0, 0), (10, 10)) is False

    def test_both_degenerate_no_crossing(self) -> None:
        assert segments_cross((5, 5), (5, 5), (5, 5), (5, 5)) is False


# ---------------------------------------------------------------------------
# 3. score_assignment — unit tests
# ---------------------------------------------------------------------------
#
# Soft-cost formula (confirmed): soft_geometry_cost = Σ_placed(soft_i * importance_i)
# where each soft_i = 1000*scale_term + 50*conn_len_term + 500*cross_term
#                    + 100*disp_term + 150*sw_term + 25*lane_term.
# Each sub-term is in 0..10_000 bp.  ratio() is used inside sub-term computation.
# No ratio() at the final cross-note reduction.
#
# Importance formula (from design doc):
#   importance_i = (8 − ANNOTATION_TYPE_PRIORITY[type_i]) * 1001 + confidence_milli_i
# We pass importance directly in Candidate, so tests don't depend on annotation types.

class TestScoreAssignment:
    # (a) All-placed, zero soft baseline ----------------------------------

    def test_zero_soft_single_placed(self) -> None:
        # scale=1.0, no connectors, no displacement, no side-switch, single note →
        # every soft sub-term is 0 → soft_geometry_cost = 0.
        c = _cand("n1", ordinal=0, scale_bp=10000, importance=1,
                  connector_a_mpt=None, connector_b_mpt=None,
                  displacement_bp=0, side_switched=False)
        count, omit_imp, soft, key = score_assignment((c,), _CFG)
        assert count == 0
        assert omit_imp == 0
        assert soft == 0
        assert key == (0,)

    def test_zero_soft_two_placed(self) -> None:
        # One note on each side so lane unevenness = 0; scale=1.0, no connectors.
        # Every soft sub-term is 0 → soft_geometry_cost = 0.
        c1 = _cand("n1", ordinal=0, scale_bp=10000, importance=1,
                   side="right", connector_a_mpt=None, connector_b_mpt=None)
        c2 = _cand("n2", ordinal=1, scale_bp=10000, importance=1,
                   side="left",  connector_a_mpt=None, connector_b_mpt=None)
        count, omit_imp, soft, key = score_assignment((c1, c2), _CFG)
        assert count == 0
        assert omit_imp == 0
        assert soft == 0
        assert key == (0, 1)

    def test_skip_candidate_increments_omitted(self) -> None:
        sk = _skip("n1", ordinal=99, importance=5000)
        count, omit_imp, soft, key = score_assignment((sk,), _CFG)
        assert count == 1
        assert omit_imp == 5000
        assert soft == 0       # skips carry no soft cost
        assert key == (99,)

    # (b) One skip → omitted_count=1 dominates any soft cost ---------------

    def test_one_skip_dominates_heavy_soft_cost(self) -> None:
        # Assignment A: one skip + one heavy-soft placed
        # Assignment B: both placed (even at max soft penalty)
        # A must rank strictly worse due to omitted_count=1.
        skip_n1   = _skip("n1", ordinal=99, importance=1)
        heavy_n2  = _cand("n2", ordinal=0, scale_bp=7000, importance=1,
                          displacement_bp=10000, side_switched=True)
        score_A = score_assignment((skip_n1, heavy_n2), _CFG)

        placed_n1 = _cand("n1", ordinal=0, scale_bp=7000, importance=1)
        score_B = score_assignment((placed_n1, heavy_n2), _CFG)

        assert score_A > score_B, (
            "omitted_count=1 must rank worse than omitted_count=0 regardless of soft cost"
        )
        assert score_A[0] == 1  # omitted_count
        assert score_B[0] == 0

    # (c) Two same-omission assignments ranked by omitted_importance --------

    def test_omitted_importance_ordering(self) -> None:
        # Both assignments skip note n1, but with different importance.
        # The assignment with lower skip importance must rank better.
        low_skip  = _skip("n1", ordinal=99, importance=100)
        high_skip = _skip("n1", ordinal=99, importance=9000)
        placed_n2 = _cand("n2", ordinal=0, scale_bp=10000, importance=1,
                          connector_a_mpt=None, connector_b_mpt=None)

        score_low  = score_assignment((low_skip,  placed_n2), _CFG)
        score_high = score_assignment((high_skip, placed_n2), _CFG)

        assert score_low[0] == score_high[0] == 1, "both skip exactly one note"
        assert score_low[1] < score_high[1], "lower omit-importance must have lower omit_importance field"
        assert score_low < score_high, "assignment with lower omit importance must rank better"

    # (d) Soft terms isolated — exact weight arithmetic --------------------
    #
    # importance=1 is used throughout to keep arithmetic simple and to avoid the
    # sum-vs-mean ambiguity for multi-note assignments (single note, importance=1 →
    # soft_geometry_cost = soft_i directly for both formulas, except the ratio
    # version would give 10000*soft_i — confirmed NOT the case per team-lead).

    def test_soft_scale_term_exact(self) -> None:
        # scale=1.0 (scale_bp=10000): (1-1.0)/(1-0.7)=0 → scale_term=0 → soft=0
        # scale=0.8 (scale_bp=8000): (1-0.8)/(1-0.7) = 2000/3000
        #   scale_term = ratio(2000^2, 3000^2) = ratio(4_000_000, 9_000_000)
        #              = (40_000_000_000 + 4_500_000) // 9_000_000
        #              = 40_004_500_000 // 9_000_000
        #              = 4444
        #   soft_scale = 1000 * 4444 = 4_444_000
        #   soft_geometry_cost (importance=1) = 4_444_000
        c_10 = _cand("n1", ordinal=0, scale_bp=10000, importance=1,
                     connector_a_mpt=None, connector_b_mpt=None,
                     displacement_bp=0, side_switched=False)
        c_08 = _cand("n1", ordinal=0, scale_bp=8000, importance=1,
                     connector_a_mpt=None, connector_b_mpt=None,
                     displacement_bp=0, side_switched=False)
        _, _, soft_10, _ = score_assignment((c_10,), _CFG)
        _, _, soft_08, _ = score_assignment((c_08,), _CFG)
        assert soft_10 == 0, "scale=1.0 → scale_term=0 → soft=0"
        assert soft_08 == 4_444_000, (
            "scale=0.8, min=0.7: "
            "scale_term = ratio(4_000_000, 9_000_000) = 4444; "
            "soft = 1000 * 4444 * importance(1) = 4_444_000"
        )

    def test_soft_connector_length_exact(self) -> None:
        # Connector (0,0) → (3000,4000) millipoints — 3-4-5 right triangle.
        # dist = isqrt(3000^2 + 4000^2) = isqrt(25_000_000) = 5000 (exact).
        # conn_len_term = ratio(5000, page_diag_mpt=1_000_904)
        #   = (10000 * 5000 + 500_452) // 1_000_904
        #   = 50_500_452 // 1_000_904
        #   = 50
        # soft_conn = 50 * 50 = 2_500
        # soft_geometry_cost (importance=1, scale=1.0, all others 0) = 2_500
        c_no_conn = _cand("n1", ordinal=0, scale_bp=10000, importance=1,
                          connector_a_mpt=None, connector_b_mpt=None)
        c_conn = _cand("n1", ordinal=0, scale_bp=10000, importance=1,
                       connector_a_mpt=(0, 0), connector_b_mpt=(3000, 4000))
        _, _, soft_none, _ = score_assignment((c_no_conn,), _CFG)
        _, _, soft_conn, _ = score_assignment((c_conn,), _CFG)
        assert soft_none == 0, "no connector → conn_len_term=0 → soft=0"
        assert soft_conn == 2_500, (
            "connector (0,0)→(3000,4000): dist=5000 mpt, "
            "conn_term = ratio(5000, 1_000_904) = 50, "
            "soft = 50 * 50 * importance(1) = 2_500"
        )

    def test_soft_crossings_ordering(self) -> None:
        # Two non-crossing connectors vs two crossing connectors.
        # Crossings must strictly increase soft_geometry_cost.
        # (Exact crossing-term normalization is underspecified in design doc;
        # relative ordering is the correct test here.)
        c1_nc = _cand("n1", ordinal=0, scale_bp=10000, importance=1,
                      connector_a_mpt=(510_000, 200_000),
                      connector_b_mpt=(200_000, 200_000))
        c2_nc = _cand("n2", ordinal=0, scale_bp=10000, importance=1,
                      connector_a_mpt=(510_000, 300_000),
                      connector_b_mpt=(200_000, 300_000))
        c1_cr = _cand("n1", ordinal=0, scale_bp=10000, importance=1,
                      connector_a_mpt=(510_000, 200_000),
                      connector_b_mpt=(200_000, 250_000))
        c2_cr = _cand("n2", ordinal=0, scale_bp=10000, importance=1,
                      connector_a_mpt=(510_000, 300_000),
                      connector_b_mpt=(200_000, 210_000))

        _, _, soft_no_cross, _ = score_assignment((c1_nc, c2_nc), _CFG)
        _, _, soft_cross,    _ = score_assignment((c1_cr, c2_cr), _CFG)
        assert soft_no_cross < soft_cross, (
            "crossing connectors must cost more than non-crossing connectors"
        )

    def test_soft_displacement_ordering(self) -> None:
        # Larger displacement_bp → strictly higher soft cost.
        c_no_disp = _cand("n1", ordinal=0, importance=1, displacement_bp=0)
        c_disp    = _cand("n1", ordinal=0, importance=1, displacement_bp=5000)
        _, _, soft_zero, _ = score_assignment((c_no_disp,), _CFG)
        _, _, soft_disp, _ = score_assignment((c_disp,),    _CFG)
        assert soft_zero < soft_disp, "nonzero displacement must increase soft cost"

    def test_soft_side_switch_ordering(self) -> None:
        # side_switched=True must strictly increase soft cost vs side_switched=False.
        c_no_sw = _cand("n1", ordinal=0, importance=1, side_switched=False)
        c_sw    = _cand("n1", ordinal=0, importance=1, side_switched=True)
        _, _, soft_no, _  = score_assignment((c_no_sw,), _CFG)
        _, _, soft_yes, _ = score_assignment((c_sw,),    _CFG)
        assert soft_no < soft_yes, "side_switched=True must increase soft cost"

    def test_soft_lane_unevenness_ordering(self) -> None:
        # Two notes both on right (imbalanced) vs one on each side (balanced).
        # Balanced assignment must rank better on soft cost.
        # (Exact lane formula is underspecified; relative ordering tested.)
        c1r  = _cand("n1", ordinal=0, importance=1, side="right", height_mpt=14000)
        c2r  = _cand("n2", ordinal=1, importance=1, side="right", height_mpt=14000)
        c1r2 = _cand("n1", ordinal=0, importance=1, side="right", height_mpt=14000)
        c2l  = _cand("n2", ordinal=1, importance=1, side="left",  height_mpt=14000)
        _, _, soft_imbalanced, _ = score_assignment((c1r,  c2r), _CFG)
        _, _, soft_balanced,   _ = score_assignment((c1r2, c2l), _CFG)
        assert soft_balanced < soft_imbalanced, (
            "balanced lane distribution must rank better than all-same-side"
        )

    def test_assignment_key_is_ordinal_tuple_in_note_order(self) -> None:
        c0 = _cand("n1", ordinal=0,  importance=1)
        c5 = _cand("n2", ordinal=5,  importance=1)
        _, _, _, key = score_assignment((c0, c5), _CFG)
        assert key == (0, 5)

    def test_score_tuple_is_four_element(self) -> None:
        c = _cand("n1", ordinal=0, importance=1)
        score = score_assignment((c,), _CFG)
        assert len(score) == 4

    def test_importance_scales_soft_geometry_cost(self) -> None:
        # With scale=0.8 and importance=2 vs importance=1, soft_geometry_cost doubles.
        # This also confirms it is a SUM (weighted), not a mean (which would be equal).
        c1 = _cand("n1", ordinal=0, scale_bp=8000, importance=1,
                   connector_a_mpt=None, connector_b_mpt=None,
                   displacement_bp=0, side_switched=False)
        c2 = _cand("n1", ordinal=0, scale_bp=8000, importance=2,
                   connector_a_mpt=None, connector_b_mpt=None,
                   displacement_bp=0, side_switched=False)
        _, _, soft1, _ = score_assignment((c1,), _CFG)
        _, _, soft2, _ = score_assignment((c2,), _CFG)
        assert soft2 == 2 * soft1, (
            "soft_geometry_cost must scale linearly with importance "
            "(confirms sum formula, not mean)"
        )


# ---------------------------------------------------------------------------
# 4. solve — behavioral tests
# ---------------------------------------------------------------------------

_GREEDY_TRAP_A_BEST   = _cand("A", ordinal=0, box_mpt=(0, 100_000, 100_000, 200_000))
_GREEDY_TRAP_A_SECOND = _cand("A", ordinal=1, box_mpt=(0, 300_000, 100_000, 400_000))
_GREEDY_TRAP_A_SKIP   = _skip("A", ordinal=99)
_GREEDY_TRAP_B_ONLY   = _cand("B", ordinal=0, box_mpt=(0, 150_000, 100_000, 250_000))
_GREEDY_TRAP_B_SKIP   = _skip("B", ordinal=99)

# A_best conflicts with B_only: y-range (100..200k) vs (150..250k) → overlap at 150..200k.
# A_second (y 300..400k) does NOT conflict with B_only (y 150..250k): max(300k,150k)=300k > min(400k,250k)=250k → no overlap.


class TestSolve:
    # (a) Single note picks lowest-ordinal feasible -------------------------

    def test_single_note_picks_lowest_ordinal(self) -> None:
        cands = [
            _cand("n1", ordinal=0, scale_bp=10000),
            _cand("n1", ordinal=1, scale_bp=9000),
            _skip("n1", ordinal=99),
        ]
        result = solve([cands], _CFG, _no_conflict)
        assert len(result.chosen) == 1
        assert result.chosen[0].ordinal == 0
        assert result.chosen[0].kind == "margin"

    def test_single_note_inline_beats_margin(self) -> None:
        # inline has ordinal=0, margin has ordinal=1 → inline must be chosen.
        cands = [
            _cand("n1", ordinal=0, kind="inline",
                  box_mpt=(100_000, 200_000, 300_000, 220_000), side=""),
            _cand("n1", ordinal=1, kind="margin",
                  box_mpt=(510_000, 200_000, 570_000, 214_000), side="right"),
            _skip("n1", ordinal=99),
        ]
        result = solve([cands], _CFG, _no_conflict)
        assert result.chosen[0].kind == "inline"
        assert result.chosen[0].ordinal == 0

    # (b) Conflict forces second-best global (greedy-trap) ------------------

    def test_greedy_trap_beam128_places_both(self) -> None:
        # A_best conflicts with B_only → greedy (width=1) is forced to skip B.
        # Beam (width=128) explores A_second → B_only fits → both placed.
        # Beam wins because omitted_count=0 < 1.
        cfg_beam = SolverConfig(
            beam_width=128,
            min_scale_bp=_CFG.min_scale_bp,
            page_diag_mpt=_CFG.page_diag_mpt,
            page_height_mpt=_CFG.page_height_mpt,
        )
        result = solve(
            [[_GREEDY_TRAP_A_BEST, _GREEDY_TRAP_A_SECOND, _GREEDY_TRAP_A_SKIP],
             [_GREEDY_TRAP_B_ONLY, _GREEDY_TRAP_B_SKIP]],
            cfg_beam,
            _box_conflict,
        )
        assert len(result.chosen) == 2
        by_id = {c.note_id: c for c in result.chosen}
        assert by_id["A"].kind != "skip", "beam must place A (via second-best)"
        assert by_id["B"].kind != "skip", "beam must place B (via its only feasible)"
        assert by_id["A"].ordinal == 1, "A must use second-best (ordinal 1) when best conflicts with B"

    # (c) Every candidate conflicts → skip chosen ---------------------------

    def test_conflicting_note_gets_skip(self) -> None:
        a      = _cand("A", ordinal=0, box_mpt=(0, 0, 100_000, 100_000))
        a_skip = _skip("A", ordinal=99)
        b      = _cand("B", ordinal=0, box_mpt=(0, 0, 100_000, 100_000))  # overlaps A
        b_skip = _skip("B", ordinal=99)

        result = solve([[a, a_skip], [b, b_skip]], _CFG, _box_conflict)
        by_id = {c.note_id: c for c in result.chosen}
        # A gets placed (first note, empty state, no prior conflicts).
        # B's only margin overlaps A → B falls back to skip.
        assert by_id["B"].kind == "skip", "B must be skipped when its margin conflicts with placed A"

    # (d) Missing skip candidate → ValueError --------------------------------

    def test_missing_skip_raises_value_error(self) -> None:
        a      = _cand("A", ordinal=0, box_mpt=(0, 0, 100_000, 100_000))
        a_skip = _skip("A", ordinal=99)
        b      = _cand("B", ordinal=0, box_mpt=(0, 0, 100_000, 100_000))  # conflicts A
        # B has NO skip candidate — must raise ValueError.
        with pytest.raises(ValueError):
            solve([[a, a_skip], [b]], _CFG, _box_conflict)

    # (e) Determinism -------------------------------------------------------

    def test_determinism_same_input_same_output(self) -> None:
        cands = [
            [_cand("n1", 0), _cand("n1", 1), _skip("n1", 99)],
            [_cand("n2", 0), _skip("n2", 99)],
        ]
        r1 = solve(cands, _CFG, _no_conflict)
        r2 = solve(cands, _CFG, _no_conflict)
        assert r1.chosen == r2.chosen

    def test_determinism_pre_sorted_input_stable(self) -> None:
        # Candidates sorted by ordinal (as callers must do per contract) → identical.
        cands_sorted = [
            sorted([_cand("n1", 0), _cand("n1", 1), _skip("n1", 99)],
                   key=lambda c: c.ordinal),
            sorted([_cand("n2", 0), _skip("n2", 99)], key=lambda c: c.ordinal),
        ]
        r = solve(cands_sorted, _CFG, _no_conflict)
        assert r.chosen[0].ordinal == 0  # lowest-ordinal wins without conflicts
        assert r.chosen[1].ordinal == 0

    def test_determinism_across_pythonhashseed(self) -> None:
        # Run the solver in subprocesses with varying PYTHONHASHSEED.
        # Identical output across all seeds confirms no hash-order dependence.
        _src = "/mnt/c/Users/Trey/Downloads/half-blood-prince/src"
        _script = f"""
import sys
sys.path.insert(0, {_src!r})
from halfblood.layout.page_solver import Candidate, SolverConfig, solve

def mk(note_id, ordinal, kind="margin"):
    return Candidate(
        note_id=note_id, ordinal=ordinal, kind=kind,
        box_mpt=(500000, 200000, 570000, 214000) if kind != "skip" else None,
        scale_bp=10000, side="right" if kind != "skip" else "",
        importance=1000, displacement_bp=0, side_switched=False,
        connector_a_mpt=None, connector_b_mpt=None,
        height_mpt=14000 if kind != "skip" else 0,
    )

cfg = SolverConfig(beam_width=128, min_scale_bp=7000,
    page_diag_mpt=1000904, page_height_mpt=792000)
cands = [
    [mk("n1", 0), mk("n1", 1), mk("n1", 99, "skip")],
    [mk("n2", 0), mk("n2", 99, "skip")],
    [mk("n3", 0), mk("n3", 1), mk("n3", 2), mk("n3", 99, "skip")],
]
result = solve(cands, cfg, lambda a, b: False)
print(",".join(f"{{c.note_id}}:{{c.ordinal}}" for c in result.chosen))
"""
        outputs = []
        for seed in ("0", "1", "42", "999", "31337"):
            proc = subprocess.run(
                [sys.executable, "-c", _script],
                capture_output=True,
                text=True,
                env={**os.environ, "PYTHONHASHSEED": seed},
            )
            assert proc.returncode == 0, (
                f"solver script failed (PYTHONHASHSEED={seed}):\n{proc.stderr}"
            )
            outputs.append(proc.stdout.strip())
        assert len(set(outputs)) == 1, (
            f"solve output varies across PYTHONHASHSEED values: {outputs}"
        )

    # (f) Incremental == from-scratch score on winner -----------------------

    def test_incremental_matches_scratch_score(self) -> None:
        # Exhaustively enumerate all assignments for a 3-note case (no conflicts)
        # and confirm solve returns the assignment with the global minimum score.
        a_cands = [_cand("A", 0, scale_bp=9000), _cand("A", 1, scale_bp=8000), _skip("A", 99)]
        b_cands = [_cand("B", 0, scale_bp=10000), _skip("B", 99)]
        c_cands = [_cand("C", 0, scale_bp=10000), _skip("C", 99)]

        result = solve([a_cands, b_cands, c_cands], _CFG, _no_conflict)

        # Re-compute score from scratch on the winner.
        fresh_score = score_assignment(result.chosen, _CFG)

        # Brute-force optimal: try all combinations (2*2*3 = 12).
        best_score = min(
            score_assignment((a, b, c), _CFG)
            for a in a_cands
            for b in b_cands
            for c in c_cands
        )
        assert fresh_score == best_score, (
            f"solve winner score {fresh_score} is not the global optimum {best_score}"
        )


# ---------------------------------------------------------------------------
# 5. beam_width=1 degenerates to greedy-by-ordinal
# ---------------------------------------------------------------------------

class TestBeamWidth:
    def test_beam1_trap_skips_b(self) -> None:
        # width=1: greedy keeps only A_best → B_only conflicts → B skipped.
        cfg_w1 = SolverConfig(
            beam_width=1,
            min_scale_bp=_CFG.min_scale_bp,
            page_diag_mpt=_CFG.page_diag_mpt,
            page_height_mpt=_CFG.page_height_mpt,
        )
        result = solve(
            [[_GREEDY_TRAP_A_BEST, _GREEDY_TRAP_A_SECOND, _GREEDY_TRAP_A_SKIP],
             [_GREEDY_TRAP_B_ONLY, _GREEDY_TRAP_B_SKIP]],
            cfg_w1,
            _box_conflict,
        )
        by_id = {c.note_id: c for c in result.chosen}
        assert by_id["B"].kind == "skip", "width=1 greedy trap: B must be skipped"

    def test_beam128_trap_places_b(self) -> None:
        # width=128: A_second explored → B_only fits → both placed.
        cfg_w128 = SolverConfig(
            beam_width=128,
            min_scale_bp=_CFG.min_scale_bp,
            page_diag_mpt=_CFG.page_diag_mpt,
            page_height_mpt=_CFG.page_height_mpt,
        )
        result = solve(
            [[_GREEDY_TRAP_A_BEST, _GREEDY_TRAP_A_SECOND, _GREEDY_TRAP_A_SKIP],
             [_GREEDY_TRAP_B_ONLY, _GREEDY_TRAP_B_SKIP]],
            cfg_w128,
            _box_conflict,
        )
        by_id = {c.note_id: c for c in result.chosen}
        assert by_id["B"].kind != "skip", "width=128 beam: B must be placed (beam beats greedy)"

    def test_beam1_vs_beam128_diverge_on_trap(self) -> None:
        # Sanity: the two configs must produce DIFFERENT results on the trap.
        cfg_w1 = SolverConfig(
            beam_width=1,
            min_scale_bp=_CFG.min_scale_bp,
            page_diag_mpt=_CFG.page_diag_mpt,
            page_height_mpt=_CFG.page_height_mpt,
        )
        cfg_w128 = SolverConfig(
            beam_width=128,
            min_scale_bp=_CFG.min_scale_bp,
            page_diag_mpt=_CFG.page_diag_mpt,
            page_height_mpt=_CFG.page_height_mpt,
        )
        r1  = solve(
            [[_GREEDY_TRAP_A_BEST, _GREEDY_TRAP_A_SECOND, _GREEDY_TRAP_A_SKIP],
             [_GREEDY_TRAP_B_ONLY, _GREEDY_TRAP_B_SKIP]],
            cfg_w1, _box_conflict,
        )
        r128 = solve(
            [[_GREEDY_TRAP_A_BEST, _GREEDY_TRAP_A_SECOND, _GREEDY_TRAP_A_SKIP],
             [_GREEDY_TRAP_B_ONLY, _GREEDY_TRAP_B_SKIP]],
            cfg_w128, _box_conflict,
        )
        assert r1.chosen != r128.chosen, (
            "beam_width=1 and beam_width=128 must differ on the greedy-trap fixture; "
            "if they agree, the trap fixture is not actually trapping greedy"
        )


# ---------------------------------------------------------------------------
# 8. Connector body-span cost — regression for the "arrow across the page" bug
#
# Observed 2026-07-24 on a real-model render of tests/fixtures/potions_textbook.pdf
# page 2: a note placed in the BOTTOM-RIGHT margin was anchored to a target near
# the TOP of the page, drawing a connector diagonally through several lines of
# body text.
#
# Root cause: the solver scored connectors on Euclidean LENGTH only (weight 50),
# which is dominated 20:1 by the scale cost (weight 1000). Keeping a note at full
# size and flinging it far from its target was therefore cheaper than shrinking it
# slightly to sit beside its target. Nothing modelled the connector's traversal of
# the body block at all.
# ---------------------------------------------------------------------------


class TestConnectorBodySpanCost:
    def test_near_target_min_scale_beats_far_full_scale(self) -> None:
        """A shrunken note beside its target must score better than a full-size
        note whose connector rakes down ~79% of the page through body text.
        """
        # Connector runs (510k, 700k) -> (200k, 50k). Against a body block spanning
        # y 72k..720k that is an overlap of 628k mpt => ratio(628000, 792000) = 7929 bp.
        far_full_scale = _cand(
            "n1",
            0,
            importance=1,
            scale_bp=10000,  # full size: contributes ZERO scale cost
            connector_a_mpt=(510_000, 700_000),
            connector_b_mpt=(200_000, 50_000),
            connector_body_span_bp=7929,
            displacement_bp=8000,
        )
        # Same note beside its target: short horizontal hop, no body traversal.
        near_min_scale = _cand(
            "n1",
            1,
            importance=1,
            scale_bp=7000,  # floor: contributes the MAXIMUM scale cost
            connector_a_mpt=(510_000, 57_000),
            connector_b_mpt=(200_000, 57_000),
            connector_body_span_bp=0,
            displacement_bp=0,
        )

        _, _, soft_far, _ = score_assignment((far_full_scale,), _CFG)
        _, _, soft_near, _ = score_assignment((near_min_scale,), _CFG)

        assert soft_near < soft_far, (
            f"a min-scale note beside its target (soft={soft_near}) must beat a "
            f"full-scale note whose connector traverses the page (soft={soft_far}); "
            "otherwise the solver keeps choosing the across-the-page arrow"
        )

    def test_body_span_is_monotonic(self) -> None:
        """More body traversal must never be cheaper than less, all else equal."""
        scores = []
        for span in (0, 2500, 5000, 7500, 10000):
            cand = _cand(
                "n1",
                0,
                importance=1,
                connector_a_mpt=(510_000, 400_000),
                connector_b_mpt=(200_000, 400_000),
                connector_body_span_bp=span,
            )
            _, _, soft, _ = score_assignment((cand,), _CFG)
            scores.append(soft)

        assert scores == sorted(scores), f"cost must rise with body span, got {scores}"
        assert scores[0] < scores[-1], "a full-page traversal must cost more than none"
