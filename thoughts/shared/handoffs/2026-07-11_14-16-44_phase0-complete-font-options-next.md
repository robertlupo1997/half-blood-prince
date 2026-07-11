---
date: 2026-07-11T14:16:44-04:00
researcher: Claude (Fable 5) — controller in the Codex-implementer loop
git_commit: 9761f4014da371b2d697611c9795d77666af47fe
git_branch: main
repository: half-blood-prince
topic: "Session 7 — PHASE 0 COMPLETE & MERGED; next: font-options feature (F1), then Phase 1"
tags: [phase0-complete, sdd, codex-loop, fonts, pdf-rendering, handoff]
status: complete
---

# Handoff: Phase 0 closed & merged — font options (F1) queued, then Phase 1

> **Owner directives standing for the next session:**
> 1. **Delegate as much work as possible to Codex/GPT-5.6.** The controller
>    keeps ONLY: test authorship, independent gate verification, sha256 test
>    snapshots, diff review against the PLAN's contract (see learning #1), and
>    artifact publishing (Codex cannot publish; its sandbox has no network).
>    Everything else — implementation, doc edits, render scripts — goes to
>    Codex (`sol`=judgment-heavy, `terra`=quick/mechanical).
> 2. **Font options feature (F1) comes before Phase 1**: the owner wants to
>    choose between Just Me Again Down Here, Homemade Apple, and Mrs Saint
>    Delafield. Owner has offered to fetch any files/pages we cannot reach.

## Task Status

### Current Phase
Phase 0: **COMPLETE and MERGED to `main`** (merge commit `9761f40`, --no-ff).
Full gate re-verified ON MAIN this session: ruff clean, mypy clean,
**205 passed** (suite grew 102 → 205). NOT pushed — no remote configured.

### Progress
- [x] P0-T1..T3 (Session 6): `06c253d`, `1beeb2a`, `21318cc`
- [x] P0-T8 EPUB coverage + AUD-18 + NEW CSS-drop bug: `909c5f3`
- [x] P0-T4 web preview matching/ReDoS/U+2028: `94dac60`
- [x] P0-T7 magic bytes + --force + parents: `e09a81e`
- [x] P0-T10 offline preview + font-notice hygiene: `0e4d114`
- [x] P0-T5 PDF geometry on-page (L): `07ddc4d`
- [x] P0-T9 false-green tests (controller-executed): `811cea7`
- [x] P0-T11 docs reconciliation: `cbe572e`
- [x] P0-T6 target selection + crossed-out placement: `29252cd`
- [x] P0-T12 dep bounds + lock + closure report (controller-executed): `0b50d6a`
- [x] Merge to main + gate on main: `9761f40`
- [ ] **F1 — font options (NEXT, owner-requested)**: see plan below
- [ ] Phase 1 (P1-T1 semantic plan v2 → …) per the implementation plan
- [ ] Blocked-on-key live E2E (commands in the closure report)

## Critical References

1. `docs/superpowers/plans/2026-07-11-phase0-1-implementation-plan.md` — Phase 1 tasks (P1-T1..T9) are next after F1
2. `docs/audit/2026-07-11-phase0-closure.md` — disposition of all 44 AUD + L-1..3; blocked-on-key commands
3. `.superpowers/sdd/progress.md` — full session-by-session ledger (Session 7 appended)
4. `.superpowers/sdd/p0-t*-{brief,report}.md` — dispatch/report pairs; reuse the brief format (Pre-flight line first)
5. Font-trial artifact (owner-facing): https://claude.ai/code/artifact/e258a268-2a9b-48a7-bc05-1102ad7ebb09
   — to update it from a NEW session, pass this URL as the `url` param of the Artifact tool (otherwise a new URL is minted)

## F1 — font options plan (execute via the SDD loop, maximal Codex delegation)

**Goal:** `halfblood annotate --font <name|path>` selects the PDF handwriting
font; owner picks the default after seeing renders of all three candidates.

