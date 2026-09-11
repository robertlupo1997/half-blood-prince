# AGENTS.md — Half-Blood Prince

Entry point for Codex and Prime Agent, which read this file natively. Claude Code reads
`CLAUDE.md`; the two overlap deliberately, because an agent that opens only one of them
must still be equipped.

⛔ **Every count and claim here is re-derivable. Run the command; never carry a number
forward from prose.** This project has lost a full investigation cycle to a stale doc.

---

## What this is

A CLI and Python toolkit that takes a book (PDF or EPUB) and produces a copy with
AI-generated margin annotations in the voice of a prior owner — by default the Half-Blood
Prince, a young Severus Snape scrawling in his Potions textbook.

Two things are separable and must stay separable: **finding a quoted passage** (the
placement contract, deterministic, testable offline) and **generating a note worth reading**
(a model call). A resolved quote does not prove the note is any good.

## What done means

[`GATES.md`](GATES.md). Six gates, four met as of 2026-09-08. Read it before proposing
work; it is the definition of done this project ran 34 sessions without.

```sh
node ~/dev-harness/scripts/unlazy/gate-check.mjs --status GATES.md   # report only
```

## Build & verify — recorded 2026-09-11 by `setup-harness`

Methodology: `~/dev-harness/core/HARNESS.md`; Codex mechanism: `~/dev-harness/adapters/cross-harness.md`. ⛔ A fact belongs in exactly one layer: doctrine there, this repo's gotchas here.

**The gate**, stop at the first red: the first three commands under "Verify by running" below — `ruff`, then `mypy`, then `pytest tests/ -q` — the same three `.github/workflows/ci.yml` runs, on one interpreter. CI runs them on a 3.11/3.12/3.13 matrix and adds a separate `wheel` job, so a local green is necessary, not sufficient. The commands are spelled once, there, with the `pytest` vs `python -m pytest` trap beside them.

**What the gate does not cover.** The other two interpreters and the `wheel` job (`scripts/wheel_smoke.py`), which CI runs and this does not; `scripts/benchmark_placement.py`, which CI runs after the tests; the eval harness's real-pipeline path, exercised by hand only. `ci.yml` records the one case where a full-checkout green went red in CI (`tests/test_stress_evidence.py` needs `fetch-depth: 0`). Skips: `tests/test_real_book_placement.py` (module-level) and one test in `test_epub_inline_extraction.py` skip when `tests/corpora/real/` is absent — the corpus is tracked, so a clean clone has zero skips, but a green from a partial checkout has proven nothing about placement; `test_web_preview_editing_js.py` skips without `node`. Run with `-rs` and read the skip lines. A count with no selector is not a count: run from the repo root, `tests/`, nothing narrower.

**Pre-commit ladder:** the gate → secrets grep on the staged diff (`git diff --cached | grep -inE 'sk-or-v1|api[_-]?key|secret'`) → `git diff --cached --stat` read by eye.

**Shared checkout** (`git worktree list`: two live peers under `~/prime-agent-lab/wt/`, plus five stale Windows-side registrations whose checkout is gone — prune when you choose): one writer at a time, no `git stash`, no `git checkout -- <file>`, no formatter-wide runs (`core/HARNESS.md` §6).

**Money path — where a wrong number reaches a person:** `docs/evidence/**` (frozen run reports, `receipts.json` cost accounting), `examples/*.report.json`, `eval/eval_harness.py` metrics, `scripts/benchmark_placement.py` output. The first two are `Edit(...)`-denied in `.claude/settings.json`, which covers the Edit and Write tools (measured) but not a script that writes them — `Bash(python -c:*)` is allowed. Regenerating them is a deliberate act with a reviewer on the diff, whatever the tier.

**Layout, deliberately not the harness default:** `GATES.md` is committed project state — the definition of done — not the harness's gitignored task ledger. Do not gitignore it. Handoffs live in `HANDOFF.md` at root; plans in `docs/plans/`.

## The rule that matters most

⛔ **No gate, benchmark, or acceptance test runs on a fixture.**

Every EPUB fixture in this repo has a chapter under the 50,000-character `MAX_INPUT_CHARS`
bound (`src/halfblood/documents/matching.py`). A real book does not. `tests/corpora/real/`
holds *The Elements of Style* — an 83,063-character chapter across 1,089 blocks — plus two
frozen annotation plans, so placement is measurable with **no model call, no network, and
no API key**.

Before that corpus existed, `annotate` shipped a book containing **zero annotations** while
2,071 tests stayed green. A fixture-only suite could not see it.

## Two defects fixed 2026-09-08

Evidence: [`docs/evidence/2026-09-07-real-book-placement-failure.md`](docs/evidence/2026-09-07-real-book-placement-failure.md)

