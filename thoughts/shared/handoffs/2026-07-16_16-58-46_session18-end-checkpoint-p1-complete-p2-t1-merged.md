---
date: 2026-07-16T16:58:46-04:00
researcher: Claude (Opus 4.8) — controller session
git_commit: bf34c13032dace4c11ba03fbe6eb100b279d80ec
branch: main
repository: half-blood-prince
topic: "Session 18 end-of-session checkpoint — three merges (P1-T9a, P1-T9b, P2-T1); Phase 1 complete, Phase 2 started; 495 → 642 green"
tags: [session-checkpoint, phase1-complete, phase2, p1-t9a, p1-t9b, p2-t1, goal-loop]
status: complete
last_updated: 2026-07-16
type: handoff
---

# Session 18 checkpoint — Phase 1 complete, Phase 2 started; `main` @ `bf34c13`, 642 green

> Session-end checkpoint. **Nothing has changed since the P2-T1 handoff at `bf34c13`** — same
> HEAD, working tree clean of task paths. This consolidates the whole session's arc; the two
> per-task handoffs below carry the deep detail. **`main` @ `bf34c13`: 642 passed, ruff +
> mypy clean, nothing pushed (no remote).**

## Task(s)

Three tasks built → reviewed → merged this session, each via the `/goal` lean loop
(brief + failing tests → Codex builds → Opus adversarial review → merge to local `main`):

1. ✅ **P1-T9a** — product CLI seam. `annotate`/`preview` route through
   `resolve_generation_config` + `build_provider`. Merged `351ec98`. (495 → 539)
2. ✅ **P1-T9b** — eval seam + AUD-34. Eval generation routes through the seam; generator and
   judge resolve independently; the default invocation now RAISES rather than self-judging.
   Merged `eb1952d`. (539 → 553) **→ Phase 1 COMPLETE.**
3. ✅ **P2-T1** — normalized text index with reversible offsets (`documents/matching.py`).
   Merged `d2f5d23`. (553 → 642) **→ Phase 2 STARTED.**
4. ⏳ **P2-T2** — quote selectors + contextual evidence — is next.
5. ⏳ **OPEN DECISION:** the "versioned" model id (arch §4.4:308) — blocks v0.1.0.

## Critical References

1. **Per-task handoffs (deep detail):**
   - `thoughts/shared/handoffs/2026-07-16_09-55-56_session18-p2-t1-merged-p2-t2-next.md` (P2-T1 —
     includes the offset-map blocker, the fix, and the stacked-mark limitation).
   - `thoughts/shared/handoffs/2026-07-15_22-58-52_session18-phase1-complete-t9a-t9b-merged.md`
     (P1-T9a/b — the AUD-34 scope boundary and the Phase-5 deferral).
2. `docs/superpowers/plans/2026-07-11-phase2-3-implementation-plan.md` — Phase 2 plan; **P2-T2
   line 31** is next.
3. `docs/superpowers/specs/2026-07-11-full-project-architecture.md` §§3.1-3.2, 5.5, 7.2 (Phase 2
   matching); §4.4:308 (the model-default decision); §9 Phase 5:632 (judge transport deferral).
4. `.claude/skills/goal/SKILL.md` — the loop playbook.

## Recent changes (this session, all on `main`)

- `src/halfblood/cli.py` — `_provider_options` decorator + `_resolve_provider_and_build` (pure
  plumbing) on `annotate`/`preview` (P1-T9a).
- `src/halfblood/config.py` — `DEFAULT_ANTHROPIC_MODEL` + `ProviderPreset.default_model` preset
  fallback (P1-T9a); `resolve_eval_configs` with judge-independence check (P1-T9b). Exactly ONE
  `"claude-sonnet-5"` literal in `src/` (`config.py:26`).
- `eval/eval_harness.py` — routes generation through the seam; inline Anthropic fallback deleted;
  judge transport keeps `from anthropic import Anthropic` by design (Phase-5 deferral) (P1-T9b).
- `src/halfblood/documents/{__init__,matching}.py` — NEW normalized text index (P2-T1).
- `src/halfblood/{document_processor,epub_processor}.py` — `_normalize_search_text` are now
  byte-identical delegates over the shared index (P2-T1).
- Tests added: `test_cli_provider_seam.py`, `test_eval_seam.py`, `test_text_index.py`,
  `test_normalization_delegates.py`; plus targeted fixes to `test_cli.py`, `test_font_selection.py`.

## Learnings (session-level — see per-task handoffs for full detail)

- **Codex refused to bend on P1-T9a**, reporting 4 failing controller tests as test defects
  rather than weakening key validation. All 4 verified true; the brief's named-forbidden-shortcut
  rule is what enabled the escalation. Opposite of the recorded scope-creep failure mode.
- **The Opus gate review caught a real P2-T1 blocker a green gate hid** — the reversible offset
  map broke under canonical combining-mark reordering (10089 valid-NFC sequences). Fixed via
  prefix-alignment; verified across an 8k fuzz. The review is load-bearing, not ceremonial.
- **Two of my own controller mistakes were caught by the advisor, not the loop:** a non-hermetic
  font test (reads `cwd/halfblood.toml`), and an over-reaching regression test asserting a
  *provably impossible* per-slice reversibility. Nothing in the loop guards the controller's own
  test edits — a standing structural gap.
