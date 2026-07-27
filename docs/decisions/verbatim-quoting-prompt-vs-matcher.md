# Recovering annotations lost to non-verbatim model quoting

**Date:** 2026-07-25
**Status:** decided, implemented (`96a715e`)
**Scope:** EPUB render path; the PDF path is untouched.

## Problem

The model does not quote character-for-character. Its `target_text` is used as a lookup
key against the book's own text, so any drift means the annotation is silently dropped.
Measured on a full real-model run over *The Strange Case of Dr. Jekyll and Mr. Hyde*:
**6 of 50 annotations (12%) skipped, every one `SkipReason.MISSING_TARGET`, zero
ambiguous.**

Raw character-level diffs of each skipped target against its source chapter:

| # | model wrote | book has | class |
|---|---|---|---|
| 1 | `the death of Sir Danvers` | `The death of Sir Danvers` | case only |
| 2 | `post; and only circulars by that, he added.` | `post; "and only circulars by that," he added.` | internal quotes dropped |
| 3 | `murderer! And his blood` | `murderer!" And his blood` | internal quote dropped |
| 4 | `"I have brought on myself` | ` I have brought on myself` | quote *added* by the model |
| 5 | `the radiance of a foul soul` | `the **mere** radiance of a foul soul` | word dropped |
| 6 | `to God, I swear to God` | `to God," cried the doctor, "I swear to God` | attribution elided |

Rows 1–4 are surface drift. Rows 5–6 are genuine paraphrase: the model produced text the
book does not contain.

## Options considered

1. **Prompt hardening** — instruct the model harder to copy verbatim. Upstream of the
   matcher, zero mis-anchor risk.
2. **Tolerance ladder in the matcher** — case-insensitive and punctuation-elastic
   comparison, keeping exact semantics.
3. **Bounded fuzzy recovery** — edit distance with a similarity threshold and a
   uniqueness check.

## Decision

**Ship (2). Reject (3). Try (1), measure it, and revert it.**

### Why not fuzzy

Fuzzy would have recovered exactly one more annotation than the ladder does — row 5 — and
it would have anchored it to a span beginning **in the middle of the word `mere`**. The
best window scored 0.979 against a runner-up of 0.000, so a uniqueness check would have
happily accepted it. A note anchored to the wrong words is worse than a missing note,
because a missing note is invisible while a misplaced one is read as intentional and the
reader has no way to detect the error. This follows the existing fail-closed precedent for
ambiguous PDF targets. One recovery out of fifty does not justify a similarity threshold
that has to be defended at n=4.

### Why the ladder is not "fuzzy with extra steps"

Every rung is exact-match semantics on a transformed comparison, not a score:

- `CASE_INSENSITIVE` uses a **length-preserving** fold. `str.casefold()` maps `ß`→`ss` and
  `İ`→two code points, which would desynchronise every `RawSpan` after the folded
  character; characters whose lowering changes length are deliberately left alone.
- `PUNCTUATION_ELASTIC` builds a bounded regex in which straight quote characters at token
  edges are optional **in both directions**. Interior apostrophes (`don't`) and every other
  punctuation mark stay literal — `;` does not match `:`.

Ambiguity remains a hard stop. The ladder advances only on a clean zero; a rung that finds
two candidates ends it. A quote that is ambiguous under exact matching is *more* ambiguous
under elasticity, so falling through to a looser rung is precisely how a note would land on
the wrong occurrence.

## Measured result

Deterministic, on the frozen plan from the original run:

| | rendered | skipped |
|---|---|---|
| before | 44 / 50 (88%) | 6 |
| after | **48 / 50 (96%)** | 2 |

All 44 previously-rendered anchors are byte-identical afterwards — no annotation
relocated. The 4 new anchors carry the source's own quote marks and capitalisation. The 2
remaining skips are rows 5 and 6, which is the intended outcome.

## The negative result: prompt hardening did not help

The prompt was extended with explicit anti-patterns drawn from the failures above — do not
add or remove quotation marks, do not skip words in the middle, keep interrupting dialogue
attributions, prefer a short exact fragment over a long approximate one — plus a matching
rewrite of the `target_text` field description in the tool schema.

Three generation runs of the same book on the same model, measuring the fraction of
generated targets that occur verbatim in the source with **no** matcher tolerance:

| run | prompt | verbatim rate | rendered under the ladder |
|---|---|---|---|
| A | original | 44/50 (88.0%) | 48/50 (96.0%) |
| B | hardened | 38/45 (84.4%) | 42/45 (93.3%) |
| C | original | 40/50 (80.0%) | 48/50 (96.0%) |

The original prompt's own run-to-run range is 80–88%. The hardened prompt's 84.4% falls
inside it, and its end-to-end render rate was the lowest of the three. **There is no
evidence the change helped, so it was reverted.**

Two things worth keeping from the experiment:

- Instructing the model to reproduce quotation marks exactly changed *which* mistake it
  made — run B substituted `'` for `"` rather than dropping quotes — but not *how often*.
  Both failure modes are recovered by the elastic rung, which is why the render rate barely
  moved.
- At n≈50 on a nondeterministic model, a single run cannot distinguish a real prompt
  improvement from noise. Any future prompt change aimed at this metric needs several
  paired runs before it means anything.

**Conclusion: the matcher, not the prompt, is the effective lever here.** The prompt
already said "exact, verbatim" twice before this experiment; saying it louder did nothing.

