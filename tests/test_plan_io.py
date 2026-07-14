"""Controller-authored, test-first contract for P1-T8 (plan_io persistence).

Ground truth: docs/superpowers/specs/2026-07-11-full-project-architecture.md §§6.2, 9;
.superpowers/sdd/p1-t8-subdriver-spec.md. These tests are the frozen interface
Codex builds against -- do not edit them to make an implementation pass.

No network calls anywhere in this file.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import halfblood.plan_io as plan_io_module
from halfblood.generation.report import GenerationReport, PageGenerationStatus
from halfblood.generation.schema import generate_annotation_schema, schema_hash
from halfblood.models.documents import (
    AnnotationPlan as AnnotationPlanV2,
)
from halfblood.models.documents import (
    GenerationProvenance,
    SourceInfo,
    UnsupportedSchemaVersionError,
)
from halfblood.plan_io import load_plan, save_plan

# ---------------------------------------------------------------------------
# Sentinel / constants
# ---------------------------------------------------------------------------

#: A fake API key used to prove it never leaks into the saved artifact.
_SENTINEL_KEY = "sk-ant-sentinel-xyzzy-not-real"

#: Fixed UUID so _make_plan() is deterministic across two calls.
_PLAN_ID = "a1b2c3d4-1234-5678-9abc-def012345678"

#: Pre-computed schema hash — provenance test asserts this is persisted.
_SCHEMA_HASH = schema_hash(generate_annotation_schema())

#: A minimal v1 fixture (no schema_version) for migration tests.
_V1_FIXTURE = {
    "title": "Advanced Potion-Making",
    "prince_persona": "A brilliant, sardonic expert.",
    "pages": [
        {
            "page_number": 1,
            "original_text": "Add the wormwood slowly.",
            "annotations": [
                {
                    "page": 1,
                    "target_text": "wormwood slowly",
                    "annotation_type": "correction",
                    "content": "Crush it first.",
                    "confidence": 0.9,
                    "position": "margin_right",
                }
            ],
        }
    ],
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_plan() -> AnnotationPlanV2:
    """Return a deterministic v2 plan with filled provenance for round-trip tests."""
    return AnnotationPlanV2(
        id=_PLAN_ID,
        title="Test Book",
        persona="sardonic annotator",
        source=SourceInfo(
            fingerprint="sha256-abc123",
            media_type="application/pdf",
            unit_count=0,
        ),
        generation=GenerationProvenance(
            provider="anthropic",
            model="claude-sonnet-5",
            schema_hash=_SCHEMA_HASH,
            structured_output_mode="tool",
        ),
        document_seed=42,
    )


def _make_report() -> GenerationReport:
    return GenerationReport(
        statuses=(
            PageGenerationStatus(unit_id="u-1", ordinal=1, status="success", attempts=1),
            PageGenerationStatus(unit_id="u-2", ordinal=2, status="skipped", attempts=0),
        )
    )


# ---------------------------------------------------------------------------
# 1. Save + reload round-trip
# ---------------------------------------------------------------------------


def test_save_and_reload_v2_plan_round_trips(tmp_path: Path) -> None:
    """save_plan then load_plan returns a deep-equal AnnotationPlanV2."""
    plan = _make_plan()
    dest = tmp_path / "plan.json"

    save_plan(plan, dest)
    loaded_plan, loaded_report = load_plan(dest)

    assert loaded_plan.model_dump_json() == plan.model_dump_json()
    assert loaded_report is None


def test_save_and_reload_with_report_round_trips(tmp_path: Path) -> None:
    """A GenerationReport saved alongside a plan is reloaded faithfully."""
    plan = _make_plan()
    report = _make_report()
    dest = tmp_path / "plan.json"

    save_plan(plan, dest, report=report)
    loaded_plan, loaded_report = load_plan(dest)

    assert loaded_plan.model_dump_json() == plan.model_dump_json()
    assert loaded_report is not None
    assert len(loaded_report.statuses) == 2
    assert loaded_report.statuses[0].unit_id == "u-1"
    assert loaded_report.statuses[0].status == "success"
    assert loaded_report.statuses[1].unit_id == "u-2"
    assert loaded_report.statuses[1].status == "skipped"


def test_save_is_deterministic(tmp_path: Path) -> None:
    """Two save_plan calls with the same plan produce byte-identical files."""
    plan = _make_plan()
    dest_a = tmp_path / "a.json"
    dest_b = tmp_path / "b.json"

    save_plan(plan, dest_a)
    save_plan(plan, dest_b)

    assert dest_a.read_bytes() == dest_b.read_bytes()


# ---------------------------------------------------------------------------
# 2. Provenance in the saved artifact
# ---------------------------------------------------------------------------


def test_saved_artifact_has_provenance(tmp_path: Path) -> None:
    """The saved file contains schema_hash, provider, model, and schema_version."""
    plan = _make_plan()
    dest = tmp_path / "plan.json"
    save_plan(plan, dest)

    data = json.loads(dest.read_text(encoding="utf-8"))
    # plan_io uses a {"_hbp": "1.0", "plan": {...}, "report": ...} wrapper [INFER]
    assert data.get("_hbp") == "1.0"
    plan_data = data["plan"]

    assert plan_data.get("schema_version") == "2.0"
    gen = plan_data.get("generation", {})
    assert gen.get("schema_hash") == _SCHEMA_HASH
    assert gen.get("provider") == "anthropic"
    assert gen.get("model") == "claude-sonnet-5"


# ---------------------------------------------------------------------------
# 3. No secrets / no raw prompts persisted
# ---------------------------------------------------------------------------


def test_saved_artifact_has_no_api_key(tmp_path: Path) -> None:
    """The sentinel API key must not appear anywhere in the saved file bytes."""
    # The key is never part of AnnotationPlanV2 — this guards against accidental
    # environment variable leakage if plan_io were to inadvertently read os.environ.
    plan = _make_plan()
    dest = tmp_path / "plan.json"
    save_plan(plan, dest)

    raw = dest.read_bytes()
    assert _SENTINEL_KEY.encode() not in raw


def test_saved_artifact_has_no_raw_prompt_keys(tmp_path: Path) -> None:
    """system_prompt and user_prompt must not appear as keys in the saved file."""
    plan = _make_plan()
    dest = tmp_path / "plan.json"
    save_plan(plan, dest)

    raw = dest.read_bytes()
    assert b"system_prompt" not in raw
    assert b"user_prompt" not in raw


# ---------------------------------------------------------------------------
# 4. Overwrite protection
# ---------------------------------------------------------------------------


def test_refuse_overwrite_without_force(tmp_path: Path) -> None:
    """save_plan raises FileExistsError when dest exists and force is False."""
    plan = _make_plan()
    dest = tmp_path / "plan.json"
    original = b"precious bytes"
    dest.write_bytes(original)

    with pytest.raises(FileExistsError):
        save_plan(plan, dest)

    assert dest.read_bytes() == original


def test_overwrite_with_force(tmp_path: Path) -> None:
    """save_plan(force=True) silently overwrites an existing file."""
    plan = _make_plan()
    dest = tmp_path / "plan.json"
    dest.write_bytes(b"old bytes")

    save_plan(plan, dest, force=True)

    loaded_plan, _ = load_plan(dest)
    assert loaded_plan.model_dump_json() == plan.model_dump_json()


# ---------------------------------------------------------------------------
# 5. Atomic write: a failing os.replace must leave existing dest intact
# ---------------------------------------------------------------------------


def test_atomic_write_failure_leaves_dest_intact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failing os.replace must leave the existing destination byte-for-byte intact.

    The implementation must `import os` at module level so this monkeypatch takes
    effect. [INFER - pinned in brief]
    """
    plan = _make_plan()
    dest = tmp_path / "plan.json"
    original = b'{"_hbp":"1.0","plan":{"existing":true},"report":null}'
    dest.write_bytes(original)

    def _fail_replace(src: str, dst: str) -> None:
        # Remove the temp file (as if cleanup happened) then fail — dest must survive.
        Path(src).unlink(missing_ok=True)
        raise OSError("simulated replace failure")

    monkeypatch.setattr(plan_io_module.os, "replace", _fail_replace)

    with pytest.raises(OSError):
        save_plan(plan, dest, force=True)

    assert dest.read_bytes() == original


