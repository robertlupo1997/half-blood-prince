---
date: 2026-07-21T20:24:59-04:00
researcher: Claude (Fable 5)
git_commit: 378390c8f919745cdbde394afefda4bd67fd7209
branch: main
repository: half-blood-prince
topic: "Session 29 — P3-S2c beam perf merged (~7×, byte-identical); S3 in 25–50ms owner band; oh-my-pi adoption study delivered"
tags: [phase3, page-solver, beam, performance, rollout-gate, oh-my-pi, adoption-study]
status: complete
last_updated: 2026-07-21
type: handoff
---

# Handoff: Session 29 — S2c merged, S3 owner-gated, adoption study on main

> **`main` @ `378390c`, 1273 green, ruff + mypy clean, `v0.1.0` intact, default solver
> still greedy.** Two commits this session on top of the merge: P3-S2c beam hot-path
> optimization (merge `d521523`, ~7× speedup, byte-identical outputs, Opus GO) and the
> oh-my-pi adoption study (`378390c`, advisory). **S3 default-flip remains BLOCKED — now
> on an OWNER DECISION, not on engineering:** p95 ≈ 45–47ms vs the 25ms design budget,
> inside the brief's designated 25–50ms stop-and-ask band, with all pure-Python levers
> applied.

## Task(s)
1. ✅ **P3-S2c beam hot-path optimization** — merged `d521523` (feat `a576d03`). 1 Codex
   dispatch, tripwire 54/54 OK, controller gate table all-CONFIRMED, Opus review GO with
   0 blockers. Perf: 8-note median 237.5→~40ms, p95 338.7→~45-47ms (~7×).
2. ✅ **oh-my-pi adoption study** (owner request) — `378390c`,
   `thoughts/shared/research/2026-07-21_omp-adoption-study.md`. ADVISORY ONLY; digest +
   controller ranking below. Nothing implemented; every proposal owner-gated.
3. ⏳ **S3 default flip — OWNER DECISION REQUIRED** (see Action Items).
4. ⏳ Product validation — still blocked on an OpenRouter key.

## Critical References
- `docs/superpowers/specs/2026-07-21-phase3-page-solver-design.md` — solver design + gate.
- `.superpowers/sdd/rollout_gate_s2c.py` — durable recreated rollout bench (sha256
  `8b35adc1…`). **BASELINE SUPERSESSION: corpus hash is now `f8915d0031f29ef33af5ac39749e711
  16df7ea6ea0f538ff72c80a1a2eb33b09`** — the old `e18ccde0…` belonged to Session 28's lost
  session-local script; byte-identity invariant unchanged.
- `thoughts/shared/research/2026-07-21_omp-adoption-study.md` — adoption matrix + top-5.

## Recent changes
- `src/halfblood/layout/page_solver.py` (+311/−18 with engine): precomputed pairwise
  conflict bitmasks (still consulting the injected callable), grouped crossing
  contributions, per-candidate local soft cost, tuple hot-loop states with incremental
  scores, `bisect_right` online top-k (≡ sort+slice under the strict total order).
- `src/halfblood/layout/engine.py`: conflict wiring via `functools.partial`; greedy path
  untouched (reviewer-verified).
- Ledger: `.superpowers/sdd/progress.md` Session-29 entries (orientation → dispatches →
  incident recurrence → merge → gate re-run → study commit).

## Learnings
- **Measurement was a red-herring lever.** cProfile showed candidate enumeration + ALL
  measurement = 4% of beam runtime; the solver core was 96% (conflicts 45%, crossings 17%,
  soft cost 13%, state churn 15%). The draft brief's memoize-measurement lever was demoted
  before dispatch. Profile-first saved a wasted dispatch.
- **Beam at width 128 can place fewer notes than greedy** (corpus page 65: 7/8 at 128,
  8/8 at ≥512 — verified by width sweep). Pruning artifact, not an enumeration bug. The
  Session-28 corpus never exposed it; "0 regressions" was corpus luck, not a theorem.
  Post-S2c, wider beams are affordable (~linear cost) — S3 material.
- **Idle-without-report recurred** (driver went idle mid-dispatch; recovered by SendMessage
  resume; final report honest and complete). Live evidence for adoption-study proposal 3
  (driver Stop hook). Also: a driver's foreground 600s Bash cap will lap a 15-min Codex
  run — drivers must poll-wait, which this one did after the nudge.
- **Dual-impl drift risk (on record from review):** `_extend_state`/`_state_score` now
  serve only `score_assignment`; the hot path is fully inlined. Circuit-breaker:
  `tests/test_page_solver.py::test_incremental_matches_scratch_score`. Whoever next touches
  scoring constants must change BOTH paths.

