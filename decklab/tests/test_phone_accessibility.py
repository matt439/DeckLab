"""E11-S55's fixes from the phone audit (decklab/design/accessibility-audit-phone-2026-11-04.md), kept fixed.

Source checks of the stylesheets and scripts, as test_web_pages does; no browser, no server.
"""
import re
import unittest

from decklab.tests.test_web import _function, _text

FOCUSABLE = ":where(a[href], button, input, select, textarea, summary, [tabindex])"


def _rule(css, selector):
    """The declarations of every rule whose selector is exactly selector, joined; None when there's none."""
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    found = re.findall(r"(?:^|[}\n])\s*" + re.escape(selector) + r"\s*\{([^}]*)\}", css)
    return "\n".join(found) if found else None


class FocusClearOfTheBarsTests(unittest.TestCase):
    """Finding 1: a focused control stops clear of the sticky header, the deck tabs, the tab bar and a page's bar
    (WCAG 2.4.11)."""

    def test_focusable_controls_keep_clear_of_the_bars(self):
        base = _text("base.css")
        rule = _rule(base, FOCUSABLE)
        self.assertIsNotNone(rule)
        self.assertIn("scroll-margin-top: calc(var(--focus-clear-top) + var(--s-2))", rule)
        self.assertIn("scroll-margin-bottom: calc(var(--focus-clear-bottom) + var(--s-2))", rule)
        body = _rule(base, "body")
        self.assertIn("--focus-clear-top: var(--shell-top)", body)
        self.assertIn("--focus-clear-bottom: var(--shell-bottom, 0px)", body)
        # The deck page's sticky tab strip, and a page's own bar on top of the tab bar.
        self.assertIn("calc(var(--shell-top) + var(--tap))", _rule(base, "body:has(#main .deck-tabs)"))
        self.assertIn("var(--bar-h)", _rule(base, "body:is(.has-edit-bar, :has(#main .action-bar))"))
        # Inside a sheet, the viewer or a menu nothing sticks, so only a small margin.
        self.assertIn("scroll-margin: var(--s-2)",
                      _rule(base, ':where(dialog, [role="dialog"], .menu) ' + FOCUSABLE))

    def test_the_tab_bar_keeps_the_padding_variable_in_step(self):
        # The bar may grow with large text; shell.js sets --shell-bottom to its height, so the focus clearance
        # and the page's padding follow it.
        shell = _text("shell.js")
        watch = _function(shell, "watchTabbarHeight")
        self.assertIn("ResizeObserver", watch)
        self.assertIn('setProperty("--shell-bottom"', watch)
        self.assertIn('removeProperty("--shell-bottom")', watch)
        self.assertIn("watchTabbarHeight(bar);", shell)


class LargeTextTests(unittest.TestCase):
    """Finding 3: the phone's text at 200 %."""

    def test_tab_labels_wrap_rather_than_cut_off(self):
        css = _text("shell.css")
        label = _rule(css, ".tab .tab-label")
        self.assertIsNotNone(label)
        self.assertNotIn("nowrap", label)
        self.assertNotIn("ellipsis", label)
        self.assertIn("overflow-wrap: anywhere", label)
        # They grow with the text up to 15 px, where the longest word still fits a phone's 78 px tab.
        self.assertIn("--fs-tab: min(var(--fs-xs), 15px);", _text("tokens.css"))
        self.assertIn("font-size: var(--fs-tab)", css)
        bar = re.search(r"body\.has-shell \.tabbar:not\(\[hidden\]\) \{([^}]*)\}", css).group(1)
        self.assertIn("min-height: calc(56px + env(safe-area-inset-bottom))", bar)
        self.assertNotIn("height: var(--shell-bottom)", bar)

    def test_the_skip_link_hides_by_its_own_height(self):
        base = _text("base.css")
        skip = _rule(base, ".skip")
        self.assertNotIn("-60px", skip)
        self.assertIn("transform: translateY(calc(-100% - var(--s-2)))", skip)
        self.assertIn("transform: translateY(var(--s-2))", _rule(base, ".skip:focus"))

    def test_the_deck_page_never_grows_wider_than_the_screen(self):
        # Found on the recheck: at 200 % text the kit chip, the price table's number columns, Practice's colour
        # table and its sources list each pushed the deck page wider, and the tab bar off the screen.
        deck = _text("deck.css")
        self.assertIn("white-space: normal", _rule(deck, ".deck-kit-chip .status"))
        for col, em, share in (("c-need", "3.1em", "13%"), ("c-have", "3.5em", "14%"),
                               ("c-miss", "4.4em", "17%"), ("c-price", "4.4em", "18%")):
            self.assertIn(f"width: min({em}, {share})", _rule(deck, f".owned-table col.{col}"))
        stats = _text("stats.css")
        self.assertIn("overflow-x: auto", _rule(stats, ".chance-scroll"))
        self.assertIn("position: static", _rule(stats, ".chance-scroll .chance-table th"))
        self.assertIn("min-width: 0; overflow-wrap: anywhere", _rule(stats, ".sources-list > li"))
        # A scrolling region a keyboard can reach and a screen reader can name.
        self.assertIn('el("div", { class: "chance-scroll", role: "region", tabindex: "0",', _text("practice.js"))

    def test_the_avatar_initial_stays_in_its_circle(self):
        self.assertIn("--fs-avatar: min(var(--fs-md), 18px);", _text("tokens.css"))
        self.assertIn("font-size: var(--fs-avatar)", _rule(_text("shell.css"), ".avatar"))


class StructureTests(unittest.TestCase):
    """Findings 2, 4 and 5: headings and names a screen reader can tell apart."""

    def test_the_cards_tab_has_an_h2_over_its_type_groups(self):
        parts = _function(_text("deck.js"), "cardsParts")
        self.assertIn('el("h2", { class: "sr-only", text: listName(data.version) })', parts)
        self.assertIn("return [heading, screen.cardsBar", parts)

    def test_pod_cards_name_their_game_too(self):
        pods = _function(_text("play-pods.js"), "podCard")
        self.assertIn('el("h3", { id: headId }', pods)
        self.assertIn('"aria-describedby": headId', pods)
        self.assertIn("playSnapshotDetails(record.seats", pods)
        self.assertIn(", headId)", pods)

    def test_library_tiles_say_the_title_before_the_colours(self):
        card = _function(_text("library.js"), "deckCard")
        self.assertIn('pips.setAttribute("aria-hidden", "true")', card)
        self.assertIn('el("span", { class: "sr-only", text: ` (${colours.label})` })', card)
        # The colours come after the title inside the title row.
        self.assertLess(card.index('class: "deck-title", text: title'), card.index("colours.label"))


class ReducedMotionTests(unittest.TestCase):
    """Finding 6: a scroll the page makes itself jumps when the device asks for reduced motion."""

    def test_no_page_hard_codes_a_smooth_scroll(self):
        from decklab.tests.test_web import WEB
        offenders = [path.name for path in sorted(WEB.glob("*.js"))
                     if path.name != "core.js" and 'behavior: "smooth"' in path.read_text(encoding="utf-8")]
        self.assertEqual(offenders, [])
        helper = _function(_text("core.js"), "scrollBehaviour")
        self.assertIn("prefers-reduced-motion: reduce", helper)
        self.assertIn('"auto" : "smooth"', helper)


if __name__ == "__main__":
    unittest.main()
