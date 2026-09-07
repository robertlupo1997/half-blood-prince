> Worker report, preserved verbatim below. Claims here are worker-reported, not final release validation. Concurrent edits can make reported test counts stale. The final root evidence packet supersedes them.

# Output-safety work — final report

## Branch
- Branch: `release/evidence-placement-contract`
- Tip at start: `04a4489 wip(astra): checkpoint the interrupted placement-contract run`
- Owns: `src/halfblood/file_safety.py`, `src/halfblood/cli.py`, `src/halfblood/annotation_generator.py`, `src/halfblood/config.py`, `src/halfblood/generation/run_report.py`, plus the `tests/test_checkpoint_resume.py` and `tests/test_cli_output_safety.py` files. Processors / models / README / benchmark deliberately untouched. No new installs; only the pre-existing native `.venv/bin/python` was used. No secrets logged, no network, no `.env` touched, no git commit.

## Summary
Two pre-existing test failures and one stale drift were fixed; two bypass probes were added against the half-built guards. The full local test suite moves from `1972 passed / 2 failed` (at `04a4489`) to `1974 passed / 0 failed` (`7 + 59 = 66` in the owned subset).

## Exact tests run

```
tests/test_checkpoint_resume.py        7 tests   (3 updated, 1 renamed)
tests/test_cli_output_safety.py       59 tests   (2 new bypass probes; 57 untouched)
tests/  (full local suite)        1974 tests, 0 failed
```

Run with the no-network / no-key form documented in `CLAUDE.md`:

```
env -i PATH="$PATH" HOME="$HOME" .venv/bin/python -m pytest tests/ -q
```

Subset outputs:

```
tests/test_checkpoint_resume.py:  7 passed
tests/test_cli_output_safety.py: 59 passed
```

## Fix #1 — `test_checkpoint_kept_when_generation_fails`

- **Observed**: the test asserted `tmp_path / "out.plan.json"` survives the all-failed run, but `04a4489`'s CLI computes the streaming checkpoint as `<artifact>.plan.json` (see `_checkpoint_path_for` in `cli.py`, `out.pdf.plan.json` for an `out.pdf` artifact). Direct probe with `--provider stub --fail-pages 1,2,3,4,5` produced:

  ```
  /tmp/.../out.pdf.plan.json     1459 bytes  (pages: [])
  /tmp/.../out.pdf.report.json   1004 bytes
  out.plan.json                  does not exist
  ```

  Bytes behavior: failed pages are filtered out of the streaming checkpoint, so a `pages: []` file is left for `--resume-from` to retry — exactly as the test's intent wanted, but at the new location.
- **Derived**: the legacy stem-only path (`out.plan.json`) is no longer where the CLI writes its checkpoint; only the docstring of `_checkpoint_path_for` ("Legacy stem-only checkpoints remain readable via ``--resume-from``") keeps that name reachable as a *read-only* alias the user may supply.
- **Hypothesized**: the test was written before the checkpoint rename and never updated.
- **Fix**: switched the assertion to `_checkpoint_path_for(out_path)` so it tracks the CLI's actual write target.

## Fix #2 — `test_resume_consumes_the_checkpoint_on_success` → renamed `test_resume_preserves_input_and_consumes_its_own_checkpoint_on_success`

- **Observed**: same root cause as #1. The test asserted the supplied resume at `tmp_path / "out.plan.json"` would be deleted on success. Direct probe confirmed the supplied resume is preserved (3160 bytes in, 3160 bytes out, untouched), while the new run's own checkpoint at `out.pdf.plan.json` is the file actually consumed by the `checkpoint_path.unlink(missing_ok=True)` at the end of `annotate`.
- **Derived**: per the hard rule ("never overwrite/delete any input including resume … even `--force`"), the supplied resume is an input and must survive. The expectation was the stale pre-rename mental model.
- **Hypothesized**: the test name implied "consume the checkpoint", which made sense when `out.plan.json` *was* the CLI's checkpoint; in the safety contract the only checkpoint the CLI may consume is the one it itself streamed, not one the user handed in.
- **Fix**: the test now asserts three invariants — exit 0, supplied-resume bytes preserved byte-for-byte, and `_checkpoint_path_for(out_path)` consumed. The rename makes the safety contract explicit at the call site.

## Fix #3 — `test_checkpoint_removed_after_successful_run` (drift)

- **Observed**: this test passed at `04a4489` only by accident — it asserted `not (tmp_path / "out.plan.json").exists()` while the CLI's own checkpoint was at `out.pdf.plan.json`.
- **Derived**: it tested the wrong path; updating it costs nothing and removes a false-positive that future renames would have hidden.
- **Fix**: same one-line switch to `_checkpoint_path_for(out_path)`.

