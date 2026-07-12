---
date: 2026-07-11T23:45:50-04:00
researcher: Claude (Sonnet 5) — controller session
git_commit: c131b920f6f1d7aa314b795ac6df91fa0d40a0ce
branch: phase1-t5
repository: half-blood-prince
topic: "Session 12 — P1-T5 (native Anthropic HTTP adapter, parity cutover) built by Codex and gate-green on phase1-t5; adversarial review, Fable merge-gate, and merge to main are NOT done"
tags: [phase1, anthropic-provider, httpx, provider-seam, test-inventory-gap, codex-usage, handoff]
status: complete
last_updated: 2026-07-11
type: handoff
---

# Handoff: P1-T5 source built and full gate green on `phase1-t5`, but NOT reviewed, NOT Fable-gated, NOT merged

> Session 12 resumed from Session 11's handoff (P1-T4 merged; P1-T5 flagged
> as a bigger blast-radius jump than T1–T4) and ran P1-T5 through: brief
> authorship → controller-authored failing tests → Codex dispatch → tripwire
> verify → full gate. **It stopped there, mid-runbook, at the user's
> request**, to hand off cleanly rather than push through review/merge in a
> single long session. The next session's job is exactly the two runbook
> steps this one didn't reach: first-pass adversarial review of the diff,
> then the Fable merge-gate, then merge.
>
> One real process finding: the controller's pre-dispatch test inventory was
> incomplete. `grep -rln "import anthropic" tests/` (used to scope which test
> files the P1-T5 brief needed to touch) missed five pre-existing test files
> that exercised removed internals (`_parse_response`, `_ANNOTATION_TOOL_SCHEMA`,
> the old 3-tuple return signature, `anthropic` as a core dependency) without
> literally importing the SDK. Codex built exactly what the brief specified
> and correctly declined to touch any test file when the resulting 24
> failures surfaced (self-reported this accurately in its report — see
> Learnings). The controller then updated those five files by hand, which is
> the only place that work can happen (Codex is architecturally forbidden
> from touching `tests/` — see `.superpowers/sdd/phase1-orchestration-runbook.md`).
> Full gate is green now, but **that remediation itself has not been
> adversarially reviewed** — it is controller-authored and self-verified
> only.

## Task(s)

1. ✅ **P1-T5 brief authored** — full pinned interface for
   `AnthropicProvider` (retry loop, error taxonomy mapping, response
   parsing) and the `AnnotationGenerator` adaptation, written from the plan
   + architecture + the live Anthropic wire contract (verified via the
   `claude-api` skill, not recalled from training data).
2. ✅ **Controller-authored failing tests written** — `tests/test_anthropic_provider.py`
   (new) and `tests/test_failure_handling.py` (rewritten to inject a fake
   `LLMProvider`); `tests/test_annotation_generator.py` deleted (coverage
   redistributed). Confirmed failing for the intended reason before dispatch.
3. ✅ **Codex dispatch complete** — `gpt-5.6-sol`, `model_reasoning_effort=high`,
   exit 0. Built `src/halfblood/generation/providers/anthropic.py` (new) and
   adapted `src/halfblood/annotation_generator.py` + `pyproject.toml`
   exactly per the pinned brief. Tripwire held: touched zero test files
   (verified — see Verification table).
