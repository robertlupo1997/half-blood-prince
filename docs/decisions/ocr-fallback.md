---
title: "OCR fallback for page-image scans"
type: decision-record
status: ACCEPTED
date_opened: 2026-07-27
decided_on: 2026-07-27
covers: [scanned input, dependencies, anchor quality, CLI error surface]
---

# OCR fallback for page-image scans

## Status: ACCEPTED — do NOT bundle OCR. Keep diagnosing and hand the user the command.

## The question

A PDF that is a scan of page images with no OCR text layer has nothing the annotator can read.
Since `2bc6f2c` this is *diagnosed* rather than silently reported as "0 annotations": the CLI
exits non-zero and names `ocrmypdf` as the next step
(`src/halfblood/cli.py:304-331`, `_require_text_layer`).

The open question was whether the tool should OCR such files *itself* behind a flag
(`--ocr`, shelling out to `ocrmypdf`/Tesseract) instead of telling the user to.

## Decision

Keep the current behavior. `halfblood` does not perform OCR.

## Why

### 1. The dependency is heavy, non-Python, and not installable by `pip` alone

`ocrmypdf` is pip-installable but is a front-end to system binaries — the Tesseract OCR engine
and Ghostscript, plus optional `jbig2enc`/`pngquant`/`unpaper`. Those are OS packages, not
wheels. Declaring an `ocr` extra would therefore produce an extra that installs cleanly and then
fails at runtime on any machine lacking the binaries, which is a worse failure than the current
honest refusal. Confirmed on this development machine: `gs` is present, `tesseract` and
`ocrmypdf` are not — a perfectly ordinary state for a Python developer's box.

The project's dependency policy is deliberately conservative (`docs/decisions/tech-stack-validation.md`:
intentional upper bounds, majors excluded until reviewed). A system-binary toolchain is a large
step outside it, taken for an input class the tool already handles gracefully.

### 2. Owning the OCR means owning the anchor quality it destroys — and we now know the size of that effect

This is the decisive argument, and it is measured rather than asserted.

OCR text quality directly determines how many annotations can be anchored, because the model
silently repairs OCR damage while quoting: handed `tlie sight of a pol` it writes
`the sight of a policeman`. The quote is faithful to the text as a human reads it and unfaithful
to the bytes, so the *complete* quote stops matching.

Measured over 88 real annotations on 20 pages of the Internet Archive's OCR'd scan of
Jekyll & Hyde — a **good** OCR layer produced by a well-tuned pipeline:

| | matched |
|---|---|
| complete quote (tier 0) | **53 of 88** (60%) |
| after prefix-tier recovery | 84 of 88 (95%) |

Even a good OCR layer costs 40% of complete-quote matches. A text layer we generated ourselves
with default Tesseract settings would be *worse* than the Internet Archive's, and every point of
additional OCR noise converts directly into annotations that anchor to a prefix instead of the
full passage, or drop out entirely. We would be shipping a flag whose predictable outcome is a
visibly degraded annotation experience, and we would own the blame for it.

Letting the user run OCR keeps that quality decision — engine, language, `--deskew`,
`--clean`, DPI — where it belongs: with the person who can see the source and judge the result.
`ocrmypdf` exposes those knobs properly; a `--ocr` passthrough would either hide them or
re-export them, at which point we are maintaining a wrapper around someone else's CLI.

### 3. It is not this tool's job

The product is "annotate a book in the margins." OCR is a separate, well-solved problem with a
mature dedicated tool. A one-line, copy-pasteable instruction pointed at that tool is a better
answer than a subprocess we have to supervise, whose runtime on a 150-page scan is minutes, and
whose failure modes (missing binary, wrong language pack, encrypted PDF, out-of-disk on the
intermediate file) all become our error surface.

### 4. The current behavior is already the good version of "no"

The failure is specific, names the cause, and gives the exact next command. The condition is
"not one readable character anywhere in the selection" rather than a guessed per-page threshold,
so it cannot misfire on a legitimately thin page — a title page, a part-divider, a page holding
one line of verse. It is also empirically sufficient: on the Internet Archive's Google scan of
Jekyll & Hyde exactly 1 of 171 pages carried any text, and that one was the scanner's own
front-matter notice (`src/halfblood/cli.py:304-320`).

## What would change this decision

- OCR becoming available as a pure-Python wheel with no system binaries and quality comparable
  to Tesseract.
- Evidence that users are commonly blocked here. Right now the diagnostic is one release old and
  there is no usage signal at all; adding a heavyweight dependency ahead of that signal is
  speculative.

## Consequences

- Scanned page-image PDFs remain out of scope for v0.1.0, by design and with a clear message.
- Scanned books that *do* carry an OCR layer are supported and measured: the anchor rules hold at
  84/88 on a real scan, and `PdfAlignmentError` fired 0 of 156 times on it.
- No new runtime dependency; the `pip install` story stays "one command, pure wheels."

## See also

- `docs/decisions/verbatim-quoting-prompt-vs-matcher.md` — why a wrong anchor is worse than no
  annotation, and the prefix-tier rule that recovers OCR-damaged quotes.
- `src/halfblood/document_processor.py:178` (`_is_lone_word_anchor`) — the structural rule that
  survived this scanned corpus where a tuned coverage constant did not.
