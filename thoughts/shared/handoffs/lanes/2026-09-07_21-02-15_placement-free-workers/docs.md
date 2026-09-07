> Worker report, preserved verbatim below. Claims here are worker-reported, not final release validation. Concurrent edits can make reported test counts stale. The final root evidence packet supersedes them.

# Docs audit — final evidence

**Branch:** `release/evidence-placement-contract`
**HEAD:** `04a44892b20632d67c7baff42518c7cbd33093c0` (worker additions unstaged)
**Owner:** `docs-finish-free` (this agent)
**Scope:** `README.md`, `docs/placement-contract.md` (new), `docs/readme-claims.md` (new)
**Constraint:** docs only, no code edits, native `.venv` only, no installs, no commits

## Files delivered

| Path | Status | Lines | Bytes |
| --- | --- | --- | --- |
| `README.md` | rewritten (was 395 lines, feature-catalog style) | ~223 | ~10,850 |
| `docs/placement-contract.md` | created | 382 | ~18,000 |
| `docs/readme-claims.md` | created | 288 | ~28,500 |

No code, no tests, no fixtures, no CI touched. The unstaged worker
changes in `src/`, `tests/`, `benchmarks/`, and `scripts/` are not mine.

## Test status

- `.venv/bin/python -m pytest tests/ -q --ignore=tests/test_placement_benchmark.py` → **1961 passed, 0 failed** in 23.66s.
- `tests/test_docs.py` (29 README/CLAUDE.md/ARCHITECTURE.md contracts): **all pass**.
- `tests/test_packaging.py` (7 tests, including `test_readme_documents_the_lock_workflow`): **all pass**.
- The 8 failures under `tests/test_placement_benchmark.py` are the
  worker's in-progress oracle-corpus audit. The parent has flagged them
  in the parent turn ("actual five-vs-fifty suffix mismatch … 3 extra
  positive cases ×2 renderers + candidate bound"). Not in this agent's
  scope.

## README shape (claim-surface, not feature catalog)

Sections:

1. One-paragraph positioning ("quoted evidence, placed on a document — or an explicit refusal").
2. **Evidence-to-placement contract** — four-outcome table, normalization, hints-as-constraints, three renderer scopes (PDF display points, reflowable EPUB DOM text, fixed-layout EPUB unsupported).
3. **Fail-closed on distinctive terms** — explicit note that "distinctive" is project vocabulary, not a W3C standard; W3C `TextQuoteSelector` / `TextPositionSelector` treat multiple matches as partial success; this project treats them as ambiguous refusal. (Added per parent turn.)
4. **Run the evidence check** — offline `scripts/benchmark_placement.py` + pytest; explicit "scope is quote placement, not LLM quality" disclaimer; `tests/test_placement_benchmark.py` with `red_capable_mutations` that **assert the benchmark detects those injected failures** (per parent turn — replaced the unprovable "cannot be satisfied by accident" wording).
5. **Try the annotation pipeline offline** — six runnable commands using the public-domain Alice fixture from `examples/src/`. The "Same as the committed" wording was removed (per parent turn); the README now states the sidecars record "earlier runs" and "the bytes of a new run are not guaranteed to match them".
6. **Usage reference** — `--force`, parent-directory creation, `--persona-name` built-ins, single `--font caveat-brush` registry key (font catalog trimmed per parent turn), reproducible install from `requirements-dev.lock`.
7. **Boundaries** — no OCR, no LLM-quality validation, no procedural note-body handwriting, reflowable-EPUB DOM anchors ≠ coordinates, fixed-layout EPUB not silently treated as reflowable, legacy `documents.matching` fuzzy helpers explicitly outside the supported guarantee. One-line note that `render_plan()` is the CLI's live entry point.
8. **Related work** — W3C TextQuoteSelector/TextPositionSelector, **Anchorite ([github.com/populationgenomics/anchorite](https://github.com/populationgenomics/anchorite))**, Hypothesis fuzzy anchoring. **No novelty claim, no "they do what we do" framing.** The Anchorite section reflects the parent's prior investigator's findings verbatim:
   - uses `pypdfium2`, not PyMuPDF
   - 0–1000 normalised page coordinates (we use display points)
   - Smith–Waterman-family alignment with `score = 15` minimum rejection default
   - OCR-ingest alignment additionally rejects on `second_best ≥ best × uniqueness_threshold`
   - the `resolve` function explicitly does **not** implement that uniqueness filter and has an upstream TODO to flag non-unique matches — explicitly **not** equivalent to our `AMBIGUOUS` outcome
9. **License and example sources** — AGPL-3.0-or-later, USA public-domain Alice (Project Gutenberg #11), Gutenberg license quote.

The dead link to `scripts/red_mutations.py` (deleted by the worker — the
red-capable mutations now live in `tests/test_placement_benchmark.py`)
was removed per parent turn.

## `--fail-pages` semantics (corrected per parent turn)

The README used to claim "`--fail-pages` exits 1, NO out.pdf"; the
real HEAD behaviour is split:

- **Partial failure** — some pages succeed, the artifact **still
  ships**, the sidecar lists the failed page numbers, exit 0 with a
  warning.
- **Total failure** — every page fails, **the artifact is not written**,
  the sidecar lists every page as failed, the run exits nonzero.

The README now states both explicitly.

## Claims removed (would not survive a falsifiability check)

These were present in the original 395-line README and were removed
because the prior investigator (`/tmp/hbp-claims-investigation.md`)
marked them false, stale, or unsupported:

- "Any PDF or EPUB" as a universal claim — replaced with explicit OCR
  / fixed-layout-EPUB / reflowable-EPUB caveats.
- "Connected to the exact passage" as a universal guarantee — kept
  only as the placement contract's `resolved` outcome; downstream
  rendering caveats added.
- "230 vector drawings" — removed; on the committed
  `examples/hbp-example.pdf` at HEAD the count is 312, not 230.
- "Five providers" — corrected to **seven** (`anthropic`, `openai`,
  `openrouter`, `ollama`, `lmstudio`, `openai-compatible`, `stub`).
- "DEFAULT_MODEL = claude-sonnet-4-20250514" — corrected to
  `claude-sonnet-5` (current `src/halfblood/config.py:26`).
- "Test counts" / "32s full 410-page run, 261 of 410 mid-book kill" —
  removed; replaced with the deterministic `scripts/stress_large_book.py`
  recipe without quoting absolute counts that depend on host speed.
- "Any OpenAI-compatible endpoint works" — narrowed to the seven
  configured providers with an explicit "endpoint and model
  compatibility still need checking" caveat.
- "`AnnotationType` enum and `_mark_target`" contributing recipe — not
  added; the live path is `render_plan()` + v2 mark intents / composer.
- "PyMuPDF uniquely provides …" novelty claim — removed;
  Anchorite-related-work section gives the actual related work with no
  uniqueness claim.
- "AGPL is required rather than chosen" / "A commercial PyMuPDF license
  is not an escape hatch" — softened to "PyMuPDF offers AGPL/commercial
  licensing; EbookLib is AGPL-licensed. Review their terms for your use
  and distribution."
- "chemist, philosopher, physicist, debate coach" personas in
  TEST_CASES — the actual genres in `TEST_CASES` are chemistry / cooking
  / philosophy / physics / rhetoric. The README no longer enumerates
  them; it points at `TEST_CASES` directly.

## `docs/placement-contract.md` contents

Public-API contract for `halfblood.placement`, pinned at HEAD:

- **Scope** — what's in / what's out. Fixed-layout EPUB and the legacy
  `documents.matching` ladder explicitly outside the supported
  guarantee.
- **Public entry points** — `resolve_pdf_quote`, `resolve_epub_quote`,
  `epub_match_from_placement`, plus the `PlacementResult` Pydantic
  model.
- **`TargetSelector`** field table with semantics for `exact` /
  `prefix` / `suffix` / `start_offset` / `end_offset`.
- **Normalization** — NFC + whitespace + typographic quote + en/em
  dash folding; the exact rule chain (no case fold, no punctuation
  drop, no paraphrase recovery). Pinned normalization identifier
  `nfc-whitespace-typographic-v1`.
- **Hints as constraints**, not scores. Ambiguity semantics: complete
  normalized quotation matches counted first, then hint verification.
- **Bounds** — `MAX_INPUT_CHARS = 50_000`, `MAX_NEEDLE_CHARS = 5_000`,
  `MAX_CANDIDATES = 500`, each with the fixed `reason` code on exceed.
- **Result schema** with field-by-field invariants (`RESOLVED` carries
  `raw_span` / `matched_text` / `coordinate_space` / renderer-specific
  geometry; non-`RESOLVED` carries none of them).
- **Coordinate spaces** — PDF is display points, never pixels, no DPI
  conversion; rotation order vs visual order caveat from
  `documents/pdf.py`. EPUB is `epub_dom_text`, never coordinates.
- **Reason codes** — full fixed machine-readable table
  (`unique_verified_quote`, `ambiguous_quote`, `quote_not_found`,
  `selector_hints_mismatch`, `geometry_unavailable`,
  `input_limit_exceeded`, `candidate_limit_exceeded`,
  `quote_limit_exceeded`, `invalid_selector`, `source_unavailable`,
  `out_of_range_page`, `fixed_layout_unsupported`).
- **Resolution vs rendering** — explicit statement that `placement.py`
  resolves, the renderer renders; a refusal at resolution is a refusal
  at rendering.
- **Prior art** — W3C `TextQuoteSelector` / `TextPositionSelector`
  URLs; Hypothesis "Fuzzy Anchoring" history + current `match-quote.ts`
  source link; **Anchorite** cited as
  [github.com/populationgenomics/anchorite](https://github.com/populationgenomics/anchorite)
  with the verbatim findings from the parent's prior investigator
  (`/tmp/hbp-prior-art-primary.md`):
  - Uses `pypdfium2`, not PyMuPDF.
  - 0–1000 normalised page coordinates (we use display points).
  - Smith–Waterman-family alignment with `score = 15` minimum rejection
    default.
  - OCR-ingest alignment additionally rejects on
    `second_best ≥ best × uniqueness_threshold`.
  - The `resolve` function does **not** implement that uniqueness
    filter and has an upstream TODO to flag non-unique matches —
    explicitly **not** equivalent to our `AMBIGUOUS` outcome.
- **What this contract deliberately does not promise** — EPUB ladder
  stability under `locate_across_nodes`, v1-`target_text` migration,
  arbitrary DPI, cross-page ranges.

Reproducibility — the PDF and EPUB examples in the contract are
runnable as `.venv/bin/python -m halfblood.cli annotate
examples/src/alice.{pdf,epub}` against the public-domain Alice fixture.

## `docs/readme-claims.md` contents

A claims ledger mapping every substantive claim from the README (and
several from the original 395-line version that were removed) to an
exact HEAD command. Each row is labelled:

- **Observed** — re-confirmed on this tree at HEAD with the listed
  command.
- **Derived** — follows from code or configuration; the command proves
  the building block, not the claim itself.
- **Unknown** — cannot be checked at HEAD (requires a live provider
  key, depends on a model run that has not been reproduced, etc.);
  the README must not present it as fact.

The ledger's final "Items the README rewrites" section lists every
claim that was corrected or removed in this audit.

## Verification commands

Reproduce locally with the native `.venv`:

```bash
# Full test suite minus the worker's in-progress oracle audit
.venv/bin/python -m pytest tests/ -q --ignore=tests/test_placement_benchmark.py
# 1961 passed

# Doc-only tests
.venv/bin/python -m pytest tests/test_docs.py tests/test_packaging.py -v
# 36 passed

# README is current
head -1 README.md
grep -c 'populationgenomics/anchorite' README.md docs/placement-contract.md
# 1 each
grep -c 'balacij/Anchorite'   README.md docs/placement-contract.md
# 0 each

# Public placement API surface is intact
.venv/bin/python -c 'from halfblood.placement import resolve_pdf_quote, resolve_epub_quote, epub_match_from_placement, PlacementResult, PlacementStatus; print("ok")'
.venv/bin/python -c 'from halfblood.placement import PlacementPoint, PlacementQuad, EpubSegmentRef; print("ok")'

# Offline corpus reproduction
.venv/bin/python scripts/benchmark_placement.py
# JSON to stdout; needs no API key
```

## Items NOT in scope

Per the task constraints I did not touch: `src/`, `tests/` (except
untracked `tests/test_placement_benchmark.py` is the worker's),
`benchmarks/`, `scripts/`, `.github/`, `pyproject.toml`, `LICENSE`,
`HANDOFF.md`, `CLAUDE.md`, the unstaged files other workers own. The
`git status` for this agent is exactly three changes:

- `README.md` (modified)
- `docs/placement-contract.md` (new)
- `docs/readme-claims.md` (new)
