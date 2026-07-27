---
title: "Runtime dependency and tech-stack validation"
type: decision-record
status: ACCEPTED
date_opened: 2026-07-24
decided_on: 2026-07-24
covers: [runtime dependencies, eval extra, provider transport, PDF rendering, EPUB rendering]
---

# Runtime dependency and tech-stack validation

## Status: ACCEPTED — retain the current dependency set

The declared runtime dependencies use intentional upper bounds that exclude unreviewed major
versions; EbookLib is additionally capped at its tested pre-1.0 minor because its write-time head
regeneration behavior is relied upon (`pyproject.toml:26-40`). The optional `eval` extra separately
includes Anthropic and repeats Rich (`pyproject.toml:43`).

One premise in the existing validation brief is stale. `CLAUDE.md` describes the Anthropic SDK as
the direct-call production dependency (`CLAUDE.md:42-54`), but the production Anthropic adapter
states that it uses `httpx` without a vendor SDK and posts directly to `/v1/messages`
(`src/halfblood/generation/providers/anthropic.py:1-12`,
`src/halfblood/generation/providers/anthropic.py:44-45`,
`src/halfblood/generation/providers/anthropic.py:99-107`). The Anthropic package is no longer declared anywhere: the `eval` extra dropped it once the
judge migrated to the shared provider seam, and as of 2026-07-27 it is gone from
`requirements-dev.lock` too. Nothing in `src/`, `eval/`, `tests/` or `scripts/` imports it. Therefore the `CLAUDE.md` “Direct Anthropic SDK” row, its SDK retry
discussion, and its `anthropic.AsyncAnthropic` suggestion are stale descriptions of the main
generation path (`CLAUDE.md:49`, `CLAUDE.md:86-88`).

## 1. httpx (`>=0.27.0,<1`)

**Used for.** This is the core provider transport, not an incidental helper
(`pyproject.toml:31`). `AnthropicProvider` constructs an `httpx.Client`, sends the Messages API
request directly, and classifies `httpx` transport failures
(`src/halfblood/generation/providers/anthropic.py:59-77`,
`src/halfblood/generation/providers/anthropic.py:95-116`). `OpenAICompatibleProvider` likewise
constructs an `httpx.Client`, posts to `/chat/completions`, and handles transport failures
(`src/halfblood/generation/providers/openai_compat.py:50-64`,
`src/halfblood/generation/providers/openai_compat.py:99-103`,
`src/halfblood/generation/providers/openai_compat.py:118-135`). Both constructors accept an
injectable `httpx.BaseTransport`, which provides the transport seam used by callers and tests
(`src/halfblood/generation/providers/anthropic.py:62-77`,
`src/halfblood/generation/providers/openai_compat.py:66-103`).

**Why it stays / alternatives.** Retain `httpx`: the repository owns a small, explicit wire
contract for both supported API shapes, including request construction, retry ownership, response
parsing, and error normalization
(`src/halfblood/generation/providers/anthropic.py:89-135`,
`src/halfblood/generation/providers/openai_compat.py:109-145`,
`src/halfblood/generation/providers/openai_compat.py:263-332`). Returning to the Anthropic vendor
SDK would cover only the Anthropic endpoint while discarding the shared injectable-transport
approach; that SDK is retained only where the eval judge constructs `Anthropic`
(`eval/eval_harness.py:41`, `eval/eval_harness.py:801-809`). No production requirement shown by
these call sites justifies adding a higher-level orchestration dependency.

**Thread safety.** `AnthropicProvider` creates a single `httpx.Client` in `__init__`
(`src/halfblood/generation/providers/anthropic.py:77`). `generate_for_document` submits
`_generate_for_page_tracked` tasks to a `ThreadPoolExecutor`
(`src/halfblood/annotation_generator.py:468-478`), all of which call
`self._provider.complete(request)` (`src/halfblood/annotation_generator.py:336`) on the same
shared provider — and therefore the same `httpx.Client` — across all `k` worker threads.
The usage accumulators (`total_input_tokens`, etc.) are aggregated from `future.result()` returns
in the main thread (`src/halfblood/annotation_generator.py:540-545`), not mutated inside worker
callables, so there is no unsynchronized counter state across threads. `httpx` documents `Client`
as safe for concurrent use across threads. Any injectable `BaseTransport` (the `transport=`
parameter at `src/halfblood/generation/providers/anthropic.py:69`) must also be thread-safe if
the provider is used with `k > 1`; the production default (no custom transport) is safe.

