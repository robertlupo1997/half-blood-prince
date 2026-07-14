---
date: 2026-07-14T19:27:36-04:00
researcher: Claude (Opus 4.8) — controller session
git_commit: 22b9853f19dfacae5cc0eefc65fe2c0fff7a0ae0
branch: main
repository: half-blood-prince
topic: "Sessions 14–16 — P1-T6/T7/T8 built via lean Codex loop + Sonnet sub-driver, all merged to local main; /goal skill hardened 4×; Codex adversarial-review flagged a tripwire gap"
tags: [phase1, structured-output, openai-compat, provider-registry, provider-doctor, plan-io, goal-loop, sonnet-sub-driver, tripwire, adversarial-review]
status: complete
last_updated: 2026-07-14
type: handoff
---

# Handoff: P1-T6/T7/T8 merged; /goal loop hardened; adversarial-review tripwire gap open

> Three SDD tasks were built and merged this run — **P1-T6** (structured-output
> negotiation + bounded parsing), **P1-T7** (OpenAI-compatible adapter + provider
> registry), **P1-T8** (provider doctor + atomic plan/report persistence). All via the
> lean Codex loop; T7/T8 used the **"Stay Opus, spawn Sonnet sub-driver"** cost model
> (owner's choice: preserve Opus usage). Gate on `main` is green (**495 passed**, ruff
> `--no-cache` clean, mypy clean, zero `anthropic` SDK imports). **Nothing pushed.** A
> Codex adversarial review at the end flagged ONE open item (the test tripwire is not
> recursive) — recorded below, deliberately NOT fixed (review was review-only).

## Task(s)

1. ✅ **P1-T6 merged** (structured-output negotiation + bounded parsing, arch §4.3).
   `StructuredOutputPolicy` + bounded parsers (tool/json-schema/prompt) in
   `src/halfblood/generation/structured_output.py`. Opus gate review found a real
   `_fenced_blocks` defect (≥2 non-json fences before a json fence → false raise); fixed
   via a regression test + Codex fix. Merged `9e0cdcb`.
2. ✅ **P1-T7 merged** (OpenAI-compatible HTTP adapter + provider registry, arch §§4.1/4.3/4.4).
   `src/halfblood/generation/providers/openai_compat.py` + `src/halfblood/generation/registry.py`
   (`build_provider`, 6 profiles). OpenAI wire contract verified from live docs (Context7
   was down → Haiku agent verified). Opus review PASS. Merged `e682e2a`. A ruff cached
   false-green briefly let lint-dirty test imports merge; caught + fixed forward (`09e57c7`).
3. ✅ **P1-T8 merged** (provider doctor + saved plan/report boundary, arch §§4.4/6.2/9).
   `src/halfblood/plan_io.py` (atomic save/load + v1→v2 migration) + a `providers doctor`
   CLI group in `src/halfblood/cli.py`. Opus review PASS (3 LOW follow-ups). Merged
   `22b9853` — but the FIRST merge produced an **empty/broken merge** from a transient WSL
   FS error; recovered (see Learnings). Gate on `main`: 495 passed.
4. ✅ **`/goal` skill hardened 4×** this run (`.claude/skills/goal/SKILL.md`, uncommitted —
   `.claude/` is never auto-committed): (a) mandatory fresh Opus re-review after any fix
   round; (b) ruff `--no-cache` in the gate; (c) re-sort controller test imports + re-snapshot
   before gating; (d) post-merge `git show --stat HEAD` non-empty check.
5. ⏳ **NOT done: Codex adversarial-review finding** — the tripwire (`sha256sum tests/*.py`)
   is not recursive/addition-aware. Recorded as Action Item #1. **Deliberately not fixed**
   (the review command is review-only).
6. ⏳ **NOT started: P1-T9** — the last Phase-1 task (route CLI + eval through the provider
   seam; closes AUD-34). First task to wire `build_provider` into annotate/preview/eval.

## Critical References

