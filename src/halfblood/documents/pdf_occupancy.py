"""PDF text-layer extraction for page occupancy and body columns."""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass
from statistics import median
from typing import Any

import fitz

from halfblood.layout.occupancy import PageOccupancy, TextColumn
from halfblood.models.rendering import SurfaceRect

_LINE_PAD = 1.5
_RUN_SPLIT_GAP = 20.0
_START_CLUSTER_TOLERANCE = 20.0
_MIN_COLUMN_LINES = 5
_SHORT_LINE_RATIO = 0.4


@dataclass(frozen=True)
class _WordGeometry:
    rect: SurfaceRect
    block_no: int
    line_no: int


@dataclass(frozen=True)
class _LineRun:
    rect: SurfaceRect
    block_no: int
    line_no: int


def _surface_rect(rect: fitz.Rect) -> SurfaceRect:
    return SurfaceRect(
        x0=float(rect.x0),
        y0=float(rect.y0),
        x1=float(rect.x1),
        y1=float(rect.y1),
    )


def _display_rect(values: tuple[float, float, float, float], matrix: fitz.Matrix) -> fitz.Rect:
    rect = fitz.Rect(*values)
    rect.transform(matrix)
    return rect


def _valid_rect(rect: fitz.Rect) -> bool:
    values = (rect.x0, rect.y0, rect.x1, rect.y1)
    return all(math.isfinite(float(value)) for value in values) and rect.width > 0 and rect.height > 0


def _padded_rect(rect: SurfaceRect, page_rect: fitz.Rect) -> SurfaceRect:
    return SurfaceRect(
        x0=max(float(page_rect.x0), rect.x0 - _LINE_PAD),
        y0=max(float(page_rect.y0), rect.y0 - _LINE_PAD),
        x1=min(float(page_rect.x1), rect.x1 + _LINE_PAD),
        y1=min(float(page_rect.y1), rect.y1 + _LINE_PAD),
    )


def _line_runs(words: list[_WordGeometry]) -> list[_LineRun]:
    grouped: dict[tuple[int, int], list[_WordGeometry]] = defaultdict(list)
    for word in words:
        grouped[(word.block_no, word.line_no)].append(word)

    runs: list[_LineRun] = []
    for (block_no, line_no), line_words in grouped.items():
        ordered = sorted(line_words, key=lambda word: (word.rect.x0, word.rect.y0))
        current: list[_WordGeometry] = []
        for word in ordered:
            if current and word.rect.x0 - current[-1].rect.x1 >= _RUN_SPLIT_GAP:
                runs.append(_make_run(current, block_no, line_no))
                current = []
            current.append(word)
        if current:
            runs.append(_make_run(current, block_no, line_no))
    return sorted(runs, key=lambda run: (run.rect.y0, run.rect.x0, run.block_no, run.line_no))


def _make_run(
    words: list[_WordGeometry],
    block_no: int,
    line_no: int,
) -> _LineRun:
    rect = SurfaceRect(
        x0=min(word.rect.x0 for word in words),
        y0=min(word.rect.y0 for word in words),
        x1=max(word.rect.x1 for word in words),
        y1=max(word.rect.y1 for word in words),
    )
    return _LineRun(rect=rect, block_no=block_no, line_no=line_no)


def _body_candidates(runs: list[_LineRun], page_rect: fitz.Rect) -> list[_LineRun]:
    top_limit = float(page_rect.y0) + float(page_rect.height) * 0.08
    bottom_limit = float(page_rect.y1) - float(page_rect.height) * 0.08

    block_centers: dict[int, list[float]] = defaultdict(list)
    for run in runs:
        center_y = (run.rect.y0 + run.rect.y1) / 2.0
        block_centers[run.block_no].append(center_y)

    furniture_blocks = {
        block_no
        for block_no, centers in block_centers.items()
        if all(center < top_limit for center in centers)
        or all(center > bottom_limit for center in centers)
    }
    return [run for run in runs if run.block_no not in furniture_blocks]


def _x0_clusters(lines: list[_LineRun]) -> list[list[_LineRun]]:
    clusters: list[list[_LineRun]] = []
    centers: list[float] = []
    for line in sorted(lines, key=lambda item: item.rect.x0):
        nearest: int | None = None
        nearest_distance = math.inf
        for index, center in enumerate(centers):
            distance = abs(line.rect.x0 - center)
            if distance < _START_CLUSTER_TOLERANCE and distance < nearest_distance:
                nearest = index
                nearest_distance = distance
        if nearest is None:
            clusters.append([line])
            centers.append(line.rect.x0)
            continue
        clusters[nearest].append(line)
        centers[nearest] = median(item.rect.x0 for item in clusters[nearest])
    return clusters


def _accepted_lines(lines: list[_LineRun]) -> list[_LineRun]:
    typical_width = median(line.rect.x1 - line.rect.x0 for line in lines)
    threshold = typical_width * _SHORT_LINE_RATIO
    return [line for line in lines if line.rect.x1 - line.rect.x0 >= threshold]


