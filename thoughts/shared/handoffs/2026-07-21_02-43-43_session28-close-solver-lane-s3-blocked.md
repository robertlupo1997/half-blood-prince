---
date: 2026-07-21T02:43:43-04:00
researcher: Claude (Fable 5)
git_commit: e7540b3
branch: main
repository: half-blood-prince
topic: "Session 28 close — Phase-3 solver lane through S2b merged; S3 BLOCKED by rollout gate (perf); one orchestration incident, contained"
tags: [phase3, page-solver, beam, rollout-gate, performance, incident, epub-track-complete]
status: complete
last_updated: 2026-07-21
type: handoff
---

# Handoff: Session 28 close — solver lane at safe checkpoint, S3 perf-blocked

> **`main` @ `e7540b3`, 1273 green, ruff + mypy clean (42 files), `v0.1.0` intact.**
> Full night: **10 task merges** — MP2a/MP2b/MP2c + EPUB NL1–NL4 (track COMPLETE) +
> P3-S1/S2a/S2b (solver lane). 10/10 Opus reviews GO. Beam solver is merged but
> **default-OFF (greedy)** — main behavior unchanged. **S3 default-flip BLOCKED by the
> controller rollout gate: quality PASS (0 regressions), determinism PASS, performance FAIL
> (p95 658ms vs 25ms budget on 8-note pages).** Next task queued: S2c beam hot-path
> optimization, then re-run the gate.

## State snapshot
- Suite: 1138 (nightfall) → **1273** now. Warnings 39 → 12.
- Designs of record committed: EPUB note-layout (`2026-07-20-epub-note-layout-track-design.md`),
  Phase-3 solver (`2026-07-21-phase3-page-solver-design.md`, incl. SUM-aggregation amendment).
- Cap RETIRED by owner (skill commit `14c5539`; memory `merge-cap-retired-by-owner`).

## Solver lane detail (for whoever picks up S2c)
- `layout/page_solver.py` — pure core: lexicographic integer score
  `(omitted_count, omitted_importance, soft_geometry_cost=SUM(soft_i×imp_i), ordinal-tuple)`,
  bounded beam (width 128), integer-only ranking. `tests/test_page_solver.py` is the
  arithmetic's normative reference.
- `layout/engine.py` — `LayoutConfig.solver: "greedy"|"beam"` (default greedy),
  `beam_width=128`; `_iter_margin_side_candidates` (greedy ≡ first yield, reviewer-verified);
  `_candidates_for_note` builds quantized `page_solver.Candidate`s (≤74/note, MP1c = no margin
  candidates without columns); `_run_beam` dispatches via module attribute `_page_solver.solve`
  (spy-able) and reconstructs winning-geometry results.
- **Rollout gate results (controller-run, 75-page seeded synthetic corpus):** beam-wins=5,
  ties=70, regressions=0; corpus hash identical across PYTHONHASHSEED=0/42; 8-note p95=658ms
  (26× over the 25ms budget), beam/greedy total 1410×.
- **S2c scope (queued, not started):** memoize measurement `(id, lane_width_mpt, scale_bp)`;
  kill per-extension allocation churn (hot loop on tuples, not dataclasses); precompute
  pairwise connector geometry; re-run gate; S3 only after p95 <25ms or owner revises budget.

## Incident (P3-S2a, contained — full account in progress.md ~02:00 entry)
Controller retracted a formula ruling without telling the executing driver first → 4 rogue
Codex dispatches, a soft-reset that left the checkout on main, transiently staged CLAUDE.md
(verified intact, never committed), and S2a landing LINEAR on main (no `--no-ff` merge commit).
**Rollback asymmetry: S2a = `git revert eddfe42` (plain); every other merge = `git revert -m 1
<merge-sha>`.** Old driver retired; fresh driver ran S2b flawlessly. Lessons in memory
`ruling-changes-go-to-executor-first`. A WIP stash (`stash@{0}` on the S2a branch) holds the
old driver's debris — safe to ignore or drop after inspection.

## Verification (controller-run)
| Claim | Result |
|---|---|
| main HEAD | `e7540b3` (S2b merge) |
| Full suite / ruff / mypy | `1273 passed` / clean / clean |
| Beam default-off | `LayoutConfig().solver == "greedy"`; explicit-greedy ≡ default (test-pinned) |
| Rollout determinism | corpus hash `e18ccde0…` identical across hash seeds |
| `M CLAUDE.md` | unstaged, rewrite intact (12,828B), never committed |
| Rollback tag | `pre-overnight-2026-07-20` @ `7c7bb80` |

## Action Items & Next Steps
1. **S2c — beam performance** (scope above), then re-run rollout gate, then S3 flip.
2. Deferred: reader-lab EPUB fixtures; NL-series minor findings; MP2a/MP2b test nits;
   `attempted_count` docstring; EPUB intent CSS on real readers.
3. **Product validation** — still owed, still blocked on an OpenRouter key.
4. Owner review of the night: `git log pre-overnight-2026-07-20..main --oneline` (10 task
   merges + docs), the incident entry, and the S3 block decision.

## Other Notes
- Never push. Local-only. Loop rails: no merge-count cap; stop on quality degradation or
  STOP-FLAG only.
- Pre-existing dirty tree (leave alone): `M CLAUDE.md`, untracked
  `.claude/skills/halfblood-roadmap/`, `docs/superpowers/plans/2026-07-11-...`.
- Resume: `/loop /goal` — next iteration should brief S2c with the perf levers above.
