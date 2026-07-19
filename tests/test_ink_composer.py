"""P3-T12(composer) — InkComposer builds one InkScene per resolved annotation.

Controller-owned test file (SDD lean loop). Codex must NOT modify this file.

Scope: `src/halfblood/ink/composer.py` as a PURE unit. The composer joins the
semantic ``Annotation`` (mark_intent / doodle_kind / content) to its
``ResolvedAnnotation`` geometry (by id), asks an injectable ``RoughInkEngine`` for
mark strokes with role-isolated deterministic seeds, post-processes each path once,
and assembles an immutable ``InkScene`` plus a body result. Procedural letterforms
are NO-GO, so the default ``HandwritingEngine`` reports a typed unavailable.

Design + assertion-to-contract map: `.superpowers/sdd/p3-t12-design.md`.
No network calls are made anywhere in this file.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from halfblood.ink.composer import (
    ComposeRequest,
    CompositionResult,
    DefaultPathPostprocessor,
    HandwritingUnavailable,
    InkComposer,
    P3T5NoGoHandwritingEngine,
    RoughResult,
    RoughRole,
    TypesetBody,
)
from halfblood.ink.model import (
    CubicTo,
    InkGroup,
    InkRole,
    LineTo,
    LocalRect,
    MoveTo,
    StrokePath,
    StrokeStyle,
    scene_structural_hash,
)
from halfblood.ink.seeding import derive_seed
from halfblood.ink.style import load_builtin_style
from halfblood.models.annotations import Annotation, MarkIntent, TargetSelector
from halfblood.models.legacy import AnnotationType
from halfblood.models.rendering import (
    ResolvedAnchor,
    ResolvedAnnotation,
    SurfacePoint,
    SurfaceQuad,
    SurfaceRect,
)

_ALGO = "ink-1.0"
_DOC_SEED = 0x1234
_PAGE = SurfaceRect(x0=0.0, y0=0.0, x1=200.0, y1=300.0)
_STROKE = StrokeStyle(color="#804000", base_width=1.0, opacity=0.9)


# --------------------------------------------------------------------------- #
# Injected fakes
# --------------------------------------------------------------------------- #


class RecordingRough:
    """A RoughInkEngine that records every (request, seed) and echoes one group."""

    def __init__(self) -> None:
        self.calls: list[tuple[Any, int]] = []

    def generate(self, request: Any, *, style: Any, seed: int) -> RoughResult:
        self.calls.append((request, seed))
        path = StrokePath(commands=(MoveTo(x=10.0, y=10.0), LineTo(x=20.0, y=10.0)), stroke=_STROKE)
        role = InkRole.UNDERLINE if request.role == RoughRole.HIGHLIGHT else InkRole(request.role.value)
        group = InkGroup(group_id=f"{request.role.value}-0", role=role, paths=(path,))
        return RoughResult(groups=(group,))

    @property
    def roles(self) -> list[RoughRole]:
        return [req.role for req, _ in self.calls]

    def request_for(self, role: RoughRole) -> tuple[Any, int | None]:
        for req, seed in self.calls:
            if req.role == role:
                return req, seed
        return None, None


class RecordingPost:
    """A PathPostprocessor that records each path and returns it unchanged."""

    def __init__(self) -> None:
        self.calls: list[StrokePath] = []

    def process(self, path: StrokePath, *, bounds: Any, tolerance: float, input_budget: int) -> StrokePath:
        self.calls.append(path)
        return path


class RecordingHand:
    """A HandwritingEngine that records calls (to prove typeset mode never calls it)."""

    def __init__(self) -> None:
        self.calls: list[Any] = []

    def synthesize(self, request: Any, *, style: Any, seed: int) -> HandwritingUnavailable:
        self.calls.append(request)
        return HandwritingUnavailable()


# --------------------------------------------------------------------------- #
# Fixtures / builders
# --------------------------------------------------------------------------- #


def _annotation(
    *,
    ann_id: str = "ann-rough-001",
    mark_intent: MarkIntent = MarkIntent.UNDERLINE,
    annotation_type: AnnotationType = AnnotationType.CORRECTION,
    content: str = "No, crush it.",
    doodle_kind: str | None = None,
) -> Annotation:
    return Annotation(
        id=ann_id,
        target=TargetSelector(exact="crush the bean"),
        annotation_type=annotation_type,
        content=content,
        confidence=0.9,
        requested_placement="margin_right",
        mark_intent=mark_intent,
        doodle_kind=doodle_kind,
    )


def _quad(x0: float, y0: float, x1: float, y1: float) -> SurfaceQuad:
    return SurfaceQuad(
        ul=SurfacePoint(x=x0, y=y0),
        ur=SurfacePoint(x=x1, y=y0),
        lr=SurfacePoint(x=x1, y=y1),
        ll=SurfacePoint(x=x0, y=y1),
    )


def _resolved(*, ann_id: str = "ann-rough-001", quads: tuple[SurfaceQuad, ...] | None = None) -> ResolvedAnnotation:
    if quads is None:
        quads = (_quad(40, 80, 100, 92), _quad(40, 96, 85, 108))
    return ResolvedAnnotation(
        annotation_id=ann_id,
        source_locator="loc-1",
        requested_placement="margin_right",
        resolved_placement="margin_right",
        anchor=ResolvedAnchor(char_range=(0, 13), quads=quads),
        note_box=SurfaceRect(x0=140.0, y0=70.0, x1=190.0, y1=120.0),
        render_seed=42,
    )


def _request(*, ann: Annotation | None = None, resolved: ResolvedAnnotation | None = None) -> ComposeRequest:
    return ComposeRequest(
        annotation=ann or _annotation(),
        resolved=resolved or _resolved(),
        document_seed=_DOC_SEED,
        page_bounds=_PAGE,
    )


def _composer(rough: Any, *, hand: Any = None, post: Any = None) -> InkComposer:
    return InkComposer(
        rough,
        hand or P3T5NoGoHandwritingEngine(),
        path_postprocessor=post or RecordingPost(),
        algorithm_version=_ALGO,
    )


# --------------------------------------------------------------------------- #
# Assembly + join
# --------------------------------------------------------------------------- #


def test_compose_builds_scene_for_annotation() -> None:
    result = _composer(RecordingRough()).compose(_request(), load_builtin_style())
    assert isinstance(result, CompositionResult)
    assert result.scene.annotation_id == "ann-rough-001"
    assert result.scene.groups, "composed scene should contain the generated mark groups"


def test_underline_intent_requests_underline_role() -> None:
    rough = RecordingRough()
    _composer(rough).compose(_request(), load_builtin_style())
    assert RoughRole.UNDERLINE in rough.roles


def test_marks_use_per_quad_geometry_not_unioned() -> None:
    rough = RecordingRough()
    _composer(rough).compose(_request(), load_builtin_style())  # 2 target quads
    req, _ = rough.request_for(RoughRole.UNDERLINE)
    assert req is not None
    assert len(req.local_target_quads) == 2, "each target line quad must be a separate generator input"


# --------------------------------------------------------------------------- #
# Role-isolated deterministic seeds
# --------------------------------------------------------------------------- #


def test_underline_seed_matches_derive_seed() -> None:
    rough = RecordingRough()
    _composer(rough).compose(_request(), load_builtin_style())
    _, seed = rough.request_for(RoughRole.UNDERLINE)
    assert seed == derive_seed(_DOC_SEED, "ann-rough-001", RoughRole.UNDERLINE.value, _ALGO, "composer")


def test_seed_isolated_by_annotation_id() -> None:
    r1, r2 = RecordingRough(), RecordingRough()
    _composer(r1).compose(_request(ann=_annotation(ann_id="ann-A"), resolved=_resolved(ann_id="ann-A")), load_builtin_style())
    _composer(r2).compose(_request(ann=_annotation(ann_id="ann-B"), resolved=_resolved(ann_id="ann-B")), load_builtin_style())
    _, s1 = r1.request_for(RoughRole.UNDERLINE)
    _, s2 = r2.request_for(RoughRole.UNDERLINE)
    assert s1 is not None and s2 is not None and s1 != s2


# --------------------------------------------------------------------------- #
# Postprocess-once + immutability + determinism
# --------------------------------------------------------------------------- #


def test_postprocessor_called_once_per_generated_path() -> None:
    rough, post = RecordingRough(), RecordingPost()
    _composer(rough, post=post).compose(_request(), load_builtin_style())
    # each fake generate() returns exactly one path, so one process() call per generate().
    assert len(post.calls) == len(rough.calls)
    assert len(post.calls) >= 1


def test_scene_is_immutable() -> None:
    result = _composer(RecordingRough()).compose(_request(), load_builtin_style())
    with pytest.raises(ValidationError):
        result.scene.seed = 999  # frozen pydantic InkScene


def test_same_inputs_produce_identical_scene_hash() -> None:
    c1 = _composer(RecordingRough()).compose(_request(), load_builtin_style())
    c2 = _composer(RecordingRough()).compose(_request(), load_builtin_style())
    assert scene_structural_hash(c1.scene) == scene_structural_hash(c2.scene)


# --------------------------------------------------------------------------- #
# Body engine selection (NO-GO)
# --------------------------------------------------------------------------- #


def test_typeset_mode_uses_annotation_body_and_skips_handwriting_engine() -> None:
    hand = RecordingHand()
    result = _composer(RecordingRough(), hand=hand).compose(
        _request(), load_builtin_style(), handwriting_mode="typeset"
    )
    assert isinstance(result.body, TypesetBody)
    assert result.body.text == "No, crush it."
    assert hand.calls == [], "typeset mode must not invoke the handwriting engine"


def test_procedural_mode_reports_handwriting_unavailable() -> None:
    result = _composer(RecordingRough(), hand=P3T5NoGoHandwritingEngine()).compose(
        _request(), load_builtin_style(), handwriting_mode="procedural"
    )
    assert isinstance(result.body, HandwritingUnavailable)
    assert result.body.code == "p3_t5_no_go"
    assert all(g.role != InkRole.HANDWRITING for g in result.scene.groups)


# --------------------------------------------------------------------------- #
# F2 guard — the default postprocessor never simplifies cubic paths
# --------------------------------------------------------------------------- #


def test_default_postprocessor_preserves_cubic_paths() -> None:
    post = DefaultPathPostprocessor()
    cubic = StrokePath(
        commands=(MoveTo(x=10.0, y=10.0), CubicTo(x1=20.0, y1=5.0, x2=40.0, y2=15.0, x=50.0, y=10.0)),
        stroke=_STROKE,
    )
    # a large tolerance would simplify a polyline aggressively; a cubic path must pass through intact
    # because `_douglas_peucker` ignores control points (latent F2 bug).
    out = post.process(cubic, bounds=LocalRect(x0=0.0, y0=0.0, x1=200.0, y1=300.0), tolerance=100.0, input_budget=64)
    assert out is not None
    assert sum(1 for c in out.commands if isinstance(c, CubicTo)) == 1, "cubic must not be simplified/dropped"


# --------------------------------------------------------------------------- #
# Connector near-edge property (moved to the LIVE composer path from the legacy
# _draw_resolved_note regression). Guards the "connector arrows reversed" bug
# class: the connector must leave the note-box edge FACING the target.
# --------------------------------------------------------------------------- #


def test_connector_leaves_note_near_edge_facing_target() -> None:
    """With the note to the RIGHT of the target, the connector starts at the
    note's LEFT (near) edge and lands on the target's nearest (right) edge —
    never the far edge of the note box."""
    rough = RecordingRough()
    # Default fixture: note_box (140,70)-(190,120); target quads at x 40..100 and
    # 40..85 — i.e. entirely LEFT of the note.
    _composer(rough).compose(_request(), load_builtin_style())

    req, _ = rough.request_for(RoughRole.CONNECTOR)
    assert req is not None, "a connector must be generated when note_box and target exist"
    assert req.note_edge is not None and req.target_edge is not None

    assert req.note_edge.x == pytest.approx(140.0), (
        "connector must start at the note's NEAR edge (x0=140) facing the target, "
        "not the far edge (x1=190)"
    )
    assert req.note_edge.x < 190.0, "must not anchor to the far edge of the note box"
    assert req.target_edge.x == pytest.approx(100.0), (
        "connector must land on the nearest target quad's right edge (x=100)"
    )
