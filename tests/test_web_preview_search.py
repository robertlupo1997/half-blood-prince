"""Free-text search over annotation content in the web preview.

The preview already filters by annotation *type* (the legend chips toggle
`state.hiddenTypes`, and `applyFilters()` puts `.filtered-out` on every `[data-type]`
element). What it cannot do is answer "where did the Prince mention bezoars" — on a
300-page book that is the difference between a browsable artifact and a novelty.

Everything needed is already on the page: notes, target marks and connector paths all
carry `data-ann-id` **and** `data-type`, so search reuses the existing `.filtered-out`
mechanism rather than inventing a second hiding path.

Design constraints pinned here:

1. **Search composes with the type filter, it does not replace it.** Hiding CORRECTIONS
   and searching "bezoar" must show only un-hidden corrections... i.e. the two are ANDed.
   An implementation that overwrites `classList` from one filter clobbers the other.
2. **An empty query means no filtering**, not "match nothing" — otherwise clearing the
   box leaves a blank page.
3. **A note, its target mark, and its connector move together.** Hiding a note while
   leaving its mark highlighted in the body text points the reader at nothing.
4. **The query is never interpolated into HTML.** It is user input; it is used for
   matching only. The page's no-external-assets and escaping guarantees are unchanged.
5. **Matching is case-insensitive substring** over the note content. Not regex: a user
   typing `(` should get results, not a syntax error or a crash.
"""

from __future__ import annotations

import re

from halfblood.models import AnnotatedPage, Annotation, AnnotationPlan, AnnotationType
from halfblood.web_preview import _render


def _plan() -> AnnotationPlan:
    return AnnotationPlan(
        title="Advanced Potion-Making",
        prince_persona="the Half-Blood Prince",
        pages=[
            AnnotatedPage(
                page_number=1,
                original_text="Crush the sopophorous bean. Add the powdered root slowly.",
                annotations=[
                    Annotation(
                        page=1,
                        target_text="Crush the sopophorous bean",
                        annotation_type=AnnotationType.CORRECTION,
                        content="Crush, don't cut — keep a bezoar within reach.",
                        confidence=0.9,
                        position="margin_right",
                    ),
                    Annotation(
                        page=1,
                        target_text="Add the powdered root",
                        annotation_type=AnnotationType.SHORTCUT,
                        content="Skip this entirely. Wasted effort.",
                        confidence=0.7,
                        position="margin_left",
                    ),
                ],
            )
        ],
    )


def _html() -> str:
    html, _data = _render(_plan(), None)
    return html


class TestSearchControlExists:
    def test_a_search_input_is_rendered(self) -> None:
        html = _html()
        assert 'id="note-search"' in html

    def test_it_is_a_search_input_with_an_accessible_label(self) -> None:
        html = _html()
        match = re.search(r"<input[^>]*id=\"note-search\"[^>]*>", html)
        assert match, "note-search must be an <input>"
        tag = match.group(0)
        assert 'type="search"' in tag, "use type=search so browsers offer a clear button"
        assert "aria-label" in tag or "placeholder" in tag

    def test_it_sits_with_the_other_header_controls(self) -> None:
        html = _html()
        controls = html[html.index('class="controls"') : html.index("</header>")]
        assert 'id="note-search"' in controls


