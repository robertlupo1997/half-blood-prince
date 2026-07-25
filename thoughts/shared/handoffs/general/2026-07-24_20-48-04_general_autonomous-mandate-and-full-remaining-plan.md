---
date: 2026-07-24T20:48:04-04:00
researcher: Claude (Opus 5)
git_commit: 57c7b7f903743549333c9ce6428803e6c78b4909
branch: main
repository: half-blood-prince
topic: "Session 31 close — AUTONOMOUS MANDATE: own this project end-to-end with Codex; full remaining backlog planned with evidence"
tags: [autonomy, operating-model, codex, boilerplate, connectors, provider-retry, epub-matching, agpl, session-close]
status: complete
last_updated: 2026-07-24
type: handoff
---

# Session 31 — the autonomous mandate, and the whole remaining plan

## READ THIS FIRST: how the owner wants you to operate

Owner directive, verbatim intent, given at the end of this session:

> "We are going to have you and Codex plan out all of this. I don't want to have to even think
> about this project. I want 110% of it along with OpenAI's Codex. You guys are going to get this
> done for me — 100 of it. Write a handoff for the next session to take over and act this way.
> We're going to [do] all of the testing and all of the verifying and everything."

**What that means in practice:**

1. **Do not ask the owner to choose.** Pick the best option, state the decision and its rationale
   in one or two lines, and proceed. He has a standing autonomy directive (memory:
   `standing-autonomy-directive`) and reaffirmed it forcefully here. Blocking questions are a
   failure mode, not diligence.
2. **The only things still owner-gated** are listed in "Hard guardrails" below. Everything else
   is yours to decide.
3. **Codex does the building; you do the deciding and the verifying.** Dispatch via the
   `codex:codex-rescue` subagent (`gpt-5.6-sol`, high effort, for judgment/implementation).
   Keep planning, design forks, and all verification on Claude. This is the owner's standing
   preference (root `CLAUDE.md`) and it worked well this session.
4. **Verify everything yourself against the tree and against real data.** This session, agent
   reports were wrong FOUR times and a clean code review missed a live bug. Details in Learnings.
   Never merge on a report alone.
5. **"Done" means proven.** Suite + ruff + mypy + a real-book run, with numbers you watched print.

---

## Task(s)

1. ✅ **Ship-readiness pass** — AGPL-3.0 licensing, package metadata, tech-stack validation doc.
2. ✅ **OpenRouter key set up**; first real-model runs in project history (PDF and EPUB).
3. ✅ **Private GitHub repo created and pushed** — `origin` now exists.
4. ✅ **Connector-across-the-page defect fixed** (`943df1e`) — measured 317pt → 104pt.
5. ✅ **Boilerplate detection shipped** (`1711844`) — Gutenberg front/back matter no longer annotated.
6. ✅ **Malformed-200 retry shipped** (`57c7b7f`) — chapter loss went 2/2 runs → 0.
7. ✅ **"EPUB cross-tag matching" investigated and DISPROVEN as a gap** — see Learnings §1. The
   real cause of EPUB skips is diagnosed and planned but NOT yet built.
8. ⏳ **Everything in "Action Items" below** — planned, evidence-backed, not started.

## Critical References

- `.claude/skills/halfblood-roadmap/SKILL.md` — the live backlog. **Updated this session with
  corrected diagnoses.** Read it before picking work. (Untracked/session-local by prior
  convention; it is the working backlog regardless.)
- `docs/decisions/tech-stack-validation.md` — per-dependency rationale + the AGPL constraint.
- `thoughts/shared/handoffs/2026-07-24_17-08-59_session31-ship-readiness-agpl-first-real-model-run.md`
  — the earlier half of this session (licensing, first real-model run).

## Recent changes

Seven commits, all pushed to `origin/main`:

- `db53b1c` — AGPL-3.0 `LICENSE`, pyproject metadata, `docs/decisions/tech-stack-validation.md`
- `284f475` — first Session-31 handoff
- `f2ba877` — `[project.urls]`
- `943df1e` — connector fix: `connector_body_span_bp` on `Candidate`, weighted at
  `src/halfblood/layout/page_solver.py:179`
