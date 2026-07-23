# EPUB reader lab (advisory only)

These tiny, deterministic books exercise the production `EpubProcessor.render_plan` path. Sideload both artifacts into real readers to inspect behavior the offline test suite cannot establish: popup activation, conversion rewriting, pagination and fragmentation, user-style overrides, and painted overlap.

Results are **ADVISORY**. Record findings in the project ledger; they never become merge gates.

## Artifact shapes

- `reader_lab_epub3.epub` is an EPUB 3 package with a navigation document. Notes are linked semantic `<aside epub:type="footnote">` elements.
- `reader_lab_epub2.epub` is an EPUB 2 package with an NCX and no EPUB 3 navigation document. Notes use the linked `<div class="hbp-note">` fallback and contain no `epub:type` attributes.

Both books have the same four reading chapters:

| Chapter | Reader-lab feature |
| --- | --- |
| 1 — Marks and Single Notes | One-note blocks; UNDERLINE, CIRCLE, STRIKE, HIGHLIGHT, CARET, and NONE intents; INVENTION and WARNING styling; a real-DOM `‸` caret; a visual mark-only CARET probe; and the production NONE note-only behavior. |
| 2 — Three-Note Cluster | Three targets in one paragraph and one cluster. Notes must remain in numbered plan order: “First,” “Second,” “Third.” |
| 3 — Dense Eight-Note Block | Eight targets in one paragraph, the NL3 `hbp-note-cluster-dense` block fallback, a pre-existing source float, and a long unbreakable token in both prose and the eighth WARNING note. |
| 4 — Cross-Node Target | One CARET selector crossing `<em>` and `<strong>` nodes; every target fragment is marked and only the final fragment owns the real-DOM caret glyph. |

`MarkIntent.NONE` is note-only in the production renderer: it emits a linked note without a target mark. EPUB never reports `marks_only`. To retain the requested visual mark-only reader probe without falsifying that contract, `lab-mark-only-caret` uses a CARET mark and a U+2060 WORD JOINER as its nonprinting plan body. Its linked note container/backlink may exist, but no commentary body should paint.

## Per-reader checklist

Use narrow and wide windows where the reader permits resizing, and repeat once with a substantially larger user font. Put short observations (including reader/version and conversion path) in the ledger.

| Reader | Popup or inline aside/div | Real-DOM `‸` caret visible | Floats engage only at width | Dense block falls back readably | Visual mark-only CARET paints, no body | No unreadable overlap |
| --- | --- | --- | --- | --- | --- | --- |
| Apple Books | ☐ popup ☐ inline | ☐ | ☐ | ☐ | ☐ | ☐ |
| Kindle Previewer | ☐ popup ☐ inline | ☐ | ☐ | ☐ | ☐ | ☐ |
| Kobo | ☐ popup ☐ inline | ☐ | ☐ | ☐ | ☐ | ☐ |
| Calibre | ☐ popup ☐ inline | ☐ | ☐ | ☐ | ☐ | ☐ |

Also verify that the Chapter 2 note order survives, the Chapter 3 token wraps instead of widening the page, the NONE probe displays its note with no painted target, backlinks work, and nothing disappears under reader themes. These observations remain supplementary and advisory, never merge gates.
