# Lane A Handoff — async/concurrent page generation
**Date:** 2026-07-23  
**Branch:** `lane-a-async-generation`  
**Head SHA:** `57ed3d6`  
**Worktree:** `/mnt/c/Users/Trey/Downloads/half-blood-prince/.claude/worktrees/agent-a795bcecbd99f592b`

---

## Result Summary

Lane complete. All deliverables implemented, tested, and verified.

- Thread-pool wave concurrency implemented in `AnnotationGenerator.generate_for_document`
- Phase-1 concurrency hard-lock removed from `config.py`; replaced with unlock + clamp(1..8), default 3
- `config.concurrency` wired through CLI to generator constructor
- 1371 tests pass (was 1357 before lane; +14 net new tests)
- `ruff check src/ tests/ eval/ scripts/` → clean
- `mypy src/halfblood/` → clean

---

## Commits on Branch

```
57ed3d6  feat: async/concurrent page generation (Lane A)
9bcc84c  tests: async generation contract (Lane A, controller-authored, red)
```

**Authorship timeline:**
- `9bcc84c`: Controller (Claude lane-a agent) authored all tests before Codex dispatch. Tests were intentionally red (28 failures).
- `57ed3d6`: Src implementation by Codex (gpt-5.6-sol, receipt below) + controller-authored contract guard updates to test files (adding `concurrency=3` to fake generator `__init__` signatures, updating stale `_FAKE_CLI_SOURCES` and AC6 concurrency assertions to reflect unlock semantics).

---

## Design

Implemented exactly per brief with one clarification:

**Wave semantics**: `generate_for_document` processes pages in consecutive waves of `k`. Each wave's prompts are built from `running_notes` as of the end of the PREVIOUS wave (snapshot). After a wave completes, its INVENTION/WARNING notes are folded in PAGE ORDER into `running_notes`, trimmed to last 8, then the next wave starts. k=1 reduces to the prior sequential behavior exactly.

**Thread safety**: `ThreadPoolExecutor` + per-index result slots (no shared list appends). Results assembled in wave-page order. `_generate_for_page_tracked` remains the per-page unit (existing tests monkeypatch it); it catches ProviderError internally so a failing page returns a tuple rather than poisoning siblings.

**Provider thread safety verified**: Both `AnthropicProvider` and `OpenAICompatProvider` use `httpx.Client` (documented thread-safe) with retry state as local loop variables — no per-call mutable instance state. Safe to share across threads.

---

## k=1 Sequential-Equivalence Evidence

Two tests prove this explicitly:
- `test_k1_two_runs_produce_identical_plans` — two k=1 runs on the same input yield identical plans
- `test_k1_carries_invention_and_warning_notes_forward` — INVENTION/WARNING carry-forward matches expected sequential behavior

Mechanically: with k=1, each "wave" is one page, and the `ThreadPoolExecutor` fast-path is bypassed (k=1 uses a sequential loop). `running_notes` accumulate one page at a time, identical to the pre-lane sequential loop. The wave note-folding step (`running_notes.extend(wave_new_notes); del running_notes[:-8]`) applied to single-element waves is mathematically equivalent to the old per-page accumulation.

---

## Test Counts

| Scope | Before | After |
|---|---|---|
| Full suite | 1357 | 1371 |
| New tests (test_async_generation.py) | 0 | 14 |
| Updated existing tests | — | 44 (k=1 pins + contract guards) |

