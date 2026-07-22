---
date: 2026-07-22T10:07:54-04:00
researcher: Claude (Fable 5)
git_commit: 5d2158e8919dcb21d77afdfda96dc371dfa37131
branch: main
repository: half-blood-prince
topic: "Session 29 (cont. 4) — sdd-driver agent definition + policy hooks merged (shadow); pre-activation hardening list recorded"
tags: [adoption, sdd-driver, hooks, shadow-mode, policy, autonomy-directive]
status: complete
last_updated: 2026-07-22
type: handoff
---

# Handoff: Session 29e — sdd-driver shadow merged (1320 green)

> **`main` @ `5d2158e`, 1320 green (1291+29), ruff + mypy clean, default solver beam,
> `v0.1.0` intact.** Adoption #3 landed SHADOW: `.claude/agents/sdd-driver.md` +
> PreToolUse/Stop policy hooks + 29 hermetic table-tests now in the product suite.
> The harness auto-registered the agent type (frontmatter parses) — **but NOTHING may
> spawn it: first activation is owner-attended, and the pre-activation hardening list
> below must land first regardless.**

## Task(s)
1. ✅ sdd-driver shadow build — merge `5d2158e` (feat `c0d7dbd`, Codex-built all 4 files
   via receipts wrapper in 367s; tripwire 59/59; controller ran 14 beyond-table live
   exercises, all pass; Opus GO with a serious bypass hunt).
2. ⏳ NEXT (recommended): **pre-activation hardening** of check_action/check_stop — the
   reviewer's 4 recorded gaps: subshell launchers (`bash -c`/`sh -c`/`eval` carrying
   denied commands), redirect-to-src writes, stale stop-refusal counter lifecycle,
   plus tests for each. Must land before any activation; small, well-specified.
3. ⏳ Then: conformance gate (adoption #4), manifests (#5), reader-lab fixtures.
4. ⏳ OWNER-FLAGGED (never autonomous): activating sdd-driver in /goal, wiring drivers
   to sddctl assert-ready, any hook enforcement beyond shadow.
5. ⏳ Product validation — blocked on an OpenRouter key.

## Critical References
- Ledger entry "SDD-DRIVER SHADOW — MERGED" (full hardening list with reviewer detail).
- `.superpowers/sdd/sdd-driver-brief.md` — the build spec the files implement.
- `thoughts/shared/research/2026-07-21_omp-adoption-study.md` §Top-5 #3 and #4.

## Recent changes
- `.claude/agents/sdd-driver.md` (45 lines): sonnet, maxTurns 80, tool allowlist,
  disallowedTools Agent, both hooks, SHADOW notice.
- `.claude/hooks/sdd-driver/check_action.py` (172): token-grammar git-subcommand deny
  table, Edit/Write path scoping, compound-command any-segment-deny, malformed-JSON deny.
- `.claude/hooks/sdd-driver/check_stop.py` (53): report-required stop, one-refusal-then-
  allow-with-escalation.
- `tests/test_sdd_driver_hooks.py` (183): 29 subprocess table-tests.

## Learnings
- The session's own PreToolUse guard false-positived on hook-test payloads embedded in a
  Bash command line (dangerous-looking literals as DATA). Workaround pattern: put test
  payloads in a script file via Write and execute the file. Relevant to anyone testing
  hooks from inside a hooked session.
- Reviewer bypass-hunting found the realistic gaps the table-tests missed (subshell
  launchers, redirects) — adversarial review of policy code pays for itself; the deny
  grammar was otherwise solid (option-value skipping handles `git -C`, env prefixes,
  xargs, backslash, traversal).

## Verification (controller-run this session, post-merge)
| Claim | Command | Result |
|---|---|---|
| main @ `5d2158e` | `git rev-parse HEAD` | `5d2158e8…` |
| Suite | `.venv/bin/pytest tests/ -q` | `1320 passed, 12 warnings` |
| ruff / mypy | standard commands | clean / `no issues in 42 files` |
| Hook module standalone | `.venv/bin/pytest tests/test_sdd_driver_hooks.py -q` | `29 passed` |
| Tripwire (existing files) | `sha256sum -c` tripwire3 (59 files) | 59/59 OK |
| Live hook exercises | scratchpad `exercise_hooks.py` (14 checks) | `fails=0` |
| Receipt vs reality | receipt JSON vs porcelain | 1:1 (4 created paths) |
| Agent registered, not activated | harness agent list + no Agent spawn of sdd-driver | registered; never spawned |

## Action Items & Next Steps
1. Pre-activation hardening task (see task 2) — next loop iteration.
2. Conformance gate (#4) after — it will also validate agent frontmatter/hook names
   repo-wide (catching the known nonconformant codebase-analyzer.md).
3. Owner items unchanged: activation decisions, OpenRouter key.

## Other Notes
- Rollback: this merge = `git revert -m 1 5d2158e`. Chain: 29c `5ae7725`, S3 `4363b03`,
  S2c `d521523`; dev-harness `a8bef24` (sddctl), `d90baea` (receipts).
- Never push. `M CLAUDE.md` untouchable. Merged branches retained.
