---
date: 2026-07-19T16:23:47-04:00
researcher: Claude (Opus 4.8) — controller session (Session 24)
git_commit: 1dc540a
branch: main
repository: half-blood-prince (local-only, never push)
topic: "Renderer + composer merged (pure units); NEXT = P3-T12b integration (wire into render_plan + CLI — the risky one)"
tags: [p3-t12, p3-t12b, integration, renderer, composer, cli, codex, lean-loop]
status: complete
last_updated: 2026-07-19
type: handoff
---

# Session 24 (cont.) — renderer + composer merged; next is P3-T12b integration

hbp `main` @ `1dc540a`, **1102 passed** (ruff+mypy clean). Four clean feat merges this session
(P3-T11, P3-T12a renderer, P3-T12 composer — the last two are pure units nothing calls yet).

## Merged this session
- **P3-T5 = NO-GO** (owner) → `docs/decisions/stroke-assets.md`; T6→T10 blocked.
- **P3-T11** (`126dea0`) — 4 license-cleared fonts ship in the wheel (no more Helvetica fallback).
- **P3-T12a** (`1c6e275`) — `renderers/pdf.py` `PdfRenderer`: InkScene→`fitz.Shape` vectors.
- **P3-T12 composer** (`1dc540a`) — `ink/composer.py` `InkComposer`: builds one InkScene per resolved
  annotation. Both Opus-reviewed APPROVE.

## NEXT — P3-T12b integration (the RISKY one; touches production render behavior)
Design: `.superpowers/sdd/p3-t12-design.md` (§ `document_processor.py` / CLI integration). Wire the two
merged units into the live path so vector marks actually reach the PDF:
1. Add `handwriting_engine: Literal["typeset","procedural"] = "typeset"` to `DocumentProcessor`.
2. In `render_plan`: after resolve/layout, **join each `ResolvedAnnotation` to its semantic
   `Annotation` by id** (render_plan takes a v2 `AnnotationPlan` → its `units[].annotations` are the
   semantic `Annotation`s carrying mark_intent/doodle_kind/content; `document_seed` from the plan).
   Build a `ComposeRequest` per placed annotation, `InkComposer.compose(...)`, then
   `PdfRenderer.render_scene(page, scene)` — **replacing** the `_mark_target` + `_draw_connector`
   calls for marks/connectors/doodles. Split `_draw_resolved_note` to draw ONLY the note body text
   (legacy typeset); it must no longer draw a connector.
3. `--handwriting-engine typeset|procedural` on the `annotate` CLI (`cli.py`, between `--font` and
   `--force`): default `typeset`; selecting `procedural` → reject up front with
   `click.ClickException` surfacing `HandwritingUnavailable(code="p3_t5_no_go")`. `--font` applies to
   typeset only. Do NOT add `--allow-typeset-fallback`.
4. Add `DegradationFlag.CONNECTOR_ROUTING_FALLBACK` + `DegradationFlag.INK_PATH_BUDGET_EXCEEDED`;
   fold composer/renderer degradations + skips into the `RenderReport`.
5. Underlay/overlay commit split now matters: highlight (z<0) → `commit(overlay=False)`, others
   overlay=True (T12a deliberately deferred this to here — the renderer currently commits one shape
   overlay=True; extend it OR drive two shapes from the integration).
6. Retain atomic save (`tempfile` + `os.replace`); add final PDF output hash.
**Honest P3-T9 divergence (NO-GO):** marks are vector-default but the note BODY defaults to typeset;
flip to procedural-default only when a future P3-T7 lands letterforms.
Tests: modify `tests/test_cli.py` (add `--handwriting-engine`), add an integration test asserting the
v2 render path draws vector marks (no `add_*_annot` native marks) while the body still `insert_text`s,
and that `procedural` raises. Controller owns tests. Merge as `p3-t12b`.
**RISK:** this is the first T12 task that changes EXISTING render behavior — author integration tests
carefully; verify the v2 `render_plan` path end-to-end. Consider a fresh session for it.

## Deferred non-blocking follow-ups (from reviews)
- CARET always degrades (ResolvedAnnotation has no interline gap) — T12b could skip adding the CARET
  role when geometry is unavailable.
- No direct `BuiltinRoughInkEngine` unit test (reviewer live-verified it) — T12b exercises it e2e.
- Dead `detail` assignment `composer.py:716`; redundant OFL per-font copyright header (P3-T11 N1).

## Gotchas (still live)
- **`M CLAUDE.md` + untracked `.claude/skills/…`, `docs/superpowers/plans/…` are PRE-EXISTING** — never
  revert/commit; reviews falsely block on CLAUDE.md (pre-empt in review prompts). [[claude-md-preexisting-uncommitted-rewrite]]
- Codex build: `timeout 900 ~/dev-harness/scripts/codex-safe.sh --workspace <repo> --brief <f> --out
  <f> --model gpt-5.6-sol --effort high`. Read-only design: `codex exec --sandbox read-only … -o <f> -
  < <prompt>`. Controller owns `tests/`; snapshot `sha256sum tests/*.py` per task for the tripwire.
- WSL transient: `git merge` once failed "Unable to write index" — `git merge --abort` + retry worked.
- Rollback for this run's 3 feat merges: `git reset --hard pre-overnight-2026-07-19` (@ `8f9c911`).

## Verification (this checkpoint)
| Claim | Command | Result |
|---|---|---|
| main / green | `git rev-parse --short HEAD`; `pytest -q` | `1dc540a`; **1102 passed** |
| composer+renderer inert | `grep -rn "renderers\|composer" src/halfblood --include=*.py \| grep -vE "ink/composer\|renderers/"` | (nothing imports them yet) |
| feat merges since tag | `git log pre-overnight-2026-07-19..main --oneline \| grep -c feat:` | 3 |
