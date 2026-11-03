"""E5-S30's first slice on the Wishlist page: a card your own decks are short of says so, on its tile and,
with the decks linked, in its sheet (wishlist.js's wishlistShort)."""
import json
import subprocess
import unittest

from decklab.tests.test_workspace_ui import NODE, RUNNER, WEB


@unittest.skipUnless(NODE, "Node.js isn't installed")
class WishlistShortUiTests(unittest.TestCase):
    def run_js(self, scenario):
        setup = """
          clear(main);
          document.body.append(el("p", {id: "toast"}));
          state.profiles = [{id: "user1", name: "User1"}];
          state.profile = state.profiles[0];
          location.hash = "#/wishlist";
          const entry = (card, extra = {}) => ({name: card.name, set: "", number: "", card,
            have: {owned: 0, on_the_way: 0}, notes: "", source: "", ...extra});
          const show = (entries) => drawWishlist({profile: "user1", entries, warnings: []}, state.profile, routeToken);
          const openDialog = () => document.querySelectorAll("dialog").pop();
          const deck = (id, title, missing = 1) => ({id, title, missing});
        """
        result = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), setup + scenario]),
                                capture_output=True, text=True, encoding="utf-8", timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")

    def test_one_deck_short_shows_a_chip_and_a_linked_sentence(self):
        self.run_js("""
          const view = show([entry(alpha, {short_in: [deck("casual/free-peoples", "The Free Peoples")]})]);
          const chip = view.cards.querySelector(".wishlist-short-chip");
          assert(chip);
          assert.equal(chip.textContent, "Short in 1 deck");
          assert.equal(chip.getAttribute("title"), "The Free Peoples is short of this card.");
          const open = view.cards.querySelector(".card-tile-open");
          assert(open.getAttribute("aria-label").includes("The Free Peoples is short of this card"));
          open.click();
          const line = openDialog().querySelector(".wishlist-short");
          assert.equal(line.textContent, "The Free Peoples is short of this card.");
          const link = line.querySelector("a");
          assert.equal(link.getAttribute("href"), deckHref("casual/free-peoples"));
        """)

    def test_several_decks_are_named_with_copies_then_counted(self):
        self.run_js("""
          const two = entry(alpha, {short_in: [deck("casual/a", "Gruul Ramp", 2), deck("commander/b", "Elves")]});
          assert.equal(wishlistShortText(two), "Gruul Ramp (2 copies) and Elves are short of this card");
          const five = entry(beta, {short_in: [deck("casual/a", "A", 3), deck("casual/b", "B"), deck("casual/c", "C"),
            deck("casual/d", "D"), deck("casual/e", "E")]});
          assert.equal(wishlistShortText(five), "A (3 copies), B, C and 2 more decks are short of this card");
          const view = show([two, five]);
          const chips = view.cards.querySelectorAll(".wishlist-short-chip").map((c) => c.textContent);
          same(chips, ["Short in 2 decks", "Short in 5 decks"]);
          view.cards.querySelectorAll(".card-tile-open")[1].click();
          const line = openDialog().querySelector(".wishlist-short");
          assert.equal(line.textContent, "A (3 copies), B, C and 2 more decks are short of this card.");
          same(line.querySelectorAll("a").map((a) => a.textContent), ["A", "B", "C"]);
        """)

    def test_nothing_shows_when_no_deck_is_short_or_it_cant_be_said(self):
        self.run_js("""
          for (const short_in of [[], null, undefined]) {
            const view = show([entry(alpha, short_in === undefined ? {} : {short_in})]);
            assert.equal(view.cards.querySelector(".wishlist-short-chip"), null);
            assert(!view.cards.textContent.includes("short"));
            view.cards.querySelector(".card-tile-open").click();
            assert.equal(openDialog().querySelector(".wishlist-short"), null);
            clear(main);
          }
        """)

    def test_short_warnings_have_their_own_box_and_heading(self):
        self.run_js("""
          const answer = (warnings, short_warnings) => drawWishlist({profile: "user1", entries: [entry(alpha)],
            warnings, short_warnings}, state.profile, routeToken);
          const headings = (view) => view.warnings.querySelectorAll("h2").map((h) => h.textContent);
          const skipped = "Some of your decks couldn't be counted, so they may also be short of these cards.";
          let view = answer(["No card details for 'X'; it stays on your wishlist."], [skipped]);
          same(headings(view), ["Some card details aren't available", "Some decks short of these cards may not be shown"]);
          const boxes = view.warnings.querySelectorAll(".box-warn");
          assert(!boxes[0].textContent.includes(skipped));
          assert(boxes[1].textContent.includes(skipped));
          clear(main);
          view = answer([], [skipped]);
          same(headings(view), ["Some decks short of these cards may not be shown"]);
          clear(main);
          for (const short_warnings of [[], undefined]) {
            view = answer([], short_warnings);
            same(headings(view), []);
            clear(main);
          }
        """)
