# Half-Blood Prince — v0.1.0 Portfolio Release Design

**Date:** 2026-07-10
**Status:** Approved (pending final user review)
**Owner:** Trey

## Context

Half-Blood Prince is a working prototype: a Python CLI that annotates any
PDF/EPUB with AI-generated margin notes in the voice of a persona (default:
young Snape). It was built and once-reviewed by a prior AI session whose work
is **explicitly untrusted** — including its bug list, its 44 passing (fully
mocked) tests, and its documentation. The `.git` directory was found corrupt
(interrupted `git init`) and has been repaired; a baseline "as received"
commit captures the starting state.

## Goal

Ship the repo public at v0.1.0 as a launch-first portfolio project:

1. Demos itself in under 10 seconds of README scrolling.
2. Survives a skeptical senior engineer reading any file.
3. Launchable on Show HN / r/Python with novelty as the hook and engineering
   rigor discoverable underneath ("novelty leads, rigor backs it").

## Decisions (from brainstorming Q&A)

| Question | Decision |
|---|---|
| Audience | Launch-first; stars become the portfolio credential |
| Effort budget | 2–4 focused sessions |
| Try-it path | Bundled sample gallery + GitHub Pages web preview. No PyPI, no hosted upload demo (deferred post-launch) |
| Launch narrative | Novelty headline; rigor as supporting material, not the pitch |
| Prior-work strategy | Approach A: full adversarial audit first, then one severity-ranked fix pass |
| License | MIT (default; user may override before Phase 4 completes) |

## Non-Goals (v0.1.0)

- PyPI packaging / pipx distribution
- Hosted upload-your-own-PDF web app
- New annotation features beyond the hardening list below
- OCR fallback, config-file support, persona library, batch mode

## Definition of Done

- Public GitHub repo, tagged `v0.1.0`, meaningful commit history starting
  from the baseline commit.
- README: demo GIF + gallery images above the fold; honest per-book cost
  estimate; zero docs-vs-code drift; working quickstart.
- Live GitHub Pages demo (web-preview HTML of an annotated gallery book).
- CI (GitHub Actions): `pytest` + `ruff` + `mypy` green on every push/PR.
- All audit findings of severity Medium or higher fixed; audit ledger
  committed under `docs/audit/`.
- Test files exist for `epub_processor.py` and `web_preview.py`; one real
  API E2E run verified per format (PDF + EPUB) with outputs visually checked.
- MIT `LICENSE`, `CONTRIBUTING.md`, repo description/topics, launch post
  drafts committed under `launch/`.

## Phase Plan

### Phase 0 — Foundation (partially complete)

- [x] Repair corrupt `.git` (stale `config.lock`, missing `objects/`),
  branch `main`.
- [x] Baseline commit of as-received state.
- [ ] Add `ruff` + `mypy` config to `pyproject.toml` dev extras; fix or
  explicitly waive initial violations.
- [ ] GitHub Actions workflow: pytest + ruff + mypy on push/PR (matrix:
  3.11/3.12).

Rationale for tooling-before-audit: every subsequent commit is lint/type
gated, and the audit's fixes show up as a clean, reviewable history.

### Phase 1 — Adversarial Audit

Six independent lenses, run as parallel reviewer subagents. No lens trusts
CLAUDE.md's claims; each verifies against code.

1. **Correctness — generation:** `annotation_generator.py`. Tool schema vs
   Pydantic model drift, context-windowing off-by-ones, prompt construction,
   response parsing, error paths.
2. **Correctness — rendering:** `document_processor.py`. Margin geometry
   math, morph rotation, connector endpoints, `_search_variants` matching
   and mismatching, `epub_processor.py` HTML injection.
3. **The tests themselves:** Do the 44 tests assert behavior or mirror
   implementation? Are mocked Anthropic responses faithful to real SDK
   response shapes? Enumerate what is untested.
4. **Security & robustness:** `web_preview.py` XSS (verify the
   `html.escape` claim), regex catastrophic backtracking, path handling,
   and the LLM-output trust boundary (`target_text` flows into regex and
   PDF search).
5. **API usage:** Validate against current Anthropic SDK docs (not
   memory): model IDs (`claude-sonnet-4-20250514` default is stale),
   tool_choice semantics, max_tokens, SDK built-in retry behavior, error
   taxonomy. Load the claude-api skill / live docs before this lens runs.
