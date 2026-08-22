"""Tests for deterministic, role-isolated ink PRNG seeding (P3-T2, §§5.2–5.3).

Every role-isolation test includes a discriminating proof: a naive shared-RNG
implementation (single ``random.Random`` drawn in sequence) FAILS the isolation
invariant, confirming the test is non-vacuous rather than trivially satisfied
by any pure function.
"""

from __future__ import annotations

import os
import random
import subprocess
import sys
from pathlib import Path

from halfblood.ink.model import InkRole
from halfblood.ink.seeding import derive_seed, make_stream

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DOC_SEED = 9_876_543_210
_ANN_ID = "ann-uuid-0001"
_ALGO_VER = "test-v1"
_LABEL = "stroke"


def _ref_seed() -> int:
    return derive_seed(_DOC_SEED, _ANN_ID, InkRole.HANDWRITING, _ALGO_VER, _LABEL)


def _draw(rng: random.Random, n: int = 20) -> list[float]:
    return [rng.random() for _ in range(n)]


# ---------------------------------------------------------------------------
# 1. Stability — same inputs, same output
# ---------------------------------------------------------------------------


class TestSeedStability:
    def test_stable_for_fixed_inputs(self) -> None:
        a = derive_seed(_DOC_SEED, _ANN_ID, InkRole.HANDWRITING, _ALGO_VER, _LABEL)
        b = derive_seed(_DOC_SEED, _ANN_ID, InkRole.HANDWRITING, _ALGO_VER, _LABEL)
        assert a == b

    def test_output_in_valid_range(self) -> None:
        s = _ref_seed()
        assert isinstance(s, int)
        assert 0 <= s <= 2**64 - 1

    def test_make_stream_is_deterministic(self) -> None:
        """Two make_stream calls with the same params produce the same sequence."""
        a = make_stream(_DOC_SEED, _ANN_ID, InkRole.HANDWRITING, _ALGO_VER, _LABEL)
        b = make_stream(_DOC_SEED, _ANN_ID, InkRole.HANDWRITING, _ALGO_VER, _LABEL)
        assert _draw(a) == _draw(b)


# ---------------------------------------------------------------------------
# 2. Sensitivity — differ when any component differs
# ---------------------------------------------------------------------------


class TestSeedSensitivity:
    def test_differs_on_document_seed(self) -> None:
        a = derive_seed(1, _ANN_ID, InkRole.HANDWRITING, _ALGO_VER, _LABEL)
        b = derive_seed(2, _ANN_ID, InkRole.HANDWRITING, _ALGO_VER, _LABEL)
        assert a != b

    def test_differs_on_annotation_id(self) -> None:
        a = derive_seed(_DOC_SEED, "ann-A", InkRole.HANDWRITING, _ALGO_VER, _LABEL)
        b = derive_seed(_DOC_SEED, "ann-B", InkRole.HANDWRITING, _ALGO_VER, _LABEL)
        assert a != b

    def test_differs_on_role(self) -> None:
        a = derive_seed(_DOC_SEED, _ANN_ID, InkRole.HANDWRITING, _ALGO_VER, _LABEL)
        b = derive_seed(_DOC_SEED, _ANN_ID, InkRole.CONNECTOR, _ALGO_VER, _LABEL)
        assert a != b

    def test_differs_on_algorithm_version(self) -> None:
        a = derive_seed(_DOC_SEED, _ANN_ID, InkRole.HANDWRITING, "v1", _LABEL)
        b = derive_seed(_DOC_SEED, _ANN_ID, InkRole.HANDWRITING, "v2", _LABEL)
        assert a != b

    def test_differs_on_label(self) -> None:
        a = derive_seed(_DOC_SEED, _ANN_ID, InkRole.HANDWRITING, _ALGO_VER, "stroke_0")
        b = derive_seed(_DOC_SEED, _ANN_ID, InkRole.HANDWRITING, _ALGO_VER, "stroke_1")
        assert a != b

    def test_no_boundary_collision(self) -> None:
        """canonical_json prevents naive concatenation collisions like 'ab'+'c' == 'a'+'bc'."""
        a = derive_seed(0, "x", "ab", "c", "d")
        b = derive_seed(0, "x", "a", "bc", "d")
        assert a != b

    def test_accepts_string_role(self) -> None:
        """Role may be passed as a plain string (InkRole | str contract)."""
        via_enum = derive_seed(_DOC_SEED, _ANN_ID, InkRole.HANDWRITING, _ALGO_VER, _LABEL)
        via_str = derive_seed(
            _DOC_SEED, _ANN_ID, InkRole.HANDWRITING.value, _ALGO_VER, _LABEL
        )
        assert via_enum == via_str


# ---------------------------------------------------------------------------
# 3. PYTHONHASHSEED independence — no reliance on Python hash()
# ---------------------------------------------------------------------------


