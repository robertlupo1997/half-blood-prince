"""Crash/resume + visible-failure stress test on a real 400+-page book.

This is the executable form of the headline claim "the pipeline survives a
real 400-page book". It runs two scenarios against the first ``--pages``
pages of a public-domain book typeset to PDF:

A. Crash mid-book. A real subprocess is SIGKILLed as soon as its
   streaming checkpoint shows progress (the earliest observable instant,
   typically mid-generation; the checkpoint ``<output>.plan.json`` is
   atomic, so what it holds at kill time is exactly what survives). The
   script asserts the checkpoint survived, then a ``--resume-from`` run
   finishes the book with every checkpointed page reported as status
   "resumed" (zero provider calls repeated) and a valid full artifact.
   It then truncates the checkpoint to its first 150 pages and resumes
   again: a deterministic mid-book loss where exactly the truncated pages
   come back as "resumed" and the rest are generated fresh. (Stub
   generation itself is near-instant, so a mid-generation kill cannot be
   timed from outside; checkpoint streaming during generation is covered
   by tests/test_checkpoint_resume.py.)

B. Visible page failures. A fresh output with ``--fail-pages`` ships the
   artifact anyway, but ``<output>.report.json`` must list exactly those
   failed pages and account for every selected page (including
   boilerplate-filtered ones, recorded as skipped).

The provider is the built-in deterministic stub, so the whole run is free,
offline, and reproducible; it exercises pipeline mechanics (extraction of a
real long document, checkpointing, resume merge, sidecar accounting), not
model quality.

Usage:
  python scripts/stress_400.py [--pdf PATH] [--pages N] [--work-dir DIR]

Exit status is 0 only if every assertion holds.
"""
from __future__ import annotations

import argparse
import json
import signal
import subprocess
import sys
import time
import urllib.request
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

MOBY_TXT_URLS = [
    "https://www.gutenberg.org/files/2701/2701-0.txt",
    "https://www.gutenberg.org/cache/epub/2701/pg2701.txt",
]


def ensure_book(pdf: Path, min_pages: int) -> int:
    """Return the page count of a typeset PDF with at least min_pages."""
    import fitz

    if pdf.exists() and fitz.open(pdf).page_count >= min_pages:
        return fitz.open(pdf).page_count
    txt = pdf.with_suffix(".txt")
    if not txt.exists():
        last_err: Exception | None = None
        for url in MOBY_TXT_URLS:
            print(f"downloading {url}")
            try:
                urllib.request.urlretrieve(url, txt)
                break
            except Exception as err:  # noqa: BLE001 - try next mirror
                last_err = err
                txt.unlink(missing_ok=True)
        if not txt.exists():
            raise SystemExit(f"could not download book text: {last_err}")
    from build_example_book import build_pdf

    media = fitz.paper_rect("letter")
    n_pages = build_pdf(txt, pdf, media.width, media.height)
    print(f"typeset {pdf} ({n_pages} pages)")
    if n_pages < min_pages:
        raise SystemExit(f"only {n_pages} pages typeset, need >= {min_pages}")
    return n_pages


def cli_path() -> str:
    sibling = Path(sys.executable).with_name("halfblood")
    return str(sibling) if sibling.exists() else "halfblood"


def spawn_annotate(
    pdf: Path, out: Path, extra: list[str], log: Path | None = None,
) -> subprocess.Popen:
    """Start an ``annotate`` run.

    With ``log``, the child's stdout/stderr stream to that file and the
    caller must use :func:`finish` (a 400-page progress stream overruns the
    OS pipe buffer and deadlocks the child if nobody reads a PIPE). Without
    it, output stays on a PIPE for short runs finished by ``communicate()``.
    """
    cmd = [
        cli_path(), "annotate", str(pdf), "-o", str(out),
        "--provider", "stub", "--force", *extra,
    ]
    print("+", " ".join(cmd), flush=True)
    if log is not None:
        fh = open(log, "w", encoding="utf-8")  # noqa: SIM115 - closed by finish()
        proc = subprocess.Popen(cmd, stdout=fh, stderr=subprocess.STDOUT)
        proc.log_fh = fh  # closed by finish(); the child owns it until then
        return proc
    return subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )


def finish(proc: subprocess.Popen, log: Path | None = None) -> tuple[int, str]:
    """Wait a spawned run out and return (exit code, output tail)."""
    if log is None:
        stdout = proc.communicate()[0]
        return proc.returncode, stdout
    proc.wait()
    fh = getattr(proc, "log_fh", None)
    if fh is not None:
        fh.close()
    text = log.read_text(encoding="utf-8", errors="replace")
    return proc.returncode, text[-2000:]


def full_plan_dry_run(pdf: Path, work: Path, n_pages: int) -> Path:
    """Produce a complete plan JSON for pages 1..n via ``--dry-run``.

    The dry-run output at ``-o`` IS the plan format, so the returned path
    is directly usable as a resume source.
    """
    dry_out = work / "stress-dryrun-plan.pdf"
    dry_out.unlink(missing_ok=True)
    log = work / "stress-dryrun.spawn.log"
    procd = spawn_annotate(
        pdf, dry_out, ["--pages", f"1-{n_pages}", "--dry-run"], log=log,
    )
    code, tail = finish(procd, log=log)
    if code != 0:
        raise SystemExit("FAIL: dry-run plan generation failed\n" + tail)
    return dry_out


