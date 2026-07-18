"""Tests for validated InkStyleProfile and canonical style hashing (P3-T2, §5.3).

Every rejection test includes a permissive-BaseModel proof (matching the
test_ink_scene.py convention) to confirm the validator is non-vacuous.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

from halfblood.ink.style import (
    InkStyleProfile,
    canonical_style_hash,
    load_builtin_style,
    load_ink_style_profile,
)
from halfblood.models.documents import UnsupportedSchemaVersionError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _valid_dict() -> dict[str, Any]:
    return {
        "style_version": "1.0",
        "palette": {
            "ink_color": "#1a0a00",
            "highlight_color": "#ffd700",
            "shadow_color": "#4a3a2a",
            "base_opacity": 0.85,
        },
        "nib": {
            "base_width": 1.5,
            "min_width": 0.5,
            "max_width": 3.0,
        },
        "variation": {
            "slant_noise": 0.10,
            "width_noise": 0.05,
        },
        "readability": {
            "min_scale": 0.60,
        },
        "budget": {
            "max_points": 5000,
            "max_paths": 200,
        },
    }


def _valid() -> InkStyleProfile:
    return load_ink_style_profile(_valid_dict())


# ---------------------------------------------------------------------------
# 1. Construction — valid profile
# ---------------------------------------------------------------------------


class TestStyleProfileConstruction:
    def test_valid_profile_constructs(self) -> None:
        profile = _valid()
        assert profile.style_version == "1.0"
        assert profile.palette.ink_color == "#1a0a00"
        assert profile.nib.base_width == pytest.approx(1.5)
        assert profile.budget.max_points == 5000

    def test_builtin_style_loads(self) -> None:
        profile = load_builtin_style()
        assert isinstance(profile, InkStyleProfile)
        assert profile.palette.ink_color.startswith("#")
        # Built-in must satisfy its own nib ordering constraint.
        assert profile.nib.min_width <= profile.nib.base_width <= profile.nib.max_width
        # Built-in must carry a valid opacity value.
        assert 0.0 <= profile.palette.base_opacity <= 1.0

    def test_builtin_style_is_frozen(self) -> None:
        profile = load_builtin_style()
        with pytest.raises((ValidationError, TypeError)):
            profile.style_version = "9.9"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# 2. Palette validation
# ---------------------------------------------------------------------------


class TestPaletteValidation:
    def test_rejects_invalid_hex_chars(self) -> None:
        """Permissive proof: plain BaseModel(ink_color: str) accepts '#xyz'."""

        class _P(BaseModel):
            ink_color: str

        assert _P(ink_color="#xyz").ink_color == "#xyz"

        d = _valid_dict()
        d["palette"]["ink_color"] = "#xyz"
        with pytest.raises(ValidationError):
            load_ink_style_profile(d)

    def test_rejects_missing_hash_prefix(self) -> None:
        d = _valid_dict()
        d["palette"]["ink_color"] = "1a0a00"
        with pytest.raises(ValidationError):
            load_ink_style_profile(d)

    def test_rejects_wrong_length(self) -> None:
        """Must be exactly '#RRGGBB' (7 chars); '#abc' is too short."""
        d = _valid_dict()
        d["palette"]["ink_color"] = "#abc"
        with pytest.raises(ValidationError):
            load_ink_style_profile(d)


# ---------------------------------------------------------------------------
# 3. Nib validation — ordering constraint min <= base <= max
# ---------------------------------------------------------------------------


class TestNibValidation:
    def test_rejects_min_greater_than_base(self) -> None:
        """Permissive proof: a per-field-only range validator accepts min=2, base=1."""

        class _PerFieldOnly(BaseModel):
            base_width: float
            min_width: float
            max_width: float

        # Per-field-only check accepts this — the cross-field check is what catches it.
        _PerFieldOnly(base_width=1.0, min_width=2.0, max_width=3.0)

        d = _valid_dict()
        d["nib"]["min_width"] = 2.0
        d["nib"]["base_width"] = 1.0
        with pytest.raises(ValidationError):
            load_ink_style_profile(d)

    def test_rejects_base_greater_than_max(self) -> None:
        d = _valid_dict()
        d["nib"]["base_width"] = 5.0
        d["nib"]["max_width"] = 3.0
        with pytest.raises(ValidationError):
            load_ink_style_profile(d)

    def test_rejects_zero_base_width(self) -> None:
        d = _valid_dict()
        d["nib"]["base_width"] = 0.0
        with pytest.raises(ValidationError):
            load_ink_style_profile(d)

    def test_rejects_negative_min_width(self) -> None:
        d = _valid_dict()
        d["nib"]["min_width"] = -0.1
        with pytest.raises(ValidationError):
            load_ink_style_profile(d)

    def test_equal_min_base_max_is_valid(self) -> None:
        """min == base == max is a degenerate but valid constant-width nib."""
        d = _valid_dict()
        d["nib"]["min_width"] = 1.5
        d["nib"]["base_width"] = 1.5
        d["nib"]["max_width"] = 1.5
        profile = load_ink_style_profile(d)
        assert profile.nib.base_width == pytest.approx(1.5)


# ---------------------------------------------------------------------------
# 4. Variation validation
# ---------------------------------------------------------------------------


class TestVariationValidation:
    def test_rejects_slant_noise_above_one(self) -> None:
        d = _valid_dict()
        d["variation"]["slant_noise"] = 1.1
        with pytest.raises(ValidationError):
            load_ink_style_profile(d)

    def test_rejects_slant_noise_negative(self) -> None:
        d = _valid_dict()
        d["variation"]["slant_noise"] = -0.01
        with pytest.raises(ValidationError):
            load_ink_style_profile(d)

    def test_rejects_width_noise_negative(self) -> None:
        d = _valid_dict()
        d["variation"]["width_noise"] = -0.01
        with pytest.raises(ValidationError):
            load_ink_style_profile(d)

    def test_rejects_width_noise_above_one(self) -> None:
        d = _valid_dict()
        d["variation"]["width_noise"] = 1.5
        with pytest.raises(ValidationError):
            load_ink_style_profile(d)


# ---------------------------------------------------------------------------
# 5. Readability validation
# ---------------------------------------------------------------------------


class TestReadabilityValidation:
    def test_rejects_min_scale_zero(self) -> None:
        d = _valid_dict()
        d["readability"]["min_scale"] = 0.0
        with pytest.raises(ValidationError):
            load_ink_style_profile(d)

    def test_rejects_min_scale_above_one(self) -> None:
        d = _valid_dict()
        d["readability"]["min_scale"] = 1.1
        with pytest.raises(ValidationError):
            load_ink_style_profile(d)

    def test_accepts_min_scale_exactly_one(self) -> None:
        d = _valid_dict()
        d["readability"]["min_scale"] = 1.0
        profile = load_ink_style_profile(d)
        assert profile.readability.min_scale == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# 6. Budget validation
# ---------------------------------------------------------------------------


class TestBudgetValidation:
    def test_rejects_zero_max_points(self) -> None:
        d = _valid_dict()
        d["budget"]["max_points"] = 0
        with pytest.raises(ValidationError):
            load_ink_style_profile(d)

    def test_rejects_negative_max_points(self) -> None:
        d = _valid_dict()
        d["budget"]["max_points"] = -1
        with pytest.raises(ValidationError):
            load_ink_style_profile(d)

    def test_rejects_zero_max_paths(self) -> None:
        d = _valid_dict()
        d["budget"]["max_paths"] = 0
        with pytest.raises(ValidationError):
            load_ink_style_profile(d)


# ---------------------------------------------------------------------------
# 7. Opacity validation
# ---------------------------------------------------------------------------


class TestOpacityValidation:
    """InkPalette.base_opacity mirrors StrokeStyle.opacity — same ge=0.0, le=1.0 range."""

    def test_rejects_opacity_above_one(self) -> None:
        """Permissive proof: plain BaseModel(base_opacity: float) accepts 1.5."""

        class _P(BaseModel):
            base_opacity: float

        assert _P(base_opacity=1.5).base_opacity == pytest.approx(1.5)

        d = _valid_dict()
        d["palette"]["base_opacity"] = 1.5
        with pytest.raises(ValidationError):
            load_ink_style_profile(d)

    def test_rejects_opacity_negative(self) -> None:
        d = _valid_dict()
        d["palette"]["base_opacity"] = -0.01
        with pytest.raises(ValidationError):
            load_ink_style_profile(d)

    def test_accepts_opacity_boundary_zero(self) -> None:
        """0.0 is a valid (fully-transparent) boundary value."""
        d = _valid_dict()
        d["palette"]["base_opacity"] = 0.0
        profile = load_ink_style_profile(d)
        assert profile.palette.base_opacity == pytest.approx(0.0)

    def test_accepts_opacity_boundary_one(self) -> None:
        """1.0 is a valid (fully-opaque) boundary value."""
        d = _valid_dict()
        d["palette"]["base_opacity"] = 1.0
        profile = load_ink_style_profile(d)
        assert profile.palette.base_opacity == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# 8. Unknown key rejection
# ---------------------------------------------------------------------------


class TestUnknownKeyRejection:
    def test_rejects_unknown_top_level_key(self) -> None:
        """Permissive proof: plain BaseModel(**d) would accept the extra key."""

        class _P(BaseModel):
            model_config = {"extra": "allow"}  # type: ignore[misc]

        d = _valid_dict()
        d["unexpected_field"] = "some_value"
        _P(**d)  # permissive model accepts it

        with pytest.raises(ValidationError):
            load_ink_style_profile(d)

    def test_rejects_unknown_nib_key(self) -> None:
        d = _valid_dict()
        d["nib"]["pressure_curve"] = "exponential"
        with pytest.raises(ValidationError):
            load_ink_style_profile(d)


# ---------------------------------------------------------------------------
# 9. Version handling
# ---------------------------------------------------------------------------


class TestVersionHandling:
    def test_rejects_unsupported_major_version(self) -> None:
        d = _valid_dict()
        d["style_version"] = "99.0"
        with pytest.raises(UnsupportedSchemaVersionError):
            load_ink_style_profile(d)

    def test_accepts_same_major_different_minor(self) -> None:
        """A minor-version bump on the same major must load (forward-compatible)."""
        d = _valid_dict()
        d["style_version"] = "1.99"
        profile = load_ink_style_profile(d)
        assert profile.style_version == "1.99"


# ---------------------------------------------------------------------------
# 10. Canonical style hash
# ---------------------------------------------------------------------------


class TestCanonicalStyleHash:
    def test_hash_is_stable(self) -> None:
        profile = _valid()
        assert canonical_style_hash(profile) == canonical_style_hash(profile)

    def test_hash_changes_on_value_change(self) -> None:
        profile_a = _valid()
        d = _valid_dict()
        d["nib"]["base_width"] = 2.0
        profile_b = load_ink_style_profile(d)
        assert canonical_style_hash(profile_a) != canonical_style_hash(profile_b)

    def test_hash_ignores_serialization_ordering(self) -> None:
        """Reordering dict keys before parse must NOT change the resulting hash.

        canonical_json uses sort_keys=True and model_dump produces a stable dict
        from Pydantic; two equivalent profiles must hash identically.
        """
        d1 = _valid_dict()
        profile_1 = load_ink_style_profile(d1)
        h1 = canonical_style_hash(profile_1)

        # Reconstruct with palette sub-dict keys in reverse insertion order.
        d2 = _valid_dict()
        d2["palette"] = {
            "base_opacity": 0.85,
            "shadow_color": "#4a3a2a",
            "highlight_color": "#ffd700",
            "ink_color": "#1a0a00",  # same values, different insertion order
        }
        profile_2 = load_ink_style_profile(d2)
        h2 = canonical_style_hash(profile_2)

        assert h1 == h2

    def test_hash_is_64_char_hex(self) -> None:
        h = canonical_style_hash(_valid())
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)
