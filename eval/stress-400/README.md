# Stress run — 400 pages, real crash/resume (2026-08-23)

One committed execution of `scripts/stress_400.py --pages 400` against a freshly
typeset 562-page public-domain book (Project Gutenberg #2701). Provider: built-in
deterministic stub.

## What is proven here

- A book-length run of a real extracted document survives a **real SIGKILL**
  mid-run: the streaming checkpoint `<output>.plan.json` held 7 finished pages at
  kill time; `--resume-from` finished the artifact with exactly those 7 pages
  reported `resumed` (zero provider calls repeated) and all 400 selected pages
  accounted for.
- A deep mid-book loss (full plan truncated to its first 150 pages) recovers with
  exactly those 150 pages resumed.
- Injected failures on pages 37/101/233 still ship an artifact, and the failure
  sidecar `<output>.report.json` lists them exactly, with per-page records.

## What is NOT proven here

Model annotation quality. The provider is deterministic stub code, not an LLM.
Cost/latency under a real rate-limited API is also out of scope. Those claims
remain open (Phase 2 item 1).

## Files

- `summary.json` — machine-written record: commands, assertions held, sha256 of
  every large binary (not committed, regenerable via `scripts/stress_400.py`)
- `console.log` — the run's console output, ending `STRESS RESULT: PASS`
- `stress-crash-resume.report.json` — sidecar after SIGKILL + resume
- `stress-truncated-resume.report.json` — sidecar after 150-page truncation resume
- `stress-fail.report.json` — sidecar with injected visible failures

The sidecars are large because they carry per-page status for 400 pages each;
that per-page data is the point.
