"""Stable, role-isolated pseudo-random streams for ink generation."""

from __future__ import annotations

import hashlib
import random
from typing import Any, cast

from halfblood.ink.model import InkRole
from halfblood.models.documents import canonical_json


def derive_seed(
    document_seed: int,
    annotation_id: str,
    role: InkRole | str,
    algorithm_version: str,
    label: str,
) -> int:
    """Return a BLAKE2b-derived 64-bit seed, stable for fixed inputs.

    Uses canonical_json to eliminate input-boundary collisions.
    Never touches random.Random global state or Python hash().
    """

    role_str = role.value if isinstance(role, InkRole) else str(role)
    key_material = canonical_json(
        cast(Any, [document_seed, annotation_id, role_str, algorithm_version, label])
    )
    digest = hashlib.blake2b(key_material.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, byteorder="big", signed=False)


def make_stream(
    document_seed: int,
    annotation_id: str,
    role: InkRole | str,
    algorithm_version: str,
    label: str,
) -> random.Random:
    """Return an independent random.Random seeded from derive_seed(...).

    Each returned instance is fully isolated — drawing from one stream
    never affects any other stream's sequence. Never calls random.seed()
    or modifies any global random state.
    """

    seed = derive_seed(document_seed, annotation_id, role, algorithm_version, label)
    rng = random.Random()
    rng.seed(seed)
    return rng


__all__ = ["derive_seed", "make_stream"]
