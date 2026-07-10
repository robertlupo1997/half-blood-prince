# Architecture

This document describes how Half-Blood Prince is put together, for developers who want to understand, extend, or debug it. For install/usage instructions, see the top-level `README.md`.

## System diagram

The pipeline is a strict, one-directional pipe with three stages, glued together by `cli.py`:

```
                 ┌───────────────────────┐
  input.pdf ---> │  DocumentProcessor     │ --- list[PageContent] --->
                 │  .load()                │      (page_number, text,
                 └───────────────────────┘       width, height)
                                                        |
                                                        v
                 ┌────────────────────────────────────────────┐
                 │  AnnotationGenerator                          │
                 │  .generate_for_document()                     │
                 │    for each page:                             │
                 │      build system prompt (persona)            │
                 │      build user prompt (page text + context)  │
                 │      call Claude, forced tool_choice           │
                 │      parse + validate tool_use block           │
                 │      fold INVENTION/WARNING notes into        │
                 │        rolling "running_notes" context         │
                 └────────────────────────────────────────────┘
                                                        |
                                                        v
                                              AnnotationPlan
                                          (title, persona, pages[])
                                                        |
                                                        v
                 ┌────────────────────────────────────────────┐
                 │  DocumentProcessor.render_annotations()       │
                 │    group Annotation by page                   │
                 │    for each: find_text_rect() on the PDF page │
                 │      add_margin_note():                       │
                 │        _mark_target() (underline/circle/      │
                 │          strikeout/highlight annot)            │
                 │        _write_margin_text / _write_inline_text │
                 │          / _write_between_lines_text (fitz     │
                 │          Shape, rotated via morph matrix)      │
                 │        _draw_connector() (bowed arrow)          │
                 └────────────────────────────────────────────┘
                                                        |
                                                        v
                                            output.pdf (annotated)
```

`cli.py` orchestrates all three stages under a single `rich.Progress` bar and is the only module that imports both `DocumentProcessor` and `AnnotationGenerator` together; the two are otherwise decoupled and only share the `models.py` vocabulary plus the `PageContent` dataclass.

## Module responsibilities

### `models.py`

Owns the shared data vocabulary and nothing else — no I/O, no API calls, no PDF logic. Everything downstream (generator, renderer, CLI, eval harness) imports from here so the "shape" of an annotation is defined exactly once.

### `document_processor.py`

Owns everything that touches PDF bytes, via PyMuPDF (`fitz`):

- **Extraction** (`load`): PDF → `list[PageContent]`, one per page, 1-indexed.
- **Target location** (`find_text_rect` / `_search_variants` / `_normalize_search_text`): given an LLM-produced `target_text`, finds where it actually sits on the page, tolerating whitespace reflow, smart-quote/dash normalization, and partial matches.
- **Rendering** (`render_annotations` / `add_margin_note` and its private `_write_*`/`_mark_target`/`_draw_connector` helpers): burns the annotation plan back onto the PDF as native annotations plus hand-styled text.
- **Font resolution** (`_resolve_handwriting_font` / `_load_measure_font`): locates a handwriting TTF/OTF or falls gracefully back to a standard PDF font.

It has no knowledge of Claude, personas, or prompts — its only external inputs are an `AnnotationPlan`/`list[Annotation]` and PDF paths. This is a deliberate boundary: rendering doesn't need to know how annotations were produced, only what to draw and where.

### `annotation_generator.py`

Owns everything that talks to Claude:

- Persona and system-prompt construction (`_build_system_prompt`).
- Per-page prompt construction with surrounding context (`_build_user_prompt`).
- The forced-tool-use API call and response parsing/validation (`generate_for_page`, `_parse_response`, `_extract_raw_annotations`).
- Whole-document orchestration with a sliding context window and a running "notes" memory (`generate_for_document`).

