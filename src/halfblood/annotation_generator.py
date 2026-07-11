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

import json
import logging
import os
from typing import Any

import anthropic

from halfblood.document_processor import PageContent
from halfblood.models import AnnotatedPage, Annotation, AnnotationPlan, AnnotationType

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-sonnet-5"


class AllPagesFailedError(RuntimeError):
    """Raised when every page sent to the API failed to generate annotations.

    Distinguishes a systemic failure (retired model, bad key, no network)
    from a document that legitimately produced zero annotations.
    """


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


# --------------------------------------------------------------------------
# Tool schema used to force structured output from Claude
# --------------------------------------------------------------------------

_ANNOTATION_TOOL_NAME = "record_annotations"

_ANNOTATION_TOOL_SCHEMA: anthropic.types.ToolParam = {
    "name": _ANNOTATION_TOOL_NAME,
    "description": (
        "Record the margin annotations produced for this page. Call this "
        "exactly once with the complete list of annotations for the page."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "annotations": {
                "type": "array",
                "description": "The margin annotations for this page, in reading order.",
                "items": {
                    "type": "object",
                    "properties": {
                        "target_text": {
                            "type": "string",
                            "description": (
                                "The exact, verbatim passage from the page text "
                                "that this annotation is attached to."
                            ),
                        },
                        "annotation_type": {
                            "type": "string",
                            "enum": [t.value for t in AnnotationType],
                            "description": "The category of this annotation.",
                        },
                        "content": {
                            "type": "string",
                            "description": "The handwritten margin note itself, in character.",
                        },
                        "confidence": {
                            "type": "number",
                            "minimum": 0.0,
                            "maximum": 1.0,
                            "description": "How certain the annotator is (0.0-1.0).",
                        },
                        "position": {
                            "type": "string",
                            "enum": ["margin_right", "margin_left", "inline", "between_lines"],
                            "description": "Where the note should be placed relative to the text.",
                        },
                    },
                    "required": ["target_text", "annotation_type", "content"],
                },
            }
        },
        "required": ["annotations"],
    },
}

_ANNOTATION_TOOL_CHOICE: anthropic.types.ToolChoiceToolParam = {
    "type": "tool",
    "name": _ANNOTATION_TOOL_NAME,
}


