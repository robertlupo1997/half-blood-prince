---
date: 2026-07-11T00:39:38-04:00
researcher: Claude (Opus 4.8) — controller / reviewer in a Codex-implementer loop
git_commit: a0a643f8e058d191d73594f518a8f4e74783c764
branch: main
repository: half-blood-prince
topic: "Session 5 — model-fix batch shipped; full-project architecture + Phase 0/1 plan authored (multi-provider + real handwriting)"
tags: [provider-layer, handwriting-rendering, audit, sdd, codex-loop, architecture]
status: complete
last_updated: 2026-07-11
type: handoff
---

# Handoff: v0.1.0 → finished open-source — Session 5

Written to be resumed by **either a Codex session or a Claude session** (the
owner expects the next session may be Codex). It assumes no tool-specific
context: the workflow is *controller writes failing tests → implementer writes
code → controller runs the gate → commit*. In this session the controller was
Claude (Opus 4.8) and the implementer/architect was Codex (`codex exec`,
authenticated, `codex-cli 0.144.1`).

## Task(s)

Governing documents (read in this order):
1. `docs/superpowers/specs/2026-07-11-full-project-architecture.md` — THE spec
   for the finished product (Codex-authored, §12 is the controller review).
2. `docs/superpowers/plans/2026-07-11-phase0-1-implementation-plan.md` — the
   21-task executable plan (Phase 0 audit-close + Phase 1 provider foundation).
3. `docs/audit/2026-07-10-adversarial-audit.md` — the AUD-01..44 backlog.
4. `.superpowers/sdd/progress.md` — the running SDD ledger (gitignored, on disk).

- ✅ **Merged the model-fix batch to `main`** (was on `phase2-model-fix`, ff-merged).
- ✅ **AUD-01/02/03/04** (commit `82c5834`): retired default `claude-sonnet-4-20250514`
  → single-sourced `DEFAULT_MODEL="claude-sonnet-5"`; added the `[eval]` extras group.
- ✅ **AUD-16** (commit `4ae00a4`): API failures now surface — `AllPagesFailedError`
  when all attempted pages fail; `failed_pages` tracks partial failures; CLI exits
  non-zero cleanly + configures logging.
- ✅ **Full-project architecture spec** (commit `9a99f25`) — Codex architected it, controller reviewed + adopted.
- ✅ **Phase 0 + Phase 1 implementation plan** (commit `a0a643f`) — Codex authored, controller reviewed + adopted.
- ⏳ **NEXT: execute the plan**, task by task, starting at `P0-T1`. None of the
  21 tasks is started.
- ⏳ **Two OWNER decisions still open** (see Action Items) — orchestration model
  and P1-T5 SDK-vs-httpx — neither blocks starting Phase 0.
- ⏳ **Key-blocked**: live E2E / provider `doctor` smoke tests need `ANTHROPIC_API_KEY`
  (still unset). All *commit* gates are mocked/offline; the key is never required to commit.

## Critical References

1. `docs/superpowers/specs/2026-07-11-full-project-architecture.md` — the target
   architecture. Keystone: **separate semantic `AnnotationPlan` / resolved layout /
   renderer-neutral `InkScene`** so paid LLM generation is reusable across styles
   and formats. Provider layer = thin `httpx`, two wire protocols (Anthropic +
   OpenAI-compatible), OpenRouter/Ollama/LM Studio as profiles, no LiteLLM.
   Handwriting = procedural centerline strokes (offline default) + optional
   licensing-gated ONNX; wobbly marks/connectors/doodles generated once, rendered
   per surface. §12 = controller review (accuracy check + 4 caveats).
2. `docs/superpowers/plans/2026-07-11-phase0-1-implementation-plan.md` — start
   at `P0-T1`. Each task has: covered AUD-NN, goal, test-first spec, acceptance
   criteria, effort (S/M/L), dependencies. Critical path is stated at the bottom.
3. `docs/audit/2026-07-10-adversarial-audit.md` — the finding detail behind each
   Phase 0 task (repro scripts at `.superpowers/sdd/audit/repro/`, gitignored).

## Recent changes

- `src/halfblood/annotation_generator.py` — `DEFAULT_MODEL = "claude-sonnet-5"`
  (line 31); `class AllPagesFailedError(RuntimeError)` (line 34);
  `_generate_for_page_tracked` helper feeds the all-failed check in
  `generate_for_document` (first use at line 314). `generate_for_page` still
  returns `[]` on `APIError` (public contract unchanged).
