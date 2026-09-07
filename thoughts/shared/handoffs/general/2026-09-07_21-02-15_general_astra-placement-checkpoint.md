---
date: 2026-09-07
researcher: Astra (root); explicit free MiniMax workers
branch: release/evidence-placement-contract
repository: half-blood-prince
topic: "Preserved placement refactor and free-worker results"
status: in-progress
---

# Preservation checkpoint — not a release verdict

## Observed

- Original baseline at `0739f28` was re-established: 1883 passing tests, Ruff/mypy clean, wheel smoke passed, three known harness items.
- Interrupted work was preserved by the owner at `04a4489`.
- Resumed workers all used `openrouter/minimax/minimax-m3:free` explicitly. No Astra child was restarted or messaged.
- Code now includes strict whole-quote placement, JSON-safe four-outcome records, input/sidecar/checkpoint alias protection, original-DOM EPUB range isolation, and raw-OPF fixed-layout detection.
- Root ran the original byte-preservation matrix: `8 passed, 26 deselected`.
- Root observed installed-wheel placement smoke passing and real offline Alice runs (78 PDF and 12 EPUB resolved quotes). These are not LLM-quality results.

## Worker outputs preserved

- `thoughts/shared/handoffs/lanes/2026-09-07_21-02-15_placement-free-workers/safety.md`
- `thoughts/shared/handoffs/lanes/2026-09-07_21-02-15_placement-free-workers/benchmark.md`
- `thoughts/shared/handoffs/lanes/2026-09-07_21-02-15_placement-free-workers/placement.md`
- `thoughts/shared/handoffs/lanes/2026-09-07_21-02-15_placement-free-workers/docs.md`

The reports are retained as evidence of work, not adopted wholesale. Root review caught stale documentation, insufficient benchmark crux coverage, and unsupported claims; final corrections are in progress.

## Pending

- Finish the README claim ledger and final root evidence packet.
- Re-run the complete suite, Ruff, mypy, benchmark, original safety matrix, harness checker, and wheel smoke against the settled tree. Concurrent worker runs are not final counts.
- Review the complete diff, commit release-ready work, push this branch and open the PR. Do not merge or change visibility.
- Frontier quality evaluation remains Blocked: repository credential rejected with HTTP 401. Do not re-probe; owner owns credential repair.

## Highest-value next action

Run final checks on the preserved tree after correcting the documentation ledger, then put the exact results in the release evidence packet and PR.
