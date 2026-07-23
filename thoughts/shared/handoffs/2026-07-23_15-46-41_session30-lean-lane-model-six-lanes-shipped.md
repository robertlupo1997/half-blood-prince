---
date: 2026-07-23T15:46:41-04:00
researcher: Claude (Fable 5)
git_commit: ed75c1a7897d7f68346a7de6876855848024876f
branch: main
repository: half-blood-prince
topic: "Session 30: lean E2E lane model proven — six feature lanes shipped (8 merges, 6 GO reviews, 0 blockers); sdd-driver hooks FAILED activation smoke"
tags: [lanes, async-generation, cli-e2e, dry-run, anchor-disambiguation, token-usage, persona, sdd-driver, session-close]
status: complete
last_updated: 2026-07-23
type: handoff
---

# Session 30 — the lean E2E lane model, first full run

## Task(s)

1. ✅ **Re-orient + verify baseline + tag** — baseline re-verified myself (1357 green, ruff+mypy clean, beam default, v0.1.0); `pre-overnight-2026-07-23` tagged at `2b15e1a`.
2. ✅ **Activate the guards** — Monitor armed (codex runaway, no alerts fired all session); receipts wrapper used for every Codex dispatch. **sdd-driver activation FAILED its owner-endorsed smoke** (see Learnings §1 — the single most important finding of the session).
3. ✅ **Lane A — async wave generation** (merged `592bd9c`, Opus GO): ThreadPoolExecutor wave concurrency in `generate_for_document`, default 3 clamp 1..8, k=1 ≡ sequential at prompt level; config hard-lock removed.
4. ✅ **Lane B — true E2E CLI validation** (merged `479a79c` + hardening `0eb647b`): 20 hermetic tests driving real CLI→generator→renderer→artifact with a stub provider; then hardened to page-identity routing after lane A's reviewer caught call-order luck.
5. ✅ **Lane C — --dry-run + streaming progress** (merged, Opus GO): plan JSON round-trips into `web-preview` (real loader), `on_page_done` main-thread page-ordered callback, per-page Rich bar.
6. ✅ **Lane D — PDF anchor disambiguation, issue #13** (merged `d1ddf22` + skip-fix `aae5c6b`, Opus GO): `score_candidates` wired into `_resolve_annotation_to_anchor` (v2 only); Ambiguous→fail-closed (MISSING_TARGET); NoMatch→legacy ladder; v1 untouched.
7. ✅ **Lane E — token usage aggregation** (merged, Opus GO): `UsageTotals` summed in main-thread wave assembly, `generator.usage_totals`, CLI token line in annotate/dry-run/preview; counts only, no dollar table (decided).
8. ✅ **Lane F — persona unification** (merged, Opus GO): cli.py's shadowing generic `DEFAULT_PERSONA` deleted — **the full Snape persona is now actually reachable/default via CLI** (intended behavior change); `--persona-file`; `[generation].persona/persona_file` + `HALFBLOOD_PERSONA{,_FILE}` with standard precedence. Survived a mid-lane spend-limit kill (resumed, no redispatch).
9. ⏳ **Remaining backlog** — ranked in Action Items; all lower-value than what shipped.

## Critical References

- `thoughts/shared/handoffs/2026-07-23_09-03-01_session30-brief-lean-e2e-lane-model.md` — the operating model this session executed (owner directive).
- `thoughts/shared/handoffs/lanes/` — SIX lane handoffs, one per feature, each with its own evidence/receipts (this is the lane model working as designed).
- `.superpowers/sdd/progress.md` (tail) — blow-by-blow ledger incl. every gate number and finding.

## Recent changes

All via `--no-ff` merges to local main (8): lanes A–F above plus `lane-b-stub-hardening` and `lane-d-skip-fix`. Key src surface: `annotation_generator.py` (waves, callback, usage), `cli.py` (dry-run, progress, token line, persona flags), `config.py` (concurrency unlock, persona resolution), `document_processor.py:527+` (score_candidates wiring). Test suite 1357 → **1443**.

## Learnings

