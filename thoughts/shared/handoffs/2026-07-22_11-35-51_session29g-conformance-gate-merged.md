---
date: 2026-07-22T11:35:51-04:00
researcher: Claude (Fable 5)
git_commit: f7a2c75b43f1e339b34d9aff42df919c7c6527fa
branch: main
repository: half-blood-prince
topic: "Session 29 (cont. 6) — conformance checker + divergence ledger merged (adoption #4); owner queue consolidated"
tags: [adoption, conformance, divergence-ledger, shadow-mode, owner-queue]
status: complete
last_updated: 2026-07-22
type: handoff
---

# Handoff: Session 29g — conformance gate merged (1351 green)

> **`main` @ `f7a2c75`, 1351 green (1343+8), ruff (incl. scripts/) + mypy clean.**
> `scripts/check_harness_contracts.py` now audits the harness surface read-only and
> advisory: on this repo it reports exactly 2 nonconformant legacy agents + the seeded
> historical-audit divergence, and `--strict` still exits 0 (no ERRORs). Adoption
> build-out is 5-for-6: only manifests (#5) remains.

## Task(s)
1. ✅ Conformance gate — merge `f7a2c75` (feat `30667b2`). Codex caught a BRIEF DEFECT
   (brief said 4 legacy divergences; reality is 2 — locator/pattern-finder are valid)
   and reported instead of bending. Opus GO, 0 blockers, 4 advisories.
2. ⏳ NEXT (recommended): **brief/source manifests** (adoption #5, study §"Brief manifest
   rather than hashline") — manifest JSON generated per task (brief sha, testsums,
   base HEAD, allowed outputs, source-input hashes) + preflight validation in the
   dispatch path (shadow: generate + validate + report, no refusal yet).
3. ⏳ Reader-lab EPUB fixtures after; product validation blocked (OpenRouter key).

## OWNER QUEUE (consolidated — decisions only you can make)
1. Fix or retire the 2 nonconformant agents: `.claude/agents/codebase-analyzer.md`,
   `.claude/agents/web-search-researcher.md` (no YAML frontmatter → undiscoverable).
2. Label `docs/superpowers/specs/2026-07-19-codex-usage-audit.md` § historical.
3. Add `scripts/` to the documented gate command (lives in CLAUDE.md — untouchable by
   the loop; controller-run gates already include it).
4. Activation flags: sdd-driver agent (hardening complete), /goal↔sddctl wiring,
   receipts enforcement (refuse-retry on reconcile_required).
5. OpenRouter key for product validation.

## Critical References
- `scripts/check_harness_contracts.py` — run `python3 scripts/check_harness_contracts.py`
  any time for the current divergence ledger.
- Ledger "CONFORMANCE GATE — MERGED" (advisory detail + owner queue).
- `thoughts/shared/research/2026-07-21_omp-adoption-study.md` §secondary (manifest spec).

## Learnings
- Second confirmed instance of Codex refusing a defective brief pin and escalating
  (count expectation 4 vs reality 2) — the name-the-forbidden-shortcut brief style keeps
  paying off; also a reminder that MY pinned expectations need probe-first verification
  (the 4-count came from memory, not a read).

## Verification (controller-run this session, post-merge)
| Claim | Command | Result |
|---|---|---|
| main @ `f7a2c75` | `git rev-parse HEAD` | `f7a2c75b…` |
| Suite | `.venv/bin/pytest tests/ -q` | `1351 passed, 12 warnings` |
| ruff incl. scripts/ / mypy | `ruff check src tests eval scripts` / mypy | clean / clean |
| Checker on real repo | `python3 scripts/check_harness_contracts.py` (+ --strict) | rc 0 both; 2+1 divergences; ledger renders |
| Checker read-only | porcelain before/after run | unchanged |
| Tripwire | `sha256sum -c` tripwire5 (64 files) | 64/64 OK |
| Receipt vs reality | receipt JSON vs porcelain | exactly 2 created files |

## Action Items & Next Steps
1. Manifests (#5) — next loop iteration (shadow: generate/validate/report only).
2. Owner queue above.

## Other Notes
- Rollback: `git revert -m 1 f7a2c75`; chain: 29f `8ffcda6`, 29e `5d2158e`, 29c
  `5ae7725`, S3 `4363b03`, S2c `d521523`.
- Never push. `M CLAUDE.md` untouchable. Merged branches retained.
