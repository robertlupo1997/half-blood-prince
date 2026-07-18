---
title: "Stroke-asset licensing go/no-go (P3-T5)"
type: decision-record
task: P3-T5
status: PENDING            # PENDING | GO | NO-GO  — do NOT change until the owner decides
date_opened: 2026-07-18
git_commit_at_open: fe29dd6
decided_option:           # a | b | c | d          (fill on decision)
decided_by:               # owner name             (fill on decision)
decided_on:               # YYYY-MM-DD             (fill on decision)
covers: [architecture §5.1, §5.3, §8.3, §10 risk 1, §12 caveat 2]
---

# P3-T5 — Stroke-asset licensing go/no-go decision

## Status: ⬜ PENDING — no decision recorded yet

> **This file is a scaffold.** It is a *form to fill in*, not a decision. The gate stays
> `PENDING` until the owner records a choice. A **GO is only valid** once every field in
> [Provenance record](#provenance-record--required-on-any-go-abc) is filled and signed off.
> Per the plan's acceptance criteria, **none of these count as approval**: absence, ambiguity,
> "the font is OFL," or an inference drawn from open-source *code*. A **NO-GO** is a fully
> acceptable outcome, but it does **not** authorize any later letterform/PDF-handwriting task.

---

## The question in one line

We already **typeset** margin notes in Google handwriting **outline** fonts (works today).
Phase 3 wants **procedural handwriting** — drawing each letter stroke-by-stroke from
**centerline** pen-paths, so every glyph varies. Outline fonts don't contain pen-paths.
**This gate decides where the centerlines come from — and whether we go there at all.**

### Outline vs. centerline (the crux)

- **Outline font** — Caveat & ~every font. Stores each letter as the **boundary of its filled
  shape** (thickness baked in). Like a **coloring-book page**: shapes pre-drawn, software fills
  them. Perfect for **typesetting** — this is what ships today
  (`src/halfblood/document_processor.py:19-26,175`, fonts in `fonts/`).
- **Single-stroke / centerline font** — e.g. Hershey. Stores each letter as the **line down the
  middle of each pen stroke**, no thickness. Like a **connect-the-dots / pen-plotter path**: the
  route a pen travels; *you* pick the nib width when you draw. Required to **procedurally draw**
  letters with pressure/jitter so no two are identical. You **cannot reliably un-bake** a pen path
  out of a filled outline — that's *skeletonization*: lossy, **and** it makes a derivative work of
  the font (the licensing question in option (c)).

---

## Context

- **Already shipped (Phase 2 + P3-T1→T4):** handwriting-*font* typeset notes, plus seeded rough
  scribble marks — underlines, circles, strike-throughs, connectors, doodles. This is a complete,
  working product on its own.
- **What GO commits to:** a substantial procedural-ink build (P3-T6→T10 — packaged trajectory
  alphabet, the stroke handwriter, cache, PDF vector renderer, goldens).
- **Why a gate exists:** a font license does **not** automatically permit derived centerlines.
  Shipping unverified stroke assets would make "genuine handwriting" legally unshippable. The
  architecture (§8.3) is explicit: *"Do not extract centerlines from a font unless its license
  permits that derivative and attribution/Reserved Font Name obligations are understood. Prefer
  project-authored stroke assets under the repository license."*

---

## Options considered

| # | Option | License risk | Look | Effort |
|---|--------|--------------|------|--------|
| **a** | **Hershey** single-stroke fonts (public domain) | none | mechanical / plotter | low (package existing) |
| **b** | **Original** authored / commissioned centerline alphabet | none — we own it | as authentic as drawn | high (design work) |
| **c** | **Skeletonize** an existing handwriting outline font (e.g. Caveat) | **must clear OFL derivative rights + Reserved-Font-Name / attribution** — this is the actual P3-T5 risk | authentic, but auto-skeletonization is imperfect | medium + legal review |
| **d** | **NO-GO** — keep font typesetting + rough marks | none | static handwriting font | zero (ship what's built) |

### Codex recommendation (fill in before deciding)

Per the P3-T5 brief, get Codex's read-only opinion on the handwriting-source strategy *first*,
then paste its recommendation + reasoning here so the decision is on record next to it.

> _Codex recommendation: ___________________________________________________________________

---

## Decision

**DECISION: ⬜ PENDING** — choose exactly one and set `status` + `decided_option` in the frontmatter.

- [ ] **(a) Hershey** — GO
- [ ] **(b) Original authored alphabet** — GO
- [ ] **(c) Skeletonize a handwriting font** — GO (requires the license clearance in the provenance record)
- [ ] **(d) NO-GO** — keep font typesetting + rough marks; permanently blocks P3-T6→T10 this milestone

**Rationale:** _______________________________________________________________________________

---

## Provenance record — REQUIRED on any GO (a/b/c)

> The controller must verify **every** field below is filled before a single asset is committed.
> Leave this entire section as-is if the decision is NO-GO.

| Field | Value |
|-------|-------|
| **Authorship / source** | |
| **Exact version or content hash** | |
| **License** | |
| **Modification / derivation method** | |
| **Attribution & Reserved Font Name obligations** (if relevant) | |
| **Redistribution conclusion** | |
| **Approved character coverage** (lowercase / uppercase / digits / Latin-1 punctuation) | |
| **Approving owner** | |
| **Approval date** | |

---

## Consequences

- **GO (a/b/c)** → unblocks **P3-T6 through P3-T10**. Then, and only then, create:
  - `src/halfblood/ink/assets/manifest.json` — every packaged stroke/doodle/font/algorithm asset
    with a checksum, compatible declared license, source, modification status, package-data inclusion.
  - `tests/test_ink_asset_manifest.py` — asserts every asset has a `THIRD_PARTY_NOTICES.md` row +
    checksum + compatible license; **orphaned files and unknown licenses must fail**.
  - Rows added to `THIRD_PARTY_NOTICES.md` for the approved asset(s).
  - Packaging metadata updated **only after** approved assets exist.
- **NO-GO (d)** → **P3-T6 through P3-T10 stay blocked for this milestone.** Do **not** write a fake
  manifest test or a placeholder alphabet. Ship the already-built handwriting-font typesetting +
  rough marks. Procedural handwriting can be reopened as a future milestone.

---

## References

- Plan: `docs/superpowers/plans/2026-07-11-phase2-3-implementation-plan.md` — **§ P3-T5** (lines 246-258)
- Architecture: `docs/superpowers/specs/2026-07-11-full-project-architecture.md` — **§8.3** (font/stroke/model licensing), §10 risk 1, §12 caveat 2
- Decision brief (owner-facing explanation + Codex-first instruction):
  `thoughts/shared/handoffs/2026-07-18_14-08-19_session23-P3T5-DECISION-brief-call-codex-first.md`
- Fonts in use today: `fonts/` — Caveat Brush, Homemade Apple, Just Me Again Down Here, Mrs Saint Delafield