1. **sdd-driver agent-frontmatter hooks are NOT honored by this Claude Code installation.** Owner-endorsed smoke: instructed driver src-edit was ALLOWED, `git commit` LANDED (empty `8319c88`, soft-reset away), no Stop-hook refusal. Cleanup surgical (`reset --soft`, targeted checkout; `M CLAUDE.md` never touched). Memory saved: `sdd-driver-hooks-not-honored`. **Do not activate sdd-driver until re-smoked on a newer installation.** Lanes ran as general-purpose sonnet drivers with orchestrator tree-diff enforcement instead — this worked (every tree-diff matched every report).
2. **The lane model held up.** 6 features end-to-end in one session, every gate green first try, 0 review blockers. The one gate per lane + tree-diff + receipts combination caught everything the old per-step ceremony would have, cheaper.
3. **Cross-lane integration is where the real bugs hid**: lane A's reviewer caught lane B's stubs passing by scheduling luck under k=3 (fixed: page-identity routing); lane D's fail-closed change silently retired an overflow-contract test via runtime `pytest.skip` (caught only because I diffed skip counts at the gate — **watch the skip count, not just the pass count**; fixed with disambiguating context that also exercises the new path).
4. **Opus reviewers idle-without-report** recurred (review-lane-c; nudge recovered). Instructing "deliver verdict as a message, do not idle" in later review prompts worked.
5. Codex scope deviation, benign but real: lane C's Codex added an unlisted `except Exception → ProviderError` wrap in `annotation_generator.py` (reviewer-verified benign; recorded).
6. Spend-limit kill mid-agent is recoverable via SendMessage resume (transcript intact) — no redispatch needed.

## Verification

| Claim | Command run this session | Result |
|---|---|---|
| main @ `ed75c1a` | `git rev-parse HEAD` | `ed75c1a7897d7f68346a7de6876855848024876f` |
| full suite green | `python -m pytest tests/ -q` (after last merge, lane F) | `1443 passed, 28 warnings` |
| ruff clean | `ruff check src tests eval scripts` (same point) | `All checks passed!` |
| mypy clean | `mypy src/halfblood` (same point) | `Success: no issues found in 42 source files` |
| beam default intact | `grep -n 'solver' src/halfblood/layout/engine.py` (session start) | `engine.py:66: solver: ... = "beam"` — solver files untouched by any lane (tree-diffs) |
| rollback tag | `git tag -l pre-overnight-2026-07-23` | exists, at `2b15e1a` |
| 6 lane handoffs | `ls thoughts/shared/handoffs/lanes/` | 6 files, lane-a … lane-f |
| tolerated dirt only | `git status --porcelain` (repeatedly) | exactly `M CLAUDE.md` + 2 known untracked |
| 8 lane branches merged | `git branch --list 'lane-*'` + merge log | all 8 listed, all in main's history |
| worktrees present | `git worktree list` | 6 agent worktrees remain (see Other Notes) |

## Artifacts

- This handoff; `HANDOFF.md` pointer updated.
- `thoughts/shared/handoffs/lanes/lane-{a,b,c,d,e,f}-*.md` (committed on their branches, merged).
- `.superpowers/sdd/lane-{a,b,c,d,e,f}-brief.md` (session-local, gitignored).
- Codex receipts in session scratchpad (lane-a/-c/-d ×2/-e/-f; all verified present).
- Memory: `sdd-driver-hooks-not-honored` (+ MEMORY.md index line).

## Action Items & Next Steps

1. **Owner: read Learnings §1** before any future sdd-driver activation attempt.
2. Remaining backlog, ranked (all fine as future lanes, none urgent): batch mode (`annotate-batch`), web-preview UX (Copy-JSON button, search/filter), config keys for `max_per_page`/`font_path`, eval-judge migration to the provider seam (Phase-5, owner-adjacent), review advisories (freeze `UsageTotals`, empty-persona-string edge test, tighten lane-D e2e-a assert).
3. Owner-gated, unchanged: OpenRouter key product validation, 29g owner queue, any push.
4. Housekeeping when convenient: `git worktree remove` the 6 agent worktrees (left in place deliberately — removing them breaks SendMessage-resume of lane agents), then optionally delete merged `lane-*` branches.

## Other Notes

- Rollback: `git reset` to tag `pre-overnight-2026-07-23` would drop all 8 merges — but NEVER `--hard` with the dirty `M CLAUDE.md` present; prefer `git revert -m 1` of individual merge commits.
- Intended behavior changes shipped this session (user-visible): default concurrency 3 (waves), bare CLI now gets the FULL Snape persona, ambiguous PDF targets now skip (MISSING_TARGET) instead of guessing first occurrence, token-usage line in CLI output.
- WSL: the Monitor pattern + TERM-exact-PID doctrine remain the standard for codex runaways (no incidents this session).