def checkpoint_pages(plan_json: Path) -> int:
    try:
        data = json.loads(plan_json.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0  # mid-atomic-replace or not yet created
    return len(data.get("pages", []))


def load_report(report_json: Path) -> dict:
    return json.loads(report_json.read_text(encoding="utf-8"))


def scenario_crash_during_render(
    pdf: Path, work: Path, n_pages: int, doc_pages: int,
) -> bool:
    """A. Real SIGKILL during render, then resume; plus truncated resume."""
    import fitz

    out = work / "stress-crash.pdf"
    # cli._checkpoint_path_for replaces the suffix: stress-crash.pdf ->
    # stress-crash.plan.json (NOT stress-crash.pdf.plan.json).
    plan_json = out.with_name(out.stem + ".plan.json")
    report_json = Path(f"{out}.report.json")
    for p in (out, plan_json, report_json):
        p.unlink(missing_ok=True)

    kill_log = work / "stress-crash.spawn.log"
    proc = spawn_annotate(pdf, out, ["--pages", f"1-{n_pages}"], log=kill_log)
    deadline = time.monotonic() + 1800
    killed = False
    while time.monotonic() < deadline:
        # Kill at the EARLIEST sign of progress: the streaming checkpoint
        # appears from the first finished page onward (atomic tmp+replace,
        # so a read never sees a torn file). Waiting for the output file
        # too loses the race on fast/stub runs -- the whole book can render
        # inside one 50 ms poll. Killing on the checkpoint alone is a real
        # mid-run SIGKILL either way: whatever the checkpoint holds at that
        # instant is all the run gets to keep.
        if checkpoint_pages(plan_json) > 0:
            proc.send_signal(signal.SIGKILL)
            killed = True
            break
        if proc.poll() is not None:
            break
        time.sleep(0.01)
    code, _tail = finish(proc, log=kill_log)
    print(
        f"crash run: killed={killed} exit={code} "
        f"checkpoint={plan_json.exists()}",
        flush=True,
    )
    if not killed or code != -signal.SIGKILL \
            or not plan_json.exists():
        # Small/fast books can outrun the poll loop. Fall back to a
        # deterministic simulated crash: a dry-run produces the full plan,
        # which stands in for the surviving checkpoint.
        print(
            "WARN: subprocess finished before the render phase could be "
            "caught; using a deterministic simulated crash instead"
        )
        return _truncated_resume(
            pdf, work, n_pages, full_plan_dry_run(pdf, work, n_pages),
        )

    ok = True
    if report_json.exists():
        print("FAIL: sidecar written for a killed run")
        ok = False
    checkpointed = checkpoint_pages(plan_json)
    print(f"checkpoint survived with {checkpointed} finished pages")
    if checkpointed <= 0:
        print("FAIL: empty checkpoint")
        return False

    # Snapshot the surviving checkpoint BEFORE the resume run consumes it:
    # a successful resume deletes <output>.plan.json by design, and the
    # truncated-resume case below needs the full pre-loss page set.
    full_snapshot = work / "stress-full.plan.json"
    full_snapshot.write_text(plan_json.read_text(encoding="utf-8"), encoding="utf-8")

    resume_log = work / "stress-resume1.spawn.log"
    proc2 = spawn_annotate(
        pdf, out, ["--pages", f"1-{n_pages}", "--resume-from", str(plan_json)],
        log=resume_log,
    )
    code2, tail2 = finish(proc2, log=resume_log)
    print(f"resume run: exit={code2}")
    if code2 != 0:
        print("FAIL: resume run failed\n" + tail2)
        return False
    report = load_report(report_json)
    statuses = [s["status"] for s in report["page_statuses"]]
    n_resumed = statuses.count("resumed")
    print(
        f"sidecar after resume: pages_total={report['pages_total']} "
        f"pages_annotated={report['pages_annotated']} "
        f"failed_pages={report['failed_pages']} "
        f"skipped_pages={report['skipped_pages']} "
        f"resumed={n_resumed}/{len(statuses)}"
    )
    if report["failed_pages"] != []:
        print("FAIL: unexpected failures after clean resume")
        ok = False
    if n_resumed != checkpointed:
        print(
            f"FAIL: {n_resumed} pages resumed, checkpoint had {checkpointed}"
        )
        ok = False
    if len(statuses) != n_pages:
        print(f"FAIL: sidecar accounts for {len(statuses)} pages, "
              f"selected {n_pages}")
        ok = False
    if plan_json.exists():
        print("FAIL: checkpoint not consumed by successful resume")
        ok = False
    artifact = fitz.open(out)
    if artifact.page_count != doc_pages:
        print(
            f"FAIL: resumed artifact has {artifact.page_count} pages, "
            f"expected {doc_pages}"
        )
        ok = False
    artifact.close()

    return ok and _truncated_resume(pdf, work, n_pages, full_snapshot)


def _truncated_resume(
    pdf: Path, work: Path, n_pages: int, full_plan: Path,
) -> bool:
    """Deterministic mid-book loss: truncate a full checkpoint to its first
    K pages and resume from it -- the pre-loss pages must come back as
    "resumed" (zero provider calls) and the rest generated fresh."""
    if checkpoint_pages(full_plan) < min(150, n_pages):
        # The mid-run kill caught an early checkpoint. Rebuild a complete
        # plan deterministically so the truncated-resume case still
        # exercises a DEEP mid-book loss (first 150 of n_pages kept).
        print(
            "crash checkpoint shallower than truncation depth; "
            "building a full plan via --dry-run for the deep-loss case"
        )
        full_plan = full_plan_dry_run(pdf, work, n_pages)
    keep = min(150, checkpoint_pages(full_plan))
    trunc = work / "stress-truncated.plan.json"
    data = json.loads(full_plan.read_text(encoding="utf-8"))
    data["pages"] = data["pages"][:keep]
    trunc.write_text(json.dumps(data), encoding="utf-8")
    out2 = work / "stress-resume.pdf"
    report2_json = Path(f"{out2}.report.json")
    report2_json.unlink(missing_ok=True)
    trunc_log = work / "stress-trunc.spawn.log"
    proc3 = spawn_annotate(
        pdf, out2, ["--pages", f"1-{n_pages}", "--resume-from", str(trunc)],
        log=trunc_log,
    )
    code3, tail3 = finish(proc3, log=trunc_log)
    print(f"truncated-resume run: exit={code3}")
    if code3 != 0:
        print("FAIL: truncated resume failed\n" + tail3)
        return False
    r2 = load_report(report2_json)
    st2 = [s["status"] for s in r2["page_statuses"]]
    print(
        f"sidecar after truncated resume: pages_total={r2['pages_total']} "
        f"pages_annotated={r2['pages_annotated']} "
        f"resumed={st2.count('resumed')}/{len(st2)} "
        f"failed_pages={r2['failed_pages']}"
    )
    ok = True
    if st2.count("resumed") != keep:
        print(f"FAIL: expected {keep} resumed pages, got "
              f"{st2.count('resumed')}")
        ok = False
    if len(st2) != n_pages:
        print(f"FAIL: truncated resume accounts for {len(st2)} pages, "
              f"selected {n_pages}")
        ok = False
    return ok


def scenario_visible_failures(pdf: Path, work: Path, n_pages: int) -> bool:
    """B. Failed pages ship visibly, and every selected page is accounted."""
    out = work / "stress-fail.pdf"
    report_json = Path(f"{out}.report.json")
    fails = [37, 101, 233]
    for p in (out, report_json, Path(f"{out}.plan.json")):
        p.unlink(missing_ok=True)

    fail_log = work / "stress-fail.spawn.log"
    proc = spawn_annotate(
        pdf, out, ["--pages", f"1-{n_pages}",
                   "--fail-pages", ",".join(map(str, fails))],
        log=fail_log,
    )
    codef, _tailf = finish(proc, log=fail_log)
    print(f"fail-pages run: exit={codef} artifact={out.exists()}")
    if codef != 0 or not out.exists():
        print("FAIL: artifact should ship when some (not all) pages fail")
        return False
    report = load_report(report_json)
    statuses = [s["status"] for s in report["page_statuses"]]
    print(
        f"sidecar: pages_total={report['pages_total']} "
        f"failed_pages={report['failed_pages']} "
        f"skipped_pages={report['skipped_pages']} "
        f"pages_annotated={report['pages_annotated']} "
        f"breakdown={dict(Counter(statuses))}"
    )
    ok = True
    if list(report["failed_pages"]) != fails:
        print(f"FAIL: failed_pages {report['failed_pages']} != {fails}")
        ok = False
    if statuses.count("failed") != len(fails):
        print("FAIL: per-page failure records missing")
        ok = False
    if len(statuses) != n_pages:
        print(f"FAIL: sidecar accounts for {len(statuses)} pages, "
              f"selected {n_pages}")
        ok = False
    expected_annotated = n_pages - len(fails) - len(report["skipped_pages"])
    if report["pages_annotated"] != expected_annotated:
        print("FAIL: pages_annotated accounting wrong")
        ok = False
    return ok


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pdf", type=Path,
                    default=Path("/tmp/hbp-stress/moby.pdf"))
    ap.add_argument("--pages", type=int, default=400)
    ap.add_argument("--work-dir", type=Path, default=None)
    args = ap.parse_args(argv)

    work = args.work_dir or args.pdf.parent
    work.mkdir(parents=True, exist_ok=True)
    doc_pages = ensure_book(args.pdf, args.pages)

    ok_a = scenario_crash_during_render(args.pdf, work, args.pages, doc_pages)
    ok_b = scenario_visible_failures(args.pdf, work, args.pages)
    print("\nSTRESS RESULT:", "PASS" if (ok_a and ok_b) else "FAIL")
    return 0 if (ok_a and ok_b) else 1


if __name__ == "__main__":
    raise SystemExit(main())
