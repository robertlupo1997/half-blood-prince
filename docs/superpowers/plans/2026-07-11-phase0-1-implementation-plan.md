# Phase 0 + Phase 1 implementation plan

**Date:** 2026-07-11  
**Ground truth:** `docs/superpowers/specs/2026-07-11-full-project-architecture.md` §§4, 9, 12; `docs/audit/2026-07-10-adversarial-audit.md`  
**Scope:** remaining audit closure and the synchronous provider foundation only

## Execution notes

Execute one task at a time. For every task, the controller first writes the specified failing pytest tests and confirms they fail for the intended reason; Codex then implements only that task; the controller runs `ruff check src tests eval`, `mypy src/halfblood`, and `pytest tests/ -q`, and commits only after all three gates pass. Tests use pytest and `SimpleNamespace`/`httpx.MockTransport`-style SDK or HTTP doubles; they make no network calls. Preserve `tests/test_config.py` and `tests/test_failure_handling.py`, including the merged `claude-sonnet-5`, `failed_pages`, partial-failure, and `AllPagesFailedError` behavior. Phase 0 may improve the current SDK implementation, but Phase 1 replaces production provider traffic with `httpx`; do not build a second retry layer around the Anthropic SDK. Concurrency remains exactly 1 throughout this plan.

Live PDF/EPUB/provider smoke tests are explicitly **blocked-on-key: `ANTHROPIC_API_KEY`**. They are supplementary gates, never substitutes for mocked tests. When a maintainer supplies a key, run the ledger's prepared E2E commands with the current model, record tokens/cost and output validation, and do not commit generated copyrighted artifacts or credentials.

## Phase 0 — close the remaining audit ledger

### P0-T1 — Harden Anthropic response handling and SDK-shaped tests

**Covers:** AUD-05, AUD-10, AUD-14, AUD-21, AUD-23, L-1, L-3; architecture §9 Phase 0 response/schema safety.

**Goal:** Make truncation, empty tool input, API failures, and block typing explicit while exercising the same Message-shaped path production uses. **Why:** malformed or truncated responses can otherwise look like legitimate zero-annotation pages, and string-only tests can leave the production branch broken.

**Files to create/modify:** `src/halfblood/annotation_generator.py`, `tests/test_pipeline.py` (or focused `tests/test_annotation_generator.py`).

**Test-first:** Replace the six JSON-string-biased parser cases with `SimpleNamespace` Message/content-block fixtures matching the SDK shape. Add tests asserting: `stop_reason="max_tokens"` raises/records a page failure rather than returning `[]`; a matching `tool_use` with `input=None`, `{}`, or a non-object is malformed and not a successful empty result; `{"annotations": []}` with a valid non-truncated finish is successful; unrelated text plus exactly one matching tool block parses with a warning; no matching block fails explicitly; an `anthropic.APIError` becomes the already-merged failed-page path and all attempted failures still raise `AllPagesFailedError`. Add a real `anthropic.types.ToolUseBlock` narrowing test (construct/validate the SDK type) so non-tool blocks are never accessed through `.input`. Assert the SDK call arguments are typed without `type: ignore` suppressions through the mypy gate.

**Acceptance criteria:** No silent success for truncated/empty malformed tool responses; valid empty arrays remain valid; production-shaped tests cover the API error path; L-1/L-3 ignores are gone; merged failure tests are unchanged and green; all standard gates pass.

**Effort:** M. **Dependencies:** none.

### P0-T2 — Validate annotation strings, fences, and enum compatibility

**Covers:** AUD-15, AUD-32, L-2; architecture §§2.1, 4.2, 9.

**Goal:** Reject blank semantic fields, parse only actual Markdown fences, and make the enum migration behavior deliberate. **Why:** empty targets reach undefined renderer searches, character-strip fence handling corrupts data, and an incidental `StrEnum` migration can alter public string behavior.

**Files to create/modify:** `src/halfblood/models.py`, `src/halfblood/annotation_generator.py`, `tests/test_pipeline.py` or `tests/test_models.py`.

