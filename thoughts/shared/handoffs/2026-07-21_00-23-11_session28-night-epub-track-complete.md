---
date: 2026-07-21T00:23:11-04:00
researcher: Claude (Fable 5)
git_commit: 65c3752
branch: main
repository: half-blood-prince
topic: "Session 28 night run — cap retired by owner; MP2c + EPUB note-layout track NL1-NL4 all merged (7 feat merges total tonight)"
tags: [epub, note-layout, clusters, noteref, density, caret, cap-retired, codex, driver-protocol, monitor]
status: complete
last_updated: 2026-07-21
type: handoff
---

# Handoff: Session 28 night — EPUB note-layout track COMPLETE (NL1→NL4)

> **`main` @ `65c3752`, 1188 green (was 1138 at nightfall), ruff + mypy clean, `v0.1.0` intact.**
> **7 feat merges tonight:** MP2a (EPUB mark-intent parity), MP2b (CLI mark-only count),
> MP2c (hardening), NL1 (semantic note DOM), NL2 (block-first CSS + float), NL3 (density +
> degradation flag), NL4 (real-DOM caret). **The merge-count cap was RETIRED by the owner
> mid-run** (recorded in `.claude/skills/goal/SKILL.md` commit `14c5539` + memory
> `merge-cap-retired-by-owner`): never stop on merge count; stop only on quality degradation
> or STOP-FLAG. All 7 reviews returned GO.

## Task(s)
- ✅ Cap retirement (owner instruction, attended) — durable in skill + memory + ledger.
- ✅ MP2c hardening — merged `c5e7452` (see prior handoff for MP2a/MP2b).
- ✅ EPUB note-layout design ADOPTED — `docs/superpowers/specs/2026-07-20-epub-note-layout-track-design.md`
  (progressive semantic hybrid; from a Codex advisory that also found the same-block
  note-ordering REVERSAL defect).
- ✅ NL1 semantic note DOM (merged `157d4cb`): per-block `div.hbp-note-cluster` append-in-plan-order
  (ordering defect fixed); notes are `aside epub:type="footnote"` (EPUB 3, `book.version`) or
  `div` (EPUB 2/unknown); noterefs after last mark span (NONE → text-split; nested-anchor →
  after outermost `<a>`); bidirectional links; V1 routed through the same helper.
- ✅ NL2 block-first CSS (merged `fde4ffd`): base `display:block` presentation, `@supports` and
  `inline-block` removed, float is `@media (min-width:40em)` enhancement on
  `hbp-note-cluster-floatable`.
- ✅ NL3 density (merged `b037111`): ≥4 notes → cluster loses floatable, gains
  `hbp-note-cluster-dense`; additive `DegradationFlag.EPUB_DENSE_NOTES_BLOCK_FALLBACK` emitted
  once per book by `render_plan` (V1 returns None — DOM flip only; accepted deviation from an
  erroneous brief line).
- ✅ NL4 caret (merged `65c3752`): real `span.hbp-caret-glyph[aria-hidden]` on the final mark
  fragment, `::after` rule removed. Reader-lab fixture artifacts DEFERRED.
- ⏳ Next lane selection in progress (scout out on design §5 remnants: global solver /
  scene-owns-note-body / expanded-canvas / OCR).
- ⏳ Product validation still owed (real LLM run; OpenRouter key not available).

## Process (what worked — keep doing this)
- **Roles:** Fable orchestrates (briefs, verification, merges); Sonnet driver owns
  tests+dispatch+tripwire+gate+branch-commit; Codex (gpt-5.6-sol high, codex-safe.sh) builds
  src-only; ONE Opus review per merge. 7/7 GO.
- **Codex escalated controller-test defects TWICE** (NL1: substring class matches; NL2: my
  over-broad no-px pin) instead of bending production code — the "name the boundary in the
  brief" discipline is load-bearing. It also correctly deviated on NL3's impossible V1-flag
  clause. Treat Codex as a peer: its escalations were right all three times.
- **Persistent Monitor** (30s poll: phase-branch commits, codex start/stop, out-file updates)
  replaced slow heartbeat-only waking. Driver idle-without-report quirk persists — Monitor +
  proactive pings cover it.
- **Review prompts carry the process timeline** (tests snapshotted BEFORE Codex; tripwire
  verified) — stopped reviewers misreading test authorship (memory:
  gate-reviewers-misread-test-authorship).
- **NL3 commit had 4 force-added loop artifacts** — controller amended to task files only;
  memory `sdd-loop-artifacts-stay-out-of-git` added; NL4 commit was clean.

## Verification (all controller-run tonight)
| Claim | Result |
|---|---|
| main HEAD | `65c3752` (NL4 merge) |
| Full suite | `1188 passed`, 12 warnings (was 1138 / 39 warnings at nightfall) |
| ruff / mypy | clean / clean (41 files) |
| Tripwires | clean on every Codex task (MP2a, MP2b→n/a, NL1-NL4) |
| Rollback tag | `pre-overnight-2026-07-20` @ `7c7bb80` |
| `M CLAUDE.md` | untouched, unstaged all night |

## Rollback
`git revert -m 1` per merge, newest first: `65c3752` (NL4), `b037111` (NL3), `fde4ffd` (NL2),
`157d4cb` (NL1), `c5e7452` (MP2c), `9c838e6` (MP2b), `c62c9cb` (MP2a). Never `reset --hard`.

## Action Items & Next Steps
1. Pick next lane from the scout report (design §5: global solver / scene-owns-note-body /
   expanded-canvas / OCR) — probe-HEAD-first, decompose into pinned Codex tasks like NL1-NL4.
2. Deferred/recorded follow-ups: reader-lab EPUB fixtures (NL4); NL3 flag-count test weakness;
   NL1 `_next_note_number` degenerate fallback; V1/V2 NONE mark-span semantic difference.
3. Product validation via OpenRouter when a key is available.

## Other Notes
- Loop rails now: NO merge-count cap (owner-retired); stop on quality degradation
  (2 consecutive tasks needing 2+ fix redispatches / unresolvable NO-GO) or STOP-FLAG.
- Pre-existing dirty tree (leave alone): `M CLAUDE.md`, untracked `.claude/skills/halfblood-roadmap/`,
  `docs/superpowers/plans/2026-07-11-...`.
