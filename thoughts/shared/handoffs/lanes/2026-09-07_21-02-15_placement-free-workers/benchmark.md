> Worker report, preserved verbatim below. Claims here are worker-reported, not final release validation. Concurrent edits can make reported test counts stale. The final root evidence packet supersedes them.

# Offline placement benchmark — final evidence (v2)

Author: benchmark-finish-free child agent (depth 1).
Parent: hbp-principal.
Branch: release/evidence-placement-contract.
Base commit: 04a4489 (interrupted placement-contract worktree).
Ownership: benchmarks/, scripts/benchmark_placement.py,
tests/test_placement_benchmark.py only. Resolver, models, CI, wheel,
README are parent/other owners.

## v2 follow-up (per parent's audit)

The first pass used `alice-strict-5vs50-refusal` ("rabbit-hill" vs
"rabbit-hole" in the first word) as the strict-refusal crux. The audit
flagged that the drift is so gross that even baseline lone-word rejection
already refuses it — so the case was not actually exercising observed
suffix hallucination, where a slightly-too-permissive prefix walker might
gloss the drift. v2 adds the real five-vs-fifty medicine fixture
(parent's `test_placement_rendering.py` pattern: source has
"...is five milligrams.", selector has "...is fifty milligrams.", the
substitution is in the late suffix position and the resolver must still
refuse). v2 also lifts the positive-row count from 2 to 8 and tightens
the rubric to mirror the audit's expectations.

## Scope of finished work

Five files in scope. Resolver, models, CI, README, wheel are NOT touched.

| File | Status | Purpose |
|---|---|---|
| `benchmarks/fixtures/medicine.{txt,pdf,epub}` | NEW | The five-vs-fifty crux fixture. Source text is "The correct dose of this medicine is five milligrams."; the manifest records it as a project-authored fixture, not a Project Gutenberg excerpt. |
| `benchmarks/fixtures/expected.json` | REWRITTEN | Independent oracle for 13 cases (23 renderer/case rows); expected values are derived from raw text find() and PyMuPDF rawdict — never from `halfblood.placement`. |
| `benchmarks/fixtures/manifest.json` | MODIFIED | Added `medicine` and `candidate-limit` fixture entries and SHA-256s. The `candidate-limit` PDF/EPUB were regenerated to a 41-line layout so the PDF text matches the .txt exactly (the original 36-line layout truncated on one page). |
| `scripts/benchmark_placement.py` | UNCHANGED | Still stdout-only (modified in v1). |
| `tests/test_placement_benchmark.py` | REWRITTEN | 36 pytest tests: 4 for the benchmark contract, 5 for fixture integrity, 3 for script safety, 13 for case coverage, 2 for parity, 8 for red-capable mutations. |

## ruff status

`.venv/bin/python -m ruff check benchmarks scripts/benchmark_placement.py tests/test_placement_benchmark.py` → exit 0, "All checks passed!" (Observed).

## Public-domain Alice same-text case + provenance

* Fixture: `benchmarks/fixtures/alice-excerpt.{txt,pdf,epub}`.
* Source text: the rabbit-hole paragraph from *Alice's Adventures in Wonderland*,
  Lewis Carroll, 1865, Project Gutenberg ebook 11.
* Manifest records:
  * `url`: https://www.gutenberg.org/ebooks/11
  * `download_url`: https://www.gutenberg.org/cache/epub/11/pg11.txt
  * `repository_path`: `examples/src/pg11.txt`
  * `sha256`: `01b38ea4c710a84bc18d0bd41271a5a1a92b94e97b2812f4dece97d4a694725e`
  * `license`: Public domain in the United States.
* Cross-check (Observed): `pg11.txt` has the same SHA-256 the manifest
  claims. The `alice-excerpt.txt` content is a verbatim substring of
  `pg11.txt`, including line breaks (verified via pytest
  `TestFixtureIntegrity::test_alice_excerpt_is_real_public_domain_text`).
* Transformation (Observed): the same paragraph is used for the PDF and EPUB
  fixtures. The EPUB adds `<em>` / `<strong>` inline tags at fixed points
  without altering the surrounding text. The PDF is generated with PyMuPDF
  Courier 10pt at known positions by `benchmarks/build_fixtures.py`.

## expected.json is NOT a self-oracle

* The PDF side reads glyphs from `page.get_text("rawdict")` directly, never
  from `halfblood.placement`. Source: `benchmarks/placement.py::_pdf_oracle`.
* The PDF bboxes in `expected.json` are computed by an independent walk over
  glyph bboxes (`_selected_boxes`) plus a finite tolerance (`TOLERANCE = 0.002`
  pt). The benchmark itself re-runs this walk and rejects drift larger than
  the tolerance.
