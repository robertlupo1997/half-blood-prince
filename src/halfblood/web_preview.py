"""Interactive HTML "web preview" for Half-Blood Prince annotation plans.

This module turns an :class:`~halfblood.models.AnnotationPlan` into a single,
self-contained HTML file: a page-by-page book viewer where the Prince's
margin notes hover beside the text, connected to their target passage by a
small hand-drawn line, and "write themselves" onto the page in a locally
available handwriting font, fading in and out like ink that hasn't
quite dried -- an homage to the Riddle diary's self-writing pages.

Everything -- CSS, JS, and the annotation data itself (as JSON) -- is
embedded directly in the emitted HTML file, so the result is a single
artifact you can email, drop on a static file host, or just double-click.

Usage::

    from halfblood.web_preview import generate_preview
    from halfblood.models import AnnotationPlan

    plan = AnnotationPlan(...)
    generate_preview(plan, "preview.html")

    # or, from a JSON file on disk:
    generate_preview("annotated_plan.json", "preview.html")

The matching CLI command lives in :mod:`halfblood.cli` as ``web-preview``.
"""

from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from halfblood.file_safety import atomic_write_text, require_distinct_output
from halfblood.models import AnnotatedPage, Annotation, AnnotationPlan, AnnotationType

# ---------------------------------------------------------------------------
# Type metadata: display label + a small glyph used in the legend and
# before each note. Colors themselves live in the CSS (`_CSS` below) as
# CSS custom properties, keyed the same way (by `AnnotationType.value`), so
# Python and CSS never have to agree on hex codes in two places.
# ---------------------------------------------------------------------------

_TYPE_META: dict[AnnotationType, dict[str, str]] = {
    AnnotationType.CORRECTION: {"label": "Correction", "glyph": "✎"},
    AnnotationType.IMPROVEMENT: {"label": "Improvement", "glyph": "↑"},
    AnnotationType.INSIGHT: {"label": "Insight", "glyph": "✦"},
    AnnotationType.INVENTION: {"label": "Invention", "glyph": "⚗"},
    AnnotationType.WARNING: {"label": "Warning", "glyph": "⚠"},
    AnnotationType.SHORTCUT: {"label": "Shortcut", "glyph": "⇢"},
    AnnotationType.CROSSED_OUT: {"label": "Crossed out", "glyph": "✕"},
    AnnotationType.DOODLE_NOTE: {"label": "Doodle", "glyph": "❦"},
}

_VALID_POSITIONS = {"margin_right", "margin_left", "inline", "between_lines"}


@dataclass
class PreviewResult:
    """Small summary returned by :func:`generate_preview`."""

    output_path: Path
    page_count: int
    annotation_count: int
    matched_count: int


# ---------------------------------------------------------------------------
# Text matching: locate each annotation's `target_text` inside the page's
# `original_text` so we can wrap it in a <mark> the viewer can hover/connect
# a line to. LLM-generated target_text rarely matches byte-for-byte (smart
# quotes, collapsed whitespace, reflowed line breaks), so this builds a
# forgiving regex rather than doing a literal substring search -- similar in
# spirit to DocumentProcessor.find_text_rect, but working against plain page
# text instead of a PDF text layer, and returning character offsets instead
# of a rect.
# ---------------------------------------------------------------------------

_QUOTE_CHARS = "'‘’′"
_DQUOTE_CHARS = '"“”″'
_DASH_CHARS = "-–—"
_SPECIAL_CHARS = set(_QUOTE_CHARS + _DQUOTE_CHARS + _DASH_CHARS)
_MAX_TARGET_LENGTH = 1500


def _char_class_for(ch: str) -> str:
    if ch in _QUOTE_CHARS:
        return "[" + _QUOTE_CHARS + "]"
    if ch in _DQUOTE_CHARS:
        return "[" + _DQUOTE_CHARS + "]"
    return "[" + _DASH_CHARS + "]"


def _flexible_pattern(text: str) -> str:
    """Build a regex that matches `text` loosely: any run of whitespace
    matches any other run of whitespace, and quote/dash characters match
    any of their "smart" typographic variants.
    """
    collapsed = re.sub(r"\s+", " ", text.strip())
    out: list[str] = []
    for ch in collapsed:
        if ch == " ":
            out.append(r"\s+")
        elif ch in _SPECIAL_CHARS:
            out.append(_char_class_for(ch))
        else:
            out.append(re.escape(ch))
    return "".join(out)


def _candidate_variants(text: str) -> list[str]:
    """Progressively shorter anchors to try, so a small transcription drift
    in a long `target_text` doesn't cause the whole annotation to be
    dropped from the interactive view (it'll just anchor to a prefix).
    """
    words = text.split()
    variants = [text]
    for n in (10, 6, 4):
        if len(words) > n:
            variants.append(" ".join(words[:n]))
    longest = max((w.strip(".,;:!?\"'()[]") for w in words), key=len, default="")
    if len(longest) >= 4:
        variants.append(longest)

    seen: set[str] = set()
    unique: list[str] = []
    for variant in variants:
        variant = variant.strip()
        if variant and variant not in seen:
            seen.add(variant)
            unique.append(variant)
    return unique


def _find_target_span(haystack: str, target: str) -> tuple[int, int] | None:
    if not haystack or not target or not target.strip():
        return None
    if len(target) > _MAX_TARGET_LENGTH:
        return None
    for variant in _candidate_variants(target):
        pattern = _flexible_pattern(variant)
        if not pattern:
            continue
        try:
            match = re.search(pattern, haystack, re.IGNORECASE)
        except re.error:
            continue
        if match:
            return match.start(), match.end()
    return None


_PARA_SEP = re.compile(r"\n[ \t]*\n[ \t\n]*")


def _paragraph_spans(text: str) -> list[tuple[int, int]]:
    """Split `text` into paragraph (start, end) character spans on blank
    lines, preserving offsets into the original string.
    """
    if not text:
        return []
    spans: list[tuple[int, int]] = []
    last = 0
    for match in _PARA_SEP.finditer(text):
        if match.start() > last:
            spans.append((last, match.start()))
        last = match.end()
    if last < len(text):
        spans.append((last, len(text)))
    if not spans:
        spans = [(0, len(text))]
    return spans


def _esc(segment: str) -> str:
    return html.escape(segment, quote=False).replace("\n", "<br>\n")


