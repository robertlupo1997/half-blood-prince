# HBP-ROADMAP-OX — What `half-blood-prince` Becomes

Written from `HBP-STATE-OX.md` at `ed235f5`. Every uncertain point in the assessment
was re-resolved against source before being carried into a phase here:

- *Is resume hard?* No. `AnnotationGenerator.generate_for_document` already fires an
  `on_page_done` callback per page (`annotation_generator.py:398`, invoked at `:594`),
  and the `--dry-run` plan JSON (`cli.py:831`, `model_dump_json`) is a ready-made
  partial-plan format. Resume is a streaming hook plus one flag.
- *Is prompt caching easy?* Yes, but modest alone. The Anthropic adapter sends the system
  prompt as a bare string (`generation/providers/anthropic.py:186`). Converting it to a
  content block with `cache_control` is a change at exactly one seam. The arithmetic below
  shows why caching alone saves little and model tiering is the real lever.
- *How much does one honest eval run cost?* The harness has 5 curated passages and a
  `--judge-model` flag (`eval/eval_harness.py:23`, `:198`). Generation + independent
  judging is under \$5 even at frontier pricing.
- *Do anchor-benchmark corpora exist?* No. The measured rates (48/50, 84/88) exist only
  in prose handoffs. The benchmark is new work, budgeted as such below.

---

## 0. THE DECISION

Section 4 of the assessment found three products hiding in this repository. Keeping all
three alive is how this repo stays a very well-tested demo forever. The decision:

> **Primary direction: Product 3 — the grounded document-annotation engine.**
> The exact-quote anchoring ladder with fail-closed ambiguity handling, cross-node EPUB
> matching, the integer beam layout solver, structured-output negotiation with downgrade
> chains, and typed degradation reporting. This is the part of the repo that answers a
> question other builders actually have: *how do you put LLM output onto a document at the
> right pixels without lying about it.* It matches the code's own center of gravity, it has
> no direct named competitor (see §4), and it is the claim a technical portfolio reviewer
> cannot dismiss.

**What the other two become:**

- **Product 1 (the Snape gag): MODE, not direction.** It stays exactly as shipped — it is
  the hook that makes a reviewer open the repo, and it already works. It gets Phase 1–2
  fixes only because broken software embarrasses whatever it demos. Zero new feature work.
- **Product 2 (persona-voiced study tool): DROPPED as a product ambition.** It would
  compete with Readwise Reader AI, NotebookLM, and Perusall on their turf, with worse unit
  economics (one LLM call per page vs. retrieval-on-demand) and unproven quality (n≈1
  self-judged run). Personas survive only as a CLI feature the eval rubric happens to
  score. No phase below spends an hour chasing this market.

Everything below serves the primary direction: first make the pipeline survivable and
provable (Phases 1–2), then turn the engine's hidden excellence into committed,
reproducible evidence (Phases 3–4).

---

## 1. PHASES

### Phase 1 — Survive a real book (one person, one weekend)

Fixes §5 items 1, 4, 3 of the assessment. Nothing here is glamorous; all of it is
load-bearing for every public claim later.

Work items:
1. **Checkpoint/resume.** Stream each finished page into a partial plan JSON via the
   existing `on_page_done` callback; add `--resume-from plan.json`. Reuse the dry-run
   format so no new serialization path exists.
2. **Failure sidecar.** Write `<output>.report.json` next to every artifact: per-page
   generation failures, skip reasons, mark-only degradations (the types already exist in
   `models/rendering.py`). A run with failed pages still ships the artifact, but never
   silently.
3. **Environment-proof console tests.** Strip ANSI / force a deterministic Rich console in
   the test harness so the 7 known plain-shell failures die.