- **AUD-34 is closed in substance, not in full** (owner-approved, spec-backed): the judge's
  transport stays on the SDK because `GenerationResult.parsed` is hard-typed to
  `RecordAnnotations`; spec §9 Phase 5:632 assigns the move to Phase 5.

## Verification

| Claim | Command run this session | Result |
|---|---|---|
| Gate on `main` (re-run at checkpoint) | `.venv/bin/pytest tests/ -q` | `642 passed, 22 warnings` |
| Ruff clean | `.venv/bin/ruff check src tests eval --no-cache` | `All checks passed!` |
| Mypy clean | `.venv/bin/mypy src/halfblood` | `Success: no issues found in 24 source files` |
| `main` HEAD unchanged since P2-T1 handoff | `git rev-parse HEAD` | `bf34c13032dace4c11ba03fbe6eb100b279d80ec` |
| Working tree clean of task paths | `git status --porcelain -- src tests eval` | empty (only never-commit set dirty) |
| The three merges landed | `git log --oneline --grep="Merge phase" main` | `d2f5d23` P2-T1, `eb1952d` P1-T9b, `351ec98` P1-T9a |
| Test count grew 495 → 642 across the session | pytest counts per merge | 495 → 539 → 553 → 642 |
| eval SDK import survives (judge transport only) | `grep -c "from anthropic import" eval/eval_harness.py` | `1` |
| Exactly one model literal in `src/` (AUD-02/03/04 closed) | `grep -rc '"claude-sonnet-5"' src/` | `config.py:1`, all others 0 |
| `documents/` package exists (P2-T1) | `ls src/halfblood/documents/` | `__init__.py  matching.py` |
| Rollback tags present | `git tag \| grep -E "pre-phase2\|pre-overnight-2026-07-15"` | `pre-overnight-2026-07-15`, `pre-phase2-2026-07-16` |
| Nothing pushed | `git remote -v` | empty |
| Pointer target current | `grep "Latest handoff" -A1 HANDOFF.md` | (updated below to this file) |

## Artifacts

- **Merged to `main`** (this session): `cli.py`, `config.py`, `annotation_generator.py`,
  `eval/eval_harness.py`, `documents/{__init__,matching}.py`, `document_processor.py`,
  `epub_processor.py`, `README.md`, and 4 new + 2 edited test files.
- Handoffs: this checkpoint + the two per-task handoffs listed under Critical References.
- Gitignored scratch under `.superpowers/sdd/`: `p1-t9a-*`, `p1-t9b-*`, `p2-t1-*` briefs/reports,
  `*.testsums`, `progress.md`.
- Merged branches (safe to delete): `phase1-t9a`, `phase1-t9b`, `phase2-t1`.
- Rollback tags: `pre-phase2-2026-07-16` @ `7ade9cd`, `pre-overnight-2026-07-15` @ `8b58383`.

## Action Items & Next Steps

1. **P2-T2 — quote selectors + contextual evidence** (plan line 31; depends P2-T1). Renderer-
   neutral quote + prefix/suffix context + approximate position. Its durable v2 serialization is
   coupled to Phase-1 `P1-T1` — confirm that task's status before assuming v2 model types exist;
   core selector validation can proceed independently.
2. **Known P2-T1 limitation, deferred to P2-T3:** clusters whose NFC retains 3+/duplicate
   combining marks may return a *covering* (not exact) span. P2-T3 (scoring/ambiguity) owns
   grapheme-cluster-aware match precision — close it there, not piecemeal in `matching.py`.
3. **OPEN DECISION — the "versioned" model id** (arch §4.4:308). `claude-sonnet-5` is a floating
   alias; the spec argues against itself (a pinned dated id is what gets retired). Recommend
   keeping the floating id and amending the spec to pin the rationale. Verify against live
   Anthropic docs (`claude-api` skill) first. Blocks v0.1.0.
4. **Deferred backlog (unchanged):** autouse conftest hermeticity fixture; migrate deprecated
   `AnnotationGenerator(api_key=...)` test callsites; `pytest-cov` not installed; P1-T8 report
   redaction; loop-hardening (nothing guards controller test edits).

## Other Notes

- **Cap:** since re-tag `pre-phase2-2026-07-16`, one task merged (P2-T1). Re-tag before any
  unattended continuation.
- **Attended-run deviations this session** (both recorded): drove directly on Opus rather than a
  Sonnet sub-driver (the sub-driver has diverged from the tree twice here, and test authoring was
  the deliverable); and substituted exhaustive empirical verification for the loop's step-7d
  fresh-Opus re-review of the P2-T1 fix (the fix's core question is a numeric property best
  checked by computation).
- Repo on `/mnt/c` under WSL: use `.venv/bin/…`; always `git show --stat HEAD` after a merge (all
  three this session verified non-empty). `.claude/settings.local.json` `bypassPermissions` is
  intentional. `PreToolUse` hook blocks `git reset --hard` on main — use `--mixed`. `thoughts/`
  is gitignored (needs `git add -f`).
- **A bare `/goal` next session** reads the active plan for the next unstarted task; point it at
  the Phase 2 plan (its SKILL text still name-checks P1-T6), or resume from the P2-T1 handoff for
  P2-T2.
