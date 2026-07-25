# Phase 2 + Phase 3 implementation plan

**Date:** 2026-07-11  
**Ground truth:** `docs/superpowers/specs/2026-07-11-full-project-architecture.md` §§3, 5.2–5.6, 5.9, 7.2–7.3, 9–10, 12; `docs/audit/2026-07-11-phase0-closure.md`  
**Scope:** target resolution/layout correctness and PDF-first shared procedural ink only

## Execution notes

Execute one task at a time. For every task, the controller first writes the specified failing pytest tests and confirms they fail for the intended reason; Codex then implements only that task; the controller runs `ruff check src tests eval`, `mypy src/halfblood`, and `pytest tests/ -q`, and commits only after all three gates pass. Tests are mocked, deterministic, and offline. They use synthetic text/DOM/PDF fixtures and spies around drawing calls; no provider, network, system font, or reader application is required. Only tasks explicitly labeled geometry/visual/performance golden may rasterize checked-in project-authored or public-domain fixtures. Golden updates require explicit maintainer review and never happen as an incidental implementation update.

Phase 1 has not landed at plan-writing time. Do not pre-create guessed Phase 1 provider or model interfaces. Tasks marked Phase-1-independent start from the current `src/halfblood/document_processor.py`, `epub_processor.py`, and `models.py` shape and leave narrow compatibility adapters. Tasks that need stable annotation IDs, v2 source locators, or the package split wait for the named Phase 1 task and attach to its actual merged types. Preserve all Phase 0 tests and behavior, including deterministic first-hit compatibility where an old caller supplies only `target_text`. The uncommitted `--font`/registered-font feature is treated as delivered and is not part of this plan; later legacy-typeset work may consume it but must not redesign it.

Phase 3 has a separate legal gate. P3-T1 through P3-T4 use only models and project-authored algorithms and can ship before letter assets. **P3-T5 is blocked-on-owner-decision** for stroke-alphabet authorship, provenance, license, attribution, modification, and redistribution. P3-T6 through P3-T10 must not begin, ship placeholder alphabets, derive centerlines from a font, or claim genuine handwritten letters until that gate records a go decision. A no-go pauses those tasks while leaving rough marks and the explicitly selected legacy typeset mode usable.

## Phase 2 — target resolution and layout correctness

### P2-T1 — Build a normalized text index with reversible offsets

**Covers:** architecture §§3.1–3.2, 5.5, 7.2; Phase 2 normalized text indexes.

**Goal:** Create one bounded, surface-neutral normalized-text index that maps normalized character spans back to exact source offsets. **Why:** the current PDF and EPUB search helpers normalize independently, lose occurrence identity, and cannot support contextual selection or cross-node ranges reliably.

**Files to create/modify:** create `src/halfblood/documents/matching.py` and `src/halfblood/documents/__init__.py`; modify `src/halfblood/document_processor.py`, `src/halfblood/epub_processor.py`; create `tests/test_text_index.py`; retain current targeting tests.

**Test-first:** Parameterize straight/curly quotes, apostrophes, en/em dashes, tabs, CRLF, repeated whitespace, Unicode composed/decomposed accents, leading/trailing whitespace, and empty input. Assert normalization is documented and symmetric; every normalized `[start, end)` maps to the smallest covering raw half-open span; slicing the raw span renormalizes to the indexed text; repeated occurrences remain distinct and ordered; source segment boundaries can be retained without changing normalized text. Assert `find_all(literal)` returns all overlapping/non-overlapping candidates according to one documented rule, rejects blank/over-limit needles, performs no regex construction, and has explicit maximum input/candidate limits. Pin the current PDF/EPUB normalization helpers as compatibility delegates rather than two divergent implementations.

**Acceptance criteria:** One typed index owns normalization and reversible offset mapping; repeated matches are not collapsed; work is structurally bounded; existing Phase 0 smart-punctuation and target tests remain green; all standard gates pass.

**Effort:** M. **Dependencies:** none. **Phase 1:** independent; after P1-T1 lands, accept its actual document/source-locator values without changing index semantics.

### P2-T2 — Represent quote selectors and contextual evidence

> **STATUS (2026-07-16): DONE — merged `2b274ae`, 667 green.** Re-scoped (owner-approved):
> P1-T1 already delivered the selector surface (exact/prefix/suffix/offsets, versioning,
> unknown-version rejection). Genuine delta built = `normalized_exact/prefix/suffix` views +
> `start_offset <= end_offset` validation. See `.superpowers/sdd/progress.md` (Session 19) and
> `.superpowers/sdd/p2-t2-brief.md`. Deliberately declined: per-selector version field, coarse
> unit/page/chapter offset field (arch §6.1 has neither).

**Covers:** architecture §§3, 5.5, 6.1, 10.12; Phase 2 quote selectors/context.

**Goal:** Represent a requested quote, optional prefix/suffix context, and approximate source position without embedding surface geometry. **Why:** `target_text` alone cannot disambiguate repeated phrases, while coordinates in the semantic plan would make saved generation surface-specific.

**Files to create/modify:** create or extend the Phase 1 annotation/document model files only after they exist; until then create compatibility types beside `src/halfblood/documents/matching.py`; modify `src/halfblood/models.py` only for a non-breaking re-export if needed; create `tests/test_quote_selector.py` and v1/v2 migration fixtures in the Phase 1-established location.

**Test-first:** Assert a selector requires a nonblank exact quote; prefix/suffix are normalized but preserve raw serialized values; approximate unit/page/chapter offset is optional and range-validated; unknown future selector versions fail explicitly. Assert current `Annotation(target_text=...)` adapts deterministically to an exact-only selector with no invented context, and selector-to-JSON round-trips without geometry. Once P1-T1 is merged, extend its real v1 migration fixtures to prove stable IDs and existing serialized plans are unchanged except for documented defaults; do not replace or guess its migration entry point.

**Acceptance criteria:** Exact-only legacy annotations remain valid; contextual selectors are renderer-neutral, versioned through the actual Phase 1 model boundary, and losslessly serialized; no provider schema asks for coordinates; all standard gates pass.

**Effort:** M. **Dependencies:** P2-T1. **Phase 1:** core selector validation may proceed independently, but durable v2 serialization/migration integration is blocked on P1-T1.

### P2-T3 — Score all target candidates and reject ambiguity

> **STATUS (2026-07-16): DONE — merged `0f336de`, 694 green.** Built the tier-dominant
> exactness ladder (interpretation B: full-exact tier dominates every shortened candidate;
> parity with `_search_variants`). Adversarial review caught a real blocker — ambiguity was
> decided on context alone, leaving `offset_score` inert — fixed test-first so proximity breaks
> context near-ties (plan line 60 / §6.1). `_search_variants` superseded as the repeated-fallback
> authority; processor cutover deferred to P2-T8/T9. Non-blocking follow-up: `AMBIGUITY_MARGIN`
> comment now understates its dual (context+offset) role. See progress.md Session 20.

