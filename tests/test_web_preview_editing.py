"""Annotation editing controls in the web preview.

Tests that the rendered HTML carries the edit / delete / reposition affordances,
that user-supplied content is always safely escaped, and that the Copy-JSON
export continues to use the live DATA object (so edits are reflected).
"""

from __future__ import annotations

import re

from halfblood.models import AnnotatedPage, Annotation, AnnotationPlan, AnnotationType
from halfblood.web_preview import _render

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_function(src: str, name: str) -> str:
    """Extract a function declaration by brace-depth counting."""
    pattern = f"function {name}("
    start = src.find(pattern)
    if start == -1:
        return ""
    brace_start = src.index("{", start)
    depth = 0
    for i in range(brace_start, len(src)):
        if src[i] == "{":
            depth += 1
        elif src[i] == "}":
            depth -= 1
            if depth == 0:
                return src[start : i + 1]
    return ""


def _main_script() -> str:
    html, _ = _render(_plan(), None)
    matches = list(re.finditer(r"<script>(.*?)</script>", html, re.DOTALL))
    return matches[-1].group(1)


def _plan() -> AnnotationPlan:
    return AnnotationPlan(
        title="Advanced Potion-Making",
        prince_persona="the Half-Blood Prince",
        pages=[
            AnnotatedPage(
                page_number=1,
                original_text="Crush the sopophorous bean. Add the powdered root slowly.",
                annotations=[
                    Annotation(
                        page=1,
                        target_text="Crush the sopophorous bean",
                        annotation_type=AnnotationType.CORRECTION,
                        content="Crush, don't cut — keep a bezoar within reach.",
                        confidence=0.9,
                        position="margin_right",
                    ),
                    Annotation(
                        page=1,
                        target_text="Add the powdered root",
                        annotation_type=AnnotationType.SHORTCUT,
                        content="Skip this entirely. Wasted effort.",
                        confidence=0.7,
                        position="margin_left",
                    ),
                ],
            )
        ],
    )


def _html() -> str:
    h, _data = _render(_plan(), None)
    return h


# ---------------------------------------------------------------------------
# Controls present in rendered output
# ---------------------------------------------------------------------------


class TestEditControlsExist:
    def test_edit_button_class_in_html(self) -> None:
        assert "note-ctrl-edit" in _html()

    def test_delete_button_class_in_html(self) -> None:
        assert "note-ctrl-delete" in _html()

    def test_reposition_button_class_in_html(self) -> None:
        assert "note-ctrl-side" in _html()

    def test_note_controls_container_in_html(self) -> None:
        assert "note-controls" in _html()

    def test_edit_aria_label(self) -> None:
        """The aria-label is set via JS setAttribute; look for it in the script."""
        html = _html()
        script = html[html.index("<script>", html.index("__HB_DATA__")) :]
        assert re.search(r'setAttribute\s*\(\s*"aria-label"\s*,\s*"[Ee]dit', script)

    def test_delete_aria_label(self) -> None:
        html = _html()
        script = html[html.index("<script>", html.index("__HB_DATA__")) :]
        assert re.search(r'setAttribute\s*\(\s*"aria-label"\s*,\s*"[Dd]elete', script)

    def test_reposition_aria_label(self) -> None:
        html = _html()
        script = html[html.index("<script>", html.index("__HB_DATA__")) :]
        assert re.search(r'setAttribute\s*\(\s*"aria-label"\s*,\s*"[Mm]ove', script)

    def test_controls_are_type_button(self) -> None:
        """Affordance buttons must not submit forms — at least 3 new ctrl buttons."""
        html = _html()
        script = html[html.index("<script>", html.index("__HB_DATA__")) :]
        # Count type = "button" assignments in JS (sideBtn.type, editBtn.type, delBtn.type, …)
        assert script.count('type = "button"') >= 3 or 'type="button"' in html


# ---------------------------------------------------------------------------
# JS functions present
# ---------------------------------------------------------------------------


