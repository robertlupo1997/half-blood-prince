"""A page-image scan with no OCR layer must say so, not report "0 annotations".

Trying to annotate a scanned book is a normal thing for a user to do, and a
large share of scans on the internet carry no text layer at all. The pipeline
reads the text layer, so its honest answer is that it cannot work with the file.

Before this check it extracted pages, found nothing on them, never called the
API, printed "0 annotations across 5 pages" and exited 0 — indistinguishable
from a book the annotator simply had no opinions about. Verified against the
Internet Archive's Google scan of Jekyll & Hyde (`strangecasedrje01stevgoog`),
where 170 of 171 pages carry no text.

No network calls; no API key required.
"""

from __future__ import annotations

import click
import pytest

from halfblood.cli import _require_text_layer
from halfblood.document_processor import PageContent


def _page(n: int, text: str) -> PageContent:
    return PageContent(page_number=n, text=text, width=612.0, height=792.0)


class TestRequireTextLayer:
    def test_a_page_image_scan_is_reported_clearly(self) -> None:
        pages = [_page(i, "") for i in range(1, 6)]
        with pytest.raises(click.ClickException) as exc:
            _require_text_layer(pages)
        message = str(exc.value)
        assert "No readable text" in message
        assert "OCR" in message, "the message must name the actual cause"
        assert "ocrmypdf" in message, "the message must give the user a next step"

    def test_whitespace_only_pages_count_as_empty(self) -> None:
        pages = [_page(i, "   \n\n \t ") for i in range(1, 4)]
        with pytest.raises(click.ClickException):
            _require_text_layer(pages)

    def test_a_real_text_layer_passes(self) -> None:
        pages = [
            _page(1, "Mr. Utterson the lawyer was a man of a rugged countenance."),
            _page(2, "He was austere with himself; drank gin when he was alone."),
        ]
        _require_text_layer(pages)  # must not raise

    def test_one_readable_page_is_enough(self) -> None:
        """Real books have blank pages; only a wholly textless run is fatal."""
        pages = [
            _page(1, ""),
            _page(2, "   "),
            _page(3, "The last good influence in the lives of down-going men."),
        ]
        _require_text_layer(pages)  # must not raise

    def test_an_empty_selection_is_not_this_error(self) -> None:
        """`--pages` selecting nothing is a different problem with its own path."""
        _require_text_layer([])  # must not raise

    def test_a_single_sparse_page_is_not_treated_as_a_scan(self) -> None:
        """The rule is "nothing at all", not a per-page threshold.

        A part-divider or a page holding one line of verse is thin but real, and
        a character threshold would reject a range made only of those. An earlier
        draft used 24 characters per page and broke 47 existing tests, which was
        the same misfire showing up against fixtures.
        """
        _require_text_layer([_page(1, "II")])
        _require_text_layer([_page(1, "THE END")])
