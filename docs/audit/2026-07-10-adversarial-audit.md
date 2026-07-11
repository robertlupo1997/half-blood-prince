# Adversarial Audit Ledger — 2026-07-10

Phase 1 output of the v0.1.0 portfolio-release plan
(`docs/superpowers/plans/2026-07-10-foundation-and-audit.md`). This document is
the single input for the Phase 2 fix plan; every finding carries a stable
`AUD-NN` id that Phase 2 tasks reference.

## Method

- **Six audit lenses**, run as parallel read-only agents, each with a distinct
  charter: L1 generation/prompting, L2 PDF rendering, L3 test suite,
  L4 security, L5 API currency (live doc checks against SDK 0.116.0 and the
  current model tables), L6 documentation. Raw output: 45 findings
  (`.superpowers/sdd/audit/lens-{1..6}.md`).
- **Adversarial verification**: three independent verifier agents, each
  assigned a lens pair it did not author (A: 1+5, B: 2+4, C: 3+6), instructed
  to refute each finding against the actual code and to write runnable repros
  for every High. Result: **45 raw → 42 confirmed / 0 refuted / 2 downgraded /
  1 merged** (44 verified entries). Controller merged and deduplicated into
  `verified.md`.
- **Repro scripts** for the six worst findings live at
  `.superpowers/sdd/audit/repro/*.py` (session artifacts, durable on disk but
  not in git; each finding below names its script). AUD-01's repro is a
  one-line pip command, inlined below.
