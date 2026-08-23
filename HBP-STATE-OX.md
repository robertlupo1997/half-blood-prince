# HBP-STATE-OX — What `half-blood-prince` Actually Is

Assessed from source, tests, and eval artifacts at `ed235f5` (git worktree `hbp-assess`).
README.md and CLAUDE.md were read last; all line numbers below come from `grep -n` / `cat -n` / `sed -n`.
The suite was executed with the project's own venv (`1849` tests collected: **1842 passed, 7 failed** —
all 7 are Rich ANSI/console-detection environment artifacts; they fail identically on the main
checkout, so they are not code regressions, but see §5.3).

---

## 1. WHAT IT ACTUALLY IS

A CLI tool that takes a PDF or EPUB, sends each page's text to an LLM, and burns the model's
margin notes back into a new copy of the book — hand-drawn-style ink marks, rotated
handwriting-font notes, connector arrows. The default voice is a young Severus Snape
(`annotation_generator.py:77`), but the voice is a plain string parameter
(`annotation_generator.py:73`, CLI `--persona/--persona-file/--persona-name`).

### The real pipeline, end to end

**Entry points** (`src/halfblood/cli.py`): `main` click group at `cli.py:576`; commands
`annotate` (`:583`, def `:656`), `preview` (`:910`), `web-preview` (`:1045`), `eval` (`:1083`),
`providers` (`:1114`). Console script `halfblood` (`pyproject.toml`, `[project.scripts]`).

1. **Input** — PDF (PyMuPDF) or EPUB (EbookLib). Auto-detected by extension (`cli.py:56`).
   PDFs are magic-byte-checked before opening (`cli.py:449`); a scan with no text layer is
   refused with an OCR hint, not a fake "0 annotations" (`cli.py:350`, `tests/test_scanned_input.py`).
   Boilerplate (Gutenberg headers, copyright) is skipped by default (`cli.py:795-812`).

2. **Segmentation** — the unit is the **page** (PDF) or spine item (EPUB), flattened to
   `PageContent(page_number, text, width, height)` (`document_processor.py:121`,
   `epub_processor.py:253`). No semantic chunking, no retrieval; context is the previous
   page's last 500 chars + next page's first 500 chars + the last 8 running INVENTION/WARNING
   notes (`annotation_generator.py:443`, `:598`). Pages are processed in waves of
   `concurrency` (default 3, `config.py:35`) via ThreadPoolExecutor
   (`annotation_generator.py:567`).

3. **What goes to the model** — one stateless call per page. System prompt = persona
   (~4.8k chars, `annotation_generator.py:106-135`) + persona-independent craft rules for the
   8 annotation types (`ANNOTATION_CRAFT`, `annotation_generator.py:111`). User prompt =
   page number, context, page text (`annotation_generator.py:354`). `max_tokens=2048`
   (`annotation_generator.py:360`). Measured: ~7.4k chars ≈ **~1,850 input tokens per page**.
   Output is forced structured: one canonical Draft 2020-12 schema derived from the Pydantic
   `RecordAnnotations` model (`generation/schema.py:117`), delivered via tool-call /
   json-schema / prompted modes negotiated per provider with a documented downgrade chain
   (`generation/structured_output.py:50-112`), always re-validated locally
   (`schema.py:5`). Transport is raw httpx — no vendor SDK anywhere
   (`generation/providers/anthropic.py:77`, `openai_compat.py:63`, `registry.py:100`);
   the provider seam is the sole retry owner with backoff and retry-after handling
   (`anthropic.py:110-177`); a typed error taxonomy exists (`generation/errors.py:7-109`).

4. **What comes back** — per page: `{target_text, annotation_type(8 kinds), content,
   confidence, position}` (`schema.py:20-52`), capped at `max_per_page` (default 5,
   `config.py:122`) by confidence. Everything accumulates into an `AnnotationPlan`.