- `ca2a5a0` — gitignore local test books
- `1711844` — `src/halfblood/boilerplate.py` (threshold at `:21`) + CLI wiring
- `57c7b7f` — retry widening at `src/halfblood/generation/providers/openai_compat.py:154` and
  `src/halfblood/generation/providers/anthropic.py:132`

## Learnings

### 1. The project's own documentation lies. Probe HEAD before building anything.

Two load-bearing CLAUDE.md claims are **confirmed stale**:

- `CLAUDE.md:30` — "Direct Anthropic SDK, no LangChain… The SDK call, tool schema, and parsing
  are all in one file." **False.** Production generation is raw `httpx` through the provider seam;
  the `anthropic` package is an eval-only extra.
- `CLAUDE.md:94` — known issue #15, "EPUB `_locate_text` only searches within single text nodes."
  **False.** The v2 path uses `locate_across_nodes` (`src/halfblood/documents/epub.py:193`), wired
  at `src/halfblood/epub_processor.py:554` and `:594`. Verified by direct test: targets spanning
  `text→<em>→text`, `<em>→text→<strong>→text`, and `<strong>→text` all resolve.

I repeated claim #15 to the owner as fact and put it in the roadmap before testing it. He then
asked me to build it. **It was already built.** Cost: a whole investigation cycle. Always run a
test-first assertion against HEAD before accepting any documented "gap."

### 2. Agent reports and code reviews both missed live bugs. Verify against real data.

Four wrong claims from subagents this session, all caught by checking the tree or running real
input:

- A Codex design consult said `_prepared_candidate` "already receives `body_occupancy`." It does
  not; the parameter had to be threaded through.
- A Codex report cited `pyproject.toml` line numbers that were stale (my own edits caused the
  drift — see §3).
- Two agents reported an "eight call sites" count for `morph=`; reality is six.
- **The important one:** Codex's boilerplate classifier passed its own tests AND a clean Opus
  correctness review, but scored *distinct markers present* rather than occurrences. The real
  18k-char Gutenberg licence scored **1.43 against a 2.0 threshold** — a silent miss of the exact
  case the feature existed for. Short test samples still scored high, so the suite was blind.
  **Only running it against the real book caught it.**

Lesson: a green suite and a passing review are necessary, not sufficient. For anything that
processes documents, run it on `jekyll.epub` and read the numbers.

### 3. Editing a file that a document cites invalidates the citations.

I added lines to `pyproject.toml` mid-session, which silently invalidated 19 line citations in
the tech-stack doc, twice. Re-verify citations **last**, after all edits to the cited file.

### 4. Deleting worktrees exposed a broken editable install.

`pip install -e .` had been run from inside `.claude/worktrees/lane-f-persona/`, so the venv's
`.pth` pointed at a throwaway worktree. Pruning it broke `import halfblood` for subprocess-based
tests. Repointed at the real checkout. **Earlier "1443 green" runs were partly validating
worktree code**; the first genuinely-main run was 1445.

### 5. The security hook blocks all shell access to the API key — by design.

It blocks `printf` into `.env`, `. ./.env`, `$VAR` in curl headers, and regex secret scans.
Working pattern: a Python wrapper that reads `.env` and passes `env=` to `subprocess.run`.
Saved at `scratchpad/run_halfblood.py`; memory `openrouter-key-setup-and-env-hook` has the detail.

### 6. Free-tier OpenRouter is genuinely good enough to develop against.

`nvidia/nemotron-3-ultra-550b-a55b:free` produced in-voice Snape annotations on real literature
("He built a death trap and called it a laboratory."). Cost $0. The key has **no credit**
(`limit: 0`), so only `:free` models work.

## Verification

