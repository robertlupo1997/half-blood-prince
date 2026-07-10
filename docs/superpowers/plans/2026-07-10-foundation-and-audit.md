# Foundation & Adversarial Audit Implementation Plan (Session 1)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Gate the repo with lint/type/test CI, then produce a fully verified adversarial-audit ledger of the untrusted prototype — the input for the Phase 2 fix plan.

**Architecture:** Phase 0 tooling lands first so every later commit is gated. The audit runs as six independent read-only review lenses (parallel subagents) plus two real-API E2E runs; every finding is adversarially re-verified before entering the committed ledger at `docs/audit/2026-07-10-adversarial-audit.md`.

**Tech Stack:** Python 3.11+, ruff, mypy, pytest, GitHub Actions, PyMuPDF, ebooklib, Anthropic SDK.

## Global Constraints

- Python `>=3.11` (spec + pyproject floor).
- Audit lenses are **read-only** for product code: no fixes during Phase 1; instrumentation only in scratch scripts outside `src/`.
- No new runtime dependencies in this session; dev-deps limited to `ruff`, `mypy`, `pytest` (already present).
- Every commit after Task 1 must pass: `.venv/bin/ruff check src tests eval && .venv/bin/mypy src/halfblood && .venv/bin/pytest tests/ -q`.
- Findings ledger severity scale: Critical / High / Medium / Low (spec definition).
- Real-API runs use the fixture PDF and generated EPUB only; record token usage and dollar cost in the ledger.
- All work on branch `main` (no remote exists yet; nothing to protect).

---

### Task 1: Ruff + mypy configuration

**Files:**
- Modify: `pyproject.toml`
- Test: existing suite (`tests/test_pipeline.py`) must stay green

**Interfaces:**
- Consumes: nothing.
- Produces: the gate command used by all later tasks:
  `.venv/bin/ruff check src tests eval && .venv/bin/mypy src/halfblood && .venv/bin/pytest tests/ -q`

- [ ] **Step 1: Add dev deps + tool config to `pyproject.toml`**

Replace the `[project.optional-dependencies]` block and append tool sections:

```toml
[project.optional-dependencies]
dev = [
    "pytest>=8.0.0",
    "ruff>=0.5.0",
    "mypy>=1.10.0",
]

[tool.ruff]
line-length = 100
target-version = "py311"

[tool.ruff.lint]
select = ["E", "F", "W", "I", "UP", "B", "SIM"]
ignore = ["E501"]  # long strings in personas/prompts; line-length still guides new code

[tool.mypy]
python_version = "3.11"
warn_unused_ignores = true
warn_redundant_casts = true
disallow_untyped_defs = true
no_implicit_optional = true
ignore_missing_imports = true  # fitz, ebooklib, bs4 lack stubs
```

- [ ] **Step 2: Install and run the linters**

Run: `.venv/bin/pip install -q -e ".[dev]" && .venv/bin/ruff check src tests eval; .venv/bin/mypy src/halfblood`
Expected: a list of violations (unknown count — prototype code).

- [ ] **Step 3: Triage violations — mechanical fixes only**

Apply `ruff check --fix` for auto-fixable items (imports, upgrades). For mypy errors that reveal *behavioral* bugs, do NOT fix — record them in `/tmp/claude-1000/-mnt-c-Users-Trey-Downloads-half-blood-prince/e39f5cd5-1e95-451d-bee5-9483e099ef88/scratchpad/lint-findings.md` as audit input. For unfixable-without-refactor noise, add targeted `# noqa`/`# type: ignore[code]` with a comment, or per-file ignores in pyproject. The bar: `ruff` and `mypy` exit 0 without masking real defects silently.

- [ ] **Step 4: Verify gate passes**

Run: `.venv/bin/ruff check src tests eval && .venv/bin/mypy src/halfblood && .venv/bin/pytest tests/ -q`
Expected: exit 0, `44 passed`.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml src tests eval
git commit -m "chore: add ruff + mypy, mechanical lint fixes"
```

### Task 2: GitHub Actions CI

**Files:**
- Create: `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: Task 1's gate command.
- Produces: CI that runs on push/PR once the repo has a GitHub remote (Phase 5).

- [ ] **Step 1: Write the workflow**

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:

jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ["3.11", "3.12"]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}
      - run: pip install -e ".[dev]"
      - run: ruff check src tests eval
      - run: mypy src/halfblood
      - run: pytest tests/ -q
```

- [ ] **Step 2: Validate locally (no remote yet)**

Run each workflow command inside the venv exactly as CI would:
`.venv/bin/pip install -q -e ".[dev]" && .venv/bin/ruff check src tests eval && .venv/bin/mypy src/halfblood && .venv/bin/pytest tests/ -q`
Expected: exit 0.

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: pytest + ruff + mypy on 3.11/3.12"
```

