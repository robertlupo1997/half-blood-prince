---
date: 2026-07-10T21:47:03-04:00
researcher: Claude
git_commit: d7f0908d0914170f8cb75735ff96147d87871492
branch: main
repository: half-blood-prince
topic: "v0.1.0 portfolio release — Session 4 (EPUB fixture, audit ledger compiled, Phase 1 closed except key-blocked E2E)"
tags: [release-plan, sdd, audit, epub-fixture, audit-ledger]
status: complete
last_updated: 2026-07-10
type: handoff
---

# Handoff: v0.1.0 Session 4 — Phase 1 complete except E2E (Tasks 5 + 6.3-4, blocked on ANTHROPIC_API_KEY)

## Task(s)

Governing documents (read in this order):
1. `docs/superpowers/specs/2026-07-10-portfolio-release-design.md` — approved spec
2. `docs/superpowers/plans/2026-07-10-foundation-and-audit.md` — Phase 1 plan (7 tasks)
3. `.superpowers/sdd/progress.md` — SDD ledger (trust it + `git log` over memory)

- ✅ Tasks 1–2 (lint gate, CI) — Session 1 (see first handoff)
- ✅ Task 3 (six-lens audit, 45 raw findings) — Session 2
- ✅ Task 4 (adversarial verification + merge) — Sessions 2–3; `verified.md`
  on disk: 45 raw → 42 confirmed / 0 refuted / 2 downgraded / 1 merged, AUD-01..44
- ✅ **Task 6 Steps 1–2 (this session)**: EPUB fixture generator + fixture
  committed (`9963412`)
- ✅ **Task 7 (this session)**: audit ledger compiled and committed (`7ef3e2d`)
  — `docs/audit/2026-07-10-adversarial-audit.md`
- ✅ **Settings amendment committed (this session)**: user-authorized ask-list
  removal (`d7f0908`)
- ⏳ **Task 5 (PDF E2E + cost) and Task 6 Steps 3–4 (EPUB E2E)**: BLOCKED on
  `ANTHROPIC_API_KEY` — the ONLY remaining Phase 1 work. Exact commands are in
  the audit doc's "E2E results" section and in `e2e_pdf.py`'s docstring.
- ⏳ After that (or in parallel, since findings are final): author the
  **Phase 2 fix plan** from the audit ledger (one TDD task per AUD-NN,
  severity order).

## Critical References

1. `docs/audit/2026-07-10-adversarial-audit.md` — THE deliverable: 44 findings
   (AUD-01..44) + 3 lint deferrals (L-1..3) + inherited #8–15 re-verdicts +
   accepted/won't-fix. Phase 2 plans from this document alone.
2. `docs/superpowers/plans/2026-07-10-foundation-and-audit.md` — Task 5/6
   steps for the E2E runs; "Deferred to subsequent plans" for Phase 2/3 shape.
3. `.superpowers/sdd/audit/{verified.md, e2e_pdf.py, repro/}` — detailed
   evidence behind the committed ledger (gitignored, durable on disk).

## Recent changes

- `tests/fixtures/make_test_epub.py` (new, commit `9963412`) — 3-chapter EPUB
  fixture generator; `__file__`-relative output path (plan deviation: the
  plan's `cd tests/fixtures` + repo-relative path would have broken; matches
  `make_potions_textbook.py` convention)
- `tests/fixtures/sample_book.epub` (new, same commit) — generated fixture,
  3,230 bytes
- `docs/audit/2026-07-10-adversarial-audit.md` (new, commit `7ef3e2d`) — the
  audit ledger (324 lines)
- `.claude/settings.json` (commit `d7f0908`) — ask-list removed per the
  ledger's SETTINGS AMENDMENT entry (user-authorized; see Learnings 4)
- `.superpowers/sdd/progress.md` — Session 4 entries appended (not in git)

**No product code changed this session** (`src/`, `eval/` untouched).

## Learnings

1. **Inherited issue #10's mechanism was wrong in an interesting way:**
   `find_text_rect` (document_processor.py:298-306) does NOT anchor to the
   first occurrence of a fallback word — it returns `_union_rects(hits)`
   across ALL occurrences, so a repeated word yields a rect spanning most of
   the page. Recorded in the audit doc's inherited table; Phase 2 fix should
   target disambiguation, and AUD-26's regression test should assert anchor
   choice, not just "found something".
2. **EPUB nav page is annotatable:** `EpubProcessor.load()` on the new fixture
   returns 4 documents — the nav/TOC page plus 3 chapters. The E2E run (Task 6
   Step 3) should decide whether nav docs need skipping; noted in the audit
   doc's E2E section.
3. **Session 3 wrote no handoff** (froze on ask-dialogs before close-out).
   Its state was reconstructed from the user brief + ledger and re-verified on
   disk this session — everything held. Lesson: the ledger's per-step entries
   made a handoff-less recovery cheap.