1. `docs/superpowers/plans/2026-07-11-phase0-1-implementation-plan.md` — P1-T9 section is
   the next task's spec (and P1-T1…T8 for context).
2. `docs/superpowers/specs/2026-07-11-full-project-architecture.md` §§2.6, 4.4, 9 Phase 1 —
   ground truth for P1-T9 (the provider seam + eval judge independence + AUD-34).
3. `.claude/skills/goal/SKILL.md` — the lean-loop playbook, hardened this run. Read before
   running the loop or continuing.
4. `.superpowers/sdd/progress.md` — Sessions 14/15/16 entries have the full per-task detail,
   review verdicts, non-blocking findings, and the incident write-ups.

## Recent changes (committed to `main`, in order)

- `9e0cdcb` — Merge P1-T6 (`structured_output.py` + exports; `1fc76ff` feat).
- `e682e2a` — Merge P1-T7 (`openai_compat.py` + `registry.py` + exports; `d866111` feat).
- `09e57c7` — chore: sort imports in P1-T7 test files (ruff I001 false-green fix).
- `22b9853` — Merge P1-T8 (`plan_io.py` + `providers doctor` in `cli.py`; `0585c01` feat).

## Uncommitted (intentional — do NOT auto-commit)

- `M .claude/skills/goal/SKILL.md` — the 4 hardenings this run.
- `M CLAUDE.md` — cross-session housekeeping (pre-existing, never auto-committed).
- `?? .claude/skills/halfblood-roadmap/SKILL.md`, `?? docs/superpowers/plans/2026-07-11-phase2-3-implementation-plan.md`.

## Learnings

- **Sonnet sub-driver model (T7/T8):** on an Opus session, spawn a Sonnet sub-agent to
  author the brief + failing tests, a Haiku agent for factual lookups (wire verification
  when Context7 is down — verify from live docs, never recall), and Codex to build. Opus
  spends only on the scope spec, the brief-vs-plan checkpoint, and the ONE gate review. The
  irreducible rule: Codex must never author its own tests (the test-first contract).
- **ruff isort is module-existence-dependent.** A test importing a not-yet-built
  `halfblood.X` module sorts differently once `X` exists on disk, so the sub-driver's
  pre-build ruff-clean check can't catch the post-build I001. Fix: re-sort controller test
  imports (`ruff --fix --no-cache`) + re-snapshot the tripwire AFTER the Codex build. This
  (not caching alone) was the real mechanism behind both the P1-T7 and P1-T8 lint surprises.
- **Transient WSL `/mnt/c` "Unable to write index"** can produce an *empty* merge commit
  that silently drops the whole task (P1-T8 first merge). Always `git show --stat HEAD` after
  a merge + confirm the gate shows the NEW test count. The feat commit stays safe on the
  branch; recover with `git reset --mixed <pre-merge-sha>` (NOT `--hard` — hook-blocked and
  would nuke uncommitted skill edits), restore uncommitted files, re-merge.
- **Codex adversarial review (this run) — OPEN, not fixed:** the tripwire
  `sha256sum tests/*.py` (`.claude/skills/goal/SKILL.md:73,81,101`) covers only top-level
  `tests/*.py` — it excludes `tests/fixtures/**`, nested test modules, and files ADDED after
  the snapshot. An unattended Codex run could alter/add controller-owned tests undetected.
  Recommendation: verify the full controller-owned test tree
  (`git ls-files --cached --others --exclude-standard tests/` manifest + hashes; fail on any
  Codex-authored `git status`/`git diff` under `tests/`), before enabling unattended runs.

## Verification

