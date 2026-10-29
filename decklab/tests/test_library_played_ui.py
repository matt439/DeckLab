"""The library's last played words and the Not played lately sort (E1-S27, library.js deckPlayed and
libPlayedRank), in the event/DOM double with the API stubbed.

Run from the repo root: python scripts/test_fixtures.py decklab.tests.test_library_played_ui
"""
import unittest

from decklab.tests.test_library_ui import _Shelf
from decklab.tests.test_workspace_ui import NODE


@unittest.skipUnless(NODE, "Node.js isn't installed")
class LibraryPlayedTests(_Shelf):
    def test_a_tile_says_when_it_was_last_played_or_that_it_hasn_t_been(self):
        self.run_js("""
          as("matt", MAY.admin);
          const played = { "Gruul": { last: "2026-10-08", games: 3 }, "Angels": { last: null, games: 0 },
            "Vampires": { last: "2026-10-20", games: 1 } };
          const data = { ...DATA, decks: DECKS.map((d) => ({ ...d, played: played[d.title] ?? null })) };
          drawLibrary(data, libraryFilters(new URLSearchParams("all=1&format=casual")));
          const words = (title) => { const n = tile(title).querySelector(".deck-played"); return n ? n.textContent : null; };
          assert.equal(words("Gruul"), "Last played 2026-10-08 · 3 games");
          assert.equal(words("Vampires"), "Last played 2026-10-20 · 1 game");
          assert.equal(words("Angels"), "Not played at home yet");
          // Games that couldn't be read (null) say nothing, never "not played".
          assert.equal(words("Otters"), null);
        """)

    def test_not_played_lately_puts_never_played_first_then_the_oldest(self):
        self.run_js("""
          as("matt", MAY.admin);
          const decks = [deck("casual/a", "A", { played: { last: "2026-10-20", games: 2 } }),
            deck("casual/b", "B", { played: null }),
            deck("casual/c", "C", { played: { last: "2026-09-01", games: 5 } }),
            deck("casual/d", "D", { played: { last: null, games: 0 } }),
            deck("casual/e", "E", { played: { last: null, games: 0 } })];
          same(sortDecks(decks, "played").map((d) => d.title), ["D", "E", "C", "A", "B"]);
          same(libraryFilters(new URLSearchParams("sort=played")).sort, "played");
          drawLibrary({ ...DATA, decks }, libraryFilters(new URLSearchParams("all=1")));
          main.querySelector("#filter-sort").fire("change", { target: { value: "played" } });
          same(titles(), ["D", "E", "C", "A", "B"]);
          assert(main.querySelector("#filter-sort").querySelectorAll("option").map((o) => o.textContent)
            .includes("Sort: Not played lately"));
        """)
