# Lane B Handoff — CLI E2E Validation with Stub Provider

**Date:** 2026-07-23  
**Branch:** `lane-b-cli-e2e`  
**HEAD:** `85505eeaa1cb39466afb205d1843bf016775a496`  
**Gate:** 1357 → 1377 tests (20 new, 0 regressions)

---

## What This Lane Delivered

One new test module: `tests/test_cli_end_to_end.py` (639 lines, 20 tests, zero src changes).

Covers the complete pipeline—CLI entry point → AnnotationGenerator → DocumentProcessor / EpubProcessor → output artifact—without a network call or an API key, by injecting a `DeterministicStubProvider` at the `halfblood.cli.build_provider` seam.

---

## Design Decisions

### Injection seam: `halfblood.cli.build_provider`

The CLI's `_resolve_provider_and_build` calls `build_provider(config, api_key=api_key)`. Monkeypatching `halfblood.cli.build_provider` with a lambda that returns the stub intercepts the provider construction without touching `AnnotationGenerator` or any business logic.

### Config hermeticity: wrap `resolve_generation_config`

`resolve_generation_config` reads `os.environ`, `Path.cwd()/halfblood.toml`, and `user_config_dir("halfblood")/config.toml`. The CLI only threads `project_config_path` (from `--config`), so `--config /nonexistent` alone would leave the user config unprotected.

Fix: monkeypatch `halfblood.cli.resolve_generation_config` with a wrapper that calls the **real** function with three sealed parameters:
- `environ={"ANTHROPIC_API_KEY": "stub-fake-key-for-testing"}`
- `project_config_path=tmp_path / "nonexistent_config.toml"`
- `user_config_path=tmp_path / "nonexistent_user.toml"`

This keeps the real config validation live (correct approach per advisor) while sealing all machine reads.

### Rich console capture: no monkeypatch needed

`console = Console()` in `cli.py` is created with `file=None`. Rich resolves `.file` as `sys.stdout` **at write time**, not at construction. CliRunner replaces `sys.stdout` during invoke, so Rich's output lands in `result.output`. Confirmed empirically before writing any tests.

### PDF assertions: drawings, not native annotations

`render_plan` uses the vector ink path (`InkComposer` / `PdfRenderer.render_scene`), which emits vector drawings (`page.get_drawings()`). Native PDF annotation objects (`page.annots()`) stay empty. All five KNOWN_PASSAGES passages resolve → `rendered_count == 5`.

### EPUB assertions: hbp- CSS classes + XHTML validity

All four EPUB_PASSAGES passages resolve → `rendered_count == 4`. Annotated chapters (ch1.xhtml, ch2.xhtml, ch3.xhtml) gain `hbp-` CSS class tokens. All chapters remain parseable XHTML (lxml).

### Determinism: structural equality, not byte equality

fitz writes two random 16-byte /ID values into the PDF trailer on each save. First byte difference appears at offset ~180,107 (near EOF) between any two renders of the same plan. Byte-level equality assertion would be wrong.

Correct assertion: same page count, same per-page drawing count across two independent runs. The nondeterminism test (`test_pdf_byte_output_differs_between_runs`) documents this behaviour explicitly — if fitz ever becomes deterministic, the test will fail and alert the team to upgrade to a byte-level check.

### Failure surface: `ProviderTransientError` on first call

`_PartialFailureProvider` raises on call 1 (page 1), returns success for calls 2–5. Outcome: `generator.failed_pages == [1]`, `plan.total_annotations == 4`. CLI exits 0, writes the output, prints "Warning: 1 page(s) failed". All-fail path (always raise) → `AllPagesFailedError` → `click.ClickException` → exit 1.

---

## Files Changed

- `tests/test_cli_end_to_end.py` — created (test-only, as required)

No src/, eval/, scripts/, config, or CLAUDE.md changes.

---

## Empirical Findings for Gate / Next Lane

1. **PDF drawings per page (stub, 1 annotation each):** pages 1–4 gain 5 drawings each, page 5 gains 7. Baseline is 0. Any regression that breaks the ink path will show as drawing count = 0.

2. **EPUB annotation resolve rate:** 4/4 (100%) for the chosen passages. `locate_across_nodes` handles inline-tag boundaries gracefully for these fixtures; the known limitation (cross-node spans) does not affect sample_book.epub.

3. **fitz nondeterminism:** only the /ID bytes (2 × 16 = 32 bytes near EOF) differ. All other bytes are identical. If a future renderer introduces additional randomness (e.g. random jitter seeds not yet seeded from annotation ID), the structural test will catch it.

4. **CliRunner Click version:** `CliRunner(mix_stderr=False)` raises `TypeError` in this project's Click version; `CliRunner()` is the correct call.

---

## Gate Summary

| Check | Before | After |
|---|---|---|
| `pytest tests/ -q` | 1357 passed | 1377 passed |
| `ruff check tests/test_cli_end_to_end.py` | n/a | clean |
| `mypy tests/test_cli_end_to_end.py` | n/a | no issues |
| Src changes | — | 0 |
