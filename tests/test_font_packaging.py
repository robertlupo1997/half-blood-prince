"""P3-T11 — the handwriting fonts must ship inside the installed package and
resolve without a repo checkout (installed-wheel simulation), with full license
provenance.

Controller-owned test file (SDD lean loop). Codex must NOT modify this file.

Fonts were license-cleared on 2026-07-19 from embedded name-table metadata:
  - Caveat Brush              OFL 1.1 (Google / Pablo Impallari, v1.096) — no RFN
  - Homemade Apple            Apache-2.0 (Font Diner, v1.001)
  - Just Me Again Down Here   OFL 1.1 (Kimberly Geswein, v1.002) — no RFN
  - Mrs Saint Delafield       OFL 1.1 (Sudtipos, v1.001) — RFN "Mrs Saint Delafield"
See docs/decisions/stroke-assets.md and the plan's P3-T11.
"""

from __future__ import annotations

import hashlib
import importlib.resources as resources
from pathlib import Path

import pytest

from halfblood.document_processor import DocumentProcessor

# The four cleared fonts, pinned to the exact cleared artifact (sha256). "unmodified"
# means the packaged bytes equal these — OFL/Apache both require either unmodified
# redistribution or explicit modification handling (and the RFN forbids modified reuse
# of the Mrs Saint Delafield name).
CLEARED_FONTS: dict[str, str] = {
    "CaveatBrush-Regular.ttf": "e565bd7bffd895ca64f8d1cb77c816b9b38d9c010246386a07c9648592f6f282",
    "HomemadeApple-Regular.ttf": "dd1baaca3cde1b1f8415aed3b0aea6808655c9d9ca5a99c7282d9accc16c1a58",
    "JustMeAgainDownHere.ttf": "0412aa1e460666d339738991b48e9f4bd51e10b6f04e2e1341fce4d2b3244c31",
    "MrsSaintDelafield-Regular.ttf": "67a7abc298ce9d368b2c00fcbff52ec54be948889b8a59032ae80ca3322e5b34",
}
DEFAULT_FONT = "CaveatBrush-Regular.ttf"


def _pkg_fonts_dir() -> Path:
    """The fonts directory that ships inside the installed `halfblood` package."""
    return Path(str(resources.files("halfblood").joinpath("fonts")))


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _notices_text() -> str:
    notices = _repo_root() / "THIRD_PARTY_NOTICES.md"
    assert notices.is_file(), "THIRD_PARTY_NOTICES.md is missing at the repo root"
    return notices.read_text(encoding="utf-8")


# --- packaging: fonts live inside the installed package -------------------------------

def test_bundled_fonts_dir_exists() -> None:
    assert _pkg_fonts_dir().is_dir(), (
        f"expected packaged fonts at {_pkg_fonts_dir()} so the wheel ships them"
    )


@pytest.mark.parametrize("name", list(CLEARED_FONTS))
def test_every_cleared_font_is_packaged(name: str) -> None:
    assert (_pkg_fonts_dir() / name).is_file(), f"font not packaged inside halfblood: {name}"


@pytest.mark.parametrize(("name", "expected_sha"), list(CLEARED_FONTS.items()))
def test_packaged_fonts_are_byte_unmodified(name: str, expected_sha: str) -> None:
    data = (_pkg_fonts_dir() / name).read_bytes()
    assert hashlib.sha256(data).hexdigest() == expected_sha, (
        f"{name} differs from the license-cleared artifact — redistribution must be "
        f"byte-unmodified (RFN/OFL/Apache obligations)"
    )


# --- resolution: installed-wheel simulation (no repo fonts) ---------------------------

def test_default_font_resolves_from_package_not_helvetica(tmp_path: Path) -> None:
    """With an empty project_root (as in a pip-installed wheel with no repo `fonts/`),
    the processor must resolve the bundled default font via package resources and must
    NOT degrade to Helvetica-Oblique. The package candidate must also outrank the
    hardcoded system-font paths (so this asserts the packaged copy specifically)."""
    dp = DocumentProcessor(project_root=str(tmp_path))
    assert dp._fontfile is not None, "resolution fell back to Helvetica in installed-wheel sim"
    assert dp._fontname != "Helvetica-Oblique"
    assert Path(dp._fontfile).name == DEFAULT_FONT
    assert Path(dp._fontfile).resolve() == (_pkg_fonts_dir() / DEFAULT_FONT).resolve(), (
        "default font did not resolve to the packaged copy"
    )


# --- provenance: THIRD_PARTY_NOTICES.md + bundled license texts -----------------------

@pytest.mark.parametrize("name", list(CLEARED_FONTS))
def test_every_font_has_a_notices_row(name: str) -> None:
    assert name in _notices_text(), f"THIRD_PARTY_NOTICES.md has no row for {name}"


def test_notices_declare_both_license_families() -> None:
    text = _notices_text()
    assert "Open Font License" in text or "OFL" in text, "OFL not declared in notices"
    assert "Apache" in text, "Apache-2.0 (Homemade Apple) not declared in notices"


def test_mrs_saint_delafield_reserved_font_name_is_recorded() -> None:
    text = _notices_text()
    assert "Reserved Font Name" in text, "RFN obligation not recorded"
    assert "Mrs Saint Delafield" in text, "RFN font name not recorded"


def test_license_texts_are_bundled_with_the_fonts() -> None:
    fonts_dir = _pkg_fonts_dir()
    names = {p.name for p in fonts_dir.iterdir()} if fonts_dir.is_dir() else set()
    assert "OFL.txt" in names, "SIL OFL license text must ship alongside the OFL fonts"
    assert any("Apache" in n for n in names), (
        "Apache-2.0 license text must ship alongside Homemade Apple"
    )
