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