**Completion test (runnable by anyone):**
```bash
# 1. Resume: interrupt mid-book, finish from the checkpoint.
halfblood annotate book.pdf -o out.pdf --max-pages 20 &
kill %1   # after several pages complete
halfblood annotate book.pdf -o out.pdf --resume-from out.plan.json --force
test -f out.pdf && python -c "import json; r=json.load(open('out.pdf.report.json')); assert r['pages_annotated'] > 0"

# 2. Failure visibility: force a failing page, confirm the sidecar names it.
halfblood annotate book.pdf -o out.pdf --provider stub --fail-pages 7,13 --force
python -c "import json; r=json.load(open('out.pdf.report.json')); assert r['failed_pages'] == [7, 13]"

# 3. Clean suite anywhere, including a plain non-tty shell:
env -i PATH="$PATH" HOME="$HOME" .venv/bin/python -m pytest -q   # 1849 passed, 0 failed
```

| Cost | Arithmetic |
| --- | --- |
| Hours | Resume 6h (hook exists) + sidecar 4h + console tests 2h + buffer 4h = **16h** |
| API spend | **\$0.** All three items are provable with the deterministic stub provider used by `tests/test_cli_end_to_end.py`. Optional single real-model smoke: 20 pages × ~1.85k in / ~0.6k out tokens ≈ 37k + 12k tokens → at Sonnet-class \$3/\$15 per M ≈ \$0.11 + \$0.18 ≈ **< \$0.30** |

**Portfolio evidence produced:** the resume command above becomes a README snippet; the
report-sidecar fixture is committed under `tests/fixtures/`. Claim enabled: *"crash-safe
long runs"* — backed by a command, not prose.

---

### Phase 2 — Make every public claim falsifiable (1–2 evenings + one paid afternoon)

Fixes §5 items 2, 7, 10. This is the phase that converts the repo's biggest weakness
("how do you know the notes are good?" — answer today: one eyeballed 9-page run) into its
strongest exhibit.

Work items:
1. **Run the eval harness with an independent judge and commit everything.** Generate with
   one provider family, judge with a different frontier model (the harness already enforces
   this separation; `--allow-self-judge` stays off). Commit `eval/results-gen-<model>.json`,
   `eval/results-judge-<model>.json`, and a summary table in `README.md`.
2. **Commit rendered examples.** One annotated public-domain PDF (~40–80 pages, chosen for
   clean text layer) rendered end-to-end, plus its EPUB twin, plus one screenshot in the
   README. First images of actual output ever committed to this repo.
3. **CLAUDE.md truth pass.** Fix the five documented stale claims (44 tests, no concurrency,
   collision detection open, Anthropic SDK, native annots). Tiny effort, ends the
   wasted-investigation tax the file currently charges.

**Completion test:**
```bash
# Eval artifacts exist and reproduce:
python eval/eval_harness.py --generator-model <committed-gen-model> \
                            --judge-model    <committed-judge-model>
git status --porcelain eval/ | wc -l        # == 0: committed results still match a rerun
grep -c "results-" README.md                # >= 2: summary table cites committed files

# Examples exist and were produced by this tree:
ls examples/hbp-example.pdf examples/hbp-example.epub examples/screenshot.png
halfblood providers doctor --offline         # exits 0
```

| Cost | Arithmetic |
| --- | --- |
| Hours | Eval run + write-up 4h + example selection/render/eyeball 4h + README/CLAUDE.md pass 3h + buffer 3h = **14h** |
| API spend | Eval: 5 passages × (gen ~2k in + ~2k out) + 5 judge calls × ~3k in/~0.5k out ≈ 25k gen + 17.5k judge tokens → Sonnet-class gen ≈ \$0.34; Opus-class judge (\$15/\$75 per M) ≈ \$0.30. Example book: 60 pages ≈ 111k in + 36k out ≈ **\$0.87** Sonnet-class, or **~\$0.22** Haiku-class. Total ≈ **\$1.50–\$2.50** |

**Portfolio evidence produced:** committed judge scorecards, the annotated example
PDF/EPUB, screenshot. Claims enabled: *"LLM-judged quality with an independent judge"*, *"you
can see the output before you spend a token."* These are precisely the two questions a
reviewer asks first (assessment §6).

---

