"""Error-precedence: persona/usage errors must fire before API-key errors.

Three persona-related error kinds are tested for both ``annotate`` and
``preview``, each with NO API key in the environment:

    1. Mutually-exclusive persona flags   → UsageError → exit 2
    2. Unknown built-in persona name      → ClickException → exit 1
    3. Missing ``--persona-file`` path    → ClickException → exit 1

Baseline (no persona flags + no key) is also pinned to prove the API-key
check was not accidentally suppressed.

The fix in ``cli.py`` moves ``_resolve_persona`` before
``_resolve_provider_and_build`` in both commands.  The "WITH key" variants
confirm the fix does not alter behaviour when a key is present.

Hermeticity: monkeypatch clears ANTHROPIC_API_KEY and OPENROUTER_API_KEY so
results are independent of the developer's environment.  The autouse
``_isolate_user_config`` fixture in ``conftest.py`` already neutralises the
user-level config file.  No real API calls are made anywhere in this file.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from halfblood.cli import main as cli_main

# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------

_TESTS_DIR = Path(__file__).resolve().parent
_PDF_FIXTURE = _TESTS_DIR / "fixtures" / "potions_textbook.pdf"

#: Fake key that passes ``not environment.get(api_key_env)`` in config.py.
#: Assembled in two parts so it is never a literal matching a secret scanner.
_FAKE_KEY = "sk-ant-" + "fake-precedence-test-x1y2z3"

#: The mutual-exclusion error text from ``_resolve_persona``.
_MUTEX_MSG = "--persona, --persona-file, and --persona-name are mutually exclusive"

#: Substring of the ProviderConfigurationError when no key is found.
_API_KEY_MSG = "ANTHROPIC_API_KEY is required"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture()
def _no_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove API-key env vars from os.environ for the duration of the test.

    This ensures ``resolve_generation_config`` sees no valid key even if the
    developer has ``ANTHROPIC_API_KEY`` set on their machine.
    """
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("HALFBLOOD_API_KEY_ENV", raising=False)
    monkeypatch.delenv("HALFBLOOD_PROVIDER", raising=False)


@pytest.fixture()
def _with_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Plant a fake (but syntactically valid) API key in os.environ."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", _FAKE_KEY)


# ---------------------------------------------------------------------------
# Helper: one-line assertion with clear failure message
# ---------------------------------------------------------------------------


def _assert_error(result: object, *, exit_code: int, contains: str) -> None:
    """Check exit code and message substring with a useful failure report."""
    assert result.exit_code == exit_code, (  # type: ignore[union-attr]
        f"Expected exit {exit_code}, got {result.exit_code}.\n"  # type: ignore[union-attr]
        f"Full output:\n{result.output}"  # type: ignore[union-attr]
    )
    assert contains in result.output, (  # type: ignore[union-attr]
        f"Expected {contains!r} in output.\n"
        f"Full output:\n{result.output}"  # type: ignore[union-attr]
    )


# ===========================================================================
# annotate — mutual-exclusion of persona flags
# ===========================================================================


def test_annotate_persona_conflict_fires_before_key_check(
    runner: CliRunner, _no_key: None, tmp_path: Path
) -> None:
    """``--persona x --persona-name chemist`` → exit 2 even with no API key.

    Before the fix: exit 1 (API-key error).
    After the fix: exit 2 (UsageError from _resolve_persona).
    """
    result = runner.invoke(
        cli_main,
        [
            "annotate", str(_PDF_FIXTURE),
            "-o", str(tmp_path / "out.pdf"),
            "--persona", "some text",
            "--persona-name", "chemist",
        ],
        catch_exceptions=False,
    )
    _assert_error(result, exit_code=2, contains=_MUTEX_MSG)


def test_annotate_persona_conflict_with_key_is_exit2(
    runner: CliRunner, _with_key: None, tmp_path: Path
) -> None:
    """With a key present the mutual-exclusion error is identical (exit 2).

    Verifies the fix did not change the already-correct with-key behaviour.
    """
    result = runner.invoke(
        cli_main,
        [
            "annotate", str(_PDF_FIXTURE),
            "-o", str(tmp_path / "out.pdf"),
            "--persona", "some text",
            "--persona-name", "chemist",
        ],
        catch_exceptions=False,
    )
    _assert_error(result, exit_code=2, contains=_MUTEX_MSG)


