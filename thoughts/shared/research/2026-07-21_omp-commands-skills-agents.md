# oh-my-pi commands, skills, and agents: a source-traced walkthrough

**Research date:** 2026-07-21  
**Source commit:** [`7b141199d524b859c357fc89654f10b62b9f3df1`](https://github.com/can1357/oh-my-pi/tree/7b141199d524b859c357fc89654f10b62b9f3df1)  
**Repository:** [`can1357/oh-my-pi`](https://github.com/can1357/oh-my-pi)  
**Public site:** [`omp.sh`](https://omp.sh/) (live, therefore not commit-pinned)

## 0. Scope, method, and authority

This report extends, rather than repeats, the architecture in [`2026-07-21_oh-my-pi-deep-dive.md`](./2026-07-21_oh-my-pi-deep-dive.md), especially its §§4, 5.2, 10.3, and 11. Those sections already establish the CLI/session composition root, the agent loop, the memory heuristic, and the existence of commands, skills, agents, extensions, and MCP. Here the question is narrower and more mechanical: **what bytes live on disk, what loader turns them into runtime objects, what wins on collision, what enters model context, and what happens after invocation?**

The authority order used throughout is:

1. Source code at the pinned commit.
2. Internal Markdown documentation at that same commit.
3. The live `omp.sh` site, only for product-level framing.

The public site says that `task` can fan work into isolated subagents with schema-validated yields and that `skill://<name>` exposes skill instructions through the ordinary read surface. Those are useful summaries, but the source decides the exact behavior. This matters because some pinned internal docs already lag the pinned implementation; the divergence ledger in §8 records every consequential mismatch found.

### 0.1 The triad in one picture

```text
human input
   |
   +-- /command --------> UI/ACP builtin or skill dispatch
   |                         |
   |                         +-- local state/action, OR
   |                         +-- expanded prompt -----------+
   |                                                       |
   +-- ordinary prompt ------------------------------------v
                                                   AgentSession.prompt()
                                                     | extension command
                                                     | TS/MCP custom command
                                                     | Markdown file command
                                                     | prompt template
                                                     v
                                                  model loop
                                                     |
                     system prompt lists skill metadata
                     skill body arrives through skill:// or /skill:
                                                     |
                                                     +-- model calls task
                                                            |
                                                            v
                                                   child AgentSession
                                                            |
                                              required yield + schema check
                                                            |
                                                            v
                                                   result to parent
```

The most important conceptual separation is this:

- A **command** is an input-routing mechanism. It may perform a local action or turn short syntax into a prompt.
- A **skill** is an instruction resource. Its metadata advertises when it may help; its body is read or injected when selected.
- An **agent definition** is a child-session policy and prompt. It becomes active only when the parent calls `task`.

None of the three is automatically “just a prompt,” although all three can eventually influence one.

---

## 1. Slash commands, end to end

### 1.1 There are four command families, not one

OMP uses the word “command” for several runtime shapes:

| Family | Authored as | Runtime behavior | Primary loader/dispatcher |
|---|---|---|---|
| Builtin | TypeScript registry entry | Local action and/or returned prompt | `builtin-registry.ts` + surface controller |
| Extension | TypeScript extension registration | Arbitrary handler with session/UI context | `ExtensionRunner` + `AgentSession` |
| Custom | TypeScript module, plus MCP prompt commands | Arbitrary action or returned prompt string | custom-command loader + `AgentSession` |
| File-based | Markdown file | Body expansion into an ordinary prompt | capability discovery + `expandSlashCommand()` |

The internal guide makes the same broad split and also documents provider priorities and discovery paths ([`docs/slash-command-internals.md` L21-L48](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/docs/slash-command-internals.md#L21-L48)). The source is more useful for understanding where the families meet.

### 1.2 Builtin registry: what one entry contains

The public shape is `BuiltinSlashCommand`. Its core fields are ([`slash-commands/types.ts` L14-L27](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/slash-commands/types.ts#L14-L27)):

```ts
interface BuiltinSlashCommand {
  name: string;
  aliases?: readonly string[];
  description: string;
  allowArgs?: boolean;
  subcommands?: readonly ...[];
  inlineHint?: string;
  getTuiDescription?: (...) => string | undefined;
}
```

The executable registry uses a richer `SlashCommandSpec`, adding `handle` and `handleTui` callbacks ([`slash-commands/types.ts` L88-L136](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/slash-commands/types.ts#L88-L136)). This separation is deliberate: UI and ACP consumers can materialize metadata without exposing each callback.

Registration is literal data: `BUILTIN_SLASH_COMMAND_REGISTRY` is an array of specs ([`builtin-registry.ts` L206-L235](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/slash-commands/builtin-registry.ts#L206-L235)). Near the bottom, the file builds a lookup map containing both canonical names and aliases ([`builtin-registry.ts` L2336-L2344](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/slash-commands/builtin-registry.ts#L2336-L2344)), and separately materializes display metadata ([`builtin-registry.ts` L2511-L2560](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/slash-commands/builtin-registry.ts#L2511-L2560)).

Execution is centralized in `executeBuiltinSlashCommand()` ([`builtin-registry.ts` L2569-L2623](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/slash-commands/builtin-registry.ts#L2569-L2623)):

1. Parse the leading slash command.
2. Look up canonical name or alias.
3. Reject arguments unless `allowArgs` is true.
4. Apply collaboration-guest restrictions.
5. Prefer the TUI handler when a TUI context exists.
6. Otherwise adapt the generic handler.
7. Return either “consumed” or a prompt that should continue through normal processing.

The builtin parser treats either the first whitespace **or a colon** as the name boundary. Thus `/foo bar` and `/foo:bar` both select `foo`; the rest is the argument string ([`helpers/parse.ts` L17-L35](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/slash-commands/helpers/parse.ts#L17-L35)). A `BuiltinCommandResult` is explicitly either `{ consumed: true }` or `{ prompt: string }` ([`slash-commands/types.ts` L36-L48](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/slash-commands/types.ts#L36-L48)).

### 1.3 The real interception order—and the important correction

It is tempting to describe the order as “extension → custom → file → builtin inside `AgentSession.prompt()`.” That is incorrect. **Builtins are normally intercepted by the input surface before `AgentSession.prompt()` is called.**

In the interactive TUI, `InputController` tries a builtin, then a skill invocation, and only later calls `session.prompt()` ([`input-controller.ts` L674-L732](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/modes/controllers/input-controller.ts#L674-L732), [`input-controller.ts` L784-L800](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/modes/controllers/input-controller.ts#L784-L800)). Its idle/follow-up route preserves the same builtin-then-skill order before prompting ([`input-controller.ts` L1278-L1335](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/modes/controllers/input-controller.ts#L1278-L1335)). ACP reverses those first two surface checks—skill, then ACP-supported builtin—before it too calls `session.prompt()` ([`acp-agent.ts` L792-L838](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/modes/acp/acp-agent.ts#L792-L838)). ACP has a filtered builtin set because some commands require TUI-only capabilities ([`acp-builtins.ts` L8-L69](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/slash-commands/acp-builtins.ts#L8-L69)).

Once text reaches `AgentSession.prompt()`, the order is exactly ([`agent-session.ts` L8649-L8692](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/session/agent-session.ts#L8649-L8692)):

1. **Extension command.** If handled, return `false`; no model turn is expected.
2. **TypeScript custom command**, with MCP prompt commands as a fallback in that same stage. If it returns `undefined`, stop. If it returns a string, replace the input.
3. **File-based slash command**, but only if the possibly transformed text still starts with `/`.
4. **Prompt-template expansion.** This is a separate, later templating layer.
5. Queue as steer/follow-up if already streaming, or construct the user message and enter the agent loop.

Therefore collision precedence is surface-sensitive:

- A supported builtin generally wins because the surface consumes it before the session sees it.
- Among commands that reach `AgentSession.prompt()`, extension wins over custom, and custom wins over file.
- A custom command can intentionally return another slash-prefixed string; then file expansion still gets a chance.
- An unknown slash name is not an error at this layer. If no expansion recognizes it, it proceeds as ordinary text ([`docs/slash-command-internals.md` L209-L215](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/docs/slash-command-internals.md#L209-L215)).

The combined “available commands” list is **display metadata, not the execution algorithm**. It deduplicates in the order builtin, skill, extension, custom, file ([`available-commands.ts` L31-L97](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/slash-commands/available-commands.ts#L31-L97)). Do not infer session dispatch from that list.

### 1.4 File-command discovery and on-disk format

The native project locations are:

```text
<project>/.omp/commands/*.md
~/.omp/agent/commands/*.md
```

OMP also imports compatible commands from Claude, Codex, OpenCode, Agents, and installed OMP plugins. The full path table is in [`docs/slash-command-internals.md` L60-L107](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/docs/slash-command-internals.md#L60-L107). Providers have numeric priority; native is 100, OMP plugins 90, Claude 80, Claude plugins and Agents 70, Codex 70, and OpenCode 55. A tie is broken by registration order ([`docs/slash-command-internals.md` L29-L39](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/docs/slash-command-internals.md#L29-L39)).

The generic capability manager loads providers concurrently, then flattens them in provider order; its first-seen name wins and later entries are marked shadowed ([`capability/index.ts` L101-L205](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/capability/index.ts#L101-L205)). Native discovery explicitly searches project configuration before the user agent directory ([`discovery/builtin.ts` L329-L359](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/discovery/builtin.ts#L329-L359)). This gives a project-native file the first position within the highest-priority native provider.

A file command is intentionally small:

```md
---
description: Prepare release notes for a version
---

Prepare release $ARGUMENTS.
Check the changelog and tests, then summarize any blockers.
```

The runtime item has a command name, description, Markdown body, source path, and source metadata ([`capability/slash-command.ts` L12-L40](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/capability/slash-command.ts#L12-L40)). The filename supplies the command name. The loader parses `description` from YAML frontmatter and retains the body ([`extensibility/slash-commands.ts` L37-L107](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/extensibility/slash-commands.ts#L37-L107)).

Arguments use a small shell-like tokenizer: whitespace separates tokens, single and double quotes preserve spaces, escapes are not interpreted, and an unmatched quote simply runs to end of input ([`utils/command-args.ts` L1-L32](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/utils/command-args.ts#L1-L32)). Substitution supports:

- `$1`, `$2`, … for positional arguments;
- `$@` and `$ARGUMENTS` for all arguments;
- `$@[start]` and `$@[start:length]` for slices.

Substitution is a single, non-recursive pass ([`utils/command-args.ts` L34-L76](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/utils/command-args.ts#L34-L76)). `expandSlashCommand()` matches the name, parses the remaining arguments, substitutes the body, and returns the rendered prompt ([`extensibility/slash-commands.ts` L113-L130](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/extensibility/slash-commands.ts#L113-L130)). It does **not** execute shell commands merely because the Markdown contains command-looking text.

### 1.5 TypeScript custom commands

Custom commands are trusted executable modules. A `CustomCommand` has `name`, optional `description` and argument metadata, and an `execute(args, context)` method that returns either a prompt string or `void` ([`custom-commands/types.ts` L78-L98](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/extensibility/custom-commands/types.ts#L78-L98)). Each command is a child directory containing `index.ts`, `index.js`, `index.mjs`, or `index.cjs`; the loader dynamically imports the module, accepts a default command or factory, and validates the exported shape ([`custom-commands/loader.ts` L31-L65](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/extensibility/custom-commands/loader.ts#L31-L65), [`custom-commands/loader.ts` L83-L139](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/extensibility/custom-commands/loader.ts#L83-L139)). Bundled modules load first; user/project modules may override a bundled name, while user/project conflicts are reported and first-loaded wins ([`custom-commands/loader.ts` L174-L242](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/extensibility/custom-commands/loader.ts#L174-L242)).

At runtime, `#tryExecuteCustomCommand()` looks in loaded TS commands first and MCP prompt commands second, tokenizes arguments, and calls `execute()` ([`agent-session.ts` L9153-L9197](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/session/agent-session.ts#L9153-L9197)). A returned string replaces the input and enters the ordinary prompt path. `undefined` means the command performed its action itself, so the turn is consumed. Errors are logged/emitted and also consume the command rather than sending broken syntax to the model.

The bundled `/review` is a concrete example: it gathers review choices in interactive mode, builds a review instruction string, and returns that prompt ([`custom-commands/bundled/review/index.ts` L475-L489](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/extensibility/custom-commands/bundled/review/index.ts#L475-L489), [`custom-commands/bundled/review/index.ts` L492-L633](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/extensibility/custom-commands/bundled/review/index.ts#L492-L633)). The TypeScript does the deterministic UI work; the model receives the resulting review task.

### 1.6 Extension commands

An extension registers a named handler. When multiple extensions register the same name, the runner searches extensions from last to first, so the latest loaded registration wins ([`extensions/runner.ts` L502-L534](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/extensibility/extensions/runner.ts#L502-L534)). `AgentSession` parses the first space, obtains an extension command context, and awaits the handler ([`agent-session.ts` L9050-L9077](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/session/agent-session.ts#L9050-L9077)). The handler can change sessions, compact, reload, query/set state, emit UI, or schedule work through the context ([`agent-session.ts` L9080-L9142](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/session/agent-session.ts#L9080-L9142)). It is always considered consumed, even when it throws; the extension error channel receives the failure.

### 1.7 Three complete walks

#### Walk A: trivial builtin `/exit`

1. The registry entry names `exit`, describes it, disallows arguments, and binds the TUI shutdown handler ([`builtin-registry.ts` L1737-L1740](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/slash-commands/builtin-registry.ts#L1737-L1740)).
2. The TUI controller recognizes it before `AgentSession.prompt()`.
3. `executeBuiltinSlashCommand()` validates the no-argument contract and selects `handleTui`.
4. `shutdownHandlerTui` clears the editor, calls `ctx.shutdown()`, and returns “consumed” ([`builtin-registry.ts` L143-L147](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/slash-commands/builtin-registry.ts#L143-L147)).
5. No prompt is created and no model turn occurs. This is a **direct local action**.

#### Walk B: stateful builtin `/prewalk`

1. The registry accepts no user arguments. Its handler resolves the `@smol` role, resolves that role to an actual model, checks credentials, and calls `session.armPrewalk(...)` ([`builtin-registry.ts` L467-L488](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/slash-commands/builtin-registry.ts#L467-L488)).
2. `armPrewalk()` stores the target model, marks the plan nudge and continuation as armed, immediately steers a hidden planning message into the live agent, and emits a notice ([`agent-session.ts` L2487-L2519](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/session/agent-session.ts#L2487-L2519)). The command itself is consumed; the steering message, not the slash text, reaches the loop.
3. At each assistant-turn boundary, `#advancePrewalk()` observes successful tools. A successful `todo` opens a gate; then the first successful `edit` or `write` becomes the switch point ([`agent-session.ts` L2396-L2445](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/session/agent-session.ts#L2396-L2445)). If `todo` is not an active tool, the gate is treated as already open.
4. On the switch, OMP waits for transcript persistence, removes the temporary plan nudge from live model context, changes to the target model, clears the one-shot state, emits a notice, and steers a hidden verification checklist ([`agent-session.ts` L2458-L2484](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/session/agent-session.ts#L2458-L2484)).

This is a **direct state mutation that later injects steering and changes model selection**. It is much more than prompt text.

#### Walk C: repository file command `/release "3.13.0"`

The repository contains a real native command at [`.omp/commands/release.md` L1-L41](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/.omp/commands/release.md#L1-L41).

1. Native project discovery finds `.omp/commands/release.md` and derives the name `release`.
2. The loader parses its description and body; capability precedence determines whether it is shadowed.
3. The user enters `/release "3.13.0"`. No builtin/skill consumes it, and no extension/custom command with that name wins.
4. `expandSlashCommand()` parses one argument, `3.13.0`, then replaces `$ARGUMENTS` in the Markdown body.
5. Prompt-template expansion runs after command expansion.
6. If idle, the expanded text becomes the user message. If streaming, `AgentSession.prompt()` queues it as either a steer or follow-up according to `streamingBehavior` ([`agent-session.ts` L8711-L8726](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/session/agent-session.ts#L8711-L8726)).

This is **prompt expansion**. The command body may instruct the model to run tools, but the expansion code itself performs no release action.

### 1.8 How output re-enters—or does not re-enter—the loop

| Command result | Example | What happens next |
|---|---|---|
| Consumed local action | `/exit` | No model call |
| Consumed state change + steering | `/prewalk` | Hidden custom messages steer current/future turns |
| Builtin returns prompt | e.g. the `/loop` family can return `{prompt}` | Surface sends returned prompt through the normal session path ([`builtin-registry.ts` L312-L330](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/slash-commands/builtin-registry.ts#L312-L330)) |
| Custom TS returns string | `/review` | String replaces slash text, then file/template expansion and model delivery continue |
| Custom TS returns `void` | a settings UI command | Consumed; handler owns all effects |
| File command | `/release` | Expanded Markdown becomes the prompt |
| Command arrives while streaming | extension vs text-producing command | Extension executes immediately; resulting text is queued as steer/follow-up ([`docs/slash-command-internals.md` L217-L235](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/docs/slash-command-internals.md#L217-L235)) |

---

## 2. Skills, end to end

### 2.1 On-disk contract

An authored skill is a directory containing a non-recursively discovered `SKILL.md`:

```text
.omp/skills/
└── test-helper/
    ├── SKILL.md
    ├── examples.md       # optional supporting resource
    └── scripts/          # optional resources/tools referenced by the body
```

The documented frontmatter fields are ([`docs/skills.md` L50-L70](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/docs/skills.md#L50-L70)):

| Field | Type | Meaning at this commit |
|---|---|---|
| `name` | string | Invocation and `skill://` identity; directory name is a fallback in discovery |
| `description` | string | Model-facing selection hint; some providers require it |
| `globs` | string or string[] | Parsed metadata for file-pattern applicability |
| `alwaysApply` | boolean | Parsed metadata indicating intended automatic applicability |
| `hide` | boolean | Omit from model-facing skill listing |
| `disableModelInvocation` | boolean | Mapped by the pinned loader to the runtime `hide` flag: suppresses model-facing advertising while retaining exact/direct access; it is not a protocol-level deny |
| `enabled` | boolean | Source-supported discovery switch: `false` skips the file ([`discovery/helpers.ts` L376-L381](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/discovery/helpers.ts#L376-L381)) |

Unknown frontmatter keys are preserved. The normalized capability type contains name, description, body/file metadata, `globs`, `alwaysApply`, `hide`, and `disableModelInvocation` ([`capability/skill.ts` L12-L50](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/capability/skill.ts#L12-L50)). Runtime validation itself is intentionally light: name and path are the essential checks ([`capability/skill.ts` L52-L62](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/capability/skill.ts#L52-L62)).

### 2.2 Discovery locations and precedence

Native discovery walks ancestor projects for `.omp/skills`, with the closest project first, then the active user profile, then managed skills ([`discovery/builtin.ts` L271-L327](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/discovery/builtin.ts#L271-L327)). Cross-ecosystem providers also import compatible skills. The documented global order is native project/user, Claude, Codex, Gemini, Cursor, Windsurf, Copilot, Cline, and plugin sources, subject to settings toggles and the capability provider priorities ([`docs/skills.md` L71-L126](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/docs/skills.md#L71-L126)).

Within one skills directory, the scanner:

1. reads immediate child directories only;
2. looks for `SKILL.md` in each;
3. parses frontmatter;
4. skips `enabled: false`;
5. falls back to the directory name when `name` is absent;
6. returns deterministic sorted results.

See [`discovery/helpers.ts` L329-L419](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/discovery/helpers.ts#L329-L419). The runtime loader applies source toggles and custom directories, filters disabled capabilities, and adds managed skills last ([`extensibility/skills.ts` L123-L247](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/extensibility/skills.ts#L123-L247), [`extensibility/skills.ts` L249-L380](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/extensibility/skills.ts#L249-L380)). As with commands, first unshadowed capability wins after provider ordering.

### 2.3 What enters context, and when

Authored skills use **progressive disclosure**:

1. **System prompt: metadata only.** If `read` is active, OMP lists non-hidden skill names and descriptions and tells the model to read `skill://<name>` when one matches ([`system-prompt.ts` L758-L817](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/system-prompt.ts#L758-L817), [`system-prompt.md` L26-L34](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/prompts/system/system-prompt.md#L26-L34)). The full body is not copied into the base system prompt.
2. **Model-chosen read.** The model selects a skill semantically from the descriptions and calls the ordinary read surface on `skill://name`.
3. **Explicit user invocation.** `/skill:name optional arguments` resolves the named skill, reads and strips frontmatter from `SKILL.md`, wraps the full body with base-directory and argument context, and sends a user-attributed custom message ([`extensibility/skills.ts` L383-L511](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/extensibility/skills.ts#L383-L511), [`modes/skill-command.ts` L36-L90](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/modes/skill-command.ts#L36-L90)).
4. **Subagent autoload.** An agent definition may name `autoloadSkills`; the child receives each selected body as a hidden custom message before its first prompt (§3.5).

The explicit-user wrapper says that the user invoked the skill and includes its path, body, and arguments ([`prompts/skills/user-invocation.md` L1-L11](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/prompts/skills/user-invocation.md#L1-L11)). The subagent autoload wrapper contains the same operational data but does not falsely claim user invocation ([`prompts/skills/autoload.md` L1-L8](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/prompts/skills/autoload.md#L1-L8)).

#### Is a skill always on, name-triggered, or model-chosen?

All three ideas exist, but at different layers:

- Every visible skill's **metadata** is effectively always available in the system prompt when the `read` tool is active.
- `/skill:name` is a deterministic, name-triggered user invocation.
- `skill://name` is a deterministic read once selected.
- Ordinary selection is model-chosen from the name/description list.
- `autoloadSkills` is definition-chosen for a subagent.
- `alwaysApply` and `globs` are parsed and retained, but the pinned system-prompt path does not itself splice matching bodies into context. They should not be read as “the body is always in the system prompt.”
- `hide` removes the skill from model advertising. At this commit `disableModelInvocation` is normalized to the same runtime `hide` flag ([`extensibility/skills.ts` L104-L108](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/extensibility/skills.ts#L104-L108)). The exact name remains resolvable through `skill://` and `/skill:`, so this is discoverability control rather than a hard invocation deny.

### 2.4 `skill://` is a guarded file view

The protocol handler resolves the host to an active skill, returns `SKILL.md` for the bare URL, and permits resources below the skill directory for paths such as `skill://test-helper/examples.md` ([`skill-protocol.ts` L41-L103](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/internal-urls/skill-protocol.ts#L41-L103)). It rejects:

- absolute paths;
- normalized `..` traversal;
- any resolved path outside the skill base directory;
- nonexistent or non-file/non-directory targets.

Those checks are explicit at [`skill-protocol.ts` L24-L36](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/internal-urls/skill-protocol.ts#L24-L36) and [`skill-protocol.ts` L64-L93](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/internal-urls/skill-protocol.ts#L64-L93). This is a read boundary, not a sandbox for whatever instructions the Markdown contains.

### 2.5 Interaction with `rebuildSystemPrompt()`

The SDK composition root gives the session a `rebuildSystemPrompt` callback. The callback rebuilds against the current active tools and the session's current skills snapshot ([`sdk.ts` L2461-L2560](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/sdk.ts#L2461-L2560)). This is important because skill advertising depends on tool availability: without `read`, the prompt should not promise `skill://` access.

`AgentSession.refreshSkills()` resets capabilities, rediscovers disk-backed skills, replaces the session's skills/warnings, updates the global active set for a main agent, rebuilds the base system prompt, and refreshes command metadata ([`agent-session.ts` L7522-L7547](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/session/agent-session.ts#L7522-L7547)). `refreshBaseSystemPrompt()` calls the supplied builder and installs the new prompt on the agent ([`agent-session.ts` L7620-L7644](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/session/agent-session.ts#L7620-L7644)). Active-tool presentation changes also trigger rebuilds when the tool signature changes ([`agent-session.ts` L7433-L7460](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/session/agent-session.ts#L7433-L7460)).

So a skill edit is not magical live context mutation. OMP must refresh/reload skills; rebuilding changes the metadata list. The body still arrives only through explicit invocation, a model read, or subagent autoload.

### 2.6 Worked bundled skill: `semantic-compression`

The repository ships this project-native skill at [`.omp/skills/semantic-compression/SKILL.md` L1-L66](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/.omp/skills/semantic-compression/SKILL.md#L1-L66). Its complete frontmatter is:

```yaml
---
name: semantic-compression
description: Use when asked to shorten, simplify, or tighten code while preserving behavior, or when reviewing code for semantic compression opportunities.
---
```

Field by field:

- `---` opens and closes YAML frontmatter. It is metadata, not part of the invoked instruction body.
- `name` creates the exact lookup key `semantic-compression`, hence `skill://semantic-compression` and `/skill:semantic-compression`.
- `description` is the selection contract shown to the model. It names both the trigger (“shorten, simplify, or tighten”) and the safety property (“preserving behavior”).
- There is no `hide`, so it is advertised.
- There is no `disableModelInvocation`, so model selection is allowed.
- There is no `alwaysApply` or `globs`; selection is semantic, not tied to every turn or a filename pattern.

The body begins:

```md
# Semantic Compression

Make code shorter by making each remaining line carry more meaning, not by golfing.

## Core Principle

Prefer fewer concepts over fewer characters. Preserve behavior exactly unless the user explicitly asks for a change.
```

It then gives a sequence: understand behavior, identify redundancy, compress safely, and verify; it closes with patterns and anti-patterns. Those headings and lists are ordinary Markdown instructions. They are not parsed into runtime fields. When the model reads `skill://semantic-compression`, it receives the file content; when the user invokes `/skill:semantic-compression`, OMP strips the YAML wrapper and places the body inside the invocation template.

This skill is a good teaching example because its metadata is concise enough to select correctly while the body holds the detailed procedure. Copying the entire procedure into the system prompt would waste tokens on unrelated turns; progressive disclosure avoids that.

### 2.7 Authored skills versus memory-generated “skill playbooks”

OMP's hindsight-memory consolidation can generate files named `skills/<name>/SKILL.md`, but those are **not the same discovery channel as authored skills**.

The memory lifecycle is:

1. Startup injects a compact memory summary plus `memory://` navigation hints, but skips disabled, subagent, and ephemeral sessions ([`memories/index.ts` L118-L224](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/memories/index.ts#L118-L224)).
2. Consolidation asks a model for a strict JSON object containing updated memory, summary, and reusable skill playbooks ([`prompts/memories/consolidation.md` L1-L30](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/prompts/memories/consolidation.md#L1-L30)).
3. The implementation calls the consolidation model and strictly parses its response ([`memories/index.ts` L850-L924](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/memories/index.ts#L850-L924)).
4. It writes `MEMORY.md`, `memory_summary.md`, playbook `SKILL.md` files, and optional scripts/templates/examples under the **memory root**, while pruning stale generated artifacts ([`memories/index.ts` L927-L980](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/memories/index.ts#L927-L980)).
5. The output is schema-validated, sensitive text is redacted, names are sanitized, and every output path is checked against the memory root ([`memories/index.ts` L1025-L1178](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/memories/index.ts#L1025-L1178)).

The crucial distinction:

| Authored/managed skill | Memory-generated playbook |
|---|---|
| Lives in a discovered skills directory | Lives beneath the memory store |
| Has authored YAML metadata and a stable selection description | Is model-produced consolidation output; frontmatter is not the discovery contract |
| Listed in the skill section of the system prompt | Reached through `memory://root/...` and the memory summary heuristic |
| Read with `skill://name` | Read through `memory://...` |
| Source/provider precedence applies | Memory schema, redaction, and path guards apply |

There is a second feature called **managed skills**, loaded last from OMP's managed-skill location ([`extensibility/skills.ts` L315-L380](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/extensibility/skills.ts#L315-L380)). Those *are* ordinary discovered skills. Do not conflate managed skills with memory playbooks merely because both may be machine-produced.

---
## 3. Agents and the `task` tool, end to end

### 3.1 An agent definition is policy plus prompt

Agent files use YAML frontmatter followed by the child's system-prompt instructions. The normalized `AgentDefinition` contains ([`task/types.ts` L349-L367](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/task/types.ts#L349-L367)):

| Field | Type | Effect |
|---|---|---|
| `name` | string | Stable name used by `task` and discovery deduplication |
| `description` | string | Parent-model-facing routing hint |
| body / `systemPrompt` | Markdown | Child's role, method, and constraints |
| `tools` | string[] | Child tool allowlist; `yield` is added automatically |
| `spawns` | `*` or string[] | Agent names this child may delegate to |
| `model` | string or string[] | Model/role preference or fallback list |
| `thinkingLevel` | configured level | Child reasoning setting |
| `output` | unknown schema object | Definition-level structured yield contract |
| `blocking` | boolean | Whether the task must run synchronously/block its caller |
| `autoloadSkills` | string[] | Skill bodies injected before the child's first task prompt |
| `readSummarize` | boolean | Whether long reads are summarized for this agent |
| `prewalk` | boolean or string | Optional prewalk behavior/model target |
| `source`, `filePath` | runtime metadata | Discovery provenance and diagnostics |

The parser requires `name` and `description`; accepts CSV or YAML arrays for `tools`, `spawns`, models, and autoloaded skills; accepts `spawns: "*"`; normalizes aliases such as `thinking-level`; parses booleans; and adds `yield` to the tool list ([`discovery/helpers.ts` L223-L312](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/discovery/helpers.ts#L223-L312)). If `tools` contains `task` and `spawns` is not declared, the parser can infer broad spawn capability; declare `spawns` explicitly when containment matters.

An example definition with every policy-oriented field is:

```md
---
name: api-scout
description: Locate API implementation paths and return a typed inventory.
tools: [read, grep, glob]
spawns: []
model: ["@smol", "@default"]
thinking-level: medium
blocking: false
read-summarize: false
prewalk: false
autoloadSkills: [test-helper]
output:
  type: object
  properties:
    summary: { type: string }
    files:
      type: array
      elements:
        type: object
        properties:
          path: { type: string }
          purpose: { type: string }
        required: [path, purpose]
  required: [summary, files]
---

Trace the API from route to implementation. Read only what is necessary.
Yield the requested object; do not merely print JSON in prose.
```

The `output` grammar here is JTD-style, matching bundled definitions. It is carried as an object rather than flattened into prompt prose.

### 3.2 Discovery and collision precedence

At the pinned commit, `discoverAgents()` searches in this order ([`task/discovery.ts` L61-L137](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/task/discovery.ts#L61-L137)):

1. nearest project `.omp/agents`;
2. active user-profile agents;
3. OMP extension-package agent roots, ordered by their configured/package precedence;
4. Claude plugin agents, project plugins before user plugins;
5. bundled agents.

Each directory is sorted lexicographically and malformed external files are warned about and skipped ([`task/discovery.ts` L42-L59](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/task/discovery.ts#L42-L59)). Loads may be concurrent, but results are flattened in the declared source order and a `Map` retains the first agent of each name. A project definition therefore overrides the same user, plugin, or bundled name. Bundled definitions are parsed from embedded Markdown and treated as fatal build data rather than optional user data ([`task/agents.ts` L43-L73](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/task/agents.ts#L43-L73), [`task/agents.ts` L103-L139](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/task/agents.ts#L103-L139)).

This is one place where source beats pinned docs: the implementation includes OMP extension-package agents, while the older discovery document omits that tier. See §8.

### 3.3 Parent invocation: the wire contract

The parent does not execute an agent file directly. Its model calls the `task` tool. The input supports both a single task and batches, with fields including agent name, task text, shared context, per-spawn `outputSchema`, `schemaMode`, and isolation ([`task/types.ts` L112-L172](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/task/types.ts#L112-L172)). A representative call is:

```json
{
  "context": "We are tracing request authentication at commit X.",
  "tasks": [
    {
      "agent": "api-scout",
      "task": "Find the route, middleware, and token verifier.",
      "outputSchema": {
        "type": "object",
        "properties": {
          "summary": { "type": "string" },
          "files": { "type": "array", "items": { "type": "string" } }
        },
        "required": ["summary", "files"]
      },
      "schemaMode": "strict",
      "isolated": false
    }
  ]
}
```

The tool validates and normalizes the request, discovers agent definitions, performs asynchronous preflight, and registers/runs jobs ([`task/index.ts` L622-L774](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/task/index.ts#L622-L774)). Each normalized spawn eventually calls `runStructuredSubagent()` ([`task/index.ts` L1363-L1407](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/task/index.ts#L1363-L1407)).

Schema precedence is based on **property presence**, not truthiness: a caller-supplied schema wins if that property exists, then the agent definition's `output`, then a session-level schema, then none ([`structured-subagent.ts` L170-L181](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/task/structured-subagent.ts#L170-L181)). This permits a caller to make the contract specific to one use without editing the reusable role.

### 3.4 Preflight constraints

Before a child session exists, shared policy resolves the effective definition and rejects or narrows unsafe/invalid requests ([`structured-subagent.ts` L209-L312](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/task/structured-subagent.ts#L209-L312)):

- **Agent allowlist:** the parent definition's `spawns` restricts which named agents it may launch. `*` is broad; a list is exact.
- **Depth:** recursion is capped by session/config policy. At the maximum depth, the child loses `task` even if declared.
- **Disabled agents:** configuration can refuse an otherwise discovered definition.
- **Model policy:** agent preferences are resolved through model-role aliases and available credentials; call/session overrides are reconciled.
- **Output contract:** the effective schema is prepared before execution.
- **Plan mode:** plan-mode children are forced to a read-only tool set: `read`, `grep`, `glob`, `web_search`, plus `ast_grep` when available; `spawns` and prewalk are cleared ([`structured-subagent.ts` L184-L193](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/task/structured-subagent.ts#L184-L193)).
- **Isolation:** the request and settings determine whether a separate worktree/backend is prepared.
- **Coordination features:** LSP and IRC availability are resolved rather than assumed.

These are capability constraints, not merely reminders in the child's prompt. A child cannot call a tool omitted from its constructed tool registry.

### 3.5 `createAgentSession()` composition for the child

`runStructuredSubagent()` first assembles inherited state: all parent-discovered skills, the exact autoload subset, the parent's MCP manager, relevant context files, prompts, rules, extension/custom-tool configuration, memory state, and parent/depth identifiers ([`structured-subagent.ts` L351-L430](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/task/structured-subagent.ts#L351-L430)). Missing names in `autoloadSkills` are filtered out rather than synthesized ([`structured-subagent.ts` L351-L356](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/task/structured-subagent.ts#L351-L356)).

The executor then composes the actual child:

1. Resolve read summarization, request budgets, depth, and effective tools ([`executor.ts` L2218-L2278](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/task/executor.ts#L2218-L2278)).
2. Auto-add `task` only when the definition permits spawns and depth remains; remove it at max depth. Add the coordination hub where policy allows. Expand compound capabilities such as `exec` into their actual tools.
3. Resolve prewalk and working-directory/worktree state ([`executor.ts` L2447-L2498](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/task/executor.ts#L2447-L2498)).
4. Build `createAgentSession()` options: model and thinking level; exact tool names; required output schema; child restrictions; `requireYieldTool: true`; inherited context/skills/prompts/rules; the agent body's system-prompt addition; parent IDs/depth; worktree; MCP proxy tools; and no child TUI ([`executor.ts` L2540-L2617](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/task/executor.ts#L2540-L2617)).
5. Initialize the child transcript/session file, initialize child extension instances, and remove inappropriate inherited state such as the parent's ordinary todo list ([`executor.ts` L2655-L2748](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/task/executor.ts#L2655-L2748)).
6. Inject each autoloaded skill body as a hidden custom message before the first prompt ([`executor.ts` L2753-L2767](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/task/executor.ts#L2753-L2767)).
7. Prompt the child with shared context plus its specific task and drive it until a valid `yield` or terminal failure ([`executor.ts` L2769-L2879](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/task/executor.ts#L2769-L2879)).

This reuse of `createAgentSession()` is why subagents get the same core loop, provider/model plumbing, extension hooks, internal URLs, and transcript machinery as the parent. The difference is the deliberately narrowed composition object.

### 3.6 Budgets, depth, and worktrees

Subagents have request-count budgets. The executor defines cheaper defaults for `scout`/`sonic`, a larger generic budget, warning thresholds, a hard multiplier, and a small grace window ([`executor.ts` L80-L101](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/task/executor.ts#L80-L101)). Settings can alter behavior, so those constants should be read as fallback policy rather than a promise that every run stops at one fixed number.

Depth is enforced twice: preflight refuses disallowed delegation, and tool assembly removes `task` at the maximum depth. This defense in depth prevents a persuasive prompt body from restoring an absent capability.

For isolated jobs, `runStructuredSubagent()` prepares an isolation backend/worktree, runs the child there, then merges or reports merge failure according to policy ([`structured-subagent.ts` L527-L619](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/task/structured-subagent.ts#L527-L619)). Sibling workers therefore do not have to edit the same checkout. Isolation is still not a security sandbox: a child with network or process tools has those capabilities inside its execution environment.

### 3.7 Yield and schema validation

Every structured child receives a `yield` tool. The wrapper distinguishes a final result from incremental progress and sectioned results ([`yield.ts` L19-L38](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/tools/yield.ts#L19-L38), [`yield.ts` L77-L151](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/tools/yield.ts#L77-L151)). When an output schema exists, the tool wraps that schema in the required yield envelope and builds a validator ([`yield.ts` L154-L192](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/tools/yield.ts#L154-L192), [`yield.ts` L233-L307](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/tools/yield.ts#L233-L307)).

On execution it validates:

1. the yield wrapper and type;
2. progress/section semantics;
3. the result against the effective schema;
4. retry count and strict/permissive mode.

Invalid final yields return model-visible correction errors and permit retries, with a bounded retry policy ([`yield.ts` L195-L210](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/tools/yield.ts#L195-L210), [`yield.ts` L310-L420](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/tools/yield.ts#L310-L420)). Sectioned yields are assembled deterministically before final validation ([`yield-assembly.ts` L120-L198](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/task/yield-assembly.ts#L120-L198)).

The executor does not passively wait forever. `driveSessionToYield()` sends the task, detects an assistant stop without yield, and issues up to three increasingly forceful reminders, ending with a forced `yield` tool choice ([`executor.ts` L1654-L1821](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/task/executor.ts#L1654-L1821)). Finalization assembles and revalidates results; strict mode rejects an invalid/missing contract, while permissive paths can surface warnings/fallback text ([`executor.ts` L489-L670](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/task/executor.ts#L489-L670)).

The teaching lesson is that “tell the child to return JSON” is not the contract. The contract is the schema attached to a required tool whose output is validated both at call time and finalization.

### 3.8 Result surfacing to the parent

For a synchronous task, the tool result includes a concise summary/preview and structured details containing agent identity, status, artifacts, and structured output ([`task/index.ts` L1422-L1478](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/task/index.ts#L1422-L1478)). The parent model sees that tool result in its own loop and can use the structured object without scraping the child's prose.

For an asynchronous task, the initial call reports that jobs were spawned; the job manager later delivers the completed text/details into the parent session ([`task/index.ts` L1016-L1180](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/task/index.ts#L1016-L1180)). Full artifacts remain addressable through `agent://<id>`, and child transcripts through `history://<id>`. The preview is for model economy, not the only copy.

### 3.9 MCP proxy tools without duplicate connections

The parent passes its existing `MCPManager` into child composition ([`structured-subagent.ts` L371-L413](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/task/structured-subagent.ts#L371-L413)). The executor asks that manager for its discovered tools and creates child-facing proxy `AgentTool` wrappers. Each wrapper waits for the existing connection if necessary and delegates `callTool` through that same manager, with a bounded timeout ([`executor.ts` L730-L789](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/task/executor.ts#L730-L789)).

So the architecture is:

```text
parent MCPManager ---- one connection/server lifecycle ---- MCP server
        ^                                      ^
        | direct parent tool                   | delegated call
        +---------------- child proxy tool ----+
```

The child gets a normal tool-shaped interface, but it does not independently spawn or connect to every MCP server. This avoids duplicated processes, authentication, discovery, and connection races.

### 3.10 Bundled agent, line by line: `scout`

The bundled definition is [`prompts/agents/scout.md` L1-L58](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/prompts/agents/scout.md#L1-L58). Its frontmatter can be read as executable policy:

| Lines | Content | Runtime interpretation |
|---|---|---|
| 1, 31 | `---` | Delimit YAML; the rest is the system-prompt body |
| 2 | `name: scout` | Registers `scout`, shadowable by project/user definitions |
| 3 | Description | Tells the parent when to delegate: fast, bounded repository reconnaissance |
| 4 | `tools: read, grep, glob, web_search` | Read-oriented allowlist; parser adds `yield`; no edit/write/bash |
| 5 | `model: "@smol"` | Resolve the inexpensive/small model role |
| 6 | `thinking-level: medium` | Apply medium child reasoning after model capability normalization |
| 7 | `read-summarize: false` | Preserve direct reads rather than read-summarization behavior |
| 8-30 | `output` object | Require `summary`, `files`, and `architecture`; each file entry needs `path` and `description` |

What is absent matters too:

- no `task` tool and no `spawns`, so this scout cannot recursively delegate;
- no `blocking`, so ordinary background scheduling remains possible;
- no `autoloadSkills`, so no skill body is injected before its task;
- no `prewalk`, so it stays on the resolved scout model;
- no mutating tool, so “read-only” is enforced by capability construction, not trust in prose.

The body, lines 33-58, tells the child to be fast, use parallel searches, follow symbol paths, cite file paths, and avoid proposing implementation. Its last instruction is to yield the structured result. The prose improves behavior; the frontmatter supplies the enforceable model/tool/schema boundary.

---

## 4. How commands, skills, agents, and extensions compose

### 4.1 A slash command can cause an agent spawn—indirectly

The repository's embedded `/init` Markdown command explicitly instructs the model to launch multiple `scout` agents with `task` ([`prompts/agents/init.md` L1-L7](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/prompts/agents/init.md#L1-L7)). The rest specifies how to synthesize their findings ([`prompts/agents/init.md` L9-L32](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/prompts/agents/init.md#L9-L32)). The project file command `.omp/commands/fix-issues.md` similarly tells the model to use parallel `task` agents ([`.omp/commands/fix-issues.md` L1-L32](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/.omp/commands/fix-issues.md#L1-L32)).

The sequence is:

```text
/init
  -> Markdown command expansion
  -> expanded user prompt enters parent model
  -> model chooses task tool
  -> task preflight and child session creation
```

The command loader does not call `task` itself. A TypeScript custom or extension command could perform more direct session logic, but an ordinary Markdown command remains instruction expansion.

### 4.2 A skill can reference commands, but references are prose

A skill body may say “after the audit, ask the user to run `/review`” or include command examples. That reference helps the model/user coordinate a workflow, but inserting the skill body does **not recursively feed its lines back into slash dispatch**. Slash parsing occurs on an input string at the surface/session boundary; skill content is a custom message or `read` result already inside the loop.

If automatic composition is required, use one of these explicit mechanisms:

- a file command whose expanded prompt tells the model to read `skill://name` and call tools;
- a subagent definition with `autoloadSkills`;
- a TypeScript custom/extension command that invokes session APIs;
- an extension hook that injects messages or changes results.

This separation prevents an instructional Markdown file from silently becoming an imperative macro language.

### 4.3 Extension hooks wrap the whole path at several seams

Extensions have more than slash handlers:

- Before an agent turn, `before_agent_start` may add messages or replace the effective system prompt ([`agent-session.ts` L8957-L8999](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/session/agent-session.ts#L8957-L8999)). This can affect a command-expanded prompt, a skill invocation, or an ordinary prompt.
- Tool wrappers enforce user approval first, then emit `tool_call`, which may block execution ([`extensions/wrapper.ts` L116-L228](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/extensibility/extensions/wrapper.ts#L116-L228)). Thus an extension can observe/block the `task` call caused by a command or skill.
- After execution, `tool_result` may replace content/details and explicitly preserve, clear, or introduce error state ([`extensions/wrapper.ts` L230-L287](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/extensibility/extensions/wrapper.ts#L230-L287)).
- Child sessions initialize their own extension instances from inherited configuration, so hooks can also surround subagent tool calls.

Approval is deliberately before extension `tool_call`: an extension cannot use the pre-call hook to bypass a user deny/prompt policy. Conversely, an approved tool can still be blocked by an extension policy.

---

## 5. Trust and validation model

OMP's extensibility system is based on **trusted local configuration plus guarded runtime boundaries**, not on treating Markdown or TypeScript plugins as hostile code.

### 5.1 Boundary table

| Boundary | What is validated/enforced | What is still trusted |
|---|---|---|
| File command discovery | Recognized source/path, name/content shape, provider precedence, shadowing | The Markdown instruction's intent and correctness |
| File command invocation | Known name, quote-aware args, bounded placeholder grammar | Expanded text may persuade the model to use any active tool |
| Builtin invocation | Registry lookup, argument policy, surface/guest gates | Builtin implementation is application code |
| TS custom command | Module/export shape, loader errors, runtime exception containment | Imported TypeScript has process-level code execution |
| Extension command/hook | Registration shape, handler isolation/error reporting, event contracts; tool approval runs before hooks | Extension module is executable trusted code |
| Skill discovery | File layout, parsed metadata, enabled/disabled filters, precedence | Skill instructions may be wrong or prompt-injecting |
| `skill://` read | Exact active name; no absolute/traversal/out-of-root paths; file checks | Contents are delivered to the model as instructions/data |
| Agent definition | Required name/description, field normalization, deterministic precedence | Body can contain poor instructions but cannot restore omitted tools |
| Task preflight | Agent/spawn allowlists, depth, disabled agents, model resolution, plan-mode narrowing, isolation policy | A permitted child can use every tool it was actually granted |
| Child execution | Exact tool construction, budgets, cancellation, required yield | Tool side effects are real within the chosen worktree/environment |
| Yield | Envelope, type, section assembly, schema, retries, strict/permissive behavior | Schema-valid content can still be factually wrong |
| MCP proxy | Parent-owned connection, tool schema, timeout, result/error routing | Remote MCP server behavior and data remain trusted per its grant |
| Memory playbook | Strict consolidation schema, redaction, sanitized names, root-confined paths | Generated advice is advisory; live repository evidence must win |

### 5.2 “Validated” does not mean “safe”

Three examples prevent overconfidence:

1. A JSON schema can prove that `files` is an array of strings. It cannot prove that those paths are relevant or even that the model understood the architecture.
2. `skill://` prevents `../` escape, but a skill can still instruct the model to call an active shell or network tool. Capability control occurs at tool construction/approval, not Markdown parsing.
3. A TS command or extension is dynamically imported executable code. Shape checks catch accidental malformed exports; they are not a sandbox.

The strongest controls are therefore compositional: grant the minimum tools, use exact spawn lists, limit depth, use isolation for concurrent writes, require typed yields, and retain user approval policies around mutating tools.

---

## 6. Exactly what to create on disk

These are minimal **project-local** examples, so they do not depend on the active user profile and are easy to review in version control.

### 6.1 One Markdown slash command

Create `.omp/commands/explain-path.md`:

```md
---
description: Trace a symbol or path and explain it to a learner
---

Trace `$1` through the real repository.

Audience level: $2

Show definitions, callers, data transformations, and one small exercise.
Use pinned file-and-line citations. Preserve uncertainty rather than guessing.
```

Invoke it as:

```text
/explain-path "createAgentSession" beginner
```

Expected expansion: `$1` becomes `createAgentSession`; `$2` becomes `beginner`. Reload command metadata if the session was already running.

### 6.2 One authored skill

Create `.omp/skills/test-helper/SKILL.md`:

```md
---
name: test-helper
description: Use when adding or repairing tests; maps behavior to focused cases and verification commands.
---

# Test Helper

1. State the behavior under test in one sentence.
2. Find the nearest existing test with the same setup style.
3. Add the smallest case that fails before the fix and passes after it.
4. Run the narrow test first, then the relevant suite.
5. Report the exact commands and outcomes.

Do not weaken assertions merely to make a test pass.
```

Use it explicitly with:

```text
/skill:test-helper packages/example/src/widget.ts
```

Or let the model select it from its description and read `skill://test-helper`. The directory name and `name` should match to reduce human confusion even though the parser has fallbacks.

### 6.3 One subagent

Create `.omp/agents/test-scout.md`:

```md
---
name: test-scout
description: Find the smallest existing test surface for a named behavior and return typed evidence.
tools: [read, grep, glob]
spawns: []
model: "@smol"
thinking-level: medium
read-summarize: false
autoloadSkills: [test-helper]
output:
  type: object
  properties:
    summary: { type: string }
    candidate:
      type: object
      properties:
        path: { type: string }
        reason: { type: string }
      required: [path, reason]
    commands:
      type: array
      elements: { type: string }
  required: [summary, candidate, commands]
---

Find the nearest test covering the requested behavior.
Trace its setup and assertion style. Do not edit files.
Yield exactly the requested structure with evidence-backed paths and runnable commands.
```

The parent can invoke it with the model-visible `task` tool:

```json
{
  "agent": "test-scout",
  "task": "Find where command placeholder substitution should be tested.",
  "context": "Focus on quote handling and $@[start:length].",
  "isolated": false
}
```

Because the definition owns an output schema, the call does not need to repeat one. A caller-level `outputSchema` would override it for that spawn.

### 6.4 Optional executable custom command

When Markdown expansion is insufficient, create a command module directory in the active project custom-command location discovered by `getConfigDirs(...)/commands`, with an `index.ts` exporting a validated `CustomCommand` or factory. The essential shape is:

```ts
export default {
  name: "teach",
  description: "Build a teaching prompt from structured arguments",
  async execute(args: string[]) {
    const subject = args[0] ?? "this subsystem";
    return `Teach ${subject} from source. Include one traced call path and one exercise.`;
  },
};
```

Prefer a Markdown command when substitution is enough. Choose TypeScript only when the command needs deterministic UI, state inspection, external computation, or direct session actions; importing it grants executable-code trust.

---

## 7. Learning notes and graded exercises

### 7.1 Language and design idioms worth studying

#### Discriminated unions

`{ consumed: true } | { prompt: string }` makes an impossible state—both local consumption and prompt continuation—harder to represent. `yield` similarly uses a `type` discriminator for progress/final forms. When reading TypeScript, find the field whose literal value narrows the rest of the object.

#### `Map` as a precedence engine

Several loaders turn “who wins?” into insertion order:

- first-seen capability names win after ordered provider flattening;
- agent discovery inserts project before user/plugins/bundled;
- extension command lookup searches extension registrations in reverse.

The data structure is simple; correctness lives in the order feeding it.

#### Presence versus truthiness

Schema precedence uses an own-property test. `{ outputSchema: false }`, `{ outputSchema: null }`, or an explicit empty value may mean something different from omitting the property. `Object.hasOwn()` communicates this more accurately than `if (x.outputSchema)`.

#### Dynamic import and trust

The custom-command loader uses `import()` because extensions are discovered at runtime. Type checking cannot prove arbitrary external modules are well formed, so the loader performs runtime validation. This is a common plugin-system pattern: static types for authors, runtime guards at the boundary.

#### Async concurrency with deterministic ordering

Discovery can use `Promise.all()` to read providers concurrently without surrendering precedence. Awaited results are flattened according to the original provider list. Concurrency determines completion time; the array determines semantics.

#### Private fields and encapsulated state machines

`#prewalk`, `#prewalkTodoSeen`, and `#advancePrewalk()` form a small state machine hidden inside `AgentSession`. Trace which events set, inspect, and clear each flag. This is more reliable than reading one function in isolation.

#### Capability security

The child prompt says what the agent **should** do. The child tool list determines what it **can** do. Good agent systems use both: prose for nuanced behavior, capabilities for hard boundaries.

#### Two schema dialects

Bundled agent frontmatter uses a JTD-shaped `output` schema (`elements`, required properties), while per-call `outputSchema` can be JSON-Schema-shaped (`items`, `required`). Follow the parser/validator selected by the field instead of assuming every “schema” object is the same dialect.

### 7.2 Exercises

#### Exercise 1 — File command substitution (introductory)

Create `.omp/commands/trace-two.md` accepting two quoted symbols and a remainder slice. Make the expanded prompt label `$1`, `$2`, `$@`, and `$@[2]` separately.

**Pass evidence:** show invocations with quoted spaces, no arguments, and an unmatched quote; write the exact expansion predicted from `parseCommandArgs()` and verify it in OMP.  
**Stretch:** explain why replacement is non-recursive and devise an input containing literal `$1`.

#### Exercise 2 — Skill selection modes (introductory/intermediate)

Author a skill with a precise description, invoke it through `/skill:name`, then start a new ordinary prompt whose wording should cause the model to choose `skill://name`.

**Pass evidence:** capture which parts were in base system metadata and which arrived only after invocation/read.  
**Stretch:** set `hide: true` and explain the expected difference between model discovery and explicit invocation.

#### Exercise 3 — Prompt-producing versus action-producing custom command (intermediate)

Implement `/teach` so one branch returns a prompt and another uses the command context to show a local notice and returns `void`.

**Pass evidence:** demonstrate that the first branch causes an agent turn and the second does not. Trigger an intentional exception and identify the extension/error path that consumes it.  
**Stretch:** return a slash-prefixed string matching a file command and observe the remaining file-expansion stage.

#### Exercise 4 — Typed subagent result (intermediate)

Create `test-scout` from §6.3, call it once with its definition-level schema, then call it with a stricter per-spawn `outputSchema`.

**Pass evidence:** consume a field from the structured result rather than parsing prose; record which schema won and cite the own-property precedence code.  
**Stretch:** deliberately omit a required field, observe the yield retry, then fix the child instructions.

#### Exercise 5 — Capability and depth audit (advanced)

Define a coordinator allowed to spawn only `scout`, and give it `task`. Ask it to spawn another name and to edit a file.

**Pass evidence:** distinguish spawn preflight rejection from an unavailable edit tool. Then run the coordinator at maximum depth and show that `task` is removed.  
**Stretch:** repeat in plan mode and compare the effective tool set with the definition's requested tools.

#### Exercise 6 — Hooked task lifecycle (advanced)

Write an extension that logs `before_agent_start`, `tool_call`, and `tool_result` for `task`, blocks one recognizable task input, and annotates one successful result without changing its structured data.

**Pass evidence:** show approval ordering, the blocked path, the successful child yield, and the parent-visible annotation.  
**Stretch:** allow an MCP tool to the child and prove from logs/process inspection that the child used the parent's connection rather than creating a second server connection.

### 7.3 Suggested grading scale

| Grade | Evidence |
|---|---|
| A | Mechanism works; prediction matches runtime; source lines explain why; failure path tested |
| B | Mechanism works and happy path is source-linked; edge behavior mostly explained |
| C | File parses and basic invocation works; precedence/context/yield behavior is asserted without evidence |
| D | Prompt text exists but wrong directory/schema/dispatch assumptions prevent reliable use |

---

## 8. Documentation/source divergence ledger

Source is authoritative at the pinned commit.

### 8.1 Agent discovery includes OMP extension packages

[`docs/task-agent-discovery.md` L58-L74](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/docs/task-agent-discovery.md#L58-L74) lists project, user, Claude plugin, and bundled agents. The implementation also loads OMP extension-package agents between user and Claude plugin sources ([`task/discovery.ts` L61-L120](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/task/discovery.ts#L61-L120)). **Use the source order.**

### 8.2 Per-call output schemas exist

Pinned prose says the agent owns the schema and implies there is no per-call schema ([`docs/task-agent-discovery.md` L127-L132](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/docs/task-agent-discovery.md#L127-L132), [`docs/tools/task.md` L41-L50](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/docs/tools/task.md#L41-L50)). The task input type explicitly accepts per-spawn `outputSchema` and `schemaMode`, and shared policy gives caller presence first precedence ([`task/types.ts` L112-L172](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/task/types.ts#L112-L172), [`structured-subagent.ts` L170-L181](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/task/structured-subagent.ts#L170-L181)). **Per-call schemas are implemented and win.**

### 8.3 Plan-mode tool names changed

Older docs describe a broader/differently named read-only set. The pinned policy constant narrows a child to `read`, `grep`, `glob`, and `web_search`, adding `ast_grep` if available, and clears spawns/prewalk ([`structured-subagent.ts` L184-L193](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/task/structured-subagent.ts#L184-L193)). **Use the exact source list.**

### 8.4 Builtins are not an `AgentSession.prompt()` stage

The slash-command guide's compact order is easy to overread as one dispatcher. Source shows the TUI/ACP surface consumes supported builtins and skills before session prompting; only extension, custom/MCP, and file commands are inside `AgentSession.prompt()`. **Use the two-layer dispatch model in §1.3.**

### 8.5 Live website is descriptive, not pinned

As accessed on 2026-07-21, [`omp.sh`](https://omp.sh/) advertises typed subagent results, isolated worktrees, slash commands, imported capabilities, and `skill://`. It is a compiled live SPA and may describe a newer version than commit `7b1411…`. It is therefore not used to settle field names, precedence, or enforcement behavior.

---

## 9. Compact source map

For follow-up reading, these are the highest-yield source entry points:

| Topic | Start here |
|---|---|
| Builtin command API and registry | [`slash-commands/types.ts`](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/slash-commands/types.ts), [`builtin-registry.ts`](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/slash-commands/builtin-registry.ts) |
| Session command precedence | [`agent-session.ts` L8649-L8692](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/session/agent-session.ts#L8649-L8692) |
| File command load/expand | [`extensibility/slash-commands.ts`](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/extensibility/slash-commands.ts), [`utils/command-args.ts`](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/utils/command-args.ts) |
| Skill load/invoke | [`extensibility/skills.ts`](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/extensibility/skills.ts) |
| Skill context advertising | [`system-prompt.ts` L758-L817](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/system-prompt.ts#L758-L817) |
| Agent fields/discovery | [`task/types.ts` L349-L367](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/task/types.ts#L349-L367), [`task/discovery.ts`](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/task/discovery.ts) |
| Shared child policy | [`structured-subagent.ts`](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/task/structured-subagent.ts) |
| Child composition/run | [`task/executor.ts` L2167-L2879](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/task/executor.ts#L2167-L2879) |
| Typed yield | [`tools/yield.ts`](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/tools/yield.ts) |
| Memory playbooks | [`memories/index.ts`](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/memories/index.ts), [`consolidation.md`](https://github.com/can1357/oh-my-pi/blob/7b141199d524b859c357fc89654f10b62b9f3df1/packages/coding-agent/src/prompts/memories/consolidation.md) |

## 10. Bottom line

OMP's extensibility triad is a set of staged boundaries:

- commands decide whether text is consumed locally, transformed, or delivered;
- skills advertise cheaply and disclose full instructions only when selected;
- agents turn a reusable role file into a restricted child session with independent model/tool/context policy and a validated return channel.

The codebase's strongest idea is not any one Markdown format. It is **composition with enforcement**: precedence is deterministic, model context is explicit, child tools are constructed rather than merely requested, recursive delegation is bounded, and typed results cross back through a real tool schema. The places that remain trust-based—plugin code, instruction quality, and factual correctness—are visible rather than disguised as validation.

## Inaccessible or unresolved material

No requested source was inaccessible. The pinned repository, its internal docs, the prior deep dive, and the live `omp.sh` site were all readable. The public site is not commit-versioned, so it was intentionally not treated as proof of pinned implementation details.
