#!/usr/bin/env python
"""Evaluation harness for Half-Blood Prince annotation quality.

This script exercises the annotation pipeline against a small set of
curated, hand-written public-domain-style passages (chemistry, cooking,
philosophy, physics, rhetoric) and grades the resulting margin
annotations with an LLM-as-judge across five quality metrics:

    * voice_consistency  -- does it sound like the Prince (terse, sardonic, expert)?
    * relevance          -- is it actually anchored to the target text?
    * insight_depth      -- does it add real value, or just restate the passage?
    * variety            -- healthy mix of annotation types, not one type repeated?
    * density             -- roughly the right number of notes for the passage?

If ``halfblood.annotation_generator.AnnotationGenerator`` (and
``halfblood.document_processor.PageContent``) are importable, the harness
uses the real pipeline to generate annotations for each test passage. If
those modules aren't available yet (e.g. during early development), it
falls back to a small built-in generator that calls the Anthropic API
directly, so this harness is runnable standalone from day one.

Usage:

    export ANTHROPIC_API_KEY=sk-...
    python eval/eval_harness.py
    python eval/eval_harness.py --model claude-opus-4-1-20250805
    python eval/eval_harness.py --json-out results.json
    python eval/eval_harness.py --list

Exit code is 0 if every test case passed every metric threshold, 1 otherwise.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from anthropic import Anthropic
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.table import Table

# ---------------------------------------------------------------------------
# Make the `halfblood` package importable when this file is run directly via
# `python eval/eval_harness.py` without the project having been pip-installed.
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).resolve().parents[1]
_SRC_DIR = _REPO_ROOT / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from halfblood.annotation_generator import DEFAULT_MODEL as _PIPELINE_DEFAULT_MODEL  # noqa: E402
from halfblood.models import Annotation, AnnotationType  # noqa: E402

try:
    from halfblood.annotation_generator import AnnotationGenerator
except ImportError:  # not implemented yet -- harness falls back to a built-in generator
    AnnotationGenerator = None  # type: ignore[assignment,misc]

try:
    from halfblood.document_processor import PageContent
except ImportError:  # not implemented yet
    PageContent = None  # type: ignore[assignment,misc]


DEFAULT_MODEL = os.environ.get("HALFBLOOD_EVAL_MODEL", _PIPELINE_DEFAULT_MODEL)


# ---------------------------------------------------------------------------
# Metric definitions
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Metric:
    """A single quality dimension the LLM judge scores from 1 to 5."""

    key: str
    label: str
    description: str
    rubric: str
    threshold: float = 3.5  # minimum average score to "pass" this metric


METRICS: list[Metric] = [
    Metric(
        key="voice_consistency",
        label="Voice Consistency",
        description=(
            "Does the annotation sound like the Half-Blood Prince -- terse, "
            "sardonic, quietly expert -- rather than a generic assistant?"
        ),
        rubric=(
            "1 = Generic textbook tone, no personality. "
            "2 = Slight personality but verbose or bland. "
            "3 = Recognizable voice but inconsistent, occasionally too chatty or formal. "
            "4 = Consistently terse, dry, confident -- reads like real handwritten marginalia. "
            "5 = Unmistakably the Prince: economical, sardonic, betrays deep mastery in a few words."
        ),
        threshold=3.5,
    ),
    Metric(
        key="relevance",
        label="Relevance",
        description=(
            "Does each annotation clearly and specifically relate to the exact "
            "passage text it is attached to, rather than floating free of it?"
        ),
        rubric=(
            "1 = Annotations are generic and could apply to any passage. "
            "2 = Loosely related, vague connection to the text. "
            "3 = Related but sometimes misidentifies or misquotes the target text. "
            "4 = Clearly tied to specific words or claims in the passage. "
            "5 = Every annotation is precisely anchored to an exact, correctly-quoted piece of the passage."
        ),
        threshold=4.0,
    ),
    Metric(
        key="insight_depth",
        label="Insight Depth",
        description=(
            "Does the annotation add genuine expert value beyond simply "
            "paraphrasing or restating what the passage already says?"
        ),
        rubric=(
            "1 = Pure restatement or summary of the text, no new information. "
            "2 = Mostly restatement with a thin opinion layered on top. "
            "3 = Some genuine insight but shallow or obvious to any competent reader. "
            "4 = Clear expert-level insight, correction, or extension a novice wouldn't think of. "
            "5 = Consistently surprising, specific, expert-level insight that changes how you'd read the passage."
        ),
        threshold=3.5,
    ),
    Metric(
        key="variety",
        label="Variety",
        description=(
            "Across the full set of annotations for this passage, is there a "
            "healthy mix of annotation types rather than one type repeated?"
        ),
        rubric=(
            "1 = Every annotation is the same type. "
            "2 = Two types used, heavily skewed toward one. "
            "3 = At least three types represented, somewhat balanced. "
            "4 = Good spread across types, matching what the passage calls for. "
            "5 = Types are precisely matched to what each spot in the text needs -- none feel forced."
        ),
        threshold=3.0,
    ),
    Metric(
        key="density",
        label="Density",
        description=(
            "Is the number of annotations appropriate for the length and "
            "complexity of the passage -- not so sparse it feels unfinished, "
            "not so dense it clutters the margin?"
        ),
        rubric=(
            "1 = Wildly off the ideal range (essentially empty or overwhelming). "
            "2 = Noticeably too sparse or too dense. "
            "3 = Close to the ideal range but a bit off. "
            "4 = Within or very near the ideal range for this passage. "
            "5 = Exactly the right amount -- every annotation earns its place, nothing important is missed."
        ),
        threshold=3.5,
    ),
]

METRIC_BY_KEY: dict[str, Metric] = {m.key: m for m in METRICS}


# ---------------------------------------------------------------------------
# Curated test cases
#
# Each passage below was written for this harness (not reproduced from any
# copyrighted source) to give broad genre coverage: a chemistry textbook, a
# cooking recipe, a philosophy excerpt, a physics textbook, and a rhetoric /
# writing guide. `expected_annotation_types` and `ideal_annotation_range`
# give the judge concrete, passage-specific expectations for the variety
# and density metrics.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TestCase:
    """A single curated passage used to exercise the annotation pipeline."""

    id: str
    title: str
    genre: str
    persona: str
    passage: str
    expected_annotation_types: list[str]
    ideal_annotation_range: tuple[int, int]
    notes: str


TEST_CASES: list[TestCase] = [
    TestCase(
        id="chemistry-titration",
        title="Principles of Quantitative Analysis",
        genre="Chemistry Textbook",
        persona=(
            "A meticulous, sardonic analytical chemistry professor who has run "
            "ten thousand titrations and has no patience for sloppy technique."
        ),
        passage=(
            "To determine the concentration of an unknown acid, slowly add "
            "standardized base from the burette while swirling the flask "
            "continuously. Watch for the first permanent color change in the "
            "indicator; this marks the endpoint. Record the volume of titrant "
            "used. Repeat the trial at least twice more to confirm "
            "reproducibility, then average your results. Most students stop "
            "titrating the instant they see any hint of color, which "
            "introduces systematic error. A careful analyst always overshoots "
            "slightly on the first trial to bracket the endpoint before "
            "approaching it slowly on subsequent trials."
        ),
        expected_annotation_types=["warning", "correction", "insight", "shortcut"],
        ideal_annotation_range=(3, 6),
        notes=(
            "Good annotations call out the deliberate-overshoot technique as "
            "genuine insight, warn about premature endpoint calls, and flag "
            "missing detail such as swirling technique or using a white "
            "background under the flask."
        ),
    ),
    TestCase(
        id="cooking-omelette",
        title="The Weeknight Kitchen",
        genre="Cooking / Recipe",
        persona=(
            "A blunt, classically trained cook who thinks most recipe writers "
            "have never actually cooked the dish they're describing."
        ),
        passage=(
            "Crack three eggs into a bowl and whisk until just combined. Melt "
            "a knob of butter in a nonstick pan over medium heat. Pour in the "
            "eggs and let them sit undisturbed for a few seconds, then use a "
            "spatula to gently push the cooked edges toward the center, "
            "tilting the pan so uncooked egg flows to the sides. When the "
            "eggs are mostly set but still glossy on top, fold the omelette "
            "in half and slide it onto a plate."
        ),
        expected_annotation_types=["correction", "improvement", "shortcut", "doodle_note"],
        ideal_annotation_range=(2, 5),
        notes=(
            "Good annotations correct the heat level ('medium is too hot, "
            "you'll get rubber'), suggest resting the eggs at room "
            "temperature first, or reassure the reader that 'glossy' "
            "(baveuse) is intentional, not underdone."
        ),
    ),
    TestCase(
        id="philosophy-certainty",
        title="On the Foundations of Certainty",
        genre="Philosophy",
        persona=(
            "A dry, rigorous epistemologist who delights in poking holes in "
            "comfortable assumptions."
        ),
        passage=(
            "Suppose everything we perceive through the senses could, in "
            "principle, be an elaborate deception. If even our most basic "
            "experiences are open to doubt, can any knowledge be considered "
            "truly secure? One response is to seek a foundation immune to "
            "doubt: some starting point so certain that even the deceived "
            "mind cannot deny it. From this single foothold, the argument "
            "proceeds, a structure of reliable knowledge might be rebuilt "
            "piece by piece."
        ),
        expected_annotation_types=["insight", "warning", "invention", "correction"],
        ideal_annotation_range=(2, 5),
        notes=(
            "Good annotations note the circularity risk in 'rebuilding "
            "knowledge' from one foothold, reference the general problem of "
            "finding a non-arbitrary criterion for certainty, or push back "
            "on the assumption that knowledge requires immunity to all doubt."
        ),
    ),
    TestCase(
        id="physics-newton",
        title="Classical Mechanics: A First Course",
        genre="Physics Textbook",
        persona=(
            "An impatient theoretical physicist who thinks most textbook "
            "explanations bury the intuition under notation."
        ),
        passage=(
            "An object at rest remains at rest, and an object in motion "
            "continues at constant velocity, unless acted upon by a net "
            "external force. This tendency to resist changes in motion is "
            "called inertia and depends on the object's mass. When a force "
            "is applied, the resulting acceleration is directly proportional "
            "to the force and inversely proportional to the mass. For every "
            "action force exerted by one body on another, there exists an "
            "equal and opposite reaction force exerted by the second body on "
            "the first."
        ),
        expected_annotation_types=["insight", "shortcut", "invention", "correction"],
        ideal_annotation_range=(3, 6),
        notes=(
            "Good annotations flag that this only holds in inertial frames, "
            "connect F=ma to the more general F=dp/dt for variable-mass or "
            "relativistic cases, and correct the common misconception that "
            "action-reaction pairs act on the same body (they don't, which "
            "is why they don't cancel)."
        ),
    ),
    TestCase(
        id="rhetoric-persuasion",
        title="The Art of Persuasion",
        genre="Rhetoric / Writing Guide",
        persona=(
            "A no-nonsense debate coach who has watched a thousand mediocre "
            "arguments collapse under the first hard question."
        ),
        passage=(
            "A persuasive argument begins with a clear claim, followed by "
            "evidence that supports it, and closes by addressing the "
            "strongest objection your audience is likely to raise. Writers "
            "often skip the final step, assuming that stacking more evidence "
            "will overwhelm any doubt. In practice, an audience that senses "
            "an unaddressed objection trusts the entire argument less, even "
            "if every individual piece of evidence is sound."
        ),
        expected_annotation_types=["insight", "warning", "improvement", "doodle_note"],
        ideal_annotation_range=(2, 4),
        notes=(
            "Good annotations praise the counter-argument point but push "
            "further by naming the strongest objection explicitly, or warn "
            "against 'gish gallop' style evidence-stacking as a substitute "
            "for actually engaging with objections."
        ),
    ),
]


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


@dataclass
class MetricScore:
    """A single metric's score and justification for one test case."""

    metric_key: str
    score: float
    justification: str
    passed: bool