# ===========================================================================
# annotate — unknown --persona-name
# ===========================================================================


def test_annotate_unknown_persona_name_fires_before_key_check(
    runner: CliRunner, _no_key: None, tmp_path: Path
) -> None:
    """``--persona-name nosuchpersona`` → exit 1 even with no API key.

    Before the fix: exit 1 but API-key error (wrong message).
    After the fix: exit 1 with the 'Unknown persona' message.
    """
    result = runner.invoke(
        cli_main,
        [
            "annotate", str(_PDF_FIXTURE),
            "-o", str(tmp_path / "out.pdf"),
            "--persona-name", "nosuchpersona",
        ],
        catch_exceptions=False,
    )
    _assert_error(result, exit_code=1, contains="Unknown persona 'nosuchpersona'")


def test_annotate_unknown_persona_name_with_key_is_exit1(
    runner: CliRunner, _with_key: None, tmp_path: Path
) -> None:
    """With a key present the unknown-persona error is identical (exit 1)."""
    result = runner.invoke(
        cli_main,
        [
            "annotate", str(_PDF_FIXTURE),
            "-o", str(tmp_path / "out.pdf"),
            "--persona-name", "nosuchpersona",
        ],
        catch_exceptions=False,
    )
    _assert_error(result, exit_code=1, contains="Unknown persona 'nosuchpersona'")


# ===========================================================================
# annotate — missing --persona-file
# ===========================================================================


def test_annotate_missing_persona_file_fires_before_key_check(
    runner: CliRunner, _no_key: None, tmp_path: Path
) -> None:
    """``--persona-file /nonexistent`` → exit 1 even with no API key.

    Before the fix: exit 1 but API-key error (wrong message).
    After the fix: exit 1 with the 'Persona file not found' message.
    """
    missing = tmp_path / "no_such_persona.txt"
    result = runner.invoke(
        cli_main,
        [
            "annotate", str(_PDF_FIXTURE),
            "-o", str(tmp_path / "out.pdf"),
            "--persona-file", str(missing),
        ],
        catch_exceptions=False,
    )
    _assert_error(result, exit_code=1, contains="Persona file not found")
    assert str(missing) in result.output, (
        f"Missing-file path must appear in error. Full output:\n{result.output}"
    )


def test_annotate_missing_persona_file_with_key_is_exit1(
    runner: CliRunner, _with_key: None, tmp_path: Path
) -> None:
    """With a key present the missing-file error is identical (exit 1)."""
    missing = tmp_path / "no_such_persona.txt"
    result = runner.invoke(
        cli_main,
        [
            "annotate", str(_PDF_FIXTURE),
            "-o", str(tmp_path / "out.pdf"),
            "--persona-file", str(missing),
        ],
        catch_exceptions=False,
    )
    _assert_error(result, exit_code=1, contains="Persona file not found")


# ===========================================================================
# annotate — no persona flags + no key (baseline: API-key check must still run)
# ===========================================================================


def test_annotate_no_persona_flags_no_key_yields_api_key_error(
    runner: CliRunner, _no_key: None, tmp_path: Path
) -> None:
    """No persona flags + no API key → exit 1 with the API-key error.

    Guards against accidentally suppressing the API-key check entirely.
    This path must be UNCHANGED by the fix.
    """
    result = runner.invoke(
        cli_main,
        [
            "annotate", str(_PDF_FIXTURE),
            "-o", str(tmp_path / "out.pdf"),
        ],
        catch_exceptions=False,
    )
    _assert_error(result, exit_code=1, contains=_API_KEY_MSG)


# ===========================================================================
# preview — mutual-exclusion of persona flags
# ===========================================================================


