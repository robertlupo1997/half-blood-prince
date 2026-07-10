"""One-off generator script for tests/fixtures/potions_textbook.pdf.

Not part of the test suite itself (no test_*.py naming) -- it's the
recipe used to build the fixture. Re-run this file directly if the
fixture ever needs to be regenerated:

    python tests/fixtures/make_potions_textbook.py
"""

from __future__ import annotations

from pathlib import Path

import fitz  # PyMuPDF

OUT_PATH = Path(__file__).resolve().parent / "potions_textbook.pdf"

PAGE_WIDTH, PAGE_HEIGHT = 612, 792  # US Letter, points
MARGIN_LEFT = 72
MARGIN_RIGHT = 72
MARGIN_TOP = 72
MARGIN_BOTTOM = 72
BODY_SIZE = 11
BODY_LEADING = 15
HEADING_SIZE = 20
SUBHEADING_SIZE = 13
TITLE_SIZE = 28

FONT_BODY = "helv"
FONT_BOLD = "hebo"
FONT_ITALIC = "heit"

TEXT_WIDTH = PAGE_WIDTH - MARGIN_LEFT - MARGIN_RIGHT


def new_page(doc: fitz.Document) -> fitz.Page:
    return doc.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)


def draw_page_number(page: fitz.Page, number: int) -> None:
    page.insert_text(
        fitz.Point(PAGE_WIDTH / 2 - 6, PAGE_HEIGHT - 40),
        f"{number}",
        fontsize=10,
        fontname=FONT_BODY,
        color=(0, 0, 0),
    )


def wrap_words(words: list[str], font: fitz.Font, size: float, max_width: float) -> list[str]:
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if font.text_length(candidate, fontsize=size) <= max_width:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def draw_paragraph(
    page: fitz.Page,
    y: float,
    text: str,
    size: float = BODY_SIZE,
    leading: float = BODY_LEADING,
    fontname: str = FONT_BODY,
    x: float = MARGIN_LEFT,
    width: float = TEXT_WIDTH,
    color: tuple[float, float, float] = (0, 0, 0),
) -> float:
    """Draw a word-wrapped paragraph starting at y, return the new y."""
    font = fitz.Font(fontname)
    words = text.split()
    lines = wrap_words(words, font, size, width)
    for line in lines:
        page.insert_text(
            fitz.Point(x, y), line, fontsize=size, fontname=fontname, color=color
        )
        y += leading
    return y


def draw_heading(page: fitz.Page, y: float, text: str) -> float:
    page.insert_text(
        fitz.Point(MARGIN_LEFT, y), text, fontsize=HEADING_SIZE, fontname=FONT_BOLD, color=(0, 0, 0)
    )
    y += 8
    page.draw_line(
        fitz.Point(MARGIN_LEFT, y), fitz.Point(PAGE_WIDTH - MARGIN_RIGHT, y), color=(0, 0, 0), width=0.75
    )
    return y + 24


def draw_subheading(page: fitz.Page, y: float, text: str) -> float:
    page.insert_text(
        fitz.Point(MARGIN_LEFT, y), text, fontsize=SUBHEADING_SIZE, fontname=FONT_BOLD, color=(0, 0, 0)
    )
    return y + 20


def draw_numbered_step(page: fitz.Page, y: float, number: int, text: str) -> float:
    label = f"{number}."
    page.insert_text(fitz.Point(MARGIN_LEFT, y), label, fontsize=BODY_SIZE, fontname=FONT_BOLD, color=(0, 0, 0))
    indent = MARGIN_LEFT + 22
    font = fitz.Font(FONT_BODY)
    words = text.split()
    width = TEXT_WIDTH - 22
    lines = wrap_words(words, font, BODY_SIZE, width)
    for i, line in enumerate(lines):
        yy = y + i * BODY_LEADING
        page.insert_text(fitz.Point(indent, yy), line, fontsize=BODY_SIZE, fontname=FONT_BODY, color=(0, 0, 0))
    return y + len(lines) * BODY_LEADING + 6