It has no knowledge of PDF bytes, fonts, or rendering — its only output is `Annotation` / `AnnotatedPage` / `AnnotationPlan` objects built from `PageContent` input. This is the other half of the same boundary: generation doesn't need to know how its output will be drawn.

### `cli.py`

The `halfblood` Click group (`annotate`, `preview`, `eval`). Owns:

- CLI option parsing and validation, including page-range parsing (`_parse_page_range`, `_filter_pages`).
- Wiring `DocumentProcessor` → `AnnotationGenerator` → `DocumentProcessor` together with a `rich.Progress` UI.
- Pretty-printing an `AnnotatedPage` as a table (`preview`, via `_print_annotated_page`).
- Shelling out to `eval/eval_harness.py` as a subprocess for the `eval` subcommand (kept as a separate process/script so the harness stays independently runnable without the package installed).

### `eval/eval_harness.py`

A standalone script (importable but designed to run via `python eval/eval_harness.py` even before the package is pip-installed — it inserts `src/` onto `sys.path` itself). Owns:

- The curated `TEST_CASES` (passage, persona, expected types, ideal count range).
- The `METRICS` rubric definitions.
- Generation (preferring the real `AnnotationGenerator`, falling back to an inline API call if that import fails).
- LLM-as-judge scoring (`judge_annotations`) and reporting (`print_report`, `_results_to_json`).

## Data model

```
AnnotationPlan
├── title: str
├── prince_persona: str            # persona active for this whole document
└── pages: list[AnnotatedPage]
        ├── page_number: int
        ├── original_text: str
        └── annotations: list[Annotation]
                ├── page: int                      # 1-indexed, matches AnnotatedPage.page_number
                ├── target_text: str                # verbatim quote anchoring the note
                ├── annotation_type: AnnotationType  # CORRECTION | IMPROVEMENT | INSIGHT |
                │                                    #   INVENTION | WARNING | SHORTCUT |
                │                                    #   CROSSED_OUT | DOODLE_NOTE
                ├── content: str                     # the handwritten note text
                ├── confidence: float (0.0-1.0)      # drives rendered ink opacity
                └── position: str                    # margin_right | margin_left |
                                                       #   inline | between_lines
```

`AnnotationPlan` is the unit of work that flows from generation to rendering; `AnnotatedPage` is the natural per-page grouping the generator builds incrementally; `Annotation` is the atomic renderable unit. `AnnotationPlan.total_annotations` is a convenience property summing across all pages.

`DocumentProcessor.annotations_from_plan()` flattens a plan into a flat `list[Annotation]` for `render_annotations`, and — defensively — trusts `AnnotatedPage.page_number` over `Annotation.page` if the two ever disagree, since the page is the grouping the plan was assembled under.

## LLM integration

### Tool-use structured output

Rather than asking Claude to emit JSON in prose and parsing it out of a text block, `annotation_generator.py` defines a single tool, `record_annotations`, whose `input_schema` mirrors the `Annotation` model (`target_text`, `annotation_type` enum, `content`, `confidence`, `position`). The API call is made with:

```python
tool_choice={"type": "tool", "name": "record_annotations"}
```

which forces Claude to respond with exactly one call to that tool — no prose-parsing, no code-fence stripping, no risk of the model "explaining itself" instead of producing data. `_extract_raw_annotations` pulls the `tool_use` block's `input["annotations"]` directly. A plain-JSON-string code path also exists in the same function for testability and as a defensive fallback (also used by the eval harness's design, which expects either shape).

Every raw annotation dict is then run through `Annotation(**item)` (Pydantic), and any individual item that fails validation is logged and dropped rather than aborting the whole page — a partial, slightly-smaller annotation set is preferred over losing a page entirely.

### The persona system

