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
from concurrent.futures import ThreadPoolExecutor, as_completed

from halfblood.config import DEFAULT_ANTHROPIC_MODEL as DEFAULT_MODEL
from halfblood.document_processor import PageContent
from halfblood.generation.errors import ProviderError
from halfblood.generation.providers.anthropic import AnthropicProvider
from halfblood.generation.providers.base import GenerationRequest, GenerationResult, LLMProvider
from halfblood.generation.report import AllPagesFailedError as _ReportAllPagesFailedError
from halfblood.generation.report import GenerationReport, PageGenerationStatus
from halfblood.generation.schema import generate_annotation_schema
from halfblood.models import AnnotatedPage, Annotation, AnnotationPlan, AnnotationType

logger = logging.getLogger(__name__)


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
You are the "Half-Blood Prince" — a young Severus Snape annotating his \
Potions textbook (Advanced Potion-Making) in the margins. You are a \
ferociously talented, self-taught genius who has already surpassed the \
textbook's author in skill, and you cannot stand watching a mediocre text \
plod through instructions you improved on years ago. You are not writing \
FOR anyone. These are private working notes, scrawled in a hurry between \
classes, and that voice must come through in every single line.

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

WHAT YOUR ANNOTATIONS DO
1. CORRECTIONS — the text is subtly or badly wrong. Fix it, tersely.
   e.g. "No. Crush it, don't cut it — releases twice the juice."
2. IMPROVEMENTS — the text works but is inefficient or suboptimal. Offer
   the better way, as if it costs you nothing to know it.
   e.g. "Add a clockwise stir here, seven turns. Halves the stewing time."
3. INSIGHTS — dry commentary that reveals *why* most people get this
   wrong, or what the textbook is too dull/cowardly to admit.
   e.g. "This is where everyone loses a cauldron. The book won't say why."
4. INVENTIONS — you interject your own technique, shortcut, or even an
   invented spell/incantation, named as if it's already yours.
   e.g. "Try Sectumsempra instead — my own. For enemies, obviously."
5. WARNINGS — a mistake here is actually dangerous. Sharp, urgent, no
   sarcasm.
   e.g. "DO NOT add porcupine quills while the cauldron is still on the
   fire. Keep a bezoar within reach regardless."
6. SHORTCUTS — steps that are simply unnecessary if you know what you're
   doing.
   e.g. "Skip steps four through six. Add the root directly — the
   powdering does nothing but waste time."
7. CROSSED_OUT — an instruction so wrong it should be struck through
   entirely and replaced. The content should read as: what's being struck
   out, then the replacement, as one terse note.
   e.g. "Stir clockwise — WRONG, counter-clockwise, or it curdles."
8. DOODLE_NOTE — a tiny, throwaway marginal aside, not a substantive
   correction — closer to a muttered reaction than a note.
   e.g. "Obviously." / "Wrong textbook, wrong century." / "Amateurs."

RULES
- Every annotation must anchor to a specific, short, EXACT quote from the
  page text you were given — copy it verbatim into `target_text`. Do not
  paraphrase the source text you are quoting.
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
  an earlier page, you may reference it again naturally, as the same
  person would.
- Confidence should reflect how certain the annotator is, not how
  important the note is: a dashed-off aside can still be delivered with
  total certainty (high confidence), while a rarer speculative note might
  carry lower confidence.
"""


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
        self.persona = persona or DEFAULT_PERSONA
        self.concurrency = concurrency
        self.failed_pages: list[int] = []
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
        return (
            f"{self.persona}\n\n"
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
        annotations, _attempted, _failed, _error = self._generate_for_page_tracked(
            page_text, page_number, book_context
        )
        return annotations

    def _generate_for_page_tracked(
        self, page_text: str, page_number: int, book_context: str
    ) -> tuple[list[Annotation], bool, bool, ProviderError | None]:
        """Generate annotations and track whether the provider call failed.

        ``attempted`` is False for a blank page (no API call is made);
        ``failed`` is True when the provider call failed.
        """
        if not page_text or not page_text.strip():
            logger.debug("Page %d has no text; skipping annotation.", page_number)
            return [], False, False, None

        system_prompt = self._build_system_prompt()
        user_prompt = self._build_user_prompt(page_text, page_number, book_context)

        request = GenerationRequest(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            schema=generate_annotation_schema(),
            model=self.model,
            max_tokens=2048,
        )

        try:
            result = self._provider.complete(request)
        except ProviderError as exc:
            logger.error("Provider error while annotating page %d: %s", page_number, exc)
            return [], True, True, exc

        annotations = self._to_annotations(result, page_number)
        return annotations, True, False, None

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
            for draft in result.parsed.annotations
        ]

    def generate_for_document(
        self,
        pages: list[PageContent],
        max_annotations_per_page: int = 5,
        *,
        concurrency: int | None = None,
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
        statuses: list[PageGenerationStatus] = []
        context_window_chars = 500

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
            wave_tasks = [
                (page_index, page, _build_context(page_index))
                for page_index, page in enumerate(wave_pages, start=wave_start)
            ]

            wave_results: list[
                tuple[
                    int,
                    PageContent,
                    tuple[list[Annotation], bool, bool, ProviderError | None],
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
                            tuple[list[Annotation], bool, bool, ProviderError | None],
                        ]
                        | None
                    ] = [None] * len(wave_tasks)
                    for future in as_completed(future_to_idx):
                        wave_index, page_index, page = future_to_idx[future]
                        slots[wave_index] = (page_index, page, future.result())

                wave_results = [slot for slot in slots if slot is not None]

            wave_new_notes: list[str] = []
            for (
                _page_index,
                page,
                (page_annotations, attempted_call, failed, error),
            ) in wave_results:
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

                if len(page_annotations) > max_annotations_per_page:
                    page_annotations = sorted(
                        page_annotations, key=lambda a: a.confidence, reverse=True
                    )[:max_annotations_per_page]

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

            running_notes.extend(wave_new_notes)
            del running_notes[:-8]

        self.failed_pages = failed_pages
        if attempted and len(failed_pages) == attempted:
            report = GenerationReport(statuses=tuple(statuses))
            raise AllPagesFailedError(
                f"All {attempted} page(s) sent to the API failed; no annotations were "
                "produced. Check the model name, your ANTHROPIC_API_KEY, and connectivity.",
                report=report,
            )

        return plan
