# Lane C Handoff — `--dry-run` flag + streaming per-page progress callback

**Date**: 2026-07-23  
**Branch**: `lane-c-dryrun-progress`  
**HEAD SHA**: `4e1265d7f17808a2570a8581df7d3ac0dac52922`  
**Base SHA**: `592bd9c` (merge of lane-a-async-generation)

---

## Result: COMPLETE

All deliverables implemented, tested, and verified.

---

## Gate Numbers

| Check | Before | After |
|---|---|---|
| `pytest tests/` (excl. test_cli_end_to_end.py) | 1371 passed | 1382 passed (+11) |
| `ruff check src tests eval scripts` | clean | clean |
| `mypy src/halfblood` | 0 issues | 0 issues |
| Lane C tests | 10 failed / 1 passed | 11 passed |

---

## Commits on Branch

1. `5c086f4` — `test(lane-c): red tests for --dry-run flag and per-page progress callback`  
2. `4e1265d` — `feat(lane-c): --dry-run flag + streaming per-page progress callback`

---

## Files Changed

### `src/halfblood/annotation_generator.py`
- Added `from collections.abc import Callable` import
- `generate_for_document` gains `on_page_done: Callable[[int, int], None] | None = None` keyword parameter
- Callback fires from the orchestrating thread immediately after each `plan.pages.append()` inside the wave-assembly loop
- Signature: `on_page_done(done_count, total)` where `done_count` = `len(plan.pages)` (1-indexed) and `total` = `len(pages)` (constant)
- Never fires from ThreadPoolExecutor worker threads
- Docstring updated

### `src/halfblood/cli.py`
- Added `import inspect` at top
- Added `_generate_with_progress(generator, pages, max_per_page, on_page_done)` helper — uses `inspect.signature` to pass callback only when the generator's `generate_for_document` accepts `on_page_done`, preserving compatibility with third-party doubles that have older signatures
- `annotate` command:
  - New `--dry-run` flag (`is_flag=True`, documented in help)
  - `dry_run: bool` added to function signature
  - Suffix-mismatch warning suppressed when `dry_run=True`
  - Callback wired via `_generate_with_progress` (bar advances per page)
  - Dry-run branch: writes `plan.model_dump_json()` to `-o`; prints "dry run — no artifact rendered" summary; returns before rendering
- `preview` command:
  - Callback wired via `_generate_with_progress` (same pattern)

---

## Design Decisions

### Dry-run output format: raw `plan.model_dump_json()` (NOT `plan_io.save_plan`)

`plan_io.save_plan` writes an `{"_hbp": "1.0", "plan": {...}, "report": ...}` wrapper.  
`web_preview._load_plan` calls `AnnotationPlan.model_validate_json(path.read_text())` directly — this expects a top-level `title` key, not the `_hbp` wrapper.

Using raw `plan.model_dump_json()` gives a same-class round-trip that works with `web-preview` as-is, without needing to migrate `_load_plan`. Updating `_load_plan` to handle the wrapper would have required changing `test_web_preview.py` behavior and risked unintended schema migrations. **Decision: dry-run writes raw JSON.**

### `_generate_with_progress` compatibility shim

Codex introduced an `inspect.signature` check to avoid `TypeError` when the callback is passed to generator doubles with old signatures. The `_CapturingGenerator` in `test_cli_provider_seam.py` was updated (by the lane driver) to accept `on_page_done=None` before Codex ran, so this shim is belt-and-suspenders rather than strictly necessary in the test suite. Safe to keep.

### Wave-burst progress behavior

With `k=3` concurrency, the progress bar advances in bursts of `k` when each wave completes (3 pages at a time). This is correct per the brief: "With concurrency k, the bar advances in wave-completion bursts — that's correct and expected; do not fake smooth per-page timing."

---

## Test Coverage

### New file: `tests/test_dry_run_progress.py` (11 tests)

| Test | What it proves |
|---|---|
| `test_callback_k1_fires_n_times_in_order_from_main_thread` | k=1: callback fires N times, monotonically 1..N, from calling thread |
| `test_callback_k3_fires_n_times_in_order_from_main_thread` | k=3: same guarantees despite wave concurrency |
| `test_callback_blank_pages_still_fire` | Blank/skipped pages still trigger one callback fire each |
| `test_callback_total_correct_and_done_monotonic` | total == len(pages); done strictly increasing |
| `test_dry_run_writes_json_and_does_not_render` | JSON written; `render_plan`/`render_annotations` NOT called (spy asserts) |
| `test_dry_run_json_round_trips_through_web_preview` | dry-run JSON loadable by `generate_preview`; returns valid `PreviewResult` |
| `test_dry_run_summary_mentions_dry_run_and_no_artifact` | Output contains "dry run" and "no artifact rendered" (case-insensitive) |
| `test_dry_run_force_overwrites_existing_file` | `--force` overwrites; output contains updated content |
| `test_dry_run_rejects_existing_output_without_force` | Without `--force`, exits non-zero on existing output file |
| `test_annotate_wires_progress_callback` | `annotate --dry-run` passes non-None `on_page_done` to `generate_for_document` |
| `test_preview_wires_progress_callback` | `preview` passes non-None `on_page_done` to `generate_for_document` |

### Updated: `tests/test_cli_provider_seam.py`
- `_CapturingGenerator.generate_for_document` updated to accept `on_page_done=None` keyword arg
- No acceptance criterion assertions changed — this is a test double maintenance update to prevent `TypeError` when the CLI calls `generate_for_document(..., on_page_done=callback)` through the seam fake

---

## Receipt Paths

- Codex brief: `/tmp/claude-1000/-mnt-c-Users-Trey-Downloads-half-blood-prince/15ca87c7-cd50-47c5-92f6-dc0bee6bc7e8/scratchpad/lane-c-codex-brief.md`
- Codex output: `/tmp/claude-1000/-mnt-c-Users-Trey-Downloads-half-blood-prince/15ca87c7-cd50-47c5-92f6-dc0bee6bc7e8/scratchpad/lane-c-codex-out.md`
- Codex receipt: `/tmp/claude-1000/-mnt-c-Users-Trey-Downloads-half-blood-prince/15ca87c7-cd50-47c5-92f6-dc0bee6bc7e8/scratchpad/lane-c-codex-receipt.json`

---

## Anomalies / Notes

- `test_cli_end_to_end.py` excluded from full-suite run per lane-driver instructions (parallel lane B owns that file).
- The `_generate_with_progress` helper uses `inspect.signature` for generator-double compatibility. Direct equivalent: `generator.generate_for_document(pages, max_annotations_per_page=n, on_page_done=cb)`.
- Codex tokens used: 91,836 (gpt-5.6-sol, effort=high).
