# README claim ledger

This ledger covers the current [README](../README.md), not its historical
feature catalog. The [final handoff](../HANDOFF.md) records the execution-time
outputs and commit. Run commands from the repository root in its `.venv`.

Labels: **Observed** means an executed check supplied the stated evidence;
**Derived** means the conclusion follows from those observations or inspected
code/metadata; **Unknown** means not established. API rules below are documented
contract requirements and are tested by the named commands, not universal proofs.

## Placement and rendering

| README claim | Falsifying check | Evidence class and limit |
| --- | --- | --- |
| Four outcomes, complete normalized quotes, strict hints, no prefix recovery in the supported interface | `.venv/bin/python -m pytest tests/test_strict_placement.py tests/test_placement_result_model.py tests/test_placement_rendering.py tests/test_placement_migration.py -q` | Observed cases: whole-quote mismatch, overlaps, repeated passages, exact/stale hints, bounds, JSON invariants, renderer integration. Not all possible books. |
| NFC, whitespace, typographic quote/dash normalization, not case or paraphrase recovery | Same strict-placement command; `.venv/bin/python scripts/benchmark_placement.py` | Observed raw-span checks and the five/fifty refusal. Normalization is explicit equivalence, not semantic validation. |
| PDF gives display-space line quads, not pixel contours or OCR truth | Strict-placement command above | Observed corners checked against independent raw glyphs and rotation at 0/90/180/270 degrees. PyMuPDF remains a shared dependency, not an independent OCR oracle. |
| Reflowable EPUB gives cross-node text ranges, never fixed screen coordinates | Same strict-placement command | Observed cross-node and block-boundary tests; resolved EPUB records reject PDF quads. Actual reader layout is Unknown. |
| Fixed-layout EPUB is unsupported, including package/itemref declarations | `.venv/bin/python -m pytest tests/test_placement_rendering.py -k rendition -q` | Observed global pre-paginated declaration, per-item fixed layout, and explicit reflowable override. Arbitrary CSS is not evaluated by the text resolver. |
| `render_plan` is the CLI path; legacy compatibility methods are outside the guarantee | `.venv/bin/python -m pytest tests/test_cli_end_to_end.py -q`; `.venv/bin/python docs/evidence/placement-release/legacy_probe.py` | Observed CLI integration; the legacy probe deliberately still reproduces unsafe prefix selection in excluded helpers. Derived scope distinction, not a claim those helpers were fixed. |
| Resolution, generation, and drawing are separate checks | `.venv/bin/python -m pytest tests/test_degradation_mapping.py tests/test_pdf_render_report.py -q`; `.venv/bin/python docs/evidence/placement-release/composition_probe.py` | Observed omitted caret/doodle diagnostics remain in reports. A rendered note can have a missing optional mark or degraded connector. |

## Example output

