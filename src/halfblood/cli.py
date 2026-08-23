"""Command-line interface for Half-Blood Prince.

    halfblood annotate input.pdf -o output.pdf --persona "sardonic chemistry professor"
    halfblood annotate input.epub -o output.epub
    halfblood preview input.pdf --pages 1-5
    halfblood preview input.epub --pages 1-3
    halfblood eval

Both the ``annotate`` and ``preview`` commands auto-detect the input file
type from its extension (``.pdf`` or ``.epub``) and dispatch to
`DocumentProcessor` or `EpubProcessor` accordingly -- everything else
(annotation generation, page filtering, progress reporting) is shared.
"""

from __future__ import annotations

import importlib.resources as resources
import inspect
import logging
import os
import re
import subprocess
import sys
import webbrowser
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal, TypeVar

import click
from rich import box
from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.table import Table

from halfblood.annotation_generator import (
    DEFAULT_MODEL as _ANNOTATION_DEFAULT_MODEL,
)
from halfblood.annotation_generator import (
    AllPagesFailedError,
    AnnotationGenerator,
)
from halfblood.config import ResolvedConfig, resolve_generation_config
from halfblood.document_processor import DocumentProcessor, PageContent
from halfblood.epub_processor import EpubProcessor
from halfblood.generation.errors import ProviderConfigurationError, ProviderError
from halfblood.generation.providers.base import GenerationRequest, LLMProvider
from halfblood.generation.providers.stub import FailPagesProvider
from halfblood.generation.registry import build_provider
from halfblood.generation.run_report import build_run_report, write_run_report
from halfblood.generation.schema import generate_annotation_schema
from halfblood.ink.composer import HandwritingUnavailable
from halfblood.models import AnnotatedPage, AnnotationPlan
from halfblood.web_preview import generate_preview

Processor = DocumentProcessor | EpubProcessor

#: File extensions this CLI knows how to route to a processor.
_SUPPORTED_SUFFIXES = {".pdf", ".epub"}

#: The handwriting fonts ship *inside* the package (``halfblood/fonts``), so the
#: registry must resolve them through package resources. Deriving this from
#: ``__file__.parents[2]`` pointed at the repo-root ``fonts/`` directory, which
#: exists only in a source checkout: from a pip-installed wheel it resolved to a
#: non-existent path above site-packages, and every registered ``--font`` name
#: (and the config ``font`` key) failed with "is not installed" while pointing
#: the user at a font already bundled in the package.
_FONTS_DIR = Path(str(resources.files("halfblood").joinpath("fonts")))

#: PDF handwriting fonts understood by ``annotate --font``. Values are
#: ``(display name, expected filename, download URL)``.
REGISTERED_FONTS: dict[str, tuple[str, str, str]] = {
    "caveat-brush": (
        "Caveat Brush",
        "CaveatBrush-Regular.ttf",
        "https://fonts.google.com/specimen/Caveat+Brush",
    ),
    "homemade-apple": (
        "Homemade Apple",
        "HomemadeApple-Regular.ttf",
        "https://fonts.google.com/specimen/Homemade+Apple",
    ),
    "just-me-again-down-here": (
        "Just Me Again Down Here",
        "JustMeAgainDownHere.ttf",
        "https://fonts.google.com/specimen/Just+Me+Again+Down+Here",
    ),
    "mrs-saint-delafield": (
        "Mrs Saint Delafield",
        "MrsSaintDelafield-Regular.ttf",
        "https://fonts.google.com/specimen/Mrs+Saint+Delafield",
    ),
}

console = Console()

# Backward-compatible module export; the CLI no longer supplies this as a flag default.
DEFAULT_MODEL = _ANNOTATION_DEFAULT_MODEL

_CommandFunction = TypeVar("_CommandFunction", bound=Callable[..., Any])


def _provider_options(command: _CommandFunction) -> _CommandFunction:
    """Apply the shared provider/configuration options to a CLI command."""
    options = (
        click.option(
            "--provider",
            type=click.Choice(
                (
                    "anthropic",
                    "openai",
                    "openrouter",
                    "ollama",
                    "lmstudio",
                    "openai-compatible",
                    "stub",
                )
            ),
            default=None,
        ),
        click.option("--model", type=str, default=None),
        click.option("--base-url", type=str, default=None),
        click.option("--api-key-env", type=str, default=None),
        click.option(
            "--structured-output",
            type=click.Choice(("auto", "tool", "json-schema", "prompt")),
            default=None,
        ),
        click.option("--timeout", type=float, default=None),
        click.option("--max-retries", type=int, default=None),
        click.option("--concurrency", type=int, default=None),
        click.option("--allow-insecure-http", is_flag=True, default=False),
        click.option(
            "--config",
            "config_path",
            type=click.Path(dir_okay=False, path_type=Path),
            default=None,
        ),
    )
    for option in reversed(options):
        command = option(command)
    return command


def _resolve_provider_and_build(
    provider: str | None,
    model: str | None,
    base_url: str | None,
    api_key_env: str | None,
    structured_output: str | None,
    timeout: float | None,
    max_retries: int | None,
    concurrency: int | None,
    allow_insecure_http: bool,
    config_path: Path | None,
    *,
    max_per_page: int | None = None,
    font: str | None = None,
) -> tuple[ResolvedConfig, LLMProvider]:
    """Resolve provider settings and construct the selected provider adapter."""
    cli_overrides = {
        key: value
        for key, value in {
            "provider": provider,
            "model": model,
            "base_url": base_url,
            "api_key_env": api_key_env,
            "structured_output": structured_output,
            "timeout_seconds": timeout,
            "max_retries": max_retries,
            "concurrency": concurrency,
            "allow_insecure_http": allow_insecure_http or None,
            "max_per_page": max_per_page,
            "font": font,
        }.items()
        if value is not None
    }

    try:
        config = resolve_generation_config(
            cli_overrides,
            project_config_path=config_path,
        )
        api_key = os.environ.get(config.api_key_env) if config.api_key_env else None
        provider_obj = build_provider(config, api_key=api_key)
    except ProviderError as exc:
        raise click.ClickException(str(exc)) from exc

    return config, provider_obj