## Verification (all controller-run this session, post-merge)
| Claim | Command | Result |
|---|---|---|
| main HEAD `378390c`, branch main | `git rev-parse HEAD` / `--abbrev-ref` | `378390c8…` / `main` |
| Full suite green | `.venv/bin/pytest tests/ -q` | `1273 passed, 12 warnings` |
| ruff / mypy clean | `.venv/bin/ruff check src tests eval` / `.venv/bin/mypy src/halfblood` | `All checks passed!` / `no issues in 42 files` |
| Byte-identical outputs | `.venv/bin/python .superpowers/sdd/rollout_gate_s2c.py bench` | `corpus_hash=f8915d00…` (exact match to pre-S2c baseline) |
| Quality unchanged | same bench run | `beam_wins=30 ties=44 REGRESSIONS=1` (exact) |
| Perf post-S2c | same bench run | `median=40.8ms p95=46.9ms` (baseline 237.5/338.7) |
| Hash-seed determinism | `PYTHONHASHSEED=0/42 … bench` (2 subprocesses) | identical `f8915d00…` both |
| Default solver greedy | `python -c "…LayoutConfig().solver"` | `greedy` |
| Study tracked on main | `git ls-files thoughts/shared/research/` | `…omp-adoption-study.md` listed |
| `M CLAUDE.md` untouched/uncommitted | `git status --porcelain \| grep CLAUDE` | ` M CLAUDE.md` (unstaged) |
| Tags intact | `git tag -l 'v0.1.0' 'pre-overnight-2026-07-21'` | both present |
| Session commit count | `git log pre-overnight-2026-07-21..main --oneline \| wc -l` | 3 (feat + merge + docs) |
| Page-65 pruning claim | width sweep script (this session) | 128→7 placed; 512/1024/4096→8 placed |

## Artifacts
- Merge `d521523` (feat `a576d03`): `src/halfblood/layout/page_solver.py`,
  `src/halfblood/layout/engine.py`.
- Docs commit `378390c`: `thoughts/shared/research/2026-07-21_omp-adoption-study.md`.
- Durable (gitignored): `.superpowers/sdd/rollout_gate_s2c.py`,
  `p3s2c-beam-perf-brief.md` (finalized), `p3s2c-out.md`, `p3s2c-tripwire.sha256`,
  `omp-adoption-study-out.md`, `omp-adoption-dispatch.log`, progress.md Session-29 tail.
- This handoff + HANDOFF.md pointer update.

## Action Items & Next Steps
1. **OWNER: S3 decision (the only blocker).** Beam is merged, byte-identical, default-off,
   p95 ≈ 45–47ms vs the 25ms budget after all pure-Python levers. Options:
   (a) revise budget to ~50ms and flip the default — optionally with `beam_width` 256–512
   for quality headroom (page-65 datum), at roughly linear extra cost;
   (b) commission C-extension work to chase <25ms;
   (c) keep greedy as default and close the lane.
   Controller recommendation: **(a) with beam_width=128 initially** — 45ms/page is
   imperceptible in a batch pipeline whose per-page LLM call costs seconds; the 25ms budget
   predates measurement. Flip S3 as its own task with the rollout gate re-run at the
   revised budget.
2. **OWNER: adoption-study digest** (advisory; controller's ranking, differs from the
   study's ordering):
   1. Host-generated Codex run receipts + side-effect-aware retry (study #2) — best
      evidence-per-effort; closes false-testimony and hung-after-write classes at the
      wrapper boundary with no prompt changes.
   2. Durable ruling epochs + acknowledgements, events.jsonl + sddctl (study #1) — the
      structural Session-28 fix; needs shadow mode first.
   3. `sdd-driver` agent definition with action/stop hooks (study #3) — would have blocked
      tonight's idle-without-report and Session-28's stash/reset improvisation.
   4. Harness conformance + divergence ledger (study #4) — small; two real local
      divergences already seeded.
   5. Brief/source manifests (study secondary) — cheap fail-closed staleness check.
   Prewalk: agree with the study — reject for production; optional confined
   codex-resume spike only. ALL owner-gated; nothing implemented.
3. Product validation — needs OpenRouter key (unchanged).
4. Deferred small items carry over from Session 28 (reader-lab EPUB fixtures, NL-series
   minor findings, MP2a/MP2b test nits, `attempted_count` docstring).

## Other Notes
- Rollback: S2c = `git revert -m 1 d521523`; study = `git revert 378390c`; night tag
  `pre-overnight-2026-07-21` @ `58b26e1`. S2a rollback asymmetry still applies
  (`git revert eddfe42` plain).
- Never push; local only. `M CLAUDE.md` + the two untracked paths remain tolerated dirt.
- Branch `phase-p3s2c-beam-perf` retained (merged); safe to delete after owner eyeball.
- The Session-28 WIP stash (`stash@{0}`) still exists — inspect or drop at leisure.
