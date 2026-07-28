---
date: 2026-07-27
researcher: Claude (Opus 5)
git_commit: f59fce8
branch: main
repository: half-blood-prince
topic: "Session 34 — the renderer crashed on real books and the CLI ate them; EPUB prefix anchors; README truth pass"
tags: [crash, data-loss, matching, epub, connectors, packaging, docs, parallel-lanes, adversarial-review]
status: complete
last_updated: 2026-07-27
---

# Session 34 — two defects that were on nobody's list

**28 commits. Suite 1750 → 1849. Five parallel lanes, every one sent back at least
once by adversarial review, three sent back twice.**

The two worst defects this session were found by **running the product**, not by
reading it, and neither was on any list — not CLAUDE.md's Known Issues, not the
Session 33 handoff, not either reconnaissance pass's initial sweep:

1. **`halfblood annotate` crashed outright on densely-typeset books.** A bare
   `ValueError("too many obstacles")` escaped `render_plan`. It fires on **12 of
   156 pages (8%)** of a genuine Internet Archive scan.
2. **The tool destroyed the user's book.** `-o INPUT --force` overwrote the
   source. Worst case measured: EPUB `rendered=0 skipped=1` — it destroyed the
   original *and* produced nothing.

The single most valuable process note is **Learnings §1**: every Codex review
found something real, including three defects in this session's own work. The
review loop is not ceremony here; it is where correctness actually came from.

---

## Task(s)

