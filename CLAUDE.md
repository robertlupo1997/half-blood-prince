# Half-Blood Prince — Engineering Guide

## Read this first (2026-09-08)

⛔ **Every count and claim below is re-derivable. Run the command; do not carry the number.**
This file has been stale before and cost a full investigation cycle.

**What done means:** [`GATES.md`](GATES.md). Six gates; four are met. That file is the
definition of done this project ran 34 sessions without.

## Build & verify — recorded 2026-09-11 by `setup-harness`

Methodology: `~/dev-harness/core/HARNESS.md`. ⛔ A fact belongs in exactly one layer: doctrine there, this repo's gotchas here.

**The gate**, stop at the first red — the same three commands `.github/workflows/ci.yml` runs, on one interpreter. CI runs them on a 3.11/3.12/3.13 matrix and adds a separate `wheel` job, so a local green is necessary, not sufficient:

```sh
.venv/bin/ruff check src tests eval scripts && .venv/bin/mypy src/halfblood && .venv/bin/pytest tests/ -q
```

**What the gate does not cover.** The other two interpreters and the `wheel` job (`scripts/wheel_smoke.py`), which CI runs and this does not; `scripts/benchmark_placement.py`, which CI runs after the tests; the eval harness's real-pipeline path, exercised by hand only. `ci.yml` records the one case where a full-checkout green went red in CI (`tests/test_stress_evidence.py` needs `fetch-depth: 0`). Skips: `tests/test_real_book_placement.py` (module-level) and one test in `test_epub_inline_extraction.py` skip when `tests/corpora/real/` is absent — the corpus is tracked, so a clean clone has zero skips, but a green from a partial checkout has proven nothing about placement; `test_web_preview_editing_js.py` skips without `node`. Run with `-rs` and read the skip lines. A count with no selector is not a count: run from the repo root, `tests/`, nothing narrower.

**Pre-commit ladder:** the gate → secrets grep on the staged diff (`git diff --cached | grep -inE 'sk-or-v1|api[_-]?key|secret'`) → `git diff --cached --stat` read by eye.

**Shared checkout** (`git worktree list`: two live peers under `~/prime-agent-lab/wt/`, plus five stale Windows-side registrations whose checkout is gone — prune when you choose): one writer at a time, no `git stash`, no `git checkout -- <file>`, no formatter-wide runs (`core/HARNESS.md` §6).

**Money path — where a wrong number reaches a person:** `docs/evidence/**` (frozen run reports, `receipts.json` cost accounting), `examples/*.report.json`, `eval/eval_harness.py` metrics, `scripts/benchmark_placement.py` output. The first two are `Edit(...)`-denied in `.claude/settings.json`, which covers the Edit and Write tools (measured) but not a script that writes them — `Bash(python -c:*)` is allowed. Regenerating them is a deliberate act with a reviewer on the diff, whatever the tier.

**Layout, deliberately not the harness default:** `GATES.md` is committed project state — the definition of done — not the harness's gitignored task ledger. Do not gitignore it. Handoffs live in `HANDOFF.md` at root; plans in `docs/plans/`.

**Bash output is compacted by RTK** (global hook, `~/dev-harness/adapters/claude-code.md` "Shell-output compaction"). When completeness is the claim — the final staged diff, "no line matches" — prefix `RTK_DISABLED=1 ` on every command in the chain.

**The binding rule for any placement or rendering change: no gate runs on a fixture.**
Every EPUB fixture here is under the 50,000-character `MAX_INPUT_CHARS` bound. A real book
is not. `tests/corpora/real/` holds *The Elements of Style* (83,063-character chapter, 1,089
blocks) plus two frozen annotation plans, so placement is measurable with **no model call,
no network, and no API key**. Before this corpus existed, `annotate` shipped a book
containing zero annotations while 2,071 tests stayed green.