def available_personas(personas_dir: Path | None = None) -> list[str]:
    """Sorted names of the bundled personas (file stems, no extension).

    Args:
        personas_dir: Injectable search directory for tests.  When *None* the
            directory that ships inside the installed ``halfblood`` package is
            used.
    """
    if personas_dir is not None and personas_dir.is_dir():
        names = sorted(
            p.stem for p in personas_dir.iterdir()
            if p.suffix == ".txt" and p.stem != "README"
        )
        if names:
            return names
    # Fall back to the package-bundled directory.
    pkg_dir = Path(str(resources.files("halfblood").joinpath("personas")))
    return sorted(
        p.stem for p in pkg_dir.iterdir()
        if p.suffix == ".txt" and p.stem != "README"
    )


def _resolve_persona_name(name: str, personas_dir: Path | None = None) -> str:
    """Return the text of a bundled persona, or raise ``click.ClickException``.

    Resolution order: injected ``personas_dir`` first (so tests and custom
    directories work without touching the package), then the directory bundled
    inside the installed ``halfblood`` package.  A name that resolves in
    neither raises a :class:`click.ClickException` that lists every available
    persona.

    Args:
        name: Stem of a persona file (e.g. ``"chemist"``).
        personas_dir: Injectable directory, searched before the package
            resource.  When *None* only the package resource is searched.

    Raises:
        click.ClickException: if *name* is unknown.
    """
    # Injected directory first.
    if personas_dir is not None:
        candidate = personas_dir / f"{name}.txt"
        if candidate.is_file():
            return candidate.read_text(encoding="utf-8")

    # Package resource second.
    pkg_dir = Path(str(resources.files("halfblood").joinpath("personas")))
    pkg_candidate = pkg_dir / f"{name}.txt"
    if pkg_candidate.is_file():
        return pkg_candidate.read_text(encoding="utf-8")

    available = ", ".join(available_personas(personas_dir))
    raise click.ClickException(
        f"Unknown persona {name!r}. Available names: {available}."
    )


def _resolve_persona(
    persona_flag: str | None,
    persona_file: Path | None,
    persona_name: str | None,
    config_persona: str | None,
) -> str | None:
    """Resolve the effective persona: whichever CLI flag was given > config > None.

    ``--persona``, ``--persona-file`` and ``--persona-name`` are mutually
    exclusive -- supplying two or more is a :class:`click.UsageError`, which
    extends the pre-existing rule for the first two rather than introducing a
    new convention. There is therefore no precedence *between* the flags; the
    order they are checked in below is unreachable for a conflicting call, and
    only the flag-vs-config precedence is observable.
    """
    flags_given = sum(x is not None for x in (persona_flag, persona_file, persona_name))
    if flags_given >= 2:
        raise click.UsageError(
            "--persona, --persona-file, and --persona-name are mutually exclusive; "
            "provide at most one."
        )
    if persona_flag is not None:
        return persona_flag
    if persona_file is not None:
        if not persona_file.exists():
            raise click.ClickException(f"Persona file not found: {persona_file}")
        try:
            return persona_file.read_text(encoding="utf-8")
        except OSError as exc:
            raise click.ClickException(
                f"Could not read persona file {persona_file}: {exc}"
            ) from exc
    if persona_name is not None:
        return _resolve_persona_name(persona_name)
    return config_persona


def _parse_page_range(spec: str | None, total_pages: int) -> list[int]:
    """Parse ``"1-5,8,10-12"`` into a sorted list of 1-indexed page numbers.

    Rules:
    - Page numbers are 1-based; ``0`` is rejected as ``BadParameter``.
    - Reversed ranges (e.g. ``'5-1'``) are rejected as ``BadParameter``.
    - Leading/trailing whitespace and empty comma-separated slots are ignored.
    - Page numbers beyond ``total_pages`` are silently filtered out; the
      caller's "no pages matched" guard handles the resulting empty list.

    Raises:
        click.BadParameter: if any token is not an ASCII positive integer or a
            valid ascending range (e.g. ``'foo'``, ``'3-'``, ``'-3'``,
            ``'1-3-5'``, ``'5-1'``, ``'0'``).
    """
    if not spec:
        return list(range(1, total_pages + 1))

    # ASCII-only to exclude Unicode decimal digits (e.g. Arabic-Indic '١٢٣'
    # which re.match(r'\d+') would accept but whose intent is unclear).
    _INT_RE = re.compile(r"^[0-9]+$")

    def _parse_positive_int(token: str, context: str) -> int:
        """Parse an ASCII decimal integer >= 1, raising BadParameter on failure."""
        if not _INT_RE.match(token):
            raise click.BadParameter(
                f"invalid page number {token!r} in {context!r}; "
                "expected a positive integer (e.g. '3' or '1-5')",
                param_hint="--pages",
            )
        n = int(token)
        if n < 1:
            raise click.BadParameter(
                f"page number {n} in {context!r} is invalid; "
                "pages are 1-based so the minimum is 1",
                param_hint="--pages",
            )
        return n

    pages: set[int] = set()
    for chunk in spec.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        if "-" in chunk:
            parts = chunk.split("-", 1)
            start_s, end_s = parts[0], parts[1]
            if not start_s or not end_s:
                raise click.BadParameter(
                    f"invalid range {chunk!r}; expected 'START-END' with both integers present",
                    param_hint="--pages",
                )
            start = _parse_positive_int(start_s, chunk)
            end = _parse_positive_int(end_s, chunk)
            if start > end:
                raise click.BadParameter(
                    f"invalid range {chunk!r}: start ({start}) must be <= end ({end}); "
                    "reversed ranges are not supported",
                    param_hint="--pages",
                )
            pages.update(range(start, end + 1))
        else:
            pages.add(_parse_positive_int(chunk, chunk))

    return sorted(p for p in pages if 1 <= p <= total_pages)


