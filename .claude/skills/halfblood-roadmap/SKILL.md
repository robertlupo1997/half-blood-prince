---
name: halfblood-roadmap
description: Feature backlog (medium/low priority improvement areas) and the recommended file-reading order for orienting in the half-blood-prince codebase. Use when deciding what to build next, reviewing the project roadmap, or getting oriented in this codebase for the first time.
---

Moved out of the project's root `CLAUDE.md` (which keeps only Mission, architecture rationale, tech-stack validation, known issues, manual-testing guidance, and High Priority improvement areas — including the retry-ownership constraint, which stays there because it's safety-critical).

## Medium Priority

- **~~Publisher boilerplate gets annotated~~ — FIXED 2026-07-24 (`1711844`).** `halfblood.boilerplate`
  scores weighted marker occurrences per 1000 chars; the CLI filters before generation so skipped
  sections cost no tokens. `--annotate-boilerplate` restores old behaviour.
- **~~A malformed provider 200 loses the whole page~~ — FIXED 2026-07-24 (`57c7b7f`).**
  `StructuredOutputError` escaped the provider retry loop uncaught; now retried on the existing
  bounded budget in BOTH httpx providers. Retry ownership stays singular. Safety refusals still
  fail immediately.
- **CORRECTION — "EPUB cross-tag matching" is NOT a real gap. Do not build it.**
  CLAUDE.md known-issue #15 (and an earlier version of this entry) claims `_locate_text` can only
  match inside a single `NavigableString`. That is **stale**: the v2 path uses
  `documents/epub.py:locate_across_nodes`, wired at `epub_processor.py:554,594`. Proven directly —
  targets spanning `text -> <em> -> text`, `<em> -> text -> <strong> -> text`, and
  `<strong> -> text` all resolve. The legacy `_locate_text` still exists but is not the v2 path.

