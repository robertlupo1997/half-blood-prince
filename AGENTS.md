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

[`GATES.md`](GATES.md). Five gates, three met as of 2026-09-08. Read it before proposing
work; it is the definition of done this project ran 34 sessions without.

```sh
node ~/dev-harness/scripts/unlazy/gate-check.mjs --status GATES.md   # report only
```

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

⛔ **No free model on this account can generate annotations.** Measured 2026-09-08 across two
models and all three `--structured-output` modes (`function`, `json-schema`, `prompt`):
every combination failed — truncated at max_tokens, "response was incomplete", or "contained
no JSON object". Cutting the ask from 8 annotations to 2 changed nothing, so it is not
payload size. The same prompt on a paid model succeeds.

⇒ Free models are fine for reading, judging, review, and bulk analysis. **Budget a paid
model for anything that must emit a schema-valid object, and say so before the run.**

⚠ **Probe with the task shape, not a ping.** A model that answers "reply with ALIVE" can
still fail every page of structured generation. That exact gap cost a 13-minute run.

## Verify by running

All offline, no key required:

```sh
.venv/bin/pytest tests/ -q                      # CI runs bare pytest, not python -m pytest
.venv/bin/ruff check src tests eval scripts     # CI lints scripts/ too
.venv/bin/mypy src/halfblood
.venv/bin/python scripts/benchmark_placement.py # the guarantee, not a render count
.venv/bin/python scripts/wheel_smoke.py         # builds a wheel, installs it outside the
                                                # repo, annotates the REAL book
```

⚠ **`pytest` and `python -m pytest` are not equivalent** — only the latter puts the cwd on
`sys.path`. CI runs the former. `pyproject.toml` sets `pythonpath = ["."]` so they agree;
do not remove it. See [`LESSONS.md`](LESSONS.md), which records four defects that all share
one shape: **the thing that verified was not the thing that ships.**

## Known-untested risk

`_resolve_bounded` performs many leaf-block searches where there was one chapter search. It
fails closed on multiple hits, but whether real books surface collisions the chapter-scoped
call never had to disambiguate is **unmeasured**. A gate counting `ambiguous_target` skips
would close it.

## Boundaries

- **Do not reopen** `HBP-ROADMAP-OX.md`'s decision to drop the persona-voiced study tool as
  a product ambition. Notes read by their author are n≈1, the same shape that decision
  discounted.
- **Public claims describe engineering, not output quality** (`DECISIONS.md`, 2026-08-22).
  Output quality is unproven at n≈1.
- The repository is **private**. Making it public is the owner's call alone.
- `.pdf` and `.epub` only (`cli.py`). HTML is out of scope by decision, not by defect.
- Legacy helpers (`_search_variants`, `_locate_text`, `render_annotations`) are compatibility
  code **outside** the placement contract. Do not use their recovery rates as evidence.
