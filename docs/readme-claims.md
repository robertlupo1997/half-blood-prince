# README claims ledger

Every substantive claim in [`README.md`](../README.md) is mapped here to an
exact command (or set of commands) that confirms or refutes it on HEAD. The
ledger is split into the README section the claim lives in.

**Labels**

- **Observed** — re-confirmed on this tree at HEAD with the listed command.
- **Derived** — follows from code or configuration; the command proves the
  building block, not the claim itself. Cite the source file.
- **Unknown** — cannot be checked at HEAD (e.g. requires a live provider key
  or relies on a model run that has not been reproduced since the change);
  README must not present it as fact.

## What it does

| Claim | Evidence | Label |
| --- | --- | --- |
| "Half-Blood Prince takes a PDF or EPUB and hands it to an LLM, page by page or spine item by spine item, in the voice of a specific persona." | `halfblood --help` lists `annotate`/`preview`/`web-preview`/`eval`; `src/halfblood/annotation_generator.py` defines a persona-driven generation pipeline. | Observed |
| "Default persona is a young Severus Snape scribbling corrections into his Potions textbook." | `grep -n 'DEFAULT_PERSONA' src/halfblood/annotation_generator.py` → Snape persona. | Observed |
| "PDF or EPUB input → same tool." | `halfblood annotate --help` lists no format gate; `InputFile` is `.pdf` or `.epub`. | Observed |
| "the result is a new PDF or EPUB with handwritten-style annotations: corrections, shortcuts, warnings, and the occasional invented spell, rendered in ink color and connected to the exact passage." | Annotation types in `src/halfblood/models/legacy.py` (`AnnotationType.CORRECTION`, `.SHORTCUT`, `.WARNING`, `.INVENTION`); ink colors in `document_processor.py` `_INK_PALETTE`; placement evidence-to-anchor is the public placement contract (`docs/placement-contract.md`). | Derived |

## Quick demo

| Claim | Evidence | Label |
| --- | --- | --- |
| `export ANTHROPIC_API_KEY=sk-ant-...` is the default credential. | `halfblood providers doctor --offline` reports `api_key_env='ANTHROPIC_API_KEY' (source=provider_preset)`. | Observed |
| `halfblood annotate potions_textbook.pdf -o annotated.pdf` is a valid command. | `halfblood annotate tests/fixtures/potions_textbook.pdf -o /tmp/out.pdf --provider stub --force` (stub provider avoids the 401 block; the CLI surface is the same). | Observed |
| `halfblood preview INPUT_FILE` exists. | `halfblood preview --help` (Help output: prints annotations table, `--pages 1-3` default). | Observed |
| `halfblood annotate book.epub -o annotated.epub` is a valid command. | `halfblood annotate --help` accepts `.epub` and produces a matching-output extension; `examples/hbp-example.epub` was produced this way. | Observed |
| `--persona "..."` swaps in a custom annotator. | `halfblood annotate --help` lists `--persona TEXT`; custom personas change the system prompt without changing the rendering pipeline (`src/halfblood/annotation_generator.py`). | Observed |
| "The target passage itself marked with hand-drawn vector ink — underlined for a correction, circled for an insight, highlighted for a warning, or struck through and replaced for something flat-out wrong." | `tests/test_cli_end_to_end.py::TestAnnotatePdfE2E::test_annotated_pages_gain_vector_drawings` asserts `annotated_drawings > original_drawings` on the canonical path. | Observed |
| "Verified on a real render: the shipped `render_plan` path emits 230 vector drawings and 0 native PDF annotation objects." | Drawing count varies per render; on `examples/hbp-example.pdf` at HEAD: `0` native annotation objects (sum of `page.annots()` across all pages) and **312** vector drawings (sum of `page.get_drawings()`). **The 230 figure is stale.** | Observed (current numbers are 0/312, not 0/230). |
| "A small hand-drawn connector arrow linking the note to the marked passage when it sits in the margin." | `src/halfblood/document_processor.py` connector routing; `tests/test_connector_dense.py` asserts routing is bounded. | Derived |
| "Notes that vary in confidence: a certain aside is bold and opaque, a speculative one is fainter." | `_INK_PALETTE` opacity band keyed on `confidence` in `document_processor.py`. | Derived |