1. **The bound was applied to the wrong unit.** `render_plan` passed a whole chapter to
   `resolve_epub_quote`, which is contracted to resolve "within one reflowable EPUB inline
   DOM run" and whose bound counts **all** descendant text. Every annotation on a real book
   was refused before matching. `_resolve_bounded` now tries the chapter first (so small
   chapters are unchanged) and falls back to leaf blocks, returning `AMBIGUOUS` on more than
   one hit rather than taking a first hit. The PDF path was never affected — it bounds per
   page, which is its matching unit.

2. **Inline markup became a line break.** `_html_to_text` inserted a newline between every
   *text node*, so `<i>hers</i>, <i>its</i>` reached the model as `hers\n,\nits`. The model
   quoted that faithfully and placement correctly refused a string that does not exist in
   the document. Only block-level elements break a line now.

⚠ **Keep skip reasons truthful.** A bound refusal used to be reported as `MISSING_TARGET` —
the code for "the model quoted loosely" — and that mislabel aimed the diagnosis at the model
for six weeks. If you add a skip path, do not collapse a distinct reason into a generic one.

## Cost rules — read before any model call

⛔ **Free models only. Ask before any paid call.** Owner's standing instruction.

`.env` holds a **zero-spend OpenRouter key on purpose**: free models return 200, paid return
**403 "Key limit exceeded"**. That is the feature — it makes overspending structurally
impossible. **Do not "fix" the 403 by swapping in a paid key.**

✅ **RETRACTED 2026-09-08: free models CAN generate annotations.** The earlier entry here
said no free model on this account could, measured across two models and all three
`--structured-output` modes. The measurement was real; the conclusion named the wrong cause.
`annotation_generator.py` asked for **2048** output tokens per page and the provider seam
escalates once to 4096 without reaching its own 8192 ceiling. A reasoning model spends that
budget on reasoning tokens, so the payload was cut off mid-object every time. Re-measured on
one real page, `function` mode, nothing else changed:

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
five is a working transport and a weak generator. Budget lives in `DEFAULT_MAX_OUTPUT_TOKENS`, override with
`HALFBLOOD_MAX_OUTPUT_TOKENS`. Raising it costs nothing: providers bill actual output tokens
and this is only an upper bound.

⚠ **Probe with the task shape, not a ping** — still true, and it is not the whole rule. A
probe that holds the failing variable fixed measures the variable, not the cause. **Vary the
local knob before blaming the vendor.**

## Verify by running

All offline, no key required:

```sh
.venv/bin/ruff check src tests eval scripts     # CI lints scripts/ too
.venv/bin/mypy src/halfblood
.venv/bin/pytest tests/ -q                      # CI runs bare pytest, not python -m pytest
.venv/bin/python scripts/benchmark_placement.py # the guarantee, not a render count
.venv/bin/python scripts/wheel_smoke.py         # builds a wheel, installs it outside the
                                                # repo, annotates the REAL book
```

⚠ **`pytest` and `python -m pytest` are not equivalent** — only the latter puts the cwd on
`sys.path`. CI runs the former. `pyproject.toml` sets `pythonpath = ["."]` so they agree;
do not remove it. See [`LESSONS.md`](LESSONS.md), which records four defects that all share
one shape: **the thing that verified was not the thing that ships.**

## The ambiguity cost, measured

`_resolve_bounded` performs many leaf-block searches where there was one chapter search, so a
quote unique inside a chapter can collide across blocks. It fails closed on multiple hits and
cannot misplace a note; the cost is notes the reader never sees. **Measured 2026-09-08:**
`plan-snape.json` places 5/8 (three `missing_target`), `plan-editor.json` places 6/8 with
**two `ambiguous_target`** — two of sixteen, 12.5%. Gate **G6** pins that ceiling alongside
the placement floor. The ceiling is a measurement, not a target: if it rises, fix the
resolver rather than the number.

## Boundaries

- **Do not reopen** `HBP-ROADMAP-OX.md`'s decision to drop the persona-voiced study tool as
  a product ambition. Notes read by their author are n≈1, the same shape that decision
  discounted.
- **Public claims describe engineering, not output quality**
  (`~/project-ops/workstreams/portfolio/DECISIONS.md`, 2026-08-22 — that file is in the ops
  hub, not in this repo).
  Output quality is unproven at n≈1.
- The repository is **private**. Making it public is the owner's call alone.
- `.pdf` and `.epub` only (`cli.py`). HTML is out of scope by decision, not by defect.
- Legacy helpers (`_search_variants`, `_locate_text`, `render_annotations`) are compatibility
  code **outside** the placement contract. Do not use their recovery rates as evidence.