### Phase 3 — Turn the engine's hidden numbers into committed numbers (1 week of evenings)

This is where the primary direction stops being a claim. Fixes §5 items 6, 9 (first slice),
5.

Work items:
1. **Prompt caching at the one seam.** Convert `"system": request.system_prompt`
   (`anthropic.py:186`) to a cached content block; measure. Honest expectation from the
   arithmetic in §3: caching trims roughly half the input bill, not 10×. Commit the
   before/after usage lines as a cost table in the README.
2. **`--cheap-model` triage.** Route DOODLE_NOTE-class pages to a small model. This is the
   actual 3–8× lever; measure it on the same example book and commit both runs' usage
   totals.
3. **Anchor-rate benchmark.** Build the missing corpus fixtures: ~50 clean-text anchors +
   ~50 degraded anchors (scans with OCR text layers, odd dashes/whitespace, EPUB cross-node
   cases — the shapes `matching.py:317` tiers already handle). Add
   `tests/test_anchor_benchmark.py` printing committed anchor-rate numbers. The handoff
   figures (48/50, 84/88) finally get a home anyone can check.
4. **Total degradation-code coverage.** Extend `test_degradation_mapping.py` until all
   composer codes map (Session 34 leftover).

**Completion test:**
```bash
.venv/bin/python -m pytest tests/test_anchor_benchmark.py -q -s | tail -3
# prints: clean anchor rate X/50, degraded anchor rate Y/50 — numbers committed in README

# Cost table reproduces from committed usage logs:
halfblood annotate examples/book.pdf -o /tmp/a.pdf --force && grep "usage" /tmp/a.report.json
halfblood annotate examples/book.pdf -o /tmp/b.pdf --cheap-model --force && grep "usage" /tmp/b.report.json
python scripts/check_harness_contracts.py     # still green

# Caching proven on-wire, not claimed:
.venv/bin/python -m pytest tests/test_anthropic_provider.py -q -k cache   # asserts cache_control blocks present
```

| Cost | Arithmetic |
| --- | --- |
| Hours | Caching 3h (one seam) + triage 6h + corpus building 12h (the real cost — sourcing/verifying 100 anchor cases) + benchmark test 4h + degradation codes 2h + buffer 5h = **32h** |
| API spend | Corpus generation uses deterministic fixtures, **\$0**. Measurement runs: example book twice (cached, tiered) ≈ 2 × \$0.9 ≈ **\$1.80**; eval re-run after triage changes prompts ≈ \$0.65. Total ≈ **\$2.50** |

**Portfolio evidence produced:** committed anchor-rate benchmark with a runnable command;
committed cost table with before/after token logs; total degradation coverage. Claim
enabled: *"measured grounding accuracy of X% on Y adversarial anchors — run it yourself."*

---

### Phase 4 — Extract the library (only if Phase 3's numbers earn it)

Conditional later phase: split `documents/` (+ the schema/downgrade-chain seam) into an
installable package with its own README and the Phase 3 benchmark as its headline. Add
connector routing around body columns (`pdf_occupancy.py` data already exists) only if the
demo remains the library's showcase.

**Completion test:**
```bash
pip install dist/halfblood_anchor-*.whl && python -c \
  "from halfblood_anchor import match_target; print(match_target('text','target').exactness)"
pytest tests/test_anchor_benchmark.py -q      # benchmark passes against the extracted package
```

| Cost | Arithmetic |
| --- | --- |
| Hours | Package boundary audit 8h + decoupling 12h + packaging/wheel 4h + docs 4h + buffer 4h = **32h** (do not start without 2 clear weeks) |
| API spend | **\$0** — pure refactoring; benchmark is deterministic |

**Portfolio evidence produced:** second installable artifact + the benchmark running
against it.

---

## 2. TOTAL INVESTMENT

| Phase | Hours | API spend |
| --- | --- | --- |
| 1 Survive | 16h | < \$0.30 |
| 2 Evidence | 14h | \$1.50–2.50 |
| 3 Numbers | 32h | ~\$2.50 |
| 4 Library (conditional) | 32h | \$0 |
| **Through Phase 3** | **62h** | **under \$6** |

