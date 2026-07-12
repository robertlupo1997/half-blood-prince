---
date: 2026-07-11T18:15:26-04:00
researcher: Claude (Opus 4.8) — controller/reviewer session
git_commit: b352589c2210c709116ef6225476052b54f539e9
branch: main
repository: half-blood-prince
topic: "Session 9 — F1 (--font) reconciled, reviewed, merged; fonts fetched; default = Caveat Brush; artifact regenerated"
tags: [f1-font-options, cli, fonts, artifact, codex-usage, handoff]
status: complete
last_updated: 2026-07-11
type: handoff
---

# Handoff: F1 complete end-to-end (default chosen), Phase 1 is next

> Session 9 was pure controller/reviewer work — **no Codex dispatch** (there was
> nothing to implement; reviewing + committing already-correct code and fetching
> assets is controller work). The owner-facing F1 workstream is now fully closed
> including the default-font decision. Next roadmap step is **Phase 1 (P1-T1)**.

## Task(s)

1. ✅ **F1 `--font` reconciliation** — the pre-existing, uncommitted, unreviewed
   `--font` diff was adversarially reviewed against the F1 spec, accepted as-is
   (option (a): ad hoc accept, not redone through Codex), and merged to `main`.
2. ✅ **Fetch the 2 missing TTFs** (Homemade Apple, Mrs Saint Delafield) — done
   via pre-approved `urllib`; all 4 registered fonts now resolve + load.
3. ✅ **Resolve the open font-license question** — Homemade Apple = Apache-2.0,
   Mrs Saint Delafield = OFL-1.1 (RFN).
4. ✅ **Regenerate the font-trial artifact** — all 4 candidates, self-contained,
   republished in place. Structure validated; visual render NOT confirmed (no
   browser in this env).
5. ✅ **Owner decision: default font = Caveat Brush** (the incumbent, already
   installed) — no code change needed; it is already the auto-discovered default.
6. ⏳ **Phase 1 (P1-T1)** — semantic plan v2 + provider foundation. NOT started;
   large, needs test-first Codex briefs written by the controller before dispatch.

## Critical References

1. `docs/superpowers/specs/2026-07-11-full-project-architecture.md` §Phase 0–6
   (lines 599–634) — the 7-phase roadmap.
2. `docs/superpowers/plans/2026-07-11-phase0-1-implementation-plan.md` — Phase 1
   tasks (P1-T1…), next in execution order.
3. `docs/superpowers/plans/2026-07-11-phase2-3-implementation-plan.md` — Phase 2/3
   task plan (19 tasks; §13 is the controller review). Still untracked (uncommitted).
4. `.superpowers/sdd/progress.md` — Session 9 entries (default decision, F1
   reconciliation rationale, fetch/license/artifact outcomes). Gitignored ledger.
5. Memory (Claude-side): `codex-implementer-orchestration` — Codex is the
   primary/maximal builder; controller only implements if Codex cannot.

## Recent changes

- `src/halfblood/cli.py` — `REGISTERED_FONTS` registry, `_resolve_font_option()`,
  `_FONTS_DIR` (`parents[2]`), `--font NAME|PATH` on `annotate`, EPUB-ignored
  warning. Merged (commit `5e55140`).
- `fonts/README.md` — rewritten with the registry table + license note. Merged.
- `tests/test_font_selection.py` — 8 new tests. Merged.
- `fonts/HomemadeApple-Regular.ttf`, `fonts/MrsSaintDelafield-Regular.ttf` —
  fetched into place (gitignored, NOT committed).
- Artifact `e258a268-…` regenerated in place (external, not a repo file).

## Learnings

- The real `DocumentProcessor.__init__` accepts `font_path` (`document_processor.py:119`),
  so the test's recording fake was not masking a signature mismatch.
- **The green suite never exercised the real `_FONTS_DIR`** — every test injects
  `fonts_dir` or monkeypatches `cli._FONTS_DIR`. The real `parents[2]` path was
  verified separately (resolves to the repo `fonts/`). Re-check this if `cli.py`
  moves in the directory tree.
- Codex CLI 0.144.1 has **no** non-interactive usage/quota/rate-limit command
  (`codex --help` lists none; `doctor` shows only auth health). The ChatGPT auth
  token's plan claim currently reads `chatgpt_plan_type = free`, no active paid
  window — flagged for the owner (may be a stale token or the sub isn't active on
  this account; conflicts with the "maximal OpenAI subscription" directive).

