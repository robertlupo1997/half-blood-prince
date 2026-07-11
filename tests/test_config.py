"""Regression tests for the model-default fix batch.

Covers the Phase 2 audit findings:
    - AUD-01: README documents ``pip install -e ".[eval]"`` but pyproject.toml
      defines no ``[eval]`` extras group, so the documented install fails.
    - AUD-02/03/04: the default model ``claude-sonnet-4-20250514`` is retired,
      and it is hard-coded in three separate places (annotation_generator,
      cli, eval_harness) instead of a single source of truth.

No network calls are made anywhere in this file.
"""

from __future__ import annotations

import sys
import tomllib
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

#: The retired model id that must no longer appear anywhere in shipped code.
RETIRED_MODEL = "claude-sonnet-4-20250514"

#: The current default the pipeline should ship with.
EXPECTED_DEFAULT_MODEL = "claude-sonnet-5"


def test_eval_extras_group_exists() -> None:
    """AUD-01: the ``[eval]`` extras group the README installs must exist."""
    data = tomllib.loads((_REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    extras = data["project"]["optional-dependencies"]
    assert "eval" in extras, (
        "README documents `pip install -e \".[eval]\"`, so pyproject.toml must "
        "define an [eval] optional-dependencies group."
    )


def test_generator_default_model_is_current() -> None:
    """AUD-02: the annotation generator's default model is current, not retired."""
    from halfblood.annotation_generator import DEFAULT_MODEL, AnnotationGenerator

    assert DEFAULT_MODEL == EXPECTED_DEFAULT_MODEL
    gen = AnnotationGenerator(api_key="sk-ant-test-fake-key-not-real")
    assert gen.model == EXPECTED_DEFAULT_MODEL


def test_cli_default_model_is_single_sourced() -> None:
    """AUD-03: the CLI reuses the generator's default rather than its own copy."""
    from halfblood.annotation_generator import DEFAULT_MODEL as GEN_DEFAULT
    from halfblood.cli import DEFAULT_MODEL as CLI_DEFAULT

    assert CLI_DEFAULT == GEN_DEFAULT


def test_retired_model_absent_from_all_sources() -> None:
    """AUD-02/03/04: the retired model id is gone from every call site."""
    targets = [
        _SRC / "halfblood" / "annotation_generator.py",
        _SRC / "halfblood" / "cli.py",
        _REPO_ROOT / "eval" / "eval_harness.py",
    ]
    offenders = [
        f.relative_to(_REPO_ROOT).as_posix()
        for f in targets
        if RETIRED_MODEL in f.read_text(encoding="utf-8")
    ]
    assert not offenders, f"retired model id still present in: {offenders}"
