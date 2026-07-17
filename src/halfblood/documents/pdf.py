"""PDF character-range geometry aligned to PyMuPDF text extraction."""

from __future__ import annotations

from dataclasses import dataclass

import fitz


class PdfAlignmentError(RuntimeError):
    """rawdict could not be reconstructed to equal page.get_text('text')."""


@dataclass(frozen=True)
class PdfAnchor:
    """A resolved PDF target: one quad per touched line, in reading order.

    "Reading order" here means **content-stream order** (the order lines are emitted
    by ``page.get_text`` / ``rawdict``), which is *not* necessarily visual
    top-to-bottom order. On an unrotated page the two coincide, but under page
    rotation they diverge: e.g. at 180 degrees ``quads[0]`` (the first content line)
    is the visually *lowest* quad in displayed space. Consumers must treat quad order
    as the character-range order, never assume ``quads[0]`` is the topmost on screen.
    """

    quads: tuple[fitz.Quad, ...]
    char_range: tuple[int, int]
    line_count: int
    page_rotation: int

    def bounding_rect(self) -> fitz.Rect:
        """Return the union of the quads' bounding rectangles."""
        if not self.quads:
            return fitz.Rect()

        bounding = fitz.Rect(self.quads[0].rect)
        for quad in self.quads[1:]:
            bounding |= quad.rect
        return bounding


@dataclass(frozen=True)
class _CharacterGeometry:
    bbox: fitz.Rect | None
    line_key: int | None


class PdfPageIndex:
    """Per-character geometry for one page, aligned to page.get_text('text').

    Build an instance once per page and reuse it for multiple anchor resolutions.
    """

    def __init__(self, page: fitz.Page) -> None:
        rawdict = page.get_text("rawdict")
        reconstructed: list[str] = []
        entries: list[_CharacterGeometry] = []
        line_ordinal = 0

        for block in rawdict["blocks"]:
            if block["type"] != 0:
                continue
            for line in block["lines"]:
                for span in line["spans"]:
                    for char in span["chars"]:
                        reconstructed.append(char["c"])
                        entries.append(
                            _CharacterGeometry(
                                bbox=fitz.Rect(char["bbox"]),
                                line_key=line_ordinal,
                            )
                        )
                reconstructed.append("\n")
                entries.append(_CharacterGeometry(bbox=None, line_key=None))
                line_ordinal += 1

        text = "".join(reconstructed)
        if text != page.get_text("text"):
            raise PdfAlignmentError(
                "rawdict reconstruction does not equal page.get_text('text')"
            )

        self._text = text
        self._entries = entries
        self._rotation_matrix = fitz.Matrix(page.rotation_matrix)
        self._page_rect = fitz.Rect(page.rect)
        self._page_rotation = page.rotation

    @property
    def text(self) -> str:
        """Return text equal to page.get_text('text') byte-for-byte."""
        return self._text

    def char_span_for_rects(self, rects: list[fitz.Rect]) -> tuple[int, int] | None:
        """Return the span of glyphs whose bbox centre is inside any rect."""
        matched_positions: list[int] = []
        for position, entry in enumerate(self._entries):
            if entry.bbox is None:
                continue
            centre = fitz.Point(
                (entry.bbox.x0 + entry.bbox.x1) / 2,
                (entry.bbox.y0 + entry.bbox.y1) / 2,
            )
            if any(centre in rect for rect in rects):
                matched_positions.append(position)

        if not matched_positions:
            return None
        return matched_positions[0], matched_positions[-1] + 1


def resolve_pdf_anchor(
    index: PdfPageIndex, start: int, end: int
) -> PdfAnchor | None:
    """Resolve a half-open page-text range to ordered per-line display quads."""
    start = max(0, start)
    end = min(len(index._entries), end)
    if start >= end:
        return None

    line_groups: dict[int, list[fitz.Rect]] = {}
    for entry in index._entries[start:end]:
        if entry.bbox is None or entry.line_key is None:
            continue
        line_groups.setdefault(entry.line_key, []).append(entry.bbox)

    if not line_groups:
        return None

    quads: list[fitz.Quad] = []
    for bboxes in line_groups.values():
        union = fitz.Rect(bboxes[0])
        for bbox in bboxes[1:]:
            union |= bbox
        quads.append(union.quad * index._rotation_matrix)

    return PdfAnchor(
        quads=tuple(quads),
        char_range=(start, end),
        line_count=len(quads),
        page_rotation=index._page_rotation,
    )
