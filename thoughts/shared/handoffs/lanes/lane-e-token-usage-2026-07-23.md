# Lane E Handoff — Token Usage Aggregation + CLI Reporting

**Date:** 2026-07-23
**Branch:** `lane-e-token-usage`
**Head SHA:** `eaf4972eee7dc59dc47479e3104c3a078f7b50b5`
**Off of main SHA:** `9078af3107353cd53eb6a04bfde1b841344c20c9`

---

## What was built

Token usage aggregation from the generation layer through to CLI output, end-to-end.

### New public surface

**`UsageTotals` dataclass** (`src/halfblood/annotation_generator.py`):
```python
@dataclass
class UsageTotals:
    input_tokens: int
    output_tokens: int
    pages_with_usage: int      # pages where provider returned non-None usage
    pages_missing_usage: int   # pages attempted + succeeded but usage was None
```

**`generator.usage_totals`** — set on every `generate_for_document` call (reset at start, like `failed_pages`). Initialized to zeros in `__init__`.

**CLI helper `_print_usage_line(generator, console)`** (`src/halfblood/cli.py`):
- Reads via `getattr(generator, "usage_totals", None)` — safe for old fakes
- Suppressed when `pages_with_usage == 0`
- Appends `" — usage unavailable for N page(s)"` when `pages_missing_usage > 0`
- Wired in three places: `annotate` (inside progress block, before dry-run branch), `annotate --dry-run` (same location covers both), `preview` (after progress block, before annotation dump)

### Internal changes

**`_generate_for_page_tracked` → 5-tuple:**
- Added `GenerationUsage | None` at position [4]
- Blank page: `([], False, False, None, None)`
- Failed page: `([], True, True, exc, None)`
- Success: `(annotations, True, False, None, result.usage)`

**Wave loop in `generate_for_document`:**
- Accumulates `total_input_tokens`, `total_output_tokens`, `pages_with_usage`, `pages_missing_usage`
- Condition: only `attempted_call and not failed` pages contribute; `page_usage is None` → `pages_missing_usage += 1`
- `self.usage_totals` assigned before the `AllPagesFailedError` raise

---

## Gate numbers

| Check | Result |
|---|---|
| `pytest tests/ -q` | **1413 passed, 28 warnings** |
| `ruff check src tests eval scripts` | Clean |
| `mypy src/halfblood` | Clean (42 source files) |

Baseline (pre-lane): 1402 tests. Lane adds 11 new tests.

---

## Commits on branch

1. `2b09f1c` — `test(lane-e): red tests for token usage aggregation + CLI reporting` (11 tests, 10 red)
2. `eaf4972` — `feat(lane-e): token usage aggregation + CLI reporting`

---

## Existing test files touched and why

| File | Why |
|---|---|
| `tests/test_generation_orchestration.py` | `_Recorder.__call__` returned a 4-tuple; `generate_for_document` now unpacks a 5-tuple. Updated arity and docstring. |

No other existing test files were modified. CLI fakes in `test_cli.py` and `test_dry_run_progress.py` are untouched — `_print_usage_line` uses `getattr(..., None)` so they continue to work (they produce no token line, which is the correct behaviour for fakes that don't set `usage_totals`).

---

## Receipts

- Brief: `/tmp/claude-1000/-mnt-c-Users-Trey-Downloads-half-blood-prince/15ca87c7-cd50-47c5-92f6-dc0bee6bc7e8/scratchpad/lane-e-codex-brief.md`
- Receipt: `/tmp/claude-1000/-mnt-c-Users-Trey-Downloads-half-blood-prince/15ca87c7-cd50-47c5-92f6-dc0bee6bc7e8/scratchpad/lane-e-codex-receipt.json.receipt.json`
- Codex model: `gpt-5.6-sol`, effort: `high`, duration: 344s

---

## Design decisions

- **No `GenerationResult.usage` type change**: `usage` stays `GenerationUsage` (non-Optional) in `base.py` — no provider changes. The 5-tuple slot is `GenerationUsage | None` to allow test doubles to inject `None` (testing provider-omits-usage scenarios).
- **`getattr` pattern on CLI**: Old fakes that don't set `usage_totals` produce no token line (correct fallback). New instances of real `AnnotationGenerator` always have `usage_totals` (set in `__init__`).
- **No pricing table**: counts only, per the design decision in the brief.
- **Failed pages excluded**: failed pages go to `failed_pages` list (already surfaced by the "N page(s) failed" warning line). Double-counting them in `pages_missing_usage` would confuse users.
- **Blank pages excluded**: blank pages make no API call; neither counter should increment.

---

## Gate merge instructions (for orchestrator)

```bash
# From the primary checkout
git merge --no-ff lane-e-token-usage -m "Merge lane-e-token-usage: token usage aggregation + CLI reporting"
```

Pre-merge gate: full suite + ruff (src tests eval scripts) + mypy + ONE Opus review.
