---
date: 2026-07-17T18:46:12-04:00
researcher: Claude (Opus 4.8) — controller session
git_commit: 6168e03b0693042d72bd4ee2df21de99b47c7d5c
branch: main
repository: half-blood-prince (local-only)
topic: "Session 22 — P2-T6 merged (763 green); window 2/3; P2-T7 next"
tags: [session-checkpoint, phase2, p2-t6, resolved-plan, render-report, contracts, goal-loop]
status: complete
last_updated: 2026-07-17
type: handoff
---

# Session 22 — hbp P2-T6 merged (763 green); chain-audit window 2/3; P2-T7 next

> Supersedes `2026-07-17_08-27-45_session21-...`. One repo: **half-blood-prince**
> (`main` @ `6168e03`, **763 green**, local-only, **never push**). The `/goal` loop ran
> **one task** this session (P2-T6). **⚠️ Chain-audit window is now 2/3 — the audit is DUE
> after the NEXT feat merge (P2-T7).** A bare `/goal` next runs **P2-T7**, and its merge trips
> the window to 3/3, so the plan-independent Opus chain-audit MUST run before any P2-T8 task.

## Task(s)

1. ✅ **hbp P2-T6 — resolved-plan + render-report contracts.** Merged `6168e03` (feat `a12dabf`).
   Gate 721 → 763. New `src/halfblood/models/rendering.py`; `Placement` alias extracted in
   `models/annotations.py`. Contract-definition only — NO renderer cutover (P2-T8 PDF, P2-T9 EPUB).
   Opus review CLEAN (1 non-blocking, FIXED before merge). Folded in the deferred P2-T4
   rotation×multi-line ordering test + `PdfAnchor` "reading order = content-stream" docstring.
2. ⏳ **hbp P2-T7 — measured occupancy-based layout.** NOT started. Next task (plan line ~145;
   deps P2-T4, P2-T6). **PROBE HEAD FIRST.** First real CONSUMER of the P2-T6 contracts.
3. ⏳ **CHAIN-AUDIT DUE after the P2-T7 merge** (window will be 3/3). Do NOT start P2-T8 until it
   runs. Baseline for the audit window is `pre-overnight-2026-07-17-073137` @ `9d55b23`.
4. ⏳ **CARRIED — OPEN DECISION: versioned model id** (arch §4.4); blocks v0.1.0. Untouched.
5. ⏳ **CARRIED — owner-requested `/goal` prompting research** (Sonnet subagent; do NOT
   auto-apply). Untouched.

## ⚠️ On-disk-only state (read before resuming)

- **`.claude/skills/goal/SKILL.md`** — hardened, uncommitted by design (`.claude/` is never-commit).
  Integrity `sha256sum` → `c42a5f9d27ba51794285ad34fc235710635ffd301327f763b0c5318fd6252eaa`
  (UNCHANGED this session — survived the WSL merge-abort). If gone/reverted, see Session 20's
  handoff to reapply.
- **`.superpowers/sdd/progress.md`** (Session 22 entry: P2-T6), the plan's P2-T6 DONE marker, and
  `.superpowers/sdd/p2-t6-*` (brief, report, testsums) are gitignored/never-commit scratch. **The
  `p2-t6-brief.md` captures the full validated pinned interface** (all contract fields, the shared
  `Placement` mandate, the EPUB-segment deferral) — read it if extending the contracts.

## Critical References

1. `docs/superpowers/plans/2026-07-11-phase2-3-implementation-plan.md` — **P2-T7 at line ~145**
   (P2-T6 marked DONE at line 117). Remaining: P2-T7→T9 + Phase 3 (P3-T1→T10).
2. `docs/superpowers/specs/2026-07-11-full-project-architecture.md` — §6.1 (`ResolvedPlan` shape),
   §3.2 (`RenderReport` contents; "Secrets never appear"), §5.5 (char ranges + line quads; ranking,
   per-side occupancy — the P2-T7 core), §5.9 (degradation flags). NOTE: plan's "Covers §10.8/§10.12"
   for P2-T6 are **phantom refs** — those sections do not exist in the spec.