**Lock-in cost.** A swap would primarily rewrite the two provider adapters and any construction or
testing code that supplies their `BaseTransport` parameters
(`src/halfblood/generation/providers/anthropic.py:62-77`,
`src/halfblood/generation/providers/openai_compat.py:63-103`). Their normalized provider boundary
would remain available through `GenerationRequest` and `GenerationResult`
(`src/halfblood/generation/providers/anthropic.py:36-41`,
`src/halfblood/generation/providers/openai_compat.py:31-37`).

## 2. platformdirs (`>=4.0.0,<5`)

**Used for.** `config.py` imports `user_config_dir` and computes the user configuration file as
`Path(user_config_dir("halfblood")) / "config.toml"`; the project-local path is separately
`Path.cwd() / "halfblood.toml"` (`src/halfblood/config.py:20`,
`src/halfblood/config.py:310-325`). Its declared range is `>=4.0.0,<5`
(`pyproject.toml:32`).

**Why it stays / alternatives.** Retain `platformdirs`: the code needs one platform-appropriate
application config directory, while the alternative of hand-maintained operating-system branches
would replace a single library call with project-owned path policy
(`src/halfblood/config.py:310-325`). `pathlib` remains appropriate for composing the returned
directory with `config.toml`, but it does not choose the user config root in this implementation
(`src/halfblood/config.py:16`, `src/halfblood/config.py:320-322`).

**Lock-in cost.** The direct migration surface is confined to `config.py`'s import and default
`user_path` calculation (`src/halfblood/config.py:20`, `src/halfblood/config.py:310-325`).

## 3. pymupdf (`>=1.24.0,<2`)

**Used for.** The declared PyMuPDF range is `>=1.24.0,<2` (`pyproject.toml:33`). All three
capabilities cited in the original stack rationale are genuinely exercised:

| Capability | Verified call sites |
|---|---|
| Text extraction and search | PDF loading calls `page.get_text("text")` (`src/halfblood/document_processor.py:342-365`); target resolution calls `page.search_for` in both legacy and v2 paths (`src/halfblood/document_processor.py:474-513`, `src/halfblood/document_processor.py:533-609`); character geometry also consumes `get_text("rawdict")` and checks it against `get_text("text")` (`src/halfblood/documents/pdf.py:48-81`). |
| Native PDF annotation objects | Strikeout, highlight, circle, and underline are created with `add_strikeout_annot`, `add_highlight_annot`, `add_circle_annot`, and `add_underline_annot`, then styled and updated (`src/halfblood/document_processor.py:1158-1183`). |
| Shape text with affine morph | Six call sites use `Shape.insert_text(..., morph=...)`: resolved note and note body (`src/halfblood/document_processor.py:722-735`, `src/halfblood/document_processor.py:787-800`), margin and inline text (`src/halfblood/document_processor.py:1249-1261`, `src/halfblood/document_processor.py:1297-1311`), and between-line and replacement text (`src/halfblood/document_processor.py:1341-1353`, `src/halfblood/document_processor.py:1381-1393`). |

PyMuPDF also supplies the vector shape implementation used by the ink renderer: the renderer
creates a page shape, draws lines, Beziers, or polylines, and commits underlay and overlay
partitions (`src/halfblood/renderers/pdf.py:16-36`,
`src/halfblood/renderers/pdf.py:188-216`,
`src/halfblood/renderers/pdf.py:234-256`).

**Why it stays / alternatives.** The deciding factor is the combination of searchable text,
editable native annotations, affine-morphed text, page geometry, and vector drawing behind one
document/page model, all of which the current pipeline crosses in a single render flow
(`src/halfblood/document_processor.py:474-513`,
`src/halfblood/document_processor.py:1158-1183`,
`src/halfblood/document_processor.py:1249-1261`,
`src/halfblood/renderers/pdf.py:188-216`). `pdfplumber` is rejected as a read-only substitute
because it would not replace the native annotation or drawing calls; ReportLab is rejected as a
write-only substitute because it would not replace `search_for`; and pypdf is rejected because it
does not replace the required `Shape.insert_text(..., morph=...)` call sites. Using two or more of
them would introduce cross-library coordinate and document-lifecycle boundaries exactly where the
current code shares `fitz.Page`, `fitz.Rect`, `fitz.Quad`, and `fitz.Shape`
(`src/halfblood/documents/pdf.py:14-39`,
`src/halfblood/renderers/pdf.py:16-36`).

