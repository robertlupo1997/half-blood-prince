---
date: 2026-07-26
researcher: Claude (Opus 5)
git_commit: 2bc6f2c
branch: main
repository: half-blood-prince
topic: "Session 33 — --font broken in every installed wheel; PDF anchor quality 5→0 and 10→0 stubs; preview editing"
tags: [packaging, fonts, matching, pdf, rendering, web-preview, cli, parallel-lanes, negative-result]
status: complete
last_updated: 2026-07-26
---

# Session 33 — the shipped wheel couldn't find its own fonts

**10 commits. Suite 1644 → 1750. All four suggested lanes landed, plus five defects found by
rendering the real book, and by testing against a genuinely scanned one.**

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
5. ✅ **NEW — un-indexed resolution path unguarded.** 10 stub anchors of 50 → 0.
6. ✅ **NEW — margin notes clipped by the page top.** Glyph tops at y = −0.39, fixed.
7. ✅ **NEW — over-wide words broke mid-morpheme.** `counter-clockw`/`ise`, now hyphen-aware.
8. ⏳ **P3 — quality on a frontier model.** Still owner-gated (needs credit).
9. ⏳ **Release decision.** Still owner-gated.

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
| `8c474c2` | PDF: same ladder + floor on the un-indexed path; line-break union fix |
| `8ca46e6` | PDF: reject lone-word anchors instead of low coverage (scanned-book evidence) |
| `2bc6f2c` | CLI: name the cause when a PDF is a scan with no OCR text layer |

### The scanned book (`8ca46e6`, `2bc6f2c`) — the coverage floor did not survive it

Tested against the Internet Archive's 1886 scan of Jekyll & Hyde
(`strangecaseofdrj00stevrich`, "Text PDF", 151 pages with an OCR layer), with 88 real
annotations generated over 20 story pages.

**Mechanism first:** on a scanned book the model *silently repairs OCR damage while
quoting*. Handed `tlie sight of a pol` it writes `the sight of a policeman`; handed
`mould- ings` broken across a line it writes `mould-ings`. The quote is faithful to the
text as a human reads it and unfaithful to the bytes, so the complete quote matched only
**53 of 88** here against 48 of 50 on the clean corpus, and a prefix tier picked each
passage up as far as the first corrupted word. Those prefixes are correct anchors.

`coverage >= 0.5` was throwing them away — 28 of 88, nearly a third of the book:

| policy | clean (50) | scanned (88) | lone-word anchors admitted |
|---|---|---|---|
| `coverage >= 0.5` (was shipped) | 48 | **60** | 0 |
| `coverage >= 0.2` | 48 | 76 | 0 |
| **reject lone words** (now) | **49** | **84** | **0** |
| both | 48 | 76 | 0 |

`_exactness_tiers` makes the replacement structural rather than tuned: the ladder is full
quote → 8-word → 5-word → 3-word → longest single word, so **every multi-word tier is a
prefix** (it starts where the passage starts) and the single-word tier is the only one that
can land anywhere. `_is_lone_word_anchor` rejects exactly that. It *dominates* on both
corpora at once, which is the sign it is the rule and not a fitted constant.

Tier-0 rates above are from one generation run on one free-tier model. The ranking does not
depend on them.

**Also found:** `PdfAlignmentError` fired **0 of 156** times on the real scan too, so the
un-indexed path remains rare even on genuinely messy input — but a *different* real-world
class does break the tool: a page-image scan with no OCR layer at all. The first candidate
downloaded (`strangecasedrje01stevgoog`) has text on exactly 1 of 171 pages. That reported
"0 annotations" and exited 0. It now fails with the cause and `ocrmypdf` as the next step.

### The un-indexed path (`8c474c2`)

`1c5e8ed` fixed only the `index is not None` branch. Forcing `index=None` over the same
book and plan showed the un-indexed chain was **worse than the indexed path had ever been**:

```
un-indexed  before: matched 50/50, 10 stub anchors, 40 clean
un-indexed  after:  matched 48/50,  0 stub anchors, 48 clean
indexed     after:  matched 48/50,  0 stub anchors, 48 clean   (unchanged)
EPUB        after:  rendered 48, skipped 2                     (unchanged)
```

`page.search_for` is already case-insensitive, so the drift it cannot absorb alone is
punctuation the model dropped. `_tolerant_full_quote_hits` locates the quote in the page's
own text layer at `PUNCTUATION_ELASTIC` tolerance and then searches for the substring the
page *actually* contains — verbatim, therefore findable. The `_search_variants` loop is now
gated by the same coverage floor, which also closes the matching bypass on the indexed path
(reachable when `score_candidates` returns `NoMatchResult`).