@dataclass
class EvalResult:
    """The full result of generating and judging annotations for one test case."""

    test_case: TestCase
    annotations: list[Annotation] = field(default_factory=list)
    scores: list[MetricScore] = field(default_factory=list)
    generation_error: str | None = None

    @property
    def overall_score(self) -> float:
        if not self.scores:
            return 0.0
        return statistics.fmean(s.score for s in self.scores)

    @property
    def grade(self) -> str:
        return _letter_grade(self.overall_score)

    @property
    def all_passed(self) -> bool:
        return bool(self.scores) and all(s.passed for s in self.scores)


def _letter_grade(score: float) -> str:
    """Convert a 1-5 average score into a letter grade."""
    if score >= 4.5:
        return "A"
    if score >= 3.8:
        return "B"
    if score >= 3.0:
        return "C"
    if score >= 2.0:
        return "D"
    return "F"


# ---------------------------------------------------------------------------
# Annotation generation (real pipeline if available, otherwise built-in
# fallback that talks to Claude directly)
# ---------------------------------------------------------------------------

GENERATION_TOOL: dict[str, Any] = {
    "name": "record_annotations",
    "description": (
        "Record the set of Half-Blood-Prince-style margin annotations "
        "generated for a passage."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "annotations": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "target_text": {
                            "type": "string",
                            "description": "A short, verbatim excerpt from the passage this note refers to.",
                        },
                        "annotation_type": {
                            "type": "string",
                            "enum": [t.value for t in AnnotationType],
                        },
                        "content": {
                            "type": "string",
                            "description": "The handwritten margin note itself.",
                        },
                        "confidence": {
                            "type": "number",
                            "minimum": 0,
                            "maximum": 1,
                        },
                        "position": {
                            "type": "string",
                            "enum": ["margin_right", "margin_left", "inline", "between_lines"],
                        },
                    },
                    "required": ["target_text", "annotation_type", "content"],
                },
            }
        },
        "required": ["annotations"],
    },
}


