---
date: 2026-07-16T20:55:18-04:00
researcher: Claude (Opus 4.8) — controller session
git_commit: 2b274ae133d89469e3e8d373f0fc5ed5d0b2e978
branch: main
repository: half-blood-prince (local-only) + dev-harness (pushed, private)
topic: "Session 19 — hbp P2-T2 merged (re-scoped); dev-harness codex-safe safety suite built + pushed; P2-T3 next"
tags: [session-checkpoint, phase2, p2-t2, p2-t3, dev-harness, codex-safe, goal-loop, safety-tests]
status: complete
last_updated: 2026-07-16
type: handoff
---

# Session 19 — hbp P2-T2 merged (re-scoped, 667 green); dev-harness codex-safe suite pushed; P2-T3 next

> Supersedes `2026-07-16_17-52-10_session18-...`. Two repos in play: **half-blood-prince**
> (`main` @ `2b274ae`, 667 green, local-only) and **`~/dev-harness`** (`62d9fbb`, pushed to
> the PRIVATE GitHub repo). **Read "⚠️ On-disk-only state" — the `/goal` hardening is still NOT
> in git.**

## Task(s)

1. ✅ **hbp P2-T2 (re-scoped)** — quote-selector normalization accessors + offset validation.
   Merged `2b274ae` (feat `f178c05`). Gate 642 → **667**. A HEAD probe showed P1-T1 already
   delivered ~2/3 of the plan's P2-T2; owner approved re-scoping to the genuine 2-item delta.
2. ✅ **dev-harness `#3`** — deterministic safety-regression suite for `codex-safe.sh`
   (`tests/test-codex-safe.sh`, 34 checks). Committed + **pushed** (`38bb4b3` suite,
   `62d9fbb` discoverability wiring + vision-doc update).
3. ⏳ **hbp P2-T3** — score all target candidates + reject ambiguity — NOT started. **Next hbp
   task. PROBE HEAD FIRST** (`matching.py` already ships `find_all` + `MAX_CANDIDATES`, so it is
   likely front-run like P2-T2 was).
4. ⏳ **Research better `/goal` prompting (owner request, this session).** Have a **Sonnet
   research subagent** investigate best-practice prompting methods for the `/goal` SDD loop —
   specifically (a) how it orchestrates **subagents** (the Opus review agent's prompt in step 7,
   any driver subagent), and (b) how it dispatches **Codex** (brief structure, the NO-DELETE
   contract, confinement flags, fix-brief re-dispatch). Output = concrete edits to improve
   `/goal` SKILL.md prompting reliability/quality. Not started.
5. ⏳ **OPEN DECISION (carried):** the "versioned" model id (arch §4.4) — `claude-sonnet-5` is an
   alias, not a pinned dated id. Blocks hbp v0.1.0. Verify against live Anthropic docs
   (`claude-api` skill) before acting.

## ⚠️ On-disk-only state (read before resuming — easy to lose)

- **`.claude/skills/goal/SKILL.md` is hardened but UNCOMMITTED by design** (`.claude/` is in
  hbp's never-commit set; loop step 8 forbids committing it; the SDD session reverts `.claude/`
  edits). **Unchanged this session** — I used it as-is. Its steps 3/4/5/7 controls
  (discriminating check on the controller's own test edits, NO-DELETE contract + confined
  `codex-safe.sh` dispatch, whole-tree deletion sweep, Opus review of the controller test delta)
  are present. **Integrity check:** `sha256sum .claude/skills/goal/SKILL.md` →
  `183bf46b0e60224b8ee1e9fc73f8ec25b960f1628bbccefcc7c43b9947d9c8d0` (this session). If it is
  gone/reverted next session, reapply from handoff `2026-07-16_17-52-10_...` + the postmortem
  `docs/postmortems/2026-07-16-controller-test-edits-unguarded.md`.
- **`.superpowers/sdd/progress.md`** (Session 19 entry) and **`.superpowers/sdd/*.testsums`** are
  gitignored scratch. The **P2-T2 STATUS marker in the plan** and the whole
  `docs/superpowers/plans/2026-07-11-phase2-3-implementation-plan.md` are untracked/never-commit.
- **The probe-first lesson is now ALSO in durable memory** (survives `git clean`/fresh clone):
  `~/.claude/projects/-mnt-c-Users-Trey-Downloads-half-blood-prince/memory/probe-head-before-phase2-briefs.md`.
- The **canonical, durable copy** of the Codex-safety mechanism lives in *dev-harness*
  (committed + pushed): `scripts/codex-safe.sh` + now `tests/test-codex-safe.sh`.

## Critical References

