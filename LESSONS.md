# Lessons

How this codebase fails. Newest first.

Companion ledger — how we work with agents — is
`~/dev-harness/ledger/LEARNINGS.md`. App-repo lessons are that file's raw material; an
entry here that never propagates up stops the harness learning.

Each entry: mechanism, evidence, **shape** (phrased so a repeat is recognisable), tally,
status. Cap ~10 entries. Past that, a new entry merges with or evicts an existing one.

Every entry below is one shape: **the thing that verified was not the thing that ships.**

---

## 1. `--font` resolved fonts from the repo, so every wheel shipped it broken

**Mechanism.** `_FONTS_DIR` came from `__file__.parents[2]`. In a checkout that is the
repo-root `fonts/` directory, which exists locally and is gitignored. From a
pip-installed wheel it resolves to a path *above* `site-packages`, which does not exist.

**Evidence.** Every registered `--font` name, and the config `font` key, failed with
"Font is not installed. Download it from …" — naming a font that ships inside the
package. 1600+ tests and both linters stayed green throughout, because in the source
tree the path happens to exist. Documented at `scripts/wheel_smoke.py:10` and, in the
source, at `src/halfblood/cli.py:73`. The fix is `src/halfblood/cli.py:78`, which now
resolves through `resources.files("halfblood").joinpath("fonts")`.

**Shape.** Path arithmetic relative to the repo. A test run from the source tree cannot
see it, because in the source tree the path is real.

**Tally.** 2 — with entry 2, same mechanism, same file.

**Status.** Fixed, and the class is guarded: `scripts/wheel_smoke.py` builds the wheel,
installs it into a throwaway venv outside the repo with the repo off `sys.path`, and
asserts every packaged data file is actually inside the wheel. Runs in CI.

---

## 2. `halfblood eval` resolved its harness the same way, and could not work for any installed user

**Mechanism.** `__file__.parents[2] / "eval"`. The wheel packages only `src/halfblood`,
so `eval/eval_harness.py` is never present in an install.

**Evidence.** `scripts/wheel_smoke.py:14`. The command was unusable for every
pip-installed user while the suite was green. Fixed at `src/halfblood/cli.py:1272`,
which now distinguishes a broken checkout from a wheel install and raises an actionable
`ClickException` naming the `pip install -e .` requirement rather than a nonsense path.

**Shape.** Identical to entry 1. That it recurred *after* entry 1 was found is the
point: fixing one call site does not fix the class. Only the artifact check does.

**Tally.** 2. This is the second occurrence, and `wheel_smoke.py` is the landed edit.

**Status.** Fixed and guarded by the same script.

---

## 3. `python -m pytest` passed while CI's bare `pytest` failed on collection

**Mechanism.** `python -m pytest` puts the current directory on `sys.path`. The bare
`pytest` console script does not. So `from benchmarks.placement import run_benchmark`
resolved locally and raised `ModuleNotFoundError: No module named 'benchmarks'` in CI.

**Evidence.** CI failed on `test (3.12)` while the same suite passed locally with a
clean tree and every `benchmarks/` file tracked. Nothing was missing; the invocation
differed. Reproduced both ways at that commit before changing anything — commit
`b83c466`.

**Shape.** Verifying with a more permissive invocation than the one that ships. Same
shape as entries 1 and 2, one level up: there the artifact differed, here the entry
point did.

**Tally.** 3 with entries 1 and 2.

**Status.** Fixed. `pyproject.toml` sets `pythonpath = ["."]` under
`[tool.pytest.ini_options]`, which makes the two invocations agree. Re-verified with
CI's exact commands rather than the convenient ones: bare `pytest tests/ -q` → 2070
passed; `ruff check src tests eval scripts` clean (CI lints `scripts/`, which local runs
had not); `mypy src/halfblood` clean; wheel smoke passed.

---

## 4. A dependency's import-time notice on stdout corrupted a JSON contract

**Mechanism.** `scripts/benchmark_placement.py` promises JSON on stdout and nothing
else. On any PyMuPDF newer than the dev lock's pin, `import fitz` prints its deprecation
notice to **stdout** rather than stderr. CI installs from the `pyproject.toml` range
`pymupdf>=1.24.0,<2` rather than from `requirements-dev.lock`, which pins
`pymupdf==1.28.0`, so CI resolved a newer release and the local lockfile did not.

**Evidence.** `json.loads(proc.stdout)` raised `Expecting value: line 1 column 1`. The
workflow's own artifact step, `python scripts/benchmark_placement.py >
placement-benchmark.json`, had been writing a file that is not JSON and failing nothing
— which is worse than the failure. Commit `7dcec5b`.

**Shape.** A resolved-version gap between the lockfile a human verifies against and the
range CI resolves, surfacing through a third party's choice of stream. Note the
generalisation: the defect is not "pin PyMuPDF." Any dependency may write to stdout at
import time, so a stdout contract has to be enforced by the program that promises it.

**Tally.** 1. Watch for a second: any "green locally, malformed in CI" where the two
install from different sources.

**Status.** Fixed. The import that can print runs under
`contextlib.redirect_stdout(sys.stderr)`, so import-time chatter lands on stderr and the
stdout contract holds whatever a dependency decides to say.

---

## The rule these four buy

**Verify with the command that ships, not the one that is convenient.** The installed
wheel, not the source tree. CI's bare `pytest`, not `python -m pytest`. The range CI
resolves, not the lockfile you hold. Each of the four was green under the convenient
check at the moment it shipped broken.
