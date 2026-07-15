---
date: 2026-07-15T16:16:18-04:00
researcher: Claude (Opus 4.8) — controller session
git_commit: 8b583837557dae167b50f1c45bf3b9b7e05fb071
branch: phase1-t9a
repository: half-blood-prince
topic: "Session 17 — /goal loop hardened (tripwire + step-1); P1-T9 split into T9a/T9b; T9a brief + 37 failing tests ready for Codex; five brief defects caught pre-build"
tags: [phase1, p1-t9, provider-seam, cli, goal-loop, tripwire, brief-vs-plan, sub-driver, aud-34]
status: complete
last_updated: 2026-07-15
type: handoff
---

# Handoff: /goal hardened; P1-T9 split; T9a brief ready to dispatch (nothing built yet)

> Two `/goal` unattended-run defects fixed and verified. **P1-T9 split into T9a (product
> CLI seam) + T9b (eval seam + AUD-34)** with owner approval. The **T9a brief + 37 failing
> tests are authored and verified** — Codex has NOT been dispatched. **`main` is untouched
> at `8b58383` (495 green).** Five brief-level defects were caught at the brief-vs-plan
> checkpoint before any code was built; three would have merged gate-green.

## Task(s)

1. ✅ **Tripwire made recursive/addition-aware** (the open item from the Session 16
   adversarial review). `.claude/skills/goal/SKILL.md:57` now defines a canonical
   TRIPWIRE-SNAPSHOT/TRIPWIRE-VERIFY pair over a `git ls-files` manifest + hashes of the
   whole `tests/` tree. Empirically proven against 3 evasion paths (see Learnings).
2. ✅ **Step-1 dirty-git STOP-FLAG contradiction fixed** (`SKILL.md:93`). Found while
   orienting, not previously known. See Learnings.
3. ✅ **P1-T9 split into T9a/T9b** — owner-approved. T9a = product CLI seam. T9b = eval
   seam + AUD-34 judge independence.
4. ✅ **T9a brief + failing tests authored + verified.** `.superpowers/sdd/p1-t9a-brief.md`,
   `tests/test_cli_provider_seam.py` (new), `tests/test_cli.py` (extended).
   Gate on branch: **37 failed, 502 passed** — all 37 fail for the intended reason.
5. ⏳ **NOT done: dispatch Codex for T9a.** The brief is ready. This is the next action.
6. ⏳ **NOT started: T9b** (eval seam + AUD-34). `eval/eval_harness.py:44` still does
   `from anthropic import Anthropic`.

## Critical References

1. `.superpowers/sdd/p1-t9a-brief.md` — the pinned interface Codex builds against. Ready.
2. `.superpowers/sdd/p1-t9a-subdriver-spec.md` — the Opus-authored scope spec, incl. all 10
   acceptance criteria and the WITHDRAWN/corrected decisions with rationale.
3. `docs/superpowers/specs/2026-07-11-full-project-architecture.md` §4.4 (line 258) — the
   provider/config contract. **Line 308 is the load-bearing sentence** for the model default.
4. `docs/superpowers/plans/2026-07-11-phase0-1-implementation-plan.md` §P1-T9 (line 297).
5. `.claude/skills/goal/SKILL.md` — the loop playbook, hardened twice this session.

## Recent changes

**No product code has been built.** `main` carries only docs commits; the T9a tests are
committed (WIP, red by design) on branch `phase1-t9a`.

- `main` @ `9e099f9` — `docs:` this handoff + pointer. Parent `8b58383` (Session 16 handoff)
  is the last commit before this session; product code on `main` is unchanged since then.
- `phase1-t9a` @ `b082337` — `test:` the 37 failing T9a tests (WIP; **Codex NOT dispatched**).
  Branches from `8b58383`, so it does NOT contain this handoff — that is expected; the branch
  never touches `HANDOFF.md`, so the eventual merge keeps `main`'s pointer with no conflict.

- `.claude/skills/goal/SKILL.md:57` — new `## Tripwire (controller-owned tests/)` section.
- `.claude/skills/goal/SKILL.md:93` — step 1 rewritten (task-scoped dirty check).
- `.claude/skills/goal/SKILL.md` steps 3/5/6/7a — now reference TRIPWIRE-SNAPSHOT/VERIFY.
- `tests/test_cli_provider_seam.py` — NEW, ~37 behavioral tests for the T9a seam.
- `tests/test_cli.py` — extended (fake config/provider + widened `_FakeGenerator`).
- `git tag pre-overnight-2026-07-15` @ `8b58383`.

