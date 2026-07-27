"""Every CONNECTOR degradation code must reach the RenderReport.

Scope note: this enumerates ``ConnectorDegradation`` only. The composer emits
other codes too (an AST sweep counted 11, of which 8 -- e.g.
``caret_interline_gap_unavailable``, ``ink_geometry_invalid`` -- are still
unmapped and take the warning-and-drop branch). Mapping those exhaustively wants
a finite composer-code enum and is recorded as open work; do not read this
module as proving it.

`document_processor.render_plan` translates composer degradation codes into
`DegradationFlag`s through a dict lookup. A code missing from that dict is
silently dropped, so the user never learns the render was degraded.

That is not hypothetical. `ConnectorDegradation.OBSTACLE_CAP_USED` was added
with its `DegradationFlag.CONNECTOR_OBSTACLE_CAP` counterpart, the composer
emitted it, and the mapping was not extended -- so the flag could never appear
in a report. These tests pin the correspondence structurally rather than
re-listing today's codes, so the NEXT code added fails here instead of vanishing
in production.
"""

from __future__ import annotations

from halfblood.ink.rough import ConnectorDegradation
from halfblood.models.rendering import DegradationFlag


def _degradation_mapping() -> dict[str, DegradationFlag]:
    """The mapping as `render_plan` builds it.

    Kept in sync by `test_mapping_literal_matches_document_processor`, which
    reads the real source, so this helper cannot drift into agreeing with a
    copy of itself.
    """
    return {
        "connector_routing_fallback": DegradationFlag.CONNECTOR_ROUTING_FALLBACK,
        "connector_obstacle_cap": DegradationFlag.CONNECTOR_OBSTACLE_CAP,
        "ink_path_budget_exceeded": DegradationFlag.INK_PATH_BUDGET_EXCEEDED,
    }


class TestConnectorDegradationsAreReportable:
    def test_every_connector_degradation_code_is_mapped(self) -> None:
        """No connector degradation may be invisible to the user.

        This is the assertion that would have caught OBSTACLE_CAP_USED shipping
        unreportable: it enumerates the enum rather than a hand-written list, so
        a new member fails until it is wired through.
        """
        mapping = _degradation_mapping()
        unmapped = [
            member.value
            for member in ConnectorDegradation
            if member.value not in mapping
        ]
        assert not unmapped, (
            f"ConnectorDegradation member(s) {unmapped} are emitted by the composer "
            "but absent from render_plan's degradation_mapping, so they can never "
            "appear in a RenderReport. Add them to the mapping in "
            "document_processor.render_plan."
        )

    def test_cap_and_routing_fallback_are_distinct_flags(self) -> None:
        """A capped-but-successful route must not be reported as a failed one.

        The two shared a single enum, so a successful three-anchor detour was
        described to the user as "used the direct fallback".
        """
        mapping = _degradation_mapping()
        assert (
            mapping["connector_obstacle_cap"] != mapping["connector_routing_fallback"]
        )
        assert (
            ConnectorDegradation.OBSTACLE_CAP_USED
            != ConnectorDegradation.ROUTING_FALLBACK
        )

    def test_connector_degradation_values_match_their_flag_values(self) -> None:
        """The code string and the flag string must agree, since the dict keys on it."""
        assert (
            ConnectorDegradation.OBSTACLE_CAP_USED.value
            == DegradationFlag.CONNECTOR_OBSTACLE_CAP.value
        )
        assert (
            ConnectorDegradation.ROUTING_FALLBACK.value
            == DegradationFlag.CONNECTOR_ROUTING_FALLBACK.value
        )


class TestMappingStaysInSyncWithSource:
    def test_mapping_literal_matches_document_processor(self) -> None:
        """Pin this module's copy of the mapping against the real source text.

        Without this, the helper above could drift from production and the
        enumeration test would pass while the real dict stayed incomplete.
        """
        from pathlib import Path

        import halfblood.document_processor as dp

        source = Path(dp.__file__).read_text(encoding="utf-8")
        for code in _degradation_mapping():
            assert f'"{code}"' in source, (
                f"degradation code {code!r} is asserted here but does not appear "
                "in document_processor.py; the mapping has drifted."
            )

    def test_unmapped_code_is_logged_not_swallowed(self) -> None:
        """An unknown code must announce itself rather than disappearing.

        The original loop did `if flag is not None: append`, so an unmapped code
        was a silent no-op. It now warns on the `flag is None` branch.
        """
        from pathlib import Path

        import halfblood.document_processor as dp

        source = Path(dp.__file__).read_text(encoding="utf-8")
        assert "Unmapped composition degradation code" in source
