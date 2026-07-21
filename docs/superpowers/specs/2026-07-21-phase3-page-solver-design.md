# Phase-3 Global Page Solver — Design of Record (2026-07-21)

**Status:** ADOPTED (controller decision, Session 28 night; Codex advisory
`.superpowers/sdd/solver-design-consult{,-out}.md`, read-only gpt-5.6-sol high, verified
against HEAD). Parent design: `2026-07-19-annotation-placement-architecture-design.md` §5
Phase 3. Groundwork merged: P3-S1 greedy seam (`_run_greedy` in `layout/engine.py`).

## Objective (lexicographic, integer — never aggregate floats)

`Score = (omitted_count, omitted_importance, soft_geometry_cost, assignment_key)`, lower wins.

- Quantization: `q_pt` = half-even to 0.001pt as integer millipoints; `q_scale` to 1/10,000;
  `q_conf` to 1/1,000; `ratio(a,b) = (10_000*a + b//2)//b`. Reject non-finite geometry.
- `importance_i = (8 − ANNOTATION_TYPE_PRIORITY[type_i]) * 1001 + confidence_milli_i`
  (type tier strictly dominates confidence; type/conf/id stays the canonical ordering).
- Soft terms, each normalized to 0..10,000 basis points, importance-weighted:
  `soft = 1000*scale + 50*connector_length + 500*connector_crossings +
  100*target_displacement + 150*side_switches + 25*lane_unevenness`.
  Scale term: `10_000*((1−scale)/(1−min_scale))²`. Connector endpoints per composer
  `_connector_edges`; crossings/length are straight-segment PROXIES (real routing is
  downstream in `rough.make_connector` — never promise rendered zero-crossing).
- **AMENDED at S2a merge (2026-07-21): aggregation is the importance-weighted SUM
  `soft = Σ(soft_i × importance_i)`, NOT the mean this doc's advisory phrasing implied.**
  Reviewer-verified equivalence: every beam step processes the same note set, so total
  importance is constant across states; at equal `omitted_importance`, placed importance W is
  fixed, making sum and mean rank identically at every pruning point. Sub-term rounding pins
  per the S2a test suite (e.g. `r²` scaled by truncating `ratio`; scale=0.8/min=0.7 ⇒ term
  4444 bp). `tests/test_page_solver.py` is the arithmetic's normative reference.
- Hard constraints (infeasible, never priced): off-page, non-finite/oversized measurement,
  scale < min_scale, margin < margin_min_width, any note/body/target/note overlap beyond
  tolerance, same-margin interval overlap, attempt over `attempt_budget`, and — MP1c — **no
  `body_columns` ⇒ no margin candidates generated at all** (not penalized: removed). Inline
  keeps its existing exemption. Skip is always feasible; it is the primary soft penalty.

## Search

- Candidate generation REUSES the engine machinery: current sort key; `_target_rect` anchors;
  column-derived strips; single `_try_inline` position; margin candidates enumerate scales
  `1.0, 0.9, … min_scale` × preferred-then-opposite side × attempts `0..attempt_budget` via
  `_shift_multiplier`, with existing centering/clamping/collision rules. Extract
  `_iter_margin_side_candidates`; `_try_margin_side` = "first yielded" (greedy compat).
  Ordinal preference: inline; then (scale_idx, side_idx, attempt_idx); skip last. Dedup
  clamped candidates by quantized `(placement, scale, box)` keeping earliest ordinal.
  Defaults ⇒ ≤74 candidates/note.
- Beam search, `beam_width=128`, per canonical request: expand × candidates, reject dynamic
  conflicts, incremental connector-pair/lane terms, sort by (partial score, tuple of candidate
  ordinals), keep 128. Reconstruct `ResolvedAnnotation`/warnings/skips/flags for the WINNING
  state only. Worst case n=8: ≤66,378 extensions. Above 8 notes: same fixed beam — no greedy
  fallback, no chunking, no silent caps. Exhaustive search rejected (74^8 ≈ 9e14).

## Compatibility & rollout

`LayoutConfig` gains `solver: Literal["greedy","beam"] = "greedy"` and `beam_width: int = 128`
(S2b). First merge defaults GREEDY. Flip (S3, separate merge) only after the controller rollout
gate: fixture PDFs, synthetic dense corpus, subprocess determinism (PYTHONHASHSEED), ~300-page
benchmark (target p95 < 25ms per 8-note page; ≤ ~2× greedy end-to-end). Greedy stays as escape
hatch ≥1 release. Contract tests must hold for BOTH solvers (placed-or-skipped-exactly-once,
canonical ordering, containment/collision, MP1c, inline exemption, min_scale, measure≡render,
warnings for winning geometry, determinism, 7-note zero-overlap, mark-only). Greedy-specific
tests get `solver="greedy"` pins or rewrites (named in the advisory).

## Task split
S2a `layout/page_solver.py` (NEW, pure: immutable prepared-candidate/state types, integer
objective, segment crossing, canonical keys, generic bounded beam; MUST NOT import
layout.engine) → S2b engine.py (candidate enumeration via `_iter_margin_side_candidates`,
config fields, dispatch; default greedy) → controller rollout gate → S3 default flip.

## Key risks (full list in advisory RISKS)
Float/dict-order determinism; pure memoized measurer keyed `(id, lane_width_mpt, scale_bp)`;
duplicate-ID/NaN-confidence inputs pinned invalid; warning-sequence compatibility characterized;
future seventh term (connector routing difficulty) once a renderer-neutral estimator exists;
Phase-2 supplies wider strips through the same seam later; spec §6 (`faithful` default) is
authoritative over §3. Cross-page continuity explicitly OUT of scope.
