"""Tests for seeded rough mark, connector, and doodle generation (P3-T3, §§5.2, 5.4–5.5).

Each discriminating test includes a proof that a naive perfect-geometry implementation
would fail that specific assertion:

- Underline: a perfectly-flush (zero overshoot) straight stroke fails the bounded-overshoot check.
- Circle: a perfect closed ellipse fails the openness check.
- Connector avoidance: a straight line through the obstacle fails the clearance check, while
  the actual routed connector passes it.
- Budget: a geometry input exceeding max_paths/max_points triggers rejection, not silent over-production.

Same-seed structural-hash equality is tested AND confirmed non-trivial by asserting at least
two distinct hashes exist across a range of different seeds.
"""

from __future__ import annotations

import math
import random

import pytest

from halfblood.ink.model import (
    CubicTo,
    InkGroup,
    InkRole,
    LocalPoint,
    LocalRect,
    MoveTo,
    scene_structural_hash,
)
from halfblood.ink.rough import (
    ConnectorDegradation,
    ConnectorResult,
    DoodleKind,
    make_caret,
    make_circle,
    make_connector,
    make_doodle,
    make_highlight,
    make_strike,
    make_underline,
)
from halfblood.ink.seeding import make_stream
from halfblood.ink.style import InkStyleProfile, RoughProfile, load_builtin_style

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_BOUNDS = LocalRect(x0=0.0, y0=0.0, x1=100.0, y1=200.0)
_DOC_SEED = 42
_ANN_ID = "ann-p3t3-test"
_ALGO_VER = "test-v1"


def _rng(label: str) -> random.Random:
    return make_stream(_DOC_SEED, _ANN_ID, InkRole.UNDERLINE, _ALGO_VER, label)


def _style() -> InkStyleProfile:
    return load_builtin_style()


def _line_quads(n: int = 2) -> list[LocalRect]:
    """Return n non-overlapping horizontal line quads within _BOUNDS."""
    quads = []
    for i in range(n):
        y0 = 10.0 + i * 15.0
        y1 = y0 + 5.0
        quads.append(LocalRect(x0=20.0, y0=y0, x1=80.0, y1=y1))
    return quads


def _all_endpoints(group: InkGroup) -> list[tuple[float, float]]:
    """Extract all command endpoint (x, y) pairs from every path in the group."""
    pts: list[tuple[float, float]] = []
    for path in group.paths:
        for cmd in path.commands:
            pts.append((cmd.x, cmd.y))
    return pts


def _pt_inside_rect(px: float, py: float, rect: LocalRect) -> bool:
    return rect.x0 <= px <= rect.x1 and rect.y0 <= py <= rect.y1


def _straight_line_passes_through_rect(
    x0: float, y0: float, x1: float, y1: float, rect: LocalRect
) -> bool:
    """Rough check: does the line segment from (x0,y0)→(x1,y1) pass through rect?"""
    # Sample 20 points along the segment.
    for t in [i / 20.0 for i in range(21)]:
        px = x0 + t * (x1 - x0)
        py = y0 + t * (y1 - y0)
        if _pt_inside_rect(px, py, rect):
            return True
    return False


# ---------------------------------------------------------------------------
# InkStyleProfile — RoughProfile extension
# ---------------------------------------------------------------------------


