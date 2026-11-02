"""An empty space's library (E11-S56): with no deck in the visitor's own space and no cards in its collection
(/api/decks' own_collection_empty), the empty state offers Add a precon, Import cards and New deck, a line each,
and the Collection page opens the asked sheet from #/collection?open=.

Loads every page script in its real order into the event/DOM double (fixtures/workspace_ui_runner.js), with
the API stubbed: no browser, server, inventory write or Forge run.

Run from the repo root: python scripts/test_fixtures.py decklab.tests.test_library_start_ui
"""
import json
import subprocess
import unittest

from decklab.tests.test_library_ui import SHELF
from decklab.tests.test_workspace_ui import NODE, RUNNER, WEB

START = SHELF + r"""
  const EMPTY = { warnings: [], halves: [], decks: [], own_collection_empty: true };
  const ways = () => {
    const box = main.querySelector(".lib-start");
    return box ? box.querySelectorAll("li").map((li) => [li.querySelector("a").textContent,
      li.querySelector("a").getAttribute("href"), li.querySelector(".lib-start-line").textContent]) : null;
  };
  const draw = (data, query = "") => { clear(main); drawLibrary(data, libraryFilters(new URLSearchParams(query))); };
  const FIND = { types: [], roles: [], total: 0, page: 1, pages: 1, note: "", warnings: [], cards: [] };
  // The runner's timers wait for flushTimers(); its history keeps no address, so this one writes it back.
  const tick = async () => { flushTimers(); await flush(); };
  history.replaceState = (_state, _title, url) => { if (url) location.hash = url; };
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class LibraryStartTests(unittest.TestCase):
    def run_js(self, scenario):
        result = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), START + scenario, True]),
                                capture_output=True, text=True, encoding="utf-8", timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")

    def test_an_empty_home_offers_the_three_ways_in_order_with_a_line_each(self):
        self.run_js("""
          for (const [who, query] of [["matt", ""], ["matt", "all=1"], ["user1", ""]]) {
            as(who, who === "matt" ? MAY.admin : MAY.user1);
            draw(EMPTY, query);
            const got = ways();
            same(got.map((w) => w[0]), ["Add a precon", "Import cards", "New deck"]);
            same(got.map((w) => w[1]), ["#/collection?open=precon", "#/collection?open=import", "#/new"]);
            assert(got[0][2].includes("precon") && got[1][2].includes("ManaBox, Moxfield or Deckbox"));
            assert(got.every((w) => w[2].length > 20));
            const box = main.querySelector(".lib-start");
            assert(box.matches(".empty"));
            assert(box.textContent.includes("There are no decks or cards here yet."));
            // Plain buttons: the head keeps the page's one New deck primary.
            assert(box.querySelectorAll("a").every((a) => a.getAttribute("class") === "btn"));
            assert(!main.textContent.includes("You don't play any decks yet."));
            assert(!main.textContent.includes("There are no decks yet."));
          }
        """)

    def test_a_members_empty_space_gets_the_same_start_in_their_own_space(self):
        self.run_js("""
          as("user2", MAY.user2);
          draw(EMPTY);
          same(ways().map((w) => w[1]), ["#/collection?open=precon", "#/collection?open=import", "#/new?space=user2"]);
          assert.equal(main.querySelector(".lib-nothing-public").textContent, "Nothing else is public yet.");
          // Another space's public deck doesn't make the member's own space any less empty.
          const theirs = deck("user4/casual/elves", "Elves", { space: "user4", player: null });
          draw({ ...EMPTY, decks: [theirs] });
          same(ways().map((w) => w[0]), ["Add a precon", "Import cards", "New deck"]);
        """)

    def test_only_the_ways_the_visitor_may_use_are_offered(self):
        self.run_js("""
          as("user2", { ...MAY.user2, spaces: [] });             // may make decks, not change the collection
          draw(EMPTY);
          same(ways().map((w) => w[0]), ["New deck"]);
          as("user2", { ...MAY.user2, create: [] });             // the collection only
          draw(EMPTY);
          same(ways().map((w) => w[0]), ["Add a precon", "Import cards"]);
          as("user2", { ...MAY.user2, spaces: [], create: [] }); // nothing: the usual empty state
          draw(EMPTY);
          assert.equal(ways(), null);
          assert(main.querySelector(".empty").textContent.includes("You don't play any decks yet."));
        """)

    def test_a_space_with_decks_or_cards_or_a_filter_keeps_the_usual_empty_states(self):
        self.run_js("""
          as("matt", MAY.admin);
          // Cards but no decks, or an answer that doesn't say (a script's, an older server's): no change.
          for (const data of [{ ...EMPTY, own_collection_empty: false }, { warnings: [], halves: [], decks: [] }]) {
            draw(data, "all=1");
            assert.equal(ways(), null);
            assert(main.querySelector(".empty").textContent.includes("There are no decks yet."));
          }
          // A deck of the space's own, even one the filters hide or someone else plays: no change.
          const hers = deck("commander/giada", "Giada", { kind: "commander", player: "wife", ...counts(0) });
          draw({ ...EMPTY, decks: [hers] });
          assert.equal(ways(), null);
          assert(main.querySelector(".empty").textContent.includes("You don't play any decks yet."));
          draw({ ...EMPTY, decks: [hers] }, "all=1&format=casual");
          assert.equal(ways(), null);
          assert(main.querySelector(".empty").textContent.includes("No decks match these filters."));
          // A product deck is home's too.
          const product = DECKS.find((d) => d.id.startsWith("product/"));
          draw({ ...EMPTY, decks: [product] }, "all=1&format=casual");
          assert.equal(ways(), null);
          // A filter or a search that empties an empty space's view says so, rather than how to start.
          for (const query of ["status=built", "all=1&format=commander", "q=elf"]) {
            draw(EMPTY, query);
            assert.equal(ways(), null, query);
            assert(main.querySelector(".empty").textContent.includes("No decks match these filters."), query);
          }
        """)

    def test_the_collection_page_opens_the_asked_sheet_once_where_it_may(self):
        self.run_js("""
          const paths = [];
          api = async (path) => { paths.push(path);
            return path.startsWith("/api/collection") ? { ...FIND, space: state.profile.space, editable: editable } : {}; };
          let editable = true;
          for (const [who, may, open, hash, title] of [
              ["matt", MAY.admin, "precon", "#/collection", "Add a precon to the collection"],
              ["user2", MAY.user2, "import", "#/collection?space=user2", "Import cards into User2's collection"]]) {
            as(who, may);
            location.hash = `#/collection?open=${open}`; route(); await flush(); await tick();
            const sheet = openDialog();
            assert(sheet && sheet.textContent.includes(title), document.body.textContent);
            assert.equal(location.hash, hash);                    // ?open= is gone: Back or a reload doesn't reopen it
            assert(paths.every((p) => !p.includes("open=")));
            colCloseSheets();
          }
          // Someone who may not change the collection: the page, no sheet; an unknown sheet: none either.
          for (const [ed, open] of [[false, "precon"], [true, "nonsense"]]) {
            editable = ed;
            as("matt", MAY.admin);
            const before = document.querySelectorAll("dialog").length;
            location.hash = `#/collection?open=${open}`; route(); await flush(); await tick();
            assert.equal(document.querySelectorAll("dialog").length, before, open);
            assert.equal(location.hash, "#/collection");
          }
          // Left before the sheet's turn came: it doesn't open over the next page.
          editable = true;
          location.hash = "#/collection?open=precon"; route(); await flush();
          const before = document.querySelectorAll("dialog").length;
          location.hash = "#/wishlist"; showWishlist = () => {}; noteVisit = () => {}; route(); await tick();
          assert.equal(document.querySelectorAll("dialog").length, before);
          assert.equal(location.hash, "#/wishlist");
        """)


if __name__ == "__main__":
    unittest.main()