def _fallback_generate(tc: TestCase, client: Anthropic, model: str) -> list[Annotation]:
    """Generate annotations directly via the Anthropic API.

    Used when ``halfblood.annotation_generator.AnnotationGenerator`` is not
    yet available, so this harness can run standalone.
    """
    lo, hi = tc.ideal_annotation_range
    system_prompt = (
        "You are ghost-writing marginalia in the voice of the Half-Blood "
        f"Prince: {tc.persona} You are terse, sardonic, and quietly "
        "brilliant. You annotate the margins of a book with corrections, "
        "improvements, warnings, shortcuts, inventions, and the occasional "
        "dry aside. Never restate what the text already says; only add "
        "annotations that a genuine expert reading over the author's "
        "shoulder would actually bother to scrawl down."
    )
    user_prompt = (
        f"Book: {tc.title} ({tc.genre})\n\n"
        f'Passage:\n"""\n{tc.passage}\n"""\n\n'
        f"Produce between {lo} and {hi} margin annotations for this "
        "passage using the record_annotations tool. Vary the annotation "
        f"types (favor: {', '.join(tc.expected_annotation_types)}). Each "
        "target_text must be a short verbatim excerpt copied exactly from "
        "the passage above."
    )
    response = client.messages.create(
        model=model,
        max_tokens=2048,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
        tools=[GENERATION_TOOL],
        tool_choice={"type": "tool", "name": "record_annotations"},
    )
    tool_block = next((b for b in response.content if b.type == "tool_use"), None)
    if tool_block is None:
        return []
    raw_annotations = tool_block.input.get("annotations", [])  # type: ignore[union-attr]

    annotations: list[Annotation] = []
    for raw in raw_annotations:
        try:
            annotations.append(
                Annotation(
                    page=1,
                    target_text=raw["target_text"],
                    annotation_type=AnnotationType(raw["annotation_type"]),
                    content=raw["content"],
                    confidence=float(raw.get("confidence", 0.8)),
                    position=raw.get("position", "margin_right"),
                )
            )
        except (KeyError, ValueError):
            # Skip malformed entries rather than failing the whole test case.
            continue
    return annotations