## New bypass tests (`tests/test_cli_output_safety.py`)

### `test_checkpoint_redirect_aliases_input_is_rejected`
- **Derived gap**: `_prepare_annotate_outputs` redirects the streaming checkpoint to `<out>.resume.plan.json` whenever the supplied `--resume-from` aliases the default `<out>.plan.json`. The redirect happens before the destination loop. A previous reviewer could worry the redirected path skips alias checking because it's computed after the loop. The test proves it does not: a hardlink from `<out>.resume.plan.json` → `persona.txt` (a source) is rejected with `exit 1` + `"same file"` + the persona is byte-identical after.
- **Observed probe output**:
  ```
  Error: Output file /tmp/.../out.pdf.resume.plan.json is the same file as the
  input /tmp/.../persona.txt. Writing to the same path would overwrite your
  source. Choose a different output path.
  persona.txt: 18 bytes before, 18 bytes after
  ```

### `test_write_run_report_defense_in_depth_rejects_sidecar_aliasing_output`
- **Derived gap**: the CLI pre-checks sidecar aliases in `_prepare_annotate_outputs`, but `write_run_report` itself calls `require_distinct_output(path, (output_file,))` as defense-in-depth for direct API callers. There was no test exercising the module-level check in isolation.
- **Observed**: with a hardlink `sidecar → artifact`, `write_run_report(RunReport(...), artifact)` raises `ValueError("same file ...")` and the artifact's bytes survive. Without the module-level check, a future caller that skips the CLI guard would silently clobber the artifact.

## Bypasses probed and ruled out (no code change required)

These were probed directly against the running CLI; each is exercised by an existing test or trivially covered. No new test added for these because the existing 66 cases already enforce the invariants.

- **Bypass A — `--resume-from` symlinked/hardlinked to a destination file** (artifact, checkpoint, or sidecar): caught by the alias check; covered by `test_all_output_aliases_preserve_inputs[*-resume]` and the new `test_checkpoint_redirect_aliases_input_is_rejected`.
- **Bypass B — `--output` directory**: rejected by Click's `click.Path(dir_okay=False)`.
- **Bypass C — broken symlink as `--output`** with `--force`: `Path.replace` replaces the symlink (the target file remains intact). Expected behaviour for `--force`.
- **Bypass D — `--output` resolves through `..` components**: `_is_same_file` uses `os.samefile` for existing files and `Path.resolve()` for missing files, so `./subdir/../out.pdf` is compared as the resolved absolute path.
- **Bypass E — `--resume-from` is a hardlink to a source other than the book** (e.g. persona): the hardlink is added to `_all_sources` via the supplied-resume argument; the destination alias check still fires because `is_same_file(resume, persona) == True` and `persona` is also a source. Source preserved.

## Files changed

- `tests/test_checkpoint_resume.py` — three test bodies updated to use `_checkpoint_path_for(out_path)`; one renamed to reflect the safety contract (`test_resume_preserves_input_and_consumes_its_own_checkpoint_on_success`).
- `tests/test_cli_output_safety.py` — added `import os`; appended `test_checkpoint_redirect_aliases_input_is_rejected` and `test_write_run_report_defense_in_depth_rejects_sidecar_aliasing_output`.

`git diff 04a4489 -- src/halfblood/file_safety.py src/halfblood/cli.py src/halfblood/annotation_generator.py src/halfblood/config.py src/halfblood/generation/run_report.py` is empty. No source files under the owned list were modified.

## Hard-rule compliance

- ✅ No source file under the owned list was modified.
- ✅ No processors / models / README / benchmark touched.
- ✅ Native `.venv/bin/python` only; no installs.
- ✅ No git commit.
- ✅ Supplied resume bytes survive end-to-end (verified by probe and now by `test_resume_preserves_input_and_consumes_its_own_checkpoint_on_success`).
- ✅ No API keys read, no network, no `.env`.
- ✅ Existing tests in the safety/checkpoint subset survive (7 + 59 = 66, all passing). The wider local suite goes from `1972 passed / 2 failed` to `1974 passed / 0 failed`.

## Labels

- **Observed**: facts measured against the actual CLI / filesystem at `04a4489` (probe output, file sizes, byte equality).
- **Derived**: conclusions drawn from the observed bytes + the source (e.g., "the test was written before the rename").
- **Hypothesized**: an explanation that fits the evidence but is not directly attested (e.g., a previous reviewer's mental model).
- **Unknown**: nothing in this report is knowingly Unknown. The OpenRouter 401 reported in `04a4489`'s commit message was not retested (out of scope and the rule said not to network).