def _require_text_layer(selected: list[PageContent]) -> None:
    """Fail with an actionable message when nothing readable was extracted.

    A page-image PDF with no OCR layer is a normal thing for a user to try, and
    the pipeline's honest answer is that it cannot do anything with it. Without
    this check it reported "0 annotations" and exited 0, which is
    indistinguishable from a book the annotator simply had no opinions about.

    The condition is deliberately "not one readable character anywhere in the
    selection" rather than a per-page character threshold. A threshold has to
    guess how sparse a real page may be, and would misfire on a range that is
    legitimately thin -- a title page, a part-divider, a page holding one line of
    verse. Nothing at all is unambiguous. It is also sufficient: measured on the
    Internet Archive's Google scan of Jekyll & Hyde, exactly 1 of 171 pages
    carried any text, and that one was the scanner's own front-matter notice.
    """
    if not selected:
        return
    if any(p.text and not p.text.isspace() for p in selected):
        return
    raise click.ClickException(
        "No readable text found in the selected pages. This usually means the "
        "file is a scan of page images with no OCR text layer — the annotator "
        "works from the text layer, so there is nothing for it to read.\n"
        "Run the file through OCR first (for example: "
        "'ocrmypdf input.pdf output.pdf'), then annotate the result."
    )


def _filter_pages(all_pages: list[PageContent], page_numbers: list[int]) -> list[PageContent]:
    """Keep only pages whose page_number is in the requested set."""
    wanted = set(page_numbers)
    return [p for p in all_pages if p.page_number in wanted]


def _processor_for(
    path: Path,
    font_path: Path | None = None,
    handwriting_engine: Literal["typeset", "procedural"] = "typeset",
) -> Processor:
    """Pick a `DocumentProcessor` (PDF) or `EpubProcessor` (EPUB) based on
    `path`'s extension.

    Raises:
        click.ClickException: if the extension isn't `.pdf` or `.epub`.
    """
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        # `handwriting_engine` is accepted for signature stability but intentionally
        # NOT threaded to the PDF processor: `annotate` rejects `procedural` before
        # this point (P3-T5 NO-GO), so only `typeset` — the DocumentProcessor default
        # — ever reaches here. Threading a value that can only be the default adds no
        # behavior and would couple every DocumentProcessor construction assertion to it.
        if font_path is not None:
            return DocumentProcessor(font_path=str(font_path))
        return DocumentProcessor()
    if suffix == ".epub":
        return EpubProcessor()
    raise click.ClickException(
        f"Unsupported file type {suffix!r} for {path.name!r}; "
        f"expected one of {sorted(_SUPPORTED_SUFFIXES)}."
    )


def _resolve_font_option(value: str, fonts_dir: Path | None = None) -> Path:
    """Resolve a registered font name or an existing explicit font path.

    Args:
        value: Registered kebab-case name or path to a TTF/OTF file.
        fonts_dir: Registry search directory, injectable for tests.

    Raises:
        click.ClickException: if the name is unknown or the requested file is absent.
    """
    candidate = Path(value).expanduser()
    if candidate.is_file():
        return candidate

    font = REGISTERED_FONTS.get(value)
    if font is not None:
        display_name, filename, url = font
        expected = (fonts_dir or _FONTS_DIR) / filename
        if expected.is_file():
            return expected
        raise click.ClickException(
            f"Font {display_name!r} is not installed. Expected {expected}. "
            f"Download it from {url}."
        )

    looks_like_path = candidate.suffix.lower() in {".ttf", ".otf"} or candidate.parent != Path(".")
    if looks_like_path:
        raise click.ClickException(f"Font file does not exist: {candidate}")

    names = ", ".join(REGISTERED_FONTS)
    raise click.ClickException(
        f"Unknown font {value!r}. Use an existing .ttf/.otf path or one of: {names}."
    )


def _validate_input_signature(path: Path) -> None:
    """Reject files whose bytes do not match the routed input type."""
    suffix = path.suffix.lower()
    if suffix not in _SUPPORTED_SUFFIXES:
        # Keep the unsupported-suffix error centralized in the router.
        _processor_for(path)

    with path.open("rb") as input_stream:
        signature = input_stream.read(4)
    expected = b"%PDF" if suffix == ".pdf" else b"PK\x03\x04"
    if not signature.startswith(expected):
        file_type = "PDF" if suffix == ".pdf" else "EPUB (ZIP)"
        raise click.ClickException(
            f"{path.name!r} does not appear to be a valid {file_type} file."
        )


def _is_same_file(a: Path, b: Path) -> bool:
    """Return True when *a* and *b* refer to the same filesystem object.

    Uses :func:`os.path.samefile` when both paths exist (handles symlinks and
    hard-links correctly), and falls back to comparing resolved paths when the
    output does not yet exist (covers ``./book.pdf`` vs ``book.pdf`` etc.).
    """
    try:
        return os.path.samefile(a, b)
    except OSError:
        # One or both paths do not exist yet; resolved comparison is best-effort.
        return a.resolve() == b.resolve()


def _refuse_existing_output(
    path: Path,
    force: bool,
    *,
    source_paths: tuple[Path, ...] = (),
) -> None:
    """Require an explicit opt-in before replacing an output file.

    Args:
        path: The proposed output path.
        force: When True, allow overwriting *a different* file.
        source_paths: Zero or more input paths that must never be overwritten.
            If *path* resolves to the same file as any of them the command
            refuses unconditionally — even with ``--force``.  ``--force``
            means "overwrite the output", never "destroy my source(s)".
            Pass all inputs (plan, book text, …) here so a future command with
            multiple inputs cannot accidentally omit one.
    """
    for src in source_paths:
        if _is_same_file(path, src):
            raise click.ClickException(
                f"Output file {path} is the same file as the input {src}. "
                "Writing to the same path would overwrite your source. "
                "Choose a different output path."
            )
    if path.exists() and not force:
        raise click.ClickException(
            f"Output file {path} already exists; use --force to overwrite it."
        )


