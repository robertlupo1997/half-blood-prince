# Persona library

Ready-made annotator voices for `--persona-file`:

```bash
halfblood annotate book.epub -o annotated.epub --persona-file personas/philosopher.txt
```

| file | voice |
|---|---|
| `chemist.txt` | An 1890s industrial chemist. Practical, quantitative, has been burned before. |
| `philosopher.txt` | Argues with the author's unexamined premises. Dry, precise about language. |
| `editor.txt` | An old-school line editor. Performs the cut rather than describing it. |
| `detective.txt` | Reads narrative as testimony. Hunts inconsistency and the unnoticed detail. |

The built-in default (no flag) is the Half-Blood Prince — a young Severus Snape
annotating his Potions textbook.

> **These files live in the repository, not in the installed package.** `pyproject.toml`
> ships only `src/halfblood`, so the paths above work from a git checkout. If you
> installed via `pip`, copy a persona out of the repo (or write your own) and point
> `--persona-file` at it. Packaging the library and adding a `--persona-name` shortcut —
> mirroring how `--font` resolves registered names against a bundled directory — is a
> tracked follow-up.

## Writing your own

**Describe a voice, nothing else.** A persona file supplies the annotator's identity
and temperament. It does *not* need to explain what the eight annotation types mean or
how to anchor a note — that scaffolding lives in `ANNOTATION_CRAFT`
(`src/halfblood/annotation_generator.py`) and is appended to every persona
automatically. Restating it here would only mean your file goes stale the next time the
type list changes.

What earns its place in a persona file:

- **Who is holding the pencil, and why they are annotating this at all.** The default
  persona works because Snape has a motive: he has already surpassed the book.
- **Specific temperament, not adjectives.** "Impatient with theory that has never been
  tested" produces better notes than "grumpy".
- **A range.** Every persona above has at least one line describing when it drops its
  usual register — the chemist when something is genuinely dangerous, the detective when
  a detail is well observed. Notes that are all one note get tiring across 300 pages.
- **Terseness.** These are marginalia scrawled in a real book, not essays.

A blank or whitespace-only file falls back to the default persona rather than producing
a voiceless prompt.