**License.** Installed `pymupdf` 1.28.0 declares its license as
`Dual Licensed — GNU AFFERO GPL 3.0 or Artifex Commercial License`
(`.venv/lib/python3.12/site-packages/pymupdf-1.28.0.dist-info/METADATA`; full text in
`COPYING` in the same directory). This is the single most legally consequential dependency
choice in the project. AGPL-3.0 carries a network-use clause (§13): any service that lets
users interact with the software over a network must release its complete corresponding source
under the same license, unless an Artifex commercial license is in place. Distribution of a
binary that incorporates AGPL-3.0 code carries similar obligations.

**RESOLVED (owner decision, 2026-07-24): the project ships under AGPL-3.0-or-later**
(`pyproject.toml:10`, `LICENSE`). Note that EbookLib compounds the constraint rather than
merely duplicating it: EbookLib is AGPLv3-**or-later with no commercial option**
(`.venv/lib/python3.12/site-packages/ebooklib-0.20.dist-info/METADATA`), so purchasing an
Artifex commercial license for PyMuPDF would **not** free the project from AGPL terms. AGPL
was therefore a constraint to be recognized, not a preference to be chosen.

**Lock-in cost.** This is the highest-cost swap. It would affect the main processor
(`src/halfblood/document_processor.py:48`), vector PDF renderer
(`src/halfblood/renderers/pdf.py:9`), PDF character geometry
(`src/halfblood/documents/pdf.py:7`), text-layer occupancy provider
(`src/halfblood/documents/pdf_occupancy.py:11`), and the fitz-to-surface layout adapter
(`src/halfblood/layout/anchors.py:1-9`). The surface-neutral layout engine is intentionally
fitz-free, which limits the rewrite beyond that adapter
(`src/halfblood/layout/engine.py:1`, `src/halfblood/layout/anchors.py:1-4`).

## 4. click (`>=8.1.0,<9`)

**Used for.** Click defines the root group and version option
(`src/halfblood/cli.py:380-384`), commands such as `annotate` and `preview`
(`src/halfblood/cli.py:387-461`, `src/halfblood/cli.py:583-604`), shared provider options
(`src/halfblood/cli.py:91-129`), and typed arguments and choices
(`src/halfblood/cli.py:388-438`). The console script targets `halfblood.cli:main`
(`pyproject.toml:66-67`), and Click's declared range is `>=8.1.0,<9`
(`pyproject.toml:34`).

**Why it stays / alternatives.** Retain Click. Typer is Click-based and would mainly move option
metadata into type annotations; the current CLI already expresses paths, choices, flags, groups,
subcommands, and shared decorator-generated options without a functional gap
(`src/halfblood/cli.py:91-129`, `src/halfblood/cli.py:380-438`,
`src/halfblood/cli.py:759-769`). A syntax-only migration would create churn without changing the
published entry point (`pyproject.toml:66-67`).

**Lock-in cost.** The direct rewrite is concentrated in `src/halfblood/cli.py`, including command
declarations, parameter conversion, usage errors, and user-facing exceptions
(`src/halfblood/cli.py:27`, `src/halfblood/cli.py:380-438`,
`src/halfblood/cli.py:464-468`).

## 5. pydantic (`>=2.0.0,<3`)

**Used for.** The project explicitly requires Pydantic v2 or later within major version 2
(`pyproject.toml:35`). The semantic models use `BaseModel`, `ConfigDict`, constrained `Field`
definitions, and v2 `field_validator` / `model_validator` decorators
(`src/halfblood/models/annotations.py:6-6`,
`src/halfblood/models/annotations.py:25-51`,
`src/halfblood/models/annotations.py:70-81`). Versioned document models validate and serialize
plans with `model_validate` and `model_dump`
(`src/halfblood/models/documents.py:31-38`,
`src/halfblood/models/documents.py:85-89`,
`src/halfblood/models/documents.py:113-117`). Generation models produce the provider JSON Schema
with `model_json_schema` (`src/halfblood/generation/schema.py:14-23`,
`src/halfblood/generation/schema.py:55-62`,
`src/halfblood/generation/schema.py:117-130`), and the Anthropic adapter validates each returned
annotation while catching `ValidationError`
(`src/halfblood/generation/providers/anthropic.py:23`,
`src/halfblood/generation/providers/anthropic.py:241-248`).