**Two defects fixed 2026-09-08** — read
[`docs/evidence/2026-09-07-real-book-placement-failure.md`](docs/evidence/2026-09-07-real-book-placement-failure.md):

1. `render_plan` resolved quotes against a whole chapter, but `resolve_epub_quote` is
   contracted to one inline run and the bound counts **all** descendant text. Every
   annotation on a real book was refused before matching. `_resolve_bounded` now tries the
   chapter first and falls back to leaf blocks, failing closed on more than one hit.
2. `_html_to_text` inserted a newline between every *text node*, so `<i>hers</i>, <i>its</i>`
   reached the model as `hers\n,\nits`. The model quoted it faithfully and placement
   refused a string that does not exist. Only block-level elements break a line now.

⚠ **`MISSING_TARGET` used to mean two different things.** A bound refusal was reported under
the reason code for "the model quoted loosely," and that mislabel aimed the diagnosis at the
model for six weeks. If you add a skip path, keep the reason code truthful.

**Free models CAN generate annotations. The earlier claim that they cannot was a defect in
this repository.** `annotation_generator.py` asked for 2048 output tokens per page, and the
provider seam escalates once to 4096 without ever reaching its own 8192 ceiling. A reasoning
model spends that on reasoning tokens and the payload is cut off mid-object. Re-measured
2026-09-08 on one real page, `--structured-output function`, nothing else changed:

| budget | outcome |
|---|---|
| 2048 | `IncompleteResponseError`, truncated after the escalated retry |
| 8192 | `StructuredOutputError`, no tool call returned |
| 16000 | 3 schema-valid annotations, 141s |

And on the whole book (one 82,383-char chapter, 4.5x that page):

| budget | outcome |
|---|---|
| 16000 | `StructuredOutputError`, no tool call |
| **32000** | **`Rendered 5 / Skipped 0`**, 21,214 in / 7,660 out, 3m09s |

⚠ The successful run spent **fewer** output tokens (7,660) than the 8192 that failed, so
this is not simply a payload that did not fit. `DEFAULT_MAX_OUTPUT_TOKENS` is set to the
value measured working end to end, not to an isolated threshold.

`nvidia/nemotron-3.5-lightning:free` (3 annotations) and
`nvidia/nemotron-3-super-120b-a12b:free` (1 annotation, 84s) both emit a schema-valid
payload. ⚠ "Emits a payload" is not "is good enough" — one annotation for a page asked for
five is a working transport and a weak generator. `nex-agi/nex-n2.5-pro:free` returns no choice; `google/gemma-4-31b-it:free` was
rate-limited. Budget is `DEFAULT_MAX_OUTPUT_TOKENS`, overridable with
`HALFBLOOD_MAX_OUTPUT_TOKENS`. Raising it costs nothing — providers bill actual output
tokens and this is only an upper bound.

⚠ **The lesson is bigger than the constant.** A measurement across two models and three
modes was real, and the conclusion drawn from it named the wrong cause, because the one
variable that mattered was never varied. Vary the local knob before blaming the vendor.

⛔ `.env` still holds a **zero-spend key on purpose**: free returns 200, paid returns 403.
Do not "fix" the 403 by swapping in a paid key — ask first.

**Measured 2026-09-08, and no longer a risk in the ledger — it is a number.**
`_resolve_bounded` searches many leaf blocks where there was one chapter search, so a quote
unique inside a chapter can collide across blocks. It fails closed (`AMBIGUOUS`, never a
first hit), so it cannot misplace a note; what it costs is notes the reader does not get.
Replaying both frozen plans: `plan-snape.json` places 5/8 with three `missing_target` skips,
`plan-editor.json` places 6/8 with **two `ambiguous_target` skips**. **Two of sixteen — 12.5%
— are lost to collisions.** Gate G6 pins that ceiling together with the placement floor, so
neither number can move without the suite saying so.

## Current placement work

