> Worker report, preserved verbatim below. Claims here are worker-reported, not final release validation. Concurrent edits can make reported test counts stale. The final root evidence packet supersedes them.

# Half-Blood Prince — Placement Contract Falsification (04a4489)

**Author:** placement-check-free (cc4381c022ea)  
**Date:** post-04a4489 interrupted run  
**Branch:** release/evidence-placement-contract  
**Scope:** `halfblood.placement`, `halfblood.models.placement`, EPUB/PDF public seam.  
**Test file:** `tests/test_strict_placement.py` (73 tests, all green).

## TL;DR

- **Observed**: the parent commit on this branch (`04a4489 wip(astra): checkpoint …`) left 8
  failing tests, 1938 passing. The strict placement contract is mid-flight; the suite
  went from `1883 passed / 0 failed` at `0739f28` to `1938 passed / 8 failed` here.
- **Observed**: parent has since applied strengthening to `PlacementResult` (schema version
  pinned to `1.0`, `PlacementReason = Literal[...]` finite reason set, refusal cannot carry
  a usable anchor, resolved requires raw evidence + digest + renderer-appropriate geometry,
  and `source_digest` must be a 64-char lowercase SHA-256). The model now refuses
  self-contradictory payloads with a `ValidationError` — verified directly.
- **Observed**: parent has fixed `_fixed_layout_item` to be replaced by a raw OPF / container
  XML parser (`EpubProcessor._fixed_layout_ids(input_path)` at `epub_processor.py:563`)
  that reads itemref properties before EbookLib discards them. I confirmed via probe
  that two EPUB3 cases that the *old* helper mis-handled are now correctly classified:
  - per-itemref `rendition:layout-pre-paginated` with **no** global meta → `{'ch1'}`
    (Observed, before: silently `False`).
  - global `rendition:layout = pre-paginated` plus per-itemref `rendition:layout-reflowable`
    → the reflowable item is **not** in the set, the rest are. (Observed, before: all items
    in the set, so the reflowable override was ignored.)
  Parent's own test `test_epub_spine_rendition_override` covers this at the processor seam.
- **Observed**: PDF geometry on rotated pages is in display coordinates (mediabox
  * `page.rotation_matrix`), per the resolver docstring. The numeric oracle I built from
  `page.get_text("rawdict")` + `page.rotation_matrix` agrees with the placement quad's
  corners on rotations 0, 90, 180, 270. **No wrong-anchor defect observed on the resolver
  itself** for the public surface.
- **Observed**: the v2 mark pipeline in `document_processor.py:1270` (the `_draw_note_body`
  → composer → renderer path) does apply `page.derotation_matrix` at `_transform_point` in
  `renderers/pdf.py:232` (`fitz.Point(x, y) * path_matrix * page.derotation_matrix`), so
  the *vector ink* path does NOT send display coordinates to an unrotated drawing API.
  The pipeline is internally consistent on the test fixtures I built (a 270° rotated page
  still places the underline mark on the visible "milligrams" glyphs).
- **Derived**: the resolver contract is sound. I cannot, from the public API alone,
  reproduce a wrong-anchor case. The placement module is not the source of the documented
  "wrong anchor" failures the parent flagged at the checkpoint — those belong to v1 plan
  migration, the v1 prefix-search tier ladder, or annotation generators upstream.

## What I did not find

- **No PDF wrong-anchor via the public resolver.** I could not construct a case where
  `resolve_pdf_quote` returns `RESOLVED` with quads that do not cover the requested
  characters. Every test case I built for repeated / overlapping / partial-prefix / 
  stale-offset / NFC / whitespace / smart-quote inputs is fail-closed (`unresolved`,
  `ambiguous`, or `selector_hints_mismatch`).
- **No EPUB wrong-anchor via the public resolver.** I could not construct a case where
  `resolve_epub_quote` returns `RESOLVED` with `epub_segments` that point at text other
  than the requested quote. Cross-node matches are joined into the same run; block
  boundaries are respected; cross-block quotes refuse with `quote_not_found`.
- **No display-coordinate / unrotated-drawing mismatch in the v2 mark pipeline.**
  The ink renderer's `_transform_point` (line 232) applies the page's
  `derotation_matrix`, so quads in display space are correctly de-rotated before
  they are passed to `fitz.Shape.draw_line` / `draw_bezier`. The renderer's
  `committed_underlay` path uses the same `_transform_point`, so marks and
  connectors agree.

## Test file

