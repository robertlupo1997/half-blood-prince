# Gates — the annotated book a reader would keep

What "done" means for the product goal: hand it a book you own, get back an annotated copy
worth reading. Written 2026-09-07, rewritten the same day once the first two gates were
actually met.

Run with:

```sh
node ~/dev-harness/scripts/unlazy/gate-check.mjs --status GATES.md   # report only, never executes
node ~/dev-harness/scripts/unlazy/gate-check.mjs GATES.md            # run unmet runnable gates
```

⚠ **Read this before trusting a checkbox. Fixed and measured 2026-09-08.**

**The runner had never parsed this file.** Every gate id came back
`invalid gate id **G1` — the parser reads the id before the first colon, and `**G1` is not
an id. That was true of all five original gates from the day they were written, so no
`[x]` in this file has ever been confirmed by the tool the file tells you to run. The
headers now read `- [x] G1: **…**`, and the runner parses all six.

**The checkboxes are still hand-asserted.** `--status` now reports
`UNMET: 6 (met: 0)`, because a checked gate is only *met* to the runner once its `CHECK:`
has been approved and run, which writes an `EVIDENCE:` line back. Nothing here has one yet.

⛔ **Approving is Trey's call, not an agent's.** `--approve` takes no per-gate selection: it
approves every pending oracle at once, **including G5's, which is the paid one**, and the
approval persists outside this repository under `~/.unlazy/approved`. An agent granting that
is granting itself a standing authorization to spend. G1, G2, G3, and G6 are free and
offline and were each run directly this session; G5 is the only one that costs anything.

## The binding rule: no gate runs on a fixture

Measured 2026-09-07. Every EPUB fixture in this repository is under the 50,000-character
`MAX_INPUT_CHARS` bound; a real book is not.

| corpus | blocks | largest chapter | over the bound |
|---|---|---|---|
| `tests/fixtures/.../sample_book.epub` | 6 | far under | no |
| `examples/src/alice.epub` | 94 | under | no |
| `tests/corpora/real/elements-of-style.epub` | 1,089 | 83,063 chars | **yes** |

Every gate this project could have written against its fixtures would have been green while
`annotate` shipped a book containing zero annotations. **Every gate here runs against a real
book.** Corpus and provenance: `tests/corpora/real/`.

## A note on who writes these

`dev-harness/docs/research/2026-08-31-unlazy-evaluated.md` §4 measured the hole in this
mechanism: an agent that authors its own gate can write `node -e "console.log('passed')"`,
and it lints clean, passes, and writes real evidence while measuring nothing. The defense is
a second party reading the `CHECK:` line.

⚠ An earlier draft of this file answered that by requiring Trey to approve all five
`CHECK:` lines before any code was written. A reviewer pointed out the obvious problem:
owner gates are already this project's bottleneck — Vercel since Aug 23, FerroML publish
since Jul 13 — so adding five more is the wrong direction. **The gates below are therefore
written to be checkable by a machine and falsifiable by anyone reading them**, not to be
approved in advance. G4 is the single exception, and it is manual because taste cannot be
automated, not as a control.

---

## G1 — a real book gets its notes placed ✅ MET

- [x] G1: **at least 60% of generated annotations are placed on a real book.**

  CHECK: `.venv/bin/pytest tests/test_real_book_placement.py::test_the_processor_places_notes_on_a_real_book -q`
  EXPECT: `/1 passed/`

  Threshold set by Trey 2026-09-07: **≥60% placed, no silent drops.**

  **Met 2026-09-07 at `0a3cba1`.** `halfblood annotate` on *The Elements of Style* went from
  `Rendered 0 / Skipped 8` to placing the majority of its notes, and the note bodies were
  confirmed present in the output EPUB itself rather than inferred from the run report.

  ⚠ **Corrected 2026-09-08. This paragraph claimed `Rendered 7 / Skipped 1` — 87.5% — and
  that number is not reproducible from anything committed.** Replaying the frozen plans at
  `85334d5` gives `plan-snape.json` **5/8** (three `missing_target`) and `plan-editor.json`
  **6/8** (two `ambiguous_target`). The gate below asserts ≥5 and passes; the prose asserted
  a number the gate never checked, which is the exact shape this file exists to prevent. The
  87.5% probably came from a live model run whose plan was never frozen — plausible, and not
  evidence. **The honest figure is 5/8 = 62.5%, still above the 60% bar.**

  The gate replays a frozen plan (`tests/corpora/real/plan-snape.json`), so it costs no model
  call, no network, and no API key, and runs free in CI.

