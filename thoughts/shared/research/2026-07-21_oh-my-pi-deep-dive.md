# oh-my-pi, from process start to first safe edit

**A teaching-grade source walk, researched 2026-07-21**

This report studies oh-my-pi at repository commit [`7b141199d524b859c357fc89654f10b62b9f3df1`](https://github.com/can1357/oh-my-pi/tree/7b141199d524b859c357fc89654f10b62b9f3df1), version 17.0.7. Pinning the commit matters: this is a fast-moving project, and unpinned `main` links would make the line-by-line explanations drift.

All three requested sources were accessible:

- the [actual GitHub repository](https://github.com/can1357/oh-my-pi), including TypeScript, Rust, tests, prompts, and internal documentation—not only its README;
- the [omp.sh product site](https://omp.sh/) and its [documentation](https://omp.sh/docs), recovered from its client-rendered documentation bundles and sitemap where the plain HTML reader exposed only the application shell;
- Can Bölük's [“You only need the frontier model for one single edit”](https://stencil.so/blog/prewalk), including its canonical Markdown representation.

No required source was unreachable. Product and benchmark claims below are attributed to their authors; reading the implementation verifies how the mechanisms work, not the statistical validity of every published benchmark.

## 1. The shortest useful mental model

oh-my-pi, whose executable is `omp`, is an open-source coding-agent **harness**. It is not a model. It connects a chosen language model to a persistent conversation, a terminal UI, source-aware tools, model/provider adapters, project instructions, extensions, and durable session state. Its own one-line description is “a coding agent with the IDE wired in”; the repository describes itself as a fork of Mario Zechner's [Pi](https://github.com/badlogic/pi-mono) ([README lines 5–27](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/README.md#L5-L27)).

The problem it tries to solve is the **harness problem**: a strong model can still perform badly when it receives the wrong context, has awkward edit primitives, repeatedly re-reads files, lacks compiler/IDE feedback, or loses its work when the process ends. omp treats the machinery around the model as a first-class software system:

- normalize dozens of provider APIs behind one event stream;
- give the model one flat tool namespace instead of making it shell out for everything;
- make reads compact but edits safe;
- expose IDE protocols—LSP for code intelligence and DAP for debugging—as model-callable tools;
- preserve conversation as a branchable append-only journal;
- keep long sessions usable through pruning and compaction;
- allow subagents, extensions, MCP servers, terminal use, ACP/RPC clients, and collaboration without building separate agents for each surface.

That makes its audience different from that of a model SDK. It is aimed at developers who want a ready-to-use terminal agent, power users who want to bring their own provider and configuration, and agent engineers who want to study or change the complete harness. The main package is explicitly published as a “Coding agent CLI with read, bash, edit, write tools and session management” and requires Bun 1.3.14 or newer ([coding-agent `package.json` lines 1–32 and 103–105](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/package.json#L1-L32)).

### Why exist beside alternatives?

There are three comparisons to keep separate.

1. **Versus raw model APIs:** a model API supplies inference. It does not supply repository discovery, file snapshots, safe edit application, a shell, session branches, terminal rendering, language servers, debugger adapters, or project-rule loading. omp supplies that control plane.
2. **Versus its Pi ancestor:** omp preserves the small, scriptable Pi lineage but deliberately adds a much larger “batteries included” surface. The README's inventory—providers, tools, LSP/DAP operations, native Rust—communicates this direction ([README lines 96–170](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/README.md#L96-L170)).
3. **Versus first-party or IDE-tied agents:** omp's own comparison pages emphasize provider choice, MIT source availability, terminal/ACP/RPC/SDK surfaces, hashline edits, debugger integration, and reading several competitors' config formats in place ([omp vs. Claude Code](https://omp.sh/vs/claude-code), [comparison index](https://omp.sh/vs)). These are product-authored comparisons, so treat them as the project's design goals rather than neutral consumer advice.

The important engineering proposition is testable in the code: **the harness can change a model's effective behavior without changing its weights**. Hashline changes how it expresses edits. `prewalk` changes which model owns which portion of one trajectory. LSP changes what evidence it can obtain. Compaction changes what history fits. Those are all control-system interventions.

## 2. Architecture at a glance

The codebase is a Bun/TypeScript monorepo plus a Rust workspace. The root [`package.json`](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/package.json#L1-L16) declares ESM modules and Bun workspaces; [`Cargo.toml`](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/Cargo.toml#L1-L35) declares Rust 2024 crates and a release profile with optimization, fat LTO, and unwindable panics.

```text
terminal / pipe / ACP / RPC / SDK
              │
              ▼
  coding-agent CLI and mode controllers
  cli.ts → cli-commands.ts → launch.ts → main.ts
              │
              ▼
       createAgentSession (sdk.ts)
  settings + auth + models + project context
  tools + extensions + MCP + session journal
              │
        ┌─────┴──────────────┐
        ▼                    ▼
  AgentSession          InteractiveMode
  policy/lifecycle      event → component → TUI
        │                    │
        ▼                    ▼
  Agent + agentLoop     ANSI terminal renderer
        │
   model request ⇄ provider adapter (`packages/ai`)
        │
   assistant text/tool calls
        │
   shared/exclusive tool scheduler
        │
  ┌─────┼──────────┬───────────┬───────────┐
  ▼     ▼          ▼           ▼           ▼
 read/edit/bash   LSP         DAP        task/MCP/etc.
  │     │          │           │
  └── hashline     └ subprocess JSON-RPC ─┘
        │
        ▼
 native N-API boundary → Rust grep/glob/walker/shell/PTY/text/AST

Every final message/tool result ──► append-only JSONL session tree
```

This diagram also shows the most useful boundary in the project:

- **TypeScript owns policy:** configuration precedence, prompt construction, state machines, model routing, validation, UI semantics, approvals, session reconstruction.
- **Rust owns portable hot paths and dangerous runtime boundaries:** searching, walking, shell/PTY work, text measurement, AST primitives, cancellation-aware blocking tasks, and N-API panic containment.

### Package map

The major workspace packages are:

| Package | Responsibility |
|---|---|
| `packages/coding-agent` | Product assembly: CLI, session policy, tools, modes, project discovery, extensions, LSP/DAP, subagents, memory. |
| `packages/agent` | Provider-neutral agent state and the model/tool event loop. |
| `packages/ai` | Model types, provider adapters, credential/request mapping, unified streaming events. |
| `packages/catalog` | Bundled model metadata used for matching, capabilities, token limits, and defaults. |
| `packages/tui` | Message-agnostic terminal component engine, input normalization, differential rendering, overlays. |
| `packages/hashline` | Edit grammar, parser, snapshots, stale-anchor recovery, pure patch application. |
| `packages/natives` | Generated JavaScript/TypeScript surface for the Rust N-API addon. |
| `packages/snapcompact` | Deterministic image-based conversation compaction. |
| `packages/mnemopi` | Memory-related machinery; `coding-agent` also contains the user-facing memory backends and local pipeline. |
| `packages/wire` | Shared protocol/wire shapes. |
| `packages/collab-web` | Browser collaboration UI and relay-facing components. |
| `packages/utils`, `stats`, `metaharness`, benchmarks | Cross-cutting utilities, telemetry/statistics, evaluation, and edit benchmarks. |

The important Rust crates are `pi-natives`, `pi-shell`, `pi-walker`, `pi-ast`, and `pi-iso`, plus vendored implementations. The N-API root declares modules for grep, glob, workspace walking, AST, PTY, shell, task scheduling, token/text helpers, and more ([`crates/pi-natives/src/lib.rs` lines 16–56](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/crates/pi-natives/src/lib.rs#L16-L56)).

## 3. Lifecycle of a normal invocation

Here is the end-to-end lifecycle before we zoom into each subsystem.

1. `omp` starts in [`packages/coding-agent/src/cli.ts`](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/cli.ts). It performs Bun/version/bootstrap checks, then delegates the argument vector.
2. [`resolveCliArgv()`](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/cli-commands.ts#L140-L165) recognizes real subcommands. Otherwise it prepends `launch`, allowing `omp "fix this"` to behave as `omp launch "fix this"`. It also protects ambiguous management words from silently becoming model prompts.
3. [`commands/launch.ts`](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/commands/launch.ts#L25-L75) parses launch flags, including model roles, modes, `--prewalk`, and `--prewalk-into`, then calls `runRootCommand()`.
4. [`runRootCommand()`](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/main.ts#L1072-L1174) establishes cwd, auth, model registry, settings, plugins, terminal/protocol ownership, and interactive versus print mode. Independent discovery is started early and awaited only when needed.
5. A `SessionManager` is selected or restored. Model scope, file arguments, extensions, and initial prompt are resolved. [`createAgentSession()`](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/sdk.ts#L1195-L1325) assembles the session.
6. Session assembly discovers context files, skills, rules, prompt templates, workspace structure, MCP servers, and tools; constructs the system prompt; instantiates `Agent`; restores prior messages; then wraps it in `AgentSession` ([`sdk.ts` lines 2452–2561](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/sdk.ts#L2452-L2561), [2787–2989](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/sdk.ts#L2787-L2989)).
7. Interactive mode builds the TUI and subscribes to session events; print/RPC/ACP modes install different consumers over the same session core.
8. User input becomes `AgentSession.prompt()`. It resolves slash commands/templates and constructs attributed messages before handing the request to `Agent.prompt()`.
9. `Agent` invokes `agentLoop()`. The loop streams a provider response, emits incremental events, executes any tool calls, appends their results, and asks the model again until a natural stop or queued follow-up occurs.
10. `AgentSession` persists finalized messages into JSONL, runs policy hooks such as retries, compaction, todo reminders, and prewalk, and re-emits domain events. Interactive mode turns those events into components; the TUI paints a differential ANSI frame.
11. On graceful exit the session writer is flushed/closed, native processes and protocol connections are disposed, and the JSONL can reconstruct the active branch later.

Notice what is *not* present: no single giant “agent function” does everything. The design uses layers with event contracts between them.

## 4. Subsystem walk: CLI, configuration, and assembly

### 4.1 CLI dispatch is intentionally conservative

The `commands` array is data, not a switch statement: each entry has a name and a lazy `import()` ([`cli-commands.ts` lines 14–47](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/cli-commands.ts#L14-L47)). This keeps startup lighter and makes command metadata reusable for generated completion scripts.

`resolveCliArgv()` embodies a subtle product requirement. Positional text is normally a prompt, but command-like text might be a misspelled management command. It therefore:

- passes help/version through;
- keeps a recognized subcommand;
- scans past global flags and hoists a recognized subcommand;
- otherwise returns `['launch', ...argv]`.

The reserved-word guard exists because accidentally sending `omp marketplace add x` to a model is much worse than a usage error. This is a good example of engineering from observed failures: comments name regressions where command arguments leaked into prompts.

### 4.2 Startup overlaps independent work

`runRootCommand()` starts plugin-root preloading while it initializes settings, mode, theme, and models ([`main.ts` lines 1121–1130](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/main.ts#L1121-L1130)). It also claims stdin early for RPC so plugin code cannot consume protocol frames, and it distinguishes:

- interactive terminal;
- print mode;
- automatically selected print mode when stdin is piped;
- ACP and RPC protocol modes.

This is more than optimization. Ownership of stdin, terminal raw mode, and process-global environment must be settled before extensions can introduce side effects.

Settings form a layered configuration tree. CLI values use runtime overrides rather than mutating persisted config. Model **roles** such as `default`, `smol`, `slow`, and `plan` separate intent from a concrete provider/model ID. That indirection is what lets `--prewalk` default to `@smol` while a user decides what “small and fast” means.

### 4.3 `createAgentSession()` is the composition root

If you want to understand dependency injection without a framework, read [`sdk.ts`](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/sdk.ts). It is long because it is the composition root: the one place where subsystems are selected, configured, and connected.

Its important data structure is `ToolSession`, an object carrying live session-scoped services: cwd, settings, snapshot stores, active tools, todo state, registries, UI capability, session/agent IDs, and callbacks. Tool factories receive this capability object rather than importing one global session. The object even exposes cwd through a getter so `/move` takes effect without rebuilding all tools.

Built-in tool factories are declared in [`tools/index.ts`](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/tools/index.ts#L379-L419). `createTools()` filters them by settings, explicit tool names, session depth, and related invariants. Tools are collected into a `Map<string, AgentTool>`: maps give O(1) name replacement and make extension overrides explicit. Every tool is then wrapped at the registry boundary, where approval checks and extension hooks can apply consistently. Rare tools may remain discoverable behind `xd://` rather than bloating the active model schema.

System-prompt construction is similarly compositional. `rebuildSystemPrompt()` combines memory guidance, auto-learning guidance, MCP instructions, context files such as `AGENTS.md`, skills, rules, workspace metadata, and the **currently active tool descriptions**. Rebuilding is necessary because MCP connection or active-tool changes can happen after startup. A useful invariant appears here: never tell a model to use a tool that is not actually active.

Finally, `sdk.ts` creates an `Agent` with provider-neutral state and callbacks, restores messages or persists initial model/thinking metadata, and creates `AgentSession` with all higher-level policy services ([`sdk.ts` lines 2787–2872](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/sdk.ts#L2787-L2872)).

### Learner notes: TypeScript features in this layer

- `import type { X }` removes a dependency at runtime; it is only for compile-time checking.
- `import('./file').then(m => m.default)` is a dynamic import. It returns a Promise and enables lazy loading.
- `foo?.bar` is optional chaining; `x ?? fallback` uses the fallback only for `null`/`undefined`, unlike `||`, which also treats `0` and `''` as absent.
- `Map<string, AgentTool>` states both key and value types. Unlike a plain object, a `Map` preserves insertion order and avoids prototype keys.
- A getter inside an object literal—`get cwd() { ... }`—computes a fresh value every access.
- A discriminated union is a union of object types sharing a tag such as `type` or `role`. Switching on that tag narrows the remaining fields automatically.
- `as const` preserves literal values instead of widening them to `string` or `number`.
- Private fields such as `#prewalk` are enforced JavaScript private fields, not merely a TypeScript convention.

## 5. Subsystem walk: Agent, provider stream, and tool scheduler

### 5.1 Three layers with three jobs

Do not conflate these classes:

- `AgentSession` in `coding-agent` owns product policy: persistence, slash commands, retry/compaction, modes, model changes, todos, prewalk, extensions.
- `Agent` in `packages/agent/src/agent.ts` owns provider-neutral live state: messages, current model, tools, queues, abort controller, and event forwarding.
- `agentLoop()` in `packages/agent/src/agent-loop.ts` owns the algorithm: request model → execute tool calls → append results → request model again.

This separation makes the core loop reusable without knowing about omp's entire product surface.

### 5.2 The loop is two nested loops

[`agentLoop()`](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/agent/src/agent-loop.ts#L332-L367) copies the prior context, adds new prompts, emits `agent_start` and the first `turn_start`, then calls `runLoop()`. The core at [`runLoopBody()` lines 758–849](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/agent/src/agent-loop.ts#L758-L849) has:

- an outer loop for queued follow-up messages arriving after the agent would otherwise stop;
- an inner loop while the last response contains runnable tool calls or pending steering messages.

At each inner iteration it flushes pending messages into context, synchronizes live prompt/tool state, resolves tool-choice policy exactly once for that logical turn, then streams an assistant response. Tool calls run for stop reasons `toolUse` **or** normal `stop`; `length` is deliberately excluded because arguments may be truncated ([`agent-loop.ts` lines 994–1018](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/agent/src/agent-loop.ts#L994-L1018)).

This is an important lesson about protocol adapters: provider metadata is not always semantically consistent. The loop uses the content plus a small safe set of stop conditions rather than assuming every provider labels a tool turn identically.

The interactive input path above this loop is also concrete. [`submitInteractiveInput()`](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/main.ts#L286-L340) decides whether input should queue or prompt now. [`AgentSession.prompt()`](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/session/agent-session.ts#L8665-L8846) first intercepts extension/custom/file slash commands, expands prompt templates, and routes input typed during streaming into steering/follow-up queues. The private [`#promptWithMessage()`](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/session/agent-session.ts#L8847-L9040) owns the policy-heavy prelude: model/API-key checks, pending yields, compaction, plan/goal guidance, `@file` auto-reads, extension hooks, automatic thinking effort, and context accounting. Only then does `#promptAgentWithIdleRetry()` call `this.agent.prompt(...)`. This is why `Agent.prompt()` can stay small: product policy has already converted raw input into ready-to-run messages.

### 5.3 Streaming is a translation boundary

`streamAssistantResponse()` resolves the **current** model for every request, transforms omp messages to generic LLM messages, then asks `packages/ai` to stream. Resolving per request is what makes mid-run switches such as prewalk possible.

[`streamDispatch()`](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/ai/src/stream.ts#L757-L850) routes on `model.api` to Anthropic, OpenAI Responses/completions, OpenRouter, Google, Bedrock, Ollama, and other adapters. Each adapter translates its provider's event taxonomy into the common `AssistantMessageEvent` sequence. The loop turns those into `message_start`, repeated `message_update`, and `message_end` events.

`streamSimple()` contains another subtle correctness boundary: when an API-key resolver can rotate credentials, it buffers only the initial safe event. It may retry an authentication failure **before any replay-unsafe output escapes**; after text/tool deltas are visible, replay could duplicate output or side effects, so it surfaces the error instead ([`stream.ts` lines 1004–1117](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/ai/src/stream.ts#L1004-L1117)).

There is no bounded backpressure queue in this stream design. It favors simple ordered, responsive delivery; a sufficiently slow consumer can accumulate in-memory events. That is a conscious simplicity/performance tradeoff documented in [`provider-streaming-internals.md`](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/docs/provider-streaming-internals.md).

### 5.4 Tool execution is validated, observable, and partially concurrent

[`executeToolCalls()`](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/agent/src/agent-loop.ts#L1770-L1853) creates one record per tool call: resolved tool, raw arguments, abort signal, execution state, result, and error flags. `runTool()` then:

1. validates arguments against the tool schema;
2. emits `tool_execution_start`;
3. runs a `beforeToolCall` hook that may block;
4. transforms arguments (for timeout caps or secret de-obfuscation);
5. calls `tool.execute(...)`, forwarding partial updates;
6. normalizes the result so malformed extension output cannot corrupt the session;
7. runs the post-hook;
8. emits a paired `ToolResultMessage` even for errors.

Pairing is critical because provider APIs require every tool-use block to have a corresponding result on replay.

Concurrency is not simply `Promise.all`. Each tool declares `shared` or `exclusive`. The scheduler at [`agent-loop.ts` lines 2197–2244](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/agent/src/agent-loop.ts#L2197-L2244) lets adjacent shared tools run together; an exclusive tool waits for the previous exclusive and all outstanding shared tools, then becomes a barrier for following tools. Conceptually:

```text
read A ─┐
read B ─┴─ concurrently ─┐
                         ├─ edit C (exclusive) ─┬─ grep D ─┐
                         │                      └─ read E ─┴─ concurrently
```

It awaits `Promise.allSettled`, not `Promise.all`, so one rejection does not prevent the loop from accounting for every call. Abort signals distinguish user steering, external cancellation, and peer/IRC interruption; non-interruptible side-effecting tools are protected from an IRC-only abort.

### Learner notes: asynchronous idioms

- An `async` function always returns a Promise. `await` pauses that function, not the whole process.
- `for await (const event of stream)` consumes an async iterator as events arrive.
- `AbortController`/`AbortSignal` is cooperative cancellation. `AbortSignal.any([...])` produces a signal that aborts when any input does.
- `Promise.allSettled()` returns every outcome; `Promise.all()` rejects at the first rejection.
- A closure captures variables from its surrounding scope. The scheduler's `start.then(() => runTool(record, index))` closes over each record.
- Type predicates such as `(c): c is ToolCallContent => ...` tell TypeScript that a filter narrows the resulting array.

## 6. Subsystem walk: reads, snapshots, and hashline edits

This is the best subsystem for learning how product design, data structures, parsing, and safety meet.

### 6.1 `read` is a dispatcher, not `fs.readFile`

`ReadTool.execute()` begins at [`tools/read.ts` line 2136](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/tools/read.ts#L2136-L2185). It recognizes conflict URLs, HTTP(S), internal schemes, directories, archives, SQLite, PDFs, notebooks/documents, images, and plain files. This implements a broader design idea: make resources look filesystem-shaped so the model learns fewer interfaces.

For a plain text file, it streams only the selected range under line/byte caps. A crucial implementation detail is the separation between:

- `collectedLines`: exact source text used for snapshots;
- `displayLines`: possibly column-truncated text shown to the model/UI.

Mutating the exact lines for display used to make long-line files uneditable, so the code now clones only when a display line needs truncation ([`read.ts` lines 2593–2615](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/tools/read.ts#L2593-L2615)). That is a general lesson: **presentation loss must not leak into identity or validation data**.

When hashline display is active, the read records a whole-file snapshot—even for a range read, within a size bound—and returns a header plus numbered lines ([`read.ts` lines 2646–2663](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/tools/read.ts#L2646-L2663)). A simplified output is:

```text
[src/auth.ts#9F3E]
41:export function authenticate(token: string) {
42:  return verify(token)
43:}
```

The model later points at line anchors under that file tag rather than reproducing a fragile exact “old string.”

### 6.2 What the four-hex tag really means

[`computeFileHash()`](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/hashline/src/format.ts#L85-L115) trims trailing spaces/tabs/CR per line, computes xxHash32, and keeps the low 16 bits as four uppercase hexadecimal characters.

That is not a collision-resistant content ID. It is a compact lookup tag into a session snapshot store. The system remains safe because a collision is not accepted blindly: the retained snapshot text, anchors, neighboring context, and live file are compared before recovery. [`Recovery.tryRecover()`](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/hashline/src/recovery.ts#L264-L289) explicitly chooses the latest retained text on a 16-bit collision and still requires unambiguous mapping.

The tradeoff is excellent for an LLM-facing format: four characters are cheap to copy; robust host-side verification carries the safety burden.

### 6.3 Patch grammar and preflight

The hashline format supports concrete replacement/deletion/insertion, start/end insertion, tree-sitter block operations, and file operations. The constants live in [`format.ts` lines 9–49](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/hashline/src/format.ts#L9-L49). An illustrative replacement is:

```text
[src/auth.ts#9F3E]
SWAP 42.=42:
+  return verifyAndAudit(token)
```

The coding-agent wrapper parses the patch and delegates to `Patcher`. `Patcher.prepare()` performs all non-writing work first ([`patcher.ts` lines 280–365](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/hashline/src/patcher.ts#L280-L365)):

- parse the section;
- require its snapshot tag;
- read and canonicalize the path;
- optionally recover a mistyped directory using unique filename + tag;
- run the write/approval preflight;
- preserve BOM and detect line endings;
- normalize to LF;
- validate or recover anchors;
- apply edits in memory.

Only `commit()` restores BOM/line endings and calls the filesystem. Multi-section patches prepare every section before any write, reject duplicate canonical targets and no-ops, then commit sequentially ([`patcher.ts` lines 219–263](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/hashline/src/patcher.ts#L219-L263)).

There is a nuance worth learning from: the comment calls the batch “naturally all-or-nothing,” which is true for validation failures, but not for an I/O failure during the commit loop. Earlier files are not rolled back; the thrown error lists which landed and which did not. Full cross-file atomicity would require a transaction/staging protocol that ordinary filesystems do not offer cheaply.

### 6.4 The pure edit algorithm

[`applyEdits()`](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/hashline/src/apply.ts#L1224-L1330) is pure: text and parsed edits in, new text plus warnings/first changed line out. It:

1. rejects unresolved structural block edits;
2. splits the file into an array of lines;
3. validates line bounds and repairs certain replacement/structural landing mistakes;
4. partitions BOF, EOF, and anchor-targeted edits;
5. buckets targeted edits by line;
6. processes line buckets from bottom to top;
7. uses `Array.splice()` to replace each target with before/replacement/original/after rows;
8. adds start/end insertions and joins with `\n`.

Why bottom-up? If line 10 is edited before line 100, adding rows at 10 changes the array index of 100. Editing 100 first leaves all smaller indexes stable. This is a standard text-editor and compiler-rewrite technique.

### 6.5 Stale-anchor recovery

Suppose the model read a file, another process inserted three lines at the top, and then the model edits old line 42. Rejecting every shifted file would be safe but frustrating. Blindly applying at 42 would be dangerous. Recovery proves whether the intended region is still unchanged.

[`buildLineMap()`](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/hashline/src/recovery.ts#L47-L73) diffs the snapshot's line array against the current line array and maps unchanged old line numbers to new ones. Recovery then:

- requires every anchor to map;
- checks neighboring non-anchor context, with stricter checks for duplicate line text;
- remaps all anchors;
- requires all anchors to share one consistent offset;
- replays the edit against current text;
- rejects ambiguity, changed/deleted targets, or a no-op.

The neighbor computation groups contiguous anchors and runs in roughly `O(a log a)` for `a` anchors rather than walking across a large block from every anchor ([`recovery.ts` lines 93–114](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/hashline/src/recovery.ts#L93-L114)). This is an example of optimizing the pathological shape, not merely the average case.

## 7. Subsystem walk: native Rust core

The JavaScript wrapper's handwritten part is almost comically small: call `loadNative()`, then re-export generated classes/functions ([`packages/natives/native/index.js` lines 1–27](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/natives/native/index.js#L1-L27)). `napi-rs` generates the TypeScript declarations and binding glue.

The exported surface includes `grep`, `glob`, `listWorkspace`, shell execution, `PtySession`, AST search/edit, token counting, highlighting, image/text helpers, and terminal-key parsing ([`index.js` lines 28–71](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/natives/native/index.js#L28-L71)). The addon exposes a version sentinel such as `__piNativesV17_0_7`; the loader refuses a stale `.node` binary after an interrupted upgrade rather than failing later with a mysterious missing function ([`pi-natives/src/lib.rs` lines 235–252](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/crates/pi-natives/src/lib.rs#L235-L252)).

### Grep and glob

[`grep.rs`](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/crates/pi-natives/src/grep.rs#L1-L38) embeds ripgrep-family crates. It has separate in-memory `search()` and filesystem `grep()` APIs, Rust-regex and PCRE2 matchers, context/count/file modes, global/per-file limits, gitignore/glob filtering, and a 4 MiB per-file cap. A thread-local `Searcher` cache avoids rebuilding identical workers inside parallel traversal ([`grep.rs` lines 581–659](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/crates/pi-natives/src/grep.rs#L581-L659)). Binary detection stops on NUL.

[`glob.rs`](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/crates/pi-natives/src/glob.rs#L128-L228) builds a `pi_walker::WalkRequest`: hidden/gitignore policy, `.git` and `node_modules` rules, symlink policy, depth bound derived from the glob, optional cache, deterministic path order, cancellation heartbeat, and optional mtime ranking. Pushing filtering/limit knowledge into the walker avoids traversing an entire tree only to discard results later.

### Blocking work and cancellation

N-API's JS thread must not run filesystem scans or CPU-heavy work synchronously. [`task.rs`](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/crates/pi-natives/src/task.rs#L1-L27) wraps work as `napi::Task`, whose `compute()` runs on libuv's worker pool and whose `resolve()` returns to the JS thread. Long loops receive a cloneable `CancelToken` and call `heartbeat()`.

The boundary also catches Rust panics before they cross a non-unwind-safe C FFI callback and abort Bun ([`task.rs` lines 152–208](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/crates/pi-natives/src/task.rs#L152-L208)). The Cargo release profile deliberately uses `panic = "unwind"` for this recovery strategy. On constrained Windows hosts, module setup probes how many worker threads can coexist, caps Tokio/Rayon pools, and can fall back to a current-thread runtime rather than panicking during addon load ([`lib.rs` lines 68–128 and 130–233](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/crates/pi-natives/src/lib.rs#L68-L128)).

### Learner notes: Rust constructs

- `enum` variants can carry data and are exhaustively matched. `Option<T>` is `Some(T)` or `None`; `Result<T, E>` is `Ok(T)` or `Err(E)`.
- `?` returns early on `Err` (or `None` in an option-returning context), reducing error-handling boilerplate.
- `#[napi(object)]` and `#[napi]` are procedural attributes generating JS bindings.
- `impl Trait for Type` implements an interface-like trait. `impl Task for Blocking<T>` defines how N-API schedules the generic wrapper.
- `where T: Send + 'static` constrains values crossing threads: they must be thread-safe to move and own any referenced data long enough.
- `Arc` is atomically reference-counted shared ownership; `AtomicBool` supports lock-free signaling.
- `RefCell` allows runtime-checked interior mutation on one thread; here it supports a thread-local reusable search worker.
- `catch_unwind(AssertUnwindSafe(...))` catches panics at a carefully chosen boundary. It is not a substitute for normal `Result` errors.

## 8. Subsystem walk: LSP and DAP—the “IDE wired in”

### 8.1 LSP

The LSP tool entry is [`lsp/index.ts`](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/lsp/index.ts); [`client.ts`](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/lsp/client.ts) owns server processes and JSON-RPC; `config.ts` selects servers; `edits.ts` applies workspace edits. The project's [LSP source guide](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/docs/tools/lsp.md) documents the current branches and limits in detail.

One cached client exists per `command:cwd`. On first use it spawns the server, starts a message reader, sends `initialize`, stores capabilities, and sends `initialized`. The reader distinguishes responses by incrementing JSON-RPC ID, notifications such as `publishDiagnostics`, progress events, and server-to-client requests such as `workspace/applyEdit`. Each outgoing request registers timeout and abort handlers; cancellation sends `$/cancelRequest`.

The model-facing `lsp` tool dispatches actions including diagnostics, definition, references, hover, symbols, rename, file rename, code actions, capabilities, and raw requests. File-scoped actions call `ensureFileOpen()` and convert omp's one-based line numbers to LSP's zero-based positions. When the user supplies `symbol`, `resolveSymbolColumn()` finds its occurrence on the line, supporting `name#N` to disambiguate repeats.

The most revealing operation is `rename_file`:

1. enumerate affected file URI pairs;
2. ask every applicable server for `workspace/willRenameFiles` edits;
3. merge/coalesce edits, with project-aware servers winning overlaps;
4. apply text edits from snapshots;
5. perform the filesystem rename;
6. close renamed open documents and send `workspace/didRenameFiles`.

This is why an IDE-aware file move can update imports and barrel exports whereas `mv` cannot. It is also why this tool has more failure modes and stricter preflight than a shell command.

### 8.2 DAP

The model-facing debug tool is [`tools/debug.ts`](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/tools/debug.ts); [`dap/session.ts`](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/dap/session.ts) owns the session tree, and `dap/client.ts` implements DAP framing and requests. See the repository's [debug tool source guide](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/docs/tools/debug.md).

Launching or attaching selects an adapter, spawns/connects it, sends `initialize`, handles the `initialized`/breakpoint/`configurationDone` handshake, and caches capabilities. Reverse requests are important:

- `runInTerminal` asks omp to spawn the debuggee;
- `startDebugging` creates a child DAP session, enabling compound/debug-child trees.

Events update cached output, stop location, threads, frames, and active child. Tool actions use that cache so `variables` or `evaluate` can default to the current stopped frame. Continue/step subscribe for a future stop/termination *before* sending the command, avoiding a race where a fast stop arrives first. Breakpoint sets propagate to children before configuration completes.

LSP and DAP demonstrate a repeated project pattern: wrap a stateful subprocess protocol in a session manager, convert it to a small model-facing action schema, and retain enough state that later calls can omit boilerplate IDs.

## 9. Subsystem walk: terminal UI

The TUI engine is deliberately ignorant of agents. [`packages/tui/src/tui.ts`](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/tui/src/tui.ts) understands components with `render(width)` and `handleInput(data)`, focus, overlays, cursor markers, and terminal painting. [`InteractiveMode`](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/modes/interactive-mode.ts#L626-L710) builds domain components—chat, pending messages, todos, subagents, status, editor—and controllers translate `AgentSessionEvent` into their state.

Input travels:

```text
stdin → ProcessTerminal → StdinBuffer → TUI listeners
      → focused component → editor/controller callbacks
```

`StdinBuffer` matters because a terminal escape sequence may arrive across several chunks. It buffers incomplete CSI/OSC/DCS/APC/SS3 sequences and treats bracketed paste as one paste event. Without it, half an arrow-key sequence could become literal text.

Rendering is not “clear screen and print everything.” `requestRender()` coalesces requests and rate-limits ordinary frames. The root component produces rows and a seam marking which prefix is final. The renderer maintains an append-only scrollback ledger, commits settled rows exactly once, slices the visible window, overlays screen-coordinate components, extracts the hardware cursor marker, then chooses among:

- append new settled rows;
- diff changed in-window rows;
- rewrite the seam plus window;
- full repaint for explicit gestures such as resize/session replacement.

The repository's [`tui-runtime-internals.md`](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/docs/tui-runtime-internals.md) is unusually good supplementary reading because it records why terminal limitations force each invariant. Native scrollback cannot be queried reliably, width changes alter wrapping, overlays must freeze commits, and an over-wide line can corrupt later cursor math.

Streaming events create/update a live assistant component. Tool execution events create cards and progress updates. On `message_end`, the streaming component is finalized; on `agent_end`, loaders stop and deferred UI state is flushed. A spinner requests a component-scoped render so the engine can reuse unrelated transcript rows instead of re-rendering the entire tree.

The architectural taste here is clear: rendering is a separate deterministic system with its own correctness rules, not printf calls sprinkled through business logic.

## 10. Subsystem walk: sessions, branches, compaction, and memory

### 10.1 The session is an append-only tree in JSONL

The source of truth is [`session-manager.ts`](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/session/session-manager.ts) plus the focused [session format document](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/docs/session.md).

Line one is a versioned session header. Every later line is a `SessionEntry` with short `id`, `parentId`, timestamp, and a discriminating `type`: message, model/thinking/service-tier change, compaction, branch summary, custom state/message, label, mode change, and others.

This is not merely a list. `parentId` forms a tree; the manager's current leaf selects the active branch. Branching moves the leaf pointer and subsequent append forms a new child. Old entries remain. `SessionEntryIndex` keeps:

- `Map<id, entry>` for O(1) lookup;
- `Map<parentId, children[]>` for tree traversal;
- labels;
- current leaf;
- cumulative usage.

[`buildSessionContext()`](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/session/session-context.ts#L140-L207) walks from leaf to root through `parentId`, reverses the path, then interprets metadata and messages. Therefore two branches can share a long prefix without duplicating it on disk.

Persistence is optimized for the hot path. A new empty/draft session is not materialized until it has an assistant response or file creation is forced. Once current, an append is synchronously handed to the writer so the entry is durable in the OS page cache when the method returns ([`session-manager.ts` lines 691–735](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/session/session-manager.ts#L691-L735)). Operations that change prior state use a full temp-write/atomic-replace path with an epoch and fence so a concurrent append cannot be lost ([`session-manager.ts` lines 629–689](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/session/session-manager.ts#L629-L689)). It is software-crash durable, not power-loss durable: normal appends are not `fsync`ed.

### 10.2 Compaction changes LLM context, not history

Compaction appends a `CompactionEntry`; it does not delete old JSONL entries. During context rebuild, the latest compaction summary replaces the old prefix for the model, while recent entries from `firstKeptEntryId` onward remain verbatim. Transcript mode can still render the historical conversation with a compaction divider. The [compaction guide](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/docs/compaction.md) traces manual, threshold, overflow, incomplete-output, mid-turn, and idle triggers.

Before summarizing, omp can blank stale/useless or oversized tool results while preserving tool-call/result pairing. Cut points never split at a tool result. If the cut falls inside a user turn, it summarizes both prior history and the kept turn prefix so the model does not awaken halfway through an unexplained action.

The conventional strategy asks a model to summarize. `snapcompact` instead serializes older history into dense local bitmap frames for a vision-capable model, retaining bounded text at chronological edges. It trades semantic compression for deterministic visual archival and provider-specific image-token economics. This is an unusual but architecturally clean plug-in point: both strategies produce data stored in a compaction entry and reconstructed by the same context builder.

### 10.3 Memory is explicitly heuristic

The local memory backend is disabled by default. At startup it can process older persisted sessions in two phases: extract durable facts per session, then consolidate them into `MEMORY.md`, a smaller injection summary, and generated skill playbooks. A lease/heartbeat prevents two processes consolidating the same bank, and common secret patterns are redacted before output. The files and settings are documented in [`docs/memory.md`](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/docs/memory.md).

The system prompt tells the agent that memory is heuristic and must be checked against current repository evidence. This is a strong design choice: durable model-written memory is valuable but inherently stale and probabilistic. The memory system does not get to outrank the working tree or the user's instruction.

## 11. Subsystem walk: subagents and extensibility

### 11.1 Subagents reuse the same composition path

Subagents are not a completely separate runtime. [`task/executor.ts`](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/task/executor.ts#L1-L74) calls `createAgentSession()` again with isolated settings, identity, session file/artifacts, tool set, system prompt, depth, and output schema. Agent definitions are Markdown plus frontmatter and normalize to `AgentDefinition` fields such as name, prompt, tools, spawns, model, output schema, and optional prewalk.

Discovery merges project `.omp/agents`, user agents, enabled plugin agent directories, then bundled definitions using first-name-wins precedence. Bad user definitions warn and skip; malformed bundled definitions are fatal because they indicate a broken release. Execution rediscovers definitions, so a file changed during a session can affect the next spawn. These details and recursion constraints are mapped in [`task-agent-discovery.md`](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/docs/task-agent-discovery.md).

The task subsystem adds safety/control around the reused loop:

- parent spawn allowlists and disabled-agent settings;
- recursion-depth removal of the child `task` tool;
- plan-mode reduction to read-only tools;
- per-agent soft request budgets, followed by forced final `yield` and eventual abort;
- optional isolated worktrees;
- schema validation of structured yields;
- event forwarding into a parent-visible registry/HUD.

[`finalizeSubprocessOutput()`](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/task/executor.ts#L541-L670) illustrates robust boundary code: assemble one or more yields, parse stringified JSON when appropriate, validate the normalized schema, preserve prior failure state, distinguish aborted/invalid/unavailable/valid outcomes, and produce a nonzero exit for strict schema violations.

### 11.2 Extensions wrap stable boundaries

Extensions, custom tools, skills, rules, prompt templates, hooks, MCP servers, and slash commands enter through discovery during session assembly. The core protection is placement: untrusted/custom behavior is invoked at explicit boundaries—tool wrapper hooks, context transforms, compact/model hooks, event listeners—and its results are validated or caught. For example, malformed post-tool hook content is normalized before persistence, and an advisor exception at turn end is logged without aborting the primary agent.

MCP tools share existing manager connections with subagents through proxy tools rather than spawning duplicate server connections. ACP and RPC expose the same `AgentSession` through different transports. This is the payoff of keeping modes/UI outside the agent loop.

## 12. Prewalk: the idea, experiment, and exact implementation

### 12.1 Why read-only planning can cost more

The Stencil article starts with a counterintuitive result: a frontier model planning read-only and a cheap model implementing can cost more than letting the frontier model do everything. The article attributes this to the token distribution of agent work: in one reported sample, edits/writes were only 9% of 1.81 billion tokens across roughly two million tool calls; reads dominated ([article lines 29–47](https://stencil.so/blog/prewalk)).

The economic argument is:

1. The strong planner reads the repository and builds a rich trajectory of evidence.
2. A plan document compresses that experience into a small prose artifact.
3. The executor cannot edit prose; it re-reads source and reconstructs much of the lost grounding.
4. The “cheap” architecture duplicated the dominant work.

The deeper information argument is equally important. A trajectory contains which hypotheses failed, which files were relevant, tool results, ordering, and implicit confidence. A plan is a lossy summary of that state.

### 12.2 Prewalk's intervention

The article's key phrase is “hand off a trajectory, not a fairytale.” Its mechanism is:

1. start on the frontier model;
2. secretly ask it to produce a concrete plan, capture a bounded todo list, and begin;
3. after the first valid edit, switch the current session to the cheaper model;
4. remove the hidden planning instruction but keep the exploration, plan, todos, and first edit in context.

The executor therefore receives the actual path and an in-context example of successful action. Autoregressively, it sees a history in which “it” already understood the code and began implementing. The article compares this to prefill at the level of whole turns rather than a forced assistant prefix ([article lines 158–174](https://stencil.so/blog/prewalk)).

The reported SWE-bench Pro results are:

| Guide/executor family | Cheap oneshot | Prewalk | Frontier oneshot |
|---|---:|---:|---:|
| GPT-5.6 Luna / Sol | 77%, $0.60, 570s | 85%, $1.04, 300s | 88%, $1.71, 372s |
| Gemini Flash 3.5 / Opus 4.8 | 60%, $1.16, 360s | 78%, $1.46, 402s | 85%, $2.78, 606s |

These are author-reported benchmark arms, not replicated here ([article lines 94–142](https://stencil.so/blog/prewalk)). Fixed-turn switching failed because task progress varies. Switching on any edit was finicky. Todo-gating improved follow-through, and the prompt needed a todo item cap because one guide made huge lists ([article lines 75–92](https://stencil.so/blog/prewalk)).

The article also reports less web-search “cheating” and proposes—not proves—a behavioral explanation: the frontier model exits during its confident early phase, and the executor inherits a successful-looking trajectory rather than a desperate one ([article lines 144–156](https://stencil.so/blog/prewalk)). Keep that labeled as inference.

### 12.3 The current code is a turn-boundary state machine

The shipping implementation is more precise than “switch after an edit.” `Prewalk` holds a target model and optional thinking level ([`agent-session.ts` lines 841–856](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/session/agent-session.ts#L841-L856)). Private state records whether the plan nudge was injected, a continuation is armed, and a successful todo call has opened the gate.

Only `edit` and `write` result names trigger the switch. `bash` is excluded because it is often exploration; `todo` opens the gate but does not trigger because switching there would hand all implementation to the cheap model ([`agent-session.ts` lines 510–536](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/session/agent-session.ts#L510-L536)). If `todo` is not in the **active** tool set, the gate is treated as open to avoid deadlock.

There is a small but real distinction between comments and executable condition here. Comments call these “successful” calls and the article says the first edit “lands,” but `#advancePrewalk()` tests only `result.toolName`; it does not inspect `ToolResultMessage.isError`. The common loop includes error results in the turn-end `toolResults` array ([`emitTurnEnd()`](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/agent/src/agent-loop.ts#L435-L454)). Therefore, at this pinned commit, a completed but failed `todo` result opens the gate and a completed but failed `edit`/`write` result can cause the swap. The intended benchmark concept is “first landed action”; the literal implementation trigger is “first paired result with that tool name.” This is exactly the kind of detail for which reading source instead of only prose matters.

`#advancePrewalk()` runs from the Agent's awaited turn-end hook ([`agent-session.ts` lines 2396–2485](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/session/agent-session.ts#L2396-L2485)):

1. ignore non-assistant turns or an unarmed session;
2. note any todo result;
3. maintain a one-shot continuation safety net, because a prose-only planning reply would otherwise naturally end the agent loop;
4. find an edit/write result only if the todo gate is open;
5. if no action and no plan nudge yet, steer a hidden planning message into the next model call;
6. once an action lands, await persistence of the assistant and all tool results;
7. scrub the plan nudge from the live context and agent state;
8. set the target model temporarily/ephemerally;
9. clear prewalk so the switch is one-way and cannot fire again;
10. steer a hidden verification checklist to the target.

The continuation safety net deserves attention. The general loop ends when a model returns text with no tools. But the hidden prompt explicitly asks for prose plan, then todo, then action. Tool progress arms exactly one continuation. If a text-only turn consumes it with no new progress, another consecutive text-only reply ends normally. This avoids both premature termination and an infinite “continue” loop. Regression tests encode these sequences in [`agent-session-prewalk.test.ts`](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/test/agent-session-prewalk.test.ts#L113-L175).

The three hidden prompt files are small and pivotal:

- [`prewalk-plan.md`](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/prompts/system/prewalk-plan.md) demands an explicit execution-order plan, risks, exact verification, then 5–9 meaningful todo items, followed by continued work.
- [`prewalk-continue.md`](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/prompts/system/prewalk-continue.md) is the minimal one-turn safety net.
- [`prewalk-checklist.md`](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/prompts/system/prewalk-checklist.md) asks the executor to check matching sites, limit scope, and run the surrounding test module.

Scrubbing is an in-place array operation. `#scrubPrewalkPlanNudge()` invalidates conversion caches, splices matching custom messages out of the loop's live array, and replaces Agent state with a filtered array ([`agent-session.ts` lines 2521–2545](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/session/agent-session.ts#L2521-L2545)). The persisted transcript intentionally retains the hidden nudge for audit; reloading can therefore rematerialize it, acceptable because prewalk is a single-run lifecycle.

### 12.4 How it is armed

At launch, `--prewalk`, `--prewalk-into`, or `prewalk.enabled` resolves a target, defaulting through `@smol`, verifies configured auth, and puts `{target, thinkingLevel}` in session options ([`main.ts` lines 943–964](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/main.ts#L943-L964)). The plan nudge is injected after the first completed assistant turn, so the guide first receives the user's task normally and begins grounding itself.

The `/prewalk` slash command can arm an existing session. It resolves `@smol`, checks auth, and calls `armPrewalk()` ([`builtin-registry.ts` lines 466–488](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/slash-commands/builtin-registry.ts#L466-L488)). Manual arming injects the plan nudge immediately because the user explicitly says to begin the mechanism now ([`agent-session.ts` lines 2487–2519](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/session/agent-session.ts#L2487-L2519)).

### 12.5 Where prewalk sits architecturally

Prewalk is not a provider feature, a tool, or a separate planning session. It is **AgentSession policy at the turn boundary**:

```text
provider-neutral Agent loop finishes a turn
                  │
                  ▼
AgentSession sees assistant + completed tool results
                  │
       todo seen? edit/write seen?
          │ no              │ yes
          ▼                 ▼
 hidden steering       persist boundary
                          scrub nudge
                          switch Agent.model
                          hidden checklist
                               │
                               ▼
same live context, next provider request, cheaper model
```

That placement gives it exactly the evidence it needs—completed, persisted tool results—and lets the next generic loop iteration pick up the new model without provider-specific code.

## 13. Three complete concrete traces

### Trace A: `omp "change the greeting"` → safe edit → terminal card

Assume interactive mode, a configured model, and hashline edits.

1. **Dispatch.** `resolveCliArgv(['change the greeting'])` returns `['launch', 'change the greeting']`.
2. **Assembly.** `runRootCommand()` initializes settings/auth/models, resolves a new `SessionManager`, then `createAgentSession()` constructs active tools and system prompt. `InteractiveMode` subscribes to the session and starts the TUI.
3. **Prompt.** The input controller eventually calls session prompting. `AgentSession.prompt()` expands templates/file mentions and builds the user message; `Agent.prompt()` starts `agentLoop()`.
4. **Model request.** `streamAssistantResponse()` converts messages, resolves the model/API key, and provider dispatch emits deltas. The model asks to `read` `src/greeting.ts`.
5. **Tool scheduling.** The loop validates the call and invokes `ReadTool.execute()`. The read stores exact whole-file text in the session snapshot store and returns `[src/greeting.ts#ABCD]` plus numbered lines.
6. **Persistence/UI.** The assistant tool-call message and paired read result are appended as JSONL entries. `EventController` creates/finalizes the read card; TUI paints only changed rows.
7. **Second model request.** The loop includes the read result in context. The model emits an `edit` hashline patch anchored to `ABCD`.
8. **Edit preflight.** `Patcher.prepare()` verifies the snapshot tag and seen anchors, normalizes line endings, parses edits, and runs `applyEdits()` in memory. If the file shifted harmlessly, recovery remaps all anchors; if the target changed ambiguously, it fails closed with fresh context.
9. **Commit.** The edit tool has exclusive concurrency, writes restored line endings/BOM, records a new snapshot, optionally requests diagnostics, and returns a structured success result.
10. **Continuation.** The result goes back to the model. It may run tests with `bash`; when a text-only response arrives with no follow-up, the loop emits `agent_end`.
11. **Durability and display.** Final messages are already append-persisted. Interactive mode stops its loader and finalizes cards; the TUI commits settled rows to native scrollback.

Observable effect: the file changed only after host-side validation, the transcript shows the read/edit/test chain, and resume can reconstruct it.

### Trace B: model requests a symbol rename through LSP

Assume the model calls `lsp` with `action: 'rename'`, a file, line/symbol, and `new_name`.

1. The common tool runner validates the LSP schema, applies approval, combines the user abort signal with an LSP timeout, and calls `LspTool.execute()`.
2. LSP config merges defaults and project/user overrides and chooses the primary non-linter server by filename/extension and root markers.
3. `getOrCreateClient()` reuses an initialized `command:cwd` client or spawns one and completes the LSP initialization handshake.
4. `ensureFileOpen()` sends `didOpen`/refresh as needed. `resolveSymbolColumn()` reads the target line and locates the requested occurrence.
5. The client sends `textDocument/rename` with an incrementing request ID. The response reader resolves that pending Promise when the matching JSON-RPC response arrives.
6. The returned `WorkspaceEdit` may touch many URIs. `applyWorkspaceEdit()` snapshots sources, orders text edits safely, writes changes, and notifies affected language servers.
7. The LSP tool formats applied locations and returns one ordinary `ToolResultMessage` to the common agent loop. Later diagnostics can be delivered immediately or through the deferred-diagnostics queue registered during session assembly.
8. The model sees cross-file effects as one tool result and can verify with references/search/tests.

Observable effect: a semantic rename updates references the model may never have manually found. Architecturally, however, it still uses the same tool result/persistence/UI path as `read`.

### Trace C: prewalk from frontier model to `@smol`

1. Startup resolves `--prewalk-into` or `@smol` and puts a `Prewalk` target into `AgentSession`.
2. The frontier model receives the user's task and explores. After its first completed assistant turn, `#advancePrewalk()` injects the hidden plan prompt and arms continuation.
3. The next provider request still resolves the frontier model. It outputs a plan and calls `todo`; the tool result opens `#prewalkTodoSeen` but does not switch.
4. More reads/bash calls remain on the frontier model. Each tool-progress turn can arm one continuation, preventing the prose plan from stopping the run.
5. The frontier model calls `edit` or `write`; the common scheduler executes it. Only a completed result reaches turn-end policy.
6. `#advancePrewalk()` waits until the assistant and tool results have landed in the session journal. It removes the hidden planning instruction from live model context, calls `setModelTemporary(target, ..., {ephemeral: true})`, clears `#prewalk`, and queues the hidden checklist.
7. The next `streamAssistantResponse()` resolves the now-current cheap model. Its context contains exploration, the explicit plan, todo state, and a successful action—but not the instruction to stop and plan.
8. The cheap model continues through the same tool loop and validation paths. The todo system and final checklist add steering without a separate planner/executor transcript.

Observable effect: one transcript and one agent run visibly change model after the first todo-gated edit/write; the target completes the remainder.

## 14. Engineering taste and tradeoffs

The code's “taste” is more informative than its feature count.

### Optimize the model-machine interface

Hashline spends host computation to save model tokens and retries. Unified filesystem-like URLs reduce schema diversity. Tool descriptions are pruned or mounted behind `xd://`. Read output is summarized/truncated for the model while exact snapshots remain host-side. The author optimizes the bottleneck actually paid for: model context and failure loops, not merely local CPU cycles.

### Fail closed on mutation; recover when proof is available

Edits preflight everything possible before writing. Stale anchors can recover only through unchanged-line mapping plus context and consistent offset. LSP applies from snapshots. Exclusive tool barriers prevent overlapping mutation. Yet the system does not pretend ordinary filesystem batches are transactional; it reports partial commit precisely.

### Put policy at stable boundaries

Approvals wrap tools. Prewalk runs at completed turn boundaries. Key rotation retries only before replay-unsafe events. Memory enters prompt construction. Persistence happens on final message events. These locations let mechanisms apply across every provider and UI without duplicated code.

### Preserve evidence and auditability

Sessions append rather than rewrite normal history. Branches retain abandoned paths. Compaction changes reconstructed model context rather than erasing the transcript. Hidden prewalk nudges remain persisted for audit even when removed from live inference context. Errors generally become paired tool results rather than broken histories.

### Prefer explicit state machines to magical heuristics

Prewalk has named booleans and one trigger table. DAP caches explicit stopped state. Session atomic rewrites use epochs/fences. Tool scheduling declares shared/exclusive modes. These can look verbose, but every transition can be tested.

### Engineer from real failure reports

Comments repeatedly cite concrete regressions: leaked CLI arguments, truncated read text poisoning snapshots, text-only prewalk ending early, infinite continuation, stale native binaries, Windows thread-creation failures, completed side effects mislabeled “skipped.” This produces defensive complexity. The tradeoff is a large codebase with long functions and many special cases; the benefit is encoded operational knowledge.

### Notable costs and risks

- `createAgentSession()` and `AgentSession` are very large orchestration units. They centralize invariants but are difficult for a newcomer to hold mentally.
- Many features depend on process-global caches/singletons (native pools, DAP manager, LSP client cache, agent registry). Lifecycle cleanup is therefore part of correctness.
- The provider abstraction necessarily leaks: thinking signatures, stop reasons, credentials, usage, and tool-call dialects require adapter-specific branches.
- Append durability is not `fsync` durability.
- Stream queues are unbounded.
- A 16-bit file tag can collide; safety relies on the snapshot/context recovery protocol, not hash strength.
- “Batteries included” increases attack surface: shell, browser, remote protocols, custom tools, hooks, and MCP all need approvals and validation.
- Product pages mix implementation facts with benchmark/competitive claims. Read source and tests before treating a claim as a guarantee.

## 15. Recommended reading path

Do not read the repository alphabetically. Follow one causal thread at a time.

### Stage 0: prerequisites

Know basic JavaScript/TypeScript: objects/arrays, classes, modules, promises, `async`/`await`, unions/generics. Be able to read basic Rust enums, `Option`, `Result`, traits, and ownership at a high level. Look up:

- event loop and Promises;
- async iterators;
- `AbortController`;
- discriminated unions and type predicates;
- JSON-RPC 2.0;
- terminal ANSI escape sequences;
- LSP and DAP concepts;
- Rust ownership/borrowing, traits, and FFI.

### Stage 1: product shape, not internals

Read in order:

1. [`README.md`](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/README.md#L78-L275)
2. [omp docs overview](https://omp.sh/docs)
3. [using omp](https://omp.sh/docs/using) and [tool reference](https://omp.sh/docs/tools)
4. root [`package.json`](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/package.json#L1-L16) and [`Cargo.toml`](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/Cargo.toml#L1-L35)

Before moving on, be able to explain the difference between a model, provider adapter, agent loop, tool, session, and UI mode.

### Stage 2: follow startup to a constructed session

Read:

1. `packages/coding-agent/src/cli.ts`
2. [`cli-commands.ts`](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/cli-commands.ts#L110-L165)
3. [`commands/launch.ts`](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/commands/launch.ts#L25-L75)
4. `main.ts`, initially only `runRootCommand()` and its mode dispatch
5. `sdk.ts`, initially only the `createAgentSession()` skeleton, `ToolSession`, tool registry, system-prompt builder, and `new Agent`/`new AgentSession`
6. [`tools/index.ts`](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/tools/index.ts#L379-L419)

Before moving on, draw which object owns settings, model registry, session manager, tools, and messages. Explain why `sdk.ts` is a composition root rather than “the agent algorithm.”

### Stage 3: learn the smallest core loop

Read:

1. `packages/agent/src/agent.ts`: constructor, `prompt()`, and `#runLoop()`
2. [`packages/agent/src/agent-loop.ts`](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/agent/src/agent-loop.ts#L332-L415): entry functions
3. `runLoopBody()` around the nested loops and tool-call decision
4. `streamAssistantResponse()`
5. [`executeToolCalls()`](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/agent/src/agent-loop.ts#L1770-L1853) and its scheduler
6. [`packages/ai/src/stream.ts`](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/ai/src/stream.ts#L757-L850), then one provider adapter only

Before moving on, simulate on paper: user message → assistant tool call → tool result → assistant text. List the emitted events in order.

### Stage 4: master one vertical feature—read/edit

Read:

1. `tools/read.ts`, only the plain-file path
2. `packages/hashline/src/format.ts` and types
3. parser/tokenizer tests before the whole parser
4. [`apply.ts::applyEdits()`](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/hashline/src/apply.ts#L1224-L1330)
5. [`patcher.ts::prepare/commit`](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/hashline/src/patcher.ts#L280-L470)
6. [`recovery.ts`](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/hashline/src/recovery.ts#L47-L289)
7. coding-agent's hashline edit wrapper and tests

Before moving on, explain the difference between file tag, snapshot text, seen lines, anchor, and line map. Explain why bottom-up splice is correct.

### Stage 5: persistence and UI

Read:

1. [`docs/session.md`](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/docs/session.md)
2. `session-entries.ts`, `SessionEntryIndex`, append methods, and `session-context.ts`
3. [`docs/tui-runtime-internals.md`](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/docs/tui-runtime-internals.md)
4. `packages/tui/src/terminal.ts`, `stdin-buffer.ts`, then `tui.ts`
5. `coding-agent`'s event and input controllers; use `interactive-mode.ts` as a map, not a first read

Before moving on, reconstruct a branch path from sample `parentId`s. Explain why the TUI needs a final-row seam and why overlay composition happens after window slicing.

### Stage 6: study prewalk as a bounded feature

Read:

1. the [Stencil article](https://stencil.so/blog/prewalk)
2. the three `prewalk-*.md` prompt files
3. `Prewalk` and `#advancePrewalk()` in `agent-session.ts`
4. [`agent-session-prewalk.test.ts`](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/test/agent-session-prewalk.test.ts#L113-L300)
5. launch and slash-command arming paths
6. subagent prewalk tests if interested in reuse

Before moving on, draw the booleans after each turn for: read → prose plan → todo → edit → target response. Then draw the bash-only no-edit case and show why it terminates.

### Stage 7: choose an advanced branch

- IDE intelligence: `docs/tools/lsp.md` → `lsp/client.ts` → one action in `lsp/index.ts` → `lsp/edits.ts`.
- Debugging: `docs/tools/debug.md` → `dap/client.ts` → `dap/session.ts` → `tools/debug.ts`.
- Native performance: `packages/natives/native/loader-state.js` → `pi-natives/src/lib.rs` → `task.rs` → `glob.rs` or `grep.rs`.
- Long context: `docs/compaction.md` → compaction preparation/cut points → `session-context.ts` → `snapcompact`.
- Subagents: `docs/task-agent-discovery.md` → discovery/types → `TaskTool` → `task/executor.ts`.

## 16. Exercises, easy to hard

These are designed as small reimplementations or contained modifications. Work in a fork and run the nearest test file plus its full package checks.

### 1. Easy — recreate CLI launch fallback

Write a standalone TypeScript function that accepts `string[]`, a set of command names, and a table saying which flags consume values. Return a new vector that hoists a recognized command or prepends `launch`.

Add tests for:

- `['fix', 'the', 'bug']`;
- `['--approval-mode', 'yolo', 'acp']`;
- `['--', 'acp']`;
- `['@prompt.md']`.

**Teaches:** pure functions, argv parsing, data-driven dispatch, regression tests.

### 2. Easy — implement bottom-up line edits

Implement a tiny `applyEdits(text, edits)` supporting insert-before, insert-after, and delete by one-based line number. Apply buckets bottom-up and preserve authored order within one bucket.

Then deliberately implement top-down and write a test that proves it corrupts later indexes.

**Teaches:** array indexing, stable ordering, why edit algorithms separate coordinates from mutation.

### 3. Easy/medium — build an `EventStream`

Create an async-iterable queue with `push`, `end`, `fail`, and `result()`. Use it to stream fake `start`, `text_delta`, and `done` events from a timer. Add an abort signal.

**Teaches:** Promises, async iterators, producer/consumer contracts, cancellation, terminal events.

### 4. Medium — visualize a JSONL session branch

Given sample entries with `id` and `parentId`, build `byId` and `children` maps, find root-to-leaf paths, and render an ASCII tree with the active leaf marked. Add a compaction entry and produce two views: full transcript and model context.

**Teaches:** adjacency lists, parent pointers, append-only event sourcing, derived views.

### 5. Medium — strengthen and benchmark a snapshot tag

Reimplement `computeFileHash()` and generate random small files until a 16-bit collision appears. Then build a snapshot store keyed by path + tag and demonstrate why context validation still rejects a wrong snapshot. Compare token/character overhead for 4-, 8-, and 16-hex tags.

**Teaches:** hashes versus identity, birthday collisions, protocol tradeoffs, defense in depth.

### 6. Medium/hard — reimplement stale-line recovery

Using a line diff library, map unchanged old lines to current lines. Accept a patch only when every anchor maps, adjacent context is unchanged, and all anchors have one offset. Test:

- insertion before the target succeeds;
- target text modification fails;
- duplicate target lines without distinguishing neighbors fail;
- two anchors shifted differently fail.

**Teaches:** diff algorithms, ambiguity, invariants, fail-closed recovery.

### 7. Hard — extract prewalk into a pure reducer

Model prewalk as:

```ts
type State = {
  armed: boolean;
  planInjected: boolean;
  continuePending: boolean;
  todoSeen: boolean;
  switched: boolean;
}
```

Write `reducePrewalk(state, turn): {state, effects}` where effects can be `steerPlan`, `steerContinue`, `persist`, `scrub`, `switchModel`, or `steerChecklist`. Use table-driven tests for the real regression sequences: read/todo/write, write-before-todo, text-only after plan, and bash-only completion.

Then compare the reducer with `#advancePrewalk()` and list what still requires impure orchestration.

**Teaches:** finite-state machines, separating decisions from effects, property/table testing, feature extraction from a large class.

### 8. Hard — write a miniature exclusive/shared scheduler

Give tasks a duration and `shared`/`exclusive` mode. Reproduce omp's barrier semantics, record start/end timestamps, and assert:

- adjacent shared tasks overlap;
- an exclusive waits for all prior work;
- later shared tasks wait for the last exclusive;
- one rejection does not prevent accounting for every task.

Add cancellation and decide which tasks may be interrupted.

**Teaches:** Promise dependency graphs, barriers, `allSettled`, concurrency policy versus execution mechanism.

## 17. Questions to carry while studying

When a large file becomes overwhelming, ask these questions instead of reading every line equally:

1. What state does this module own, and what state is borrowed?
2. Which inputs are trusted, validated, normalized, or merely displayed?
3. What is the exact durable boundary?
4. Can this operation be replayed safely?
5. Which events cross the boundary, and in what order?
6. What happens on partial failure or cancellation?
7. Is a comment describing preflight atomicity, visibility atomicity, or actual rollback?
8. Is the model being given evidence, a summary of evidence, or a tool to obtain evidence?
9. Which behavior belongs to all providers and which leaks from one provider protocol?
10. What real failure report likely caused this branch to exist?

If you can answer those for CLI dispatch, the agent loop, hashline, session persistence, and prewalk, you understand the project's architectural core. The rest of the repository is mostly the same habits applied to more protocols and resources.

## 18. Source index

### Required sources

- [oh-my-pi GitHub repository, pinned research commit](https://github.com/can1357/oh-my-pi/tree/7b141199d524b859c357fc89654f10b62b9f3df1)
- [omp.sh](https://omp.sh/)
- [omp documentation](https://omp.sh/docs) and [sitemap](https://omp.sh/sitemap.xml)
- [Stencil: “You only need the frontier model for one single edit”](https://stencil.so/blog/prewalk)

### Repository documentation especially useful for continued study

- [Session storage and entry model](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/docs/session.md)
- [TUI runtime internals](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/docs/tui-runtime-internals.md)
- [Provider streaming internals](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/docs/provider-streaming-internals.md)
- [Compaction and branch summaries](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/docs/compaction.md)
- [Autonomous memory](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/docs/memory.md)
- [Bash tool runtime](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/docs/bash-tool-runtime.md)
- [LSP source guide](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/docs/tools/lsp.md)
- [Debug/DAP source guide](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/docs/tools/debug.md)
- [Task agent discovery and selection](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/docs/task-agent-discovery.md)

### Access note

The three required sources were all accessible. The omp docs are client-rendered; their sitemap and shipped documentation modules were used alongside the repository's source-of-truth internal docs. The Stencil page's normal web reader failed to render in one retrieval path, but its canonical Markdown at `https://stencil.so/blog/prewalk/index.md` was accessible and matched the requested article URL. No factual gap was filled by fabrication.