5. **Anchoring** — `target_text` is located in the real text layer with quote/dash/whitespace
   normalization, an exactness-tier ladder (full → 8-word → 5-word → 3-word → longest word,
   `documents/matching.py:317`), tolerance modes (`matching.py:52`), candidate scoring with
   ambiguity fail-closed (`matching.py:582`), bounded inputs (`matching.py:35-37`), and
   cross-inline-tag matching for EPUB (`documents/epub.py:380`). Unmatched notes are skipped
   with typed reasons, never guessed (`models/rendering.py` SkipReason/SkipRecord).

6. **Layout + rendering** — a per-page placement engine proposes margin/inline/skip
   candidates, then a pure integer-quantized beam solver (default, width 128,
   `layout/page_solver.py:48`, `layout/engine.py:66`) picks a conflict-free assignment
   (overlap, connector-crossing, and displacement costs). Marks are procedural vector strokes
   (`ink/rough.py`: underline `:133`, circle `:159`, strike `:215`, highlight `:247`, caret
   `:278`); note bodies are typeset handwriting fonts bundled in the wheel (4 fonts,
   `cli.py:69-90`); the "procedural handwriting body" engine is an honest NO-GO stub that the
   CLI refuses (`ink/composer.py:271`, `cli.py:684`). PDF out = vector drawings, **not**
   native PDF annots (verified in `tests/test_cli_end_to_end.py:15-16`); EPUB out = XHTML/CSS
   semantic notes (`epub_processor.py:504`). `--dry-run` writes the plan JSON instead
   (`cli.py:831`); `web-preview` renders a plan to a self-contained offline HTML viewer with
   editing (`web_preview.py:366`, `:377`).

### What the persona system actually parameterizes
Only the **voice block** of the system prompt. The craft rules, the 8 types, the schema, and
all machinery are shared — a custom persona cannot lose the type definitions (that bug
happened and is pinned: `annotation_generator.py:106-110`, byte-for-byte prompt test in
`tests/test_persona_craft.py:99-106`). Personas ship as packaged files
(`src/halfblood/personas/*.txt`).

---

## 2. WHAT WORKS AND WHAT DOESN'T

**Scale:** 82 test files, **1,523 test functions**, ~34,600 test lines (grep/wc). CI runs
ruff + mypy(strict-ish) + pytest + a wheel-install smoke script (`.github/workflows/ci.yml:22-24,40`).

**Genuinely covered (tests that assert real behavior):**
- Text anchoring: tolerance ladder, disambiguation, grapheme safety, EPUB cross-node
  matching (`test_match_tolerance.py`, `test_epub_prefix_tiers.py`, `test_epub_tolerance_ladder.py`).
- Layout: both solvers against shared contracts, connector geometry, dense-page degradation
  (`test_solver_contracts.py`, `test_page_solver.py` 860 lines, `test_connector_dense.py` 563).
- Providers: retry/backoff, malformed-200, structured-output mode chains, secret redaction
  (`test_anthropic_provider.py`, `test_openai_compat_provider.py` 989 lines).
- True end-to-end CLI with a deterministic stub provider through real PDF/EPUB bytes
  (`tests/test_cli_end_to_end.py` — the v0.1.0-era gap, closed).
- Data-loss guards: every file input fed back as `-o … --force` must be refused
  (table-driven, `cli.py:754`).
- Web preview including the inline JS under DOM stubs (`test_web_preview_editing_js.py`, 851 lines).

**Tests that assert little:** the suite is unusually free of vacuous tests, but thin spots
exist — `test_scanned_input.py` (3 asserts/73 lines), `test_note_measure_render.py`,
`test_normalization_delegates.py`, `test_font_resolution.py` are delegate/one-path checks.
The real fragility is different: several tests assert **exact Rich console output** and fail
in a plain non-tty shell (7 failures here, reproducible on main) — green on the author's
machine, red for a fresh contributor.

**Eval harness:** yes, `eval/eval_harness.py` (874 lines). It runs the real pipeline on 5
curated passages (`:198`) and grades with an LLM-as-judge over the same provider seam across
5 rubric metrics — voice, relevance, insight, variety, density, threshold 3.5/5 (`:85-100`).
It enforces judge independence (`--allow-self-judge` required for same model).

