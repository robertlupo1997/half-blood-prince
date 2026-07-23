---
date: 2026-07-23T09:03:01-04:00
researcher: Claude (Fable 5)
git_commit: 27f93d293159f9b53ea35fc4afc2caa2881c714b
branch: main
repository: half-blood-prince
topic: "Session 30 BRIEF — owner-directed pivot: lean E2E lane model (subagents own features end-to-end; one gate per lane)"
tags: [operating-model, lanes, e2e, owner-directive, session-brief]
status: complete
last_updated: 2026-07-23
type: handoff
---

# Session 30 brief: the lean E2E lane model (owner-directed)

> **Owner directive (2026-07-23, verbatim intent):** stop the per-step checks and
> balances; use subagents to implement whole features END-TO-END and test them
> end-to-end; lane subagents write their own handoffs when done so the next
> chat/agent stays informed. Memory: `lean-e2e-lane-model` + `standing-autonomy-directive`.
> Baseline: `main` @ `27f93d2`, **1357 green**, ruff (incl. scripts/) + mypy clean,
> default solver beam, `v0.1.0` intact.

## The operating model (replaces per-step ceremony for routine work)
1. **Lanes, not steps.** Each lane = one feature, owned end-to-end by a subagent
   (sonnet, general-purpose — or the `sdd-driver` agent once activated, see §Guards):
   probe → implement (Codex via `~/dev-harness/scripts/codex-receipts.sh` for
   substantial code, direct authorship for tests/small stuff) → test → self-verify →
   **write its own lane handoff** to `thoughts/shared/handoffs/lanes/<lane>-<date>.md`
   (result, evidence, commit shas, receipt paths, anomalies) → report and stop.
2. **Parallel lanes use worktree isolation** (memory: parallel drivers touching
   code/git need worktrees). Independent lanes only; anything touching the same
   modules runs serial.
3. **One gate per lane, at merge:** full suite + ruff (src tests eval scripts) + mypy,
   run by the orchestrator, plus ONE review — and only for lanes touching product src.
   Test-only / docs / fixture lanes: orchestrator verification suffices, no review.
4. **Trust the automated guards** instead of re-proving claims: receipts prove what
   changed; tripwires (or sdd-manifest) prove protected files untouched; the suite
   proves behavior. The orchestrator spot-checks, not re-litigates.
5. **Full ceremony is reserved** for: solver arithmetic/determinism contracts
   (`page_solver.py`/`engine.py` scoring), git history surgery, and anything the
   owner flags. Those still get the old protocol.
6. Handoffs: lane agents write lane handoffs; the orchestrator writes ONE
   session-close handoff + HANDOFF.md pointer. Ledger entries stay (they're cheap
   and they saved us twice).

## Guards to activate first (they REPLACE manual checking — do this before lane 1)
- **Activate `sdd-driver`** (definition + hardened hooks merged `5d2158e`+`8ffcda6`,
  52 table-tests): spawn lanes as `subagent_type: "sdd-driver"` where the lane fits
  its policy (no src edits by the driver itself, Codex builds src). Its Stop hook
  enforces exactly the handoff-before-idle the owner asked for. First activation:
  verify the hooks fire in-anger on a trivial probe task before trusting a real lane.
- Dispatch Codex ONLY through `codex-receipts.sh`; the lane handoff must cite its
  receipt path. Optional: `sdd-manifest generate/validate` per lane (remember shadow
  finding #1: testsums drift is expected when a lane adds test files).
- Keep the runaway Monitor (pgrep codex pattern) armed while any lane runs.

## First lane set (probe-first — the roadmap skill is PARTIALLY STALE; verify each
against HEAD before briefing, e.g. EPUB cross-tag matching was largely addressed by NL1)
- **Lane A — async/concurrent page generation** (CLAUDE.md high-priority): asyncio +
  provider-seam-compatible concurrency with a semaphore (default 3-5), ordered
  results, rate-limit awareness; end-to-end test with a deterministic fake provider
  on a multi-page fixture. Biggest real-user win (300-page books).
- **Lane B — true end-to-end CLI validation with a stub provider** (the owner's
  "test it end to end"): drive `halfblood annotate` (PDF fixture AND an EPUB) through
  the REAL CLI with a deterministic stub provider (no API key), assert the output
  artifacts end-to-end (pages annotated, marks present, report counts, EPUB validity;
  reuse reader-lab structural assert patterns). This closes the E2E gap that has
  existed since v0.1.0 without needing the OpenRouter key.
- **Lane C — `--dry-run` + streaming per-page progress** (CLI UX pair from the
  improvement list): plan-JSON output without rendering; per-page progress callbacks.
- (Config-file support is a candidate LATER lane — memory warns: config resolution
  currently reads real cwd/user config in tests; that lane MUST add injectable paths.)
Lanes A and B are independent (worktrees); C after A (both touch generation/CLI).

## Still owner-gated (unchanged)
Product validation with a REAL model (OpenRouter key), pushing anywhere, `M CLAUDE.md`,
the 29g owner queue (2 agent frontmatter fixes, audit historical label, scripts/ in the
documented gate line).

## Verification (state this brief was written against)
| Claim | Command | Result |
|---|---|---|
| main @ `27f93d2` | `git rev-parse HEAD` | `27f93d29…` |
| 1357 green / ruff / mypy | run at Session-29 close (same HEAD) | all clean |
| Guards exist | merges `d90baea`/`a8bef24`/`5d2158e`/`8ffcda6`/`f7a2c75`/`d7b090d` | on the respective mains |
| Roadmap staleness example | NL1 merged cross-node DOM (design doc) vs roadmap item | roadmap predates it — probe first |

## Other Notes
- Rollback chain and tags: see Session 29 FINAL handoff (previous pointer entry).
- Never push. Local only. Lane handoff dir `thoughts/shared/handoffs/lanes/` — force-add
  (`git add -f`) like all thoughts/ files, ONLY at lane close.
