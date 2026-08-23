# Half-Blood Prince — Claude Code Session Handoff

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
        → targets resolved by a tolerance ladder (_resolve_annotation_to_anchor), never lone-word anchors
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

5. **Progressive text matching.** LLM `target_text` rarely matches the PDF text layer byte-for-byte. `_search_variants()` tries: exact → 8-word prefix → 5-word → 3-word → longest single word. Plus whitespace/smart-quote normalization.

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

13. **`_search_variants` can match the wrong passage.** If the longest single word in `target_text` appears multiple times on the page, the annotation anchors to the first occurrence, which may be wrong. No disambiguation.

14. ~~Overlapping margin notes with no layout avoidance~~ **BUILT** (`layout/page_solver.py`): candidate placement runs pairwise conflict detection (`_candidate_conflicts`, conflict-mask pruning) so overlapping margin notes are resolved at layout time rather than drawn on top of each other.

15. ~~**EPUB processor `_locate_text` only searches within single text nodes.**~~ **FIXED — do not rebuild this.** The v2 render path resolves targets across inline tag boundaries via `documents/epub.py:locate_across_nodes`, wired at `epub_processor.py` phase 1 and phase 4. Verified directly: targets spanning `text → <em> → text`, `<em> → text → <strong> → text`, and `<strong> → text` all resolve. The legacy `_locate_text` still exists but is no longer the v2 path. This entry stayed stale long enough to cost a full wasted investigation cycle — **probe HEAD with a real command before believing any documented gap in this file.**

16. **Non-verbatim model quoting — partly mitigated.** The model does not reliably quote character-for-character, which is now the main source of dropped EPUB annotations. `documents/matching.py:MatchTolerance` walks EXACT → CASE_INSENSITIVE → PUNCTUATION_ELASTIC in `locate_across_nodes`, recovering case drift and quote-mark drift with exact semantics and no similarity threshold. Measured on a real book: **88% → 96% of annotations rendered**, across two independent generation runs. The residue is genuine paraphrase (dropped words, elided dialogue attributions), which is **deliberately not recovered** — fuzzy matching would anchor a note to the wrong words, and the reader cannot detect that. Prompt hardening was tried against this residue and **measurably did not help** across three runs, so the prompt was left alone — see `docs/decisions/verbatim-quoting-prompt-vs-matcher.md`.

---

## TESTING INSTRUCTIONS

### Run existing tests (no API key needed):

```bash
uv venv && uv pip install -e ".[dev]"   # or: pip install -e ".[dev]"
.venv/bin/python -m pytest tests/ -q
```

All tests must pass in a plain non-tty shell too (`env -i PATH="$PATH" HOME="$HOME" .venv/bin/python -m pytest -q`). They use mocked/stub providers — no real API calls. Current count: **1,861 tests, all passing** (verify with the command above; this file's counts go stale — trust the run).

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

### High Priority

- **Keep retry ownership singular during the provider transition.** The SDK retries currently cover transient responses; per architecture spec §4.6, Phase 1's httpx provider transport becomes the **sole retry owner**. Do not wrap the SDK in another retry layer meanwhile.
- **Add async page processing** with a configurable concurrency limit (default 3-5). Massive speedup on long books.
- **Add annotation collision detection** in `document_processor.py`. Track occupied margin regions per page and shift notes that would overlap.
- **Add proper error messages** when PyMuPDF can't open a file (validate magic bytes before passing to `fitz.open`).
- **Add a `--dry-run` flag** to the CLI that generates annotations but doesn't render, outputting the `AnnotationPlan` as JSON. Useful for debugging persona/prompt issues without waiting for rendering.
- **Add streaming progress** — currently `generate_for_document` blocks until all pages are done. Show per-page progress as annotations come back.

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

# Run tests
pytest tests/ -v

# Lint (if you add ruff/mypy)
ruff check src/ tests/ eval/
mypy src/halfblood/

# Type check
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
2. Preserve the SDK's existing retries until Phase 1's httpx provider transport is the **sole retry owner**, with no duplicate retry layer
3. Have test coverage for EPUB processor and web preview
4. Have linting configured (ruff + mypy)
5. Have a validated tech stack with documented reasoning
6. Have any new bugs you find fixed
7. Have improved prompt engineering if you find weaknesses in annotation quality
8. Be ready to push to GitHub as a v0.1.0