3. `src/halfblood/models/rendering.py` — the P2-T6 contracts P2-T7 consumes (`ResolvedAnchor:78`,
   `ResolvedAnnotation:149`, `ResolvedPlan:162`, `RenderReport:177`).
4. `src/halfblood/documents/pdf.py` — `PdfAnchor` quads (content-stream order) that P2-T7 layout
   places; `resolve_pdf_anchor:104`.

## Recent changes (committed on `main`)

- **P2-T6** (merge `6168e03` / feat `a12dabf`): NEW `src/halfblood/models/rendering.py` (254 lines):
  neutral serializable geometry (`SurfacePoint`/`SurfaceQuad` fitz-corner-named, no `fitz` import/
  `SurfaceRect` x0≤x1,y0≤y1); `ResolvedAnchor` (char_range≥0 & start≤end + ordered quads, empty
  valid for EPUB); `ResolvedAnnotation` (real `Annotation.id`/`Unit.source_locator` str refs;
  requested-vs-resolved `Placement`; render_seed uint64; note_box optional); `ResolvedPlan`
  (layout_version, 64-hex semantic_plan_hash — holds hash+ids only, never the plan object); finite
  `SkipReason`/`AnchorWarningCode`/`DegradationFlag`; `SkipRecord`/`AnchorWarning` (detail
  max_length=500); `OutputHash` (64-hex); `RenderReport` (exact rendered/skipped partition; stable
  degradation dedup; extra=forbid ⇒ secrets impossible); `load_resolved_plan:214`/
  `load_render_report:225` reject unknown MAJOR (reuse `UnsupportedSchemaVersionError` +
  `canonical_json` from documents.py). `models/annotations.py:11` extracts
  `Placement = Literal[...]`, reused in `Annotation.requested_placement` — behavior-identical.
  `pdf.py` `PdfAnchor` docstring clarified (content-stream ≠ visual order). Tests:
  `tests/test_resolved_plan.py` (NEW, 19), `tests/test_render_report.py` (NEW, 22),
  `tests/test_pdf_anchors.py` (+1 rotation×multi-line fold-in).

## Learnings

- **The acceptance-critical trap for contract tasks: parallel type substitutes pass gate + per-task
  review.** A second inline `Literal` in `rendering.py` would be runtime-INDISTINGUISHABLE from the
  shared `Placement` alias (CPython interns identical `Literal`s ⇒ `is` returns True), so a runtime
  identity test is VACUOUS. The advisor caught this pre-brief; the Opus review caught the vacuous
  test I wrote. The only test-level guard is **source inspection** (assert `rendering.py` imports
  `Placement` and never `Placement =`-redefines it) — now
  `test_rendering_uses_the_shared_placement_alias_not_a_parallel_literal`, verified discriminating
  against a synthetic parallel-`Literal` source. Memory `brief-seeded-reviews-not-plan-independent`.
- **`RenderReport` (render phase) ≠ `GenerationReport` (generation phase).** The existing
  `generation/report.py` `GenerationReport` records which PAGES the LLM annotated; P2-T6's
  `RenderReport` records which ANNOTATIONS produced ink. Distinct concerns, distinct models.
- **Fold-in rotation×multi-line test is a GREEN characterization test, not red-first.** Current
  `resolve_pdf_anchor` already returns quads in content-stream (`line_key` insertion) order
  regardless of rotation. Non-vacuity comes from asserting `tops == sorted(tops, reverse=True)`
  under 180° — content-stream order is visually bottom-to-top, so a resolver that sorted by display
  y would FAIL. Empirically verified the 180° flip (line0 at y=100 → display bottom) before dispatch.