def generate_annotations(
    tc: TestCase, client: Anthropic, model: str, console: Console
) -> list[Annotation]:
    """Generate annotations for a test case, preferring the real pipeline."""
    if AnnotationGenerator is not None and PageContent is not None:
        try:
            generator = AnnotationGenerator(persona=tc.persona, model=model)
            result = generator.generate_for_page(
                page_text=tc.passage, page_number=1, book_context=""
            )
            if isinstance(result, list):
                return result
        except Exception as exc:  # noqa: BLE001 - defensive fallback boundary
            console.print(
                f"[yellow]AnnotationGenerator unavailable or failed ({exc}); "
                "using the eval harness's built-in generator instead.[/yellow]"
            )
    return _fallback_generate(tc, client, model)


# ---------------------------------------------------------------------------
# LLM-as-judge
# ---------------------------------------------------------------------------


def _build_judge_tool() -> dict[str, Any]:
    """Build the tool schema the judge model must fill in, one entry per metric."""
    properties = {
        m.key: {
            "type": "object",
            "properties": {
                "score": {"type": "integer", "minimum": 1, "maximum": 5},
                "justification": {"type": "string"},
            },
            "required": ["score", "justification"],
        }
        for m in METRICS
    }
    return {
        "name": "record_scores",
        "description": (
            "Record a 1-5 score and a specific justification for each "
            "annotation-quality metric."
        ),
        "input_schema": {
            "type": "object",
            "properties": properties,
            "required": [m.key for m in METRICS],
        },
    }


