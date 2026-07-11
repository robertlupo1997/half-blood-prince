---
date: 2026-07-11T02:06:30-04:00
researcher: Claude (Opus 4.8) — controller in a Codex-implementer loop
git_commit: 21318cc9e7483fd341f0b639a518b6a5af9b9db4
branch: phase0-audit-close
repository: half-blood-prince
topic: "Session 6 — research spike shipped; Phase 0 execution started (P0-T1/T2/T3 done on a branch)"
tags: [phase0, sdd, codex-loop, provider-research, tdd]
status: complete
last_updated: 2026-07-11
type: handoff
---

# Handoff: v0.1.0 → Phase 0 execution — Session 6

The workflow is the SDD loop from Session 5: **controller writes failing tests →
implementer writes code → controller re-runs the full gate itself → commit only
when green.** This session the controller was Claude (Opus 4.8); the implementer
was **Codex** (`codex exec`, `codex-cli 0.144.1`, ChatGPT auth). The owner
directed mid-session: *use Codex for implementations — `gpt-5.6-sol` for
judgment-heavy, `gpt-5.6-terra` for quick/mechanical.* Both models are validated
and working.

> **The NEXT session is led by Fable (`claude-fable-5`).** Owner's mandate for it:
> 1. **Confirm we are building this the correct way** — before writing any more
>    tests or code, sanity-check the *direction* against the architecture spec
>    (`docs/superpowers/specs/2026-07-11-full-project-architecture.md`) and the
>    P0-T1/T2/T3 work already on this branch. If something is off-course, raise it
>    with the owner rather than grinding more tasks.
> 2. **Adversarially code-review what Codex / GPT-5.6 produces.** Treat every
>    Codex diff as *testimony to be attacked, not trusted*: re-run the full gate,
>    verify tests were not touched (`sha256sum -c` the pre-dispatch snapshot), and
>    actively hunt for correctness bugs, scope creep, silent behavior changes, and
>    weak/vacuous tests. This is the same controller discipline used this session,
>    with the adversarial-review emphasis made explicit and primary.
>
> Fable remains the controller/reviewer; Codex/GPT-5.6 stays the implementer.

## Task(s)

Governing docs (read in order): `docs/superpowers/plans/2026-07-11-phase0-1-implementation-plan.md`
(the 21-task plan), `docs/superpowers/specs/2026-07-11-full-project-architecture.md`
(target arch), `docs/audit/2026-07-10-adversarial-audit.md` (AUD backlog).

- ✅ **Research spike** (Action Item 2 from Session 5) — committed `f20d196` **on `main`**.
- ✅ **P0-T1** — harden Anthropic response handling (AUD-05/10/14/21/23, L-1/L-3). Commit `06c253d`.
- ✅ **P0-T2** — blank-field validation + delimiter-aware fences + enum contract (AUD-15/32, L-2). Commit `1beeb2a`.
- ✅ **P0-T3** — orchestration coverage + bound running_notes (AUD-22/31). Commit `21318cc`.
- 🚧 **Branch `phase0-audit-close`** holds P0-T1/T2/T3 (3 commits ahead of `main`).
  **NOT merged, NOT pushed.** The spike is already on `main`.
- ⏳ **NEXT: P0-T8** (EPUB coverage, critical path) or any no-dependency task
  (P0-T4 web preview, P0-T5 PDF geometry, P0-T7 CLI validation). 9 Phase-0 tasks remain.
- ⏳ **Key-blocked**: live E2E/doctor need `ANTHROPIC_API_KEY` (still unset). All commit gates are offline/mocked.

## Critical References

1. `docs/superpowers/plans/2026-07-11-phase0-1-implementation-plan.md` — each task's
   test-first spec, acceptance criteria, dependencies. Critical path at the bottom:
   `P0-T1 → P0-T2 → P0-T3/P0-T8 → P0-T12 → P1-*`.
2. `docs/superpowers/research/2026-07-11-provider-and-render-comparators.md` (NEW,
   `f20d196`) — spike output. **Decision for P1-T5/owner-decision-1b: adopt raw `httpx`
   for BOTH providers** (single retry owner, uniform taxonomy, MockTransport wire tests;
   corroborated by Riddle). **Handwriting lead:** Riddle skeletonizes an OFL font into
   pen strokes → OFL-font skeletonization may source procedural strokes with NO separately
   licensed asset (our Caveat Brush is OFL 1.1). Verify before Phase 3; IAM-trained synth
   models are non-commercial-license-blocked.
