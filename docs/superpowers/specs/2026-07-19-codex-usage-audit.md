# Codex Usage Audit — 2026-07-19

**Scope:** How this project uses the OpenAI Codex CLI vs official/recommended patterns.
**Auditor:** Sonnet subagent. Evidence: read all four mechanisms in full; ran `codex --version`; fetched
official plugin repo + OpenAI non-interactive docs.

---

## 1. Inventory of Mechanisms

This project has **four distinct Codex invocation paths**:

| Mechanism | File | Sandbox | Model | Delete guard | WSL2-safe? |
|---|---|---|---|---|---|
| **codex-safe.sh** | `~/dev-harness/scripts/codex-safe.sh` | `workspace-write` (Landlock) | configurable, default `gpt-5.6-sol` | YES — git sweep + restore (exit 3) | **Uncertain** (no `--skip-git-repo-check`; bubblewrap may be blocked) |
| **codex-build** | `~/.local/bin/codex-build` | `--dangerously-bypass-approvals-and-sandbox` | configurable | NO | YES (explicitly designed for WSL2 AppArmor) |
| **/goal SDD skill** | `.claude/skills/goal/SKILL.md` | `workspace-write` (raw CLI) | `gpt-5.6-sol` hardcoded | NO (relies on tripwire instead) | Uncertain |
| **official plugin** | `codex@openai-codex` v1.0.6 | Let Codex choose (companion script) | plugin default / config.toml | NO | YES (companion uses `app-server` path) |

### 1a. `codex-safe.sh` — purpose and mechanism

`~/dev-harness/scripts/codex-safe.sh` wraps `codex exec` with two hard guarantees not present in the raw CLI:

1. **OS-level write containment.** Passes `--sandbox workspace-write` to `codex exec`. On Linux this uses Landlock/seccomp to prevent writes to any path outside the given `--workspace`. Opt-in `--net` flag available; does not widen file access.

2. **Hard deletion prevention.** Two layers:
   - A `NON-NEGOTIABLE OPERATING RULES` preamble prepended to every brief (soft, model-visible).
   - A post-run `git status --porcelain | grep '^( ?D|D |R )'` sweep; any detected deletions or renames cause the script to `git checkout` them back and return exit code 3. The rest of Codex's edits are preserved; only removals are reverted.

**Known gap:** does not pass `--skip-git-repo-check`, so it cannot run against non-git directories (confirmed: the test with `--workspace /tmp` failed immediately with "Not inside a trusted directory").

**WSL2 concern:** The `workspace-write` sandbox requires bubblewrap, which WSL2's AppArmor blocks. If bubblewrap is blocked on this machine, `codex-safe.sh` silently falls back to whatever Codex does without a sandbox. The `codex-build` wrapper exists precisely because this was "learned the hard way" — but the goal SDD skill still tries `workspace-write` directly.

### 1b. `codex-build` — purpose and mechanism

`~/.local/bin/codex-build` is a WSL2-specific alternative that explicitly opts out of sandboxing:

```
codex exec --dangerously-bypass-approvals-and-sandbox -C <dir> --skip-git-repo-check --color never ...
```

Adds stdin redirect (`< /dev/null`) to work around the codex#20919 exec-hangs-on-stdin bug, a 480s timeout wrapper, and configurable `EFFORT` / `MODEL` env vars. Invoked by the global `/codex-build` Claude Code command, which then runs a parallel Fable + Opus adversarial review of whatever Codex produced.

No sandbox, no deletion guard. Safety relies entirely on trusting the brief text and doing human review after.

### 1c. `/goal` SDD loop

The bespoke `SKILL.md` drives the project's nightly spec-driven-development loop. Codex is dispatched in step 4 via raw CLI:

```
codex exec --sandbox workspace-write -C <repo> -m gpt-5.6-sol \
    -c model_reasoning_effort=high -o <report.md> < <brief.md>
```

Differences from `codex-safe.sh`:
- **No NO-DELETE preamble.** Safety against deletion relies on the pre-run `sha256sum` tripwire (if Codex touches test files the loop stops, but tracked-file deletion is not caught).
- **Hardcoded model `gpt-5.6-sol` and effort `high`.** These are fragile constants; effort `high` raises cost and triggers the ~300s stream-idle timeout on long sessions (the reason `codex-build` defaults to `medium`).
- **No git sweep.** Deleted files are not restored.