**Covers:** architecture §§5.5, 5.9, 7.2, 9 Phase 2; inherited `_search_variants` ambiguity gap.

**Goal:** Rank every literal candidate using explicit evidence and return a match, ambiguous result, or no match with diagnostics. **Why:** first-hit/fallback-word selection silently annotates the wrong repeated passage and cannot explain why a target was skipped.

**Files to create/modify:** `src/halfblood/documents/matching.py`; create `tests/test_candidate_scoring.py`; modify `tests/test_pdf_targeting.py`, `tests/test_epub_processor.py` only to preserve legacy adapter expectations.

**Test-first:** Build repeated-quote fixtures varying exactness, prefix/suffix agreement, normalized case/punctuation, source offset, line continuity, and uniqueness. Assert the full exact quote outranks every shortened candidate; context agreement outranks proximity; proximity breaks only otherwise equal scores; stable source order is the final deterministic tie-break only above the confidence threshold. Assert a tie/near-tie inside a documented ambiguity margin returns `ambiguous` with candidate spans/scores, never a guessed hit. Assert exact-only legacy mode retains deterministic first exact occurrence but never promotes a repeated fallback token; candidate counts and diagnostic reasons are bounded and contain no source text beyond configured excerpts.

**Acceptance criteria:** Scoring weights/order, minimum score, and ambiguity margin are named constants or configuration with tests; ambiguous low-confidence targets are skipped/reportable; `_search_variants` is no longer an authority for choosing repeated fallback words; all standard gates pass.

**Effort:** L. **Dependencies:** P2-T1, P2-T2. **Phase 1:** independent for scoring; consume P1-T1 selectors/IDs through the P2-T2 adapter when available.

### P2-T4 — Resolve PDF targets to ordered multi-quad anchors

> **STATUS (2026-07-17): DONE — merged `9d55b23`, 714 green.** New `documents/pdf.py`
> (`PdfPageIndex` + `resolve_pdf_anchor` + `PdfAnchor`) maps a selected char range to ordered
> per-line quads in displayed space (rotation_matrix applied, within page.rect); never unions
> separate lines/occurrences. `find_text_rect` delegates only geometry, legacy selection
> unchanged (scorer wiring deferred to P2-T8/T9). Opus review CLEAN. Follow-ups: baseline-noise
> assertion delegated to MuPDF (untested by design); `_page_rect` unused. See progress.md Session 21.

**Covers:** architecture §§3.1–3.2, 5.5–5.6, 7.2–7.3; Phase 2 PDF multi-quad ranges.

**Goal:** Map a selected PDF character range to ordered per-line quads without unioning separate lines or occurrences. **Why:** one union rectangle covers unrelated whitespace/body text, produces incorrect native marks, and gives layout/connectors unreliable geometry.

**Files to create/modify:** create `src/halfblood/documents/pdf.py` and `src/halfblood/layout/anchors.py` when the gradual split reaches them, otherwise first implement behind `src/halfblood/document_processor.py`; modify `tests/test_pdf_targeting.py`; create `tests/test_pdf_anchors.py`; extend `tests/fixtures/make_potions_textbook.py` only with authored geometry cases.

**Test-first:** Create in-memory PDFs with a phrase wrapping two/three lines, repeated phrases, hyphenation/whitespace drift, crop-box offsets, and 90/180/270-degree page rotation. Assert the selected candidate maps to one quad per touched line in reading order; quads have finite coordinates, stay within the effective page box, cover only selected words, and never bridge two occurrences. Assert line clusters tolerate small baseline noise but split at real line gaps. Assert the compatibility `find_text_rect` returns only the union of the chosen anchor's quads, while the new resolver exposes the quads and match diagnostics. Mock no drawing calls in this task.

**Acceptance criteria:** All tested PDF anchors preserve occurrence and line identity across page boxes/rotations; old callers retain a bounded rectangle adapter; no geometry is rendered yet; all standard gates pass.

**Effort:** L. **Dependencies:** P2-T3. **Phase 1:** resolver can start on current `fitz.Page`; attach the result to P1-T1's actual source locator/stable ID after it lands.

### P2-T5 — Resolve and wrap EPUB ranges across text nodes

> **STATUS (2026-07-17): DONE — merged `118728d`, 721 green.** Standalone cross-node
> capability: `documents/epub.py` (`iter_inline_runs` bounded by block tags;
> `locate_across_nodes` — per-run `NormalizedText`+`score_candidates`, tier-0 full-quote only,
> repeats within/across runs → None; ordered per-node segments) + `EpubProcessor.
> wrap_cross_node_segments` (reverse-order, markup-preserving, one note). `render_annotations`
> left UNCHANGED (routing is P2-T9). Opus review CLEAN. Follow-ups for P2-T9: note-placement
> consistency (currently after block parent), dead `_segments_for_span` guard. See progress.md S21.

**Covers:** architecture §§5.5, 5.8, 7.3, 9 Phase 2; inherited multi-`NavigableString` EPUB gap.

**Goal:** Resolve a selected quote across adjacent DOM text nodes and wrap exactly that range without flattening or duplicating markup. **Why:** targets split by emphasis, links, or inline spans are currently skipped, and naïve string replacement destroys valid XHTML structure.

**Files to create/modify:** create `src/halfblood/documents/epub.py` when appropriate or implement behind `src/halfblood/epub_processor.py`; modify `tests/test_epub_processor.py`; add a focused authored XHTML fixture under `tests/fixtures/` if clearer.

**Test-first:** Construct XHTML where one target spans plain text, `<em>`, `<strong>`, nested `<span>`, entity-decoded punctuation, and whitespace between nodes. Assert the locator returns ordered `(node, raw_start, raw_end)` segments whose concatenated normalized text equals the quote. Render a target that starts/ends mid-node and assert untouched siblings, attributes, links, element order, tail text, and original typography survive; no text is duplicated or lost; valid XHTML parses with lxml. Assert script/style/comment and existing `hbp-*` markup are excluded, ranges never cross forbidden block/chapter boundaries, two annotations in one node/range render deterministically, overlap follows a documented skip/report policy, and repeated cross-node candidates use P2-T3 scoring.

**Acceptance criteria:** Cross-inline-element targets are found and wrapped without DOM corruption; overlap/forbidden-boundary cases degrade explicitly; all existing EPUB round-trip/spine/CSS tests pass; all standard gates pass.

**Effort:** L. **Dependencies:** P2-T3. **Phase 1:** independent on current annotations; use actual v2 selectors/source locators once P1-T1 lands.

### P2-T6 — Define resolved-plan and render-report contracts