**Test-first:** Parameterize `target_text` and `content` with `""`, spaces, and newlines and assert `pydantic.ValidationError`; assert surrounding whitespace is stripped from valid values. Feed fenced JSON with exactly `````json``/````` boundaries and assert parsing; feed legitimate leading/trailing backticks inside JSON string values and assert they survive byte-for-byte. Pin `AnnotationType.CORRECTION.value == "correction"`, JSON serialization as `"correction"`, and the chosen `str()` behavior. Then either migrate to `StrEnum` with the new expected `str()` result or retain `str, Enum` with a permanent documented Ruff exemption; the test makes the compatibility choice explicit.

**Acceptance criteria:** Blank semantic strings cannot instantiate; fence removal is delimiter-aware; enum behavior is documented and tested; no unexplained UP042 suppression; all gates pass.

**Effort:** S. **Dependencies:** P0-T1.

### P0-T3 — Cover document orchestration and bound running context

**Covers:** AUD-22, AUD-31; architecture §§2.2, 9.

**Goal:** Pin sequential document assembly and cap retained running notes to the eight entries actually consumed. **Why:** page context, confidence trimming, blank-page semantics, and plan assembly can regress without touching page-level tests, while unbounded history wastes memory.

**Files to create/modify:** `src/halfblood/annotation_generator.py`, `tests/test_pipeline.py` or `tests/test_generation_orchestration.py`.

**Test-first:** Mock `generate_for_page` and use `PageContent` objects to assert calls occur in page order; previous/next context is exactly the trailing/leading 500 characters; only the latest eight prior `INVENTION`/`WARNING` notes are passed; the stored running list never exceeds eight; blank pages are skipped and are neither calls nor failures; over-cap results retain highest confidence in stable order; assembled `AnnotatedPage.original_text`, page numbers, title/persona, total, and `failed_pages` are correct. Include partial and all-failed cases to confirm merged semantics.

**Acceptance criteria:** Sequential behavior and all orchestration invariants are covered; retained context is bounded; existing failure tests remain green; all gates pass.

**Effort:** M. **Dependencies:** P0-T1.

### P0-T4 — Fix web target matching with a complexity guard

**Covers:** AUD-06, AUD-25, AUD-35; architecture §§2.5, 5.7, 9.

**Goal:** Anchor multi-word web targets correctly without reintroducing catastrophic regex behavior, and safely embed all plan data. **Why:** the current pattern misses every multi-word target; a naive correction creates a ReDoS vector and untested script embedding can break or inject markup.

**Files to create/modify:** `src/halfblood/web_preview.py`, create `tests/test_web_preview.py`.

**Test-first:** Assert `_flexible_pattern("two words")` matches spaces, tabs, and newlines but not arbitrary intervening text; punctuation remains escaped; empty/oversized targets are rejected or safely unanchored. Add an adversarial long repeated-prefix input and assert the guard rejects it or completes within a deterministic structural bound (prefer bounded pattern/input construction over flaky wall-clock timing). Generate HTML containing `</script>`, `<>&`, quotes, U+2028, and U+2029 in title/text/content and assert HTML text is escaped, the JSON script cannot terminate early, U+2028/U+2029 are escaped, and parsed embedded JSON round-trips. Assert multi-word annotations receive an anchor while unmatched ones degrade safely.

**Acceptance criteria:** Sentinel-before-escape behavior is correct; regex work is bounded by explicit input/pattern limits or a linear matcher; HTML/JSON embedding tests cover the shipping path; no network; all gates pass.

**Effort:** M. **Dependencies:** none.

### P0-T5 — Keep PDF margin and interline geometry on-page

**Covers:** AUD-07, AUD-08, AUD-09, AUD-20, AUD-40; architecture §§2.3, 5.5, 9.

**Goal:** Ensure wrapped notes and interline text stay inside page bounds without colliding with their target. **Why:** notes currently disappear beyond right/top/bottom edges, long tokens invade body text, and the top clamp can overlap the annotated baseline.

**Files to create/modify:** `src/halfblood/document_processor.py`, `tests/test_pipeline.py` or create `tests/test_pdf_geometry.py`.