def _build_page_html(
    original_text: str, annotations: list[Annotation]
) -> tuple[str, list[bool]]:
    """Render `original_text` as paragraph HTML with each annotation's
    `target_text` wrapped in a `<mark>`, where locatable.

    Returns the HTML string plus a parallel list of booleans (same order
    as `annotations`) saying whether each one was actually anchored to a
    `<mark>` in the output -- annotations whose text can't be found, or
    whose match straddles a paragraph break, or which overlap an
    earlier-claimed span, come back `False` and are left for the front end
    to place as unanchored notes.
    """
    paragraphs = _paragraph_spans(original_text)

    accepted: list[tuple[int, int, int]] = []  # (start, end, annotation_index)
    matched = [False] * len(annotations)

    for idx, annotation in enumerate(annotations):
        span = _find_target_span(original_text, annotation.target_text)
        if span is None:
            continue
        start, end = span
        if not any(p_start <= start and end <= p_end for p_start, p_end in paragraphs):
            continue  # spans a paragraph break; too awkward to mark inline
        overlaps = any(not (end <= a_end or start >= a_start) for a_start, a_end, _ in accepted)
        if overlaps:
            continue
        accepted.append((start, end, idx))
        matched[idx] = True

    accepted.sort(key=lambda item: item[0])

    if not original_text.strip():
        return '<p class="empty-page"><em>(no page text available)</em></p>', matched

    paragraph_html: list[str] = []
    for p_start, p_end in paragraphs:
        cursor = p_start
        pieces: list[str] = []
        for start, end, idx in accepted:
            if start < p_start or end > p_end or start < cursor:
                continue
            if start > cursor:
                pieces.append(_esc(original_text[cursor:start]))
            annotation = annotations[idx]
            pieces.append(
                f'<mark class="target type-{annotation.annotation_type.value}" data-ann-id="a{idx}" '
                f'data-type="{annotation.annotation_type.value}">{_esc(original_text[start:end])}</mark>'
            )
            cursor = end
        if cursor < p_end:
            pieces.append(_esc(original_text[cursor:p_end]))
        paragraph_html.append(f"<p>{''.join(pieces)}</p>")

    return "\n".join(paragraph_html), matched


# ---------------------------------------------------------------------------
# Plan -> JSON payload
# ---------------------------------------------------------------------------


def _annotation_payload(annotation: Annotation, ann_id: str, is_matched: bool) -> dict:
    position = annotation.position if annotation.position in _VALID_POSITIONS else "margin_right"
    return {
        "id": ann_id,
        "type": annotation.annotation_type.value,
        "content": annotation.content,
        "target_text": annotation.target_text,
        "confidence": round(float(annotation.confidence), 3),
        "position": position,
        "matched": is_matched,
    }


def _build_data(plan: AnnotationPlan) -> dict:
    pages_sorted = sorted(plan.pages, key=lambda page: page.page_number)

    pages_payload = []
    total_annotations = 0
    total_matched = 0

    for page in pages_sorted:
        page_html, matched_flags = _build_page_html(page.original_text or "", page.annotations)
        annotations_payload = []
        for idx, annotation in enumerate(page.annotations):
            annotations_payload.append(
                _annotation_payload(annotation, f"a{idx}", matched_flags[idx])
            )
            total_annotations += 1
            if matched_flags[idx]:
                total_matched += 1

        pages_payload.append(
            {
                "number": page.page_number,
                "html": page_html,
                "annotations": annotations_payload,
            }
        )

    types_payload = [
        {"value": t.value, "label": meta["label"], "glyph": meta["glyph"]}
        for t, meta in _TYPE_META.items()
    ]

    return {
        "title": plan.title or "Untitled",
        "persona": plan.prince_persona or "",
        "generated": datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
        "pages": pages_payload,
        "types": types_payload,
        "totals": {
            "pages": len(pages_payload),
            "annotations": total_annotations,
            "matched": total_matched,
        },
    }


# ---------------------------------------------------------------------------
# Loading / filling in text
# ---------------------------------------------------------------------------


def _load_plan(plan: AnnotationPlan | str | Path) -> AnnotationPlan:
    if isinstance(plan, AnnotationPlan):
        return plan
    path = Path(plan)
    return AnnotationPlan.model_validate_json(path.read_text(encoding="utf-8"))


def _fill_missing_text(
    pages: list[AnnotatedPage], book_text: str | None
) -> list[AnnotatedPage]:
    """Best-effort backfill of `AnnotatedPage.original_text` from a
    separately-supplied full book text, for plans whose pages don't already
    carry their own text. Only kicks in if `book_text` contains form-feed
    (``\\f``) page breaks and splits into at least as many chunks as there
    are pages; otherwise the pages are returned unchanged.
    """
    if not book_text:
        return pages
    if all((page.original_text or "").strip() for page in pages):
        return pages

    chunks = book_text.split("\f") if "\f" in book_text else None
    if not chunks or len(chunks) < len(pages):
        return pages

    filled: list[AnnotatedPage] = []
    for i, page in enumerate(pages):
        if (page.original_text or "").strip():
            filled.append(page)
        else:
            filled.append(page.model_copy(update={"original_text": chunks[i].strip()}))
    return filled


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _render(plan: AnnotationPlan, book_text: str | None) -> tuple[str, dict]:
    pages = _fill_missing_text(list(plan.pages), book_text)
    plan = plan.model_copy(update={"pages": pages})

    data = _build_data(plan)
    data_json = (
        json.dumps(data, ensure_ascii=False)
        .replace("</", "<\\/")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )

    out = _HTML_TEMPLATE
    out = out.replace("%%CSS%%", _CSS)
    out = out.replace("%%JS%%", _JS)
    out = out.replace("%%PAGE_TITLE%%", html.escape(plan.title or "Untitled", quote=True))
    out = out.replace("%%DATA_JSON%%", data_json)
    return out, data


def render_html(plan: AnnotationPlan | str | Path, book_text: str | None = None) -> str:
    """Render `plan` to a standalone HTML string, without writing a file.

    `plan` may be an :class:`AnnotationPlan` instance or a path to a
    JSON file containing one (as produced by ``AnnotationPlan.model_dump_json()``).
    """
    loaded_plan = _load_plan(plan)
    html_str, _data = _render(loaded_plan, book_text)
    return html_str


def generate_preview(
    plan: AnnotationPlan | str | Path,
    output_path: str | Path,
    book_text: str | None = None,
) -> PreviewResult:
    """Render `plan` into a single self-contained interactive HTML file.

    Args:
        plan: An :class:`AnnotationPlan`, or a path to a JSON file
            containing one.
        output_path: Where to write the HTML file. Parent directories are
            created if needed.
        book_text: Optional full book text, used only to backfill any page
            whose `original_text` is empty (see :func:`_fill_missing_text`).
            Most plans already carry their own per-page text and won't need
            this.

    Returns:
        A :class:`PreviewResult` summarizing what was written.
    """
    out_path = Path(output_path)
    if isinstance(plan, (str, Path)):
        require_distinct_output(out_path, (Path(plan),))
    loaded_plan = _load_plan(plan)
    html_str, data = _render(loaded_plan, book_text)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(out_path, html_str)

    totals = data["totals"]
    return PreviewResult(
        output_path=out_path,
        page_count=totals["pages"],
        annotation_count=totals["annotations"],
        matched_count=totals["matched"],
    )