1. `docs/superpowers/plans/2026-07-11-phase2-3-implementation-plan.md` — **P2-T3 at line 52**
   (P2-T2 marked DONE at line 32). 17 tasks remain: P2-T3→T9 + all of Phase 3 (P3-T1→T10).
2. `docs/superpowers/specs/2026-07-11-full-project-architecture.md` — §§5.5/5.9/7.2/9 (P2-T3
   scoring); §6.1 (the semantic-v2 surface P1-T1 built).
3. `src/halfblood/documents/matching.py` — `find_all` (ordered multi-candidate) + `MAX_CANDIDATES`;
   likely front-runs P2-T3's scoring substrate.
4. `~/dev-harness/scripts/codex-safe.sh` + `~/dev-harness/tests/test-codex-safe.sh` — the confined
   dispatch wrapper and its new regression suite (run the suite after editing the wrapper).
5. Prior handoff `thoughts/shared/handoffs/2026-07-16_17-52-10_session18-...md`.

## Recent changes

**half-blood-prince (committed on `main`):**
- `src/halfblood/models/annotations.py:41-70` — `TargetSelector` gains 3 `normalized_*`
  `@property` views (delegate to `matching.normalize`; NOT serialized) + a `_validate_offset_order`
  `@model_validator(mode="after")` (start ≤ end). Merge `2b274ae`, feat `f178c05`.
- `tests/test_quote_selector.py` — NEW, 22 selector-contract tests (incl. a `model_computed_fields
  == {}` guard so the accessors can never silently serialize).
- `tests/test_plan_migration.py` — +81 lines: byte-frozen `GOLDEN_V2_DEFAULTS_JSON` + no-normalized-key
  / ordered-offset / absent-target-exact-only guards (P2-T2 clause 7 migration stability).
- (scratch/uncommitted) `.superpowers/sdd/progress.md` Session 19; plan P2-T2 STATUS marker;
  `.superpowers/sdd/p2-t2-brief.md` + `p2-t2-report.md` + `p2-t2.testsums`.

**~/dev-harness (committed + pushed):**
- `tests/test-codex-safe.sh` — NEW, first tests in the repo (`38bb4b3`).
- `scripts/codex-safe.sh` header — "run `bash tests/test-codex-safe.sh` after editing" pointer;
  `docs/design/harness-vision.md` — Week-1 item 3 marked DONE + gap-analysis row updated (`62d9fbb`).

**memory:** `probe-head-before-phase2-briefs.md` — NEW (+ MEMORY.md index line).

## Learnings

- **P1-T1 front-ran the arch §6.1 surface.** hbp Phase-2 tasks are **verify-extend, not
  greenfield**. Author the task's test-first assertions and run them against HEAD as a throwaway
  probe *before* writing the brief; pin the brief to what actually fails. Surface the empirical
  delta to the owner for a re-scope decision. (P2-T2 collapsed from a full task to 2 additions.)
- **Testing `codex-safe.sh` deterministically:** put a **fake `codex` stub on PATH** that records
  argv/stdin and performs a scripted mutation. This runs the wrapper's real logic hermetically
  (no network, no real Codex). Non-vacuity was *proven* by a real harness bug mid-build: a
  non-exported env var (`FAKE_CODEX_ACTION`) made the stub inert, so the `exit 3` guarantee
  assertions failed until fixed — evidence the checks depend on the wrapper's sweep, not
  incidental state.
- **`codex-safe.sh` guarantees vs gaps (from the suite):** GUARANTEES = fail-closed args,
  correct sandbox/model/network flags, NO-DELETE preamble, tracked delete/rename restore (exit 3),
  Codex rc passthrough. GAPS (baseline for dev-harness weeks 2–4) = untracked-delete NOT recovered
  (commit before dispatch), non-git workspace skips the sweep, in-workspace edit NOT reverted /
  no per-path allowlist, no stale-base concept. Kernel sandbox enforcement is out of scope (needs
  a live run).
- **Codex CLI is v0.144.5** already — the prior handoff's pending `npm i -g @openai/codex` bump is moot.

## Verification

