# Real-model showcase: review of the notes

Two public-domain books, generated 2026-10-22 with `--provider claude-cli`
(the Claude Code CLI on a Claude subscription, CLI model alias `opus`), default
Half-Blood Prince persona. Read line by line against the source text by the
agent that produced them. **That is a self-review, not an independent judgement:
gate G5 (a frontier quality score) is still open.**

## Files

| file | what it is |
|---|---|
| `alice.plan.json` | the generated annotation plan, *Alice's Adventures in Wonderland*, pages 1–12 of `examples/src/alice.pdf` |
| `alice.plan.json.report.json` | generation report for that plan |
| `alice-annotated.pdf`, `.report.json` | rendered from the plan with `--resume-from` (no second model call) |
| `alice-page-02.png`, `-06.png`, `-12.png` | 150 dpi renders of three annotated pages |
| `elements-of-style.plan.json`, `.report.json` | the plan for the one 82,383-character chapter of `tests/corpora/real/elements-of-style.epub` |
| `elements-of-style-annotated.epub`, `.report.json` | rendered from that plan |
| `elements-of-style-lecky.png` | one page of the annotated EPUB as drawn by MuPDF's EPUB engine (reader styling differs) |

Reproduce:

```bash
halfblood annotate examples/src/alice.pdf -o alice.plan.json --pages 1-12 --provider claude-cli --dry-run
halfblood annotate examples/src/alice.pdf -o alice-annotated.pdf --pages 1-12 --provider claude-cli --resume-from alice.plan.json
halfblood annotate tests/corpora/real/elements-of-style.epub -o eos.plan.json --pages 2 --provider claude-cli --dry-run
```

Model output is not reproducible byte for byte.

## Counts

| run | generated | rendered | skipped | tokens in / out | generation time |
|---|---|---|---|---|---|
| Alice, PDF pages 1–12 | 60 | 60 | 0 | 92,296 / 13,452 | 1m08 |
| Elements of Style, one chapter (7 windows of ≤12,000 chars) | 35 | 35 | 0 | 72,756 / 14,766 | 2m44 |

Every quote resolved to exactly one place: no `ambiguous_target`, no
`missing_target`. The PDF render reports 2 `connector_routing_fallback`
degradations and 8 layout warnings (6 `shifted`, 2 `side_switched`).

## What changed before these were generated

A first run with the prompt as it stood (same books, same counts: 60/60 and
35/35 placed) produced notes that were well placed and often badly aimed:

- **The persona told the model it was annotating a Potions textbook**, so it
  treated *Alice* and a style manual as one. More than a dozen notes drifted into the
  wizarding world — a spell to open the doors, a house joke, a complaint that
  "someone has rebound my copy", cauldron advice in a grammar book. All eight
  craft examples were potion recipes, one of them a named curse.
- **Claims the page did not support.** "She ate a little bit … then she throws
  it away" — she finishes the cake.
- **The same note, page after page.** "Test the dose" in five forms across pages
  4–6, plus bare "Idiot." / "Useless." doodles that would fit any page.
- **`crossed_out` struck the wrong words**: the quote was "So she set to work,
  and very soon" while the note struck "finished off the cake".

