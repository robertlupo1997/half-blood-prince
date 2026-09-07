---
date: 2026-09-07
researcher: Astra (primary investigator); explicit free MiniMax workers
git_commit: 79da678e66127466d69da26de4f37c7c9d0dcd9b
branch: release/evidence-placement-contract
repository: half-blood-prince
topic: "Whole-quote placement contract, refusal benchmark, and input preservation"
tags: [placement, refusal, evidence, pdf, epub, safety, release]
status: review-ready-with-blocked-external-eval
---

# Placement release evidence packet

## Conclusion — Derived, bounded

This branch is ready for pull-request review of the **documented placement
contract**. It is not a public release, a merge authorization, or a model-quality
verdict. The important measured claims below survived executable checks. The
frontier quality gate remains **Blocked**; no quality score is claimed.

The crux was not a shortage of successful anchors. **Observed:** the former
prefix path could place a quote saying “fifty milligrams” on source text saying
“five milligrams.” The supported path now requires the complete normalized
quote or returns `resolved`, `ambiguous`, `unresolved`, or
`unsupported_renderer` as specified in `docs/placement-contract.md`.
A resolved quote still does not prove that the note is true or can be drawn well.

## Provenance and scope

- **Observed:** baseline `0739f28` was checked before edits. Owner preserved the
  interrupted refactor at `04a4489`; preservation commits are `323e81f` and
  `d67d9cc`. Final source/docs correction commit is `79da678e66127466d69da26de4f37c7c9d0dcd9b`.
- **Observed:** all resumed implementation/review workers were explicitly
  dispatched to `openrouter/minimax/minimax-m3:free`. The old Astra children were
  not restarted or messaged. Worker reports remain under
  `thoughts/shared/handoffs/lanes/2026-09-07_21-02-15_placement-free-workers/`.
- **Observed:** the primary final tests, Ruff, mypy, and benchmark below ran
  after the final source commit. Other probes ran against the same runtime
  implementation immediately before it. This packet and its raw logs are an
  evidence-only follow-up. Exact commands, exit codes, environment, and log
  paths are in `docs/evidence/placement-release/final/receipts.json`.
- **Observed:** upstream main was still `0739f288578fcda5fc6174f470c75368f57dea66`
  when `git ls-remote origin refs/heads/main` returned that hash. No merge or
  visibility-changing command was used. PR/push receipt is recorded below when
  available; this packet makes no claim that main contains the changes.

## Strongest evidence — exact commands and output

Run from the repository root. The project interpreter was used throughout.
The final run used `PYTHONPYCACHEPREFIX=/tmp/hbp-final-release-pycache`,
`NO_COLOR=1`, and `TERM=dumb`. A fresh bytecode location avoided stale shared
cache results seen during concurrent edits; final claims use the settled run.
Full captured stdout/stderr, including warnings, is preserved in the linked
repository paths. Excerpts below reproduce the result lines, not invented
summaries. Ruff's terminal escape bytes remain in its raw log.

### 1. Baseline was re-established — Observed, root execution

| Exact command at `0739f28` | Captured result | Full output |
| --- | --- | --- |
| `.venv/bin/python -m pytest tests/ -q` | `1883 passed, 28 warnings in 27.54s` | `docs/evidence/placement-release/baseline/pytest.txt` |
| `.venv/bin/python -m ruff check src/ tests/ eval/` | `All checks passed!` | `baseline/ruff.txt` |
| `.venv/bin/python -m mypy src/halfblood/` | `Success: no issues found in 45 source files` | `baseline/mypy.txt` |
| `.venv/bin/python scripts/check_harness_contracts.py` | Three known ledger entries; no new item | `baseline/contracts.txt` |
| `.venv/bin/python scripts/wheel_smoke.py` | `wheel smoke test PASSED` | `baseline/wheel.txt` |

The abbreviated `baseline/` paths in this table are relative to
`docs/evidence/placement-release/`. Counts in old handoffs are historical, not
substitutes for these outputs.

### 2. Final automated checks — Observed, root execution

