"""P2-T9 — Phase 2 regression guards and CLI render-summary coverage (fold-in #4).

These tests pin end-to-end behaviors that must not regress as P2-T9 wires
``EpubProcessor.render_plan``:

1. **Format regression** — the same ``render_plan`` contract holds for both
   PDF (``DocumentProcessor``) and EPUB (``EpubProcessor``); a unique exact
   target produces a non-empty rendered partition in both formats.

2. **CLI render-summary coverage** — the ``annotate`` command must print
   "Rendered N / Skipped M" for EPUB inputs, mirroring the PDF path.

No network calls are made anywhere in this file.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

import halfblood.cli as cli_module
from halfblood.config import ResolvedConfig
from halfblood.document_processor import DocumentProcessor, PageContent
from halfblood.epub_processor import EpubProcessor
from halfblood.models import AnnotatedPage, Annotation, AnnotationPlan, AnnotationType
from halfblood.models.annotations import Annotation as V2Annotation
from halfblood.models.annotations import MarkIntent, TargetSelector
from halfblood.models.documents import AnnotationPlan as V2Plan
from halfblood.models.documents import GenerationProvenance, SourceInfo, Unit
from halfblood.models.rendering import DegradationFlag, RenderReport

_FIXTURES = Path(__file__).parent / "fixtures"
_PDF_FIXTURE = _FIXTURES / "potions_textbook.pdf"
_EPUB_FIXTURE = _FIXTURES / "sample_book.epub"

_FINGERPRINT = "b" * 64


# ---------------------------------------------------------------------------
# V2 plan helpers (mirrors test_epub_render_report.py's helpers)
# ---------------------------------------------------------------------------


def _v2_ann(ann_id: str, exact: str) -> V2Annotation:
    return V2Annotation(
        id=ann_id,
        target=TargetSelector(exact=exact),
        annotation_type=AnnotationType.INSIGHT,
        content="Commentary.",
        confidence=0.9,
        requested_placement="margin_right",
        mark_intent=MarkIntent.CIRCLE,
    )


def _v2_plan(ordinal: int, ann_id: str, exact: str) -> V2Plan:
    return V2Plan(
        id="regression-plan-id",
        title="Regression Plan",
        persona="Snape",
        source=SourceInfo(
            fingerprint=_FINGERPRINT,
            media_type="test",
            unit_count=1,
        ),
        generation=GenerationProvenance(),
        document_seed=99,
        units=[
            Unit(
                unit_id=f"unit-{ordinal}",
                ordinal=ordinal,
                label=f"Page {ordinal}",
                original_text="",
                source_locator=f"page:{ordinal}",
                annotations=[_v2_ann(ann_id, exact)],
            )
        ],
    )


# ---------------------------------------------------------------------------
# 1. Format regression — render_plan contract holds for both PDF and EPUB
# ---------------------------------------------------------------------------


def test_pdf_render_plan_finds_unique_target(tmp_path: Path) -> None:
    """PDF render_plan is the reference baseline — this test must stay green."""
    plan = _v2_plan(1, "pdf-unique", "discipline of exactitude")
    processor = DocumentProcessor(seed=1)
    report = processor.render_plan(str(_PDF_FIXTURE), plan, str(tmp_path / "out.pdf"))
    assert isinstance(report, RenderReport)
    assert report.rendered_count >= 1, "unique PDF target must appear in rendered"


def test_epub_render_plan_finds_unique_target(tmp_path: Path) -> None:
    """EPUB render_plan (P2-T9) must offer the same rendered-count guarantee.

    Fails before P2-T9 because ``EpubProcessor`` has no ``render_plan`` method.
    Passes once Codex adds the method and it correctly locates the target.
    """
    # "unburnt carbon particles" appears once on chapter 2 of the sample EPUB.
    # Nav counts as spine page 1 (EbookLib bug), so ch1 (Combustion) = page 2.
    plan = _v2_plan(2, "epub-unique", "unburnt carbon particles")
    processor = EpubProcessor(seed=1)
    report = processor.render_plan(str(_EPUB_FIXTURE), plan, str(tmp_path / "out.epub"))
    assert isinstance(report, RenderReport)
    assert report.rendered_count >= 1, "unique EPUB target must appear in rendered"


# ---------------------------------------------------------------------------
# 2. CLI render-summary coverage — fold-in #4 (P2-T8 gap closed)
# ---------------------------------------------------------------------------

_FAKE_CLI_SOURCES: dict[str, str] = {
    "provider": "default",
    "model": "cli",
    "base_url": "preset",
    "api_key_env": "preset",
    "structured_output": "preset",
    "timeout_seconds": "default",
    "max_retries": "default",
    "concurrency": "default",
    "allow_insecure_http": "default",
}

_FAKE_CLI_CONFIG = ResolvedConfig(
    provider="anthropic",
    model="claude-sonnet-5",
    base_url="https://api.anthropic.com",
    api_key_env="ANTHROPIC_API_KEY",
    structured_output="tool",
    timeout_seconds=60.0,
    max_retries=0,
    concurrency=3,
    allow_insecure_http=False,
    sources=_FAKE_CLI_SOURCES,
)


class _FakeProviderCapabilities:
    tool_use = True
    streaming = False


class _FakeLLMProvider:
    @property
    def capabilities(self):
        return _FakeProviderCapabilities()

    def complete(self, request):
        raise AssertionError("provider.complete must not be called — generator is faked")


class _FakeGenerator:
    def __init__(
        self,
        persona: str | None = None,
        model: str | None = None,
        provider: object | None = None,
        concurrency: int = 3,
    ) -> None:
        self.failed_pages: list[int] = []

    def generate_for_document(
        self, pages: list[PageContent], max_annotations_per_page: int = 5
    ) -> AnnotationPlan:
        # One annotation per page so migrate_v1_to_v2 has something to work with.
        return AnnotationPlan(
            title="fake plan",
            prince_persona="p",
            pages=[
                AnnotatedPage(
                    page_number=p.page_number,
                    original_text=p.text,
                    annotations=[
                        Annotation(
                            page=p.page_number,
                            target_text="bezoar",
                            annotation_type=AnnotationType.INSIGHT,
                            content="Obvious.",
                            confidence=0.9,
                            position="margin_right",
                        )
                    ],
                )
                for p in pages
            ],
        )


class _FakePdfProcessor:
    def load(self, path: str) -> list[PageContent]:
        return [PageContent(page_number=1, text="some page text", width=612.0, height=792.0)]

    def render_annotations(
        self, input_path: str, annotations: list, output_path: str
    ) -> None:
        Path(output_path).write_text("rendered-pdf", encoding="utf-8")

    def annotations_from_plan(self, plan: AnnotationPlan) -> list:
        return [a for page in plan.pages for a in page.annotations]

    def render_plan(self, input_path: str, plan: V2Plan, output_path: str) -> RenderReport:
        Path(output_path).write_text("rendered-pdf", encoding="utf-8")
        return RenderReport(rendered=("pdf-ann-1",))


class _FakeEpubProcessorWithReport:
    """Fake EpubProcessor that includes a render_plan method returning a report.

    Before Codex wires the CLI to call render_plan for EPUB, the CLI's
    ``isinstance(processor, DocumentProcessor)`` check causes it to skip the
    render_plan branch — so even though THIS fake has render_plan, the CLI
    calls render_annotations instead (report = None → no summary printed).
    The test fails for that reason and stays a valid failing test until the
    CLI condition is fixed.
    """

    def load(self, path: str) -> list[PageContent]:
        return [PageContent(page_number=1, text="chapter text", width=600.0, height=800.0)]

    def render_annotations(
        self, input_path: str, annotations: list, output_path: str
    ) -> None:
        Path(output_path).write_text("rendered-epub", encoding="utf-8")

    def render_plan(self, input_path: str, plan: V2Plan, output_path: str) -> RenderReport:
        Path(output_path).write_text("rendered-epub", encoding="utf-8")
        return RenderReport(
            rendered=("epub-ann-1",),
            degradation_flags=(DegradationFlag.EPUB_NO_TARGET_GEOMETRY,),
        )


@pytest.fixture()
def regression_fakes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Patch CLI-level names so no real API, PDF, or EPUB processing occurs."""
    monkeypatch.setattr(cli_module, "DocumentProcessor", _FakePdfProcessor)
    monkeypatch.setattr(cli_module, "EpubProcessor", _FakeEpubProcessorWithReport)
    monkeypatch.setattr(cli_module, "AnnotationGenerator", _FakeGenerator)
    monkeypatch.setattr(
        cli_module, "resolve_generation_config", lambda *a, **k: _FAKE_CLI_CONFIG
    )
    monkeypatch.setattr(
        cli_module, "build_provider", lambda *a, **k: _FakeLLMProvider()
    )


_ZIP_MAGIC = b"PK\x03\x04" + b"\x00" * 32


def test_cli_annotate_prints_render_summary_for_epub(
    regression_fakes: None,
    tmp_path: Path,
) -> None:
    """The annotate command must print "Rendered N / Skipped M" for EPUB inputs.

    Currently the CLI branch ``isinstance(processor, DocumentProcessor) and
    hasattr(processor, "render_plan")`` is False for EpubProcessor, so the
    else branch runs, report=None, and no summary is printed.  This test fails
    until Codex removes the isinstance guard so EPUB reaches render_plan too.
    """
    src = tmp_path / "book.epub"
    src.write_bytes(_ZIP_MAGIC)
    out = tmp_path / "book-out.epub"

    runner = CliRunner()
    result = runner.invoke(cli_module.main, ["annotate", str(src), "-o", str(out)])

    assert result.exit_code == 0, f"CLI exited {result.exit_code}:\n{result.output}"
    assert "Rendered" in result.output, (
        "CLI must print render summary for EPUB inputs; "
        f"got:\n{result.output}"
    )