> **STATUS (2026-07-17): DONE — merged `6168e03`, 763 green.** New
> `src/halfblood/models/rendering.py`: versioned renderer-neutral `ResolvedPlan` +
> `RenderReport`, neutral serializable geometry (`SurfacePoint`/`SurfaceQuad`/`SurfaceRect`),
> `ResolvedAnchor` (char range + ordered quads, no provider data), `ResolvedAnnotation` (real
> `Annotation.id` / `Unit.source_locator` refs; requested-vs-resolved placement), finite
> `SkipReason`/`AnchorWarningCode`/`DegradationFlag` enums, exact rendered/skipped partition,
> stable degradation dedup, 64-hex output hashes, major-version-rejecting loaders; secrets
> structurally impossible (`extra="forbid"`). Placement extracted to a shared `Placement` alias
> in `annotations.py` and reused in both (real type, not a parallel substitute). Contract-only —
> no renderer cutover (P2-T8/T9). Folded in the deferred P2-T4 rotation×multi-line ordering test
> + `PdfAnchor` "reading order = content-stream, not visual" docstring. Opus review CLEAN (1
> non-blocking: vacuous alias-identity test — strengthened to a source-level guard, verified
> discriminating). EPUB serializable-range representation deferred to P2-T9 (documented minor
> extension point). See progress.md S22.

**Covers:** architecture §§3.1–3.2, 5.5, 5.9, 6, 10.8, 10.12.

**Goal:** Add versioned renderer-neutral records for resolved anchors, requested versus chosen placement, warnings, skips, degradations, and output identity. **Why:** layout decisions otherwise disappear into logs and renderers cannot share or audit the same geometry.

**Files to create/modify:** extend the actual Phase 1 `src/halfblood/models/rendering.py`/document model location after P1-T1; create `tests/test_resolved_plan.py`, `tests/test_render_report.py`; add compatibility exports only where Phase 1 establishes them.

**Test-first:** Assert `ResolvedPlan` links each result to the stable annotation ID and source locator from the merged Phase 1 model; anchors contain character range plus ordered surface geometry but not provider data; requested position remains unchanged when resolved placement differs; warnings/skips use finite enums/codes plus safe detail; report counts partition attempted annotations exactly into rendered/skipped; degradation flags deduplicate stably; output hashes are validated and secrets/raw provider payloads cannot be fields. Assert deterministic JSON round-trip, unknown future versions fail, empty plans/reports are valid, and old current-shape rendering can return/ignore the report without breaking callers.

**Acceptance criteria:** The semantic plan is not mutated by resolution; every attempted annotation has one observable disposition; contracts use Phase 1's real IDs/types rather than parallel substitutes; all standard gates pass.

**Effort:** M. **Dependencies:** P2-T2, P2-T4, P2-T5. **Phase 1:** blocked on P1-T1; saved report attachment also follows P1-T8's actual saved-plan/report boundary if it has landed.

### P2-T7 — Implement measured occupancy-based layout

**Covers:** architecture §§5.3, 5.5, 5.9, 7.2; inherited collision and both-margins-degenerate gaps.

**Goal:** Place measured notes by priority using per-side occupancy, bounded shifting, side switching, scaling, and safe fallback/skip decisions. **Why:** independently centered notes collide, overflow, or obscure source text, and handwritten bounds must influence layout before ink is drawn.

**Files to create/modify:** create `src/halfblood/layout/engine.py`; extend `src/halfblood/layout/anchors.py`; modify `src/halfblood/document_processor.py` only through an adapter; create `tests/test_layout_engine.py`, extend `tests/test_pdf_geometry.py`.

**Test-first:** Use a fake deterministic measurer returning known note bounds. Cover every edge/corner, multiple nearby targets, both requested margins, inline/interline requests with and without real gaps, long notes, unbreakable tokens, cropped/rotated page boxes, and occupied body/target rectangles. Assert higher-priority annotation types/confidence are placed first with stable ID tie-breaks; vertical intervals on the same side never overlap beyond tolerance; preferred side is retained when safe, otherwise bounded shift precedes side switch; scale never falls below the configured readable minimum; inline/interline falls back to a margin with a reason; no rectangle leaves page bounds or intersects forbidden target/body occupancy; both margins degenerate yields a skipped disposition, not off-page geometry. Property-style deterministic samples assert finite bounds and termination within configured attempts.

**Acceptance criteria:** Layout is deterministic and independent of drawing; all placements satisfy page, readability, occupancy, and attempt-budget invariants; every fallback/skip is represented in P2-T6 contracts; all standard gates pass.

**Effort:** L. **Dependencies:** P2-T4, P2-T6. **Phase 1:** blocked on P1-T1 through P2-T6; the fake measurer allows work before Phase 3 handwriting.

### P2-T8 — Cut PDF rendering over to resolved anchors and layout reports

**Covers:** architecture §§3, 5.5–5.6, 5.9, 7.3, 9 Phase 2.

**Goal:** Make the current typeset PDF renderer consume the resolved plan, mark every target quad, respect chosen layout boxes, and return a complete report. **Why:** correct locators/layout provide no value if the shipping path re-searches text or recomputes placement ad hoc.

**Files to create/modify:** `src/halfblood/document_processor.py`; the actual split `src/halfblood/documents/pdf.py`/`renderers/pdf.py` only as established incrementally; `src/halfblood/cli.py`; modify `tests/test_pipeline.py`, `tests/test_pdf_geometry.py`, `tests/test_pdf_targeting.py`; create `tests/test_pdf_render_report.py`.

**Test-first:** Spy on resolution, layout, native mark, note, connector, and save boundaries. Assert each annotation is resolved exactly once; drawing receives ordered target quads and the resolved note box; wrapped targets create one mark per quad rather than a union mark; annotations are processed in layout priority/order; ambiguous, missing, overlapping, and unplaceable targets cause no ink and produce distinct report codes; side switches and scale reductions are reported; rendered/skipped counts partition input including out-of-range pages. Assert source content/page boxes/rotation remain intact, output is written atomically, the CLI emits a concise report summary, and existing direct `add_margin_note` compatibility tests remain green. This remains typeset rendering and does not claim procedural ink.

**Acceptance criteria:** The PDF shipping path no longer performs private fallback placement after resolution; no tested collision/off-page case renders; report and CLI counts match observed drawing calls; all standard gates pass.

**Effort:** L. **Dependencies:** P2-T6, P2-T7. **Phase 1:** blocked on P1-T1 and attach saved reports using P1-T8 if available; independent of provider adapters P1-T2–P1-T7/P1-T9.

### P2-T9 — Integrate EPUB range resolution and close Phase 2 regressions

**Covers:** architecture §§5.5, 5.8–5.9, 7.2–7.3, 9 Phase 2.

**Goal:** Route EPUB rendering through the shared selector/scoring/range path and report every annotation outcome while retaining Phase 2's intentionally typeset EPUB presentation. **Why:** a standalone cross-node helper can regress unused, and EPUB misses/overlaps currently survive only as logs.

