---
date: 2026-07-18T14:08:19-04:00
researcher: Claude (Opus 4.8) — controller session
git_commit: fe29dd6f3e084c6a500895b301695b35ab72cecb
branch: main
repository: half-blood-prince (local-only, never push)
topic: "P3-T5 DECISION brief — stroke-asset licensing go/no-go; owner leaning GO but needs the outline-vs-single-stroke question answered; CALL CODEX FIRST"
tags: [p3-t5, owner-decision, licensing, handwriting, fonts, codex-first]
status: complete
last_updated: 2026-07-18
type: handoff
---

# P3-T5 DECISION brief — CALL CODEX FIRST, then help the owner decide

> **Read `2026-07-18_02-32-32_session23-p3t4-merged-p3t5-owner-gate.md` (same dir) for full project
> state.** hbp `main` @ `fe29dd6`, **1065 green**, Phase 2 + P3-T1→T4 done, `/loop /goal` STOPPED at
> P3-T5 (owner licensing gate). This doc is ONLY about getting P3-T5 decided.

## ⚡ FIRST ACTION (owner's explicit instruction): call Codex for its recommendation, immediately

Before explaining anything or writing the decision, **dispatch Codex for a second opinion** on the
handwriting-source strategy. Use a READ-ONLY/opinion call (e.g. the `codex:rescue` skill, or
`codex exec` with a read-only sandbox — NOT a build; we want analysis, not code). Send it this:

> half-blood-prince adds AI "Half-Blood Prince"-style scrawled margin annotations to books (PDF/EPUB).
> Phase 2 (shipped) TYPESETS the margin notes using Google-Fonts handwriting **outline** fonts —
> `fonts/` already has Caveat Brush, Homemade Apple, Just Me Again Down Here, Mrs Saint Delafield.
> Phase 3 aims for *genuine procedural handwriting*: drawing each letter **stroke-by-stroke** from
> **centerline trajectories** + pressure/jitter, so every glyph varies (a static font can't do that).
> P3-T5 is a licensing gate: we need a legally-redistributable SOURCE of letter **centerlines**
> (outline fonts don't contain pen paths). Options: (a) **Hershey** single-stroke public-domain fonts —
> clean license, but mechanical/plotter look; (b) **commission/author an original** centerline alphabet
> — authentic, real work, we own it; (c) **skeletonize an existing handwriting outline font** (e.g.
> Caveat) — license question (OFL derivative rights, attribution/Reserved-Font-Name) + auto-
> skeletonization quality; (d) **NO-GO** — skip procedural handwriting, keep the already-working
> handwriting-FONT typesetting + the Phase-3 rough scribble marks (underlines/circles/doodles) that are
> already merged. Recommend, with reasoning: is procedural single-stroke handwriting worth it here vs.
> polishing the font typesetting, and if GO, which source — weighing effort, legal risk, and visual
> payoff for a scrawled-marginalia aesthetic.

Relay Codex's recommendation to the owner alongside the explanation below, then help them decide.

## The question the owner actually asked (answer this clearly)

> "Why Hershey and not the free Google handwriting fonts I already found? What does *single-stroke
> vector font* even mean?"

**Great question — and the project ALREADY uses those Google fonts.** `fonts/CaveatBrush-Regular.ttf`
(+ 3 more) are what Phase 2 renders the notes in (`src/halfblood/document_processor.py:19-26,175`).
So the confusion is fair. The gap is **outline vs. centerline**:

- **Outline font** (Caveat, and ~every font): stores each letter as the **boundary of its filled
  black shape** — a silhouette. Thickness is *baked in*. → Like a **coloring-book page**: the shapes
  are pre-drawn; software just fills them. Perfect for **typesetting** (what we already do).
- **Single-stroke / centerline font** (Hershey): stores each letter as the **line down the middle of
  each pen stroke**, with **no thickness**. → Like a **connect-the-dots / pen-plotter path**: it's the
  route a pen travels; *you* choose the pen width when you draw. Perfect for **procedurally drawing**.

**Why Phase 3 needs centerlines:** the procedural handwriter simulates a *pen* — following a path and
laying ink with variable pressure/jitter/imperfection so each 'e' is a little different. That needs the
**path** (centerline). An outline font gives the final silhouette, not the path — and you can't
reliably "un-bake" a pen stroke from a filled shape (that's *skeletonization*: lossy, AND it makes a
derivative work of the font → the licensing problem). Caveat is a coloring-book page; the handwriter
wants a pen-plotter path.

## The DEEPER product question (surface this to the owner — it may change the decision)

We **already** render notes in a nice handwriting *font* (Phase 2 + those 4 fonts). Phase-3 procedural
handwriting is an **additional, ambitious** feature: more organic/varied strokes a static font can't
do. **Is that extra fidelity worth the licensing + engineering cost, or is polished font-typesetting
"good enough" for the scrawled-marginalia look?** This is exactly what Codex's opinion (above) should
inform. The owner said "willing to say GO" — but should understand GO commits to P3-T6→T10 (a
substantial procedural-ink + PDF-vector-renderer build), while the already-shipped rough marks
(scribbles, circles, connectors, doodles from P3-T3) + font-typeset notes are a complete product on
their own.

## Options (record the chosen one in `docs/decisions/stroke-assets.md`)

| # | Option | License risk | Look | Effort |
|---|---|---|---|---|
| a | **Hershey** single-stroke (public domain) | none | mechanical/plotter | low (package existing) |
| b | **Original** authored/commissioned centerline alphabet | none (we own it) | as authentic as drawn | high (design work) |
| c | **Skeletonize Caveat** (or another handwriting font) | **must clear OFL derivative + RFN/attribution** — the actual P3-T5 risk | authentic but auto-skeletonization is imperfect | medium + legal review |
| d | **NO-GO** — keep font typesetting + rough marks | none | static handwriting font | zero (ship what's built) |

A **GO** (a/b/c) needs a full signed-off provenance record (author/source, version or content-hash,
license, derivation method, attribution/RFN obligations, redistribution conclusion, char coverage,
owner + date) — the plan forbids vague approval ("'font is OFL' is not approval"). GO unblocks
P3-T6→T10. **NO-GO** permanently blocks them for this milestone.

## Verification

| Claim | Command run this session | Result |
|---|---|---|
| hbp HEAD | `git rev-parse HEAD` | `fe29dd6f3e084c6a500895b301695b35ab72cecb` |
| gate green | `.venv/bin/pytest tests/ -q` | `1065 passed` |
| Phase 2 uses Google handwriting OUTLINE fonts | `grep -rn caveat/ttf src/halfblood` + `ls fonts/` | CaveatBrush + 3 more `.ttf`; used at `document_processor.py:19-26,175` |
| P3-T5 is the owner gate | `grep -n "### P3-T5" docs/…plan.md` | `246:### P3-T5 — Record the stroke-asset licensing go/no-go decision` |
| Codex wrapper present (next chat) | `ls ~/dev-harness/scripts/codex-safe.sh` | present (use read-only/rescue mode for OPINION, not a build) |
| full state handoff exists | `ls thoughts/shared/handoffs/2026-07-18_02-32-32_*` | present (read it for merges, F2 latent bug, mechanism notes) |

## Action Items & Next Steps (for the next chat)

1. **Call Codex** with the question above; relay its recommendation.
2. **Explain outline-vs-single-stroke** to the owner (coloring-book vs connect-the-dots), and surface
   the deeper "is procedural handwriting worth it vs. font typesetting" question.
3. **Get the owner's decision**, then **write `docs/decisions/stroke-assets.md`** with the full
   provenance record (GO) or the recorded NO-GO. On GO also plan `src/halfblood/ink/assets/manifest.json`
   + `tests/test_ink_asset_manifest.py` (that IS P3-T5's deliverable).
4. **Then resume** `/loop /goal` — GO drives P3-T6→T10; carry the **F2 latent bug** (P3-T7 must make
   `_douglas_peucker`/`simplify_commands` cubic-aware) and the **Codex-timeout mechanism fix** (wrap
   dispatch in `timeout 720 codex-safe.sh`) from the state handoff.

## Other Notes

- Owner stance (verbatim intent): "willing to say GO" but wants to understand why not the free Google
  fonts, and what single-stroke means — do NOT record a GO until they've understood + confirmed.
- Local-only, never push. `docs/decisions/**` IS committable (unlike `docs/superpowers/plans/**`).
