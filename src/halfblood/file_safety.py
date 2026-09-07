"""Filesystem guards and atomic text writes shared by CLI and direct APIs.

The guards detect existing path, symlink, and hard-link aliases. They do not
lock a directory against another process changing links after validation.
Concurrent invocations targeting the same output are not supported.
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import Iterable
from pathlib import Path


def is_same_file(a: Path, b: Path) -> bool:
    """Compare file identity, falling back to resolved paths for missing files."""
    try:
        return os.path.samefile(a, b)
    except OSError:
        return a.resolve() == b.resolve()


def require_distinct_output(output: Path, inputs: Iterable[Path]) -> None:
    """Raise ValueError if an output aliases an input, even through a hard link."""
    output = Path(output)
    for source in inputs:
        source = Path(source)
        if is_same_file(output, source):
            raise ValueError(
                f"Output file {output} is the same file as the input {source}. "
                "Writing to the same path would overwrite your source. "
                "Choose a different output path."
            )


def atomic_write_text(path: Path, text: str) -> None:
    """Replace a UTF-8 text file using an exclusively created sibling temp file.

    Each writer owns only its unique temp file. A failed write/replace preserves
    the old destination and cleans up the temp file. Existing symlink and hard-
    link targets are not opened for writing. Callers must still validate paths
    and ownership before replacing a destination or deleting it later.
    """
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent,
            prefix=f".{path.name}.", suffix=".tmp", delete=False,
        ) as stream:
            temporary = Path(stream.name)
            stream.write(text)
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