| README claim | Falsifying check | Evidence class and limit |
| --- | --- | --- |
| The *Alice* page images and the quoted Elements of Style note came from real-model runs through `--provider claude-cli` (CLI alias `opus`); counts 60/60/0 and 35/35/0 | `halfblood annotate examples/src/alice.pdf -o alice.plan.json --pages 1-12 --provider claude-cli --dry-run`, then render with `--resume-from`; `halfblood annotate tests/corpora/real/elements-of-style.epub -o eos.plan.json --pages 2 --provider claude-cli --dry-run`; compare with `examples/real/*.plan.json` and `examples/real/*.report.json` | Observed once each: Alice on 2026-10-23 (regenerated after the source rebuild that restored 74 dropped paragraphs) `Rendered 60 / Skipped 0`, Elements of Style on 2026-10-22 `Rendered 35 / Skipped 0`. Plans and reports are committed. Model output is not reproducible byte for byte. Note quality is **Unknown**: `examples/real/NOTES-REVIEW.md` is the generating agent's self-review against the source text (it lists 9 of 95 notes as wrong, overstated or invented), not an independent judgement. The G5 grading below covered the eval set, not these books. |
| The connectors on the *Alice* page images run in the margin and the leading and cross no body text outside their quote | `.venv/bin/python -m pytest tests/test_connector_leading_route.py -q` (reads drawn connector paths back from a `render_plan` PDF); `examples/real/alice-annotated.pdf.report.json` has no `connector_routing_fallback` | Observed on a synthetic mid-line-quote fixture and on the 12 committed *Alice* pages, re-rendered from the committed plan on 2026-10-23: 0 of 60 connectors cross a body glyph (20 of 60 did before the routing fix, none of them flagged). Measured against PyMuPDF glyph outline boxes (`TEXT_ACCURATE_BBOXES`), not rendered pixels. An arrow may touch its own quote and the mark around it; other books are Unknown, so the report flag, not this row, is the per-render evidence. |
| The quoted "oneself" note identifies a real error in the 1918 text | Read the target sentence in `tests/corpora/real/elements-of-style.epub` ("the pronominal possessives hers, its, theirs, yours, and oneself have no apostrophe") | Derived: "oneself" is a reflexive pronoun, and the possessive "one's" takes an apostrophe. |
| `claude-cli` generates through a signed-in Claude Code CLI with no API key | `.venv/bin/python -m pytest tests/test_claude_cli_provider.py -q` | Observed with a stubbed executable; the live runs above are the only end-to-end evidence. Requires the `claude` CLI on PATH and a signed-in account. |
| `codex-cli` judges through a signed-in Codex CLI in a read-only sandbox, and the eval JSON records `self_judged` | `.venv/bin/python -m pytest tests/test_codex_cli_provider.py tests/test_stub_judge.py -q` | Observed with a stubbed executable only; no live Codex run yet. Requires the `codex` CLI on PATH and a prior `codex login`. |
| Independent grading scored the eval set 3.92/5 (grade B) and failed it on density | `docs/evidence/2026-10-23-g5/eval-result.json`; rerun with `eval/eval_harness.py --provider claude-cli --judge-provider codex-cli --json-out eval-result.json` (needs both CLIs signed in) | Observed once, 2026-10-23, `"self_judged": false`, generator `claude-cli`/`opus`, judge `codex-cli`/owner default. Three of five cases pass; two fail density only. The later density revision of the prompt is not re-graded. |
| Long pages are generated in windows of at most 12,000 characters | `.venv/bin/python -m pytest tests/test_page_windowing.py -q` | Observed with a scripted provider: exact slices, one call per window, cap scaled per window, a failed window fails the page. How many notes a real model returns per window is Unknown until rerun. |

## Benchmark

| README claim | Falsifying check | Evidence class and limit |
| --- | --- | --- |
| Runnable offline benchmark, checked-in expectations, JSON stdout, nonzero on mismatch | `.venv/bin/python scripts/benchmark_placement.py`; `.venv/bin/python -m pytest tests/test_placement_benchmark.py -q` | Observed corpus verdict and CLI tests. No network/provider call in this harness. |
| Oracle is separate from the resolver | Inspect `benchmarks/placement.py`, `benchmarks/fixtures/expected.json`, and run the benchmark tests | Derived from code plus Observed tests: expected spans/segments are pinned; glyph data are walked without calling the placement index; stale fixture hashes fail. Both PDF paths use PyMuPDF extraction, a stated limitation. |
| Injected corruptions turn the benchmark red | `.venv/bin/python -m pytest tests/test_placement_benchmark.py -k RedMutations -q` | Observed eight injected failures, not proof that every possible defect is detected. |
| No LLM quality, routing quality, whole-book accuracy, or reader-similarity measurement | Inspect the benchmark inputs and calls | Derived scope. Those broader quality claims remain Unknown. |

## CLI, safety, and examples

