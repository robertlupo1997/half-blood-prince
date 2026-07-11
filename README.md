# Half-Blood Prince

*"This book is the property of the Half-Blood Prince."*

Turn any PDF into a book someone brilliant, impatient, and a little bit dangerous has already annotated.

## What it does

Half-Blood Prince takes a PDF and hands it to Claude, page by page, in the voice of a specific persona — by default, a young Severus Snape scribbling corrections into his Potions textbook. The result is a new PDF with handwritten-style margin notes: corrections, shortcuts, warnings, and the occasional invented spell, rendered in ink color, rotated at a natural angle, and connected to the exact passage they're reacting to.

It's the "Advanced Potion-Making" gag from *Harry Potter and the Half-Blood Prince*, generalized: any textbook, novel, or manual can get its own Prince in the margins — yours doesn't have to be a genius at potions, it can be a sardonic chemistry professor, a blunt line cook, or an impatient physicist.

## Quick demo

```bash
export ANTHROPIC_API_KEY=sk-ant-...

# Annotate a whole book
halfblood annotate potions_textbook.pdf -o annotated.pdf

# Preview just the first few pages without writing a PDF
halfblood preview potions_textbook.pdf --pages 1-3

# Use a custom persona
halfblood annotate cookbook.pdf -o annotated.pdf \
  --persona "A blunt, classically trained cook who thinks most recipe writers have never cooked the dish they're describing."
```

`annotate` produces a PDF that looks like someone read the book with a pen in hand:

- A slightly rotated, handwritten-style note in the margin next to the passage it reacts to, in dark iron-gall-blue or rust-red ink depending on the kind of note (a warning reads redder and bolder than a dry aside).
- The target passage itself marked with a native PDF annotation — underlined for a correction, circled for an insight, highlighted for a warning, or struck through and replaced for something flat-out wrong.
- A small hand-drawn connector arrow linking the note to the marked passage when it sits in the margin.
- Notes that vary in confidence: a certain aside is bold and opaque, a speculative one is fainter, as if dashed off less certainly.

## Installation

```bash
git clone <this repo>
cd half-blood-prince
pip install -e .

# for running tests
pip install -e ".[dev]"

# for the eval harness
pip install -e ".[eval]"
```

### Font setup (optional but recommended)

Annotations render in a handwriting font. It isn't bundled (font licensing), so download it yourself:

1. Go to <https://fonts.google.com/specimen/Caveat+Brush> (or [Caveat](https://fonts.google.com/specimen/Caveat))
2. Download the family and extract `CaveatBrush-Regular.ttf`
3. Drop it at `fonts/CaveatBrush-Regular.ttf` in the project root

No font? The pipeline still runs — it silently falls back to `Helvetica-Oblique`, just less magical-looking. See `fonts/README.md` for details.

### API key

Half-Blood Prince calls Claude to write the annotations, so it needs an Anthropic API key:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
```

## Usage

### `halfblood annotate`

Generate a fully annotated PDF.

```bash
halfblood annotate INPUT_PDF -o OUTPUT_PDF [OPTIONS]

Options:
  -o, --output PATH      Path to write the annotated PDF. [required]
  --persona TEXT         Annotator personality description.
  --pages TEXT           Page range, e.g. '1-5,8'. Default: all pages.
  --model TEXT           Claude model to use. [default: claude-sonnet-4-20250514]
  --max-per-page INT     Max annotations kept per page. [default: 5]
  --force                Overwrite an existing output file.
```

For safety, `annotate` and `web-preview` refuse to replace an existing output
file unless you pass `--force`.

```bash
halfblood annotate advanced_potion_making.pdf -o annotated.pdf --pages 1-40
```

### `halfblood preview`

Generate annotations and print them as a table — no PDF written. Useful for iterating on a persona quickly.

```bash
halfblood preview INPUT_PDF [OPTIONS]

Options:
  --pages TEXT           Page range to preview. [default: 1-3]
  --persona TEXT         Annotator personality description.
  --model TEXT           Claude model to use.
  --max-per-page INT     Max annotations kept per page. [default: 5]
```

```bash
halfblood preview textbook.pdf --pages 12-14 --persona "an impatient theoretical physicist"
```

### `halfblood eval`

Run the annotation-quality evaluation harness (see [Evaluation](#evaluation) below).

```bash
halfblood eval [OPTIONS]

Options:
  --model TEXT       Override model for the eval harness.
  --json-out PATH    Write raw evaluation results as JSON.
  --list             List test cases and exit without calling the API.
