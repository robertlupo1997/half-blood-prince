# Lane F Handoff — Persona Unification + --persona-file + Config Support
**Date**: 2026-07-23
**Branch**: `lane-f-persona`
**Head SHA**: `3699e9d`
**Gate numbers**: pytest 1443 passed / 0 failed | ruff: clean | mypy: clean (42 files)

---

## What Was Done

### The Bug Fixed

Two divergent `DEFAULT_PERSONA` constants existed:
- `cli.py:88` — short generic "sardonic expert" text, used as Click option default → **always passed**
- `annotation_generator.py:69` — the full Snape persona, fallback only when `persona=None` → **unreachable**

The full Snape Half-Blood Prince persona was unreachable through the CLI. Every bare invocation of `halfblood annotate` or `halfblood preview` passed the generic text, bypassing the real Snape voice.

### Changes Made

**`src/halfblood/config.py`**:
- Added `"persona": "HALFBLOOD_PERSONA"` and `"persona_file": "HALFBLOOD_PERSONA_FILE"` to `_ENVIRONMENT_FIELDS`
- Added `persona: str | None = None` to `ResolvedConfig` as the trailing field with a default (placed AFTER `sources` to avoid breaking 7 existing test files that construct `ResolvedConfig` by keyword)
- Added `_read_persona_file()` private helper
- Added per-level persona resolver in `resolve_generation_config` with:
  - Same-level `persona` + `persona_file` conflict detection (raises `ProviderConfigurationError`)
  - Precedence: CLI overrides > `HALFBLOOD_PERSONA`/`HALFBLOOD_PERSONA_FILE` env > project toml > user toml > None
  - `persona_file` from TOML resolved relative to that TOML file's parent directory
  - `persona_file` from env treated as absolute path
  - Source tracking in `sources["persona"]`

**`src/halfblood/cli.py`**:
- Deleted `DEFAULT_PERSONA` constant (was unused after the fix; `annotation_generator.DEFAULT_PERSONA` is the single source of truth)
- Changed `--persona` default from the short generic text to `None` on both `annotate` and `preview`
- Added `--persona-file PATH` option to both `annotate` and `preview` (mutually exclusive with `--persona`)
- Added `_resolve_persona(persona_flag, persona_file, config_persona)` helper:
  - Both flags given → `click.UsageError` (mutually exclusive)
  - `--persona` given → return it directly
  - `--persona-file` given → read file as UTF-8, `click.ClickException` if missing/unreadable
  - Neither → fall back to `config.persona` (may be None → generator uses Snape default)
- Threaded `effective_persona` to `AnnotationGenerator(persona=effective_persona, ...)` in both commands

### Behavior Change (Intentional)

Bare `halfblood annotate` / `halfblood preview` now gets the **full Half-Blood Prince (Severus Snape) persona** instead of the short generic "sardonic expert" text. The full persona is in `annotation_generator.DEFAULT_PERSONA` and is applied via the `persona or DEFAULT_PERSONA` fallback in `AnnotationGenerator.__init__`.

---

## Tests Authored (Red-First)

**File**: `tests/test_persona_config.py` — 24 tests total, committed red at `5777dc9`, all green at `3699e9d`.