**Why it stays / alternatives.** Retain Pydantic v2 because the same definitions currently enforce
runtime constraints, strict unknown-field policy, serialization, loading, and provider-schema
generation (`src/halfblood/models/annotations.py:25-51`,
`src/halfblood/models/documents.py:85-89`,
`src/halfblood/generation/schema.py:117-130`). Dataclasses plus a separate schema/validation stack
would split those responsibilities, while a v1 downgrade would require replacing the v2
`model_validate`, `model_dump`, `model_json_schema`, `ConfigDict`, and validator APIs already used
(`src/halfblood/models/documents.py:85-89`,
`src/halfblood/generation/schema.py:14-23`,
`src/halfblood/generation/schema.py:117-123`).

**Lock-in cost.** A full swap would touch `src/halfblood/models/annotations.py`,
`src/halfblood/models/documents.py`, `src/halfblood/models/legacy.py`, and
`src/halfblood/models/rendering.py` at their model imports
(`src/halfblood/models/annotations.py:6`, `src/halfblood/models/documents.py:11`,
`src/halfblood/models/legacy.py:6`, `src/halfblood/models/rendering.py:25`). It would also affect
the generation schema and validation boundary (`src/halfblood/generation/schema.py:14`,
`src/halfblood/generation/structured_output.py:10`,
`src/halfblood/generation/providers/anthropic.py:23`) and the validated ink models and styles
(`src/halfblood/ink/model.py:9`, `src/halfblood/ink/style.py:11`).

## 6. rich (`>=13.0.0,<16`)

**Used for.** Rich is both a main dependency and an overlapping member of the eval extra
(`pyproject.toml:36`, `pyproject.toml:43`). The CLI imports `Console`, progress columns, and `Table`
and creates its shared console (`src/halfblood/cli.py:28-31`, `src/halfblood/cli.py:83`). The
`annotate` command reports extraction and generation through a Rich `Progress` context
(`src/halfblood/cli.py:509-529`), while CLI results are rendered as Rich tables
(`src/halfblood/cli.py:359-377`). The eval harness independently imports Rich console, panel,
progress, and table components (`eval/eval_harness.py:42-46`), uses a progress context
(`eval/eval_harness.py:525-559`), and builds report tables (`eval/eval_harness.py:567-585`).

**Why it stays / alternatives.** Retain Rich because progress, styled diagnostics, panels, and
tables share one console abstraction in both runtime CLI and eval reporting
(`src/halfblood/cli.py:28-31`, `src/halfblood/cli.py:509-529`,
`eval/eval_harness.py:42-46`, `eval/eval_harness.py:567-585`). Plain Click output would require
project-owned progress and table formatting while losing that shared rendering layer at the
existing call sites.

**Lock-in cost.** The direct migration surface is `src/halfblood/cli.py` and
`eval/eval_harness.py`, where Rich is imported and instantiated
(`src/halfblood/cli.py:28-31`, `src/halfblood/cli.py:83`,
`eval/eval_harness.py:42-46`, `eval/eval_harness.py:753-765`).

## 7. ebooklib (`>=0.18,<0.21`)

**Used for.** EbookLib reads EPUB containers, walks typed spine items, mutates chapter content and
manifest items, and writes the result (`src/halfblood/epub_processor.py:48-50`,
`src/halfblood/epub_processor.py:258-305`,
`src/halfblood/epub_processor.py:702-716`,
`src/halfblood/epub_processor.py:747-762`). Its range is capped at `>=0.18,<0.21`
(`pyproject.toml:37`).

**Why it stays / alternatives.** Retain EbookLib because the renderer depends on its cohesive
book, spine, item, manifest, TOC, and write APIs rather than treating an EPUB as unstructured ZIP
members (`src/halfblood/epub_processor.py:269-305`,
`src/halfblood/epub_processor.py:702-716`,
`src/halfblood/epub_processor.py:747-762`). The cap is deliberate: the dependency is pre-1.0,
minor bumps may break behavior, and the renderer depends on write-time head regeneration
(`pyproject.toml:26-29`).

The code contains a concrete compatibility workaround. `_ensure_toc_uids`, beginning at line 718,
backfills missing `uid` values on parsed `Link` and `Section` entries to avoid a write-time
`TypeError` from EbookLib 0.20 (`src/halfblood/epub_processor.py:718-745`). Both render paths call
the repair immediately after `read_epub` and before `write_epub`. The two `_ensure_toc_uids`
invocations are at `src/halfblood/epub_processor.py:529` (first render path) and
`src/halfblood/epub_processor.py:656` (second render path, `render_annotations`); the two
`write_epub` endpoints that prove the ordering constraint are at
`src/halfblood/epub_processor.py:631` and `src/halfblood/epub_processor.py:716`.