def _checkpoint_path_for(output_file: Path) -> Path:
    """Return the streaming checkpoint-plan path for an artifact path.

    ``out.pdf`` checkpoints to ``out.plan.json`` — the file a later run can
    pass to ``--resume-from`` after an interruption.
    """
    return output_file.with_name(output_file.stem + ".plan.json")


def _load_resume_pages(resume_from: Path) -> dict[int, AnnotatedPage]:
    """Load a partial plan for ``--resume-from``; page number -> page."""
    try:
        resume_plan = AnnotationPlan.model_validate_json(
            resume_from.read_text(encoding="utf-8")
        )
    except ValueError as exc:
        raise click.ClickException(
            f"--resume-from {resume_from} is not a valid annotation plan "
            f"JSON: {exc}"
        ) from exc
    return {page.page_number: page for page in resume_plan.pages}


def _generate_with_progress(
    generator: AnnotationGenerator,
    pages: list[PageContent],
    max_annotations_per_page: int,
    on_page_done: Callable[[int, int], None],
    resume_pages: dict[int, AnnotatedPage] | None = None,
    checkpoint_path: Path | None = None,
) -> AnnotationPlan:
    """Generate a plan with callbacks when the generator supports them.

    The signature check preserves compatibility with third-party generator
    doubles written against the older two-argument method: ``resume_pages``
    and ``checkpoint_path`` are only forwarded when the target accepts them.
    """
    generate = generator.generate_for_document
    parameters = inspect.signature(generate).parameters.values()
    names = {parameter.name for parameter in parameters}
    has_var_kw = any(
        parameter.kind is inspect.Parameter.VAR_KEYWORD for parameter in parameters
    )

    def _supports(parameter_name: str) -> bool:
        return parameter_name in names or has_var_kw

    kwargs: dict[str, Any] = {"max_annotations_per_page": max_annotations_per_page}
    if _supports("on_page_done"):
        kwargs["on_page_done"] = on_page_done
    if resume_pages and _supports("resume_pages"):
        kwargs["resume_pages"] = resume_pages
    if checkpoint_path is not None and _supports("checkpoint_path"):
        kwargs["checkpoint_path"] = checkpoint_path
    return generate(pages, **kwargs)


def _generation_statuses(generator: object) -> tuple[Any, ...]:
    """Return retained per-page statuses; tolerant of legacy test doubles."""
    statuses = getattr(generator, "generation_statuses", None)
    return tuple(statuses) if statuses else ()


def _print_usage_line(generator: object, console: Console) -> None:
    """Print a token-count summary line if usage data is available."""
    usage = getattr(generator, "usage_totals", None)
    if usage is None or usage.pages_with_usage == 0:
        return
    line = f"Tokens: {usage.input_tokens} in / {usage.output_tokens} out"
    if usage.pages_missing_usage > 0:
        line += f" — usage unavailable for {usage.pages_missing_usage} page(s)"
    console.print(line)


def _print_annotated_page(annotated_page: AnnotatedPage) -> None:
    """Pretty-print one page's annotations."""
    if not annotated_page.annotations:
        console.print(f"[dim]Page {annotated_page.page_number}: no annotations.[/dim]")
        return

    table = Table(
        title=f"Page {annotated_page.page_number}",
        box=box.SIMPLE_HEAVY,
        show_lines=True,
    )
    table.add_column("Type", style="bold")
    table.add_column("Target text")
    table.add_column("Note")
    table.add_column("Conf.", justify="right")

    for ann in annotated_page.annotations:
        snippet = ann.target_text[:57] + "..." if len(ann.target_text) > 60 else ann.target_text
        table.add_row(
            ann.annotation_type.value,
            snippet,
            ann.content,
            f"{ann.confidence:.2f}",
        )
    console.print(table)


