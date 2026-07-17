---
date: 2026-07-17T08:27:45-04:00
researcher: Claude (Opus 4.8) — controller session
git_commit: 118728da042a2a9d340a61ad419bd39a34e7f49f
branch: main
repository: half-blood-prince (local-only)
topic: "Session 21 — P2-T4 + P2-T5 merged; chain-audit #1 CLEAN; P2-T6 next"
tags: [session-checkpoint, phase2, p2-t4, p2-t5, chain-audit, pdf-anchors, epub-cross-node, goal-loop]
status: complete
last_updated: 2026-07-17
type: handoff
---

# Session 21 — hbp P2-T4 + P2-T5 merged (721 green); chain-audit #1 CLEAN; P2-T6 next

> Supersedes `2026-07-16_22-50-06_session20-...`. One repo: **half-blood-prince**
> (`main` @ `118728d`, **721 green**, local-only, **never push**). The `/goal` loop ran
> **two full tasks** this session (P2-T4, P2-T5) plus its **first autonomous chain-audit**
> (owner chose fully-unattended handling; verdict CLEAN). Chain-audit window is at **1/3**, so a
> bare `/goal` next runs **P2-T6** (probe HEAD first); no audit due.

## Task(s)

1. ✅ **hbp P2-T4 — PDF targets → ordered multi-quad anchors.** Merged `9d55b23` (feat `699ea9e`…
   no: feat `1f36dfb`). Gate 694 → 714. New `documents/pdf.py`; `find_text_rect` delegates geometry.
   Opus review CLEAN.
2. ✅ **Chain-audit #1 (P2-T2→P2-T4).** Fresh plan-independent `Agent(opus)` — **CLEAN**, 0
   blockers, 5 non-blocking findings (all recorded, folded into future tasks). Baseline advanced to
   `pre-overnight-2026-07-17-073137` @ `9d55b23`; window reset to 0.
3. ✅ **hbp P2-T5 — Resolve + wrap EPUB ranges across text nodes.** Merged `118728d` (feat
   `32c40d8`). Gate 714 → 721. New `documents/epub.py` (standalone cross-node locator) +
   `EpubProcessor.wrap_cross_node_segments`. Opus review CLEAN. `render_annotations` UNCHANGED
   (routing is P2-T9).
4. ⏳ **hbp P2-T6 — resolved-plan and render-report contracts.** NOT started. Next task
   (plan line 117; deps P2-T2/T4/T5). **PROBE HEAD FIRST.**
5. ⏳ **CARRIED — OPEN DECISION: versioned model id** (arch §4.4); blocks v0.1.0. Untouched.
6. ⏳ **CARRIED — owner-requested `/goal` prompting research** (Sonnet subagent; do NOT
   auto-apply). Untouched.

## ⚠️ On-disk-only state (read before resuming)

