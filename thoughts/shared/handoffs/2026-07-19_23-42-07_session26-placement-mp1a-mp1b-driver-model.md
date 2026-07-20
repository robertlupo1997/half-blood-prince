---
date: 2026-07-19T23:42:07-04:00
researcher: Claude (Opus 4.8)
git_commit: 629d659bc96b496c139d2815962b9feeda15ffc5
branch: main
repository: half-blood-prince
topic: "Annotation placement rework (MP1a+MP1b): notes now sit in true margins, 0 body overlap; new delegated-driver workflow; Codex-usage audit"
tags: [annotation-placement, layout, occupancy, margins, measure-render, codex, driver-subagents, audit, epub]
status: complete
last_updated: 2026-07-19
type: handoff
---

# Handoff: Session 26 — placement rework (notes off the words), driver-subagent workflow, Codex audit

> **The problem Trey flagged is fixed and visible.** Handwritten margin NOTES no longer ride over
> body text — they now sit in the page's TRUE outer margin (0 note/body-word overlaps on the 7-note
> demo, was 3 notes over 4–6 words). Two placement tasks merged (MP1a measure≡render, MP1b margin
> discipline). This session also changed HOW WE WORK: the orchestrator delegates each task's full
> Codex-build loop to a driver subagent (context isolation), and we audited/standardized Codex usage.

## Task(s)
- ✅ **MP1a — measure≡render** (merged `e33b54d`). The layout measurer now predicts the wrapped
  height + per-type font the renderer draws; `note_scale` carried on `ResolvedAnnotation`. Fixes
  silent note overflow/truncation.
- ✅ **MP1b — margin discipline** (merged `017a650`). Occupancy model + true-margin gutter placement;
  notes never over body text. **Verified: 0 overlaps on the demo.** Opus review APPROVE, no blockers.
- ✅ **Codex usage audit + `/goal` delete-guard fix** (merged `629d659`).
- ✅ **New workflow adopted:** delegated driver subagents own each task's Codex loop.
- ⏳ **Next (Phase-1 remainder):** clean up MP1b's dead code (review findings 1+2), then
  **mark-survives-unplaceable-note** (MP1d). Then the broader phased roadmap (expanded-canvas is an
  OPTIONAL later mode; EPUB is a first-class parallel track; OCR is a later milestone).
- ⛔ Not started: expanded-canvas `--page-mode`, global page solver, scene-owns-note-body, OCR.

## Critical References
1. `docs/superpowers/specs/2026-07-19-annotation-placement-architecture-design.md` — **the design of
   record** (decisions RESOLVED: gutter-first geometry-gated placement; `faithful`/preserve-size
   default with expanded-canvas as an optional lower-priority mode; EPUB first-class; OCR later).
2. `.superpowers/sdd/margin-discipline-design-consult-report.md` (Codex mechanics) +
   `.superpowers/sdd/margin-strategy-consult-report.md` (Codex strategy — overrode "hybrid by intent").
3. `docs/superpowers/specs/2026-07-19-codex-usage-audit.md` — Codex usage audit + the standard.
4. `.superpowers/sdd/progress.md` — running log; newest entries cover MP1a/MP1b/audit + the 5
   MP1b follow-ups.
5. Memories (loaded every session): `delegate-driving-to-subagent`, `codex-standard-invocations`,
   `consult-codex-when-uncertain`, and the reinforced `prefers-autonomous-execution`.

## Recent Changes (`file:line`, on `main` @ `629d659`)
- `src/halfblood/layout/occupancy.py` — NEW: fitz-free `PageOccupancy` / `TextColumn` + column &
  outer-margin inference.
- `src/halfblood/documents/pdf_occupancy.py` — NEW: `PdfTextLayerOccupancyProvider` (rotation/
  header/footer/page-number aware) → `PageOccupancy` from `page.get_text("words")`.
- `src/halfblood/layout/engine.py` — notes placed in the true outer margin (from `body_columns`),
  hugging the body-facing edge, centered on the target; occupancy is the final safety invariant.
- `src/halfblood/document_processor.py` — `render_plan` builds occupancy and feeds real body rects +
  connector obstacles (replaced `[]`/`()`); measurer uses `max(_FONT_SIZE_BY_TYPE)`; `_draw_note_body`
  renders at `font*note_scale`.
- `src/halfblood/models/rendering.py` — `ResolvedAnnotation.note_scale: float = Field(1.0, gt=0)`.
- `tests/` — NEW `test_note_measure_render.py` (3) + `test_occupancy_layout.py` (13).
- `.claude/skills/goal/SKILL.md` — dispatch via `codex-safe.sh` (delete guard) not raw `codex exec`.

## Learnings
- **Codex overrode the owner's "hybrid by intent"** → gutter-first, geometry-gated (geometry decides
  legality, intent only ranks). For thin margins Codex's *ideal* is to widen the output canvas, but
  research (EPUB dominates real books & is reflowable; PDFs are mostly reference/technical where layout
  matters) → we chose **`faithful` preserve-size as default**, expanded-canvas OPTIONAL. Owner
  delegated: "research & decide, don't ask me."
- **Delegated-driver workflow:** orchestrator specs → driver subagent writes brief + controller
  failing tests, dispatches Codex via `codex-safe.sh`, gates, spawns Opus review, merges → orchestrator
  VERIFIES vs the tree. Keeps orchestrator context lean. See memory `delegate-driving-to-subagent`.