def judge_annotations(
    tc: TestCase, annotations: list[Annotation], client: Anthropic, model: str
) -> list[MetricScore]:
    """Score a generated annotation set against all metrics using Claude as judge."""
    tool = _build_judge_tool()

    if annotations:
        annotations_text = "\n".join(
            f'- [{a.annotation_type.value}] near "{a.target_text}": {a.content} '
            f"(confidence={a.confidence:.2f}, position={a.position})"
            for a in annotations
        )
    else:
        annotations_text = "(no annotations were produced)"

    metrics_brief = "\n".join(
        f"- {m.key} ({m.label}): {m.description}\n  Rubric: {m.rubric}" for m in METRICS
    )

    system_prompt = (
        "You are a strict, senior editorial reviewer grading AI-generated "
        "marginalia written in the voice of the 'Half-Blood Prince' -- a "
        "brilliant, terse, sardonic expert annotator. Score objectively "
        "against the rubric provided. Do not be swayed by confident "
        "phrasing alone; reward substance."
    )
    user_prompt = (
        f"BOOK: {tc.title} ({tc.genre})\n"
        f"TARGET PERSONA: {tc.persona}\n\n"
        f'ORIGINAL PASSAGE:\n"""\n{tc.passage}\n"""\n\n'
        f"EXPECTED ANNOTATION TYPES: {', '.join(tc.expected_annotation_types)}\n"
        f"IDEAL ANNOTATION COUNT FOR THIS PASSAGE: "
        f"{tc.ideal_annotation_range[0]}-{tc.ideal_annotation_range[1]}\n"
        f"REVIEWER NOTES: {tc.notes}\n\n"
        f"GENERATED ANNOTATIONS ({len(annotations)} total):\n{annotations_text}\n\n"
        f"METRICS TO SCORE (integer 1-5 each):\n{metrics_brief}\n\n"
        "Score every metric using the record_scores tool. Be specific in "
        "each justification (reference actual annotation content), and be "
        "willing to give low scores when warranted."
    )
    response = client.messages.create(
        model=model,
        max_tokens=1536,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
        tools=[tool],
        tool_choice={"type": "tool", "name": "record_scores"},
    )
    tool_block = next((b for b in response.content if b.type == "tool_use"), None)
    if tool_block is None:
        return [
            MetricScore(metric_key=m.key, score=0, justification="(judge returned no tool call)", passed=False)
            for m in METRICS
        ]
    data: dict[str, Any] = tool_block.input  # type: ignore[assignment]

    scores: list[MetricScore] = []
    for m in METRICS:
        entry = data.get(m.key, {})
        score = float(entry.get("score", 0))
        justification = entry.get("justification", "(no justification returned)")
        scores.append(
            MetricScore(
                metric_key=m.key,
                score=score,
                justification=justification,
                passed=score >= m.threshold,
            )
        )
    return scores


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def run_eval(
    test_cases: list[TestCase], client: Anthropic, model: str, console: Console
) -> list[EvalResult]:
    """Generate and judge annotations for every test case, with progress reporting."""
    results: list[EvalResult] = []
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Running evaluation...", total=len(test_cases) * 2)
        for tc in test_cases:
            progress.update(task, description=f"[cyan]{tc.id}[/cyan]: generating annotations")
            try:
                annotations = generate_annotations(tc, client, model, console)
                progress.advance(task)
                progress.update(task, description=f"[cyan]{tc.id}[/cyan]: judging quality")
                scores = judge_annotations(tc, annotations, client, model)
                progress.advance(task)
                results.append(EvalResult(test_case=tc, annotations=annotations, scores=scores))
            except Exception as exc:  # noqa: BLE001 - keep evaluating remaining cases
                progress.advance(task, 2)
                results.append(EvalResult(test_case=tc, generation_error=str(exc)))
    return results


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def print_report(results: list[EvalResult], console: Console) -> bool:
    """Print per-case tables plus a summary table. Returns True iff everything passed."""
    console.rule("[bold magenta]Half-Blood Prince -- Evaluation Report[/bold magenta]")

    for result in results:
        tc = result.test_case
        header = f"{tc.id} -- {tc.title} ({tc.genre})"

        if result.generation_error:
            console.print(
                Panel(
                    f"[bold red]FAILED[/bold red]: {result.generation_error}",
                    title=header,
                    border_style="red",
                )
            )
            continue

        table = Table(title=header, box=box.SIMPLE_HEAVY, show_lines=True)
        table.add_column("Metric", style="bold")
        table.add_column("Score", justify="center")
        table.add_column("Status", justify="center")
        table.add_column("Justification")
        for score in result.scores:
            metric = METRIC_BY_KEY[score.metric_key]
            status = "[green]PASS[/green]" if score.passed else "[red]FAIL[/red]"
            table.add_row(metric.label, f"{score.score:.0f}/5", status, score.justification)
        console.print(table)
        console.print(
            f"  Annotations generated: {len(result.annotations)}  |  "
            f"Overall: {result.overall_score:.2f}/5  |  Grade: [bold]{result.grade}[/bold]\n"
        )

    summary = Table(title="Summary", box=box.HEAVY_EDGE)
    summary.add_column("Test Case")
    summary.add_column("Genre")
    summary.add_column("# Annotations", justify="right")
    summary.add_column("Overall", justify="right")
    summary.add_column("Grade", justify="center")
    summary.add_column("Metrics Passed", justify="center")
    summary.add_column("Result", justify="center")
    for result in results:
        if result.generation_error:
            summary.add_row(
                result.test_case.id, result.test_case.genre, "-", "-", "-", "-", "[red]ERROR[/red]"
            )
            continue
        passed_count = sum(1 for s in result.scores if s.passed)
        summary.add_row(
            result.test_case.id,
            result.test_case.genre,
            str(len(result.annotations)),
            f"{result.overall_score:.2f}",
            result.grade,
            f"{passed_count}/{len(result.scores)}",
            "[green]PASS[/green]" if result.all_passed else "[red]FAIL[/red]",
        )
    console.print(summary)

    valid_results = [r for r in results if not r.generation_error]
    all_passed = bool(valid_results) and all(r.all_passed for r in results)

    if valid_results:
        overall_avg = statistics.fmean(r.overall_score for r in valid_results)
        per_metric_avgs = {
            m.key: statistics.fmean(
                s.score for r in valid_results for s in r.scores if s.metric_key == m.key
            )
            for m in METRICS
        }
        metric_table = Table(title="Average Score by Metric", box=box.MINIMAL)
        metric_table.add_column("Metric")
        metric_table.add_column("Avg Score", justify="right")
        metric_table.add_column("Threshold", justify="right")
        metric_table.add_column("Status", justify="center")
        for m in METRICS:
            avg = per_metric_avgs[m.key]
            status = "[green]PASS[/green]" if avg >= m.threshold else "[red]FAIL[/red]"
            metric_table.add_row(m.label, f"{avg:.2f}", f"{m.threshold:.1f}", status)
        console.print(metric_table)
        console.print(
            Panel(
                f"Overall average score: [bold]{overall_avg:.2f}/5[/bold]   "
                f"Overall grade: [bold]{_letter_grade(overall_avg)}[/bold]   "
                f"Result: {'[bold green]PASS[/bold green]' if all_passed else '[bold red]FAIL[/bold red]'}",
                border_style="magenta",
            )
        )
    else:
        console.print("[bold red]All test cases failed to run.[/bold red]")

    return all_passed