**Files to create/modify:** `src/halfblood/epub_processor.py`; gradual `src/halfblood/documents/epub.py`; `src/halfblood/cli.py`; modify `tests/test_epub_processor.py`; create `tests/test_epub_render_report.py`, `tests/test_phase2_regressions.py`; update `docs/ARCHITECTURE.md` only to describe shipped Phase 2 behavior.

**Test-first:** Render an authored EPUB containing repeated quotes, context-selected second occurrences, cross-node targets, two non-overlapping annotations in one text node, an overlapping pair, forbidden block crossings, missing targets, and an out-of-range spine index. Unzip and assert only selected ranges are marked; XHTML validates; text/links/metadata/spine/TOC/resources survive; stylesheet injection remains once; dispositions and counts exactly match markup. Add a format-parameterized regression asserting the same selector selects the same logical occurrence in normalized PDF and EPUB fixtures. Assert the known nav `linear="yes"` behavior remains pinned and reported honestly rather than being silently re-scoped.

**Acceptance criteria:** Both current renderers use shared candidate semantics; inherited repeated-match, collision, both-margins-degenerate, and cross-node EPUB gaps have permanent tests and observable reports; Phase 0 closure remains closed; all standard gates pass.

**Effort:** L. **Dependencies:** P2-T5, P2-T6, P2-T8. **Phase 1:** blocked on P1-T1/P2-T6; no dependency on live providers or Phase 1 HTTP work.

## Phase 3 — shared ink scene and procedural handwriting

### P3-T1 — Define and version the immutable InkScene model

**Covers:** architecture §§3.1–3.2, 5.2, 6.2, 7.2, 10.8.

**Goal:** Define a surface-neutral, immutable, versioned scene of groups, paths, commands, stroke styles, width profiles, transforms, z-order, and accessibility labels. **Why:** without a canonical scene, each renderer invents geometry/jitter and exact rerendering or cross-surface comparison is impossible.

**Files to create/modify:** create `src/halfblood/ink/model.py`, `src/halfblood/ink/__init__.py`; extend the actual Phase 1 `models/rendering.py` only for public references; create `tests/test_ink_scene.py`, `tests/fixtures/ink/` for small human-readable JSON fixtures.

**Test-first:** Construct every `MoveTo`/`LineTo`/`CubicTo` command and role. Assert scenes are immutable; reject NaN/Inf, negative widths, opacity outside `[0,1]`, invalid transforms, non-monotonic width-profile positions, pen-down paths without a move/segment, duplicate group IDs, and bounds that do not contain commands within tolerance. Assert stable serialization order and round-trip, explicit `scene_version`/`ink_algorithm_version`, unknown future versions fail, accessibility labels and degradation flags survive, and normalized local coordinates do not mention PDF/SVG types. Pin a small rounded-command structural hash without rasterizing.

**Acceptance criteria:** One validated scene contract can represent all architecture roles and pressure data; malformed/unbounded scenes fail before rendering; serialization is deterministic and versioned; all standard gates pass.

**Effort:** L. **Dependencies:** P2-T6. **Phase 1:** blocked on P1-T1/P2-T6 for stable annotation IDs; otherwise independent of providers and asset licensing.

### P3-T2 — Add stable labeled seeds and validated style profiles

**Covers:** architecture §§5.2–5.3, 5.9, 7.2, 10.8.

**Goal:** Derive independent deterministic PRNG streams and load validated palettes, nib, variation, readability, and budget settings. **Why:** Python `hash()`/global randomness breaks reproducibility, and unlabeled randomness makes adding a doodle change existing letters or marks.

**Files to create/modify:** create `src/halfblood/ink/seeding.py`, `src/halfblood/ink/style.py`; add built-in style TOML/JSON only if packaging conventions support it; create `tests/test_ink_seeding.py`, `tests/test_ink_style.py`; modify `pyproject.toml` only if package-data inclusion is required.

**Test-first:** Assert BLAKE2b-derived sub-seeds are stable for fixed `(document_seed, annotation_id, role, algorithm_version, label)`, differ when any component differs, are identical across subprocesses with different `PYTHONHASHSEED`, and do not touch `random`/NumPy global state. Assert requesting streams in a different order or adding a `doodle` stream leaves `handwriting`/`connector` output unchanged. Validate style ranges for colors, base/min/max nib width, opacity, slant/noise, minimum readable scale, and maximum points/paths; reject unknown keys unless explicitly versioned; assert built-ins load from an installed-package-like resource and canonical style hashes ignore irrelevant serialization ordering.

**Acceptance criteria:** Reproducibility is process-independent and role-isolated; styles and hard budgets are validated/versioned; no system font or asset is needed; all standard gates pass.

**Effort:** M. **Dependencies:** P3-T1. **Phase 1:** only stable IDs from P1-T1/P2-T6; not blocked on stroke licensing.

### P3-T3 — Generate seeded rough marks, connectors, and doodles

**Covers:** architecture §§5.2, 5.4–5.5, 12 caveat 2.

**Goal:** Generate project-authored rough underlines, circles, strikes, highlights, carets, obstacle-aware connectors, arrowheads, and a small parametric doodle vocabulary as InkScene groups. **Why:** these asset-free marks deliver the immediate scribbled visual language and must not be perfect native-PDF geometry or renderer-specific jitter.

**Files to create/modify:** create `src/halfblood/ink/rough.py`; extend `src/halfblood/ink/style.py`; create `tests/test_rough_ink.py`; add rounded SVG debug artifacts under `tests/fixtures/ink/` only for maintainer-reviewed geometry goldens.

**Test-first:** For fixed seeds/quads/styles, assert underline strokes follow each line separately with bounded overshoot/gaps; circles are open, irregular, and cover logical clusters; strikes cross each target line; highlights sit behind text with broad width; carets fit the resolved interline gap. Assert connectors start on the chosen note edge, end on the nearest target edge, avoid supplied rectangular obstacles within clearance, have cubic low-frequency wobble and a two-stroke arrowhead, and use a bounded routing-attempt fallback recorded as degradation. Assert supported doodle kinds are finite/semantic, unknown kinds reject or use a documented neutral fallback, all coordinates/point counts satisfy scene/style budgets, same seed is structurally identical, different seeds vary within bounds, and no external rough.js/code/assets are copied.

**Acceptance criteria:** Every non-letter role is reproducible, bounded, finite, and renderer-neutral; obstacle/fallback behavior is explicit; geometry goldens are human-readable and reviewed; all standard gates pass.

**Effort:** L. **Dependencies:** P3-T1, P3-T2, P2-T7. **Phase 1:** stable IDs only; not blocked on stroke-asset licensing because algorithms and doodles are project-authored.

### P3-T4 — Expand pressure strokes and simplify paths safely