- **Driver stall bug:** the MP1b driver dispatched Codex in the BACKGROUND, ended its turn (idle), and
  never auto-resumed when Codex finished. Orchestrator had to nudge, then take over the finish. **Fix
  for future drivers: run Codex in the FOREGROUND (block) so the driver doesn't idle mid-loop**; the
  orchestrator should also verify tree state on any driver idle_notification, not trust it as "done."
- **Two Opus reviewers, one broken:** the driver spawned a review subagent that had NO tools (advisor
  only) and couldn't review; the orchestrator's own `Agent(general-purpose, model:opus)` review worked.
  Spawn reviewers as `general-purpose` so they get file/shell access.
- **`M CLAUDE.md` is STILL a pre-existing uncommitted rewrite — never revert/commit it.** Verified
  present all session.

## Verification
| Claim | Command run this session | Result |
|---|---|---|
| HEAD `629d659` on `main` | `git rev-parse --short HEAD` | `629d659` |
| Full suite passes | `.venv/bin/pytest tests/ -q` (re-run on main after merge) | `1128 passed` |
| Lint clean | `.venv/bin/ruff check src tests eval` | `All checks passed!` |
| Types clean | `.venv/bin/mypy src/halfblood` | `Success: no issues found in 41 source files` |
| MP1a + MP1b merged | `git log --oneline …` | `e33b54d` (mp1a), `017a650` (mp1b) present |
| **Notes off the words** | ran `scratchpad/review_overlaps.py` on the fixture | **0 body words under all 7 notes** (was 3 notes over 4–6) |
| zero-overlap contract test | `.venv/bin/pytest tests/test_occupancy_layout.py -k "overlap or demo"` | `3 passed` |
| occupancy modules exist | `ls src/halfblood/layout/occupancy.py src/halfblood/documents/pdf_occupancy.py` | both present |
| demo renders clean | ran `scratchpad/render_demo.py` | `8 annotations, 8 rendered, 0 skipped` → `C:\Users\Trey\Downloads\hbp-render-demo.pdf` |
| v0.1.0 tag intact | `git tag \| grep v0.1.0` | `v0.1.0` (local, unpushed) |

## Artifacts
- Code (merged): `src/halfblood/layout/{occupancy.py,engine.py}`, `src/halfblood/documents/pdf_occupancy.py`,
  `src/halfblood/document_processor.py`, `src/halfblood/models/rendering.py`.
- Tests: `tests/test_note_measure_render.py`, `tests/test_occupancy_layout.py`.
- Docs: design `docs/superpowers/specs/2026-07-19-annotation-placement-architecture-design.md`; audit
  `…/2026-07-19-codex-usage-audit.md`.
- Loop artifacts (untracked/local): `.superpowers/sdd/{mp1a-*,mp1b-*,margin-*consult*,progress.md}`.
- Scratchpad (not in repo): `…/scratchpad/{review_overlaps.py,render_demo.py,e2e_observe.py}`.
- Memories: `delegate-driving-to-subagent`, `codex-standard-invocations`, `consult-codex-when-uncertain`.

## Action Items & Next Steps (owner delegated: research & decide, don't ask)
1. **MP1b cleanup (do first — quick):** review findings 1+2 — remove the dead
   `inspect.signature(layout_page_annotations)` branch + `import inspect`
   (`document_processor.py:900–919`) and the `_PdfBodyOccupancy(list)` subclass side-channel
   (`document_processor.py:118–130`); make `body_columns` a real field on `PageOccupancy` (also
   sharpens the OCR seam). Then findings 3 (hardcode `8.0` pad → `LayoutConfig`), 4 (multi-line
   header/footer exclusion), 5 (make the fail-closed test exercise `run_layout`, not a constructor).
2. **MP1d — mark-survives-unplaceable-note:** a target mark (underline/strike/…) should still render
   even when its NOTE is skipped as unplaceable (design §6 decided YES). Needs a mark-only disposition
   separate from the note's placed/skipped status in `render_plan`.
3. **Then** the phased roadmap (design §5): expanded-canvas `--page-mode` (OPTIONAL), global solver,
   scene-owns-note-body, EPUB track, OCR milestone.
4. **Use the delegated-driver workflow** for each — but dispatch Codex FOREGROUND (see Learnings) and
   verify every driver claim against the tree.
5. **Product validation still owed:** no real `halfblood annotate` LLM run has happened (no Anthropic
   key). Use **OpenRouter** (`--provider openrouter --model anthropic/claude-3.7-sonnet`,
   `OPENROUTER_API_KEY`) for a real end-to-end + visual check.

## Other Notes
- **Never push. Local-only.** Merges are `--no-ff` to local `main`. Rollback of the run's feats:
  `git revert -m 1 <merge>` (NOT `reset --hard` — kills the uncommitted `CLAUDE.md`).
- **Pre-existing dirty tree (leave alone):** `M CLAUDE.md`, untracked `.claude/skills/halfblood-roadmap/`,
  `docs/superpowers/plans/…`.
- **Codex standard (audited):** SDD loop/drivers → `codex-safe.sh` (`gpt-5.6-sol`, high); ad-hoc →
  `/codex:rescue`; review → `/codex:review`; WSL2 throwaway → `/codex-build`. Sandbox + `--net` web
  access confirmed working. One un-applied fix (owner OK needed, outside repo): add
  `--skip-git-repo-check` to `~/dev-harness/scripts/codex-safe.sh`.
