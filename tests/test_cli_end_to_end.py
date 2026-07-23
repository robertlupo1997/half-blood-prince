"""True end-to-end CLI validation using a deterministic stub LLM provider.

No network access, no API key, no real filesystem config reads.  Tests
exercise the full pipeline:

    CliRunner → halfblood.cli.annotate
        → AnnotationGenerator (stub provider)
        → DocumentProcessor / EpubProcessor
        → annotated output artifact

Empirical design notes (validated before writing, 2026-07-23):

* Rich console output IS captured in ``result.output`` — CliRunner's stdout
  replacement is seen at Rich write-time, so no console monkeypatch is needed.
* ``render_plan`` emits vector drawings (``page.get_drawings()``), NOT native
  PDF annotation objects (``page.annots()``).  PDF assertions use drawings.
* All five KNOWN_PASSAGES targets resolve in the fixture PDF (rendered_count==5).
* All four EPUB_PASSAGES targets resolve in sample_book.epub (rendered_count==4).
* fitz writes non-deterministic /ID bytes into the PDF trailer; byte-level
  equality fails reliably.  Structural equality (page count + per-page drawing
  counts) is the correct determinism assertion.
"""

from __future__ import annotations

import zipfile
from pathlib import Path
from typing import Any
from unittest.mock import patch

import fitz
from click.testing import CliRunner

from halfblood.cli import main as cli_main
from halfblood.config import ResolvedConfig, resolve_generation_config
from halfblood.generation.errors import StructuredOutputError
from halfblood.generation.providers.base import (
    GenerationResult,
    GenerationUsage,
    LLMProvider,
    ProviderCapabilities,
)
from halfblood.generation.schema import AnnotationDraft, RecordAnnotations
from halfblood.models.legacy import AnnotationType

# ---------------------------------------------------------------------------
# Fixtures: absolute paths to test assets
# ---------------------------------------------------------------------------

_TESTS_DIR = Path(__file__).resolve().parent
_PDF_FIXTURE = _TESTS_DIR / "fixtures" / "potions_textbook.pdf"
_EPUB_FIXTURE = _TESTS_DIR / "fixtures" / "sample_book.epub"

# One target passage per PDF page (verified to resolve: rendered_count == 5).
_PDF_PASSAGES: dict[int, str] = {
    1: "Potion-making is, and has always been, a discipline of exactitude.",
    2: "Sopophorous bean",
    3: "Amortentia is widely considered the most powerful love potion in existence.",
    4: "Felix Felicis",
    5: "Golpalott's Third Law",
}

# One target passage per EPUB page (verified to resolve: rendered_count == 4).
_EPUB_PASSAGES: dict[int, str] = {
    1: "On Combustion",
    2: "candle burns",
    3: "acid turns blue litmus red",
    4: "Impatient heating spoils the spirit",
}


# ---------------------------------------------------------------------------
# Stub providers
# ---------------------------------------------------------------------------


class DeterministicStubProvider:
    """LLMProvider that returns scripted RecordAnnotations responses in order.

    The response list is consumed round-robin: call 0 returns responses[0],
    call 1 returns responses[1], and so on.  Extra calls cycle back to the
    start.  Every returned GenerationResult is fully populated so that all
    downstream validation passes.
    """

    def __init__(self, responses: list[RecordAnnotations]) -> None:
        self._responses = list(responses)
        self._call_index = 0

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            supports_tool_calling=True,
            supports_json_schema=True,
            supports_strict_json_schema=True,
        )

    def complete(self, request: Any) -> GenerationResult:
        response = self._responses[self._call_index % len(self._responses)]
        self._call_index += 1
        return GenerationResult(
            parsed=response,
            request_id=f"stub-req-{self._call_index}",
            finish_reason="stop",
            usage=GenerationUsage(input_tokens=120, output_tokens=60),
            latency_seconds=0.001,
            structured_output_mode="tool",
        )


