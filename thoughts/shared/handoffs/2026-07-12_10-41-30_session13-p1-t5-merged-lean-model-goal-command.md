---
date: 2026-07-12T10:41:30-04:00
researcher: Claude (Opus 4.8) — controller session
git_commit: cf68fe51a694b4a2bc6c713200666c0f08ab2d87
branch: main
repository: half-blood-prince
topic: "Session 13 — P1-T5 reviewed + merged to main; lean orchestration model adopted; /goal overnight command built and ready to launch"
tags: [phase1, anthropic-provider, p1-t5-merged, lean-orchestration, goal-command, overnight-loop, cost-management]
status: complete
last_updated: 2026-07-12
type: handoff
---

# Handoff: P1-T5 merged, lean orchestration model adopted, `/goal` overnight loop ready

> Session 13 resumed Session 12's handoff (P1-T5 built by Codex, gate green,
> uncommitted, unreviewed). This session **reviewed P1-T5 adversarially on
> Opus, verified its wire contract against the `claude-api` skill, committed
> it, and merged it to `main`** — then, at the owner's direction, **redefined
> the orchestration model to cut Claude-usage burn** and **built a reusable
> `/goal` command** so the SDD phase plan can be driven autonomously overnight.
> Nothing is pushed to any remote.

## Task(s)

1. ✅ **P1-T5 reviewed + merged.** Committed the Session-12 WIP as `b0ae59e`
   (exactly the 10 P1-T5 files; excluded `CLAUDE.md` + tooling). Opus
   adversarial review found no blockers; wire contract (request-id header,
   refusal/`stop_details`, error body shape, `anthropic-version: 2023-06-01`,
   usage fields) confirmed correct against the authoritative `claude-api`
   skill. Merged `phase1-t5` → `main` `--no-ff` as `cf68fe5`. Gate on `main`:
   **345 passed, ruff clean, mypy clean, zero `anthropic` SDK imports.** Local
   only, not pushed.
2. ✅ **Lean orchestration model adopted (owner cost decision).** Owner runs
   out of Claude usage too often; the drain was the triple-review stack + a
   two-tier orchestrator. New model: **Sonnet drives → Codex builds (free to
   Claude usage) → ONE Opus adversarial review at the merge gate.** Dropped
   the separate Fable merge-gate and the second orchestrator tier; kept the
   token-saving disciplines (handoffs, verification, systematic debugging).
   Recorded in the `codex-implementer-orchestration` auto-memory.
