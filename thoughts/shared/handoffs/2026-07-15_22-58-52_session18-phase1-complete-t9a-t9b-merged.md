---
date: 2026-07-15T22:58:52-04:00
researcher: Claude (Opus 4.8) — controller session
git_commit: eb1952d0d410ec7607ccaaff9c1ac7327d580b94
branch: main
repository: half-blood-prince
topic: "Session 18 — PHASE 1 COMPLETE: P1-T9a + P1-T9b merged (553 green, both Opus reviews CLEAN); AUD-34 closed in substance; judge transport deferred to Phase 5 by spec"
tags: [phase1, p1-t9a, p1-t9b, provider-seam, eval, aud-34, scope-boundary, phase5, goal-loop, tripwire]
status: complete
last_updated: 2026-07-15
type: handoff
---

# Handoff: **Phase 1 is COMPLETE.** T9a + T9b merged; next decision is Phase 2 vs product bugs

> **`main` @ `eb1952d` — 553 passed, ruff clean, mypy clean. Nothing pushed (no remote).**
> Both Opus gate reviews returned **CLEAN, no blockers**. Two `feat:` merges this session
> (`351ec98` T9a, `eb1952d` T9b) = **cap 2/2, the `/goal` loop stops here by design.**
> P1-T9 was the last Phase-1 task. **No P1 tasks remain.**
>
> **AUD-34 is closed in substance, not in full** — an owner-approved, spec-backed carve-out.
> Read "The scope boundary" below before touching eval.

## Task(s)

1. ✅ **P1-T9a — product CLI seam.** Merged `351ec98`. Gate 495 → 539.
2. ✅ **P1-T9b — eval seam + AUD-34.** Merged `eb1952d`. Gate 539 → **553**.
3. ✅ **Phase 1 complete.** `docs/…/phase0-1-implementation-plan.md` has 9 P1 tasks; T9 was
   the last. `.superpowers/sdd/progress.md` confirms: "After P1-T9, Phase 1 is complete."
4. ⏳ **DECISION NEEDED: what's next** — Phase 2, or CLAUDE.md's Medium/Low product bugs.
   See Action Items #1.
5. ⏳ **OPEN DECISION carried since Session 17:** the "versioned" model id. Blocks v0.1.0.

## Critical References

1. `docs/superpowers/specs/2026-07-11-full-project-architecture.md` — **§9 Phase 5 (line 632)
   is the load-bearing line for the eval scope boundary**; §2 (88), §7.1 (527), §9 Phase 1 (616);
   §4.4 (258) provider/config contract, line 308 governs the model default.
2. `docs/superpowers/plans/2026-07-11-phase0-1-implementation-plan.md` §P1-T9 (line 297).
   **Its test-first (305) and acceptance (307) OVERREACH the spec — see the boundary below.**
3. `docs/superpowers/plans/2026-07-11-phase2-3-implementation-plan.md` — **untracked** (in the
   never-commit set); this is where Phase 2 work is planned.
4. `.claude/skills/goal/SKILL.md` — the loop playbook; `:57` Tripwire, `:93` step 1.

## Recent changes

**P1-T9a** (`351ec98`): `cli.py:95` `_provider_options` shared decorator; `cli.py:136`
`_resolve_provider_and_build` (pure plumbing); `cli.py:84` `DEFAULT_MODEL` re-export;
`config.py:26` `DEFAULT_ANTHROPIC_MODEL` (the ONLY `"claude-sonnet-5"` literal in `src/`);
`config.py:348-356` preset fallback; `annotation_generator.py:22` single-sources the literal;
`:149` keeps `model: str = DEFAULT_MODEL`. Plus `8c60708` (font-test hermeticity, post-merge).

