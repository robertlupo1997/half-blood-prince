---
date: 2026-07-22T12:12:43-04:00
researcher: Claude (Fable 5)
git_commit: b770fb3ccbb75dd1f70aa1f49efb1bd79e729098
branch: main
repository: half-blood-prince (+ dev-harness)
topic: "Session 29 (cont. 7) — sdd-manifest landed; ADOPTION BUILD-OUT COMPLETE (all 5 mechanisms, all shadow)"
tags: [adoption, manifests, shadow-mode, scoreboard, owner-queue]
status: complete
last_updated: 2026-07-22
type: handoff
---

# Handoff: Session 29h — adoption build-out COMPLETE

> **hbp `main` @ `b770fb3` (unchanged this unit), 1351 green. dev-harness `d7b090d`:
> `sdd-manifest.py` + 11 hermetic tests.** With this, all five oh-my-pi adoption
> mechanisms are BUILT and verified — every one shadow/advisory; every
> activation/enforcement flip remains owner-gated.

## ADOPTION SCOREBOARD (all shadow)
| # | Mechanism | Where | Verified by |
|---|---|---|---|
| 1 | Run receipts + side-effect retry advice | dev-harness `d90baea` | 33 hermetic tests; 3 live receipts, 3/3 judged accurate vs git reality |
| 2 | sddctl ruling-epoch journal | dev-harness `a8bef24` | 10 tests; Session-28 replay live: stale mission → assert-ready refuses |
| 3 | sdd-driver definition + policy hooks | hbp `5d2158e` + `8ffcda6` | 52 table-tests in the product suite; 31 controller live checks |
| 4 | Conformance checker + divergence ledger | hbp `f7a2c75` | 8 tests; live ledger: 2 agent + 1 audit divergence |
| 5 | Brief/source manifests | dev-harness `d7b090d` | 11 tests; live vs real repo: drift codes 0/5/6/7 confirmed |

## Task(s)
1. ✅ sdd-manifest (adoption #5) — dev-harness `d7b090d`; receipt accurate, tripwire 7/7,
   all four dev-harness suites re-run green by controller, live-exercise clean.
2. ⏳ NEXT (recommended): **reader-lab EPUB fixtures** (the NL4 §2 deferral — product
   work: real-reader rendering fixtures for the EPUB note-layout track; needs a brief +
   driver + Opus review per hbp product protocol).
3. ⏳ OWNER QUEUE (unchanged, consolidated in 29g handoff): agent frontmatter fixes ×2,
   audit historical label, scripts/ in documented gate, activation flags (sdd-driver /
   sddctl wiring / receipts enforcement), OpenRouter key.
4. ⏳ Product validation — blocked on the key.

## Critical References
- Ledger "MANIFESTS — LANDED … ADOPTION BUILD-OUT COMPLETE" (scoreboard + live-exercise detail).
- `~/dev-harness/scripts/` — the four shadow tools (`codex-safe.sh` untouched throughout).
- `docs/superpowers/specs/2026-07-20-epub-note-layout-track-design.md` §NL4 (fixtures spec).

## Learnings
- The full adoption arc (5 mechanisms, 2 repos, 6 Codex dispatches, 4 Opus reviews)
  ran without a single tripwire violation or inaccurate receipt — the receipts wrapper
  itself provided the evidence trail for the later mechanisms' builds (tools bootstrapping
  each other's verification).

## Verification (controller-run this session)
| Claim | Command | Result |
|---|---|---|
| dev-harness @ `d7b090d`, clean | `git show --stat` + porcelain | 2 files +779; porcelain 0 |
| Tripwire (7 existing files) | `sha256sum -c` tripwire3 | 7/7 OK |
| All four dev-harness suites | run individually | 11 + 34 + 33 + 10 — all green |
| Live drift codes vs real hbp | generate/validate + tampered copies | 0 / 5 / 6 / 7 as specced; hbp tree untouched |
| hbp unchanged this unit | `git rev-parse HEAD` | `b770fb3…` |

## Action Items & Next Steps
1. Reader-lab EPUB fixtures — next loop iteration (product protocol: brief + driver +
   ONE Opus review + --no-ff merge).
2. Owner queue (29g handoff has the full list with context).

## Other Notes
- Rollbacks: dev-harness `git revert d7b090d` / `a8bef24` / `d90baea`; hbp chain
  unchanged (29g `f7a2c75` newest).
- Never push. `M CLAUDE.md` untouchable.
