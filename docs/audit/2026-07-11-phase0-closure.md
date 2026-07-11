# Phase 0 closure report — audit ledger disposition

**Date:** 2026-07-11
**Branch:** `phase0-audit-close` (12 commits ahead of `main` at close)
**Source audit:** `docs/audit/2026-07-10-adversarial-audit.md` (AUD-01…AUD-44, L-1…L-3)
**Plan:** `docs/superpowers/plans/2026-07-11-phase0-1-implementation-plan.md`

Every finding is dispositioned below; none is silently dropped. All commit
gates were offline and mocked (`ruff check src tests eval`,
`mypy src/halfblood`, `pytest tests/ -q` — 199 passed at close). Live
provider checks are **blocked-on-key** (see bottom); they are supplementary
and were never substitutes for the mocked gates.

## Disposition table

| ID | Disposition | Where |
|---|---|---|
| AUD-01 | merged pre-branch (Session 5 batch) | `main` |
| AUD-02 | merged pre-branch (Session 5 batch) | `main` |
| AUD-03 | merged pre-branch (Session 5 batch) | `main` |
| AUD-04 | merged pre-branch (Session 5 batch) | `main` |
| AUD-05 | fixed P0-T1 | `06c253d` |
| AUD-06 | fixed P0-T4 | `94dac60` |
| AUD-07 | fixed P0-T5 | `07ddc4d` |
| AUD-08 | fixed P0-T5 | `07ddc4d` |
| AUD-09 | fixed P0-T5 | `07ddc4d` |
| AUD-10 | fixed P0-T1 | `06c253d` |
| AUD-11 | fixed P0-T11 | `cbe572e` |
| AUD-12 | fixed P0-T11 | `cbe572e` |
| AUD-13 | fixed P0-T11 | `cbe572e` |
| AUD-14 | fixed P0-T1 | `06c253d` |
| AUD-15 | fixed P0-T2 | `1beeb2a` |
| AUD-16 | merged pre-branch (Session 5 batch) | `main` |
| AUD-17 | fixed P0-T7 | `e09a81e` |
| AUD-18 | fixed P0-T8 | `909c5f3` |
| AUD-19 | fixed P0-T6 | `29252cd` |
| AUD-20 | fixed P0-T5 | `07ddc4d` |
| AUD-21 | fixed P0-T1 | `06c253d` |
| AUD-22 | fixed P0-T3 | `21318cc` |
| AUD-23 | fixed P0-T1 | `06c253d` |
| AUD-24 | fixed P0-T8 | `909c5f3` |
| AUD-25 | fixed P0-T4 | `94dac60` |
| AUD-26 | fixed P0-T6 | `29252cd` |
| AUD-27 | fixed P0-T11 | `cbe572e` |
| AUD-28 | fixed P0-T11 | `cbe572e` |
| AUD-29 | fixed P0-T11 | `cbe572e` |
| AUD-30 | fixed P0-T11 | `cbe572e` |
| AUD-31 | fixed P0-T3 | `21318cc` |
| AUD-32 | fixed P0-T2 | `1beeb2a` |
| AUD-33 | fixed P0-T11 (docs corrected; Phase 1 transport is the sole retry owner) | `cbe572e` |
| AUD-34 | deferred to P1-T9 by plan/spec §9 (eval judge/provider separation) | plan P1-T9 |
| AUD-35 | fixed P0-T4 (accepted item, fixed opportunistically as specified) | `94dac60` |
| AUD-36 | fixed P0-T10 | `0e4d114` |
| AUD-37 | fixed P0-T7 | `e09a81e` |
| AUD-38 | fixed P0-T12 (dependency upper bounds + dev lock) | this commit |
| AUD-39 | fixed P0-T6 | `29252cd` |
| AUD-40 | fixed P0-T5 | `07ddc4d` |
| AUD-41 | fixed P0-T9 | `811cea7` |
| AUD-42 | fixed P0-T9 | `811cea7` |
| AUD-43 | fixed P0-T9 | `811cea7` |
| AUD-44 | fixed P0-T11 | `cbe572e` |
| L-1 | fixed P0-T1 (typed SDK params, ignore removed) | `06c253d` |
| L-2 | fixed P0-T2 (str,Enum contract pinned by tests) | `1beeb2a` |
| L-3 | fixed P0-T1 (isinstance narrowing) | `06c253d` |

## Residuals deliberately left for later phases (tracked, not dropped)

- Occupancy-based collision layout, both-margins-degenerate skip+report:
  Phase 2 (architecture §5.5, §5.9).
- EPUB cross-node (multi-`NavigableString`) matching: Phase 2 locator work.
- Nav spine item with `linear="yes"` counts as page 1 (pinned in
  `tests/test_epub_processor.py`); annotations matching nav text are
  discarded at write by EbookLib's nav regeneration.
- Async/concurrency, checkpoints, cost budgets: Phase 5.

## Blocked-on-key live checks (require `ANTHROPIC_API_KEY`; not run)

```bash
export ANTHROPIC_API_KEY=sk-ant-...
halfblood annotate tests/fixtures/potions_textbook.pdf -o /tmp/annotated.pdf --pages 1-3
halfblood annotate tests/fixtures/sample_book.epub -o /tmp/annotated.epub
halfblood preview tests/fixtures/potions_textbook.pdf --pages 2-3
python eval/eval_harness.py --list && python eval/eval_harness.py
```

Record tokens/cost and validate outputs when a maintainer supplies a key; do
not commit generated artifacts or credentials.