# ---------------------------------------------------------------------------
# 6. v1→v2 migration on load and version guard
# ---------------------------------------------------------------------------


def test_load_v1_fixture_migrates_to_v2(tmp_path: Path) -> None:
    """load_plan on a plain v1 JSON file (no _hbp wrapper) returns a migrated AnnotationPlanV2."""
    dest = tmp_path / "v1plan.json"
    dest.write_text(json.dumps(_V1_FIXTURE), encoding="utf-8")

    loaded_plan, loaded_report = load_plan(dest)

    assert isinstance(loaded_plan, AnnotationPlanV2)
    assert loaded_plan.schema_version == "2.0"
    assert loaded_plan.title == _V1_FIXTURE["title"]
    assert loaded_report is None


def test_load_v2_round_trips(tmp_path: Path) -> None:
    """load_plan on a v2 plan saved by save_plan returns the original plan."""
    original = _make_plan()
    dest = tmp_path / "v2plan.json"
    save_plan(original, dest)

    loaded, _ = load_plan(dest)
    assert loaded.model_dump_json() == original.model_dump_json()


def test_load_unknown_major_version_rejected(tmp_path: Path) -> None:
    """load_plan rejects a plan whose schema_version has an unknown major version."""
    plan = _make_plan()
    dest = tmp_path / "futuristic.json"
    save_plan(plan, dest)

    data = json.loads(dest.read_text(encoding="utf-8"))
    # Mutate the nested plan's schema_version to an unknown future major version.
    data["plan"]["schema_version"] = "99.0"
    dest.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UnsupportedSchemaVersionError):
        load_plan(dest)
