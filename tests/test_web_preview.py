"""P0-T4 — web preview target matching, complexity bounds, and safe embedding.

AUD-06: ``_flexible_pattern`` runs ``re.escape`` BEFORE substituting spaces,
so ``re.escape(" ")`` -> ``"\\ "`` and the replace yields a literal-backslash
``\\\\s+`` — every multi-word target fails to match (even against plain
spaces) and silently falls back to anchoring its longest single word, which
can sit anywhere on the page. Fixing the pattern re-opens the inherited
ReDoS concern (#13), so the correction is coupled with explicit input
bounds: oversized targets must be safely unanchored, never fed to the
regex engine.

AUD-25: this module had zero test coverage — AUD-06 shipped precisely
because of that.

AUD-35 (accepted, fixed opportunistically while the file is open):
``json.dumps(..., ensure_ascii=False)`` can emit raw U+2028/U+2029 into the
inline ``<script>`` block, a syntax error in pre-ES2019 engines. The data
payload must escape them while round-tripping content byte-for-byte.

The page HTML (including ``<mark>`` anchors) is embedded inside the
``window.__HB_DATA__`` JSON payload and rendered client-side, so these tests
parse that payload rather than scanning the template.

No network calls are made anywhere in this file.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from halfblood.models import AnnotatedPage, Annotation, AnnotationPlan, AnnotationType
from halfblood.web_preview import (
    _find_target_span,
    _flexible_pattern,
    generate_preview,
    render_html,
)

# Contract pinned by this suite: targets longer than this are never fed to
# the regex engine — they come back unanchored instead.
_TARGET_CHAR_CEILING = 1500


def _ann(
    target: str,
    content: str = "Obvious.",
    atype: AnnotationType = AnnotationType.INSIGHT,
) -> Annotation:
    return Annotation(
        page=1,
        target_text=target,
        annotation_type=atype,
        content=content,
        confidence=0.9,
        position="margin_right",
    )


def _plan(text: str, annotations: list[Annotation], title: str = "Test Plan") -> AnnotationPlan:
    return AnnotationPlan(
        title=title,
        prince_persona="the Prince",
        pages=[
            AnnotatedPage(page_number=1, original_text=text, annotations=annotations)
        ],
    )


def _extract_data(html_out: str) -> tuple[dict, str]:
    """Parse the embedded ``window.__HB_DATA__`` JSON. Returns (data, raw_payload)."""
    match = re.search(r"window\.__HB_DATA__ = (.*?);</script>", html_out, re.DOTALL)
    assert match, "embedded data script not found"
    payload = match.group(1)
    return json.loads(payload), payload


# ---------------------------------------------------------------------------
# AUD-06 — the flexible pattern must actually match multi-word targets
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "haystack",
    ["two words", "two\twords", "two\n   words", "two  \t\n words"],
    ids=["space", "tab", "newline", "mixed-run"],
)
def test_flexible_pattern_matches_any_whitespace_run(haystack: str) -> None:
    assert re.fullmatch(_flexible_pattern("two words"), haystack) is not None


def test_flexible_pattern_rejects_intervening_text() -> None:
    assert re.search(_flexible_pattern("two words"), "two clever words") is None


def test_flexible_pattern_keeps_punctuation_literal() -> None:
    pattern = _flexible_pattern("costs 2+2 (four).")
    assert re.search(pattern, "costs 2+2 (four).") is not None
    # '+' must not quantify, '.' must not wildcard, parens must not group.
    assert re.search(pattern, "costs 222 (four).") is None
    assert re.search(pattern, "costs 2+2 (fourX.") is None


def test_flexible_pattern_matches_smart_punctuation_variants() -> None:
    assert re.search(_flexible_pattern("don't stop"), "don’t stop") is not None
    assert re.search(_flexible_pattern('a "quote" here'), "a “quote” here") is not None
    assert re.search(_flexible_pattern("pre-war"), "pre–war") is not None


def test_find_target_span_anchors_the_full_phrase() -> None:
    haystack = "You must stir the cauldron slowly, then rest."
    span = _find_target_span(haystack, "stir the cauldron")
    assert span is not None
    start, end = span
    assert haystack[start:end] == "stir the cauldron"


def test_full_phrase_wins_over_stray_fallback_word() -> None:
    # The longest single word also appears EARLIER on the page; the full
    # phrase must be tried (and found) first, not the fallback anchor.
    haystack = "cauldron soup is fine. Later, stir the cauldron slowly."
    span = _find_target_span(haystack, "stir the cauldron")
    assert span is not None
    start, end = span
    assert haystack[start:end] == "stir the cauldron"


def test_find_target_span_across_reflowed_linebreak() -> None:
    haystack = "First you stir\nthe cauldron with care."
    span = _find_target_span(haystack, "stir the cauldron")
    assert span is not None
    start, end = span
    assert haystack[start:end] == "stir\nthe cauldron"


# ---------------------------------------------------------------------------
# AUD-06 coupled guard — bounded inputs instead of pathological regex work
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("blank", ["", "   ", "\n\t"])
def test_blank_targets_are_unanchored(blank: str) -> None:
    assert _find_target_span("some page text", blank) is None


def test_oversized_target_is_safely_unanchored() -> None:
    # Contract: beyond the ceiling the target is never handed to the regex
    # engine, even when it is literally present in the page text.
    target = ("lacewing flies stewed twenty one days " * 50)[:_TARGET_CHAR_CEILING + 400]
    haystack = f"prefix {target} suffix"
    assert _find_target_span(haystack, target) is None


def test_adversarial_repeated_prefix_completes_with_prefix_anchor() -> None:
    # Repeated-token target vs. an almost-matching page: bounded work (a
    # pathological implementation hangs the suite), resolving to the DESIGNED
    # degradation — the deterministic 10-word prefix anchor at the first
    # occurrence. Anchor-quality scoring beyond this is Phase 2 locator work.
    target = ("ab " * 60).strip()
    haystack = ("ab " * 59) + "ac"
    span = _find_target_span(haystack, target)
    assert span is not None
    start, end = span
    assert start == 0
    assert haystack[start:end] == ("ab " * 10).strip()


# ---------------------------------------------------------------------------
# Embedding safety — HTML escaping and the JSON <script> payload (AUD-35)
# ---------------------------------------------------------------------------


def test_script_terminator_in_content_cannot_break_out() -> None:
    evil = 'x</script><script>alert("pwn")</script>y'
    out = render_html(_plan("Stir the cauldron.", [_ann("cauldron", content=evil)]))
    data, payload = _extract_data(out)
    assert "</script>" not in payload, "raw terminator inside the data payload"
    assert data["pages"][0]["annotations"][0]["content"] == evil


def test_u2028_u2029_never_raw_in_payload() -> None:
    tricky = "line one line two done"
    out = render_html(_plan("Stir the cauldron.", [_ann("cauldron", content=tricky)]))
    data, payload = _extract_data(out)
    assert " " not in payload and " " not in payload, (
        "raw JS line separators inside the inline <script> payload"
    )
    assert data["pages"][0]["annotations"][0]["content"] == tricky


def test_title_is_html_escaped_outside_the_json_payload() -> None:
    # The raw title legitimately rides inside the JSON payload (it is data);
    # every TEMPLATE substitution of it must be HTML-escaped.
    out = render_html(_plan("text", [], title='Bad <Title> & "Co"'))
    _, payload = _extract_data(out)
    markup = out.replace(payload, "")
    assert "Bad <Title>" not in markup
    assert "Bad &lt;Title&gt; &amp;" in markup


def test_page_text_is_html_escaped_in_payload() -> None:
    out = render_html(_plan("evil <script>alert(1)</script> text", []))
    data, _ = _extract_data(out)
    page_html = data["pages"][0]["html"]
    assert "<script>" not in page_html
    assert "&lt;script&gt;" in page_html


# ---------------------------------------------------------------------------
# End-to-end anchoring through the shipping payload
# ---------------------------------------------------------------------------


def test_multiword_annotation_is_anchored_in_page_html() -> None:
    out = render_html(
        _plan(
            "You must stir the cauldron slowly, then rest.",
            [_ann("stir the cauldron")],
        )
    )
    data, _ = _extract_data(out)
    page = data["pages"][0]
    assert ">stir the cauldron</mark>" in page["html"].replace("\n", " ")
    assert page["annotations"][0]["matched"] is True
    assert data["totals"]["matched"] == 1


def test_unmatched_annotation_degrades_safely() -> None:
    out = render_html(
        _plan(
            "Nothing relevant on this page.",
            [_ann("entirely absent phrasing indeed")],
        )
    )
    data, _ = _extract_data(out)
    page = data["pages"][0]
    assert "<mark" not in page["html"]
    assert page["annotations"][0]["matched"] is False
    assert data["totals"]["matched"] == 0


def test_generate_preview_writes_file_and_counts(tmp_path: Path) -> None:
    out_file = tmp_path / "preview.html"
    result = generate_preview(
        _plan(
            "You must stir the cauldron slowly.",
            [_ann("stir the cauldron"), _ann("absent phrase entirely gone")],
        ),
        out_file,
    )
    assert out_file.exists()
    assert result.page_count == 1
    assert result.annotation_count == 2
    assert result.matched_count == 1