---

## Addendum (2026-07-26): what "a wrong anchor is worse than none" actually forbids

This document has been cited to justify dropping any annotation whose quote cannot be
matched in full. That is too strong, and a real scanned book showed the cost.

The principle is about anchors a reader **cannot interpret**. It is worth separating two
things the earlier text ran together:

- A **prefix** of the correct passage. The mark is shorter than the note's quote, but it
  begins exactly where the passage begins, so the reader's eye lands on the right words.
  This is honest and should render.
- A **lone word** from somewhere inside the passage. The note discusses a sentence, the
  mark sits on one word, and nothing distinguishes that from a correct anchor. This is the
  case the principle forbids.

`_exactness_tiers` makes the separation exact rather than a matter of taste: the ladder is
full quote → 8-word prefix → 5-word prefix → 3-word prefix → longest single word. Every
multi-word tier *is* a prefix; the single-word tier is the only one that can land anywhere.
So "reject lone-word anchors" is a structural predicate, not a tuned threshold.

### Why this needed a scanned book to see

The PDF path first shipped a `coverage >= 0.5` rule (`1c5e8ed`). That was correct on the
only corpus that existed — a clean PDF synthesised from the EPUB, where every legitimate
match sat at coverage 1.00 and the rule cost nothing.

A genuine OCR'd scan (Internet Archive `strangecaseofdrj00stevrich`, the 1886 edition,
151 pages with a text layer) behaves completely differently, because **the model silently
repairs OCR damage while quoting**. Handed a page reading `tlie sight of a pol`, it writes
`the sight of a policeman`; handed `mould- ings` broken across a line, it writes
`mould-ings`. The quote is faithful to the text as a human reads it and unfaithful to the
bytes, so the complete quote matches far less often — **53 of 88** on this book, against
48 of 50 on the clean one — and a prefix tier picks the passage up as far as the first
corrupted word.

Those prefixes are correct anchors. Measured over the same 88 real annotations:

| policy | clean corpus (50) | scanned corpus (88) | lone-word anchors admitted |
|---|---|---|---|
| `coverage >= 0.5` | 48 | **60** | 0 |
| `coverage >= 0.2` | 48 | 76 | 0 |
| **reject lone words** | **49** | **84** | **0** |
| both | 48 | 76 | 0 |

Rejecting lone words *dominates* — same protection, 24 more annotations on the scanned
book. A tuned constant trades; this one does not, which is the sign it is the right rule.

Caveat: the tier-0 rates above come from one generation run on one free-tier model. The
policy comparison does not depend on them, because the ranking holds at any rate.

### Former divergence from the EPUB path — now resolved

`documents/epub.py:locate_across_nodes` accepted **tier 0 only**, so on the same plan
EPUB rendered 48/50 where PDF rendered 49/50.  That divergence is resolved — see the
addendum below.

---

## Addendum (2026-07-27): EPUB prefix-tier fix

**Status:** decided, implemented.

### Decision

`locate_across_nodes` now mirrors the PDF rule exactly: after the complete-quote
tolerance ladder (EXACT → CASE_INSENSITIVE → PUNCTUATION_ELASTIC) finds nothing, it
tries multi-word prefix tiers (8-word → 5-word → 3-word) under EXACT matching.  The
lone-word tier is always rejected, for the same reason it is rejected on the PDF side.

The two phases are ordered, never pooled: a PUNCTUATION_ELASTIC full-quote match always
wins over an EXACT prefix match.  Ambiguity at the prefix level halts immediately.

### Measurement

The scanned corpus (88 annotations, 20 pages, Internet Archive Jekyll & Hyde OCR scan)
was measured with the frozen plan used for the PDF addendum above:

| path | rendered | skipped |
|---|---|---|
| EPUB baseline (tier-0 only) | 53 / 88 (60%) | 35 |
| **EPUB with prefix tiers** | **84 / 88 (95%)** | **4** |

Genuine prefixes admitted (anchor starts where the passage starts): **62**.
Interior fragments admitted (reader cannot interpret): **0**.

The 4 remaining skips are all `MISSING_TARGET` — genuine paraphrase where even the
3-word prefix is absent from the source.

The clean corpus (50 annotations, *The Strange Case of Dr. Jekyll and Mr. Hyde*,
clean EPUB) did not change: **48 / 50** before and after.  Both skips are correctly
retained — one `MISSING_TARGET` (genuine paraphrase, no prefix match) and one
`AMBIGUOUS_TARGET` (quote appears multiple times; no matcher can resolve that).

The PDF path gets 49/50 on the clean corpus; the remaining gap is the AMBIGUOUS_TARGET
case, which no amount of matching strategy can fix without guessing.

### Why it is safe

The same argument applies as on the PDF side: a prefix anchor starts exactly where the
passage starts, so the underline is shorter than the note's quote but points the reader at
the right words.  The lone-word tier is the only tier that can land inside the passage
rather than at its start, and it is structurally excluded.  An A/B measurement over 88
real annotations confirmed zero interior fragments and +31 rendered annotations.

### Classifier consistency

`EpubProcessor._epub_miss_reason` was updated to mirror the same two-phase ladder, so its
`AMBIGUOUS_TARGET` / `MISSING_TARGET` classification stays consistent with the locator's
decision even when the locator's new prefix phase is the one that halts on ambiguity.