**Committed results: none.** `eval/` contains only the harness. The single known run —
**4.72/5, self-judged, generator = judge = one free OpenRouter model** — exists only as a
prose claim in `thoughts/shared/handoffs/general/2026-07-25_18-26-24_*.md:146,161-162`.
The handoff itself says it "proves transport, NOT quality."

**Tested ≠ verified:** rendering correctness is verified structurally (drawing counts,
geometry) plus **one** eyeballed real-model run of 9 rendered pages on a free model
(Session 31 handoff). Nobody has verified output quality on a real book with an independent
judge, and no rendered example artifact is committed to the repo at all.

---

## 3. THE HONEST MATURITY LINE

**Verdict: a working demo with genuinely production-grade engineering bones — not a product.**

The deciding fact: the pipeline's **entire accumulated real-world validation is one 9-page
render eyeballed once** (Session 31 handoff), while the repo carries 1,523 tests. The
engineering is verified; the *product output* is essentially unverified. Corroborating
evidence from the project's own Session 34 handoff: when it was finally run on real Internet
Archive books, it **crashed on 8% of pages and destroyed a user's input file** — defects no
test found, found only by running the product. Both are now fixed and guarded, but the
pattern is the point.

**What breaks on a 400-page book:**
- **No checkpoint/resume.** The plan is written only at the very end (`cli.py:831`, `:846-847`).
  A crash, Ctrl-C, or rate-limit storm at page 390 discards ~390 pages of paid API output.
  `--pages` chunking is the only mitigation.
- **Failed pages are silently absent** from the output — a warning at `cli.py:856-859`, then
  the artifact is written anyway. A 400-page book can ship with 20 unannotated pages.
- **Cost:** 400 pages = **≥400 API calls** at ~1,850 input tokens/page (measured above) plus
  ≤2,048 output tokens/page (`annotation_generator.py:360`). That is roughly 0.75M input +
  up to 0.8M output tokens per book at Sonnet-class pricing — tens of dollars per book —
  with **no prompt caching** (no `cache_control` anywhere in `src/`, grep) and no cheap-model
  triage. Concurrency 3 (`config.py:35`) makes wall-clock hours, throttled by retry/backoff.
- Memory is fine (per-page processing; the fitz doc is closed after load).

