"""Pytest bootstrap: make the ``halfblood`` package importable from source
without requiring an editable install (useful in sandboxes running a Python
version older than the project's declared ``requires-python``, where
``pip install -e .`` refuses to resolve).
"""

from __future__ import annotations

import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))