The skill adds value that the plugin cannot replicate: controller-authored failing tests, sha256sum tripwire (Codex cannot touch tests), 2-attempt fix retry, auto-merge to local main, and overnight safety caps.

### 1d. Official Codex plugin (`codex@openai-codex` v1.0.6)

Installed at `~/.claude/plugins/cache/openai-codex/codex/1.0.6/`. Provides:

- **`/codex:setup`** — verifies Codex auth + install; can auto-install via npm.
- **`/codex:review`** — runs a structured Codex code review against local git state (working-tree or branch diff). Output is a JSON-schema-validated structured result rendered as findings; verbatim to user.
- **`/codex:adversarial-review`** — same as review but with adversarial framing: questions design choices and assumptions, not just defects.
- **`/codex:rescue`** — delegates arbitrary investigation, fix, or follow-up tasks to a `codex:codex-rescue` subagent; that subagent calls the companion `task` command once and returns stdout verbatim. Supports `--background`, `--wait`, `--resume`, `--fresh`, `--model`, `--effort`.
- **`/codex:status`, `/codex:result`, `/codex:cancel`** — background job management.
- **`/codex:transfer`** — imports the current Claude Code conversation into a Codex session.

Three internal skills (`codex-cli-runtime`, `codex-result-handling`, `gpt-5-4-prompting`) are non-user-invocable; they govern how the `codex:codex-rescue` subagent composes prompts and presents results.

The companion uses an `app-server` invocation path for review commands (structured, richer than raw `exec`). For task commands, it invokes `codex exec` through the same node.js runtime.

---

## 2. Official Recommendations (web research)

Sources: [openai/codex-plugin-cc](https://github.com/openai/codex-plugin-cc), [OpenAI non-interactive docs](https://learn.chatgpt.com/docs/non-interactive-mode), [SmartScope Codex audit](https://smartscope.blog/en/blog/codex-plugin-cc-openai-claude-code-2026/), [OpenAI sandbox docs](https://developers.openai.com/codex/concepts/sandboxing).

**Primary recommended pattern (Claude Code + Codex):**
- Use the official plugin as the primary integration point. `/codex:review` before shipping, `/codex:rescue` for delegation, `/codex:adversarial-review` for design challenges.
- Do NOT hardcode `--model` or `--effort` in plugin invocations; let Codex choose defaults or use `~/.codex/config.toml` for project-level overrides.
- For write tasks, `--sandbox workspace-write` is the recommended explicit setting. `danger-full-access` only in containerized CI.
- Loops between Claude Code and Codex should run under human supervision only (usage concern).

**Non-interactive `codex exec` pattern (for automation):**
- Pass the task as a single argument; brief via stdin or file; capture output via `-o <file>` or stdout.
- `--ephemeral` prevents session files accumulating on disk.
- `--ignore-user-config` for reproducible CI runs.
- `< /dev/null` required on some platforms to prevent exec from blocking on stdin.

---

## 3. Comparison: Is Our Custom Tooling Redundant?

### `codex-safe.sh` vs `/codex:rescue`

**`codex-safe.sh` adds real value the plugin lacks:**
- Hard deletion prevention (git sweep + restore + exit 3) — the plugin has no equivalent.
- Audit-friendly exit code 3 signals exactly when Codex touched tracked files it shouldn't have.
- Brief-as-file prevents metacharacter injection in shell-expanded prompts.

**`/codex:rescue` adds value `codex-safe.sh` lacks:**
- Background job management (`/codex:status`, `/codex:result`) with persistent job IDs.
- Session continuity (`--resume` resumes the same Codex thread).
- App-server path for richer context and structured output.
- Does not require a git repo in the workspace.
- Model aliasing (`spark` → `gpt-5.3-codex-spark`).

**Verdict:** NOT redundant. The two tools serve different purposes. `codex-safe.sh` is the right tool for the SDD loop where deletion safety is a hard invariant. `/codex:rescue` is the right tool for ad-hoc investigation and one-off delegation where background execution and session continuity matter more.

### `/codex-build` vs `/codex:rescue`

The global `/codex-build` command is a WSL2-compatible build-then-review workflow: Codex builds, then Fable + Opus review in parallel. `/codex:rescue` focuses on delegation without a parallel review step. These are complementary; neither is redundant. However, `/codex-build` uses `--dangerously-bypass-approvals-and-sandbox`, which means zero OS-level confinement — this is a deliberate WSL2 workaround but should be documented as such at the call site.

### `/goal` SDD skill vs official plugin

Not redundant. The SDD loop encodes project methodology: brief → failing tests → Codex → tripwire → gate → Opus review → merge. The plugin has no awareness of this loop and cannot replace it.

---

## 4. Problems Found

### P1 (LOW — VERIFIED WORKING): `/goal` SDD skill sandbox concern is resolved

The skill dispatches `codex exec --sandbox workspace-write`. The `codex-build` wrapper comment documents "WSL2 AppArmor blocks bubblewrap" — but `codex doctor` (run 2026-07-19) confirms this machine's sandbox is **fully operational**:

```
✓ sandbox  restricted fs + restricted network · approval OnRequest
    filesystem sandbox   restricted
    network sandbox      restricted
    linux helper         ~/.codex/tmp/arg0/codex-…/codex-linux-sandbox
```

Codex on this machine uses a `codex-linux-sandbox` helper (Landlock/seccomp), **not** bubblewrap. The `codex-build` comment refers to a past setup where the bubblewrap-based sandbox was used; the current Codex version (0.144.5) uses a different mechanism that works on WSL2. The SDD loop's `workspace-write` sandbox is enforced correctly.

The goal skill still lacks a post-run deletion sweep (see P3), but the sandbox itself is not a concern.

### P2 (MEDIUM): Model `gpt-5.6-sol` hardcoded in two places

Both the `/goal` skill and `codex-safe.sh`'s default hardcode `gpt-5.6-sol`. If OpenAI renames or retires this model, the SDD loop silently fails. The official plugin recommends project-level `~/.codex/config.toml` for model selection. Consider moving the model name to a single config source or documenting it as the one intentional constant.

### P3 (MEDIUM): `/goal` SDD skill has no deletion guard

The tripwire catches test-file tampering but not deletion of other tracked files. If Codex deletes a source file during a build run, the tripwire won't catch it (test checksums are fine) and the gate may still go green. Add a deletion check to the gate step (same pattern as `codex-safe.sh`'s git porcelain sweep).

