# Research spike: provider transport (SDK vs raw HTTP) + handwriting/render comparators

**Date:** 2026-07-11
**Status:** spike — informational; **no code changes**. Feeds Session 5 owner decision **1b** (P1-T5 SDK-vs-`httpx`) and the handwriting release-blocker in spec §10.1.
**Scope:** two questions from the Session 5 handoff Action Item 2 — (A) is raw-`httpx`-for-Anthropic actually best? (B) how do Riddle and comparable tools pick their LLM API and render handwriting, and what are the asset-license constraints?
**Method:** Half A = reasoning over the codebase seam + spec §4 (controller). Half B = web study of Riddle + handwriting-synthesis comparators (delegated researcher; citations preserved below). Timeboxed per plan.

---

## A. Provider transport — recommendation for P1-T5

**Recommendation: raw `httpx` for BOTH Anthropic and OpenAI-compatible** (i.e. adopt P1-T5 as written; do **not** take the SDK-for-Anthropic + httpx-for-OpenAI hybrid). Retain the `anthropic` SDK only as an *optional* compatibility extra for one deprecation cycle (spec §4.1).

The seam being replaced is one call: `annotation_generator.py:335` — a single non-streaming, forced-tool-use `client.messages.create(...)`. Everything downstream already consumes a provider-neutral `AnnotationPlan`. Evaluated against the handoff's five criteria:

| Criterion | Raw `httpx` (both) | Hybrid (SDK Anthropic + httpx OpenAI) | Winner |
|---|---|---|---|
| **Retry + timeout uniformity** | One retry owner in the provider layer; one backoff/jitter/`Retry-After` policy for all providers. | Two engines: the Anthropic SDK retries internally (default `max_retries=2`) with its own semantics, plus a separate httpx path for OpenAI. To unify you must set the SDK's `max_retries=0` and wrap it — at which point the SDK is just an HTTP client behind an abstraction. Spec §4.6 **requires** "retrying must be owned by the provider layer so an SDK cannot also retry invisibly." | **httpx** |
| **Auth & versioning burden** | Set `x-api-key` + `anthropic-version` (a pinned date string) and `Authorization: Bearer` by hand — trivial, and pinning the API version *explicitly* is a feature: no silent behavior shift on SDK upgrade (this project just got burned by a silent model retirement). | SDK hides auth/versioning but bumps `anthropic-version` on upgrade. | **httpx (slight)** |
| **Error-type fidelity** | One status+body → taxonomy mapping (spec §4.6) shared by both adapters. | SDK gives typed Anthropic exceptions *for free*, but you must re-normalize them into the shared taxonomy AND write a second mapping for OpenAI — two code paths that can diverge. | **httpx (uniform)** |
| **Test surface** | `httpx.MockTransport`/respx asserts the exact wire request (URL, headers, tool schema, `tool_choice`) and injects exact statuses/timeouts — no network, no SDK-version coupling. One suite covers both adapters. This is what P1-T5's test-first spec is built on. | Mocking `client.messages.create` with `SimpleNamespace` doubles (today's approach) never exercises the wire layer and drifts from real SDK behavior on upgrade. | **httpx (decisive)** |
| **Maintenance** | Own a ~50-line shared backoff helper + one version constant. Shed the `anthropic`/`openai`/LiteLLM runtime deps (spec §4.5). Wire surface used here is tiny and stable; the SDK's "free" features (streaming, prompt caching) are unused by this batch pipeline. | SDK tracks new Anthropic features automatically, but this pipeline uses none of them; you inherit SDK major-bump churn. | **httpx** |

**Honest cost of raw httpx (not a blocker):** you hand-write ~20 lines constructing/​parsing Anthropic's forced `tool_use` (`tool_choice={"type":"tool","name":"record_annotations"}` → require exactly one matching `tool_use` block → read `.input`). The SDK does this for you today. Mitigation: the format is small and stable, it's pinned by `anthropic-version`, and P1-T5's parity tests + a blocked-on-key live smoke test anchor correctness. You also own correctness of edge cases like `overloaded_error` (529) — again small and testable.

**Why the hybrid loses:** it reintroduces exactly the two-retry-engine / two-error-mapping non-uniformity that spec §4.6 forbids, to avoid hand-writing a stable, tiny wire format. The uniformity is the whole point of the provider seam.