# ---------------------------------------------------------------------------
# Templates: HTML shell / CSS / JS.
#
# Kept as plain (non-f) strings and stitched together with `%%TOKEN%%`
# placeholders in `_render`, since the CSS and JS below are full of literal
# `{`/`}` that would otherwise collide with `str.format`/f-strings.
# ---------------------------------------------------------------------------

_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en" data-theme="parchment">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>%%PAGE_TITLE%% — Half-Blood Prince Preview</title>
<style>
%%CSS%%
</style>
</head>
<body>
<noscript>
  <p style="padding:2rem;font-family:Georgia,serif;max-width:40rem;margin:0 auto;">
    This preview needs JavaScript enabled for the margin notes to write
    themselves in. Please enable it and reload.
  </p>
</noscript>

<div id="app">
  <header class="site-header">
    <div class="title-block">
      <h1 id="book-title"></h1>
      <p class="persona" id="book-persona"></p>
    </div>
    <div class="controls">
      <div class="legend" id="legend" aria-label="Annotation types (click to toggle)"></div>
      <input type="search" id="note-search" aria-label="Search annotations" placeholder="Search annotations…">
      <span id="search-count"></span>
      <button type="button" id="copy-json" class="theme-toggle" aria-label="Copy the annotation plan as JSON">&#128203; Copy JSON</button>
      <button type="button" id="theme-toggle" class="theme-toggle" aria-label="Toggle dark mode">&#127769; Dark</button>
    </div>
  </header>

  <main class="page-stage">
    <button type="button" class="nav-btn prev" id="prev-btn" aria-label="Previous page">&#8249;</button>

    <div class="page-frame" id="page-frame">
      <div class="margin margin-left" id="margin-left"></div>
      <article class="book-page" id="book-page">
        <div class="page-number-badge" id="page-number-badge"></div>
        <div class="book-text" id="book-text"></div>
      </article>
      <div class="margin margin-right" id="margin-right"></div>
      <svg class="connector-layer" id="connector-layer" aria-hidden="true"></svg>
    </div>

    <button type="button" class="nav-btn next" id="next-btn" aria-label="Next page">&#8250;</button>
  </main>

  <footer class="page-nav-footer">
    <input type="range" id="page-slider" min="1" max="1" value="1" aria-label="Jump to page">
    <span id="page-indicator">Page 1 of 1</span>
    <span class="generated-stamp" id="generated-stamp"></span>
  </footer>
</div>

<script>window.__HB_DATA__ = %%DATA_JSON%%;</script>
<script>
%%JS%%
</script>
</body>
</html>
"""

_CSS = r"""
:root{
  --bg:#e9dfc4;
  --bg-page:#faf3e2;
  --bg-page-edge:#efe4c8;
  --text:#2b2117;
  --text-muted:#71624a;
  --rule:rgba(90,68,35,.22);
  --shadow:rgba(45,30,10,.35);
  --header-bg:rgba(255,251,240,.6);
  --accent:#7a1f1f;
  --focus-ring:#c1650a;

  --ink-correction:#8b1e1e;         --ink-correction-soft:rgba(139,30,30,.16);
  --ink-improvement:#256b32;        --ink-improvement-soft:rgba(37,107,50,.16);
  --ink-insight:#1c4f8b;            --ink-insight-soft:rgba(28,79,139,.16);
  --ink-invention:#5b2a86;          --ink-invention-soft:rgba(91,42,134,.16);
  --ink-warning:#c1650a;            --ink-warning-soft:rgba(193,101,10,.18);
  --ink-shortcut:#74741f;           --ink-shortcut-soft:rgba(116,116,31,.18);
  --ink-crossed_out:#5a5a5a;        --ink-crossed_out-soft:rgba(90,90,90,.18);
  --ink-doodle_note:#17171a;        --ink-doodle_note-soft:rgba(23,23,26,.14);

  --serif:Georgia,'Times New Roman',serif;
  --hand:'Caveat','Bradley Hand','Segoe Print','Comic Sans MS',cursive;
}

[data-theme="dark"]{
  --bg:#141210;
  --bg-page:#1d1a15;
  --bg-page-edge:#171512;
  --text:#e9ddc4;
  --text-muted:#a8967a;
  --rule:rgba(255,240,210,.14);
  --shadow:rgba(0,0,0,.7);
  --header-bg:rgba(10,9,7,.6);
  --accent:#e2a5a5;
  --focus-ring:#f1a545;

  --ink-correction:#e0706f;         --ink-correction-soft:rgba(224,112,111,.22);
  --ink-improvement:#79c97e;        --ink-improvement-soft:rgba(121,201,126,.22);
  --ink-insight:#79aee0;            --ink-insight-soft:rgba(121,174,224,.22);
  --ink-invention:#bd93e6;          --ink-invention-soft:rgba(189,147,230,.22);
  --ink-warning:#f0ab5e;            --ink-warning-soft:rgba(240,171,94,.24);
  --ink-shortcut:#d3cf6c;           --ink-shortcut-soft:rgba(211,207,108,.24);
  --ink-crossed_out:#a9a9a9;        --ink-crossed_out-soft:rgba(169,169,169,.22);
  --ink-doodle_note:#d8d0bc;        --ink-doodle_note-soft:rgba(216,208,188,.2);
}

/* per-type indirection: everything that needs "the ink color" just reads
   var(--ink)/var(--ink-soft); these classes are the only place that maps
   an annotation type onto a concrete color. */
.type-correction{--ink:var(--ink-correction);--ink-soft:var(--ink-correction-soft);}
.type-improvement{--ink:var(--ink-improvement);--ink-soft:var(--ink-improvement-soft);}
.type-insight{--ink:var(--ink-insight);--ink-soft:var(--ink-insight-soft);}
.type-invention{--ink:var(--ink-invention);--ink-soft:var(--ink-invention-soft);}
.type-warning{--ink:var(--ink-warning);--ink-soft:var(--ink-warning-soft);}
.type-shortcut{--ink:var(--ink-shortcut);--ink-soft:var(--ink-shortcut-soft);}
.type-crossed_out{--ink:var(--ink-crossed_out);--ink-soft:var(--ink-crossed_out-soft);}
.type-doodle_note{--ink:var(--ink-doodle_note);--ink-soft:var(--ink-doodle_note-soft);}