```

```bash
halfblood eval --list
halfblood eval --json-out results.json
```

## Custom Personas

The "Prince" is just a system-prompt persona string — swap it out and you get an entirely different annotator personality while reusing all the generation, parsing, and rendering plumbing. Pass one with `--persona` on the CLI, or construct an `AnnotationGenerator(persona=...)` directly in Python:

```python
from halfblood.annotation_generator import AnnotationGenerator

generator = AnnotationGenerator(
    persona=(
        "A no-nonsense debate coach who has watched a thousand mediocre "
        "arguments collapse under the first hard question. Terse, "
        "impatient, allergic to hand-waving."
    )
)
```

A good persona description covers:

- **Domain expertise** — what they're actually an expert in, so annotations stay specific and plausible rather than generic.
- **Voice and temperament** — terse vs. verbose, sardonic vs. earnest, how they react to sloppiness.
- **What "counts" as worth annotating** — a good persona is selective, not a highlighter over every sentence.

See `DEFAULT_PERSONA` in `src/halfblood/annotation_generator.py` for the full Snape persona as a worked example, and `eval/eval_harness.py`'s `TEST_CASES` for five more (chemist, cook, philosopher, physicist, debate coach).

## Architecture

```
PDF in --> DocumentProcessor.load()        (extract: PDF -> per-page plain text)
       --> AnnotationGenerator.generate_for_document()
                                            (generate: text -> AnnotationPlan via Claude tool-use)
       --> DocumentProcessor.render_annotations()
                                            (render: AnnotationPlan -> annotated PDF out)
```

- **`models.py`** — the shared Pydantic vocabulary (`Annotation`, `AnnotatedPage`, `AnnotationPlan`, `AnnotationType`) that every other module speaks.
- **`document_processor.py`** — everything that touches PDF bytes: text extraction (PyMuPDF), locating target passages on the page, and drawing the handwritten margin notes back on.
- **`annotation_generator.py`** — everything that talks to Claude: persona/system prompt construction, per-page and whole-document generation, forced tool-use structured output, and response validation.
- **`cli.py`** — the `halfblood` command (`annotate`, `preview`, `eval`), wiring the two modules together with a Rich progress UI.
- **`eval/eval_harness.py`** — standalone LLM-as-judge quality evaluation, runnable independently of the CLI.

See `docs/ARCHITECTURE.md` for the full technical write-up.

## Evaluation

`eval/eval_harness.py` exercises the real annotation pipeline against five curated passages (chemistry, cooking, philosophy, physics, rhetoric) and grades the output with Claude as a judge across five metrics: **voice consistency**, **relevance**, **insight depth**, **variety**, and **density**. Each metric has a 1-5 rubric and a pass/fail threshold.

```bash
export ANTHROPIC_API_KEY=sk-ant-...

# via the CLI
halfblood eval

# or standalone (no install required)
python eval/eval_harness.py
python eval/eval_harness.py --model claude-opus-4-1-20250805
python eval/eval_harness.py --json-out results.json
python eval/eval_harness.py --list
```

The harness prints a per-test-case table of scores and justifications, then a summary table and an overall grade. Exit code is `0` only if every test case passes every metric's threshold — wire it into CI to catch persona or prompt regressions.

## Contributing

**Adding a new annotation type**

1. Add the value to `AnnotationType` in `models.py`.
2. Give it an ink color in `_INK_PALETTE` and a font size in `_FONT_SIZE_BY_TYPE` in `document_processor.py`.
3. Decide how it should mark the target passage in `DocumentProcessor._mark_target` (underline / highlight / circle / strikeout).
4. Describe it in `DEFAULT_PERSONA`'s "WHAT YOUR ANNOTATIONS DO" list (and in any custom personas you maintain) so the model actually knows when to use it.

**Adding a new document format (e.g. EPUB)**

`DocumentProcessor` is the only module that knows about PDF bytes; `AnnotationGenerator` only ever sees plain `PageContent` (page number, text, width, height). To support a new format, add a loader that produces the same `PageContent` shape and a renderer that can place text/marks given a passage's bounding rect — the generation and CLI layers need no changes.

**Adding eval test cases**

Append a `TestCase` to `TEST_CASES` in `eval/eval_harness.py` with a persona, a passage, expected annotation types, and an ideal annotation-count range — the harness picks it up automatically.

## Inspiration

This project is a riff on [Riddle](https://github.com/MaximeRivest/riddle) and the "Half-Blood Prince" gag from *Harry Potter and the Half-Blood Prince* — a used Potions textbook whose margins are full of a previous, better student's corrections, shortcuts, and dangerous inventions. Half-Blood Prince asks: what if any book could have its own Prince?