**Lock-in cost.** The direct swap is concentrated in `src/halfblood/epub_processor.py`, but it
would replace container reading/writing, spine traversal, typed items, TOC handling, stylesheet
manifest updates, and chapter content updates
(`src/halfblood/epub_processor.py:258-305`,
`src/halfblood/epub_processor.py:528-548`,
`src/halfblood/epub_processor.py:702-716`,
`src/halfblood/epub_processor.py:718-762`).

## 8. beautifulsoup4 (`>=4.12.0,<5`)

**Used for.** Beautiful Soup parses EPUB chapter HTML, strips non-content tags for extraction, and
provides the mutable node types used to locate and wrap annotation targets
(`src/halfblood/epub_processor.py:49`,
`src/halfblood/epub_processor.py:307-316`,
`src/halfblood/epub_processor.py:386-415`). Its declared range is `>=4.12.0,<5`
(`pyproject.toml:38`).

**Why it stays / alternatives.** Beautiful Soup owns the forgiving HTML/DOM layer: the processor
explicitly chooses lenient HTML handling for imperfect real-world chapter XHTML
(`src/halfblood/epub_processor.py:75-81`) and performs tag creation and text-node replacement
through its API (`src/halfblood/epub_processor.py:820-840`,
`src/halfblood/epub_processor.py:897-920`). Rewriting directly against lxml would duplicate this
mutation and malformed-input policy without removing the need for an HTML tree.

**Lock-in cost.** A swap would affect the parser and DOM manipulation in
`src/halfblood/epub_processor.py` (`src/halfblood/epub_processor.py:49`,
`src/halfblood/epub_processor.py:307-316`,
`src/halfblood/epub_processor.py:778-920`) and the Beautiful Soup node-based EPUB matching helpers
in `src/halfblood/documents/epub.py` (`src/halfblood/documents/epub.py:8`).

## 9. lxml (`>=5.0.0,<7`)

**Used for.** lxml is the parser backend selected by each relevant Beautiful Soup construction:
plain-text extraction uses `BeautifulSoup(html, "lxml")`
(`src/halfblood/epub_processor.py:307-316`), and both render paths parse chapter content with the
same backend (`src/halfblood/epub_processor.py:548`,
`src/halfblood/epub_processor.py:679`). Its declared range is `>=5.0.0,<7`
(`pyproject.toml:39`).

**Why it stays / alternatives.** The division of labor is deliberate: Beautiful Soup supplies the
lenient traversal and mutation API, while `"lxml"` selects its concrete parser backend at all
three construction sites (`src/halfblood/epub_processor.py:49`,
`src/halfblood/epub_processor.py:310`,
`src/halfblood/epub_processor.py:548`,
`src/halfblood/epub_processor.py:679`). Using Python's built-in parser would remove the lxml
dependency but change the parser behind the same mutation code; using lxml directly would instead
rewrite the Beautiful Soup node API used throughout the renderer
(`src/halfblood/epub_processor.py:386-415`,
`src/halfblood/epub_processor.py:820-920`).

**Lock-in cost.** Swapping only the backend changes the three parser-selection sites in
`src/halfblood/epub_processor.py` (`src/halfblood/epub_processor.py:310`,
`src/halfblood/epub_processor.py:548`,
`src/halfblood/epub_processor.py:679`); replacing both lxml and Beautiful Soup expands the cost to
the DOM operations described above (`src/halfblood/epub_processor.py:386-415`,
`src/halfblood/epub_processor.py:778-920`).

## 10. anthropic (`>=0.30.0,<2`)

**Used for.** Anthropic is not a main dependency; it is declared only in the `eval` extra
(`pyproject.toml:42-43`). The eval harness imports `Anthropic`, types its judge client with that
class, and constructs the judge client after requiring an Anthropic judge provider
(`eval/eval_harness.py:41`,
`eval/eval_harness.py:525-530`,
`eval/eval_harness.py:801-809`).