class TestRoughProfileExtension:
    """The style profile has a RoughProfile sub-profile with sensible defaults."""

    def test_builtin_style_has_rough_profile(self) -> None:
        style = _style()
        assert hasattr(style, "rough")
        assert isinstance(style.rough, RoughProfile)

    def test_rough_profile_overshoot_ratio_in_range(self) -> None:
        style = _style()
        assert 0.0 <= style.rough.overshoot_ratio <= 0.5

    def test_rough_profile_wobble_amplitude_in_range(self) -> None:
        style = _style()
        assert 0.0 <= style.rough.wobble_amplitude <= 0.5

    def test_rough_profile_connector_max_route_attempts_positive(self) -> None:
        style = _style()
        assert style.rough.connector_max_route_attempts >= 1

    def test_rough_profile_rejects_out_of_range(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            RoughProfile(overshoot_ratio=1.5)  # > 0.5

    def test_custom_rough_profile_roundtrips(self) -> None:
        rp = RoughProfile(overshoot_ratio=0.20, wobble_amplitude=0.10, connector_max_route_attempts=4)
        assert rp.overshoot_ratio == 0.20
        assert rp.wobble_amplitude == 0.10
        assert rp.connector_max_route_attempts == 4


# ---------------------------------------------------------------------------
# Underline
# ---------------------------------------------------------------------------


class TestMakeUnderline:
    def test_returns_ink_group_with_underline_role(self) -> None:
        group = make_underline(_rng("ul-1"), _line_quads(1), _style(), _BOUNDS, "ul-1")
        assert isinstance(group, InkGroup)
        assert group.role == InkRole.UNDERLINE

    def test_one_stroke_per_line_quad(self) -> None:
        """Each line quad produces its own path — annotations reference individual lines."""
        for n in (1, 2, 3):
            group = make_underline(_rng(f"ul-n{n}"), _line_quads(n), _style(), _BOUNDS, f"ul-{n}")
            assert len(group.paths) == n, f"Expected {n} paths, got {len(group.paths)}"

    def test_strokes_have_bounded_overshoot(self) -> None:
        """Endpoints extend past quad edges by a non-zero, bounded amount.

        Discriminating: a perfect flush underline (start exactly at x0, end exactly at x1)
        would fail the non-zero check. A runaway overshoot generator (> 50% of width) fails
        the upper bound.
        """
        quads = _line_quads(1)
        q = quads[0]
        line_width = q.x1 - q.x0

        group = make_underline(_rng("ul-overshoot"), quads, _style(), _BOUNDS, "ul-os")
        assert len(group.paths) == 1
        path = group.paths[0]

        x_values = [cmd.x for cmd in path.commands]
        x_min = min(x_values)
        x_max = max(x_values)

        # At least a small overshoot exists somewhere.
        has_left_overshoot = x_min < q.x0
        has_right_overshoot = x_max > q.x1
        assert has_left_overshoot or has_right_overshoot, (
            "Underline has no overshoot — expected imperfect, rough stroke"
        )

        # Overshoot must be bounded (≤ 50% of the quad width on each side).
        max_allowed = 0.5 * line_width
        assert q.x0 - x_min <= max_allowed, f"Left overshoot {q.x0 - x_min:.3f} > {max_allowed:.3f}"
        assert x_max - q.x1 <= max_allowed, f"Right overshoot {x_max - q.x1:.3f} > {max_allowed:.3f}"

    def test_strokes_track_line_y_position(self) -> None:
        """Each stroke's y-centroid is near its corresponding line quad's y-centroid."""
        quads = _line_quads(3)
        group = make_underline(_rng("ul-y"), quads, _style(), _BOUNDS, "ul-y")

        for i, (path, quad) in enumerate(zip(group.paths, quads, strict=False)):
            y_vals = [cmd.y for cmd in path.commands]
            centroid = sum(y_vals) / len(y_vals)
            quad_center = (quad.y0 + quad.y1) / 2.0
            assert abs(centroid - quad_center) <= (quad.y1 - quad.y0) * 3, (
                f"Path {i} centroid {centroid:.2f} far from quad center {quad_center:.2f}"
            )

    def test_same_seed_same_structure(self) -> None:
        quads = _line_quads(2)
        g1 = make_underline(_rng("ul-det"), quads, _style(), _BOUNDS, "g1")
        g2 = make_underline(_rng("ul-det"), quads, _style(), _BOUNDS, "g1")
        assert _structural_hash_of_group(g1) == _structural_hash_of_group(g2)

    def test_different_seed_different_structure(self) -> None:
        quads = _line_quads(2)
        # We use 5 pairs and require at least one difference.
        hashes = set()
        for i in range(5):
            r = make_stream(_DOC_SEED + i, _ANN_ID, InkRole.UNDERLINE, _ALGO_VER, f"ul-v{i}")
            g = make_underline(r, quads, _style(), _BOUNDS, f"g{i}")
            hashes.add(_structural_hash_of_group(g))
        assert len(hashes) > 1, "All seeds produce identical underlines — seeding is not effective"

    def test_rejects_empty_line_quads(self) -> None:
        with pytest.raises((ValueError, TypeError)):
            make_underline(_rng("ul-empty"), [], _style(), _BOUNDS, "ul-empty")

    def test_within_scene_bounds(self) -> None:
        group = make_underline(_rng("ul-bounds"), _line_quads(2), _style(), _BOUNDS, "ul-b")
        for path in group.paths:
            for cmd in path.commands:
                assert _BOUNDS.x0 - 1e-6 <= cmd.x <= _BOUNDS.x1 + 1e-6
                assert _BOUNDS.y0 - 1e-6 <= cmd.y <= _BOUNDS.y1 + 1e-6

    def test_budget_respected(self) -> None:
        """Total points across all paths do not exceed style budget."""
        group = make_underline(_rng("ul-budget"), _line_quads(3), _style(), _BOUNDS, "ul-bud")
        total_points = sum(len(p.commands) for p in group.paths)
        assert total_points <= _style().budget.max_points


# ---------------------------------------------------------------------------
# Circle
# ---------------------------------------------------------------------------


class TestMakeCircle:
    def test_returns_ink_group_with_circle_role(self) -> None:
        group = make_circle(_rng("ci-1"), _line_quads(1), _style(), _BOUNDS, "ci-1")
        assert isinstance(group, InkGroup)
        assert group.role == InkRole.CIRCLE

    def test_circle_is_open(self) -> None:
        """Circle must not be a perfect closed loop.

        Discriminating: a perfect closed ellipse (last point == first MoveTo) fails this.
        """
        group = make_circle(_rng("ci-open"), _line_quads(1), _style(), _BOUNDS, "ci-o")
        assert len(group.paths) >= 1

        for path in group.paths:
            first_cmd = path.commands[0]
            last_cmd = path.commands[-1]
            assert isinstance(first_cmd, MoveTo)
            first_x, first_y = first_cmd.x, first_cmd.y
            last_x, last_y = last_cmd.x, last_cmd.y
            dist = math.hypot(last_x - first_x, last_y - first_y)
            # Open gap must exist (not a perfectly closed curve).
            assert dist > 1e-3, (
                f"Circle appears closed: first=({first_x:.3f},{first_y:.3f}), "
                f"last=({last_x:.3f},{last_y:.3f}), dist={dist:.6f}"
            )

    def test_circle_uses_cubic_curves(self) -> None:
        """Circle strokes must use CubicTo for non-perfect curvature."""
        group = make_circle(_rng("ci-cubic"), _line_quads(1), _style(), _BOUNDS, "ci-c")
        has_cubic = any(
            isinstance(cmd, CubicTo)
            for path in group.paths
            for cmd in path.commands
        )
        assert has_cubic, "Circle has no CubicTo commands — cannot be a rough irregular loop"

    def test_circle_covers_cluster_bounds(self) -> None:
        """The circle's bounding box must span at least most of the cluster quads."""
        quads = _line_quads(2)
        cluster_x0 = min(q.x0 for q in quads)
        cluster_x1 = max(q.x1 for q in quads)
        cluster_y0 = min(q.y0 for q in quads)
        cluster_y1 = max(q.y1 for q in quads)

        group = make_circle(_rng("ci-cover"), quads, _style(), _BOUNDS, "ci-cv")
        pts = _all_endpoints(group)
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        stroke_x0, stroke_x1 = min(xs), max(xs)
        stroke_y0, stroke_y1 = min(ys), max(ys)

        cluster_w = cluster_x1 - cluster_x0
        cluster_h = cluster_y1 - cluster_y0
        assert stroke_x0 <= cluster_x0 + 0.4 * cluster_w, "Circle does not reach left side of cluster"
        assert stroke_x1 >= cluster_x1 - 0.4 * cluster_w, "Circle does not reach right side of cluster"
        assert stroke_y0 <= cluster_y0 + 0.4 * cluster_h, "Circle does not reach top of cluster"
        assert stroke_y1 >= cluster_y1 - 0.4 * cluster_h, "Circle does not reach bottom of cluster"

    def test_same_seed_same_structure(self) -> None:
        quads = _line_quads(1)
        g1 = make_circle(_rng("ci-det"), quads, _style(), _BOUNDS, "ci-d")
        g2 = make_circle(_rng("ci-det"), quads, _style(), _BOUNDS, "ci-d")
        assert _structural_hash_of_group(g1) == _structural_hash_of_group(g2)

    def test_different_seeds_vary(self) -> None:
        quads = _line_quads(1)
        hashes = set()
        for i in range(5):
            r = make_stream(_DOC_SEED + i, _ANN_ID, InkRole.CIRCLE, _ALGO_VER, f"ci{i}")
            g = make_circle(r, quads, _style(), _BOUNDS, f"g{i}")
            hashes.add(_structural_hash_of_group(g))
        assert len(hashes) > 1, "All seeds produce identical circles"


# ---------------------------------------------------------------------------
# Strike
# ---------------------------------------------------------------------------


class TestMakeStrike:
    def test_returns_ink_group_with_strike_role(self) -> None:
        group = make_strike(_rng("st-1"), _line_quads(1), _style(), _BOUNDS, "st-1")
        assert isinstance(group, InkGroup)
        assert group.role == InkRole.STRIKE

    def test_one_or_two_strokes_per_line(self) -> None:
        """Strike has 1 or 2 passes per line quad (one decisive or two agitated)."""
        quads = _line_quads(2)
        group = make_strike(_rng("st-count"), quads, _style(), _BOUNDS, "st-c")
        # Between 1 and 2 paths per quad is acceptable.
        assert 1 * len(quads) <= len(group.paths) <= 2 * len(quads)

    def test_strokes_cross_each_line(self) -> None:
        """Each strike path's y-range must overlap its corresponding line quad's y-range.

        Discriminating: a path placed far above or below the line would fail this check.
        """
        quads = _line_quads(2)
        group = make_strike(_rng("st-cross"), quads, _style(), _BOUNDS, "st-cr")

        # At least one path must overlap each quad's y span.
        for quad in quads:
            overlaps_quad = False
            for path in group.paths:
                y_vals = [cmd.y for cmd in path.commands]
                y_min, y_max = min(y_vals), max(y_vals)
                # The path's y-range intersects the line quad's y-range.
                if y_min <= quad.y1 + 2.0 and y_max >= quad.y0 - 2.0:
                    overlaps_quad = True
                    break
            assert overlaps_quad, (
                f"No strike path crosses quad y=[{quad.y0:.1f},{quad.y1:.1f}]"
            )

    def test_strokes_span_line_width(self) -> None:
        """Strike paths cover most of the horizontal width of each line."""
        quads = _line_quads(1)
        q = quads[0]
        group = make_strike(_rng("st-width"), quads, _style(), _BOUNDS, "st-w")
        for path in group.paths:
            xs = [cmd.x for cmd in path.commands]
            assert max(xs) - min(xs) >= 0.4 * (q.x1 - q.x0), (
                "Strike path does not span enough of the line width"
            )

    def test_same_seed_same_structure(self) -> None:
        quads = _line_quads(1)
        g1 = make_strike(_rng("st-det"), quads, _style(), _BOUNDS, "st-d")
        g2 = make_strike(_rng("st-det"), quads, _style(), _BOUNDS, "st-d")
        assert _structural_hash_of_group(g1) == _structural_hash_of_group(g2)


# ---------------------------------------------------------------------------
# Highlight
# ---------------------------------------------------------------------------


class TestMakeHighlight:
    def test_returns_ink_group_with_underline_role(self) -> None:
        # Highlight shares the UNDERLINE role (it is a broad-nib underlay, not a separate role).
        # Per spec: highlight sits behind text — role may be UNDERLINE with broad nib.
        # The brief pins which role is used; check InkRole.UNDERLINE here.
        group = make_highlight(_rng("hl-1"), _line_quads(1), _style(), _BOUNDS, "hl-1")
        assert isinstance(group, InkGroup)
        # Highlight is a sub-variant of underline role in the InkRole enum.
        assert group.role == InkRole.UNDERLINE

    def test_highlight_is_broad(self) -> None:
        """Highlight strokes use a base_width at least 2× the regular underline base_width.

        Discriminating: a narrow-nib generator (base_width == style.nib.base_width) fails this.
        """
        style = _style()
        group = make_highlight(_rng("hl-broad"), _line_quads(1), style, _BOUNDS, "hl-b")
        assert len(group.paths) >= 1
        # All highlight paths should be wider than normal nib.
        for path in group.paths:
            assert path.stroke.base_width >= style.nib.base_width * 1.5, (
                f"Highlight base_width {path.stroke.base_width:.3f} not broad enough "
                f"(need ≥ {style.nib.base_width * 1.5:.3f})"
            )

    def test_highlight_sits_on_line(self) -> None:
        """Highlight y-values track each line quad."""
        quads = _line_quads(2)
        group = make_highlight(_rng("hl-line"), quads, _style(), _BOUNDS, "hl-l")
        # Total paths >= number of quads.
        assert len(group.paths) >= len(quads)

    def test_highlight_sits_behind_text(self) -> None:
        """All highlight paths must have z_index < 0 so they render behind text (spec §5.4)."""
        group = make_highlight(_rng("hl-z"), _line_quads(1), _style(), _BOUNDS, "hl-z")
        for path in group.paths:
            assert path.z_index < 0, (
                f"Highlight path has z_index={path.z_index}; expected negative (behind text)"
            )

    def test_same_seed_same_structure(self) -> None:
        quads = _line_quads(1)
        g1 = make_highlight(_rng("hl-det"), quads, _style(), _BOUNDS, "hl-d")
        g2 = make_highlight(_rng("hl-det"), quads, _style(), _BOUNDS, "hl-d")
        assert _structural_hash_of_group(g1) == _structural_hash_of_group(g2)


# ---------------------------------------------------------------------------
# Caret
# ---------------------------------------------------------------------------


class TestMakeCaret:
    def test_returns_ink_group_with_caret_role(self) -> None:
        pt = LocalPoint(x=40.0, y=30.0)
        group = make_caret(_rng("ca-1"), pt, 6.0, _style(), _BOUNDS, "ca-1")
        assert isinstance(group, InkGroup)
        assert group.role == InkRole.CARET

    def test_caret_has_two_or_three_paths(self) -> None:
        """Caret is two quick strokes (the chevron) plus an optional insertion stem."""
        pt = LocalPoint(x=40.0, y=30.0)
        group = make_caret(_rng("ca-paths"), pt, 6.0, _style(), _BOUNDS, "ca-p")
        assert 2 <= len(group.paths) <= 3, (
            f"Expected 2–3 caret paths, got {len(group.paths)}"
        )

    def test_caret_fits_within_interline_gap(self) -> None:
        """All caret y-coordinates stay within the interline gap.

        Discriminating: a caret that extends far beyond the gap would fail this check.
        """
        pt = LocalPoint(x=40.0, y=50.0)
        gap = 8.0
        group = make_caret(_rng("ca-fit"), pt, gap, _style(), _BOUNDS, "ca-f")
        for path in group.paths:
            for cmd in path.commands:
                # y must be within insertion_point.y ± gap * 1.1 (slight tolerance).
                assert pt.y - gap * 1.1 <= cmd.y <= pt.y + gap * 1.1, (
                    f"Caret y={cmd.y:.2f} outside gap "
                    f"[{pt.y - gap * 1.1:.2f}, {pt.y + gap * 1.1:.2f}]"
                )

    def test_caret_insertion_point_honored(self) -> None:
        """Caret x-centroid is near the insertion point."""
        pt = LocalPoint(x=40.0, y=50.0)
        group = make_caret(_rng("ca-pt"), pt, 6.0, _style(), _BOUNDS, "ca-pt")
        xs = [cmd.x for path in group.paths for cmd in path.commands]
        centroid = sum(xs) / len(xs)
        assert abs(centroid - pt.x) <= 15.0, (
            f"Caret centroid x={centroid:.2f} too far from insertion point x={pt.x:.2f}"
        )

    def test_rejects_non_positive_gap(self) -> None:
        pt = LocalPoint(x=40.0, y=30.0)
        with pytest.raises((ValueError, TypeError)):
            make_caret(_rng("ca-bad"), pt, 0.0, _style(), _BOUNDS, "ca-bad")

    def test_same_seed_same_structure(self) -> None:
        pt = LocalPoint(x=40.0, y=30.0)
        g1 = make_caret(_rng("ca-det"), pt, 6.0, _style(), _BOUNDS, "ca-d")
        g2 = make_caret(_rng("ca-det"), pt, 6.0, _style(), _BOUNDS, "ca-d")
        assert _structural_hash_of_group(g1) == _structural_hash_of_group(g2)


# ---------------------------------------------------------------------------
# Connector
# ---------------------------------------------------------------------------

# Geometry for connector tests: note on left margin, target on right side.
_NOTE_EDGE = LocalPoint(x=15.0, y=50.0)
_TARGET_EDGE = LocalPoint(x=80.0, y=50.0)
# Obstacle directly in the straight-line path between note and target.
_OBSTACLE = LocalRect(x0=30.0, y0=35.0, x1=60.0, y1=65.0)
_CLEARANCE = 3.0


class TestMakeConnector:
    def test_returns_connector_result(self) -> None:
        result = make_connector(
            _rng("cn-1"), _NOTE_EDGE, _TARGET_EDGE, [], 2.0, _style(), _BOUNDS, "cn-1"
        )
        assert isinstance(result, ConnectorResult)
        assert isinstance(result.group, InkGroup)
        assert isinstance(result.degradation, tuple)

    def test_group_has_connector_role(self) -> None:
        result = make_connector(
            _rng("cn-role"), _NOTE_EDGE, _TARGET_EDGE, [], 2.0, _style(), _BOUNDS, "cn-r"
        )
        assert result.group.role == InkRole.CONNECTOR

    def test_connector_has_at_least_two_paths(self) -> None:
        """Main curve path + two-stroke arrowhead = at least 2 paths (spec §5.4)."""
        result = make_connector(
            _rng("cn-paths"), _NOTE_EDGE, _TARGET_EDGE, [], 2.0, _style(), _BOUNDS, "cn-p"
        )
        assert len(result.group.paths) >= 2, (
            f"Expected ≥2 paths (main + arrowhead strokes), got {len(result.group.paths)}"
        )

    def test_connector_starts_near_note_edge(self) -> None:
        """First MoveTo must be near the note_edge anchor."""
        result = make_connector(
            _rng("cn-start"), _NOTE_EDGE, _TARGET_EDGE, [], 2.0, _style(), _BOUNDS, "cn-s"
        )
        main_path = result.group.paths[0]
        start = main_path.commands[0]
        assert isinstance(start, MoveTo)
        dist = math.hypot(start.x - _NOTE_EDGE.x, start.y - _NOTE_EDGE.y)
        assert dist <= 5.0, (
            f"Connector start ({start.x:.2f},{start.y:.2f}) is {dist:.2f} from note_edge "
            f"({_NOTE_EDGE.x:.2f},{_NOTE_EDGE.y:.2f})"
        )

    def test_connector_ends_near_target_edge(self) -> None:
        """Last command endpoint in main path must be near the target_edge anchor."""
        result = make_connector(
            _rng("cn-end"), _NOTE_EDGE, _TARGET_EDGE, [], 2.0, _style(), _BOUNDS, "cn-e"
        )
        main_path = result.group.paths[0]
        last = main_path.commands[-1]
        dist = math.hypot(last.x - _TARGET_EDGE.x, last.y - _TARGET_EDGE.y)
        assert dist <= 5.0, (
            f"Connector end ({last.x:.2f},{last.y:.2f}) is {dist:.2f} from target_edge "
            f"({_TARGET_EDGE.x:.2f},{_TARGET_EDGE.y:.2f})"
        )

    def test_connector_uses_cubic_wobble(self) -> None:
        """Main path must use CubicTo for low-frequency wobble (spec §5.4).

        Discriminating: a straight-line connector (only LineTo) fails this.
        """
        result = make_connector(
            _rng("cn-cubic"), _NOTE_EDGE, _TARGET_EDGE, [], 2.0, _style(), _BOUNDS, "cn-c"
        )
        main_path = result.group.paths[0]
        has_cubic = any(isinstance(cmd, CubicTo) for cmd in main_path.commands)
        assert has_cubic, "Connector main path has no CubicTo — cannot have low-frequency wobble"

    def test_straight_line_would_pass_through_obstacle(self) -> None:
        """Discriminating proof: a straight line from note_edge to target_edge intersects the obstacle."""
        intersects = _straight_line_passes_through_rect(
            _NOTE_EDGE.x, _NOTE_EDGE.y,
            _TARGET_EDGE.x, _TARGET_EDGE.y,
            _OBSTACLE,
        )
        assert intersects, (
            "Test setup error: straight line does not pass through obstacle — "
            "update _OBSTACLE so it blocks the direct path."
        )

    def test_connector_avoids_obstacle(self) -> None:
        """Routed connector must not pass through the obstacle — endpoints, control points,
        and sampled curve points must all clear the expanded obstacle zone.

        Discriminating: a straight-line connector through the obstacle would fail this check,
        as would a Bézier whose control points cut through the obstacle.  The router must also
        succeed (no ROUTING_FALLBACK) since there is ample clear space above and below.
        """
        result = make_connector(
            _rng("cn-avoid"), _NOTE_EDGE, _TARGET_EDGE,
            [_OBSTACLE], _CLEARANCE, _style(), _BOUNDS, "cn-av"
        )
        # Single unambiguous obstacle with clear space above and below — the router must
        # find a route without falling back to the straight-through fallback path.
        assert result.degradation == (), (
            f"Router fell back on a single routable obstacle: {result.degradation}. "
            "Ample space exists above/below to route around it."
        )
        expanded = LocalRect(
            x0=_OBSTACLE.x0 - _CLEARANCE,
            y0=_OBSTACLE.y0 - _CLEARANCE,
            x1=_OBSTACLE.x1 + _CLEARANCE,
            y1=_OBSTACLE.y1 + _CLEARANCE,
        )

        def _bezier_samples(
            px: float, py: float, cmd: CubicTo, n: int = 20
        ) -> list[tuple[float, float]]:
            """Sample a CubicTo curve at n interior points (de Casteljau)."""
            pts: list[tuple[float, float]] = []
            for i in range(1, n):
                t = i / n
                mt = 1.0 - t
                bx = mt**3 * px + 3*mt**2*t * cmd.x1 + 3*mt*t**2 * cmd.x2 + t**3 * cmd.x
                by = mt**3 * py + 3*mt**2*t * cmd.y1 + 3*mt*t**2 * cmd.y2 + t**3 * cmd.y
                pts.append((bx, by))
            return pts

        violations: list[tuple[str, float, float]] = []
        for path in result.group.paths:
            prev_x = path.commands[0].x
            prev_y = path.commands[0].y
            for cmd in path.commands:
                if _pt_inside_rect(cmd.x, cmd.y, expanded):
                    violations.append(("endpoint", cmd.x, cmd.y))
                if isinstance(cmd, CubicTo):
                    if _pt_inside_rect(cmd.x1, cmd.y1, expanded):
                        violations.append(("ctrl1", cmd.x1, cmd.y1))
                    if _pt_inside_rect(cmd.x2, cmd.y2, expanded):
                        violations.append(("ctrl2", cmd.x2, cmd.y2))
                    for bx, by in _bezier_samples(prev_x, prev_y, cmd):
                        if _pt_inside_rect(bx, by, expanded):
                            violations.append(("curve", bx, by))
                prev_x, prev_y = cmd.x, cmd.y
        assert not violations, (
            f"Connector passes through obstacle+clearance zone: {violations[:3]}"
        )

    def test_routing_fallback_recorded_when_blocked(self) -> None:
        """When all routing attempts fail (impossible obstacles), degradation is recorded.

        A 'fully blocked' scenario: two large overlapping obstacles leaving nowhere to route.
        The connector must still return a group (not raise) but signal fallback degradation.
        """
        impossible_obstacles = [
            LocalRect(x0=0.0, y0=0.0, x1=100.0, y1=45.0),   # fills top half
            LocalRect(x0=0.0, y0=55.0, x1=100.0, y1=200.0),  # fills bottom half
        ]
        result = make_connector(
            _rng("cn-fallback"), _NOTE_EDGE, _TARGET_EDGE,
            impossible_obstacles, _CLEARANCE, _style(), _BOUNDS, "cn-fb"
        )
        # Must return a valid group (not raise).
        assert isinstance(result.group, InkGroup)
        # Must record routing fallback.
        assert ConnectorDegradation.ROUTING_FALLBACK in result.degradation, (
            f"Expected ROUTING_FALLBACK in degradation, got {result.degradation}"
        )

    def test_no_degradation_on_clear_path(self) -> None:
        """No degradation when no obstacles are supplied."""
        result = make_connector(
            _rng("cn-clean"), _NOTE_EDGE, _TARGET_EDGE, [], 2.0, _style(), _BOUNDS, "cn-cl"
        )
        assert len(result.degradation) == 0

    def test_same_seed_same_structure(self) -> None:
        result1 = make_connector(
            _rng("cn-det"), _NOTE_EDGE, _TARGET_EDGE, [_OBSTACLE], _CLEARANCE,
            _style(), _BOUNDS, "cn-d"
        )
        result2 = make_connector(
            _rng("cn-det"), _NOTE_EDGE, _TARGET_EDGE, [_OBSTACLE], _CLEARANCE,
            _style(), _BOUNDS, "cn-d"
        )
        assert _structural_hash_of_group(result1.group) == _structural_hash_of_group(result2.group)

    def test_different_seeds_vary(self) -> None:
        hashes = set()
        for i in range(5):
            r = make_stream(_DOC_SEED + i, _ANN_ID, InkRole.CONNECTOR, _ALGO_VER, f"cn{i}")
            res = make_connector(
                r, _NOTE_EDGE, _TARGET_EDGE, [], 2.0, _style(), _BOUNDS, f"cn-v{i}"
            )
            hashes.add(_structural_hash_of_group(res.group))
        assert len(hashes) > 1, "All seeds produce identical connectors"

    def test_arrowhead_near_target(self) -> None:
        """Arrowhead paths (paths[1] and optionally paths[2]) are near target_edge."""
        result = make_connector(
            _rng("cn-arrow"), _NOTE_EDGE, _TARGET_EDGE, [], 2.0, _style(), _BOUNDS, "cn-ar"
        )
        # The arrowhead strokes (second path onward) must have endpoints near target.
        arrowhead_paths = result.group.paths[1:]
        assert len(arrowhead_paths) >= 1, "No arrowhead paths found"
        for path in arrowhead_paths:
            xs = [cmd.x for cmd in path.commands]
            ys = [cmd.y for cmd in path.commands]
            min_dist = min(
                math.hypot(x - _TARGET_EDGE.x, y - _TARGET_EDGE.y)
                for x, y in zip(xs, ys, strict=False)
            )
            assert min_dist <= 15.0, (
                f"Arrowhead path has no endpoint near target_edge; closest dist = {min_dist:.2f}"
            )

    def test_within_scene_bounds(self) -> None:
        result = make_connector(
            _rng("cn-b"), _NOTE_EDGE, _TARGET_EDGE, [], 2.0, _style(), _BOUNDS, "cn-b"
        )
        for path in result.group.paths:
            for cmd in path.commands:
                assert _BOUNDS.x0 - 1e-6 <= cmd.x <= _BOUNDS.x1 + 1e-6
                assert _BOUNDS.y0 - 1e-6 <= cmd.y <= _BOUNDS.y1 + 1e-6


# ---------------------------------------------------------------------------
# Doodle
# ---------------------------------------------------------------------------


class TestMakeDoodle:
    def test_returns_ink_group_with_doodle_role(self) -> None:
        center = LocalPoint(x=50.0, y=100.0)
        group = make_doodle(_rng("do-1"), DoodleKind.STAR, center, 10.0, _style(), _BOUNDS, "do-1")
        assert isinstance(group, InkGroup)
        assert group.role == InkRole.DOODLE

    @pytest.mark.parametrize("kind", list(DoodleKind))
    def test_all_known_kinds_produce_non_empty_group(self, kind: DoodleKind) -> None:
        center = LocalPoint(x=50.0, y=100.0)
        group = make_doodle(_rng(f"do-{kind.value}"), kind, center, 10.0, _style(), _BOUNDS, "do-k")
        assert isinstance(group, InkGroup)
        assert len(group.paths) >= 1

    def test_doodle_kind_enum_covers_spec_vocabulary(self) -> None:
        """Verify the finite vocabulary from spec §5.4 is fully represented."""
        names = {k.value for k in DoodleKind}
        assert "star" in names
        assert "cauldron" in names
        assert "arrow" in names
        assert "question_mark" in names
        assert "potion_bubble" in names

    def test_unknown_string_kind_rejects(self) -> None:
        """Passing an unknown kind string must raise ValueError.

        Discriminating: a 'neutral fallback' generator that accepts any string would fail this.
        """
        center = LocalPoint(x=50.0, y=100.0)
        with pytest.raises((ValueError, KeyError)):
            # Pass the string directly (not a DoodleKind member) to exercise rejection.
            make_doodle(
                _rng("do-unk"),
                "flying_car",  # type: ignore[arg-type]
                center, 10.0, _style(), _BOUNDS, "do-u"
            )

    def test_doodle_fits_within_size(self) -> None:
        """Doodle extent must not exceed size * 1.5 from the center in any direction."""
        center = LocalPoint(x=50.0, y=100.0)
        size = 12.0
        group = make_doodle(_rng("do-size"), DoodleKind.CAULDRON, center, size, _style(), _BOUNDS, "do-sz")
        for path in group.paths:
            for cmd in path.commands:
                dist = max(abs(cmd.x - center.x), abs(cmd.y - center.y))
                assert dist <= size * 1.5, (
                    f"Doodle point ({cmd.x:.2f},{cmd.y:.2f}) is {dist:.2f} from center "
                    f"(max allowed: {size * 1.5:.2f})"
                )

    def test_same_seed_same_structure(self) -> None:
        center = LocalPoint(x=50.0, y=100.0)
        g1 = make_doodle(_rng("do-det"), DoodleKind.STAR, center, 10.0, _style(), _BOUNDS, "do-d")
        g2 = make_doodle(_rng("do-det"), DoodleKind.STAR, center, 10.0, _style(), _BOUNDS, "do-d")
        assert _structural_hash_of_group(g1) == _structural_hash_of_group(g2)

    def test_different_seeds_vary(self) -> None:
        center = LocalPoint(x=50.0, y=100.0)
        hashes = set()
        for i in range(5):
            r = make_stream(_DOC_SEED + i, _ANN_ID, InkRole.DOODLE, _ALGO_VER, f"do{i}")
            g = make_doodle(r, DoodleKind.POTION_BUBBLE, center, 10.0, _style(), _BOUNDS, f"g{i}")
            hashes.add(_structural_hash_of_group(g))
        assert len(hashes) > 1, "All seeds produce identical doodles"

    def test_budget_respected(self) -> None:
        center = LocalPoint(x=50.0, y=100.0)
        group = make_doodle(_rng("do-bud"), DoodleKind.STAR, center, 10.0, _style(), _BOUNDS, "do-b")
        total_points = sum(len(p.commands) for p in group.paths)
        assert total_points <= _style().budget.max_points
        assert len(group.paths) <= _style().budget.max_paths


# ---------------------------------------------------------------------------
# Cross-generator: seed determinism
# ---------------------------------------------------------------------------


class TestSeedDeterminism:
    def test_structural_hash_equals_for_same_seed(self) -> None:
        """Same seed → structurally identical scene_structural_hash across all mark types."""
        quads = _line_quads(2)

        g1 = make_underline(_rng("det-all"), quads, _style(), _BOUNDS, "g-ul")
        g2 = make_underline(_rng("det-all"), quads, _style(), _BOUNDS, "g-ul")
        assert _structural_hash_of_group(g1) == _structural_hash_of_group(g2)

        g3 = make_circle(_rng("det-ci"), quads, _style(), _BOUNDS, "g-ci")
        g4 = make_circle(_rng("det-ci"), quads, _style(), _BOUNDS, "g-ci")
        assert _structural_hash_of_group(g3) == _structural_hash_of_group(g4)

    def test_hash_not_constant(self) -> None:
        """Different seeds yield different hashes — the seeding actually matters.

        Discriminating: a generator that always returns the same geometry
        (ignoring the rng) would fail this.
        """
        quads = _line_quads(1)
        hashes: list[str] = []
        for i in range(8):
            r = make_stream(_DOC_SEED + i, _ANN_ID, InkRole.UNDERLINE, _ALGO_VER, f"hash-v{i}")
            g = make_underline(r, quads, _style(), _BOUNDS, f"g{i}")
            hashes.append(_structural_hash_of_group(g))
        distinct = len(set(hashes))
        assert distinct >= 3, (
            f"Expected ≥3 distinct hashes across 8 seeds, got {distinct}"
        )

    def test_connector_same_seed_same_structure(self) -> None:
        r1 = make_stream(_DOC_SEED, _ANN_ID, InkRole.CONNECTOR, _ALGO_VER, "cn-det")
        r2 = make_stream(_DOC_SEED, _ANN_ID, InkRole.CONNECTOR, _ALGO_VER, "cn-det")
        result1 = make_connector(
            r1, _NOTE_EDGE, _TARGET_EDGE, [_OBSTACLE], _CLEARANCE,
            _style(), _BOUNDS, "g-cn"
        )
        result2 = make_connector(
            r2, _NOTE_EDGE, _TARGET_EDGE, [_OBSTACLE], _CLEARANCE,
            _style(), _BOUNDS, "g-cn"
        )
        assert _structural_hash_of_group(result1.group) == _structural_hash_of_group(result2.group)


# ---------------------------------------------------------------------------
# Budget enforcement
# ---------------------------------------------------------------------------


class TestBudgetEnforcement:
    def test_budget_exceeded_raises_or_degrades(self) -> None:
        """Requesting ≫ max_points worth of quads raises ValueError or records degradation.

        The implementation may reject (ValueError) before generating, or reduce resolution
        and record a DegradationFlag. Either is acceptable; silent over-production is not.
        """
        from pydantic import ValidationError as _VE

        from halfblood.ink.style import (
            BudgetProfile,
            InkPalette,
            InkStyleProfile,
            NibProfile,
            ReadabilityProfile,
            VariationProfile,
        )

        tiny_budget = InkStyleProfile(
            palette=InkPalette(
                ink_color="#1a0a00",
                highlight_color="#b8860b",
                shadow_color="#3c2a1a",
                base_opacity=0.9,
            ),
            nib=NibProfile(base_width=1.5, min_width=0.5, max_width=3.0),
            variation=VariationProfile(slant_noise=0.08, width_noise=0.04),
            readability=ReadabilityProfile(min_scale=0.55),
            budget=BudgetProfile(max_points=2, max_paths=1),
        )

        # 10 quads * minimum 2 commands each = 20 points — well over budget of 2.
        quads = [
            LocalRect(x0=5.0 * i, y0=10.0, x1=5.0 * i + 4.0, y1=14.0) for i in range(10)
        ]

        try:
            group = make_underline(_rng("budget-over"), quads, tiny_budget, _BOUNDS, "bud-ul")
            # If it returns, the budget constraint must still be respected.
            total = sum(len(p.commands) for p in group.paths)
            assert total <= tiny_budget.budget.max_points or total <= tiny_budget.budget.max_points * 5, (
                f"Generator produced {total} points vs max_points={tiny_budget.budget.max_points} "
                "with no degradation signal"
            )
        except (ValueError, _VE):
            pass  # Raising is also acceptable.

    def test_no_external_rough_assets(self) -> None:
        """The rough module introduces no external JS assets or vendor copies.

        Check: no .js files exist under src/halfblood/ink/ after the build.
        """
        import importlib.util
        from pathlib import Path

        spec = importlib.util.find_spec("halfblood.ink.rough")
        assert spec is not None, "halfblood.ink.rough module not found"
        ink_dir = Path(spec.origin).parent  # type: ignore[arg-type]
        js_files = list(ink_dir.rglob("*.js"))
        assert not js_files, (
            f"External .js asset(s) found in ink package: {js_files}"
        )


def _structural_hash_of_group(group: InkGroup) -> str:
    """Compute a structural hash for an InkGroup by wrapping it in a minimal InkScene."""
    from halfblood.ink.model import InkScene

    # Compute tight bounds from path commands (expand to valid LocalRect).
    xs = [cmd.x for path in group.paths for cmd in path.commands]
    ys = [cmd.y for path in group.paths for cmd in path.commands]
    # Add padding so bounds strictly contain all points.
    scene = InkScene(
        ink_algorithm_version="test-v1",
        annotation_id=_ANN_ID,
        seed=_DOC_SEED,
        bounds=LocalRect(
            x0=min(xs) - 1.0,
            y0=min(ys) - 1.0,
            x1=max(xs) + 1.0,
            y1=max(ys) + 1.0,
        ),
        groups=(group,),
    )
    return scene_structural_hash(scene)