The "Prince" is just a string plugged into the system prompt (`self.persona`, default `DEFAULT_PERSONA`). `_build_system_prompt` concatenates the persona description with a fixed, persona-agnostic "TASK" block that explains the input format, instructs verbatim `target_text` quoting, and points at the `record_annotations` tool. This split is what makes personas swappable without touching any generation, parsing, or rendering code — `DEFAULT_PERSONA` is a detailed Snape voice-and-rules document (temperament, what each `AnnotationType` means in-voice, example lines, and hard rules like "never break character" and "quote verbatim"); a caller can pass an arbitrarily different `persona` string (see `cli.py`'s simpler default, or the five personas in `eval/eval_harness.py`'s `TEST_CASES`) and get a completely different annotator with zero code changes.

### Context windowing

`generate_for_document` calls `generate_for_page` once per page but is not memoryless: each call is given a `book_context` string built from three ingredients, joined with blank lines:

1. **Previous-page tail** — the last 500 characters of the prior page's text, so notes acknowledge the page opening mid-thought.
2. **Next-page head** — the first 500 characters of the next page's text, so notes can anticipate what's coming.
3. **Running notes** — the content of every `INVENTION` or `WARNING` annotation emitted on prior pages (capped to the most recent 8), fed back in as "Running notes on techniques/grudges established so far." This is what lets the Prince reference "my own method" from thirty pages ago without re-deriving it, and is the harness's main lever for cross-page voice consistency.

This is a fixed-size sliding window, not a full running summary or a stateful conversation — each `generate_for_page` call is a fresh, independent API request; continuity comes entirely from what's re-injected into the prompt, not from conversation history.

`max_annotations_per_page` is enforced client-side, after generation: if Claude returns more than the cap, the highest-`confidence` annotations are kept and the rest silently dropped.

## PDF rendering pipeline

`DocumentProcessor` uses PyMuPDF (`fitz`) exclusively, for two distinct jobs on the same page:

1. **Marking the target passage** (`_mark_target`) with a *native* PDF annotation — `add_underline_annot` (correction/improvement/shortcut), `add_highlight_annot` (warning), `add_circle_annot` with a small pad (insight/invention/doodle_note), or `add_strikeout_annot` (crossed_out). These stay first-class, editable PDF annotation objects (visible/removable in any PDF viewer's annotation panel) rather than being flattened into ink, and are colored/opacity-set per `annotation_type` via `_INK_PALETTE`.
2. **Drawing the handwritten note** via a `fitz.Shape` (`page.new_shape()`), which is the only PyMuPDF primitive that supports `insert_text(..., morph=...)` — an arbitrary affine transform applied per glyph run. This is what makes the "rotation jitter" possible without pre-rendering each note as a rasterized image.

### Font resolution

`_resolve_handwriting_font` searches, in order: an explicit `font_path` argument, `<project_root>/fonts/CaveatBrush-Regular.ttf`, any `*aveat*.ttf`/`*aveat*.otf` in that folder, then a short list of common system install paths (Windows/macOS/Linux). The first hit wins and is registered under the alias `HBProseHand`. If nothing is found, it falls back to the standard PDF font `Helvetica-Oblique` (no file needed — always available) and logs a warning with download instructions. A separate `fitz.Font` instance (`_measure_font`) is loaded purely for text-width measurement during word-wrap, using the same file if custom, or Helvetica metrics as a stand-in otherwise, so wrap width stays roughly correct even without the real handwriting font.

### Ink styling

Two independent per-type lookup tables drive the "handwriting" feel:

- `_INK_PALETTE`: an (r, g, b) triple per `AnnotationType` — mostly a blue-black "iron gall ink" palette, with `WARNING` and `CROSSED_OUT` shifted toward a rustier red for urgency.
- `_FONT_SIZE_BY_TYPE`: base point size per type (warnings largest at 10pt, doodle notes smallest at 8pt).

`confidence` (0.0-1.0) is mapped to opacity via `_opacity`: `0.55 + 0.4 * confidence`, so even a zero-confidence note is never fully transparent, and a full-confidence note tops out just short of 1.0 (target-passage marks get a small +0.05 boost on top of that so they read clearly against the page).

### Rotation jitter

`_organic_angle` seeds a `random.Random` with either an explicit per-`DocumentProcessor` `seed` (for reproducible test renders) or the note's own text (so renders are stable across re-runs of the *same* annotation without needing external state, but different notes on the same page don't all lean the same way). It draws a magnitude in `[1.0, 3.0]` degrees and a random sign, producing a `fitz.Matrix(angle)` passed as the `morph` transform origin-pivoted at the text insertion point.

