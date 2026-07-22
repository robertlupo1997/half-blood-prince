---
date: 2026-07-22T08:30:39-04:00
researcher: Claude (Fable 5)
git_commit: 4b43925d74760c8c90a0e6d9fa7b2ed1bb7c5f04
branch: main
repository: half-blood-prince (+ dev-harness for sddctl)
topic: "Session 29 (cont. 3) — sddctl epoch journal landed in dev-harness (shadow); first receipts-wrapper live run judged accurate"
tags: [adoption, sddctl, epoch-journal, receipts, shadow-mode, harness]
status: complete
last_updated: 2026-07-22
type: handoff
---

# Handoff: Session 29d — epoch journal shadow-landed

> **hbp `main` @ `4b43925` (unchanged this unit — all work in dev-harness), 1291 green.
> dev-harness `a8bef24`: `scripts/sddctl.py` + `tests/test-sddctl.py`** — the durable
> ruling-epoch journal (adoption #1, the structural Session-28 fix), Codex-built through
> `codex-receipts.sh` (whose FIRST live receipt was judged accurate against git reality).
> Shadow mode: nothing in /goal or any driver prompt changed.

## Task(s)
1. ✅ Epoch journal (adoption #1) — dev-harness `a8bef24`. One dispatch (434s), tripwire
   5/5, suite 10/10 (contention, truncation, tamper, epoch lifecycle), **Session-28
   replay verified LIVE by controller**: retraction without executor ack → `assert-ready`
   exit 6 naming the unacked epoch; stale ack of superseded epoch → exit 5.
2. ✅ Receipts wrapper first live use — receipt matched reality 1:1 (changed_paths,
   side-effect flag, correctly excludes its own receipt file).
3. ⏳ NEXT: **sdd-driver agent definition + hooks** (adoption #3) — build SHADOW (define
   `.claude/agents/sdd-driver.md` + hook scripts + table-tests, but nothing spawns it);
   FIRST ACTIVATION is attended/owner-flagged per the study. Sketch: study §Top-5 #3.
   Then conformance gate (#4), manifests (#5), reader-lab fixtures.
4. ⏳ Product validation — blocked on an OpenRouter key (owner).

## Critical References
- `thoughts/shared/research/2026-07-21_omp-adoption-study.md` §Top-5 #3 (sdd-driver
  sketch: allowlist policy split, PreToolUse/Stop hook behaviors, validation plan).
- `~/dev-harness/scripts/sddctl.py --help` — journal commands; log path is always
  explicit: `--log <repo>/.superpowers/sdd/events.jsonl`.
- Ledger: progress.md "EPOCH JOURNAL — LANDED".

## Recent changes
- dev-harness `a8bef24`: sddctl.py (524 lines: hash-chained JSONL, per-task epochs,
  idempotent acks, flock appends, truncated-last-line tolerance, verify) +
  test-sddctl.py (300 lines, 10 tests).
- Memory `codex-standard-invocations` updated (sddctl + receipt-accuracy note).

## Learnings
- The receipts wrapper's evidence loop works end-to-end on a real dispatch — future
  driver briefs can require "attach the receipt" instead of trusting self-reports.
- sddctl deviation from the study recorded: lives in dev-harness (project-agnostic,
  explicit `--log`), not hbp `scripts/`.

## Verification (controller-run this session)
| Claim | Command | Result |
|---|---|---|
| dev-harness @ `a8bef24`, clean | `git show --stat HEAD` + porcelain | 2 files, +824; porcelain empty |
| Tripwire (5 protected files) | `sha256sum -c` tripwire2 | 5/5 OK |
| sddctl suite | `python3 tests/test-sddctl.py` | `Ran 10 tests … OK` |
| Session-28 replay | live scratchpad exercise (4 events) | ready→0; replay→6; stale ack→5; verify→OK |
| Receipt accuracy | receipt JSON vs `git status --porcelain` | 1:1 match, side_effect=true, advice=safe |
| hbp unchanged this unit | `git rev-parse HEAD` | `4b43925…` (as at 29c close) |

## Action Items & Next Steps
1. sdd-driver definition (shadow build + hermetic table-tests; NO activation) — next
   loop iteration, fresh context.
2. Owner-flagged (do NOT do autonomously): wiring /goal drivers to sddctl
   (`assert-ready` before dispatch/commit), activating sdd-driver, any hook enforcement.
3. Conformance gate (#4) and manifests (#5) after; reader-lab fixtures; product
   validation on key arrival.

## Other Notes
- Rollback: dev-harness `git revert a8bef24` (journal) / `git revert d90baea` (receipts).
  hbp rollback points unchanged (see 29c handoff).
- Never push. `M CLAUDE.md` untouchable. Dispatch artifacts archived to session scratchpad.