- **~~The model does not quote verbatim~~ — LARGELY FIXED 2026-07-25 (`96a715e`).**
  `documents/matching.py:MatchTolerance` (EXACT → CASE_INSENSITIVE → PUNCTUATION_ELASTIC), walked
  strictest-first by `locate_across_nodes`. Measured on Jekyll & Hyde: **44/50 → 48/50 rendered**,
  with all 44 original anchors byte-identical. Both looser rungs keep exact semantics — no edit
  distance, no threshold.
  - **Fuzzy matching was considered and deliberately rejected.** It would recover exactly one more
    annotation and would anchor it to a span starting inside the word `mere`. Fail-closed per the
    lane-D precedent: a note on the wrong words is worse than a missing note, because the reader
    cannot detect it. Do not revisit without a real book that shows a different failure mix.
  - **Prompt hardening was tried and measurably did not help** (three runs; the hardened prompt's
    verbatim rate landed inside the original's own 80–88% run-to-run range). Reverted. Full
    numbers in `docs/decisions/verbatim-quoting-prompt-vs-matcher.md`. Do not re-attempt without
    several paired runs — n=1 cannot distinguish a prompt win from noise on this model.
  - **Residue (~4%)** is genuine paraphrase: dropped words and elided dialogue attributions.
    No known safe fix.

- **Shortened-tier fallback under `EXACT` anchors to a single word.** When the full quote misses,
  the tier ladder falls back 8-word → 5-word → 3-word → longest single word, so a case- or
  quote-drifted PDF target can anchor to just `death` or `circulars`. Harmless on the EPUB path
  (the DOM contract accepts tier 0 only) but live on the PDF path. Pinned by
  `TestShortenedTierFallbackIsUnchanged` in `tests/test_match_tolerance.py` so it can only change
  deliberately. Narrowing it changes which PDF annotations render, so it needs its own
  before/after measurement on a real PDF — do not fold it into an unrelated change (an early
  build of the tolerance ladder did exactly that and it was reverted).

- **~~Connector arrows cross body text~~ — FIXED 2026-07-24 (`943df1e`).** Root cause was NOT
  connector routing: `_draw_connector` renders whatever placement hands it. The solver scored
  connectors on Euclidean *length* only (weight 50) against a scale weight of 1000, so keeping a
  note full-size and far from its target beat shrinking it to sit nearby — and `page_solver.py`
  had zero references to body geometry. Fixed with a directional `connector_body_span_bp` term
  (vertical overlap of connector with the body block) weighted 1300. Measured on the repro page:
  worst connector **317pt (40% of page) → 104pt (13%)**.
  - **Residual, if it ever bothers you:** a designed-but-unimplemented two-layer follow-up exists.
    `AnchorWarningCode.CONNECTOR_OMITTED` (`models/rendering.py:113`) is still declared and wired
    to nothing; the plan is to emit it in `engine._run_beam()` when `connector_body_span_bp > 5000`
    and skip `_draw_connector` for annotations carrying it. NOTE: this would **not** have fired on
    the residual 13% connector (1310 bp, far below the 5000 bp gate) — it is defense-in-depth for
    rare cases where the beam is genuinely forced far from target, not a further improvement on the
    common case. Only worth building if real books show forced-far placements.

- **Prompt engineering improvements.** The `DEFAULT_PERSONA` is good but could be refined:
  - Add few-shot examples directly in the system prompt (2-3 example annotations with target_text + content)
  - Experiment with different `max_tokens` values — 2048 may be too generous, encouraging verbosity
  - Test with `claude-haiku-4-5-20251001` for cost savings on the generation step (judge can stay on sonnet)
  - **Measure any of these across several paired runs.** One run at n≈50 on this model cannot
    tell a real improvement from noise — see the reverted verbatim-quoting experiment above.
- **PDF text extraction quality.** Some PDFs have weird text layer encodings. Consider adding OCR fallback via `page.get_text("text", flags=fitz.TEXT_PRESERVE_WHITESPACE)` or PyMuPDF's built-in OCR.
- **Web preview improvements:**
  - **~~Copy JSON button~~ — SHIPPED 2026-07-25 (`b8cf39b`).** Reads the already-embedded
    `window.__HB_DATA__`; no new data path. Key constraint: previews open over `file://`,
    which is **not** a secure context in Chrome, so `navigator.clipboard` is often
    `undefined` exactly where the button is used — it is feature-detected with a hidden
    `<textarea>` + `execCommand` fallback and a visible outcome either way. Verified by
    `node --check` on the generated page's JS (a syntax error in JS-embedded-in-Python is
    invisible to every Python test) and by executing the handler under a DOM stub with
    `navigator.clipboard` absent.
  - **~~Search/filter~~ — ALREADY BUILT, do not rebuild.** `web_preview.py` has legend-based
    type filtering (`applyFilters()`, `.filtered-out`). What is genuinely missing is
    free-text search over annotation *content*.
  - Note: `tests/test_web_preview.py` exists (~280 lines). The "web preview has zero tests"
    claim that circulated in CLAUDE.md was stale and is corrected.
  - Add annotation editing (modify content, delete, re-position)
  - Server-sent events for live preview during generation

## Low Priority / Nice-to-Have

- **~~Configuration file support~~ — COMPLETE 2026-07-25.** `halfblood.toml` (project) and
  `<user_config_dir>/halfblood/config.toml` now cover provider, model, base_url, api_key_env,
  structured_output, timeout, max_retries, concurrency, allow_insecure_http, persona,
  persona_file, `max_per_page` and `font`, each with a `HALFBLOOD_*` env override and
  provenance in `sources`. The hermeticity trap that used to sit in front of this is closed
  (`94494d7`). Nothing outstanding.
- **Pure usage errors are reported after provider configuration errors.** `annotate --persona x
  --persona-name y` with no API key configured reports the missing-key error, not the
  mutual-exclusion error, because `_resolve_provider_and_build` runs before `_resolve_persona`
  (which needs `config.persona` for its fallback). **Pre-existing** — the older
  `--persona`/`--persona-file` conflict behaves identically; `--persona-name` only inherited it.
  Verified reachable once a provider *is* configured: `--persona-name nope` correctly prints
  `Unknown persona 'nope'. Available names: chemist, detective, editor, philosopher.` Fixing it
  means splitting flag validation out of `_resolve_persona` and calling it before the provider
  build in both commands — cheap, but it reorders CLI error precedence, so it wants its own
  check that no other error path depends on the current ordering.