| Exact command | Exact result line | Exit | Full output under `docs/evidence/placement-release/final/` |
| --- | --- | --- | --- |
| `.venv/bin/python -m pytest tests/ -q` | `2070 passed, 29 warnings in 24.65s` | 0 | `tests.txt` |
| `.venv/bin/python -m ruff check src/ tests/ eval/ scripts/ benchmarks/` | `All checks passed!` | 0 | `ruff.txt` |
| `.venv/bin/python -m mypy src/halfblood/` | `Success: no issues found in 48 source files` | 0 | `mypy.txt` |
| `.venv/bin/python scripts/wheel_smoke.py` | `wheel smoke test PASSED` | 0 | `wheel.txt` |
| `.venv/bin/python -c "import halfblood; print(halfblood.__file__)"` | `/home/tlupo/projects/half-blood-prince/src/halfblood/__init__.py` | 0 | `import.txt` |

The wheel check built and installed outside the checkout. Its new API probe
printed exactly:

```text
PLACEMENT_OK: four outcomes, cross-node range, round-trip, source intact
```

It also checked packaged fonts and the actionable source-checkout requirement
for `eval`; it did **not** run a quality judge from the wheel.

Harness command: `.venv/bin/python scripts/check_harness_contracts.py` (exit 0).
Exact remaining entries, unchanged from baseline:

```text
[CHECK-1] DIVERGENCE: .claude/agents/codebase-analyzer.md: missing opening frontmatter delimiter
[CHECK-1] DIVERGENCE: .claude/agents/web-search-researcher.md: missing opening frontmatter delimiter
[CHECK-4] DIVERGENCE: docs/superpowers/specs/2026-07-19-codex-usage-audit.md: historical claim says /goal uses raw Codex; .claude/skills/goal/SKILL.md is the current source of truth
```

Full output: `final/harness.txt`. These owner/historical-document items were not
silently repaired or treated as product failures.

### 3. Never overwrite an input — Observed, root execution

```bash
.venv/bin/python -m pytest tests/test_cli_hardening.py -k "refuses_to_overwrite_file_input or dry_run_also_refuses_file_input_as_output" -q
```

Exact output (`final/guard8.txt`, exit 0):

```text
........                                                                 [100%]
8 passed, 26 deselected in 2.23s
```

Those tests assert source bytes are unchanged, not just an error code. The
expanded source/derived-output/hardlink/symlink/resume matrix was also run in:

```bash
.venv/bin/python -m pytest tests/test_strict_placement.py tests/test_placement_rendering.py tests/test_placement_result_model.py tests/test_placement_migration.py tests/test_placement_benchmark.py tests/test_cli_output_safety.py tests/test_checkpoint_resume.py tests/test_degradation_mapping.py -q
```

Exact result: `199 passed, 1 warning in 8.31s` (exit 0, `final/strict.txt`). This includes
`tests/test_cli_output_safety.py` and the original-DOM, fixed-layout, model, and
benchmark contracts. Source, config/persona/font, and supplied resume paths are
protected against the artifact, checkpoint, and report destinations. Supplied
resume files remain inputs; only this run's distinct checkpoint is removed.

### 4. Runnable placement benchmark — Observed, root execution

```bash
.venv/bin/python scripts/benchmark_placement.py
```

Exit 0. Exact `totals` object from stdout (`final/benchmark.txt`):

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

The full JSON records each expected result, actual evidence, geometry checks,
fixture hashes, and mismatches. It covers the actual late-suffix five/fifty
refusal, unique and multiline positives, duplicate/overlap disambiguation by
exact offsets, stale hints, bounds, no-text-layer PDF, and unsupported EPUB.

```bash
.venv/bin/python -m pytest tests/test_placement_benchmark.py -k RedMutations -q
```

Exact output (`final/benchmark_mutations.txt`, exit 0):

```text
........                                                                 [100%]
8 passed, 28 deselected in 0.85s
```

**Derived limitation:** expected spans and EPUB segments are independent of the
resolver, and the PDF glyph walk bypasses its index; both PDF paths still depend
on PyMuPDF extraction. This is not a second renderer, a formal proof, or an
accuracy estimate for all books. The original benchmark was rejected in review
because its early-word typo did not exercise the late-suffix misanchor; the
checked-in medicine case fixes that evidence gap.