**P1-T9b** (`eb1952d`):
- `src/halfblood/config.py:452` — NEW `resolve_eval_configs(generator_overrides,
  judge_overrides, *, environ, project_config_path, user_config_path, allow_self_judge)
  -> tuple[ResolvedConfig, ResolvedConfig]`. Delegates BOTH sides to the merged
  `resolve_generation_config`, then enforces judge independence LAST (`config.py:484-492`).
- `config.py:467-469` — `HALFBLOOD_EVAL_MODEL` → generator's model only, below an explicit
  `--model`. Cannot leak to the judge (`_ENVIRONMENT_FIELDS` maps only `HALFBLOOD_MODEL`).
- `eval/eval_harness.py` — 862 → 832 lines. Deleted `_fallback_generate`, `GENERATION_TOOL`,
  the `try/except ImportError` scaffolding, and the bare-except fallback branch.
  `generate_annotations` now takes `generator_provider` / `generator_model` keywords.
- `eval/eval_harness.py:41` — **`from anthropic import Anthropic` SURVIVES, by design**
  (judge transport only; Phase 5 moves it).
- `README.md:219` — `HALFBLOOD_EVAL_MODEL` documented as deprecated for one minor release.
- `tests/test_eval_seam.py` — NEW, 368 lines, 14 tests.

## Learnings

- **⚠️ THE SCOPE BOUNDARY — read before touching eval.** T9b could NOT be built as the plan
  described. Routing the judge through `LLMProvider` requires generalizing
  `GenerationResult.parsed` (hard-typed to `RecordAnnotations`,
  `generation/providers/base.py:45`) through `structured_output.py` (every parse fn returns it)
  and `providers/anthropic.py:248` (constructs it) — **4 merged src files under 161 merged
  tests**. Spec §9 Phase 5:632 independently assigns *"Move judge generation through the
  provider layer, separate generator and judge families"* to **Phase 5**; Phase 1:616 only says
  *"Update annotate, preview, and eval to use the same seam"*. **The technical reality
  corroborates the spec's own phasing** — that agreement is what makes this a reading rather
  than a rationalization, and the Opus reviewer independently confirmed it ("the controller did
  not under-deliver"). The PLAN overreaches its own spec. **Spec > plan.**
- **⚠️ I hit the recorded brief-vs-merged-code failure class AGAIN, from the other side.** My
  T9b brief told Codex to delete `_PIPELINE_DEFAULT_MODEL`; a merged T9a guard pinned it. The
  guard was using it as a **proxy** for "DEFAULT_MODEL still exists in annotation_generator.py"
  — its own failure message says so. The real invariant is pinned directly by a passing sibling
  (`test_annotation_generator_exports_default_model_constant`), so I removed the stale proxy.
  **Generalization: a test that asserts on a PROXY breaks when the proxy is legitimately
  refactored away, and the fix is indistinguishable from weakening a guard unless you can point
  at the direct test that still covers the invariant.** Prefer direct assertions.
- **Codex refused rather than bent (T9a).** It stopped at 535/539 and reported 4 failing
  controller tests as test defects: "weakening key validation or bypassing the seam would
  violate this brief." All 4 verified true. The brief's **FIRST-CLASS RULE naming the forbidden
  shortcut** is what gave it standing to escalate rather than rationalize. Both T9a and T9b
  briefs used this pattern; both merged review-clean.
- **Seam tasks break every fake positioned after the moved validation.** All 4 T9a test defects
  had ONE root cause: the seam moves the key check ahead of the `AnnotationGenerator` fakes that
  were shielding those tests. **Grep `monkeypatch.setattr(cli_module, ...)` before briefing any
  future seam task.**
- **A green gate and a CLEAN Opus review are both blind to "passes only because a file happens
  not to exist."** The T9a font-test fix read `cwd/halfblood.toml` + the user config off the
  real machine; both passed it. Caught only on a second pass. Proven load-bearing by planting
  arch §4.4's own example config → resolver picked up `provider = "openai"` and raised.
- **Codex's deviations were improvements twice.** T9a: caught `ProviderError` (the base of
  `ProviderConfigurationError`, `generation/errors.py:17`) — a strict superset. **Check the
  class hierarchy before flagging a deviation.**