3. ✅ **`/goal` overnight command built** — `.claude/skills/goal/SKILL.md`.
   One task iteration of the lean loop per invocation; safe for unattended
   `/loop /goal`; auto-merges each green+clean task to **local `main`**
   (owner's choice), Opus review, no Fable, Codex build. Self-stops on plan
   completion or a stop-and-flag condition.
4. ✅ **progress.md logged** (Sessions 12 + 13 entries appended).
5. ⏳ **NOT started: the overnight run.** It is 2026-07-12 ~10:41 local
   (morning), so the run was set up but not launched. Owner will launch
   `/loop /goal` tonight — see Action Items.

## Critical References

1. `.claude/skills/goal/SKILL.md` — the overnight loop playbook (roles,
   per-iteration steps, safety rails, stop conditions). **Read first** before
   launching or continuing the loop.
2. `.superpowers/sdd/phase1-orchestration-runbook.md` — the per-task SDD loop
   the `/goal` command automates.
3. `.superpowers/sdd/progress.md` — session log; Session 13 entry has the full
   P1-T5 review + the lean-model rationale + non-blocking findings.
4. `docs/superpowers/plans/2026-07-11-phase2-3-implementation-plan.md` — the
   Phase 2/3 plan (currently **untracked/uncommitted**).
5. `src/halfblood/generation/providers/anthropic.py` — the merged P1-T5
   provider (the safety-anchor httpx adapter; sole retry owner).

## Recent changes (committed to `main`)

- `cf68fe5` — Merge `phase1-t5` (P1-T5): native httpx `AnthropicProvider`,
  `annotation_generator.py` cutover onto the provider protocol,
  `AllPagesFailedError` reconciliation, `anthropic` dropped from core deps,
  new `tests/test_anthropic_provider.py` + remediated test suites,
  `tests/test_annotation_generator.py` deleted.
- `b0ae59e` — the P1-T5 feat commit (parent of the merge).

## Uncommitted (intentional — do NOT auto-commit)

- `M CLAUDE.md` — cross-session housekeeping, never auto-committed.
- `?? .claude/skills/` — now holds `goal/` (this session) + `halfblood-roadmap/`.
- `?? docs/superpowers/plans/2026-07-11-phase2-3-implementation-plan.md`.

## Learnings

- **Mocked tests can hide wire-contract errors.** All 26 P1-T5 provider tests
  use `httpx.MockTransport`, so they'd pass even if a header name or error
  shape were wrong. The advisor caught that the wire facts were verified from
  memory, not source; the fix was a targeted `claude-api` skill check (all 5
  facts correct). **Any provider-facing task's review MUST verify the wire
  contract against `claude-api`, not recall** — baked into the `/goal` brief step.
- **`temperature` is correctly dropped.** `_build_body` ignores
  `request.temperature` — correct, because temperature 400s on Opus 4.8 /
  Sonnet 5. Silent-drop (vs reject) is a latent wart, not a bug.
- **Fable use-it-before-you-lose-it:** owner flagged Fable leaves their plan
  ~2026-07-13. Owner chose NOT to use Fable in the overnight loop (Opus
  reviews); Fable remains available for a one-off deep review if wanted.

## Non-blocking P1-T5 findings (follow-ups, NOT P1-T5 scope)

1. `generate_for_document` success path hardcodes `attempts=1`
   (`annotation_generator.py:399`), discarding `result.attempts` — pages that
   succeeded after a retry under-report. Fix touches the 4-tuple contract the
   tests pin → defer.
2. max_tokens escalation increments the shared `attempts` counter (brief prose
   says it shouldn't; brief skeleton does too — Codex matched it; edge case).
3. `min(max_tokens*2, 8192)` shrinks the budget if a caller passes
   `max_tokens>8192` (only caller hardcodes 2048 → latent).
4. `float(retry_after)` throws on an HTTP-date `Retry-After` (Anthropic sends
   int seconds → latent); `_should_retry_attempt` hardcodes 60s; redundant
   `TimeoutException` in the except tuple; pyproject dep-comment wart.
5. **Owner-facing:** no live `ANTHROPIC_API_KEY` smoke test has run against
   `AnthropicProvider` — supplementary, worth doing before real traffic.

## Verification

| Claim | Command | Result |
|---|---|---|
| P1-T5 merged to main | `git log --oneline -2 main` | `cf68fe5` merge on top of `b0ae59e` feat |
| Gate green on main | `.venv/bin/pytest tests/ -q` | `345 passed` |
| ruff clean | `.venv/bin/ruff check src tests eval` | `All checks passed!` |
| mypy clean | `.venv/bin/mypy src/halfblood` | `Success: no issues found in 18 source files` |
| SDK fully removed | `grep -rn "import anthropic\|from anthropic" src/ tests/` | empty |
| Not pushed | (no push command was run this session) | remote unchanged |

## Action Items & Next Steps

1. **Validate `/goal` on ONE task (P1-T6) attended before any unattended run.**
   The loop has never executed; it auto-merges to `main`, so watch one full
   iteration first — ideally after `/model sonnet` so the exact overnight
   config (Sonnet driver + Opus review subagent + Codex build) is exercised.
   Confirm step 1 resolves to P1-T6 with the right scope, Codex dispatches,
   the review subagent spawns, and the merge lands green.
2. **Then launch overnight:** `/loop /goal` (self-paced). Built-in first-night
   safety (see the skill): it tags `main` with `pre-overnight-<date>` for
   one-command rollback and **stops after 2 merged tasks** so a misread-brief
   chain can't run ten deep — loosen the cap once you've eyeballed the first
   merges. Monitor: `tail .superpowers/sdd/progress.md`; `git log --oneline main`.
   Known gap: review checks diff-vs-brief, nothing independently checks
   brief-vs-plan-intent — the cap + tag are the mitigation.
3. **Next task is P1-T6** (structured-output negotiation + bounded parsing) —
   depends on P1-T2/P1-T4 (merged), not on P1-T5.
4. **If the loop stop-flags:** read its `progress.md` note + the handoff it
   writes; resolve the flagged blocker; re-launch `/loop /goal`.
5. **Nothing is pushed.** If the owner wants `main` published, push manually
   after reviewing.

## Other Notes

- Repo on `/mnt/c` under WSL: use `.venv/bin/…` for everything.
- `.claude/settings.local.json` `bypassPermissions` is intentional — do not "fix".
- Codex CLI 0.144.1, chatgpt-authenticated; `codex exec --sandbox
  workspace-write` proven across Phase 0/1 dispatches.
