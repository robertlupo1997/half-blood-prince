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


def test_every_file_reference_in_summary_exists() -> None:
    s = _summary()

    def walk(node: object) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if isinstance(value, str) and (
                    key.endswith("_file") or "sidecar_file" in key
                ):
                    path = Path(__file__).resolve().parents[1] / value
                    assert path.is_file(), f"summary references missing file: {value}"
                else:
                    walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(s)


def test_provenance_names_the_sha_that_ran() -> None:
    """The recorded code sha must name the commit that produced the evidence.

    Checkable at ANY future HEAD (a HEAD-pinning assertion would invalidate
    itself on the very next commit): the sha must be a real ancestor of
    HEAD, distinct from the non-reproducing base, AND the last commit that
    touched scripts/stress_400.py as of that sha -- i.e. it names exactly
    the code version that produced this evidence.
    """
    import subprocess

    s = _summary()
    sha = s["executed_code_sha"]
    base = s["base_commit_before_fixes"]
    repo = EVIDENCE.parents[1]

    def git(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", "-C", str(repo), *args], capture_output=True, text=True,
        )

    assert len(sha) >= 7 and sha != base  # d28f625 cannot run the primary path
    assert git("cat-file", "-e", f"{sha}^{{commit}}").returncode == 0
    assert git("merge-base", "--is-ancestor", sha, "HEAD").returncode == 0
    last_touch = git(
        "log", "-1", "--format=%h", sha, "--", "scripts/stress_400.py",
    ).stdout.strip()
    assert last_touch == sha, (
        f"executed_code_sha {sha} is not the last commit touching "
        f"scripts/stress_400.py (that is {last_touch!r})"
    )


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