### P4 (LOW): `codex-safe.sh` missing `--skip-git-repo-check`

Cannot be used with non-git workspaces (e.g., `/tmp` scratch dirs). Add `--skip-git-repo-check` to the `codex exec` invocation in `codex-safe.sh`, since the workspace-write sandbox itself already provides containment.

### P5 (LOW): Effort hardcoded to `high` in goal SDD skill

`model_reasoning_effort=high` is the right default for implementation tasks, but the brief says effort `high` can trigger the ~300s stream-idle timeout. The `codex-build` wrapper defaults to `medium` for this reason. Consider using `high` as a named constant in the brief template and allowing per-task override via the brief's front matter.

---

## 5. Codex Web Access Test

**Result: Web access CONFIRMED working with `--net`.**

First attempt (workspace `/tmp`) failed immediately: `Not inside a trusted directory and --skip-git-repo-check was not specified.` That is P4 (missing flag), not a network signal.

Second attempt with the correct workspace (`--workspace /mnt/c/.../half-blood-prince --net`):

```
sandbox: workspace-write [workdir, /tmp, $TMPDIR] (network access enabled)
web search: https://github.com/openai/codex
[returned content from the README]
tokens used: 20,337
```

Codex successfully fetched the GitHub page and returned content. **Conclusion:** With `--net` passed, Codex has working web/search access in this setup. Without `--net`, network is sandboxed off (confirmed by `codex doctor`'s `network sandbox: restricted`).

---

## 6. Recommended Standard

### When to use what

| Scenario | Recommended tool | Reason |
|---|---|---|
| SDD nightly loop (brief → build → gate → merge) | `/goal` skill + `codex-safe.sh` | Unique loop logic; needs deletion guard |
| Ad-hoc task delegation (investigation, one-off fix) | `/codex:rescue` | Background job management, session continuity |
| Code review before shipping | `/codex:review` or `/codex:adversarial-review` | Structured output, built-in review schema |
| Creative/throwaway build (HTML, scripts, PoC) | `/codex-build` (WSL2-safe, Fable+Opus review) | Known-working WSL2 invocation |
| Checking Codex auth / install | `/codex:setup` | Only this path installs Codex automatically |

### Exact recommended invocations

**SDD loop (inside `/goal`):**
```bash
codex exec --sandbox workspace-write -C <repo> -m gpt-5.6-sol \
    -c model_reasoning_effort=high -o <report.md> \
    < <brief.md>
# + sha256sum tripwire + deletion sweep
```
Add the deletion sweep from `codex-safe.sh` after each Codex run:
```bash
git -C "$WORKSPACE" status --porcelain | grep -E '^( ?D|D |R )' && exit 1 || true
```

**Ad-hoc task:**
```
/codex:rescue [--background] [--model gpt-5.6-sol] <task description>
```

**Review:**
```
/codex:review [--background] [--base main]
/codex:adversarial-review [--background]
```

**WSL2 build:**
```
/codex-build <what to build>
```

### What to change

1. **Add `--skip-git-repo-check` to `codex-safe.sh`** so it can test non-git workspaces and the web-access test can be re-run.
2. **Add a deletion sweep to the `/goal` SDD skill** (step 5.5, after the tripwire) using the same git porcelain pattern.
3. **Verify bubblewrap availability** on this WSL2 machine (`bubblewrap --version` or `codex doctor`) and document whether `workspace-write` is actually enforced. If not, switch the SDD loop to use `codex-build`.
4. **Do not add a project-level `codex.toml`** yet — the model-name hardcode is intentional for the SDD loop's reproducibility.

---

## 7. Proposed Persistence

### Memory file: `codex-standard-invocations.md`

```markdown
---
name: codex-standard-invocations
description: Which Codex invocation path to use for each scenario in half-blood-prince (SDD loop vs ad-hoc vs review vs build)
metadata:
  type: project
---

Standard Codex invocation map for this project (established 2026-07-19 audit):

- **SDD loop** (`/goal`): raw `codex exec --sandbox workspace-write` + sha256sum tripwire + deletion sweep. Model `gpt-5.6-sol`, effort `high`. NO secondary retry layer (SDK owns retries per arch §4.6).
- **Ad-hoc tasks** (investigation, one-off fix, follow-up): `/codex:rescue` (official plugin). Background when long; foreground otherwise. No hardcoded model or effort.
- **Code review**: `/codex:review` or `/codex:adversarial-review`. Always verbatim output; never auto-apply fixes.
- **WSL2 creative builds**: `/codex-build` (uses `--dangerously-bypass-approvals-and-sandbox`; safe on WSL2 where bubblewrap is blocked). Followed by parallel Fable+Opus review.
- **Auth/install check**: `/codex:setup`.

Open action: verify `bubblewrap --version` on this WSL2 machine; if absent, SDD loop sandbox is not enforced and should switch to `codex-build` path.

**Why:** See `docs/superpowers/specs/2026-07-19-codex-usage-audit.md` for full analysis.
```

### CLAUDE.md addition (optional, append to ## COMMANDS section)

```markdown
## CODEX INVOCATION STANDARD

| Use case | Command |
|---|---|
| SDD loop build step | `codex exec --sandbox workspace-write -C <repo> -m gpt-5.6-sol -c model_reasoning_effort=high -o <out> < <brief>` + git deletion sweep |
| Ad-hoc task/fix | `/codex:rescue [--background] <description>` |
| Code review | `/codex:review` or `/codex:adversarial-review` |
| WSL2 throwaway build | `/codex-build <what to build>` |

See `docs/superpowers/specs/2026-07-19-codex-usage-audit.md` for full rationale.
```

---

## Sources

- [openai/codex-plugin-cc (GitHub)](https://github.com/openai/codex-plugin-cc)
- [OpenAI Non-interactive mode docs](https://learn.chatgpt.com/docs/non-interactive-mode)
- [Introducing Codex Plugin for Claude Code (OpenAI Community)](https://community.openai.com/t/introducing-codex-plugin-for-claude-code/1378186)
- [SmartScope: codex-plugin-cc analysis](https://smartscope.blog/en/blog/codex-plugin-cc-openai-claude-code-2026/)
- [OpenAI sandbox docs](https://developers.openai.com/codex/concepts/sandboxing)
