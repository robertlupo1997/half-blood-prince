---
date: 2026-07-20T20:16:25-04:00
researcher: Claude (Fable 5)
git_commit: 9c838e6
branch: main
repository: half-blood-prince
topic: "Session 28 — EPUB parity re-scoped → MP2a mark-intent parity + MP2b CLI mark-only surfacing (both merged; first-night cap reached)"
tags: [epub, mark-intent, marks-only, cli, re-scope, codex, controller-discipline, driver-subagent]
status: complete
last_updated: 2026-07-20
type: handoff
---

# Handoff: Session 28 — MP2a EPUB mark-intent parity + MP2b CLI mark-only count (both merged)

> **The handoff's "EPUB parity" task was probed, found mostly inapplicable, re-scoped with a
> Codex advisory, and the REAL gap shipped.** MP2a merged `c62c9cb` (feat `1b21012`); MP2b
> merged `9c838e6` (feat `568c51f`). `main` @ `9c838e6`, **1152 green**, ruff + mypy clean,
> `v0.1.0` intact. **First-night cap (2 feat merges since `pre-overnight-2026-07-20`) reached —
> loop stopped cleanly.**

## Task(s)
- ✅ **Re-scope decision (auditable)** — Session 27 named "EPUB parity (mark-survival +
  fail-closed)" next. Probing HEAD showed: every EPUB skip is target-location-based (no
  "note failed after target resolved" state), no geometry to fail closed on
  (`EPUB_NO_TARGET_GEOMETRY` always set), mark+note are one atomic DOM pass. Codex advisory
  (gpt-5.6-sol high, read-only; `.superpowers/sdd/epub-parity-consult{,-out}.md`) CONFIRMED
  and supplied the contract. Adopted ledger language: **EPUB fail-closed: N/A** (no inferred
  columns/margin geometry; inline fallback is the EPUB contract). **EPUB mark-survival: N/A**
  (no independent note-placement failure after successful target resolution; overlap and
  mutation re-resolution failures stay fully suppressed).
- ✅ **MP2a — EPUB mark-intent parity** — MERGED `c62c9cb` (feat `1b21012`). The real gap: V2
  `mark_intent` was silently dropped by the legacy conversion in `render_plan`, so the same
  plan rendered different marks on EPUB vs PDF (e.g. INSIGHT circled on PDF, underlined on
  EPUB) and NONE-intent still marked. Now: V2 annotation passes through;
  `wrap_cross_node_segments` split into `_wrap_mark_segments` + `_insert_note`; mark spans
  carry `hbp-target hbp-target-{type} hbp-mark-{intent}`; mark geometry moved from type CSS to
  `.hbp-mark-*`; `MarkIntent.NONE` = note-only (counts rendered); legacy callers derive intent
  via `_MARK_INTENTS`. Codex also updated the V1 `_wrap_and_annotate` path to emit intent
  classes — reviewer assessed **LOAD-BEARING** (post-CSS-move, V1 renders would otherwise
  silently lose all mark visuals).
- ✅ **MP2b — CLI surfaces mark-only count** — MERGED `9c838e6` (feat `568c51f`). Summary line
  (`cli.py:462-466`) appends ` ({N} mark-only)` only when `report.marks_only` non-empty;
  empty case byte-identical. Closes Session 27's "CLI labels mark-only notes skipped" gap.
- ⏹ **Loop stopped: first-night cap reached** (2 feat merges since `pre-overnight-2026-07-20`).
  Owner should eyeball the merged chain before continuing.

## Critical References
1. `.superpowers/sdd/epub-parity-consult.md` + `-out.md` — the re-scope advisory (why literal
   EPUB fail-closed/mark-survival are N/A; the mark-intent contract).
2. `.superpowers/sdd/mp2a-epub-mark-intent-brief.md`, `mp2b-cli-marks-only-brief.md` — pinned
   contracts used for the builds.
3. `docs/superpowers/specs/2026-07-19-annotation-placement-architecture-design.md` — design of
   record (§6 mark-survives stated universally; its EPUB application is the N/A record above).
4. `.superpowers/sdd/progress.md` — ledger; newest two sections cover MP2a/MP2b + cap stop.

## Recent changes (`file:line`, on `main` @ `9c838e6`)
- `src/halfblood/epub_processor.py` (+168/−56): legacy conversion in `render_plan` removed (V2
  annotation passed through); `wrap_cross_node_segments` decomposed into `_wrap_mark_segments`
  (skipped when effective intent is NONE) + `_insert_note` (always, same block-anchor insertion
  point); `_effective_mark_intent` derives legacy intent via `_MARK_INTENTS`
  (`models/documents.py:19-28`); `_ANNOTATION_CSS` gains `.hbp-mark-{underline,circle,strike,
  highlight,caret}` rules, type rules keep only non-geometry semantics (warning keeps bold);
  V1 `_wrap_and_annotate` also emits intent classes; dead `_note_style` fallback removed.
- `src/halfblood/cli.py:462-466`: mark-only qualifier on the render summary.
- Tests: `tests/test_epub_render_report.py` (+200: parameterized 5-intent class-set test,
  orthogonality WARNING+CIRCLE, NONE note-only, cross-node fragment classes, overlap ∉
  marks_only, CSS rules), `tests/test_epub_processor.py` (+44: legacy intent derivation ×2,
  strengthened span-parity), `tests/test_cli.py` (+94: 2 summary tests + fake render_plan
  processor + captured-Console helpers).