**Why it stays / alternatives.** Retain it in the eval extra for the current judge path, but do not
describe it as the production generation transport. Note that the declared upper bound `<2`
currently admits any 1.x release, including a hypothetical 1.0 that could introduce breaking
changes — this mirrors the pattern documented for Pydantic in §5 ("Revisit before accepting
Pydantic 3"). The re-evaluation trigger below captures this explicitly.

Production annotation generation defaults to
`AnthropicProvider` (`src/halfblood/annotation_generator.py:198-216`), and that provider directly
constructs and calls `httpx.Client` (`src/halfblood/generation/providers/anthropic.py:59-77`,
`src/halfblood/generation/providers/anthropic.py:95-108`). The provider module also explicitly
records that the vendor SDK is no longer imported in `src/`
(`src/halfblood/generation/providers/anthropic.py:9-12`). Reusing the production provider boundary
for judging is the natural future alternative once the eval judge no longer needs the SDK-specific
client interface (`eval/eval_harness.py:525-530`, `eval/eval_harness.py:801-809`).

**Lock-in cost.** Removing the SDK affects only the eval harness's import, judge-client type, client
construction, and SDK-style judging calls, not either production provider
(`eval/eval_harness.py:41`,
`eval/eval_harness.py:525-530`,
`eval/eval_harness.py:801-809`;
`src/halfblood/generation/providers/anthropic.py:22`,
`src/halfblood/generation/providers/openai_compat.py:17`).

## Open risks / re-evaluation triggers

| Dependency | Re-evaluate when |
|---|---|
| httpx | Revisit if the two direct adapters can no longer share the current client/transport boundary, or if manually tracking a breaking Anthropic wire change — the hardcoded `ANTHROPIC_API_VERSION = "2023-06-01"` at `src/halfblood/generation/providers/anthropic.py:44` is the concrete staleness tripwire — becomes riskier than adopting the vendor SDK (`src/halfblood/generation/providers/anthropic.py:44-45`, `src/halfblood/generation/providers/anthropic.py:62-77`, `src/halfblood/generation/providers/openai_compat.py:66-103`). |
| platformdirs | Revisit if configuration storage expands beyond the single user config file or its path policy must become portable across a non-filesystem environment (`src/halfblood/config.py:310-325`). |
| pymupdf | Revisit if the project selects a distribution license incompatible with AGPL-3.0, or if an Artifex commercial license is evaluated (see §3 License note); also revisit if another library demonstrably replaces search, native annotations, morph text, geometry, and vector drawing together at the verified call sites (`src/halfblood/document_processor.py:474-513`, `src/halfblood/document_processor.py:1158-1183`, `src/halfblood/document_processor.py:1249-1261`, `src/halfblood/renderers/pdf.py:188-216`). |
| click | Revisit if the CLI requires a type-hint-driven command API or another framework supplies a concrete feature missing from the existing groups, commands, choices, paths, and shared options (`src/halfblood/cli.py:91-129`, `src/halfblood/cli.py:380-438`, `src/halfblood/cli.py:759-769`). |
| pydantic | Revisit before accepting Pydantic 3, or if provider-schema generation and runtime model validation cease to share compatible definitions (`pyproject.toml:35`, `src/halfblood/generation/schema.py:117-130`, `src/halfblood/generation/providers/anthropic.py:241-248`). |
| rich | Revisit if non-terminal output becomes the primary interface, or if the CLI and eval harness no longer need progress and tabular terminal reports (`src/halfblood/cli.py:509-529`, `eval/eval_harness.py:534-559`, `eval/eval_harness.py:567-585`). |
| ebooklib | Revisit when EbookLib reaches 1.0 with a stable API and the TOC UID round-trip defect is fixed, or whenever moving beyond the tested minor removes the current workaround and write-time behavior dependency (`pyproject.toml:26-29`, `src/halfblood/epub_processor.py:718-745`). |
| beautifulsoup4 | Revisit if EPUB inputs become strictly valid XHTML or DOM mutation is redesigned around a renderer-neutral tree API (`src/halfblood/epub_processor.py:75-81`, `src/halfblood/epub_processor.py:820-920`). |
| lxml | Revisit if deployment constraints make its backend unacceptable, or parser-compatibility tests show that another Beautiful Soup backend preserves the three current parse paths (`src/halfblood/epub_processor.py:310`, `src/halfblood/epub_processor.py:548`, `src/halfblood/epub_processor.py:679`). |
| ~~anthropic~~ (removed) | **Resolved 2026-07-27.** The eval judge did move behind `LLMProvider`, so the SDK was dropped from `pyproject.toml` — but it survived in `requirements-dev.lock` as `anthropic==0.116.0`, and README instructs developers to `pip install -r requirements-dev.lock`, so the documented dev setup still installed a vendor package nothing imports. Now removed from the lock, with `tests/test_packaging.py::test_dev_lock_declares_no_llm_vendor_sdk` pinning the lock as well as `pyproject.toml` — the original policy test checked only the latter, which is how this survived. |