- `src/halfblood/cli.py` — imports `DEFAULT_MODEL, AllPagesFailedError`;
  `logging.basicConfig(...)` in the `main` group; `annotate`/`preview` catch
  `AllPagesFailedError` → `click.ClickException` and warn on `failed_pages`.
- `eval/eval_harness.py` — `DEFAULT_MODEL` fallback now imported from the
  generator (`HALFBLOOD_EVAL_MODEL` override preserved).
- `pyproject.toml` — added `[project.optional-dependencies] eval`.
- `tests/test_config.py` (new, 4 tests), `tests/test_failure_handling.py`
  (new, 5 tests) — regression tests for the above.
- `docs/superpowers/specs/2026-07-11-full-project-architecture.md`,
  `docs/superpowers/specs/2026-07-11-multi-provider-proposal.md`,
  `docs/superpowers/plans/2026-07-11-phase0-1-implementation-plan.md` — new docs.

**No product code beyond the two fix commits changed this session** — the
architecture and plan are docs only.

## Learnings

1. **The Codex-implementer loop works cleanly and unattended.** `codex exec
   --sandbox workspace-write -C <repo> -o <report> < <brief>` implements against
   a controller-written failing-test spec without approval hangs (the machine's
   `~/.codex` is authenticated and `/mnt/c/Users/Trey` is `trust_level=trusted`).
   Briefs/reports live at `.superpowers/sdd/phase2-task-{1,2}-{brief,report}.md`,
   `.superpowers/sdd/{architect,planner}-{brief,report}.md`. **Codex's report is
   testimony — the controller MUST re-run the full gate itself** (both Codex runs
   claimed pass; both were independently re-verified).
2. **The whole Anthropic coupling is one seam** — `annotation_generator.py`'s
   forced-tool-use `client.messages.create(...)`. Everything downstream consumes
   an `AnnotationPlan` and is provider-agnostic. This is why the provider layer
   (Phase 1) is tractable.
3. **"Scribbling, not just letters" is two problems.** Today there is NO real
   handwriting anywhere — it's the Caveat *font* + a 1–3° tilt (PDF via
   `fitz.Shape.insert_text` morph; web/EPUB via CSS). The only truly drawn stroke
   is the connector arrow. Real handwriting = (a) letterforms (the long pole —
   needs an authored stroke alphabet or a licensed ONNX model) and (b) hand-drawn
   *marks* (cheap, no assets). Recommend shipping marks first (spec §12 caveat 2).
4. **The stroke-asset license is the main handwriting release blocker** (spec
   §10.1) — a font license does NOT automatically permit deriving centerline
   trajectory data. Do not start letterform work depending on assets before this
   is settled.
5. **No universal model default** is a deliberate design rule (spec §4.4): each
   provider preset requires an explicit model, so a retirement can never again
   silently break everyone (the failure we just fixed).

## Verification

| Claim | Command run this session | Result |
|---|---|---|
| HEAD `a0a643f`, branch `main`, tree clean | `git rev-parse HEAD; git rev-parse --abbrev-ref HEAD; git status --short` | `a0a643f8...`, `main`, empty |
| Full gate green after all changes | `.venv/bin/ruff check src tests eval && .venv/bin/mypy src/halfblood && .venv/bin/pytest tests/ -q` (re-run 00:39) | ruff "All checks passed!"; mypy "no issues in 7 files"; **53 passed** |
| `annotation_generator.py:31` — `DEFAULT_MODEL = "claude-sonnet-5"` | `grep -n "^DEFAULT_MODEL" src/halfblood/annotation_generator.py` | `31:DEFAULT_MODEL = "claude-sonnet-5"` |
| `annotation_generator.py:34` — `AllPagesFailedError` | `grep -n "class AllPagesFailedError" src/halfblood/annotation_generator.py` | `34:class AllPagesFailedError(RuntimeError):` |
| `annotation_generator.py:314` — tracked-helper wired | `grep -n "_generate_for_page_tracked" src/halfblood/annotation_generator.py` | first use at `314:` |
| Retired model gone from all sources | `grep -rn "claude-sonnet-4-20250514" src eval` | no matches (ABSENT) |
| Merged fix commits present | `git log --oneline -6` | `82c5834` (AUD-01/02/03/04), `4ae00a4` (AUD-16) on `main` |
| Spec + plan committed | `git log --oneline -6` + `ls docs/superpowers/{specs,plans}/2026-07-11-*` | `9a99f25` spec, `a0a643f` plan; both files present |
| `ANTHROPIC_API_KEY` present | `python3 -c "os.environ.get('ANTHROPIC_API_KEY')"` (earlier this session) | UNSET — live E2E/doctor remain blocked-on-key |