*{box-sizing:border-box;}
html,body{height:100%;}
body{
  margin:0;
  min-height:100vh;
  background:var(--bg);
  background-image:radial-gradient(ellipse at top, rgba(255,255,255,.18), transparent 60%);
  color:var(--text);
  font-family:var(--serif);
  transition:background .4s ease, color .4s ease;
}
#app{display:flex;flex-direction:column;min-height:100vh;}

button{font-family:inherit;}
:focus-visible{outline:2px solid var(--focus-ring);outline-offset:2px;}

/* ---------- header ---------- */
.site-header{
  position:sticky;top:0;z-index:20;
  display:flex;align-items:flex-start;justify-content:space-between;gap:1.5rem;
  padding:1rem 2rem;
  background:var(--header-bg);
  backdrop-filter:blur(8px);
  border-bottom:1px solid var(--rule);
  flex-wrap:wrap;
}
.title-block h1{
  margin:0;font-size:1.5rem;font-weight:600;letter-spacing:.02em;
}
.title-block .persona{
  margin:.25rem 0 0;max-width:56ch;
  font-family:var(--hand);font-size:1.15rem;color:var(--accent);
  overflow:hidden;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;
}
.controls{display:flex;align-items:center;gap:1rem;flex-wrap:wrap;}
.legend{display:flex;flex-wrap:wrap;gap:.4rem;max-width:46rem;}
.legend-chip{
  display:inline-flex;align-items:center;gap:.3em;
  border:1px solid var(--ink);color:var(--ink);
  background:transparent;border-radius:999px;padding:.2rem .65rem;
  font-size:.76rem;letter-spacing:.01em;cursor:pointer;
  transition:opacity .2s ease, background-color .2s ease;
}
.legend-chip:hover{background:var(--ink-soft);}
.legend-chip.off{opacity:.32;text-decoration:line-through;}
.theme-toggle{
  border:1px solid var(--rule);background:transparent;color:var(--text);
  border-radius:999px;padding:.35rem .9rem;font-size:.82rem;cursor:pointer;
  transition:background-color .2s ease;
}
.theme-toggle:hover{background:var(--rule);}

/* ---------- page stage / nav ---------- */
.page-stage{
  flex:1;display:flex;align-items:flex-start;justify-content:center;gap:1rem;
  padding:2.5rem 1.5rem;
}
.nav-btn{
  flex:0 0 auto;width:2.6rem;height:2.6rem;border-radius:50%;
  border:1px solid var(--rule);background:var(--bg-page);color:var(--text);
  font-size:1.4rem;line-height:1;cursor:pointer;
  box-shadow:0 4px 12px var(--shadow);
  transition:transform .15s ease, opacity .2s ease;
  position:sticky;top:9rem;
}
.nav-btn:hover:not(:disabled){transform:translateY(-2px);}
.nav-btn:disabled{opacity:.25;cursor:default;}

.page-frame{
  position:relative;
  display:grid;
  grid-template-columns:minmax(120px,180px) minmax(320px,680px) minmax(120px,180px);
  column-gap:28px;
  align-items:stretch;
  width:100%;
  max-width:1180px;
}
.margin-left{grid-column:1;grid-row:1;}
.book-page{grid-column:2;grid-row:1;}
.margin-right{grid-column:3;grid-row:1;}
.connector-layer{grid-column:1 / -1;grid-row:1;pointer-events:none;overflow:visible;width:100%;height:100%;}
.connector{fill:none;stroke:var(--ink);stroke-width:1.4;opacity:.32;transition:opacity .25s ease, stroke-width .25s ease;}
.connector.active{opacity:.95;stroke-width:2;}
.connector.filtered-out{opacity:.05 !important;}

.margin{position:relative;}

/* ---------- the page itself ---------- */
.book-page{
  position:relative;
  background:var(--bg-page);
  border-radius:2px;
  padding:3.4rem 3rem 3rem;
  box-shadow:0 22px 50px var(--shadow), 0 0 0 1px var(--bg-page-edge);
  background-image:
    repeating-linear-gradient(0deg, rgba(0,0,0,.015) 0 2px, transparent 2px 4px),
    radial-gradient(ellipse at 50% 0%, rgba(255,255,255,.35), transparent 55%);
  opacity:0;transform:translateY(8px);
}
.book-page.entering{animation:pageEnter .55s ease forwards;}
@keyframes pageEnter{to{opacity:1;transform:translateY(0);}}

.page-number-badge{
  position:absolute;top:1rem;right:1.2rem;
  font-family:var(--hand);font-size:1.05rem;color:var(--text-muted);
}
.book-text{font-size:1.08rem;line-height:1.8;}
.book-text p{margin:0 0 1.15em;text-indent:1.4em;}
.book-text p:first-child{text-indent:0;}
.book-text p:first-child::first-letter{
  font-family:var(--hand);font-size:2.7em;line-height:.75;
  float:left;padding:.05em .08em 0 0;color:var(--accent);
}
.book-text .empty-page{text-indent:0;color:var(--text-muted);font-style:italic;}

mark.target{
  background:transparent;color:inherit;padding:.02em .05em;border-radius:2px;
  cursor:pointer;box-shadow:inset 0 -.14em 0 0 var(--ink);
  transition:background-color .25s ease, box-shadow .25s ease;
}
mark.target:hover, mark.target.active{
  background-color:var(--ink-soft);
  box-shadow:inset 0 -.2em 0 0 var(--ink);
}
mark.target.filtered-out{box-shadow:none;background:transparent;opacity:.55;}

/* ---------- margin notes ---------- */
.note{
  position:absolute;left:0;right:0;
  font-family:var(--hand);font-weight:600;color:var(--ink);
  line-height:1.22;opacity:.5;cursor:pointer;
  transform:rotate(var(--tilt,0deg));
  transition:opacity .35s ease, transform .3s ease;
}
.margin-left .note{text-align:right;}
.margin-right .note{text-align:left;}
.note .glyph{font-family:var(--serif);font-size:.8em;opacity:.85;margin:0 .15em;}
.note .note-text{
  display:inline;
  clip-path:inset(0 100% 0 0);
  transition:clip-path 1.2s steps(28,end);
}
.note.revealed .note-text{clip-path:inset(0 0 0 0);}
.note.settled{animation:inkFade 7s ease-in-out infinite;animation-delay:var(--flicker-delay,0s);}
.note.active, .note:hover, .note:focus-within{
  opacity:1 !important;transform:rotate(0deg) scale(1.02);z-index:5;
  animation-play-state:paused;
}
.note.unmatched{opacity:.6;}
.note-flag{font-family:var(--serif);font-size:.62rem;font-style:italic;color:var(--text-muted);margin-top:.15rem;}
.note.filtered-out{opacity:.1 !important;pointer-events:none;}
@keyframes inkFade{0%,100%{opacity:.5;}50%{opacity:.8;}}