For changes to quote resolution, rendering, or public guarantees, read
`docs/placement-contract.md` first. The supported seam is `halfblood.placement`
and the processors' `render_plan`; legacy prefix helpers are outside it.
Run `scripts/benchmark_placement.py` to check the guarantee, not a render count.
`HANDOFF.md` points to the latest evidence packet. Historical measurements below
are not release gates: re-run their commands before carrying them forward.

## MISSION

You are picking up a working but early-stage Python project called **Half-Blood Prince**. It takes any book (PDF or EPUB) and produces a new copy with AI-generated margin annotations in the style of Snape's scrawled-in Potions textbook from Harry Potter — terse corrections, sardonic commentary, shortcuts, warnings, and invented techniques, rendered in handwriting-style text with ink colors, rotation jitter, and connector arrows.

Your job is to **adversarially review, test, validate the tech stack, and improve this project in every way you can find**. This is not a maintenance task — treat it as a thorough code review by a hostile but constructive senior engineer who wants to ship this as a real product.

---

## HOW THE PIPELINE WORKS

```
PDF/EPUB in
    → DocumentProcessor.load() / EpubProcessor.load()
        → list[PageContent] (page_number, text, width, height)
    → AnnotationGenerator.generate_for_document()
        → pages are generated in concurrent waves (ThreadPoolExecutor,
          `concurrency` default 3, `config.py`) — not one page at a time
        → for each page: build system+user prompt → call the configured provider;
          structured-output mode is negotiated per provider (`generation/structured_output.py`),
          payloads re-validated via Pydantic → AnnotationPlan
    → DocumentProcessor.render_plan() / EpubProcessor.render_plan()   ← what the CLI runs
        → complete normalized quotes resolved by halfblood.placement; ambiguity and misses refuse
        → margin notes drawn as VECTOR DRAWINGS via fitz.Shape with morph rotation
        → bowed connector arrows from notes to target passages
        → this path emits NO native PDF annotation objects (asserted in tests/test_cli_end_to_end.py)
      Legacy v1 render_annotations()/add_margin_note()/_mark_target() (native PDF
      underline/highlight annots) still exists but is NOT the CLI path — verify before probing it.
    → annotated PDF/EPUB out
```

**Key architectural decisions:**

1. **A thin provider seam over raw `httpx`, no vendor SDK and no LangChain.** The task is a single stateless structured-output call per page — no chains, no agents, no retrieval. Everything goes through `src/halfblood/generation/providers/` (`anthropic.py` and `openai_compat.py`, both direct `httpx`), selected via `generation/registry.py`. **No LLM vendor package is a dependency at all** — generation *and* the eval judge share the seam, and `pyproject.toml` declares no `anthropic`/`openai` SDK in any group (pinned by `tests/test_packaging.py` and `tests/test_judge_provider_seam.py`). That seam is also the **sole retry owner** (see §4.6 of the architecture spec and the High Priority note below).

2. **Structured output is negotiated per provider, not hard-coded.** `generation/schema.py` derives one canonical Draft 2020-12 schema from the Pydantic `RecordAnnotations` model; `generation/structured_output.py` pins how each provider is asked to honour it (tool call, JSON-schema response format, or prompted). Returned payloads are always re-validated locally — provider-side validation is treated as an aid, never as a guarantee.

3. **PyMuPDF (`fitz`) for everything PDF.** It uniquely provides text extraction with `search_for`, native PDF annotation objects, AND `Shape.insert_text(..., morph=...)` for per-glyph affine transforms (the rotation jitter).

4. **Context windowing for cross-page continuity.** Each page gets the previous page's last 500 chars, next page's first 500 chars, and a rolling list of INVENTION/WARNING notes from prior pages. This is re-injected into the prompt — no conversation history, no state.

5. **Whole-quote placement.** The supported renderer uses `resolve_pdf_quote` and
   `resolve_epub_quote`. Prefix recovery, case folding, and first-hit fallbacks
   remain only in legacy helpers; they must not enter the supported path.
   A shortened prefix was observed anchoring “fifty milligrams” onto “five
   milligrams”; the regression is in `tests/test_placement_rendering.py`.

