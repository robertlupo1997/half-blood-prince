---
date: 2026-07-16T22:50:06-04:00
researcher: Claude (Opus 4.8) — controller session
git_commit: 0f336de10723a4b27a66fb2ce9a9b4315c86a0b8
branch: main
repository: half-blood-prince (local-only)
topic: "Session 20 — hbp P2-T3 merged (candidate scoring + ambiguity rejection); first-night cap reached; P2-T4 next"
tags: [session-checkpoint, phase2, p2-t3, p2-t4, goal-loop, candidate-scoring, ambiguity, first-night-cap]
status: complete
last_updated: 2026-07-16
type: handoff
---

# Session 20 — hbp P2-T3 merged (694 green); FIRST-NIGHT CAP REACHED; P2-T4 next

> Supersedes `2026-07-16_20-55-18_session19-...`. One repo in play:
> **half-blood-prince** (`main` @ `0f336de`, 694 green, local-only). **The `/goal` loop is NOT
> blocked.** The human first-night cap was replaced (owner-approved, at this session's tail)
> with an **autonomous chain-audit gate** (`AUDIT_EVERY = 3`): the window is at **2/3**, so the
> next `/goal` proceeds straight to **P2-T4**, and after it merges (window → 3) a plan-independent
> Opus **chain-audit** fires automatically over the P2-T2→P2-T4 chain (CLEAN → advance baseline +
> continue; BLOCKER → bounded auto-fix or STOP-FLAG). The `/goal` SKILL was edited on-disk this
> session — **new sha `c42a5f9d…`** (see On-disk-only state).

## Task(s)

1. ✅ **hbp P2-T3 — Score all target candidates + reject ambiguity.** Merged `0f336de`
   (feat `699ea9e`). Gate 667 → **694**. Ran the full `/goal` lean loop: probe → brief
   (interpretation B, controller-authored after a sub-driver revision didn't land) → Codex
   build → Opus review (found a real blocker) → **test-first fix loop** → fresh Opus re-review
   → merge. Details in Learnings.
2. ⏳ **hbp P2-T4 — Resolve PDF targets to ordered multi-quad anchors.** NOT started. Next hbp
   task (plan line 66; depends P2-T3). **PROBE HEAD FIRST** per the probe-first lesson.
3. ⏳ **CARRIED from Session 19 — OPEN DECISION: the "versioned" model id** (arch §4.4).
   `claude-sonnet-5` is an alias, not a pinned dated id. Blocks hbp v0.1.0. Verify against live
   Anthropic docs (`claude-api` skill) before acting. Untouched this session.
4. ⏳ **CARRIED from Session 19 — owner-requested `/goal` prompting research** (Sonnet subagent).
   Investigate best-practice prompting for the loop's subagent orchestration (step-7 Opus
   reviewer; whether a Sonnet driver subagent should be used) and its Codex dispatch (brief
   structure, NO-DELETE contract, confinement, fix re-dispatch). Deliver concrete `/goal`
   SKILL.md edits. **Do NOT auto-apply** — `.claude/` is never-committed; changes land on-disk
   and must be re-verified. Untouched this session.

## ⚠️ On-disk-only state (read before resuming — easy to lose)

- **`.claude/skills/goal/SKILL.md` is hardened AND was EDITED this session, still UNCOMMITTED by
  design** (`.claude/` is in hbp's never-commit set; loop step 8 forbids committing it). **Change
  this session:** the human "First-night cap" section was replaced with the **Autonomous
  chain-audit gate** (owner-approved) — periodic plan-independent Opus audit every `AUDIT_EVERY`
  (=3) merges; CLEAN → advance baseline + auto-continue; BLOCKER → bounded auto-fix (max 2 Codex
  attempts, ≤2 blockers) else STOP-FLAG. The step-1 orient + section title reference it. **New
  integrity check:** `sha256sum .claude/skills/goal/SKILL.md` →
  `c42a5f9d27ba51794285ad34fc235710635ffd301327f763b0c5318fd6252eaa`. If gone/reverted (an SDD
  session reverts `.claude/`), the loop falls back to the OLD human cap=2 — reapply the chain-audit
  edit (this handoff's Recent-changes describes it) + the base hardening from handoff
  `2026-07-16_17-52-10_...` + postmortem `docs/postmortems/2026-07-16-controller-test-edits-unguarded.md`.
- **`.superpowers/sdd/progress.md`** (Session 20 entry), the plan's P2-T3 DONE STATUS marker,
  and `.superpowers/sdd/p2-t3-*.md` (brief, fix-brief, reports, testsums) are gitignored/
  never-commit scratch.
- The whole `docs/superpowers/plans/2026-07-11-phase2-3-implementation-plan.md` is
  untracked/never-commit; its P2-T3 heading now carries a DONE marker.

## Critical References

1. `docs/superpowers/plans/2026-07-11-phase2-3-implementation-plan.md` — **P2-T4 at line 66**
   (P2-T3 marked DONE at line 52). 16 tasks remain: P2-T4→T9 + all of Phase 3 (P3-T1→T10).
2. `docs/superpowers/specs/2026-07-11-full-project-architecture.md` — §§3.1–3.2, 5.5–5.6,
   7.2–7.3 (P2-T4 PDF multi-quad anchors); §5.5 line 421 (ranking factors); §6.1 (selectors).
3. `src/halfblood/documents/matching.py` — the P2-T3 scorer (`score_candidates`, exactness
   ladder, ambiguity logic) that P2-T4's anchor resolver consumes.
4. `.superpowers/sdd/progress.md` (Session 20) + prior handoff `2026-07-16_20-55-18_session19-...md`.

## Recent changes

**half-blood-prince (committed on `main`, merge `0f336de` / feat `699ea9e`):**
- `src/halfblood/documents/matching.py` (+247) — NEW `score_candidates(selector, text, *,
  legacy_exact_only=False)` returning `MatchResult` | `AmbiguousResult` | `NoMatchResult`;
  helpers `_exactness_tiers` (parity with `document_processor._search_variants`),
  `_find_normalized_occurrences`, `_context_score`, `_offset_score`, `_candidate`; dataclasses
  `ScoredCandidate` (incl. `exactness_tier`, `reason`), the 3 result types; constants
  `MIN_CONTEXT_SCORE = 0.0`, `AMBIGUITY_MARGIN = 0.15`. `ScoringOutcome` union alias.
- `src/halfblood/documents/__init__.py` (+16) — exports the 8 new public symbols.
- `tests/test_candidate_scoring.py` (NEW, 27 tests) — 23 within-tier scenarios + 3 exactness-
  ladder tests + `test_proximity_breaks_context_tie` (the fix-loop regression) + rebuilt
  `test_offset_score_populated_in_genuinely_ambiguous_candidates`.

**scratch/uncommitted:** `.superpowers/sdd/p2-t3-brief.md`, `p2-t3-fix-brief.md`,
`p2-t3-report.md`, `p2-t3-fix-report.md`, `p2-t3.testsums`; progress.md Session 20; plan DONE marker.

**`.claude/skills/goal/SKILL.md` (on-disk, never-committed) — chain-audit gate (owner-approved):**
Replaced the "First-night safety" section (§ retitled *Autonomous chain-audit gate*) and its
step-1 orient reference. New behavior: at `AUDIT_EVERY` (=3) feat-merges since the newest
`pre-overnight-*` tag, spawn a **fresh `Agent(general-purpose, model:"opus")`** that reads the
**plan + spec (NOT the briefs)** + the cumulative window delta (`git diff <baseline>..HEAD -- src
tests`) + the task list, hunting cross-task compounding / correctness / scope-creep / weak tests;
returns `{verdict: CLEAN|BLOCKER, findings}`. CLEAN → `git tag pre-overnight-<ts>` at HEAD (window→0)
+ continue. BLOCKER → per-finding bounded auto-fix on a `fix/chain-audit-<ts>` branch (failing
regression test + tripwire re-snapshot → Codex ≤2 attempts → gate → fresh Opus re-review → merge
`--no-ff`); all clean → advance baseline + continue; else / >2 blockers → STOP-FLAG. Loop now runs
unbounded until plan-complete or STOP-FLAG. Motivated by memory `brief-seeded-reviews-not-plan-independent`.

## Learnings

- **P2-T3 was NOT front-run** (unlike P2-T2). The substrate (`find_all`/`MAX_CANDIDATES`/
  `NormalizedText`/P2-T2 selectors) existed; the scorer did not. Probe-first still paid off: it
  pinned the substrate boundary (build ON it) and the demotion sites (`_search_variants` at
  `document_processor.py:317`, `epub_processor.py:271` — superseded by the scorer, physical
  cutover deferred to P2-T8/T9).
- **Scope correction A→B at the brief gate.** The sub-driver's first brief scoped the scorer to
  the *full quote only* (reading A). That drops plan line 60's "the full exact quote outranks
  every shortened candidate" (untestable without shortened candidates in the scored set) and
  §5.5's "exactness" factor. Ruled **B**: build the tier-dominant exactness ladder. Principle:
  a reading that requires deleting a plan-mandated test is the wrong reading.
- **The gate is green + review-passed is NOT sufficient — a blocker slipped the first Opus
  review.** The initial build decided ambiguity on `context_score` alone, so `offset_score`
  never changed the match-vs-ambiguous outcome (inert). That drops plan line 60's "proximity
  breaks only otherwise equal scores" and defeats §6.1 (offsets exist to disambiguate repeated
  phrases). **Opus reviewer #1 APPROVED reading-A**; the controller's `advisor` overruled it as
  a blocker (both reviews had started from the controller-authored brief, which encoded A — not
  independent of A's framing; the only brief-independent signal, the plan text, is B). Fix loop
  (test-first → Codex fix → **fresh** Opus re-review #2 APPROVE) made proximity break context
  near-ties.
- **Why reusing `AMBIGUITY_MARGIN` (0.15) for both context and offset near-tie bands is safe:**
  `_context_score = agreements/checks` is quantized to `{0.0, 0.5, 1.0}`; the smallest nonzero
  context gap (0.5) far exceeds the margin (0.15), so context only ever *near*-ties at exactly
  equal — proximity therefore only ever breaks a **true** context tie, never overrides a real
  context difference. **This correctness is coupled to that quantization: if `context_score`
  ever becomes continuous, or a separate `OFFSET_MARGIN` splits out, re-check that
  `AMBIGUITY_MARGIN < 0.5`.**
- **Sub-driver reliability:** the Sonnet driver authored an excellent first brief + tests and
  correctly *flagged* the A-vs-B decision, but a later "revision applied" report did NOT match
  the tree (brief still reading A; new tests absent — the `subdriver-reports-need-tree-
  verification` pattern). Controller took over the brief + 3 tests directly. Always grep the
  tree; never trust "corrections applied."

## Verification

| Claim | Command run this session | Result |
|---|---|---|
| hbp HEAD | `git rev-parse HEAD` | `0f336de10723a4b27a66fb2ce9a9b4315c86a0b8` |
| gate green on `main` (fresh, post-merge) | `.venv/bin/pytest tests/ -q` | `694 passed, 22 warnings` |
| ruff clean on `main` | `.venv/bin/ruff check src tests eval --no-cache` | `All checks passed!` |
| mypy clean on `main` | `.venv/bin/mypy src/halfblood` | `Success: no issues found in 24 source files` |
| merge is non-empty | `git show --stat HEAD` | merge `0f336de`, 3 files (+855) |
| P2-T3 fix regression passes | `.venv/bin/pytest ...::test_proximity_breaks_context_tie ...::test_offset_score_populated_in_genuinely_ambiguous_candidates -q` | `2 passed` |
| task-scoped tree clean | `git status --porcelain -- src tests eval` | empty |
| full status = never-commit set only | `git status --porcelain` | ` M .claude/skills/goal/SKILL.md`, ` M CLAUDE.md`, `?? .claude/skills/halfblood-roadmap/`, `?? docs/superpowers/plans/...` |
| `/goal` SKILL.md integrity (EDITED this session — chain-audit gate) | `sha256sum .claude/skills/goal/SKILL.md` | `c42a5f9d27ba51794285ad34fc235710635ffd301327f763b0c5318fd6252eaa` |
| chain-audit window (`AUDIT_EVERY=3`; NOT blocked) | `git log pre-overnight-2026-07-16..main --oneline \| grep -c feat:` | `2` (2/3 → next `/goal` runs P2-T4; audit fires at 3) |
| rollback tag exists | `git tag -l pre-overnight-2026-07-16` | present (@ `27c70e2`) |
| hbp has no remote (never push) | `git remote -v` | empty |
| tripwire clean (Codex touched zero tests/) | `sha256sum -c --quiet .superpowers/sdd/p2-t3.testsums` + added/removed diff | both clean, exit 0 |
| Codex src scope | `git status --porcelain -- src` | only `documents/matching.py` + `documents/__init__.py` |

## Artifacts

- hbp (committed): `src/halfblood/documents/matching.py`, `src/halfblood/documents/__init__.py`,
  `tests/test_candidate_scoring.py` (merge `0f336de`).
- hbp (scratch, on-disk): `.superpowers/sdd/p2-t3-brief.md`, `p2-t3-fix-brief.md`,
  `p2-t3-report.md`, `p2-t3-fix-report.md`, `p2-t3.testsums`, `progress.md` (Session 20),
  plan P2-T3 DONE marker. `/goal` SKILL.md (hardened, uncommitted).
- Rollback tags (hbp): `pre-overnight-2026-07-16` @ `27c70e2` (the cap baseline),
  `pre-phase2-2026-07-16` @ `7ade9cd`.
- Merged hbp branches (safe to delete): `phase2-t3` (+ older `phase1-*`, `phase2-t1/t2`).

## Action Items & Next Steps

0. **✅ NO MANUAL UNBLOCK NEEDED — the human cap is now the autonomous chain-audit gate**
   (owner-approved change this session; on-disk in the `/goal` SKILL, new sha `c42a5f9d…`). The
   window (feat merges since `pre-overnight-2026-07-16`) is at **2/3** (`AUDIT_EVERY=3`), so a bare
   `/goal` next session proceeds straight to **P2-T4**. After P2-T4 merges (window → 3), the loop
   auto-spawns a **fresh plan-independent Opus chain-audit** over the P2-T2→P2-T4 chain: CLEAN →
   `git tag pre-overnight-<ts>` at HEAD + continue autonomously; BLOCKER → bounded auto-fix (fix
   branch, test-first, Codex ≤2 attempts, fresh Opus re-review) else STOP-FLAG (also STOP-FLAG if
   >2 distinct blockers). Owner can stop the loop anytime; every `pre-overnight-*` tag stays a
   rollback point. (If the SKILL gets reverted, this falls back to the old human cap=2 — see
   On-disk-only state.)
1. **hbp P2-T4** (PDF targets → ordered multi-quad anchors; plan line 66; depends P2-T3). Runs
   under the hardened `/goal`. **PROBE HEAD FIRST** — check what `document_processor.find_text_rect`
   / `_find_contiguous_hit_group` already ship before writing the brief.
2. **CARRIED — owner-requested `/goal` prompting research** (Sonnet subagent; do NOT auto-apply).
3. **CARRIED — OPEN DECISION: versioned model id** (arch §4.4); verify vs live Anthropic docs;
   blocks v0.1.0.
4. **Non-blocking follow-up (P2-T3):** the `AMBIGUITY_MARGIN` inline comment
   (`matching.py:42-43`) says "context_score difference" but the constant now also bands the
   offset near-tie. Extend the comment or split a named `OFFSET_MARGIN` next time P2 touches
   `matching.py` (and see the quantization caveat in Learnings).
5. **CLAUDE.md Medium/Low product-bug backlog** — repeated-match/collision/EPUB-multi-node fold
   into later Phase-2 tasks; retry-ownership + async page processing remain.

## Other Notes

- **Two-repo hygiene:** hbp is local-only (**never push**). `~/dev-harness` IS pushed (private,
  `62d9fbb`) — untouched this session. Codex dispatch for hbp is always via
  `~/dev-harness/scripts/codex-safe.sh --workspace <hbp>` (confined, NO-DELETE); NEVER
  `--dangerously-bypass-*` or `--add-writable-dir`.
- **Attended-run deviation from the lean model:** this session drove on Opus (controller) rather
  than spawning a Sonnet driver for the whole loop, because the task was subtle and attended.
  The controller authored the brief + tests directly; Codex built src; Opus reviewed. For an
  unattended overnight `/loop /goal`, prefer the Sonnet-driver division per the SKILL.
- **WSL `/mnt/c`:** `.venv/bin/…`; `git show --stat HEAD` after every merge; `git reset --hard`
  on main is hook-blocked (use `--mixed`); `.claude/settings.local.json` bypass is intentional;
  `thoughts/` is gitignored (this handoff force-added with `git add -f`).
