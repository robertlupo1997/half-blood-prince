#!/usr/bin/env python
"""Build a wheel, install it into a throwaway venv OUTSIDE the repo, and use it.

Why this exists
---------------
Twice now a bug has shipped broken in every installed wheel while 1600+ tests and
both linters stayed green, because **the development tree has files the wheel does
not**:

* ``--font <name>`` resolved fonts via ``__file__.parents[2]``, which is the
  repo-root ``fonts/`` directory in a checkout (present locally, gitignored) and a
  path *above* site-packages from a wheel. Every installed user got "Font is not
  installed. Download it from ..." for a font that ships inside the package.
* ``halfblood eval`` resolved its harness via ``__file__.parents[2] / "eval"``,
  and the wheel packages only ``src/halfblood`` — so the command could not work
  for any installed user.

Both are the same failure: **path arithmetic relative to the repo**. A test run
from the source tree cannot see either one, because in the source tree the paths
happen to exist. The only thing that catches this class is using the real artifact.

This script is that check, and it is deliberately cheap enough to run in CI.

What it asserts
---------------
1. The wheel builds.
2. It installs into a clean venv created outside the repo, with no source tree in
   sight and the repo directory not on ``sys.path``.
3. Every packaged data file the code expects is actually inside the wheel.
4. The installed console script runs, and each user-facing command either works or
   fails with an actionable message — never a traceback, and never a message that
   names a nonsense path.

Run directly: ``python scripts/wheel_smoke.py``
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import venv
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# Data files the package resolves at runtime via importlib.resources. If one of
# these stops being packaged, the feature that needs it breaks only for installed
# users -- exactly the bug class this script exists to catch.
REQUIRED_WHEEL_MEMBERS = (
    "halfblood/fonts/CaveatBrush-Regular.ttf",
    "halfblood/personas/",
)

failures: list[str] = []
notes: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  -- {detail}" if detail else ""))
    if not ok:
        failures.append(f"{label}: {detail}" if detail else label)


def build_wheel(workdir: Path) -> Path:
    out = workdir / "dist"
    subprocess.run(
        [sys.executable, "-m", "pip", "wheel", "--no-deps", "-w", str(out), str(REPO)],
        check=True,
        capture_output=True,
        text=True,
    )
    wheels = sorted(out.glob("*.whl"))
    if not wheels:
        raise RuntimeError("pip wheel produced no .whl")
    return wheels[-1]


def main() -> int:
    print(f"repo: {REPO}")
    with tempfile.TemporaryDirectory(prefix="hbp-wheel-smoke-") as tmp:
        workdir = Path(tmp)

        print("\n[1/4] building wheel")
        try:
            wheel = build_wheel(workdir)
        except subprocess.CalledProcessError as exc:
            print(exc.stdout)
            print(exc.stderr, file=sys.stderr)
            check("wheel builds", False, "pip wheel failed")
            return 1
        check("wheel builds", True, wheel.name)

        print("\n[2/4] inspecting wheel contents")
        with zipfile.ZipFile(wheel) as zf:
            names = zf.namelist()
        for member in REQUIRED_WHEEL_MEMBERS:
            if member.endswith("/"):
                present = any(n.startswith(member) for n in names)
                detail = f"{sum(1 for n in names if n.startswith(member))} file(s)"
            else:
                present = member in names
                detail = "" if present else "absent from wheel"
            check(f"packaged: {member}", present, detail)

        print("\n[3/4] installing into a clean venv outside the repo")
        env_dir = workdir / "venv"
        venv.create(env_dir, with_pip=True)
        bindir = env_dir / ("Scripts" if sys.platform == "win32" else "bin")
        py = bindir / ("python.exe" if sys.platform == "win32" else "python")
        subprocess.run(
            [str(py), "-m", "pip", "install", "-q", str(wheel)],
            check=True,
            capture_output=True,
            text=True,
        )
        exe = bindir / ("halfblood.exe" if sys.platform == "win32" else "halfblood")
        check("console script installed", exe.exists(), str(exe))
        if not exe.exists():
            return 1

        # Run from a neutral cwd so the repo is nowhere near sys.path or the CWD.
        runcwd = workdir

        def run(args: list[str], *, exe_path: Path = exe) -> subprocess.CompletedProcess[str]:
            return subprocess.run(
                [str(exe_path), *args], cwd=runcwd, capture_output=True, text=True
            )

        print("\n[4/4] using the installed CLI")

        res = run(["--version"])
        check("--version exits 0", res.returncode == 0, res.stderr.strip()[:120])

        res = run(["--help"])
        check("--help exits 0", res.returncode == 0, res.stderr.strip()[:120])

        # The font bug: a registered font NAME had to resolve from package data.
        # Resolve it through the installed package, not the repo.
        probe = (
            "import halfblood.document_processor as d;"
            "p=d.DocumentProcessor();"
            "print('FONT_OK', p._fontfile)"
        )
        res = subprocess.run([str(py), "-c", probe], cwd=runcwd, capture_output=True, text=True)
        ok = res.returncode == 0 and "FONT_OK" in res.stdout
        check(
            "default font resolves from installed package",
            ok,
            (res.stderr or res.stdout).strip()[:160],
        )
        if ok and str(REPO) in res.stdout:
            check(
                "resolved font path is inside site-packages, not the repo",
                False,
                res.stdout.strip()[:160],
            )
        elif ok:
            check("resolved font path is inside site-packages, not the repo", True)

        # Probe the public placement API from the installed wheel, without repo paths.
        placement_probe = 'import json\nfrom pathlib import Path\nimport fitz\nimport halfblood\nfrom bs4 import BeautifulSoup\nfrom halfblood.placement import resolve_pdf_quote, resolve_epub_quote, PlacementResult\nfrom halfblood.models.annotations import TargetSelector\nfrom halfblood.document_processor import DocumentProcessor\n\nassert "site-packages" in halfblood.__file__\nwith fitz.open() as doc:\n    page = doc.new_page()\n    page.insert_text((72, 100), "The dose is five milligrams. Repeat. Repeat.")\n    resolved = resolve_pdf_quote(page, TargetSelector(exact="The dose is five milligrams."))\n    assert resolved.status == "resolved" and resolved.raw_span == (0, 28)\n    assert PlacementResult.model_validate_json(resolved.model_dump_json()) == resolved\n    assert resolve_pdf_quote(page, TargetSelector(exact="The dose is fifty milligrams.")).status == "unresolved"\n    assert resolve_pdf_quote(page, TargetSelector(exact="Repeat.")).status == "ambiguous"\n    doc.save("wheel-source.pdf")\nroot = BeautifulSoup("<p>The <em>dose</em> is five milligrams.</p>", "html.parser")\nresult = resolve_epub_quote(root, TargetSelector(exact="The dose is five milligrams."))\nassert result.status == "resolved" and not result.quads\nassert resolve_epub_quote(root, TargetSelector(exact="The dose"), fixed_layout=True).status == "unsupported_renderer"\nsource = Path("wheel-source.pdf")\nbefore = source.read_bytes()\ntry:\n    DocumentProcessor().render_annotations(str(source), [], str(source))\nexcept ValueError:\n    pass\nelse:\n    raise AssertionError("input-overwrite guard missing")\nassert source.read_bytes() == before\nprint("PLACEMENT_OK: four outcomes, cross-node range, round-trip, source intact")\n'
        res = run(["-I", "-c", placement_probe], exe_path=py)
        check(
            "installed placement contract",
            res.returncode == 0 and "PLACEMENT_OK" in res.stdout,
            (res.stdout if res.returncode == 0 else res.stderr).strip()[-500:],
        )

        # Every command must fail cleanly, never with a traceback.
        for args in (["annotate", "/nonexistent/book.pdf", "-o", "out.pdf"], ["eval", "--list"]):
            res = run(args)
            combined = res.stdout + res.stderr
            has_tb = "Traceback (most recent call last)" in combined
            check(f"`{' '.join(args[:2])}` does not traceback", not has_tb, combined.strip()[-200:])

        # `eval` is developer-only and cannot work from a wheel (the harness lives
        # in eval/, which is not packaged). It must say so intelligibly.
        #
        # The assertion keys on the *install prefix*, not on the string
        # "site-packages". First attempt at this check tested for "site-packages"
        # and passed while the bug was live: `__file__.parents[2]` from
        # `<venv>/lib/python3.12/site-packages/halfblood/cli.py` is
        # `<venv>/lib/python3.12/`, which strips "site-packages" right back off.
        # A test that passes for the wrong reason is the thing this script is
        # supposed to catch, so it keys on the venv root -- any path fabricated by
        # __file__ arithmetic inside the installed environment contains it.
        res = run(["eval", "--list"])
        combined = res.stdout + res.stderr
        check(
            "`eval` failure message does not name a fabricated install path",
            str(env_dir) not in combined,
            combined.strip()[:200],
        )

    print("\n" + "=" * 66)
    for note in notes:
        print(f"NOTE  {note}")
    if failures:
        print(f"FAILED ({len(failures)}):")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("wheel smoke test PASSED")
    return 0


if __name__ == "__main__":
    if shutil.which("git") is None:
        print("git not found; continuing anyway")
    raise SystemExit(main())