4. ✅ **Post-hoc test remediation (controller-authored, NOT reviewed)** — 5
   pre-existing test files broke against the intentional interface change
   and were fixed by hand this session:
   - `tests/test_generation_orchestration.py` — mechanical: its `_Recorder`
     double now returns/consumes the new 4-tuple shape (adds a synthesized
     `None` error element; no behavioral assertions changed).
   - `tests/test_generation_report.py` — one assertion flipped: the P1-T4
     test that pinned `annotation_generator.AllPagesFailedError` and
     `generation.report.AllPagesFailedError` as *unrelated* siblings now
     asserts the intentional P1-T5 reconciliation (real subclass
     relationship) — this is the exact "unified during a later phase's
     cutover" the P1-T4 docstring anticipated.
   - `tests/test_generation_schema.py` — 2 tests retired
     (`test_legacy_tool_schema_is_generated_not_hand_maintained`,
     `test_parse_response_still_reads_position_key_unchanged`) because their
     subjects (`_ANNOTATION_TOOL_SCHEMA`, `_parse_response`) no longer exist;
     their invariants now live in `test_anthropic_provider.py`
     (`test_request_url_headers_and_payload_shape`, and a NEW
     `test_non_default_position_value_survives_parsing` added specifically
     to close a real gap — the existing provider tests only used the
     default `position` value).
   - `tests/test_packaging.py` — `test_anthropic_is_capped_below_two`
     replaced with `test_anthropic_is_absent_from_core_dependencies`
     (confirms `anthropic` left `[project.dependencies]` and is still
     bounded `<2` in the `eval` extra).
   - `tests/test_pipeline.py` — the `TestParseResponse` class (9 tests, all
     exercising the now-deleted `_parse_response`/`_extract_raw_annotations`)
     removed; its one still-valid test
     (`test_generate_for_page_short_circuits_on_empty_text`, which never
     touched `_parse_response`) preserved as a standalone function.
5. ⏳ **NOT done: first-pass adversarial review of the diff.** The runbook's
   step 8 (read the actual diff, build a controller-discipline gate table,
   hunt correctness/scope-creep/hidden behavior/weak tests) has not been
   performed. The controller read `annotation_generator.py`'s diff
   incidentally while diagnosing the test failures and it appeared to match
   the brief exactly, but this was not a structured review and
   `src/halfblood/generation/providers/anthropic.py` (the new file, ~250
   lines of retry/parsing logic) has not been reviewed line-by-line at all.
6. ⏳ **NOT done: Fable merge-gate.** Per Session 11's finding, dispatch as
   `subagent_type: "general-purpose", model: "fable"` — NOT `code-reviewer`
   (that subagent type came up with only 6 task-management tools, no
   Read/Bash/Grep, in Session 11).
7. ⏳ **NOT done: merge to `main`.** Nothing on `phase1-t5` is committed yet —
   see Verification table.
8. ⏳ **NOT done: `.superpowers/sdd/progress.md` entry** for this session
   (gitignored, local-only — lower priority than the above).

## Critical References

1. `.superpowers/sdd/p1-t5-brief.md` — the full pinned interface Codex built
   against (33KB; includes the retry-loop pseudocode, the exact 400/413→
   `ProviderConfigurationError` mapping rationale, the `AllPagesFailedError`
   reconciliation design, and the `annotation_generator.py` diff shape).
   Read this FIRST — it's the ground truth for what "correct" means for the
   next session's review.
2. `.superpowers/sdd/p1-t5-report.md` — Codex's self-report (short, 18
   lines). Accurately flags the 24 pre-remediation failures as "stale tests
   asserting interfaces explicitly removed or reversed by P1-T5" and
   correctly states it did not edit them.
3. `.superpowers/sdd/phase1-orchestration-runbook.md` — the per-task loop.
   This session executed steps 1–7; steps 8–10 (first-pass review, Fable
   gate, commit+merge) are what's left.
4. `docs/superpowers/specs/2026-07-11-full-project-architecture.md` §§4.1,
   4.3 (Anthropic), 4.6 — the architecture ground truth the brief was
   written from; needed to judge whether `AnthropicProvider`'s retry/error
   logic actually matches intent, not just the brief's paraphrase of it.

## Recent changes

All uncommitted on `phase1-t5` (branched from `main` at `c131b92`):

- `src/halfblood/generation/providers/anthropic.py` (new, Codex-authored) —
  `AnthropicProvider` implementing `LLMProvider` over `httpx`: bounded
  backoff retry (429 honors `Retry-After`; 408/409/425/5xx transient-retry;
  401/403/404 no-retry; unclassified 4xx incl. 400/413 →
  `ProviderConfigurationError`, deliberately never `ProviderCapabilityError`);
  a separate one-shot `max_tokens` escalation for truncation, independent of
  the backoff budget; response parsing with per-item tolerant annotation
  validation (all-invalid → empty success, not a page failure — P1-T6 scope
  to tighten). No `anthropic` SDK import (AST-verified by
  `test_no_anthropic_sdk_import`).
