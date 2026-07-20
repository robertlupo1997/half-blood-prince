---
date: 2026-07-20T00:46:16-04:00
researcher: Claude (Opus 4.8)
git_commit: 8c777f33ac126c9c672d60a0d1ddc81d9e7bdb1e
branch: main
repository: half-blood-prince
topic: "MP1b cleanup MERGED + MP1d mark-survives-unplaceable-note MERGED; finding 5 re-scoped as MP1c"
tags: [annotation-placement, layout, occupancy, mark-survives, render-report, ink-composer, codex, controller-discipline]
status: complete
last_updated: 2026-07-20
type: handoff
---

# Handoff: Session 27 — MP1b cleanup + mark-survives-unplaceable-note (both merged)

> **Both tasks the owner asked for are done and on local `main`.** MP1b cleanup
> (dead-code + config const + header/footer filter) merged `6441973`; **mark-survives-
> unplaceable-note** (MP1d) merged `8c777f3`. `main` is **1136 green**, ruff + mypy clean,
> `v0.1.0` tag intact. Two independent Opus reviews returned **GO**. Finding 5 turned out to
> be a real engine-contract change, not a quick tweak — **re-scoped as MP1c and deferred**
> (evidence below). **NEW BOUNDARY the next session must know: MP1d is PDF-only — the EPUB
> render path is separate and unaddressed.**

## Task(s)
- ✅ **MP1b cleanup (findings 1–4)** — MERGED `6441973` (feat `78c4159`). Removed dead
  `inspect.signature` branch + `_PdfBodyOccupancy` side-channel; hoisted the `8.0` page-edge
  pad to `LayoutConfig.page_edge_pad`; `_body_candidates` now excludes a text block from
  column inference only when the WHOLE block sits in the top/bottom 8% band (multi-line
  running headers/footers no longer inflate columns).
- ✅ **MP1d — mark-survives-unplaceable-note** — MERGED `8c777f3` (feat `748b95e`). A target
  mark now renders even when its margin note is skipped as unplaceable, recorded in a new
  additive `RenderReport.marks_only`.
- 🚧 **MP1c — fail-closed when columns can't be inferred (was "finding 5")** — DEFERRED,
  scoped. See Learnings; this is the next Phase-1 task.
- ⏳ **Phased roadmap** (design §5): expanded-canvas `--page-mode` (OPTIONAL), global solver,
  scene-owns-note-body, EPUB track (incl. EPUB mark-survival), OCR milestone.
- ⏳ **Product validation still owed** — no real `halfblood annotate` LLM run yet (no key).
  Use OpenRouter (`--provider openrouter --model anthropic/claude-3.7-sonnet`).

## Critical References
1. `docs/superpowers/specs/2026-07-19-annotation-placement-architecture-design.md` — design of
   record. §6 decided **mark-survives-unplaceable-note = YES** (this session implemented it).
   §5 Phase-1 says "fail closed → skip rather than target-relative fallback" (this is MP1c).
2. `.superpowers/sdd/progress.md` — running ledger; newest section covers MP1b/MP1c/MP1d.
3. `.superpowers/sdd/{mp1b-cleanup-brief.md, mp1d-mark-survives-brief.md}` — the Codex briefs
   used this session (untracked loop artifacts).

## Recent changes (`file:line`, on `main` @ `8c777f3`)
- `src/halfblood/models/rendering.py:188` — NEW `RenderReport.marks_only: tuple[str, ...] = ()`;
  the `@model_validator` (`rendering.py:205-207`) enforces uniqueness + `marks_only ⊆ skipped`.
  `report_version` stays `"1.0"` (additive).
- `src/halfblood/ink/composer.py:535` — NEW keyword-only `compose(..., mark_only=False)`;
  `composer.py:582` guards CONNECTOR **and** DOODLE roles behind `if not mark_only:` (the DOODLE
  role is NOT note_box-gated — this is why the param is required).
- `src/halfblood/document_processor.py:974-1016` — mark-only render path in `render_plan`: for
  each `layout_result.skipped` note with a usable anchor + real `mark_intent` (gated via
  `_MARK_ROLES`, imported `document_processor.py:58`), compose `mark_only=True`, render, and
  record the id in `marks_only` when `scene_result.rendered`. `req_by_id` built per page at
  `document_processor.py:913`.