API spend is negligible throughout; the currencies are hours and honesty. Pricing assumed:
Sonnet-class \$3/\$15 per M tokens, Opus-class \$15/\$75, Haiku-class ~\$1/\$5; per-page
usage measured in the assessment (~1.85k in, ≤2.05k out capped, ~0.6k out typical).

## 3. COST ARITHMETIC PER BOOK (why Phase 3 matters)

400-page book, Sonnet-class, current code:
input 400 × 1,850 tok = 740k × \$3/M = \$2.22; output 400 × 600 tok = 240k × \$15/M =
\$3.60 → **~\$5.80/book** (worst case with maxed outputs: ~\$14.50).

- Prompt caching (static ~1.25k tok/page of the 1.85k cached at 0.1× read price):
  saves 0.5M × \$3 × 0.9 ≈ **\$1.35/book**. Worth it; not transformative.
- Triage (Haiku-class for most pages): 320k in × \$1/M + 190k out × \$5/M ≈ \$1.27 vs
  \$5.80 → **~4.5× cheaper**, ~\$1.30/book. This is the real lever, which is why it —
  not caching — carries Phase 3's cost story.

## 4. WHAT IT COMPETES WITH

- **As a visible product (Snape demo):** AI-novelty content generally and Riddle (named
  inspiration, `CLAUDE.md:95`) specifically. Differentiator: the annotations are *grounded*
  (anchored to exact quotes, fail-closed on ambiguity) and physically *rendered* (vector
  ink, layout-solved, connectors) rather than pasted chat bubbles. That difference is real
  but shallow as a moat — it is the door, not the house.
- **As a study tool: deliberately not competing.** Readwise Reader AI, NotebookLM, Perusall,
  chat-with-PDF. We lose on unit economics by design; see Decision.
- **As the engine: no direct named competitor.** The honest statement is that its
  competition is *hand-rolled fuzzy matching inside every in-house document tool* —
  invisible, fragmented, and universally mediocre. There is no product to beat, only a gap
  to occupy with measured numbers. If a reviewer names an equivalent open-source anchored-
  markup library, that is a Phase 4 kill-criterion input, not a reason to hide.

## 5. KILL CRITERIA

Stop conditions, stated before starting so they cannot be negotiated away later:

1. **Quality fails independently.** If the Phase 2 independent-judge run scores any rubric
   metric below 3.0 average, or two different judge models disagree by more than 1.5
   points on the same passage set, the quality claim cannot be made publicly. Do not tune
   prompts to chase the number more than once. One retry, then accept: this is a demo, not
   a product, and skip Phases 3–4.
2. **The engine numbers don't materialize.** If the Phase 3 benchmark lands below 90%
   anchor rate on clean text or below 70% on degraded inputs, the "defensible engine"
   thesis is dead. Freeze at Phase 2 state: a charming, well-tested demo — which is a fine
   thing for a portfolio's third slot, and worth no further hours.
3. **Phase 1 misses the weekend badly.** If resume takes more than double its 6-hour
   estimate or touches more than three modules, the architecture resists its own
   callbacks — treat that as information about the whole codebase and reassess before
   spending anything else.
4. **Budget breach.** If cumulative hours pass 70 before Phase 3 completes, stop and ship
   what exists. The marginal hour is buying polish, not evidence.
5. **Silence after publication.** If, six weeks after Phase 2 evidence goes up, the repo
   has zero external issues, forks, or substantive contacts, the portfolio value was
   already fully captured by the existing code. Archive with a good README rather than
   grind Phase 3 into a ghost town.

Willingness to say it plainly: at `ed235f5` this repository already demonstrates rare
engineering discipline. Its marginal value over the next 62 hours is entirely in evidence
and extraction, not features. If Phases 2 and 3 do not produce committed, reproducible
numbers, the correct move is to stop — the repo deserves to be shown, not perpetually
finished.
