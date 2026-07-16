---
date: 2026-07-15T21:44:57-04:00
researcher: Claude (Opus 4.8) — controller session
git_commit: 8c60708ae1308f1c49da251889d5a5ab47fcd2e1
branch: main
repository: half-blood-prince
topic: "Session 18 — P1-T9a merged (provider seam for annotate/preview, 539 green); Codex refused 4 defective controller tests instead of bending product code; T9b next"
tags: [phase1, p1-t9a, provider-seam, cli, goal-loop, tripwire, codex-refusal, aud-02, aud-34]
status: complete
last_updated: 2026-07-15
type: handoff
---

# Handoff: P1-T9a merged (539 green); T9b (eval seam + AUD-34) is next

> **P1-T9a is merged to local `main` @ `351ec98`** — `annotate` and `preview` now route
> through `resolve_generation_config` + `build_provider`. Gate on `main`: **539 passed,
> ruff clean, mypy clean** (up from 495 — the merge is verified non-empty). The Opus gate
> review returned **CLEAN, no blockers**. Nothing pushed (no remote).
>
> **The notable event: Codex REFUSED to make 4 failing controller tests pass**, reporting
> that doing so "would require weakening key validation or bypassing the seam." It was
> right in all 4 cases. This is the *inverse* of the failure mode this project has
> recorded before (Codex bending product semantics to satisfy a defective test).

## Task(s)

1. ✅ **P1-T9a built, reviewed, merged.** Codex (gpt-5.6-sol) built against
   `.superpowers/sdd/p1-t9a-brief.md`; Opus review CLEAN; merged @ `351ec98`.
2. ✅ **4 controller test defects found and fixed** (see Learnings — all one root cause).
3. ✅ **Tripwire held.** Codex touched ZERO files under `tests/` and stayed entirely
   inside the brief's MAY-touch list. First task where the recursive tripwire ran for real.
4. ⏳ **NOT started: T9b** (eval seam + AUD-34 judge independence).
   `eval/eval_harness.py:44` still does `from anthropic import Anthropic`.
5. ⏳ **OPEN DECISION carried forward:** the "versioned" model id (see Action Items).

## Critical References

1. `docs/superpowers/specs/2026-07-11-full-project-architecture.md` §4.4 (line 258) — the
   provider/config contract. Line 308 governs the model default.
2. `docs/superpowers/plans/2026-07-11-phase0-1-implementation-plan.md` §P1-T9 (line 297).
3. `.claude/skills/goal/SKILL.md` — the loop playbook; `:57` Tripwire, `:93` step 1.
4. `.superpowers/sdd/p1-t9a-brief.md` — the T9a pinned interface (gitignored scratch).

## Recent changes

All on `main`, merged via `--no-ff` from `phase1-t9a`.

- `src/halfblood/cli.py:95` — new `_provider_options` shared Click decorator (all 10
  provider flags), applied to `annotate` and `preview` only.
