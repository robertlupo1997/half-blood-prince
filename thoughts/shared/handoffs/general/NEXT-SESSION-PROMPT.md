# Kickoff prompt for the next session

Paste everything below the line. It is self-contained — assume the next session
remembers nothing.

---

You have a FULL AUTONOMOUS MANDATE on this project. I don't want to think about it.
Pick the best option, state the decision in one line, proceed. Blocking questions are a
failure. **Use a dynamic workflow** to orchestrate this — fan out, review adversarially,
verify, merge. **Use Codex (gpt-5.6-sol, high effort) as the adversarial code reviewer**,
not Opus.

## FIRST: confirm the baseline

At `3b12786` on `main`:

```
python -m pytest tests/ -q          # 1750 passed
ruff check src tests eval scripts   # All checks passed!
mypy src/halfblood                  # Success: no issues found in 43 source files
git status --short                  # empty
```

If those don't match, stop and tell me before doing anything else.

Then read `thoughts/shared/handoffs/general/2026-07-26_general_font-wheel-bug-pdf-anchor-quality.md`.
Read its **Learnings §1** first — the biggest bug of that session was invisible to 1750
tests, both linters, and the dev tree, because the dev tree has a directory the shipped
wheel does not.

## WHAT "DONE" MEANS

Ship v0.1.0-quality. Work the list below top-down. Stop when the list is empty **or** when
two consecutive defect-hunt rounds find nothing new — then write a handoff and stop. Do not
churn for the sake of activity.

### Automatable — do all of these