- **WSL `/mnt/c` "Unable to write index" recurred on the FIRST merge (S16/S21/S22 — now reliable).**
  It left `MERGE_HEAD` mid-flight ("all conflicts fixed, still merging"). **Do NOT conclude a
  write-failed merge with `git commit`** — that risks the S16 empty-merge-drops-task failure.
  Recovery: `git merge --abort` (main stayed intact @ `b3252d8`, goal SKILL sha preserved, task
  tree clean) → re-merge succeeded non-empty. Always `git show --stat HEAD` after to confirm the 6
  files are listed.

## Verification

| Claim | Command run this session | Result |
|---|---|---|
| hbp HEAD | `git rev-parse HEAD` | `6168e03b0693042d72bd4ee2df21de99b47c7d5c` |
| merge parents correct | `git show --no-patch --format="%h parents: %p" HEAD` | `6168e03 parents: b3252d8 a12dabf` |
| gate green on `main` (fresh, post-merge) | `.venv/bin/pytest tests/ -q` | `763 passed, 22 warnings` |
| ruff clean | `.venv/bin/ruff check src tests eval --no-cache` | `All checks passed!` |
| mypy clean | `.venv/bin/mypy src/halfblood` | `Success: no issues found in 27 source files` |
| P2-T6 merge non-empty | `git show --stat 6168e03` | 6 files (+844/-5); rendering.py/2 test files created |
| `ResolvedPlan` present | `grep -n "^class ResolvedPlan" src/halfblood/models/rendering.py` | `162:class ResolvedPlan(_StrictModel):` |
| `RenderReport` present | `grep -n "^class RenderReport" src/halfblood/models/rendering.py` | `177:class RenderReport(_StrictModel):` |
| `load_resolved_plan`/`load_render_report` present | `grep -n "^def load_" src/halfblood/models/rendering.py` | `214:` / `225:` |
| `Placement` alias extracted | `grep -n "^Placement = Literal" src/halfblood/models/annotations.py` | `11:Placement = Literal["margin_right", ...]` |
| rendering imports the shared alias | `grep -n "from halfblood.models.annotations import Placement" src/halfblood/models/rendering.py` | `27:` |
| strengthened source-guard test present | `grep -n "def test_rendering_uses_the_shared_placement_alias_not_a_parallel_literal" tests/test_resolved_plan.py` | `101:` |
| rotation fold-in test present | `grep -n "def test_rotated_180_multiline_quads_follow_content_stream_not_visual_order" tests/test_pdf_anchors.py` | `159:` |
| **chain-audit window** | `git log pre-overnight-2026-07-17-073137..main --oneline \| grep -c feat:` | **`2` (2/3 → audit DUE after P2-T7 merge)** |
| baseline tag NOT advanced this session | `git tag -l 'pre-overnight-*'` | newest = `pre-overnight-2026-07-17-073137` (@ `9d55b23`, unchanged) |
| task-scoped tree clean | `git status --porcelain -- src tests eval` | empty |
| full status = never-commit set only | `git status --porcelain` | ` M .claude/skills/goal/SKILL.md`, ` M CLAUDE.md`, `?? .claude/skills/halfblood-roadmap/`, `?? docs/superpowers/plans/...` |
| `/goal` SKILL integrity (unchanged) | `sha256sum .claude/skills/goal/SKILL.md` | `c42a5f9d27ba51794285ad34fc235710635ffd301327f763b0c5318fd6252eaa` |
| P2-T7 heading | `grep -n "### P2-T7" docs/superpowers/plans/...` | `145:### P2-T7 — Implement measured occupancy-based layout` |
| hbp has no remote (never push) | `git remote -v` | empty |

## Artifacts

- hbp (committed): `src/halfblood/models/rendering.py` (NEW), `src/halfblood/models/annotations.py`
  (Placement), `src/halfblood/documents/pdf.py` (docstring), `tests/test_resolved_plan.py` (NEW),
  `tests/test_render_report.py` (NEW), `tests/test_pdf_anchors.py` (+rotation). Merge `6168e03`,
  feat `a12dabf`. Plan P2-T6 STATUS marker + progress.md S22.
