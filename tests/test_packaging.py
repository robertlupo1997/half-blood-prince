"""P0-T12 — dependency bounds, dev reproducibility, and audit-ledger closure.

AUD-38: floor-only dependency specifiers permit silent breaking upgrades.
Every runtime dependency must carry an intentional compatible upper bound,
and development installs must be reproducible from a checked-in lock
artifact. ``anthropic`` was capped below 2 as a core dependency until P1-T5
replaced the SDK with a native ``httpx`` adapter; it now lives only in the
``eval`` extra (still bounded — see ``test_eval_extra_is_present_and_bounded``
and ``test_anthropic_is_absent_from_core_dependencies`` below).

Ledger closure: every audit finding (AUD-01…AUD-44, L-1…L-3) must have an
explicit disposition in the Phase 0 closure report — merged, fixed in a P0
task, deferred to a named P1 task, or blocked-on-key — with no blanks. A
finding that disappears between phases without a row here fails this test.

No network calls are made anywhere in this file.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_CLOSURE = _ROOT / "docs" / "audit" / "2026-07-11-phase0-closure.md"


@pytest.fixture(scope="module")
def pyproject() -> dict:
    return tomllib.loads((_ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def test_every_runtime_dependency_has_an_upper_bound(pyproject: dict) -> None:
    deps = pyproject["project"]["dependencies"]
    assert deps, "no runtime dependencies parsed"
    for spec in deps:
        assert "<" in spec, f"floor-only dependency permits breaking upgrades: {spec!r}"


def test_anthropic_is_absent_from_every_dependency_group(pyproject: dict) -> None:
    """No LLM vendor SDK anywhere -- core or extras.

    P1-T5 moved production Anthropic traffic to a native ``httpx`` adapter but left the
    SDK in the ``eval`` extra, because the eval *judge* still used it. This test asserted
    that boundary: absent from core, present-and-bounded in ``eval``.

    Phase 5 moved the judge onto the same provider seam, so nothing imports the SDK at
    all and the dependency was dropped. The old assertion is now inverted -- it would
    require reintroducing a package no code uses. Updated rather than deleted so the
    stronger property is still pinned: generation *and* judging run over the shared httpx
    seam, and this project depends on no LLM vendor package.
    """
    deps = pyproject["project"]["dependencies"]
    extras = pyproject["project"]["optional-dependencies"]
    everywhere = list(deps) + [spec for group in extras.values() for spec in group]

    offenders = [spec for spec in everywhere if spec.lower().startswith("anthropic")]
    assert not offenders, (
        f"the anthropic SDK is declared but nothing imports it: {offenders}"
    )


def test_eval_extra_is_present_and_bounded(pyproject: dict) -> None:
    extras = pyproject["project"]["optional-dependencies"]
    assert "eval" in extras
    for spec in extras["eval"]:
        assert "<" in spec, f"unbounded eval extra: {spec!r}"


def test_dev_lock_artifact_exists_and_pins_exact_versions() -> None:
    lock = _ROOT / "requirements-dev.lock"
    assert lock.is_file(), "checked-in dev lock artifact missing"
    lines = [
        line.strip()
        for line in lock.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    ]
    assert len(lines) >= 10
    assert all("==" in line for line in lines), "lock must pin exact versions"


def test_readme_documents_the_lock_workflow() -> None:
    readme = (_ROOT / "README.md").read_text(encoding="utf-8")
    assert "requirements-dev.lock" in readme


def test_closure_report_dispositions_every_audit_finding() -> None:
    assert _CLOSURE.is_file(), "Phase 0 closure report missing"
    text = _CLOSURE.read_text(encoding="utf-8")
    rows = dict(
        re.findall(r"^\|\s*(AUD-\d{2}|L-\d)\s*\|\s*([^|]+?)\s*\|", text, re.MULTILINE)
    )
    expected = [f"AUD-{i:02d}" for i in range(1, 45)] + ["L-1", "L-2", "L-3"]
    missing = [item for item in expected if item not in rows]
    assert not missing, f"findings with no disposition row: {missing}"
    blank = [item for item, disposition in rows.items() if not disposition.strip()]
    assert not blank, f"blank dispositions: {blank}"
