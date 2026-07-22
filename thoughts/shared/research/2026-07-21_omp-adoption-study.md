# oh-my-pi → Claude Code + Codex harness: adoption study

**Date:** 2026-07-21  
**oh-my-pi source pin:** [`7b141199d524b859c357fc89654f10b62b9f3df1`](https://github.com/can1357/oh-my-pi/tree/7b141199d524b859c357fc89654f10b62b9f3df1)  
**Status:** advisory only; no tooling changes are authorized by this report.

## Abstract

The useful part of oh-my-pi for this harness is not its TUI, provider layer, or edit syntax. It is its treatment of orchestration as a state machine with durable messages, capability-reduced agents, host-validated outputs, and explicit replay boundaries.

The highest-value adoption is therefore:

1. make rulings and interrupts durable, versioned, and acknowledged instead of relying on `SendMessage` delivery;
2. make the wrapper, not the model, produce the authoritative run receipt, and never auto-retry after a run has observable filesystem side effects;
3. replace the generic Sonnet driver with a policy-bearing `sdd-driver` definition plus scoped hooks;
4. add a small conformance/divergence gate for agent definitions, harness docs, and live invocation behavior;
5. do **not** put prewalk into the production SDD loop yet. The exact mechanism requires one transcript and an in-session model switch, while Claude subagents and Codex runs are isolated contexts. Run a disposable Codex-resume feasibility experiment first.

This ordering is driven by actual failures, not theoretical elegance: the Session-28 stale-ruling runaway (`progress.md:2442-2455`), false “Codex wrote nothing” testimony after a landed write (`progress.md:1851-1902`), driver idle/stall behavior (`progress.md:1593-1597`, `2156-2158`), broken test custody (`progress.md:2428-2431`), and the review race caused by treating a commit as completion (`progress.md:1831-1837`). The rollout-gate practice at `progress.md:2465-2480` is the model for introducing every change below: measure it under supervision, keep the old path available, and do not flip the default merely because the mechanism works in a unit test.

## Decision criteria

The matrix and proposals use five tests:

- **Does it prevent a failure already seen here?** Preference goes to mechanisms that close a named incident.
- **Is it enforceable at a host boundary?** A prompt reminder is weaker than a wrapper, hook, schema, or independently computed digest.
- **Does it preserve role custody?** The controller owns tests and intent; Codex owns production implementation; Opus reviews; only the controller merges.
- **Does it work across two separate runtimes?** oh-my-pi can change models inside one `AgentSession`; Claude Code and `codex exec` normally cannot.
- **Can it be rolled out behind an explicit gate?** No default flip before supervised evidence.

Source is authoritative at the pinned commit. The two prior local studies are assumed rather than repeated. Important direct source seams used below include oh-my-pi's [prewalk turn-boundary state machine](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/session/agent-session.ts#L2396-L2485), [late-queue polling](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/agent/src/agent-loop.ts#L812-L1179), [settle-time queue drain](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/session/agent-session.ts#L2232-L2279), [structured child execution](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/task/executor.ts#L1654-L1821), and [retry refusal after observable output](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/docs/non-compaction-retry-policy.md#L29-L42).

## Adoption matrix

Effort is implementation plus tests: **S** ≤ about two focused days, **M** several days/a supervised rollout, **L** a multi-component project. Risk is the risk of adopting the mechanism incorrectly, not the risk it is meant to reduce.

| Mechanism | What it is, in one line | Concrete value to this loop | Where it lands | Verdict | Effort | Risk |
|---|---|---|---|---|---:|---|
| **Prewalk** | A guide explores, creates a bounded todo, lands the first successful edit, then one-way switches the same transcript to a cheaper executor. | Would reduce re-reading and “fairytale” briefs only if Codex inherits the real trajectory. It does not fix Session 28 if the ruling itself is stale. | Research spike in `codex-safe.sh` tests; no production `/goal` change yet. | **Adapt experimentally; reject for production now.** Claude and Codex lack one shared live context; `/codex:transfer` is outside the proven delete-guarded SDD path; a prose trajectory capsule is still a summary. | L | High: custody blur, hidden-instruction leakage, resume sandbox uncertainty. |
| **Todo gate + first-landed-edit trigger** | Switch only after a bounded execution checklist exists and a mutating tool result succeeded. | Gives a precise handoff predicate instead of “brief exists.” Avoids oh-my-pi's pinned `isError` bug. | Future prewalk experiment; `sddctl assert-ready`; wrapper event/working-tree verification. | **Adapt.** Our gate is: bounded todo + no open ruling + failing-test proof + epoch acknowledgement. “Landed” means non-error write event **and** allowed-path digest changed. | M | Medium. False positives are dangerous; require two independent signals. |
| **Hashline / stale-anchor recovery** | Reads return compact snapshot tags; edits cite anchors and recover only when unchanged context maps unambiguously. | Could reject stale briefs/source assumptions and wrong-branch dispatches. Whole edit-grammar replacement would not address the dominant failures and would fight native Claude/Codex editing. | Brief manifest generated by a new `scripts/sddctl.py`; preflight in `codex-safe.sh`. | **Adapt at file/brief level; skip wholesale edit syntax.** Pin source-input digests, branch, HEAD, brief digest, testsums digest, and ruling epoch. On mismatch, re-read and regenerate; do not auto-remap production patches yet. | S–M | Low–medium. Excessively broad manifests cause false stops. |
| **Agent definitions as policy** | Agent frontmatter constructs a reduced model/tool/turn/hook surface rather than merely asking for restraint. | Stops the driver from stash/reset/merge improvisation seen in Session 28; makes the missing-report and background-idle paths enforceable. Existing `.claude/agents/codebase-analyzer.md` does not even have valid native frontmatter (`codebase-analyzer.md:1-6`). | New `.claude/agents/sdd-driver.md`; scoped hooks; `/goal` role text. | **Adapt now.** Native Claude subagents already support tool allowlists, `maxTurns`, skills, and hooks. Current Claude docs say subagents cannot spawn subagents, so the parent/orchestrator must own the Opus review. | M | Medium. Parent `bypassPermissions` can override permission mode; hooks must carry hard policy. |
| **Spawn allowlists / recursion-depth removal** | Only named children may be spawned; delegation disappears at max depth. | Prevents accidental reviewer/fixer fan-out and expensive recursive orchestration. | Driver frontmatter and parent `/goal` prompt. | **Adopt the outcome, not custom machinery.** Omit `Agent` from the driver entirely; let the parent spawn exactly one Opus review. Native Claude subagents already cannot recursively spawn. | S | Low. |
| **Per-agent request budgets + forced final yield** | A soft request budget triggers one forced structured yield before a hard abort. | Bounds wandering and prevents “idle with no report”; complements, but does not replace, the two-fix cap. oh-my-pi explicitly tests partial-yield recovery rather than output loss. | `maxTurns` in driver frontmatter; `SubagentStop` validator; driver schema. | **Adapt.** Use a phase budget and one report-only grace turn; never translate budget exhaustion into permission to merge partial work. | S–M | Medium. A budget can truncate legitimate work; status must become `partial`/`blocked`. |
| **Plan-mode capability reduction** | Planning children receive only read/search tools and no spawns or prewalk. | Protects brief-vs-plan work from accidental source mutation and makes “advisor” genuinely read-only. | Separate `.claude/agents/sdd-planner.md` or `permissionMode: plan`; Opus reviewer definition. | **Adopt as-is in concept.** Use native read-only tools/plan mode; do not rely on prose. | S | Low. Parent permission mode precedence needs a hook test. |
| **Schema-validated yields** | A required tool validates the child's final object and retries missing/invalid yields before completion. | Directly addresses reports refuted by the tree (`progress.md:1883-1888`) and reports trusted only after manual verification (`1593-1597`). | Codex `--output-schema`; model report schema; host receipt; Claude `SubagentStop` hook. | **Adopt, with a trust split.** Schema validates shape only. Host-generated hashes, diffs, exit codes, and gate outputs remain authoritative. | M | Low. Main danger is mistaking schema-valid claims for facts. |
| **Append-only JSONL session tree** | Durable entries retain all branches while the active leaf selects current context. | A versioned ruling/event history would have shown that the driver had not acknowledged the retraction before dispatching four fixes. It also separates audit history from the human summary in `progress.md`. | `.superpowers/sdd/events.jsonl`; `scripts/sddctl.py`; `progress.md` as a projection. | **Adapt to a linear, hash-chained event log.** Branch-tree reconstruction is unnecessary for a serial merge loop. | M | Medium. Split-brain risk if both JSONL and `progress.md` are writable authorities; declare JSONL authoritative for control state only. |
| **Compaction changes context, not history** | Summaries replace old context for the model while the original event history remains intact. | Lets overnight orientation use a compact current-state projection without losing incident/ruling evidence. | `sddctl summary`; generated task-state block injected into driver prompt. | **Adapt later.** Deterministic projection first; no LLM-written compaction in the control path. | M | Medium–high if a summary drops a live ruling. |
| **Steering and follow-up queues** | Steering interrupts at a tool boundary; follow-ups wait; both are re-polled at yield and drained again when the session settles. | Exact match for `SendMessage`/idle pain and for stale rulings delivered to everyone except the active driver. The pinned tests describe visible-but-never-delivered messages and settle-boundary races. | Append-only control inbox in the SDD event log; driver safe-point poll; Monitor; `SubagentStop` hook. | **Adapt now.** `SendMessage` becomes a wake-up optimization, never the source of truth. Require acknowledgement of the latest epoch before dispatch/commit. | M | Medium. Must prevent duplicate delivery and stale acknowledgements. |
| **Memory-generated playbooks + lease/heartbeat** | Background extraction/consolidation emits advisory memory/playbooks under a single-owner renewable lease. | Could turn repeated lessons—controller-test defects, no background Codex, artifact discipline—into candidate procedures without simultaneous writers. | Later `sddctl consolidate`; memory candidate directory; lock/lease record. | **Adapt narrowly, later.** Generate review candidates, never auto-activate skills or delete stale playbooks. Current `/goal` already warns that old memory can revive retired policy (`SKILL.md:48-53`). | M–L | High: stale generated procedure can become an autonomous bad ruling. |
| **Doc-vs-source divergence ledger** | Each review records where prose and implementation disagree, with source winning at the pin. | Already needed locally: the 2026-07-19 audit says `/goal` uses raw Codex and lacks a deletion guard (`codex-usage-audit.md:17,48-58`), while current `/goal` uses `codex-safe.sh` (`SKILL.md:16-17,76-85`). | Review template; `scripts/check-harness-contracts.py`; CI/local gate. | **Adopt as-is.** Keep it small, pinned, and actionable. | S | Low. |
| **Side-effect-aware retry boundary** | Automatic retry is allowed only before any observable output or mutation; after that, reconcile instead of replaying. | Directly prevents the P3-T1/P3-T4 “hung after writing → redispatch” failure class and limits damage from stale missions. | `codex-safe.sh` receipt/trap; `/goal` retry text; event log. | **Adopt as-is as a principle.** A changed allowed file is observable output even if Codex exits nonzero or times out. | S–M | Low. Conservative stops cost time but preserve correctness. |
| **No-op/runaway guard** | Repeated identical no-op mutations escalate from a hint to a hard error after a small bound. | Generalizes the existing two-fix cap to repeated briefs/diffs/rulings and would stop identical redispatches earlier. oh-my-pi's guard was added after 182 repeated no-ops. | `sddctl dispatch-check`; compare brief digest + ruling epoch + working-tree fingerprint. | **Adapt.** Refuse a third identical dispatch; require a new epoch, changed brief, or explicit owner override. | S | Low. Hash equivalence must include relevant state, not just prompt bytes. |
| **Model-role indirection** | Stable roles (`builder`, `driver`, `reviewer`) resolve to pinned concrete models in one config source. | Removes duplicated model literals while retaining reproducibility. The audit already flags hardcoding in multiple places. | Versioned `.superpowers/sdd/harness-config.json`; `/goal` and wrapper read/echo resolved values. | **Adapt.** Keep exact IDs pinned in the role map; do not silently float to “latest.” | S | Low. A bad resolver fallback must fail closed. |
| **Shared/exclusive tool scheduler** | Reads may overlap; mutators form barriers before and after themselves. | Elegant inside one agent runtime, but this loop deliberately serializes branch mutation, tests, review, and merge. Parallel review already caused a race (`progress.md:1831-1837`). | Nowhere. | **Skip.** Keep mutation and review sequential; use parallelism only for independent read-only scouting. | — | Adoption would raise race risk. |

## Top 5 proposals

### 1. Durable SDD control journal with ruling epochs and acknowledgements

**Decision: adopt first.** This is the direct fix for Session 28.

Create a small append-only control log, not a general conversation archive:

- `.superpowers/sdd/events.jsonl` — control/audit events only;
- `scripts/sddctl.py` — the only supported appender and projector;
- `.superpowers/sdd/current-state.json` — optional generated cache, never authoritative;
- keep `.superpowers/sdd/progress.md` as the human narrative, not the machine control plane.

Minimum event envelope:

```json
{
  "seq": 184,
  "time": "2026-07-21T01:45:00-04:00",
  "task_id": "p3-s2a",
  "actor": "controller",
  "type": "ruling_issued",
  "epoch": 7,
  "supersedes": 6,
  "payload": {
    "subject": "soft_cost_formula",
    "decision": "sum_accepted_mean_retracted",
    "requires_ack": ["driver"]
  },
  "prev_hash": "...",
  "hash": "..."
}
```

Required state-machine rules:

1. `sddctl issue-ruling` increments the task epoch and appends; it never rewrites history.
2. The controller sends `SendMessage` after the append, but delivery is advisory. The durable event is authoritative.
3. The driver polls at fixed safe points: before authoring a fix brief, before every Codex dispatch, before commit, and before its final report.
4. `sddctl ack --task T --actor driver --epoch E` is required before dispatch or commit.
5. `sddctl assert-ready` fails if there is an unacknowledged ruling, pending question, mismatched task/branch, or superseded epoch.
6. The Monitor watches for `requires_ack` older than a short threshold. It wakes the driver; if the driver is idle/unreachable, it reports to the controller rather than executing the old mission itself.
7. A `SubagentStop` hook blocks a driver from stopping while it owns an unacknowledged event or lacks a final schema-valid report. One report-only grace turn is allowed; after that, fail closed to the parent.

This is the two-runtime analogue of oh-my-pi's queue discipline: one queue owner, insertion order, a late poll at the yield boundary, and a settle-time drain. Its regression tests should copy the *failure shapes*, not its TypeScript implementation: ruling lands just after the driver's last poll; ruling lands while Codex is in flight; driver becomes idle before acknowledgement; duplicate wake-up; superseded ruling acknowledged late; user abort suppresses autonomous follow-up.

Validation plan:

- Unit-test JSONL append locking, monotonic sequence/epoch, hash chain, idempotent acknowledgement, and projection from a truncated last line.
- Replay the exact Session-28 sequence: issue mean → driver acks → retract mean/accept sum → withhold ack → assert that four dispatch attempts all fail before process launch.
- Run five attended tasks in “shadow” mode where assertions only log, then five in enforcing mode.
- Success gate: zero stale-epoch dispatches, every ruling acknowledged or explicitly abandoned, no duplicated wake-driven turn, and `progress.md` projection matches the event log.

### 2. Host-generated Codex run receipts + strict model report + side-effect-aware retry

**Decision: adopt second.** This closes the false-testimony and hung-after-write classes.

Change the future wrapper contract from “Codex writes a Markdown report” to two outputs with different trust levels:

- `<task>.codex-report.json` — model-authored, validated with the local CLI's `codex exec --output-schema` support;
- `<task>.run-receipt.json` — wrapper-authored evidence.

Suggested model report schema:

```json
{
  "status": "complete | partial | blocked | escalate",
  "task_id": "p3-s2c",
  "ruling_epoch": 9,
  "summary": "string",
  "claimed_files": [{"path": "string", "operation": "created | modified"}],
  "escalations": [{"kind": "controller_test_defect | spec_conflict | tool_failure | other", "evidence": "string"}],
  "remaining_work": ["string"],
  "proposed_removals": ["string"]
}
```

The wrapper receipt—not the model—records:

```text
dispatch_id, task_id, ruling_epoch, started_at, ended_at, duration_ms,
wrapper_exit, codex_exit, timed_out, start_head, end_head, branch,
brief_sha256, manifest_sha256, pre_status_sha256, post_status_sha256,
changed_paths with pre/post digests, test_tripwire_result,
deletion_or_rename_attempt, model_report_schema_valid,
observable_side_effect, event_log_path
```

Implementation sketch for `~/dev-harness/scripts/codex-safe.sh`:

```bash
preflight_manifest_or_exit_4
snapshot_host_evidence
install_EXIT_TERM_INT_trap_that_always_sweeps_and_writes_receipt
run_timeout_inside_wrapper codex exec --json --output-schema "$SCHEMA" ...
parse_jsonl_for_session_id_and_completed_mutation_events
snapshot_post_state
observable_side_effect = changed_allowed_path || successful_mutation_event
if timed_out && observable_side_effect: exit RECONCILE_REQUIRED
if no_side_effect && transient_failure: retry_policy_may_consider_one_retry
```

Move the timeout **inside** the wrapper. Today `/goal` wraps the entire script in external `timeout` (`SKILL.md:80-82`); a hard termination can bypass the wrapper's post-run sweep and evidence write. The wrapper should own child termination and execute its trap/finalizer regardless of Codex's exit path.

The retry rule is categorical: if `observable_side_effect=true`, never replay the brief automatically. Inspect the tree, run the tripwire/gate as applicable, and either accept the landed work, issue a focused continuation under a new dispatch ID, or stop. This is oh-my-pi's replay-safety rule applied to filesystem effects: a partially emitted turn is not silently replayable.

Validation plan:

- Hermetic wrapper tests for success, schema failure, Codex nonzero before edits, timeout before edits, timeout after creating a file, interrupted rename/delete, malformed JSONL, and missing final model report.
- Reproduce the P3-T4 shape with a fake Codex that writes `geometry.py` then hangs. Expected: receipt says `timed_out=true`, `observable_side_effect=true`, and automatic redispatch is denied.
- Tamper with tests during the fake run. Expected: receipt independently reports tripwire failure even if the model says “tests untouched.”
- Roll out in shadow mode for three tasks, then make the receipt mandatory. Keep Markdown rendering as a generated human view if desired.

### 3. A real `sdd-driver` agent definition with least privilege and a stop hook

**Decision: adopt third.** The present skill describes a Sonnet role, but the actual driver is usually a generic agent governed largely by prose.

Add `.claude/agents/sdd-driver.md` with native frontmatter along these lines:

```yaml
---
name: sdd-driver
description: Builds one already-selected SDD task through tests, Codex dispatch, and gate; never reviews or merges.
model: sonnet
effort: high
maxTurns: 80
skills: [goal]
tools: Read, Grep, Glob, Edit, Write, Bash
disallowedTools: Agent
hooks:
  PreToolUse:
    - matcher: "Edit|Write|Bash"
      hooks:
        - type: command
          command: "python scripts/check-sdd-driver-action.py"
  Stop:
    - hooks:
        - type: command
          command: "python scripts/check-sdd-driver-stop.py"
---
```

The policy split should be explicit:

- **Driver may:** read; author controller-owned tests and task artifacts; run failing tests; invoke `codex-safe.sh` in the foreground; run tripwire/gate; append driver events; submit its structured report.
- **Driver may not:** edit `src/` directly; use `git stash`, `reset`, `merge`, or ref-moving commands; spawn reviewers; amend/commit while a ruling is pending; run Codex in the background.
- **Parent/orchestrator owns:** task selection, branch creation, intent/ruling changes, Opus spawn, final scope verification, commit, `--no-ff` merge, post-merge gate, and progress projection.

This intentionally narrows the current role description in `/goal`, where the Sonnet driver also merges and logs (`SKILL.md:18-21`). It follows the source-backed lesson that omitted capability is stronger than a warning. Current Claude Code documentation supports tool allowlists, `disallowedTools`, `maxTurns`, preloaded skills, and agent-scoped hooks; it also states that subagents start with isolated context and cannot spawn other subagents. See [custom subagents](https://code.claude.com/docs/en/sub-agents) and [hooks](https://code.claude.com/docs/en/hooks).

`check-sdd-driver-action.py` should parse hook JSON, not shell text heuristically where structured fields exist. For Bash, use a tight allowlist for read-only git commands, test/gate commands, checksum commands, `sddctl`, and the exact wrapper invocation. Deny `git add -f`, stash/reset/merge/checkout/commit, raw `codex exec`, and background dispatch. Because the local parent uses `bypassPermissions`, do not rely on `permissionMode` for containment; the hook is the enforcement seam.

`check-sdd-driver-stop.py` should allow stop only if the latest event is one of:

- schema-valid `driver_complete` with receipt and gate evidence;
- `driver_blocked` with a concrete blocker and no live Codex child;
- explicit controller cancellation.

On the first missing-report stop, return a blocking reason that forces a report-only turn. On a second failure, let the subagent return as blocked so the parent can take over; do not create an infinite stop-hook loop.

Validation plan:

- Table-test every allowed and denied tool/path/command, including quoted paths and command chaining.
- Confirm the hook blocks the exact Session-28 stash/reset/merge actions and `git add -f .superpowers/sdd/*` from `progress.md:1595-1597`.
- Confirm a driver that launches background Codex and tries to stop is forced to account for the live run.
- Run two attended tasks with the parent still performing manual duplicate checks, then compare policy decisions and evidence.

### 4. Harness conformance gate and standing divergence ledger

**Decision: adopt fourth.** This is small and already justified by local drift.

Add `scripts/check-harness-contracts.py` and a compact “Harness divergence” section to every `/goal` review. The script should be read-only and check:

1. every `.claude/agents/*.md` has parseable YAML frontmatter with required `name` and `description`;
2. named tools and hook event names are valid for the installed Claude Code surface;
3. `/goal` invokes `codex-safe.sh`, not raw Codex;
4. the configured builder/reviewer/driver role map has one source of truth and `/goal` echoes the resolved values;
5. the wrapper's tested flags match its help text and the installed `codex exec --help` surface;
6. documentation claims tagged `CURRENT` have a source assertion or an expiry/pin;
7. known historical documents are labeled historical and are not loaded as current instructions.

Seed the ledger with two real entries:

| Claim | Document says | Current source says | Action |
|---|---|---|---|
| `/goal` Codex path | Audit lines 17 and 48-58: raw CLI, no deletion guard | `/goal` lines 16-17 and 76-85: `codex-safe.sh`, delete guard | Mark audit section historical/superseded; source wins. |
| `codebase-analyzer` definition | Markdown headings simulate fields | Native agents require YAML `name`/`description`; file has none | Convert only after owner approval; until then flag as undiscoverable/nonconformant. |

The reviewer output should contain only divergences that can change behavior: stale command, tool, model, policy, schema, or ownership claims. Do not turn it into a documentation-style lint.

Validation plan:

- Golden tests over current files should fail on the two seeded divergences, then become passing tests when future approved fixes land.
- Mutate fixtures to simulate a renamed Codex flag, missing agent frontmatter, raw Codex invocation, and mismatched model pin.
- Run it as an advisory gate for five tasks. Promote only behavior-affecting failures to STOP-FLAG.

### 5. Prewalk: reject production adoption; run a confined same-session feasibility spike

**Decision: explicitly reject production use now.** This remains in the top five because it is the most tempting change and the easiest to adopt incorrectly.

The exact oh-my-pi mechanism depends on properties this stack does not presently have:

- one append-only transcript used by both guide and executor;
- an in-session model switch after a tool result;
- ability to scrub the hidden planning nudge from live inference context while retaining it in history;
- a turn-end hook that can inspect the actual tool result.

Claude Code subagents start with fresh isolated context rather than the parent's trajectory, and `codex exec` starts another runtime. `/codex:transfer` may import a Claude conversation, but the local audit places it in the official plugin path, not the proven sandboxed/delete-guarded SDD path (`codex-usage-audit.md:62-75`). Passing read transcripts, shell outputs, and a plan in a bigger brief is a **trajectory capsule**, not trajectory inheritance; it can help grounding but does not earn the prewalk claim.

The equivalents in the current loop are:

| oh-my-pi predicate | Safe equivalent here |
|---|---|
| Todo gate | `ruling_epoch` acknowledged; bounded todo (maximum 8); `open_questions=[]`; controller tests fail for the intended reason; testsums and brief manifest valid. |
| First landed edit | A completed Codex mutation event with non-error status **and** a host-observed digest change on an allowed production path. A tool name alone is insufficient. |
| One-way switch | Only a future `codex exec resume <session> -m <cheaper-model>` experiment; never switch back automatically. |
| Hidden-prompt scrub | No equivalent proven in current Codex CLI; this is a blocking gap, not a prompt-writing task. |
| Continuation safety net | At most one forced “reach handoff or yield blocked” continuation; then stop. Never an unbounded wake loop. |

The pinned oh-my-pi implementation's bug must be intentionally inverted: it looks only at `toolName` for todo/edit/write and does not reject `ToolResultMessage.isError`. Our trigger specification is:

```text
handoff_ready =
  todo_schema_valid
  AND todo_count in 1..8
  AND no_open_ruling
  AND mutation_event.completed
  AND mutation_event.is_error == false
  AND mutation_event.path in allowed_paths
  AND post_digest(path) != pre_digest(path)
  AND test_tripwire_clean
  AND no_delete_or_rename_attempt
```

If the owner wants evidence, build only a disposable harness test outside the production `/goal` route:

1. Extend the wrapper test fake to emit Codex `--json` events and capture a session ID.
2. Guide run: use a fixture repo, bounded todo schema, and instruction to stop after one valid edit.
3. Verify the predicate above from host evidence.
4. Resume the same Codex session with a cheaper model and ask it to finish.
5. Before any real-repo trial, prove that `resume` preserves the original cwd, `workspace-write` sandbox, allowed writable roots, output schema, and deletion sweep. The currently installed `codex exec resume --help` does not expose `-C` or `--sandbox`, so inheritance must be tested rather than assumed.
6. Compare against current one-shot Codex on at least 20 representative tasks: pass rate, reread/tool-call count, wall time, token/cost, fix redispatches, scope violations, and review blockers.

Promotion gate: statistically or operationally meaningful improvement with zero safety/custody regressions, proven hidden-instruction handling, and a wrapper-level resume contract. Until then, keep the existing SDD split and improve the brief with manifests/structured evidence, without calling it prewalk.

## Secondary implementation notes

### Brief manifest rather than hashline tool replacement

A future `.superpowers/sdd/<task>.manifest.json` should contain:

```json
{
  "task_id": "p3-s2c",
  "ruling_epoch": 9,
  "branch": "phase3-s2c",
  "base_head": "<40-hex>",
  "brief_sha256": "<64-hex>",
  "testsums_sha256": "<64-hex>",
  "allowed_outputs": ["src/halfblood/layout/page_solver.py"],
  "source_inputs": [
    {"path": "src/halfblood/layout/page_solver.py", "sha256": "<64-hex>"},
    {"path": "docs/superpowers/specs/...md", "sha256": "<64-hex>"}
  ]
}
```

`codex-safe.sh` validates it immediately before launch. A mismatch is not automatically “recovered”; it returns a distinct stale-input code and requires the driver to re-read the changed input, update tests/brief if needed, issue a new manifest, and acknowledge the current epoch. This takes hashline's core lesson—cheap model-facing coordinates plus strong host-side identity—without building a parallel editing protocol that Codex cannot natively use.

### Memory consolidation should produce candidates, not active policy

oh-my-pi's memory pipeline is careful: it is disabled by default, labels memory heuristic, schema-validates and redacts output, and uses a lease/heartbeat for the consolidation writer ([memory documentation](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/docs/memory.md#L42-L56)). The same operational discipline is worth copying, but auto-generated SDD skills are not.

If added later:

- consume only completed task events older than a cooling-off window;
- exclude live tasks/rulings;
- use a renewable lease with ownership token;
- write candidate lessons to a review queue;
- require owner approval to promote a candidate into `.claude/skills/`, an agent prompt, or a hook;
- never prune or delete old candidates automatically in this repository;
- record the source event IDs and an `expires_when` condition on every promoted lesson.

This matters because the existing `/goal` skill already contains a supersession warning against old handoffs/memories reviving the retired merge cap. Generated memory must never outrank the event log, current repository, or owner instruction.

### Preserve the successful rollout-gate pattern

The beam solver was merged default-off, measured for quality, determinism, and performance, and correctly blocked from default-on when p95 missed its budget by 26× (`progress.md:2465-2480`). Apply that same pattern to harness changes:

- add mechanism behind `enforce=false` shadow mode;
- collect incidents prevented, false stops, latency, and operator interventions;
- run attended first;
- flip one mechanism at a time;
- retain the prior path as an explicit escape hatch through the evaluation window.

## Rejects

- **Wholesale oh-my-pi adoption or embedding:** wrong layer; Claude Code and Codex already provide the model/tool runtimes. We need selected control-plane invariants.
- **Hashline as a replacement for Claude Edit/Codex apply-patch:** large integration cost, competing edit dialects, and no direct match to the dominant failures. Adopt manifests first.
- **Automatic stale-anchor patch replay:** fail closed at the task/brief boundary until there is evidence that edit-level staleness is a material source of failures.
- **Production prewalk across Claude → Codex today:** no shared mutable transcript, no proven hidden-prompt scrub, and no proven resume sandbox contract.
- **“Trajectory” as a larger prose brief:** useful context packaging, but still lossy; do not claim prewalk economics or behavior.
- **Letting Sonnet/Opus land the first production edit to manufacture a prewalk trigger:** violates the current builder custody boundary and complicates tripwire/authorship evidence.
- **Trusting schema-valid driver testimony:** schema proves shape, not truth. Host receipts and controller-run gates remain authoritative.
- **Using `SendMessage` as the only ruling channel:** it is a wake-up hint, not durable delivery or acknowledgement.
- **Background Codex from the driver:** already produced idle stalls; keep foreground execution and let a Monitor observe the wrapper-owned process.
- **Automatic retry after timeout when the working tree changed:** filesystem mutation is observable output and makes replay unsafe.
- **Automatic activation of memory-generated skills:** stale policy can autonomously recreate retired rulings; owner promotion is required.
- **LLM compaction of live control state:** a summary may omit the very ruling that must block dispatch. Use deterministic projection only.
- **Full branchable JSONL conversation store for SDD:** unnecessary complexity for a serial task/merge loop; a linear control event log is enough.
- **Recursive driver delegation:** native Claude subagents do not need it here; parent owns the single reviewer spawn.
- **Parallel review before a final driver yield:** already caused review of a superseded commit. Review only an immutable receipt/diff snapshot.
- **General shared/exclusive scheduler in the SDD harness:** serial mutation is a safety feature; parallelize only independent read-only research.
- **Floating model aliases without a checked-in exact resolution:** reproducibility wins. Use stable roles backed by pinned IDs and fail closed.

## Recommended adoption order

1. Build the wrapper receipt/schema and side-effect-aware retry rule.
2. Add the control event log, epoch acknowledgement, and shadow-mode assertions.
3. Introduce `sdd-driver` with scoped action/stop hooks; move review and merge to the parent.
4. Add the conformance/divergence checker and role config.
5. Add brief/source manifests.
6. Only then run the disposable prewalk/resume experiment.
7. Consider reviewed memory candidates after enough clean event history exists.

The first three should be treated as one safety release: receipts establish facts, the event log establishes current authority, and the driver policy prevents bypass. None should auto-merge on its first night. Use the existing attended rollout-gate discipline before enabling enforcement unattended.

## Source notes

- Local operating contract: `.claude/skills/goal/SKILL.md`.
- Local invocation audit: `docs/superpowers/specs/2026-07-19-codex-usage-audit.md` (historical claims must be checked against current source).
- Local incident record: `.superpowers/sdd/progress.md`, especially lines 1593-1597, 1831-1837, 1851-1902, 2156-2158, and 2422-2480.
- Current wrapper inspected: `~/dev-harness/scripts/codex-safe.sh` (105 lines at review time).
- Current local Codex help inspected: `codex exec --help` exposes `--json` and `--output-schema`; `codex exec resume --help` exposes session resume and model override but not an explicit cwd/sandbox flag.
- oh-my-pi pinned prewalk implementation and tests: [`agent-session.ts`](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/session/agent-session.ts#L2396-L2485), [`agent-session-prewalk.test.ts`](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/test/agent-session-prewalk.test.ts#L113-L340).
- oh-my-pi queue semantics and race regressions: [`agent-loop.ts`](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/agent/src/agent-loop.ts#L812-L1179), [`queued-steer delivery tests`](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/test/agent-session-queued-steer-delivery.test.ts#L1-L207), [`idle-drain tests`](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/test/agent-session-steer-idle-drain.test.ts#L14-L25).
- oh-my-pi session/history model: [`docs/session.md`](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/docs/session.md), [`session-context.ts`](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/session/session-context.ts#L140-L207).
- oh-my-pi subagent policy/yields: [`structured-subagent.ts`](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/task/structured-subagent.ts#L170-L312), [`yield.ts`](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/tools/yield.ts#L154-L420), [`soft-budget tests`](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/test/task/executor-soft-budget.test.ts#L16-L27).
- oh-my-pi edit identity/recovery: [`format.ts`](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/hashline/src/format.ts#L85-L115), [`recovery.ts`](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/hashline/src/recovery.ts#L47-L289), [`no-op guard`](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/edit/hashline/noop-loop-guard.ts#L1-L98).
- Claude Code native enforcement surfaces: [custom subagents](https://code.claude.com/docs/en/sub-agents), [hooks reference](https://code.claude.com/docs/en/hooks).

