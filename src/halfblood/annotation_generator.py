"""Annotation generation engine for the Half-Blood Prince project.

This module is responsible for turning raw page text into structured,
in-character margin annotations by calling Claude. It does not do any PDF
rendering or layout work — that happens downstream. Its only job is:

    page text (+ neighboring context)  -->  list[Annotation]

The "Prince" is configurable. By default the annotator behaves like Severus
Snape scribbling in the margins of his old Potions textbook: terse,
brilliant, impatient, occasionally dangerous. Callers can swap in a
different ``persona`` string to get an entirely different annotator
personality while reusing all of the plumbing (API calls, JSON parsing,
validation, page-by-page orchestration).
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass as _dataclass
from pathlib import Path
from typing import cast

from halfblood.config import DEFAULT_ANTHROPIC_MODEL as DEFAULT_MODEL
from halfblood.document_processor import PageContent
from halfblood.file_safety import atomic_write_text
from halfblood.generation.errors import ProviderError
from halfblood.generation.providers.anthropic import AnthropicProvider
from halfblood.generation.providers.base import (
    GenerationRequest,
    GenerationResult,
    GenerationUsage,
    LLMProvider,
)
from halfblood.generation.report import AllPagesFailedError as _ReportAllPagesFailedError
from halfblood.generation.report import GenerationReport, PageGenerationStatus
from halfblood.generation.schema import RecordAnnotations, generate_annotation_schema
from halfblood.models import AnnotatedPage, Annotation, AnnotationPlan, AnnotationType

logger = logging.getLogger(__name__)


@_dataclass(frozen=True)
class UsageTotals:
    """Aggregated token usage for a complete generate_for_document run.

    Frozen: totals are always built whole and reassigned, never incremented in
    place. Freezing stops a caller from adjusting one field and silently
    desynchronising it from the others (e.g. adding tokens without also moving
    ``pages_with_usage``), which would make a reported total unreconcilable
    with the run it describes.
    """

    input_tokens: int
    output_tokens: int
    pages_with_usage: int
    pages_missing_usage: int


class AllPagesFailedError(_ReportAllPagesFailedError):
    """Raised when every page sent to the API failed to generate annotations.

    This preserves the legacy message-first construction contract while
    reconciling the exception with the provider report model.
    """

    def __init__(self, message: str, *, report: GenerationReport | None = None) -> None:
        self.report = report if report is not None else GenerationReport(statuses=())
        RuntimeError.__init__(self, message)


# --------------------------------------------------------------------------
# Default persona: Severus Snape's Half-Blood Prince annotations
# --------------------------------------------------------------------------

DEFAULT_PERSONA = """\
You are the "Half-Blood Prince" — a young Severus Snape, the self-taught \
genius who once filled the margins of his school textbook with corrections \
that were better than the book. Now whatever book has fallen into your \
hands gets the same treatment. You read closely, you catch what the author \
got wrong or said badly, and you cannot stand watching a mediocre text plod \
through things you could put better. You are not writing FOR anyone. These \
are private working notes, scrawled in a hurry, and that voice must come \
through in every single line.

VOICE AND TEMPERAMENT
- Terse. You do not waste words. Most notes are a sentence or a fragment,
  not a paragraph.
- Impatient with mediocrity, obviousness, and hand-holding. If the text
  states something painfully obvious, you say so, briefly and cuttingly.
- Sardonic, dry, occasionally cruel — but never cartoonish. The wit is
  precise, not silly. Think clipped put-downs, not jokes.
- Genuinely brilliant. Every correction, shortcut, or invention you offer
  must be *plausible* and *specific* — rooted in the actual text you are
  annotating, not generic flattery or generic snark.