class _PartialFailureProvider:
    """Provider that raises StructuredOutputError for the first call only.

    Models a page whose LLM response was malformed — page 1 is lost, pages 2-N
    succeed.  Verifies that the CLI continues and still writes the output.
    Using StructuredOutputError (retryable=False) is more faithful to the
    brief ("a page's completion is malformed") and decouples the test from
    any future retry-on-transient layer.
    """

    def __init__(self, success_response: RecordAnnotations) -> None:
        self._success = success_response
        self._calls = 0

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            supports_tool_calling=True,
            supports_json_schema=True,
            supports_strict_json_schema=True,
        )

    def complete(self, request: Any) -> GenerationResult:
        self._calls += 1
        if self._calls == 1:
            raise StructuredOutputError(
                "stub: simulated malformed output response on first page call",
            )
        return GenerationResult(
            parsed=self._success,
            request_id=f"stub-req-{self._calls}",
            finish_reason="stop",
            usage=GenerationUsage(input_tokens=120, output_tokens=60),
            latency_seconds=0.001,
            structured_output_mode="tool",
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _pdf_record(page_number: int, passage: str) -> RecordAnnotations:
    """Build a single-annotation RecordAnnotations for one PDF page."""
    return RecordAnnotations(
        annotations=[
            AnnotationDraft(
                target_text=passage,
                annotation_type=AnnotationType.CORRECTION,
                content=f"Stub correction note — page {page_number}",
                confidence=0.9,
                position="margin_right",
            )
        ]
    )


def _epub_record(page_number: int, passage: str) -> RecordAnnotations:
    """Build a single-annotation RecordAnnotations for one EPUB page."""
    return RecordAnnotations(
        annotations=[
            AnnotationDraft(
                target_text=passage,
                annotation_type=AnnotationType.INSIGHT,
                content=f"Stub insight note — page {page_number}",
                confidence=0.85,
                position="margin_right",
            )
        ]
    )


def _pdf_stub_responses() -> list[RecordAnnotations]:
    """Five scripted responses, one per potions_textbook.pdf page (1–5)."""
    return [_pdf_record(pg, text) for pg, text in sorted(_PDF_PASSAGES.items())]


def _epub_stub_responses() -> list[RecordAnnotations]:
    """Four scripted responses, one per sample_book.epub page (1–4)."""
    return [_epub_record(pg, text) for pg, text in sorted(_EPUB_PASSAGES.items())]


def _build_fake_resolve(tmp_path: Path) -> Any:
    """Return a hermetic wrapper around resolve_generation_config.

    Injects:
      - ``environ`` without reading ``os.environ``, providing only the fake key
      - ``project_config_path`` pointing at a nonexistent file
      - ``user_config_path`` pointing at a nonexistent file
    so no real machine config affects test outcomes.
    """
    nonexistent = tmp_path / "nonexistent_config.toml"
    nonexistent_user = tmp_path / "nonexistent_user.toml"

    def _hermetic_resolve(
        cli_overrides: Any = None,
        *,
        project_config_path: Path | None = None,
        **kwargs: Any,
    ) -> ResolvedConfig:
        # Ignore the caller's config_path (from `--config`); always use our
        # nonexistent stub paths so real machine files are never read.
        return resolve_generation_config(
            cli_overrides,
            environ={"ANTHROPIC_API_KEY": "stub-fake-key-for-testing"},
            project_config_path=nonexistent,
            user_config_path=nonexistent_user,
        )

    return _hermetic_resolve


def _invoke_annotate(
    tmp_path: Path,
    stub: LLMProvider,
    *,
    input_file: Path,
    output_suffix: str,
    extra_args: list[str] | None = None,
) -> tuple[Any, Path]:
    """Invoke ``halfblood annotate`` with hermetic stubs, return (result, out_path)."""
    out_path = tmp_path / f"out.{output_suffix}"
    fake_resolve = _build_fake_resolve(tmp_path)

    def _fake_build(config: Any, *, api_key: Any = None) -> LLMProvider:
        return stub

    args = [
        "annotate",
        str(input_file),
        "-o",
        str(out_path),
        "--force",
        *(extra_args or []),
    ]

    runner = CliRunner()
    with (
        patch("halfblood.cli.build_provider", _fake_build),
        patch("halfblood.cli.resolve_generation_config", fake_resolve),
    ):
        result = runner.invoke(cli_main, args, catch_exceptions=False)

    return result, out_path


# ---------------------------------------------------------------------------
# Test class 1: PDF path
# ---------------------------------------------------------------------------


class TestAnnotatePdfE2E:
    """Validate the full annotate pipeline with a PDF input."""

    def test_exit_code_is_zero(self, tmp_path: Path) -> None:
        stub = DeterministicStubProvider(_pdf_stub_responses())
        result, _ = _invoke_annotate(
            tmp_path, stub, input_file=_PDF_FIXTURE, output_suffix="pdf"
        )
        assert result.exit_code == 0, (
            f"Expected exit 0 but got {result.exit_code}.\nOutput:\n{result.output}"
        )

    def test_output_file_is_valid_pdf(self, tmp_path: Path) -> None:
        stub = DeterministicStubProvider(_pdf_stub_responses())
        _, out_path = _invoke_annotate(
            tmp_path, stub, input_file=_PDF_FIXTURE, output_suffix="pdf"
        )
        assert out_path.exists(), "Output PDF was not created"
        magic = out_path.read_bytes()[:4]
        assert magic == b"%PDF", f"Output file does not have PDF magic bytes: {magic!r}"

    def test_page_count_is_preserved(self, tmp_path: Path) -> None:
        stub = DeterministicStubProvider(_pdf_stub_responses())
        _, out_path = _invoke_annotate(
            tmp_path, stub, input_file=_PDF_FIXTURE, output_suffix="pdf"
        )
        original = fitz.open(str(_PDF_FIXTURE))
        annotated = fitz.open(str(out_path))
        try:
            assert annotated.page_count == original.page_count, (
                f"Page count changed: {original.page_count} → {annotated.page_count}"
            )
        finally:
            original.close()
            annotated.close()

    def test_annotated_pages_gain_vector_drawings(self, tmp_path: Path) -> None:
        """render_plan emits vector drawings; verify they appear on annotated pages."""
        stub = DeterministicStubProvider(_pdf_stub_responses())
        _, out_path = _invoke_annotate(
            tmp_path, stub, input_file=_PDF_FIXTURE, output_suffix="pdf"
        )
        original = fitz.open(str(_PDF_FIXTURE))
        annotated = fitz.open(str(out_path))
        try:
            original_drawings = sum(len(p.get_drawings()) for p in original)
            annotated_drawings = sum(len(p.get_drawings()) for p in annotated)
        finally:
            original.close()
            annotated.close()

        # Stub provides one annotation per page → renderer must add drawing paths.
        assert annotated_drawings > original_drawings, (
            f"Expected more drawings after annotation "
            f"(original {original_drawings}, annotated {annotated_drawings})"
        )

    def test_cli_output_reports_all_five_annotations_rendered(
        self, tmp_path: Path
    ) -> None:
        stub = DeterministicStubProvider(_pdf_stub_responses())
        result, _ = _invoke_annotate(
            tmp_path, stub, input_file=_PDF_FIXTURE, output_suffix="pdf"
        )
        # Exact counts from the empirically validated render path.
        assert "Rendered 5 / Skipped 0" in result.output, (
            f"Expected 'Rendered 5 / Skipped 0' in output:\n{result.output}"
        )
        assert "Done." in result.output, (
            f"Expected 'Done.' in CLI output:\n{result.output}"
        )
        assert "5 annotations" in result.output, (
            f"Expected '5 annotations' in CLI output:\n{result.output}"
        )

    def test_no_real_api_calls_are_made(self, tmp_path: Path) -> None:
        """Confirm provider call count matches page count (stub not bypassed)."""
        stub = DeterministicStubProvider(_pdf_stub_responses())
        _invoke_annotate(tmp_path, stub, input_file=_PDF_FIXTURE, output_suffix="pdf")
        # 5 pages → exactly 5 provider calls.
        assert stub._call_index == 5, (
            f"Expected 5 stub calls (one per page), got {stub._call_index}"
        )


# ---------------------------------------------------------------------------
# Test class 2: EPUB path
# ---------------------------------------------------------------------------


class TestAnnotateEpubE2E:
    """Validate the full annotate pipeline with an EPUB input."""

    def test_exit_code_is_zero(self, tmp_path: Path) -> None:
        stub = DeterministicStubProvider(_epub_stub_responses())
        result, _ = _invoke_annotate(
            tmp_path, stub, input_file=_EPUB_FIXTURE, output_suffix="epub"
        )
        assert result.exit_code == 0, (
            f"Expected exit 0 but got {result.exit_code}.\nOutput:\n{result.output}"
        )

    def test_output_file_is_valid_zip(self, tmp_path: Path) -> None:
        stub = DeterministicStubProvider(_epub_stub_responses())
        _, out_path = _invoke_annotate(
            tmp_path, stub, input_file=_EPUB_FIXTURE, output_suffix="epub"
        )
        assert out_path.exists(), "Output EPUB was not created"
        assert zipfile.is_zipfile(str(out_path)), "Output EPUB is not a valid ZIP"

    def test_output_has_correct_mimetype(self, tmp_path: Path) -> None:
        stub = DeterministicStubProvider(_epub_stub_responses())
        _, out_path = _invoke_annotate(
            tmp_path, stub, input_file=_EPUB_FIXTURE, output_suffix="epub"
        )
        with zipfile.ZipFile(str(out_path)) as zf:
            assert b"application/epub+zip" in zf.read("mimetype")

    def test_annotated_chapters_contain_hbp_css_classes(
        self, tmp_path: Path
    ) -> None:
        """Chapters where annotations resolved must contain hbp- CSS class tokens."""
        stub = DeterministicStubProvider(_epub_stub_responses())
        _, out_path = _invoke_annotate(
            tmp_path, stub, input_file=_EPUB_FIXTURE, output_suffix="epub"
        )
        annotated_chapter_names = {"ch1.xhtml", "ch2.xhtml", "ch3.xhtml"}
        with zipfile.ZipFile(str(out_path)) as zf:
            for name in zf.namelist():
                basename = name.rsplit("/", 1)[-1]
                if basename in annotated_chapter_names:
                    content = zf.read(name).decode("utf-8")
                    assert "hbp-" in content, (
                        f"Expected hbp- CSS classes in {name} but none found"
                    )

    def test_annotated_chapters_are_parseable_xhtml(self, tmp_path: Path) -> None:
        """Every annotated chapter must remain well-formed XHTML after rendering."""
        from lxml import etree

        stub = DeterministicStubProvider(_epub_stub_responses())
        _, out_path = _invoke_annotate(
            tmp_path, stub, input_file=_EPUB_FIXTURE, output_suffix="epub"
        )
        with zipfile.ZipFile(str(out_path)) as zf:
            for name in zf.namelist():
                if name.endswith(".xhtml"):
                    raw = zf.read(name)
                    try:
                        etree.fromstring(raw)
                    except etree.XMLSyntaxError as exc:
                        raise AssertionError(
                            f"EPUB chapter {name!r} is not valid XHTML after annotation: {exc}"
                        ) from exc

    def test_cli_output_reports_all_four_annotations_rendered(
        self, tmp_path: Path
    ) -> None:
        stub = DeterministicStubProvider(_epub_stub_responses())
        result, _ = _invoke_annotate(
            tmp_path, stub, input_file=_EPUB_FIXTURE, output_suffix="epub"
        )
        assert "Rendered 4 / Skipped 0" in result.output, (
            f"Expected 'Rendered 4 / Skipped 0' in output:\n{result.output}"
        )
        assert "4 annotations" in result.output, (
            f"Expected '4 annotations' in CLI output:\n{result.output}"
        )

    def test_no_real_api_calls_are_made(self, tmp_path: Path) -> None:
        stub = DeterministicStubProvider(_epub_stub_responses())
        _invoke_annotate(tmp_path, stub, input_file=_EPUB_FIXTURE, output_suffix="epub")
        # 4 EPUB pages → exactly 4 provider calls.
        assert stub._call_index == 4, (
            f"Expected 4 stub calls (one per EPUB page), got {stub._call_index}"
        )


# ---------------------------------------------------------------------------
# Test class 3: Determinism
# ---------------------------------------------------------------------------


class TestDeterminism:
    """Verify that two identical runs produce structurally equivalent output.

    fitz embeds non-deterministic /ID bytes in the PDF trailer on each save,
    so byte-level equality is intentionally NOT asserted.  The nondeterminism
    source is the two 16-byte /ID values written at file offset near EOF.
    Structural equality (page count, per-page drawing counts) is deterministic
    and is what is asserted here.
    """

    def test_pdf_byte_output_differs_between_runs(self, tmp_path: Path) -> None:
        """Document the known nondeterminism: two renders of the same plan differ."""
        responses = _pdf_stub_responses()
        out1 = tmp_path / "run1.pdf"
        out2 = tmp_path / "run2.pdf"
        fake_resolve = _build_fake_resolve(tmp_path)

        def _fake_build(config: Any, *, api_key: Any = None) -> LLMProvider:
            return DeterministicStubProvider(list(responses))

        runner = CliRunner()
        common_args = ["annotate", str(_PDF_FIXTURE)]

        with (
            patch("halfblood.cli.build_provider", _fake_build),
            patch("halfblood.cli.resolve_generation_config", fake_resolve),
        ):
            runner.invoke(
                cli_main,
                [*common_args, "-o", str(out1), "--force"],
                catch_exceptions=False,
            )
            runner.invoke(
                cli_main,
                [*common_args, "-o", str(out2), "--force"],
                catch_exceptions=False,
            )

        # Confirm the known nondeterminism (fitz /ID bytes):
        assert out1.read_bytes() != out2.read_bytes(), (
            "Unexpected: two independent fitz saves produced byte-identical PDFs. "
            "If fitz now uses a deterministic /ID, the structural-equality test "
            "below can be upgraded to byte-level comparison."
        )

    def test_pdf_structural_equality_across_runs(self, tmp_path: Path) -> None:
        """Despite byte-level nondeterminism, structure must be identical."""
        responses = _pdf_stub_responses()
        out1 = tmp_path / "run1.pdf"
        out2 = tmp_path / "run2.pdf"
        fake_resolve = _build_fake_resolve(tmp_path)

        def _fake_build(config: Any, *, api_key: Any = None) -> LLMProvider:
            return DeterministicStubProvider(list(responses))

        runner = CliRunner()
        common_args = ["annotate", str(_PDF_FIXTURE)]

        with (
            patch("halfblood.cli.build_provider", _fake_build),
            patch("halfblood.cli.resolve_generation_config", fake_resolve),
        ):
            runner.invoke(
                cli_main,
                [*common_args, "-o", str(out1), "--force"],
                catch_exceptions=False,
            )
            runner.invoke(
                cli_main,
                [*common_args, "-o", str(out2), "--force"],
                catch_exceptions=False,
            )

        doc1 = fitz.open(str(out1))
        doc2 = fitz.open(str(out2))
        try:
            assert doc1.page_count == doc2.page_count, (
                f"Page count differs: {doc1.page_count} vs {doc2.page_count}"
            )
            for page_idx in range(doc1.page_count):
                drawings1 = doc1[page_idx].get_drawings()
                drawings2 = doc2[page_idx].get_drawings()
                assert len(drawings1) == len(drawings2), (
                    f"Page {page_idx + 1}: drawing count differs "
                    f"({len(drawings1)} vs {len(drawings2)})"
                )
        finally:
            doc1.close()
            doc2.close()


# ---------------------------------------------------------------------------
# Test class 4: Failure surface
# ---------------------------------------------------------------------------


class TestFailureSurface:
    """Verify CLI behaviour under partial provider failure.

    A StructuredOutputError on the first page call (page 1) leaves pages 2–5
    un-annotated for page 1 but allows pages 2–5 to succeed.  The CLI must:
    - exit 0 (partial failure is not fatal)
    - write the output artifact
    - print a warning mentioning the failed page count
    - report the correct annotation count for surviving pages
    """

    def test_partial_failure_exits_zero(self, tmp_path: Path) -> None:
        success_response = _pdf_record(2, _PDF_PASSAGES[2])
        stub = _PartialFailureProvider(success_response)
        result, _ = _invoke_annotate(
            tmp_path, stub, input_file=_PDF_FIXTURE, output_suffix="pdf"
        )
        assert result.exit_code == 0, (
            f"Expected exit 0 for partial failure, got {result.exit_code}.\n"
            f"Output:\n{result.output}"
        )

    def test_partial_failure_still_writes_output_file(self, tmp_path: Path) -> None:
        success_response = _pdf_record(2, _PDF_PASSAGES[2])
        stub = _PartialFailureProvider(success_response)
        _, out_path = _invoke_annotate(
            tmp_path, stub, input_file=_PDF_FIXTURE, output_suffix="pdf"
        )
        assert out_path.exists(), "Output PDF must be written even when one page fails"
        assert out_path.read_bytes()[:4] == b"%PDF", "Output must be a valid PDF"

    def test_partial_failure_prints_warning(self, tmp_path: Path) -> None:
        success_response = _pdf_record(2, _PDF_PASSAGES[2])
        stub = _PartialFailureProvider(success_response)
        result, _ = _invoke_annotate(
            tmp_path, stub, input_file=_PDF_FIXTURE, output_suffix="pdf"
        )
        assert "1 page(s) failed" in result.output, (
            f"Expected '1 page(s) failed' warning in CLI output:\n{result.output}"
        )

    def test_partial_failure_reports_surviving_annotation_count(
        self, tmp_path: Path
    ) -> None:
        """Pages 2–5 each get one annotation; page 1 gets none → 4 annotations."""
        success_response = _pdf_record(2, _PDF_PASSAGES[2])
        stub = _PartialFailureProvider(success_response)
        result, _ = _invoke_annotate(
            tmp_path, stub, input_file=_PDF_FIXTURE, output_suffix="pdf"
        )
        assert "4 annotations" in result.output, (
            f"Expected '4 annotations' (pages 2-5 survived) in output:\n{result.output}"
        )

    def test_all_pages_failed_raises_click_exception(self, tmp_path: Path) -> None:
        """When every page fails AllPagesFailedError → ClickException → exit 1."""

        class _AlwaysFailProvider:
            @property
            def capabilities(self) -> ProviderCapabilities:
                return ProviderCapabilities(
                    supports_tool_calling=True,
                    supports_json_schema=True,
                    supports_strict_json_schema=True,
                )

            def complete(self, request: Any) -> GenerationResult:
                raise StructuredOutputError("stub: always fail — malformed output")

        stub = _AlwaysFailProvider()
        out_path = tmp_path / "out.pdf"
        fake_resolve = _build_fake_resolve(tmp_path)

        def _fake_build(config: Any, *, api_key: Any = None) -> LLMProvider:
            return stub

        runner = CliRunner()
        with (
            patch("halfblood.cli.build_provider", _fake_build),
            patch("halfblood.cli.resolve_generation_config", fake_resolve),
        ):
            result = runner.invoke(
                cli_main,
                [
                    "annotate",
                    str(_PDF_FIXTURE),
                    "-o",
                    str(out_path),
                    "--force",
                ],
                catch_exceptions=False,
            )

        assert result.exit_code != 0, (
            "Expected non-zero exit when every page fails, got 0"
        )
        # The ClickException message must surface the failure reason.
        assert "Error" in result.output or "error" in result.output.lower(), (
            f"Expected an error message in output:\n{result.output}"
        )
