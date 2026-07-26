---
date: 2026-07-26
researcher: Claude (Opus 5)
git_commit: f78e181
branch: main
repository: half-blood-prince
topic: "Session 33 — --font broken in every installed wheel; PDF anchor quality 5 stubs → 0; preview editing"
tags: [packaging, fonts, matching, pdf, rendering, web-preview, cli, parallel-lanes, negative-result]
status: complete
last_updated: 2026-07-26
---

# Session 33 — the shipped wheel couldn't find its own fonts

**6 commits. Suite 1644 → 1738. All four suggested lanes landed, plus two defects
found by rendering the real book and looking at it.**

The single most valuable thing here is **Learnings §1**: the session's biggest bug was
invisible to 1644 tests *and* to both linters *and* to the dev tree, because the dev tree
has a directory that the shipped artifact does not. Testing the installed wheel is what
found it.

---

## Task(s)

1. ✅ **Lane C — CLI error precedence.** Persona usage errors now precede provider-config errors.
2. ✅ **NEW — `--font <name>` broken in every pip-installed wheel.** Found, proven, fixed.
3. ✅ **Lane A — PDF anchor quality.** 5 stub anchors → 0; 48/50, matching EPUB exactly.
4. ✅ **Lane B — web preview editing.** Edit content, delete, re-position, edited export.
5. ✅ **NEW — margin notes clipped by the page top.** Glyph tops at y = −0.39, fixed.
6. ✅ **NEW — over-wide words broke mid-morpheme.** `counter-clockw`/`ise`, now hyphen-aware.
7. ⏳ **P3 — quality on a frontier model.** Still owner-gated (needs credit).
8. ⏳ **Release decision.** Still owner-gated.

## Critical References

- `docs/decisions/verbatim-quoting-prompt-vs-matcher.md` — why a wrong anchor is worse than
  no annotation. This is the principle the whole of Lane A rests on.
- `tests/test_font_packaging.py` — now also pins that registered font names resolve to the
  **packaged** directory. This is the test that would have caught the wheel bug.
- `tests/test_match_tolerance.py::TestShortenedTierFallbackIsUnchanged` — docstring rewritten.
  Its assertions are unchanged and still guard `score_candidates`' shared EXACT contract.

## Recent changes

| commit | what |
|---|---|
| `3ece281` | CLI: resolve persona before provider config, in `annotate` and `preview` |
| `aba2d30` | CLI: `_FONTS_DIR` from package resources, not `__file__.parents[2]` |
| `1c5e8ed` | PDF: tolerance ladder on the full quote + `_MIN_ANCHOR_COVERAGE` floor |
| `5b09bcf` | Preview: annotation edit / delete / re-position + edited Copy-JSON |
| `a955ee9` | PDF: `_first_baseline` reserves glyph ascent + rotation lift at the page top |
| `f78e181` | PDF: break over-wide words at their hyphen |

## Learnings

### 1. The dev tree masked a bug that broke the shipped product for every user

`src/halfblood/cli.py` had `_FONTS_DIR = Path(__file__).resolve().parents[2] / "fonts"`.
In a source checkout that is the repo-root `fonts/` directory, which exists locally but is
**gitignored**. From a pip-installed wheel, `parents[2]` lands *above* site-packages, so the
path does not exist — and every registered `--font` name and the config `font` key failed with:

```
Font 'Caveat Brush' is not installed.
Expected .../lib/python3.12/fonts/CaveatBrush-Regular.ttf.
Download it from https://fonts.google.com/specimen/Caveat+Brush.
```

…telling the user to download a font **that ships inside the package**. The default font was
fine, because `DocumentProcessor` already resolved via package resources — which is exactly
why nothing caught it.

**How it was found:** built the wheel, installed it into a throwaway venv outside the repo,
and asked the installed CLI to resolve a font name. `prove_font_bug.py` does this in ~40s.
**Do this for anything that computes a path from `__file__`.** Relative-to-repo path
arithmetic is the tell.