## Verification

| Claim | Command run this session | Result |
|---|---|---|
| F1 merged to `main` | `git log --oneline -3` | `b352589` merge + `5e55140` feat on top of `e56622d` |
| Full suite green | `.venv/bin/pytest tests/ -q` (after merge) | `213 passed` |
| ruff clean | `.venv/bin/ruff check src tests eval` | `All checks passed!` |
| mypy clean | `.venv/bin/mypy src/halfblood` | `no issues found in 7 source files` |
| `DocumentProcessor` takes `font_path` | `grep -n "def __init__" src/halfblood/document_processor.py` | `117:    def __init__(` → `119: font_path: str | None = None` |
| Real `_FONTS_DIR` resolves registered names | `python -c "import halfblood.cli as c; c._resolve_font_option('caveat-brush')"` | `…/fonts/CaveatBrush-Regular.ttf`, `is_file: True` |
| All 4 fonts load in fitz | `python … fitz.Font(fontfile=…)` for each | 642 / 230 / 353 / 238 glyphs |
| Default (no `--font`) = Caveat Brush | `python -c "…DocumentProcessor()…_fontfile"` | `…/fonts/CaveatBrush-Regular.ttf` (alias `HBProseHand`) |
| 2 fetched TTFs present, gitignored | `ls fonts/*.ttf` + `git status --short` | 4 TTFs on disk; none appear in `git status` |
| Artifact structure complete | `grep -o` counts on generated HTML | 4 cards, 20 notes, 4 families, tags balanced |
| Artifact visual render | (no browser in env) | UNVERIFIED (no tool access) — structure only |
| Total phases | `grep '### Phase' …full-project-architecture.md` | 7 phases (0–6); Phase 0 done |
| Codex dispatches to date | `ls .superpowers/sdd/*report*.md` + ledger grep | ~19 reports (9 `sol`, 8 `terra` mentions); this session 0 |
| Codex plan type | decoded `~/.codex/auth.json` id_token claims | `chatgpt_plan_type = free`, no active window |

## Artifacts

- Committed to `main`: `src/halfblood/cli.py`, `fonts/README.md`,
  `tests/test_font_selection.py` (feat `5e55140`, merge `b352589`).
- Written this session (durable, being committed with this handoff):
  `thoughts/shared/handoffs/2026-07-11_18-15-26_session9-f1-complete-default-caveat.md`,
  `HANDOFF.md` (pointer updated).
- Gitignored: `fonts/HomemadeApple-Regular.ttf`, `fonts/MrsSaintDelafield-Regular.ttf`.
- External: artifact `https://claude.ai/code/artifact/e258a268-2a9b-48a7-bc05-1102ad7ebb09`.
- Generator scratch (not in repo): `scratchpad/gen_font_trial.py`,
  `scratchpad/prince-hand-font-trial.html`.

## Action Items & Next Steps

1. **Phase 1 at P1-T1** — semantic plan v2 + provider foundation, maximal Codex
   delegation per `docs/superpowers/plans/2026-07-11-phase0-1-implementation-plan.md`.
   Controller writes failing tests first, then dispatches Codex briefs.
2. **Owner: confirm Codex/ChatGPT plan** — the token says `free`. If a paid
   ChatGPT sub should be active, re-login (`codex login`) or check the ChatGPT
   dashboard; real rate-limit usage is only visible in the interactive TUI
   (`/status`) or the dashboard, not from the CLI headlessly.
3. Still-uncommitted harness housekeeping (owner reviews via `git diff`, never
   auto-committed): `CLAUDE.md`, `.claude/skills/`, the phase2-3 plan.
4. Optional: if the owner actually meant Just Me Again Down Here as default, that
   is a one-line change (raise the opacity floor ~0.7 for that thin face too).

## Other Notes

- Repo on `/mnt/c` under WSL: use `.venv/bin/…` for everything.
- `.claude/settings.local.json` `bypassPermissions` is intentional — do not "fix".
- `curl` is denied in this environment; use `.venv/bin/python` + `urllib.request`
  for network fetches (that is how the 2 TTFs were fetched).