### 5. Real public-domain book runs — Observed, root execution

```bash
.venv/bin/halfblood annotate examples/src/alice.pdf -o /tmp/hbp-final-alice.pdf --provider stub --force
.venv/bin/halfblood annotate examples/src/alice.epub -o /tmp/hbp-final-alice.epub --provider stub --force
.venv/bin/python docs/evidence/placement-release/verify_real_books.py
```

All exited 0. Exact verification stdout (`final/verify_real_books.txt`):

```text
{"failed_pages": [], "format": "pdf", "native_annotations": 0, "pages_annotated": 78, "pages_total": 78, "placement_statuses": {"resolved": 78}, "render_skips": 0, "rendered": 78, "skipped_pages": [], "source_page_text_retained": true, "vector_drawings": 312}
{"failed_pages": [], "format": "epub", "pages_annotated": 12, "pages_total": 15, "pdf_quads": 0, "placement_statuses": {"resolved": 12}, "render_skips": 0, "rendered": 12, "skipped_pages": [1, 2, 15], "target_spans": 12}
```

`final/alice_pdf.txt` and `final/alice_epub.txt` contain the complete CLI runs.
The EPUB's 15 extracted units, 12 generated/placed notes, and skipped units
`[1, 2, 15]` must not be confused with the historical example sidecar's counts.
The PDF probe checks that every original page's extracted text is retained.
`git diff --exit-code 0739f28 -- examples/src/alice.pdf examples/src/alice.epub`
returned exit 0 with empty stdout (`final/source_unchanged.txt`).

Additional exact commands, all exit 0:

```bash
.venv/bin/halfblood annotate examples/src/alice.pdf -o /tmp/hbp-final-plan.json --provider stub --pages 1-3 --dry-run --force
.venv/bin/halfblood web-preview /tmp/hbp-final-plan.json -o /tmp/hbp-final-preview.html --force
```

Their complete outputs are `final/dry_run.txt` and `final/web_preview.txt`.
These are stub-provider pipeline checks only. They do not evaluate note quality,
reader appearance, or semantic truth. Demo inputs are Alice / Gutenberg #11,
whose retained notices say public domain in the USA; worldwide clearance is not
claimed. The original input files were not regenerated during this finish.

### 6. Former defects and boundaries — Observed plus Derived

```bash
.venv/bin/python docs/evidence/placement-release/legacy_probe.py
.venv/bin/python docs/evidence/placement-release/composition_probe.py
```

Both exit 0; complete output is `final/legacy_probe.txt` and
`final/degradations.txt`. The first intentionally exercises **excluded legacy
helpers** and still shows prefix selection. It is evidence for why those helpers
must not be confused with the supported contract, not a claim to have fixed
all legacy APIs. The full suite tests the supported path refusing the medicine
mismatch without any mark.

The second uses the real Alice PDF and records `caret_interline_gap_unavailable`
and `unknown_doodle_kind` in `composition_degradations`; the latter run also
records `connector_routing_fallback`. These codes previously disappeared from
the report. A finite summary flag list is not the complete diagnostic record.

Fixed-layout evidence: `tests/test_placement_rendering.py::test_epub_spine_rendition_override`
failed two of three cases before the correction, then passed all three. Native
inspection of `EpubReader._load_spine` showed it retains `(idref, linear)` only.
The processor now reads itemref layout properties from raw OPF before they are
lost. This is covered by the final full/strict test commands, not only reviewed.

## What was independently verified vs only reviewed

- **Observed independently by root execution:** all final commands above, raw
  benchmark output, injected-failure tests, real-book outputs, unchanged source
  bytes, wheel behavior, and package import location. Workers authored much of
  the new coverage; their reported counts were not substituted for root runs.
- **Worker-reported, then rerun through root tests:** the 73-case strict placement
  suite, safety aliases/resume behavior, benchmark oracles/mutations, and EPUB
  fixed-layout/rotation probes. Preserved worker reports can contain stale
  counts or unfinished assertions and are superseded by this packet.