@click.group()
@click.version_option(package_name="half-blood-prince")
def main() -> None:
    """halfblood -- annotate any book like the Half-Blood Prince."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")


@main.command(context_settings={"terminal_width": 160})
@click.argument("input_file", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("-o", "--output", "output_file", required=True,
              type=click.Path(dir_okay=False, path_type=Path),
              help="Path to write the annotated file (.pdf or .epub, matching the input).")
@click.option(
    "--persona",
    default=None,
    show_default=False,
    help=(
        "Annotator personality description. Defaults to the Half-Blood Prince "
        "(Severus Snape) persona when not specified."
    ),
)
@click.option(
    "--persona-file",
    "persona_file",
    type=click.Path(dir_okay=False, path_type=Path),
    default=None,
    help=(
        "Path to a UTF-8 text file containing a custom annotator persona. "
        "Use --persona-name for built-in voices (chemist, philosopher, editor, detective). "
        "Mutually exclusive with --persona and --persona-name."
    ),
)
@click.option(
    "--persona-name",
    "persona_name",
    default=None,
    metavar="NAME",
    help=(
        "Built-in annotator persona by name. "
        "Available: chemist, detective, editor, philosopher. "
        "Mutually exclusive with --persona and --persona-file."
    ),
)
@click.option("--pages", default=None, help="Page/chapter range, e.g. '1-5,8'. Default: all.")
@click.option("--max-per-page", default=None,
              help="Max annotations per page/chapter. Default: 5.")
@click.option(
    "--font",
    default=None,
    metavar="NAME|PATH",
    help="PDF handwriting font. Registered names: " + ", ".join(REGISTERED_FONTS) + ".",
)
@click.option(
    "--handwriting-engine",
    type=click.Choice(("typeset", "procedural")),
    default="typeset",
    show_default=True,
    help="Note-body engine. Rough PDF marks are always procedural vectors.",
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help=(
        "Generate annotations but skip rendering entirely; write the annotation "
        "plan as JSON to the -o path. Useful for debugging persona/prompt issues "
        "without waiting for rendering. The JSON output is loadable by web-preview."
    ),
)
@click.option(
    "--annotate-boilerplate",
    is_flag=True,
    default=False,
    help=(
        "Annotate even sections that look like boilerplate (copyright notices, "
        "Project Gutenberg headers/licenses). Default: skip boilerplate sections."
    ),
)
@click.option("--force", is_flag=True, help="Overwrite an existing output file.")
@click.option(
    "--fail-pages",
    default=None,
    metavar="N,N",
    help=(
        "Simulate a provider failure on these page numbers (e.g. '7,13'). "
        "Testing knob for the report sidecar; typically used with --provider stub."
    ),
)
@click.option(
    "--resume-from",
    "resume_from",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    help=(
        "Resume an interrupted run: skip the pages already annotated in this "
        "partial annotation-plan JSON and generate only the missing ones. "
        "Every annotate run streams its partial plan to <output>.plan.json "
        "while it works, so after a crash you can resume from that file."
    ),
)
@_provider_options
def annotate(
    input_file: Path,
    output_file: Path,
    persona: str | None,
    persona_file: Path | None,
    persona_name: str | None,
    pages: str | None,
    max_per_page: int | None,
    font: str | None,
    handwriting_engine: Literal["typeset", "procedural"],
    dry_run: bool,
    annotate_boilerplate: bool,
    force: bool,
    fail_pages: str | None,
    resume_from: Path | None,
    provider: str | None,
    model: str | None,
    base_url: str | None,
    api_key_env: str | None,
    structured_output: str | None,
    timeout: float | None,
    max_retries: int | None,
    concurrency: int | None,
    allow_insecure_http: bool,
    config_path: Path | None,
) -> None:
    """Annotate INPUT_FILE (a .pdf or .epub) in the style of the Half-Blood Prince."""
    console.rule("[bold magenta]Half-Blood Prince -- Annotate[/bold magenta]")

    _validate_input_signature(input_file)
    if handwriting_engine == "procedural":
        unavailable = HandwritingUnavailable()
        raise click.ClickException(f"{unavailable.code}: {unavailable.detail}")
    if not dry_run and output_file.suffix.lower() != input_file.suffix.lower():
        console.print(
            f"[yellow]Warning:[/yellow] output extension {output_file.suffix!r} doesn't "
            f"match input extension {input_file.suffix!r}; writing "
            f"{input_file.suffix.lower()}-formatted content to {output_file} regardless."
        )

    # ------------------------------------------------------------------
    # Resolve ALL file inputs before guarding the output.
    #
    # The guard must see every path this run will read so that
    # ``-o <any-input-file> --force`` is always refused.  Each new CLI
    # option that reads a file MUST be registered here.
    #
    # Persona errors surface before provider/config errors (existing
    # precedence preserved) because persona is resolved first.
    # ------------------------------------------------------------------

    # Resolve persona before provider setup so that pure usage errors
    # (mutual exclusion, bad name, missing file) surface with the correct
    # exit code regardless of whether an API key is present.
    early_persona = _resolve_persona(persona, persona_file, persona_name, None)

    config, provider_obj = _resolve_provider_and_build(
        provider,
        model,
        base_url,
        api_key_env,
        structured_output,
        timeout,
        max_retries,
        concurrency,
        allow_insecure_http,
        config_path,
        max_per_page=max_per_page,
        font=font,
    )
    if fail_pages:
        try:
            fail_pages_set = frozenset(
                int(part) for part in fail_pages.split(",") if part.strip()
            )
        except ValueError as exc:
            raise click.ClickException(
                f"--fail-pages must be a comma-separated list of integers: {exc}"
            ) from exc
        if not fail_pages_set:
            raise click.ClickException("--fail-pages parsed to an empty page set")
        provider_obj = FailPagesProvider(provider_obj, fail_pages_set)
    effective_font = config.font
    if input_file.suffix.lower() == ".epub" and effective_font is not None:
        console.print(
            "[yellow]Warning:[/yellow] --font is ignored for EPUB input; "
            "EPUB typography is controlled by reader/CSS fonts."
        )
        font_path = None
    else:
        font_path = _resolve_font_option(effective_font) if effective_font is not None else None

    # Detect a font supplied as an explicit CLI path even when the config
    # resolver is replaced (e.g. in tests).  ``font_path`` covers the
    # config-file-derived case; this catches the CLI-explicit case.
    _cli_font_source: Path | None = None
    if font is not None:
        _cand = Path(font).expanduser()
        if _cand.is_file():
            _cli_font_source = _cand

    # Collect every file this command will read, then refuse writing the
    # output over any of them — even with --force.
    _all_sources: list[Path] = [input_file]
    if persona_file is not None:
        _all_sources.append(persona_file)
    if config_path is not None:
        _all_sources.append(config_path)
    if _cli_font_source is not None:
        _all_sources.append(_cli_font_source)
    if font_path is not None:
        _all_sources.append(font_path)
    if resume_from is not None:
        _all_sources.append(resume_from)
    checkpoint_path = _checkpoint_path_for(output_file)
    _refuse_existing_output(output_file, force, source_paths=tuple(_all_sources))

    output_file.parent.mkdir(parents=True, exist_ok=True)
    processor = _processor_for(input_file, font_path, handwriting_engine)
    # If no persona flag was given, fall back to the config-layer persona.
    effective_persona = early_persona if early_persona is not None else config.persona
    generator = AnnotationGenerator(
        persona=effective_persona,
        model=config.model,
        provider=provider_obj,
        concurrency=config.concurrency,
    )
    console.print(
        f"Provider: {config.provider} | Model: {config.model} | Mode: {config.structured_output}"
    )

    with Progress(
        SpinnerColumn(), TextColumn("[progress.description]{task.description}"),
        BarColumn(), TextColumn("{task.completed}/{task.total}"),
        TimeElapsedColumn(), console=console,
    ) as progress:
        # Extract
        extract_task = progress.add_task("Extracting text...", total=1)
        all_pages = processor.load(str(input_file))
        progress.update(extract_task, completed=1)

        if not all_pages:
            console.print("[yellow]No pages extracted.[/yellow]")
            raise SystemExit(1)

        # Filter pages
        page_numbers = _parse_page_range(pages, len(all_pages))
        selected = _filter_pages(all_pages, page_numbers)

        if not selected:
            console.print("[yellow]No pages matched.[/yellow]")
            raise SystemExit(1)

        _require_text_layer(selected)

        # Filter boilerplate sections (unless overridden)
        pages_selected = len(selected)
        boilerplate_skipped: list[int] = []
        if not annotate_boilerplate:
            from halfblood.boilerplate import classify

            bp_pages = [p for p in selected if classify(p.text).is_boilerplate]
            if bp_pages:
                bp_nums = [p.page_number for p in bp_pages]
                if len(bp_pages) == len(selected):
                    # Every section looks like boilerplate — fall back to annotating all
                    console.print(
                        "[yellow]Warning:[/yellow] All selected sections appear to be boilerplate; "
                        "annotating them anyway. Pass --annotate-boilerplate to suppress this warning."
                    )
                else:
                    selected = [p for p in selected if p not in bp_pages]
                    boilerplate_skipped = list(bp_nums)
                    console.print(
                        f"Skipped {len(bp_pages)} boilerplate section(s): "
                        + ", ".join(str(n) for n in bp_nums)
                    )

        # Generate
        resume_pages: dict[int, AnnotatedPage] | None = None
        if resume_from is not None:
            loaded = _load_resume_pages(resume_from)
            selected_numbers = {page.page_number for page in selected}
            ignored = sorted(set(loaded) - selected_numbers)
            if ignored:
                console.print(
                    f"[yellow]Warning:[/yellow] {len(ignored)} page(s) in "
                    f"{resume_from} are outside the selected range and will be "
                    f"regenerated: {ignored}"
                )
            resume_pages = {
                number: page
                for number, page in loaded.items()
                if number in selected_numbers
            }
            if resume_pages:
                console.print(
                    f"[cyan]Resuming:[/cyan] {len(resume_pages)} page(s) already "
                    f"annotated in {resume_from}; skipping them."
                )
            if not resume_pages:
                console.print(
                    f"[yellow]Nothing to resume:[/yellow] no page in {resume_from} "
                    "matches the selection; generating everything."
                )
                resume_pages = None
        gen_task = progress.add_task("Generating annotations...", total=len(selected))
        try:
            plan = _generate_with_progress(
                generator,
                selected,
                config.max_per_page,
                lambda done, _total: progress.update(
                    gen_task, completed=done
                ),
                resume_pages=resume_pages,
                checkpoint_path=checkpoint_path,
            )
        except (AllPagesFailedError, ProviderError) as exc:
            if checkpoint_path.exists():
                console.print(
                    f"[yellow]Checkpoint kept:[/yellow] {checkpoint_path} — "
                    f"rerun with --resume-from {checkpoint_path} to continue "
                    "from the pages that already finished."
                )
            if _generation_statuses(generator):
                sidecar = write_run_report(
                    build_run_report(
                        output_file=output_file,
                        plan=None,
                        statuses=_generation_statuses(generator),
                        boilerplate_pages=boilerplate_skipped,
                        pages_selected=pages_selected,
                    ),
                    output_file,
                )
                console.print(f"Run report -> [cyan]{sidecar}[/cyan]")
            raise click.ClickException(str(exc)) from exc
        progress.update(gen_task, completed=len(selected))
        _print_usage_line(generator, console)

        if dry_run:
            output_file.write_text(plan.model_dump_json(), encoding="utf-8")
            sidecar = write_run_report(
                build_run_report(
                    output_file=output_file,
                    plan=plan,
                    statuses=_generation_statuses(generator),
                    boilerplate_pages=boilerplate_skipped,
                    pages_selected=pages_selected,
                ),
                output_file,
            )
            console.print(f"Run report -> [cyan]{sidecar}[/cyan]")
            console.print(
                f"[bold green]Done.[/bold green] {plan.total_annotations} annotations "
                f"across {len(plan.pages)} pages. "
                f"Dry run — no artifact rendered -> [cyan]{output_file}[/cyan]"
            )
            checkpoint_path.unlink(missing_ok=True)
            return

        # Render — both DocumentProcessor and EpubProcessor define render_plan.
        # The hasattr guard and render_annotations fallback existed only for
        # test-double compatibility and are no longer needed now that all
        # processor fakes have been updated to define render_plan.
        render_task = progress.add_task("Rendering annotated file...", total=1)
        from halfblood.models.documents import migrate_v1_to_v2

        v2_plan = migrate_v1_to_v2(plan.model_dump())
        report = processor.render_plan(str(input_file), v2_plan, str(output_file))
        progress.update(render_task, completed=1)

    render_dump = report if report is not None else None

    sidecar = write_run_report(
        build_run_report(
            output_file=output_file,
            plan=plan,
            statuses=_generation_statuses(generator),
            render_report=render_dump,
            boilerplate_pages=boilerplate_skipped,
            pages_selected=pages_selected,
        ),
        output_file,
    )
    console.print(f"Run report -> [cyan]{sidecar}[/cyan]")

    if report is not None:
        summary = f"Rendered {report.rendered_count} / Skipped {report.skipped_count}"
        if report.marks_only:
            summary += f" ({len(report.marks_only)} mark-only)"
        console.print(summary)

    if generator.failed_pages:
        console.print(
            f"[yellow]Warning:[/yellow] {len(generator.failed_pages)} page(s) failed "
            f"and were left un-annotated: {generator.failed_pages}"
        )

    console.print(
        f"[bold green]Done.[/bold green] {plan.total_annotations} annotations "
        f"across {len(plan.pages)} pages -> [cyan]{output_file}[/cyan]"
    )
    checkpoint_path.unlink(missing_ok=True)


@main.command()
@click.argument("input_file", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--pages", default="1-3", show_default=True, help="Page/chapter range to preview.")
@click.option(
    "--persona",
    default=None,
    show_default=False,
    help="Annotator personality description.",
)
@click.option(
    "--persona-file",
    "persona_file",
    type=click.Path(dir_okay=False, path_type=Path),
    default=None,
    help=(
        "Path to a UTF-8 text file containing a custom annotator persona. "
        "Use --persona-name for built-in voices (chemist, philosopher, editor, detective). "
        "Mutually exclusive with --persona and --persona-name."
    ),
)
@click.option(
    "--persona-name",
    "persona_name",
    default=None,
    metavar="NAME",
    help=(
        "Built-in annotator persona by name. "
        "Available: chemist, detective, editor, philosopher. "
        "Mutually exclusive with --persona and --persona-file."
    ),
)
@click.option("--max-per-page", default=None, help="Max annotations per page/chapter. Default: 5.")
@click.option(
    "--annotate-boilerplate",
    is_flag=True,
    default=False,
    help=(
        "Annotate even sections that look like boilerplate (copyright notices, "
        "Project Gutenberg headers/licenses). Default: skip boilerplate sections."
    ),
)
@_provider_options
def preview(
    input_file: Path,
    pages: str,
    persona: str | None,
    persona_file: Path | None,
    persona_name: str | None,
    max_per_page: int | None,
    annotate_boilerplate: bool,
    provider: str | None,
    model: str | None,
    base_url: str | None,
    api_key_env: str | None,
    structured_output: str | None,
    timeout: float | None,
    max_retries: int | None,
    concurrency: int | None,
    allow_insecure_http: bool,
    config_path: Path | None,
) -> None:
    """Generate annotations for INPUT_FILE (a .pdf or .epub) and print them
    (no annotated file is written)."""
    console.rule("[bold magenta]Half-Blood Prince -- Preview[/bold magenta]")

    _validate_input_signature(input_file)
    processor = _processor_for(input_file)

    # Resolve persona before provider setup so that pure usage errors
    # (mutual exclusion, bad name, missing file) surface with the correct
    # exit code regardless of whether an API key is present.
    early_persona = _resolve_persona(persona, persona_file, persona_name, None)

    config, provider_obj = _resolve_provider_and_build(
        provider,
        model,
        base_url,
        api_key_env,
        structured_output,
        timeout,
        max_retries,
        concurrency,
        allow_insecure_http,
        config_path,
        max_per_page=max_per_page,
    )
    # If no persona flag was given, fall back to the config-layer persona.
    effective_persona = early_persona if early_persona is not None else config.persona
    generator = AnnotationGenerator(
        persona=effective_persona,
        model=config.model,
        provider=provider_obj,
        concurrency=config.concurrency,
    )
    console.print(
        f"Provider: {config.provider} | Model: {config.model} | Mode: {config.structured_output}"
    )

    with Progress(
        SpinnerColumn(), TextColumn("[progress.description]{task.description}"),
        BarColumn(), TextColumn("{task.completed}/{task.total}"),
        TimeElapsedColumn(), console=console,
    ) as progress:
        extract_task = progress.add_task("Extracting text...", total=1)
        all_pages = processor.load(str(input_file))
        progress.update(extract_task, completed=1)

        page_numbers = _parse_page_range(pages, len(all_pages))
        selected = _filter_pages(all_pages, page_numbers)
        _require_text_layer(selected)

        # Filter boilerplate sections (unless overridden)
        if not annotate_boilerplate:
            from halfblood.boilerplate import classify

            bp_pages = [p for p in selected if classify(p.text).is_boilerplate]
            if bp_pages:
                bp_nums = [p.page_number for p in bp_pages]
                if len(bp_pages) == len(selected):
                    # Every section looks like boilerplate — fall back to annotating all
                    console.print(
                        "[yellow]Warning:[/yellow] All selected sections appear to be boilerplate; "
                        "annotating them anyway. Pass --annotate-boilerplate to suppress this warning."
                    )
                else:
                    selected = [p for p in selected if p not in bp_pages]
                    console.print(
                        f"Skipped {len(bp_pages)} boilerplate section(s): "
                        + ", ".join(str(n) for n in bp_nums)
                    )

        if not selected:
            console.print("[yellow]No pages matched.[/yellow]")
            raise SystemExit(1)

        gen_task = progress.add_task("Generating annotations...", total=len(selected))
        try:
            plan = _generate_with_progress(
                generator,
                selected,
                config.max_per_page,
                lambda done, _total: progress.update(
                    gen_task, completed=done
                ),
            )
        except (AllPagesFailedError, ProviderError) as exc:
            raise click.ClickException(str(exc)) from exc
        progress.update(gen_task, completed=len(selected))

    if generator.failed_pages:
        console.print(
            f"[yellow]Warning:[/yellow] {len(generator.failed_pages)} page(s) failed "
            f"and were left un-annotated: {generator.failed_pages}"
        )

    _print_usage_line(generator, console)
    console.print()
    total = 0
    for ap in plan.pages:
        _print_annotated_page(ap)
        total += len(ap.annotations)

    console.print(f"\n[bold]{total}[/bold] annotations across {len(plan.pages)} page(s).")


@main.command(name="web-preview")
@click.argument("plan_path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("-o", "--output", "output_path", default=Path("preview.html"), show_default=True,
              type=click.Path(dir_okay=False, path_type=Path),
              help="Path to write the interactive HTML preview.")
@click.option("--book", "book_text_path", default=None,
              type=click.Path(exists=True, dir_okay=False, path_type=Path),
              help="Optional plain-text file with the original book, used to backfill "
                   "any pages missing embedded text (split on form-feed characters).")
@click.option("--open", "open_browser", is_flag=True, default=False,
              help="Open the generated preview in your default browser when done.")
@click.option("--force", is_flag=True, help="Overwrite an existing output file.")
def web_preview(
    plan_path: Path,
    output_path: Path,
    book_text_path: Path | None,
    open_browser: bool,
    force: bool,
) -> None:
    """Render PLAN_PATH (a JSON-serialized AnnotationPlan) as a self-contained,
    interactive HTML book preview with animated, hand-written margin notes."""
    console.rule("[bold magenta]Half-Blood Prince -- Web Preview[/bold magenta]")

    _sources = (plan_path,) if book_text_path is None else (plan_path, book_text_path)
    _refuse_existing_output(output_path, force, source_paths=_sources)
    book_text = book_text_path.read_text(encoding="utf-8") if book_text_path else None

    with console.status("[bold]Rendering interactive preview...[/bold]"):
        result = generate_preview(plan_path, output_path, book_text=book_text)

    console.print(
        f"[bold green]Done.[/bold green] {result.annotation_count} annotation(s) "
        f"({result.matched_count} anchored to text) across {result.page_count} page(s) "
        f"-> [cyan]{result.output_path}[/cyan]"
    )

    if open_browser:
        webbrowser.open(result.output_path.resolve().as_uri())


#: Override for tests — monkeypatch this to a directory that looks like a source
#: checkout (contains ``pyproject.toml`` and ``eval/eval_harness.py``).
#: When None the command derives the root from ``__file__`` as usual.
_EVAL_REPO_ROOT: Path | None = None


@main.command(name="eval")
@click.option("--model", default=None, help="Override model for eval harness.")
@click.option("--json-out", type=click.Path(dir_okay=False, path_type=Path), default=None)
@click.option("--list", "list_only", is_flag=True, help="List test cases and exit.")
def eval_cmd(model: str | None, json_out: Path | None, list_only: bool) -> None:
    """Run the annotation-quality evaluation harness."""
    import halfblood.cli as _self  # noqa: PLC0415 — avoids a module-level self-import

    repo_root = _self._EVAL_REPO_ROOT or Path(__file__).resolve().parents[2]
    harness = repo_root / "eval" / "eval_harness.py"

    if not harness.exists():
        # Distinguish a broken source checkout from a wheel install.
        if not (repo_root / "pyproject.toml").exists():
            raise click.ClickException(
                "halfblood eval requires a source checkout of the half-blood-prince "
                "repository — install with 'pip install -e .' from the repo root and "
                "run again. The eval harness is not included in the installed package."
            )
        raise click.ClickException(
            f"Eval harness not found at {harness}; is the repository intact?"
        )

    cmd = [sys.executable, str(harness)]
    if model:
        cmd += ["--model", model]
    if json_out:
        cmd += ["--json-out", str(json_out)]
    if list_only:
        cmd += ["--list"]

    raise SystemExit(subprocess.run(cmd).returncode)


@main.group("providers")
def providers() -> None:
    """Provider management and diagnostics."""


@providers.command("doctor")
@click.option(
    "--provider", "provider_name", default=None, help="Provider to check (overrides config)."
)
@click.option("--model", "model_name", default=None, help="Model name (overrides config).")
@click.option(
    "--offline", is_flag=True, default=False, help="Skip the live request; print config only."
)
def doctor(provider_name: str | None, model_name: str | None, offline: bool) -> None:
    """Diagnose provider configuration and connectivity."""
    cli_overrides: dict[str, object] = {}
    if provider_name is not None:
        cli_overrides["provider"] = provider_name
    if model_name is not None:
        cli_overrides["model"] = model_name

    try:
        # --offline prints the resolved config only, so a missing API key is
        # reported as part of that output rather than aborting the check.
        config = resolve_generation_config(
            cli_overrides or None, require_api_key=not offline
        )
    except ProviderConfigurationError as exc:
        raise click.ClickException(str(exc)) from exc

    click.echo(config.safe_repr())
    if offline:
        key_env = config.api_key_env
        if key_env is not None and not os.environ.get(key_env):
            click.echo(f"api_key: NOT SET ({key_env} missing; live calls will fail)")
        return

    api_key = os.environ.get(config.api_key_env) if config.api_key_env else None
    try:
        provider = build_provider(config, api_key=api_key)
    except ProviderConfigurationError as exc:
        raise click.ClickException(str(exc)) from exc

    request = GenerationRequest(
        system_prompt="Diagnostic connectivity check.",
        user_prompt="Return an empty annotations list.",
        schema=generate_annotation_schema(),
        model=config.model,
        max_tokens=64,
    )

    try:
        result = provider.complete(request)
    except ProviderError as exc:
        raise click.ClickException(f"{type(exc).__name__}: {exc}") from exc

    click.echo(f"request_id: {result.request_id}")
    click.echo(f"latency: {result.latency_seconds:.3f}s")
    click.echo(f"finish_reason: {result.finish_reason}")
    capabilities = provider.capabilities
    click.echo(
        f"capabilities: tool_calling={capabilities.supports_tool_calling},"
        f" json_schema={capabilities.supports_json_schema},"
        f" strict_json_schema={capabilities.supports_strict_json_schema}"
    )


if __name__ == "__main__":
    main()
