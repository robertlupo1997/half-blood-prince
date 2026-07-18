"""Tests for the immutable InkScene model (P3-T1, architecture §5.2).

Every rejection test includes a discriminating permissive proof: a plain
BaseModel (no validators, allow_inf_nan=True by default) that accepts the
same malformed dict, confirming the strict model's rejection is non-vacuous.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import BaseModel, ValidationError

from halfblood.ink.model import (
    _BOUNDS_TOLERANCE,
    _HASH_DECIMALS,
    AffineTransform,
    CubicTo,
    InkGroup,
    InkRole,
    InkScene,
    LineTo,
    LocalRect,
    MoveTo,
    PressureSample,
    StrokePath,
    StrokeStyle,
    WidthSample,
    load_ink_scene,
    scene_structural_hash,
)
from halfblood.models.documents import UnsupportedSchemaVersionError
from halfblood.models.rendering import DegradationFlag

FIXTURES = Path(__file__).parent / "fixtures" / "ink"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _style(color: str = "#1a0a00", base_width: float = 1.5, opacity: float = 0.9) -> StrokeStyle:
    return StrokeStyle(color=color, base_width=base_width, opacity=opacity)


def _simple_path(x_end: float = 50.0, y_end: float = 50.0) -> StrokePath:
    """A valid MoveTo + LineTo path within [0, 100] x [0, 200]."""
    return StrokePath(
        commands=(MoveTo(x=10.0, y=10.0), LineTo(x=x_end, y=y_end)),
        stroke=_style(),
    )


def _bounds() -> LocalRect:
    return LocalRect(x0=0.0, y0=0.0, x1=100.0, y1=200.0)


def _minimal_scene(**overrides: object) -> InkScene:
    defaults: dict = dict(
        scene_version="1.0",
        ink_algorithm_version="test-v1",
        annotation_id="ann-001",
        seed=42,
        bounds=_bounds(),
        groups=(
            InkGroup(
                group_id="g0",
                role=InkRole.UNDERLINE,
                paths=(_simple_path(),),
            ),
        ),
    )
    defaults.update(overrides)
    return InkScene(**defaults)


# ---------------------------------------------------------------------------
# 1. Construction — every command type and every InkRole
# ---------------------------------------------------------------------------


class TestCommandConstruction:
    def test_move_to(self) -> None:
        cmd = MoveTo(x=1.0, y=2.0)
        assert cmd.kind == "M"
        assert cmd.x == 1.0
        assert cmd.y == 2.0

    def test_line_to(self) -> None:
        cmd = LineTo(x=3.0, y=4.5)
        assert cmd.kind == "L"
        assert cmd.x == 3.0
        assert cmd.y == 4.5

    def test_cubic_to(self) -> None:
        cmd = CubicTo(x1=1.0, y1=2.0, x2=3.0, y2=4.0, x=5.0, y=6.0)
        assert cmd.kind == "C"
        assert cmd.x1 == 1.0
        assert cmd.x2 == 3.0
        assert cmd.x == 5.0

    def test_all_roles_constructable(self) -> None:
        for role in InkRole:
            grp = InkGroup(
                group_id=f"g-{role.value}",
                role=role,
                paths=(_simple_path(),),
            )
            assert grp.role == role


# ---------------------------------------------------------------------------
# 2. Immutability
# ---------------------------------------------------------------------------


class TestImmutability:
    def test_scene_is_frozen(self) -> None:
        scene = _minimal_scene()
        with pytest.raises(ValidationError):
            scene.annotation_id = "changed"  # type: ignore[misc]

    def test_local_rect_is_frozen(self) -> None:
        r = LocalRect(x0=0.0, y0=0.0, x1=10.0, y1=10.0)
        with pytest.raises(ValidationError):
            r.x0 = 5.0  # type: ignore[misc]

    def test_stroke_path_is_frozen(self) -> None:
        path = _simple_path()
        with pytest.raises(ValidationError):
            path.z_index = 99  # type: ignore[misc]


# ---------------------------------------------------------------------------
# 3. Rejection — NaN / Inf
# ---------------------------------------------------------------------------


class _PermissiveFloatModel(BaseModel):
    """Used as discriminating control: accepts NaN/Inf because it has no restriction."""
    x: float
    y: float


class TestNanInfRejection:
    def test_nan_in_move_to_x_rejected(self) -> None:
        # Discriminating proof: permissive model accepts NaN
        _PermissiveFloatModel(x=float("nan"), y=0.0)
        # Strict model must reject it via allow_inf_nan=False
        with pytest.raises(ValidationError):
            MoveTo(x=float("nan"), y=0.0)

    def test_nan_in_line_to_y_rejected(self) -> None:
        _PermissiveFloatModel(x=0.0, y=float("nan"))
        with pytest.raises(ValidationError):
            LineTo(x=0.0, y=float("nan"))

    def test_inf_in_cubic_to_control_point_rejected(self) -> None:
        _PermissiveFloatModel(x=float("inf"), y=0.0)
        with pytest.raises(ValidationError):
            CubicTo(x1=float("inf"), y1=0.0, x2=50.0, y2=50.0, x=50.0, y=50.0)

    def test_neg_inf_in_pressure_sample_rejected(self) -> None:
        _PermissiveFloatModel(x=float("-inf"), y=0.0)
        with pytest.raises(ValidationError):
            PressureSample(x=float("-inf"), y=0.0, pressure=0.5, time=0.0, pen_down=True)

    def test_nan_in_local_rect_rejected(self) -> None:
        _PermissiveFloatModel(x=float("nan"), y=0.0)
        with pytest.raises(ValidationError):
            LocalRect(x0=float("nan"), y0=0.0, x1=10.0, y1=10.0)


# ---------------------------------------------------------------------------
# 4. Rejection — negative base_width
# ---------------------------------------------------------------------------


class _PermissiveWidth(BaseModel):
    base_width: float


class TestNegativeWidthRejection:
    def test_zero_base_width_rejected(self) -> None:
        # Discriminating: permissive model accepts 0.0
        _PermissiveWidth(base_width=0.0)
        with pytest.raises(ValidationError):
            _style(base_width=0.0)

    def test_negative_base_width_rejected(self) -> None:
        _PermissiveWidth(base_width=-1.0)
        with pytest.raises(ValidationError):
            _style(base_width=-1.0)

    def test_negative_width_sample_rejected(self) -> None:
        _PermissiveWidth(base_width=-0.5)
        with pytest.raises(ValidationError):
            WidthSample(position=0.5, width=-0.5)

    def test_zero_width_sample_rejected(self) -> None:
        _PermissiveWidth(base_width=0.0)
        with pytest.raises(ValidationError):
            WidthSample(position=0.5, width=0.0)


# ---------------------------------------------------------------------------
# 5. Rejection — opacity outside [0, 1]
# ---------------------------------------------------------------------------


class _PermissiveOpacity(BaseModel):
    opacity: float


class TestOpacityRejection:
    def test_opacity_above_1_rejected(self) -> None:
        _PermissiveOpacity(opacity=1.5)
        with pytest.raises(ValidationError):
            _style(opacity=1.5)

    def test_opacity_below_0_rejected(self) -> None:
        _PermissiveOpacity(opacity=-0.1)
        with pytest.raises(ValidationError):
            _style(opacity=-0.1)

    def test_opacity_at_boundary_0_accepted(self) -> None:
        s = _style(opacity=0.0)
        assert s.opacity == 0.0

    def test_opacity_at_boundary_1_accepted(self) -> None:
        s = _style(opacity=1.0)
        assert s.opacity == 1.0


# ---------------------------------------------------------------------------
# 6. Rejection — invalid AffineTransform (wrong tuple length)
# ---------------------------------------------------------------------------


class _PermissiveTuple(BaseModel):
    matrix: tuple


class TestAffineTransformRejection:
    def test_identity_transform_accepted(self) -> None:
        t = AffineTransform()
        assert t.matrix == (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)

    def test_too_few_elements_rejected(self) -> None:
        _PermissiveTuple(matrix=(1.0, 0.0, 0.0, 1.0))
        with pytest.raises(ValidationError):
            AffineTransform(matrix=(1.0, 0.0, 0.0, 1.0))  # type: ignore[arg-type]

    def test_too_many_elements_rejected(self) -> None:
        _PermissiveTuple(matrix=(1.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0))
        with pytest.raises(ValidationError):
            AffineTransform(matrix=(1.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0))  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 7. Rejection — non-monotonic width_profile positions
# ---------------------------------------------------------------------------


class TestWidthProfileMonotonicity:
    def test_monotone_increasing_accepted(self) -> None:
        path = StrokePath(
            commands=(MoveTo(x=0.0, y=0.0), LineTo(x=10.0, y=0.0)),
            stroke=_style(),
            width_profile=(
                WidthSample(position=0.0, width=1.0),
                WidthSample(position=0.5, width=1.5),
                WidthSample(position=1.0, width=1.0),
            ),
        )
        assert len(path.width_profile) == 3

    def test_repeated_position_accepted(self) -> None:
        # Equal positions are non-decreasing (monotone non-strict)
        StrokePath(
            commands=(MoveTo(x=0.0, y=0.0), LineTo(x=10.0, y=0.0)),
            stroke=_style(),
            width_profile=(
                WidthSample(position=0.5, width=1.0),
                WidthSample(position=0.5, width=1.2),
            ),
        )

    def test_non_monotone_positions_rejected(self) -> None:
        # Discriminating: build with no validator to confirm dict is otherwise valid
        class _PermissivePath(BaseModel):
            width_profile: list[dict]
        _PermissivePath(width_profile=[{"position": 0.8, "width": 1.0}, {"position": 0.2, "width": 1.0}])

        with pytest.raises(ValidationError):
            StrokePath(
                commands=(MoveTo(x=0.0, y=0.0), LineTo(x=10.0, y=0.0)),
                stroke=_style(),
                width_profile=(
                    WidthSample(position=0.8, width=1.0),
                    WidthSample(position=0.2, width=1.0),
                ),
            )


# ---------------------------------------------------------------------------
# 8. Rejection — pen-down path validation
# ---------------------------------------------------------------------------


class TestPenDownPathValidation:
    def test_valid_move_then_line(self) -> None:
        path = _simple_path()
        assert len(path.commands) == 2

    def test_valid_move_then_cubic(self) -> None:
        path = StrokePath(
            commands=(
                MoveTo(x=0.0, y=0.0),
                CubicTo(x1=5.0, y1=5.0, x2=50.0, y2=50.0, x=60.0, y=60.0),
            ),
            stroke=_style(),
        )
        assert path.commands[1].kind == "C"

    def test_empty_commands_rejected(self) -> None:
        class _PermissivePath(BaseModel):
            commands: tuple
        _PermissivePath(commands=())

        with pytest.raises(ValidationError):
            StrokePath(commands=(), stroke=_style())

    def test_first_command_not_move_rejected(self) -> None:
        class _PermissivePath(BaseModel):
            commands: tuple
        _PermissivePath(commands=({"kind": "L", "x": 0.0, "y": 0.0},))

        with pytest.raises(ValidationError):
            StrokePath(
                commands=(LineTo(x=0.0, y=0.0),),
                stroke=_style(),
            )

    def test_move_only_no_segments_rejected(self) -> None:
        class _PermissivePath(BaseModel):
            commands: tuple
        _PermissivePath(commands=({"kind": "M", "x": 0.0, "y": 0.0},))

        with pytest.raises(ValidationError):
            StrokePath(
                commands=(MoveTo(x=0.0, y=0.0),),
                stroke=_style(),
            )


# ---------------------------------------------------------------------------
# 9. Rejection — duplicate group IDs in InkScene
# ---------------------------------------------------------------------------


class TestDuplicateGroupIds:
    def test_unique_group_ids_accepted(self) -> None:
        scene = _minimal_scene(
            groups=(
                InkGroup(group_id="g0", role=InkRole.UNDERLINE, paths=(_simple_path(),)),
                InkGroup(group_id="g1", role=InkRole.CONNECTOR, paths=(_simple_path(),)),
            )
        )
        assert len(scene.groups) == 2

    def test_duplicate_group_ids_rejected(self) -> None:
        class _PermissiveScene(BaseModel):
            groups: list[dict]
        _PermissiveScene(groups=[{"group_id": "same"}, {"group_id": "same"}])

        with pytest.raises(ValidationError, match="duplicate group_ids"):
            _minimal_scene(
                groups=(
                    InkGroup(group_id="same", role=InkRole.UNDERLINE, paths=(_simple_path(),)),
                    InkGroup(group_id="same", role=InkRole.CONNECTOR, paths=(_simple_path(),)),
                )
            )


# ---------------------------------------------------------------------------
# 10. Rejection — bounds containment
# ---------------------------------------------------------------------------


class TestBoundsContainment:
    def test_within_bounds_accepted(self) -> None:
        # Endpoint well within bounds [0,0,100,200]
        scene = _minimal_scene()
        assert scene.bounds.x1 == 100.0

    def test_endpoint_at_boundary_accepted(self) -> None:
        # Exactly on the boundary
        path = StrokePath(
            commands=(MoveTo(x=0.0, y=0.0), LineTo(x=100.0, y=200.0)),
            stroke=_style(),
        )
        _minimal_scene(
            groups=(InkGroup(group_id="g0", role=InkRole.UNDERLINE, paths=(path,)),)
        )

    def test_endpoint_within_tolerance_accepted(self) -> None:
        # Slightly outside boundary but within _BOUNDS_TOLERANCE
        tiny = _BOUNDS_TOLERANCE * 0.5
        path = StrokePath(
            commands=(MoveTo(x=0.0, y=0.0), LineTo(x=100.0 + tiny, y=100.0)),
            stroke=_style(),
        )
        _minimal_scene(
            groups=(InkGroup(group_id="g0", role=InkRole.UNDERLINE, paths=(path,)),)
        )

    def test_endpoint_outside_bounds_rejected(self) -> None:
        class _PermissiveScene(BaseModel):
            bounds: dict
            groups: list
        _PermissiveScene(bounds={"x0": 0, "y0": 0, "x1": 10, "y1": 10}, groups=[])

        # Way outside bounds
        path = StrokePath(
            commands=(MoveTo(x=0.0, y=0.0), LineTo(x=500.0, y=100.0)),
            stroke=_style(),
        )
        with pytest.raises(ValidationError):
            _minimal_scene(
                groups=(InkGroup(group_id="g0", role=InkRole.UNDERLINE, paths=(path,)),)
            )

    def test_cubic_to_endpoint_outside_bounds_rejected(self) -> None:
        # CubicTo endpoint (x,y) must be within bounds; control points may be outside
        path = StrokePath(
            commands=(
                MoveTo(x=0.0, y=0.0),
                CubicTo(
                    x1=200.0, y1=300.0,   # control points outside bounds — allowed
                    x2=250.0, y2=350.0,
                    x=500.0, y=100.0,     # endpoint outside bounds — rejected
                ),
            ),
            stroke=_style(),
        )
        with pytest.raises(ValidationError):
            _minimal_scene(
                groups=(InkGroup(group_id="g0", role=InkRole.UNDERLINE, paths=(path,)),)
            )

    def test_cubic_to_control_points_outside_bounds_accepted(self) -> None:
        # Control points outside bounds are fine; only endpoint matters
        path = StrokePath(
            commands=(
                MoveTo(x=0.0, y=0.0),
                CubicTo(
                    x1=200.0, y1=300.0,  # control points outside bounds — OK
                    x2=250.0, y2=350.0,
                    x=50.0, y=100.0,     # endpoint inside bounds — OK
                ),
            ),
            stroke=_style(),
        )
        scene = _minimal_scene(
            groups=(InkGroup(group_id="g0", role=InkRole.UNDERLINE, paths=(path,)),)
        )
        assert scene.groups[0].paths[0].commands[1].x == 50.0


# ---------------------------------------------------------------------------
# 11. LocalRect validation
# ---------------------------------------------------------------------------


class TestLocalRect:
    def test_inverted_x_rejected(self) -> None:
        with pytest.raises(ValidationError, match="x0 must be <= x1"):
            LocalRect(x0=10.0, y0=0.0, x1=0.0, y1=10.0)

    def test_inverted_y_rejected(self) -> None:
        with pytest.raises(ValidationError, match="y0 must be <= y1"):
            LocalRect(x0=0.0, y0=10.0, x1=10.0, y1=0.0)

    def test_zero_size_rect_accepted(self) -> None:
        r = LocalRect(x0=5.0, y0=5.0, x1=5.0, y1=5.0)
        assert r.x0 == r.x1


# ---------------------------------------------------------------------------
# 12. Versioning fields survive serialization round-trip
# ---------------------------------------------------------------------------


class TestVersioningAndSerialization:
    def test_scene_version_default(self) -> None:
        scene = _minimal_scene()
        assert scene.scene_version == "1.0"

    def test_ink_algorithm_version_survives_roundtrip(self) -> None:
        scene = _minimal_scene(ink_algorithm_version="procedural-v2.3.1")
        data = json.loads(scene.model_dump_json())
        assert data["ink_algorithm_version"] == "procedural-v2.3.1"

    def test_full_scene_roundtrip(self) -> None:
        scene = _minimal_scene()
        data = json.loads(scene.model_dump_json())
        restored = InkScene.model_validate(data)
        assert restored.annotation_id == scene.annotation_id
        assert restored.seed == scene.seed
        assert restored.scene_version == scene.scene_version

    def test_serialization_is_deterministic(self) -> None:
        scene = _minimal_scene()
        dump1 = scene.model_dump_json()
        dump2 = scene.model_dump_json()
        assert dump1 == dump2

    def test_accessibility_label_survives_roundtrip(self) -> None:
        path = StrokePath(
            commands=(MoveTo(x=0.0, y=0.0), LineTo(x=10.0, y=0.0)),
            stroke=_style(),
            accessibility_label="this is an underline mark",
        )
        grp = InkGroup(group_id="g0", role=InkRole.UNDERLINE, paths=(path,))
        scene = _minimal_scene(groups=(grp,))
        data = json.loads(scene.model_dump_json())
        restored = InkScene.model_validate(data)
        assert restored.groups[0].paths[0].accessibility_label == "this is an underline mark"

    def test_degradation_flags_survive_roundtrip(self) -> None:
        flags = (
            DegradationFlag.PROCEDURAL_STROKE_FALLBACK,
            DegradationFlag.GLYPH_FALLBACK,
        )
        scene = _minimal_scene(degradation_flags=flags)
        data = json.loads(scene.model_dump_json())
        restored = InkScene.model_validate(data)
        assert set(restored.degradation_flags) == set(flags)


# ---------------------------------------------------------------------------
# 13. load_ink_scene — version gating
# ---------------------------------------------------------------------------


class TestLoadInkScene:
    def _minimal_dict(self, **overrides: object) -> dict:
        base: dict = {
            "scene_version": "1.0",
            "ink_algorithm_version": "test-v1",
            "annotation_id": "ann-x",
            "seed": 0,
            "bounds": {"x0": 0.0, "y0": 0.0, "x1": 10.0, "y1": 10.0},
            "groups": [],
        }
        base.update(overrides)
        return base

    def test_load_version_1_accepted(self) -> None:
        scene = load_ink_scene(self._minimal_dict())
        assert scene.scene_version == "1.0"

    def test_load_version_1_minor_forward_accepted(self) -> None:
        scene = load_ink_scene(self._minimal_dict(scene_version="1.99"))
        assert scene.scene_version == "1.99"

    def test_load_version_2_rejected(self) -> None:
        with pytest.raises(UnsupportedSchemaVersionError):
            load_ink_scene(self._minimal_dict(scene_version="2.0"))

    def test_load_missing_version_defaults_to_1(self) -> None:
        d = self._minimal_dict()
        d.pop("scene_version")
        scene = load_ink_scene(d)
        assert scene.scene_version == "1.0"

    def test_load_rejects_extra_fields(self) -> None:
        d = self._minimal_dict(unknown_future_field="hello")
        with pytest.raises(ValidationError):
            load_ink_scene(d)


# ---------------------------------------------------------------------------
# 14. No renderer-specific types in ink/model.py
# ---------------------------------------------------------------------------


class TestNoRendererTypes:
    def test_fitz_not_imported(self) -> None:
        import halfblood.ink.model as m
        assert not hasattr(m, "fitz"), "fitz must not be imported into ink/model"
        source = Path(m.__file__).read_text()
        assert "fitz" not in source, "fitz reference found in ink/model.py"
        assert "SurfacePoint" not in source, "SurfacePoint (fitz-tied) found in ink/model.py"
        assert "SurfaceRect" not in source, "SurfaceRect (fitz-tied) found in ink/model.py"
        assert "SurfaceQuad" not in source, "SurfaceQuad (fitz-tied) found in ink/model.py"


# ---------------------------------------------------------------------------
# 15. Structural hash — stable and discriminating
# ---------------------------------------------------------------------------


class TestSceneStructuralHash:
    def _scene_with_commands(self) -> InkScene:
        path = StrokePath(
            commands=(
                MoveTo(x=10.0, y=20.0),
                LineTo(x=30.0, y=40.0),
                CubicTo(x1=35.0, y1=45.0, x2=55.0, y2=65.0, x=60.0, y=70.0),
            ),
            stroke=_style(),
        )
        grp = InkGroup(group_id="g0", role=InkRole.HANDWRITING, paths=(path,))
        return _minimal_scene(
            bounds=LocalRect(x0=0.0, y0=0.0, x1=100.0, y1=100.0),
            groups=(grp,),
        )

    def test_hash_is_deterministic(self) -> None:
        scene = self._scene_with_commands()
        assert scene_structural_hash(scene) == scene_structural_hash(scene)

    def test_hash_stable_across_json_roundtrip(self) -> None:
        scene = self._scene_with_commands()
        h1 = scene_structural_hash(scene)
        restored = InkScene.model_validate(json.loads(scene.model_dump_json()))
        h2 = scene_structural_hash(restored)
        assert h1 == h2, "structural hash changed after JSON round-trip"

    def test_hash_changes_on_coordinate_change(self) -> None:
        # Change an endpoint by 10 * 10^-_HASH_DECIMALS (well above rounding granularity)
        delta = 10 * 10 ** (-_HASH_DECIMALS)
        path_a = StrokePath(
            commands=(MoveTo(x=10.0, y=20.0), LineTo(x=30.0, y=40.0)),
            stroke=_style(),
        )
        path_b = StrokePath(
            commands=(MoveTo(x=10.0, y=20.0), LineTo(x=30.0 + delta, y=40.0)),
            stroke=_style(),
        )
        grp_a = InkGroup(group_id="g0", role=InkRole.UNDERLINE, paths=(path_a,))
        grp_b = InkGroup(group_id="g0", role=InkRole.UNDERLINE, paths=(path_b,))
        scene_a = _minimal_scene(groups=(grp_a,))
        scene_b = _minimal_scene(groups=(grp_b,))
        assert scene_structural_hash(scene_a) != scene_structural_hash(scene_b), (
            "structural hash must differ when a command coordinate changes "
            "by more than rounding granularity"
        )

    def test_hash_stable_for_noise_below_rounding(self) -> None:
        # Sub-rounding-granularity noise must NOT change the hash
        noise = 0.3 * 10 ** (-_HASH_DECIMALS)
        path_a = StrokePath(
            commands=(MoveTo(x=10.0, y=20.0), LineTo(x=30.0, y=40.0)),
            stroke=_style(),
        )
        path_b = StrokePath(
            commands=(MoveTo(x=10.0, y=20.0), LineTo(x=30.0 + noise, y=40.0)),
            stroke=_style(),
        )
        grp_a = InkGroup(group_id="g0", role=InkRole.UNDERLINE, paths=(path_a,))
        grp_b = InkGroup(group_id="g0", role=InkRole.UNDERLINE, paths=(path_b,))
        scene_a = _minimal_scene(groups=(grp_a,))
        scene_b = _minimal_scene(groups=(grp_b,))
        assert scene_structural_hash(scene_a) == scene_structural_hash(scene_b), (
            "structural hash must be stable for noise smaller than rounding granularity"
        )

    def test_hash_is_32_byte_hex(self) -> None:
        h = scene_structural_hash(self._scene_with_commands())
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)


# ---------------------------------------------------------------------------
# 16. Fixture JSON round-trip
# ---------------------------------------------------------------------------


class TestFixtureRoundtrip:
    def test_minimal_scene_fixture_loads(self) -> None:
        data = json.loads((FIXTURES / "minimal_scene.json").read_text())
        scene = load_ink_scene(data)
        assert scene.annotation_id == "ann-001"
        assert scene.seed == 42
        assert len(scene.groups) == 2
        roles = {g.role for g in scene.groups}
        assert InkRole.UNDERLINE in roles
        assert InkRole.CONNECTOR in roles

    def test_minimal_scene_fixture_roundtrip(self) -> None:
        data = json.loads((FIXTURES / "minimal_scene.json").read_text())
        scene = load_ink_scene(data)
        dumped = json.loads(scene.model_dump_json())
        restored = load_ink_scene(dumped)
        assert scene_structural_hash(scene) == scene_structural_hash(restored)

    def test_minimal_scene_has_width_profile(self) -> None:
        data = json.loads((FIXTURES / "minimal_scene.json").read_text())
        scene = load_ink_scene(data)
        underline_group = next(g for g in scene.groups if g.role == InkRole.UNDERLINE)
        assert len(underline_group.paths[0].width_profile) == 3


# ---------------------------------------------------------------------------
# 17. Pressure sample validation
# ---------------------------------------------------------------------------


class TestPressureSample:
    def test_valid_sample(self) -> None:
        s = PressureSample(x=10.0, y=20.0, pressure=0.5, time=1.23, pen_down=True)
        assert s.pressure == 0.5

    def test_pressure_above_1_rejected(self) -> None:
        class _PermissiveSample(BaseModel):
            pressure: float
        _PermissiveSample(pressure=1.5)
        with pytest.raises(ValidationError):
            PressureSample(x=0.0, y=0.0, pressure=1.5, time=0.0, pen_down=True)

    def test_pressure_below_0_rejected(self) -> None:
        class _PermissiveSample(BaseModel):
            pressure: float
        _PermissiveSample(pressure=-0.1)
        with pytest.raises(ValidationError):
            PressureSample(x=0.0, y=0.0, pressure=-0.1, time=0.0, pen_down=True)

    def test_negative_time_rejected(self) -> None:
        with pytest.raises(ValidationError):
            PressureSample(x=0.0, y=0.0, pressure=0.5, time=-0.001, pen_down=True)


# ---------------------------------------------------------------------------
# 18. Extra fields rejected (extra="forbid")
# ---------------------------------------------------------------------------


class TestExtraForbid:
    def test_extra_field_in_local_rect_rejected(self) -> None:
        with pytest.raises(ValidationError):
            LocalRect(x0=0.0, y0=0.0, x1=10.0, y1=10.0, extra="oops")  # type: ignore[call-arg]

    def test_extra_field_in_stroke_style_rejected(self) -> None:
        with pytest.raises(ValidationError):
            StrokeStyle(color="#000", base_width=1.0, opacity=1.0, unknown=True)  # type: ignore[call-arg]

    def test_extra_field_in_ink_scene_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _minimal_scene(undocumented_field="boom")