def test_preview_persona_conflict_fires_before_key_check(
    runner: CliRunner, _no_key: None
) -> None:
    """``preview --persona x --persona-name chemist`` → exit 2 with no API key.

    Before the fix: exit 1 (API-key error).
    After the fix: exit 2 (UsageError from _resolve_persona).
    """
    result = runner.invoke(
        cli_main,
        [
            "preview", str(_PDF_FIXTURE),
            "--persona", "some text",
            "--persona-name", "chemist",
        ],
        catch_exceptions=False,
    )
    _assert_error(result, exit_code=2, contains=_MUTEX_MSG)


def test_preview_persona_conflict_with_key_is_exit2(
    runner: CliRunner, _with_key: None
) -> None:
    """With a key present the mutual-exclusion error is identical (exit 2)."""
    result = runner.invoke(
        cli_main,
        [
            "preview", str(_PDF_FIXTURE),
            "--persona", "some text",
            "--persona-name", "chemist",
        ],
        catch_exceptions=False,
    )
    _assert_error(result, exit_code=2, contains=_MUTEX_MSG)


# ===========================================================================
# preview — unknown --persona-name
# ===========================================================================


def test_preview_unknown_persona_name_fires_before_key_check(
    runner: CliRunner, _no_key: None
) -> None:
    """``preview --persona-name nosuchpersona`` → exit 1 even with no API key.

    Before the fix: exit 1 but API-key error (wrong message).
    After the fix: exit 1 with the 'Unknown persona' message.
    """
    result = runner.invoke(
        cli_main,
        [
            "preview", str(_PDF_FIXTURE),
            "--persona-name", "nosuchpersona",
        ],
        catch_exceptions=False,
    )
    _assert_error(result, exit_code=1, contains="Unknown persona 'nosuchpersona'")


def test_preview_unknown_persona_name_with_key_is_exit1(
    runner: CliRunner, _with_key: None
) -> None:
    """With a key present the unknown-persona error is identical (exit 1)."""
    result = runner.invoke(
        cli_main,
        [
            "preview", str(_PDF_FIXTURE),
            "--persona-name", "nosuchpersona",
        ],
        catch_exceptions=False,
    )
    _assert_error(result, exit_code=1, contains="Unknown persona 'nosuchpersona'")


# ===========================================================================
# preview — missing --persona-file
# ===========================================================================


def test_preview_missing_persona_file_fires_before_key_check(
    runner: CliRunner, _no_key: None, tmp_path: Path
) -> None:
    """``preview --persona-file /nonexistent`` → exit 1 even with no API key.

    Before the fix: exit 1 but API-key error (wrong message).
    After the fix: exit 1 with the 'Persona file not found' message.
    """
    missing = tmp_path / "no_such_persona.txt"
    result = runner.invoke(
        cli_main,
        [
            "preview", str(_PDF_FIXTURE),
            "--persona-file", str(missing),
        ],
        catch_exceptions=False,
    )
    _assert_error(result, exit_code=1, contains="Persona file not found")
    assert str(missing) in result.output, (
        f"Missing-file path must appear in error. Full output:\n{result.output}"
    )


def test_preview_missing_persona_file_with_key_is_exit1(
    runner: CliRunner, _with_key: None, tmp_path: Path
) -> None:
    """With a key present the missing-file error is identical (exit 1)."""
    missing = tmp_path / "no_such_persona.txt"
    result = runner.invoke(
        cli_main,
        [
            "preview", str(_PDF_FIXTURE),
            "--persona-file", str(missing),
        ],
        catch_exceptions=False,
    )
    _assert_error(result, exit_code=1, contains="Persona file not found")


# ===========================================================================
# preview — no persona flags + no key (baseline)
# ===========================================================================


def test_preview_no_persona_flags_no_key_yields_api_key_error(
    runner: CliRunner, _no_key: None
) -> None:
    """No persona flags + no API key → exit 1 with the API-key error.

    Guards against accidentally suppressing the API-key check entirely.
    This path must be UNCHANGED by the fix.
    """
    result = runner.invoke(
        cli_main,
        [
            "preview", str(_PDF_FIXTURE),
        ],
        catch_exceptions=False,
    )
    _assert_error(result, exit_code=1, contains=_API_KEY_MSG)