### Layout by `position`

Four placement strategies, dispatched in `add_margin_note`:

- `margin_right` / `margin_left` (`_write_margin_text`): word-wraps into the available horizontal space between the target rect and the page edge (clamped to `[_MIN_MARGIN_WIDTH, _MAX_MARGIN_WIDTH]` points), vertically centers the note block on the target passage, then a bowed `_draw_connector` arrow (a `draw_curve` plus a hand-built two-line arrowhead) links the note back to the passage edge.
- `inline` (`_write_inline_text`): tries to squeeze a short (≤2 line), slightly smaller note directly after the target text on the same line if there's ≥30pt of room; otherwise drops just below the passage.
- `between_lines` (`_write_between_lines_text`): a very short, small note packed into the interline gap directly above the target, positioned to avoid colliding with the line above.
- `CROSSED_OUT` additionally always calls `_write_replacement_above` regardless of `position`, hovering the replacement text just above the struck-through passage.

If `find_text_rect` fails to locate `target_text` on the page at all (LLM transcription drift beyond what the fallback search variants can absorb), `render_annotations` counts it as skipped and logs a warning rather than guessing at a location; `add_margin_note` itself has a defensive fallback (a placeholder rect near the page top) for direct callers that pass `rect=None`.

## Evaluation framework

`eval/eval_harness.py` is deliberately decoupled from the package (it can run via `python eval/eval_harness.py` before `pip install -e .`, inserting `src/` onto `sys.path` itself) but prefers the real `AnnotationGenerator`/`PageContent` when importable, falling back to an inline, harness-local generator (`_fallback_generate`) that hits the Anthropic API directly with an equivalent tool schema, so the harness never hard-fails just because the package isn't wired up yet.

**Test cases** (`TEST_CASES`): five hand-written, non-copyrighted passages spanning genre (chemistry, cooking, philosophy, physics, rhetoric), each with its own `persona`, `expected_annotation_types`, an `ideal_annotation_range`, and free-text `notes` describing what a *good* annotation set would actually say — these are fed to the judge as grading context, not just the passage itself.

**Metrics** (`METRICS`, five total): `voice_consistency`, `relevance`, `insight_depth`, `variety`, `density` — each a `Metric` dataclass with a `label`, `description`, a five-point `rubric` (written out per score level 1-5), and a pass/fail `threshold` (3.0-4.0 depending on metric; `relevance` is held to the highest bar at 4.0).

**LLM-as-judge** (`judge_annotations`): builds a tool schema (`_build_judge_tool`) with one object property per metric (`score` 1-5 int, `justification` string), and asks Claude — as "a strict, senior editorial reviewer" — to score the generated annotation set against the passage, the expected types/count, and the reviewer notes, again via forced tool-use so scoring is structured rather than free text.

**Orchestration and reporting** (`run_eval`, `print_report`): runs generation + judging for every test case under a progress bar, catching exceptions per-case so one failure doesn't abort the run (`EvalResult.generation_error`). Reporting renders a per-case Rich table (metric / score / pass-fail / justification), a cross-case summary table, and an aggregate "average score by metric vs. threshold" table with an overall letter grade (`_letter_grade`, A-F on the 1-5 average). `--json-out` serializes everything (`_results_to_json`) for CI artifact storage or trend tracking. The process exit code is `0` iff every test case passed every one of its metric thresholds — this is what makes `halfblood eval` usable as a CI gate against prompt/persona regressions.