- `src/halfblood/document_processor.py:889-899` — MP1b F1: `render_plan` now unconditionally
  calls `layout_page_annotations(..., body_columns=)` (no `inspect`, no shim).
- `src/halfblood/layout/engine.py:63` — `LayoutConfig.page_edge_pad: float = 8.0`; used at
  `engine.py:307,309`.
- `src/halfblood/documents/pdf_occupancy.py:99` — `_body_candidates` block-level furniture filter.
- Tests: `tests/test_occupancy_layout.py` (+2 header/footer white-box), `tests/test_render_report.py`
  (+3 marks_only model), `tests/test_pdf_render_report.py` (+2 integration),
  `tests/test_ink_composer.py:324` (+1 airtight doodle-suppression), `tests/test_note_measure_render.py:103`
  (spy forwards `body_columns`).

## Learnings
- **Finding 5 is MP1c, not a cleanup.** `run_layout` with `body_columns=()` sets
  `margin_strips=None` and falls to the **target-relative fallback** (`engine.py:355-359`) — the
  exact behavior design §5 says to remove. But that fallback is load-bearing: **31 `run_layout`
  calls in `tests/test_layout_engine.py` pass NO `body_columns`**. Making the engine fail-closed
  means converting all 31 tests + pinning the contract. That is a real task (MP1c), correctly
  refused as scope creep on a "quick cleanup."
- **The doodle role is the mark-survives trap.** In `composer.compose`, CONNECTOR is note_box-
  gated but **DOODLE is not** — a skipped DOODLE_NOTE composed with `note_box=None` would emit a
  doodle against a missing box. The fix is an explicit `mark_only=True` that drops both roles;
  relying on `note_box=None` alone is insufficient. (Advisor caught this before the brief.)
- **A brief that forbids test edits can force a worse production hack.** MP1b-F1's brief said
  "don't touch tests"; the correct fix required updating a spy in `test_note_measure_render.py`
  to forward `body_columns`. Codex, obeying the brief, instead added a brittle stringly-typed
  `try/except TypeError` matching the CPython error wording. The controller replaced it with the
  spy fix. Lesson: when the clean fix touches a test double, say so in the brief.
- **Reviewer caught a vacuous test.** MP1d's integration doodle assertion used a CORRECTION
  annotation (never doodles) → the `assert DOODLE not in roles` passed trivially. Added a real
  composer-level test with a DOODLE_NOTE that asserts the doodle IS requested normally but NOT
  under `mark_only` (`test_ink_composer.py:324`).
