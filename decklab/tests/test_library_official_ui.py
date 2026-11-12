"""The Decks page's Game Changer and ban changes panel (web/library-official.js, E9-S36): the cards the last card
data update changed, the viewer's Commander decks holding each with today's counted minimum and aim, and
hidden when there's nothing kept, no Commander deck or a failure.

Loads every page script into the event/DOM double (fixtures/workspace_ui_runner.js) with the API stubbed.

Run from the repo root: python scripts/test_fixtures.py decklab.tests.test_library_official_ui
"""
import unittest

from decklab.tests.test_library_ui import _Shelf
from decklab.tests.test_workspace_ui import NODE

OFFICIAL = r"""
  const CHANGED = { change: { recorded_at: "2026-11-10T09:00:00+00:00", old_date: "2026-11-03", new_date: "2026-11-10" },
    unread: 0,
    cards: [
      { name: "Rhystic Study", kind: "game_changer_added", words: "Became a Game Changer",
        now: { game_changer: true, banned: false },
        decks: [{ id: "commander/giada", title: "Giada", status: "building", version: "target", target_bracket: 2,
                  minimum: 3, label: "Bracket 3 or higher" }] },
      { name: "Sol Ring", kind: "game_changer_removed", words: "No longer a Game Changer",
        now: { game_changer: true, banned: false }, decks: [] },
      { name: "Black Lotus", kind: "banned", words: "Banned in Commander", now: null, decks: [] }] };
  const asked = [];
  function serve(answer) {
    api = async (path) => {
      asked.push(path);
      if (path === "/api/official-changes") {
        if (answer instanceof Error) throw answer;
        return answer;
      }
      throw new ApiError(404, "unexpected " + path);
    };
  }
  const official = () => main.querySelector("#official-changes");
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class LibraryOfficialTests(_Shelf):

    def run_js(self, scenario):
        super().run_js(OFFICIAL + scenario)

    def test_the_changed_cards_and_the_decks_holding_them(self):
        self.run_js("""
          as("matt", MAY.admin);
          serve(CHANGED);
          drawLibrary(DATA, libraryFilters(new URLSearchParams("all=1")));
          // Drawn with the shelf, hidden until its own request answers.
          assert(official().hidden);
          assert(tiles().length > 0);
          await flush();
          assert(!official().hidden);
          assert(asked.includes("/api/official-changes"));
          // After the Tables out of date list, before the filters.
          assert(main.children.indexOf(official()) < main.children.indexOf(main.querySelector(".lib-filters")));
          const details = official().querySelector("details");
          assert(details.open === true || details.getAttribute("open") !== null);     // a deck holds one: open
          assert.equal(official().querySelector("h2").textContent, "Game Changer and ban changes in the card data of 2026-11-10");
          const text = official().textContent;
          assert(text.includes("3 cards changed; 1 of your Commander decks holds one."));
          assert(text.includes("Compared with the card data of 2026-11-03."));
          assert(text.includes("Rhystic Study: Became a Game Changer."));
          const link = official().querySelectorAll("a")[0];
          assert.equal(link.getAttribute("href"), deckHref("commander/giada"));
          assert.equal(link.textContent, "Giada");
          assert(text.includes("(counted Bracket 3 or higher today; aiming at Bracket 2)"));
          assert(text.includes("Above its aim."));
          assert(official().querySelector(".lib-official-over"));
          // Today's data disagrees with the kept change: said, never hidden.
          assert(text.includes("Sol Ring: No longer a Game Changer. Today's card data lists it as one again."));
          assert(text.includes("None of your Commander decks hold it."));
          assert(text.includes("Black Lotus: Banned in Commander."));
          // Read-only: no buttons, no forms.
          assert.equal(official().querySelectorAll("button").length, 0);
        """)

    def test_no_deck_holding_a_card_leaves_it_closed(self):
        self.run_js("""
          as("matt", MAY.admin);
          serve({ ...CHANGED, cards: CHANGED.cards.map((c) => ({ ...c, decks: [] })), unread: 2 });
          drawLibrary(DATA, libraryFilters(new URLSearchParams("all=1")));
          await flush();
          assert(!official().hidden);
          const details = official().querySelector("details");
          assert(!(details.open === true || details.getAttribute("open") !== null));
          assert(official().textContent.includes("none of your Commander decks hold one."));
          assert(official().textContent.includes("2 Commander decks couldn't be read, so they weren't checked."));
        """)

    def test_nothing_kept_a_failure_or_no_commander_deck_leaves_it_hidden(self):
        self.run_js("""
          as("matt", MAY.admin);
          serve({ change: null });
          drawLibrary(DATA, libraryFilters(new URLSearchParams("all=1")));
          await flush();
          assert(official().hidden);
          assert.equal(official().children.length, 0);
          clear(main);
          serve(new ApiError(503, "There's no card data yet."));
          drawLibrary(DATA, libraryFilters(new URLSearchParams("all=1")));
          await flush();
          assert(official().hidden);
          assert(tiles().length > 0);
          // A shelf without a Commander deck doesn't ask at all.
          clear(main);
          asked.length = 0;
          serve(CHANGED);
          const casual = { ...DATA, decks: DATA.decks.filter((d) => d.kind !== "commander") };
          drawLibrary(casual, libraryFilters(new URLSearchParams("all=1")));
          await flush();
          assert(official().hidden);
          assert(!asked.includes("/api/official-changes"));
        """)

    def test_an_unknown_minimum_or_aim_says_so_plainly(self):
        self.run_js("""
          as("user1", MAY.user1);
          const held = { id: "commander/giada", title: "Giada", status: "idea", version: "target",
                         target_bracket: null, minimum: null, label: null };
          serve({ ...CHANGED, change: { ...CHANGED.change, old_date: null, new_date: null },
                  cards: [{ ...CHANGED.cards[2], decks: [held] }] });
          drawLibrary(DATA, libraryFilters(new URLSearchParams("all=1")));
          await flush();
          const text = official().textContent;
          assert.equal(official().querySelector("h2").textContent, "Game Changer and ban changes in the latest card data");
          assert(text.includes("The earlier card data's date isn't known."));
          assert(text.includes("Giada (its minimum couldn't be counted)"));
          assert(!text.includes("Above its aim."));
        """)


if __name__ == "__main__":
    unittest.main()