/* ---------- footer / nav ---------- */
.page-nav-footer{
  display:flex;align-items:center;justify-content:center;gap:1rem;
  padding:1.1rem 1rem 2rem;flex-wrap:wrap;color:var(--text-muted);font-size:.85rem;
}
#page-slider{accent-color:var(--accent);width:min(360px,60vw);}
.generated-stamp{font-family:var(--hand);opacity:.7;}

/* ---------- responsive: tablet and narrower ---------- */
@media (max-width: 1000px){
  .page-frame{grid-template-columns:1fr;max-width:640px;}
  .margin-left,.book-page,.margin-right{grid-column:1;grid-row:auto;}
  .connector-layer{display:none;}
  .margin{
    position:static;display:flex;flex-direction:column;gap:.9rem;
    padding:1.2rem 0 0;margin-top:1rem;border-top:1px dashed var(--rule);
  }
  .margin-left{border-top:none;}
  .margin-left .note,.margin-right .note{text-align:left;}
  .note{position:static !important;opacity:.9 !important;transform:none !important;}
  .book-page{padding:2.4rem 1.6rem 2rem;}
  .nav-btn{position:static;}
  .page-stage{padding:1.5rem 1rem;flex-wrap:wrap;}
  .site-header{padding:1rem;}
}
@media (max-width: 560px){
  .title-block h1{font-size:1.2rem;}
  .book-text{font-size:1rem;}
}

