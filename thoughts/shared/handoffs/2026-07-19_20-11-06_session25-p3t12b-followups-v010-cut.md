---
date: 2026-07-19T20:11:06-04:00
researcher: Claude (Opus 4.8)
git_commit: e1552e4c21b7605e3b6a03432482f00b845bed8a
branch: main
repository: half-blood-prince
topic: "P3-T12b integration merged + review follow-ups + v0.1.0 cut — Phase 3 NO-GO redirect COMPLETE"
tags: [pdf-rendering, ink-scene, renderer, composer, cli, render-plan, release, codex, lean-loop]
status: complete
last_updated: 2026-07-19
type: handoff
---

# Handoff: Session 25 — P3-T12b integrated, follow-ups landed, v0.1.0 cut

> **The P3-T5 NO-GO redirect is now fully complete and tagged `v0.1.0`.** Rough vector ink
> marks finally reach the PDF. There is **no runnable un-gated Phase-3 work left** — the
> `/goal` loop is out of tasks (P3-T6→T10 stay NO-GO-blocked). Next work is a decision, not
> a loop iteration: post-v0.1.0 polish (5 recorded non-blockers were already resolved),
> reopening P3-T5 for letterforms (owner call, large), or new milestone scope.

## Task(s)

- ✅ **P3-T12b — integration** (wire `InkComposer` + `PdfRenderer` into `render_plan`).
  Merged `5d92644` (feat `a343585`). Opus review: APPROVE, zero blockers.
- ✅ **P3-T12b review follow-ups** (5 non-blocking findings). Merged `e1552e4`
  (refactor `ae0319f`). 3 fixed, 1 honestly removed, 1 consciously declined (see Learnings).
- ✅ **v0.1.0 cut** — annotated **local** tag `v0.1.0` at `e1552e4` (NOT pushed).
- ⛔ **P3-T6→T10** — permanently NO-GO-blocked this milestone. Do not attempt.
- ⏳ **Next** — owner decision (see Action Items). No SDD task is queued.

## Critical References

1. `docs/superpowers/plans/2026-07-11-phase2-3-implementation-plan.md` — the SDD plan
   (untracked/local; loop reads it off disk). P3-T12b def + T6→T10 NO-GO banners.
2. `docs/superpowers/specs/2026-07-11-full-project-architecture.md` — §5 ink engine, §9 phases.
3. `.superpowers/sdd/p3-t12-design.md` — Codex's full T12 design + assertion-to-contract map.
4. `docs/decisions/stroke-assets.md` — the P3-T5 NO-GO decision record.
5. `.superpowers/sdd/progress.md` — running loop log (untracked/local); newest entries cover
   T12b + follow-ups + v0.1.0.

## Recent Changes (`file:line`, on `main` @ `e1552e4`)

- `src/halfblood/document_processor.py:56,89` — now **imports** `InkComposer` + `PdfRenderer`
  (they are no longer production-inert — this is the whole point of T12b).
- `src/halfblood/document_processor.py:763-770` — `render_plan` constructs the production wiring:
  `InkComposer(BuiltinRoughInkEngine(), P3T5NoGoHandwritingEngine(),
  path_postprocessor=DefaultPathPostprocessor(), algorithm_version="ink-1.0")`,
  `load_builtin_style()`, `PdfRenderer()`.
- `src/halfblood/document_processor.py:866-871` — per placed annotation: `composer.compose(...)`
  → `renderer.render_scene(page, composition.scene)`, replacing `_mark_target`/`_draw_connector`.
- `src/halfblood/document_processor.py:688` — new `_draw_note_body` (typeset body only, no connector).
- `src/halfblood/renderers/pdf.py` — `render_scene` now preflights the whole scene once, then
  commits z<0 (highlight) paths on an underlay shape (`overlay=False`) and the rest on an overlay
  shape (`overlay=True`); zero shapes/commits on preflight failure.
- `src/halfblood/models/rendering.py` — `DegradationFlag.CONNECTOR_ROUTING_FALLBACK`,
  `INK_PATH_BUDGET_EXCEEDED` (additive).
- `src/halfblood/cli.py:347` — new `--handwriting-engine typeset|procedural` (default typeset);
  procedural → early `ClickException` containing `p3_t5_no_go` before font/provider/generation.
- `src/halfblood/cli.py:221` — `_processor_for` comment: `handwriting_engine` deliberately NOT
  threaded (procedural is rejected upstream; only typeset—the default—ever reaches it).
- `src/halfblood/document_processor.py:889` (follow-up) — bare `assert scene_result.skip_reason
  is not None` replaced with `reason = scene_result.skip_reason or SkipReason.INK_GEOMETRY_INVALID`.

## Learnings

- **"Thread the param everywhere" briefs must account for EVERY faked constructor across ALL
  test files.** The follow-up brief told Codex to thread `handwriting_engine` through
  `_processor_for`; it broke 19 tests — 17 in `tests/test_cli_provider_seam.py` (its fake
  `DocumentProcessor` takes no args → `TypeError`) and 2 in `tests/test_font_selection.py`
  (exact constructor-kwargs assertions). Root cause: threading a value that can only be its
  default (procedural is CLI-rejected upstream) is pure noise that couples every construction
  assertion. Resolution: removed the dead branch but did NOT thread. The Opus gate had flagged
  the non-threading as "brief letter not followed" — but the brief letter was worse than Codex's
  original conservative omission. **When a param can only carry its default, don't thread it.**