- `src/halfblood/annotation_generator.py` (Codex-authored, 346-line diff) —
  `anthropic` SDK import and all direct usage removed; constructor gained an
  injectable `provider: LLMProvider | None` parameter (falls back to a real
  `AnthropicProvider` when `None`, preserving the exact
  missing-api-key-raises-`ValueError` contract); `_generate_for_page_tracked`
  now returns a 4-tuple (`annotations, attempted, failed, error`) instead of
  3; `AllPagesFailedError` is now a real subclass of
  `generation.report.AllPagesFailedError`, carrying a genuine per-page
  `GenerationReport` (not a stub) built inside `generate_for_document`.
- `pyproject.toml` — `anthropic>=0.30.0,<2` removed from
  `[project.dependencies]`; `eval` extras group (which also lists
  `anthropic`) untouched. Minor cosmetic wart introduced by the controller's
  own brief: the dependency-bounds comment above `dependencies = [...]` now
  reads `# ebooklib\n# is pre-1.0 (minor bumps are breaking...` — grammatically
  awkward mid-sentence line break, harmless but worth a follow-up polish
  (see Action Items).
- `tests/test_anthropic_provider.py` (new, controller-authored, 26
  functions) — wire-level tests against `httpx.MockTransport`.
- `tests/test_failure_handling.py` (controller-authored rewrite) — injects a
  fake `LLMProvider`; adds coverage that `AllPagesFailedError.report` is a
  real, populated `GenerationReport`.
- `tests/test_annotation_generator.py` — deleted (superseded; coverage
  redistributed into the two files above).
- `tests/test_generation_orchestration.py`, `tests/test_generation_report.py`,
  `tests/test_generation_schema.py`, `tests/test_packaging.py`,
  `tests/test_pipeline.py` — controller remediation for the test-inventory
  gap described above (see Task 4).

## Learnings

- **The controller's pre-dispatch test-scoping method was insufficient.**
  `grep -rln "import anthropic" tests/` found the files that literally
  imported the SDK, but missed files that called now-deleted private methods
  (`_parse_response`) or asserted on a now-deleted module constant
  (`_ANNOTATION_TOOL_SCHEMA`) without importing `anthropic` themselves (e.g.
  `test_pipeline.py`'s `TestParseResponse` class built its own
  `types.SimpleNamespace` fakes rather than real SDK objects). Next time:
  grep for every symbol the brief plans to *delete*
  (`_parse_response|_ANNOTATION_TOOL_SCHEMA|_extract_raw_annotations|...`)
  across `tests/`, not just SDK imports, before finalizing which test files
  the brief authorizes touching.
- **Codex behaved exactly as designed when it hit tests it couldn't fix.**
  It built precisely what the brief specified, hit 24 failures in files
  outside its brief-granted scope, and self-reported this honestly instead
  of either (a) editing the forbidden files or (b) silently declaring
  success. This is the runbook's test/builder separation working as
  intended — see `p1-t5-report.md`.
