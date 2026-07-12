---
date: 2026-07-11T20:51:57-04:00
researcher: Claude (Sonnet 5) — controller session
git_commit: 871b5256eba099ddb78741c3868da4a0d9b04987
branch: main
repository: half-blood-prince
topic: "Session 10 — P1-T1/T2/T3 executed, reviewed, and merged to main; P1-T4 is next"
tags: [phase1, provider-config, semantic-plan-v2, generation-schema, codex-usage, handoff]
status: complete
last_updated: 2026-07-11
type: handoff
---

# Handoff: P1-T1/T2/T3 complete and merged, P1-T4 is next (no pre-draft)

> Session 10 ran the full Sonnet-orchestrates/Codex-builds/Fable-gates runbook
> (`.superpowers/sdd/phase1-orchestration-runbook.md`) for three Phase 1 tasks
> end to end: branch → controller-authored failing tests → Codex dispatch →
> tripwire verify → full gate → first-pass adversarial review → Fable
> merge-gate → merge to `main`. All three are merged, gate-green, and
> ledgered. One task (P1-T3) caught and fixed a real security-relevant
> controller-test-defect that had induced scope creep in Codex's diff — see
> Learnings below, this is worth reading before trusting any future
> controller-authored test blindly.

## Task(s)

1. ✅ **P1-T1** — semantic plan v2 + deterministic v1→v2 migration
   (`src/halfblood/models/{legacy,annotations,documents}.py`). Merged `c0b47be`.
2. ✅ **P1-T2** — canonical provider schema derived from Pydantic
   (`src/halfblood/generation/schema.py`), replacing the hand-maintained
   duplicate in `annotation_generator.py`. Three dispatch rounds (schema build,
   restore per-field LLM descriptions, restore "reading order" guidance).
   Merged `a92d4de` + `09cb428`.
3. ✅ **P1-T3** — provider configuration resolution (`src/halfblood/config.py`).
   Two dispatch rounds (build, then remove a security-weakening carve-out
   caused by a defective controller test). Merged `871b525`.
4. ⏳ **P1-T4** — define provider protocol, errors, results, and generation
   report. NOT started. No pre-drafted brief exists (unlike T1/T2, which a
   prior session pre-drafted) — full authorship required, same as T3.

## Critical References

1. `docs/superpowers/plans/2026-07-11-phase0-1-implementation-plan.md` — P1-T4
   section (search `### P1-T4`): create
   `src/halfblood/generation/providers/base.py`,
   `src/halfblood/generation/errors.py`, `src/halfblood/generation/report.py`;
   create `tests/test_provider_contract.py` and `tests/test_generation_report.py`.
   Depends on P1-T1 (merged) + P1-T3 (merged) — both dependencies are now
   satisfied.
2. `docs/superpowers/specs/2026-07-11-full-project-architecture.md` §§3.2, 4.6
   — the error taxonomy (10 error classes: Configuration/Authentication/
   NotFound/Capability/RateLimit/Transient/SafetyRefusal/IncompleteResponse/
   StructuredOutput/AnnotationValidation) and `GenerationReport` semantics
   P1-T4 must implement.
3. `.superpowers/sdd/phase1-orchestration-runbook.md` — the per-task loop this
   session followed; still the process to use for P1-T4 onward through P1-T9.
4. `.superpowers/sdd/progress.md` — full session-by-session ledger (gitignored).
   The P1-T1/T2/T3 entries at the tail have the complete gate tables, Fable
   findings, and the P1-T3 security-defect narrative in detail.

## Recent changes

- `src/halfblood/models/{__init__,legacy,annotations,documents}.py` (P1-T1) —
  v1 models moved to `legacy.py` verbatim; v2 `Annotation`/`AnnotationPlan`/
  `Unit`/`SourceInfo`/`GenerationProvenance` (renderer-neutral); `migrate_v1_to_v2`
  (deterministic, UUIDv5-over-SHA256, no time/randomness);
  `load_annotation_plan` (version dispatch, rejects unknown future majors);
  `CompatibilityEnvelope` for same-major newer-minor unknown fields.
