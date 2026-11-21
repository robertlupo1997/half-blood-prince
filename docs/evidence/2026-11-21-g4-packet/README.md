# G4 reading packet, 2026-11-21

A fresh real-book run on the **current** persona prompt (the density revision of
2026-10-23, merged in PR #11), so that Trey's G4 read is of notes the shipped prompt
actually writes. The *Alice* showcase in `examples/real/` predates that revision.

- **Book:** *Alice's Adventures in Wonderland* (public domain), `examples/src/alice.pdf`, pages 1–12
- **Code:** `d2ee3f1` (`main` after PR #12)
- **Generator:** `--provider claude-cli` (Claude Code CLI, alias `opus`), default persona
- **Result:** 60 notes generated, **60 placed, 0 refused**; 107,506 tokens in / 10,866 out, about 1 minute

```sh
halfblood annotate examples/src/alice.pdf -o alice-p1-12.plan.json --pages 1-12 --provider claude-cli --dry-run
halfblood annotate examples/src/alice.pdf -o alice-p1-12-annotated.pdf --pages 1-12 --provider claude-cli --resume-from alice-p1-12.plan.json
```

An earlier, discarded run of the same command (not committed) placed 59 of 60, with one
`quote_not_found` on page 7. Model output is not reproducible byte for byte.

## The three notes put to Trey

| page | type | passage | note |
|---|---|---|---|
| 4 | warning | However, this bottle was not marked "poison," so Alice ventured to taste it | No label is not a safe label. And she drinks with no idea how to undo it. Way out first. |
| 8 | insight | four times five is twelve, and four times six is thirteen | Not wrong, only changing base: 4×5=12 in base 18, 4×6=13 in base 21. Add three each step and she never reaches 20. |
| 12 | correction | The question is, what did the archbishop find? | Nothing. 'It' points ahead: 'advisable to go with Edgar.' The bird can't wait for the end of a sentence. |

The base arithmetic was checked: 4×5 = 20 = 1·18 + 2, 4×6 = 24 = 1·21 + 3.

Chosen by the agent for range (one warning, one insight, one correction on three
different pages), not at random, so this is a best-case sample. Trey's verdict is his
to write, and G4 stays open until it is recorded here.