class TestSearchBehaviour:
    def test_the_handler_is_wired_to_the_input(self) -> None:
        html = _html()
        assert re.search(r"getElementById\(\s*\"note-search\"\s*\)", html)

    def test_it_listens_for_typing_not_just_submit(self) -> None:
        """A search box that only responds to Enter feels broken."""
        html = _html()
        assert re.search(r"addEventListener\(\s*\"input\"", html)

    def test_the_query_is_held_in_state_alongside_the_type_filter(self) -> None:
        """Both filters must live in one place so applyFilters can AND them."""
        html = _html()
        assert re.search(r"state\.\w*[Qq]uery", html)

    def test_matching_is_case_insensitive(self) -> None:
        html = _html()
        assert re.search(r"toLowerCase\(\)|toLocaleLowerCase\(\)", html)

    def test_it_searches_the_embedded_plan_not_the_rendered_dom(self) -> None:
        """Matching against DATA keeps search correct for notes not currently on screen."""
        html = _html()
        script = html[html.index("<script>", html.index("__HB_DATA__")) :]
        assert "DATA" in script
        assert re.search(r"annotations", script)

    def test_it_reuses_the_existing_filtered_out_mechanism(self) -> None:
        """A second hiding path would fight the type filter."""
        html = _html()
        assert html.count("filtered-out") >= 2
        assert "applyFilters" in html

    def test_the_user_sees_how_many_matched(self) -> None:
        """Silent filtering is indistinguishable from a broken box.

        Requires a dedicated element rather than the word "match" appearing anywhere,
        which it already does in unrelated code.
        """
        html = _html()
        assert 'id="search-count"' in html
        assert re.search(r"getElementById\(\s*\"search-count\"\s*\)", html)


class TestSearchKeepsThePageSafe:
    def test_the_query_is_not_treated_as_a_regex(self) -> None:
        """`new RegExp(query)` would throw on '(' and is a ReDoS surface."""
        html = _html()
        script = html[html.index("<script>", html.index("__HB_DATA__")) :]
        assert "new RegExp(" not in script, "match with indexOf/includes, not RegExp"

    def test_no_external_asset_is_introduced(self) -> None:
        html = _html()
        assert "fonts.googleapis" not in html
        assert "@import" not in html
        residue = html.replace("http://www.w3.org", "")
        assert "https://" not in residue
        assert "http://" not in residue

    def test_the_embedded_payload_is_still_escaped(self) -> None:
        html = _html()
        found = re.search(r"window\.__HB_DATA__\s*=\s*(\{.*?\});", html, re.DOTALL)
        assert found, "embedded payload not found"
        raw = found.group(1)
        assert "</" not in raw
        assert "\u2028" not in raw and "\u2029" not in raw

    def test_annotation_content_is_still_html_escaped(self) -> None:
        """Regression guard: adding search must not change how notes are rendered."""
        html = _html()
        assert "escapeHtml" in html


class TestExistingFilteringSurvives:
    def test_the_legend_still_builds_type_chips(self) -> None:
        html = _html()
        assert "legend-chip" in html
        assert "hiddenTypes" in html

    def test_both_annotations_are_still_present_in_the_payload(self) -> None:
        html = _html()
        assert "bezoar" in html
        assert "Wasted effort" in html


class TestMatchSetIsScopedToTheCurrentPage:
    """Annotation ids are page-local, so a global match set is a real bug.

    `ann.id` is a per-page index ("a0", "a1", ...), so page 0 and page 1 both have an
    "a0". A match set built across the whole book would un-hide page 1's "a0" purely
    because page 0's "a0" matched the query — showing a note that does not contain the
    search term at all.

    Confirmed by executing the shipped `applyFilters` under a DOM stub with two pages
    whose "a0" annotations differ: querying a term present only in page 0's "a0" leaves
    page 1's "a0" correctly hidden, and surfaces page 1's "a1" instead. These assertions
    are the durable, in-suite form of that check — they fail if someone "simplifies" the
    per-page lookup back to a whole-book set.
    """

    def test_the_match_set_is_built_from_the_current_page(self) -> None:
        html = _html()
        script = html[html.index("<script>", html.index("__HB_DATA__")) :]
        body = script[script.index("function applyFilters()") :]
        assert re.search(r"DATA\.pages[^\n]*\[\s*state\.idx\s*\]", body), (
            "applyFilters must index DATA.pages by state.idx; a whole-book match set "
            "collides on page-local annotation ids"
        )

    def test_filtering_keys_on_the_annotation_id(self) -> None:
        html = _html()
        script = html[html.index("<script>", html.index("__HB_DATA__")) :]
        body = script[script.index("function applyFilters()") :]
        assert "annId" in body, (
            "notes, marks and connectors share data-ann-id; keying on it is what makes "
            "them hide together"
        )
