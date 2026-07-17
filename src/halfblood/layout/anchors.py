"""Adapter bridging fitz types to renderer-neutral surface geometry.

This is the ONLY module in halfblood.layout that may import fitz.
engine.py must remain fitz-free.
"""

from __future__ import annotations

import fitz

from halfblood.documents.pdf import PdfAnchor
from halfblood.models.rendering import (
    ResolvedAnchor,
    SurfacePoint,
    SurfaceQuad,
    SurfaceRect,
)


def surf_point_from_fitz(point: fitz.Point) -> SurfacePoint:
    """Convert a fitz point to renderer-neutral surface coordinates."""
    return SurfacePoint(x=float(point.x), y=float(point.y))


def surf_rect_from_fitz(rect: fitz.Rect) -> SurfaceRect:
    """Convert a fitz rectangle to renderer-neutral surface coordinates."""
    return SurfaceRect(
        x0=float(rect.x0),
        y0=float(rect.y0),
        x1=float(rect.x1),
        y1=float(rect.y1),
    )


def surf_quad_from_fitz(quad: fitz.Quad) -> SurfaceQuad:
    """Convert a fitz quadrilateral while preserving named corner order."""
    return SurfaceQuad(
        ul=surf_point_from_fitz(quad.ul),
        ur=surf_point_from_fitz(quad.ur),
        lr=surf_point_from_fitz(quad.lr),
        ll=surf_point_from_fitz(quad.ll),
    )


def pdf_anchor_to_resolved_anchor(anchor: PdfAnchor) -> ResolvedAnchor:
    """Convert a fitz-typed PdfAnchor to a renderer-neutral ResolvedAnchor.

    Preserves char_range and converts each fitz.Quad to a SurfaceQuad
    using the quad's corner attributes (ul, ur, lr, ll).
    """
    return ResolvedAnchor(
        char_range=anchor.char_range,
        quads=tuple(surf_quad_from_fitz(quad) for quad in anchor.quads),
    )
