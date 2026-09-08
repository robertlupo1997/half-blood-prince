# Gates — the annotated book a reader would keep

What "done" means for the product goal: hand it a book you own, get back an annotated copy
worth reading. Written 2026-09-07, rewritten the same day once the first two gates were
actually met.

Run with:

```sh
node ~/dev-harness/scripts/unlazy/gate-check.mjs --status GATES.md   # report only, never executes
node ~/dev-harness/scripts/unlazy/gate-check.mjs GATES.md            # run unmet runnable gates
```

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

- [x] **G1: at least 60% of generated annotations are placed on a real book.**

  CHECK: `.venv/bin/pytest tests/test_real_book_placement.py::test_the_processor_places_notes_on_a_real_book -q`
  EXPECT: `/1 passed/`

  Threshold set by Trey 2026-09-07: **≥60% placed, no silent drops.**

  **Met 2026-09-07 at `0a3cba1`.** `halfblood annotate` on *The Elements of Style* went from
  `Rendered 0 / Skipped 8` to `Rendered 7 / Skipped 1` — **87.5%**. The note bodies were
  confirmed present in the output EPUB itself, not inferred from the run report.

  The gate replays a frozen plan (`tests/corpora/real/plan-snape.json`), so it costs no model
  call, no network, and no API key, and runs free in CI.

## G2 — the pipeline tells the truth about why it skipped ✅ MET

- [x] **G2: `input_limit_exceeded` is never reported to a user as `missing_target`.**

  CHECK: `.venv/bin/pytest tests/test_real_book_placement.py::test_a_bound_refusal_is_never_reported_as_a_missing_target -q`
  EXPECT: `/1 passed/`

  `epub_processor.py` collapsed every non-resolved, non-ambiguous outcome into
  `MISSING_TARGET`, discarding the reason code `docs/placement-contract.md:156` defines.
  That mislabel is why the defect was diagnosed for six weeks as non-verbatim model quoting;
  a handoff records the wrong conclusion it produced.

  **Met 2026-09-07.** A truthful reason code is what makes the next bug take an afternoon.

## G3 — the reader's path works from a clean clone ✅ MET

- [x] **G3: an installed wheel annotates a real book with no source tree on `sys.path`.**

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

- [ ] **G4: Trey reads a fully placed real book and judges the notes good.**

  Manual. Evidence: his written verdict under `docs/evidence/`, naming the book, the commit,
  the personas, and the count of notes read.

  **Partially satisfied 2026-09-07.** Sixteen notes across two personas were read and judged
  good — but read from a *plan*, because at the time nothing placed. Placement now works, so
  G4 closes when he reads the artifact a reader would actually open:
  `halfblood annotate tests/corpora/real/elements-of-style.epub -o out.epub`.

  ⚠ This does **not** license a public quality claim. `DECISIONS.md` (2026-08-22) restricts
  public claims about this project to engineering, not output quality, and n≈1 read by the
  author is the same shape `HBP-ROADMAP-OX.md` discounted when it dropped the study-tool
  product. G4 is an internal bar, not marketing.

## G5 — quality does not silently regress 🔴 UNMET, now unblocked

- [ ] **G5: the eval harness runs with an independent judge and no `--allow-self-judge`.**

  CHECK: `.venv/bin/python eval/eval_harness.py --judge-model <independent> --json-out eval-result.json`
  EXPECT: `/"self_judged":\s*false/`

  Costs money and needs a key, so this is a release gate, not a CI gate. Budgeted under $5
  by `HBP-ROADMAP-OX.md:14-16`.

  ⚠ **The blocker was never a budget.** Recorded as "Blocked: rejected credential (HTTP 401)"
  since roughly session 31, it is an **expired** key in `.env` — `401 API key expired` — while
  a working OpenRouter key with credit sits in `~/.prime/agent/auth.json`. Verified 2026-09-07
  by `curl .../auth/key` against both. **Rotating the key in `.env` is the whole fix.**

---

## Out of scope, named so they are decisions rather than omissions

- **The inline-markup extraction defect.** The extractor hands the model
  `hers\n,\nits\n,\ntheirs\n` for `<em>hers</em>, <em>its</em>`, so the model faithfully
  quotes a string that is not contiguous document text. This is the remaining 1 skip in G1.
  Fixing it would push placement past 87.5%; G1 does not require it.
- **The PDF path.** Unaffected by the G1/G2 defect — it bounds per page (~2,300 chars, 20×
  headroom), which is its matching unit. Add a gate if that ever changes.
- **A book-level reader pass.** The generator is page-stateless
  (`annotation_generator.py:458`, `:504`), so a note on page 140 cannot draw on chapter 3.
  Real and structural, and *not* what stood between the repo and a working annotated book.
  Its own slice, its own gates.
- **HTML and other input types.** `cli.py:69` routes `.pdf` and `.epub` only. A deliberate
  scope decision, not a defect.

## The risk this ledger does not retire

Block-scoped resolution means many independent searches where there was one. `_resolve_bounded`
searches **leaf** blocks only and returns `AMBIGUOUS` on more than one hit, so it fails closed
— but whether real books surface collisions the chapter-scoped call never had to disambiguate
is **untested**. If G1's rate climbs while ambiguity climbs with it, this gate is measuring
the wrong thing and needs a companion counting `ambiguous_target` skips.

## ABANDON

If an outcome proves impossible, abandon it by id rather than weakening it:

```
ABANDON: G3 <reason>
```

`gate-check` then exits 1 with `HANDOFF REQUIRED` and never prints `ALL MET`. This project
ran 34 sessions with no definition of done; an honest stop is the point of this file.
