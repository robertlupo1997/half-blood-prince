# Design: Annotation placement & the "annotated edition" architecture

**Status:** DRAFT for owner review (not yet approved; no implementation started).
**Date:** 2026-07-19. **Author:** Claude (Opus 4.8), synthesizing two Codex `gpt-5.6-sol`
read-only consults (`.superpowers/sdd/margin-discipline-design-consult-report.md` = mechanics;
`.superpowers/sdd/margin-strategy-consult-report.md` = strategy).

> **Provisional decisions made autonomously** (owner was away; owner's standing instruction
> is "go with what Codex thinks is best"). All are flagged **[CONFIRM]** for owner review:
> 1. Placement model = **gutter-first, geometry-gated** (Codex overrode the owner's tentative
>    "hybrid by intent").
> 2. Thin-margin behavior = **expand the output canvas by default**, with a **faithful /
>    preserve-size mode** as a designed-in option (`--page-mode edition|faithful`).
> 3. OCR = **architecture now, implementation later** (a separate milestone).

## 1. Problem & evidence

Handwritten margin notes are drawn over body text. Measured on the fixture demo
(`scratchpad/review_overlaps.py`): **3 of 7 notes ride over 4–6 body words each**, while
every page has ~75pt of unused true right margin. Marks (underline/strike/highlight/circle/
caret) correctly overlay their target words — that overlay is intended; only the *note bodies*
misbehave.

## 2. Root causes (confirmed by reading the code)

1. **Empty occupancy** — `render_plan` calls `layout_page_annotations(page, requests, [], …)`
   (`document_processor.py:839`); the occupancy-aware engine is told the page is blank.
2. **Target-relative "margin"** — `_margin_geometry` (`layout/engine.py:133`) starts the note
   just past the *target word's* right edge, not the page's real margin column. On a mid-line
   target that's the rest of the sentence.
3. **Measure ≠ render (latent overflow bug)** — `_LayoutMeasurer` reports one line at a fixed
   9pt regardless of wrapping (`document_processor.py:162`), while `_draw_note_body` wraps and
   uses the per-type font size (`document_processor.py:688`). The engine can approve a box the
   rendered text then overflows. **Feeding occupancy does not fix this** — it's a prerequisite.
4. **Note body bypasses the scene** — `InkComposer` emits marks/connector into the `InkScene`,
   but the note *text* is drawn separately by `DocumentProcessor` (`document_processor.py:903`).
   The renderer never receives the complete visual scene.
5. **Empty connector obstacles** — `ComposeRequest(obstacles=())` (`document_processor.py:859`),
   so connectors can cross words even once notes are clean.
6. **`inline` and `between_lines` are the same code path** (`_try_inline`) — both just try the
   slot immediately above the target; neither finds a real interline corridor.

## 3. Adopted strategy [CONFIRM]

**Geometry decides legality; intent only ranks candidates.** A note may occupy body/interline
space *only* if it measurably fits there (including rotation and ink-bleed clearance). Three
placement tiers, in order:

1. **Existing true gutters**, inferred from real content regions (not from the target word).
2. **Added reserved gutters** — when a page's native margins can't hold the annotations,
   widen the output canvas to add a real lane; original content stays at original size and
   pagination. (Rejected alternatives: PDF reflow — unreliable, breaks anchors/pagination;
   shrinking the book to fake a border — degrades the text. Both per Codex strategy §1.)
3. **Geometry-qualified interline insertions** — only for tiny corrections/carets that
   verifiably fit in an interline corridor. Not a category by intent; a rare geometric result.

**Page modes [CONFIRM]:** `edition` (default) widens when needed for clean, dense annotation;
`faithful` preserves exact input dimensions and instead shrinks-or-skips notes that don't fit
(never covering text). Same placement engine underneath; only the thin-margin fallback differs.

Intent still *ranks* (warnings/insights/inventions/doodles prefer margins; short corrections
may prefer a fitting interline slot), per the mechanics consult's routing table — but it never
forces an unsafe placement.

## 4. Target contracts (the architecture we grow toward)

- **`PageAnalysis` / `PageAnalysisProvider`** (surface-neutral) — richer than a rect list:
  normalized text + char-range mapping, word/line boxes, coarse body/column regions, figures/
  obstacles, writing direction & rotation, confidence, and source↔output transforms. Implement
  `PdfTextLayerAnalysisProvider` now by extending the proven `PdfPageIndex` extraction
  (`documents/pdf.py:48`); a future `PdfOcrAnalysisProvider` yields the *same* contract. This
  is the OCR seam — deliberately not a narrow `body_occupancy: Sequence[Rect]`.