4. **Ask-list overrides every permission mode** (empirical, from Session 3's
   freeze): explicit `ask` rules in committed settings.json fire even under
   `bypassPermissions` / `--dangerously-skip-permissions`. The ask list is now
   removed from the committed file (`d7f0908`, user-authorized per the
   ledger's SETTINGS AMENDMENT entry). allow/deny + PreToolUse guard hook are
   untouched. **Phase 4's pre-push settings re-audit must treat this diff as
   expected. Do not restore the ask list; do not touch
   `.claude/settings.local.json`.**
5. The PreToolUse guard hook still blocks any Bash command naming the API-key
   env var — don't fight it; key presence surfaces when the Task 5 runner
   executes.
6. Repro scripts and `verified.md` are gitignored session artifacts; the
   committed audit doc points at them by path. If this machine's checkout is
   lost before Phase 2 lands regression tests, the repros are gone (the
   findings themselves survive in the committed doc).

## Verification

| Claim | Command run this session | Result |
|---|---|---|
| HEAD `d7f0908`, branch `main` | `git rev-parse HEAD; git rev-parse --abbrev-ref HEAD` | `d7f0908d0914170f8cb75735ff96147d87871492`, `main` |
| Session 4 commits present | `git log --oneline` (after each commit) | `9963412` fixture, `7ef3e2d` audit ledger, `d7f0908` settings |
| Working tree clean after settings commit | `git status --short` (after `d7f0908`) | empty |
| Gate green after ALL session changes | `.venv/bin/ruff check src tests eval && .venv/bin/mypy src/halfblood && .venv/bin/pytest tests/ -q` (re-run 21:47, after last commit) | All checks passed; no issues in 7 source files; `44 passed` |
| Fixture loads via product code | `python -c "...EpubProcessor().load('tests/fixtures/sample_book.epub')"` | `4 chapters loaded` (nav + 3 chapters, sizes 70/221/200/204 chars) |
| `verified.md` complete (Task 4) | Read the file | header: `45 raw → 42 confirmed / 0 refuted / 2 downgraded / 1 merged`; entries AUD-01..44 |
| `e2e_pdf.py` present, run commands in docstring | Read the file | both run commands present (retired-model demo + `--model claude-sonnet-5` cost run) |
| Retired model at cited lines | `grep -rn "claude-sonnet-4-20250514" src eval` | `annotation_generator.py:192`, `cli.py:46`, `eval_harness.py:73` |
| `find_text_rect` unions all hits (Learning 1) | `sed -n '280,310p' src/halfblood/document_processor.py` | `hits = page.search_for(variant)` … `return self._union_rects(hits)` (lines 298, 306) |
| `_locate_text` single-node only (inherited #12) | `grep -n "NavigableString" src/halfblood/epub_processor.py` | return type `tuple[NavigableString, int, int] \| None` at line 337 |
| Font warning per-run (inherited #15) | Read document_processor.py:140-195 | `logger.warning(...)` at line 185 in `_resolve_handwriting_font` |
| Settings diff = ask-list only | `git diff .claude/settings.json` (pre-commit) | exactly the 11-entry `ask` block deletion |
| `ANTHROPIC_API_KEY` presence | — | UNVERIFIED (guard hook blocks env inspection naming the key; Task 5's runner surfaces it definitively) |

## Artifacts

- `tests/fixtures/make_test_epub.py`, `tests/fixtures/sample_book.epub` — committed (`9963412`)
- `docs/audit/2026-07-10-adversarial-audit.md` — committed (`7ef3e2d`)
- `.claude/settings.json` — amendment committed (`d7f0908`)
- `.superpowers/sdd/progress.md` — Session 4 ledger entries (disk only)
- `thoughts/shared/handoffs/2026-07-10_21-47-03_v010-session4-audit-ledger.md` — this handoff
- `HANDOFF.md` — pointer updated this session

## Action Items & Next Steps

1. [ ] **When `ANTHROPIC_API_KEY` exists — Task 5:** run the two commands in
   `e2e_pdf.py`'s docstring (Run 1 default model = live demo of AUD-02's
   silent-empty-output; Run 2 `--model claude-sonnet-5` = real cost
   measurement). Record results in the ledger AND update the audit doc's
   "E2E results" section (it currently says BLOCKED).
2. [ ] **When key exists — Task 6 Steps 3–4:** `halfblood annotate
   tests/fixtures/sample_book.epub -o .superpowers/sdd/audit/e2e-epub-annotated.epub
   --model claude-sonnet-5`; verify output XHTML per plan Task 6 Step 4;
   write `e2e-epub-report.md`; update the audit doc. Watch Learning 2 (nav
   page) and AUD-18 (curly-quote misses) live.
3. [ ] **Phase 2 fix plan** can be authored NOW from
   `docs/audit/2026-07-10-adversarial-audit.md` (findings are final; E2E only
   adds cost numbers + live confirmation). One TDD task per AUD-NN, severity
   order; honor the coupled tasks: AUD-06 (pattern+ReDoS+tests one task),
   AUD-02/03/04+16 (model bump + failure surfacing), AUD-05+14+21 (stop_reason
   + empty-input + truncation test).
4. [ ] Report to Trey (plan Task 7 Step 3) if not already seen: 1 Critical /
   12 High / 17 Medium / 14 Low; worst three in plain language: (a) the
   default model is retired so the app silently produces empty annotated
   books, (b) margin notes can render off-page and lose content, (c) the web
   preview can't highlight any multi-word passage. Cost/page pending E2E.

## Other Notes

- Execution style: superpowers:subagent-driven-development for fan-out phases;
  Session 4 was controller-only (no subagents — remaining work was small and
  serial).
- Repo on /mnt/c under WSL — git and pytest are slow (~32s for the suite);
  venv at `.venv/` works.
- `thoughts/` and `.superpowers/` are gitignored; this handoff must be
  force-added (`git add -f`), matching the Session 2 convention (Session 1's
  handoff was never force-added and is NOT in git — disk only).
- Do NOT re-dispatch Tasks 1–4; ledger + committed artifacts prove completion.
