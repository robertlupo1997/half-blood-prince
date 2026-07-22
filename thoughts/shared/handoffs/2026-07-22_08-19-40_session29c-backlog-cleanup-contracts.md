---
date: 2026-07-22T08:19:40-04:00
researcher: Claude (Fable 5)
git_commit: 5ae7725de193c85c75fe2905cdb74650e5ed20ac
branch: main
repository: half-blood-prince
topic: "Session 29 (cont. 2) — backlog cleanup merged: attempted_count docstring + both-solver contract tests"
tags: [backlog, contracts, greedy-escape-hatch, attempted-count, autonomy-directive]
status: complete
last_updated: 2026-07-22
type: handoff
---

# Handoff: Session 29c — backlog cleanup merged (1291 green)

> **`main` @ `5ae7725`, 1291 green (1273+18), ruff + mypy clean, default solver beam,
> `v0.1.0` intact.** One small merge this iteration: the recorded MP1d
> `attempted_count` docstring + `tests/test_solver_contracts.py` (9 contracts × 2
> solvers) closing the S3 reviewer's greedy-coverage gap. Standing autonomy directive
> remains in effect.

## Task(s)
1. ✅ Backlog cleanup — merge `5ae7725` (docstring `8bc1b43` controller-authored; contract
   tests `de80381` driver-authored, no Codex; Opus GO, 0 blockers; one comment nit fixed
   pre-merge).
2. ⏳ NEXT (recommended): **ruling-epoch journal** (adoption proposal #1 — events.jsonl +
   sddctl + acknowledgements, shadow mode first) — the structural Session-28 fix; start
   fresh-context, spec from `thoughts/shared/research/2026-07-21_omp-adoption-study.md`
   §Top-5 #1. Then: sdd-driver definition + hooks → conformance gate → manifests.
3. ⏳ Reader-lab EPUB fixtures (NL4 §2 deferral) — larger; after the journal.
4. ⏳ Product validation — blocked on an OpenRouter key (owner).

## Critical References
- `thoughts/shared/research/2026-07-21_omp-adoption-study.md` — implementation sketches
  for the adoption remainder (validation plans included).
- `~/dev-harness/scripts/codex-receipts.sh` — USE for all future Codex dispatches
  (shadow; receipt at `<out>.receipt.json`).
- `docs/superpowers/specs/2026-07-21-phase3-page-solver-design.md` — solver lane record.

## Recent changes
- `src/halfblood/models/rendering.py:222` — `attempted_count` docstring (mark-only ⊆
  skipped; pair with `len(marks_only)` when reporting visible output). Behavior unchanged.
- `tests/test_solver_contracts.py` (new, 422 lines) — 9 contracts × greedy/beam:
  coverage-exactly-once, containment, no-overlap, body non-invasion, MP1c skip + inline
  exemption, scale floor (stress measurer), determinism, permutation invariance.

## Learnings
- Hardening pins that pass green-on-first-run need a vacuity-focused review; the Opus
  reviewer's per-contract audit (placed non-empty guards, live-config tolerances,
  which note actually scale-reduces) is the template for future test-only merges.
- Recorded MP2a/MP2B test nits were already absorbed by MP2c (`c5e7452`) — deferred-item
  lists rot; re-verify against the ledger before briefing them as work.

## Verification (controller-run this session, post-merge)
| Claim | Command | Result |
|---|---|---|
| main @ `5ae7725` | `git rev-parse HEAD` | `5ae7725d…` |
| Suite | `.venv/bin/pytest tests/ -q` | `1291 passed, 12 warnings` |
| ruff / mypy | standard commands | clean / `no issues in 42 files` |
| New module standalone | `.venv/bin/pytest tests/test_solver_contracts.py -q` | `18 passed` |
| Docstring-only src diff | `git diff main^..main -- src/` reviewed pre-merge | +7 lines, docstring only (reviewer-confirmed) |
| Tolerated dirt unchanged | `git status --porcelain` | `M CLAUDE.md` + 2 untracked (same) |

## Artifacts
- Merge `5ae7725` (`8bc1b43` + amended `de80381`).
- Ledger: progress.md "BACKLOG CLEANUP" entries.
- This handoff + HANDOFF.md pointer.

## Action Items & Next Steps
1. Next iteration: ruling-epoch journal (task 2 above) — substantial; use
   codex-receipts.sh for any Codex dispatch; shadow-mode assertions first (study's
   validation plan: replay the Session-28 sequence as a regression test).
2. Then reader-lab fixtures; then remaining adoption items.
3. Product validation on key arrival.

## Other Notes
- Rollback: this merge = `git revert -m 1 5ae7725`. Prior points unchanged
  (S3 `4363b03`, S2c `d521523`, study `378390c`; tag `pre-overnight-2026-07-21`).
- Never push. `M CLAUDE.md` untouchable. Branches retained: phase-p3s2c-beam-perf,
  phase-p3s3-default-flip, phase-backlog-cleanup (all merged).