**A bug was introduced and caught inside this work**, worth knowing because it is
counter-intuitive: a passage crossing a line break returns *one rect per line*, and all of
them belong to the single occurrence just located. Running them through
`_first_contiguous_hit_group_rects` — which exists to stop a short variant unioning across
*distinct* occurrences — kept only the first line, collapsing `"Mr.\nHyde has a key."` onto
a 15pt anchor over `"Mr."`: the exact symptom being fixed. Grouping now applies only when
the needle genuinely repeats on the page. The first version of the regression test did not
catch this, because a single line at fontsize 11 is ~13.9pt tall and cleared its
`height > 12` threshold; the test asserts both dimensions now.

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
| full suite | `python -m pytest tests/ -q` | **`1750 passed`** |
| ruff | `ruff check src tests eval scripts` | `All checks passed!` |
| mypy | `mypy src/halfblood` | `Success: no issues found in 43 source files` |
| PDF anchor quality (indexed) | `python pdf_anchor_quality3.py` | **`49/50`**, 0 lone-word anchors |
| PDF anchor quality (un-indexed) | `python unindexed_quality.py` | **`49/50`**, 0 stubs (was 10) |
| real scanned book | `python floor_policy_ab.py` | **`84/88`** (was 60), 0 lone-word anchors |
| image-only scan is diagnosed | real CLI on `scanned_jekyll.pdf` | exit 1, names OCR + `ocrmypdf` |
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

**Caveat 2 — RESOLVED in `8c474c2`.** The ladder and floor initially lived only inside the
`index is not None` branch, leaving the un-indexed chain unguarded. Forcing `index=None`
over the same book showed it was **worse than the indexed path had been — 10 stub anchors
of 50** (`"Mr. Hyde has a key."` → `"Mr."`). Now fixed; all three paths agree at 48/50.
See "The un-indexed path" below. Reachability of that branch remains low (**0 of 77 pages**
across `jekyll_tall.pdf`, `jekyll.pdf` and a real rendered output failed to index), but it
is no longer a hole.

**Caveat 3 — `find_text_rect` (v1) is deliberately still loose.** It keeps the
unconditional single-word fallback, because `tests/test_pdf_targeting.py` (AUD-26) pins that
fallback firing, and because the CLI never reaches it — `render_plan` exists on both
processors, so the `hasattr` branch always takes v2. The asymmetry is now recorded in the
method's docstring so it is not mistaken for an oversight.

## Artifacts

Committed: `src/halfblood/{cli,document_processor,web_preview}.py`; new tests
`test_cli_error_precedence.py`, `test_pdf_anchor_coverage.py`, `test_note_placement.py`,
`test_word_wrap_hyphens.py`, `test_web_preview_editing{,_js}.py`; `test_font_packaging.py`
and `test_match_tolerance.py` extended.

Scratchpad (session-local, recreate as needed): `build_jekyll_tall.py`,
`pdf_anchor_quality3.py`, `unindexed_quality.py`, `diagnose_unindexed.py`, `tier_census.py`, `prove_font_bug.py`, `probe_cli_precedence.py`,
`check_render_geometry.py`, `check_epub_output.py`, `check_preview_js.py`, `xss_probe.py`,
`analyze_skips.py`, `run_halfblood.py`.

## Action Items & Next Steps

1. **OCR fallback for page-image scans.** Now that a textless scan is *diagnosed* rather
   than silently empty, the open question is whether the tool should OCR such files itself
   (shelling out to `ocrmypdf`/Tesseract behind a flag) or keep telling the user to. That
   is a dependency decision, not a matcher one. The rest of the "PDF extraction quality"
   item is answered: on a real OCR'd scan the anchor rules hold at 84/88, and
   `PdfAlignmentError` fired 0 of 156 times.
2. **Should the EPUB path accept prefix anchors too?** `documents/epub.py` is still tier-0
   only, so PDF renders 49/50 where EPUB renders 48/50 on the same plan. Its docstring
   frames tier-0-only as a contract ("segments always represent the selector's full
   normalized exact quote"), not a technical limit — a prefix span would still produce
   valid segments. Wants its own measurement on a real EPUB before changing.
3. **Annotation collision detection** — still open (known issue #14). Notes at the top of a
   page now stay on the sheet, but nothing prevents two notes overlapping each other.
4. **Connector re-draw after a preview re-position was never executed** — `doLayout` is
   stubbed in the JS harness. Correct by construction, not verified.
5. **P3 — frontier-model quality run** (owner-gated, needs credit) and the **release
   decision** (owner-gated) are both unchanged from Session 32.
6. The `hasattr(processor, "render_plan")` branch in `cli.py` is effectively dead — both
   processors have `render_plan`. Harmless, but it hides which path is live.

## Other Notes

- **Probe HEAD before believing any documented gap**, including this file. The roadmap was
  right about the matcher and my reframe was wrong; only measurement settled it.
- **Guardrails (unchanged, owner-gated):** never make the repo public; never add a second
  retry layer; never spend money; don't activate `sdd-driver`.
- Free-tier OpenRouter still drops a page occasionally; budget for it when measuring.
- **Rotate the OpenRouter key** when convenient — still pending from Session 32.