| README claim | Falsifying check | Evidence class and limit |
| --- | --- | --- |
| Committed example files exist; they are historical stub demonstrations | `.venv/bin/python -m pytest tests/test_docs.py -q`; inspect `examples/*.report.json` and stub note text in the files | Observed existence and retained historical reports; not a claim of byte identity with HEAD. |
| The committed Alice sources run offline through the current PDF/EPUB pipeline | `.venv/bin/halfblood annotate examples/src/alice.pdf -o /tmp/hbp-final-alice.pdf --provider stub --force`; `.venv/bin/halfblood annotate examples/src/alice.epub -o /tmp/hbp-final-alice.epub --provider stub --force` | Observed real-book runs; record nested placement/render counts separately from generated-page counts. Stub notes carry no model-quality signal. |
| Dry-run produces a plan; web-preview consumes one | `.venv/bin/halfblood annotate examples/src/alice.pdf -o /tmp/hbp-final-plan.json --provider stub --pages 1-3 --dry-run --force`; `.venv/bin/halfblood web-preview /tmp/hbp-final-plan.json -o /tmp/hbp-final-preview.html --force` | Observed CLI runs, plus `tests/test_dry_run_progress.py` and `tests/test_web_preview.py`. The HTML viewer is not a PDF geometry oracle. |
| Partial failure can ship an artifact; total generation failure exits nonzero without creating one | `.venv/bin/python -m pytest tests/test_checkpoint_resume.py tests/test_failure_sidecar.py -q` | Observed provider-stub failures. Setup errors and SIGKILL do not promise a sidecar; existing unrelated outputs are not deleted on failure. |
| Inputs survive output aliases, including `--force`, sidecars, checkpoints, resume | `.venv/bin/python -m pytest tests/test_cli_output_safety.py tests/test_cli_hardening.py tests/test_checkpoint_resume.py -q` | Observed byte equality for direct paths, symlinks, and hard links. These guards do not lock paths against hostile concurrent replacement; concurrent writes to the same output are unsupported. |
| Existing outputs require `--force`; missing output parents are created | `.venv/bin/python -m pytest tests/test_cli_hardening.py tests/test_cli_output_safety.py -q` | Observed CLI tests. Applies to program writes, not a shell redirect that a user supplies externally. |
| Four persona names, configured providers, default model, credential variable | `.venv/bin/halfblood annotate --help`; `.venv/bin/python -m pytest tests/test_config.py tests/test_persona_config.py tests/test_persona_packaging.py -q` | Observed local CLI/config tests. Remote model availability, provider credentials, and model quality are Unknown. |
| Example-source rebuild script exists and uses Gutenberg | Inspect `scripts/build_example_book.py` | Derived from source. The final offline gates do not re-download or rebuild the committed source books. |

## Installation, fonts, licensing, and prior art

| README claim | Falsifying check | Evidence class and limit |
| --- | --- | --- |
| Package installs; Python 3.11+ declaration; dependencies and lock workflow | `.venv/bin/python scripts/wheel_smoke.py`; `.venv/bin/python -m pytest tests/test_packaging.py -q` | Observed clean-wheel install and metadata checks on the recorded local Python. CI separately covers the declared Python matrix; local checks do not prove every interpreter/platform. |
| Four bundled fonts, source override/glob order, display-name rejection, package/system/fallback resolution | `.venv/bin/python -m pytest tests/test_font_packaging.py tests/test_font_resolution.py tests/test_font_selection.py -q`; wheel smoke above | Observed packaged-font checks; fallback order also Derived from `DocumentProcessor._resolve_font` and CLI registry. EPUB typography is controlled by reader/CSS. |
| AGPL source license and separate font licenses | Inspect `LICENSE`, `pyproject.toml`, `THIRD_PARTY_NOTICES.md`, `src/halfblood/fonts/OFL.txt`, `src/halfblood/fonts/Apache-2.0.txt` | Observed notices/metadata. Legal applicability to a deployment is not independently adjudicated. |
| Alice is public domain in the USA; retained Gutenberg terms apply to these copies | Inspect the rights metadata in `examples/src/alice.epub` and the footer of `examples/src/pg11.txt`; [Gutenberg #11](https://www.gutenberg.org/ebooks/11) and [license](https://www.gutenberg.org/policy/license.html) | Observed source notices and primary listing. Worldwide permission is Unknown; README does not claim it. |
| Anchorite already provides PDF quote/bbox alignment, including Smith–Waterman and rejection policies | `gh api repos/populationgenomics/anchorite/readme --jq .content` (base64 decode); [primary repo](https://github.com/populationgenomics/anchorite) | Observed primary documentation, saved excerpt in `docs/evidence/placement-release/prior-art.md`. No runtime comparison or superiority claim. Uniqueness checks during alignment are not asserted to equal this API's ambiguity policy. |
| W3C selector names and Hypothesis fuzzy anchoring are established references | [W3C TextQuoteSelector](https://www.w3.org/TR/annotation-model/#text-quote-selector), [TextPositionSelector](https://www.w3.org/TR/annotation-model/#text-position-selector), [Hypothesis](https://web.hypothes.is/blog/fuzzy-anchoring/) | Primary reference citations, not a conformance certification. “Fail-closed anchoring” is this project's label. |
| No quality evaluation is presented for this release | Final evidence packet | Blocked: rejected HTTP 401 repository credential, observed before the checkpoint and not re-probed. Neither stub scores nor self-judging count as quality evidence. |

## What the reader should not believe

Do not infer universal correct anchoring, semantic truth, OCR correctness,
byte-identical rendered files, collision-free connectors, fixed-layout EPUB
support, reflowable EPUB pixel positions, remote model availability, or a paid
frontier quality score from passing these checks. Preserved worker reports are
inputs to review, not substitutes for the final root command outputs.