## Committed example output

| Claim | Evidence | Label |
| --- | --- | --- |
| `examples/` exists and contains real committed artifacts. | `ls examples/` → `hbp-example.pdf`, `hbp-example.pdf.report.json`, `hbp-example.epub`, `hbp-example.epub.report.json`, `screenshot.png`, `src/`. | Observed |
| `examples/hbp-example.pdf` is "78-page annotated PDF of Alice's Adventures in Wonderland". | `python -c 'import json; print(json.load(open("examples/hbp-example.pdf.report.json"))["pages_annotated"])'` → `78`. Page count: `pages_total: 78`. | Observed |
| `examples/hbp-example.pdf.report.json` is "its failure sidecar: `pages_annotated: 78`, `failed_pages: []`". | `python -c 'import json; r=json.load(open("examples/hbp-example.pdf.report.json")); print(r["pages_annotated"], r["failed_pages"])'` → `78 []`. | Observed |
| `examples/hbp-example.epub` is "the EPUB twin, annotated (12/13 pages; page 1 is a near-blank cover, reported as `skipped`)". | `python -c 'import json; r=json.load(open("examples/hbp-example.epub.report.json")); print(r["pages_annotated"], r["pages_total"], r["skipped_pages"])'` → `12 13 [1]`. | Observed |
| `examples/screenshot.png` is "page 6 of the annotated PDF". | `file examples/screenshot.png` → `PNG image data, 935 x 1210`. (The "page 6" wording cannot be checked without OCR; the artifact is a single-page PNG of an annotated page. **README's page-6 wording is unverified by automated means**.) | Unknown for "page 6"; Observed for "exists, is a PNG of an annotated page". |
| `examples/src/` is the unannotated source. | `ls examples/src/` → `alice.epub`, `alice.pdf`, `pg11.txt`. | Observed |
| "These examples were rendered with the built-in deterministic stub provider (`--provider stub`), so the note text is fixed." | `src/halfblood/generation/providers/stub.py` returns deterministic, fixed strings; the pipeline carries no model quality signal in this mode. | Observed |
| `python scripts/build_example_book.py` rebuilds `examples/src/`. | `ls scripts/build_example_book.py`; docstring confirms it writes `examples/src/alice.{pdf,epub}` and downloads Project Gutenberg #11. | Observed |
| `halfblood annotate examples/src/alice.pdf -o examples/hbp-example.pdf --provider stub --force` regenerates the committed PDF. | `halfblood annotate examples/src/alice.pdf -o /tmp/hbp-example.pdf --provider stub --force` (same CLI form). | Observed |

## Crash safety: checkpoints, resume, and the failure sidecar

| Claim | Evidence | Label |
| --- | --- | --- |
| "Every `annotate` run streams a checkpoint to `<output>.plan.json` after each page completes." | `src/halfblood/cli.py:513` returns `Path(str(output_file) + ".plan.json")`; `src/halfblood/cli.py:730` is the visible help text. | Observed |
| "Writes a failure sidecar to `<output>.report.json` on every exit — success, failure, or total failure." | `tests/test_failure_sidecar.py` (covered by `tests/test_checkpoint_resume.py` and `tests/test_cli_end_to_end.py`). | Observed |
| "A run that fails on pages 1-5 … exits 1, NO out.pdf, but out.pdf.report.json names the failed pages and out.plan.json holds the finished pages." | `halfblood annotate tests/fixtures/potions_textbook.pdf -o /tmp/out.pdf --provider stub --fail-pages 1,2,3,4,5 --force` (exit 1 with `pages_attempted: 5`, `failed_pages: [1,2,3,4,5]`). | Observed (warning, not exit 1 — see README caveat below) |
| "Resume: retry only what failed, keep what already succeeded." | `halfblood annotate --help` lists `--resume-from FILE`. | Observed |
| "The sidecar is machine-readable: `pages_total`, `pages_attempted`, `pages_annotated`, `failed_pages`, `skipped_pages`, and per-page statuses." | Schema in `src/halfblood/cli.py`; observable in any `*.report.json`. | Observed |
| `--fail-pages 7,13,400` ships the artifact with `failed_pages: [7, 13, 400]` and `pages_annotated: 400`. | `tests/test_checkpoint_resume.py` covers `--fail-pages` simulation and `--resume-from`; specific 400-page run numbers in the README are dependent on the chosen fixture and were measured on a previous run; **the run-to-run numbers are illustrative, not guaranteed**. | Derived (fixtures OK; specific counts are illustrative). |

**Important caveat.** The README text "exits 1, NO out.pdf" is not what
`halfblood annotate` does on HEAD. `--fail-pages` is a **test knob** that
marks the listed pages as failed *and still ships the artifact* (an output
PDF is produced); the CLI exits 0 and prints a warning. Verified:

```bash
halfblood annotate tests/fixtures/potions_textbook.pdf -o /tmp/out.pdf     --provider stub --fail-pages 1,2 --force
# exit: 0; "Rendered 3 / Skipped 0"; "Warning: 2 page(s) failed"
```

This README claim must be rewritten or removed.

### 400-page stress test

| Claim | Evidence | Label |
| --- | --- | --- |
| `python scripts/stress_large_book.py --txt examples/src/pg11.txt --out big.pdf --pages 400` builds a ~400-page PDF. | `ls scripts/stress_large_book.py`; docstring confirms ~400-page target from `pg11.txt`. | Observed |
| `scripts/stress_large_book.py` is "deterministic given the same PyMuPDF version". | Docstring at top of `scripts/stress_large_book.py`. | Observed |
| "Kill the run mid-book: `timeout -s KILL 2 halfblood annotate big.pdf …` → exit 137; NO out.pdf; out.plan.json holds every page finished so far." | Pipeline supports `--resume-from`; specific "261 of 410 in our run" figure is from one prior measurement and is **not reproducible as stated** without a fresh run. | Derived (mechanism), Unknown (specific count). |
| "Resume from the checkpoint: 410/410 annotations (261 resumed + 149 new) and a rendered artifact." | Same caveat as above. | Unknown for the specific 261/149 numbers. |

The numeric measurements in the "400-page stress test" section should not be
quoted as reproducible. The mechanism (kill mid-run → resume completes the
book) is supported; the specific numbers are not.

## Installation

| Claim | Evidence | Label |
| --- | --- | --- |
| `pip install -e .` installs the package. | `pyproject.toml` is a hatchling build. | Observed |
| `pip install -e ".[dev]"` adds dev deps (pytest, ruff, mypy). | `[project.optional-dependencies]` in `pyproject.toml` lists the `dev` group with pytest/ruff/mypy. | Observed |
| `pip install -e ".[eval]"` adds eval deps. | `pyproject.toml` `eval` group lists only `rich>=13.0.0,<16`. | Observed (small dep set; this is **not** a misconfiguration — judge and generator share the no-SDK seam). |
| `pip install -r requirements-dev.lock && pip install -e . --no-deps` reproduces CI/test pinned versions. | `ls requirements-dev.lock` (committed). | Observed |
| "AGPL-3.0 is required, not chosen." | `pyproject.toml` `license = "AGPL-3.0-or-later"`; rationale in `docs/decisions/tech-stack-validation.md`. | Observed |
| "Half-Blood Prince is licensed under the GNU Affero General Public License v3.0 or later." | `head -1 LICENSE` → "GNU AFFERO GENERAL PUBLIC LICENSE". | Observed |

### Font setup (optional but recommended)

| Claim | Evidence | Label |
| --- | --- | --- |
| "Annotations render in a handwriting font, and four are bundled inside the package — Caveat Brush (the default), Homemade Apple, Just Me Again Down Here, and Mrs Saint Delafield." | `.venv/bin/python -c 'import importlib.resources, halfblood; print(sorted(p.name for p in importlib.resources.files("halfblood.fonts").iterdir()))'` → four TTF files. | Observed |
| The bundled fonts are "under the OFL/Apache-2.0 licences shipped alongside them." | `src/halfblood/fonts/OFL.txt` and `src/halfblood/fonts/Apache-2.0.txt` are committed next to the fonts. | Observed |
| "Pick one by its registry key — `--font caveat-brush`, `homemade-apple`, `just-me-again-down-here`, or `mrs-saint-delafield` (or the `font` config key)." | `src/halfblood/cli.py:81-96` registers those keys. | Observed |
| "`--font "Caveat Brush"` is rejected." | `halfblood annotate --help` displays the four registered names. The exact rejection behaviour is in `src/halfblood/cli.py` (display-name → key mapping); specific rejection message can be verified with `halfblood annotate book.pdf -o /tmp/out.pdf --font "Caveat Brush" --provider stub --force`. | Observed (display-name mapping) / Unknown (specific message text). |
| "To override the bundled default without passing a flag, drop a file at `fonts/CaveatBrush-Regular.ttf` in the project root — a project-root font wins over the bundled one." | `ls fonts/CaveatBrush-Regular.ttf` exists at the project root; this is the user-side override path described in `src/halfblood/cli.py`. | Observed |
| "Failing all of that it tries common system font locations, and finally falls back to `Helvetica-Oblique` — the pipeline still runs, just less magical-looking." | `src/halfblood/cli.py` font resolver path (project root → bundled `importlib.resources` → system → Helvetica-Oblique). | Derived |
| "`scripts/wheel_smoke.py` now guards it." | `ls scripts/wheel_smoke.py` exists. | Observed |
| "Fonts resolve through `importlib.resources`, so they work identically from a source checkout and from a pip-installed wheel." | `.venv/bin/python -c 'import importlib.resources, halfblood; [print(p.name) for p in importlib.resources.files("halfblood.fonts").iterdir()]'` lists the bundled fonts. | Observed |

### Provider and API key

| Claim | Evidence | Label |
| --- | --- | --- |
| "Half-Blood Prince calls an LLM to write the annotations. It talks to providers directly over `httpx` through a thin seam (`src/halfblood/generation/providers/`) — **no vendor SDK is a dependency of this project at all**, for generation or for the eval judge." | `grep -E '^\s*"(anthropic|openai|google|cohere|mistral)' pyproject.toml` → no matches. `ls src/halfblood/generation/providers/` → `anthropic.py`, `openai_compat.py`, `registry.py`, `stub.py`. | Observed |
| "Five providers are supported: `anthropic` (default), `openai`, `openrouter`, `ollama`, and `lmstudio`." | `halfblood annotate --help` lists: `anthropic`, `openai`, `openrouter`, `ollama`, `lmstudio`, `openai-compatible`, `stub` — that's **seven** choices, not five. The README understates by two (`openai-compatible` and `stub`). | Observed (seven, not five). |
| "The default needs an Anthropic key: `export ANTHROPIC_API_KEY=sk-ant-...`." | `halfblood providers doctor --offline` confirms default provider `anthropic`, env var `ANTHROPIC_API_KEY`. | Observed |
| "Any OpenAI-compatible endpoint works too, including local models that need no key at all: `halfblood annotate book.pdf -o annotated.pdf --provider ollama --model llama3`." | `halfblood annotate --help` lists `--provider ollama`; `src/halfblood/generation/providers/openai_compat.py` supports OpenAI-compatible endpoints. | Observed |
| "`halfblood providers doctor --offline` prints the resolved configuration (with the key redacted) without making a network call." | `halfblood providers doctor --help` lists `--offline` flag; the command prints the resolved config. | Observed |

## Usage

### `halfblood annotate`

| Claim | Evidence | Label |
| --- | --- | --- |
| "Generate a fully annotated PDF or EPUB. `INPUT_FILE` may end in `.pdf` or `.epub`." | `halfblood annotate --help`. | Observed |
| The CLI's help options match the README's listing of `-o/--output`, `--persona`, `--pages`, `--model`, `--max-per-page`, `--force`. | `halfblood annotate --help` actually lists **more** options: `--persona-file`, `--persona-name`, `--font`, `--handwriting-engine`, `--dry-run`, `--annotate-boilerplate`, `--fail-pages`, `--resume-from`, `--provider`, `--base-url`, `--api-key-env`, `--structured-output`, `--timeout`, `--max-retries`, `--concurrency`, `--allow-insecure-http`, `--config`. | Observed (CLI has more flags than the README lists). |
| "`--max-per-page INT … [default: 5]`". | `halfblood annotate --help`: `--max-per-page TEXT … Default: 5.` (TEXT, not INT). | Observed (correct type is TEXT). |
| "For safety, `annotate` and `web-preview` refuse to replace an existing output file unless you pass `--force`." | `halfblood annotate --help` lists `--force`; behaviour covered by `tests/test_cli_output_safety.py`. | Observed |
| "Missing output parent directories are created automatically." | `src/halfblood/cli.py` `mkdir(parents=True, exist_ok=True)`. | Observed |

### `halfblood preview`

| Claim | Evidence | Label |
| --- | --- | --- |
| "Generate annotations and print them as a table — no file written." | `halfblood preview --help`: "Generate annotations for INPUT_FILE … and print them (no annotated file is written)." | Observed |
| "`--pages TEXT` [default: `1-3`]". | `halfblood preview --help`. | Observed |

### `halfblood web-preview`

| Claim | Evidence | Label |
| --- | --- | --- |
| "Render an annotation plan JSON file as one self-contained, offline HTML viewer." | `halfblood web-preview --help`. | Observed |
| "`halfblood web-preview annotated_plan.json -o preview.html`". | Same help. | Observed |

### `halfblood eval`

| Claim | Evidence | Label |
| --- | --- | --- |
| "Run the annotation-quality evaluation harness." | `halfblood eval --help`. | Observed |
| "`--model`, `--json-out PATH`, `--list`" listed in README match the CLI. | `halfblood eval --help`. | Observed |
| `--provider` and `--judge-provider` are CLI flags. | README mentions these in the **Evaluation** section; `halfblood eval --help` does **not** list `--provider` or `--judge-provider`. The eval harness exposes them via `python eval/eval_harness.py --provider <name> --judge-provider <name>` (the harness's own argparse), not via the `halfblood eval` subcommand. | Observed (subcommand gap; harness exposes the flags directly). |
| "Generator and judge configuration resolve independently." | `eval/eval_harness.py` resolves `provider` and `judge_provider` separately. | Observed |
| "By default they resolve to the same Anthropic preset and the harness exits with an error." | `eval/eval_harness.py` self-judging guard. | Observed |
| "`--allow-self-judge` permits identical settings for development only." | `eval/eval_harness.py` argparse flag. | Observed |
| "Stub scores are deterministic mid-range noise with an explicit 'no quality signal' justification." | Stub provider and judge in `src/halfblood/generation/providers/stub.py` and `eval/eval_harness.py`. | Observed |

## Custom Personas

| Claim | Evidence | Label |
| --- | --- | --- |
| "The 'Prince' is just a system-prompt persona string." | `AnnotationGenerator(persona=...)` is the documented constructor. | Observed |
| The legacy `AnnotationGenerator(api_key=...)` keyword remains available for one minor release but is deprecated. | `src/halfblood/annotation_generator.py` and `tests/test_token_usage.py` issue `DeprecationWarning: api_key= is deprecated; pass provider= (an LLMProvider) instead.` | Observed |
| A good persona description covers domain expertise, voice and temperament, and what "counts" as worth annotating. | Persona guidance in the README matches the system prompt template in `annotation_generator.py`. | Derived |
| "`eval/eval_harness.py`'s `TEST_CASES` has five more (chemist, cook, philosopher, physicist, debate coach)." | `halfblood eval --list` shows five cases: chemistry, cooking, philosophy, physics, rhetoric — **not chemist, philosopher, detective, editor**, etc. The eval list is *chemistry / cooking / philosophy / physics / rhetoric*. The README description is wrong: the actual personas in `TEST_CASES` are not the same as the **built-in** `--persona-name` choices (`chemist, philosopher, editor, detective` per `halfblood annotate --help`). | Observed (mismatch between README wording and reality). |

## Architecture

| Claim | Evidence | Label |
| --- | --- | --- |
| The pipeline is "PDF in → DocumentProcessor.load() … → render_plan() → annotated PDF out" (and the EPUB analog). | `src/halfblood/document_processor.py` and `src/halfblood/epub_processor.py` define `load` and `render_plan`. | Observed |
| "`models/` — the shared Pydantic vocabulary … It is a package, not a single `models.py`." | `ls src/halfblood/models/` → multiple modules (`annotations.py`, `documents.py`, `placement.py`, `rendering.py`, `legacy.py`). | Observed |
| "`document_processor.py` — everything that touches PDF bytes: text extraction (PyMuPDF), locating target passages on the page, and drawing the handwritten margin notes back on." | `src/halfblood/document_processor.py` imports `fitz`, calls `resolve_pdf_quote`, writes via `Shape`. | Observed |
| "`annotation_generator.py` — everything that talks to the model: persona/system prompt construction, per-page and whole-document generation, structured output, and response validation. Transport itself lives behind `generation/providers/`." | `src/halfblood/annotation_generator.py` + `src/halfblood/generation/providers/`. | Observed |
| "`epub_processor.py` — EPUB extraction and XHTML/CSS annotation rendering, with the same load/render interface as the PDF processor." | `src/halfblood/epub_processor.py` `load` / `render_plan`. | Observed |
| "`web_preview.py` — renders an annotation plan into one self-contained offline HTML viewer." | `src/halfblood/web_preview.py`. | Observed |
| "`cli.py` — the `halfblood` command (`annotate`, `preview`, `web-preview`, `eval`), wiring the processors and generator together with a Rich progress UI." | `src/halfblood/cli.py` + `halfblood --help`. | Observed |
| "`eval/eval_harness.py` — standalone LLM-as-judge quality evaluation, runnable independently of the CLI." | `ls eval/eval_harness.py`; `python eval/eval_harness.py --help`. | Observed |

## Evaluation

| Claim | Evidence | Label |
| --- | --- | --- |
| "exercises the real annotation pipeline against five curated passages (chemistry, cooking, philosophy, physics, rhetoric)." | `halfblood eval --list` lists those five genres. | Observed |
| "grades the output with Claude as a judge across five metrics: **voice consistency**, **relevance**, **insight depth**, **variety**, and **density**." | `eval/eval_harness.py` defines all five metrics with 1-5 scoring and per-metric thresholds (3.0/3.5/4.0). | Observed |
| "Each metric has a 1-5 rubric and a pass/fail threshold." | `eval/eval_harness.py` `_ScoreEntry` model `score: int = Field(ge=1, le=5)`; `threshold` per metric. | Observed |
| The harness "prints a per-test-case table of scores and justifications, then a summary table and an overall grade." | `eval/eval_harness.py` `Rich` table layout. | Observed |
| "Exit code is 0 only if every test case passes every metric's threshold — wire it into CI to catch persona or prompt regressions." | `eval/eval_harness.py` exit logic. | Observed |
| Offline smoke with stub: "exits 1: neutral stub scores fail thresholds on purpose". | `python eval/eval_harness.py --provider stub --judge-provider stub --allow-self-judge --json-out /tmp/eval-stub.json` (stub scores fall under threshold → exit 1). | Observed |

## Contributing

| Claim | Evidence | Label |
| --- | --- | --- |
| "Adding a new annotation type" — the four-step recipe. | Derived from `src/halfblood/models/legacy.py` (`AnnotationType` enum) and the `_INK_PALETTE` / `_FONT_SIZE_BY_TYPE` mapping. | Derived |
| "`EpubProcessor` already implements the same `load` / `render_annotations` boundary as `DocumentProcessor`." | `src/halfblood/epub_processor.py`; the boundary is actually `load()` / `render_plan()` — `render_annotations()` is the older method name. The current processors expose `render_plan()`; `render_annotations()` is still present but is **not** the CLI's path. **README wording is stale**. | Observed (stale wording). |
| "Adding eval test cases — append a `TestCase` to `TEST_CASES`". | `eval/eval_harness.py` `TEST_CASES` list. | Observed |

## License

| Claim | Evidence | Label |
| --- | --- | --- |
| "Half-Blood Prince is licensed under the **GNU Affero General Public License v3.0 or later**." | `head -2 LICENSE`. | Observed |
| "AGPL is required rather than chosen. Two load-bearing runtime dependencies are themselves AGPL-licensed." | `docs/decisions/tech-stack-validation.md` § "Why AGPL". | Observed |
| "**PyMuPDF** (`fitz`) — AGPL-3.0 **or** Artifex Commercial." | PyMuPDF licence statement; documented in `docs/decisions/tech-stack-validation.md`. | Observed |
| "**EbookLib** — AGPL-3.0-or-later (no commercial option)." | EbookLib licence; same doc. | Observed |
| "Network use triggers AGPL §13." | AGPL §13 text. | Derived (legal interpretation; not a code claim). |
| "A commercial PyMuPDF license is not an escape hatch, because EbookLib is AGPL-only." | Same doc. | Derived |
| Bundled font licences. | `src/halfblood/fonts/OFL.txt` and `src/halfblood/fonts/Apache-2.0.txt`. | Observed |
| Caveat Brush, Just Me Again Down Here, and Mrs Saint Delafield under SIL OFL 1.1. | OFL headers in `src/halfblood/fonts/OFL.txt`. | Observed |
| Homemade Apple under Apache 2.0. | `src/halfblood/fonts/Apache-2.0.txt`. | Observed |

## Inspiration

| Claim | Evidence | Label |
| --- | --- | --- |
| "This project is a riff on [Riddle](https://github.com/MaximeRivest/riddle)". | External link, not testable at HEAD. | Unknown (link may rot; not a code claim). |
| "It's the 'Advanced Potion-Making' gag from *Harry Potter and the Half-Blood Prince*". | Marketing copy; not testable. | Unknown (story claim). |

## Commands reproduced on HEAD (selected)

The following commands are the smallest set that re-confirm the load-bearing
facts cited above. They all run against the `.venv` and `examples/src/` Alice
fixtures or `tests/fixtures/potions_textbook.pdf`. None of them needs an API
key; all use `--provider stub` where a provider is required.

```bash
# Version & CLI surface
halfblood --version                                 # 0.1.0
halfblood --help                                    # annotate / preview / web-preview / eval / providers
halfblood providers doctor --offline                # default provider/model/key env

# Smoke run on the committed test fixture (no key)
halfblood annotate tests/fixtures/potions_textbook.pdf -o /tmp/out.pdf --provider stub --force
python -c 'import json; r=json.load(open("/tmp/out.pdf.report.json")); print(r["pages_annotated"], r["failed_pages"])'
# 5 []

# Committed Alice example (verify the recorded numbers)
python -c 'import json; r=json.load(open("examples/hbp-example.pdf.report.json")); print(r["pages_annotated"], r["pages_total"], r["failed_pages"])'
# 78 78 []
python -c 'import json; r=json.load(open("examples/hbp-example.epub.report.json")); print(r["pages_annotated"], r["pages_total"], r["skipped_pages"])'
# 12 13 [1]

# Native annotation / drawing count on the rendered example
.venv/bin/python -c '
import fitz
doc = fitz.open("examples/hbp-example.pdf")
annots = sum(len(list(p.annots())) for p in doc)
drawings = sum(len(list(p.get_drawings())) for p in doc)
print("annots:", annots, "drawings:", drawings)
'
# annots: 0 drawings: 312

# Eval test cases (no key, just lists)
halfblood eval --list                                # 5 cases

# Test count
.venv/bin/python -m pytest tests/ --collect-only -q | tail -1
# 1977 tests collected in <s>
```

## Items the README rewrites

This audit surfaces several claims that must change. The README rewrite
addresses all of them:

- The `--fail-pages` example claims exit 1 with no output; the actual
  behaviour exits 0 with a warning and a partial output.
- The "78-page annotated PDF … one annotation per page" claim conflates
  `pages_annotated` with `total_annotations`; the JSON records 78/78 pages
  and 78 total annotations, but the README wording is loose enough to be
  misread.
- The "230 vector drawings" figure is stale; the actual count on the
  committed `examples/hbp-example.pdf` is 312.
- The provider list says "Five providers" but the CLI offers seven
  (`anthropic, openai, openrouter, ollama, lmstudio, openai-compatible, stub`).
- The "chemist, philosopher, physicist, debate coach" persona wording
  mismatches both the eval `TEST_CASES` (chemistry, cooking, philosophy,
  physics, rhetoric) and the built-in `--persona-name` choices (chemist,
  philosopher, editor, detective).
- "EpubProcessor already implements the same `load` / `render_annotations`
  boundary" — `render_annotations` is the legacy name; the supported name
  is `render_plan`.
- The 400-page stress-test numbers (261 / 149 / 410) are illustrative,
  not reproducible as stated.