## Extension points

**EPUB (or other format) support.** `AnnotationGenerator` only depends on `PageContent` (page_number, text, width, height) and never imports `fitz` — so a new `EpubProcessor.load() -> list[PageContent]` slots into the exact same generation call with no changes there. The harder half is rendering: `render_annotations`/`add_margin_note` are written against `fitz.Page`/`fitz.Rect`/`fitz.Shape` specifically. Supporting EPUB rendering means either (a) converting EPUB → PDF first and reusing the existing PyMuPDF renderer unchanged, or (b) writing a parallel renderer against EPUB's XHTML/CSS content model (no page-fixed geometry, so "margin" placement would need to become CSS-based, e.g. an injected `<aside>` styled to look hand-annotated). Option (a) is the much smaller lift.

**New annotation types.** Add the enum value to `AnnotationType` in `models.py`; add an ink entry to `_INK_PALETTE` and a size to `_FONT_SIZE_BY_TYPE` in `document_processor.py`; decide its `_mark_target` marking style (or add a new one — the four are underline/highlight/circle/strikeout, but nothing stops a new shape); and describe it in the persona text (`DEFAULT_PERSONA`'s numbered list) so personas actually invoke it. The JSON schema enum (`_ANNOTATION_TOOL_SCHEMA` in the generator, and the near-identical `GENERATION_TOOL` in the eval harness) is derived automatically from `[t.value for t in AnnotationType]`, so no manual schema edit is needed there.

**New renderers.** Because `DocumentProcessor` is the sole consumer of `fitz`, an entirely different renderer (e.g. HTML/CSS margin notes for an EPUB or web reader, or a "diff view" renderer that shows only the annotations without touching page layout) can be written as a new class that consumes the same `AnnotationPlan`/`list[Annotation]` and never needs to know anything about how annotations were generated.

**New personas.** No code changes needed at all — pass a different `persona` string via `--persona` (CLI) or the `AnnotationGenerator(persona=...)` constructor (Python/eval harness). See the "Custom Personas" section of the README.

## Design decisions

**Direct Anthropic SDK over LangChain.** The generator is a thin, explicit wrapper around `anthropic.Anthropic().messages.create(...)` — no chain/agent framework in between. The task is a single, stateless, tool-forced call per page; there's no multi-step agentic reasoning, retrieval, or branching that would justify an orchestration framework's overhead. Keeping the SDK call direct and visible in `annotation_generator.py` makes the prompt, the tool schema, and the parsing logic all auditable in one file, which matters a lot for a project whose entire value proposition is "the voice has to be right."

**PyMuPDF (`fitz`) over other PDF libraries.** PyMuPDF was chosen because it uniquely offers, in one library: fast/accurate text extraction with layout-preserving `search_for` (needed to relocate LLM-quoted passages), native PDF annotation objects (underline/highlight/circle/strikeout — first-class, viewer-editable), *and* low-level shape/text drawing with an arbitrary per-glyph affine transform (`Shape.insert_text(..., morph=...)`) — which is exactly what's needed for the rotation jitter that makes notes look hand-scrawled rather than typeset. Achieving all three with, say, `reportlab` + `pypdf` would mean stitching together separate extraction and generation libraries and losing native annotation objects.

**Tool-use over JSON mode / prompted JSON.** Forcing `tool_choice={"type": "tool", "name": "record_annotations"}` guarantees the response is a single, schema-validated tool call — no prose to strip, no markdown fences to detect, no risk of the model "explaining" instead of producing data, and enum fields (`annotation_type`, `position`) are constrained at the API level before they ever reach Pydantic. The same pattern is reused for the eval harness's judge (`record_scores`), which is exactly why both generation and grading in this codebase get the same reliability properties. A plain-JSON string parsing path also exists in `_parse_response`/`_extract_raw_annotations` purely as a defensive/testable fallback, not as the primary path.