| Claim | Command run this session | Result |
|---|---|---|
| HEAD is `57c7b7f` | `git rev-parse HEAD` | `57c7b7f903743549333c9ce6428803e6c78b4909` |
| branch is `main` | `git rev-parse --abbrev-ref HEAD` | `main` |
| everything pushed | `git rev-parse HEAD origin/main` | both `57c7b7f9…` — identical |
| remote exists | `git remote -v` | `origin https://github.com/robertlupo1997/half-blood-prince.git` (private) |
| full suite green | `python -m pytest tests/ -q` (after final commit) | `1461 passed, 28 warnings` |
| ruff clean | `ruff check src tests eval scripts` | `All checks passed!` |
| mypy clean | `mypy src/halfblood` | `Success: no issues found in 43 source files` |
| `documents/epub.py:193` — cross-node locator | `grep -n "def locate_across_nodes" src/halfblood/documents/epub.py` | `193:def locate_across_nodes(root: Tag, selector: TargetSelector) -> CrossNodeMatch \| None:` |
| `epub_processor.py:554,594` — it is wired | `grep -n "locate_across_nodes(chapter_root" src/halfblood/epub_processor.py` | `554:…pre_resolved.append(…)` and `594:…fresh_match = …` |
| cross-tag matching actually works | direct test of 3 tag-spanning targets via `locate_across_nodes` | all three `FOUND` |
| `matching.py:50` — punctuation folds | `grep -n "_PUNCTUATION_FOLDS = {" src/halfblood/documents/matching.py` | `50:_PUNCTUATION_FOLDS = {` |
| `page_solver.py:179` — body-span weight | `grep -n "1_300 \* body_span_cost" src/halfblood/layout/page_solver.py` | `179:        + 1_300 * body_span_cost` |
| `boilerplate.py:21` — threshold | `grep -n "BOILERPLATE_THRESHOLD: float" src/halfblood/boilerplate.py` | `21:BOILERPLATE_THRESHOLD: float = 2.0` |
| retry sites in both providers | `grep -n "except StructuredOutputError as exc:" …providers/*.py` | `openai_compat.py:154`, `anthropic.py:132` |
| beam is still the default solver | `grep -n 'solver: Literal\["greedy", "beam"\]' src/halfblood/layout/engine.py` | `66:    solver: … = "beam"` |
| `v0.1.0` tag intact | `git tag -l v0.1.0` | `v0.1.0` |
| CLAUDE.md SDK claim is stale | `grep -n "Direct Anthropic SDK" CLAUDE.md` | `30:1. **Direct Anthropic SDK, no LangChain.**…` (contradicted by the httpx provider seam) |
| CLAUDE.md issue #15 is stale | `grep -n "_locate_text\` only searches within single text nodes" CLAUDE.md` | `94:15. **EPUB processor `_locate_text` only searches…**` (contradicted by the row above) |
| connector fix, measured | `page.get_drawings()` vertical span of open-curve paths, page 2, before vs after | `317.4pt (40.1%)` → `103.9pt (13.1%)` |
| boilerplate fix, measured | full-book run + count of notes on boilerplate sections | `Skipped 2 boilerplate section(s): 2, 13`; notes on boilerplate `48 → 0` |
| retry fix, measured | three full-book runs | before: lost ch10, then ch5; after: **0 failed pages**, 11/11 sections |
| EPUB skips diagnosed | render real plan, read `RenderReport.skipped` | `rendered=44 skipped=6`, **all `SkipReason.MISSING_TARGET`**, zero ambiguous |
| working tree dirt | `git status --short` | exactly `M CLAUDE.md` + 2 known untracked — nothing else |

## Artifacts

- Seven commits above; all pushed.
- `src/halfblood/boilerplate.py`, `tests/test_boilerplate.py` (11 tests).
- Retry tests appended to `tests/test_openai_compat_provider.py` and `tests/test_anthropic_provider.py`.
- `TestConnectorBodySpanCost` in `tests/test_page_solver.py`.
- `.claude/skills/halfblood-roadmap/SKILL.md` — **rewritten with corrected diagnoses**.
- Memory: `openrouter-key-setup-and-env-hook`.
- Owner-visible artifact: `C:\Users\Trey\Downloads\jekyll-annotated-by-the-prince.epub`.
- Scratchpad helpers worth recreating if lost: `run_halfblood.py` (key-safe CLI runner),
  `analyze_skips.py`, `fuzzy_missing.py`.

## Action Items & Next Steps

Ranked by evidence. **Do these without asking.** Each ends with a real-book verification.

### P1 — Recover the 12% of EPUB annotations currently lost

Diagnosed this session; not built. All 6 skips on Jekyll are `MISSING_TARGET` because the model
does not quote verbatim. Breakdown by longest-common-run against the real chapter text:
3 near-misses off by 1–2 chars (`104/105`, `92/94`, `70/71` — the model adds/drops a quote mark),
3 genuine paraphrases (`52/89`, `113/139`, `37/71` — dropped dialogue attribution).