def build() -> None:
    doc = fitz.open()

    # ------------------------------------------------------------------
    # Page 1: Title page + intro
    # ------------------------------------------------------------------
    page = new_page(doc)
    page.insert_text(
        fitz.Point(MARGIN_LEFT, 160), "ADVANCED POTION-MAKING", fontsize=TITLE_SIZE, fontname=FONT_BOLD
    )
    page.insert_text(
        fitz.Point(MARGIN_LEFT, 195),
        "A Compendium for the N.E.W.T.-Level Student",
        fontsize=14,
        fontname=FONT_ITALIC,
    )
    page.insert_text(
        fitz.Point(MARGIN_LEFT, 220),
        "Fifth Edition, Revised and Approved for Hogwarts School of Witchcraft and Wizardry",
        fontsize=10,
        fontname=FONT_BODY,
    )
    page.draw_line(fitz.Point(MARGIN_LEFT, 250), fitz.Point(PAGE_WIDTH - MARGIN_RIGHT, 250), width=1.0)

    y = 290
    y = draw_subheading(page, y, "Introduction")
    intro = (
        "Potion-making is, and has always been, a discipline of exactitude. Where a wandless "
        "charm may forgive a sloppy gesture and a poorly pronounced incantation may still, on "
        "occasion, produce a usable result, a potion offers no such mercy. The cauldron does not "
        "care about your intentions. It cares only about heat, timing, and the precise order in "
        "which ingredients meet the boil."
    )
    y = draw_paragraph(page, y, intro) + 10
    intro2 = (
        "This volume assumes a working knowledge of the standard ingredients catalogued in "
        "One Thousand Magical Herbs and Fungi and a basic grasp of cauldron safety as taught "
        "at O.W.L. level. Students are reminded that the instructions that follow represent the "
        "orthodox, examination-approved method for each potion. They are reliable. They are "
        "also, frequently, not the fastest or the cleverest way to arrive at the same result -- "
        "a fact that more gifted brewers tend to discover for themselves, usually by page thirty."
    )
    y = draw_paragraph(page, y, intro2) + 10
    intro3 = (
        "A note on caution: several potions in this book, if brewed incorrectly, produce effects "
        "ranging from the mildly embarrassing to the lethal. Where a step is marked with a "
        "warning, it is marked for good reason. Read every instruction twice before lighting "
        "your fire. Stir only in the direction specified. When in doubt, consult your instructor "
        "rather than your own initiative."
    )
    y = draw_paragraph(page, y, intro3)
    draw_page_number(page, 1)

    # ------------------------------------------------------------------
    # Page 2: Draught of Living Death
    # ------------------------------------------------------------------
    page = new_page(doc)
    y = MARGIN_TOP
    y = draw_heading(page, y, "Chapter Seven: The Draught of Living Death")
    para = (
        "The Draught of Living Death is among the most powerful sleeping potions known to the "
        "wizarding world, inducing a state so profound that the drinker's breathing and heartbeat "
        "become nearly undetectable. It is a popular, if difficult, N.E.W.T. examination potion, "
        "and mistakes made in its brewing tend to be unforgiving."
    )
    y = draw_paragraph(page, y, para) + 14

    y = draw_subheading(page, y, "Ingredients")
    ingredients = (
        "One sprig of wormwood, chopped; one Sopophorous bean, cut into thin slices; two measures "
        "of standard ingredient, powdered valerian root; one sprig of asphodel; one measure of "
        "wormwood infusion, prepared separately; and a pinch of powdered root of asphodel for "
        "finishing."
    )
    y = draw_paragraph(page, y, ingredients) + 14

    y = draw_subheading(page, y, "Method")
    y = draw_numbered_step(page, y, 1, "Bring your cauldron to a low simmer over a moderate flame and add the wormwood infusion.")
    y = draw_numbered_step(page, y, 2, "Cut the Sopophorous bean with a silver knife and add the slices to the cauldron, stirring occasionally.")
    y = draw_numbered_step(page, y, 3, "Add the chopped valerian root in two measures, then stir the potion seven times clockwise and let it stand for exactly one minute.")
    y = draw_numbered_step(page, y, 4, "Crush the powdered root of asphodel thoroughly in a mortar before adding it, then sprinkle it evenly over the surface of the potion.")
    y = draw_numbered_step(page, y, 5, "Add the sprig of wormwood whole, without chopping, and allow the potion to brew undisturbed for a further ten minutes.")
    y = draw_numbered_step(page, y, 6, "Stir once more, counter-clockwise, and remove from heat. The potion should turn a pale, translucent lilac when finished correctly.")
    draw_page_number(page, 2)

    # ------------------------------------------------------------------
    # Page 3: Amortentia
    # ------------------------------------------------------------------
    page = new_page(doc)
    y = MARGIN_TOP
    y = draw_heading(page, y, "Chapter Eight: Amortentia")
    para = (
        "Amortentia is widely considered the most powerful love potion in existence. It does not, "
        "of course, create genuine love -- no potion can do that -- but it produces a powerful and "
        "dangerous infatuation. Amortentia is recognisable by its distinctive mother-of-pearl sheen "
        "and the spiralling steam it gives off, and it smells differently to each person according "
        "to what attracts them."
    )
    y = draw_paragraph(page, y, para) + 14

    y = draw_subheading(page, y, "A Note on Safety")
    warn = (
        "It is generally considered prudent, though not strictly necessary for most classroom "
        "purposes, to exercise a degree of caution when handling Amortentia, insofar as the potion "
        "may, under some circumstances, produce a mild and largely temporary infatuation effect in "
        "individuals who happen to inhale the fumes in an enclosed space for a prolonged period, "
        "although the Ministry has not classified it as a restricted substance for teaching purposes."
    )
    y = draw_paragraph(page, y, warn) + 14

    y = draw_subheading(page, y, "Ingredients")
    ingredients = (
        "Rose thorns, powdered; ashwinder eggs, crushed; peppermint, finely chopped; a pearl "
        "dissolved in wine; and a moonstone infusion prepared the night before under a waxing moon."
    )
    y = draw_paragraph(page, y, ingredients) + 14

    y = draw_subheading(page, y, "Method")
    y = draw_numbered_step(page, y, 1, "Dissolve the pearl in the wine over gentle heat, stirring until fully incorporated, which may take up to twenty minutes.")
    y = draw_numbered_step(page, y, 2, "Add the crushed ashwinder eggs one at a time, waiting thirty seconds between each addition to avoid a sudden rise in temperature.")
    y = draw_numbered_step(page, y, 3, "Fold in the powdered rose thorns and the chopped peppermint together, then bring the cauldron to a rolling boil for three minutes.")
    y = draw_numbered_step(page, y, 4, "Reduce the heat and add the moonstone infusion slowly, drop by drop, stirring continuously in a figure-eight pattern.")
    y = draw_numbered_step(page, y, 5, "Allow the potion to cool undisturbed. The finished Amortentia should be kept in a stoppered crystal bottle, away from direct sunlight.")
    draw_page_number(page, 3)

    # ------------------------------------------------------------------
    # Page 4: Felix Felicis
    # ------------------------------------------------------------------
    page = new_page(doc)
    y = MARGIN_TOP
    y = draw_heading(page, y, "Chapter Nine: Felix Felicis")
    para = (
        "Felix Felicis, known colloquially as Liquid Luck, is a potion of extraordinary complexity "
        "and extraordinary effect: the drinker becomes lucky for a set period, succeeding at "
        "whatever they attempt. It is toxic in excess and heavily regulated. Brewing it correctly "
        "takes six months, and the process cannot safely be rushed."
    )
    y = draw_paragraph(page, y, para) + 14

    y = draw_subheading(page, y, "Ingredients")
    ingredients = (
        "Squill bulb, sliced; a measure of powdered common rue; three sprigs of Ashwinder ash; "
        "a single Murtlap tentacle, finely diced; standard ingredient, ground squill root; and "
        "twelve measures of prepared base, matured for at least ninety days before use."
    )
    y = draw_paragraph(page, y, ingredients) + 14

    y = draw_subheading(page, y, "Method")
    y = draw_numbered_step(page, y, 1, "Begin with the prepared base, which must first be brought to a rolling boil, then reduced to a bare simmer over the course of one full hour.")
    y = draw_numbered_step(page, y, 2, "Add the sliced squill bulb one slice at a time, in a strict clockwise rotation around the cauldron's rim, pausing between each to let the surface settle completely.")
    y = draw_numbered_step(page, y, 3, "Introduce the powdered common rue by first dissolving it separately in a small quantity of dragon tonic, then adding the dissolved mixture slowly over a period of no less than fifteen minutes.")
    y = draw_numbered_step(page, y, 4, "Dice the Murtlap tentacle as finely as possible and stir it in with a copper rod, taking care to scrape the sides of the cauldron thoroughly to prevent scorching.")
    y = draw_numbered_step(page, y, 5, "Add the Ashwinder ash in three separate sprigs, each one measured to within a hundredth of an ounce, waiting a full day between additions.")
    y = draw_numbered_step(page, y, 6, "Allow the potion to mature, covered, for no fewer than six months, checking weekly that its colour remains a uniform molten gold.")
    draw_page_number(page, 4)

    # ------------------------------------------------------------------
    # Page 5: Antidotes
    # ------------------------------------------------------------------
    page = new_page(doc)
    y = MARGIN_TOP
    y = draw_heading(page, y, "Chapter Ten: Antidotes and Golpalott's Third Law")
    para = (
        "No study of potions is complete without a working understanding of antidotes, and no "
        "understanding of antidotes is complete without Golpalott's Third Law, which states that "
        "the antidote for a blended poison will be equal to more than the sum of the antidotes "
        "for each of the separate components."
    )
    y = draw_paragraph(page, y, para) + 14

    y = draw_subheading(page, y, "Common Mistakes")
    para2 = (
        "The most frequent error among N.E.W.T. students is to attempt to identify each poisonous "
        "ingredient in a blended sample and then brew a separate antidote for each one individually, "
        "combining them at the end. This approach, though intuitive, directly contradicts Golpalott's "
        "Third Law and will not produce a working antidote. Students routinely lose significant marks "
        "for this exact mistake."
    )
    y = draw_paragraph(page, y, para2) + 14

    y = draw_subheading(page, y, "Standard Method")
    y = draw_numbered_step(page, y, 1, "Isolate a small sample of the poison and use a standard Scarpin's Revelaspell to identify each constituent ingredient in turn.")
    y = draw_numbered_step(page, y, 2, "Add a bezoar to the sample first and observe whether it neutralises the poison outright, which it will for most common non-magical toxins.")
    y = draw_numbered_step(page, y, 3, "If the bezoar has no effect, calculate the antidote as a single unified compound rather than as a sum of individual antidotes, in accordance with Golpalott's Third Law.")
    y = draw_numbered_step(page, y, 4, "Brew the unified antidote slowly, testing a small quantity on a sample of the poison before administering the full dose to a patient.")
    y = draw_numbered_step(page, y, 5, "Always keep a bezoar within reach when working with unidentified poisons, regardless of how confident you are in your calculations.")
    draw_page_number(page, 5)

    doc.save(str(OUT_PATH), garbage=4, deflate=True)
    doc.close()
    print(f"Wrote {OUT_PATH} ({OUT_PATH.stat().st_size} bytes)")


if __name__ == "__main__":
    build()