class TestPythonHashSeedIndependence:
    """Spawn two subprocesses with different PYTHONHASHSEED values.

    Both must produce the same derive_seed output. The test also asserts that
    ``hash("sentinel")`` actually DIFFERS between them — if it does not, the
    PYTHONHASHSEED env var did not propagate and the test would pass vacuously.
    """

    def _run(self, hashseed: str) -> tuple[int, int]:
        """Return (derived_seed, hash_of_sentinel) from a fresh subprocess."""
        script = (
            "from halfblood.ink.seeding import derive_seed; "
            "from halfblood.ink.model import InkRole; "
            "s = derive_seed(9876543210, 'ann-uuid-0001', "
            "InkRole.HANDWRITING, 'test-v1', 'stroke'); "
            "h = hash('sentinel_p3t2_hashseed_probe'); "
            "print(s, h)"
        )
        # Import the package from this repo's src/ via PYTHONPATH and run in a
        # repo-derived cwd. The previous absolute cwd was the original author's
        # checkout path; on any other machine the subprocess never started.
        repo_src = str(Path(__file__).resolve().parents[1] / "src")
        env = {
            **os.environ,
            "PYTHONHASHSEED": hashseed,
            "PYTHONPATH": repo_src + os.pathsep + os.environ.get("PYTHONPATH", ""),
        }
        result = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            env=env,
            cwd=str(Path(__file__).resolve().parents[1]),
        )
        assert result.returncode == 0, (
            f"subprocess (PYTHONHASHSEED={hashseed}) failed: {result.stderr}"
        )
        seed_str, hash_str = result.stdout.strip().split()
        return int(seed_str), int(hash_str)

    def test_seeds_equal_across_pythonhashseeds(self) -> None:
        seed0, hash0 = self._run("0")
        seed1, hash1 = self._run("1")
        assert hash0 != hash1, (
            "hash('sentinel') returned the same value under PYTHONHASHSEED=0 and =1; "
            "env var likely did not propagate — test would pass vacuously"
        )
        assert seed0 == seed1


# ---------------------------------------------------------------------------
# 4. Global random state isolation
# ---------------------------------------------------------------------------


class TestGlobalRandomStateIsolation:
    def test_derive_seed_leaves_random_getstate_unchanged(self) -> None:
        before = random.getstate()
        _ = derive_seed(_DOC_SEED, _ANN_ID, InkRole.HANDWRITING, _ALGO_VER, _LABEL)
        after = random.getstate()
        assert before == after

    def test_drawing_from_stream_leaves_random_getstate_unchanged(self) -> None:
        """Drawing from the returned stream (not just creating it) must not touch globals."""
        before = random.getstate()
        stream = make_stream(_DOC_SEED, _ANN_ID, InkRole.HANDWRITING, _ALGO_VER, _LABEL)
        _ = _draw(stream, n=50)  # actually consume draws
        after = random.getstate()
        assert before == after


# ---------------------------------------------------------------------------
# 5. Role isolation — labeled streams are independent of each other
# ---------------------------------------------------------------------------


class TestRoleIsolation:
    """Adding or drawing from a new role stream must not alter output of existing streams.

    Discriminating proof: ``test_naive_shared_rng_fails_role_isolation`` shows
    that a single shared ``random.Random`` drawn in sequence *does* fail this
    property, confirming the test is non-vacuous.
    """

    def test_handwriting_stream_unchanged_when_doodle_added(self) -> None:
        # Baseline: handwriting stream drawn without any doodle.
        hw1 = make_stream(_DOC_SEED, _ANN_ID, InkRole.HANDWRITING, _ALGO_VER, "hw")
        hw_baseline = _draw(hw1)

        # With doodle stream created and drawn before consuming from a fresh hw stream.
        hw2 = make_stream(_DOC_SEED, _ANN_ID, InkRole.HANDWRITING, _ALGO_VER, "hw")
        doodle = make_stream(_DOC_SEED, _ANN_ID, InkRole.DOODLE, _ALGO_VER, "doodle")
        _ = _draw(doodle)  # consume doodle draws
        hw_with_doodle = _draw(hw2)

        assert hw_baseline == hw_with_doodle

    def test_connector_stream_unchanged_regardless_of_creation_order(self) -> None:
        # Order A: handwriting created first, then connector.
        hw_a = make_stream(_DOC_SEED, _ANN_ID, InkRole.HANDWRITING, _ALGO_VER, "hw")
        conn_a = make_stream(_DOC_SEED, _ANN_ID, InkRole.CONNECTOR, _ALGO_VER, "conn")
        _ = _draw(hw_a)
        conn_vals_a = _draw(conn_a)

        # Order B: connector created first, then handwriting.
        conn_b = make_stream(_DOC_SEED, _ANN_ID, InkRole.CONNECTOR, _ALGO_VER, "conn")
        hw_b = make_stream(_DOC_SEED, _ANN_ID, InkRole.HANDWRITING, _ALGO_VER, "hw")
        _ = _draw(hw_b)
        conn_vals_b = _draw(conn_b)

        assert conn_vals_a == conn_vals_b

    def test_naive_shared_rng_fails_role_isolation(self) -> None:
        """Discriminating proof: a shared RNG drawn in sequence FAILS isolation.

        Inserting a 'doodle' draw between two 'handwriting' draws on the same
        shared RNG shifts the handwriting sequence — which our isolated-stream
        impl avoids.  Confirms the role-isolation tests above are non-vacuous.
        """
        rng_no_doodle = random.Random(_DOC_SEED)
        hw_no_doodle = [rng_no_doodle.random() for _ in range(20)]

        rng_with_doodle = random.Random(_DOC_SEED)
        _ = [rng_with_doodle.random() for _ in range(20)]  # "doodle" consumes ahead
        hw_with_doodle = [rng_with_doodle.random() for _ in range(20)]

        # The naive shared-RNG impl fails: values are shifted.
        assert hw_no_doodle != hw_with_doodle

    def test_same_label_different_roles_are_independent(self) -> None:
        a = make_stream(_DOC_SEED, _ANN_ID, InkRole.HANDWRITING, _ALGO_VER, "same")
        b = make_stream(_DOC_SEED, _ANN_ID, InkRole.CONNECTOR, _ALGO_VER, "same")
        assert _draw(a) != _draw(b)