| Claim | Command run this session | Result |
|---|---|---|
| HEAD is the P1-T8 merge | `git rev-parse HEAD` | `22b9853f19dfacae5cc0eefc65fe2c0fff7a0ae0` |
| main history (T6→T7→T8) | `git log --oneline -6 main` | `22b9853`→`0585c01`→`09e57c7`→`e682e2a`→`d866111`→`9e0cdcb` |
| Full suite passes | `.venv/bin/pytest tests/ -q` (re-run now) | `495 passed, 11 warnings` |
| ruff clean (no false-green) | `.venv/bin/ruff check src tests eval --no-cache` | `All checks passed!` |
| mypy clean | `.venv/bin/mypy src/halfblood` | `Success: no issues found in 22 source files` |
| Anthropic SDK fully absent | `grep -rn "import anthropic\|from anthropic" src/ tests/` | `0 matches` |
| P1-T6/T7/T8 modules present | `ls …structured_output.py …openai_compat.py …registry.py …plan_io.py` | all 4 exist |
| Tripwire glob (review finding) | `grep -n "sha256sum tests/\*.py" .claude/skills/goal/SKILL.md` | lines `73, 81, 101` — top-level glob only (finding CONFIRMED) |
| First-night cap not reached | `git log pre-overnight-2026-07-14..main --oneline \| grep -c feat:` | `1` (below cap of 2) |
| Nothing pushed | `git remote -v` | empty (no remote configured) |

## Artifacts

- Source (on `main`): `src/halfblood/generation/structured_output.py`,
  `src/halfblood/generation/providers/openai_compat.py`,
  `src/halfblood/generation/registry.py`, `src/halfblood/plan_io.py`,
  edits to `src/halfblood/generation/__init__.py` and `src/halfblood/cli.py`.
- Tests (on `main`): `tests/test_structured_output.py`, `tests/test_openai_compat_provider.py`,
  `tests/test_provider_profiles.py`, `tests/test_provider_contract_shared.py`,
  `tests/test_provider_doctor.py`, `tests/test_plan_io.py`.
- SDD scratch (gitignored): `.superpowers/sdd/p1-t{6,7,8}-brief.md`, `-report`/`-codex.log`,
  `p1-t{6,7,8}.testsums`, `p1-t{7,8}-subdriver-spec.md`, `p1-t6-fix-brief.md`.
- Rollback tags: `pre-overnight-2026-07-13` (@ `51bc017`, pre-P1-T6),
  `pre-overnight-2026-07-14` (@ `09e57c7`, pre-P1-T8).

## Action Items & Next Steps

1. **(from adversarial review) Make the tripwire recursive/addition-aware** before any
   unattended `/loop /goal`. Replace `sha256sum tests/*.py` (SKILL.md steps 3/6/7) with a
   full `tests/` manifest + hashes and a "no Codex change under `tests/`" `git`-status/diff
   check. High priority *only* for unattended runs; attended runs have a human watching.
3. **Run P1-T9** (last Phase-1 task): route `annotate`/`preview`/`eval` through
   `build_provider` (the seam T7/T8 left un-wired), require an independent eval judge config,
   close AUD-34. Highest integration surface in Phase 1 (touches `cli.py`,
   `annotation_generator.py`, `eval/`) — the brief-vs-plan checkpoint matters most here.
4. **Before unattended overnight:** re-tag (`git tag -f pre-overnight-<date>` at HEAD) to
   reset the cap, then `/model sonnet` + `/loop /goal` (cheapest — driving on Sonnet, Opus
   only as the review subagent).
5. **Non-blocking P1-T8 follow-ups** (from the gate review, deferred): redact report
   `warnings` strings; validate `_hbp` container version on load; add a key-leak assertion to
   the online-doctor success test.
6. **If the owner wants `main` published:** push manually after review (nothing is pushed).

## Other Notes

- Repo on `/mnt/c` under WSL: use `.venv/bin/…`; expect occasional transient FS I/O errors
  (see Learnings — verify merges).
- `.claude/settings.local.json` `bypassPermissions` is intentional — do not "fix".
- A `PreToolUse` hook blocks `git reset --hard` on main/master — use `--mixed` for recovery.
- Codex CLI `codex-cli 0.144.1`, chatgpt-authenticated; `codex exec --sandbox
  workspace-write -m gpt-5.6-sol -c model_reasoning_effort=high` proven across P1-T6/T7/T8.