## Learnings
- **The handoff's named next task did not survive contact with HEAD.** "EPUB parity
  (mark-survival + fail-closed)" was structurally inapplicable — the probe-first rule
  (probe-HEAD-before-briefs memory) caught it before a brief was written. The Codex advisory
  found the correction (re-resolution misses are a second located-then-skipped case) AND the
  real deliverable (mark_intent drop). Consult-when-uncertain paid for itself.
- **CSS geometry moves have a hidden second consumer.** Moving mark geometry from
  `.hbp-target-{type}` to `.hbp-mark-{intent}` would have silently stripped ALL mark visuals
  from the V1 `render_annotations` path — Codex extended the V1 emitter unprompted and the
  reviewer confirmed it load-bearing. When a shared stylesheet changes, enumerate all class
  emitters, not just the path under change.
- **Both Opus reviews misattributed test authorship** ("Codex wrote the tests") because a
  single feat commit contains src+tests. Overruled both times on tripwire evidence (testsums
  snapshot mtime predates codex-out; `sha256sum -c` clean post-run). Reviews see the diff, not
  the process timeline — give future reviewers the tripwire timeline, or expect this finding.
- **Driver-subagent protocol worked this time** (Session 26 it stalled): Sonnet driver owned
  tests+dispatch+gate; Codex ran backgrounded inside the driver's context; both tasks 1
  dispatch, 0 redispatches. Quirk: the driver goes idle without sending its report — instruct
  "SEND your report to main before going idle" explicitly (fixed in MP2b's instructions).
- **Reviewer/driver reports still need tree verification.** Commit-content check
  (`git show --stat`), tripwire re-run, and controller-run gates were all re-executed here;
  they matched this time, but the MP2a driver's idle-without-report would have hidden a
  failure had the tree not been checked.

## Verification (all controller-run this session)
| Claim | Command | Result |
|---|---|---|
| HEAD on main | `git log --oneline -1` | `9c838e6` (MP2b merge) |
| Full suite green on main | `.venv/bin/pytest tests/ -q` | `1152 passed` |
| Lint / types clean | ruff / mypy | `All checks passed!` / `no issues in 41 files` |
| MP2a commit scope | `git show --stat 1b21012` | exactly epub_processor.py + 2 test files |
| MP2b commit scope | `git show --stat 568c51f` | exactly cli.py + test_cli.py |
| Codex never touched tests | `sha256sum -c .superpowers/sdd/mp2{a,b}.testsums` | all OK, both tasks |
| Cap state | `git log pre-overnight-2026-07-20..main --oneline \| grep -c feat:` | `2` (cap reached) |
| `M CLAUDE.md` untouched | `git status --porcelain` | ` M CLAUDE.md` unstaged, never committed |
| Warning delta explained | reviewer check F | +16 = XMLParsedAsHTMLWarning from new test bodies (cosmetic) |

## Boundaries / open follow-ups (recorded, not blocking)
- **MP2a:** legacy-derivation test covers 2/8 `_MARK_INTENTS` with `in` not set-equality;
  `_wrap_and_annotate` lacks a NONE guard (safe today — all 8 V1 mappings non-NONE);
  test-side `XMLParsedAsHTMLWarning` unfiltered (+16 warnings, cosmetic).
- **MP2b:** empty-case test pins by substring, not exact line equality.
- **MP1c follow-ups (from Session 27, still open):** contract test for "inline fails AND
  body_columns empty"; harden `test_narrow_outer_margin_shrinks_or_skips`
  (`test_occupancy_layout.py:302`).
- **EPUB intent CSS is untested on real readers** (circle `box-decoration-break`, caret
  `::after` are reader-dependent — advisory's RISKS section).
- **Product validation still owed** — no real `halfblood annotate` LLM run yet (OpenRouter,
  needs key).

## Action Items & Next Steps (owner green-light needed — cap reached)
1. Eyeball the merged chain (`git log pre-overnight-2026-07-20..main`) and loosen/reset the cap.
2. Next build candidates, in rough priority: design's EPUB track proper (a real design pass on
   reflowable note layout), expanded-canvas `--page-mode`, global solver, OCR milestone, the
   recorded follow-up tests above.
3. Product validation run via OpenRouter when a key is available.

## Other Notes
- **Never push. Local-only.** Rollback this run: `git revert -m 1 9c838e6`,
  `git revert -m 1 c62c9cb` (never `reset --hard` — uncommitted `CLAUDE.md`).
- Rollback tag this run: `pre-overnight-2026-07-20` @ `7c7bb80`.
- Codex pre-flight: smoke SMOKE-OK; CLI 0.144.5 unchanged since the 2026-07-19 audit; standard
  invocation (codex-safe.sh, sandbox + delete-guard) held without changes.
- Pre-existing dirty tree (leave alone): `M CLAUDE.md`, untracked
  `.claude/skills/halfblood-roadmap/`, `docs/superpowers/plans/2026-07-11-...`.