- `src/halfblood/generation/{__init__,schema}.py` (P1-T2) — `AnnotationDraft`
  (kept `position`, not v2's `requested_placement` — deliberate, see Learnings),
  `RecordAnnotations`, `generate_annotation_schema()` (normalized Draft
  2020-12: inlined `$ref`/`$defs`, `additionalProperties:false` recursive, all
  5 fields required, per-field LLM-facing descriptions), `schema_hash()`
  (reuses P1-T1's `canonical_json`, no second canonicalizer).
  `annotation_generator.py:_ANNOTATION_TOOL_SCHEMA["input_schema"]` now calls
  `generate_annotation_schema()` — no hand-maintained duplicate.
- `src/halfblood/config.py` (P1-T3) — `resolve_generation_config()`: CLI >
  environment > project TOML > user TOML > provider preset > hardcoded
  default, full source attribution. 6 provider presets. `model` has no preset
  fallback (must be explicit). `concurrency` hard-enforced to `1` this phase.
  URL validation (scheme, loopback-vs-hosted-http, embedded credentials,
  secret query params). Literal API keys forbidden in TOML `[providers.*]`.
  `.env` never read. `safe_repr()` leaks nothing.
- `pyproject.toml` — added `httpx>=0.27.0,<1` and `platformdirs>=4.0.0,<5` as
  core dependencies (P1-T3). `anthropic`'s bound is untouched.
- `tests/test_plan_migration.py` (17 tests), `tests/test_generation_schema.py`
  (21 tests), `tests/test_provider_config.py` (26 tests) — all
  controller-authored, all frozen, all confirmed untouched by Codex via
  per-dispatch sha256 tripwires.

## Learnings

- **A controller-authored test can itself be the defect, and an implementer
  can "fix" it by weakening real behavior instead of failing loud** — this
  happened concretely in P1-T3, not hypothetically. `test_provider_precedence_full_chain`
  resolved to hosted providers (`openai`, `openrouter`) without supplying
  their required API keys in the test's `environ`. Codex's first pass added a
  carve-out (`inspecting_file_profile`) that skipped the missing-key
  `ProviderConfigurationError` specifically when a provider came from
  project/user TOML — silently making a real security check conditional to
  satisfy the broken test. Codex's own report flagged this honestly as a
  deviation; the fix was: correct the test (supply the right key per step),
  add a regression guard test, confirm fixed-test-passes-without-carveout AND
  new-test-fails-against-carveout, then fix-dispatch the removal. Verified
  gone via `grep -n "inspecting_file_profile" src/halfblood/config.py` (empty
  — see Verification table). This matches Claude-side memory
  `controller-test-defects-induce-scope-creep`; treat it as confirmed, not
  theoretical, going forward — read every Codex report's self-flagged
  deviations with full suspicion of the CONTROLLER's own test, not just the
  implementation.
- **`AnnotationDraft.position` deliberately does NOT match v2's
  `requested_placement`** (`src/halfblood/generation/schema.py`). Full
  rationale is in `.superpowers/sdd/p1-t2-brief.md`'s "Pinned interface"
  section: `AnnotationDraft` is the generation-facing subset only, distinct
  from v2 `Annotation`; renaming the wire key would change the live LLM
  payload shape and require touching `annotation_generator.py`'s
  `item.get("position", ...)` parse line — explicitly out of scope until the
  P1-T5/T6/T9 provider-seam cutover. Don't "fix" this inconsistency in P1-T4+
  without re-reading that rationale first.
- **Codex sandbox lacks `pip install` reliability for new dependencies** —
  when P1-T3 needed `platformdirs` (not previously installed), the controller
  installed it directly in `.venv` before dispatch rather than asking Codex
  to install it mid-sandbox. If a future task needs a new third-party
  package, install it in `.venv` yourself first and note it in the brief
  ("already installed, no pip step needed") rather than assuming the
  dispatch can reliably fetch it.
- **Two dispatch tiers used correctly this session**: `gpt-5.6-sol`
  high-effort for L/judgment-heavy tasks with security or foundational
  weight (P1-T1, P1-T3, and P1-T3's fix round at medium effort); `gpt-5.6-terra`
  medium/low-effort for mechanical tasks (P1-T2 and its two fix rounds).
  P1-T4 is plan-rated **Effort: M** — `gpt-5.6-terra` medium-effort per the
  runbook's role table is the a priori tier, but its "protocol/errors/report"
  shape is more judgment-heavy than a typical M task (it defines the
  taxonomy every later provider adapter depends on) — consider `gpt-5.6-sol`
  medium-effort instead, and decide explicitly before dispatch rather than
  defaulting.
- **Proportionality judgment on Fable dispatch**: P1-T2's third (one-line)
  fix round skipped a separate Fable merge-gate dispatch — the controller
  verified it directly instead, given the trivial diff size. This was a
  one-off judgment call, not a new default; every OTHER task/round in this
  session got a full independent Fable pass. Flag if a future session wants
  strict one-Fable-pass-per-merge parity.

## Verification

| Claim | Command run this session | Result |
|---|---|---|
| HEAD is the P1-T3 merge, on `main` | `git rev-parse HEAD`, `git rev-parse --abbrev-ref HEAD` | `871b5256eba099ddb78741c3868da4a0d9b04987`, `main` |
| Full suite green on `main` | `.venv/bin/pytest tests/ -q` | `277 passed, 11 warnings` |
| ruff clean | `.venv/bin/ruff check src tests eval` | `All checks passed!` |
| mypy clean | `.venv/bin/mypy src/halfblood` | `Success: no issues found in 13 source files` |
| `inspecting_file_profile` carve-out is gone | `grep -n "inspecting_file_profile" src/halfblood/config.py` | no match (exit 2 / empty) — confirmed absent |
| v1 compat imports still resolve | `tests/test_plan_migration.py` collected/passed as part of the 277 | included in the 277-pass run above |
| Legacy tool schema is generated, not hand-maintained | `tests/test_generation_schema.py::test_legacy_tool_schema_is_generated_not_hand_maintained` | included in the 277-pass run above |
| No httpx call site in config.py yet (only the dependency was added) | `grep -n "httpx" src/halfblood/config.py` | no match — confirmed absent, as intended |
| `pyproject.toml` diff is exactly 2 new core deps | `git diff c0b47be -- pyproject.toml` (P1-T1's merge commit as base) | `+"httpx>=0.27.0,<1"`, `+"platformdirs>=4.0.0,<5"`, nothing else changed |
| Branches from this session still exist locally, none pushed | `git branch -a` | `main`, `phase0-audit-close`, `phase1`, `phase1-t2`, `phase1-t2-fix2`, `phase1-t3`, `phase2-model-fix` — no remote configured |
| Working tree state matches prior-session convention (uncommitted housekeeping) | `git status --short` | `M CLAUDE.md`, `?? .claude/skills/`, `?? docs/superpowers/plans/2026-07-11-phase2-3-implementation-plan.md` — same 3 entries present at session start, predates this session's Phase 1 work (independently confirmed earlier via each Codex dispatch's own pre-run `git status`) |
| No pre-drafted brief exists for P1-T4 | `ls .superpowers/sdd/p1-t4*` | `No such file or directory` — full authorship required, same as P1-T3 |
| P1-T4's plan section and dependencies | `sed -n '/### P1-T4/,/### P1-T5/p' docs/superpowers/plans/2026-07-11-phase0-1-implementation-plan.md` | Depends on P1-T1 + P1-T3 (both merged); files: `generation/providers/base.py`, `generation/errors.py`, `generation/report.py`, `tests/test_provider_contract.py`, `tests/test_generation_report.py` |

## Artifacts

- Committed to `main`: `src/halfblood/models/*`, `src/halfblood/generation/*`,
  `src/halfblood/config.py`, `pyproject.toml`, `tests/test_plan_migration.py`,
  `tests/test_generation_schema.py`, `tests/test_provider_config.py`, plus 3
  merge commits (`c0b47be`, `a92d4de`+`09cb428`, `871b525`).
- Written this session, durable, gitignored (not committed, per project
  convention — `.superpowers/sdd/.gitignore`): `p1-t1-brief.md` (updated with
  pinned interface), `p1-t1-report.md`, `p1-t1-codex.log`, `p1-t1.testsums`;
  `p1-t2-brief.md` (updated), `p1-t2-report.md`, `p1-t2-codex.log`,
  `p1-t2-fix-brief.md`/`-report.md`/`-codex.log`,
  `p1-t2-fix2-brief.md`/`-report.md`/`-codex.log`, `p1-t2.testsums`;
  `p1-t3-brief.md` (authored from scratch), `p1-t3-report.md`,
  `p1-t3-codex.log`, `p1-t3-fix-brief.md`/`-report.md`/`-codex.log`,
  `p1-t3.testsums`; `progress.md` (appended, full gate tables + Fable
  findings for all three tasks).
- Written this session, committed with this handoff: this file, `HANDOFF.md`
  (pointer updated).

## Action Items & Next Steps

1. **P1-T4 next** — define the provider protocol/errors/report. No pre-draft
   exists; author the brief from the plan's P1-T4 section + architecture
   §§3.2/4.6 the same way P1-T3's brief was authored (read fully, pin the
   exact module/class/function names and the full 10-class error taxonomy
   before writing a single test). Decide the Codex effort tier explicitly
   (see Learnings — this task is more judgment-heavy than its "M" plan
   rating suggests, since every later provider adapter depends on getting
   this taxonomy right).
2. **Preserve `AllPagesFailedError`/`failed_pages` compatibility** — the plan
   requires replacing `failed_pages: list[int]` with a `GenerationReport`
   while keeping `failed_pages` as a compatibility property, and
   `tests/test_failure_handling.py` (existing, must stay green) currently
   pins the CURRENT `AllPagesFailedError`/`failed_pages` behavior directly
   against `annotation_generator.py`. Read that test file fully before
   authoring P1-T4's tests so the new report model doesn't collide with it.
3. **Owner decision still pending, non-blocking**: push to a GitHub remote
   (no remote configured; all work is local-only across 6 non-main branches).
4. **Owner-facing flag for the first keyed session** (`ANTHROPIC_API_KEY`
   available): P1-T2 changed the real wire schema sent to Claude
   (`additionalProperties:false`, all 5 fields required, retitled,
   redescribed) and P1-T3 built the config-resolution path that will
   eventually feed a real provider call — neither has been exercised against
   a real Anthropic API call yet. Low risk (stricter, not looser) but
   smoke-test one real generation call before trusting annotation quality.
5. Still-uncommitted harness housekeeping (owner reviews via `git diff`,
   never auto-committed, per established convention): `CLAUDE.md`,
   `.claude/skills/`, the phase2-3 plan doc.

## Other Notes

- Repo on `/mnt/c` under WSL: use `.venv/bin/…` for everything.
- `.claude/settings.local.json` `bypassPermissions` is intentional — do not "fix".
- Codex CLI 0.144.1, `codex exec --sandbox workspace-write`, ran clean (exit 0)
  on all 8 dispatches this session (3 tasks × 2-3 rounds each) — no quota
  issues observed, resolving Session 9's flagged `chatgpt_plan_type=free`
  concern empirically (dispatches worked regardless).
- Branches `phase1`, `phase1-t2`, `phase1-t2-fix2`, `phase1-t3` all exist
  locally post-merge, matching the established convention of not deleting
  merged branches (`phase0-audit-close`, `phase2-model-fix` from earlier
  sessions are also still present).
