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


def fitz_rect_from_surf(surf: SurfaceRect) -> fitz.Rect:
    """Convert a renderer-neutral surface rectangle back to a fitz.Rect.

    Inverse of surf_rect_from_fitz.
    """
    return fitz.Rect(surf.x0, surf.y0, surf.x1, surf.y1)


def fitz_rect_from_surf_quad(quad: SurfaceQuad) -> fitz.Rect:
    """Return the axis-aligned bounding rectangle of a SurfaceQuad.

    Uses all four corners so it is correct for rotated quads.
    """
    xs = (quad.ul.x, quad.ur.x, quad.lr.x, quad.ll.x)
    ys = (quad.ul.y, quad.ur.y, quad.lr.y, quad.ll.y)
    return fitz.Rect(min(xs), min(ys), max(xs), max(ys))