6. **Docs-vs-code drift:** README, ARCHITECTURE.md, CLAUDE.md vs reality.
   Known already: README omits `web-preview` command and describes EPUB as
   future work while `epub_processor.py` ships.

Plus one **real E2E run** per format with a live API key (fixture PDF + a
real EPUB), outputs opened and visually verified, per-page cost recorded
for the README.

**Findings discipline:** every subagent finding is adversarially
re-verified before acceptance. Verified findings land in
`docs/audit/<date>-adversarial-audit.md` (dated on creation): severity
(Critical/High/Medium/Low), `file:line`, description, repro, proposed fix.
The 8 inherited known issues are re-verified and merged into the same
ledger, not trusted.

**Gate:** user reviews the ledger before Phase 2 begins.

### Phase 2 — Fix Pass

- Work the ledger top-down by severity, test-first: failing test → fix →
  green, one commit per finding (or small coherent group).
- Dedicated test files for `epub_processor.py` and `web_preview.py` grow
  out of this pass; remaining coverage gaps filled explicitly.
- Exit: all Medium+ findings closed; Low findings closed or documented as
  accepted with reasoning.

### Phase 3 — Hardening Features

Built on verified ground, each with tests:

- **Retry/backoff:** exponential backoff + jitter for 429/500/529 —
  designed relative to the SDK's built-in retries (audit lens 5 determines
  what is actually missing rather than duplicating SDK behavior).
- **Async page processing:** `AsyncAnthropic` + bounded semaphore (default
  ~4 concurrent). Cross-page context semantics: pages run in waves of the
  concurrency width; the running INVENTION/WARNING notes list updates
  between waves, not within one. Strictly sequential accumulation remains
  available via `--concurrency 1`. This trade-off is documented in
  ARCHITECTURE.md.
- **Collision detection:** track occupied margin regions per page; shift
  or drop overlapping notes deterministically.
- **Input validation:** PDF magic bytes before `fitz.open`; friendly
  errors.
- **Font-warning noise:** log once at INFO.
- **Model defaults:** bump to a current model ID; `--model` still
  overridable.

### Phase 4 — Launch Assets

- **Sample gallery:** 2–3 public-domain books annotated for real,
  committed under `examples/` with before/after page screenshots. Book 1: a
  vintage chemistry textbook (archive.org) with the default Snape persona.
  Book 2: a cookbook or physics text with a different persona to prove
  persona swapping.
- **GitHub Pages:** deploy the self-contained web-preview HTML of one
  gallery book; link prominently from README.
- **README overhaul:** GIF + gallery above the fold, cost line from
  measured E2E numbers, drift fixed, quickstart verified end-to-end on a
  clean machine/venv.
- **Repo hygiene:** MIT LICENSE, CONTRIBUTING.md, repo topics/description,
  short IP note (Snape persona framed as homage/parody, same posture as
  the Riddle project). Remove or relocate the `.docx` handoff and other
  non-portfolio artifacts.
- **Launch drafts:** Show HN title + first comment, r/Python post, X
  thread — committed under `launch/`.

### Phase 5 — Release

- Tag `v0.1.0`, push to GitHub, enable Pages, verify CI green and all
  README links live. User posts launch content when ready.

## Session Mapping

- **Session 1:** Phase 0 remainder + Phase 1 (audit + ledger). Gate: user
  reviews ledger.
- **Session 2:** Phase 2 + start Phase 3.
- **Session 3:** Finish Phase 3 + Phase 4.
- **Session 4 (buffer):** Phase 5 + spillover.

## Risks & Mitigations

- **Mocked-test blind spot:** the audit's E2E lens runs the real API early
  so fixes land against observed behavior, not assumed behavior.
- **API cost:** E2E + gallery generation spends a few dollars on the
  user's key; per-page cost measured on the fixture first, and gallery page
  counts chosen accordingly.
- **IP/trademark:** project name and persona reference Harry Potter.
  Mitigation: homage/parody note, no copyrighted book text in the gallery
  (public domain only), precedent: Riddle.
- **WSL /mnt/c performance:** installs and test runs are slower on the
  Windows mount; acceptable for this project size. Venv already created at
  `.venv/`.
- **Scope creep:** anything not in this spec (PyPI, hosted demo, new
  features) is deferred to post-launch issues, which themselves become
  launch-day "good first issue" fodder.

## Open Questions

- None blocking. License defaults to MIT unless the user overrides before
  Phase 4 completes. GitHub repo name/visibility handled at Phase 5.