1. **Annotation collision detection** (known issue #14, the oldest surviving item). Notes
   can overlap each other, and connectors cross body text — the latter was *observed* in a
   real render in Session 31. `layout/occupancy.py`, `documents/pdf_occupancy.py` and
   `layout/engine.py` already exist and may cover part of this. **Probe HEAD before
   building anything** — this project's docs have been wrong repeatedly, and one prior
   session wasted a full cycle rebuilding something that already worked.
2. **Should the EPUB path accept prefix anchors?** PDF now renders 49/50 where EPUB renders
   48/50 on the same plan, because `documents/epub.py:locate_across_nodes` accepts tier 0
   only. Its docstring frames that as a contract, not a technical limit, and a prefix span
   would still produce valid segments. Decide it with a measurement on a real EPUB
   (`analyze_skips.py` replays a frozen plan in ~6s, free and deterministic), not by
   argument. See the addendum in `docs/decisions/verbatim-quoting-prompt-vs-matcher.md`.
3. **Verify the preview connector re-draw after a re-position.** Lane B shipped it and
   explicitly did NOT verify it — `doLayout` is stubbed in the JS harness. It is "correct by
   construction", which is exactly the claim that has been wrong before here.
4. **OCR fallback decision.** A page-image scan is now *diagnosed* (exit 1, names
   `ocrmypdf`). Decide whether the tool should OCR such files itself behind a flag, or keep
   telling the user to. That is a dependency decision — weigh adding a heavy non-Python
   dependency against the benefit, and write it up in `docs/decisions/` either way.
5. **Dead branch:** `cli.py`'s `if hasattr(processor, "render_plan")` — both processors have
   it, so the `else` is unreachable. It hides which path is live. Remove or justify.
6. **Then hunt for new defects** using the method that has worked every time: build the real
   artifact and look at it. Render a real annotated PDF and read the page image. Install the
   wheel into a clean venv and use it. Run the preview's JS under a DOM stub. A green suite
   proves the tests pass; it does not prove the feature works.

### Owner-gated — you CANNOT do these, do not try

- **Frontier-model eval quality run.** Needs credit, and "never spend money" is a hard
  guardrail. The current 4.72/5 is *self-judged on one free model* and is not a defensible
  quality number. Leave it; tell me if you think it's the last thing blocking release.
- **Public release.** "Never make the repo public" is a hard guardrail. AGPL-3.0 licensing
  and metadata are already in place, so this is one flip by me, not work.

If you finish everything automatable, say so plainly and stop. Don't invent scope.

## WORKFLOW SHAPE

Author a dynamic workflow rather than one big fan-out. Suggested phases, adapt freely:

- **Probe** (parallel, read-only): establish what is actually true at HEAD for each item
  above. Most of this project's wasted cycles came from believing a document. Every finding
  must come with the command that produced it.
- **Build** (parallel lanes, `isolation: "worktree"`): one lane per independent item, with
  explicit FILE OWNERSHIP in each brief. Overlapping files ⇒ serialize.
- **Adversarial review** (Codex, read-only): every lane's diff gets reviewed by Codex with
  an explicit instruction to *try to break it* — find the case that fails, the test that
  passes for the wrong reason, the claim not backed by a command. Default to "refuted"
  when uncertain.
- **Verify and merge** (you, never a lane): diff each tree against its base commit yourself,
  run the suite yourself, exercise the real artifact yourself, then commit.

### Codex gotcha that will silently cost you a lane

**`codex:codex-rescue` + `isolation: "worktree"` loses all work with no error.** The rescue
agent spawns a *detached* Codex job and returns immediately; the harness then reclaims the
worktree out from under a still-live process. Proven twice on 2026-07-26 — one full lane
produced zero files and `pgrep` still showed Codex "working".

Use Codex for **read-only adversarial review in the main tree**, which needs no worktree and
sidesteps this entirely. For lanes that *write*, use a `general-purpose` agent with
`isolation: "worktree"` that works **synchronously** and returns only when done — say that
explicitly in the brief. Also note: `ls .claude/worktrees/` and `git worktree list` both
omit unregistered worktrees, so neither proves absence — stat the path.

## HOW TO VERIFY (this is the part that matters)

Recent sessions found six defects that 1600+ passing tests and both linters were blind to:
a silently broken judge, custom personas getting a 707-char prompt instead of 4779, the
suite reading the developer's real config, a cross-page search bug, `--font` broken in every
installed wheel, and margin notes clipped off the page. **Every one was caught by building
the real case by hand and running it.**

- "Done" = full suite + ruff + mypy + **the real artifact exercised**, with numbers you
  watched print. Never a count you didn't see.
- **Never merge on a lane's report.** Diff the tree against that lane's base commit. Codex
  once reported work it had not done; only `git diff` caught it.
- **Verify your own spec tests against HEAD before dispatching.** Three of five Codex
  deviations in one session were defects in the brief or its tests, not in Codex's work.
- **Briefs must name the forbidden shortcut**, not just the goal — that is what makes a lane
  escalate instead of hacking around it. And if the clean fix needs a test fixture changed,
  SAY SO; forbidding it just forces a worse hack into production code.
- **A measurement can be confidently wrong.** One session reported "23 stub anchors, 11
  verbatim matcher bugs"; all 23 were artifacts of a rig that didn't do what the product
  does. Before believing a number, ask whether the harness reproduces the real code path.

Reusable recipes (scratchpad, session-local — recreate them; the last handoff lists them):
frozen-plan A/B (`analyze_skips.py`, ~6s, no API) · `pdf_anchor_quality3.py` (per-page PDF
anchor quality) · `prove_font_bug.py` (build the wheel, install into a clean venv, use it) ·
JS-under-a-DOM-stub + `node --check` for anything in `web_preview.py` · hostile-config probe
(`XDG_CONFIG_HOME`) for anything touching config resolution.

Gotchas that cost real time: `grep` here is **ugrep** — `grep -q X <(cmd)` silently never
matches, pipe instead. The security hook blocks shell access to `.env`; use a *script file*
that reads it and passes `env=` to `subprocess.run` (inline python is blocked). Free-tier
OpenRouter drops a page occasionally — budget for it when measuring.

## HARD GUARDRAILS — you may not decide these

- Never make the repo public.
- Never add a second retry layer. The httpx provider transport is the sole retry owner.
- Never spend money.
- Do not activate `sdd-driver`.

## REPORTING

Report in batches, not per step. Tell me what shipped, what each lane found, what you
decided and why, and what's left. Push to the private remote when the suite is green.
