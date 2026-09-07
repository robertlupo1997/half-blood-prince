# Public placement API contract

Contract version: **1.0**. Render reports carrying these records use **1.1**.
Source: [`placement.py`](../src/halfblood/placement.py) and
[`models/placement.py`](../src/halfblood/models/placement.py).

## Supported interface

```python
from halfblood.models.annotations import TargetSelector
from halfblood.placement import (
    PlacementResult, PlacementStatus, resolve_pdf_quote,
    resolve_epub_quote, epub_match_from_placement,
)
```

- `resolve_pdf_quote(page: fitz.Page, selector: TargetSelector) -> PlacementResult`
- `resolve_epub_quote(root: bs4.Tag, selector: TargetSelector, *, fixed_layout=False) -> PlacementResult`
- `epub_match_from_placement(root, result) -> CrossNodeMatch | None`

The last function rehydrates verified EPUB node references against the original
DOM text structure. It returns `None` when the references are stale. Its return
value contains live nodes; `PlacementResult` itself is JSON-safe.

`DocumentProcessor.render_plan` and `EpubProcessor.render_plan`, including the
CLI's `annotate` command, consume this interface. Legacy `render_annotations`,
`find_text_rect`, `_resolve_annotation_to_anchor`, `score_candidates`, and
`locate_across_nodes` are compatibility code **outside this contract**. The
supported processors do not use their prefix/tolerance recovery. `web-preview`
is a plan viewer, not a PDF geometry validator.

## Four outcomes

| Status | Meaning | Usable anchor |
| --- | --- | --- |
| `resolved` | Exactly one complete normalized quote satisfies every supplied hint, and the renderer can represent it. | Yes |
| `ambiguous` | At least two candidates still satisfy every hint. | No |
| `unresolved` | No complete quote, conflicting hints, unavailable evidence/geometry, or exceeded bounds. | No |
| `unsupported_renderer` | Fixed-layout EPUB coordinate rendering is not implemented. | No |

Outcome selection is deterministic for identical inputs and dependency versions.
It does not use an LLM, random seed, similarity threshold, or proximity score.
This is not a guarantee about OCR truth, the meaning of a quote, or all PDFs.

## Selector and normalization

`TargetSelector.exact` is required and strips leading/trailing whitespace at
construction. `prefix` and `suffix` retain surrounding whitespace. Offsets are
optional nonnegative integers; `start_offset > end_offset` is a validation error.

The pinned normalization policy, `nfc-whitespace-typographic-v1`, performs:

1. Curly single/double quotes to ASCII single/double quotes.
2. En/em dashes to ASCII hyphen.
3. Each Unicode whitespace run to one ASCII space.
4. Unicode NFC composition.

There is **no case folding, optional punctuation, OCR repair, paraphrase,
shortened prefix, longest-word fallback, or first-hit guess**. A raw source slice
must normalize back to the entire normalized quote. A covering Unicode span
that contains extra normalized characters is refused.

Every complete occurrence is enumerated, including overlapping starts. Supplied
prefix/suffix must match normalized adjacent context. Supplied offsets must
match the raw span exactly. All hints must agree; none is merely a preference.
One verified candidate resolves. Zero candidates gives `quote_not_found`;
candidates with no hint agreement give `selector_hints_mismatch`; two or more
verified candidates give `ambiguous_quote`.

`candidate_count` counts the complete matches **before** hint filtering. Thus a
resolved result can have a count greater than one when genuine hints select one.
V1 migration produces exact-only selectors: finding the first occurrence in a
legacy plan is not evidence of the author's intended occurrence.

## Offsets and geometry

All ranges are half-open `[start, end)` Python Unicode character offsets, not
bytes, UTF-16 code units, or normalized-string offsets.

### PDF

`raw_span` indexes `page.get_text("text")`, including its line separators.
`quads` contains the bounds of touched glyphs per extraction line, in content-
stream order, transformed by the page rotation matrix. Named corners are
`ul`, `ur`, `lr`, and `ll`; each point has finite `x` and `y` values.

The coordinate space is `pdf_display_points`. PDF points are not pixels.
Rasterization needs the caller's display/DPI transform. These are text-layer
line bounds, not contours of each visible ink pixel. Content-stream order need
not be visual top-to-bottom order. `PdfPageIndex` must reconstruct the extracted
text exactly; geometry failure refuses rather than falling back to `search_for`.

### Reflowable EPUB

`raw_span` indexes the concatenated raw nodes in the selected **inline run**,
not the whole chapter. Each `EpubSegmentRef` has zero-based `run_index` and
`node_index` plus node-local `start` and `end` offsets. Inline markup can be
crossed; block boundaries cannot. The traversal excludes comments, script/style
text, and existing `hbp-*` markup. It does not compute CSS visibility or layout.

`coordinate_space="epub_dom_text"` names a text index space, **not coordinates**.
`quads` is empty. Viewport, font, CSS, and reader determine displayed positions.