def _results_to_json(results: list[EvalResult]) -> list[dict[str, Any]]:
    payload = []
    for result in results:
        payload.append(
            {
                "id": result.test_case.id,
                "title": result.test_case.title,
                "genre": result.test_case.genre,
                "generation_error": result.generation_error,
                "annotation_count": len(result.annotations),
                "overall_score": result.overall_score,
                "grade": result.grade,
                "all_passed": result.all_passed,
                "scores": [
                    {
                        "metric": s.metric_key,
                        "score": s.score,
                        "passed": s.passed,
                        "justification": s.justification,
                    }
                    for s in result.scores
                ],
                "annotations": [
                    {
                        "target_text": a.target_text,
                        "annotation_type": a.annotation_type.value,
                        "content": a.content,
                        "confidence": a.confidence,
                        "position": a.position,
                    }
                    for a in result.annotations
                ],
            }
        )
    return payload


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Run the full evaluation harness from the command line."""
    parser = argparse.ArgumentParser(
        description="Evaluate Half-Blood Prince annotation quality using an LLM judge."
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help="Anthropic model used for both the fallback generator and the judge.",
    )
    parser.add_argument(
        "--json-out",
        type=Path,
        default=None,
        help="Optional path to write raw evaluation results as JSON.",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List the curated test cases and exit without calling the API.",
    )
    args = parser.parse_args()

    console = Console()

    if args.list:
        table = Table(title="Half-Blood Prince Eval -- Test Cases", box=box.SIMPLE_HEAVY)
        table.add_column("ID")
        table.add_column("Title")
        table.add_column("Genre")
        table.add_column("Ideal # Annotations", justify="right")
        for tc in TEST_CASES:
            table.add_row(
                tc.id, tc.title, tc.genre, f"{tc.ideal_annotation_range[0]}-{tc.ideal_annotation_range[1]}"
            )
        console.print(table)
        return

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        console.print(
            "[bold red]ANTHROPIC_API_KEY is not set.[/bold red] "
            "Export it before running the eval harness."
        )
        raise SystemExit(1)

    client = Anthropic(api_key=api_key)
    results = run_eval(TEST_CASES, client, args.model, console)
    all_passed = print_report(results, console)

    if args.json_out:
        args.json_out.write_text(json.dumps(_results_to_json(results), indent=2))
        console.print(f"Wrote raw results to [cyan]{args.json_out}[/cyan]")

    raise SystemExit(0 if all_passed else 1)


if __name__ == "__main__":
    main()
