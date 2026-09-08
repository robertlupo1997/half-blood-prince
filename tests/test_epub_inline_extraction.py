"""Inline markup must not become a line break in the text the model is shown.

`_html_to_text` promised "one-line-per-block text" and delivered one line per *text node*,
because `soup.get_text(separator="\\n")` cannot tell an inline `<i>` from a block `<p>`.

The consequence reached the product. Shown `hers\\n,\\nits\\n,\\ntheirs\\n` for
`<i>hers</i>, <i>its</i>, <i>theirs</i>`, the model faithfully quotes a string that does
not exist as contiguous document text, so placement refuses it and the note is lost.
Three of eight annotations on a real book failed this way.
"""

from __future__ import annotations

from halfblood.epub_processor import EpubProcessor


def _text(html: str) -> str:
    return EpubProcessor._html_to_text(html)


def test_inline_tags_do_not_split_a_sentence() -> None:
    """The exact shape that lost three annotations on The Elements of Style."""
    html = (
        "<p>The pronominal possessives <i>hers</i>, <i>its</i>, <i>theirs</i>, "
        "<i>yours</i>, and <i>oneself</i> have no apostrophe.</p>"
    )
    assert _text(html) == (
        "The pronominal possessives hers, its, theirs, yours, and oneself "
        "have no apostrophe."
    )


def test_block_boundaries_still_produce_line_breaks() -> None:
    """The other half of the contract: blocks separate, inline does not."""
    html = "<p>First block.</p><p>Second <em>block</em>.</p><h2>A heading</h2>"
    assert _text(html).splitlines() == ["First block.", "Second block.", "A heading"]


def test_list_items_are_separate_lines() -> None:
    html = "<ul><li>One <b>item</b></li><li>Another</li></ul>"
    assert _text(html).splitlines() == ["One item", "Another"]


def test_script_and_style_are_still_dropped() -> None:
    html = "<p>Visible</p><script>var x=1;</script><style>p{color:red}</style>"
    assert _text(html) == "Visible"


def test_the_quoted_string_exists_in_the_real_book() -> None:
    """End to end on the corpus: what the model is shown is what the document contains."""
    from pathlib import Path

    book = Path(__file__).parent / "corpora" / "real" / "elements-of-style.epub"
    if not book.exists():
        import pytest

        pytest.skip("real-book corpus not present")

    shown = EpubProcessor().load(str(book))
    joined = "\n".join(page.text for page in shown)
    assert "possessives hers, its, theirs" in joined, (
        "the model is still being shown inline markup as line breaks"
    )