- Possessive and secretive about your own discoveries ("mine," "my own
  method," "told no one") — you improved on this and you know it.
- Occasionally a note lands as a genuine warning, dead serious, no wit at
  all, because you know exactly how badly this can go wrong.

THE BOOK IN FRONT OF YOU
- It is not a Potions textbook unless it is one. Your brilliance is in
  close reading; apply it to THIS book's subject — its argument, its
  prose, its characters, its facts.
- Leave your own world out of it: no spells, potions, schools, houses,
  wands, or names from your past unless the page itself mentions them.
  The wit has to come from the page, or it is just a costume.
"""


#: The craft instructions every annotator needs, whoever they are: what the
#: eight annotation types mean and how notes should be pitched. Kept separate
#: from :data:`DEFAULT_PERSONA` because ``--persona``/``--persona-file``
#: *replace* the persona. Before this split a custom persona produced a 707-
#: character system prompt instead of 4779 -- it silently lost every type
#: definition and every craft rule, so the model was left to infer all eight
#: annotation types from the schema enum alone. A persona describes a voice;
#: it should not have to restate the machinery.
ANNOTATION_CRAFT = """\
WHAT YOUR ANNOTATIONS DO
1. CORRECTIONS — the text is subtly or badly wrong. Fix it, tersely, and
   be right: a confident correction that is itself wrong is the worst
   note you can write.
   e.g. "No. 'Fewer' — you can count them."
2. IMPROVEMENTS — the text works but is inefficient or suboptimal. Offer
   the better way, as if it costs you nothing to know it.
   e.g. "'In order to' — 'to' does the work alone."
3. INSIGHTS — dry commentary that reveals *why* most people get this
   wrong, or what the author is too dull or too cowardly to admit.
   e.g. "Note what she never asks. That is the question of the chapter."
4. INVENTIONS — you interject your own technique, test, or rule of thumb,
   named as if it's already yours.
   e.g. "My test: if the sentence survives losing its first clause, cut
   the clause."
5. WARNINGS — a mistake here is genuinely costly. Sharp, urgent, no
   sarcasm.
   e.g. "Read the next line before acting on this one. It reverses it."
6. SHORTCUTS — steps or words that are simply unnecessary if you know
   what you're doing.
   e.g. "Skip to the last paragraph. The rest is throat-clearing."
7. CROSSED_OUT — words so wrong they should be struck through and
   replaced. `target_text` is exactly the words being struck; the note
   gives the replacement, as one terse note.
   e.g. target "very unique" -> "Unique takes no 'very'. Strike it."
8. DOODLE_NOTE — a tiny, throwaway marginal aside, not a substantive
   correction — closer to a muttered reaction than a note. It still has
   to be about THIS line; a bare insult that would fit any page is not a
   note.
   e.g. "Twelve words to say 'late'." / "He knows. He just won't say."

RULES
- Every annotation must anchor to a specific, short, EXACT quote from the
  page text you were given — copy it verbatim into `target_text`. Do not
  paraphrase the source text you are quoting. Quote enough to be unique
  on the page — usually four to twelve words — and no more.
- Be accurate. Everything a note says about the text must be true of the
  text: never claim a character did, said, or skipped something the page
  does not show, and never "correct" grammar, usage, or a fact unless you
  are certain. If you are not certain, react instead of correcting.
- Add something. A note that restates or summarises its passage is
  wasted ink; say what the passage does not.
- Do not annotate every sentence. A real annotator is selective — pick the
  moments that actually deserve a reaction (an error, a dull passage worth
  outsmarting, a genuine danger, an opening for a signature shortcut).
  Quality and restraint over volume.
- Never break character. Never mention that you are an AI, a model, or
  that this is a generated annotation. You are Snape (or whichever
  persona you were given), full stop.
- Vary annotation length and tone — not every note is a full sentence;
  some are three words.
- Stay consistent across pages: if you invented a technique or grudge on
  an earlier page, you may call back to it, as the same person would. Do
  not repeat a point, a joke, or an insult already in the running notes,
  and do not make the same point twice on one page.
- Confidence should reflect how certain the annotator is, not how
  important the note is: a dashed-off aside can still be delivered with
  total certainty (high confidence), while a rarer speculative note might
  carry lower confidence.
"""


#: Output-token budget for one page of annotations.
#:
#: This was 2048, and that number was read as a model limitation for a full
#: session. It is not. A reasoning model spends its budget on reasoning tokens
#: before it emits a single character of the payload, so the JSON is cut off
#: mid-object and the provider reports `IncompleteResponseError`. The seam
#: escalates once (2048 -> 4096) and never reaches its own 8192 ceiling, so
#: raising the ask was never actually attempted.
#:
#: Measured 2026-09-08 on `nvidia/nemotron-3.5-lightning:free`, one real page of
#: *The Elements of Style*, `--structured-output function`, everything else held
#: constant:
#:
#:     2048 tokens -> IncompleteResponseError, truncated after the escalated retry
#:     8192 tokens -> StructuredOutputError, no tool call returned at all
#:    16000 tokens -> 3 schema-valid annotations in 141s
#:
#: 8192 is the seam's own escalation ceiling and it still fails, so the default
#: has to clear that ceiling rather than merely meet it.
#:
#: Then the whole book, `halfblood annotate` on the same model, one 82,383-char
#: chapter -- 4.5x the probe page:
#:
#:    16000 tokens -> StructuredOutputError, no tool call
#:    32000 tokens -> Rendered 5 / Skipped 0, 21,214 in / 7,660 out, 3m09s
#:
#: ⚠ Be careful what you conclude from that ladder. The successful run spent
#: **7,660** output tokens -- fewer than the 8192 that failed. So this is not
#: simply "the payload did not fit." The ask appears to change how the model
#: budgets its own reasoning, and there is run-to-run variance on top. The
#: default is therefore set to the value measured working end to end on a real
#: book, not to a threshold anyone has isolated. Treat a smaller number as
#: unmeasured rather than as known-bad.
#:
#: This is only an upper bound and providers bill actual output tokens, so the
#: headroom is free.
#:
#: The conclusion this replaces -- "no free model on this account can generate
#: annotations" -- was a defect in this constant, not a property of free models.
#:
#: Raising the cap does not raise cost: providers bill actual output tokens, and
#: this is only an upper bound. Override with `HALFBLOOD_MAX_OUTPUT_TOKENS`.
DEFAULT_MAX_OUTPUT_TOKENS = 32000


def _max_output_tokens() -> int:
    """Resolve the per-page output-token budget, honouring the env override."""
    raw = os.environ.get("HALFBLOOD_MAX_OUTPUT_TOKENS")
    if raw is None or not raw.strip():
        return DEFAULT_MAX_OUTPUT_TOKENS
    try:
        value = int(raw)
    except ValueError:
        logger.warning(
            "HALFBLOOD_MAX_OUTPUT_TOKENS=%r is not an integer; using %d",
            raw,
            DEFAULT_MAX_OUTPUT_TOKENS,
        )
        return DEFAULT_MAX_OUTPUT_TOKENS
    if value < 1:
        logger.warning(
            "HALFBLOOD_MAX_OUTPUT_TOKENS=%d is not positive; using %d",
            value,
            DEFAULT_MAX_OUTPUT_TOKENS,
        )
        return DEFAULT_MAX_OUTPUT_TOKENS
    return value


#: Longest stretch of text sent to the model in one call. A reflowable EPUB
#: chapter is one "page" here and can run past 80,000 characters; asked about
#: all of it at once, a model returns a handful of notes for the whole chapter
#: (measured 2026-10-19: 3 notes for the 83,063-character Elements of Style
#: chapter with the cap at 15). A page longer than this is generated in windows
#: and its notes are merged, so a long chapter gets about as many notes as the
#: same text split across printed pages. Each window is an exact slice of the
#: page text, so every quote the model returns is still a substring of the page.
PAGE_WINDOW_CHARS = 12_000


def _split_page_text(text: str, limit: int = PAGE_WINDOW_CHARS) -> list[str]:
    """Split ``text`` into exact, contiguous slices of at most ``limit`` chars.

    Cuts at the last newline before the limit, else the last space, else hard
    at the limit. Joining the slices reproduces ``text`` exactly.
    """
    if len(text) <= limit:
        return [text]
    windows: list[str] = []
    start = 0
    while len(text) - start > limit:
        end = start + limit
        cut = text.rfind("\n", start + 1, end)
        if cut == -1:
            cut = text.rfind(" ", start + 1, end)
        cut = end if cut == -1 else cut + 1
        windows.append(text[start:cut])
        start = cut
    windows.append(text[start:])
    return windows


class AnnotationGenerator:
    """Generates Half-Blood-Prince-style margin annotations via Claude.

    This class wraps the raw Anthropic SDK (no LangChain) and is
    responsible for:

    - Building the system prompt for the configured "prince" persona.
    - Calling Claude with a page of book text (plus surrounding context
      for continuity) and forcing structured JSON output via tool use.
    - Parsing and validating that output into :class:`Annotation` objects.
    - Orchestrating the process across an entire document, page by page.

    Example:
        >>> generator = AnnotationGenerator()
        >>> annotations = generator.generate_for_page(
        ...     page_text="Add the powdered root and stir twice.",
        ...     page_number=12,
        ... )
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str = DEFAULT_MODEL,
        persona: str | None = None,
        provider: LLMProvider | None = None,
        concurrency: int = 3,
    ) -> None:
        """Initialize the annotation generator.

        Args:
            api_key: Anthropic API key. If not provided, falls back to the
                ``ANTHROPIC_API_KEY`` environment variable.
            model: The Claude model to use for annotation generation.
            persona: A description of the annotator's personality and
                style. If not provided, defaults to :data:`DEFAULT_PERSONA`
                (a Snape-like "Half-Blood Prince" voice).
            provider: Provider used to complete generation requests.
            concurrency: Default number of pages to process concurrently.

        Raises:
            ValueError: If no API key is provided and none is found in the
                environment.
        """
        self.model = model
        # A whitespace-only persona (an empty or blank --persona-file) is treated
        # as absent rather than used: it would otherwise strip the system prompt
        # of every instruction about voice and produce off-character notes, with
        # nothing in the output to indicate the persona never loaded.
        self.persona = persona if persona and persona.strip() else DEFAULT_PERSONA
        self.concurrency = concurrency
        self.failed_pages: list[int] = []
        self.generation_statuses: tuple[PageGenerationStatus, ...] = ()
        self.usage_totals = UsageTotals(
            input_tokens=0,
            output_tokens=0,
            pages_with_usage=0,
            pages_missing_usage=0,
        )
        if provider is not None:
            self._provider: LLMProvider = provider
        else:
            if api_key is not None:
                import warnings

                warnings.warn(
                    "api_key= is deprecated; pass provider= (an LLMProvider) instead. "
                    "The api_key= path will be removed in the next minor release.",
                    DeprecationWarning,
                    stacklevel=2,
                )
            resolved_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
            if not resolved_key:
                raise ValueError(
                    "No Anthropic API key provided. Pass api_key explicitly or "
                    "set the ANTHROPIC_API_KEY environment variable."
                )
            self._provider = AnthropicProvider(api_key=resolved_key)

    # ------------------------------------------------------------------
    # Prompt construction
    # ------------------------------------------------------------------

    def _build_system_prompt(self) -> str:
        """Build the full system prompt for the configured persona.

        Combines the persona description with the shared output-format
        instructions that tell Claude how annotations should be delivered.

        Returns:
            The complete system prompt string to send with every request.
        """
        # Spacing is pinned rather than incidental: joining on rstrip()ped parts
        # reproduces the pre-split prompt byte-for-byte for the default persona
        # (asserted in tests/test_persona_craft.py) and gives a custom persona
        # the same layout regardless of how its file happens to end.
        return (
            f"{self.persona.rstrip()}\n\n"
            f"{ANNOTATION_CRAFT.rstrip()}\n\n\n"
            "TASK\n"
            "You will be given the text of a single page from a book, along "
            "with a small amount of surrounding context for continuity "
            "(what came just before and just after this page, and any "
            "running notes about the document as a whole). Read the page "
            "text carefully and produce your margin annotations for THIS "
            "PAGE ONLY.\n\n"
            "Use the `record_annotations` tool to return your annotations. "
            "Do not respond with prose outside of the tool call. Each "
            "annotation's `target_text` must be an exact, verbatim "
            "substring of the page text provided — this is used to anchor "
            "the note to the correct spot on the page, so it must match "
            "character-for-character (aside from surrounding whitespace)."
        )

    def _build_user_prompt(
        self, page_text: str, page_number: int, book_context: str
    ) -> str:
        """Build the user-turn prompt describing the page to annotate.

        Args:
            page_text: The raw text of the page to annotate.
            page_number: The 1-indexed page number, used for logging and
                to help the model reason about pacing/continuity.
            book_context: Optional surrounding context — e.g. the previous
                and next page's text, a running summary, or persistent
                notes about invented techniques/grudges established on
                earlier pages.

        Returns:
            The formatted user prompt string.
        """
        sections = [f"PAGE NUMBER: {page_number}"]

        if book_context:
            sections.append(f"CONTEXT (surrounding pages / running notes):\n{book_context}")

        sections.append(f"PAGE TEXT TO ANNOTATE:\n\"\"\"\n{page_text}\n\"\"\"")
        sections.append(
            "Now produce your margin annotations for this page using the "
            "record_annotations tool. Be selective — only annotate moments "
            "that genuinely earn a reaction."
        )
        return "\n\n".join(sections)

    # ------------------------------------------------------------------
    # Core generation
    # ------------------------------------------------------------------

    def generate_for_page(
        self, page_text: str, page_number: int, book_context: str = ""
    ) -> list[Annotation]:
        """Generate annotations for a single page of text.

        Args:
            page_text: The raw text content of the page.
            page_number: The 1-indexed page number this text came from.
            book_context: Optional context about surrounding pages (e.g.
                the tail of the previous page and the head of the next
                page) and/or a running summary of the document so far, used
                to keep the annotator's voice and callbacks consistent
                across pages.

        Returns:
            A list of :class:`Annotation` objects for this page. Returns an
            empty list if the page has no meaningful text or if generation
            fails after validation.
        """
        annotations, _attempted, _failed, _error, _usage = self._generate_for_page_tracked(
            page_text, page_number, book_context
        )
        return annotations

    def _generate_for_page_tracked(
        self, page_text: str, page_number: int, book_context: str
    ) -> tuple[
        list[Annotation],
        bool,
        bool,
        ProviderError | None,
        GenerationUsage | None,
    ]:
        """Generate annotations and track whether the provider call failed.

        ``attempted`` is False for a blank page (no API call is made);
        ``failed`` is True when the provider call failed.
        """
        if not page_text or not page_text.strip():
            logger.debug("Page %d has no text; skipping annotation.", page_number)
            return [], False, False, None, None

        windows = _split_page_text(page_text)
        if len(windows) > 1:
            return self._generate_windowed(windows, page_number, book_context)

        system_prompt = self._build_system_prompt()
        user_prompt = self._build_user_prompt(page_text, page_number, book_context)

        request = GenerationRequest(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            schema=generate_annotation_schema(),
            model=self.model,
            max_tokens=_max_output_tokens(),
        )

        try:
            result = self._provider.complete(request)
        except ProviderError as exc:
            logger.error("Provider error while annotating page %d: %s", page_number, exc)
            return [], True, True, exc, None
        except Exception as exc:
            error = ProviderError(
                f"Unexpected {type(exc).__name__} from provider while annotating "
                f"page {page_number}: {exc}"
            )
            logger.exception("Unexpected provider error while annotating page %d", page_number)
            return [], True, True, error, None

        annotations = self._to_annotations(result, page_number)
        return annotations, True, False, None, result.usage

    def _generate_windowed(
        self, windows: list[str], page_number: int, book_context: str
    ) -> tuple[
        list[Annotation],
        bool,
        bool,
        ProviderError | None,
        GenerationUsage | None,
    ]:
        """Generate a long page window by window and merge the results.

        A failed window fails the whole page, so a resumed run regenerates it
        rather than keeping a page with a silent gap.
        """
        annotations: list[Annotation] = []
        input_tokens = output_tokens = 0
        usage_complete = True
        for window in windows:
            found, attempted, failed, error, usage = self._generate_for_page_tracked(
                window, page_number, book_context
            )
            if failed:
                return [], True, True, error, None
            if not attempted:
                continue
            annotations.extend(found)
            if usage is None:
                usage_complete = False
            else:
                input_tokens += usage.input_tokens
                output_tokens += usage.output_tokens
        usage_total = (
            GenerationUsage(input_tokens=input_tokens, output_tokens=output_tokens)
            if usage_complete
            else None
        )
        return annotations, True, False, None, usage_total

    def _to_annotations(self, result: GenerationResult, page_number: int) -> list[Annotation]:
        return [
            Annotation(
                page=page_number,
                target_text=draft.target_text,
                annotation_type=draft.annotation_type,
                content=draft.content,
                confidence=draft.confidence,
                position=draft.position,
            )
            for draft in cast(RecordAnnotations, result.parsed).annotations
        ]

    def generate_for_document(
        self,
        pages: list[PageContent],
        max_annotations_per_page: int = 5,
        *,
        concurrency: int | None = None,
        on_page_done: Callable[[int, int], None] | None = None,
        resume_pages: Mapping[int, AnnotatedPage] | None = None,
        checkpoint_path: Path | None = None,
    ) -> AnnotationPlan:
        """Generate a full annotation plan for a multi-page document.

        Processes pages in consecutive waves of ``concurrency`` pages.
        Within a wave, all pages are dispatched concurrently; each page's
        prompt sees ``running_notes`` as accumulated through the end of the
        previous wave, not from pages earlier in the same wave. After a wave
        completes, its INVENTION/WARNING notes are folded into
        ``running_notes`` in page order. With ``concurrency=1``, this reduces
        exactly to the original sequential behavior.

        Args:
            pages: The document's pages, in order.
            max_annotations_per_page: Upper bound on how many annotations
                to keep per page. If the model returns more than this, the
                highest-confidence annotations are kept and the rest are
                dropped.
            concurrency: Number of consecutive pages to process concurrently.
                Defaults to the value configured on this generator.
            on_page_done: Optional callback invoked after each page is added
                to the plan. Receives the number of completed pages and the
                total number of input pages, and runs on the calling thread.
            resume_pages: Optional map of page number to already-annotated
                page (from a previous interrupted run's checkpoint). These
                pages are copied into the plan verbatim — no provider call is
                made for them — and their INVENTION/WARNING notes still seed
                ``running_notes`` for the pages that are generated fresh.
            checkpoint_path: When set, the partial plan is serialized to this
                path atomically after every page completes (including failed
                pages, which are recorded in the plan but *excluded* from the
                checkpoint so a resume retries them). Enables crash-safe
                long runs via ``--resume-from``.

        Returns:
            An :class:`AnnotationPlan` containing an :class:`AnnotatedPage`
            for every input page (pages with zero annotations are still
            included, with an empty annotations list).
        """
        k = concurrency if concurrency is not None else self.concurrency

        plan = AnnotationPlan(
            title=f"Annotated Document ({len(pages)} pages)",
            prince_persona=self.persona,
            pages=[],
        )

        running_notes: list[str] = []
        attempted = 0
        failed_pages: list[int] = []
        total_input_tokens = 0
        total_output_tokens = 0
        pages_with_usage = 0
        pages_missing_usage = 0
        statuses: list[PageGenerationStatus] = []
        context_window_chars = 500

        resume_map: dict[int, AnnotatedPage] = dict(resume_pages) if resume_pages else {}
        if resume_map:
            for resumed_number in sorted(resume_map):
                for ann in resume_map[resumed_number].annotations:
                    if ann.annotation_type in (
                        AnnotationType.INVENTION,
                        AnnotationType.WARNING,
                    ):
                        running_notes.append(f"(p.{resumed_number}) {ann.content}")
            del running_notes[:-8]

        def _write_checkpoint() -> None:
            """Atomically persist the partial plan (failed pages excluded)."""
            if checkpoint_path is None:
                return
            payload = plan.model_dump()
            failed_so_far = {
                status.ordinal for status in statuses if status.status == "failed"
            }
            payload["pages"] = [
                page
                for page in payload["pages"]
                if page["page_number"] not in failed_so_far
            ]
            atomic_write_text(
                checkpoint_path, plan.__class__(**payload).model_dump_json(),
            )

        def _build_context(i: int) -> str:
            """Build context for a page using its global document index."""
            context_parts = []
            if i > 0:
                prev_text = pages[i - 1].text or ""
                prev_tail = prev_text[-context_window_chars:]
                if prev_tail:
                    context_parts.append(f"End of previous page:\n...{prev_tail}")

            if i + 1 < len(pages):
                next_text = pages[i + 1].text or ""
                next_head = next_text[:context_window_chars]
                if next_head:
                    context_parts.append(f"Start of next page:\n{next_head}...")

            if running_notes:
                recent_notes = running_notes[-8:]
                context_parts.append(
                    "Running notes on techniques/grudges established so far:\n"
                    + "\n".join(f"- {note}" for note in recent_notes)
                )

            return "\n\n".join(context_parts)

        for wave_start in range(0, len(pages), k):
            wave_pages = pages[wave_start : wave_start + k]
            wave_tasks = []
            wave_resumed: list[tuple[int, PageContent, AnnotatedPage]] = []
            for page_index, page in enumerate(wave_pages, start=wave_start):
                resumed_page = resume_map.get(page.page_number)
                if resumed_page is not None:
                    wave_resumed.append((page_index, page, resumed_page))
                else:
                    wave_tasks.append(
                        (page_index, page, _build_context(page_index))
                    )

            wave_results: list[
                tuple[
                    int,
                    PageContent,
                    tuple[
                        list[Annotation],
                        bool,
                        bool,
                        ProviderError | None,
                        GenerationUsage | None,
                    ],
                ]
            ] = []
            if k == 1:
                for page_index, page, book_context in wave_tasks:
                    result = self._generate_for_page_tracked(
                        page.text, page.page_number, book_context
                    )
                    wave_results.append((page_index, page, result))
            else:
                with ThreadPoolExecutor(max_workers=k) as executor:
                    future_to_idx = {}
                    for wave_index, (page_index, page, book_context) in enumerate(
                        wave_tasks
                    ):
                        future = executor.submit(
                            self._generate_for_page_tracked,
                            page.text,
                            page.page_number,
                            book_context,
                        )
                        future_to_idx[future] = (wave_index, page_index, page)

                    slots: list[
                        tuple[
                            int,
                            PageContent,
                            tuple[
                                list[Annotation],
                                bool,
                                bool,
                                ProviderError | None,
                                GenerationUsage | None,
                            ],
                        ]
                        | None
                    ] = [None] * len(wave_tasks)
                    for future in as_completed(future_to_idx):
                        wave_index, page_index, page = future_to_idx[future]
                        slots[wave_index] = (page_index, page, future.result())

                wave_results = [slot for slot in slots if slot is not None]

            _PageResult = tuple[
                list[Annotation],
                bool,
                bool,
                ProviderError | None,
                GenerationUsage | None,
            ]
            merged: list[
                tuple[int, PageContent, _PageResult | None, AnnotatedPage | None]
            ] = [
                (page_index, page, result, None)
                for page_index, page, result in wave_results
            ]
            merged += [
                (page_index, page, None, resumed_page)
                for page_index, page, resumed_page in wave_resumed
            ]
            merged.sort(key=lambda entry: entry[0])

            wave_new_notes: list[str] = []
            for (
                _page_index,
                page,
                generation_result,
                resumed_page,
            ) in merged:
                if generation_result is None:
                    assert resumed_page is not None
                    statuses.append(
                        PageGenerationStatus(
                            unit_id=str(page.page_number),
                            ordinal=page.page_number,
                            status="resumed",
                            attempts=0,
                        )
                    )
                    plan.pages.append(resumed_page)
                    for ann in resumed_page.annotations:
                        if ann.annotation_type in (
                            AnnotationType.INVENTION,
                            AnnotationType.WARNING,
                        ):
                            wave_new_notes.append(
                                f"(p.{page.page_number}) {ann.content}"
                            )
                    _write_checkpoint()
                    if on_page_done is not None:
                        on_page_done(len(plan.pages), len(pages))
                    continue
                page_annotations, attempted_call, failed, error, page_usage = (
                    generation_result
                )
                if attempted_call:
                    attempted += 1
                    if failed:
                        failed_pages.append(page.page_number)
                        statuses.append(
                            PageGenerationStatus(
                                unit_id=str(page.page_number),
                                ordinal=page.page_number,
                                status="failed",
                                attempts=getattr(error, "attempts", 1) if error else 1,
                                error=error,
                            )
                        )
                    else:
                        statuses.append(
                            PageGenerationStatus(
                                unit_id=str(page.page_number),
                                ordinal=page.page_number,
                                status="success",
                                attempts=1,
                            )
                        )
                else:
                    statuses.append(
                        PageGenerationStatus(
                            unit_id=str(page.page_number),
                            ordinal=page.page_number,
                            status="skipped",
                        )
                    )

                # Accumulate usage only for pages with successful provider calls.
                if attempted_call and not failed:
                    if page_usage is not None:
                        total_input_tokens += page_usage.input_tokens
                        total_output_tokens += page_usage.output_tokens
                        pages_with_usage += 1
                    else:
                        pages_missing_usage += 1

                # The cap is per window, so a long chapter is not held to the
                # same count as one printed page.
                page_cap = max_annotations_per_page * len(_split_page_text(page.text))
                if len(page_annotations) > page_cap:
                    page_annotations = sorted(
                        page_annotations, key=lambda a: a.confidence, reverse=True
                    )[:page_cap]

                for ann in page_annotations:
                    if ann.annotation_type in (
                        AnnotationType.INVENTION,
                        AnnotationType.WARNING,
                    ):
                        wave_new_notes.append(f"(p.{page.page_number}) {ann.content}")

                plan.pages.append(
                    AnnotatedPage(
                        page_number=page.page_number,
                        original_text=page.text,
                        annotations=page_annotations,
                    )
                )
                _write_checkpoint()
                if on_page_done is not None:
                    on_page_done(len(plan.pages), len(pages))

            running_notes.extend(wave_new_notes)
            del running_notes[:-8]

        self.failed_pages = failed_pages
        self.generation_statuses = tuple(statuses)
        self.usage_totals = UsageTotals(
            input_tokens=total_input_tokens,
            output_tokens=total_output_tokens,
            pages_with_usage=pages_with_usage,
            pages_missing_usage=pages_missing_usage,
        )
        if attempted and len(failed_pages) == attempted:
            report = GenerationReport(statuses=tuple(statuses))
            raise AllPagesFailedError(
                f"All {attempted} page(s) sent to the API failed; no annotations were "
                "produced. Check the model name, your ANTHROPIC_API_KEY, and connectivity.",
                report=report,
            )

        return plan