- **A P1-T4-pinned "these two exception types are permanently unrelated"
  test was actually pinning a *staging* invariant, not a permanent one** —
  its own module docstring (`generation/report.py`'s `AllPagesFailedError`)
  said the two classes "will be unified during a later phase's cutover when
  AnnotationGenerator migrates onto this report." P1-T5 IS that later phase.
  When a test's failure traces back to a docstring in the code under test
  that already announced the change, that's a strong signal the test needs
  updating, not the design.
- **Uncommitted work across a whole runbook pass is risky to leave
  spanning a compaction/session boundary** — this handoff exists partly
  because the user (correctly) preferred a clean stopping point with a
  written record over continuing an already-long session through
  review+merge. Nothing here is lost (all on `phase1-t5`, gate green) but
  none of it is committed — see Action Items #1.

## Verification

| Claim | Command run this session | Result |
|---|---|---|
| On branch `phase1-t5`, based on `main` at the P1-T4-merge-handoff commit | `git rev-parse HEAD`, `git rev-parse --abbrev-ref HEAD` | `c131b920f6f1d7aa314b795ac6df91fa0d40a0ce`, `phase1-t5` |
| Full suite green after all remediation | `.venv/bin/pytest tests/ -q` | `345 passed, 11 warnings` |
| ruff clean | `.venv/bin/ruff check src tests eval` | `All checks passed!` |
| mypy clean | `.venv/bin/mypy src/halfblood` | `Success: no issues found in 18 source files` |
| No `anthropic` SDK import anywhere in `src/` or `tests/` | `grep -rn "import anthropic\|from anthropic" src/ tests/` | no output (empty — confirmed absent) |
| Codex touched zero test files (checked immediately after Codex exited, before controller remediation) | `sha256sum -c .superpowers/sdd/p1-t5.testsums` (run right after Codex finished) | all 21 pre-dispatch test files `OK` |
| Diff scope: exactly the files the brief authorized Codex to touch, plus controller test remediation | `git status --short` | `M pyproject.toml`, `M src/halfblood/annotation_generator.py`, `?? src/halfblood/generation/providers/anthropic.py` (Codex); `M`/`D`/`??` on 7 files under `tests/` (controller) — plus a pre-existing unrelated `M CLAUDE.md` from before this session, not touched by this task |
| Only this handoff (+ incidentally, the `test_annotation_generator.py` deletion staged earlier via `git rm`) is committed; the rest of P1-T5's diff is not | `git log phase1-t5 --oneline -3` (run after this doc's own commit, so its content can't self-reference the resulting hash — check `git log` directly rather than trusting a hash printed here) | Exactly one new commit on top of `c131b920f6f1d7aa314b795ac6df91fa0d40a0ce` (this doc's own `docs: Session 12 handoff...` commit). `git show --stat HEAD` (or `git show --stat phase1-t5` right after resuming) shows exactly 3 files: `HANDOFF.md`, the deleted `tests/test_annotation_generator.py`, and this handoff doc. Everything else (`src/halfblood/generation/providers/anthropic.py`, `src/halfblood/annotation_generator.py`, `pyproject.toml`, the 6 other test files) is still uncommitted — see `git status --short` |
| No pre-existing branch was force-pushed or deleted | `git branch -a` | `main`, `phase0-audit-close`, `phase1`, `phase1-t2`, `phase1-t2-fix2`, `phase1-t3`, `phase1-t4`, `phase1-t5`, `phase2-model-fix` — same set as Session 11 plus the new `phase1-t5` |
| Codex dispatch artifacts present | `ls -la .superpowers/sdd/p1-t5*` | `p1-t5-brief.md` (33869 bytes), `p1-t5-codex.log` (1168381 bytes), `p1-t5-report.md` (1076 bytes), `p1-t5.testsums` (1957 bytes) |
| First-pass adversarial review has NOT been performed | (no command — this is a negative claim about work not done) | confirmed by omission: no gate table exists anywhere in this session's artifacts |

## Artifacts

- Uncommitted, on `phase1-t5` (all of "Recent changes" above) — durable on
  disk, not yet durable in git history.
- Written this session, durable, gitignored (`.superpowers/sdd/.gitignore`,
  not committed, per established convention): `p1-t5-brief.md`,
  `p1-t5-report.md`, `p1-t5-codex.log`, `p1-t5.testsums`.
- Written this session, committed with this handoff: this file, `HANDOFF.md`
  (pointer updated).
- `.superpowers/sdd/progress.md` — NOT updated this session (gitignored,
  lower priority; the next session should append a Session 12 entry
  alongside its Session 13 entry, or the resuming session can do it as its
  first action).

## Action Items & Next Steps

