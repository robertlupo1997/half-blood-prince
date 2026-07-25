"""Pytest bootstrap: make the ``halfblood`` package importable from source
without requiring an editable install (useful in sandboxes running a Python
version older than the project's declared ``requires-python``, where
``pip install -e .`` refuses to resolve).

Also isolates the suite from this machine's real Half-Blood Prince configuration.
See :func:`_isolate_user_config` for why that is not optional.
"""

from __future__ import annotations

import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

_REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _isolate_user_config(tmp_path_factory: pytest.TempPathFactory) -> Iterator[None]:
    """Point the default user-config lookup at an empty directory, for every test.

    ``resolve_generation_config`` defaults ``user_config_path`` to
    ``platformdirs.user_config_dir("halfblood")/config.toml``. Tests that exercise
    the real resolver without passing ``user_config_path`` therefore read whatever
    happens to be on the developer's machine.

    That is not hypothetical. Planting

        [generation]
        provider = "openrouter"
        model = "hostile/model"
        concurrency = 17

    at ``$XDG_CONFIG_HOME/halfblood/config.toml`` turned two previously-green tests
    in ``test_cli_provider_seam.py`` red. Anyone who actually uses this tool and has
    a real ``~/.config/halfblood/config.toml`` would hit those failures, while CI and
    every other developer stayed green — and nothing in the failure output points at
    the config file as the cause. One of the affected tests even carried a docstring
    asserting it was safe against exactly this; the probe disproved it.

    Patching the *default* only. Tests that pass ``user_config_path=`` explicitly are
    unaffected, which is how the resolver's own user-config behaviour is still tested.
    """
    import halfblood.config as config_module

    empty = tmp_path_factory.mktemp("isolated-user-config")
    original = config_module.user_config_dir
    config_module.user_config_dir = lambda *args, **kwargs: str(empty)  # type: ignore[assignment]
    try:
        yield
    finally:
        config_module.user_config_dir = original  # type: ignore[assignment]


def pytest_collection_modifyitems(
    session: pytest.Session, config: pytest.Config, items: list[pytest.Item]
) -> None:
    """Fail loudly if a stray project config would silently steer the suite.

    The other default is ``Path.cwd()/"halfblood.toml"``. Unlike the user config that
    cannot be neutralised by patching a lookup function, since tests legitimately run
    from the repo root. Turning it into an explicit, actionable error beats debugging
    a scatter of unrelated assertion failures.
    """
    stray = _REPO_ROOT / "halfblood.toml"
    if stray.is_file():
        raise pytest.UsageError(
            f"{stray} exists and will be read by every test that exercises the real "
            "config resolver, silently overriding provider/model/concurrency defaults. "
            "Move it aside before running the suite."
        )