## Learnings

- **The tripwire glob covered 27 of 33 files.** `sha256sum tests/*.py` excluded ALL of
  `tests/fixtures/` — including the executable generators `make_test_epub.py` and
  `make_potions_textbook.py` and the sample PDFs/EPUBs the suite depends on — plus any file
  ADDED after the snapshot. Verified fix catches all three evasions (nested-fixture edit,
  top-level addition, nested addition) with no false positive on a clean tree.
- **Step 1's dirty-git check contradicted step 8.** Step 8 forbids ever committing
  `CLAUDE.md`/`.claude/`, so those are permanently dirty — a bare `git status`-clean check
  would STOP-FLAG every unattended run on line one, or (worse) teach the driver to
  rationalize past a safety check. Now scoped to `src tests eval`. **NOTE: this fix is
  UNVALIDATED on the path it protects** — this session verified git state by hand.
- **⚠️ THE BIG ONE — every real defect came from the brief contradicting already-merged,
  merged-test-pinned code, never from the plan being wrong.** Five caught this session:
  1. **Model default**: the plan/arch permit an anthropic default (§4.4:308 "unless a
     provider-specific default is known and versioned"); merged `config.py:342` is STRICTER
     and raises for every provider. Owner chose the architecture's intent.
  2. **AUD-02/03/04 near-reopening**: naively adding `"claude-sonnet-5"` to the preset would
     have re-created the "default model hard-coded in three places" finding that is already
     fixed and guarded by `tests/test_config.py`.
  3. **Merged constructor guard**: `test_generator_default_model_is_current` asserts
     `AnnotationGenerator(api_key=...).model == "claude-sonnet-5"` — so the CONSTRUCTOR keeps
     its `model` default. "No universal default" governs the CLI/config layer only.
  4. **Concurrency REJECT (I approved it; it was a bug)**: merged `config.py:407-421` CLAMPS
     with a warning and `tests/test_provider_config.py:389` pins that contract. REJECT would
     hard-error `--concurrency 3` while `concurrency = 3` in TOML silently clamped — one knob,
     two behaviors, with arch §4.4's own example config (spec line 279) shipping
     `concurrency = 3`. The sub-driver's tests only covered the flag, never the config path,
     so this would have merged GREEN.
  5. **`--allow-insecure-http` missing entirely** — mandated by arch §4.4:306; the resolver
     field, env var, and merged test all exist. Only the CLI flag was absent, making
     `--base-url http://hosted` impossible from the CLI.
  **The generalization that kills the class:** merged `config.py` already owns and tests the
  COMPLETE contract for all 10 provider settings (inventory:
  `grep -n "^def test" tests/test_provider_config.py`). The CLI's correct diff contains
  **ZERO validation logic** — pure plumbing into `cli_overrides`. The brief now pins that as a
  first-class rule. **Do this audit FIRST on any future seam task.**
- **Sub-driver reports diverged from the tree twice.** It reported "corrections applied"
  having applied only the first batch; test counts were byte-identical to the pre-correction
  run, which was the cheapest tell. The tripwire guards *Codex* touching `tests/` — **nothing
  guards the sub-driver's own test edits**, and it authors the tests that define correctness.
  Structural hole in the lean loop; the only thing closing it today is an Opus re-read, which
  is the exact spend the sub-driver exists to avoid.
- **Vacuous-fixture risk**: `tests/test_cli.py`'s `fakes` fixture patches
  `resolve_generation_config` with `lambda *a, **k: _FAKE_CLI_CONFIG` — argument-ignoring.
  Any test about resolution that goes through it passes vacuously. The anthropic-default and
  concurrency-clamp tests were explicitly required to drive the REAL resolver hermetically.

## Verification

| Claim | Command run this session | Result |
|---|---|---|
| No product code built; `main` product code unchanged since Session 16 | `git log --oneline -2 main` | `9e099f9 docs: Session 17 handoff` → `8b58383 docs: Session 16 handoff` — both `docs:` only |
| T9a tests committed (durable, not just in the working tree) | `git log --oneline -2 phase1-t9a` | `b082337 test: failing tests for the P1-T9a provider seam (WIP…)` → `8b58383` |
| T9a branch tree clean (nothing left unsaved) | `git status --porcelain -- src tests eval` | empty |
| Merge won't clobber the pointer | `git diff --name-only 8b58383 phase1-t9a -- HANDOFF.md` | empty — branch never touched it |
| Brief is gitignored scratch (survives sessions on disk; `git clean -xfd` WOULD destroy it) | `git check-ignore -v .superpowers/sdd/p1-t9a-brief.md` | `.gitignore:51:.superpowers/` |
| Nothing pushed (no remote) | `git remote -v` | empty |
| Tripwire section exists | `grep -n "^## Tripwire" .claude/skills/goal/SKILL.md` | `57:## Tripwire (controller-owned \`tests/\`)` |
| Step-1 fix in place | `grep -n "task-scoped paths" .claude/skills/goal/SKILL.md` | `93:1. **Orient.** Git must be clean **of task-scoped paths**…` |
| Old tripwire glob had 27/33 coverage | `ls tests/*.py \| wc -l` vs `git ls-files --cached --others --exclude-standard tests/ \| wc -l` | `27` vs `33`; diff = 6 files under `tests/fixtures/` |
| New tripwire catches all 3 evasions | scripted: nested-fixture edit → `FAILED`; top-level add → `> tests/test_codex_sneaked_this_in.py`; nested add → `> tests/sub/test_nested.py`; baseline+restore silent | all 3 caught, 0 false positives |
| Rollback tag | `git rev-parse --short pre-overnight-2026-07-15` | `8b58383` |
| T9a gate (branch, pre-build) | `.venv/bin/pytest tests/ -q` (re-run after last edit) | `37 failed, 502 passed, 11 warnings` |
| New test files ruff-clean | `.venv/bin/ruff check tests/test_cli.py tests/test_cli_provider_seam.py --no-cache` | `All checks passed!` |
| No REJECT pin survives in brief | `grep -n "must be 1\|UsageError" .superpowers/sdd/p1-t9a-brief.md` | only negative context (`:316` "no `click.UsageError`", `:466` "An earlier draft… the owner [reversed]") |
| Concurrency tests are clamp + config-path | `grep -n "def test.*concurrency" tests/test_cli_provider_seam.py` | `811 _three_is_clamped_not_rejected`, `865 _one_is_accepted`, `902 _no_concurrency_flag_accepted`, `936 _via_config_file_is_clamped` |
| `--allow-insecure-http` pinned | `grep -n "allow-insecure-http" .superpowers/sdd/p1-t9a-brief.md` | `116:` flag table row |
| Merged code raises for missing model | `sed -n '341,342p' src/halfblood/config.py` | `if model_setting is None:` / `raise ProviderConfigurationError("model must be explicitly configured")` |
| `ProviderPreset` has no model field | `sed -n '61,67p' src/halfblood/config.py` | `class ProviderPreset:` — fields `name`, `default_base_url`, `default_key_env`, `default_structured_output` |
| Merged concurrency contract = CLAMP | `sed -n '386,401p' tests/test_provider_config.py` | `concurrency == 1`, `sources["concurrency"] == "phase1_enforced"`, warning asserted |
| Merged missing-model test uses ollama (so anthropic fallback breaks nothing) | `sed -n '198,200p' tests/test_provider_config.py` | `_resolve(tmp_path, cli_overrides={"model": None, "provider": "ollama"})` |
| eval still imports the SDK (T9b's job) | `grep -n "from anthropic import" eval/eval_harness.py` | `44:from anthropic import Anthropic` |
| Session 16 handoff's "SDK fully absent" claim was scoped to src/tests only | `grep -rn "import anthropic\|from anthropic" src/ tests/ eval/` | 1 hit, in `eval/` — its command never covered `eval/` |
| gpt-5.6-sol context window | OpenAI docs `developers.openai.com/api/docs/models/gpt-5.6-sol` | 1,050,000 context / 128,000 max output |
| Artifacts exist | `ls .superpowers/sdd/p1-t9a-brief.md .superpowers/sdd/p1-t9a-subdriver-spec.md tests/test_cli_provider_seam.py` | all 3 present |

## Artifacts

- `.superpowers/sdd/p1-t9a-brief.md` — the Codex-ready pinned interface (gitignored scratch).
- `.superpowers/sdd/p1-t9a-subdriver-spec.md` — Opus scope spec + WITHDRAWN/corrected
  decisions with rationale (gitignored scratch).
- `tests/test_cli_provider_seam.py` — NEW, **committed** on `phase1-t9a` @ `b082337`.
- `tests/test_cli.py` — extended, **committed** on `phase1-t9a` @ `b082337`.
- `.claude/skills/goal/SKILL.md` — hardened (never auto-committed).
- Rollback tags: `pre-overnight-2026-07-15` @ `8b58383` (newest), `pre-overnight-2026-07-14`
  @ `09e57c7`, `pre-overnight-2026-07-13` @ `51bc017`.

## Action Items & Next Steps

1. **Dispatch Codex for T9a** — the brief is ready and the tests are red for the right
   reasons. `git checkout phase1-t9a` first (the tests live there @ `b082337`; `main` does
   not have them). **Then run TRIPWIRE-SNAPSHOT** (SKILL.md:57) — it has NOT been taken yet.
   Then: `codex exec --sandbox workspace-write -C <repo> -m gpt-5.6-sol -c
   model_reasoning_effort=high -o .superpowers/sdd/p1-t9a-report.md <
   .superpowers/sdd/p1-t9a-brief.md`.
   **Do NOT open with a bare `/goal`** — it is the entry point for a FRESH task and would
   re-branch from `main`, skipping the T9a work entirely. Resume from this handoff instead.
2. **At the Opus gate review, specifically check:** (a) `cli.py` contains ZERO provider-setting
   validation (the whole point of Correction 5); (b) `AnnotationGenerator.__init__` still has
   `model: str = DEFAULT_MODEL` and `cli.DEFAULT_MODEL` still exists (merged guards); (c) only
   ONE `"claude-sonnet-5"` literal exists in `src/` (AUD-02/03/04); (d) `--allow-insecure-http`
   is in scope (arch prose, NOT in the plan's test-first list — flagged deliberately).
3. **Then T9b** — eval seam + AUD-34. Note `eval/eval_harness.py` is **862 lines with
   effectively zero behavioral coverage** (`tests/test_config.py` only checks the `[eval]`
   extras group exists). Author real eval tests BEFORE briefing the rewrite.
4. **OPEN DECISION — the "versioned" model id.** Arch §4.4:308 says the carve-out is for a
   default that is "known and **versioned**". `claude-sonnet-5` is an alias, not a pinned
   dated id. Kept as-is deliberately (changing it under a wiring task = behavior change;
   inventing an id from memory = forbidden). Decide before v0.1.0.
5. **`pytest-cov` is not installed** despite arch §4.5 listing it in `[dev]` — coverage could
   not be measured. Minor gap.
6. **Loop hardening follow-ups** (deferred, do NOT do inline mid-task): (a) nothing guards the
   sub-driver's own `tests/` edits; (b) the step-1 fix is unvalidated on the unattended path.
7. **Non-blocking P1-T8 follow-ups** (still deferred from Session 16): redact report
   `warnings` strings; validate `_hbp` container version on load; key-leak assertion in the
   online-doctor success test.

## Other Notes

- **Cap status:** 0 `feat:` merges since `pre-overnight-2026-07-15`. T9a and T9b both fit
  under the cap of 2 without another re-tag.
- Repo on `/mnt/c` under WSL: use `.venv/bin/…`; expect occasional transient FS I/O errors —
  always `git show --stat HEAD` after a merge (Session 16 lost a whole task to an empty merge).
- `.claude/settings.local.json` `bypassPermissions` is intentional — do not "fix".
- A `PreToolUse` hook blocks `git reset --hard` on main/master — use `--mixed` for recovery.
- `thoughts/` is gitignored — this handoff needs `git add -f`.
- Handoff dir convention here is **flat**, not the `<ticket>/` subdir the skill suggests;
  matched the 13 existing files.
- Codex CLI `codex-cli 0.144.1`, chatgpt-authenticated. `gpt-5.6-sol` = 1.05M context, so
  context is never the reason to split a task — **review surface is**.