Incidental win: the fix also makes the suite pass from a clean clone — one test previously
depended on the untracked `fonts/*.ttf`.

### 2. The roadmap's framing of the PDF matcher item was right; mine was wrong

I proposed replacing "narrow the shortened-tier fallback" with "give the PDF path the
tolerance ladder", on the theory that the ladder recovers rather than drops. Measuring showed
it needed **both**. Census over 50 real annotations:

| | n |
|---|---|
| tier 0, coverage 1.00 | 44 |
| shortened tier, rescued to tier 0 by the ladder | 4 |
| shortened tier, genuine paraphrase (coverage 0.13 / 0.18) | 2 |

The ladder fixes 4; only a coverage floor fixes the other 2. Result: **5 stub anchors → 0,
48/50 rendered**, identical to the EPUB path on the same book and plan, skipping the same
two paraphrases.

`score_candidates` was **not** touched — the ladder is applied by the PDF *caller*. That
keeps the scorer's EXACT contract intact for the EPUB locator, and meant the pinning test
kept passing rather than needing the rewrite I had pre-authorised.

### 3. Three rig versions before the numbers meant anything

The PDF measurement rig gave a confident wrong answer twice:

- **Latin-1 font.** PyMuPDF's base-14 `Times-Roman` mangles curly quotes, corrupting the text
  layer and inventing 5 phantom "extraction drift" cases. Use a Unicode TTF and assert the
  text layer round-trips.
- **Scanning every page and taking the first hit.** The product resolves each annotation
  against *its own* page. Scanning let a bogus single-word match on an earlier page beat the
  correct tier-0 match on the right page — inflating stubs from 5 to **16**. Map
  `unit.ordinal - 1`, and build one tall page per chapter so nothing straddles a break
  (arbitrary pagination added 13 more phantoms).

At one point I reported "23 stub anchors, 11 of them verbatim matcher bugs." All 23 were rig
artifacts. **Before believing a measurement, ask what the product actually does and whether
the rig does the same thing.**

### 4. `codex:codex-rescue` + `isolation: "worktree"` silently loses all work

The rescue agent spawns a **detached** Codex job and returns immediately; the harness then
reclaims the worktree, leaving a live Codex process whose `--cwd` no longer exists. Result:
zero work, no error, and `pgrep` still showing a busy Codex. A general-purpose relaunch also
died (terminated mid-orientation; an unchanged worktree is reclaimed). After two lost rounds
I did Lane A myself in ~40 minutes.

Also: `ls .claude/worktrees/` and `git worktree list` both omit unregistered worktrees, so
**neither proves absence** — stat the path.

### 5. Rendering bugs need the rendered artifact, not the code

Both new rendering defects came from generating a real annotated PDF and reading the page
image. Neither is reachable from unit tests as they existed:

- Margin notes clipped at the page top. The layout engine *does* clamp the note box; the loss
  happens later, in the drawing, from the glyph ascent plus a `morph` rotation that pivots
  about the box centre and lifts each line's left end by `(width/2)·sin(angle)` — up to
  ~3.9pt against 0.38pt of headroom. Arithmetic reproduced the measured origin to 3 decimals.
- `counter-clockw` / `ise` — character-splitting a word that carries its own hyphen.

## Verification

All run at `f78e181`, clean tree, this session.

| Claim | Command | Result |
|---|---|---|
| full suite | `python -m pytest tests/ -q` | **`1738 passed`** |
| ruff | `ruff check src tests eval scripts` | `All checks passed!` |
| mypy | `mypy src/halfblood` | `Success: no issues found in 43 source files` |
| PDF anchor quality | `python pdf_anchor_quality3.py` | **`48/50, STUB ANCHORS = 0`** (was 5) |
| EPUB unchanged | `python analyze_skips.py` | `rendered=48 skipped=2` |
| font from real wheel | `python prove_font_bug.py` | `RESOLVED -> site-packages/halfblood/fonts/...` |
| CLI precedence, 7 cases | `python probe_cli_precedence.py` | all correct, exit 2 / 1 as designed |
| preview JS parses | `node --check` on both `<script>` blocks | clean |
| preview XSS | `python xss_probe.py` | `raw payloads in body: 0` |
| render geometry | `python check_render_geometry.py e2e_final.pdf` | `offpage_text: 0`, no negative y0 |
| EPUB structure | `python check_epub_output.py` | mimetype/container OK, 14/14 XHTML well-formed, 48↔48 |
| end-to-end | real `annotate` via OpenRouter | `Rendered 24 / Skipped 0`, page image inspected |

