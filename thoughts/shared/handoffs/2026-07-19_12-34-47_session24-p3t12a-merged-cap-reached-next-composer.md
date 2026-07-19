---
date: 2026-07-19T12:34:47-04:00
researcher: Claude (Opus 4.8) — controller session (Session 24)
git_commit: 1c6e275
branch: main
repository: half-blood-prince (local-only, never push)
topic: "P3-T12a (PDF vector renderer) MERGED; first-night cap reached (2/2); next = composer then P3-T12b integration"
tags: [p3-t12, p3-t12a, renderer, composer, cap-reached, codex, lean-loop]
status: complete
last_updated: 2026-07-19
type: handoff
---

# Session 24 (cont.) — P3-T12a merged, first-night cap reached

hbp `main` @ `1c6e275`, **1091 passed** (ruff+mypy clean). Two clean feat merges this run
(P3-T11 fonts, P3-T12a renderer); the /goal first-night cap (2) is reached.

## Merged this session
- **P3-T5 = NO-GO** (owner) → `docs/decisions/stroke-assets.md`; T6→T10 blocked; redirect to un-gated work.
- **P3-T11** (`126dea0`) — 4 license-cleared fonts ship in the wheel; no more Helvetica fallback.
- **P3-T12a** (`1c6e275`) — `src/halfblood/renderers/{__init__,pdf}.py`: `PdfRenderer` translates a
  validated InkScene → `fitz.Shape` vectors via injectable `ShapeFactory`. Pure unit, nothing calls it
  yet. Opus review APPROVE. Added `SkipReason.INK_PATH_BUDGET_EXCEEDED/INK_GEOMETRY_INVALID`.

## ⚠️ CAP REACHED — owner action
Per `/goal`: **2/2 feat merges since `pre-overnight-2026-07-19`.** Stop the loop; owner eyeballs the
chain (`git log pre-overnight-2026-07-19..main`) and loosens the cap before continuing. **This is an
ATTENDED run** — if the owner says continue, proceed (the cap's unattended-compounding rationale is
weak when watched). Both merges are green + Opus-reviewed; rollback = `git reset --hard
pre-overnight-2026-07-19` (@ `8f9c911`, before both).

## NEXT (ready to build; design done)
Full T12 design + assertion-to-contract map: **`.superpowers/sdd/p3-t12-design.md`**. Plan split note:
plan `### P3-T12`.
1. **Composer** — `src/halfblood/ink/composer.py`: `InkComposer` + injectable `RoughInkEngine`/
   `HandwritingEngine`/`PathPostprocessor` protocols; `BuiltinRoughInkEngine` (delegates to
   `ink/rough.make_*`); `P3T5NoGoHandwritingEngine.synthesize→HandwritingUnavailable(code=p3_t5_no_go)`.
   Joins semantic `Annotation` (`models/annotations.py`: mark_intent/doodle_kind/annotation_type) ↔
   `ResolvedAnnotation` (`models/rendering.py`) by id; `document_seed` passed separately (ResolvedPlan
   drops it). Role-isolated seeds via `ink/seeding.derive_seed(document_seed, ann_id, role, algo,
   "composer")`. Per-quad marks (don't union). z-order: highlight -100, marks 0, handwriting 50,
   connector 100, doodle 200. **F2 guard: only `simplify_commands` paths with NO CubicTo.** Tests:
   `tests/test_ink_composer.py` (controller-authored, with recording fake engines + recording
   PathPostprocessor). Merge as `p3-t12(composer)`.
2. **P3-T12b integration** — wire composer+renderer into `render_plan` (join Annotation↔Resolved;
   replace `_mark_target`/`_draw_connector` w/ `PdfRenderer.render_scene`; split `_draw_resolved_note`
   to body-only), `--handwriting-engine typeset|procedural` CLI on `annotate` (default `typeset`;
   `procedural`→`click.ClickException(p3_t5_no_go)`; `--font` applies to typeset only), add
   `DegradationFlag.CONNECTOR_ROUTING_FALLBACK/INK_PATH_BUDGET_EXCEEDED`, underlay/overlay commit split
   (highlight z<0 → `commit(overlay=False)`). Tests: modify `tests/test_cli.py` + integration.
   **Honest P3-T9 divergence:** marks are vector-default but the note BODY defaults to typeset (NO-GO);
   flip to procedural-default only when a future P3-T7 lands letterforms.

## Gotchas (unchanged, still live)
- **`M CLAUDE.md` + untracked `.claude/skills/…`, `docs/superpowers/plans/…` are PRE-EXISTING** — never
  revert/commit; reviews falsely block on CLAUDE.md (pre-empt in review prompts). See
  [[claude-md-preexisting-uncommitted-rewrite]]. Plan file + `.superpowers/` are untracked local state.
- Codex dispatch: `timeout 900 ~/dev-harness/scripts/codex-safe.sh --workspace <repo> --brief <f>
  --out <f> --model gpt-5.6-sol --effort high`. Read-only design/opinion: `codex exec --sandbox
  read-only … -o <f> - < <prompt>`. Controller owns `tests/`; snapshot `sha256sum tests/*.py` for the
  tripwire. Gate: `.venv/bin/pytest tests/ -q && ruff check src tests eval && mypy src/halfblood`.
- WSL transient: `git merge` once failed with "Unable to write index" (FS flake) — `git merge --abort`
  + retry worked. Not a conflict.

## Verification (this checkpoint)
| Claim | Command | Result |
|---|---|---|
| main / green | `git rev-parse --short HEAD`; `pytest -q` | `1c6e275`; **1091 passed** |
| cap | `git log pre-overnight-2026-07-19..main --oneline \| grep -c feat:` | 2 |
| renderer is a pure unit | `grep -rn "renderers" src/halfblood --include=*.py \| grep -v renderers/` | (nothing imports it yet) |