**Covers:** architecture §§5.2, 5.4, 5.6, 5.9, 7.2.

**Goal:** Convert centerlines plus width profiles into valid filled outlines and simplify paths without visible topology or budget failures. **Why:** PDF cannot render a varying-width stroke consistently from centerline width samples, and uncontrolled point counts bloat output.

**Files to create/modify:** create `src/halfblood/ink/geometry.py` (or a narrowly named pressure module); modify `src/halfblood/ink/model.py`; create `tests/test_pressure_expansion.py`, `tests/test_path_simplification.py`.

**Test-first:** Cover straight, curved, acute, zero-length, repeated-point, pen-lift, and closed/open centerlines with constant and varying pressure. Assert expanded polygons are finite, closed, correctly oriented by a documented convention, bounded around the source centerline, use round caps/joins, do not exceed configured point limits, and degrade safely for degenerate samples. Assert simplification keeps endpoints/pen lifts, never exceeds tolerance smaller than the thinnest nib, preserves bounds/area within thresholds, is idempotent at fixed tolerance, and refuses input above hard budgets before quadratic work. Compare constant-width centerline and expanded-outline bounds within tolerance; no live renderer is used.

**Acceptance criteria:** Pressure expansion is one shared deterministic implementation; degenerate/pathological inputs terminate with explicit errors/degradations; simplification respects visual and complexity budgets; all standard gates pass.

**Effort:** L. **Dependencies:** P3-T1, P3-T2. **Phase 1:** independent beyond P3-T1; not blocked on stroke-asset licensing.

### P3-T5 — Record the stroke-asset licensing go/no-go decision

**Covers:** architecture §§5.1, 5.3, 8.3, 10 risk 1, 12 caveat 2.

**Goal:** Obtain and record an owner-approved redistributable source for the procedural trajectory alphabet before letterform implementation begins. **Why:** a font license does not automatically permit derived centerlines, and unverified assets would make genuine handwriting legally unshippable.

**Files to create/modify:** create `docs/decisions/stroke-assets.md`; create/modify `THIRD_PARTY_NOTICES.md`; create `src/halfblood/ink/assets/manifest.json` only after a go decision; create `tests/test_ink_asset_manifest.py` only for a go decision; modify packaging metadata only after approved assets exist.

**Test-first:** Before any asset is committed, the controller verifies the decision record names authorship/source, exact version or content hash, license, modification/derivation method, attribution and Reserved Font Name obligations if relevant, redistribution conclusion, approved character coverage, and approving owner/date. On go, write a manifest test asserting every packaged stroke/doodle/font/algorithm asset has a notice row, checksum, compatible declared license, source, modification status, and package-data inclusion; orphaned files and unknown licenses fail. On no-go, write no fake manifest test or placeholder alphabet: record the decision and stop P3-T6 through P3-T10.

**Acceptance criteria:** **Blocked-on-owner-decision.** A go requires a complete signed-off provenance record plus passing manifest/package tests; absence, ambiguity, “font is OFL,” or inference from open-source code is not approval. A no-go is an accepted gate outcome but does not authorize later letterform/PDF-handwriting tasks.

**Effort:** S engineering / owner review unbounded. **Dependencies:** none. **Phase 1:** independent. **Gate:** P3-T6 through P3-T10 are blocked until this task records go.

### P3-T6 — Package the approved trajectory alphabet and validate coverage

> ⛔ **BLOCKED — P3-T5 NO-GO (2026-07-19).** Do not start. The next runnable tasks are the un-gated
> **P3-T11 / P3-T12** below. See `docs/decisions/stroke-assets.md`.

**Covers:** architecture §§5.1, 5.3, 5.9, 8.3; Phase 3 procedural stroke assets.

**Goal:** Encode the approved centerline alphabet, alternates, contextual forms, ligatures, metrics, anchors, and pen lifts in a deterministic validated format. **Why:** the engine cannot synthesize genuine strokes from outlines or incomplete unvalidated trajectory data.