**Caveat 1:** the PDF measurement replays a frozen plan against a PDF *synthesised from
jekyll.epub*. The needle drift it measures is real (it is the model's own output), but the
haystack is cleaner than a scanned or typeset book. It does not exercise hyphenation across
line breaks, columns, or OCR noise.

**Caveat 2 — the fix is scoped to the indexed path.** Both the tolerance ladder and
`_MIN_ANCHOR_COVERAGE` live inside the `index is not None` branch of
`_resolve_annotation_to_anchor`. When `PdfPageIndex` raises `PdfAlignmentError`, resolution
falls through to the older `_search_variants` + `page.search_for` loop, which still anchors
to the longest single word with no floor and no ladder — the very defect fixed above, still
live on that path. Measured reachability: **0 of 77 pages** across `jekyll_tall.pdf` (13),
`jekyll.pdf` (59) and a real rendered output (5) failed to index, so this is a rare
degradation path rather than the common case. Not a regression — it was always like this —
but it is the natural companion to the OCR item below.

## Artifacts

Committed: `src/halfblood/{cli,document_processor,web_preview}.py`; new tests
`test_cli_error_precedence.py`, `test_pdf_anchor_coverage.py`, `test_note_placement.py`,
`test_word_wrap_hyphens.py`, `test_web_preview_editing{,_js}.py`; `test_font_packaging.py`
and `test_match_tolerance.py` extended.

Scratchpad (session-local, recreate as needed): `build_jekyll_tall.py`,
`pdf_anchor_quality3.py`, `tier_census.py`, `prove_font_bug.py`, `probe_cli_precedence.py`,
`check_render_geometry.py`, `check_epub_output.py`, `check_preview_js.py`, `xss_probe.py`,
`analyze_skips.py`, `run_halfblood.py`.

## Action Items & Next Steps

1. **PDF text-extraction quality / OCR fallback** — never investigated, and it is now the
   most likely place for real-world anchor failures, since the corpus used here is clean.
   Get a genuinely typeset or scanned PDF before assuming the 48/50 generalises.
   **Do this together with Caveat 2 above**: the un-indexed fallback path still mis-anchors,
   and a messy real-world PDF is exactly what would drive resolution onto it. Measuring on a
   scanned book would establish both how often `PdfAlignmentError` really fires and whether
   the ladder plus coverage floor need lifting out of the `index is not None` branch.
2. **Annotation collision detection** — still open (known issue #14). Notes at the top of a
   page now stay on the sheet, but nothing prevents two notes overlapping each other.
3. **Connector re-draw after a preview re-position was never executed** — `doLayout` is
   stubbed in the JS harness. Correct by construction, not verified.
4. **P3 — frontier-model quality run** (owner-gated, needs credit) and the **release
   decision** (owner-gated) are both unchanged from Session 32.
5. The `hasattr(processor, "render_plan")` branch in `cli.py` is effectively dead — both
   processors have `render_plan`. Harmless, but it hides which path is live.

## Other Notes

- **Probe HEAD before believing any documented gap**, including this file. The roadmap was
  right about the matcher and my reframe was wrong; only measurement settled it.
- **Guardrails (unchanged, owner-gated):** never make the repo public; never add a second
  retry layer; never spend money; don't activate `sdd-driver`.
- Free-tier OpenRouter still drops a page occasionally; budget for it when measuring.
- **Rotate the OpenRouter key** when convenient — still pending from Session 32.