**Font facts (license verification done this session):**
| Font | License | RFN | File on disk? |
|---|---|---|---|
| Just Me Again Down Here | OFL 1.1, Kimberly Geswein | **no RFN** | ✅ `fonts/JustMeAgainDownHere.ttf` (gitignored, persisted) |
| Caveat Brush (incumbent) | OFL 1.1, Impallari Type | RFN declared | ✅ `fonts/CaveatBrush-Regular.ttf` |
| Mrs Saint Delafield | OFL 1.1, Alejandro Paul (Sudtipos) | **RFN "Mrs Saint Delafield"** | ❌ need TTF |
| Homemade Apple | **UNVERIFIED** — NOT under google/fonts `ofl/` (only `homemademac` exists there); very likely `apache/homemadeapple` (Apache 2.0) | n/a if Apache | ❌ need TTF |

**ASK THE OWNER (he offered):** drop these two files into `fonts/`:
- `fonts/HomemadeApple-Regular.ttf` — https://fonts.google.com/specimen/Homemade+Apple (download family zip)
- `fonts/MrsSaintDelafield-Regular.ttf` — https://fonts.google.com/specimen/Mrs+Saint+Delafield
Also confirm Homemade Apple's license file from the zip (Apache 2.0 vs OFL) —
it matters for THIRD_PARTY_NOTICES and Phase-3 skeletonization candidacy.
(Next session can also try `python urllib` from `.venv` — that fetch method
was permission-approved this session; `curl` was denied twice.)

**Test-first spec (controller writes `tests/test_font_selection.py`):**
- `--font <path>` (existing .ttf): CLI constructs the processor with
  `font_path=<path>` (fake processor records ctor kwargs — existing test_cli
  fakes take no kwargs, so use new fakes in the new file).
- `--font <registered-name>`: resolves via a small registry
  (name → expected filenames/glob under `fonts/` + Google Fonts URL), e.g.
  `just-me-again-down-here`, `homemade-apple`, `mrs-saint-delafield`,
  `caveat-brush`. Present → processor gets the resolved path.
- Named font missing on disk → ClickException naming the font, the expected
  `fonts/<file>` location, AND its Google Fonts URL; generation never called.
- Unknown name that is not a path → error listing the registered names.
- `--font` with an `.epub` input → warning that EPUB uses reader/CSS fonts,
  flag ignored, pipeline proceeds (PDF-only feature for now).
- `annotate --help` lists the registered names.
- Resolution helper is unit-testable with an injected fonts dir (tmp_path).
**Then:** snapshot hashes → brief with Pre-flight line → dispatch
`gpt-5.6-terra` medium (`codex exec --sandbox workspace-write -C <repo>
-m gpt-5.6-terra -c model_reasoning_effort=medium -o <report> < <brief>`)
→ controller re-runs full gate + `sha256sum -c` → commit. Files for Codex:
`src/halfblood/cli.py` (+ optional tiny helper module), `fonts/README.md`.
Work on a short branch (`font-options`), merge on green (precedent).

**Renders + artifact update (controller, after fonts exist):** reuse the
render approach from this session — same 4 annotations, fixture p.2, seed 42,
`DocumentProcessor(font_path=...)`, rasterize via `get_pixmap`; regenerate
`prince-hand-font-trial.html` with all candidates and republish with the
`url` param above. Owner then picks the default; if adopted, raise the
opacity floor (~0.7) for thin faces like JMADH.

## Recent Changes (this session, all on `main` via `9761f40`)

- `src/halfblood/epub_processor.py` — symmetric punctuation folding in
  `_normalize_with_map`; CSS as manifest EpubItem + per-chapter link
  (EbookLib drops soup-injected `<head>` styles at write — head is rebuilt
  from `metas/title/links` only, see `ebooklib/epub.py:409`)
- `src/halfblood/web_preview.py` — per-char `_flexible_pattern` (the old one
  matched NOTHING multi-word: `re.escape` ran before the space substitution),
  `_MAX_TARGET_LENGTH=1500`, U+2028/29 escapes, Google Fonts links removed
- `src/halfblood/cli.py` — `_validate_input_signature` (magic bytes before any
  processor), `_refuse_existing_output` (--force), parent mkdir
- `src/halfblood/document_processor.py` — margin side resolution + vertical
  clamp + char-safe token split + interline capping (P0-T5);
  `_first_contiguous_hit_group` + normalized page-word fallback + crossed-out
  dispatch (P0-T6); once-per-process font notice + explicit-path warning
