"""E11-S55's fixes from the second audit, of the other pages and the lab layout
(decklab/design/accessibility-audit-pages-2026-11-04.md), kept fixed.

Source checks of the stylesheets and scripts, as test_phone_accessibility does; no browser, no server.
"""
import unittest

from decklab.tests.test_phone_accessibility import _rule
from decklab.tests.test_web import _function, _text


class PageBarFocusTests(unittest.TestCase):
    """Finding 1: Build decks' and Receive delivery's action bars grow past --bar-h, and focus hid under them."""

    def test_focus_stops_above_the_whole_page_bar(self):
        rule = _rule(_text("base.css"), "body:is(.has-edit-bar, :has(#main .action-bar))")
        self.assertIn("--focus-clear-bottom: calc(var(--shell-bottom, 0px) + max(var(--bar-h), var(--page-bar-h, 0px)))",
                      rule)
        self.assertIn("max(var(--bar-h), var(--page-bar-h, 0px))", _text("assembly.css"))

    def test_the_shell_measures_the_page_bar(self):
        shell = _text("shell.js")
        watch = _function(shell, "watchPageBar")
        self.assertIn("ResizeObserver", watch)
        self.assertIn("MutationObserver", watch)
        self.assertIn('querySelector(".action-bar")', watch)
        self.assertIn('setProperty("--page-bar-h"', watch)
        self.assertIn('removeProperty("--page-bar-h")', watch)
        self.assertIn("watchPageBar();", _function(shell, "setUpShell"))


class EditorTests(unittest.TestCase):
    """Findings 2 and 3: the editor on a phone."""

    def test_the_list_has_an_h2_beside_the_tabs(self):
        head = _function(_text("editor-screen.js"), "mainTabs")
        self.assertIn('tab("cards", "Cards"), tab("notes", "Notes")) : null', head)
        self.assertIn('class: ed.quick || notes ? "sr-only" : "edit-cards-title"', head)

    def test_a_narrow_list_puts_the_badge_on_its_own_line(self):
        css = _text("editor.css")
        self.assertIn("container: quick-list / inline-size", _rule(css, ".is-quick .edit-list"))
        self.assertIn('@container quick-list (max-width: 20em)', css)
        narrow = css[css.index('@container quick-list (max-width: 20em)'):]
        row = _rule(narrow, ".is-quick .edit-list > .edit-row")
        # Identity and badge each get a full line; tools no longer consume the name's remaining width.
        self.assertIn('"card card card"', row)
        self.assertIn('"badge badge badge"', row)
        # The list switch stays one row while it fits, and wraps its words rather than widening the page.
        switch = _rule(css, ".edit-head .version-pick .segmented > *")
        self.assertIn("white-space: normal", switch)
        self.assertIn("min-width: 0", switch)


class NamesAndLandmarksTests(unittest.TestCase):
    """Findings 4 to 6: ARIA a field may carry, unique landmark names, no empty table header."""

    def test_the_search_field_carries_no_aria_expanded(self):
        self.assertNotIn("aria-expanded", _function(_text("global-search.js"), "gsBox"))
        self.assertNotIn('setAttribute("aria-expanded"', _function(_text("global-search.js"), "gsShow"))

    def test_accessory_parts_are_named_with_their_owner(self):
        update = _function(_text("accessories.js"), "updateAccessories")
        self.assertIn('"aria-labelledby": `${ownerId} ${id}`', update)
        self.assertIn('el("h3", { id, text:', update)
        self.assertIn("font-size", _rule(_text("accessories.css"), ".acc-section > h3"))

    def test_each_queue_table_region_has_its_own_name(self):
        present = _function(_text("shopping-queue.js"), "shopQueuePresentation")
        self.assertIn('`${group === "long-term" ? "Long-term plan" : "Purchase queue"} table, scroll for more columns`',
                      present)

    def test_the_add_part_is_a_group_inside_its_named_pane(self):
        part = _function(_text("editor-cards.js"), "addPart")
        self.assertIn('el("div", { class: "edit-add", id: "edit-add", role: "group", "aria-label": "Add cards" }', part)

    def test_compare_tables_name_their_row_header_column(self):
        table = _function(_text("compare.js"), "compareTable")
        self.assertIn('el("th", { scope: "col" }, el("span", { class: "sr-only", text: "Figure" }))', table)
        self.assertNotIn('el("th", { scope: "col", text: "" })', table)


class TouchTargetTests(unittest.TestCase):
    """Findings 7 and 8: 44 px targets where there's no fine pointer."""

    def test_compare_titles_are_full_targets_on_touch(self):
        self.assertIn("@media (pointer: coarse) { .compare-title { display: inline-flex; align-items: center; "
                      "min-height: var(--tap); } }", _text("compare.css"))

    def test_which_printing_is_a_full_target_on_touch(self):
        self.assertRegex(_text("assembly-overlap.css"), r"\.pack-printing-select \{[^}]*min-height: var\(--tap\);")


if __name__ == "__main__":
    unittest.main()