- **Codex builds src only; controller owns tests + the tripwire enforces it.** Both T12b and its
  follow-ups had CLEAN tripwires (Codex touched zero test files). This separation is the reason
  the loop is trustworthy — the builder cannot grade its own homework.
- **`M CLAUDE.md` remains a pre-existing uncommitted rewrite** — never revert or commit it.
  Confirmed still present and untouched this session.

## Verification

| Claim | Command run this session | Result |
|---|---|---|
| HEAD `e1552e4` on `main` | `git rev-parse --short HEAD` | `e1552e4` |
| Full suite passes | `.venv/bin/pytest tests/ -q` (re-run on `main` after merge) | `1112 passed` |
| Lint clean | `.venv/bin/ruff check src tests eval` | `All checks passed!` |
| Types clean | `.venv/bin/mypy src/halfblood` | `Success: no issues found in 39 source files` |
| `v0.1.0` tags `e1552e4` | `git rev-parse --short v0.1.0^{commit}` | `e1552e4` |
| 4 feat merges since rollback tag | `git log pre-overnight-2026-07-19..main --oneline \| grep -c 'feat:'` | `4` |
| Marks render as vectors, not native annots | ran `scratchpad/e2e_observe.py` (builds plan → render_plan → opens PDF) | `0 native annotations, 5 vector draw objects, typeset body present → PASS` |
| `--handwriting-engine procedural` rejects cleanly | `.venv/bin/halfblood annotate …fixtures/potions_textbook.pdf … --handwriting-engine procedural` | exit `1`, `Error: p3_t5_no_go: …`, no output file |
| composer/renderer WIRED (no longer inert) | `grep -n "ink.composer\|renderers import PdfRenderer" src/halfblood/document_processor.py` | `56: from halfblood.ink.composer import …`, `89: from halfblood.renderers import PdfRenderer` |
| `render_plan` compose+render call sites | `grep -n "composer.compose\|renderer.render_scene" src/halfblood/document_processor.py` | `866`, `871` |
| bare assert removed | `grep -n "assert scene_result.skip_reason" src/halfblood/document_processor.py` | (no match — replaced by `or` fallback at `889`) |

## Artifacts

- Code (merged to `main`): `src/halfblood/document_processor.py`, `src/halfblood/renderers/pdf.py`,
  `src/halfblood/models/rendering.py`, `src/halfblood/cli.py`.
- Tests (merged): `tests/test_pdf_render_report.py`, `tests/test_cli.py`,
  `tests/test_pdf_vector_marks.py`, `tests/test_ink_composer.py`.
- Tag: `v0.1.0` (annotated, local).
- Loop artifacts (untracked/local): `.superpowers/sdd/p3-t12b-brief.md`,
  `p3-t12b-followups-brief.md`, their `-report.md`, `p3-t12b.testsums`,
  `p3-t12b-followups.testsums`, `codex-handoff-review-report.md`, updated `progress.md`.
- Global config (this session): added a "Delegate to Codex by default" section to
  `~/.claude/CLAUDE.md` (per owner request — reversible; delete that section to undo).
- Scratchpad: `…/scratchpad/e2e_observe.py` (render-path observation harness — not in repo).

## Action Items & Next Steps (owner decision — no SDD task queued)

1. **Decide the post-v0.1.0 direction:**
   - **Ship/iterate v0.1.0** — do an end-to-end run WITH an API key (`export ANTHROPIC_API_KEY=…`
     then `halfblood annotate …`), which this session could NOT do (no key available); only the
     render path was observed directly.
   - **Reopen P3-T5 for letterforms** — large; owner call on the font/alphabet path (option (b):
     original/tablet-captured alphabet after a blind margin-size bake-off). It would EXTEND T12b,
     not replace it.
   - **New milestone scope.**
2. **Optional cleanups (all minor, not blocking):** none outstanding — the 5 T12b review
   follow-ups were resolved this session (docstring, skip-reason fallback, dead branch removed;
   tautological test assertion removed; threading declined as YAGNI).
3. **If pushing to GitHub** (currently local-only, never pushed): the repo has no remote wired for
   these merges; confirm the owner wants it public before any `git push` / tag push.

## Other Notes

- **Never push. Local-only repo.** Merges are `--no-ff` to local `main`.
- **Pre-existing dirty tree (leave alone):** `M CLAUDE.md`, untracked
  `.claude/skills/halfblood-roadmap/`, `docs/superpowers/plans/…`. These are prior-session local
  state; `docs/decisions/**` IS committed.
- **Rollback:** the run's feat merges sit above tag `pre-overnight-2026-07-19`. Do NOT
  `git reset --hard` it (would destroy the uncommitted `CLAUDE.md`); prefer `git revert -m 1 <merge>`
  or stash `CLAUDE.md` first. To undo the release: `git tag -d v0.1.0`.
- **How Codex is used here:** the bespoke `/goal` SDD loop — controller (me) writes brief + failing
  tests, Codex (`gpt-5.6-sol` via `~/dev-harness/scripts/codex-safe.sh`) builds src only, a spawned
  Opus subagent reviews at the gate, auto-merge `--no-ff`. NOT `/codex-build` (that's the portable
  plugin for one-offs / other repos).