---

## TECH STACK TO VALIDATE

Review whether each dependency is the right choice. Consider alternatives and document your reasoning.

| Dependency | Purpose | Questions to investigate |
|---|---|---|
| **PyMuPDF (fitz)** | PDF text extraction, annotation rendering, Shape-based handwriting | Is this the best choice? Compare with reportlab, pypdf, pdfplumber. Key requirement: `morph` parameter on `insert_text` for rotation. |
| **Raw httpx provider seam** (no Anthropic SDK — none is installed; `pyproject.toml` declares no vendor SDK, pinned by tests/test_packaging.py) | Direct LLM calls with negotiated structured output | Is the thin httpx seam right vs. adding an SDK? (Current answer: yes — one stateless call per page, seam is the sole retry owner; validate.) |
| **Pydantic v2** | Data validation for Annotation models | Any issues with v2 vs v1? Serialization performance? |
| **Click** | CLI framework | vs. Typer? Click is more established but Typer has better type hints. |
| **ebooklib** | EPUB read/write | Known bugs (toc uid=None). Are there better EPUB libraries? |
| **BeautifulSoup + lxml** | EPUB chapter HTML manipulation | vs. lxml directly? Performance? |
| **Rich** | Progress bars and table output | Any concerns? |

---

## KNOWN ISSUES FROM PRIOR CODE REVIEW

These were found during an adversarial review. Critical and High bugs were fixed. Medium and Low bugs remain. **Find more.**

### Fixed (verify the fixes are correct):

1. **CLI interface mismatch** — CLI was built by an agent that couldn't see actual module implementations. Method signatures, constructor args, and attribute names were all wrong. Rewritten entirely.

2. **Null bytes in cli.py** — Write tool appended 7182 null bytes causing SyntaxError. Stripped.

3. **Eval harness 3 stacked critical bugs** — (a) `PageContent(title=tc.title)` → `title` doesn't exist, needs `width`/`height`. (b) `generate_page` → should be `generate_for_page`. (c) Wrong argument types (object instead of string). All silently swallowed by `except Exception`. Fixed.

4. **Unsafe `next()` without default** — `next(b for b in response.content if b.type == "tool_use")` would raise StopIteration. Fixed with `next((...), None)` + None check.

5. **Connector arrows reversed** — Left-margin arrows pointed to right edge and vice versa. Swapped.

6. **API key error surfacing as raw traceback** — Now caught and wrapped in `click.ClickException`.

7. **Model name mismatch** — eval harness used a different model string than the rest of the codebase. Fixed.

8. **Web-preview target matching bounded** — `_find_target_span` now limits target length before constructing its flexible regex, preventing the previously reported pathological-input concern.

9. **PDF input validation** — PDF paths are checked for the expected magic bytes before PyMuPDF opens them, so mislabeled files receive a useful error.

10. **Font fallback logging** — the missing-font fallback is now quiet enough for normal runs rather than emitting the former noisy warning.

### Unfixed (Medium/Low — fix these):

11. ~~Retry ownership during the provider transition~~ **RESOLVED.** There is no SDK to retry: all providers go through the direct-httpx seam (`generation/providers/`), and that seam is now the **sole retry owner** (backoff/retry lives there). Do not add a second retry layer anywhere else.

12. ~~Sequential-only page generation~~ **FIXED — concurrency shipped.** Pages are generated in concurrent waves via `ThreadPoolExecutor(max_workers=concurrency)` (`annotation_generator.py`, default `concurrency: 3` in `config.py`, tunable via `HALFBLOOD_CONCURRENCY`). Remaining question is rate-limit tuning for very large books, not the absence of concurrency.

13. **Legacy `_search_variants` can guess a passage.** It is not the supported
    `render_plan` placement seam. Keep compatibility helpers outside the public
    guarantee; do not use their recovery rate as evidence of correct placement.