## G2 — the pipeline tells the truth about why it skipped ✅ MET

- [x] G2: **`input_limit_exceeded` is never reported to a user as `missing_target`.**

  CHECK: `.venv/bin/pytest tests/test_real_book_placement.py::test_a_bound_refusal_is_never_reported_as_a_missing_target -q`
  EXPECT: `/1 passed/`

  `epub_processor.py` collapsed every non-resolved, non-ambiguous outcome into
  `MISSING_TARGET`, discarding the reason code `docs/placement-contract.md:156` defines.
  That mislabel is why the defect was diagnosed for six weeks as non-verbatim model quoting;
  a handoff records the wrong conclusion it produced.

  **Met 2026-09-07.** A truthful reason code is what makes the next bug take an afternoon.

## G3 — the reader's path works from a clean clone ✅ MET

- [x] G3: **an installed wheel annotates a real book with no source tree on `sys.path`.**

  CHECK: `.venv/bin/python scripts/wheel_smoke.py 2>&1 | grep -c "real book"`
  EXPECT: `/^[1-9]/`

  **Met 2026-09-07.** `scripts/wheel_smoke.py` now builds the wheel, installs it into a
  throwaway venv outside the repo with the repo off `sys.path`, and uses the **installed
  CLI** to annotate the real book with `--provider stub`. It asserts the run exits 0 **and
  that at least one annotation is placed** — a `rendered=0` there is exactly what shipped
  before the bounded-root fix, so this guard has a failing state that really happened.

  No model, no network, no API key: the stub provider picks its target from the page text.

  ⚠ **The first draft of this gate was worse than red — it was a false green.** It ran
  `scripts/wheel_smoke.py --real-book` / EXPECT `WHEEL SMOKE PASSED`. The script took no
  such flag, ignored it silently, ran on fixtures, and passed. That is precisely the failure
  `2026-08-31-unlazy-evaluated.md` §4 documents, authored here by the same agent that then
  implemented the fix — the argument for that section in one paragraph. Kept in the file
  rather than quietly corrected.

## G4 — the notes are worth reading ⚠ PARTIAL

- [ ] G4: **Trey reads a fully placed real book and judges the notes good.**

  Manual. Evidence: his written verdict under `docs/evidence/`, naming the book, the commit,
  the personas, and the count of notes read.

  **Partially satisfied 2026-09-07.** Sixteen notes across two personas were read and judged
  good — but read from a *plan*, because at the time nothing placed.

  ✅ **The artifact now exists, and it cost nothing.** Generated 2026-09-08 at `0a35381`
  from `tests/corpora/real/elements-of-style.epub`, default Snape persona, on
  `nvidia/nemotron-3.5-lightning:free` with `HALFBLOOD_MAX_OUTPUT_TOKENS=32000`:
  **`Rendered 5 / Skipped 0`** — every generated annotation placed. 21,214 tokens in,
  7,660 out, 3m09s, **$0.00**. Run report frozen at
  `docs/evidence/2026-09-08-free-model-real-book-run.report.json`; the five note bodies were
  read out of the output EPUB itself, not inferred from the report. File handed to Trey as
  `~/elements-of-style-annotated.epub`.

  ⚠ The earlier plan for this gate was a ~$0.10 paid generation, on the belief that no free
  model could generate. That belief was a hardcoded `max_tokens=2048` in this repository.

  **G4 now waits only on Trey reading it.** Five notes is a thin read; if that is too few to
  judge, raise `--max-per-page` and regenerate — still free.

  ⚠ This does **not** license a public quality claim.
  `~/project-ops/workstreams/portfolio/DECISIONS.md` (2026-08-22) restricts public claims
  about this project to engineering, not output quality, and n≈1 read by the
  author is the same shape `HBP-ROADMAP-OX.md` discounted when it dropped the study-tool
  product. G4 is an internal bar, not marketing.