- **Foreground Codex did not stall** (Session 26's driver-subagent stalled twice). Driving Codex
  directly via `codex-safe.sh` in the foreground, then gating/reviewing/merging as the controller,
  was clean. Reviews were `Agent(general-purpose, model:"opus")` (tool access).
- **`M CLAUDE.md` is STILL a pre-existing uncommitted rewrite — never staged all session.**

## Boundaries the gate could NOT catch (state these — verified below)
- **MP1d is PDF-ONLY.** `EpubProcessor` has its OWN `render_plan` (`epub_processor.py:454`)
  building its own `RenderReport` (`epub_processor.py:580`). It never touches the PDF mark-only
  path — EPUB `marks_only` is always empty and a skipped EPUB note still loses its mark. EPUB
  mark-survival is a **future task** (fits the design's EPUB parallel track).
- **The CLI labels mark-only notes "skipped."** `cli.py:463` prints
  `Rendered {rendered_count} / Skipped {skipped_count}`; a mark-only note is in `skipped`, so it
  reads as fully skipped even though its mark rendered. `marks_only` is not surfaced. Non-blocking
  reporting gap; also `RenderReport.attempted_count` (= rendered + skipped) counts mark-only notes.

## Verification
| Claim | Command run this session | Result |
|---|---|---|
| HEAD `8c777f3` on `main` | `git rev-parse --short HEAD` | `8c777f3` |
| Full suite passes on main | `.venv/bin/pytest tests/ -q` | `1136 passed` |
| Lint clean | `.venv/bin/ruff check src tests eval` | `All checks passed!` |
| Types clean | `.venv/bin/mypy src/halfblood` | `Success: no issues found in 41 source files` |
| MP1b + MP1d merged | `git log --oneline -3` | merges `6441973`, `8c777f3` present |
| `import inspect` gone | `grep -c inspect src/halfblood/document_processor.py` | `0` |
| `_PdfBodyOccupancy` gone | `grep -rc _PdfBodyOccupancy src/halfblood/` | `0` (no matches) |
| header/footer white-box tests | `pytest -k "running_header or dipping_into_header"` | `2 passed` (were 1 failed pre-build) |
| MP1d tests pass | `pytest -k "marks_only or mark_renders or unplaceable"` | `5 passed` (were 3 failed pre-build) |
| doodle-suppression is non-vacuous | `pytest -k mark_only_suppresses` | `1 passed` |
| zero-overlap placement contract intact | `pytest tests/test_occupancy_layout.py -k "overlap or demo or two_column or margin"` | `7 passed` |
| MP1d is PDF-only | `grep -n "render_plan\|RenderReport" src/halfblood/epub_processor.py` | EPUB has its own `render_plan` @ `:454`, own `RenderReport` @ `:580` |
| CLI mislabels mark-only | `grep -n "Skipped" src/halfblood/cli.py` | `463: ... / Skipped {report.skipped_count}` |
| v0.1.0 tag intact | `git tag \| grep v0.1.0` | `v0.1.0` (local, unpushed) |
| `M CLAUDE.md` never staged | `git status --short` | ` M CLAUDE.md` (unstaged, untouched) |

## Artifacts
- Code (merged): `src/halfblood/models/rendering.py`, `src/halfblood/ink/composer.py`,
  `src/halfblood/document_processor.py`, `src/halfblood/layout/engine.py`,
  `src/halfblood/documents/pdf_occupancy.py`.
- Tests: `tests/test_render_report.py`, `tests/test_pdf_render_report.py`,
  `tests/test_ink_composer.py`, `tests/test_occupancy_layout.py`, `tests/test_note_measure_render.py`.
- Loop artifacts (untracked/local): `.superpowers/sdd/{mp1b-cleanup-brief.md,
  mp1b-cleanup-codex-out.md, mp1d-mark-survives-brief.md, mp1d-mark-survives-codex-out.md, progress.md}`.
- Rollback tag (local): `pre-session27-cleanup` @ `1d298f4`.

## Action Items & Next Steps
1. **MP1c — fail-closed when columns can't be inferred.** Remove the target-relative fallback
   (`engine.py:355-359`); when `body_columns` is empty, skip (UNPLACEABLE) rather than place
   target-relative. Convert the 31 `run_layout` tests in `tests/test_layout_engine.py` to pass
   `body_columns` where they expect placement; add a fail-closed test that exercises `run_layout`
   (not the dataclass ctor). This is the last Phase-1 item.
2. **EPUB mark-survival** (design EPUB track) — extend the mark-only disposition to
   `EpubProcessor.render_plan` (`epub_processor.py:454`) so `marks_only` is meaningful for EPUB.
3. **Surface `marks_only` in the CLI** (`cli.py:463`) and/or clarify `attempted_count` so a
   mark-only note isn't reported as fully "skipped."
4. **Then** the broader roadmap (design §5): expanded-canvas `--page-mode` (OPTIONAL), global
   solver, scene-owns-note-body, OCR.
5. **Product validation** — a real end-to-end `halfblood annotate` run via OpenRouter + visual check.

## Other Notes
- **Never push. Local-only.** Merges are `--no-ff` to local `main`. Rollback of this session's
  feats: `git revert -m 1 8c777f3` and `git revert -m 1 6441973` (NOT `reset --hard` — would
  kill the uncommitted `CLAUDE.md`).
- **Pre-existing dirty tree (leave alone):** `M CLAUDE.md`, untracked
  `.claude/skills/halfblood-roadmap/`, `docs/superpowers/plans/2026-07-11-...`.
- **Codex standard:** SDD build → `~/dev-harness/scripts/codex-safe.sh --workspace <repo>
  --brief F --out F --model gpt-5.6-sol --effort high` (foreground). Sandbox + delete-guard
  confirmed working; the guard blocks file deletes/renames, not line-level edits.
