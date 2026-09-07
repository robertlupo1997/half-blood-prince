"""Independent, checked-answer quote-placement benchmark.

Expected answers come only from fixtures/expected.json. The PDF glyph oracle
reads PyMuPDF rawdict directly; it never asks the placement resolver for truth.
"""
from __future__ import annotations

import hashlib
import json
import math
import zipfile
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Any

import fitz
from bs4 import BeautifulSoup, NavigableString, Tag

from halfblood.models.annotations import TargetSelector
from halfblood.placement import resolve_epub_quote, resolve_pdf_quote

FIXTURES = Path(__file__).resolve().parent / "fixtures"
STATUSES = {"resolved", "ambiguous", "unresolved", "unsupported_renderer"}
TOLERANCE = 0.002  # PDF extraction uses float32 coordinates, measured in points.
Resolver = Callable[..., Any]


def _pdf_oracle(page: fitz.Page) -> tuple[str, list[dict[str, Any]]]:
    """Read original glyphs and line bounds without any project index/matcher."""
    chars: list[str] = []
    lines: list[dict[str, Any]] = []
    for block in page.get_text("rawdict")["blocks"]:
        if block.get("type") != 0:
            continue
        for line in block["lines"]:
            glyphs: list[dict[str, Any]] = []
            for span in line["spans"]:
                for char in span["chars"]:
                    start = len(chars)
                    chars.extend(char["c"])
                    glyphs.append({"start": start, "end": len(chars), "bbox": char["bbox"]})
            lines.append({"glyphs": glyphs})
            chars.append("\n")
    return "".join(chars), lines


def _union(boxes: list[list[float]]) -> list[float]:
    return [min(b[0] for b in boxes), min(b[1] for b in boxes),
            max(b[2] for b in boxes), max(b[3] for b in boxes)]


def _selected_boxes(lines: list[dict[str, Any]], span: list[int]) -> list[list[float]]:
    boxes: list[list[float]] = []
    for line in lines:
        selected = [g["bbox"] for g in line["glyphs"]
                    if g["start"] >= span[0] and g["end"] <= span[1]]
        if selected:
            boxes.append(_union(selected))
    return boxes


def _boxes_equal(actual: list[list[float]], expected: list[list[float]]) -> bool:
    return len(actual) == len(expected) and all(
        len(a) == 4 and all(math.isfinite(x) and abs(x - y) <= TOLERANCE
                           for x, y in zip(a, b, strict=True))
        for a, b in zip(actual, expected, strict=True)
    )


def _quad_boxes(actual: dict[str, Any]) -> list[list[float]]:
    return [_union([[quad[corner]["x"], quad[corner]["y"],
                     quad[corner]["x"], quad[corner]["y"]]
                    for corner in ("ul", "ur", "lr", "ll")])
            for quad in actual.get("quads", [])]


def _epub_root(path: Path, chapter: str) -> Tag:
    with zipfile.ZipFile(path) as archive:
        soup = BeautifulSoup(archive.read(chapter), "html.parser")
    assert isinstance(soup.body, Tag), "fixture EPUB must have a body"
    return soup.body


def _as_json(result: Any) -> dict[str, Any]:
    if isinstance(result, dict):
        return json.loads(json.dumps(result))
    return result.model_dump(mode="json")


def _check_result(
    case: dict[str, Any], renderer: str, actual: dict[str, Any],
    raw_text: str, lines: list[dict[str, Any]], nodes: list[str],
) -> tuple[list[str], dict[str, Any]]:
    expected = case["expected"]
    errors: list[str] = []
    evidence: dict[str, Any] = {}
    for field in ("status", "reason", "candidate_count"):
        if actual.get(field) != expected[field]:
            errors.append(f"{field}: expected {expected[field]!r}, got {actual.get(field)!r}")
    if actual.get("renderer") != renderer:
        errors.append("renderer label differs from input")
    if expected["status"] != "resolved":
        for field in ("raw_span", "matched_text", "coordinate_space"):
            if actual.get(field) is not None:
                errors.append(f"refusal must not carry {field}")
        for field in ("quads", "epub_segments"):
            if actual.get(field):
                errors.append(f"refusal must not carry {field}")
        return errors, evidence

    expected_span = expected["raw_span"]
    evidence["independent_raw_slice"] = raw_text[slice(*expected_span)]
    if evidence["independent_raw_slice"] != expected["matched_text"]:
        errors.append("checked-in expected span does not select the checked-in expected text")
    for field in ("raw_span", "matched_text"):
        if actual.get(field) != expected[field]:
            errors.append(f"{field}: expected {expected[field]!r}, got {actual.get(field)!r}")
    if renderer == "pdf":
        oracle_boxes = _selected_boxes(lines, expected_span)
        evidence["independent_glyph_bboxes"] = oracle_boxes
        if not _boxes_equal(oracle_boxes, expected["pdf_bboxes"]):
            errors.append("PDF fixture glyph positions differ from checked-in oracle")
        actual_boxes = _quad_boxes(actual)
        evidence["actual_quad_bboxes"] = actual_boxes
        if not _boxes_equal(actual_boxes, expected["pdf_bboxes"]):
            errors.append("PDF geometry does not equal checked-in selected-glyph bounds")
        if actual.get("coordinate_space") != "pdf_display_points":
            errors.append("resolved PDF must label display-point geometry")
        if actual.get("epub_segments"):
            errors.append("PDF result contains EPUB node references")
    else:
        segments = actual.get("epub_segments", [])
        if segments != expected["epub_segments"]:
            errors.append("EPUB raw node slices differ from checked-in slices")
        selected: list[str] = []
        for segment in segments:
            if (segment["run_index"] != 0 or not 0 <= segment["node_index"] < len(nodes)):
                errors.append("EPUB segment points outside the fixture inline run")
                continue
            node = nodes[segment["node_index"]]
            if not 0 <= segment["start"] < segment["end"] <= len(node):
                errors.append("EPUB segment has invalid node bounds")
                continue
            selected.append(node[segment["start"]:segment["end"]])
        evidence["independent_segment_text"] = "".join(selected)
        if evidence["independent_segment_text"] != expected["matched_text"]:
            errors.append("EPUB segments do not reconstruct the expected complete quotation")
        if actual.get("coordinate_space") != "epub_dom_text":
            errors.append("reflowable EPUB must label logical DOM text, not physical geometry")
        if actual.get("quads"):
            errors.append("reflowable EPUB must not invent page geometry")
    return errors, evidence