- `src/halfblood/cli.py:136` — new `_resolve_provider_and_build` helper. **Pure plumbing,
  zero provider-setting validation** (the brief's FIRST-CLASS RULE).
- `src/halfblood/cli.py:84` — `DEFAULT_MODEL = _ANNOTATION_DEFAULT_MODEL` (re-export kept).
- `src/halfblood/config.py:26` — `DEFAULT_ANTHROPIC_MODEL: str = "claude-sonnet-5"` — the
  **only** such literal in `src/`.
- `src/halfblood/config.py:348-356` — preset fallback at the former single raise site.
- `src/halfblood/annotation_generator.py:22` — `from halfblood.config import
  DEFAULT_ANTHROPIC_MODEL as DEFAULT_MODEL` (single-sources the literal).
- `src/halfblood/annotation_generator.py:149` — `model: str = DEFAULT_MODEL` **kept**
  (merged guard test depends on it).
- `tests/test_font_selection.py`, `tests/test_cli_provider_seam.py` — controller test fixes.
- `README.md:163` — `api_key=` deprecation notice.

## Learnings

- **⚠️ THE BIG ONE — Codex refused rather than bent.** It stopped at 535/539 and reported
  four failing controller tests as *test* defects instead of making them pass. Its report:
  "Resolving those would require controller-owned test updates; weakening key validation or
  bypassing the seam would violate this brief." **All four claims verified true.** This is
  the opposite of the recorded `controller-test-defects-induce-scope-creep` failure mode.
  What made it possible is worth preserving: the brief pinned a **FIRST-CLASS RULE** ("if
  Codex writes an `if` that validates a provider setting in `cli.py`, that is a defect")
  plus an explicit MUST-NOT-touch list for `tests/`. A brief that names the *forbidden
  shortcut* gives the implementer standing to escalate instead of rationalize.
- **All 4 test defects had ONE root cause, and it is a seam-task signature.** The T9a seam
  makes the CLI resolve config — and enforce the merged "hosted providers require a key env
  var" contract (`config.py:385`) — **before** constructing the generator. Every test that
  faked `cli_module.AnnotationGenerator` to avoid needing a key was silently relying on the
  key check happening *inside* the thing it faked. Moving validation earlier in a call chain
  breaks every fake positioned later in that chain. **Expect this on any future seam task:
  grep for `monkeypatch.setattr(cli_module, ...)` before briefing.**
- **Codex's two deviations from the brief were both improvements, not defects.**
  (a) It catches `ProviderError` where the brief said `ProviderConfigurationError` — the
  latter subclasses the former (`generation/errors.py:17`), so the catch is a strict
  superset that also covers `build_provider` failures. (b) It put `build_provider` *inside*
  the try (the brief's reference pattern had it outside), converting a would-be traceback
  into a `ClickException`. Both were confirmed by the Opus review. **A deviation is not
  automatically a defect — check the class hierarchy before flagging.**
- **The vacuous-fixture hazard was real and had to be actively avoided.** Fixing
  `test_anthropic_preset_provides_default_model` by adding a key to `environ` risked making
  it pass off the injected env instead of the preset. It does not: the resolver reads the
  model from `HALFBLOOD_MODEL`, which is absent from the injected dict, and
  `sources["model"] == "preset"` pins the origin. Independently confirmed by Opus.
- **Font tests now drive the REAL resolver + REAL `build_provider`.** Chosen over
  duplicating `test_cli.py`'s ~40-line `_FAKE_CLI_CONFIG`/`_FakeCliProvider` scaffolding.
  Safe because `AnthropicProvider.__init__` only constructs an `httpx.Client` (no network),
  and the fake generator discards the provider. Trade-off: it couples font tests to
  provider resolution — if resolution gains a new required setting, they break again.
- **⚠️ That fix initially introduced a latent machine-dependent flake — caught only on a
  second review pass, AFTER the Opus review returned CLEAN.** Driving the real resolver
  through CliRunner means the font tests cannot pass `project_config_path`/`user_config_path`
  (the seam tests' hermeticity lever), so the resolver fell back to `Path.cwd()/halfblood.toml`
  and the platformdirs user config dir — **real machine paths**. It passed on this machine
  only because neither file happens to exist. **Proven load-bearing, not theoretical:**
  planting arch §4.4's own documented example config at the repo root makes
  `resolve_generation_config({}, environ={"ANTHROPIC_API_KEY": "x"})` raise
  `OPENAI_API_KEY is required for provider openai` — i.e. a developer trying the documented
  example would have broken the font suite. Fixed in `tests/test_font_selection.py`
  (`monkeypatch.chdir(tmp_path)` + `XDG_CONFIG_HOME` → empty tmp dir) @ `8c60708`; all 8 pass
  with that config planted. **Generalization: a test that reaches the real resolver without
  injectable config paths is non-hermetic by construction — the resolver's `or` fallbacks
  (`config.py`, `project_path`/`user_path`) read the machine. Neither the gate nor the Opus
  review caught this; both are blind to "passes only because a file happens not to exist."**
- **`git status` after `git checkout main` reports the never-commit set as modified**
  (`CLAUDE.md`, `.claude/`). Expected per SKILL.md:93 — not a stop condition.

## Verification

| Claim | Command run this session | Result |
|---|---|---|
| Gate on `main` post-merge (re-run after the last edit) | `.venv/bin/pytest tests/ -q` | `539 passed, 22 warnings` |
| Ruff clean on `main` | `.venv/bin/ruff check src tests eval --no-cache` | `All checks passed!` |
| Mypy clean on `main` | `.venv/bin/mypy src/halfblood` | `Success: no issues found in 22 source files` |
| Merge is non-empty (Session 16 hazard) | `git show --stat HEAD` | 7 files, `1657 insertions(+), 28 deletions(-)`, incl. `create mode 100644 tests/test_cli_provider_seam.py` |
| Test count ROSE (proves merge landed) | pre-merge `main` 495 → post-merge | `539 passed` |
| `main` HEAD | `git rev-parse HEAD` | `351ec9865b3501f29eb2a9d6626c7fbc56362a1c` |
| Tripwire (a): Codex modified no test file | `sha256sum -c --quiet .superpowers/sdd/p1-t9a.testsums` | silent, exit 0 |
| Tripwire (b): Codex added/removed no test file | `diff <(sed 's/^[0-9a-f]*  //' …testsums \| sort) <(git ls-files --cached --others --exclude-standard tests/ \| sort)` | empty, exit 0 |
| Tripwire covers whole tree | `wc -l < .superpowers/sdd/p1-t9a.testsums` | `34` files |
| (c) exactly ONE `claude-sonnet-5` literal in `src/` (AUD-02/03/04 stays closed) | `grep -rn '"claude-sonnet-5"' src/` | 1 hit: `config.py:26` |
| `config.py:26` content | `sed -n '26p' src/halfblood/config.py` | `DEFAULT_ANTHROPIC_MODEL: str = "claude-sonnet-5"` |
| (b) generator default kept | `sed -n '149p' src/halfblood/annotation_generator.py` | `        model: str = DEFAULT_MODEL,` |
| `cli.DEFAULT_MODEL` still exists | `sed -n '84p' src/halfblood/cli.py` | `DEFAULT_MODEL = _ANNOTATION_DEFAULT_MODEL` |
| (a) `cli.py:136` helper is pure plumbing | `sed -n '136p'` + read of `136-175` | `def _resolve_provider_and_build(` — body has no provider-setting `if`; only a None-filter + `api_key_env` ternary |
| (d) `--allow-insecure-http` wired | `grep -n "allow.insecure.http" src/halfblood/cli.py` | `123:        click.option("--allow-insecure-http", is_flag=True, default=False),` |
| Preset fallback at the raise site | `sed -n '348,356p' src/halfblood/config.py` | `if preset.default_model is not None:` → `sources["model"] = "preset"` / `else: raise` |
| `ProviderConfigurationError` subclasses `ProviderError` (broad catch is correct) | `grep -n "class Provider.*Error" -A 3 src/halfblood/generation/errors.py` | `17:class ProviderConfigurationError(ProviderError, ValueError):` |
| Decorator on annotate/preview but NOT web-preview (AC 2 + AC 9) | `grep -n "_provider_options\|^def annotate\|^def preview\|^def web_preview"` | `95` def, `337` annotate, `454` preview; `550 def web_preview` has none |
| Root cause of the 4 test defects | `.venv/bin/pytest tests/test_font_selection.py::test_font_path_is_passed_to_pdf_processor -q` (pre-fix) | `Error: Environment variable ANTHROPIC_API_KEY is required for provider anthropic` |
| Opus gate review verdict | `Agent(general-purpose, model:opus)` on the full diff vs brief | `CLEAN` — 0 blockers, 3 non-blocking |
| `main` clean of task paths | `git status --porcelain -- src tests eval` | empty |
| Cap status | `git log --oneline pre-overnight-2026-07-15..main \| grep -c "feat:"` | `1` (cap is 2) |
| Nothing pushed | `git remote -v` | empty |
| eval still imports the SDK (T9b's job) | `grep -n "from anthropic import" eval/eval_harness.py` | `44:from anthropic import Anthropic` |
| eval_harness size (T9b review surface) | `wc -l < eval/eval_harness.py` | `862` |
| Rollback tag | `git rev-parse --short pre-overnight-2026-07-15` | `8b58383` |
| Font tests were non-hermetic (resolver reads cwd config) | planted `[generation] provider="openai"` at repo root, then `resolve_generation_config({}, environ={"ANTHROPIC_API_KEY": "x"})` | `ProviderConfigurationError: Environment variable OPENAI_API_KEY is required for provider openai` — proves cwd config IS read |
| Hermeticity fix works | `.venv/bin/pytest tests/test_font_selection.py -q` with that config planted | `8 passed` |
| Gate still green after the fix (re-run after last edit) | `.venv/bin/pytest tests/ -q` | `539 passed, 22 warnings` |
| No `chdir`/`autouse` in conftest (why the hole existed) | `grep -n "chdir\|XDG_CONFIG_HOME\|autouse" tests/conftest.py` | no matches |
| No repo-root or user config on this machine (why it passed anyway) | `ls halfblood.toml`; `ls ~/.config/halfblood/config.toml` | both `No such file or directory` |

## Artifacts

- `src/halfblood/cli.py`, `config.py`, `annotation_generator.py`, `README.md` — **merged**
  @ `351ec98` (feat commit `f1b6722` on `phase1-t9a`).
- `tests/test_cli_provider_seam.py` (NEW, 1365 lines), `tests/test_cli.py`,
  `tests/test_font_selection.py` — **merged**. `test_font_selection.py` further hardened
  for hermeticity @ `8c60708` (post-merge, directly on `main`).
- `.superpowers/sdd/p1-t9a.testsums` — the tripwire manifest (gitignored scratch).
- `.superpowers/sdd/p1-t9a-report.md` — Codex's own build report (gitignored scratch).
- `.superpowers/sdd/p1-t9a-brief.md`, `p1-t9a-subdriver-spec.md` — gitignored scratch.
- Rollback tags: `pre-overnight-2026-07-15` @ `8b58383` (newest), `pre-overnight-2026-07-14`
  @ `09e57c7`, `pre-overnight-2026-07-13` @ `51bc017`.

## Action Items & Next Steps

1. **T9b — eval seam + AUD-34.** `eval/eval_harness.py` is **862 lines with effectively
   zero behavioral coverage** (`tests/test_config.py` only checks the `[eval]` extras group
   exists). **Author real eval tests BEFORE briefing the rewrite.** Note `eval_harness.py:60`
   hard-imports `DEFAULT_MODEL` from `annotation_generator` at module level and nothing in
   `tests/` imports `eval_harness` — so `pytest tests/` stays green while `eval/` breaks.
   The T9a brief's AC 5c guard test (`test_eval_harness_imports_without_error`) now covers
   the import, but nothing covers eval *behavior*.
2. **Before briefing T9b, run the seam-task audit that has now paid off twice:** (a) grep
   `tests/` for fakes positioned after the code you're about to move validation ahead of
   (`monkeypatch.setattr(cli_module, ...)`); (b) inventory what the merged config/test layer
   ALREADY owns (`grep -n "^def test" tests/test_provider_config.py`) so the brief pins
   "zero validation logic here" rather than re-deriving it.
3. **OPEN DECISION — the "versioned" model id.** Arch §4.4:308 says the carve-out is for a
   default that is "known and **versioned**". `claude-sonnet-5` is an alias, not a pinned
   dated id. Deliberately unchanged (changing it under a wiring task = behavior change;
   inventing an id from memory = forbidden). **Decide before v0.1.0.**
4. **Non-blocking from the Opus review (recorded, not blocking):**
   (a) `test_annotate_with_anthropic_and_no_model_uses_preset_default` is not fully hermetic
   — CliRunner's `env=` is additive, so a machine with `HALFBLOOD_MODEL` set could satisfy
   it without the preset. **It also has the cwd-config exposure fixed for the font tests
   @ `8c60708`** (it reaches the real resolver through CliRunner, so `Path.cwd()/halfblood.toml`
   and the user config dir are live). The hermetic guard
   `test_anthropic_preset_provides_default_model` closes the *preset* gap, so this is not
   blocking — but apply the same `monkeypatch.chdir(tmp_path)` + `XDG_CONFIG_HOME` treatment,
   and consider an **autouse conftest fixture** doing both repo-wide, which would close this
   class permanently instead of per-test (`tests/conftest.py` currently has no `chdir` or
   `autouse` at all).
   (b) `annotate`'s terminal width changed 120 → 160 (in-scope but unbriefed; cosmetic).
   (c) 22 `DeprecationWarning`s from `AnnotationGenerator(api_key=...)` callsites in
   `test_pipeline.py` / `test_generation_orchestration.py` — correct behavior (AC 10), but
   migrate those callsites to `provider=` before v0.1.0.
5. **Loop hardening follow-ups** (deferred; do NOT do inline mid-task): (a) nothing guards
   the sub-driver's own `tests/` edits; (b) SKILL.md:93's step-1 fix is still **unvalidated
   on the unattended path** — this session verified git state by hand again.
6. **`pytest-cov` is not installed** despite arch §4.5 listing it in `[dev]` — coverage
   still cannot be measured. Minor gap.
7. **Non-blocking P1-T8 follow-ups** (deferred since Session 16): redact report `warnings`
   strings; validate `_hbp` container version on load; key-leak assertion in the
   online-doctor success test.

## Other Notes

- **Cap status:** 1 `feat:` merge since `pre-overnight-2026-07-15`. T9b fits under the cap
  of 2 without a re-tag.
- The `phase1-t9a` branch still exists at `f1b6722` (merged). Safe to delete.
- Repo on `/mnt/c` under WSL: use `.venv/bin/…`; expect occasional transient FS I/O errors —
  always `git show --stat HEAD` after a merge. This session's merge was verified non-empty.
- `.claude/settings.local.json` `bypassPermissions` is intentional — do not "fix".
- A `PreToolUse` hook blocks `git reset --hard` on main/master — use `--mixed` for recovery.
- `thoughts/` is gitignored — this handoff needs `git add -f`.
- Handoff dir convention here is **flat**, not the `<ticket>/` subdir the skill suggests;
  matched the 14 existing files.
- Codex CLI `codex-cli 0.144.1`, chatgpt-authenticated. `gpt-5.6-sol` = 1.05M context.
  T9a build took ~19 min wall-clock, 149,884 tokens.
- **Do NOT open the next session with a bare `/goal`** if resuming T9b mid-flight — it is
  the entry point for a FRESH task. A bare `/goal` IS correct for starting T9b from scratch,
  since T9a is merged and `main` is clean.