- **`.claude/skills/goal/SKILL.md`** — hardened, uncommitted by design (`.claude/` is never-commit).
  Integrity `sha256sum` → `c42a5f9d27ba51794285ad34fc235710635ffd301327f763b0c5318fd6252eaa`
  (UNCHANGED this session — the chain-audit gate this session used matches Session 20's edit). If
  gone/reverted, see Session 20's handoff to reapply.
- **`.superpowers/sdd/progress.md`** (Session 21 entries: P2-T4, chain-audit #1, P2-T5), the plan's
  P2-T4/P2-T5 DONE markers, and `.superpowers/sdd/p2-t4-*` / `p2-t5-*` (briefs, reports, testsums)
  are gitignored/never-commit scratch. **The `p2-t4-brief.md` and `p2-t5-brief.md` capture the full
  validated designs** (mechanism probes, scope boundaries) — read them if extending PDF/EPUB.

## Critical References

1. `docs/superpowers/plans/2026-07-11-phase2-3-implementation-plan.md` — **P2-T6 at line 117**
   (P2-T4/P2-T5 marked DONE). Remaining: P2-T6→T9 + Phase 3 (P3-T1→T10).
2. `docs/superpowers/specs/2026-07-11-full-project-architecture.md` — §5.5 (char ranges + line
   quads; ranking), §5.8 (EPUB DOM ranges), §6.1 (`ResolvedPlan`/`RenderReport` — P2-T6 core),
   §5.9 (degradation).
3. `src/halfblood/documents/pdf.py` — P2-T4 anchor resolver (`resolve_pdf_anchor:104`); consumed by
   P2-T6 layout/occupancy.
4. `src/halfblood/documents/epub.py` — P2-T5 cross-node locator (`locate_across_nodes:194`).

## Recent changes (committed on `main`)

- **P2-T4** (merge `9d55b23` / feat `1f36dfb`): NEW `src/halfblood/documents/pdf.py` (`PdfPageIndex`
  rawdict-walk aligned byte-for-byte to `get_text("text")`; `resolve_pdf_anchor` char-range → ordered
  per-line quads in displayed space via `page.rotation_matrix`, within `page.rect`;
  `char_span_for_rects:86`). `document_processor.find_text_rect` delegates geometry
  (`index = PdfPageIndex(page)` at `document_processor.py:372`), legacy `search_for` selection kept.
  `documents/__init__.py` exports. Tests: `tests/test_pdf_anchors.py` (NEW), `tests/test_pdf_targeting.py`.
- **P2-T5** (merge `118728d` / feat `32c40d8`): NEW `src/halfblood/documents/epub.py`
  (`iter_inline_runs:117`, `locate_across_nodes:194`, `selector_for`). `EpubProcessor.
  wrap_cross_node_segments` at `epub_processor.py:562` (reverse-order, markup-preserving).
  `documents/__init__.py` exports. Tests: `tests/test_epub_processor.py` (+7).

## Learnings

- **The `/goal` chain-audit works.** Its first real run (attended, owner chose unattended handling)
  independently VERIFIED the P2-T2→T3→T4 contract aligns end-to-end (`NormalizedText.raw ==
  PdfPageIndex.text == page.get_text("text")`), catching the exact compounding class it exists for.
  CLEAN. This is the plan-independent check per memory `brief-seeded-reviews-not-plan-independent`.
- **Probe-first + validate-your-own-tests paid off twice.** P2-T4: PyMuPDF `set_rotation` does NOT
  change `get_text`/`search_for`/rawdict coords (un-derotated); `page.rotation_matrix` maps them into
  `page.rect`. The rotation test is only non-vacuous with **bottom-of-page** text (un-derotated coords
  fall outside the rotated `page.rect`) — a top-of-page fixture passes even if rotation is ignored
  (caught pre-dispatch). P2-T5: reconstructing `get_text("text")` from rawdict is byte-exact; a
  single-node locator returns a **degraded fragment** (not None) for a cross-node quote, so
  "non-vacuous" means "does not cover the FULL quote", not "returns None".
- **Controller test defects induce scope-creep (proven again, P2-T5).** My initial wrap test asserted
  `normalize(block.get_text()) == before_text`, which counts the *added* note as book text and forced
  Codex to hoist the note out of the block. Fixed to exclude `hbp-note` text and not over-constrain
  placement (memory `controller-test-defects-induce-scope-creep`). A later review finding (a vacuous
  `if located is not None` guard) was likewise fixed to an unconditional assertion before merge.
- **Transient WSL `/mnt/c` "Unable to write index" recurred** on the P2-T5 merge (SKILL step 8). No
  real conflict — `git merge --abort` then re-merge succeeded; the feat commit stayed safe on the
  branch. Always `git show --stat HEAD` after a merge to confirm it's non-empty.

## Verification

| Claim | Command run this session | Result |
|---|---|---|
| hbp HEAD | `git rev-parse HEAD` | `118728da042a2a9d340a61ad419bd39a34e7f49f` |
| gate green on `main` (fresh, post-P2-T5-merge) | `.venv/bin/pytest tests/ -q` | `721 passed, 22 warnings` |
| ruff clean | `.venv/bin/ruff check src tests eval --no-cache` | `All checks passed!` |
| mypy clean | `.venv/bin/mypy src/halfblood` | `Success: no issues found in 26 source files` |
| P2-T4 merge non-empty | `git show --stat 9d55b23` | merge, 5 files (+516/-5) |
| P2-T5 merge non-empty | `git show --stat HEAD` | merge `118728d`, 4 files (+459/-1) |
| `resolve_pdf_anchor` present | `grep -n "def resolve_pdf_anchor" src/halfblood/documents/pdf.py` | `104:def resolve_pdf_anchor(` |
| `char_span_for_rects` present | `grep -n "def char_span_for_rects" src/halfblood/documents/pdf.py` | `86:    def char_span_for_rects(` |
| `find_text_rect` delegates | `grep -n "index = PdfPageIndex(page)" src/halfblood/document_processor.py` | `372:            index = PdfPageIndex(page)` |
| `locate_across_nodes` present | `grep -n "def locate_across_nodes" src/halfblood/documents/epub.py` | `194:def locate_across_nodes(` |
| `iter_inline_runs` present | `grep -n "def iter_inline_runs" src/halfblood/documents/epub.py` | `117:def iter_inline_runs(` |
| `wrap_cross_node_segments` present | `grep -n "def wrap_cross_node_segments" src/halfblood/epub_processor.py` | `562:    def wrap_cross_node_segments(` |
| task-scoped tree clean | `git status --porcelain -- src tests eval` | empty |
| full status = never-commit set only | `git status --porcelain` | ` M .claude/skills/goal/SKILL.md`, ` M CLAUDE.md`, `?? .claude/skills/halfblood-roadmap/`, `?? docs/superpowers/plans/...` |
| `/goal` SKILL integrity (unchanged) | `sha256sum .claude/skills/goal/SKILL.md` | `c42a5f9d27ba51794285ad34fc235710635ffd301327f763b0c5318fd6252eaa` |
| chain-audit window (post P2-T5) | `git log pre-overnight-2026-07-17-073137..main --oneline \| grep -c feat:` | `1` (1/3 → P2-T6 next, no audit due) |
| new baseline tag exists | `git tag -l pre-overnight-2026-07-17-073137` | present (@ `9d55b23`) |
| P2-T6 heading | `grep -n "### P2-T6" docs/superpowers/plans/...` | `117:### P2-T6 — Define resolved-plan and render-report contracts` |
| hbp has no remote (never push) | `git remote -v` | empty |

## Artifacts

- hbp (committed): `src/halfblood/documents/pdf.py`, `src/halfblood/documents/epub.py`,
  `src/halfblood/documents/__init__.py`, `src/halfblood/document_processor.py` (delegation),
  `src/halfblood/epub_processor.py` (wrapper), `tests/test_pdf_anchors.py`,
  `tests/test_pdf_targeting.py`, `tests/test_epub_processor.py`. Merges `9d55b23`, `118728d`.
- hbp (scratch, on-disk, never-commit): `.superpowers/sdd/p2-t4-brief.md`, `p2-t4-report.md`,
  `p2-t4.testsums`, `p2-t5-brief.md`, `p2-t5-report.md`, `p2-t5.testsums`, `progress.md`
  (Session 21), plan DONE markers.
- Rollback tags (hbp): `pre-overnight-2026-07-17-073137` @ `9d55b23` (current window baseline),
  `pre-overnight-2026-07-16` @ `27c70e2`, `pre-phase2-2026-07-16` @ `7ade9cd`.
- Merged hbp branches (safe to delete; SKILL says never delete): `phase2-t4`, `phase2-t5` (+ older).

## Action Items & Next Steps

1. **hbp P2-T6** (resolved-plan + render-report contracts; plan line 117; deps P2-T2/T4/T5). Runs
   under `/goal`. **PROBE HEAD FIRST** — check `models/documents.py` (`AnnotationPlan`/`ResolvedPlan`),
   `generation/report.py` (`RenderReport`), and what P1-T1 already shipped before writing the brief.
   P2-T6 is the first CONSUMER of P2-T4 quads + P2-T5 segments (occupancy layout / note boxes).
2. **Fold in at P2-T6** (from chain-audit #1 + P2-T5 review, deferred): the P2-T4 rotation×multi-line
   ordering test + `PdfAnchor` docstring "reading order = content-stream order, not visual"; the EPUB
   note-placement single/cross-node consistency; the dead `_segments_for_span` guard
   (`documents/epub.py:174`).
3. **Fold in at P2-T8** (from chain-audit #1): `TargetSelector.start_offset` unit docstring (it's a
   NORMALIZED-text position) + a whitespace-run occurrence-selection test; the
   `score_candidates → raw_span → resolve_pdf_anchor` integration test; `AMBIGUITY_MARGIN` dual-role
   comment.
4. **CARRIED — versioned model id** (arch §4.4); verify vs live Anthropic docs (`claude-api` skill);
   blocks v0.1.0.
5. **CARRIED — `/goal` prompting research** (Sonnet subagent; do NOT auto-apply).

## Other Notes

- **Chain-audit gate is now owner-trusted unattended** (owner decision this session): the loop runs
  the periodic plan-independent Opus chain-audit and acts on its verdict autonomously (CLEAN → advance
  baseline + continue; BLOCKER → bounded auto-fix or STOP-FLAG). Every `pre-overnight-*` tag is a
  rollback point; owner can stop anytime.
- **Codex dispatch for hbp** is always `~/dev-harness/scripts/codex-safe.sh --workspace <hbp> --brief
  … --out …` (confined, NO-DELETE, `gpt-5.6-sol`/high). NEVER `--dangerously-bypass-*`. Tripwire
  (`.superpowers/sdd/<pX-tY>.testsums`) proved Codex touched zero `tests/` both tasks.
- **WSL `/mnt/c`:** `.venv/bin/…`; `git reset --hard` on main is hook-blocked (use `--mixed`);
  `.claude/settings.local.json` bypass is intentional; `thoughts/` is gitignored (this handoff
  force-added with `git add -f`).
- **Attended-run deviation:** this session drove the whole loop on Opus (controller authored briefs +
  tests directly; Codex built src; Opus reviewed) because the tasks were subtle geometry/DOM work and
  attended. For an unattended overnight `/loop /goal`, prefer the Sonnet-driver division per the SKILL.