### Task 3: Dispatch the six audit lenses (parallel, read-only)

**Files:**
- Create (by agents): `<scratchpad>/audit/lens-{1..6}.md` where `<scratchpad>` = `/tmp/claude-1000/-mnt-c-Users-Trey-Downloads-half-blood-prince/e39f5cd5-1e95-451d-bee5-9483e099ef88/scratchpad`

**Interfaces:**
- Consumes: repo at the Task 2 commit.
- Produces: six raw findings files, each entry formatted `SEVERITY | file:line | claim | how-to-reproduce`.

- [ ] **Step 1: Dispatch all six reviewer subagents in one parallel batch**

Common preamble for every lens prompt: *"You are auditing untrusted prototype code at /mnt/c/Users/Trey/Downloads/half-blood-prince. Do not trust CLAUDE.md's claims — verify against code. Do NOT modify any file under src/, tests/, eval/, or docs/. Write findings to `<scratchpad>/audit/lens-N.md`, one entry per finding: `SEVERITY (Critical/High/Medium/Low) | file:line | one-sentence defect claim | concrete failure scenario (inputs → wrong behavior)`. Report only defects you can point to in code; no style nits (ruff/mypy cover those)."*

Lens bodies:

1. **Generation correctness** — `src/halfblood/annotation_generator.py`: `_ANNOTATION_TOOL_SCHEMA` vs `models.Annotation` field drift; context windowing (500-char prev/next, running-notes cap) off-by-ones and page-boundary behavior; `generate_for_document`/`generate_for_page` error paths; tool_use block parsing; max_tokens truncation handling.
2. **Rendering correctness** — `src/halfblood/document_processor.py` + `src/halfblood/epub_processor.py`: margin rect math vs page geometry; `_write_margin_text` wrapping/overflow; morph rotation anchor; connector endpoint geometry; `_search_variants` wrong-passage matching; EPUB `_locate_text` node-boundary behavior; CSS injection correctness; `_ensure_toc_uids` workaround.
3. **Test faithfulness** — `tests/test_pipeline.py` + `tests/conftest.py`: for each test, does it assert behavior or mirror implementation? Are mocked Anthropic response objects shaped like real SDK `Message` objects (content blocks, `type` fields, `input` payloads)? List concretely what the suite does NOT cover.
4. **Security & robustness** — `src/halfblood/web_preview.py` primarily: verify every LLM-derived string reaching HTML goes through `html.escape` (enumerate sinks); `_flexible_pattern` catastrophic backtracking (construct a hostile `target_text`); path handling in CLI; trust boundary of `target_text` flowing into regex + `page.search_for`. Also dependency hygiene: `pyproject.toml` pins (floors only, no upper bounds, no lockfile) — assess and recommend a pin policy for a public repo.
5. **API usage** — `src/halfblood/annotation_generator.py` + `eval/eval_harness.py` against CURRENT Anthropic docs (load the claude-api skill or live docs first; do not answer from memory): model ID currency (`claude-sonnet-4-20250514`), tool_choice semantics, SDK built-in retry/timeout defaults (determines what Phase 3 retry work is actually needed), error taxonomy (429/500/529 handling claims), max_tokens sizing, eval-judge model choice.
6. **Docs-vs-code drift** — README.md, docs/ARCHITECTURE.md, fonts/README.md vs actual code: every documented command/option/behavior must exist with the documented name and default (known seed: README omits `web-preview` and ships-EPUB); every code capability missing from docs; installation instructions correctness.

- [ ] **Step 2: Collect results**

All six agents return; confirm each `<scratchpad>/audit/lens-N.md` exists and is non-empty (an empty findings file requires the agent to state "no findings" explicitly).

### Task 4: Adversarial verification of findings

**Files:**
- Create: `<scratchpad>/audit/verified.md`

**Interfaces:**
- Consumes: `lens-{1..6}.md` raw findings.
- Produces: `verified.md` — the same entries each stamped `CONFIRMED | REFUTED | DOWNGRADED-to-<sev>` with one-line evidence.

- [ ] **Step 1: Verify every finding against the code**