The low-level DOM caller must supply `fixed_layout=True` for pre-paginated
content. The EPUB processor reads package `rendition:layout` and spine itemref
layout overrides from the input archive. It refuses fixed-layout items;
explicit reflowable overrides remain text-range supported. No fixed-layout EPUB
coordinate renderer is claimed to ship in this release.

## Serialized record

`PlacementResult` is frozen and rejects unknown fields. `model_dump_json()` and
`PlacementResult.model_validate_json(...)` provide a round trip.
`PlacementResult.model_json_schema()` exports its machine-readable schema.

| Field | Semantics |
| --- | --- |
| `schema_version` | Literal `"1.0"`; unsupported versions fail model validation. |
| `status`, `renderer`, `reason` | Four-outcome enum, `pdf`/`epub`, finite reason code. |
| `normalization` | Pinned policy identifier above. |
| `candidate_count` | Nonnegative, pre-hint count; bound failures return zero rather than a truncated claim. |
| `raw_span`, `matched_text` | Verified original source range and slice; only on resolution. |
| `coordinate_space` | `pdf_display_points` or `epub_dom_text`; only on resolution. |
| `quads` | Nonempty for resolved PDF, empty for EPUB/refusals. |
| `epub_segments` | Nonempty for resolved EPUB, empty for PDF/refusals. |
| `source_digest` | SHA-256 evidence identity; only on resolution. |

For PDF the digest hashes all extracted page text as UTF-8. For EPUB it hashes
`json.dumps([[str(node) for node in run] for run in runs], ensure_ascii=False)`
as UTF-8. It binds run text and segmentation, **not file bytes, CSS, or geometry**.
It is not a security signature and does not authenticate a book.

Model validation rejects contradictory outcomes: refusals cannot carry usable
anchors; resolutions require a nonempty range whose length equals `matched_text`,
a digest, and renderer-appropriate evidence. An ambiguous record needs at least
two candidates. Successful deserialization alone is not source verification;
use the resolver or EPUB rehydrator against the actual input.

## Bounds and failures

- Source text: at most 50,000 characters (EPUB counts all descendant text).
- Quote and each context hint: at most 5,000 characters.
- Candidate starts: at most 500.

Bounds refuse, not truncate. Constructor/type-validation errors can raise
Pydantic `ValidationError`; wrong selector types at the resolver return
`invalid_selector`. Expected source/alignment failures return records. OS errors,
resource exhaustion, programming errors, and invalid archive parsing are not
promised to become placement outcomes. Processor plans reject duplicate unit
IDs, ordinals, and annotation IDs before writing.

| Status | Reason codes |
| --- | --- |
| resolved | `unique_verified_quote` |
| ambiguous | `ambiguous_quote` |
| unresolved | `quote_not_found`, `selector_hints_mismatch`, `input_limit_exceeded`, `quote_limit_exceeded`, `candidate_limit_exceeded`, `geometry_unavailable`, `source_unavailable`, `invalid_selector`, `out_of_range_page` |
| unsupported_renderer | `fixed_layout_unsupported` |

`out_of_range_page` is emitted by processors for an absent page/spine unit.
The standalone resolvers receive a page/root, not a page ordinal.
Version 1.0 consumers should branch on status and the documented reason codes;
future changes to these semantics require an explicit contract version change.

## Resolution is not drawing

`RenderReport.placements` carries `{annotation_id, source_locator, result}` for
each attempted annotation. In reports that carry placements, IDs must cover the
rendered/skipped partition exactly. Refusals cannot be rendered or mark-only.
Legacy reports without placement records remain loadable.

A resolved quote may still have an unplaceable note. `marks_only` records a
supported target mark retained when its note is skipped. Composer omissions
are recorded in `composition_degradations` by annotation, code, and bounded
detail, including codes absent from the finite summary flags. `rendered` does
not imply every optional mark or connector is present or collision-free.

EPUB rendering resolves the original DOM once, rejects later overlaps, then
isolates accepted source ranges before applying markup. It does not re-search a
changed DOM and reinterpret a formerly ambiguous quote as unique.

## Prior art and limits

“Fail-closed anchoring” is project vocabulary, not a recognized standard.
W3C defines [TextQuoteSelector](https://www.w3.org/TR/annotation-model/#text-quote-selector)
and [TextPositionSelector](https://www.w3.org/TR/annotation-model/#text-position-selector).
[Hypothesis](https://web.hypothes.is/blog/fuzzy-anchoring/) documents fuzzy anchoring.
[Anchorite](https://github.com/populationgenomics/anchorite) already provides PDF
quote-to-bbox matching with Smith–Waterman alignment, uniqueness checks, and
rejection gates. Half-Blood Prince makes no invention or superiority claim over
these systems. Its tested combination includes PDF, cross-node EPUB, and note
layout, with the narrower full-quote policy stated here.

Run `.venv/bin/python scripts/benchmark_placement.py` for falsifiable corpus
results. The benchmark and tests establish measured cases, not a formal proof,
a worldwide accuracy rate, LLM quality, OCR correctness, or EPUB reader parity.
