"""Offline placement benchmark tests.

The benchmark script is a source-tree tree; these tests verify it executes
without network, against the public-domain Alice excerpt, and that every
red-capable mutation is caught. They do not exercise the resolver itself.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

from benchmarks.placement import run_benchmark
from halfblood.models.placement import (
    PlacementPoint,
    PlacementQuad,
    PlacementResult,
    PlacementStatus,
)
from halfblood.placement import resolve_epub_quote, resolve_pdf_quote

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "benchmark_placement.py"
FIXTURES = REPO / "benchmarks" / "fixtures"
MANIFEST = FIXTURES / "manifest.json"
EXPECTED = FIXTURES / "expected.json"

# Manifest's recorded sha256 for the full Alice source.
ALICE_SHA256 = "01b38ea4c710a84bc18d0bd41271a5a1a92b94e97b2812f4dece97d4a694725e"


def _run(argv: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *argv],
        capture_output=True,
        text=True,
        cwd=str(REPO),
    )


def _report() -> dict[str, object]:
    """Run the benchmark via the public API and return the parsed report."""
    return run_benchmark()


class TestBenchmarkPassesAgainstRealResolver:
    def test_green_report_via_script(self) -> None:
        proc = _run([])
        assert proc.returncode == 0, proc.stderr or proc.stdout
        report = json.loads(proc.stdout)
        assert report["passed"] is True
        assert report["totals"]["mismatches"] == 0
        assert report["totals"]["wrong_anchors"] == 0
        assert report["fixture_errors"] == []

    def test_stdout_is_pure_json_even_when_an_import_writes_to_stdout(
        self, tmp_path: Path
    ) -> None:
        """The script's contract is JSON on stdout and nothing else.

        PyMuPDF's ``fitz`` shim prints its deprecation notice to STDOUT, not
        stderr, on versions newer than the dev lock's 1.28.0. CI resolves
        pymupdf from the pyproject range, got one, and the leading warning line
        made both this test and the workflow's ``> placement-benchmark.json``
        artifact unparseable. This reproduces that by emitting the same line on
        ``import fitz``, which is where the real one fires.
        """
        sitecustomize = tmp_path / "sitecustomize.py"
        sitecustomize.write_text(
            "import sys, importlib.abc\n"
            "class _W(importlib.abc.MetaPathFinder):\n"
            "    fired = False\n"
            "    def find_spec(self, name, path, target=None):\n"
            "        if name == 'fitz' and not _W.fired:\n"
            "            _W.fired = True\n"
            "            sys.stdout.write('warning: deprecated fitz API\\n')\n"
            "        return None\n"
            "sys.meta_path.insert(0, _W())\n",
            encoding="utf-8",
        )
        env = dict(os.environ, PYTHONPATH=str(tmp_path))
        proc = subprocess.run(
            [sys.executable, str(SCRIPT)],
            capture_output=True,
            text=True,
            cwd=str(REPO),
            env=env,
        )
        assert proc.returncode == 0, proc.stderr or proc.stdout
        report = json.loads(proc.stdout)  # must not raise
        assert report["passed"] is True

    def test_green_report_via_public_api(self) -> None:
        report = _report()
        assert report["passed"] is True
        assert report["totals"]["mismatches"] == 0

    def test_all_four_statuses_observed(self) -> None:
        statuses = set(_report()["statuses"].keys())
        assert {"resolved", "ambiguous", "unresolved", "unsupported_renderer"} <= statuses

    def test_total_row_count_is_target(self) -> None:
        # 13 cases x renderer mix = 23 rows (4 positive pairs + 6 negative
        # pairs + 3 single-renderer cases).
        report = _report()
        assert report["totals"]["cases"] == 23


class TestFixtureIntegrity:
    def test_manifest_sha256_matches_disk(self) -> None:
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        for name, expected in manifest["sha256"].items():
            path = FIXTURES / name
            assert path.is_file(), f"missing fixture: {name}"
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
            assert actual == expected, f"sha256 mismatch: {name}"

    def test_alice_excerpt_is_real_public_domain_text(self) -> None:
        # Manifest records the Project Gutenberg URL and SHA-256 of the full
        # Alice source. The excerpt must be a verbatim substring of that file.
        excerpt = (FIXTURES / "alice-excerpt.txt").read_text(encoding="utf-8")
        full = (REPO / "examples" / "src" / "pg11.txt").read_text(encoding="utf-8")
        assert excerpt.rstrip("\n") in full, "alice-excerpt is not a verbatim Alice excerpt"
        # Compare bytes to avoid CRLF->LF normalization hiding a stale source.
        assert hashlib.sha256((REPO / "examples" / "src" / "pg11.txt").read_bytes()).hexdigest() == ALICE_SHA256

    def test_alice_fixture_raw_text_round_trips(self) -> None:
        # The PDF and EPUB renderers must agree on the underlying text.
        excerpt = (FIXTURES / "alice-excerpt.txt").read_text(encoding="utf-8").rstrip("\n")
        import zipfile

        import fitz
        from bs4 import BeautifulSoup, NavigableString

        with fitz.open(FIXTURES / "alice-excerpt.pdf") as doc:
            pdf_text = doc[0].get_text("text").rstrip("\n")
        with zipfile.ZipFile(FIXTURES / "alice-excerpt.epub") as archive:
            soup = BeautifulSoup(archive.read("EPUB/chapter.xhtml"), "html.parser")
            epub_text = "".join(
                str(n) for n in soup.body.descendants if isinstance(n, NavigableString)
            ).rstrip("\n")
        assert pdf_text == excerpt == epub_text

    def test_medicine_fixture_is_five_milligrams(self) -> None:
        # The five-vs-fifty crux case: source MUST contain "five milligrams"
        # and MUST NOT contain "fifty milligrams". If anyone edits this
        # fixture to soften it, this test fires.
        text = (FIXTURES / "medicine.txt").read_text(encoding="utf-8")
        assert "five milligrams" in text
        assert "fifty milligrams" not in text

    def test_candidate_limit_pdf_text_matches_checked_in(self) -> None:
        # PDF/EPUB text and the .txt fixture must agree byte-for-byte; the
        # benchmark's "input raw text differs from checked-in same-text corpus"
        # check will fire if anyone regenerates one without the others.
        import fitz

        txt = (FIXTURES / "candidate-limit.txt").read_text(encoding="utf-8")
        with fitz.open(FIXTURES / "candidate-limit.pdf") as doc:
            assert doc[0].get_text("text") == txt
        import zipfile

        from bs4 import BeautifulSoup, NavigableString

        with zipfile.ZipFile(FIXTURES / "candidate-limit.epub") as archive:
            soup = BeautifulSoup(archive.read("EPUB/chapter.xhtml"), "html.parser")
            epub_text = "".join(
                str(n) for n in soup.body.descendants if isinstance(n, NavigableString)
            )
        assert epub_text == txt


class TestScriptSafety:
    def test_no_unsafe_output_flag(self) -> None:
        proc = _run(["--help"])
        # The benchmark deliberately exposes no path-writing flag.
        assert "--output" not in proc.stdout

    def test_script_writes_only_to_stdout(self, tmp_path: Path) -> None:
        # Run inside an empty directory: nothing must land on disk besides the
        # captured stdout. Capturing `stderr` catches silent warnings too.
        proc = subprocess.run(
            [sys.executable, str(SCRIPT)],
            capture_output=True,
            text=True,
            cwd=str(tmp_path),
        )
        assert proc.returncode == 0
        assert proc.stderr == ""
        # Anything that landed in tmp_path besides pytest artefacts is a leak.
        leaks = [p for p in tmp_path.iterdir()]
        assert leaks == [], f"unexpected files in clean cwd: {leaks}"

    def test_unknown_argument_fails_cleanly(self) -> None:
        proc = _run(["--output", "/tmp/should-not-be-written.json"])
        # argparse rejects the now-removed flag with exit 2 and a useful message.
        assert proc.returncode == 2
        assert "unrecognized arguments" in proc.stderr or "unrecognized" in proc.stderr


class TestCaseCoverage:
    """One test per outcome. The test file is the oracle: if a case is silently
    dropped from the benchmark the test fails loudly."""

    # ------------------------------------------------------------------
    # POSITIVE: 8 resolved rows (4 cases x 2 renderers).
    # ------------------------------------------------------------------

    def test_alice_unique_quote_pdf(self) -> None:
        report = _report()
        case = next(r for r in report["cases"]
                    if r["id"] == "alice-excerpt-unique-quote:pdf")
        assert case["passed"] is True
        assert case["actual"]["status"] == "resolved"
        assert case["actual"]["coordinate_space"] == "pdf_display_points"
        assert len(case["actual"]["quads"]) == 1

    def test_alice_unique_quote_epub(self) -> None:
        report = _report()
        case = next(r for r in report["cases"]
                    if r["id"] == "alice-excerpt-unique-quote:epub")
        assert case["passed"] is True
        assert case["actual"]["status"] == "resolved"
        assert case["actual"]["coordinate_space"] == "epub_dom_text"
        assert len(case["actual"]["epub_segments"]) >= 1

    def test_alice_multiline_normalized_whitespace(self) -> None:
        # Selector with spaces matches across three source lines because the
        # normalizer collapses newlines. Three PDF line quads, six EPUB
        # segments (the quote crosses five inline node boundaries).
        report = _report()
        for renderer in ("pdf", "epub"):
            case = next(r for r in report["cases"]
                        if r["id"] == f"alice-multiline-normalized-whitespace:{renderer}")
            assert case["passed"] is True
            assert case["actual"]["status"] == "resolved"
            if renderer == "pdf":
                assert len(case["actual"]["quads"]) == 3
            else:
                assert len(case["actual"]["epub_segments"]) >= 3

    def test_duplicate_with_second_offset(self) -> None:
        # Two occurrences of the same exact quote; the second is anchored by
        # start_offset and end_offset. Resolver returns resolved with
        # candidate_count=2 (both occurrences seen) and raw_span at the second.
        report = _report()
        for renderer in ("pdf", "epub"):
            case = next(r for r in report["cases"]
                        if r["id"] == f"duplicate-with-second-offset:{renderer}")
            assert case["passed"] is True
            assert case["actual"]["status"] == "resolved"
            assert case["actual"]["candidate_count"] == 2
            assert case["actual"]["raw_span"] is not None

    def test_overlap_with_second_offset(self) -> None:
        # Two overlapping occurrences of "echo echo"; second anchored via offsets.
        report = _report()
        for renderer in ("pdf", "epub"):
            case = next(r for r in report["cases"]
                        if r["id"] == f"overlap-with-second-offset:{renderer}")
            assert case["passed"] is True
            assert case["actual"]["status"] == "resolved"
            assert case["actual"]["candidate_count"] == 2

    # ------------------------------------------------------------------
    # NEGATIVE: 15 refusal rows.
    # ------------------------------------------------------------------

    def test_duplicate_no_offset_is_ambiguous(self) -> None:
        report = _report()
        for renderer in ("pdf", "epub"):
            case = next(r for r in report["cases"]
                        if r["id"] == f"duplicate-no-offset:{renderer}")
            assert case["passed"] is True
            assert case["actual"]["status"] == "ambiguous"
            assert case["actual"]["candidate_count"] == 2

    def test_overlap_no_offset_is_ambiguous(self) -> None:
        report = _report()
        for renderer in ("pdf", "epub"):
            case = next(r for r in report["cases"]
                        if r["id"] == f"overlap-no-offset:{renderer}")
            assert case["passed"] is True
            assert case["actual"]["status"] == "ambiguous"
            assert case["actual"]["candidate_count"] == 2

    def test_medicine_five_vs_fifty_strict_refusal(self) -> None:
        # The crux case: source has "five milligrams"; selector substitutes
        # "fifty" in the LATE SUFFIX position. Baseline prefix recovery
        # cannot rescue this. Resolver must refuse with quote_not_found.
        report = _report()
        for renderer in ("pdf", "epub"):
            case = next(r for r in report["cases"]
                        if r["id"] == f"medicine-five-vs-fifty-strict-refusal:{renderer}")
            assert case["passed"] is True
            assert case["actual"]["status"] == "unresolved"
            assert case["actual"]["reason"] == "quote_not_found"
            assert case["actual"]["candidate_count"] == 0
            # Crucially no partial evidence leaks.
            assert case["actual"].get("quads") == []
            assert case["actual"].get("epub_segments") == []

    def test_alice_strict_5vs50_refusal_first_word_drift(self) -> None:
        # Distinct from the medicine case: drift is in the FIRST word
        # ("hill" vs "hole"). Both refusal cases together exercise drift in
        # both prefix and suffix positions.
        report = _report()
        for renderer in ("pdf", "epub"):
            case = next(r for r in report["cases"]
                        if r["id"] == f"alice-strict-5vs50-refusal:{renderer}")
            assert case["passed"] is True
            assert case["actual"]["status"] == "unresolved"
            assert case["actual"]["reason"] == "quote_not_found"
            assert case["actual"]["candidate_count"] == 0

    def test_alice_selector_hints_mismatch(self) -> None:
        # Unique hit, but the supplied prefix hint does not match the
        # surrounding text. Resolver must refuse.
        report = _report()
        for renderer in ("pdf", "epub"):
            case = next(r for r in report["cases"]
                        if r["id"] == f"alice-selector-hints-mismatch:{renderer}")
            assert case["passed"] is True
            assert case["actual"]["status"] == "unresolved"
            assert case["actual"]["reason"] == "selector_hints_mismatch"

    def test_candidate_limit_exceeded(self) -> None:
        # More than MAX_CANDIDATES (500) overlapping occurrences of "echo echo"
        # on the source page. Resolver must refuse with candidate_limit_exceeded.
        report = _report()
        for renderer in ("pdf", "epub"):
            case = next(r for r in report["cases"]
                        if r["id"] == f"candidate-limit-exceeded:{renderer}")
            assert case["passed"] is True
            assert case["actual"]["status"] == "unresolved"
            assert case["actual"]["reason"] == "candidate_limit_exceeded"
            assert case["actual"]["candidate_count"] == 0

    def test_fixed_layout_epub_is_unsupported(self) -> None:
        report = _report()
        case = next(r for r in report["cases"]
                    if r["id"] == "alice-fixed-layout-unsupported:epub")
        assert case["passed"] is True
        assert case["actual"]["status"] == "unsupported_renderer"
        assert case["actual"]["reason"] == "fixed_layout_unsupported"

    def test_no_text_layer_pdf(self) -> None:
        report = _report()
        case = next(r for r in report["cases"]
                    if r["id"] == "no-text-layer-pdf:pdf")
        assert case["passed"] is True
        assert case["actual"]["status"] == "unresolved"
        assert case["actual"]["reason"] == "quote_not_found"

    def test_source_limit_epub(self) -> None:
        report = _report()
        case = next(r for r in report["cases"]
                    if r["id"] == "source-limit-input-limit-exceeded:epub")
        assert case["passed"] is True
        assert case["actual"]["status"] == "unresolved"
        assert case["actual"]["reason"] == "input_limit_exceeded"


class TestParityAndCoverage:
    def test_parity_pairs_match(self) -> None:
        # For every case with both PDF and EPUB results, the four identity
        # fields must agree (same text evidence, same candidate count,
        # same status).
        report = _report()
        for row in report["parity"]:
            assert row["passed"], f"parity mismatch for {row['id']}"

    def test_no_missing_statuses(self) -> None:
        report = _report()
        assert report["missing_statuses"] == []


# ---------------------------------------------------------------------------
# Red-capable mutation tests.
#
# Each mutation wraps the real resolver and corrupts a single field of its
# returned record. The benchmark, run with the wrapped resolver injected, must
# report at least one mismatch per mutation. If any mutation slips through
# the benchmark is missing that defence and the test fails loudly.
# ---------------------------------------------------------------------------


def _pdf_omit_quads(page, selector):
    result = resolve_pdf_quote(page, selector)
    data = result.model_dump(mode="json")
    if data.get("status") == "resolved":
        data["quads"] = []
        return PlacementResult(**data)
    return result


def _pdf_wrong_raw_span(page, selector):
    result = resolve_pdf_quote(page, selector)
    data = result.model_dump(mode="json")
    if data.get("status") == "resolved" and data.get("raw_span"):
        data["raw_span"] = [data["raw_span"][0] + 1, data["raw_span"][1] + 1]
        return PlacementResult(**data)
    return result


def _pdf_wrong_coordinate_space(page, selector):
    result = resolve_pdf_quote(page, selector)
    data = result.model_dump(mode="json")
    if data.get("status") == "resolved":
        data["coordinate_space"] = "epub_dom_text"
        return PlacementResult(**data)
    return result


def _pdf_relabel_ambiguous(page, selector):
    result = resolve_pdf_quote(page, selector)
    data = result.model_dump(mode="json")
    if data.get("status") == "ambiguous":
        data["status"] = PlacementStatus.RESOLVED
        data["reason"] = "stolen"
        return PlacementResult(**data)
    return result


def _epub_empty_segments(root, selector, **kwargs):
    result = resolve_epub_quote(root, selector, **kwargs)
    data = result.model_dump(mode="json")
    if data.get("status") == "resolved":
        data["epub_segments"] = []
        return PlacementResult(**data)
    return result


def _epub_invent_quads(root, selector, **kwargs):
    result = resolve_epub_quote(root, selector, **kwargs)
    data = result.model_dump(mode="json")
    if data.get("status") == "resolved":
        data["quads"] = (PlacementQuad(
            ul=PlacementPoint(x=0.0, y=0.0),
            ur=PlacementPoint(x=1.0, y=0.0),
            lr=PlacementPoint(x=1.0, y=1.0),
            ll=PlacementPoint(x=0.0, y=1.0),
        ),)
        return PlacementResult(**data)
    return result


def _epub_relabel_unsupported(root, selector, **kwargs):
    result = resolve_epub_quote(root, selector, **kwargs)
    data = result.model_dump(mode="json")
    if data.get("status") == "unsupported_renderer":
        data["status"] = PlacementStatus.RESOLVED
        data["reason"] = "stolen"
        return PlacementResult(**data)
    return result


def _epub_zero_candidate_count(root, selector, **kwargs):
    result = resolve_epub_quote(root, selector, **kwargs)
    data = result.model_dump(mode="json")
    if data.get("status") == "resolved":
        data["candidate_count"] = 0
        return PlacementResult(**data)
    return result


class TestRedMutations:
    """Each test wraps one resolver and asserts the benchmark catches the defect."""

    def _run_with(self, pdf_fn, epub_fn) -> dict[str, object]:
        return run_benchmark(pdf_resolver=pdf_fn, epub_resolver=epub_fn)

    def _assert_caught(self, report: dict[str, object], name: str) -> None:
        assert report["passed"] is False, f"mutation {name} slipped through the benchmark"
        assert report["totals"]["mismatches"] > 0 or report["totals"]["wrong_anchors"] > 0, (
            f"mutation {name} did not register any mismatch or wrong-anchor"
        )

    def test_pdf_omit_quads(self) -> None:
        report = self._run_with(_pdf_omit_quads, resolve_epub_quote)
        self._assert_caught(report, "pdf-omit-quads")

    def test_pdf_wrong_raw_span(self) -> None:
        report = self._run_with(_pdf_wrong_raw_span, resolve_epub_quote)
        self._assert_caught(report, "pdf-wrong-raw-span")

    def test_pdf_wrong_coordinate_space(self) -> None:
        report = self._run_with(_pdf_wrong_coordinate_space, resolve_epub_quote)
        self._assert_caught(report, "pdf-wrong-coordinate-space")

    def test_pdf_relabel_ambiguous_resolved(self) -> None:
        report = self._run_with(_pdf_relabel_ambiguous, resolve_epub_quote)
        self._assert_caught(report, "pdf-relabel-ambiguous-resolved")

    def test_epub_empty_segments(self) -> None:
        report = self._run_with(resolve_pdf_quote, _epub_empty_segments)
        self._assert_caught(report, "epub-empty-segments")

    def test_epub_invent_pdf_quads(self) -> None:
        report = self._run_with(resolve_pdf_quote, _epub_invent_quads)
        self._assert_caught(report, "epub-invent-pdf-quads")

    def test_epub_relabel_unsupported_resolved(self) -> None:
        report = self._run_with(resolve_pdf_quote, _epub_relabel_unsupported)
        self._assert_caught(report, "epub-relabel-unsupported-resolved")

    def test_epub_zero_candidate_count(self) -> None:
        report = self._run_with(resolve_pdf_quote, _epub_zero_candidate_count)
        self._assert_caught(report, "epub-zero-candidate-count")