The default persona and the shared craft text were rewritten
(`src/halfblood/annotation_generator.py`): the Prince now annotates whatever
book is in front of him and is told to leave his own world out of it; the
examples are subject-neutral; new rules require accuracy ("a confident
correction that is itself wrong is the worst note you can write"), forbid
restating the passage, forbid repeating a point, define the `crossed_out`
quote as exactly the struck words, and ask for quotes of four to twelve words.
After the change: zero wizarding-world references in 95 notes.

## The five best

1. *Elements of Style*, on **"the pronominal possessives hers, its, theirs,
   yours, and oneself have no apostrophe"** — *"'Oneself' is reflexive, not
   possessive. The possessive is 'one's', and it HAS an apostrophe. Wrong word,
   wrong rule."* A real error in the 1918 text.
2. *Elements of Style*, on Strunk's model paragraph from Lecky, **"the conditions
   on which the welfare of society mainly depend"** — *"'Depends.' The subject is
   'welfare,' not 'conditions.' A style manual quoting a plural verb as a model.
   Splendid."* Correct: the relative clause's subject is "welfare".
3. *Elements of Style*, on **"But in any sentence in which it is a mere clumsy
   substitute … should of course be recast"** — *"The sentence has no subject.
   '...should of course be recast' — what should? … He breaks his own grammar
   while lecturing on it."* Correct; the main clause has no subject.
4. *Alice*, p. 2, on **"she did not like to drop the jar for fear of killing
   somebody"** — *"Wasted courtesy. Let go and the jar falls beside her at her
   speed. It can only hit anyone below if she does too."* Sound physics, in voice.
5. *Alice*, p. 12, on **"'I thought you did,' said the Mouse."** — *"A line is
   missing. Nobody answered 'Did you speak?' The Lory's denial ('Not I!') has
   dropped out, so the Mouse is replying to no one."* **Correct, and it found a
   defect in this repository**: `scripts/build_example_book.py` drops every
   paragraph shorter than 40 characters, which deletes short dialogue lines
   ("Not I!" said the Lory hastily. / "Found *what*?" said the Duck.) from
   `examples/src/alice.pdf`. The next note on that page catches the second one.
   The source PDF was left as is for now: rebuilding it would change the
   committed stub examples too.

Close behind: *"He didn't revise this. He made something up. 'Sleepily' is new
information."* on Strunk's rewrite "Somewhere in the house a guitar hummed
sleepily"; *"'For' quietly became 'in'. He changed two things and only explains
one."* on the razors example; the colon placed inside quotation marks in
Strunk's own "on the vowel:"; and on *Alice* p. 6, *"No. Grow and you get the key
but lose the door. Shrink and you get the door but lose the key."*

## Weak or wrong (after the prompt change)

- **Wrong:** on "He is very ambitious." — *"He bans 'very' further down."* The
  1918 text has no such rule (that advice is E. B. White's, decades later).
- **Wrong:** *Alice* p. 12, on the Duck's question — *"'It' points at nothing
  until the clause ends. Bad grammar."* "Found it advisable to go…" uses an
  ordinary anticipatory *it*; it is not a grammatical fault.
- **Misreading:** on "I hardly knew him, he was so changed" — *"Rule 5 lasts one
  page before it's broken on purpose."* Strunk states this as an admitted
  exception inside Rule 5 itself.
- **Anachronism:** on "Write to-day, to-night, to-morrow" — calls the hyphenated
  forms the obsolete ones; in 1918 they were the customary forms.
- **Annotating boilerplate:** a note on the Project Gutenberg transcriber's note
  ("Hover all you like. It is plain text."). The chapter starts with the
  Gutenberg header, which section-level boilerplate skipping cannot remove.
- **Thin:** "At least he admits it.", "California's tourist board, quietly
  furious.", and on *Alice* p. 3 "Dream logic. Don't look for physics here.",
  which contradicts the physics note one page earlier.
- **Still repetitive across pages:** four *Alice* notes on pages 4–6 make the
  same "test a small dose first" point. Pages are generated three at a time,
  so neighbouring pages cannot see each other's notes.

Tally: of 95 notes, 4 make a claim that is wrong or a misreading (about 4%);
about 8 more are thin or repeat a point. The rest are specific to their line and,
where checked against the source, accurate.

## Render

Checked visually at 150 dpi on all twelve PDF pages. Notes are legible and sit in
the margins, clear of the body text. One defect was fixed: the star drawn for a
`doodle_note` was centred on the note box, so it was printed across the note's
own handwriting; it now sits just above the note's top-left corner
(`src/halfblood/ink/composer.py`). Not fixed: when the target is mid-line, the
connector crosses neighbouring words of body text to reach it. The router's
obstacle handling is a known limit (the README makes no claim of collision-free
connectors). Ellipses around quotes that wrap onto two lines are large and reach
into the margin.
