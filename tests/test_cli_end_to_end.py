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
* Two PDF targets resolve uniquely; three repeated short quotes are refused as ambiguous.
* All four EPUB_PASSAGES targets resolve in sample_book.epub (rendered_count==4).
* fitz writes non-deterministic /ID bytes into the PDF trailer; byte-level
  equality fails reliably.  Structural equality (page count + per-page drawing
  counts) is the correct determinism assertion.

Stub design (post-merge hardening, 2026-07-23):

* Stubs key responses by PAGE IDENTITY (page number extracted from the
  ``PAGE NUMBER: N`` line in ``request.user_prompt``), not call order.  Under
  concurrent wave execution (default concurrency=3) three threads may call
  ``complete()`` simultaneously; order-based routing races and can deliver the
  wrong passage to the wrong page, causing ``Rendered 5 / Skipped 0``
  assertions to fail nondeterministically.  Page-identity routing is immune to
  this: each page always receives its own scripted response regardless of
  scheduling.
* ``_PartialFailureProvider`` fails a specific PAGE by identity (``fail_page``
  parameter, default 1), not "the first call".  Two threads processing pages
  simultaneously cannot both claim "first call"; with identity routing there is
  no shared mutable dispatch state to race on.
* ``DeterministicStubProvider.call_count`` is the only shared mutable counter
  and is protected by ``_lock`` for safe post-run assertion from the main
  thread.
"""

from __future__ import annotations

import json
import threading
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

# One target per PDF page: pages 2, 4, and 5 deliberately repeat and must refuse.
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


def _extract_page_num(request: Any) -> int | None:
    """Extract the page number from ``request.user_prompt``.

    ``AnnotationGenerator._build_user_prompt`` always emits a
    ``PAGE NUMBER: N`` line at the top of the user prompt.  Parse it so
    stubs can route responses by page identity, not call order.
    """
    user_prompt = getattr(request, "user_prompt", "")
    for line in user_prompt.splitlines():
        if line.startswith("PAGE NUMBER:"):
            return int(line.split(":", 1)[1].strip())
    return None


class DeterministicStubProvider:
    """LLMProvider that scripts per-page responses keyed by page number.

    ``responses`` maps ``page_number`` → ``RecordAnnotations``.  Page number
    is extracted from the ``PAGE NUMBER: N`` line in ``request.user_prompt``
    so the mapping is order-independent and race-free under concurrent wave
    execution (concurrency > 1).

    Thread-safe: ``_lock`` guards ``call_count`` so the post-run assertion
    can read it safely from the main thread.
    """

    def __init__(self, responses: dict[int, RecordAnnotations]) -> None:
        self._responses = dict(responses)
        self._lock = threading.Lock()
        self.call_count: int = 0

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            supports_tool_calling=True,
            supports_json_schema=True,
            supports_strict_json_schema=True,
        )

    def complete(self, request: Any) -> GenerationResult:
        page_num = _extract_page_num(request)
        if page_num is None or page_num not in self._responses:
            raise AssertionError(
                f"DeterministicStubProvider: no scripted response for "
                f"page_num={page_num!r} (have: {sorted(self._responses)})"
            )
        with self._lock:
            self.call_count += 1
        return GenerationResult(
            parsed=self._responses[page_num],
            request_id=f"stub-req-pg{page_num}",
            finish_reason="stop",
            usage=GenerationUsage(input_tokens=120, output_tokens=60),
            latency_seconds=0.001,
            structured_output_mode="tool",
        )


class _PartialFailureProvider:
    """Provider that raises StructuredOutputError for one specific page only.

    ``fail_page`` names the page (by page number) whose response is malformed.
    All other pages succeed.  Keying on page identity (not call order) makes
    the stub race-free under concurrent wave execution: two threads processing
    pages simultaneously each see the correct behaviour for their own page
    regardless of scheduling.

    Using StructuredOutputError (retryable=False) is faithful to the brief
    ("a page's completion is malformed") and decouples the test from any
    future retry-on-transient layer.
    """

    def __init__(self, success_response: RecordAnnotations, *, fail_page: int = 1) -> None:
        self._success = success_response
        self._fail_page = fail_page

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            supports_tool_calling=True,
            supports_json_schema=True,
            supports_strict_json_schema=True,
        )

    def complete(self, request: Any) -> GenerationResult:
        page_num = _extract_page_num(request)
        if page_num == self._fail_page:
            raise StructuredOutputError(
                f"stub: simulated malformed output for page {page_num}",
            )
        return GenerationResult(
            parsed=self._success,
            request_id=f"stub-req-pg{page_num}",
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


def _pdf_stub_responses() -> dict[int, RecordAnnotations]:
    """Five scripted responses keyed by page number (1–5)."""
    return {pg: _pdf_record(pg, text) for pg, text in _PDF_PASSAGES.items()}


def _epub_stub_responses() -> dict[int, RecordAnnotations]:
    """Four scripted responses keyed by page number (1–4)."""
    return {pg: _epub_record(pg, text) for pg, text in _EPUB_PASSAGES.items()}


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

    def test_cli_reports_unique_quotes_and_refuses_repeated_quotes(
        self, tmp_path: Path
    ) -> None:
        stub = DeterministicStubProvider(_pdf_stub_responses())
        result, output = _invoke_annotate(
            tmp_path, stub, input_file=_PDF_FIXTURE, output_suffix="pdf"
        )
        assert "Rendered 2 / Skipped 3" in result.output, result.output
        report = json.loads(Path(str(output) + ".report.json").read_text())["render"]
        assert [(p["source_locator"], p["result"]["status"], p["result"]["candidate_count"])
                for p in report["placements"]] == [
            ("page:1", "resolved", 1), ("page:2", "ambiguous", 2),
            ("page:3", "resolved", 1), ("page:4", "ambiguous", 2),
            ("page:5", "ambiguous", 4),
        ]
        assert {s["reason"] for s in report["skipped"]} == {"ambiguous_target"}
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
        assert stub.call_count == 5, (
            f"Expected 5 stub calls (one per page), got {stub.call_count}"
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
        assert stub.call_count == 4, (
            f"Expected 4 stub calls (one per EPUB page), got {stub.call_count}"
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
            return DeterministicStubProvider(dict(responses))

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
            return DeterministicStubProvider(dict(responses))

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
