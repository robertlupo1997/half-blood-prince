# EPUB Note-Layout Track — Design of Record (2026-07-20)

**Status:** ADOPTED (controller decision, Session 28; based on Codex advisory
`.superpowers/sdd/epub-track-design-consult{,-out}.md`, read-only, gpt-5.6-sol high).
**Supersedes:** the float-first presentation implied by the current `_ANNOTATION_CSS`.
**Consistent with:** the 2026-07-19 placement architecture design (EPUB = first-class parallel
track; `EPUB_NO_TARGET_GEOMETRY` always set) and the 2026-07-20 ledger N/A decisions (EPUB
fail-closed N/A; EPUB mark-survival N/A — presentation degradation is never a skip).

## Decision

Adopt the **progressive semantic hybrid** for EPUB notes:

1. One semantic representation: a safe target-adjacent **noteref** + a deterministic,
   bidirectionally linked **`<aside epub:type="footnote">`** placed after the owning block
   (EPUB 3). EPUB 2 gets an ordinary linked `<div class="hbp-note">` — never silently upgrade
   the package version, never emit `epub:type` into EPUB 2.
2. **Block-first CSS**: the unconditional base presentation is a styled handwritten block after
   the source block — visible on every engine, no `@supports` dependency. Readers with popup
   semantics may present the aside as a popup (their choice; aside stays styled).
3. **Float-right is an enhancement only**, gated by a conservative width media query + an
   emitted `hbp-note-cluster-floatable` class — never the base contract.
4. **Clusters**: notes group per owning block in one `hbp-note-cluster`, appended in plan/source
   order. Dense clusters get a forced block fallback via an emitted class — a presentation
   degradation (optional nonfatal global flag `EPUB_DENSE_NOTES_BLOCK_FALLBACK`), NEVER a skip
   or an unplaceable classification.

### Rejected alternatives (advisory §OPTIONS-RANKED)
- Absolute-position margin boxes — reject (compat 1/5, flow safety 1/5, not reflowable-safe).
- Popup-footnotes-only — weak marginalia aesthetic as the primary contract.
- Status quo (inline-block + `@supports` float) — a 9em float consumes the content measure and
  wraps body text around it (not a true margin box); `@supports`-gated means engines lacking
  `@supports` but supporting float get the worst presentation; poor base contract.

## Known live defect (fix in NL1)

Repeated `anchor.insert_after(note)` for multiple notes on the SAME block reverses their order —
later plan entries become the first sibling. Existing tests assert counts, not same-block order.

## Phases (each: failing tests first, offline DOM/CSS gate, no real-reader dependency)

- **EPUB-NL1 — semantic note DOM + stable ordering.** Shared block-note/cluster insertion
  helper used by both render paths; deterministic unique note/ref IDs; bidirectional links; no
  nested anchors (targets already inside `<a>` need an explicit safe insertion boundary);
  EPUB 3 `epub:type` + namespace vs EPUB 2 linked-div branching; plan-order preserved for
  same-block notes (fixes the live defect); `MarkIntent.NONE` + cross-node covered. No CSS
  changes yet.
- **EPUB-NL2 — block-first CSS + progressive float.** Base `display:block`; relative-unit
  spacing; `overflow-wrap` protection; float only floatable clusters under a width media query;
  drop `@supports` reliance; pin serialized CSS with artifact tests.
- **EPUB-NL3 — density + degradation contract.** 1/3/8-notes-per-block fixtures, long
  unbreakable tokens, pre-existing source floats; deterministic dense threshold (documented as
  conservative heuristic, presentation-only); optional `EPUB_DENSE_NOTES_BLOCK_FALLBACK` flag;
  rendered/skipped/marks_only semantics unchanged.
- **EPUB-NL4 — compat hardening.** Caret mark becomes real DOM text or an `aria-hidden` glyph
  span (`::after` decorative only — Kindle KF8 can drop generated content entirely); EPUB 2/3
  fixture artifacts for a future reader lab. Real-reader results stay advisory, never merge
  gates.

## Test boundary (state it)
Offline gates can verify DOM order/IDs/links, EPUB 2/3 validity, cluster classification, CSS
contract, XHTML/text/spine preservation. They CANNOT verify popup activation, store conversion
rewriting, pagination/fragmentation, user-style overrides, or painted overlap — reader-lab
checks remain supplementary.

## Risks accepted
Apple may hide asides in favor of popup UI (aesthetic loss there); Kindle/Kobo ingestion may
rewrite markup; themes override styling; rotated-ink paint overlap is not modeled by the CSS
flow box. All degrade to readable text; none block.