/* ---------- annotation editing controls ---------- */
.note-controls{
  display:flex;gap:.3em;margin-top:.35rem;
  opacity:0;transition:opacity .15s ease;
  justify-content:flex-end;
}
.note:hover .note-controls,
.note:focus-within .note-controls,
.note.active .note-controls{opacity:1;}
@media (max-width: 1000px){
  .note-controls{opacity:.75;}
}
.note-ctrl-btn{
  background:transparent;border:1px solid var(--ink);color:var(--ink);
  border-radius:3px;padding:.1em .3em;font-size:.62rem;cursor:pointer;
  line-height:1;font-family:var(--serif);
  transition:background-color .15s ease;
}
.note-ctrl-btn:hover{background:var(--ink-soft);}
.note-edit-area{
  width:100%;display:block;margin-top:.3rem;
  font-family:var(--hand);font-size:.88em;color:var(--ink);
  background:var(--bg-page);border:1px solid var(--ink);
  border-radius:3px;padding:.3em;resize:vertical;
  box-sizing:border-box;
}
.note-edit-row{display:flex;gap:.3em;margin-top:.25rem;justify-content:flex-end;}
.note-edit-save,.note-edit-cancel{
  background:transparent;border:1px solid var(--ink);color:var(--ink);
  border-radius:3px;padding:.15em .45em;font-size:.68rem;cursor:pointer;
  font-family:var(--serif);transition:background-color .15s ease;
}
.note-edit-save:hover,.note-edit-cancel:hover{background:var(--ink-soft);}
"""

_JS = r"""
(function () {
  "use strict";

  var DATA = window.__HB_DATA__ || { title: "", persona: "", pages: [], types: [] };
  var TYPE_META = {};
  (DATA.types || []).forEach(function (t) { TYPE_META[t.value] = t; });

  var els = {
    title: document.getElementById("book-title"),
    persona: document.getElementById("book-persona"),
    legend: document.getElementById("legend"),
    themeToggle: document.getElementById("theme-toggle"),
    copyJson: document.getElementById("copy-json"),
    prevBtn: document.getElementById("prev-btn"),
    nextBtn: document.getElementById("next-btn"),
    pageFrame: document.getElementById("page-frame"),
    marginLeft: document.getElementById("margin-left"),
    marginRight: document.getElementById("margin-right"),
    bookPage: document.getElementById("book-page"),
    bookText: document.getElementById("book-text"),
    pageBadge: document.getElementById("page-number-badge"),
    connectorLayer: document.getElementById("connector-layer"),
    slider: document.getElementById("page-slider"),
    indicator: document.getElementById("page-indicator"),
    stamp: document.getElementById("generated-stamp"),
    noteSearch: document.getElementById("note-search"),
    searchCount: document.getElementById("search-count"),
  };

  var state = {
    idx: 0,
    hiddenTypes: new Set(),
    hoveredId: null,
    lockedIds: new Set(),
    leftItems: [],
    rightItems: [],
    revealTimers: [],
    query: null,
    editingId: null,
  };

  function escapeHtml(s) {
    var div = document.createElement("div");
    div.textContent = s == null ? "" : String(s);
    return div.innerHTML;
  }

  function hashCode(s) {
    var h = 0;
    for (var i = 0; i < s.length; i++) {
      h = (h << 5) - h + s.charCodeAt(i);
      h |= 0;
    }
    return Math.abs(h);
  }

  function debounce(fn, ms) {
    var t = null;
    return function () {
      var args = arguments;
      clearTimeout(t);
      t = setTimeout(function () { fn.apply(null, args); }, ms);
    };
  }

  // ---------------- theme ----------------

  function applyTheme(theme) {
    document.documentElement.setAttribute("data-theme", theme);
    els.themeToggle.innerHTML = theme === "dark" ? "&#9728; Light" : "&#127769; Dark";
  }

  els.themeToggle.addEventListener("click", function () {
    var current = document.documentElement.getAttribute("data-theme");
    var next = current === "dark" ? "parchment" : "dark";
    applyTheme(next);
    try { localStorage.setItem("hb-theme", next); } catch (e) { /* ignore */ }
    requestAnimationFrame(doLayout);
  });

  // ---------------- copy JSON ----------------
  // A preview is normally opened over file://, which is NOT a secure context in
  // Chrome, so navigator.clipboard is frequently undefined exactly where this
  // button gets used. Feature-detect it and fall back to a hidden textarea, and
  // always report the outcome -- a silent copy is indistinguishable from a
  // broken button.

  function flashCopyLabel(message) {
    var original = "&#128203; Copy JSON";
    els.copyJson.innerHTML = message;
    setTimeout(function () { els.copyJson.innerHTML = original; }, 1600);
  }

  function legacyCopy(text) {
    var scratch = document.createElement("textarea");
    scratch.value = text;
    // Keep it off-screen but focusable; display:none would not be selectable.
    scratch.setAttribute("readonly", "");
    scratch.style.position = "absolute";
    scratch.style.left = "-9999px";
    document.body.appendChild(scratch);
    scratch.select();
    var ok = false;
    try { ok = document.execCommand("copy"); } catch (e) { ok = false; }
    document.body.removeChild(scratch);
    return ok;
  }

  els.copyJson.addEventListener("click", function () {
    var text = JSON.stringify(DATA, null, 2);
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(
        function () { flashCopyLabel("&#10003; Copied"); },
        function () {
          flashCopyLabel(legacyCopy(text) ? "&#10003; Copied" : "Copy failed");
        }
      );
      return;
    }
    flashCopyLabel(legacyCopy(text) ? "&#10003; Copied" : "Copy failed");
  });

  // ---------------- search ----------------
  // Count is whole-book (useful for "where did the Prince mention bezoars?");
  // filtering is per-current-page (handled inside applyFilters).

  if (els.noteSearch) {
    els.noteSearch.addEventListener("input", function (e) {
      var q = e.target.value.trim();
      state.query = q || null;
      if (state.query && els.searchCount) {
        var ql = state.query.toLowerCase();
        var n = 0;
        (DATA.pages || []).forEach(function (page) {
          (page.annotations || []).forEach(function (ann) {
            if (ann.content && ann.content.toLowerCase().indexOf(ql) !== -1) n++;
          });
        });
        // "in book", not just "N results": filtering below is per-page (only the
        // current page's DOM is live), so a bare count reads as "N on this page"
        // and looks broken when the page shows fewer.
        els.searchCount.textContent =
          n === 1 ? "1 match in book" : n + " matches in book";
      } else if (els.searchCount) {
        els.searchCount.textContent = "";
      }
      applyFilters();
    });
  }

  // ---------------- legend / filtering ----------------

  function buildLegend() {
    els.legend.innerHTML = "";
    (DATA.types || []).forEach(function (t) {
      var btn = document.createElement("button");
      btn.type = "button";
      btn.className = "legend-chip type-" + t.value;
      btn.dataset.type = t.value;
      btn.innerHTML = '<span class="glyph">' + t.glyph + "</span>" + escapeHtml(t.label);
      btn.addEventListener("click", function () {
        if (state.hiddenTypes.has(t.value)) {
          state.hiddenTypes.delete(t.value);
        } else {
          state.hiddenTypes.add(t.value);
        }
        btn.classList.toggle("off", state.hiddenTypes.has(t.value));
        applyFilters();
      });
      els.legend.appendChild(btn);
    });
  }

  function applyFilters() {
    // Build a per-page match set so IDs (which are page-local, e.g. "a0")
    // don't collide across pages — only the current page's DOM is live.
    var matchIds = null;
    if (state.query) {
      var q = state.query.toLowerCase();
      var pg = (DATA.pages || [])[state.idx];
      matchIds = new Set();
      ((pg && pg.annotations) || []).forEach(function (ann) {
        if (ann.content && ann.content.toLowerCase().indexOf(q) !== -1) {
          matchIds.add(ann.id);
        }
      });
    }
    document.querySelectorAll("[data-type]").forEach(function (el) {
      if (el.classList.contains("legend-chip")) return;
      var typeHidden = state.hiddenTypes.has(el.dataset.type);
      var searchHidden = matchIds !== null && !matchIds.has(el.dataset.annId);
      el.classList.toggle("filtered-out", typeHidden || searchHidden);
    });
  }

  // ---------------- hover / lock (active) state ----------------

  function refreshActive(id) {
    var isActive = state.hoveredId === id || state.lockedIds.has(id);
    document.querySelectorAll('[data-ann-id="' + cssEscape(id) + '"]').forEach(function (el) {
      el.classList.toggle("active", isActive);
      if (isActive) el.classList.add("revealed");
    });
  }

  function cssEscape(id) {
    return window.CSS && CSS.escape ? CSS.escape(id) : id;
  }

  function bindHover(el, id) {
    el.addEventListener("mouseenter", function () {
      state.hoveredId = id;
      refreshActive(id);
    });
    el.addEventListener("mouseleave", function () {
      if (state.hoveredId === id) state.hoveredId = null;
      refreshActive(id);
    });
    el.addEventListener("click", function (e) {
      e.stopPropagation();
      if (state.lockedIds.has(id)) {
        state.lockedIds.delete(id);
      } else {
        state.lockedIds.add(id);
      }
      refreshActive(id);
    });
  }

  document.addEventListener("click", function () {
    if (state.lockedIds.size) {
      var ids = Array.from(state.lockedIds);
      state.lockedIds.clear();
      ids.forEach(refreshActive);
    }
  });

  // ---------------- note construction ----------------

  function buildNote(ann) {
    var el = document.createElement("div");
    el.className = "note type-" + ann.type + (ann.matched ? "" : " unmatched");
    el.dataset.annId = ann.id;
    el.dataset.type = ann.type;

    var tilt = (hashCode(ann.id) % 5) - 2;
    el.style.setProperty("--tilt", tilt + "deg");
    var flicker = -((hashCode(ann.id + "x") % 500) / 100);
    el.style.setProperty("--flicker-delay", flicker + "s");

    var conf = Math.max(0, Math.min(1, ann.confidence == null ? 0.8 : ann.confidence));
    el.style.fontSize = (1.0 + conf * 0.3).toFixed(2) + "rem";

    var meta = TYPE_META[ann.type] || { glyph: "" };
    el.innerHTML =
      '<span class="glyph">' + (meta.glyph || "") + "</span>" +
      '<span class="note-text">' + escapeHtml(ann.content) + "</span>";

    if (!ann.matched) {
      var flag = document.createElement("div");
      flag.className = "note-flag";
      flag.textContent = "(couldn't anchor to page text)";
      el.appendChild(flag);
    }

    // --- inline editing controls (edit / reposition / delete) ---
    var controls = document.createElement("div");
    controls.className = "note-controls";

    var editBtn = document.createElement("button");
    editBtn.type = "button";
    editBtn.className = "note-ctrl-btn note-ctrl-edit";
    editBtn.setAttribute("aria-label", "Edit annotation");
    editBtn.textContent = "✎";
    editBtn.addEventListener("click", function (e) {
      e.stopPropagation();
      startEdit(ann.id);
    });

    var sideBtn = document.createElement("button");
    sideBtn.type = "button";
    sideBtn.className = "note-ctrl-btn note-ctrl-side";
    sideBtn.setAttribute("aria-label", "Move to other margin");
    sideBtn.textContent = "⇄";
    sideBtn.addEventListener("click", function (e) {
      e.stopPropagation();
      repositionAnnotation(ann.id);
    });

    var delBtn = document.createElement("button");
    delBtn.type = "button";
    delBtn.className = "note-ctrl-btn note-ctrl-delete";
    delBtn.setAttribute("aria-label", "Delete annotation");
    delBtn.textContent = "✕";
    delBtn.addEventListener("click", function (e) {
      e.stopPropagation();
      deleteAnnotation(ann.id);
    });

    controls.appendChild(editBtn);
    controls.appendChild(sideBtn);
    controls.appendChild(delBtn);
    el.appendChild(controls);

    bindHover(el, ann.id);
    return el;
  }

  // ---------------- page rendering ----------------

  function renderPage(index) {
    var pages = DATA.pages || [];
    if (!pages.length) return;
    index = Math.max(0, Math.min(pages.length - 1, index));
    state.idx = index;

    state.revealTimers.forEach(clearTimeout);
    state.revealTimers = [];
    state.editingId = null; // cancel any in-progress edit when the page changes

    var page = pages[index];

    els.bookText.innerHTML = page.html || "";
    els.pageBadge.textContent = "Page " + page.number;
    els.marginLeft.innerHTML = "";
    els.marginRight.innerHTML = "";
    els.connectorLayer.innerHTML = "";

    els.bookPage.classList.remove("entering");
    void els.bookPage.offsetWidth; // restart animation
    els.bookPage.classList.add("entering");

    var leftItems = [];
    var rightItems = [];
    (page.annotations || []).forEach(function (ann) {
      var el = buildNote(ann);
      if (ann.position === "margin_left") {
        els.marginLeft.appendChild(el);
        leftItems.push({ ann: ann, el: el });
      } else {
        els.marginRight.appendChild(el);
        rightItems.push({ ann: ann, el: el });
      }
    });
    state.leftItems = leftItems;
    state.rightItems = rightItems;

    // wire up hover on the marks now living in the freshly-rendered text
    els.bookText.querySelectorAll("mark.target").forEach(function (mark) {
      bindHover(mark, mark.dataset.annId);
    });

    els.slider.max = String(pages.length);
    els.slider.value = String(index + 1);
    var count = (page.annotations || []).length;
    els.indicator.textContent =
      "Page " + (index + 1) + " of " + pages.length + " · " +
      count + " note" + (count === 1 ? "" : "s");
    els.prevBtn.disabled = index === 0;
    els.nextBtn.disabled = index === pages.length - 1;

    applyFilters();
    requestAnimationFrame(function () {
      doLayout();
      scheduleReveal(page.annotations || []);
    });
  }

  function scheduleReveal(annotations) {
    annotations.forEach(function (ann, i) {
      var delay = 450 + i * 360 + Math.random() * 200;
      var t = setTimeout(function () {
        var el = els.bookText.parentElement.querySelector
          ? document.querySelector('.note[data-ann-id="' + cssEscape(ann.id) + '"]')
          : null;
        if (!el) return;
        el.classList.add("revealed");
        var textEl = el.querySelector(".note-text");
        if (!textEl) return;
        var settle = function () {
          el.classList.add("settled");
          textEl.removeEventListener("transitionend", settle);
        };
        textEl.addEventListener("transitionend", settle);
      }, delay);
      state.revealTimers.push(t);
    });
  }

  // ---------------- margin layout + connectors ----------------

  function layoutMargin(items, side) {
    if (!items.length) return;
    var marginEl = side === "left" ? els.marginLeft : els.marginRight;
    var marginRect = marginEl.getBoundingClientRect();
    var minGap = 14;

    var withTop = items.map(function (item) {
      var mark = item.ann.matched
        ? els.bookText.querySelector('mark.target[data-ann-id="' + cssEscape(item.ann.id) + '"]')
        : null;
      var top = null;
      if (mark) {
        var r = mark.getBoundingClientRect();
        top = r.top - marginRect.top + r.height / 2 - item.el.offsetHeight / 2;
      }
      return { item: item, top: top, mark: mark };
    });

    var anchored = withTop.filter(function (w) { return w.top !== null; })
      .sort(function (a, b) { return a.top - b.top; });
    var unanchored = withTop.filter(function (w) { return w.top === null; });

    var cursor = 0;
    anchored.forEach(function (w) {
      var top = Math.max(w.top, cursor, 0);
      w.item.el.style.top = top + "px";
      cursor = top + w.item.el.offsetHeight + minGap;
    });
    unanchored.forEach(function (w) {
      var top = Math.max(cursor, 0);
      w.item.el.style.top = top + "px";
      cursor = top + w.item.el.offsetHeight + minGap;
    });

    drawConnectors(anchored, side);
  }

  function drawConnectors(anchoredItems, side) {
    var frameRect = els.pageFrame.getBoundingClientRect();
    anchoredItems.forEach(function (w) {
      var mark = w.mark;
      if (!mark) return;
      var markRect = mark.getBoundingClientRect();
      var noteRect = w.item.el.getBoundingClientRect();

      var toX = (side === "left" ? markRect.left : markRect.right) - frameRect.left;
      var toY = markRect.top - frameRect.top + markRect.height / 2;
      var fromX = (side === "left" ? noteRect.right : noteRect.left) - frameRect.left;
      var fromY = noteRect.top - frameRect.top + Math.min(noteRect.height, 22) / 2;
      var midX = (fromX + toX) / 2;
      var bow = side === "left" ? -8 : 8;
      var midY = (fromY + toY) / 2 + bow;

      var path = document.createElementNS("http://www.w3.org/2000/svg", "path");
      path.setAttribute("d", "M " + fromX + " " + fromY + " Q " + midX + " " + midY + " " + toX + " " + toY);
      path.setAttribute("class", "connector type-" + w.item.ann.type);
      path.dataset.annId = w.item.ann.id;
      path.dataset.type = w.item.ann.type;
      els.connectorLayer.appendChild(path);

      try {
        var len = path.getTotalLength();
        path.style.strokeDasharray = String(len);
        path.style.strokeDashoffset = String(len);
        requestAnimationFrame(function () {
          path.style.transition = "stroke-dashoffset 1.1s ease";
          path.style.strokeDashoffset = "0";
        });
      } catch (e) { /* getTotalLength unsupported; skip draw-in */ }

      bindHover(path, w.item.ann.id);
    });
  }

  function doLayout() {
    els.connectorLayer.innerHTML = "";
    layoutMargin(state.leftItems, "left");
    layoutMargin(state.rightItems, "right");
    applyFilters();
  }

  // ---------------- annotation editing ----------------

  function deleteAnnotation(annId) {
    var page = DATA.pages[state.idx];
    if (!page) return;
    var annIdx = -1;
    var i;
    for (i = 0; i < page.annotations.length; i++) {
      if (page.annotations[i].id === annId) { annIdx = i; break; }
    }
    if (annIdx === -1) return;
    var wasMatched = !!page.annotations[annIdx].matched;
    // Close any in-progress edit for this annotation to unblock startEdit
    // on other notes — if we don't clear editingId here the guard in
    // startEdit would treat every subsequent note as "already editing".
    if (state.editingId === annId) state.editingId = null;
    page.annotations.splice(annIdx, 1);

    // Unwrap the <mark> in the book text and snapshot the updated HTML so
    // navigating away and back doesn't re-show the deleted mark.
    var mark = els.bookText.querySelector('mark[data-ann-id="' + annId + '"]');
    if (mark) {
      mark.replaceWith(document.createTextNode(mark.textContent));
      DATA.pages[state.idx].html = els.bookText.innerHTML;
    }

    // Remove note element from its margin
    var noteEl = document.querySelector('.note[data-ann-id="' + cssEscape(annId) + '"]');
    if (noteEl) noteEl.remove();

    // Remove connector path
    var conn = els.connectorLayer.querySelector('[data-ann-id="' + annId + '"]');
    if (conn) conn.remove();

    // Remove from state items so doLayout doesn't try to position it
    state.leftItems = state.leftItems.filter(function (it) { return it.ann.id !== annId; });
    state.rightItems = state.rightItems.filter(function (it) { return it.ann.id !== annId; });

    // Re-run layout so remaining notes reflow
    requestAnimationFrame(doLayout);

    // Update page indicator count
    var count = page.annotations.length;
    els.indicator.textContent =
      "Page " + (state.idx + 1) + " of " + DATA.pages.length + " \xb7 " +
      count + " note" + (count === 1 ? "" : "s");
    DATA.totals.annotations = Math.max(0, (DATA.totals.annotations || 0) - 1);
    if (wasMatched) DATA.totals.matched = Math.max(0, (DATA.totals.matched || 0) - 1);
  }

  function repositionAnnotation(annId) {
    var page = DATA.pages[state.idx];
    if (!page) return;
    var ann = null;
    var i;
    for (i = 0; i < page.annotations.length; i++) {
      if (page.annotations[i].id === annId) { ann = page.annotations[i]; break; }
    }
    if (!ann) return;

    var newPos = ann.position === "margin_left" ? "margin_right" : "margin_left";
    ann.position = newPos;

    var noteEl = document.querySelector('.note[data-ann-id="' + cssEscape(annId) + '"]');
    if (noteEl) {
      var targetMargin = newPos === "margin_left" ? els.marginLeft : els.marginRight;
      targetMargin.appendChild(noteEl);

      // Move the item between leftItems / rightItems so doLayout redraws connectors
      // on the correct side.
      var movedItem = null;
      state.leftItems = state.leftItems.filter(function (it) {
        if (it.ann.id === annId) { movedItem = it; return false; }
        return true;
      });
      state.rightItems = state.rightItems.filter(function (it) {
        if (it.ann.id === annId) { if (!movedItem) { movedItem = it; } return false; }
        return true;
      });
      if (movedItem) {
        if (newPos === "margin_left") {
          state.leftItems.push(movedItem);
        } else {
          state.rightItems.push(movedItem);
        }
      }
    }

    requestAnimationFrame(doLayout);
  }

  function startEdit(annId) {
    // Prevent opening a second edit panel while one is already open.
    if (state.editingId !== null) return;
    var page = DATA.pages[state.idx];
    if (!page) return;
    var ann = null;
    var i;
    for (i = 0; i < page.annotations.length; i++) {
      if (page.annotations[i].id === annId) { ann = page.annotations[i]; break; }
    }
    if (!ann) return;

    var noteEl = document.querySelector('.note[data-ann-id="' + cssEscape(annId) + '"]');
    if (!noteEl) return;
    var noteText = noteEl.querySelector(".note-text");
    if (!noteText) return;

    state.editingId = annId;
    noteText.style.display = "none";

    // Use createElement + textContent/value throughout — never innerHTML with
    // user-supplied content.
    var ta = document.createElement("textarea");
    ta.className = "note-edit-area";
    ta.value = ann.content;
    ta.rows = 3;
    noteEl.appendChild(ta);

    var row = document.createElement("div");
    row.className = "note-edit-row";

    var saveBtn = document.createElement("button");
    saveBtn.type = "button";
    saveBtn.className = "note-edit-save";
    saveBtn.textContent = "✓ Save";

    var cancelBtn = document.createElement("button");
    cancelBtn.type = "button";
    cancelBtn.className = "note-edit-cancel";
    cancelBtn.textContent = "Cancel";

    row.appendChild(saveBtn);
    row.appendChild(cancelBtn);
    noteEl.appendChild(row);

    if (ta.focus) ta.focus();

    function closeEdit() {
      noteEl.removeChild(ta);
      noteEl.removeChild(row);
      noteText.style.display = "";
      state.editingId = null;
    }

    saveBtn.addEventListener("click", function (e) {
      e.stopPropagation();
      var newContent = ta.value.trim();
      if (newContent) {
        ann.content = newContent;
        // Use textContent (not innerHTML) — handles all special characters safely.
        noteText.textContent = newContent;
      }
      closeEdit();
    });

    cancelBtn.addEventListener("click", function (e) {
      e.stopPropagation();
      closeEdit();
    });
  }

  // ---------------- navigation ----------------

  els.prevBtn.addEventListener("click", function () { renderPage(state.idx - 1); });
  els.nextBtn.addEventListener("click", function () { renderPage(state.idx + 1); });
  els.slider.addEventListener("input", function (e) {
    renderPage(parseInt(e.target.value, 10) - 1);
  });
  document.addEventListener("keydown", function (e) {
    if (e.target && (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA")) return;
    if (e.key === "ArrowLeft") renderPage(state.idx - 1);
    if (e.key === "ArrowRight") renderPage(state.idx + 1);
  });
  window.addEventListener("resize", debounce(doLayout, 150));

  // ---------------- init ----------------

  function init() {
    els.title.textContent = DATA.title || "Untitled";
    if (DATA.persona) {
      els.persona.textContent = '"' + DATA.persona + '"';
      els.persona.title = DATA.persona;
    }
    if (DATA.generated) {
      els.stamp.textContent = "rendered " + DATA.generated;
    }

    var savedTheme = "parchment";
    try { savedTheme = localStorage.getItem("hb-theme") || "parchment"; } catch (e) { /* ignore */ }
    applyTheme(savedTheme);

    buildLegend();

    if (!DATA.pages || !DATA.pages.length) {
      els.bookText.innerHTML = "<p><em>No pages to preview.</em></p>";
      els.prevBtn.disabled = true;
      els.nextBtn.disabled = true;
      els.slider.disabled = true;
      els.indicator.textContent = "No pages";
      return;
    }

    renderPage(0);
  }

  init();
})();
"""
