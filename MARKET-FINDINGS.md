# Market findings — grounded document annotation

**Source:** ChatGPT Deep Research, 2026-08-22. Star counts snapshotted that day.

## Verdict: real gap, niche market

The gap is NOT "how do I draw a PDF highlight" — PyMuPDF (~10.5k), pdfplumber (~10.7k),
pypdf (~10.2k), Docling (~65.4k), Unstructured (~15.3k) and Google Document AI already
cover extraction and geometry. The gap is the **reliability layer**: exact quote
anchoring + ambiguity detection + refusal on failed match + parser provenance + PDF
coordinate conversion + EPUB cross-node anchoring + renderer-aware positioning +
reproducible diagnostics + collision-free layout.

## There IS a direct competitor — read this first

**`Anchorite`** (~2 stars). Quote resolution from generated text to PDF character
bounding boxes, fuzzy Smith-Waterman matching, uniqueness thresholds, **and rejection
when coverage is inadequate**. Its predecessor `Groundmark` is archived into it.

So the core idea — quote-to-bbox with rejection on ambiguity — is **not unprecedented**.
It is very new, tiny, PDF-only, and appears to lack EPUB cross-node anchoring and a
margin-layout solver. The space is not saturated, but "nobody has done this" is false
and must not appear in any public claim.

## "Fail-closed anchoring" is not an established term

The research found no standard using that name. The adjacent established vocabulary:
- W3C `TextQuoteSelector` / `TextPositionSelector` (Web Annotation Model)
- Hypothesis "fuzzy anchoring", "intra-document / inter-document anchoring"
- LangExtract "exact character-span grounding" (`char_interval=None` when unlocatable)
- Anchorite's explicit rejection/coverage thresholds

The *framing* may be distinctive. The *principle* — escalating anchors, then abstain
when uniqueness is insufficient — is established. Claim novelty of framing at most.

## A technical caveat that constrains HBP's claims

**Reflowable EPUB has no renderer-independent pixel position.** Per EPUB 3.3, position
depends on viewport, font, CSS, pagination, and reader implementation. Fixed-layout
EPUB is the only case where pixel-precise placement is a document fact. Readium also
documents EPUB CFI interoperability problems including Unicode code-point vs code-unit
handling.

Any HBP claim about EPUB annotation placement must be scoped to fixed-layout, or stated
as renderer-relative. This is a correctness issue, not just marketing.

## Where grounding is documented to fail — use these as test cases

- The same quote occurring multiple times (W3C notes position selectors are brittle)
- PDF text is not a stable DOM: extraction varies by viewer and PDF.js version;
  native bboxes may be missing; equations extract poorly (Hypothesis issue #3720)
- Parser/OCR modes disagree on coordinates (Unstructured #3194, #3100, #1792)
- Citations present but unsupported: ALCE (EMNLP 2023) found strong systems failed
  complete citation support on ~half of ELI5 answers; RAGTruth (ACL 2024) released
  ~18,000 responses with word-level hallucination annotations

## The positioning the research recommends

Not "another PDF annotation library" but:

> **A deterministic evidence-to-geometry layer for AI-generated document annotations.**

Expose explicit outcomes: `Resolved` / `Ambiguous` / `Unresolved` / `Unsupported-renderer`.

**The defensible differentiator is not fuzzy matching — it is a publicly testable
guarantee that the library refuses to place an annotation when the evidence does not
uniquely support a location.**

Publish a benchmark containing: repeated quotes, OCR noise, hyphenation, multi-column
layouts, equations, scanned PDFs, changed PDFs, and reflowable EPUBs. That benchmark is
the artifact Decision 4 requires, and it is what makes the claim falsifiable.

## Buyers, if this is ever productised

Legal review, academic evidence extraction, medical literature workflows, audit,
regulated document QA, human-in-the-loop RAG interfaces. Unlikely to be a large
standalone developer market unless it becomes infrastructure for those systems.