class _MalformedResponseError(RuntimeError):
    """Signal that an Anthropic Message cannot be treated as a page success."""


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
    ) -> None:
        """Initialize the annotation generator.

        Args:
            api_key: Anthropic API key. If not provided, falls back to the
                ``ANTHROPIC_API_KEY`` environment variable.
            model: The Claude model to use for annotation generation.
            persona: A description of the annotator's personality and
                style. If not provided, defaults to :data:`DEFAULT_PERSONA`
                (a Snape-like "Half-Blood Prince" voice).

        Raises:
            ValueError: If no API key is provided and none is found in the
                environment.
        """
        resolved_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not resolved_key:
            raise ValueError(
                "No Anthropic API key provided. Pass api_key explicitly or "
                "set the ANTHROPIC_API_KEY environment variable."
            )

        self.client = anthropic.Anthropic(api_key=resolved_key)
        self.model = model
        self.persona = persona or DEFAULT_PERSONA
        self.failed_pages: list[int] = []

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
        annotations, _attempted, _failed = self._generate_for_page_tracked(
            page_text, page_number, book_context
        )
        return annotations

    def _generate_for_page_tracked(
        self, page_text: str, page_number: int, book_context: str
    ) -> tuple[list[Annotation], bool, bool]:
        """Generate annotations, reporting (annotations, attempted, failed).

        ``attempted`` is False for a blank page (no API call is made);
        ``failed`` is True when the API call failed or returned an unusable Message.
        """
        if not page_text or not page_text.strip():
            logger.debug("Page %d has no text; skipping annotation.", page_number)
            return [], False, False

        system_prompt = self._build_system_prompt()
        user_prompt = self._build_user_prompt(page_text, page_number, book_context)

        tools: list[anthropic.types.ToolParam] = [_ANNOTATION_TOOL_SCHEMA]
        messages: list[anthropic.types.MessageParam] = [
            {"role": "user", "content": user_prompt}
        ]

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=2048,
                system=system_prompt,
                tools=tools,
                tool_choice=_ANNOTATION_TOOL_CHOICE,
                messages=messages,
            )
        except anthropic.APIError as exc:
            logger.error("Anthropic API error while annotating page %d: %s", page_number, exc)
            return [], True, True

        try:
            annotations = self._parse_response(response, page_number, page_text=page_text)
        except _MalformedResponseError as exc:
            logger.error("Malformed Anthropic response for page %d: %s", page_number, exc)
            return [], True, True

        return annotations, True, False

    def generate_for_document(
        self, pages: list[PageContent], max_annotations_per_page: int = 5
    ) -> AnnotationPlan:
        """Generate a full annotation plan for a multi-page document.

        Processes pages in order, feeding each call a window of context
        (the tail of the previous page and the head of the next page) so
        that the annotator's voice, invented techniques, and running
        grudges stay consistent across the document. After each page, the
        page's own annotations are folded into a short rolling summary
        that is passed forward as additional context for later pages.

        Args:
            pages: The document's pages, in order.
            max_annotations_per_page: Upper bound on how many annotations
                to keep per page. If the model returns more than this, the
                highest-confidence annotations are kept and the rest are
                dropped.

        Returns:
            An :class:`AnnotationPlan` containing an :class:`AnnotatedPage`
            for every input page (pages with zero annotations are still
            included, with an empty annotations list).
        """
        plan = AnnotationPlan(
            title=f"Annotated Document ({len(pages)} pages)",
            prince_persona=self.persona,
            pages=[],
        )

        running_notes: list[str] = []
        attempted = 0
        failed_pages: list[int] = []
        context_window_chars = 500

        for i, page in enumerate(pages):
            prev_tail = ""
            next_head = ""

            if i > 0:
                prev_text = pages[i - 1].text or ""
                prev_tail = prev_text[-context_window_chars:]

            if i + 1 < len(pages):
                next_text = pages[i + 1].text or ""
                next_head = next_text[:context_window_chars]

            context_parts = []
            if prev_tail:
                context_parts.append(f"End of previous page:\n...{prev_tail}")
            if next_head:
                context_parts.append(f"Start of next page:\n{next_head}...")
            if running_notes:
                recent_notes = running_notes[-8:]
                context_parts.append(
                    "Running notes on techniques/grudges established so far:\n"
                    + "\n".join(f"- {note}" for note in recent_notes)
                )

            book_context = "\n\n".join(context_parts)

            annotations, attempted_call, failed = self._generate_for_page_tracked(
                page.text, page.page_number, book_context
            )
            if attempted_call:
                attempted += 1
                if failed:
                    failed_pages.append(page.page_number)

            if len(annotations) > max_annotations_per_page:
                annotations = sorted(
                    annotations, key=lambda a: a.confidence, reverse=True
                )[:max_annotations_per_page]

            for ann in annotations:
                if ann.annotation_type in (AnnotationType.INVENTION, AnnotationType.WARNING):
                    running_notes.append(f"(p.{page.page_number}) {ann.content}")

            plan.pages.append(
                AnnotatedPage(
                    page_number=page.page_number,
                    original_text=page.text,
                    annotations=annotations,
                )
            )

        self.failed_pages = failed_pages
        if attempted and len(failed_pages) == attempted:
            raise AllPagesFailedError(
                f"All {attempted} page(s) sent to the API failed; no annotations were "
                "produced. Check the model name, your ANTHROPIC_API_KEY, and connectivity."
            )

        return plan

    # ------------------------------------------------------------------
    # Response parsing
    # ------------------------------------------------------------------

    def _parse_response(
        self,
        response_text: anthropic.types.Message | str,
        page_number: int,
        page_text: str = "",
    ) -> list[Annotation]:
        """Parse a Claude response into a list of validated annotations.

        Accepts either a raw ``anthropic.types.Message`` object (the
        typical case, when called from :meth:`generate_for_page`) or a
        plain JSON string (useful for testing or if a caller has already
        extracted the tool input as text). In the ``Message`` case, this
        looks for the ``record_annotations`` tool_use block; in the string
        case, it expects a JSON object with an ``annotations`` key, or a
        bare JSON array of annotation objects.

        Any individual annotation that fails Pydantic validation is
        skipped and logged rather than aborting the whole page.

        Args:
            response_text: The Claude API response, or a raw JSON string.
            page_number: The page number to stamp onto each annotation.
            page_text: The original page text, used to verify that each
                annotation's ``target_text`` actually appears on the page.
                If empty, this check is skipped.

        Returns:
            A list of validated :class:`Annotation` objects.
        """
        raw_items = self._extract_raw_annotations(response_text, page_number)

        annotations: list[Annotation] = []
        for item in raw_items:
            if not isinstance(item, dict):
                logger.warning(
                    "Skipping non-object annotation entry on page %d: %r",
                    page_number,
                    item,
                )
                continue

            target_text = item.get("target_text", "")
            if page_text and target_text and target_text not in page_text:
                logger.debug(
                    "Annotation target_text not found verbatim on page %d; "
                    "keeping anyway (model may have normalized whitespace): %r",
                    page_number,
                    target_text,
                )

            try:
                annotation = Annotation(
                    page=page_number,
                    target_text=target_text,
                    annotation_type=item.get("annotation_type", AnnotationType.DOODLE_NOTE),
                    content=item.get("content", ""),
                    confidence=item.get("confidence", 0.8),
                    position=item.get("position", "margin_right"),
                )
            except Exception as exc:  # pydantic.ValidationError, etc.
                logger.warning(
                    "Dropping invalid annotation on page %d: %s (raw=%r)",
                    page_number,
                    exc,
                    item,
                )
                continue

            annotations.append(annotation)

        return annotations

    @staticmethod
    def _extract_raw_annotations(
        response: anthropic.types.Message | str, page_number: int
    ) -> list[dict[str, Any]]:
        """Extract the raw annotation dicts from a Claude response.

        Handles the ``Message`` (tool_use) case and the plain-string (JSON)
        fallback case described in :meth:`_parse_response`.

        Args:
            response: The Claude API response or a raw JSON string.
            page_number: Used only for log messages.

        Returns:
            A list of raw annotation dicts (unvalidated). Empty list if
            nothing usable was found.
        """
        # Case 1: raw anthropic.types.Message — look for the tool_use block.
        if hasattr(response, "content"):
            if getattr(response, "stop_reason", None) == "max_tokens":
                raise _MalformedResponseError("response was truncated at max_tokens")

            content = response.content
            matching_inputs: list[object] = []
            for block in content:
                if isinstance(block, anthropic.types.ToolUseBlock):
                    if block.name == _ANNOTATION_TOOL_NAME:
                        matching_inputs.append(block.input)
                    continue

                # Test doubles and compatibility callers may provide SDK-shaped,
                # duck-typed blocks rather than Pydantic SDK model instances.
                if (
                    getattr(block, "type", None) == "tool_use"
                    and getattr(block, "name", None) == _ANNOTATION_TOOL_NAME
                ):
                    matching_inputs.append(getattr(block, "input", None))

            if not matching_inputs:
                raise _MalformedResponseError(
                    "no record_annotations tool_use block was present"
                )
            if len(matching_inputs) != 1:
                raise _MalformedResponseError(
                    "multiple record_annotations tool_use blocks were present"
                )
            if len(content) != 1:
                logger.warning(
                    "Anthropic response for page %d included %d extra content block(s) "
                    "alongside record_annotations.",
                    page_number,
                    len(content) - 1,
                )

            tool_input = matching_inputs[0]
            if not isinstance(tool_input, dict):
                raise _MalformedResponseError(
                    "record_annotations input was not a JSON object"
                )
            if "annotations" not in tool_input:
                raise _MalformedResponseError(
                    "record_annotations input omitted the annotations key"
                )

            result = tool_input["annotations"]
            if not isinstance(result, list):
                raise _MalformedResponseError(
                    "record_annotations annotations value was not a list"
                )
            return result

        # Case 2: plain string, expected to be JSON (object with
        # "annotations" key, or a bare array).
        text = str(response).strip()
        if not text:
            return []

        # Be forgiving of markdown code fences around the JSON.
        if text.startswith("```"):
            text = text.strip("`")
            if text.lower().startswith("json"):
                text = text[4:]
            text = text.strip()

        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            logger.error(
                "Failed to parse JSON annotation response for page %d: %s",
                page_number,
                exc,
            )
            return []

        if isinstance(parsed, list):
            return parsed
        if isinstance(parsed, dict):
            result = parsed.get("annotations", [])
            if isinstance(result, list):
                return result

        logger.warning(
            "Unexpected JSON shape in annotation response for page %d: %r",
            page_number,
            parsed,
        )
        return []