## Artifacts

Committed on `main`:
- `82c5834` — AUD-01/02/03/04 fix + `tests/test_config.py`
- `4ae00a4` — AUD-16 fix + `tests/test_failure_handling.py`
- `9a99f25` — `docs/superpowers/specs/2026-07-11-full-project-architecture.md` (+ multi-provider-proposal.md)
- `a0a643f` — `docs/superpowers/plans/2026-07-11-phase0-1-implementation-plan.md`

On disk, gitignored (durable this machine only — `thoughts/` and `.superpowers/`
are in `.gitignore`; this handoff is force-added):
- `.superpowers/sdd/progress.md` — Session 5 ledger appended
- `.superpowers/sdd/{phase2-task-1,phase2-task-2,architect,planner}-{brief,report}.md`
- `.superpowers/sdd/audit/` — the verified audit evidence + repro scripts

## Action Items & Next Steps

1. [ ] **Owner decisions (non-blocking; capture before Phase 1, not needed for Phase 0):**
   (a) *Orchestration* — Session 5 defaulted to controller-orchestrates with the
   implementer doing code; the owner floated Codex-orchestrates and thinks
   "Codex 5.6" may be better for the next session. Either works with this plan.
   (b) *P1-T5 SDK-vs-httpx* — the plan replaces the Anthropic SDK with a raw
   `httpx` adapter for uniform retry/timeout. Lower-risk alternative: keep the
   SDK for Anthropic and use `httpx` only for OpenAI-compatible. Decide before P1-T5.
2. [ ] **Start executing the plan at `P0-T1`** (harden Anthropic response handling
   + SDK-shaped tests; covers AUD-05/10/14/21/23 + L-1/L-3). Loop per task:
   controller writes the failing tests the task specifies → implementer writes
   code → run `ruff check src tests eval` + `mypy src/halfblood` + `pytest tests/ -q`
   → commit only when all green. Preserve `tests/test_config.py` +
   `tests/test_failure_handling.py`.
3. [ ] Proceed down the plan's critical path (P0-T1 → P0-T2 → P0-T3/P0-T8 →
   P0-T12 → P1-T1 → …). Phase 0 closes the audit; Phase 1 delivers the
   cost-motivated "any cheap API" win independent of handwriting.
4. [ ] **When `ANTHROPIC_API_KEY` exists** — run the prepared E2E commands (in
   `docs/audit/2026-07-10-adversarial-audit.md` "E2E results" + `.superpowers/sdd/audit/e2e_pdf.py`)
   now that the model is current; record cost/output. Handwriting (spec §5) and
   the full module restructure are later phases (spec §9 Phases 2–6) — do NOT
   pull them forward ahead of Phase 0/1.

## Other Notes

- **Repo is on `/mnt/c` under WSL** — git and pytest are slow (~35s for the
  suite); the venv at `.venv/` has all deps (a bare system `python` does NOT —
  Codex's sandbox hit this and reported "can't collect tests"; always use `.venv`).
- **Handoffs are force-added**: `thoughts/` is gitignored, so
  `git add -f <handoff>` (matches the Session 2/4 convention). `HANDOFF.md` at
  repo root is tracked and is the pointer.
- **Autonomy is configured**: `.claude/settings.local.json` has
  `bypassPermissions`; the committed `.claude/settings.json` keeps a lightweight
  PreToolUse guard hook (blocks only genuinely destructive ops) — do not "fix" it.
- **Do NOT re-plan the merged work** (AUD-01/02/03/04/16) — the plan and spec
  both mark it done; preserve its tests.
- **For a Codex resuming session**: the plan's per-task "Test-first" blocks are
  the spec; a controller (you) writes those tests first, then implements, then
  gates. The spec's §12 controller review captures the scope/effort caveats.
