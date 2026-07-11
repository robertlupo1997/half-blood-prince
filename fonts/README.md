# PDF handwriting fonts

Choose a bundled-on-your-machine font by registered name:

```bash
halfblood annotate book.pdf -o annotated.pdf --font caveat-brush
```

| Registered name | Expected file in `fonts/` | Download |
| --- | --- | --- |
| `caveat-brush` | `CaveatBrush-Regular.ttf` | [Google Fonts](https://fonts.google.com/specimen/Caveat+Brush) |
| `homemade-apple` | `HomemadeApple-Regular.ttf` | [Google Fonts](https://fonts.google.com/specimen/Homemade+Apple) |
| `just-me-again-down-here` | `JustMeAgainDownHere.ttf` | [Google Fonts](https://fonts.google.com/specimen/Just+Me+Again+Down+Here) |
| `mrs-saint-delafield` | `MrsSaintDelafield-Regular.ttf` | [Google Fonts](https://fonts.google.com/specimen/Mrs+Saint+Delafield) |

Download a family, extract its TTF to the exact location above, then select
the registered name. You can also pass any existing TTF or OTF directly:

```bash
halfblood annotate book.pdf -o annotated.pdf --font /path/to/MyHand.ttf
```

`--font` affects PDF rendering only. EPUB readers control fonts through their
own settings and CSS, so the option is ignored with a warning for EPUB input.
Without an explicit selection, the app auto-discovers Caveat Brush and falls
back to Helvetica-Oblique if it is absent.

Font files are not committed. Verify and retain each downloaded font's license
before redistributing it or generating derivative font assets.
