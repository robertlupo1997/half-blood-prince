# Latest Handoff

> **Latest handoff:**
> `thoughts/shared/handoffs/2026-07-15_21-44-57_session18-p1-t9a-merged-t9b-next.md`
> — **P1-T9a merged to local `main` @ `351ec98`**: `annotate`/`preview` now route through `resolve_generation_config` + `build_provider`; gate on `main` is **539 passed, ruff + mypy clean** (up from 495 — merge verified non-empty), Opus gate review **CLEAN**, nothing pushed. The tripwire held: Codex touched zero files under `tests/`. Notably, **Codex refused to make 4 failing controller tests pass**, correctly reporting them as test defects rather than weakening key validation — all 4 shared one root cause (the seam moves the key check ahead of the fakes that shielded it). 1 `feat:` merge against a cap of 2. **Next:** T9b (eval seam + AUD-34) — author real eval tests BEFORE briefing the rewrite of the 862-line, effectively-uncovered `eval/eval_harness.py`.