1. **Commit the P1-T5 work-in-progress on `phase1-t5` before doing anything
   else** — right now it's real, gate-green work sitting only on disk (the
   `test_annotation_generator.py` deletion already landed incidentally in
   `d7a7489`, the handoff commit — everything else has not). Suggested
   split matching the established convention (controller tests + Codex
   source in one feat commit, matching P1-T4's `2d2b063` pattern): one
   commit for everything currently in `git status --short` under
   `src/`+`pyproject.toml`+`tests/` (Codex's source + the controller's
   original P1-T5 tests + the controller's post-hoc remediation of the 6
   remaining pre-existing files, since they're all part of making P1-T5
   green). Do NOT commit the unrelated pre-existing `M CLAUDE.md` — that's
   established cross-session housekeeping, never auto-committed.
2. **First-pass adversarial review (runbook step 8) — do this next, before
   Fable.** Read `src/halfblood/generation/providers/anthropic.py` in full
   against `.superpowers/sdd/p1-t5-brief.md`'s pinned interface line by
   line — it has NOT been reviewed at all yet. Specific things to check
   given the brief's own admitted complexity: the retry-attempt-counting
   symmetry between the connection-error branch and the HTTP-error branch
   (the brief's pseudocode had this bug once already and the controller
   caught it before dispatch — verify Codex's actual implementation still
   has matching `attempts <= self._max_retries` bounds in both branches);
   the one-shot `max_tokens` escalation not consuming a `max_retries` slot;
   the 400/413→`ProviderConfigurationError` (never `ProviderCapabilityError`)
   mapping; whether `latency_seconds` was implemented as a real measurement
   (the brief left this as an unpinned placeholder — "any correct
   implementation passes" — so it's legitimately Codex's judgment call, just
   verify it's not hardcoded to `0.0`).
3. **Adversarially review the controller's own post-hoc test remediation**
   (Task 4 above) — it has only been self-verified (each file re-run
   individually and the full suite re-run green), never reviewed by anyone
   else. In particular scrutinize whether retiring `test_pipeline.py`'s
   `TestParseResponse` class actually lost no coverage, and whether
   `test_generation_report.py`'s flipped assertion is the right call versus
   an alternative reconciliation design.
4. **Fable merge-gate** — dispatch as `subagent_type: "general-purpose",
   model: "fable"` (NOT `code-reviewer` — see Session 11's finding, still
   unresolved/unexplained as of this session).
5. **Commit + merge to `main`** on Fable sign-off; log the full session in
   `.superpowers/sdd/progress.md` (Session 12 entry — this session's work
   was not logged there).
6. **Then P1-T6** (structured-output negotiation and bounded parsing) is
   next in the plan's execution order — depends on P1-T2, P1-T4 (merged),
   NOT on P1-T5's merge, so it could theoretically be planned in parallel,
   but per established one-task-at-a-time convention, finish P1-T5's merge
   first.
7. **Low-priority polish**: the `pyproject.toml` dependency-bounds comment
   now has an awkward mid-sentence line break (`# ebooklib` / `# is pre-1.0
   (minor bumps...`) — cosmetic only, fix opportunistically.
8. **Owner-facing flag, still true**: no `ANTHROPIC_API_KEY`-backed live
   smoke test has been run against `AnthropicProvider` — P1-T5's plan entry
   explicitly marks this "Live smoke: blocked-on-key `ANTHROPIC_API_KEY`",
   supplementary and not required for merge, but worth doing before this
   sees real traffic.

## Other Notes

- Repo on `/mnt/c` under WSL: use `.venv/bin/…` for everything.
- `.claude/settings.local.json` `bypassPermissions` is intentional — do not
  "fix".
- Codex CLI 0.144.1, single `codex exec --sandbox workspace-write` dispatch,
  `gpt-5.6-sol` at `model_reasoning_effort=high` (this session's own
  judgment call, one tier above P1-T4's `medium`, given the retry-loop/
  escalation/classification control-flow interaction risk called out in the
  brief itself). Exit 0, no fix-dispatch needed — the 24 post-dispatch
  failures were all in controller-owned test files, not something Codex
  could have fixed even if asked to retry.
- No `ANTHROPIC_API_KEY` was set in this session's shell at any point; no
  network calls were made anywhere (confirmed by the full test suite using
  only `httpx.MockTransport`/fakes).
