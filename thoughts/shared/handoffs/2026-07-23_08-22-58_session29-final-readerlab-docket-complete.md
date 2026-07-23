---
date: 2026-07-23T08:22:58-04:00
researcher: Claude (Fable 5)
git_commit: f695635ffc66752b519a5100f59b63bd6844c2ba
branch: main
repository: half-blood-prince (+ dev-harness)
topic: "Session 29 FINAL — reader-lab fixtures merged; DOCKET COMPLETE; everything remaining is owner-gated"
tags: [session-close, reader-lab, epub, docket-complete, owner-queue, adoption]
status: complete
last_updated: 2026-07-23
type: handoff
---

# Handoff: Session 29 FINAL — docket complete (1357 green)

> **`main` @ `f695635`, 1357 green, ruff (incl. scripts/) + mypy clean, default solver
> beam, `v0.1.0` intact.** Session 29's full arc: S2c beam perf (~7×) → S3 default flip
> (owner-approved 50ms budget) → oh-my-pi adoption study → ALL FIVE adoption mechanisms
> built shadow → backlog cleanup + both-solver contracts → reader-lab EPUB artifacts.
> **The loop stopped on docket-complete: every remaining item needs the owner.**

## Session 29 ledger of merges (hbp, all --no-ff, all Opus-GO, all controller-gated)
| Merge | What |
|---|---|
| `d521523` | P3-S2c beam hot-path (~7×, byte-identical) |
| `4363b03` | P3-S3 default solver → beam (budget 50ms, owner-approved) |
| `378390c` | oh-my-pi adoption study (advisory docs) |
| `5ae7725` | attempted_count docstring + both-solver contract tests |
| `5d2158e` + `8ffcda6` | sdd-driver definition + hardened policy hooks (SHADOW) |
| `f7a2c75` | conformance checker + divergence ledger (advisory) |
| `f695635` | reader-lab EPUB artifacts (NL4 §2 closed, advisory) |

dev-harness: `d90baea` codex-receipts, `a8bef24` sddctl journal, `d7b090d` sdd-manifest.

## Task(s)
1. ✅ Reader-lab fixtures — merge `f695635`. Overnight WSL sleep stalled the dispatch;
   handled by the side-effect rule (TERM exact PID, receipt covered the missing
   self-report, no redispatch). Reviewer verified every README claim against generator
   AND artifacts; EPUB2 linked-div branch proven genuine.
2. ⏸ **OWNER QUEUE (everything remaining):**
   - Sideload `tests/fixtures/reader_lab/*.epub` into real readers; findings → ledger.
   - 29g queue: fix/retire 2 nonconformant agents; label codex-usage-audit historical;
     add scripts/ to documented gate (CLAUDE.md).
   - Activation flags: sdd-driver agent, /goal↔sddctl wiring, receipts enforcement,
     manifest-preflight enforcement (note: testsums check needs allowed-outputs
     awareness first — shadow finding #1).
   - OpenRouter key → product validation (the oldest owed item).

## Critical References
- `thoughts/shared/handoffs/2026-07-22_12-12-43_session29h-adoption-buildout-complete.md`
  (adoption scoreboard) and `…_11-35-51_session29g…` (owner queue detail).
- `tests/fixtures/reader_lab/README.md` — the per-reader advisory checklist.
- Ledger Session-29 entries (progress.md) — full evidence trail.

## Learnings (session-final)
- **WSL sleep freezes awake-time timeouts**: a `timeout`-guarded dispatch can outlive its
  window by wall-clock days with the deliverables already landed. Diagnostic: `ps -o
  etime` (awake time) vs file mtimes. Response: verify side effects, TERM exact PID, let
  the wrapper write its receipt, never redispatch. The receipts mechanism covered the
  missing self-report exactly as designed.
- sdd-manifest shadow finding #1: testsums drift fires on legitimately-added test files;
  enforcement needs allowed-outputs awareness.
- Idle-without-report occurred 3× this session (driver ×1, reviewers ×2), all recovered
  by one SendMessage nudge; deliver-before-idle clauses in prompts reduced but did not
  eliminate it — the Stop-hook gate (built, shadow) is the structural fix.

## Verification (controller-run, post-merge)
| Claim | Command | Result |
|---|---|---|
| main @ `f695635` | `git rev-parse HEAD` | `f695635f…` |
| Suite | `.venv/bin/pytest tests/ -q` | `1357 passed, 12 warnings` |
| ruff / mypy | `ruff check src tests eval scripts` / mypy | clean / clean |
| Artifacts deterministic | regeneration vs committed | byte-identical (sha256 match) |
| Solver default | `LayoutConfig().solver` | beam (unchanged since S3) |
| Tolerated dirt only | `git status --porcelain` | `M CLAUDE.md` + 2 untracked (same) |

## Action Items & Next Steps
Everything is in the OWNER QUEUE above. Resume the loop with `/loop /goal` (or a docket
message) once any item is unblocked; re-orient via this handoff → progress.md tail.

## Other Notes
- Rollbacks: each merge `git revert -m 1 <sha>` (table above); dev-harness plain reverts.
  Tags: `pre-overnight-2026-07-21` @ `58b26e1` (predates the whole arc).
- Never push. `M CLAUDE.md` untouchable. All merged branches retained for inspection.
