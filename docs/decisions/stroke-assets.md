---
title: "Stroke-asset licensing go/no-go (P3-T5)"
type: decision-record
task: P3-T5
status: NO-GO             # PENDING | GO | NO-GO
date_opened: 2026-07-18
git_commit_at_open: fe29dd6
decided_option: d         # a | b | c | d
decided_by: Trey Lupo (owner)
decided_on: 2026-07-19
covers: [architecture §5.1, §5.3, §8.3, §10 risk 1, §12 caveat 2]
---

# P3-T5 — Stroke-asset licensing go/no-go decision

## Status: 🛑 NO-GO — recorded 2026-07-19 (option d)

> **Decision recorded.** Procedural stroke-handwriting is **deferred for this milestone.**
> Per the plan, a NO-GO writes **no** manifest, **no** placeholder alphabet, and **no** fake
> manifest test, and it **permanently blocks P3-T6 through P3-T10** for this milestone. It does
> **not** authorize any later letterform/PDF-handwriting task. A future milestone may reopen this
> decision (see [Revisit criteria](#if-reopened-later)).

---

## The question in one line

We already **typeset** margin notes in Google handwriting **outline** fonts (works today).
Phase 3 wanted **procedural handwriting** — drawing each letter stroke-by-stroke from
**centerline** pen-paths, so every glyph varies. Outline fonts don't contain pen-paths.
**This gate decided where the centerlines would come from — and whether to go there at all.**

### Outline vs. centerline (the crux)

- **Outline font** — Caveat & ~every font. Stores each letter as the **boundary of its filled
  shape** (thickness baked in). Like a **coloring-book page**: shapes pre-drawn, software fills
  them. Perfect for **typesetting** — this is what ships today
  (`src/halfblood/document_processor.py`, fonts in `fonts/`).
- **Single-stroke / centerline font** (e.g. Hershey). Stores each letter as the **line down the
  middle of each pen stroke**, no thickness. Like a **connect-the-dots / pen-plotter path**: the
  route a pen travels; *you* pick the nib width when you draw. Required to **procedurally draw**
  letters with pressure/jitter so no two are identical. You **cannot reliably un-bake** a pen path
  out of a filled outline — that's *skeletonization*: lossy, **and** it makes a derivative work of
  the font (the licensing question in option (c)).

---

## Options considered

| # | Option | License risk | Look | Effort |
|---|--------|--------------|------|--------|
| a | **Hershey** single-stroke fonts (public domain) | none | mechanical / plotter | *not* actually low — still needs alternates/ligatures/joining |
| b | **Original** authored / commissioned centerline alphabet | none — we own it | as authentic as drawn | high (human artist / pen-capture) |
| c | **Skeletonize** an existing handwriting outline font (e.g. Caveat) | must clear OFL derivative + Reserved-Font-Name / attribution | authentic, but auto-skeletonization imperfect | medium + legal review |
| **d** | **NO-GO** — defer procedural letters ✅ **CHOSEN** | none | (keep font typesetting) | zero for letters; redirect to un-gated integration |

### Codex recommendation (read-only opinion, `gpt-5.6-sol`, 2026-07-19)

**Codex recommended (d) NO-GO for this milestone.** Verbatim thrust:

- Procedural handwriting "is not worth five substantial downstream tasks unless the letter source
  is genuinely better than the fonts already in use — and Hershey is not." Hershey Script is
  cursive but remains a 1960s plotter design; pressure/jitter can't give it authentic marginalia
  variety.
- "The content, placement, ink color, rotation, crossings, circles, arrows, and doodles will carry
  much more of the 'Prince's notes' illusion" than the letterforms.
- "Do not choose Hershey merely because it makes the licensing gate easy" — under our acceptance
  criteria it still lacks the required alternates, contextual forms, ligatures, and joining, which
  pushes option (a) toward option (b)'s design cost while keeping the weaker look.
- If reopened later, choose **(b)**: commission an artist and capture real tablet pen trajectories,
  and only after a **blind bake-off at real margin size** proves customers notice.

Full report preserved verbatim: `docs/decisions/stroke-assets-codex-opinion-2026-07-19.md`. Two
findings from it were independently verified — see [Findings](#findings-verified-this-session).

---

## Decision

**DECISION: 🛑 NO-GO (option d)** — recorded by **Trey Lupo (owner)**, **2026-07-19**.

- [ ] **(a) Hershey** — GO
- [ ] **(b) Original authored alphabet** — GO
- [ ] **(c) Skeletonize a handwriting font** — GO
- [x] **(d) NO-GO** — procedural handwriting deferred this milestone; permanently blocks P3-T6→T10

**Rationale.** Codex's read-only analysis (above), which the owner accepted, plus two findings
verified this session (below): the visual payoff of the "Prince's notes" aesthetic comes far more
from *marks* (hand-drawn circles, underlines, connectors, doodles), placement, and ink than from
procedurally-drawn letterforms. The one GO Codex would endorse — (b), an original alphabet — needs
human art we don't have; the "easy" GO — (a) Hershey — buys the expensive T6→T10 engine around
weaker-looking letters. So we **defer procedural letters** and **redirect effort to the higher-
leverage, licence-free work** that isn't wired up yet (below).

---

## Findings (verified this session)

Both surfaced by Codex, both **confirmed true** by direct inspection:

1. **The rough scribbles aren't in the PDF yet.** The `src/halfblood/ink/` rough-mark library
   (InkScene, `rough.py`, styles — P3-T1→T4, tested) is **imported by nothing outside `ink/`**;
   `document_processor.py` still renders typeset text + *native* PDF marks + the old bowed
   connector. In the current plan the scribbles only reach PDF via **P3-T9**, which was gated
   behind this decision. Verified: `grep` shows no `ink`/`rough` import in `document_processor.py`
   and no importer of `ink/` outside the package.
2. **The handwriting fonts aren't packaged.** `git ls-files fonts/` → only `fonts/README.md`; all
   four `.ttf` files are **gitignored** (`git check-ignore fonts/CaveatBrush-Regular.ttf` →
   ignored). A built wheel/release omits them → installs fall back to **Helvetica**, not the
   demonstrated handwriting look. (Straight release bug, independent of this decision.)

---

## Consequences & redirect (owner-approved)

- **NO-GO** → **P3-T6 through P3-T10 stay blocked for this milestone.** No manifest, no placeholder
  alphabet, no fake manifest test. Procedural handwriting can be reopened as a future milestone.
- **Redirect (owner-approved 2026-07-19):** advance the SDD loop on the **licence-free, un-gated**
  work instead — Codex implements, standard lean-loop gate/review/merge:
  1. **Wire the existing rough scribbles into the PDF renderer** — a de-scoped, asset-free slice of
     P3-T9's scene→PDF integration (marks/connectors/doodles only; **no letterform engine, no
     licensing**). This is where most of the "Prince's notes" visual payoff lives.
  2. **Fix font packaging** — ship the handwriting `.ttf`s (or a properly-licensed subset) in the
     wheel so installs stop falling back to Helvetica; record each font's source/version/license in
     `THIRD_PARTY_NOTICES.md`.
  - These two items are **not yet defined as plan tasks**; they will be added to the phase plan
    before the loop runs them (planning delegated to Codex, controller/Opus review).

### If reopened later

Per Codex, a future GO should choose **(b)** (original authored / tablet-captured alphabet), and
only **after a blind bake-off** at real PDF margin size (current fonts vs. Hershey Script vs. a few
human-captured words) demonstrates the difference is noticeable and valued. Carry the latent
`_douglas_peucker` cubic-awareness bug (`src/halfblood/ink/geometry.py`) into any future P3-T7.

---

## References

- Plan: `docs/superpowers/plans/2026-07-11-phase2-3-implementation-plan.md` — **§ P3-T5** (line 246),
  P3-T9 scene/PDF integration (line 302), critical-path/no-go note (line 332).
- Architecture: `docs/superpowers/specs/2026-07-11-full-project-architecture.md` — **§8.3**, §10 risk 1, §12 caveat 2.
- Decision brief (owner-facing explanation + Codex-first instruction):
  `thoughts/shared/handoffs/2026-07-18_14-08-19_session23-P3T5-DECISION-brief-call-codex-first.md`
- Fonts present but gitignored: `fonts/` — Caveat Brush, Homemade Apple, Just Me Again Down Here, Mrs Saint Delafield