3. `.superpowers/sdd/progress.md` (gitignored) — running ledger; Session 6 appended.
   Per-task briefs/reports at `.superpowers/sdd/p0-t{1,2,3}-{brief,report}.md`.

## Recent changes

- `src/halfblood/annotation_generator.py` — `class _MalformedResponseError(RuntimeError)`
  (line 184); truncation/malformed/no-block now raise it from `_parse_response`
  (lines 561, 580–607), caught in `_generate_for_page_tracked` → page failure;
  `isinstance(block, anthropic.types.ToolUseBlock)` narrowing + duck-typed fallback
  (line 566); delimiter-aware fence stripping (line 621, `startswith("```json")`);
  `del running_notes[:-8]` (line 446). Both L-1/L-3 `# type: ignore` removed.
- `src/halfblood/models.py` — `Annotation` has `model_config = ConfigDict(str_strip_whitespace=True)`
  (line 23); `target_text`/`content` `min_length=1` (lines 27, 31); `AnnotationType`
  stays `str, Enum` with clarified `# noqa: UP042` (line 9).
- Tests added: `tests/test_annotation_generator.py` (P0-T1, 21 tests),
  `tests/test_models.py` (P0-T2, 18), `tests/test_generation_orchestration.py` (P0-T3, 9).
  `tests/test_pipeline.py` — removed the contract-changed no-block test, added 2 AUD-32 fence guards.

## Learnings

1. **The Codex loop works on both tiers.** `gpt-5.6-sol` (P0-T1, judgment-heavy) and
   `gpt-5.6-terra` (P0-T2/T3, quick) both implemented cleanly. Invocation:
   `codex exec --sandbox workspace-write -C <repo> -m <model> -c model_reasoning_effort=<lvl>
   -o <report> < <brief>`. Codex's report is testimony — the controller re-ran the full
   gate AND checked `sha256sum -c` on all test files (Codex never touched a test).
2. **Design tests at the observable-behavior level** (via `generate_for_document`/
   `_generate_for_page_tracked`/`failed_pages`/`AllPagesFailedError`) so the implementer
   picks the internal mechanism. P0-T1's failure signal is Codex's choice
   (`_MalformedResponseError`), not dictated.
3. **L-3 isinstance-narrowing vs duck-typed fakes:** the merged `test_failure_handling.py`
   uses `SimpleNamespace` blocks. The impl supports BOTH real `ToolUseBlock` (isinstance)
   and duck-typed (`getattr`) so merged tests stay green — new tests use real SDK types.
4. **Not every AUD has a reachable RED.** AUD-32 (fence char-strip) does NOT corrupt valid
   bracketed JSON (proven by a probe — interior backticks are quote-protected); AUD-31
   (unbounded `running_notes`) has no observable difference from the `[-8:]` consumption.
   Both are hardening/hygiene with guard tests; the RED came from AUD-05/14/21 (P0-T1) and
   AUD-15 (P0-T2).
5. **Pyright IDE diagnostics are noisy false-positives here** (resolves a stale `halfblood`;
   flags `AllPagesFailedError`/`failed_pages` as unknown). The venv resolves `src/`
   correctly and the mypy gate (`mypy src/halfblood`, tests excluded) is clean. Ignore Pyright.

## Verification

| Claim | Command run this session | Result |
|---|---|---|
| HEAD `21318cc`, branch `phase0-audit-close`, tree clean | `git rev-parse HEAD; git rev-parse --abbrev-ref HEAD; git status --short` | `21318cc…`, `phase0-audit-close`, empty |
| Branch is 3 commits ahead of main; spike on main | `git log main..HEAD --oneline` | `21318cc`, `1beeb2a`, `06c253d` (spike `f20d196` NOT listed = on main) |
| Full gate green after P0-T3 | `.venv/bin/ruff check src tests eval && .venv/bin/mypy src/halfblood && .venv/bin/pytest tests/ -q` | ruff "All checks passed!"; mypy "no issues in 7 files"; **102 passed** |
| `annotation_generator.py:184` `_MalformedResponseError` | `grep -n "class _MalformedResponseError"` | `184:class _MalformedResponseError(RuntimeError):` |
| `annotation_generator.py:446` running_notes bound | `grep -n "del running_notes"` | `446:            del running_notes[:-8]` |
| `annotation_generator.py:566` isinstance narrowing | `grep -n "isinstance(block, anthropic.types.ToolUseBlock)"` | `566:                if isinstance(block, anthropic.types.ToolUseBlock):` |
| No `type: ignore` remain in generator | `grep -n "type: ignore" src/halfblood/annotation_generator.py` | none |
| `models.py:23/27/31` strip + min_length | `grep -n "str_strip_whitespace\|min_length=1"` | `23:model_config…str_strip_whitespace=True`; `27:min_length=1`; `31:…min_length=1…` |
| Codex modified only src (no test edits) | `sha256sum -c p0-t{1,2,3}-tests-before.sha256` | all `OK` each task |
| `ANTHROPIC_API_KEY` present | `python -c "os.environ.get('ANTHROPIC_API_KEY')"` | UNSET — live E2E blocked-on-key |

## Artifacts

Committed on `main`: `f20d196` (spike doc `docs/superpowers/research/2026-07-11-provider-and-render-comparators.md`).
Committed on `phase0-audit-close`: `06c253d` (P0-T1), `1beeb2a` (P0-T2), `21318cc` (P0-T3) — each = production fix + tests.
Gitignored on disk (this machine): `.superpowers/sdd/progress.md`, `.superpowers/sdd/p0-t{1,2,3}-{brief,report,codex.log,tests-before.sha256}`, this handoff (force-added).

## Action Items & Next Steps

**Fable, start here (see the mandate blockquote at the top):** first *confirm the
build direction is correct* — read the architecture spec and skim the P0-T1/T2/T3
diffs on this branch; if the direction is sound, proceed. Then work the queue
below, **adversarially reviewing every Codex/GPT-5.6 diff** before it is committed.

1. [ ] **Decide branch strategy:** either keep executing Phase 0 on `phase0-audit-close`
   (merge to `main` at Phase-0 close, per the Session-5 `phase2-model-fix` precedent), or
   the owner may prefer per-task commits on `main`. Current state assumes the branch.
2. [ ] **Continue the SDD loop at P0-T8** (EPUB coverage, dep P0-T2 ✅ — critical path) or a
   no-dep task (P0-T4/T5/T7). Per task: controller writes the plan's failing tests →
   confirm RED for the intended reason → Codex implements (sol=judgment, terra=quick) →
   controller re-runs `ruff check src tests eval` + `mypy src/halfblood` + `pytest tests/ -q`
   + `sha256sum -c` on tests → commit on green. **Preserve all existing tests.**
3. [ ] **Remaining Phase-0 tasks & deps:** P0-T4 (web_preview regex/ReDoS/HTML, no dep),
   P0-T5 (PDF geometry, no dep, L), P0-T6 (dep T5), P0-T7 (CLI magic-bytes+overwrite, no dep),
   P0-T8 (EPUB, dep T2 ✅), P0-T9 (dep T2/T5), P0-T10 (dep T4), P0-T11 (docs, dep T7/T10),
   P0-T12 (deps+ledger close, dep all). Then Phase 1 (P1-T1…T9).
4. [ ] **P1-T5 decision is de-risked:** the spike recommends raw `httpx` for both providers —
   no code needed now; it informs Phase 1.
5. [ ] **When `ANTHROPIC_API_KEY` exists:** run the ledger's prepared E2E (now on `claude-sonnet-5`);
   record cost/output. Do NOT pull handwriting (spec §5) or module restructure forward ahead of Phase 0/1.

## Other Notes

- **Repo on `/mnt/c` under WSL** — git/pytest slow (~30-40s suite). Use `.venv/bin/...`
  (bare system python lacks deps). Codex must use `.venv` too.
- **Handoffs are force-added** (`thoughts/` gitignored); `HANDOFF.md` at repo root is the pointer.
- **Autonomy configured** — `.claude/settings.local.json` has `bypassPermissions`; the committed
  PreToolUse guard hook blocks only destructive ops — do not "fix" it.
- **Do NOT re-plan merged work** (P0-T1/T2/T3 + Session-5 batch). Preserve their tests.
