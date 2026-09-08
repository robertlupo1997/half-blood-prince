# A 50,000-character bound silently discards every annotation on a real book

Found 2026-09-07 by running the owner's stated end-goal end-to-end on a real book.
Supersedes an earlier draft of this file that blamed block-boundary scoping; the reason
codes disproved that. The mechanism below is the isolated one.

## The finding in one line

`EpubProcessor.render_plan` resolves quotes against a whole chapter. Any chapter over
`MAX_INPUT_CHARS = 50_000` refuses **every** annotation in it before matching is
attempted, and the pipeline mislabels the refusal as `missing_target` — which is why
this was diagnosed for weeks as a model-quoting problem.

## What was run

*The Elements of Style*, William Strunk (1918, Project Gutenberg #37134), EPUB. A
genuine methods book, so "how to do better at the method it teaches" has real material.

```
halfblood annotate elements.epub -o elements-snape.epub \
  --provider openrouter --model anthropic/claude-sonnet-5 --max-per-page 8 --force
```

Credential: the working OpenRouter key in `~/.prime/agent/auth.json`. The key in the
repo's own `.env` returns `401 API key expired` — expired, not out of credit. That is
the `401` carried in the handoffs as a blocker since roughly session 31.

```
Tokens: 31544 in / 1661 out
render_plan: rendered 0, skipped 8
Rendered 0 / Skipped 8          all eight: reason "missing_target"
```

**The owner's exact hypothesis, run end to end, produces a book with zero annotations.**

## The mechanism, isolated

`src/halfblood/documents/matching.py:35`

```python
MAX_INPUT_CHARS = 50_000
```

`src/halfblood/epub_processor.py:641-648` passes an entire chapter as the search root:

```python
chapter_root: Tag = soup.body or soup
...
result = resolve_epub_quote(chapter_root, ann.target, fixed_layout=...)
```

Document sizes in this book:

| document | body text | blocks |
|---|---|---|
| `...37134-h-0.htm.xhtml` | **83,063 chars** | 955 |
| `...37134-h-1.htm.xhtml` | 18,429 chars | 52 |
| `toc.xhtml` | 1,777 chars | 82 |
| `wrap0000.xhtml` | 6 chars | 1 |

All eight annotations targeted the 83,063-character document. Resolving each against
that chapter root returns, for every one of the eight:

```
unresolved / input_limit_exceeded
```

Not `quote_not_found`. Not `ambiguous`. The bound is hit and the resolver refuses
without looking. `docs/placement-contract.md:156` lists `input_limit_exceeded` as a
documented reason code, so the resolver is behaving to contract — it is the caller that
hands it an out-of-bounds input.

Against the other three documents the same quotes return `quote_not_found`, correctly:
the text is not in them.

## The mislabel is why nobody found it

`src/halfblood/epub_processor.py:655-661` collapses every non-resolved, non-ambiguous,
non-unsupported outcome into one skip reason:

```python
skip_reason_for[idx] = (
    SkipReason.AMBIGUOUS_TARGET       if result.status is PlacementStatus.AMBIGUOUS
    else SkipReason.UNSUPPORTED_RENDERER if result.status is PlacementStatus.UNSUPPORTED_RENDERER
    else SkipReason.MISSING_TARGET
)
```

`input_limit_exceeded` becomes `MISSING_TARGET`. The reason code the contract went to
the trouble of defining is discarded at the one place a user would read it.

That mislabel has an audit trail. A prior handoff records: *"Real cause of EPUB skips is
diagnosed, not built: 6/50 all MISSING_TARGET from non-verbatim model quoting."* On a
real book, `MISSING_TARGET` does not mean the model quoted loosely. It means the chapter
was too big to search. The wrong label pointed a diagnosis at the model for weeks.

## The same engine places 5 of 8 when given a bounded root

Same eight quotes, same `lxml` parser as the shipping path, searched block by block:

| root passed to `resolve_epub_quote` | quote as generated | whitespace collapsed |
|---|---|---|
| `soup.body` — **what ships** | **0/8** | 0/8 |
| block-level (`<p>`, `<li>`, …) | **5/8** | 5/8 |

Whitespace normalization changes nothing. A control quote taken from inside one block
resolves against that block, so the resolver works when called within its bounds.

The remaining 3 of 8 fail for a second, unrelated reason: the extractor hands the model
`hers\n,\nits\n,\ntheirs\n` for `<em>hers</em>, <em>its</em>`, so the model faithfully
quotes a string that never exists as contiguous document text.

## Why 2,071 green tests did not catch it

| EPUB | blocks | largest body |
|---|---|---|
| `tests/fixtures/.../sample_book.epub` | **6** | far under the bound |
| `tests/fixtures/.../reader_lab_epub3.epub` | 20 | under |
| `tests/fixtures/.../reader_lab_epub2.epub` | 37 | under |
| `examples/src/alice.epub` | 94 | under |
| `examples/hbp-example.epub` | 96 | under |
| *The Elements of Style* | **1,089** | **83,063 — over** |

No fixture or example in the repository has a chapter that exceeds 50,000 characters, so
no test ever exercises the branch. The "48/50 EPUB recovery" figure in the handoffs
describes the fixture corpus, not a book.

This is the shape already recorded three times in `LESSONS.md`: **the thing that verified
was not the thing that ships.**

## The notes themselves are good — both personas

This is the owner's stated quality bar: his own read of the notes. Run twice as agreed,
default persona and `--persona-name editor`.

**Default (Half-Blood Prince / Snape):**

| Strunk | note |
|---|---|
| "Being in a dilapidated condition, I was able to buy the house very cheap." | "The house was dilapidated, not the buyer. Even a first-year should see it." |
| "Vigorous writing is concise. A sentence should contain no unnecessary words…" | "Then why does this book run fifty pages saying it?" |
| "This rule is difficult to apply; it is frequently hard to decide whether a single word…" | "He admits the rule is soft, then spends three pages pretending otherwise." |
| "the fact that should be revised out of every sentence in which it occurs." | "True, and the only rule in this section worth remembering without footnotes." |

**`--persona-name editor`:**

- "'Very' is the student's confession that he couldn't find the right adjective."
- "Negation is the writer's alibi. State what happened; let the reader supply what didn't."
- "Double passive is where meaning goes to die. Read the sentence aloud — you'll hear the corpse."
- "Note the sentence obeys its own rule. Rare."

Both are in voice, about the actual argument, and correct.

**A predicted defect that did not appear.** A reviewer observed, correctly, that
`ANNOTATION_CRAFT` is appended unconditionally (`annotation_generator.py:261-263`), so
every persona receives Potions-flavoured craft examples including "Try Sectumsempra
instead — my own," and predicted the editor persona would leak that vocabulary. Scanning
all eight editor notes for `sectumsempra, cauldron, potion, spell, wand, snape,
hogwarts, first-year, incantation, stir`: **none detected.** The model treats those
examples as format, not content. The source-level observation is right; the behavioural
prediction is not. Only running it settled that.

## A second, smaller defect

`halfblood annotate --help` states: *"Every run streams to `<output>.plan.json` (e.g.
out.pdf.plan.json)."* After a completed run writing `elements-snape.epub`, the directory
contains `elements-snape.epub` and `elements-snape.epub.report.json` and **no
`.plan.json`**. Either the checkpoint is not written on the EPUB path or the documented
behaviour is wrong. It cost a second identical paid generation to recover the plan.