14. ~~Overlapping margin notes with no layout avoidance~~ **BUILT** (`layout/page_solver.py`): candidate placement runs pairwise conflict detection (`_candidate_conflicts`, conflict-mask pruning) so overlapping margin notes are resolved at layout time rather than drawn on top of each other.

15. ~~**EPUB processor `_locate_text` only searches within single text nodes.**~~ **FIXED — do not rebuild this.** The v2 render path resolves targets across inline tag boundaries via `documents/epub.py:locate_across_nodes`, wired at `epub_processor.py` phase 1 and phase 4. Verified directly: targets spanning `text → <em> → text`, `<em> → text → <strong> → text`, and `<strong> → text` all resolve. The legacy `_locate_text` still exists but is no longer the v2 path. This entry stayed stale long enough to cost a full wasted investigation cycle — **probe HEAD with a real command before believing any documented gap in this file.**

16. **Historical tolerance experiments are superseded for supported placement.**
    Case drift, omitted punctuation, paraphrase, and OCR repairs are now refused
    unless the full quote agrees under the documented normalization. Historical
    recovery percentages in `docs/decisions/verbatim-quoting-prompt-vs-matcher.md`
    describe the former path, not the current placement contract.

---

## TESTING INSTRUCTIONS

### Run existing tests (no API key needed):

```bash
uv venv && uv pip install -e ".[dev]"   # or: pip install -e ".[dev]"
.venv/bin/python -m pytest tests/ -q
```

All tests must pass in a plain non-tty shell too. They use mocked/stub providers; the offline suite needs no API credentials. Trust the current test run, not historical counts.

### Offline end-to-end smoke (no API key needed):

```bash
halfblood annotate tests/fixtures/potions_textbook.pdf -o /tmp/out.pdf --provider stub --force
python -c "import json; r=json.load(open('/tmp/out.pdf.report.json')); print(r['pages_annotated'], r['failed_pages'])"
```

Every `annotate` run also streams a checkpoint to `<output>.plan.json`; if a run dies partway, rerun with `--resume-from <output>.plan.json` and finished pages are not re-billed. Failed pages are named in `<output>.report.json`.

### Run the eval harness (needs API key):

```bash
export ANTHROPIC_API_KEY=sk-ant-...
python eval/eval_harness.py --list                                  # just list test cases
python eval/eval_harness.py --generator-model <gen> --judge-model <judge>
```

The generator and judge must be different model families (self-judging is refused unless `--allow-self-judge` is passed).

### End-to-end test (needs API key + a PDF):

```bash
# Use the bundled test fixture
halfblood annotate tests/fixtures/potions_textbook.pdf -o /tmp/annotated.pdf --pages 1-3
halfblood preview tests/fixtures/potions_textbook.pdf --pages 2-3

# EPUB (need an EPUB file)
halfblood annotate book.epub -o annotated.epub --pages 1-5
```

### What to test manually:

1. **Font rendering** — With and without `fonts/CaveatBrush-Regular.ttf`. Verify fallback to Helvetica-Oblique works and notes are still readable.
2. **Long books** — Try a 50+ page PDF. Watch for: rate limiting, memory usage, annotation quality degradation on later pages.
3. **Dense text** — A page with very small margins. Do annotations overflow the page? Do connectors cross other annotations?
4. **EPUB roundtrip** — `load()` → `render_annotations()` → re-open in an EPUB reader. Verify CSS doesn't break the reader.
5. **Web preview** — Generate a `preview.html` and open in browser. Check: dark mode toggle, page navigation, connector SVGs, responsive layout below 1000px.
6. **Custom personas** — Try a non-Snape persona. Does it actually change the voice? Does annotation quality hold?

---

## IMPROVEMENT AREAS

### Current priorities