- **Reviewed/Derived, not independently proven for every input:** call-graph
  separation from legacy recovery, normalization policy, all possible archive
  shapes and layout interactions, and oracle independence beyond the shared
  PyMuPDF dependency. Primary-source citation review is not a runtime comparison
  with Anchorite or Hypothesis.
- **Not adopted:** the first worker documentation ledger used stale README text
  and sometimes treated a file's existence as proof of behavior. Root replaced
  it with `docs/readme-claims.md`, narrowed claims, and re-ran docs/package tests:
  `126 passed in 0.97s` (exit 0,
  `final/docs_tests.txt`).

An additional final free-model read-only review had not returned a usable
report at packet closure. It is **not** counted as a clean review or as evidence.
The release claims above rest on the recorded executable checks and explicitly
scoped root review, not that worker's silence.

## Serious alternatives rejected — Derived decisions

1. **Optimize recovery percentage with prefix/fuzzy matching.** Rejected because
   the observed five/fifty case is a wrong location with misleading evidence.
   The benchmark now rewards correct refusal rather than more rendered notes.
2. **Invent first-occurrence context during V1 migration.** Rejected because the
   legacy quote does not say which occurrence was intended. Exact-only migration
   preserves uncertainty; explicit caller hints are verified, never guessed.
3. **Treat reflowable EPUB nominal dimensions as coordinates, or claim a fixed-
   layout renderer without implementing one.** Rejected because DOM text ranges
   do not supply viewport-independent geometry. Fixed-layout items refuse.
4. **Make connector routing the release crux.** Rejected as the primary problem:
   correct quote selection precedes drawing. Routing remains separately reported;
   this branch does not claim a better router or a zero-crossing rate.
5. **Map only today's three composer codes.** Rejected as an extensibility trap.
   All emitted codes now reach per-annotation diagnostics even without summary
   enum entries; a synthetic new code and actual omitted caret/doodle are tested.
6. **Bridge Codex OAuth or use self-judging to clear the quality gate.** Not done.
   The owner explicitly owns the rejected credential; transport/self-judging is
   not independent quality evidence.

## Blocked and unproven — what a reader should not believe

- **Blocked: independent frontier quality evaluation.** Before the checkpoint,
  the bounded account checks printed exactly `credits_http_status: 401` and
  `key_http_status: 401`. This is rejected authentication, **not an observed
  lack of credit**. The owner reconfirmed the judge-path blocker. It was not
  re-probed during this finish. No paid/frontier score, self-judge result, or
  model-quality improvement is claimed.
- **Unknown:** the historical connector rate `10/49` and clean-corpus PDF/EPUB
  rates `49/50` vs `48/50` at current HEAD. The old session described its scripts
  as local scratch. This finish did not recreate that exact corpus/run, so those
  fractions are neither adopted nor declared fixed. The new paired corpus is
  separately measured above.
- **Unknown:** universal precision, OCR truth, semantic validity of commentary,
  full-book accuracy, pixel-exact glyph contours, and EPUB reader compatibility.
  Reflowable EPUB anchors are text ranges. Fixed-layout EPUB coordinate rendering
  is not shipped. A note can be skipped despite a resolved quote.
- **Unknown/unclaimed:** race safety against hostile concurrent path changes,
  concurrent writers to one output, exactly-once API billing, sidecars after
  SIGKILL/setup failure, and byte-identical rendered PDFs/EPUBs.
- **Observed limitation:** legacy compatibility helpers still permit unsafe
  recovery and are explicitly outside the new public guarantee. Use
  `halfblood.placement` and `render_plan`, not those helpers, for this contract.
- **Not performed:** merge to main, visibility change, public release/tag flip,
  new dependency installation in the project venv, or credential repair.

## Highest-value next action

**Owner action:** review the PR's contract and refusal trade-off, then repair the
rejected credential and run the independent frontier judge if model-quality
claims are wanted. Keep that result separate from this placement benchmark.
Merge and publication remain the owner's decisions. Further matching work
should first add a checked-answer counterexample, not raise a recovery count.

## PR / push receipt

Pending at packet construction. The final response and PR body link to this
packet; no main-branch or visibility change is authorized by it.
