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

import subprocess
import sys
import webbrowser
from pathlib import Path
from typing import Union

import click
from rich import box
from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.table import Table

from halfblood.annotation_generator import AnnotationGenerator
from halfblood.document_processor import DocumentProcessor, PageContent
from halfblood.epub_processor import EpubProcessor
from halfblood.models import AnnotatedPage, AnnotationPlan, AnnotationType
from halfblood.web_preview import generate_preview

Processor = Union[DocumentProcessor, EpubProcessor]

#: File extensions this CLI knows how to route to a processor.
_SUPPORTED_SUFFIXES = {".pdf", ".epub"}

console = Console()

DEFAULT_PERSONA = (
    "A brilliant, sardonic expert who has mastered this subject and can't "
    "help scrawling corrections and improvements in the margins. Terse. "
    "Impatient with mediocrity. Occasionally shows flashes of dark humor."
)
DEFAULT_MODEL = "claude-sonnet-4-20250514"


def _parse_page_range(spec: str | None, total_pages: int) -> list[int]:
    """Parse ``"1-5,8,10-12"`` into a sorted list of 1-indexed page numbers."""
    if not spec:
        return list(range(1, total_pages + 1))

    pages: set[int] = set()
    for chunk in spec.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        if "-" in chunk:
            start_s, end_s = chunk.split("-", 1)
            start, end = int(start_s), int(end_s)
            if start > end:
                start, end = end, start
            pages.update(range(start, end + 1))
        else:
            pages.add(int(chunk))

    return sorted(p for p in pages if 1 <= p <= total_pages)


def _filter_pages(all_pages: list[PageContent], page_numbers: list[int]) -> list[PageContent]:
    """Keep only pages whose page_number is in the requested set."""
    wanted = set(page_numbers)
    return [p for p in all_pages if p.page_number in wanted]


def _processor_for(path: Path) -> Processor:
    """Pick a `DocumentProcessor` (PDF) or `EpubProcessor` (EPUB) based on
    `path`'s extension.

    Raises:
        click.ClickException: if the extension isn't `.pdf` or `.epub`.
    """
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return DocumentProcessor()
    if suffix == ".epub":
        return EpubProcessor()
    raise click.ClickException(
        f"Unsupported file type {suffix!r} for {path.name!r}; "
        f"expected one of {sorted(_SUPPORTED_SUFFIXES)}."
    )


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


@main.command()
@click.argument("input_file", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("-o", "--output", "output_file", required=True,
              type=click.Path(dir_okay=False, path_type=Path),
              help="Path to write the annotated file (.pdf or .epub, matching the input).")
@click.option("--persona", default=DEFAULT_PERSONA, show_default=False,
              help="Annotator personality description.")
@click.option("--pages", default=None, help="Page/chapter range, e.g. '1-5,8'. Default: all.")
@click.option("--model", default=DEFAULT_MODEL, show_default=True)
@click.option("--max-per-page", default=5, show_default=True,
              help="Max annotations per page/chapter.")
def annotate(input_file: Path, output_file: Path, persona: str,
             pages: str | None, model: str, max_per_page: int) -> None:
    """Annotate INPUT_FILE (a .pdf or .epub) in the style of the Half-Blood Prince."""
    console.rule("[bold magenta]Half-Blood Prince -- Annotate[/bold magenta]")

    processor = _processor_for(input_file)
    if output_file.suffix.lower() != input_file.suffix.lower():
        console.print(
            f"[yellow]Warning:[/yellow] output extension {output_file.suffix!r} doesn't "
            f"match input extension {input_file.suffix!r}; writing "
            f"{input_file.suffix.lower()}-formatted content to {output_file} regardless."
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

        # Generate
        try:
            generator = AnnotationGenerator(persona=persona, model=model)
        except ValueError as exc:
            raise click.ClickException(str(exc)) from exc
        gen_task = progress.add_task("Generating annotations...", total=len(selected))
        plan = generator.generate_for_document(selected, max_annotations_per_page=max_per_page)
        progress.update(gen_task, completed=len(selected))

        # Render
        render_task = progress.add_task("Rendering annotated file...", total=1)
        if isinstance(processor, DocumentProcessor):
            flat_annotations = processor.annotations_from_plan(plan)
        else:
            flat_annotations = [a for ap in plan.pages for a in ap.annotations]
        processor.render_annotations(str(input_file), flat_annotations, str(output_file))
        progress.update(render_task, completed=1)

    console.print(
        f"[bold green]Done.[/bold green] {plan.total_annotations} annotations "
        f"across {len(plan.pages)} pages -> [cyan]{output_file}[/cyan]"
    )


@main.command()
@click.argument("input_file", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--pages", default="1-3", show_default=True, help="Page/chapter range to preview.")
@click.option("--persona", default=DEFAULT_PERSONA, show_default=False)
@click.option("--model", default=DEFAULT_MODEL, show_default=True)
@click.option("--max-per-page", default=5, show_default=True)
def preview(input_file: Path, pages: str, persona: str, model: str, max_per_page: int) -> None:
    """Generate annotations for INPUT_FILE (a .pdf or .epub) and print them
    (no annotated file is written)."""
    console.rule("[bold magenta]Half-Blood Prince -- Preview[/bold magenta]")

    processor = _processor_for(input_file)

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
        if not selected:
            console.print("[yellow]No pages matched.[/yellow]")
            raise SystemExit(1)

        try:
            generator = AnnotationGenerator(persona=persona, model=model)
        except ValueError as exc:
            raise click.ClickException(str(exc)) from exc
        gen_task = progress.add_task("Generating annotations...", total=len(selected))
        plan = generator.generate_for_document(selected, max_annotations_per_page=max_per_page)
        progress.update(gen_task, completed=len(selected))

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
def web_preview(
    plan_path: Path, output_path: Path, book_text_path: Path | None, open_browser: bool
) -> None:
    """Render PLAN_PATH (a JSON-serialized AnnotationPlan) as a self-contained,
    interactive HTML book preview with animated, hand-written margin notes."""
    console.rule("[bold magenta]Half-Blood Prince -- Web Preview[/bold magenta]")

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


@main.command(name="eval")
@click.option("--model", default=None, help="Override model for eval harness.")
@click.option("--json-out", type=click.Path(dir_okay=False, path_type=Path), default=None)
@click.option("--list", "list_only", is_flag=True, help="List test cases and exit.")
def eval_cmd(model: str | None, json_out: Path | None, list_only: bool) -> None:
    """Run the annotation-quality evaluation harness."""
    repo_root = Path(__file__).resolve().parents[2]
    harness = repo_root / "eval" / "eval_harness.py"

    if not harness.exists():
        console.print(f"[bold red]Eval harness not found at {harness}[/bold red]")
        raise SystemExit(1)

    cmd = [sys.executable, str(harness)]
    if model:
        cmd += ["--model", model]
    if json_out:
        cmd += ["--json-out", str(json_out)]
    if list_only:
        cmd += ["--list"]

    raise SystemExit(subprocess.run(cmd).returncode)


if __name__ == "__main__":
    main()
