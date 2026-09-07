# Real-book corpus

`elements-of-style.epub` — *The Elements of Style*, William Strunk Jr., 1918.
Project Gutenberg ebook #37134, https://www.gutenberg.org/ebooks/37134. Public domain.
Downloaded 2026-09-07.

Why this book: it is a genuine methods book, so "how to do better at the method it teaches"
has real material, and its main document is 83,063 characters — above the 50,000-character
`MAX_INPUT_CHARS` bound that no fixture in this repository exceeds.

`plan-snape.json`, `plan-editor.json` — frozen annotation plans generated 2026-09-07 against
`anthropic/claude-sonnet-5` via OpenRouter, `--max-per-page 8`, default persona and
`--persona-name editor`. Frozen so placement can be measured deterministically with no model
call, no network, and no API key.

See `docs/evidence/2026-09-07-real-book-placement-failure.md`.
