"""Guards for the committed 400-page stress-run evidence (eval/stress-400/).

The README claims a real crash/resume stress run happened and passed. These
tests keep that claim falsifiable: the artifacts must exist and the numbers in
the summary must still match the committed per-page sidecars.
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

EVIDENCE = Path(__file__).resolve().parents[1] / "eval" / "stress-400"


def _summary() -> dict:
    return json.loads((EVIDENCE / "summary.json").read_text(encoding="utf-8"))


def _sidecar(name: str) -> dict:
    return json.loads((EVIDENCE / name).read_text(encoding="utf-8"))


def test_evidence_directory_is_complete() -> None:
    required = [
        "summary.json",
        "README.md",
        "console.log",
        "stress-crash-resume.report.json",
        "stress-truncated-resume.report.json",
        "stress-fail.report.json",
    ]
    missing = [n for n in required if not (EVIDENCE / n).is_file()]
    assert missing == [], f"missing committed evidence: {missing}"


def test_run_verdict_was_pass() -> None:
    s = _summary()
    assert s["exit_status"] == 0
    assert s["verdict_line"] == "STRESS RESULT: PASS"
    console = (EVIDENCE / "console.log").read_text(encoding="utf-8")
    assert "STRESS RESULT: PASS" in console
    assert "killed=True exit=-9" in console


def test_crash_resume_numbers_match_sidecar() -> None:
    s = _summary()["scenario_A_real_crash_and_resume"]
    r = _sidecar("stress-crash-resume.report.json")
    statuses = Counter(p["status"] for p in r["page_statuses"])
    # every checkpointed page came back as resumed, none repeated a call
    assert statuses["resumed"] == s["checkpoint_pages_surviving"] > 0
    assert r["pages_total"] == s["pages_total"] == 400
    assert r["pages_annotated"] == s["pages_annotated"]
    assert r["failed_pages"] == s["failed_pages"] == []


def test_truncated_resume_recovered_exactly_kept_pages() -> None:
    s = _summary()["scenario_A2_deep_truncated_loss_and_resume"]
    r = _sidecar("stress-truncated-resume.report.json")
    statuses = Counter(p["status"] for p in r["page_statuses"])
    assert statuses["resumed"] == s["kept_pages"] == 150
    assert len(r["page_statuses"]) == 400


def test_visible_failures_match_injected_pages() -> None:
    s = _summary()["scenario_B_visible_page_failures"]
    r = _sidecar("stress-fail.report.json")
    statuses = Counter(p["status"] for p in r["page_statuses"])
    injected = sorted(s["injected_failures"])
    assert sorted(r["failed_pages"]) == injected
    assert statuses["failed"] == len(injected)
    assert len(r["page_statuses"]) == 400
