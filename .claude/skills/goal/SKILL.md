---
name: goal
description: Use to autonomously advance the half-blood-prince SDD phase plan — runs ONE task through the lean Codex loop (brief+tests → Codex build → Opus review → auto-merge to local main). Safe for unattended `/loop` overnight runs. Invoke directly, or drive overnight with `/loop /goal`.
---

# /goal — overnight SDD lean loop

Executes **one task iteration** of the half-blood-prince spec-driven-development
loop, then returns. It is **stateless per invocation** — all state lives in git and
`.superpowers/sdd/progress.md`, so it is safe to fire repeatedly. Drive it overnight
with `/loop /goal` (self-paced). It **stops itself** when the phase plan is complete
or a stop-and-flag condition trips.

## The lean model (roles)

- **Build → Codex** (`gpt-5.6-sol`), free to Claude usage — dispatched via `codex exec`.
- **Drive → Sonnet** — picks the task, authors the brief + failing tests, dispatches
  Codex, runs the gate, merges, logs. If this session is not already Sonnet, spawn a
  Sonnet subagent (`Agent`, `model:"sonnet"`) for the driving so the expensive session
  model isn't burned on mechanical work.
- **Review → Opus** — ONE adversarial review at the gate, always a spawned
  `Agent(general-purpose, model:"opus")`. No Fable, no second orchestrator tier, no
  triple review.

Cheapest to run the driving session on Sonnet (`/model sonnet`); the review is an Opus
subagent regardless.

## Config (set by the owner, Session 13)

- **Merge:** auto-merge each green+clean task to **local `main` with `--no-ff`**. **Never push.**
- **Review model:** Opus. **Fable is NOT used in this loop.**
- **Builder:** Codex `gpt-5.6-sol`, `model_reasoning_effort=high`.

## First-night safety (advisor-mandated)

The review step checks **diff-vs-brief**, and the driver authors both the brief and
the failing tests — so **nothing independently checks brief-vs-plan-intent.** A task
the driver *misreads* can produce internally-consistent, gate-green, review-passed, and
*wrong* work that auto-merges, and the next task builds on it. This risk is highest on
under-specified later tasks and compounds across merges. Mitigations, non-negotiable
until the owner has watched the loop succeed and loosens them:

- **Rollback tag.** Before the first iteration of a run, if no `pre-overnight-*` tag
  exists at `main`'s current HEAD, create one: `git tag pre-overnight-<YYYY-MM-DD>`.
  This is the one-command rollback point (`git reset --hard pre-overnight-<date>`).
- **First-night cap = 2.** Count `feat:` merges on `main` since the newest
  `pre-overnight-*` tag (`git log <tag>..main --oneline | grep -c '^\w* feat:'`... i.e.
  merges added this run). If **≥ 2**, do NOT start another task — **stop the loop** and
  report "first-night cap reached; owner should eyeball the merged chain and loosen the
  cap before continuing." A bad brief that compounds across 2 merges is recoverable;
  across 10 is a mess.
- **Validate attended first.** The very first ever run of this loop must be watched by
  the owner (one iteration), in the exact overnight config, before any unattended use.

## One iteration

1. **Orient.** `git status` must be clean; if not → **STOP-FLAG**. Apply *First-night
   safety*: ensure the `pre-overnight-*` tag exists (create it if not), and if `feat:`
   merges since that tag have reached the cap → **stop the loop** ("cap reached"). Read
   the tail of `.superpowers/sdd/progress.md`,
   `.superpowers/sdd/phase1-orchestration-runbook.md`, and the active plan
   (`docs/superpowers/plans/…`). Identify the next **unstarted** task (P1-T6 is next as
   of Session 13) and confirm its scope against the plan before writing the brief. None
   remain → **stop the loop**, report "plan complete."
2. **Branch.** `git checkout main && git checkout -b <phaseX-tY>`.
3. **Brief + failing tests.** Author `.superpowers/sdd/<pX-tY>-brief.md` — a pinned
   interface built from the plan + `docs/superpowers/specs/…architecture.md` + the
   **live** Anthropic wire contract via the `claude-api` skill for any provider-facing
   work (never recalled from memory). Author/adjust the failing tests (**controller
   owns `tests/`; Codex must never touch them**); confirm they fail for the intended
   reason. Snapshot: `sha256sum tests/*.py > .superpowers/sdd/<pX-tY>.testsums`.
4. **Dispatch Codex.** `codex exec --sandbox workspace-write -C <repo> -m gpt-5.6-sol
   -c model_reasoning_effort=high -o .superpowers/sdd/<pX-tY>-report.md <
   .superpowers/sdd/<pX-tY>-brief.md` (run in background + Monitor if long).
5. **Tripwire.** `sha256sum -c .superpowers/sdd/<pX-tY>.testsums` — Codex touched ZERO
   test files. Mismatch → **STOP-FLAG**.
6. **Gate.** `.venv/bin/pytest tests/ -q && .venv/bin/ruff check src tests eval &&
   .venv/bin/mypy src/halfblood`. Red → author a focused fix brief, re-dispatch Codex
   (**max 2 fix attempts**). Still red → **STOP-FLAG** (never merge red).
7. **Review (Opus subagent).** Spawn `Agent(general-purpose, model:"opus")` to read the
   full diff vs the brief + wire contract and hunt correctness / scope-creep /
   hidden-behavior / weak-tests, returning `{verdict, findings}`. Real blocker → fix
   (re-dispatch Codex or controller fix) + re-review. Non-blocking findings → record
   for follow-up, do not block.
8. **Merge.** Commit `feat: … (<pX-tY>)` with **exactly** the task's files (NEVER
   `CLAUDE.md`, `.claude/`, or unrelated docs). `git checkout main && git merge --no-ff
   <branch>`. Re-run the gate on `main`. **Local only — never push.**
9. **Log.** Append a `progress.md` entry: what built, gate result, review verdict,
   non-blocking findings, next task.
10. **Continue or stop.** Tasks remain and no flag → schedule the next iteration
    (`ScheduleWakeup` if in `/loop` dynamic mode). Else → stop the loop and report.

## Safety rails (unattended)

- NEVER merge a red gate or over a review objection.
- NEVER push, force-push, delete branches, or edit committed `settings.json`
  (the bypass lives in `settings.local.json` — leave it).
- NEVER commit `CLAUDE.md`, `.claude/`, or files outside the task's pinned scope.
- **STOP-FLAG** (halt the loop, write a `progress.md` note + a handoff, don't thrash)
  on: dirty git at start, Codex failing a task twice, a gate that won't go green, a
  review blocker that can't be fixed, a tripwire mismatch, or a task the plan
  under-specifies so much the brief can't be pinned with confidence.
- Prefer a clean stop with a written record over pushing through ambiguity.

## Monitor / stop

- Watch: `tail .superpowers/sdd/progress.md`; `git log --oneline main`.
- Stop: interrupt the session, or delete the loop.