### Tests that were RED pre-impl (now green):
1. `test_cli_annotate_bare_passes_none_to_generator` — verified CLI passes None, not old generic text
2. `test_cli_preview_bare_passes_none_to_generator` — same for preview
3. `test_persona_file_flag_appears_in_annotate_help` — flag didn't exist
4. `test_persona_file_flag_appears_in_preview_help` — flag didn't exist
5. `test_persona_file_reads_file_content_as_persona` — flag didn't exist
6. `test_persona_file_preview_reads_file_content` — flag didn't exist
7. `test_persona_file_missing_raises_click_exception` — flag didn't exist
8. `test_persona_and_persona_file_both_given_is_usage_error` — flag didn't exist (now checks for non-"no such option" conflict message)
9. `test_config_persona_from_project_toml` — ResolvedConfig had no `persona` field
10. `test_config_persona_from_user_toml` — same
11. `test_config_persona_from_halfblood_persona_env` — HALFBLOOD_PERSONA not in _ENVIRONMENT_FIELDS
12. `test_config_persona_from_halfblood_persona_file_env` — same
13. `test_config_persona_file_relative_to_config_dir` — persona_file key not recognized
14. `test_config_persona_precedence_cli_over_env_over_project_over_user` — no persona resolution
15. `test_config_project_toml_same_level_persona_and_persona_file_is_error` — no conflict detection
16. `test_config_user_toml_same_level_persona_and_persona_file_is_error` — same
17. `test_config_no_persona_resolves_to_none` — no persona field
18. `test_config_persona_file_missing_raises_configuration_error` — no file resolution
19. `test_cli_threads_config_persona_to_generator_when_no_flag` — config.persona not threaded

### Tests that were GREEN pre-impl (baseline and regression guards):
1. `test_generator_default_persona_contains_snape_signature` — baseline: DEFAULT_PERSONA is already Snape
2. `test_generator_none_persona_uses_snape_default` — baseline: generator already has `persona or DEFAULT_PERSONA`
3. `test_generator_explicit_persona_overrides_default` — baseline
4. `test_cli_explicit_persona_flag_passes_text_to_generator` — regression guard: explicit --persona still works
5. `test_cli_explicit_persona_flag_overrides_config_persona` — regression guard: CLI flag overrides config

### Existing tests touched:
**None.** No existing test files were modified. The 7 existing files that construct `ResolvedConfig` by keyword (`test_cli.py`, `test_cli_provider_seam.py`, `test_dry_run_progress.py`, `test_phase2_regressions.py`, `test_token_usage.py`, `test_provider_doctor.py`, `test_provider_profiles.py`) all work without modification because `persona` was added as a trailing field with a default of None.

---

## Codex Receipt

- **Script**: `~/dev-harness/scripts/codex-receipts.sh`
- **Receipt path**: `/tmp/claude-1000/-mnt-c-Users-Trey-Downloads-half-blood-prince/15ca87c7-cd50-47c5-92f6-dc0bee6bc7e8/scratchpad/lane-f-codex-receipt.json`
- **Exit code**: 0
- **Observable**: true
- **Retry advice**: safe
- **Changed paths**: `src/halfblood/cli.py` (modified), `src/halfblood/config.py` (modified)

---

## Changed-Default Evidence

Before (cli.py line 374, now deleted):
```python
@click.option("--persona", default=DEFAULT_PERSONA, show_default=False, ...)
```
Where `DEFAULT_PERSONA = "A brilliant, sardonic expert who has mastered this subject and can't help scrawling corrections and improvements in the margins. Terse. Impatient with mediocrity. Occasionally shows flashes of dark humor."`

After:
```python
@click.option("--persona", default=None, show_default=False, ...)
```
With `effective_persona = _resolve_persona(persona, persona_file, config.persona)` threading `None` to the generator, which then applies the full Snape `DEFAULT_PERSONA` from `annotation_generator.py`.

Test proof: `test_cli_annotate_bare_passes_none_to_generator` captures `_PersonaCapturingGenerator.last_persona` and asserts it is `None` (not the old short text).

---

## Scope Discipline

Lane F touched ONLY:
- `src/halfblood/config.py` — persona resolution added
- `src/halfblood/cli.py` — --persona-file flag + persona threading
- `tests/test_persona_config.py` — new test file (authored by lane driver)

Did NOT touch: `layout/`, `document_processor.py`, any provider file, `CLAUDE.md`, `.claude/`.

---

## Gate Readiness

```
pytest tests/ -q          → 1443 passed, 0 failed, 28 warnings
ruff check src tests eval scripts → All checks passed!
mypy src/halfblood         → Success: no issues found in 42 source files
```

Branch: `lane-f-persona` — ready for orchestrator gate + Opus review before merge to `main`.