## G5 — quality does not silently regress 🔴 UNMET, now unblocked

- [ ] G5: **the eval harness runs with an independent judge and no `--allow-self-judge`.**

  CHECK: `.venv/bin/python eval/eval_harness.py --judge-model <independent> --json-out eval-result.json`
  EXPECT: `/"self_judged":\s*false/`

  Costs money and needs a key, so this is a release gate, not a CI gate. Budgeted under $5
  by `HBP-ROADMAP-OX.md:14-16`.

  ⚠ **Corrected 2026-09-08. The instruction that stood here was to rotate the key in `.env`,
  and following it now would break a standing decision.** `.env` holds a **deliberate
  zero-spend key** — free models return 200, paid return 403 — so that overspending is
  structurally impossible rather than a matter of an agent remembering (`.env`'s own comment,
  2026-09-07; `AGENTS.md` "Cost rules"). The earlier note described the key that was there
  before that decision, an expired one returning `401`.

  **The fix is to pass a paid key for that single command, after asking the owner** — never
  to write one into `.env`:

  ```sh
  OPENROUTER_API_KEY=<paid key> .venv/bin/python eval/eval_harness.py --judge-model <independent> ...
  ```

---

## Out of scope, named so they are decisions rather than omissions

- **The inline-markup extraction defect.** The extractor hands the model
  `hers\n,\nits\n,\ntheirs\n` for `<em>hers</em>, <em>its</em>`, so the model faithfully
  quotes a string that is not contiguous document text. It accounts for the `missing_target`
  skips in G1's frozen plan. Fixing it would push placement above the measured 5/8; G1 does
  not require it.
- **The PDF path.** Unaffected by the G1/G2 defect — it bounds per page (~2,300 chars, 20×
  headroom), which is its matching unit. Add a gate if that ever changes.
- **A book-level reader pass.** The generator is page-stateless
  (`annotation_generator.py:458`, `:504`), so a note on page 140 cannot draw on chapter 3.
  Real and structural, and *not* what stood between the repo and a working annotated book.
  Its own slice, its own gates.
- **HTML and other input types.** `cli.py:69` routes `.pdf` and `.epub` only. A deliberate
  scope decision, not a defect.

## G6 — safety has a price, and the price is counted ✅ MET

- [x] G6: **`ambiguous_target` skips on a real book stay at or below the measured ceiling,
  and placement stays at or above the measured floor.**

  CHECK: `.venv/bin/pytest tests/test_real_book_placement.py -q -k "ambiguity or ambiguous_refusal"`
  EXPECT: `/3 passed/`

  **The risk this ledger carried as untested is now measured, and it is not zero.**
  Block-scoped resolution means many independent leaf-block searches where there was one
  chapter search. `_resolve_bounded` fails closed, returning `AMBIGUOUS` rather than a first
  hit, so it cannot place a note in the wrong spot — but a quote that was unique inside one
  large chapter root can match several small blocks, and each collision is a note the reader
  does not get. Measured 2026-09-08 across both frozen plans:

  | frozen plan | rendered | skipped | reasons |
  |---|---|---|---|
  | `plan-snape.json` | 5/8 | 3 | all `missing_target` |
  | `plan-editor.json` | 6/8 | 2 | both **`ambiguous_target`** |

  **Two of sixteen annotations — 12.5% — are lost to collisions the chapter-scoped call
  never had to disambiguate.** Real books surface them. The answer to the open question is
  yes.

  The gate pins both numbers together, because a gate counting only ambiguity would pass
  vacuously the day every quote started failing for some other reason. Its failing state was
  demonstrated, not assumed: tightening the ceiling to 1 fails with the two colliding
  annotation ids named.

  Free — replays the frozen plans, no model call, no network, no key.

  ⚠ The ceiling is a **measurement, not a target**. If a future change pushes ambiguity up,
  the honest move is to report it and fix the resolver, not to raise the number here.

## ABANDON

If an outcome proves impossible, abandon it by id rather than weakening it:

```
ABANDON: G3 <reason>
```

`gate-check` then exits 1 with `HANDOFF REQUIRED` and never prints `ALL MET`. This project
ran 34 sessions with no definition of done; an honest stop is the point of this file.
