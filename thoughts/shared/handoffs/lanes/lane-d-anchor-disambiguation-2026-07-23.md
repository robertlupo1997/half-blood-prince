# Lane D Handoff — PDF Anchor Disambiguation (Issue #13)

**Branch**: `lane-d-anchor-disambiguation`  
**Head SHA**: `1a53fb8`  
**Date**: 2026-07-23  
**Owner**: Lane D driver  

---

## What was done

Wired `score_candidates` into `_resolve_annotation_to_anchor` (the v2 PDF anchor path) to
fix known issue #13: the path was first-hit-wins, causing annotations to land on the wrong
occurrence when a word or phrase appeared multiple times on a page.

### Commits on branch

| SHA | Description |
|-----|-------------|
| `5ef2c36` | test: lane-d red — PDF anchor disambiguation via score_candidates (issue #13) |
| `aba225e` | fix(tests): update `_PAGE_TEXT[2]` to unique phrase (Sopophorous bean appears twice on page 2) |
| `1a53fb8` | feat: wire score_candidates into `_resolve_annotation_to_anchor` (issue #13) |

---

## Implementation

### Changed file
`src/halfblood/document_processor.py`

### What changed
1. Added module-level imports from `halfblood.documents.matching`:
   `AmbiguousResult`, `MatchResult`, `NormalizedText`, `score_candidates`
   (must be module-level so test monkeypatching `halfblood.document_processor.score_candidates`
   works).

2. Inserted a scorer path before the existing `_search_variants` loop in
   `_resolve_annotation_to_anchor` (lines ~571–593):
   - `MatchResult` → `resolve_pdf_anchor(index, raw_span.start, raw_span.end)` → return anchor.
     Falls through to legacy if span covers only whitespace/separators.
   - `AmbiguousResult` → fail-closed (log at debug, return None). Do NOT guess first hit.
   - `NoMatchResult` → fall through to existing `_search_variants` + `page.search_for` chain.
   - `index is None` → skip scorer entirely, use existing chain.

3. Output contract (`PdfAnchor | None`) is unchanged. `find_text_rect` (v1) is untouched.

### Design rationale
- `AmbiguousResult` → return None (not `SkipReason.AMBIGUOUS_TARGET`) because the function
  contract is `PdfAnchor | None` and "everything downstream" was explicitly preserved per the
  brief. The ambiguity signal goes to the debug log. The skip reason in `RenderReport` is
  `MISSING_TARGET` (same as any other None return). This is intentional and documented here
  so gate reviewers don't compare to the EPUB path's `AMBIGUOUS_TARGET` handling and flag it.
- `NormalizedText(index.text)` is built inline per annotation call. Page text is typically
  < 50k chars; per-page re-normalization cost is negligible. No caching added to `PdfPageIndex`
  (keeps the diff inside `document_processor.py`; `layout/` untouched).

---

## Test changes

### New file
`tests/test_pdf_anchor_disambiguation.py` — 6 new tests

| Test | Status on HEAD (pre-fix) | Status after fix |
|------|--------------------------|------------------|
| `test_prefix_suffix_context_selects_second_occurrence` | RED | GREEN |
| `test_repeated_passage_no_context_returns_none` | RED | GREEN |
| `test_unique_passage_still_resolves` | GREEN | GREEN (regression guard) |
| `test_no_match_from_scorer_falls_through_to_legacy` | GREEN | GREEN (regression guard) |
| `test_context_disambiguates_second_occurrence_is_rendered` | GREEN | GREEN (regression guard) |
| `test_ambiguous_repeated_target_no_context_is_skipped` | RED | GREEN |

### Updated file
`tests/test_pdf_render_report.py` — one line changed

`_PAGE_TEXT[2]` was `"Sopophorous bean"` which appears TWICE on page 2 of the fixture PDF
(once in the Ingredients list, once in the Method). After the fix, `score_candidates` correctly
returns `AmbiguousResult` for this phrase with no context, making 13 tests fail because they
were relying on first-hit-wins. Updated to:
`"The Draught of Living Death is among the most powerful sleeping potions"` (unique, count=1,
`MatchResult`).

This is NOT weakening the tests — it corrects a latent issue: first-hit-wins was hiding a
pre-existing ambiguity. The 13 tests continue testing the same behaviors.

---

## Gate numbers

- `pytest tests/ -q`: **1407 passed, 1 skipped**
- `ruff check src tests eval scripts`: **All checks passed**
- `mypy src/halfblood`: **Success: no issues found in 42 source files**

---

## Disambiguation impact on fixture

- Tested the 5-page `potions_textbook.pdf` fixture against `score_candidates`:
  - Pages 1, 2, 3 `_PAGE_TEXT` entries: `MatchResult` (correctly unique)
  - Pages 4, 5 `_PAGE_TEXT` entries: `AmbiguousResult` (short repeated phrases)
    - `_PAGE_TEXT[4] = "Felix Felicis"` — only used in out-of-range page tests; never reaches scorer
    - `_PAGE_TEXT[5] = "Golpalott's Third Law"` — not used in any test
- In real usage (LLM-generated annotations), short words/phrases without context that appear
  multiple times on a page will now be skipped (fail-closed) rather than anchoring to the
  first hit. Annotations with prefix/suffix/offset context will be correctly disambiguated.
- Anchors changed count: 0 anchors changed in the test suite (the updated _PAGE_TEXT[2] phrase
  is unique before and after — same resolution path, just via MatchResult instead of first-hit).

---

## Receipts

- Brief (v1, failed): `scratchpad/lane-d-codex-brief.md`
- Brief (v2, succeeded): `scratchpad/lane-d-codex-brief-v2.md`
- Codex output (v2): `scratchpad/lane-d-codex-out-v2.txt`

(v1 brief resulted in 4 regressions due to `_PAGE_TEXT[2]` ambiguity; v2 fixed the constant
first and succeeded with 1407 passed.)

---

## Files NOT touched

- `tests/test_pdf_targeting.py` (v1 path tests)
- `tests/test_candidate_scoring.py` (scorer tests)
- `src/halfblood/layout/` (all layout/solver files)
- `src/halfblood/epub_processor.py`
- `CLAUDE.md`, `.claude/`

---

## For the gate reviewer

The implementation is a clean ~15-line insertion in `_resolve_annotation_to_anchor`. The
adjacent `AmbiguousResult → MISSING_TARGET` vs `AmbiguousResult → AMBIGUOUS_TARGET` choice is
deliberate (see Design rationale above). The 13 tests that use `_PAGE_TEXT[2]` were updated
to use unique text — this is a bug fix for those tests, not a scope expansion.

---

## Post-merge fix-up (branch: lane-d-skip-fix, SHA: 29acabd)

**Problem found at gate**: After the lane-d branch merged to main (`d1ddf22`), the gate
discovered a second hardcoded `"Sopophorous bean"` with no context in
`tests/test_note_measure_render.py:75`. The original lane-d fix only updated `_PAGE_TEXT[2]`
in `test_pdf_render_report.py`. The note-measure test's `pytest.skip` at line 115 was firing:

```
if "ln" not in captured:
    pytest.skip("long note was skipped as unplaceable; overflow contract not applicable")
```

This caused the suite to go from 1413 passed / 0 skipped to 1418 passed / 1 skipped — the
overflow contract (assert `box.height >= needed_height`) was silently untested.

**Fix**: Added `prefix="Cut the ", suffix=" with a silver knife"` to the `TargetSelector` in
`test_long_note_box_fits_wrapped_render`. This unambiguously selects the second occurrence
of "Sopophorous bean" on page 2 (Method step 2: "Cut the Sopophorous bean with a silver knife"),
which is semantically correct — the note content critiques cutting with a knife.

The test now RUNS (not skipped) and PASSES — the overflow contract is intact.

**Gate numbers (post fix-up)**:
- `pytest tests/ -q`: **1419 passed, 0 skipped**
- `ruff check src tests eval scripts`: **All checks passed**
- `mypy src/halfblood`: **Success: no issues found in 42 source files**
