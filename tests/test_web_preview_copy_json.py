"""Copy-JSON: export the annotation plan straight out of the preview page.

The web preview already embeds the whole plan as `window.__HB_DATA__` (escaped for
`</`, U+2028 and U+2029 — see the serialisation tests in test_web_preview.py). Getting it
back out currently means opening devtools or re-running the CLI with `--dry-run`. A button
closes that gap with no new data path.

The constraint that shapes the implementation: **a preview is opened over `file://`**, and
`file://` is not a secure context in Chrome, so `navigator.clipboard` is frequently
`undefined` exactly where this feature is used. An implementation that only calls
`navigator.clipboard.writeText` would fail silently for the primary use case. Hence a
fallback path and a visible outcome are both required, not optional polish.

The page must also stay self-contained: a strict no-external-assets rule already applies
(`test_rendered_html_has_no_external_asset_references`), so no clipboard library.
"""

from __future__ import annotations

import json
import re

from halfblood.models import AnnotatedPage, Annotation, AnnotationPlan, AnnotationType
from halfblood.web_preview import _render


def _plan() -> AnnotationPlan:
    return AnnotationPlan(
        title="Advanced Potion-Making",
        prince_persona="the Half-Blood Prince",
        pages=[
            AnnotatedPage(
                page_number=1,
                original_text="Crush the sopophorous bean with the flat of a silver dagger.",
                annotations=[
                    Annotation(
                        page=1,
                        target_text="Crush the sopophorous bean",
                        annotation_type=AnnotationType.CORRECTION,
                        content="Crush, don't cut — releases twice the juice.",
                        confidence=0.9,
                        position="margin_right",
                    )
                ],
            )
        ],
    )


def _html() -> str:
    html, _data = _render(_plan(), None)
    return html


class TestCopyJsonControlExists:
    def test_a_copy_json_button_is_rendered(self) -> None:
        html = _html()
        assert 'id="copy-json"' in html
        assert re.search(r"copy[- ]json", html, re.IGNORECASE)

    def test_the_button_is_a_real_button_with_an_accessible_label(self) -> None:
        html = _html()
        match = re.search(r'<button[^>]*id="copy-json"[^>]*>', html)
        assert match, "copy-json must be a <button>, not a div"
        tag = match.group(0)
        assert 'type="button"' in tag, "must not submit anything"

    def test_the_button_sits_with_the_other_header_controls(self) -> None:
        """Discoverability: it belongs next to the theme toggle, not loose in the page."""
        html = _html()
        controls = html[html.index('class="controls"') : html.index("</header>")]
        assert 'id="copy-json"' in controls


class TestCopyJsonBehaviour:
    def test_the_handler_is_wired_to_the_button(self) -> None:
        html = _html()
        assert re.search(r'getElementById\(\s*"copy-json"\s*\)', html)

    def test_it_copies_the_embedded_plan_not_a_re_fetch(self) -> None:
        """The payload must come from the data already in the page."""
        html = _html()
        assert "JSON.stringify" in html
        assert "__HB_DATA__" in html

    def test_it_pretty_prints_so_the_paste_is_readable(self) -> None:
        html = _html()
        assert re.search(r"JSON\.stringify\(\s*\w+\s*,\s*null\s*,\s*2\s*\)", html)

    def test_it_survives_a_file_url_where_clipboard_is_unavailable(self) -> None:
        """`file://` is not a secure context, so navigator.clipboard is often undefined.

        Guarding the modern API and providing execCommand fallback is the whole point;
        without it the button is dead exactly where previews are opened.
        """
        html = _html()
        assert "navigator.clipboard" in html
        assert "execCommand" in html, "no fallback for non-secure-context file:// pages"
        assert re.search(
            r"navigator\.clipboard\s*&&|navigator\.clipboard\s*\?|if\s*\(\s*navigator\.clipboard",
            html,
        ), "navigator.clipboard must be feature-detected, not assumed"

    def test_the_user_gets_feedback(self) -> None:
        """A copy with no visible outcome is indistinguishable from a broken button."""
        html = _html()
        assert re.search(r"Copied|copied", html)


class TestCopyJsonKeepsThePageSafe:
    def test_no_external_asset_is_introduced(self) -> None:
        """No clipboard library, no CDN. Mirrors the exclusion used by
        ``test_rendered_html_has_no_external_asset_references``: XML namespace
        identifiers passed to ``createElementNS`` are opaque strings, not requests."""
        html = _html()
        assert "fonts.googleapis" not in html
        assert "@import" not in html
        residue = html.replace("http://www.w3.org", "")
        assert "https://" not in residue
        assert "http://" not in residue

    def test_the_embedded_payload_is_still_escaped(self) -> None:
        """Regression guard: the button must not change how data is serialised."""
        html = _html()
        found = re.search(r"window\.__HB_DATA__\s*=\s*(\{.*?\});", html, re.DOTALL)
        assert found, "embedded payload not found"
        raw = found.group(1)
        assert "</" not in raw, "unescaped </ can terminate the <script> block early"
        assert "\u2028" not in raw and "\u2029" not in raw, (
            "raw U+2028/U+2029 are JS line terminators and would break the payload"
        )

    def test_the_embedded_payload_is_still_valid_json(self) -> None:
        html = _html()
        match = re.search(r"window\.__HB_DATA__\s*=\s*(\{.*?\});", html, re.DOTALL)
        assert match, "embedded payload not found"
        payload = json.loads(match.group(1).replace("<\\/", "</"))
        assert payload["title"] == "Advanced Potion-Making"
        assert payload["pages"][0]["annotations"][0]["content"].startswith("Crush, don't cut")
