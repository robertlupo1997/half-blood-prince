## Outcome

**Observed:** the supported placement path now rejects the five-versus-fifty prefix misanchor. It returns documented `resolved`, `ambiguous`, `unresolved`, or `unsupported_renderer` records before drawing.

- Require complete normalized quotes and verified hints; V1 migration no longer invents first-occurrence evidence.
- Preserve input bytes across artifact/checkpoint/report aliases and keep supplied resume files unchanged.
- Resolve EPUB against the original DOM. Read fixed-layout item overrides before EbookLib discards them.
- Keep composer omission codes in reports, including codes without summary flags.
- Add a checked-answer offline benchmark, mutation checks, and installed-wheel API coverage.

## Evidence

[Final auditable packet](https://github.com/robertlupo1997/half-blood-prince/blob/release/evidence-placement-contract/thoughts/shared/handoffs/general/2026-09-07_21-42-43_general_astra-evidence-placement-release.md) — conclusions, exact commands and raw outputs, independent checks vs worker reports, rejected alternatives, and unproven claims. `HANDOFF.md` points to it.

**Observed at source commit `79da678`:**

- 2,070 tests pass; Ruff clean; mypy clean across 48 files.
- Wheel build/install/API smoke passes outside the checkout.
- Original input-protection matrix: 8/8, bytes intact.
- Placement benchmark: 23 cases; 8 correct resolutions, 15 correct refusals, 0 wrong anchors; 10/10 PDF/EPUB pairs agree.
- Eight injected benchmark failures are detected.
- Real offline Alice runs: 78 PDF and 12 EPUB placements. These are stub pipeline checks, not model-quality evidence.

## Limits and blocked gate

**Blocked:** independent frontier quality evaluation. The repository credential was rejected with HTTP 401; it was not re-probed. No paid quality score or self-judging result is presented as quality.

**Unproven/unclaimed:** universal accuracy, OCR truth, collision-free connectors, or reader-level EPUB visual parity. Reflowable EPUB resolves text ranges, never coordinates. Fixed-layout EPUB coordinate rendering is explicitly unsupported. Legacy compatibility matching/rendering helpers remain outside the supported contract and can still use prefix recovery.

Anchorite, W3C selectors, and Hypothesis fuzzy anchoring are cited as prior art. “Fail-closed anchoring” is project vocabulary, not a standard.

This PR does not merge, publish a release, or change repository visibility. Those remain owner decisions.
