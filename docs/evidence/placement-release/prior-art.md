# Prior-art check

Observed 2026-09-07: `gh api repos/populationgenomics/anchorite/readme --jq .content` (base64 decoded).
Primary source: https://github.com/populationgenomics/anchorite

Extract:

### 3. Resolve quotes to coordinates

Given a list of verbatim quotes (e.g. citations extracted by an LLM), find the bounding boxes that each quote covers. Two API shapes depending on what you have on hand:

**`resolve_quote`** — when you've stored Markdown and a list of `(span, page, box)` records on disk (the typical sidecar shape):

```python
spans = [
    anchorite.SpanAnchor(span=(0, 25), page=0, box=anchorite.BBox(10, 10, 20, 20)),
    anchorite.SpanAnchor(span=(25, 44), page=1, box=anchorite.BBox(30, 30, 40, 40)),
]
located = anchorite.resolve_quote(markdown, spans, "quick brown fox jumps")
# [(0, BBox(10, 10, 20, 20))]
```

**`resolve`** — when you've stored *annotated* Markdown (with `<span data-bbox=…>` tags inline, as produced by `annotate`):

```python
locations = anchorite.resolve(annotated, quotes=["Observations of a Nebula"])
# {"Observations of a Nebula": [(0, BBox(52, 120, 68, 880))]}
```

Both use the same fuzzy iterative Smith-Waterman pipeline and the same shared normaliser used during anchor generation, so a quote that aligned cleanly at ingest aligns cleanly here too. Each quote maps to a sorted list of `(page, BBox)` pairs — one per distinct anchor the quote overlaps.

For callers that only need to know whether a quote can be grounded (LLM tool-call validation, "did the model hallucinate this?"), `is_quote_grounded(text, quote) -> bool` skips the span-overlap step. `locate_quote_span(text, quote) -> (start, end) | None` returns *where* it grounds, as a half-open char span — for splicing a highlight directly into the source text:

```python
if anchorite.is_quote_grounded(text, quote):
    ...  # the LLM's quote is grounded in the source

span = anchorite.locate_quote_span(text, quote)
if span is not None:
    start, end = span  # text[start:end] is the matched region
```

**`PdfIndex`** — when you have raw PDF bytes and a list of quotes and want to skip the Markdown / Anchor pipeline entirely (e.g. the upstream LLM emitted citations against a PDF you already have on disk):

```python
index = anchorite.PdfIndex(pdf_bytes)
located = index.resolve(["Observations of a Nebula", "first 19 nebulae"])
# {"Observations of a Nebula": [(0, BBox(52, 120, 68, 880))],
#  "first 19 nebulae": [(2, BBox(...)), ...]}
```

Construction extracts per-character bounding boxes from every page (the expensive step); `.resolve` is then cheap and batches all quotes through a single `seq_smith.local_global_align_many` pass. Pages are 0-indexed.

You can optional