New tests cover: k=1 ordered results, k=1 note carry-forward, k=1 determinism, wave isolation, wave cross-wave notes, page-order assembly, Barrier concurrency proof, k=3 determinism, k=3 failure injection (failing page doesn't poison siblings), k=3 failed_pages page-ordered, default concurrency=3.

---

## Config Changes

**Removed:** `_SOURCE_PHASE1 = "phase1_enforced"` (no longer needed after unlock)

**Added:**
```python
_CONCURRENCY_DEFAULT = 3
_CONCURRENCY_MIN = 1
_CONCURRENCY_MAX = 8
```

Explicit values in range [1,8] pass through with `sources["concurrency"]` set to the originating source (e.g. "cli", "project_config"). Out-of-range values are clamped with a WARNING. Unconfigured defaults to 3 with `sources["concurrency"] == "default"`.

---

## Test Contract Updates (Existing Files)

Files I updated (controller, not Codex):
- `tests/test_generation_orchestration.py`: `_run()` helper now sets `kwargs.setdefault("concurrency", 1)` so call-order and running_notes assertions are stable; `test_all_failed_raises` direct call pinned to `concurrency=1`.
- `tests/test_failure_handling.py`: All `generate_for_document()` calls pinned to `concurrency=1`; `_FakeProvider` uses a sequential index counter that is not thread-safe — these tests exercise failure semantics, not concurrency.
- `tests/test_provider_config.py`: Replaced two Phase-1 lock tests with five unlock/clamp/default tests.
- `tests/test_cli.py`, `tests/test_cli_provider_seam.py`, `tests/test_font_selection.py`, `tests/test_phase2_regressions.py`: Added `concurrency: int = 3` to all `_FakeGenerator`/`_CapturingGenerator.__init__` signatures (contract guards mirror the real `AnnotationGenerator.__init__`); updated `_FAKE_CLI_SOURCES["concurrency"]` from `"phase1"` → `"default"` and `_FAKE_CLI_CONFIG.concurrency` from 1 → 3; updated AC6 concurrency assertions in `test_cli_provider_seam.py` (4 tests) from Phase-1-clamp semantics to unlock+valid-passthrough semantics.

---

## Receipt Paths

- **Brief:** `/tmp/claude-1000/-mnt-c-Users-Trey-Downloads-half-blood-prince/15ca87c7-cd50-47c5-92f6-dc0bee6bc7e8/scratchpad/codex-brief-async-generation.md`
- **Receipt:** `/tmp/claude-1000/-mnt-c-Users-Trey-Downloads-half-blood-prince/15ca87c7-cd50-47c5-92f6-dc0bee6bc7e8/scratchpad/codex-async-gen-receipt.json`
- **Codex output:** `/tmp/claude-1000/-mnt-c-Users-Trey-Downloads-half-blood-prince/15ca87c7-cd50-47c5-92f6-dc0bee6bc7e8/scratchpad/codex-async-gen-out.md`

Receipt metadata: model=gpt-5.6-sol, effort=high, duration=315s, workspace_git.head_before=9bcc84c (test commit), changed_paths=[annotation_generator.py, cli.py, config.py], wrapper_rc=0.

---

## Anomalies

1. **Codex made uncommitted changes** (head_before == head_after in receipt). Codex left src changes as working-tree modifications; they were staged and committed by the controller in the feat commit (57ed3d6).

2. **Baseline was 1357 not "44 tests"** — the brief referenced "all 44 tests should pass" from an older CLAUDE.md; the actual test count at session start was 1357. The baseline 1357 green → 1371 green (14 new tests, all passing).

3. **Ruff: one import-ordering fix** on `test_async_generation.py` required `ruff check --fix` after initial write. Applied before commit.

4. **25 previously-passing tests regressed after Codex** due to `_FakeGenerator.__init__` not accepting `concurrency=`. These were all contract guard tests that intentionally mirror `AnnotationGenerator.__init__` — they catch exactly this kind of signature change. Fixed by controller (adding `concurrency: int = 3` to 4 fake generator classes and updating stale assertions). All 25 restored to green.

---

## Gates Before Merge

Required per brief: full `pytest tests/ -q`, `ruff check src tests eval scripts`, `mypy src/halfblood`, ONE Opus review.

Gate numbers (self-verified in worktree):
- **pytest:** 1371 passed, 0 failed, 12 warnings
- **ruff:** All checks passed
- **mypy:** Success, no issues found in 42 source files

Opus review is the orchestrator's gate to schedule.