**Test-first:** Use synthetic `fitz.Page` dimensions and monkeypatch/spy drawing calls to capture every text baseline/box. Parameterize right-edge targets, top/bottom targets, left/right margins, and long content; assert every emitted note rectangle and line baseline lies within `page.rect`, side switching or font reduction occurs when the preferred margin is below minimum width, and top/bottom shifting preserves line order. Assert a single token wider than the column is split into nonempty character chunks each measuring at most the column (except a single glyph wider than the bound, which must terminate safely). For near-top `between_lines`, assert all note baselines stay above the target with the configured gap and on-page.

**Acceptance criteria:** No tested note geometry crosses page bounds; long-token wrapping terminates and respects width; interline collision regression is pinned; all gates pass.

**Effort:** L. **Dependencies:** none.

### P0-T6 — Correct PDF target selection and crossed-out placement

**Covers:** AUD-19, AUD-26, AUD-39; architecture §§2.3, 5.5, 9 (without implementing Phase 2's full locator).

**Goal:** Prevent fallback matches from spanning repeated occurrences, recover short targets across normalized line breaks, and route crossed-out replacement text through the requested-position dispatcher. **Why:** a repeated fallback word can create a page-sized false anchor, short quotes have no fallback, and crossed-out notes ignore their position.

**Files to create/modify:** `src/halfblood/document_processor.py`, create/modify PDF tests and fixture builder under `tests/fixtures/` if needed.

**Test-first:** Build an in-memory PDF with a repeated fallback word at separated locations and surrounding unique context; assert `find_text_rect` returns one candidate rectangle, never the union spanning both, and chooses the exact/contextually closest candidate deterministically. Add a ≤3-word target split by line-break/whitespace drift and assert the normalized-substring fallback locates it without matching unrelated text. Spy on placement helpers for `CROSSED_OUT` at each valid position and assert replacement content invokes exactly the corresponding margin/inline/interline dispatcher once, while the strike mark is still applied.

**Acceptance criteria:** No union across distinct repeated hits; short normalized fallback is bounded and deterministic; crossed-out placement honors all positions; all gates pass.

**Effort:** M. **Dependencies:** P0-T5.

### P0-T7 — Validate input signatures and protect outputs

**Covers:** AUD-17, AUD-37; architecture §§4.4, 9.

**Goal:** Fail with actionable CLI errors for mislabeled inputs and require explicit consent before overwriting output. **Why:** raw parser tracebacks confuse users and silent replacement can destroy files.

**Files to create/modify:** `src/halfblood/cli.py`, possibly a small shared input helper, `tests/test_pipeline.py` or create `tests/test_cli.py`, `README.md`.

**Test-first:** With `CliRunner`, pass non-PDF bytes named `.pdf`, non-ZIP bytes named `.epub`, valid PDF/EPUB signatures with supported suffixes, and unsupported suffixes; assert failures are `ClickException`-style messages with no traceback and processing is never called for invalid bytes. Precreate an output and assert the command refuses without `--force`, preserves bytes and does not call generation/rendering; with `--force`, assert the mocked pipeline runs. Assert missing parent directories are created and that behavior appears in help/docs.

**Acceptance criteria:** Magic bytes are checked before dispatch; overwrites are opt-in and atomic behavior is preserved where present; CLI help/docs agree; all gates pass.

**Effort:** M. **Dependencies:** none.

### P0-T8 — Normalize EPUB matching and establish round-trip coverage

**Covers:** AUD-18, AUD-24; architecture §§2.4, 9.

**Goal:** Cover the existing EPUB pipeline and make curly/straight punctuation matching symmetric. **Why:** a whole shipping format is unguarded and quote-normalization mismatches silently skip annotations.

**Files to create/modify:** `src/halfblood/epub_processor.py`, create `tests/test_epub_processor.py`, use `tests/fixtures/sample_book.epub`.

**Test-first:** Assert fixture loading follows linear spine order, excludes `linear="no"`, and explicitly pins current nav-document handling; text/page metadata are stable. Parameterize ASCII/curly single and double quotes in target and node text in both directions and assert the same slice is located. Render annotations and unzip/read the result to assert XHTML parses with lxml, original text remains, CSS is injected exactly once, target/note markup appears only in the intended chapter, unmatched targets are skipped, metadata/spine remain valid, and reloading the output succeeds.

**Acceptance criteria:** Quote normalization is symmetric; load/render/round-trip behavior is covered without network; nav behavior is documented rather than accidental; all gates pass.

**Effort:** M. **Dependencies:** P0-T2.

### P0-T9 — Remove false-green tests

**Covers:** AUD-41, AUD-42, AUD-43; architecture §9.

**Goal:** Make three weak tests prove their named behavior. **Why:** broad exceptions, missing placement assertions, and loose version output can pass for unrelated failures.

**Files to create/modify:** `tests/test_pipeline.py` (or focused model/PDF/CLI test files).

**Test-first:** Change confidence rejection to `pytest.raises(pydantic.ValidationError)` and assert the error locates `confidence`; spy on `_write_margin_text`/placement dispatch and assert an invalid position resolves specifically to `margin_right`; monkeypatch package metadata to a known version and assert `--version` exits 0 with the exact Click-formatted line, plus a separate narrowly asserted not-installed error if that branch remains supported.

**Acceptance criteria:** Each test fails under the corresponding intentional mutation; no `pytest.raises(Exception)` remains; all gates pass.

**Effort:** S. **Dependencies:** P0-T2, P0-T5.

### P0-T10 — Make the web preview honestly offline

**Covers:** AUD-36 and the noisy font-warning Phase 0 hygiene item; architecture §§2.5, 5.7, 9.

**Goal:** Produce preview HTML with no remote font requests and avoid repeating an expected optional-font warning. **Why:** “self-contained” output currently leaks viewer requests and breaks offline; repeated warnings obscure actionable failures.

**Files to create/modify:** `src/halfblood/web_preview.py`, `src/halfblood/document_processor.py`, `tests/test_web_preview.py`, PDF processor tests, possibly packaged font assets only if licensing is already established (otherwise use a local/system fallback and qualify the visual claim).

**Test-first:** Generate HTML and assert it contains no `http://`, `https://`, Google Fonts, `@import`, or other external asset URL while retaining usable fallback font CSS. Instantiate multiple processors with no Caveat font and capture logs: assert at most one informational/debug notice (not repeated warnings), and assert an explicitly configured missing font path still raises or logs one actionable warning as designed.

**Acceptance criteria:** Preview is network-independent; docstring/README wording matches reality; normal missing optional font does not spam warnings; all gates pass.

**Effort:** S. **Dependencies:** P0-T4.

### P0-T11 — Reconcile user and architecture documentation

**Covers:** AUD-11, AUD-12, AUD-13, AUD-27, AUD-28, AUD-29, AUD-30, AUD-33, AUD-44; architecture §§2, 8, 9.

**Goal:** Make public docs describe the commands, PDF/EPUB/web modules, font discovery, and retry ownership that actually exist. **Why:** stale docs hide features, invite duplicate work, and prescribe an incorrect SDK retry fix.

**Files to create/modify:** `README.md`, `docs/ARCHITECTURE.md`, `CLAUDE.md`, optionally create `tests/test_docs.py`.

**Test-first:** Add lightweight doc-contract tests (or a deterministic script invoked by pytest) asserting README names `INPUT_FILE`, PDF and EPUB, a runnable `web-preview` example, parent-directory/overwrite behavior, and `*aveat*.ttf`; architecture lists `epub_processor.py`, `web_preview.py`, and all four current commands; CLAUDE.md no longer claims retries are absent and states that Phase 1's provider transport is the sole retry owner. Check every shown local CLI command with `CliRunner --help` argument names rather than executing network operations.

**Acceptance criteria:** All nine ledger items are traceably corrected; no docs imply EPUB is future work; command snippets match CLI; all gates pass.

**Effort:** S. **Dependencies:** P0-T7, P0-T10.

### P0-T12 — Bound dependencies and close the Phase 0 ledger

**Covers:** AUD-38 plus Phase 0 E2E/audit disposition; architecture §§4.5, 9. AUD-34 is intentionally deferred to P1-T9 as specified by §9.

**Goal:** Publish compatible dependency ranges, choose a reproducible development-lock strategy, and prove every remaining finding is closed or explicitly key-blocked. **Why:** floor-only dependencies permit silent breaking upgrades, and an untracked ledger lets findings disappear between phases.

**Files to create/modify:** `pyproject.toml`, development lock file/tool config if adopted, `docs/audit/2026-07-10-adversarial-audit.md` or a linked closure report, dependency tests such as `tests/test_packaging.py`.

**Test-first:** Parse `pyproject.toml` and assert every runtime dependency has an intentional compatible upper bound (at minimum `anthropic<2` until removed in Phase 1), `[eval]` remains present, and dev reproducibility is documented with a checked lock artifact or an explicit supported alternative. Add a ledger completeness test/table mapping every AUD-01..44 and L-1..L-3 to merged, a P0 task, P1-T9 (AUD-34), accepted-with-rationale (AUD-35 still fixed in P0-T4), or blocked-on-key E2E—no blank dispositions.

**Acceptance criteria:** Clean environment resolution succeeds under the chosen strategy; package metadata remains buildable; closure report records mocked gates and the exact blocked-on-key commands; all standard gates pass. If a key exists, also run and record the prepared live PDF/EPUB checks; otherwise mark only those checks blocked, not the task's offline acceptance.

**Effort:** M. **Dependencies:** P0-T1 through P0-T11.

## Phase 1 — semantic plan and provider foundation

### P1-T1 — Introduce semantic plan v2 and deterministic v1 migration

**Covers:** architecture §§3.1–3.2, 4.2, 9 Phase 1, 10.12.

**Goal:** Version the reusable semantic contract and migrate every saved/current v1 plan without losing meaning. **Why:** provider provenance and stable identities cannot be added safely to an unversioned renderer-coupled model, and existing JSON must not be stranded.

**Files to create/modify:** create `src/halfblood/models/annotations.py`, `src/halfblood/models/documents.py`, `src/halfblood/models/__init__.py`; replace or turn `src/halfblood/models.py` into a compatibility re-export as packaging permits; create `tests/test_plan_migration.py`; update existing imports only as needed.

**Test-first:** Define frozen v1 JSON fixtures for defaults, all annotation types/positions, empty pages, and mismatched nested page numbers. Assert migration yields `schema_version=2`, stable deterministic annotation IDs for the same source data, explicit source locator/page ownership, generation provenance placeholders, render seed/style separation, and `Field(default_factory=list)` isolation. Assert v2 JSON round-trips byte-semantically, rejects unknown future major versions, and v1 compatibility imports still construct/serialize objects expected by existing tests. Page numbers supplied by the caller override model-owned ambiguity.

**Acceptance criteria:** v1 fixtures migrate deterministically with no semantic loss; v2 is explicitly versioned and renderer-neutral; compatibility imports and all Phase 0 tests pass; all gates pass.

**Effort:** L. **Dependencies:** P0-T12.

### P1-T2 — Generate and canonicalize the provider schema from Pydantic

**Covers:** architecture §§4.2–4.3.

**Goal:** Make `RecordAnnotations`/`AnnotationDraft` the only source of the structured-output contract and produce a stable schema hash. **Why:** hand-maintained schemas drift from runtime validation and poison provenance/caches.

**Files to create/modify:** create `src/halfblood/generation/schema.py`, extend v2 annotation models, create `tests/test_generation_schema.py`, remove the legacy hand-written schema when consumers migrate.

**Test-first:** Assert generated Draft 2020-12 schema has stable name `record_annotations`; all local `$refs` are inlined; `additionalProperties: false` appears recursively on objects; all expected draft fields are required; enum, confidence bounds, and stripped `minLength: 1` constraints are preserved; server-owned ID/page/provenance/style/seed fields are absent. Assert canonical JSON uses stable ordering/separators and its SHA-256 (or documented hash) is repeatable and changes when the contract changes. Validate representative payloads through Pydantic after schema parsing.

**Acceptance criteria:** No duplicate hand schema remains in production; schema hash/version can be stored in provenance; provider normalization is deterministic; all gates pass.

**Effort:** M. **Dependencies:** P1-T1.

### P1-T3 — Resolve provider configuration safely and predictably

**Covers:** architecture §§4.4–4.5.

**Goal:** Resolve generation settings with CLI → environment → project TOML → user TOML → profile precedence and never expose secrets. **Why:** multi-provider behavior is unusable or unsafe without deterministic sources, endpoint validation, and redaction.

**Files to create/modify:** create/expand `src/halfblood/config.py`, create `tests/test_provider_config.py`, update `pyproject.toml` for `httpx`/`platformdirs` and eventual SDK compatibility extra, minimally wire CLI options/help.

**Test-first:** Use temporary TOML files and monkeypatched environment to assert every precedence layer independently, source attribution for each effective value, concurrency defaults/enforcement at 1 for this phase, and no universal model fallback outside an explicitly versioned profile default. Assert hosted non-loopback HTTP is rejected unless `allow_insecure_http`; loopback HTTP is allowed; embedded URL credentials/query secrets are rejected or redacted. Assert project config cannot contain literal API keys, `--api-key-env` resolves only the named variable, missing hosted keys produce `ProviderConfigurationError`, local profiles need none, `.env` is never loaded, and `repr`/`config show` contains no secret.

**Acceptance criteria:** Precedence and profiles are deterministic across platforms; secrets cannot enter project config/diagnostics; old `tests/test_config.py` stays green; all gates pass.

**Effort:** L. **Dependencies:** P1-T1.

### P1-T4 — Define provider protocol, errors, results, and generation report

**Covers:** architecture §§3.2, 4.6; preserves AUD-16 semantics.

**Goal:** Establish transport-neutral request/result/capability contracts, normalized errors, and per-unit reporting before adding adapters. **Why:** leaking vendor shapes makes retries, partial failures, costs, and diagnostics inconsistent.

**Files to create/modify:** create `src/halfblood/generation/providers/base.py`, `src/halfblood/generation/errors.py`, report models (for example `src/halfblood/generation/report.py`), package exports, create `tests/test_provider_contract.py` and `tests/test_generation_report.py`.

**Test-first:** Supply a fake provider implementing `complete` and assert protocol-compatible request/result fields: parsed object, request ID, normalized finish reason, usage, latency, structured mode, warnings, attempts. Parameterize HTTP/status causes into the exact taxonomy (`Configuration`, `Authentication`, `NotFound`, `Capability`, `RateLimit`, `Transient`, `SafetyRefusal`, `IncompleteResponse`, `StructuredOutput`, `AnnotationValidation`). Assert `GenerationReport` has a status for every unit, skipped blank units are not failures, partial failure returns plan+report and compatibility `failed_pages`, all attempted failures raise `AllPagesFailedError(report)`, valid empty annotations are success, and serialization/redacted repr never includes keys or raw sensitive bodies.

**Acceptance criteria:** Provider protocol has no Anthropic/OpenAI imports; error retryability is explicit; merged failure tests pass unchanged or through compatibility re-exports; all gates pass.

**Effort:** M. **Dependencies:** P1-T1, P1-T3.

### P1-T5 — Implement the native Anthropic HTTP adapter and parity cutover

**Covers:** architecture §§4.1, 4.3 Anthropic, 4.6, 9 Phase 1.

**Goal:** Match current forced-tool behavior through synchronous `httpx` while normalizing responses, errors, usage, and retries. **Why:** Anthropic parity is the safety anchor for replacing the SDK and enabling a uniform provider seam.

**Files to create/modify:** create `src/halfblood/generation/providers/anthropic.py`, retry helper if needed, adapt generation service/legacy `AnnotationGenerator`, `pyproject.toml`, create `tests/test_anthropic_provider.py`, update failure/config tests only for compatibility wiring.

**Test-first:** With `httpx.MockTransport`, inspect one POST's URL, headers (`x-api-key`, `anthropic-version`, JSON content), model/messages/max tokens, tool schema, and forced `tool_choice`; assert no key appears in logs/errors. Return fixtures for exactly one matching `tool_use`, text-plus-tool warning, valid empty list, missing/multiple matching tools, malformed input, refusal, `max_tokens`, usage/request ID, and every relevant HTTP status/timeout; assert exact normalized results/errors. Use injected deterministic backoff/sleeper to assert bounded retries only for 429 honoring `Retry-After` and transient statuses/timeouts, one incomplete retry with a capped larger token budget, no retries for auth/not-found/schema/content errors, and attempts/cost-risk reporting. Run the existing generator and failure tests against an injected fake provider to prove persona/context/max-per-page and `AllPagesFailedError` parity.

**Acceptance criteria:** Production Anthropic traffic uses `httpx`, not the SDK; one retry owner is visible and testable; concurrency is 1; `anthropic` is removed from core dependencies or retained only in a documented compatibility extra; all gates pass. **Live smoke:** blocked-on-key `ANTHROPIC_API_KEY`.

**Effort:** L. **Dependencies:** P1-T2, P1-T3, P1-T4.

### P1-T6 — Implement structured-output negotiation and bounded parsing

**Covers:** architecture §4.3.

**Goal:** Select tool → JSON Schema → prompt output by declared capabilities and parse each mode conservatively. **Why:** compatible endpoints vary, and silent fallback or permissive repair can cause extra paid calls or mutate content.

**Files to create/modify:** create `src/halfblood/generation/structured_output.py`, parser/limit helpers as needed, create `tests/test_structured_output.py`.

**Test-first:** Parameterize capability sets and pins to assert `auto` ordering, pinned unsupported-mode errors, and strict mode disabling prompt fallback. For tool mode, require exactly one named call and support legacy `function_call`; for JSON Schema, parse exactly one content document and distinguish refusal/incomplete/malformed JSON; for prompt mode, accept a full object, one `json` fence, or the first balanced top-level object via a quote/escape-aware state machine. Reject greedy extraction, duplicate objects, excessive bytes/depth/items/string lengths, non-object roots, and semantic invalidity. Assert only a capability-related 400 under `auto` permits one recorded downgrade/second call; content/schema errors never trigger another paid call; local syntactic cleanup removes only BOM/fences/trailing prose and never changes values.

**Acceptance criteria:** Mode selection is deterministic/auditable; all outputs finish with Pydantic validation; limits are explicit constants/config; no regex JSON extraction or semantic repair call exists by default; all gates pass.

**Effort:** L. **Dependencies:** P1-T2, P1-T4.

### P1-T7 — Add OpenAI-compatible HTTP adapter and provider profiles

**Covers:** architecture §§4.1, 4.3 OpenAI/JSON/prompt, 4.4.

**Goal:** Support OpenAI, OpenRouter, Ollama, LM Studio, and arbitrary compatible endpoints through one adapter and profile registry. **Why:** separate provider implementations would duplicate wire behavior and make “cheap/local model” support brittle.

**Files to create/modify:** create `src/halfblood/generation/providers/openai_compat.py`, `registry.py`, profile definitions, create `tests/test_openai_compat_provider.py`, `tests/test_provider_profiles.py`.

**Test-first:** With `MockTransport`, assert endpoint joining and payloads for forced function (`strict`, forced `tool_choice`, `parallel_tool_calls=false` when supported), JSON Schema `response_format`, and prompt mode. Parse modern `tool_calls`, legacy `function_call`, JSON content, refusals, incomplete finishes, usage/request IDs, and bounded arguments. Parameterize profiles to assert exact default base URLs/key envs and that OpenRouter optional attribution headers appear only when configured; Ollama/LM Studio use the same adapter and no key; arbitrary compatible requires an explicit base URL/model. Test divergent 400/error body shapes and taxonomy mapping without leaking response secrets. Run one shared contract suite against Anthropic and OpenAI adapters for normalized invariants.

**Acceptance criteria:** Exactly two wire adapters exist; all five profiles resolve correctly; no network; no silent strategy switch outside P1-T6 policy; concurrency stays 1; all gates pass.

**Effort:** L. **Dependencies:** P1-T3, P1-T4, P1-T6.

### P1-T8 — Add provider doctor and saved plan/report boundary

**Covers:** architecture §§4.4, 6.2, 9 Phase 1 (saved plan/checkpoint format; not Phase 5 resume scheduling).

**Goal:** Expose redacted provider diagnostics and atomically persist validated v2 plans/reports for reuse. **Why:** users need to diagnose profiles before paying, and provider-independent rendering requires a durable boundary.

**Files to create/modify:** `src/halfblood/cli.py`, config/provider registry, create plan I/O module (for example `src/halfblood/plan_io.py`), create `tests/test_provider_doctor.py`, `tests/test_plan_io.py`.

**Test-first:** `halfblood providers doctor --offline` makes zero transport calls and prints provider, redacted endpoint, explicit model state, configured capabilities/mode, and config sources; missing requirements exit nonzero without a traceback/key. Online doctor clearly announces one minimal request, uses an injected mock transport, reports latency/request ID/capabilities, and maps failure taxonomy; test that it never probes multiple strategies silently. Save a v2 plan plus report to a temp destination and assert atomic replace, schema/hash/provider provenance, no secret/raw prompt persistence, deterministic reload, refusal to overwrite without force, and migration when loading v1. A simulated write failure must leave an existing destination intact. Do not add resume/concurrent scheduling.

**Acceptance criteria:** Offline doctor is truly offline; online doctor is one disclosed mocked request; keys are redacted; saved artifacts round-trip/migrate atomically; all gates pass. **Live doctor:** blocked-on-key for hosted Anthropic, optional and not required for commit.

**Effort:** M. **Dependencies:** P1-T5, P1-T7.

### P1-T9 — Route CLI and eval through the provider seam

**Covers:** architecture §§2.6, 4.4, 9 Phase 1; AUD-34.

**Goal:** Make annotate, preview, web-preview generation, and eval share provider/config/report behavior while requiring an independent judge configuration. **Why:** duplicated Anthropic clients undermine provider choice and let the generator grade itself.

**Files to create/modify:** `src/halfblood/annotation_generator.py` or new `src/halfblood/generation/generator.py`, `src/halfblood/cli.py`, `eval/eval_harness.py`, package compatibility exports, CLI/eval tests, README/config docs.

**Test-first:** Inject fake providers and invoke each generation command, asserting identical resolution of `--provider`, `--model`, `--base-url`, `--api-key-env`, `--structured-output`, `--timeout`, retry setting, `--config`, and enforced concurrency 1; output shows selected provider/model/mode before calls and a final success/partial/failure report. Assert no command constructs an Anthropic SDK/client directly. Eval tests provide distinct generator and judge provider/model settings, reject identical provider+model unless an explicit development override is supplied, and prove calls route to the correct fake; retain `HALFBLOOD_EVAL_MODEL` only through a documented compatibility mapping. Assert partial/all-failed exit semantics still match merged tests and saved plans can drive previews without any provider call.

**Acceptance criteria:** One generation seam serves product and eval; AUD-34 is closed; no universal model default is used for non-Anthropic profiles; concurrency is 1; compatibility API is documented for one minor release; full gates pass. **Hosted E2E matrix:** blocked on the corresponding API keys; local mocked/profile tests are mandatory and sufficient for commit.

**Effort:** L. **Dependencies:** P1-T5, P1-T7, P1-T8.

## Summary and critical path

This plan contains **12 Phase 0 tasks** and **9 Phase 1 tasks**. Phase 0 closes every unmerged AUD finding plus L-1/L-2/L-3, with the mandated coupled batches kept intact: response handling (AUD-05/14/21 with AUD-10/23 and typing), regex correctness/security/tests (AUD-06/25, plus AUD-35), PDF geometry (AUD-07/08/09/20/40), and documentation drift (AUD-11/12/13/27–30/33/44). Phase 1 proceeds from plan v2 → canonical schema/config/contracts → Anthropic parity and structured policy → OpenAI-compatible profiles → doctor/persistence → CLI/eval cutover. The principal critical path is **P0-T1 → P0-T2 → P0-T3/P0-T8 → P0-T12 → P1-T1 → P1-T2/P1-T3 → P1-T4 → P1-T5/P1-T6 → P1-T7 → P1-T8 → P1-T9**. Only live Anthropic PDF/EPUB/doctor smoke checks are blocked on `ANTHROPIC_API_KEY`; all implementation gates are offline and mocked.