- hbp (scratch, on-disk, never-commit): `.superpowers/sdd/p2-t6-brief.md`, `p2-t6-report.md`,
  `p2-t6.testsums`, `progress.md` (S22), plan DONE marker.
- Rollback tags (hbp): `pre-overnight-2026-07-17-073137` @ `9d55b23` (**current audit-window
  baseline — do NOT advance until the audit runs**), plus older `pre-overnight-*`.
- Merged hbp branches (safe to delete; SKILL says never delete): `phase2-t6` (+ older).

## Action Items & Next Steps

1. **hbp P2-T7** (measured occupancy-based layout; plan line ~145; deps P2-T4, P2-T6). Runs under
   `/goal`. **PROBE HEAD FIRST** — no `src/halfblood/layout/` exists yet; check what P2-T6's
   `rendering.py` provides (note_box `SurfaceRect`, `AnchorWarning`/`SkipReason` for reasons) and
   how `PdfAnchor` quads feed occupancy. Test-first uses a **fake deterministic measurer**; cover
   every edge/corner, both margins, occupancy overlap, side-switch/scale, both-margins-degenerate →
   skip. First real CONSUMER of the P2-T6 contracts.
2. **CHAIN-AUDIT after the P2-T7 merge (window → 3/3).** Spawn a fresh plan-independent
   `Agent(general-purpose, opus)` reading plan+spec (NOT briefs) + `git diff
   pre-overnight-2026-07-17-073137..HEAD -- src tests`. CLEAN → advance baseline tag + continue;
   BLOCKER → bounded auto-fix or STOP-FLAG (per `/goal` SKILL).
3. **Deferred fold-ins** (record, apply at the named task): **P2-T8** — `TargetSelector.start_offset`
   unit docstring, whitespace-run occurrence-selection test, `score_candidates → raw_span →
   resolve_pdf_anchor` integration test, `AMBIGUITY_MARGIN` dual-role comment. **P2-T9** — EPUB
   note-placement single/cross-node consistency, dead `_segments_for_span` guard (`epub.py:174`),
   **serializable EPUB range representation** (P2-T6 deferred this as a documented minor-version
   extension — `ResolvedAnchor.quads` is empty for EPUB now).
4. **CARRIED — versioned model id** (arch §4.4); verify vs live Anthropic docs (`claude-api` skill);
   blocks v0.1.0.
5. **CARRIED — `/goal` prompting research** (Sonnet subagent; do NOT auto-apply).

## Other Notes

- **Chain-audit gate is owner-trusted unattended** (owner decision, S21): the loop runs the periodic
  plan-independent Opus chain-audit and acts on its verdict autonomously. Every `pre-overnight-*` tag
  is a rollback point; owner can stop anytime.
- **This session did NOT advance the baseline tag** — no audit ran (window was 1→2, below
  AUDIT_EVERY=3). Advancing it would silently shrink the audit window. Leave it at `9d55b23`.
- **Codex dispatch for hbp** is always `~/dev-harness/scripts/codex-safe.sh --workspace <hbp> --brief
  … --out …` (confined, NO-DELETE, `gpt-5.6-sol`/high). NEVER `--dangerously-bypass-*`. Tripwire
  (`.superpowers/sdd/p2-t6.testsums`) proved Codex touched zero `tests/`.
- **WSL `/mnt/c`:** `.venv/bin/…`; `git reset --hard` on main is hook-blocked (use `--mixed`);
  `.claude/settings.local.json` bypass is intentional; `thoughts/` is gitignored (this handoff
  force-added with `git add -f`). The "Unable to write index" merge hazard is now reliable across
  S16/S21/S22 — abort + re-merge, never conclude a write-failed merge.
- **Attended-run deviation:** this session drove the P2-T6 loop on Opus (controller authored brief +
  tests directly; Codex built src; Opus reviewed) because it was an attended resume of subtle
  contract work. For an unattended overnight `/loop /goal`, prefer the Sonnet-driver division per the
  SKILL (and per advisor, do NOT drive the large P2-T7 on a long Opus context).