class TestJsFunctionsPresent:
    def test_start_edit_function_present(self) -> None:
        assert "function startEdit(" in _html()

    def test_delete_annotation_function_present(self) -> None:
        assert "function deleteAnnotation(" in _html()

    def test_reposition_annotation_function_present(self) -> None:
        assert "function repositionAnnotation(" in _html()

    def test_editing_id_in_state(self) -> None:
        assert "editingId" in _html()

    def test_start_edit_called_from_button(self) -> None:
        html = _html()
        script = html[html.index("<script>", html.index("__HB_DATA__")) :]
        assert re.search(r"startEdit\s*\(", script)

    def test_delete_called_from_button(self) -> None:
        html = _html()
        script = html[html.index("<script>", html.index("__HB_DATA__")) :]
        assert re.search(r"deleteAnnotation\s*\(", script)

    def test_reposition_called_from_button(self) -> None:
        html = _html()
        script = html[html.index("<script>", html.index("__HB_DATA__")) :]
        assert re.search(r"repositionAnnotation\s*\(", script)

    def test_textarea_createElement_in_start_edit(self) -> None:
        """Edit textarea must use createElement, not innerHTML with user content."""
        html = _html()
        script = html[html.index("<script>", html.index("__HB_DATA__")) :]
        # startEdit must create a textarea element
        assert re.search(r'createElement\s*\(\s*"textarea"', script)

    def test_edit_save_uses_textContent_not_innerHTML(self) -> None:
        """The save path must use textContent (not innerHTML) to set the note text.

        Uses the brace-depth extractor so the assertion is scoped to exactly the
        startEdit function body — not a surrounding window that may legitimately
        contain innerHTML in init() or escapeHtml calls.
        """
        script = _main_script()
        fn_body = _extract_function(script, "startEdit")
        assert fn_body, "startEdit function not found in generated script"
        assert "noteText.textContent" in fn_body, (
            "save handler must update the note DOM via textContent"
        )
        # The function may mention "innerHTML" in a defensive comment, but must
        # never assign user-controlled content through it.
        assert "noteText.innerHTML" not in fn_body, (
            "startEdit must never assign the note text via innerHTML"
        )
        assert ".innerHTML =" not in fn_body, (
            "startEdit must not contain any innerHTML assignment"
        )


# ---------------------------------------------------------------------------
# XSS / escaping guarantees
# ---------------------------------------------------------------------------


class TestEscapingHolds:
    def test_xss_content_not_raw_in_html(self) -> None:
        """Annotation content containing <script> must never appear raw."""
        plan = AnnotationPlan(
            title="XSS Test",
            prince_persona="Prince",
            pages=[
                AnnotatedPage(
                    page_number=1,
                    original_text="some text here",
                    annotations=[
                        Annotation(
                            page=1,
                            target_text="some text",
                            annotation_type=AnnotationType.CORRECTION,
                            content="<script>alert(1)</script>",
                            confidence=0.9,
                            position="margin_right",
                        ),
                    ],
                )
            ],
        )
        html, _data = _render(plan, None)
        assert "<script>alert(1)</script>" not in html

    def test_script_closer_in_content_escaped_in_payload(self) -> None:
        """A </script> literal in annotation content must be escaped in the JSON payload."""
        plan = AnnotationPlan(
            title="XSS Test",
            prince_persona="Prince",
            pages=[
                AnnotatedPage(
                    page_number=1,
                    original_text="some text here",
                    annotations=[
                        Annotation(
                            page=1,
                            target_text="some text",
                            annotation_type=AnnotationType.CORRECTION,
                            content="</script><script>alert(1)</script>",
                            confidence=0.9,
                            position="margin_right",
                        ),
                    ],
                )
            ],
        )
        html, _data = _render(plan, None)
        # The payload escape replaces "</" with "<\/"
        assert "</script><script>" not in html

    def test_escape_html_used_for_note_rendering(self) -> None:
        """Regression: editing controls must not remove the escapeHtml call."""
        assert "escapeHtml" in _html()

    def test_embedded_payload_script_closer_escaped(self) -> None:
        html = _html()
        found = re.search(r"window\.__HB_DATA__\s*=\s*(\{.*?\});", html, re.DOTALL)
        assert found, "embedded payload not found"
        raw = found.group(1)
        assert "</" not in raw, "unescaped </ can close the <script> block early"

    def test_no_external_assets_introduced(self) -> None:
        html = _html()
        residue = html.replace("http://www.w3.org", "")
        assert "https://" not in residue
        assert "http://" not in residue