def _clusters_overlap(left: list[_LineRun], right: list[_LineRun]) -> bool:
    left_right_edge = median(line.rect.x1 for line in _accepted_lines(left))
    right_left_edge = median(line.rect.x0 for line in _accepted_lines(right))
    return left_right_edge + _RUN_SPLIT_GAP > right_left_edge


def _merge_overlapping_clusters(clusters: list[list[_LineRun]]) -> list[list[_LineRun]]:
    ordered = sorted(clusters, key=lambda cluster: median(line.rect.x0 for line in cluster))
    merged: list[list[_LineRun]] = []
    for cluster in ordered:
        if merged and _clusters_overlap(merged[-1], cluster):
            merged[-1].extend(cluster)
        else:
            merged.append(list(cluster))
    return merged


def _infer_columns(lines: list[_LineRun], page_rect: fitz.Rect) -> tuple[tuple[TextColumn, ...], float]:
    if len(lines) < _MIN_COLUMN_LINES:
        return (), 0.0

    supported = [
        cluster for cluster in _x0_clusters(lines) if len(cluster) >= _MIN_COLUMN_LINES
    ]
    if not supported:
        return (), 0.0

    clusters = _merge_overlapping_clusters(supported)
    columns: list[TextColumn] = []
    for cluster in clusters:
        accepted = _accepted_lines(cluster)
        if len(accepted) < _MIN_COLUMN_LINES:
            continue
        columns.append(
            TextColumn(
                x0=min(line.rect.x0 for line in accepted),
                x1=max(line.rect.x1 for line in accepted),
            )
        )

    if not columns:
        return (), 0.0

    suspect_edge = float(page_rect.x0) + float(page_rect.width) * 0.95
    confidence = 0.3 if any(column.x1 > suspect_edge for column in columns) else 1.0
    return tuple(columns), confidence


def _glyph_ink_rects(page: fitz.Page, matrix: fitz.Matrix) -> tuple[SurfaceRect, ...]:
    """One tight outline box per visible character, in display space.

    ``TEXT_ACCURATE_BBOXES`` measures each glyph's outline instead of the
    font's line box. On the Alice example the line boxes are 19pt tall at a
    22pt pitch, leaving 3pt of "leading"; the glyph outlines leave about 9pt,
    which is where a hand-drawn connector actually runs.
    """
    raw: dict[str, Any] = page.get_text("rawdict", flags=fitz.TEXT_ACCURATE_BBOXES)
    rects: list[SurfaceRect] = []
    for block in raw.get("blocks", []):
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                for char in span.get("chars", []):
                    if str(char.get("c", "")).isspace():
                        continue
                    bbox = char.get("bbox")
                    if bbox is None:
                        continue
                    rect = _display_rect(
                        (float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])),
                        matrix,
                    )
                    if _valid_rect(rect):
                        rects.append(_surface_rect(rect))
    return tuple(rects)


class PdfTextLayerOccupancyProvider:
    """Extract occupancy from a PDF page's existing text layer."""

    def extract(self, page: fitz.Page) -> PageOccupancy:
        rotation_matrix = fitz.Matrix(page.rotation_matrix)
        raw_words = page.get_text("words")
        words: list[_WordGeometry] = []
        for raw_word in raw_words:
            if len(raw_word) < 8:
                continue
            rect = _display_rect(
                (
                    float(raw_word[0]),
                    float(raw_word[1]),
                    float(raw_word[2]),
                    float(raw_word[3]),
                ),
                rotation_matrix,
            )
            if not _valid_rect(rect):
                continue
            words.append(
                _WordGeometry(
                    rect=_surface_rect(rect),
                    block_no=int(raw_word[5]),
                    line_no=int(raw_word[6]),
                )
            )

        if not words:
            return PageOccupancy(obstacles=(), words=(), body_columns=(), confidence=0.0)

        page_rect = fitz.Rect(page.rect)
        runs = _line_runs(words)
        body_columns, confidence = _infer_columns(_body_candidates(runs, page_rect), page_rect)

        image_obstacles: list[SurfaceRect] = []
        raw_dict: dict[str, Any] = page.get_text("dict")
        for block in raw_dict.get("blocks", []):
            if block.get("type") != 1 or "bbox" not in block:
                continue
            bbox = block["bbox"]
            image_rect = _display_rect(
                (float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])),
                rotation_matrix,
            )
            if _valid_rect(image_rect):
                image_obstacles.append(_surface_rect(image_rect))

        return PageOccupancy(
            obstacles=tuple(_padded_rect(run.rect, page_rect) for run in runs)
            + tuple(image_obstacles),
            words=tuple(word.rect for word in words),
            body_columns=body_columns,
            confidence=confidence,
            glyphs=_glyph_ink_rects(page, rotation_matrix),
        )