- **Elastic-only overlap is not caught by `_has_overlapping_exact`.** That guard checks the
  *exact* needle at every rung, and `finditer` is non-overlapping, so a target that overlaps
  itself only once quotes are made elastic would report a single hit rather than ambiguity.
  Not reachable with realistic 4–15-word book quotes (it needs a short self-overlapping
  phrase with a quote character between the repeats). Recorded, not fixed.
- **~~Persona library~~ — SHIPPED 2026-07-25.** `personas/{chemist,philosopher,editor,detective}.txt`
  plus `personas/README.md`. Building it surfaced and fixed a real defect: `--persona`/
  `--persona-file` *replace* the persona string, and the eight annotation-type definitions
  lived inside `DEFAULT_PERSONA`, so a custom persona silently produced a **707-character**
  system prompt instead of 4779 — no type guidance at all. Split into `DEFAULT_PERSONA`
  (voice) + `ANNOTATION_CRAFT` (shared machinery, always appended). The default prompt is
  pinned **byte-identical** by `tests/test_persona_craft.py`; persona files must describe a
  voice only, which is also asserted.
  - **~~Follow-up~~ — DONE 2026-07-25 (P4).** `personas/` moved to `src/halfblood/personas/`
    and ships in the wheel. `--persona-name NAME` added to both `annotate` and `preview`
    commands. Resolution through `importlib.resources` with injectable `personas_dir` for
    hermetic tests (`available_personas()`, `_resolve_persona_name(name, personas_dir=None)`
    in `cli.py`). `tests/test_persona_packaging.py` covers packaging, resolution, and flag
    precedence. The three persona flags (`--persona`, `--persona-file`, `--persona-name`) are
    mutually exclusive.

- **~~Config keys for `max_per_page` and `font`~~ — SHIPPED 2026-07-25 (`2a7d113`).**
  Key is `font` (not `font_path`): `--font` takes NAME|PATH, so a path-only key would be
  less capable than the flag. A relative `font` naming an existing file resolves against the
  config file's directory (persona_file precedent); everything else passes through so
  `_resolve_font_option` owns the error. `max_per_page` **raises** rather than clamps,
  unlike `concurrency` — clamping suits a transport setting, not one where `0` silently
  yields a book with no annotations. Both flow through the single `cli_overrides` dict and
  both appear in `safe_repr()`.
  - **Watch for this pattern:** adding the two fields broke nine CLI tests because
    `test_persona_config.py` faked `ResolvedConfig` with a hand-maintained
    `SimpleNamespace`. The first implementation absorbed that with
    `getattr(config, "font", None)` in *production* — a test double's gaps dictating
    production code. Fixed by making the double the real dataclass. Grep for
    `SimpleNamespace` before adding a field to a widely-faked type.
- **Batch mode** — `halfblood annotate-batch *.pdf` processing multiple books.
- **PDF-to-EPUB annotation transfer** — Generate annotations against a PDF, render into the corresponding EPUB.
- **Annotation diff** — Compare two annotation plans (e.g., different models or personas) side by side.
- **Token cost estimation** — Before running, estimate API cost based on page count and average tokens per page.
- **Export formats** — Export annotations as standalone JSON, CSV, or Markdown (without the rendered PDF).

## Critical files to read first (recommended order)

1. `src/halfblood/models.py` — The shared vocabulary. Small, read it all.
2. `src/halfblood/annotation_generator.py` — The LLM integration. Pay special attention to `DEFAULT_PERSONA`, `_ANNOTATION_TOOL_SCHEMA`, `_build_system_prompt`, and the context windowing in `generate_for_document`.
3. `src/halfblood/document_processor.py` — The PDF rendering engine. Focus on `add_margin_note`, `_write_margin_text`, `_draw_connector`, and the font resolution chain.
4. `src/halfblood/cli.py` — The glue layer. Verify it correctly dispatches PDF vs EPUB and handles errors.
5. `eval/eval_harness.py` — The quality gate. Understand the metrics, test cases, and judge prompt.
6. `src/halfblood/epub_processor.py` — The EPUB renderer. Check the `_ensure_toc_uids` workaround and CSS injection.
7. `src/halfblood/web_preview.py` — The HTML viewer. Large file (~1100 lines). Check the JS/CSS for correctness.