- **Richer resolved model** — `ResolvedAnnotation` gains resolved scale, exact wrapped note-body
  bounds, chosen line breaks (or a candidate id), source/output page bounds + transform,
  selected lane, and connector route/constraints. **Invariant: the object measured by layout is
  the object rendered**, transformed only by the chosen placement.
- **Scene completeness** — the `InkScene` contains the *entire* visible annotation (note body
  included). `DocumentProcessor` stops drawing note text directly; the pure renderer draws
  everything.
- **Two-pass composition** — analyze+resolve → compose *local* measurable note candidates →
  solve page surface + placement globally → assemble final scene + route connectors → render.
  (Don't fully position the scene before layout; connector routes depend on placement.)

## 5. Phased roadmap (decomposition)

Each phase is independently valuable and shippable; each becomes its own spec → plan → build.

- **Phase 1 — Foundations + within-page gutter discipline (model-agnostic, highest value).**
  Fixes the demo, needed regardless of later phases.
  - Fix measure≡render: measurement uses the same wrapping + per-type font size; carry
    `note_scale` on `ResolvedAnnotation`; render at `font_size * note_scale`.
  - Extract `layout/occupancy.py` (surface-neutral `PageOccupancy`/`TextColumn` + column/margin
    inference) and a native provider; construct padded per-line occupancy in `render_plan`
    (replacing `[]`).
  - True-margin placement in the engine: derive body columns, place notes hugging the
    body-facing edge of the real outer margin, centered vertically on the target; **fail
    closed → skip** rather than target-relative fallback. Feed connector obstacles.
  - Acceptance: **zero note/body-word intersections on the 7-note demo**; headers/footers/page
    numbers/short lines/2-column gutters handled; narrow margins shrink-or-skip, never overlap.
- **Phase 2 — Expanded-canvas "edition" + `--page-mode`.** Preflight the document, choose stable
  doc-wide lanes, widen the output canvas when native margins are insufficient; preserve
  crop/media boxes, rotation, links, bookmarks, forms, existing annotations (preservation
  fixtures required); degrade unsupported interactive PDFs to a trim-preserving mode with an
  explicit report. Add `faithful` mode.
- **Phase 3 — Global page solver.** Replace top-level greedy with a bounded deterministic solver
  (beam search / small optimizer; ~5–8 annotations/page) minimizing omissions, unreadable
  scaling, connector length/crossings, target displacement, side switches, uneven lanes. Keep
  the engine's collision/priority/degradation/determinism primitives.
- **Phase 4 — Scene completeness + pipeline extraction.** Move note-body into the `InkScene`;
  introduce `rendering/pipeline.py`; `DocumentProcessor.render_plan` becomes a compatibility
  facade. Split `document_processor.py` along the new contracts (contracts first, not a cosmetic
  breakup).
- **Phase 5 — OCR milestone (later).** `PdfOcrAnalysisProvider` for image-only PDFs via the same
  `PageAnalysis` contract; low-confidence text extraction fails safe (skips), never guesses.

Recommended first build: **Phase 1** — it stops the bleeding (notes off the words) and lays the
contracts the rest depends on, without committing to canvas expansion before you've confirmed
the page-size call.

## 6. Open decisions for the owner
- **[CONFIRM] Page-size default** — `edition` (widen) vs `faithful` (preserve size) as the
  default; or build both (recommended: both, default `edition`).
- **[CONFIRM] Appetite / sequencing** — Phase 1 now then reassess, vs commit to the Phase 1–4
  arc up front.
- **Mark-survives-unplaceable-note** — today a skipped note also drops its mark. If a mark
  should still appear when its note can't be placed, the placed/skipped contract needs a
  separate mark-only disposition (Codex mechanics §7). Treat as a Phase-1 contract decision.

## 7. Principal risks
- Expanded pages: crop/media box, rotation, links, bookmarks, forms, annotation preservation —
  real work; needs preservation fixtures.
- Column inference errors (headers/footers as body, gutter-as-margin, rotation/crop coordinate
  disagreement). Mitigation: occupancy collision stays the final safety invariant — even a
  mis-inferred lane can't place a note over a word.
- Tables/vector diagrams/scanned regions aren't captured by word geometry (Phase 5 / obstacle
  extraction).
- Conservatism reduces annotation density in `faithful` mode — that's the honest cost of never
  covering text at fixed page size.