def run_benchmark(
    *, pdf_resolver: Resolver = resolve_pdf_quote, epub_resolver: Resolver = resolve_epub_quote,
    fixture_dir: Path = FIXTURES,
) -> dict[str, Any]:
    """Return a deterministic report. Resolver injection tests that bad anchors fail."""
    manifest = json.loads((fixture_dir / "manifest.json").read_text(encoding="utf-8"))
    cases = json.loads((fixture_dir / "expected.json").read_text(encoding="utf-8"))["cases"]
    fixture_errors: list[str] = []
    for name, digest in manifest["sha256"].items():
        path = fixture_dir / name
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            fixture_errors.append(f"fixture SHA-256 mismatch: {name}")
    results: list[dict[str, Any]] = []
    parity: list[dict[str, Any]] = []
    for case in cases:
        fixture = manifest["fixtures"][case["fixture"]]
        expected_raw = ((fixture_dir / fixture["text"]).read_text(encoding="utf-8")
                        if "text" in fixture else "")
        pair: list[dict[str, Any]] = []
        for renderer in case["renderers"]:
            actual: dict[str, Any] = {}
            errors: list[str] = []
            evidence: dict[str, Any] = {}
            try:
                selector = TargetSelector(**case["selector"])
                nodes: list[str] = []
                lines: list[dict[str, Any]] = []
                if renderer == "pdf":
                    with fitz.open(fixture_dir / fixture["pdf"]) as doc:
                        raw, lines = _pdf_oracle(doc[0])
                        if raw != doc[0].get_text("text"):
                            errors.append("independent glyph stream differs from PDF text extraction")
                        actual = _as_json(pdf_resolver(doc[0], selector))
                else:
                    root = _epub_root(fixture_dir / fixture["epub"], fixture["chapter"])
                    nodes = [str(n) for n in root.descendants if isinstance(n, NavigableString)]
                    raw = "".join(nodes)
                    actual = _as_json(epub_resolver(
                        root, selector, fixed_layout=case.get("fixed_layout", False)))
                if raw != expected_raw:
                    errors.append("input raw text differs from checked-in same-text corpus")
                checks, evidence = _check_result(case, renderer, actual, raw, lines, nodes)
                errors.extend(checks)
            except Exception as exc:  # A benchmark must report a failing case, not lose all evidence.
                errors.append(f"{type(exc).__name__}: {exc}")
            row = {
                "id": f"{case['id']}:{renderer}", "fixture": case["fixture"],
                "renderer": renderer, "selector": case["selector"], "expected": case["expected"],
                "actual": actual, "evidence": evidence, "passed": not errors, "errors": errors,
            }
            results.append(row)
            pair.append(row)
        if len(pair) == 2:
            fields = ("status", "raw_span", "matched_text", "candidate_count")
            same = all(pair[0]["actual"].get(f) == pair[1]["actual"].get(f) for f in fields)
            same = same and all(row["actual"] for row in pair)
            parity.append({"id": case["id"], "passed": bool(same), "compared_fields": list(fields)})

    statuses = Counter(row["actual"].get("status", "exception") for row in results)
    missing_statuses = sorted(STATUSES - statuses.keys())
    correct_resolutions = sum(row["passed"] and row["actual"]["status"] == "resolved"
                              for row in results)
    correct_refusals = sum(row["passed"] and row["actual"]["status"] != "resolved"
                           for row in results)
    wrong_anchors = sum(not row["passed"] and row["actual"].get("status") == "resolved"
                        for row in results)
    mismatches = sum(not row["passed"] for row in results)
    parity_mismatches = sum(not row["passed"] for row in parity)
    return {
        "schema_version": 1,
        "benchmark": "offline-evidence-placement",
        "scope": manifest["scope"],
        "source": manifest["source"],
        "passed": not (mismatches or fixture_errors or missing_statuses or parity_mismatches),
        "totals": {"cases": len(results), "correct_resolutions": correct_resolutions,
                   "correct_refusals": correct_refusals, "wrong_anchors": wrong_anchors,
                   "mismatches": mismatches, "parity_pairs": len(parity),
                   "parity_matches": len(parity) - parity_mismatches,
                   "parity_mismatches": parity_mismatches},
        "statuses": dict(sorted(statuses.items())),
        "missing_statuses": missing_statuses,
        "fixture_errors": fixture_errors,
        "cases": results,
        "parity": parity,
    }