`tests/test_strict_placement.py` — 73 tests, all green against the current branch tip.
The file is independent of the parent-supplied
`test_placement_rendering.py::test_epub_spine_rendition_override` (which covers the
itemref override at the processor seam). The breakdown:

| Section | Tests | What it pins |
|---|---|---|
| A. Pydantic `PlacementResult` model | 18 | `schema_version = 1.0`; refusal invariants; status/reason pairing; geometry-only-vs-text-only; SHA-256 source digest; finite points; `extra="forbid"`. |
| B. `resolve_pdf_quote` statuses | 4 | RESOLVED, AMBIGUOUS, UNRESOLVED (quote_not_found), UNRESOLVED (selector_hints_mismatch) all reachable on real pages. |
| C. PDF bounded inputs | 5 | `quote_limit_exceeded`, `candidate_limit_exceeded`, `input_limit_exceeded`, `quote_not_found` at MAX_NEEDLE_CHARS, over-long prefix refused. |
| D. PDF raw-span mapping | 4 | collapsed whitespace round-trip; curly-quote folding; no-quote-shortening; `NormalizedText.find_all` oracle. |
| E. PDF hints | 7 | disambiguating prefix / start_offset / end_offset / suffix all pick the right occurrence; stale prefix / stale offset refused; non-disambiguating hint surfaces as `ambiguous_quote`, not silent first-occurrence. |
| F. PDF geometry | 7 | quad corners lie inside the per-char display bounding box on rotations 0/90/180/270; quads stay inside `page.rect`; multi-line ambiguates; quads are finite. |
| G. `resolve_epub_quote` statuses | 5 | RESOLVED, AMBIGUOUS, UNRESOLVED (quote_not_found), UNSUPPORTED_RENDERER (fixed_layout=True), unsupported record carries no fake geometry. |
| H. EPUB cross-node / block boundary | 5 | `<em>`, nested `<em><strong>`, multi-inline, cross-block refused, raw_span indexes local run. |
| I. EPUB bounded inputs | 3 | `quote_limit_exceeded`, `candidate_limit_exceeded`, `input_limit_exceeded`. |
| J. `epub_match_from_placement` rehydration | 5 | succeeds on original DOM; refuses after text mutation (digest mismatch); refuses PDF-shaped records; refuses unresolved records; refuses unsupported_renderer records. |
| K. EPUB selector / source availability | 2 | non-Tag root → `source_unavailable`; over-long prefix refused. |
| L. Source-digest stability | 2 | identical DOM produces identical digest; text change flips digest. |

Total: **73 tests, 0 failures**.

## Probes used

- Numeric geometry oracle for rotation: built from `page.get_text("rawdict")` directly,
  transformed by `page.rotation_matrix`, accumulated the 4 display corners per glyph in
  the resolved `raw_span`, computed the bounding box, and asserted every placement-quad
  corner lies inside it. Independent of the placement module — same code path
  `documents/pdf.py:PdfPageIndex` itself uses, but built from rawdict without
  round-tripping through the resolver.
- Fixed-layout detection oracle: hand-crafted EPUB3 zip files in `/tmp` with the
  three failure modes (no global meta + per-itemref pre-paginated; global pre-paginated
  + per-itemref reflowable; both) and called the public `_fixed_layout_ids` helper.
  Re-ran the probe after the parent's fix to confirm the new helper returns the
  correct set.

## Exact repro for the original `_fixed_layout_item` defects (now fixed)

```python
# per-itemref pre-paginated, no global meta
# Old _fixed_layout_item returned False → wrong renderer
# New _fixed_layout_ids returns {'ch1'} → correct
```

```python
# global pre-paginated, per-itemref reflowable
# Old _fixed_layout_item returned True for the reflowable item → wrong renderer
# New _fixed_layout_ids excludes the reflowable item → correct
```

## Open items I did not test

- The annotation generator / plan migration: the parent's "wrong anchor" observations
  at 04a4489 (prefix-recovery on a real book anchoring "fifty milligrams" to
  "five milligrams" in both renderers, v1 plan migration inventing first-occurrence
  hints) are above the placement seam and out of scope for falsifying the public
  contract.
- The v2 layout path's handling of rotated pages: it currently fails with
  `SkipReason.UNPLACEABLE` on rotated pages because body-column inference refuses
  to commit when no body columns are detected. This is a layout concern, not a
  placement concern — the placement returns correct display-space quads; the layout
  refuses to consume them on a single-line rotated fixture. Not investigated further.