**Files to create/modify:** populate `src/halfblood/ink/assets/`; create `src/halfblood/ink/assets.py`; modify `pyproject.toml`, `THIRD_PARTY_NOTICES.md`; create `tests/test_stroke_assets.py`, `tests/test_stroke_asset_packaging.py` (`tests/test_packaging.py` already exists — P0-T12's dependency-bounds/audit-ledger-closure tests — do not overwrite it; see controller review).

**Test-first:** Load assets through package resources and assert lowercase/uppercase/digits/Latin-1 punctuation coverage promised by the approved manifest; 3–5 alternates for declared common letters; valid initial/medial/final forms and declared ligatures; finite ordered centerlines, explicit pen lifts, nonnegative advance/side bearings, entry/exit anchors inside tolerances, unique stable IDs, and checksum agreement. Assert missing/corrupt/unsupported-version assets fail clearly, installed-wheel-like loading needs no repository path, and unsupported Unicode returns a typed coverage result rather than silently borrowing a system font. Tests inspect data only and do not rasterize.

**Acceptance criteria:** Approved assets are complete for declared v1 coverage, reproducibly packaged, checksum/provenance matched, and never derived during build/runtime; no optional system font is needed; all standard gates pass.

**Effort:** L. **Dependencies:** P3-T2, P3-T5 go. **Phase 1:** independent of provider work; hard-blocked on the owner licensing decision.

### P3-T7 — Implement and measure the procedural stroke handwriter

> ⛔ **BLOCKED — P3-T5 NO-GO (2026-07-19).** Do not start. See `docs/decisions/stroke-assets.md`.
> (Carries the latent F2 `_douglas_peucker` cubic-awareness fix IF ever reopened.)

**Covers:** architecture §§3.2, 5.1–5.3, 5.9, 7.2.

**Goal:** Compose approved trajectories into word-shaped, line-wrapped handwriting with contextual variants, correlated natural variation, pressure, and explicit fallback/degradation. **Why:** independent glyph jitter looks typeset or plotter-broken and cannot honor real measured note boxes.

**Files to create/modify:** create `src/halfblood/ink/handwriting.py`, `src/halfblood/ink/procedural.py`; modify `src/halfblood/ink/style.py`; create `tests/test_procedural_handwriting.py`, `tests/test_handwriting_layout.py`; add reviewed rounded scene fixtures under `tests/fixtures/ink/`.

**Test-first:** Define a protocol from architecture behavior, not a guessed Phase 1 interface. Assert `measure/synthesize` agreement for words and multi-line notes; word-boundary wrapping; continuation state across lines; contextual alternate/ligature choice; join only when entry/exit geometry permits; preserved pen lifts; low-frequency baseline/slant/scale/spacing correlation; bounded control-point noise; pressure responding to speed/curvature; and rare imperfections controlled by style. For fixed input/style/box/seed assert identical commands; repeated occurrences with different annotation sub-seeds differ; shrinking retries stop at minimum readable scale; impossible boxes return a typed failure; point/path budgets terminate; unsupported Unicode emits explicit fallback runs/degradation and requires `allow_typeset_fallback` before any typeset substitution.

**Acceptance criteria:** Output is genuine centerline-derived strokes, measured before layout, deterministic, legible within configured bounds, and explicit about unsupported glyphs; no font outlines/system fonts drive normal output; all standard gates pass.

**Effort:** L. **Dependencies:** P3-T4, P3-T6. **Phase 1:** use actual stable IDs through P3-T2; hard-blocked on P3-T5 go.

### P3-T8 — Add content-addressed trajectory and scene caches

> ⛔ **BLOCKED — P3-T5 NO-GO (2026-07-19).** Do not start. See `docs/decisions/stroke-assets.md`.

**Covers:** architecture §§5.2–5.3, 5.9, 10.7–10.8.

**Goal:** Cache canonical word trajectories and transformed scenes by canonical content/style/box/seed/algorithm identity with corruption-safe invalidation. **Why:** procedural synthesis and pressure expansion repeat across renders, while stale or weak cache keys destroy reproducibility.

**Files to create/modify:** create `src/halfblood/ink/cache.py`; modify `src/halfblood/ink/procedural.py`; create `tests/test_ink_cache.py`; use `tmp_path` only—no real user cache.

**Test-first:** Assert canonical word keys include engine/asset/algorithm versions, normalized word, relevant style hash, and seed; scene keys additionally include annotation ID/content, resolved box/quads, role set, and degradation permissions. Assert irrelevant dict ordering does not change keys and every output-affecting field does. With a fake synthesizer, prove hit avoids work, miss computes once, memory/disk tiers agree, atomic writes survive simulated interruption, corrupt/truncated/unknown-version entries are quarantined or ignored, LRU/size limits evict deterministically, concurrent same-key calls cannot expose partial data, and cache disable produces identical scenes. Assert cache records contain no source document/provider secrets beyond hashed/canonical render inputs.

**Acceptance criteria:** Cache hits are structurally identical to fresh output; invalidation follows every version/style/geometry change; failures never poison future reads; standard gates pass.

**Effort:** M. **Dependencies:** P3-T1, P3-T2, P3-T7. **Phase 1:** no provider dependency; hard-blocked on P3-T5 through P3-T7.

### P3-T9 — Compose scenes and integrate the PDF vector renderer

> ⛔ **BLOCKED (full form) — P3-T5 NO-GO (2026-07-19).** The *glyph-engine* parts are blocked. Its
> **asset-free subset** (composer + `renderers/pdf.py` + z-order + CLI split, for marks/connectors/
> doodles only) is carved out as the runnable **P3-T12** below and MUST be built against this task's
> contract so a future GO extends it. See `docs/decisions/stroke-assets.md`.

**Covers:** architecture §§3, 5.2–5.6, 5.9, 9 Phase 3; explicit legacy typeset migration.

**Goal:** Compose one InkScene per resolved annotation and render its paths as PDF vectors while keeping typeset output available only through an explicit legacy mode. **Why:** the new scene/engine is not shipped until PDF stops inventing visible marks/text independently, but migration must retain a deliberate compatibility escape hatch.

**Files to create/modify:** create `src/halfblood/ink/composer.py`, `src/halfblood/renderers/pdf.py`, `src/halfblood/renderers/__init__.py`; modify `src/halfblood/document_processor.py`, `src/halfblood/cli.py`; modify `tests/test_cli.py`, `tests/test_pdf_geometry.py`, `tests/test_pdf_render_report.py`; create `tests/test_ink_composer.py`, `tests/test_pdf_vector_renderer.py`.

**Test-first:** With fake handwriting/rough engines, assert the composer receives P2 resolved boxes/quads, derives role-isolated seeds, orders highlight behind target and handwriting/marks/connectors by documented z-index, clips/validates/simplifies once, and returns immutable scenes plus degradations. Spy on PyMuPDF `Shape` calls: constant-width commands translate to lines/curves with round styling; pressure paths translate to filled outlines; transforms/page rotation are applied once; renderers add no jitter; multi-quad marks remain separate; path budgets skip/report rather than partially draw. Assert default `--handwriting-engine procedural` (or the final non-conflicting CLI spelling) uses scenes; `--handwriting-engine typeset` explicitly selects the existing renderer and may consume already-delivered `--font`; missing procedural assets fail unless the user explicitly permits typeset fallback. Do not re-plan font registration/selection. Assert atomic save, source preservation, and complete P2 report counts/degradations.

**Acceptance criteria:** PDF procedural mode visibly consists of vector paths, not text/native mark geometry; renderer translation is deterministic and scene-faithful; typeset is explicitly selected/authorized and documented as legacy; all standard gates pass.

**Effort:** L. **Dependencies:** P2-T8, P3-T3, P3-T4, P3-T7, P3-T8. **Phase 1:** requires P1-T1/P2 contracts, not provider traffic; hard-blocked on P3-T5 go.

### P3-T10 — Establish geometry, visual, and performance goldens

> ⛔ **BLOCKED — P3-T5 NO-GO (2026-07-19).** Do not start (depends on P3-T9 full form).
> A lighter mark-only visual-regression golden may be folded into P3-T12. See `docs/decisions/stroke-assets.md`.

**Covers:** architecture §§5.6, 5.9, 7.2–7.4, 9 Phase 3, 10.7.

**Goal:** Gate PDF-first procedural ink with structural geometry hashes, maintainer-reviewed raster diffs, and quantitative render/cache budgets. **Why:** ordinary unit tests miss visual drift, cross-layer geometry errors, and path/output explosions.

**Files to create/modify:** create `tests/test_ink_goldens.py`, `tests/test_pdf_visual_regression.py`, `tests/test_ink_performance.py`; create `tests/fixtures/goldens/` with source/license metadata, rounded scene JSON/SVG, pinned-DPI PNGs/masks, and budget data; modify CI/test markers/config only to separate standard and explicitly slow golden runs; document golden review/update commands.

**Test-first:** Using a small project-authored/public-domain PDF fixture, fixed style/seed, and pinned PyMuPDF version/DPI, assert rounded scene commands and structural hashes; extracted PDF path endpoints/bounds match the source scene within tolerance; raster perceptual difference stays inside tight documented masks/tolerances; original source pixels outside annotation regions remain unchanged within renderer tolerance. Add representative synthetic multi-page plans asserting maximum strokes/points per note, render time, peak traced memory, output expansion ratio, and cache-hit speedup under checked-in environment-qualified budgets; avoid flaky absolute microbenchmarks and keep the full 300-page smoke in a slow marker/nightly command. Assert golden update tooling refuses unreviewed overwrite or requires an explicit flag and records algorithm/style/asset versions.

**Acceptance criteria:** Geometry and visual baselines are deterministic, licensed, reviewable, and version-attributed; standard tests remain fast while the documented golden/performance commands pass in the pinned environment; regressions cannot be “fixed” by silently replacing expected files; all standard gates pass.

**Effort:** L. **Dependencies:** P3-T9. **Phase 1:** indirect through P3-T9; hard-blocked on P3-T5 go and explicit maintainer review of golden assets/changes.

## Phase 3 — redirect tasks (post-NO-GO, un-gated) — RUN THESE NEXT

> **P3-T5 = NO-GO (2026-07-19, owner).** P3-T6→T10 are blocked for this milestone. The shippable
> Phase-3 value is delivered by the two tasks below, which need **no stroke-asset license**.
> **Loop order: P3-T11 then P3-T12.** Refs: `docs/decisions/stroke-assets.md` (+ Codex opinion sibling).

### P3-T11 — Bundle & package the handwriting fonts (fix the Helvetica fallback)

**Covers:** architecture §8.3 (font/stroke/model licensing), §8.4 (packaging); `fonts/README.md`; the
NO-GO redirect. **Un-gated — not blocked by P3-T5.**

**Goal:** Ship the four license-cleared handwriting fonts *inside the installed wheel* and resolve the
default font from **package resources**, so a `pip install`-ed halfblood renders in the intended
handwriting look instead of silently falling back to Helvetica-Oblique. **Why:** the `.ttf`s are
gitignored and discovered via a *project-root-relative* path (`document_processor.py:214`), so a real
install has no `fonts/` dir and degrades to Helvetica — the demonstrated aesthetic never reaches users.

**License clearance (controller-owned, verified 2026-07-19 from embedded name-table metadata):**
Caveat Brush **OFL 1.1** (Google/Pablo Impallari, v1.096, no RFN); Homemade Apple **Apache-2.0** (Font
Diner, v1.001); Just Me Again Down Here **OFL 1.1** (Kimberly Geswein, v1.002, no RFN); Mrs Saint
Delafield **OFL 1.1** (Sudtipos, v1.001, **RFN "Mrs Saint Delafield"** — bundle unmodified only). All
four are redistributable when bundled with their license text and unmodified.

**Files to create/modify:** add the four cleared `.ttf`s under `src/halfblood/fonts/` (so hatchling's
`packages=["src/halfblood"]` includes them); add license files there (`OFL.txt`; `Apache-2.0.txt` +
`NOTICE`); un-ignore in `.gitignore` (drop/adjust the `fonts/*.ttf` rule or place under the package);
modify `src/halfblood/document_processor.py` to resolve the default font via `importlib.resources`
from the package first, keeping the existing project-root + system-path candidates as dev fallbacks;
create `THIRD_PARTY_NOTICES.md` (one row per font: source URL, version, license, RFN, modification=none,
redistribution conclusion); adjust `pyproject.toml` only if needed for font+license package-data;
create `tests/test_font_packaging.py`.

**Test-first (controller owns `tests/`; Codex must not touch them):** assert the default font (Caveat
Brush) resolves to a real bundled `.ttf` via `importlib.resources` when NO project-root `fonts/` exists
AND all system candidate paths are absent (installed-wheel simulation) — i.e. it does **not** fall back
to Helvetica; assert every bundled font has a matching `THIRD_PARTY_NOTICES.md` row and a bundled
license file; assert the Mrs Saint Delafield row records its RFN; assert each bundled `.ttf` is
byte-unmodified vs the cleared source (size/hash sanity); assert no orphan bundled font lacks a notice.

**Acceptance criteria:** a wheel-installed halfblood finds its default handwriting font with no repo
checkout; all bundled fonts are license-cleared, notice-rowed, unmodified, and shipped with their
license text; the Mrs Saint Delafield RFN obligation is recorded; all standard gates pass.

**Effort:** M. **Dependencies:** none. **Phase 1:** independent. **Gate:** none (un-gated).

### P3-T12 — Render rough marks to PDF (asset-free subset of P3-T9)

> **SPLIT into two loop iterations** (Codex design pass 2026-07-19; detailed design +
> assertion-to-contract map preserved at `.superpowers/sdd/p3-t12-design.md`):
> - **P3-T12a — pure library:** `src/halfblood/ink/composer.py` (InkComposer + injectable
>   RoughInkEngine/HandwritingEngine/PathPostprocessor protocols; `P3T5NoGoHandwritingEngine`
>   returns a typed `HandwritingUnavailable`) + `src/halfblood/renderers/pdf.py` +
>   `renderers/__init__.py` (translate InkScene→`fitz.Shape` via an injectable ShapeFactory) + new
>   `SkipReason.INK_PATH_BUDGET_EXCEEDED/INK_GEOMETRY_INVALID`. Tests: `tests/test_ink_composer.py`,
>   `tests/test_pdf_vector_marks.py`. **Nothing calls these yet → zero risk to the live render path.**
> - **P3-T12b — integration:** wire composer+renderer into `render_plan` (join semantic `Annotation`
>   ↔ `ResolvedAnnotation` by id; replace `_mark_target`/`_draw_connector`; split `_draw_resolved_note`
>   to body-only), add the `--handwriting-engine typeset|procedural` CLI (default `typeset`;
>   `procedural`→`ClickException(p3_t5_no_go)`), new `DegradationFlag.CONNECTOR_ROUTING_FALLBACK/
>   INK_PATH_BUDGET_EXCEEDED`. Tests: modify `tests/test_cli.py`, add integration tests.
> - **Honest P3-T9 divergence (NO-GO):** rough MARKS become vector-default, but the note-BODY defaults
>   to `typeset` (procedural letterforms are unavailable), inverting P3-T9's "procedural is default"
>   until a future P3-T7. `--handwriting-engine` selects the BODY engine only; marks are always vector.

**Covers:** architecture §§3, 5.2–5.6, 5.9, 9 Phase 3 — **scoped as P3-T9 minus the glyph/handwriting
engine.** **Un-gated — not blocked by P3-T5.**

**Goal:** Compose one `InkScene` per resolved annotation from the already-built P3-T1→T4 rough-mark
generators (underlines, strike-throughs, circles, connectors, doodles) and render its paths as **PDF
vectors** via a new `renderers/pdf.py`, replacing the current *native* PDF marks + bowed connector for
the mark/connector/doodle roles. The note **body text** continues to render via the existing typeset
path (explicit legacy mode). Letterform/handwriting composition is **deferred (NO-GO)**. **Why:** the
P3-T1→T4 rough-ink library is fully built and tested but wired into **no** renderer, so none of its
visual payoff currently reaches the PDF (verified 2026-07-19).

**Reconcile with P3-T9 (build the real design, not throwaway):** implement the architecture's
`composer.py` + `renderers/pdf.py` + documented z-ordering + the `--handwriting-engine typeset|
procedural` CLI split from P3-T9, but with the **procedural letterform path returning a typed
"unavailable — P3-T5 NO-GO"** while the **mark/connector/doodle paths are fully implemented**. A future
P3-T5 GO then *extends* this, it does not replace it.

**Files to create/modify:** create `src/halfblood/ink/composer.py`, `src/halfblood/renderers/pdf.py`,
`src/halfblood/renderers/__init__.py`; modify `src/halfblood/document_processor.py`,
`src/halfblood/cli.py`; create `tests/test_ink_composer.py`, `tests/test_pdf_vector_marks.py`; modify
`tests/test_cli.py`.

**Test-first (controller owns `tests/`):** with fake rough engines, assert the composer receives P2
resolved boxes/quads, derives role-isolated seeds, orders highlight behind target and marks/connectors
by documented z-index, clips/validates/simplifies once, and returns immutable scenes. Spy on PyMuPDF
`Shape` calls: constant-width commands → lines/curves with round styling; pressure paths → filled
outlines; transforms/page rotation applied once; renderer adds no jitter; multi-quad marks stay
separate; path budgets skip/report rather than partially draw. Assert the default engine renders marks
as **vectors** while the note body still renders via legacy typeset; assert selecting the procedural
letterform engine returns a **typed "unavailable (P3-T5 NO-GO)"**, never a fake glyph. **F2 guard:** if
the composer simplifies rough paths, keep `_douglas_peucker` usage cubic-safe (skip simplification for
multi-cubic rough paths) — the latent F2 bug must not be silently triggered here.

**Acceptance criteria:** PDF mark/connector/doodle output consists of scene vector paths, not native-PDF
mark geometry; translation is deterministic and scene-faithful; the note body still renders (legacy
typeset, explicitly selected); the letterform engine cleanly reports unavailable; all standard gates
pass.

**Effort:** L. **Dependencies:** P2-T8, P3-T3, P3-T4 (all merged). **Phase 1:** independent of provider
work. **Gate:** none (un-gated); run **after** P3-T11.

## Summary and critical path

This plan contains 9 Phase 2 tasks and 10 Phase 3 tasks. Phase 2's independently startable path is normalized index → selectors → scoring → PDF/EPUB resolvers; its durable contracts and layout integration wait for Phase 1 P1-T1, then proceed through resolved plan/report → occupancy layout → PDF integration → EPUB/regression closure. Phase 3 can ship scene models, stable style/seeding, rough marks/doodles, and pressure geometry before letter assets. The main critical path is P1-T1 → P2-T1/T2/T3 → P2-T4/P2-T5 → P2-T6 → P2-T7 → P2-T8/P2-T9 → P3-T1/P3-T2 → P3-T5 go → P3-T6 → P3-T7/P3-T8 → P3-T9 → P3-T10. P3-T5 is the explicit blocked-on-owner-decision gate: a no-go stops genuine letterform, cache-integrated procedural PDF, and its final goldens, but does not block the Phase 2 correctness work or the earlier project-authored rough-ink deliverables.

## 13. Controller review (Claude / Sonnet 5, 2026-07-11)

Reviewed against the architecture spec §§3, 5, 9-10 and the current codebase (not just for internal consistency). Verdict: **adopted, with one fix applied and three process notes for the executing controller.**

### Verified as correct
- **Full 1:1 coverage** of the architecture's §9 Phase 2 and Phase 3 scope paragraphs — every named deliverable (normalized indexes, selectors, scoring, PDF multi-quad, EPUB cross-node, occupancy layout, render reports; InkScene, seeding/style, rough marks, pressure expansion, stroke assets, procedural handwriter, cache, PDF integration, goldens) maps to a task. Nothing in the architecture's phase scope was silently dropped.
- **Correctly deferred Phase 1**: every task carries an explicit "Phase 1:" coupling note instead of inventing guessed P1 interfaces. Spot-checked against the actual P1-T1 task in the Phase 0+1 plan (stable IDs, source locators, v2 model) — the assumptions Phase 2/3 make about what P1-T1 will deliver match what P1-T1 actually promises to build.
- **New package paths are not invented** — `documents/`, `layout/`, `ink/`, `renderers/` and their per-file names (`ink/model.py`, `ink/procedural.py`, `layout/anchors.py`, etc.) trace exactly to the architecture's §3.1 proposed package layout.
- **The stroke-asset licensing gate (P3-T5) is modeled correctly**: blocking only T6-T10 (letterform-dependent work), explicitly *not* blocking T1-T4 (project-authored rough ink, which needs no external asset) or Phase 2. This matches architecture risk #1 and preserves a usable no-go fallback (rough marks + legacy typeset), rather than stalling the whole phase on a licensing question.

### Fix applied
- **P3-T6 named `tests/test_packaging.py` as a file to create — it already exists** (`P0-T12`'s dependency-bounds and audit-ledger-closure tests, 81 lines, unrelated to stroke assets). Following the plan literally would have collided with or overwritten Phase 0 coverage. Renamed to `tests/test_stroke_asset_packaging.py` in the task above.

### Process notes for whoever executes this (not plan defects, but risks worth naming before dispatch)
1. **Package-split timing is left to per-task judgment** ("create X when the gradual split reaches it, otherwise implement behind the existing file") — faithful to the architecture's explicit "split gradually, no big-bang rewrite" guidance, so this isn't wrong, but if different tasks are dispatched to Codex across different sessions, inconsistent ad hoc calls could produce structural drift. Recommend the controller pick one explicit trigger — e.g., stand up the full `documents/`/`layout/`/`ink/`/`renderers/` package skeleton at P2-T1 and land everything there from the start — rather than deciding per task.
2. **P3-T5 doesn't specify who does the licensing legwork before asking the owner to decide.** As written, it risks becoming an open-ended question that stalls Phase 3's back half indefinitely. Recommend the controller do the candidate research up front (same pattern as the Session 7 JMADH font-license verification) and bring the owner 2-3 vetted, pre-verified candidates plus a recommendation, not an open prompt.
3. **This plan treats the uncommitted F1 (`--font`) feature as already delivered**, per the planning brief. That's reasonable, but F1 has not itself been adversarially reviewed yet (open item from this session). If that review changes `cli.py`'s font-resolution shape, re-check P3-T9's assumption that legacy typeset mode "may consume already-delivered `--font`" before dispatching P3-T9.
4. **Scale, stated plainly**: 19 tasks, the large majority effort-L, including genuinely novel engineering (procedural handwriting synthesis, pressure-stroke geometry, licensed golden visual regression). This is very likely the largest, hardest phase pair in the whole roadmap — planning it took one Codex run; executing it will not be comparably fast. Set expectations accordingly against Phase 0's pace (12 tasks, largely S/M, closed in one session).