**Could a stranger install and run it from the README alone?** Mostly yes — the README is
accurate and unusually honest (fonts bundled, no SDK, `providers doctor --offline`). But it
requires cloning + `pip install -e .` (no published wheel), needs an API key with credit
(the author's own OpenRouter key has none), and the default `claude-sonnet-5`
(`config.py:26`) costs real money per book. The eval section's "wire it into CI" advice has
not been followed by the author himself.

---

## 4. WHAT IT IS FOR — the products hiding in this repo

Intent, reverse-engineered: the code's center of gravity is not the Snape joke; it is the
**grounded-annotation substrate** — exact-quote anchoring, fail-closed matching, page-layout
solving, degradation reporting. Three products:

1. **The Snape gag (as-is).** Turn any book into the Half-Blood Prince's copy.
   *Who wants it:* nobody as a business — it is a demo that makes people remember the repo.
   *Competes with:* AI novelty content on social media; Riddle (named as inspiration,
   `CLAUDE.md:95`). *Worth building if:* it is the portfolio hook that gets the repo read.
   It already is.

2. **A persona-voiced active-reading/study tool.** The persona library (chemist, detective,
   editor, philosopher), `--persona-file`, and the eval rubric reveal the real product
   intent: any expert voice annotating any text. *Who wants it:* students, autodidacts,
   reading-tool users. *Competes with:* Readwise Reader AI, NotebookLM, Perusall, generic
   chat-with-PDF. *Worth building if:* annotation quality is proven by an independent judge
   on real books (currently n≈1 self-judged run), and per-book cost drops ~10× (caching +
   smaller models), because chat-with-PDF is nearly free by comparison.

3. **The grounded document-annotation engine (the defensible one).** The matching tier
   ladder with ambiguity fail-closed, cross-node EPUB anchoring, the integer beam layout
   solver, structured-output negotiation with downgrade chains, and typed degradation
   reporting — this is a reusable answer to "how do you put LLM output *onto* a document at
   the right pixels without lying about it." *Who wants it:* any team building
   e-reader markups, proofreading tools, PDF review tools, or agent-output grounding.
   *Competes with:* hand-rolled fuzz matching in every in-house doc tool. *Worth building
   if:* extracted as a library with the corpus-based anchor benchmarks it already implies
   (the handoffs contain measured 48/50, 84/88 anchor rates — none committed as fixtures).

---

## 5. THE TEN THINGS MOST WORTH FIXING (ranked value ÷ effort)

*Makes it work:*

1. **Checkpoint/resume for long runs.** Defect: plan written once at the end (`cli.py:831`,
   `:846`); a crash discards all paid generation. Cost: makes any real book a financial
   gamble. Fix: stream per-page results into a partial plan JSON (the `--dry-run` format
   already exists) and add `--resume-from plan.json`. Medium effort, highest product value.
2. **Run the eval harness once with an independent frontier judge and commit the results.**
   Defect: zero committed eval artifacts; the only score is self-judged on a free model
   (§2). Cost: every quality claim is unfalsifiable. Fix: spend the credit, commit
   `eval/results-<model>.json` + a summary table. Hours of effort, converts the project's
   biggest unknown into evidence.
3. **Make console assertions environment-proof.** Defect: 7 tests fail in a plain shell on
   Rich ANSI/spinner output (e.g. `test_cli.py:552`, `test_cli_end_to_end.py:626`).
   Cost: a fresh contributor's first `pytest` is red; CI credibility. Fix: strip ANSI /
   set a deterministic console in the test harness. Small effort.
4. **Surface per-page failures as data, not a warning.** Defect: `failed_pages` printed at
   `cli.py:856-859` but the artifact ships silently incomplete; no per-page error report file.
   Fix: write a render/generation report sidecar (RenderReport already exists in
   `models/rendering.py`) next to the output. Small-medium effort.
5. **Map the 8 unmapped composer degradation codes.** Defect: silently dropped (Session 34
   handoff, "next" list). Cost: renders degrade invisibly. Fix: extend
   `test_degradation_mapping.py`'s table to total coverage. Small effort.
6. **Cut cost per book ~5–10×.** Defect: no prompt caching (grep: no `cache_control`), no
   model triage; a 400-page book is ~400 full-price calls. Fix: Anthropic prompt caching on
   the 4.8k-char static system prompt (trivial at the seam), plus a `--cheap-model` mode for
   DOODLE_NOTE-class pages. Small effort, direct product-enabler.

*Makes it impressive:*

7. **Commit rendered example outputs.** Defect: the repo contains zero images/PDFs showing
   what the tool produces (find: none). Cost: a reviewer must pay API money to see anything.
   Fix: one annotated fixture PDF + EPUB + a screenshot in the README. Tiny effort, huge
   first-impression return.
8. **Better connector routing.** Defect: 10/49 connectors still cross body text (Session 34,
   honestly flagged). Fix: route around body columns using the occupancy data the layout
   engine already computes (`documents/pdf_occupancy.py`). Medium effort, visible quality win.
9. **Extract the anchoring substrate as a benchmark + library.** Defect: the measured
   anchor-corpus results live only in prose handoffs. Fix: commit the scanned/clean corpora
   fixtures and a `pytest`-run anchor-rate benchmark; make `documents/` importable standalone.
   Medium effort; turns §4 product 3 from a claim into an artifact.
10. **Regenerate or archive CLAUDE.md.** Defect: it is badly stale — "All 44 tests should
    pass" (`CLAUDE.md:110`; actual: 1,523), "no async/concurrent page processing"
    (`CLAUDE.md:88`; waves shipped), "collision detection" listed open (`CLAUDE.md:92`;
    built at `layout/engine.py`), "Anthropic SDK" (`CLAUDE.md:49`; no SDK). Cost: the
    project's own docs warn that stale entries cost wasted investigation cycles. Fix: one
    truth pass. Tiny effort.

---

## 6. WHAT WOULD MAKE IT A PORTFOLIO CENTREPIECE

Judged as an AI-engineering artifact:

**Already strong — a reviewer can see the engineering, which is rare:**
- *Structured output handling* is the best part: one canonical schema derived from Pydantic
  (`schema.py:117`), per-provider mode negotiation with an explicit downgrade chain and
  local re-validation (`structured_output.py:50-112`), bounded decode with depth/size caps
  (`structured_output.py:114-160`), typed error taxonomy with secret redaction
  (`errors.py:109`).
- *Failure behavior* is fail-closed and honest: ambiguous anchors refuse rather than guess
  (`matching.py:43-50`, `:582`), skips carry typed reasons, connectors degrade instead of
  crashing, and the render report distinguishes mark-only survival. The Session 34 story —
  crash + data loss found by running the product, then table-driven guards — is itself a
  strong portfolio narrative if told.
- *Deterministic core:* pure integer beam solver with quantized scoring and byte-identical
  corpus gating (`page_solver.py`) is the kind of thing most LLM projects never attempt.
- *Cost/observability:* token usage totals per run (`annotation_generator.py:44-58`), usage
  line in CLI (`cli.py:538`), offline `providers doctor`.

**What a strong technical reviewer criticises first:**
1. **Evaluation is the missing pillar.** An LLM-as-judge harness exists but has one
   self-judged run on a free model, uncommitted. For a project whose entire output is
   subjective text quality, that is the first question: "how do you know the notes are
   good?" — and the honest answer today is "one eyeballed 9-page run."
2. **The prompt architecture is per-page and memoryless.** 500 chars of neighbor text and
   the last 8 notes (`annotation_generator.py:443`, `:598`) is a thin continuity model: no
   document-level planning pass, no persona-state accumulation beyond 8 strings, no
   retrieval. It works for the gag; a reviewer will ask what happens to voice consistency
   on page 300 (nobody knows — unmeasured).
3. **No cost engineering.** No prompt caching, no model tiering, no batch API; cost control
   = `max_tokens` and `max_per_page`. For a tool whose unit economics are "one LLM call per
   page of a book," that is the second question.
4. **Green-suite theater risk:** 1,523 tests, but the product was run on a real book exactly
   once and immediately crashed. The reviewer will note that test mass concentrated on units
   while the integration seam with *reality* (real scans, real EPUBs, real models) had none
   — the project knows this (`scripts/wheel_smoke.py` is the systemic response) but the
   real-model layer is still missing.

**The centrepiece move:** fix §5 items 1, 2, 6, and 7. Then the repo shows, in one glance:
a real annotated book, an independent judge's scorecard, resume-safe long runs, and cached
per-page costs — on top of the already-visible structured-output seam, fail-closed anchoring,
and deterministic layout solver. That combination (output you can see + quality you can
verify + cost you can defend) is what separates an AI-engineering centrepiece from a very
well-tested demo. Today it is the latter with the bones of the former.

---

### Doc-vs-code gaps found (code wins)

| Claim | Where | Reality |
| --- | --- | --- |
| "All 44 tests should pass" | `CLAUDE.md:110` | 1,523 tests, 82 files |
| "No async/concurrent page processing" | `CLAUDE.md:88` | Wave concurrency default 3 (`config.py:35`, `annotation_generator.py:567`) |
| "collision detection" open | `CLAUDE.md:92` | Solver conflict detection built (`layout/page_solver.py:304`, `:360`) |
| "Anthropic SDK" / forced tool_use via SDK | `CLAUDE.md:49`, `:18` | No SDK; raw httpx seam (`providers/anthropic.py:77`), mode-negotiated structured output |
| "native PDF annotations" | `CLAUDE.md:23` | Legacy path only; CLI path emits vector drawings, 0 native annots (`test_cli_end_to_end.py:15-16`, README:35 corrected) |
| Eval "wire it into CI to catch regressions" | `README.md:249` | No committed eval results; CI runs no eval (`.github/workflows/ci.yml:22-24,40`) |

README.md is broadly accurate (post Session-34 truth pass); CLAUDE.md is the stale document.