## What is verified and what is not

Verified by running:
- 0/8 placed by the shipping pipeline; all eight reported `missing_target`.
- The true reason for all eight is `unresolved / input_limit_exceeded`.
- `MAX_INPUT_CHARS = 50_000`; the target document is 83,063 characters.
- `input_limit_exceeded` is collapsed to `MISSING_TARGET` at `epub_processor.py:655-661`.
- 5/8 resolve against a block-level root; whitespace is irrelevant; the control resolves.
- No fixture or example in the repo exceeds the bound.
- Note quality on two personas, read by a human.
- No Potions leak in the editor persona.

**The PDF path is safe, and it shows what the fix should be.** Verified after the first
draft of this file, which listed it as unknown.

`placement.py:167-174` applies the identical `MAX_INPUT_CHARS` check to PDF — but to
`page.get_text("text")`, one **page** at a time:

| PDF | pages | largest page | over the 50,000 bound |
|---|---|---|---|
| `examples/src/alice.pdf` | 78 | 2,267 chars | 0 |
| `examples/hbp-example.pdf` | 78 | 2,293 chars | 0 |

A page has roughly 20x headroom against the bound. A chapter does not.

⇒ **The defect is EPUB-specific, and it is a choice of unit.** PDF resolves against a page;
EPUB resolves against a whole chapter, which on a real book is the size of a small book.
The fix is not a new mechanism — it is making the EPUB path resolve against a bounded unit
the way the PDF path already does.

Not verified:
- Whether resolving per block introduces ambiguity that the chapter-scoped call avoided.
  The contract has an `ambiguous` outcome for a reason, and 955 independent block
  searches may surface collisions the disambiguation ladder must handle. **This is the
  main risk in any fix.**
- Note quality beyond eight notes per persona on one book.
- Whether the 3-of-8 inline-markup failure has the same cause on PDF.

## Reproduce

```
scratchpad/elements.epub                     the book
scratchpad/plan-snape.json                   8 notes, default persona
scratchpad/plan-editor.json                  8 notes, --persona-name editor
scratchpad/elements-snape.epub.report.json   the 8 missing_target skips
```

Total model spend for everything above: roughly $0.18 across three generations
(one render run plus two dry runs, the second of which was only needed because the
checkpoint was missing).