- **A module-level import of a not-yet-existing symbol masks every other red test** in the file
  (collection error). `tests/test_eval_seam.py:52` imports `resolve_eval_configs` lazily inside
  the helper so each test fails for its OWN intended reason. Do this in every red-first file.
- **A test that passes before AND after pins nothing.** `test_eval_harness_imports_annotation_
  generator_unconditionally` was vacuous as first written (the guarded import succeeds today),
  so it asserts on SOURCE TEXT (`"except ImportError" not in source`) — the only thing that
  distinguishes built from unbuilt. Caught pre-dispatch by checking that all 14 were red.

## Verification

| Claim | Command run this session | Result |
|---|---|---|
| Gate on `main` post-merge (re-run after the last edit) | `.venv/bin/pytest tests/ -q` | `553 passed, 22 warnings` |
| Ruff clean on `main` | `.venv/bin/ruff check src tests eval --no-cache` | `All checks passed!` |
| Mypy clean on `main` | `.venv/bin/mypy src/halfblood` | `Success: no issues found in 22 source files` |
| T9b merge non-empty (Session 16 hazard) | `git show --stat HEAD` | 5 files, `create mode 100644 tests/test_eval_seam.py` |
| Test count ROSE (proves merge landed) | 539 pre-merge → post-merge | `553 passed` |
| `main` HEAD | `git rev-parse HEAD` | `eb1952d0d410ec7607ccaaff9c1ac7327d580b94` |
| T9b tripwire (a) Codex modified no test file | `sha256sum -c --quiet .superpowers/sdd/p1-t9b.testsums` | silent, exit 0 |
| T9b tripwire (b) none added/removed | `diff <(sed …) <(git ls-files …)` | empty, exit 0 |
| **Boundary held: zero diff to the provider layer** | `git status --porcelain -- src/halfblood/generation/` | empty |
| `resolve_eval_configs` exists at pinned signature | `grep -n "def resolve_eval_configs" src/halfblood/config.py` | `452:def resolve_eval_configs(` |
| Judge-independence check is LAST and names the remedy | `sed -n '483,492p' src/halfblood/config.py` | `if generator.provider == judge.provider and generator.model == judge.model and not allow_self_judge:` → raises "choose an independent judge with --judge-model, or use --allow-self-judge" |
| Inline fallback deleted | `grep -c "_fallback_generate\|GENERATION_TOOL" eval/eval_harness.py` | `0` |
| eval_harness shrank | `wc -l < eval/eval_harness.py` vs `git show 8b58383:eval/eval_harness.py \| wc -l` | `832` vs `862` |
| **SDK import survives for the judge (by design)** | `grep -n "from anthropic import" eval/eval_harness.py` | `41:from anthropic import Anthropic` |
| `RecordAnnotations` coupling is real (why the judge can't move) | `grep -rln "RecordAnnotations" src/halfblood/` | `schema.py`, `structured_output.py`, `providers/base.py`, `providers/anthropic.py` |
| 161 merged tests pin that layer | `grep -c '^def test'` × 6 files | `54+34+29+23+14+7 = 161` |
| Spec assigns the judge move to Phase 5 | `grep -n "^### " …architecture.md` + read 630-632 | line 630 `### Phase 5`; line 632 "Move judge generation through the provider layer" |
| All 14 T9b tests red pre-build, each for its own reason | `.venv/bin/pytest tests/test_eval_seam.py -q` (pre-dispatch) | `14 failed`; reasons: 10× absent `resolve_eval_configs`, `_fallback_generate` present, unexpected kwarg `generator_provider` |
| Pre-build gate | `.venv/bin/pytest tests/ -q` (pre-dispatch) | `14 failed, 539 passed` |
| T9b Opus review verdict | `Agent(general-purpose, model:opus)` on full diff vs brief | `CLEAN` — 0 blockers, 3 non-blocking |
| T9a Opus review verdict | `Agent(general-purpose, model:opus)` on full diff vs brief | `CLEAN` — 0 blockers, 3 non-blocking |
| Real invariant still covered after my proxy removal | `.venv/bin/pytest …::test_annotation_generator_exports_default_model_constant -q` | `1 passed` |
| Font tests hermetic (T9a follow-up) | planted arch §4.4 example config at repo root, `pytest tests/test_font_selection.py -q` | `8 passed` |
| Full suite immune to a stray config | planted config, `pytest tests/ -q` | `539 passed` (exposure was font-only) |
| Cap reached | `git log pre-overnight-2026-07-15..main --oneline \| grep -c ' feat:'` | `2` (cap is 2 → loop stops) |
| `main` clean of task paths | `git status --porcelain -- src tests eval` | empty |
| Nothing pushed | `git remote -v` | empty |
| Rollback tag | `git rev-parse --short pre-overnight-2026-07-15` | `8b58383` |

## Artifacts

- **Merged to `main`:** `src/halfblood/{cli,config,annotation_generator}.py`,
  `eval/eval_harness.py`, `README.md`, `tests/{test_cli_provider_seam,test_eval_seam,test_cli,
  test_font_selection}.py`.
- `.superpowers/sdd/p1-t9b-brief.md`, `p1-t9b-report.md`, `p1-t9b.testsums` — gitignored scratch.
- `.superpowers/sdd/p1-t9a-brief.md`, `p1-t9a-report.md`, `p1-t9a.testsums`, `p1-t9a-subdriver-spec.md`.
- `.superpowers/sdd/progress.md` — Session 18 entry appended (gitignored scratch).
- Branches `phase1-t9a` @ `f1b6722`, `phase1-t9b` @ `b6a1e73` — both merged, safe to delete.
- Rollback tags: `pre-overnight-2026-07-15` @ `8b58383`, `pre-overnight-2026-07-14` @ `09e57c7`.

## Action Items & Next Steps

1. **DECIDE WHAT'S NEXT — Phase 1 is done, so this is a real fork, not a default.**
   - **(a) Phase 2** (spec §9:618 — target resolution + layout correctness). Plan exists at
     `docs/superpowers/plans/2026-07-11-phase2-3-implementation-plan.md` (**untracked**).
     Spec says it "absorbs the inherited repeated-match, collision, and multi-node EPUB feature
     gaps" — i.e. **Phase 2 IS CLAUDE.md's bugs #13/#14/#15**, done properly on normalized text
     indexes rather than patched.
   - **(b) CLAUDE.md Medium/Low bugs first** (#12 async page processing, #13 `_search_variants`
     wrong-passage, #14 collision detection, #15 EPUB `_locate_text`). Note #13/#14/#15 overlap
     Phase 2 — doing them ad hoc likely means doing them twice.
   - Controller's read: **(a)**, because the overlap makes (b) largely redundant. #12 (async) is
     the one genuinely NOT in Phase 2 — spec §9:632 puts async windowed concurrency in Phase 5,
     and Phase 1 pinned `concurrency = 1` with a merged clamp (`test_provider_config.py:389`).
2. **OPEN DECISION — the "versioned" model id.** Arch §4.4:308 permits a provider default only
   where "known and **versioned**", rationale: *"This avoids recreating the retired-model
   failure."* T9a shipped `claude-sonnet-5`. **The sentence argues against itself:** its letter
   implies a pinned dated snapshot, but a pinned dated id is exactly what gets retired, so the
   floating id serves the stated rationale better. Suggest keeping the floating id and amending
   the spec to pin the RATIONALE. **Verify the id against live Anthropic docs (the `claude-api`
   skill) before acting — the loop forbids recalling model ids from memory.** Blocks v0.1.0.
3. **AUD-34 is closed in substance only — record this honestly.** Phase 1 stops the generator
   grading itself (default invocation now RAISES). Phase 5 (§9:632) separates families and moves
   the judge transport. If any ledger/table claims AUD-34 fully closed, correct it to reference
   the Phase-5 remainder. `tests/test_config.py`'s ledger-completeness test may need its P1-T9
   disposition updated — **check it.**
4. **Non-blocking from the T9b Opus review:** (a) `generate_for_page` swallows `ProviderError`
   internally (`_generate_for_page_tracked:301-305`) and returns `[]`, so a real provider failure
   scores as empty annotations rather than erroring — **pre-existing, not a T9b defect, but it
   undercuts eval fidelity**; (b) model-name comparison in the independence check is
   case-sensitive (`CLAUDE-SONNET-5` would evade) — contrived, no practical path.
5. **Non-blocking from the T9a Opus review:** (a)
   `test_annotate_with_anthropic_and_no_model_uses_preset_default` is not fully hermetic
   (CliRunner `env=` is additive) AND has the cwd-config exposure fixed for font tests — apply
   `monkeypatch.chdir(tmp_path)` + `XDG_CONFIG_HOME`, or better, an **autouse conftest fixture**
   closing the class repo-wide (`tests/conftest.py` has no `chdir`/`autouse` today). Verified
   NOT currently biting: the full suite passes with a hostile config planted. (b) `annotate`
   terminal width 120 → 160 (unbriefed, cosmetic). (c) 22 `DeprecationWarning`s from
   `AnnotationGenerator(api_key=...)` callsites in `test_pipeline.py` /
   `test_generation_orchestration.py` — correct behavior (T9a AC 10); migrate to `provider=`
   before v0.1.0.
6. **Loop hardening follow-ups** (deferred): (a) nothing guards the controller's/sub-driver's own
   `tests/` edits — **this session hit that twice** (the vacuous try/except test, the stale
   proxy); the only thing that caught them was an Opus re-read and my own second pass. (b)
   SKILL.md:93's step-1 fix is still **unvalidated on the unattended path**.
7. **`pytest-cov` still not installed** despite arch §4.5 listing it in `[dev]`. Minor.
8. **P1-T8 follow-ups** (deferred since Session 16): redact report `warnings` strings; validate
   `_hbp` container version on load; key-leak assertion in the online-doctor success test.

## Other Notes

- **Cap: 2/2 — the `/goal` loop stops.** Re-tag (`git tag pre-overnight-<date>` at `eb1952d`)
  before any further unattended run, per SKILL.md First-night safety.
- **Deliberate deviation this session:** I drove directly on Opus instead of spawning the Sonnet
  sub-driver the skill prescribes. Rationale: the sub-driver has diverged from the tree twice on
  this project, nothing guards its test edits, and T9b's deliverable IS the test authoring.
  Costs Opus tokens; avoided a known failure mode. Owner was informed and did not object.
- Repo on `/mnt/c` under WSL: use `.venv/bin/…`; always `git show --stat HEAD` after a merge.
  Both merges this session verified non-empty.
- `.claude/settings.local.json` `bypassPermissions` is intentional — do not "fix".
- A `PreToolUse` hook blocks `git reset --hard` on main/master — use `--mixed` for recovery.
- `thoughts/` is gitignored — this handoff needs `git add -f`.
- Handoff dir convention here is **flat**, not the `<ticket>/` subdir the skill suggests.
- Codex CLI `codex-cli 0.144.1`, chatgpt-authenticated, `gpt-5.6-sol` (1.05M context).
  T9a: ~19 min, 149,884 tokens. T9b: ~12 min. Context is never the reason to split — review
  surface is.
- **A bare `/goal` is NOT correct next session** — it would look for the next unstarted P1 task
  and find none ("plan complete"). Phase 2 needs its plan reviewed and the fork in #1 decided
  first.