- `src/halfblood/models.py` — str_strip_whitespace + min_length=1 (P0-T2)
- 10 new test files; suite 102 → 205
- `pyproject.toml` upper bounds; `requirements-dev.lock`;
  `docs/audit/2026-07-11-phase0-closure.md`
- README/ARCHITECTURE/CLAUDE.md reconciled with reality (P0-T11)

## Key Learnings

### What Worked
- The controller/implementer loop at full clip: 9 tasks in one session, every
  Codex diff hash-verified + plan-reviewed, every gate controller-run.
- Codex honesty: it flagged its own 30s-harness truncation instead of
  fabricating a green suite (P0-T7/T10 reports).
- Probing BEFORE writing tests (EPUB write-path probe found the CSS-drop bug;
  PDF probe measured the 415pt union rect).

### What Didn't Work / Watch For
1. **Defective controller tests induce scope creep** (now a memory:
   `controller-test-defects-induce-scope-creep`): Codex deleted the designed
   prefix-fallback tiers to satisfy an over-constrained adversarial test
   (P0-T4), and added a `len(words)==1` bypass to satisfy a stale legacy test
   (P0-T5). Both times: controller fixed the TEST and reverted the workaround.
   Review diffs against the plan's contract, not test greenness.
2. **Codex's sharded pytest counts inflate** (claimed 167 when the suite was
   165 at P0-T10). The controller's full run is the number of record.
3. Stale `.git/index.lock` left by the Codex sandbox once — check
   `ps aux | grep git` before removing.
4. PyMuPDF base-14 `insert_text` substitutes unsupported smart punctuation
   with `·` in the text layer — synthetic fixtures with curly chars carry
   this artifact; `_normalize_search_text` now folds it symmetrically.
5. `curl` is permission-denied in this environment; `.venv/bin/python` +
   `urllib.request` was approved for the font downloads.

### Important Discoveries
- EbookLib 0.20 `EpubHtml.get_content()` rebuilds `<head>` from
  `metas/title/links` — ANY soup-injected head content silently vanishes from
  written EPUBs (`ebooklib/epub.py:409-478`). Also `EpubNav` content is
  regenerated from the TOC, so annotations rendered into the nav are discarded.
- Nav spine items are written `linear="yes"` by EbookLib → nav counts as
  page 1 (pinned in `tests/test_epub_processor.py`).

## Blockers (if any)

- Live E2E blocked on `ANTHROPIC_API_KEY` (commands in the closure report).
- F1 blocked on the two missing TTFs (owner fetching, or python-urllib next session).
- Homemade Apple license identification (probably Apache 2.0 — verify from
  the downloaded zip's license file).

## Action Items & Next Steps

1. [ ] **F1 font options** per the plan above (owner drops TTFs in `fonts/`,
   controller writes tests, Codex implements, artifact updated, owner picks
   the default; adopt opacity-floor bump if a thin face wins).
2. [ ] **Phase 1** starting at P1-T1 (semantic plan v2 + v1 migration), then
   P1-T2/T3 per the critical path. Maximal Codex delegation throughout.
3. [ ] When a key exists: run the closure report's live E2E, record cost.
4. [ ] Owner decisions pending: default font; push to a GitHub remote.

## Verification Commands

```bash
cd /mnt/c/Users/Trey/Downloads/half-blood-prince
git rev-parse HEAD          # 9761f4014da371b2d697611c9795d77666af47fe on main
git status --short          # clean (fonts/*.ttf are gitignored)
.venv/bin/ruff check src tests eval          # All checks passed!
.venv/bin/mypy src/halfblood                 # no issues in 7 files
.venv/bin/pytest tests/ -q                   # 205 passed (~30-40s on /mnt/c)
ls fonts/                   # CaveatBrush-Regular.ttf, JustMeAgainDownHere.ttf, README.md
```

## Other Notes

- Repo on `/mnt/c` under WSL: use `.venv/bin/...` for everything; suite takes
  ~30-40s; Codex must use the same venv.
- Handoffs are force-added (`thoughts/` is gitignored); `HANDOFF.md` at repo
  root is the pointer — update it to this file.
- Autonomy config: `.claude/settings.local.json` has bypassPermissions; the
  committed PreToolUse guard blocks only destructive ops — do not "fix" it.
- The font-trial artifact and the closure report double as the before-pictures
  for Phase 2's occupancy/layout work.