1. ✅ **Connector obstacle crash** → degrade, never raise. Plus two deeper gaps.
2. ✅ **Data loss** — output==input, across three separate variants.
3. ✅ **EPUB prefix anchors** (roadmap item #2) — decided by measurement: **53 → 84 of 88**.
4. ✅ **Preview connector re-draw** (item #3) — was genuinely correct; now actually executed.
5. ✅ **OCR fallback decision** (item #4) — `docs/decisions/ocr-fallback.md`. **Do not bundle OCR.**
6. ✅ **Dead `hasattr` branch** (item #5) — removed.
7. ✅ **CI wheel smoke test** — systemic fix for the whole `__file__` bug class.
8. ✅ **README truth pass** — six materially false claims corrected.
9. ⏳ **Frontier-model eval quality run** — still owner-gated (needs credit).
10. ⏳ **Public release** — still owner-gated.

## Critical References

- `docs/decisions/ocr-fallback.md` — why OCR stays out, argued from a measurement.
- `docs/decisions/verbatim-quoting-prompt-vs-matcher.md` — the wrong-anchor principle
  everything in the matcher rests on. Its addendum now records the corpus provenance.
- `scripts/wheel_smoke.py` — builds the wheel, installs it into a clean venv outside
  the repo, and uses it. **Run this for anything computing a path from `__file__`.**

## Recent changes

| commit | what |
|---|---|
| `3e80b0f` | CI wheel smoke test, OCR decision, Python 3.13 in the matrix |
| `effe4d7` | Lane C — Anthropic malformed-response normalization |
| `7e40aac` | Lane A — connectors degrade instead of crashing |
| `277c633` | Lane B — data loss + `--pages` + `eval`-in-wheel + dead branch |
| `5217421` | cap flag reaches the render report |
| `6944311` | README truth pass; `_CONNECTOR_OBSTACLE_LIMIT` docstring corrected |
| `3bb424a` | grapheme-safe wrap; working `--font` keys; honest scope notes |
| `f59fce8` | Lane A round 3 — 4 silent crossings → 0 |

## Learnings

### 1. Every adversarial review found something real — including in my own work

Five lanes, eight review passes, **zero clean bills of health on first submission.**

| lane | round 1 | round 2 | round 3 |
|---|---|---|---|
| A connectors | 6 findings, 1 BLOCKING | 2 BLOCKING | verified |
| B CLI | 3 findings, 1 BLOCKING | 1 BLOCKING | verified |
| C provider | 4 CONFIRMED | verified | — |
| D preview | 2 BLOCKING | verified | — |
| E EPUB | 2 BLOCKING | 1 BLOCKING | verified |

Three findings in the final round were defects in **my own** work: a wrap fix that
detached combining marks (`"áb"` → `["a", "́b"]`), a README recommending
`--font "Caveat Brush"` which the CLI **rejects** (the key is `caveat-brush`), and a
test whose docstring claimed "Every composition degradation code" while enumerating
one enum of three, when an AST sweep found 8 of 11 composer codes unmapped.

**Do not skip the review because a lane's report is convincing.** The reports were
consistently accurate about what was done and consistently blind to what was missed.

### 2. Two "improvements" this session were partly wrong answers

- Lane E round 2 raised the clean corpus 48 → 49 and I recorded the PDF/EPUB
  divergence as closed. Round 3 showed **that 49th was a wrong anchor** — the
  overlap guard was case-sensitive regardless of tolerance, so an ambiguous
  overlapping quote slipped through. The honest number is **48/50, and the
  divergence is NOT closed.** 48 with no wrong anchors beats 49 with one.
- Lane A rounds 1 and 2 left the crossing count at 10/49 both times. Round 3
  explained why: validation only ran inside `if blocked:`, and `blocked` was decided
  from the **midpoint alone**, so most connectors were never validated at all.

### 3. Rig errors, again — three of mine, caught before they reached a conclusion

- Connector crossings first read **49/49**. A connector is *supposed* to reach its
  target, whose line-run is in the obstacle set. Excluding endpoint-owning
  obstacles: **10/49**. A 100% failure rate is a rig smell, not a finding.
- The scanned EPUB corpus first read `rendered=0`. The **nav document occupies spine
  ordinal 1**, so chapter *n* lands at ordinal *n+1*.
- `wheel_smoke.py`'s own first assertion passed while the bug was live: it checked
  the error didn't mention `site-packages`, but `parents[2]` from
  `<venv>/lib/python3.12/site-packages/halfblood/cli.py` is `<venv>/lib/python3.12/`
  — it strips that segment right off. It now keys on the venv root.

A cross-check that worked: the EPUB baseline landed on **53/88** and the variant on
**84/88**, the exact figures the PDF path independently produced on the same corpus.
Two independently derived numbers hitting known values is decent evidence a rig
reproduces the real path.

### 4. A lane's `pip install -e .` silently hijacked the shared venv

`_editable_impl_half_blood_prince.pth` was repointed at a lane's worktree, so bare
`python -c` in the MAIN tree imported **that lane's code**. Restored manually.
Per-lane `pytest` runs were unaffected — `tests/conftest.py:19` inserts each tree's
own `src` at `sys.path[0]` — but ad-hoc probes were. **Verify with
`python -c "import halfblood; print(halfblood.__file__)"` before trusting a probe.**

### 5. Data loss had three variants, and the "structural" fix wasn't

Round 1 guarded the input book. Round 2 found `web-preview` destroying its plan and
`--book`. Round 3 found `annotate` destroying the persona, config, and font files.

Round 2 claimed a plural `source_paths` parameter was a "structural guarantee".
Review refuted it: **a plural signature does not make callers populate it.** The
guarantee came from a table-driven test that feeds every file input of every
output-writing command back as `-o ... --force` and asserts the bytes are unchanged.

## Verification

All run at `f59fce8`, clean tree.

| Claim | Command | Result |
|---|---|---|
| full suite | `python -m pytest tests/ -q` | **`1849 passed`** |
| ruff | `ruff check src tests eval scripts` | `All checks passed!` |
| mypy | `mypy src/halfblood` | `Success: no issues found in 43 source files` |
| wheel usable from clean venv | `python scripts/wheel_smoke.py` | `PASSED` |
| EPUB scanned corpus | `verify_e.py` | **`84 / 88`** (was 53) |
| EPUB clean corpus | `verify_e.py` | `48 / 50` (unchanged; see Learnings §2) |
| PDF render, dense book | `connector_crossing.py` | `rendered 49 skipped 1`, no crash |
| silent connector crossings | `silent_check.py` | **`0`** (was 4) |
| data loss, 8 combinations | real CLI + sha | all `exit 1`, `INTACT` |
| page image read by eye | `final_page.png` | notes on-page, targets circled |

**Caveat:** the corpus numbers are measured on **session-local** corpora that are not
in the repo (a scanned-Jekyll EPUB built from an Internet Archive OCR text layer, and
frozen plans). They are reproducible only by rebuilding those; the decision doc records
how, including the spine off-by-one.

## Artifacts

Committed: `src/halfblood/{cli,document_processor,web_preview}.py`,
`src/halfblood/ink/{rough,composer}.py`, `src/halfblood/documents/epub.py`,
`src/halfblood/epub_processor.py`, `src/halfblood/generation/providers/anthropic.py`,
`src/halfblood/models/rendering.py`, `scripts/wheel_smoke.py`,
`.github/workflows/ci.yml`, `docs/decisions/ocr-fallback.md`, README; new tests
`test_connector_dense.py`, `test_cli_hardening.py`, `test_epub_prefix_tiers.py`,
`test_degradation_mapping.py`.

Scratchpad (session-local, recreate): `connector_crossing.py`, `silent_check.py`,
`verify_e.py`, `epub_prefix_ab.py`, `build_scanned_epub.py`, `prove_selfdestruct.py`,
`prove_json_asym.py`, `obstacle_census.py`, `prune_isolate.py`.

## Action Items & Next Steps

1. **Connector routing quality — the real remaining defect.** 10 of 49 connectors on
   a dense page still cross body text. They are now all honestly flagged
   (`ROUTING_FALLBACK`, 0 silent), but the router genuinely exhausts its attempts.
   Reducing the 10 needs a better router — more waypoint strategies, or accepting a
   longer path — not more validation. **This is the highest-value open item.**
2. **8 of 11 composer degradation codes are unmapped** (`caret_interline_gap_unavailable`,
   `ink_geometry_invalid`, `unknown_doodle_kind`, …) and take the warning-and-drop
   branch, so those degradations never reach the user. Wants a finite composer-code
   enum mapped exhaustively. `tests/test_degradation_mapping.py` covers only
   `ConnectorDegradation` and says so.
3. **A config-file-derived font** (not `--font`) is guarded in code but not covered by
   the data-loss table test, which uses a faked config resolver.
4. **`--pages` empty-string and `1,,2`** are tolerated silently. Defensible, not decided.
5. **Python 3.13 is now in the CI matrix but was never run locally** — no 3.13 on this
   machine. If CI goes red there, that is the claim being tested, not a regression.
6. **P3 frontier-model quality run** and the **release decision** remain owner-gated.

## Other Notes

- **Probe HEAD before believing any documented gap, including this file.** Known issue
  #14 ("annotation collision detection") was **already built** — both recon passes
  found `layout/engine.py:331` folding note boxes into `forbidden_rects` and
  `test_solver_contracts.py:229-280` pinning it. The Opus pass, which trusted
  CLAUDE.md, listed it as open. That entry can be closed.
- **`test_docs.py` asserted keywords were PRESENT**, which is why the README described
  Claude-only generation, native PDF marks, an unbundled font, and `models.py` long
  after all four became false. Tests now assert the **absence** of refuted claims and
  **execute** documented commands.
- **Guardrails (unchanged, owner-gated):** never make the repo public; never add a
  second retry layer (Codex verified by `git blame` that none was added); never spend
  money; don't activate `sdd-driver`.
- **Rotate the OpenRouter key** — still pending from Session 32.