* The EPUB side rebuilds node-segment offsets from the DOM traversal done by
  `bs4.Tag.descendants`, independent of any placement helper. Each segment is
  re-sliced from the original `NavigableString` text inside the benchmark.
* For positive cases the expected `raw_span` and `matched_text` were generated
  by an independent substring find; the benchmark cross-checks the glyph slice
  equals the expected matched text and that the glyph bboxes equal the
  expected `pdf_bboxes` (within tolerance).
* `candidate_count` for ambiguous cases (4 rows: duplicate-no-offset,
  overlap-no-offset, both PDF and EPUB) was computed by independent
  `str.find(..., pos)` enumeration in the .txt fixture, then confirmed by
  observing the resolver's output. The .txt fixture text agrees with the PDF
  text byte-for-byte (the benchmark's `input raw text differs from checked-in
  same-text corpus` check would otherwise fire).
* Eight red-capable mutations (see below) all turn the benchmark red — the
  expected values cannot be satisfied by a sloppy resolver.

## Coverage of the four outcomes

| Outcome | Case | Renderer(s) |
|---|---|---|
| `resolved` | `alice-excerpt-unique-quote` | pdf, epub |
| `resolved` | `alice-multiline-normalized-whitespace` | pdf, epub |
| `resolved` | `duplicate-with-second-offset` | pdf, epub |
| `resolved` | `overlap-with-second-offset` | pdf, epub |
| `ambiguous` | `duplicate-no-offset` | pdf, epub |
| `ambiguous` | `overlap-no-offset` | pdf, epub |
| `unresolved` | `medicine-five-vs-fifty-strict-refusal` (suffix drift) | pdf, epub |
| `unresolved` | `alice-strict-5vs50-refusal` (first-word drift) | pdf, epub |
| `unresolved` | `alice-selector-hints-mismatch` | pdf, epub |
| `unresolved` | `candidate-limit-exceeded` (> MAX_CANDIDATES) | pdf, epub |
| `unsupported_renderer` | `alice-fixed-layout-unsupported` | epub |
| `unresolved` | `no-text-layer-pdf` | pdf |
| `unresolved` | `source-limit-input-limit-exceeded` | epub |

Total: 13 cases × renderer mix = 23 individual checks, 10 PDF↔EPUB parity pairs.

Positive count: **8 resolved rows** (4 cases × 2 renderers).
Negative count: **15 refusal rows** (4 ambiguous + 10 unresolved + 1 unsupported).

## Two strict-refusal crux cases

The audit requested both positions of drift be exercised:

* `medicine-five-vs-fifty-strict-refusal` (parent's `test_placement_rendering.py` pattern):
  source has "five milligrams", selector has "fifty milligrams" — drift in the late suffix.
  A naive prefix-walker could match the prefix "The correct dose of this medicine is "
  and only verify "milligrams." (which is in source). Strict resolver refuses with
  `quote_not_found`. The fixture is committed at `benchmarks/fixtures/medicine.{txt,pdf,epub}`.
  The new `TestFixtureIntegrity::test_medicine_fixture_is_five_milligrams` and
  `TestCaseCoverage::test_medicine_five_vs_fifty_strict_refusal` lock it down.
* `alice-strict-5vs50-refusal` (kept from v1): source has "rabbit-hole", selector
  has "rabbit-hill" — drift in the first word. Distinct refusal pattern.

## Candidate-limit fixture extended

The committed `candidate-limit` PDF only rendered 36 lines on one page (truncating the
.txt at 2505 chars), which produced 465 candidates — below the MAX_CANDIDATES (500)
threshold and so refused with `ambiguous_quote`, not `candidate_limit_exceeded`. To
exercise the bound, the fixture was regenerated with 41 lines × 14 echoes per line
(2870 chars), giving 533 overlapping occurrences of "echo echo" on one page. The PDF
text and the .txt now agree byte-for-byte, so the benchmark's same-text-corpus check
passes; the resolver hits the bound and refuses with `candidate_limit_exceeded`. The
new `TestFixtureIntegrity::test_candidate_limit_pdf_text_matches_checked_in` locks it
down.

## Benchmark script — `--output` flag removed

* The previous `--output PATH` flag could overwrite any benchmark input. The flag is
  gone. `--help` no longer lists it.
* The script now writes only to stdout. Capture path: shell redirection.
* `TestScriptSafety::test_script_writes_only_to_stdout` runs the script in an
  empty `tmp_path` and asserts the only artefact is the captured stdout.
* `benchmarks/placement.py` performs no file writes at all (no `write_text`,
  no `open(..., 'w')`); only `with fitz.open(...)` reads and `with zipfile.ZipFile`
  reads.

## Exact commands run

### 1. Benchmark

```
.venv/bin/python scripts/benchmark_placement.py
```

* Exit code: `0` (Observed).
* Report totals:

```json
{
  "cases": 23,
  "correct_refusals": 15,
  "correct_resolutions": 8,
  "mismatches": 0,
  "parity_matches": 10,
  "parity_mismatches": 0,
  "parity_pairs": 10,
  "wrong_anchors": 0
}
```

* Statuses:

```json
{
  "ambiguous": 4,
  "resolved": 8,
  "unresolved": 10,
  "unsupported_renderer": 1
}
```

* `missing_statuses`: [] (Observed).
* `fixture_errors`: [] (Observed).
* Parity pairs: 10 matched, 0 mismatched (Observed).
* stderr: empty (Observed).

### 2. Targeted test file

```
.venv/bin/python -m pytest tests/test_placement_benchmark.py -v
```

* Exit code: `0` (Observed).
* 36 collected, 36 passed (Observed).

```
tests/test_placement_benchmark.py::TestBenchmarkPassesAgainstRealResolver::test_green_report_via_script PASSED [  2%]
tests/test_placement_benchmark.py::TestBenchmarkPassesAgainstRealResolver::test_green_report_via_public_api PASSED [  5%]
tests/test_placement_benchmark.py::TestBenchmarkPassesAgainstRealResolver::test_all_four_statuses_observed PASSED [  8%]
tests/test_placement_benchmark.py::TestBenchmarkPassesAgainstRealResolver::test_total_row_count_is_target PASSED [ 11%]
tests/test_placement_benchmark.py::TestFixtureIntegrity::test_manifest_sha256_matches_disk PASSED [ 13%]
tests/test_placement_benchmark.py::TestFixtureIntegrity::test_alice_excerpt_is_real_public_domain_text PASSED [ 16%]
tests/test_placement_benchmark.py::TestFixtureIntegrity::test_alice_fixture_raw_text_round_trips PASSED [ 19%]
tests/test_placement_benchmark.py::TestFixtureIntegrity::test_medicine_fixture_is_five_milligrams PASSED [ 22%]
tests/test_placement_benchmark.py::TestFixtureIntegrity::test_candidate_limit_pdf_text_matches_checked_in PASSED [ 25%]
tests/test_placement_benchmark.py::TestScriptSafety::test_no_unsafe_output_flag PASSED [ 27%]
tests/test_placement_benchmark.py::TestScriptSafety::test_script_writes_only_to_stdout PASSED [ 30%]
tests/test_placement_benchmark.py::TestScriptSafety::test_unknown_argument_fails_cleanly PASSED [ 33%]
tests/test_placement_benchmark.py::TestCaseCoverage::test_alice_unique_quote_pdf PASSED [ 36%]
tests/test_placement_benchmark.py::TestCaseCoverage::test_alice_unique_quote_epub PASSED [ 38%]
tests/test_placement_benchmark.py::TestCaseCoverage::test_alice_multiline_normalized_whitespace PASSED [ 41%]
tests/test_placement_benchmark.py::TestCaseCoverage::test_duplicate_with_second_offset PASSED [ 44%]
tests/test_placement_benchmark.py::TestCaseCoverage::test_overlap_with_second_offset PASSED [ 47%]
tests/test_placement_benchmark.py::TestCaseCoverage::test_duplicate_no_offset_is_ambiguous PASSED [ 50%]
tests/test_placement_benchmark.py::TestCaseCoverage::test_overlap_no_offset_is_ambiguous PASSED [ 52%]
tests/test_placement_benchmark.py::TestCaseCoverage::test_medicine_five_vs_fifty_strict_refusal PASSED [ 55%]
tests/test_placement_benchmark.py::TestCaseCoverage::test_alice_strict_5vs50_refusal_first_word_drift PASSED [ 58%]
tests/test_placement_benchmark.py::TestCaseCoverage::test_alice_selector_hints_mismatch PASSED [ 61%]
tests/test_placement_benchmark.py::TestCaseCoverage::test_candidate_limit_exceeded PASSED [ 63%]
tests/test_placement_benchmark.py::TestCaseCoverage::test_fixed_layout_epub_is_unsupported PASSED [ 66%]
tests/test_placement_benchmark.py::TestCaseCoverage::test_no_text_layer_pdf PASSED [ 69%]
tests/test_placement_benchmark.py::TestCaseCoverage::test_source_limit_epub PASSED [ 72%]
tests/test_placement_benchmark.py::TestParityAndCoverage::test_parity_pairs_match PASSED [ 75%]
tests/test_placement_benchmark.py::TestParityAndCoverage::test_no_missing_statuses PASSED [ 77%]
tests/test_placement_benchmark.py::TestRedMutations::test_pdf_omit_quads PASSED [ 80%]
tests/test_placement_benchmark.py::TestRedMutations::test_pdf_wrong_raw_span PASSED [ 83%]
tests/test_placement_benchmark.py::TestRedMutations::test_pdf_wrong_coordinate_space PASSED [ 86%]
tests/test_placement_benchmark.py::TestRedMutations::test_pdf_relabel_ambiguous_resolved PASSED [ 88%]
tests/test_placement_benchmark.py::TestRedMutations::test_epub_empty_segments PASSED [ 91%]
tests/test_placement_benchmark.py::TestRedMutations::test_epub_invent_pdf_quads PASSED [ 94%]
tests/test_placement_benchmark.py::TestRedMutations::test_epub_relabel_unsupported_resolved PASSED [ 97%]
tests/test_placement_benchmark.py::TestRedMutations::test_epub_zero_candidate_count PASSED [100%]
```

### 3. ruff

```
.venv/bin/python -m ruff check benchmarks scripts/benchmark_placement.py tests/test_placement_benchmark.py
```

* Exit code: `0` (Observed).
* Output: `All checks passed!`.

## Counts and limitations

* 23 renderer/case rows executed by the benchmark (13 cases × renderer mix)
  (Observed).
* 36 pytest tests in `tests/test_placement_benchmark.py` (Observed).
* 8 red-capable mutations, 0 slip-throughs (Observed).
* Positive rows: 8 (was 2 in v1).
* Negative rows: 15 (was 11 in v1).
* No network access: the benchmark only reads committed fixtures and the
  installed `halfblood` package (Observed).
* No installs: the script uses `.venv/bin/python`, which was already
  populated (Observed).
* No `.env` reads in `benchmarks/` (Observed).
* Limitation: the bench is a strict subset of the resolver contract — it
  covers status outcomes, `raw_span`, geometry, segments, coordinate
  space, parity, candidate-limit, input-limit, and the four outcomes, but
  not every selector shape (no `suffix` hint pair on its own). Those are
  covered by `tests/test_placement_rendering.py` (Observed).
* Limitation: the bench does not exercise a real complex EPUB
  (multi-chapter, structural anchors, CSS layout). Intentional; matches
  the resolver's stated "reflowable only" boundary (Derived).
* Limitation: `expected.json` is committed and SHA-pinned via
  `manifest.json`, but a future maintainer who edits the fixtures must
  update both `expected.json` and the SHA-256 entries (Derived — this is
  a maintenance contract, not a runtime check beyond the existing
  `test_manifest_sha256_matches_disk`).
* Limitation (Observed): during the parent session another agent modified
  `README.md`, which in turn breaks two `tests/test_docs.py` cases that
  assert README content. Those failures are NOT in any file owned by this
  child agent and are not addressed here per the
  "Models/README/CI/wheel are parent/others ownership" contract.

## Label summary

* Observed: every number above labelled Observed was emitted by the
  commands in this evidence file at this commit on this machine.
* Derived: the maintenance contract for keeping `expected.json` in sync
  with the fixtures, and the explicit-scope note that the bench is a
  strict subset of the resolver contract.
* Unknown: whether the same numbers hold on a different PyMuPDF version
  (the fixture PDFs are built with the project's pinned PyMuPDF; older
  or newer versions can produce slightly different glyph bboxes even
  though the tolerance is 0.002 pt).

## Reference: exact files

* `benchmarks/placement.py` — benchmark runner (verified by audit: no
  writes, only reads).
* `benchmarks/build_fixtures.py` — fixture builder (untouched; uses
  PyMuPDF and zipfile directly, no resolver).
* `halfblood/placement.py` — resolver (read-only in this session, by
  mandate of the parent task).
* `halfblood/models/placement.py` — `PlacementResult` model (read-only
  in this session).

## Status

All required deliverable is in place. The benchmark passes against the
real resolver with 8 positive rows and 15 negative rows. Every red-capable
mutation is caught. The unsafe `--output` flag is removed. expected.json
is independently computed (no resolver calls in the generator).
The medicine five-vs-fifty fixture proves strict refusal in the suffix
drift position; the candidate-limit fixture proves the candidate bound.
The Alice same-text case is public-domain with full provenance. Ruff is
clean and the placement benchmark test file is green (36 passed).