- Preserve whole-quote refusal and input-file safety when changing the pipeline.
- Verify all four outcomes and exact ranges with the offline benchmark.
- Keep failed or omitted drawing operations visible in `RenderReport`.
- Measure routing quality separately from quote resolution. A resolved quote
  does not promise a collision-free connector or a placeable margin note.
- Independent frontier-model quality evaluation requires working credentials.
  A stub or self-judge run checks wiring only.

Observed shipped mechanisms (probe before changing): concurrent generation
waves, collision-aware note layout, sole-httpx retries, `--dry-run`, and per-page
progress. They are not missing features.

---

## CODE QUALITY CHECKLIST

When reviewing, check each module for:

- [ ] **Type annotations** — Are all public method signatures fully typed? Any `Any` that should be specific?
- [ ] **Error handling** — Are exceptions caught at the right level? Any bare `except Exception`? (Known: eval harness has intentional broad catches at the case boundary.)
- [ ] **Logging** — Is the logging level appropriate? Are log messages actionable? (Known: font fallback WARNING is noisy.)
- [ ] **Docstrings** — Are all public classes and methods documented? Are the docstrings accurate after the bug fixes?
- [ ] **Test coverage** — What's not tested? (The former "EPUB processor and web preview have zero tests" note is **stale**: `tests/test_epub_processor.py`, `tests/test_epub_render_report.py` and `tests/test_web_preview.py` all exist. Verify with `ls tests/` before believing any coverage claim here. Remaining real gap: the eval harness's real-pipeline path is only tested manually.)
- [ ] **Import hygiene** — Any circular imports? Any unnecessary imports?
- [ ] **Constants** — Any magic numbers that should be named constants? (Known: 500-char context window, 8-item running_notes cap.)
- [ ] **Thread safety** — `random.Random` instance per `DocumentProcessor` is fine, but is there shared mutable state elsewhere?
- [ ] **Memory** — For very large PDFs, does `load()` hold the entire `fitz.Document` open unnecessarily? (It doesn't — it closes in a `finally` block.)
- [ ] **Security** — `web_preview.py` uses `html.escape` for all user-provided text. Verify no XSS vectors exist.

---

## COMMANDS

```bash
# Install
pip install -e ".[dev]"

# The gate (ruff -> mypy -> pytest, exact selectors) is spelled ONCE, under
# "Build & verify" at the top of this file. Do not lint or test from here.

# Import smoke
python -c "from halfblood.cli import main; print('imports ok')"

# Quick smoke test (no API key needed)
python -c "
from halfblood.document_processor import DocumentProcessor
dp = DocumentProcessor()
pages = dp.load('tests/fixtures/potions_textbook.pdf')
print(f'{len(pages)} pages loaded')
for p in pages:
    print(f'  Page {p.page_number}: {len(p.text)} chars')
"

# Generate annotations (needs API key)
export ANTHROPIC_API_KEY=sk-ant-...
halfblood preview tests/fixtures/potions_textbook.pdf --pages 2-3

# Full annotate
halfblood annotate tests/fixtures/potions_textbook.pdf -o /tmp/annotated.pdf

# Eval
python eval/eval_harness.py --list
python eval/eval_harness.py
```

---

## INSPIRATION

This project is a riff on [Riddle](https://github.com/MaximeRivest/riddle) (a Rust app for the reMarkable tablet that creates a Tom Riddle diary experience) and the "Half-Blood Prince" gag from Harry Potter. The core question: what if any book could have its own Prince in the margins?

---

## WHAT SUCCESS LOOKS LIKE

After your session, this project should:

1. Have all Medium/Low bugs fixed
2. Preserve the direct-httpx provider transport as the sole retry owner
3. Have test coverage for EPUB processor and web preview
4. Have linting configured (ruff + mypy)
5. Have a validated tech stack with documented reasoning
6. Have any new bugs you find fixed
7. Have improved prompt engineering if you find weaknesses in annotation quality
8. Be ready to push to GitHub as a v0.1.0
