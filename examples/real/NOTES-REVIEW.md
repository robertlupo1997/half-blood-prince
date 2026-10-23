# Real-model showcase: review of the notes

Two public-domain books, generated with `--provider claude-cli`
(the Claude Code CLI on a Claude subscription, CLI model alias `opus`), default
Half-Blood Prince persona. *Elements of Style* was generated on 2026-10-22;
*Alice* was regenerated on 2026-10-23 against the rebuilt
`examples/src/alice.pdf` (see "Source" below). Read line by line against the source text by the
agent that produced them. **That is a self-review, not an independent judgement.**
The independent grading (gate G5, 2026-10-23) scored the separate eval set, not these
books; see `GATES.md`.

## Files

| file | what it is |
|---|---|
| `alice.plan.json` | the generated annotation plan, *Alice's Adventures in Wonderland*, pages 1–12 of `examples/src/alice.pdf` |
| `alice.plan.json.report.json` | generation report for that plan |
| `alice-annotated.pdf`, `.report.json` | rendered from the plan with `--resume-from` (no second model call) |
| `alice-page-02.png`, `-08.png`, `-12.png` | 150 dpi renders of three annotated pages |
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
| Alice, PDF pages 1–12 (2026-10-23) | 60 | 60 | 0 | 92,893 / 13,390 | 1m07 |
| Elements of Style, one chapter (7 windows of ≤12,000 chars) | 35 | 35 | 0 | 72,756 / 14,766 | 2m44 |

Every quote resolved to exactly one place: no `ambiguous_target`, no
`missing_target`. The PDF render (re-rendered 2026-10-23 from the same plan
after the connector-routing fix below) reports 0 `connector_routing_fallback`
degradations and 8 layout warnings (7 `shifted`, 1 `scale_reduced`).

## Source

The first *Alice* run (2026-10-22) caught a defect in this repository: on
page 12 it wrote *"A line is missing. Nobody answered 'Did you speak?'"* — and
it was right. `scripts/build_example_book.py` dropped every paragraph shorter
than 40 characters, which deleted 74 paragraphs of the book, most of them
short dialogue ("Not I!" said the Lory hastily.), while keeping the table of
contents as a paragraph and the three chapter headings long enough to pass. The builder now
drops only the front matter, the chapter-heading blocks and `[Illustration]`
placeholders; every paragraph of the text is kept. `alice.pdf` grew from 77 to
80 pages, so the page boundaries moved and *Alice* was regenerated rather than
re-rendered from the old plan. Page 12 now carries "Not I!" and a note on it.

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
4. *Alice*, p. 6, on **"so either way I'll get into the garden, and I don't
   care which happens!"** — *"Wrong. Grow larger and she reaches the key but
   can't fit through the door. Only one of her two outcomes works, and she has
   already left the key on the table. She should care which happens."* Correct,
   and it is exactly what the next page shows.
5. *Alice*, p. 8, on **"four times five is twelve, and four times six is
   thirteen"** — *"Not nonsense. 4×5=20 is '12' in base 18; 4×6=24 is '13' in
   base 21. Add three to the base each step and the table never reaches 20."*
   Arithmetic checked: 18+2=20, 21+3=24, and continuing the pattern the tens
   digit never becomes 2.

Close behind: *"Five cases. Latin has six. She dropped the ablative"* on "A
mouse—of a mouse—to a mouse—a mouse—O mouse!" (correct: nominative, genitive,
dative, accusative, vocative); *"Antipodes. He meant the slip."* and *"Roughly
3,960"* (the Earth's radius in miles) on *Alice* p. 2; *"Watts's busy bee,
turned into a predator"* on the crocodile verse; on the Duck's "Found *what*?",
*"The 'it' is empty, just holding the place for 'to go with Edgar Atheling'"*
— the anticipatory *it*, which the first run had wrongly called bad grammar;
and from *Elements of Style*: *"He didn't revise this. He made something up.
'Sleepily' is new information."* on Strunk's rewrite "Somewhere in the house a
guitar hummed sleepily"; *"'For' quietly became 'in'. He changed two things and
only explains one."* on the razors example; and the colon placed inside
quotation marks in Strunk's own "on the vowel:".

## Weak or wrong (after the prompt change)

*Elements of Style* (2026-10-22 run, unchanged):