For each raw finding: open the cited `file:line`, reproduce the failure scenario mentally or with a scratch script under `<scratchpad>/audit/repro/`, and stamp it. Rules: default-skeptical (a finding that can't be traced to concrete code behavior is REFUTED); duplicates across lenses merge, keeping the higher severity; severity must match the scenario's actual blast radius. High/Critical findings additionally get a runnable repro script or exact command in the entry.

- [ ] **Step 2: Sanity totals**

`verified.md` header records: N raw → N confirmed / N refuted / N merged, per lens.

### Task 5: Real E2E — PDF with cost measurement

**Files:**
- Create: `<scratchpad>/audit/e2e_pdf.py` (instrumentation wrapper, outside repo)
- Output: `<scratchpad>/audit/e2e-pdf-annotated.pdf`, `<scratchpad>/audit/e2e-pdf-report.md`

**Interfaces:**
- Consumes: `tests/fixtures/potions_textbook.pdf`, `ANTHROPIC_API_KEY` (env).
- Produces: measured per-page token usage + dollar cost, and a visually verified annotated PDF; both feed the ledger and later the README cost line.

- [ ] **Step 1: Write the instrumented runner**

```python
"""Run the real pipeline on the fixture PDF, summing token usage."""
import sys
from pathlib import Path

from halfblood.annotation_generator import AnnotationGenerator
from halfblood.document_processor import DocumentProcessor

USAGE = {"input_tokens": 0, "output_tokens": 0, "calls": 0}

gen = AnnotationGenerator()
_orig_create = gen.client.messages.create

def counting_create(*args, **kwargs):
    resp = _orig_create(*args, **kwargs)
    USAGE["input_tokens"] += resp.usage.input_tokens
    USAGE["output_tokens"] += resp.usage.output_tokens
    USAGE["calls"] += 1
    return resp

gen.client.messages.create = counting_create

dp = DocumentProcessor()
pages = dp.load("tests/fixtures/potions_textbook.pdf")
plan = gen.generate_for_document(pages, title="Advanced Potion-Making")
out = Path(sys.argv[1])
dp.render_annotations("tests/fixtures/potions_textbook.pdf", plan, out)

n_ann = sum(len(p.annotations) for p in plan.pages)
print(f"pages={len(pages)} annotations={n_ann} calls={USAGE['calls']}")
print(f"input_tokens={USAGE['input_tokens']} output_tokens={USAGE['output_tokens']}")
```

(If attribute names differ — e.g. the generator's client attribute or render signature — adapt the scratch script to the real interfaces; that mismatch itself is a docs/API finding for the ledger. Look up current per-MTok pricing for the configured model when computing dollars.)

- [ ] **Step 2: Run it**

Run: `cd /mnt/c/Users/Trey/Downloads/half-blood-prince && .venv/bin/python <scratchpad>/audit/e2e_pdf.py <scratchpad>/audit/e2e-pdf-annotated.pdf`
Expected: nonzero annotations across 5 pages; token counts printed. Failure of any kind = Critical/High ledger finding with the traceback.

- [ ] **Step 3: Visual verification**

Render pages to PNG and inspect with Read:

```bash
.venv/bin/python - <<'EOF'
import fitz
doc = fitz.open("<scratchpad>/audit/e2e-pdf-annotated.pdf")
for i, page in enumerate(doc):
    page.get_pixmap(dpi=110).save(f"<scratchpad>/audit/e2e-pdf-page{i+1}.png")
EOF
```

Check: notes inside page bounds, connectors touch their targets, marks on plausible passages, legible fallback font. Each visual defect → ledger finding. Write `e2e-pdf-report.md` with pages/annotations/tokens/dollars + observations.

### Task 6: Real E2E — EPUB

**Files:**
- Create: `tests/fixtures/make_test_epub.py`, `tests/fixtures/sample_book.epub`
- Output: `<scratchpad>/audit/e2e-epub-annotated.epub`, `<scratchpad>/audit/e2e-epub-report.md`

**Interfaces:**
- Consumes: `ANTHROPIC_API_KEY`; ebooklib (already a runtime dep).
- Produces: a committed EPUB fixture + verified annotated output; findings to ledger.

- [ ] **Step 1: Write the fixture generator**

```python
"""Generate a small public-domain-text EPUB fixture (3 chapters)."""
from ebooklib import epub

CHAPTERS = [
    ("On Combustion", "<h1>On Combustion</h1><p>When a candle burns, the wax "
     "combines with oxygen from the air. The flame's <em>luminous</em> zone "
     "contains unburnt carbon particles heated to incandescence. Complete "
     "combustion yields carbonic acid and water vapour.</p>"),
    ("On Acids", "<h1>On Acids</h1><p>An acid turns blue litmus red. The "
     "mineral acids — sulphuric, nitric, and muriatic — must be diluted by "
     "pouring acid into water, never water into acid, lest the vessel crack "
     "from sudden heat.</p>"),
    ("On Distillation", "<h1>On Distillation</h1><p>Distillation separates "
     "liquids by their boiling points. The retort is heated gently; the "
     "vapour condenses in the worm. Impatient heating spoils the spirit and "
     "risks bursting the apparatus.</p>"),
]

book = epub.EpubBook()
book.set_identifier("halfblood-test-epub")
book.set_title("Elements of Practical Chemistry")
book.set_language("en")
book.add_author("A Public-Domain Chemist")
items = []
for i, (title, html) in enumerate(CHAPTERS, 1):
    ch = epub.EpubHtml(title=title, file_name=f"ch{i}.xhtml", lang="en")
    ch.content = html
    book.add_item(ch)
    items.append(ch)
book.toc = items
book.add_item(epub.EpubNcx())
book.add_item(epub.EpubNav())
book.spine = ["nav", *items]
epub.write_epub("tests/fixtures/sample_book.epub", book)
print("wrote tests/fixtures/sample_book.epub")
```

- [ ] **Step 2: Generate and commit the fixture**

Run: `cd tests/fixtures && ../../.venv/bin/python make_test_epub.py && cd ../..`
Expected: `wrote tests/fixtures/sample_book.epub`

```bash
git add tests/fixtures/make_test_epub.py tests/fixtures/sample_book.epub
git commit -m "test: add generated EPUB fixture for E2E and future epub tests"
```

- [ ] **Step 3: Run the real pipeline via CLI**

Run: `.venv/bin/halfblood annotate tests/fixtures/sample_book.epub -o <scratchpad>/audit/e2e-epub-annotated.epub`
Expected: exit 0, annotations reported. Any crash = ledger finding.

- [ ] **Step 4: Verify the output EPUB**

Unzip the output (`.venv/bin/python -c "import zipfile; zipfile.ZipFile('<scratchpad>/audit/e2e-epub-annotated.epub').extractall('<scratchpad>/audit/epub-out')"`), read the chapter XHTML: sidenotes present, HTML well-formed (parse with `lxml`), CSS injected once, original text intact. Write `e2e-epub-report.md` with annotation counts per chapter, skipped-target log lines, observations.

### Task 7: Compile and commit the audit ledger

**Files:**
- Create: `docs/audit/2026-07-10-adversarial-audit.md`

**Interfaces:**
- Consumes: `verified.md`, both E2E reports, `lint-findings.md` from Task 1, the 8 inherited known issues (CLAUDE.md "Unfixed" list).
- Produces: the single input document for the Phase 2 fix plan.

- [ ] **Step 1: Write the ledger**

Structure:

```markdown
# Adversarial Audit Ledger — 2026-07-10

## Method
(lenses run, verification discipline, E2E configs, what was NOT audited)

## E2E results
(PDF: pages/annotations/tokens/$; EPUB: same; visual verdicts)

## Findings
### Critical
### High
### Medium
### Low
Each: `AUD-NN | file:line | claim | failure scenario | repro | proposed fix`

## Inherited known issues — re-verification
| # | CLAUDE.md claim | Verdict (CONFIRMED / ALREADY-FIXED / WRONG) | Merged as |

## Accepted / won't-fix
(Low findings deliberately deferred, with reasoning)
```

Every confirmed finding gets a stable `AUD-NN` id — the Phase 2 plan's tasks reference these ids.

- [ ] **Step 2: Gate check + commit**

Run: `.venv/bin/ruff check src tests eval && .venv/bin/mypy src/halfblood && .venv/bin/pytest tests/ -q`
Expected: exit 0 (audit changed no product code; fixture commit already gated).

```bash
git add docs/audit/2026-07-10-adversarial-audit.md
git commit -m "audit: adversarial audit ledger (Phase 1 complete)"
```

- [ ] **Step 3: Report to Trey**

Summarize: finding counts by severity, the 3 worst findings in plain language, E2E cost per page, inherited-issue verdicts, and the proposed shape of the Phase 2 fix plan. Trey reviews the ledger asynchronously; Phase 2 planning proceeds from it.

---

## Deferred to subsequent plans (authored from the ledger)

- **Phase 2 fix plan** — one TDD task per `AUD-NN` finding, severity order.
- **Phase 3 hardening plan** — retry/backoff (scoped by lens 5's SDK findings), async waves (`--concurrency`, default 4, semantics per spec), collision detection, magic-byte validation, font-log fix, model-default bump.
- **Phase 4/5 launch plan** — gallery books, GitHub Pages, README overhaul, LICENSE/CONTRIBUTING, launch drafts, tag + push.

Planning fixes before findings exist would be placeholder-planning; the spec's session mapping (S1 = audit) makes this the intended seam.