### Comparator corroboration (Half B)
- **Riddle chose raw HTTP on purpose.** It uses the Rust `ureq` crate (no vendor SDK) precisely to stay provider-agnostic: configurable `RIDDLE_OPENAI_BASE`, `Authorization: Bearer`, POST `/chat/completions`, parse JSON — the Rust equivalent of `httpx.post(base+"/chat/completions", headers=..., json=body)`. [`riddle/src/oracle.rs`, README]
- **Nobody ships the retry seam — that's our differentiator.** Riddle has **no 429/5xx backoff** at all (it only retries a `max_tokens` vs `max_completion_tokens` naming mismatch). Our `httpx` + full-jitter backoff + `Retry-After` (spec §4.6) is strictly better and is the reason to own the transport.
- **One caveat comparators don't cover:** Riddle parses *free-form streamed text*, not structured tool calls, so it sidesteps the tool_use JSON entirely. Our schema-validated structured output is a deliberate, worthwhile extra ~20 lines — evidence on this specific dimension is thin from comparators.

---

## B. Handwriting & rendering — comparators and licensing

### Findings
- **Riddle:** loads `DancingScript.ttf` (`ab_glyph`), rasterizes glyphs to pixel masks, **skeletonizes with a Zhang-Suen `thin()`** to single-pixel paths, then `trace()`s them into ordered polyline strokes (prioritizing degree-1 endpoints to mimic pen lift/down), replayed progressively on the reMarkable e-ink display. [`riddle/src/script.rs`, README]
- **`sjvasquez/handwriting-synthesis`:** Graves-2013 LSTM mixture-density RNN predicting `(dx, dy, eos)` stroke sequences; `drawing.py` cumsum → SciPy smoothing → matplotlib PNG. Local inference, no API. [`rnn.py`, `drawing.py`, `demo.py`]
- **pytorch-handwriting-synthesis / Handwriting-Transformers family:** same Graves lineage, some transformer style-disentanglement variants; stroke sequences → SVG/matplotlib. Local inference.

### Licensing posture (the release-relevant part — spec §10.1, §8.3)
- **OFL fonts are clean.** Riddle's Dancing Script and **our already-shipped Caveat Brush are both SIL OFL 1.1**, which permits commercial bundling with no revenue restriction (cannot be sold standalone). No licensing risk on the font itself.
- **Trained-model synthesis carries a real risk.** The Graves-family checkpoints (sjvasquez et al.) appear trained on the **IAM On-Line Handwriting Database**, which is **non-commercial-research-only**. Evidence is strong (`prepare_data.py` uses IAM's `z01/z01-000/` path convention; paper citations) but *the researcher could not definitively confirm from source alone*. **Do not drop in any IAM-trained ONNX/checkpoint for a commercial/open release without due diligence.** This confirms the handoff's "stroke-asset license is the main handwriting blocker."

### Consequential lead (verify before relying on it)
**Riddle demonstrates that pen-stroke paths can be derived from an OFL font we already ship** — rasterize → Zhang-Suen skeletonize → trace strokes. If that reproduces for Caveat Brush under Python (e.g. `skimage.morphology.skeletonize` + a tracer), then the spec §5.3 "procedural centerline strokes" baseline may need **no separately-licensed stroke-asset data at all** — the letterform trajectories come from an OFL glyph outline whose license already permits derivative use. That would materially de-risk Phase 3 handwriting (spec §9) and reframe the ONNX model as a pure quality upgrade, not a prerequisite.

**Caveat:** this is a promising lead from one comparator, not validated in-repo. Before Phase 3 commits to it: (1) confirm OFL 1.1 permits deriving/redistributing *skeleton trajectory data* from the glyph outlines (font license ≠ automatic trajectory-data license — the handoff's exact worry; likely fine under OFL's derivative terms but get it in writing/reading), and (2) prototype skeleton→stroke on Caveat Brush and eyeball stroke quality vs. Riddle's e-ink result. Static-PDF rendering also differs from Riddle's animated e-ink replay: today `fitz.Shape.insert_text(morph=...)` already gives the tilt/jitter look cheaply; skeleton strokes matter most for the "actual vector pen paths" the spec promises and for any future animated web preview (where Riddle's `script.rs` is a directly applicable open reference).

---

## Decisions this spike informs
1. **P1-T5 / owner decision 1b → adopt raw `httpx` for both providers** (as the plan already specifies); keep `anthropic` as an optional extra for one deprecation cycle. Rationale: single retry owner, uniform taxonomy, deterministic wire tests — corroborated by Riddle.
2. **Phase 3 handwriting → investigate OFL-font skeletonization as the procedural-stroke source** before assuming a licensed ONNX asset is required. Treat IAM-trained models as license-blocked until cleared.

## Sources
Riddle: `github.com/MaximeRivest/riddle` — `src/oracle.rs`, `src/script.rs`, `fonts/OFL.txt`, `README.md`. Handwriting synthesis: `github.com/sjvasquez/handwriting-synthesis` (`rnn.py`, `drawing.py`, `demo.py`); `github.com/topics/handwriting-generation`. IAM OnDB license: fki.tic.heia-fr.ch/databases/iam-on-line-handwriting-database. (Web-sourced via delegated researcher, 2026-07-11; the IAM-usage identification is inferred, not confirmed from source.)