# ---------------------------------------------------------------------------
# Copy-JSON exports the live DATA object (so edits are reflected)
# ---------------------------------------------------------------------------


class TestCopyJsonReflectsEdits:
    def test_copy_json_stringifies_data_object(self) -> None:
        """Export must stringify the live DATA reference, not a snapshot string."""
        html = _html()
        script = html[html.index("<script>", html.index("__HB_DATA__")) :]
        assert re.search(r"JSON\.stringify\(\s*DATA\s*,", script)

    def test_copy_json_still_pretty_prints(self) -> None:
        html = _html()
        assert re.search(r"JSON\.stringify\(\s*\w+\s*,\s*null\s*,\s*2\s*\)", html)


# ---------------------------------------------------------------------------
# Existing features not broken
# ---------------------------------------------------------------------------


class TestExistingFeaturesUnbroken:
    def test_legend_still_builds(self) -> None:
        assert "legend-chip" in _html()
        assert "hiddenTypes" in _html()

    def test_search_still_present(self) -> None:
        assert 'id="note-search"' in _html()

    def test_copy_json_button_still_present(self) -> None:
        assert 'id="copy-json"' in _html()

    def test_apply_filters_still_scoped_to_page(self) -> None:
        html = _html()
        script = html[html.index("<script>", html.index("__HB_DATA__")) :]
        body = script[script.index("function applyFilters()") :]
        assert re.search(r"DATA\.pages[^\n]*\[\s*state\.idx\s*\]", body), (
            "applyFilters must scope the match set to the current page"
        )

    def test_both_annotations_still_in_payload(self) -> None:
        html = _html()
        assert "bezoar" in html
        assert "Wasted effort" in html


# ---------------------------------------------------------------------------
# Per-page scoping: new handlers must index DATA.pages[state.idx]
# ---------------------------------------------------------------------------


class TestNewHandlersScopedToPage:
    """Annotation IDs are page-local ('a0', 'a1', ...).

    A handler that iterates DATA globally or uses a wrong page index can
    mutate the wrong page's annotation on multi-page plans.  Pin each new
    handler to DATA.pages[state.idx] — the same invariant already pinned
    for applyFilters in test_web_preview_search.py.
    """

    def test_delete_annotation_scoped_to_current_page(self) -> None:
        script = _main_script()
        fn_body = _extract_function(script, "deleteAnnotation")
        assert fn_body, "deleteAnnotation not found"
        assert re.search(r"DATA\.pages[^\n]*\[\s*state\.idx\s*\]", fn_body), (
            "deleteAnnotation must index DATA.pages[state.idx]; "
            "a global lookup would delete the wrong annotation on multi-page plans"
        )

    def test_reposition_annotation_scoped_to_current_page(self) -> None:
        script = _main_script()
        fn_body = _extract_function(script, "repositionAnnotation")
        assert fn_body, "repositionAnnotation not found"
        assert re.search(r"DATA\.pages[^\n]*\[\s*state\.idx\s*\]", fn_body), (
            "repositionAnnotation must index DATA.pages[state.idx]"
        )

    def test_start_edit_scoped_to_current_page(self) -> None:
        script = _main_script()
        fn_body = _extract_function(script, "startEdit")
        assert fn_body, "startEdit not found"
        assert re.search(r"DATA\.pages[^\n]*\[\s*state\.idx\s*\]", fn_body), (
            "startEdit must index DATA.pages[state.idx] when committing the edited content"
        )