| Claim | Command run this session | Result |
|---|---|---|
| hbp gate green (fresh re-run) | `.venv/bin/pytest tests/ -q` | `667 passed, 22 warnings in 36.25s` |
| hbp HEAD | `git rev-parse HEAD` | `2b274ae133d89469e3e8d373f0fc5ed5d0b2e978` |
| P2-T2 merge is non-empty | `git show --stat HEAD` (earlier) | merge `2b274ae`, 3 files, +304 |
| hbp task-scoped tree clean | `git status --porcelain -- src tests eval` | empty |
| hbp full status = never-commit set only | `git status --porcelain` | ` M .claude/skills/goal/SKILL.md`, ` M CLAUDE.md`, `?? .claude/skills/halfblood-roadmap/`, `?? docs/superpowers/plans/...` |
| rollback tag exists | `git tag -l pre-overnight-2026-07-16` | present (@ `27c70e2`) |
| feat merges since tag (cap awareness) | `git log pre-overnight-2026-07-16..main --oneline \| grep -c feat:` | `1` |
| hbp has no remote (never push) | `git remote -v` | empty |
| `/goal` hardening present (on-disk) | `grep -nE "discriminating empirical\|NO-DELETE contract\|deletion sweep\|controller's OWN test delta" .claude/skills/goal/SKILL.md` | 4 hits at 114/122/133/159 |
| `/goal` SKILL.md integrity | `sha256sum .claude/skills/goal/SKILL.md` | `183bf46b0e60224b8ee1e9fc73f8ec25b960f1628bbccefcc7c43b9947d9c8d0` |
| dev-harness suite green (fresh) | `bash tests/test-codex-safe.sh` | `RESULT: 34 passed, 0 failed` |
| dev-harness HEAD | `git -C ~/dev-harness rev-parse HEAD` | `62d9fbba4fc81d485f229bce28a2e459ee0999a5` |
| dev-harness pushed / in sync | `git -C ~/dev-harness status -sb` | `## main...origin/main` (no ahead/behind) |
| probe-first memory saved | `ls ~/.claude/projects/.../memory/probe-head-before-phase2-briefs.md` | present |

## Artifacts

- hbp (committed): `src/halfblood/models/annotations.py`, `tests/test_quote_selector.py`,
  `tests/test_plan_migration.py` (merge `2b274ae`).
- hbp (scratch, on-disk): `.superpowers/sdd/p2-t2-brief.md`, `p2-t2-report.md`, `p2-t2.testsums`,
  `progress.md` (Session 19), plan STATUS marker. `/goal` SKILL.md (hardened, uncommitted).
- dev-harness (pushed): `tests/test-codex-safe.sh`, `scripts/codex-safe.sh` (header),
  `docs/design/harness-vision.md`.
- memory: `probe-head-before-phase2-briefs.md`.
- Rollback tags (hbp): `pre-overnight-2026-07-16` @ `27c70e2`, `pre-phase2-2026-07-16` @ `7ade9cd`.
- Merged hbp branches (safe to delete): `phase2-t2` (+ older `phase1-*`, `phase2-t1`).

## Action Items & Next Steps

1. **hbp P2-T3** (score candidates + reject ambiguity; plan line 52; depends P2-T1/P2-T2). Runs
   under the hardened `/goal`. **PROBE HEAD FIRST** per the probe-first lesson — `matching.py`'s
   `find_all`/`MAX_CANDIDATES` likely front-ran the scoring substrate.
2. **Research better `/goal` prompting (Sonnet subagent)** — owner request. Investigate
   best-practice prompting for the loop's **subagent** orchestration (the step-7 Opus reviewer
   prompt; whether a Sonnet driver subagent should be used per the lean model) and its **Codex**
   dispatch (brief structure, NO-DELETE contract, confinement, fix-brief re-dispatch). Deliver
   concrete `/goal` SKILL.md prompt edits. (Do NOT auto-apply — `.claude/` is never-committed;
   changes land on-disk and must be re-verified.)
3. **dev-harness weeks 2–4** — turn the documented gaps into the §5.4 "staging, inspect, import"
   behavior (disposable worktree, allowed_paths enforcement, stale-base detection), each backed by
   a `test-codex-safe.sh` case.
4. **OPEN DECISION — versioned model id** (arch §4.4); verify vs live Anthropic docs; blocks v0.1.0.
5. **CLAUDE.md Medium/Low product-bug backlog** — several fold into Phase 2 (repeated-match,
   collision, EPUB multi-node); the rest (retry ownership, async page processing) remain.

## Other Notes

- **Two-repo hygiene:** hbp is local-only (**never push**). dev-harness IS pushed (private). A
  `codex exec` for hbp uses `-C <hbp>`; for the harness uses `-C ~/dev-harness`. Never cross them.
- Codex dispatch is **always** via `~/dev-harness/scripts/codex-safe.sh` (confined, NO-DELETE).
  NEVER `--dangerously-bypass-*` or `--add-writable-dir`.
- WSL `/mnt/c`: `.venv/bin/…`; `git show --stat HEAD` after every merge; `git reset --hard` on main
  is hook-blocked (use `--mixed`); `.claude/settings.local.json` bypass is intentional; `thoughts/`
  is gitignored (handoff force-added with `git add -f`).
- A bare `/goal` next session advances hbp Phase 2 (reads the active plan → P2-T3). For dev-harness
  work, do NOT use `/goal`; drive via the harness's own tiered process (T2 in-conversation).