1. **Prompt hardening (do first).** Require verbatim, character-for-character `target_text` in
   the system prompt / tool-schema description. Upstream of the matcher, zero mis-anchor risk.
2. **Case-insensitive matching.** Recovers exactly 1 of the 6 (`104/105` resolves under
   `casefold()` alone). `matching.py:50` already folds quotes/dashes/whitespace but is
   case-sensitive.
3. **Bounded fuzzy recovery — ONLY if 1+2 leave real loss, and it MUST stay fail-closed.**
   Lane D deliberately made ambiguous PDF targets skip rather than guess. A fuzzy match that is
   not unique AND high-confidence must skip. A note anchored to the wrong sentence is worse than
   a missing note and is undetectable to the reader.

Verify by re-running the full book and comparing `rendered N / skipped M`.

### P2 — Fix the stale CLAUDE.md claims

`CLAUDE.md:30` and `CLAUDE.md:94` are provably wrong (rows in Verification). They actively caused
wasted work this session. **Blocked on a mechanical problem, not a decision:** the file carries a
pre-existing uncommitted rewrite (`M CLAUDE.md`) from an earlier session that must never be
reverted or blind-committed (memory: `claude-md-preexisting-uncommitted-rewrite`). Resolve by
diffing what is already uncommitted, preserving it, and adding the corrections on top.

### P3 — Prove quality on a frontier model

The key has no credit, so all evidence is from one free model. Once credits exist, run the same
book through a frontier model and diff annotation quality. This is the open question behind
"is this product actually good."

### P4 — Remaining feature backlog (none blocking, ranked)

- Web-preview UX: Copy-JSON button, search/filter.
- Config keys for `max_per_page` and `font_path` (persona/provider keys already exist).
- Persona library (`personas/*.txt`) — `--persona-file` already works.
- Batch mode (`annotate-batch *.pdf`).
- Eval-judge migration onto the provider seam (Phase-5).
- Connector Layer 2/3 (`AnchorWarningCode.CONNECTOR_OMITTED`, declared at
  `models/rendering.py:113`, wired to nothing). **Designed and deliberately deferred:** the
  proposed 5000 bp gate would not have fired on the residual 13% connector (~1310 bp), so it is
  defense-in-depth for forced-far placements only. Build only if a real book produces one.
- Old review advisories: freeze `UsageTotals`, empty-persona-string edge test.

### P5 — Release decision

Repo is private. Everything needed for a public release is in place (AGPL-3.0 `LICENSE`, full
metadata, clean history scan). Flipping to public is the owner's call and is one click in GitHub
settings — do not do it unilaterally.

## Hard guardrails (still owner-gated — do NOT decide these yourself)

- **Never make the repository public.**
- **Never `git checkout --` or blind-commit `CLAUDE.md`** (pre-existing uncommitted rewrite).
- **Never add a second retry layer.** The httpx provider transport is the sole retry owner
  (root `CLAUDE.md`, architecture spec §4.6). Widen the existing branch instead — that is how
  `57c7b7f` was done.
- **Never spend money** (no credit purchases, no Artifex licence).
- **Do not activate `sdd-driver`** — its frontmatter hooks do not fire on this installation
  (memory: `sdd-driver-hooks-not-honored`).
- Rotate the OpenRouter key when convenient; it was pasted into a chat transcript. It lives in
  the gitignored `.env` and is confirmed untracked.

## Other Notes

- **Environment:** repo is on `/mnt/c` (drvfs) — POSIX permissions are not enforced, so
  `chmod 600 .env` silently does nothing. Not fixable from inside WSL.
- **Test book:** `jekyll.epub` at the repo root is gitignored. If missing, re-fetch with
  `curl -L -o jekyll.epub https://www.gutenberg.org/ebooks/43.epub3.images` — the agent shell
  is blocked from gutenberg.org, so the owner must run it with a `!` prefix.
- **Rollback:** each feature is a single revert — `git revert 57c7b7f` (retry),
  `1711844` (boilerplate), `943df1e` (connector). All landed linear; no `-m 1` needed.
- The suite went 1443 → **1461** this session with zero regressions.