- **Wrong:** on "He is very ambitious." — *"He bans 'very' further down."* The
  1918 text has no such rule (that advice is E. B. White's, decades later).
- **Misreading:** on "I hardly knew him, he was so changed" — *"Rule 5 lasts one
  page before it's broken on purpose."* Strunk states this as an admitted
  exception inside Rule 5 itself.
- **Anachronism:** on "Write to-day, to-night, to-morrow" — calls the hyphenated
  forms the obsolete ones; in 1918 they were the customary forms.
- **Annotating boilerplate:** a note on the Project Gutenberg transcriber's note
  ("Hover all you like. It is plain text."). The chapter starts with the
  Gutenberg header, which section-level boilerplate skipping cannot remove.
- **Thin:** "At least he admits it.", "California's tourist board, quietly
  furious."

*Alice* (2026-10-23 run), read as a strict editor, accuracy first:

- **Wrong:** p. 7, on the Rabbit dropping the gloves and fan — *"Twelve words of
  politeness and she gets the Rabbit's things for free."* She says four ("If
  you please, sir—"), and he runs; she is not given anything.
- **Wrong:** p. 11, on the Lory's "I am older than you, and must know better" —
  *"She picked the wrong objection and won anyway, by luck."* She does not win:
  the Lory refuses to tell its age and "there was no more to be said."
- **Half right:** p. 2, on "Latitude or Longitude I've got to?" — *"She has
  dropped below the place where the grid applies."* Latitude and longitude are
  undefined only at the exact centre, which she has not reached; below the
  surface they still apply.
- **Overstated:** p. 1, on "Either the well was very deep, or she fell very
  slowly" — *"Both can be true, and so can neither."* Given that she had plenty
  of time, at least one must hold.
- **Invented detail:** p. 12, *"An hour ago it was 'older and must know
  better'"* — it was a page earlier, minutes of story time; p. 5, *"Second
  unknown substance on one page"* — the bottle is drunk on page 4.
- **Repeats a point:** "in brackets, where nobody looks" on p. 1 and again on
  p. 2; "first sound reasoning of the chapter" on p. 4 and p. 9 (different
  chapters, same formula); the terrier (p. 10) and the dog that "kills all the
  rats" (p. 11) make one point twice; "find the way out before you go in"
  (p. 1) returns as "she never once thinks of the way back" (p. 3); the
  small-dose advice recurs on pp. 4 and 6. Pages are generated three at a time,
  so neighbouring pages cannot see each other's notes.
- **Thin:** "The most honest line about advice on the page." (p. 5), "And the
  left foot? Snubbed. Expect it to limp." (p. 6), "Even the narrator is fed up
  with her." (p. 7).

Tally: of 95 notes (60 *Alice*, 35 *Elements of Style*), 9 make a claim that
is wrong, overstated or invented (6 *Alice*, 3 *Elements of Style*; about 9%);
about 11 more are thin, repeat a point, or annotate boilerplate. The rest are
specific to their line and, where checked against the source, accurate.

## Render

Checked visually at 150 dpi on all twelve PDF pages of the 2026-10-23 render,
plus a script that reads the drawn paths back: no mark or connector touches a
note's handwriting, no connector crosses a glyph of body text outside its own
quote, and no note runs off the page. Fixed while doing this:

- **Circles on wrapped quotes.** A `circle` mark drew one ellipse around the
  union of every line of its quote, padded by 6% of its width, so a two-line
  quote got a loop about 25pt out into the margin, across the margin notes
  (page 2 of the first render). Each line of the quote now gets its own tight
  hand-drawn loop, within 2pt of its glyph box horizontally and 1.5pt
  vertically, and a loop gives up that pad on any side where it would touch a
  placed note (`src/halfblood/ink/rough.py`, `tests/test_render_circle_geometry.py`).
- **Notes on the page edge.** The layout kept an 8pt pad from the side edges but
  not the top and bottom, so a shifted note could start at y=0 or end past the
  bottom trim (pages 2, 6 and 10 of the first render). The pad now applies on
  all four sides (`src/halfblood/layout/engine.py`).
- From the first render, still in place: the `doodle_note` star sits above the
  note's top-left corner instead of across its handwriting.

- **Connectors through body text.** 20 of the 60 connectors crossed glyphs
  of body text (92 glyphs in all, measured against each glyph's outline box,
  the quote's own letters excluded), e.g. through "such" on p. 8 and
  "(with Alice's love)" on p. 6. None of those 20 raised
  `connector_routing_fallback`: the router exempted every text line within
  2pt of the arrow's endpoint from its collision check, which is exactly the
  line a mid-line quote's arrow ran through, while the 4 connectors it did
  flag were others. The router also worked from line boxes, which touch
  their neighbours on these pages (19pt boxes at a 22pt pitch), so it could
  not see the ~9pt of leading between the glyphs. Connectors are now routed
  like a pen: along the margin, into the leading above or below the quote's
  line, ending on the quote's near end (left end for a left-margin note,
  right end for a right one), or level into the line when nothing stands
  between the margin and the quote; with no clean route, a short arrow stops
  at the column edge. The fallback flag now fires whenever any drawn stroke,
  arrowhead included, touches a glyph outside the quote or another note,
  with no endpoint exemption (`src/halfblood/ink/connector_route.py`,
  `tests/test_connector_leading_route.py`). Re-rendered from the committed
  plan: 0 of 60 connectors cross a body glyph, and 0 are flagged.
