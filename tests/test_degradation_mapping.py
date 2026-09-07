"""Connector summary flags and unmapped composer diagnostics stay observable.

Summary flags remain finite. Report 1.1 also records every composer code, so
unknown codes no longer depend on a log message or an ever-growing mapping.
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

    def test_unmapped_code_is_preserved_in_report(self, tmp_path, monkeypatch) -> None:
        """Even a future unmapped code survives actual composition and rendering."""
        from dataclasses import replace

        from test_placement_rendering import make_plan, make_source

        from halfblood.document_processor import DocumentProcessor
        from halfblood.ink.composer import InkComposer, InkDegradation

        original = InkComposer.compose

        def compose(self, *args, **kwargs):
            result = original(self, *args, **kwargs)
            return replace(result, degradations=(*result.degradations, InkDegradation(
                annotation_id="ann-0", role=None, code="future_unmapped_code",
                detail="The diagnostic must remain visible.",
            )))

        monkeypatch.setattr(InkComposer, "compose", compose)
        source = make_source(tmp_path, "pdf", "A uniquely supported quotation.")
        report = DocumentProcessor().render_plan(
            str(source), make_plan("A uniquely supported quotation."), str(tmp_path / "out.pdf"),
        )
        diagnostics = [d for d in report.composition_degradations
                       if d.code == "future_unmapped_code"]
        assert len(diagnostics) == 1
        assert diagnostics[0].annotation_id == "ann-0"
        assert diagnostics[0].detail == "The diagnostic must remain visible."