- **Not audited** (out of scope or blocked): live API behavior end-to-end
  (blocked, see next section); visual QA of rendered PDF/EPUB output;
  performance and memory at real book scale (300+ pages); in-browser behavior
  of the web preview; concurrency (none exists — see inherited issue #9).

Severity distribution: **1 Critical / 12 High / 17 Medium / 14 Low**.

## E2E results

**BLOCKED — `ANTHROPIC_API_KEY` not available in any session to date.**
All prep is done; when a key is present, run exactly:

```bash
# Task 5 (PDF) — Run 1, default (retired) model: expected to demonstrate the
# silent-empty-output failure live (AUD-02). Document the outcome in the ledger.
.venv/bin/python .superpowers/sdd/audit/e2e_pdf.py \
    .superpowers/sdd/audit/e2e-pdf-annotated-retired.pdf

# Task 5 (PDF) — Run 2, current model: the real cost measurement.
.venv/bin/python .superpowers/sdd/audit/e2e_pdf.py \
    .superpowers/sdd/audit/e2e-pdf-annotated.pdf --model claude-sonnet-5

# Task 6 (EPUB) — fixture is already committed (tests/fixtures/sample_book.epub).
.venv/bin/halfblood annotate tests/fixtures/sample_book.epub \
    -o .superpowers/sdd/audit/e2e-epub-annotated.epub --model claude-sonnet-5
# then unzip the output, verify sidenotes present, XHTML well-formed (lxml),
# CSS injected once, original text intact; write e2e-epub-report.md.
```

The instrumented PDF runner (`.superpowers/sdd/audit/e2e_pdf.py`) sums token
usage across calls and prints pages/annotations/calls/tokens; look up current
per-MTok pricing to convert to dollars.

Offline observation from fixture prep: `EpubProcessor.load()` on the committed
fixture returns **4** documents — the EPUB *nav* page is included as an
annotatable page alongside the 3 chapters. Whether the pipeline should skip
nav documents is a question for the E2E run to answer.

## Findings

Format: `AUD-NN | file:line | claim | failure scenario | repro | proposed fix`.
Line numbers are as of commit `5333574`.

### Critical

- AUD-01 | README.md:46 | Documented `pip install -e ".[eval]"` names a
  non-existent extras group | The documented eval install step fails outright
  for every new user | `.venv/bin/pip install -e ".[eval]" --dry-run` →
  "'eval' is not a valid extras name" | Add an `[eval]` extras group to
  pyproject.toml (or change the README to install the eval deps directly)

### High

- AUD-02 | annotation_generator.py:192 | Default model
  `claude-sonnet-4-20250514` is retired from the API | 404 NotFoundError is
  swallowed by `except anthropic.APIError` → every page returns `[]` → the app
  emits an empty annotated PDF **with no error and exit code 0** |
  `repro/repro_silent_api_error.py` | Bump the default to a current model
  (`claude-sonnet-5` verified live); must land together with AUD-16 so future
  retirements fail loudly instead of silently
- AUD-03 | cli.py:46 | CLI `DEFAULT_MODEL` is the same retired ID (used by
  `annotate`/`preview` without `--model`) | Same silent-empty-output as AUD-02
  via the CLI path | same repro | Single source of truth: define the default
  once and import it in cli.py and the eval harness
- AUD-04 | eval/eval_harness.py:73 | Eval harness `DEFAULT_MODEL` is the same
  retired ID | Every eval case records `generation_error`; the quality gate is
  dead on arrival | traced in code (verified-A) | Same single-source fix;
  `HALFBLOOD_EVAL_MODEL` env override already exists
- AUD-05 | annotation_generator.py:310-323 | `stop_reason` is never checked |
  `max_tokens` truncation yields tool input `{}` → silent zero annotations for
  the page, indistinguishable from a legitimately empty page |
  `repro/repro_stop_reason.py` | Check `response.stop_reason`; on
  `"max_tokens"` warn (or retry with a higher budget); treat empty tool input
  as an error, not an empty plan (cross-ref AUD-21 for the missing test)
- AUD-06 | web_preview.py:101 | `_flexible_pattern` emits `\\s+` (literal
  backslash + `s`) instead of `\s+` — `re.escape(" ")` runs before the space
  substitution | ALL multi-word target lookups in the web preview fail; every
  such annotation renders unanchored | `repro/repro_l4_flexible_pattern.py` |
  Substitute a sentinel before escaping:
  `re.escape(collapsed.replace(" ", "\x00")).replace("\x00", r"\s+")`.
  **Coupled fix:** the broken pattern currently neutralizes the inherited
  ReDoS risk (#13); fixing it re-opens catastrophic backtracking, so the
  pattern fix, a complexity/timeout guard, and regression tests (AUD-25) are
  ONE task
- AUD-07 | document_processor.py:494-510 | Right-margin note is placed beyond
  the page's right edge when the target ends within ~62pt of the boundary
  (`_MIN_MARGIN_WIDTH` clamp overrides available space) | Note text renders
  partially or fully off-page — invisible in viewers, content silently lost |
  `repro/repro_l2_margin_overflow.py` | Clamp the note rect to the page
  rect; when the margin is narrower than `_MIN_MARGIN_WIDTH`, switch sides or
  shrink the font instead of overflowing
- AUD-08 | document_processor.py:505 | Long wrapped notes on bottom-of-page
  passages overflow the page bottom (no vertical clamp) | Trailing note lines
  render off-page | `repro/repro_l2_margin_overflow.py` | Vertically clamp the
  note block; shift the block up when it would cross the bottom edge
- AUD-09 | document_processor.py:505 | Same missing clamp in the other
  direction: long notes on top-of-page passages start above the page top |
  Leading note lines render off-page | `repro/repro_l2_margin_overflow.py` |
  Same vertical clamp, both directions (one fix with AUD-08)
- AUD-10 | tests/test_pipeline.py:359-494 | 6 of 10 `TestParseResponse` tests
  exercise the JSON-string fallback path that production never uses | A broken
  Message-path branch would leave the suite green while every real call
  returned `[]` | verified-C code trace | Rewrite the six tests against
  Message-shaped objects (real SDK types, cross-ref AUD-10 with lint finding
  L-1 below)
- AUD-11 | README.md:107 | `web-preview` is a shipping CLI command
  (cli.py:239) entirely absent from the README | Users can't discover a
  headline feature | n/a (doc) | Document the command with an example
- AUD-12 | README.md:195 | Contributing section describes EPUB support as
  future work; EpubProcessor is implemented and wired | A contributor would
  build a duplicate implementation | n/a (doc) | Rewrite the section to
  describe the real EPUB pipeline
- AUD-13 | docs/ARCHITECTURE.md:202 | Extension-points section also treats
  EPUB as unimplemented (it implements the doc's own "Option (b)") |
  Architecture doc contradicts the code it documents | n/a (doc) | Update the
  extension-points section (one docs task with AUD-12)

### Medium

- AUD-14 | annotation_generator.py:503-517 | A tool_use block with empty/None
  `input` returns `[]` with no warning (the warning fires only when NO block
  exists) | Truncated/malformed responses silently produce zero annotations |
  `repro/repro_stop_reason.py` Case A | Warn (or raise) when a tool_use block
  arrives with empty input; fold into the AUD-05 stop_reason task
- AUD-15 | annotation_generator.py:454 + models.py:24-26 | `target_text` has
  no `min_length`; empty string passes validation | `fitz.search_for("")` is
  undefined behavior; annotation placement is garbage-in | verified-A trace |
  `min_length=1` (with `strip` normalization) on the Pydantic field + guard in
  the schema
- AUD-16 (downgraded from High) | annotation_generator.py:319-321 | After SDK
  retry exhaustion (or a non-retried 404), `APIError` is caught, logged to a
  handler-less logger (invisible in CLI), and `[]` returned | A page — or with
  a dead model, the whole book — permanently loses annotations with no
  user-facing error. Note: SDK 0.116.0 already retries 429/408/409/5xx ×2, so
  the original "no retry" framing (inherited #8) was wrong |
  `repro/repro_silent_api_error.py` | Configure logging in the CLI entry
  point; count per-page failures and report them in the run summary; non-zero
  exit (or hard error) when ALL pages fail
- AUD-17 | cli.py:84-92 | Extension-only dispatch: non-PDF bytes named `.pdf`
  crash inside PyMuPDF with a raw `FileDataError` | Unhelpful traceback
  instead of a clean CLI error (inherited #14, CONFIRMED) | verified-B trace |
  Validate magic bytes (`%PDF-` / `PK\x03\x04`) before dispatch; wrap in
  `click.ClickException`
- AUD-18 | epub_processor.py:372-386 | `_locate_text` normalizes quotes in the
  search variant but not in the node text | ASCII-quote targets miss
  curly-quote EPUB body text; annotations silently skipped |
  `repro/repro_epub_quotes.py` | Apply the same normalization to node text
  before comparison
- AUD-19 | document_processor.py:437-438 | CROSSED_OUT always calls
  `_write_replacement_above` regardless of `position` | Overlapping text for
  `between_lines`; duplicated content for margin positions |
  `repro/repro_l2_crossed_out.py` | Route CROSSED_OUT replacement text through
  the position dispatcher like every other type
- AUD-20 | document_processor.py:728-736 | `_wrap_text` has no character-level
  break | A single token wider than the margin column overflows into body
  text | `repro/repro_l2_margin_overflow.py` | Hard-break tokens wider than
  the column at character level
- AUD-21 (downgraded from High) | tests/test_pipeline.py:75-89 |
  `stop_reason="max_tokens"` truncation is completely untested | The AUD-05
  bug class can regress invisibly (the raw claim's mock-fidelity half did NOT
  hold — production reads only duck-typed fields) | verified-C | Add a
  truncation test alongside the AUD-05 fix
- AUD-22 | tests/test_pipeline.py (absent) | `generate_for_document` is
  entirely untested | Context windowing, running_notes cap, confidence
  trimming, and plan assembly can all regress silently | verified-C | Add unit
  tests with a mocked `generate_for_page`
- AUD-23 | tests/test_pipeline.py (absent) | The `APIError` handler
  (annotation_generator.py:319-321) is never exercised | The silent-`[]` path
  (AUD-16) is unguarded by tests | verified-C | Test it with a mocked client
  raising `anthropic.APIError`
- AUD-24 | tests/test_pipeline.py (absent) | EpubProcessor has zero test
  coverage (inherited known gap, CONFIRMED) | The whole EPUB pipeline can
  regress invisibly; fixture now exists (`tests/fixtures/sample_book.epub`) |
  verified-C | Add load/render/roundtrip tests against the committed fixture
- AUD-25 | tests/test_pipeline.py (absent) | web_preview.py (~1100 lines) has
  zero test coverage | AUD-06 shipped precisely because of this | verified-C |
  Add tests with the AUD-06 fix (pattern behavior, HTML escaping, JSON
  embedding)
- AUD-26 | tests/test_pipeline.py (absent) | No regression test for
  `_search_variants` multi-occurrence disambiguation (inherited #10) | The
  union-rect failure mode (see inherited table) is unpinned | verified-C |
  Add a fixture page with a repeated word and assert the anchor choice
- AUD-27 | README.md:75 | Usage shows `INPUT_PDF`/`OUTPUT_PDF`; the actual
  argument is `INPUT_FILE` accepting `.pdf` or `.epub` | Copy-pasted docs
  mislead users | n/a (doc) | Fix usage text
- AUD-28 | README.md:8-9 | Intro describes the tool as PDF-only | EPUB support
  is invisible to readers | n/a (doc) | Rewrite intro
- AUD-29 | README.md:159-163 | Architecture module list omits
  epub_processor.py and web_preview.py | Doc/code drift | n/a (doc) | Update
  list
- AUD-30 | docs/ARCHITECTURE.md:82-84 | cli.py section lists 3 commands as the
  complete set; `web-preview` is the shipped 4th | Doc/code drift | n/a (doc)
  | Update section (one docs task with AUD-11/27/28/29)

### Low

- AUD-31 | annotation_generator.py:355 | `running_notes` grows unbounded; only
  `[-8:]` is ever consumed | Pointless memory growth on very long books |
  verified-A | Trim to the cap on append
- AUD-32 | annotation_generator.py:531-533 | `text.strip("``")` is a
  character strip, not fence stripping | Corrupts legitimate boundary
  backticks on the string-fallback path | verified-A | Strip fences with
  explicit startswith/endswith handling
- AUD-33 | annotation_generator.py:319 (doc claim) | CLAUDE.md inherited issue
  #8 is factually wrong: the SDK already retries 429/500/529 ×2 | Phase 3
  "add retry" would duplicate SDK behavior | verified-A (SDK source) | Rescope
  Phase 3 retry work to surfacing failures (AUD-16), not re-implementing retry
- AUD-34 | eval/eval_harness.py:557-604 | Generator and judge use the same
  model | The model grades its own output — systematic leniency bias |
  verified-A | Use a different judge model (see Accepted below)
- AUD-35 | web_preview.py:344 | `json.dumps(..., ensure_ascii=False)` can emit
  raw U+2028/U+2029 into the `<script>` block | Syntax error in pre-ES2019
  engines | verified-B | Escape U+2028/29 (see Accepted below)
- AUD-36 | web_preview.py:415-417 | "Self-contained HTML" docstring
  contradicted by Google Fonts `<link>`s | Offline breakage + viewer IP leak |
  verified-B | Inline the font as a data URI or drop the claim from the
  docstring
- AUD-37 | cli.py:259-260 + web_preview.py:388-390 | Output overwrites
  silently; parent dirs auto-created undocumented | Users can clobber files |
  verified-B | Warn on overwrite (or add `--force`); document dir creation
- AUD-38 | pyproject.toml:7-14 | All 8 runtime deps are floor-only pins, no
  upper bounds, no lockfile | A breaking `anthropic>=2.0` installs silently |
  verified-B | Add sensible caps (at least `anthropic<2`) and/or a lockfile
- AUD-39 | document_processor.py:255-279 | `_search_variants` yields no
  fallbacks for short targets (≤3 words, no word ≥4 chars) | No recovery from
  line-break drift for short quotes | verified-B | Add a normalized-substring
  fallback for short targets
- AUD-40 | document_processor.py:596 | `_write_between_lines_text` top clamp
  can land the second note line at/below the target baseline near page top |
  Note collides with the text it annotates | verified-B | Fix the clamp math
- AUD-41 | tests/test_pipeline.py:121-123 | Bare `pytest.raises(Exception)` |
  Any exception passes, including typos in the test itself | verified-C |
  Assert the specific exception type
- AUD-42 | tests/test_pipeline.py:661-679 |
  `test_invalid_position_defaults_to_margin_right` asserts nothing about the
  fallback position | The behavior in the test's own name is unverified |
  verified-C | Assert the rendered position
- AUD-43 | tests/test_pipeline.py:545-558 | `test_version_flag` loose string
  match absorbs unrelated RuntimeErrors | False green possible | verified-C |
  Assert exit code and exact version output
- AUD-44 | README.md:54-56 | Font docs mention only CaveatBrush-Regular.ttf;
  the resolver accepts any `*aveat*.ttf` variant (document_processor.py:168) |
  Users think only one exact file works | n/a (doc) | Mention the glob (see
  Accepted below)

### Deferred lint findings (from Task 1, `.superpowers/sdd/lint-findings.md`)

Behavioral issues found during the mechanical lint pass, deliberately deferred
to the fix phase:

- L-1 | annotation_generator.py:311 | SDK call passes plain dicts where
  TypedDicts are expected (`tools`, `tool_choice`, `messages`); suppressed
  with `# type: ignore[call-overload]` | Works at runtime today, unverified by
  mypy | Cast args to their SDK TypedDict types (pairs naturally with the
  AUD-10 test rewrite)
- L-2 | models.py:3 | ruff UP042 suggests StrEnum; migration changes `str()`
  output at runtime (reverted in b5c1994 as out of scope for the lint task) |
  All current call sites use `.value`, so migration is likely safe | Decide
  deliberately in Phase 2 — migrate with a `str()`-output regression test, or
  add a permanent `noqa` with rationale
- L-3 | annotation_generator.py:508 | `.input` accessed on a content-block
  union behind a `getattr` type guard mypy can't narrow; suppressed with
  `# type: ignore[union-attr]` | A new SDK block type without `.input` would
  raise AttributeError | Replace the guard with
  `isinstance(block, anthropic.types.ToolUseBlock)`

## Inherited known issues — re-verification

CLAUDE.md "Unfixed (Medium/Low)" list, issues #8–15, re-verified against the
code at `5333574` (checks re-run 2026-07-10, Session 4):

| # | CLAUDE.md claim | Verdict | Merged as |
|---|---|---|---|
| 8 | No rate limiting or retry; 429/500 crashes the pipeline | **WRONG** — SDK 0.116.0 already retries 429/408/409/5xx ×2 with backoff; nothing crashes. The real bug is the opposite: failures are silently swallowed | AUD-16, AUD-33 |
| 9 | No async/concurrent page processing | **CONFIRMED** — `generate_for_document` is a sequential loop; no asyncio/AsyncAnthropic anywhere | Phase 3 scope (no AUD; not a defect, a feature gap) |
| 10 | `_search_variants` fallback anchors to the *first* occurrence of a repeated word | **CONFIRMED, mechanism corrected** — `find_text_rect` returns `_union_rects(hits)`, so a repeated word produces a rect spanning ALL occurrences (potentially most of the page), which is worse than first-occurrence anchoring | AUD-26 (test gap); fix scoped in Phase 2 |
| 11 | No annotation overlap/collision detection | **CONFIRMED** — no occupancy tracking of any kind in document_processor.py; compounded by the margin-geometry bugs | AUD-07/08/09 (adjacent geometry bugs); collision detection itself is Phase 3 scope |
| 12 | EPUB `_locate_text` only searches single text nodes | **CONFIRMED** — it returns a single `NavigableString` (epub_processor.py:337); cross-tag targets are unfindable. New sibling bug: quote-normalization asymmetry | AUD-18 (sibling); multi-node matching is Phase 3 scope |
| 13 | Web preview `_flexible_pattern` regex risks catastrophic backtracking | **WRONG as stated — SUPERSEDED** — the pattern is broken outright and matches nothing (instantly), so ReDoS is unreachable today; fixing the pattern re-opens it. One coupled fix task | AUD-06 |
| 14 | No input validation on PDF paths (magic bytes) | **CONFIRMED** | AUD-17 |
| 15 | Font fallback WARNING is noisy | **CONFIRMED** — `logger.warning` with download instructions fires on every `DocumentProcessor` construction without the font (document_processor.py:185) | No AUD (cosmetic); Phase 3 scope per plan |

## Accepted / won't-fix

Low findings deliberately deferred beyond Phase 2, with reasoning:

- **AUD-34** (judge = generator model): accepted for v0.1.0 — the eval harness
  is a development tool, not a shipping gate; revisit if eval scores ever gate
  a release. Cheap mitigation when touched next: judge on a different model
  family than the generator.
- **AUD-35** (U+2028/29 in `<script>`): accepted — every ES2019+ engine
  (all supported browsers) parses these fine; fix opportunistically if
  web_preview.py is touched for AUD-06/36.
- **AUD-44** (font docs glob nuance): folded into the Phase 4 README overhaul
  rather than fixed standalone.

Everything else — including all other Lows — is in scope for the Phase 2 fix
plan (one TDD task per AUD-NN, severity order) or explicitly scoped to
Phase 3 (async, collision detection, multi-node EPUB matching, font-log
noise) per the plan's "Deferred to subsequent plans" section.
