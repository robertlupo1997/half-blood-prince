# Proposal: multi-provider LLM support (OpenRouter / any OpenAI-compatible API)

> **Status: PROPOSAL — decisions pending Trey's approval.** This is not an
> approved spec. It captures the fork so the decision survives outside the
> chat. On approval it becomes a full spec + TDD plan (one task per change).

## Requirement (Trey, 2026-07-11)

> "I would also like it to work with any large language model API, like one
> from OpenRouter or something like that, and any OpenAI-type API."

## Where the seam is

The pipeline is provider-agnostic *except one point*: `annotation_generator.py`
uses the Anthropic SDK with **forced `tool_use`**
(`tool_choice={"type":"tool","name":"record_annotations"}`) to get schema-valid
structured output. Everything downstream (document/EPUB rendering, web preview)
just consumes a validated `AnnotationPlan` and does not care who produced it.

So "support any LLM API" = introduce a provider abstraction behind
`AnnotationGenerator`, plus a second structured-output strategy for
OpenAI-shaped APIs (function calling / `response_format` json-schema).

## Options

### A — Thin provider layer *(recommended)*
A small `LLMProvider` protocol: `generate_annotations(system, user, schema) ->
list[dict]`. Two concrete impls:
- `AnthropicProvider` — the current forced-tool-use path; **stays the default**
  (highest structured-output fidelity for Claude).
- `OpenAICompatProvider` — the `openai` SDK with `base_url` + `api_key`, forcing
  a `record_annotations` function call (falling back to `response_format`
  json-schema where a provider supports structured outputs but not tools). One
  impl covers **OpenAI, OpenRouter** (`base_url=https://openrouter.ai/api/v1`),
  Groq, Together, and local Ollama / LM Studio.

Selection: `--provider anthropic|openai`, `--base-url`, `--model`, and an
api-key env var. `openai` added as an **optional** dependency group so the core
stays lean.

Pros: keeps Claude's fidelity as default; covers OpenRouter + every
OpenAI-style API through one impl; preserves the repo's deliberate "direct SDK,
no LangChain-style abstraction" principle; fully mockable/testable.
Cons: two structured-output code paths to maintain; providers that support
*neither* tools nor json-schema fall back to prompt+parse (best-effort).

### B — LiteLLM
One interface, 100+ providers, least code. Cons: heavy dependency; less
auditable single-call design; contradicts the repo's explicit no-framework
decision (ARCHITECTURE.md / CLAUDE.md).

### C — Anthropic-only for now
Defer multi-provider; the retired-model fix (already shipped, see below) is
enough for a working v0.1.0. Multi-provider becomes a later phase.

## Relationship to the shipped model fix

The retired-model batch (AUD-01/02/03/04/16) already landed on
`phase2-model-fix` and is **independent** of this decision: the default model is
now a single-sourced constant (`DEFAULT_MODEL` in `annotation_generator.py`).
A future provider layer consumes that constant unchanged — no rework, no
corner painted. Nothing here was blocked on it and vice-versa.

## Open decisions (for Trey)

1. Approach A / B / C?
2. If A: default structured-output strategy on the OpenAI side — force a
   function call (mirrors Anthropic; broadest OpenRouter support) vs.
   `response_format` json-schema (cleaner, narrower model support)?
3. Add `openai` as an optional extra (`[openai]`) or a core dependency?
4. Config surface: CLI flags only, or also a `.halfblood.toml` for
   provider/base-url/model defaults?
