"""Surface-neutral page occupancy and body-column geometry."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from halfblood.models.rendering import SurfaceRect


@dataclass(frozen=True)
class TextColumn:
    """Axis-aligned body-text column in surface coordinates."""

    x0: float
    x1: float


@dataclass(frozen=True)
class PageOccupancy:
    """Renderer-neutral page geometry extracted from a document page.

    ``obstacles`` contains padded line runs plus headers, footers, and images.
    ``words`` retains fine-grained word rectangles, while ``body_columns`` is
    inferred without allowing isolated page furniture to influence its edges.
    A low confidence signals that extraction was uncertain.

    ``glyphs`` holds one tight ink box per visible character (the glyph's
    outline extent, not the font's ascender-to-descender line box). Line boxes
    on a typical book page touch or overlap their neighbours, so only glyph
    boxes show the leading a connector can travel in. Empty when the surface
    cannot supply them.
    """

    obstacles: tuple[SurfaceRect, ...]
    words: tuple[SurfaceRect, ...]
    body_columns: tuple[TextColumn, ...]
    confidence: float = 1.0
    glyphs: tuple[SurfaceRect, ...] = ()


class PageOccupancyProvider(Protocol):
    """Extract renderer-neutral occupancy from a document page."""

    def extract(self, page: object) -> PageOccupancy: ...
