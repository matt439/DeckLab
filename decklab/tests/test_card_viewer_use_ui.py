"""The card viewer's deck-use line (E1-S29's first slice, web/card-viewer.js viewerUsePart) with the real page
functions and deterministic API promises: which pages ask, the words, a quick swipe, refusals and failures.

Run from the repo root: python scripts/test_fixtures.py decklab.tests.test_card_viewer_use_ui
"""
import json
import subprocess
import unittest

from decklab.tests.test_workspace_ui import NODE, RUNNER, WEB


@unittest.skipUnless(NODE, "Node.js isn't installed")
class ViewerUseLineTests(unittest.TestCase):
    def run_js(self, scenario):
        setup = """
          state.profiles = [{id: "matt", name: "Matt", space: "home"}, {id: "user2", name: "User2", space: "user2"}];
          state.profile = state.profiles[0];
          state.may = {see_inventory: ["home"]};
          const flush = async (n = 20) => { for (let i = 0; i < n; i++) await Promise.resolve(); };
          const elves = {name: "Llanowar Elves", type_line: "Creature — Elf Druid"};
          const lotus = {name: "Black Lotus", type_line: "Artifact"};
          const reads = [];
          const answers = {};
          api = (path) => { if (path.startsWith("/api/cards/rulings")) return Promise.resolve({available: true, rulings: []});
            reads.push(path); const a = answers[path];
            return a instanceof Error ? Promise.reject(a) : Promise.resolve(a); };
          const path = (name, space) => "/api/cards/decks?" + new URLSearchParams(space ? {name, space} : {name});
          // This DOM double's <dialog> has no showModal or close: open and shut it as the browser would.
          const show = (items) => { openCardViewer(items, 0); viewerDom.dialog.open = true; };
          const shut = () => { viewerDom.dialog.open = false; viewerClosed(); };
          const line = () => viewerDom.use;
          const shown = () => (line().hidden ? null : line().textContent);
          const answer = (extra = {}) => ({name: "Llanowar Elves", space: "home", basic: false, more: false,
            holds: [{id: "casual/elf-stompy", title: "Elf Stompy", why: "built", copies: 1},
                    {id: "product/fdn-beginner-box/cats", title: "Cats", why: "intact product", copies: 1}],
            wants: [{id: "casual/gruul-test", title: "Gruul Test", status: "building", copies: 6}],
            owned: 5, incoming: 0, free: 3, ...extra});
        """
        result = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), setup + scenario]),
                                capture_output=True, text=True, encoding="utf-8", timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")

    def test_deck_page_names_holders_first_then_wanters_and_free_copies(self):
        self.run_js("""
          location.hash = "#/deck?id=casual/gruul-test";
          answers[path("Llanowar Elves")] = answer();
          show([elves]);
          await flush();
          assert.deepEqual(reads, [path("Llanowar Elves")]);
          assert.equal(shown(), "In decks: Elf Stompy holds 1, Cats holds 1, Gruul Test wants 6 \\u00b7 3 free");
          // The line sits in the viewer's foot, after the opening list's own chips.
          const foot = viewerDom.foot.children;
          assert.equal(foot.indexOf(line()), foot.indexOf(viewerDom.marks) + 1);
          // The same card again in this opening isn't asked twice; a new opening asks afresh.
          show([elves]);
          await flush();
          assert.equal(reads.length, 1);
          shut();
          show([elves]);
          await flush();
          assert.equal(reads.length, 2);
        """)

    def test_words_for_no_decks_none_owned_on_the_way_many_decks_and_basic_lands(self):
        self.run_js("""
          location.hash = "#/deck?id=casual/gruul-test";
          const words = (extra) => viewerUseWords(answer(extra));
          assert.equal(words({holds: [], wants: [], owned: 0, free: 0}), "In no decks \\u00b7 none in the collection");
          assert.equal(words({holds: [], wants: [], owned: 0, free: 0, incoming: 2}), "In no decks \\u00b7 2 on the way");
          assert.equal(words({incoming: 1}),
                       "In decks: Elf Stompy holds 1, Cats holds 1, Gruul Test wants 6 \\u00b7 3 free \\u00b7 1 on the way");
          const many = Array.from({length: 6}, (_, i) => ({id: `casual/d${i}`, title: `D${i}`, status: "idea", copies: 1}));
          assert.equal(words({holds: [], wants: many}), "In decks: D0 wants 1, D1 wants 1, D2 wants 1, D3 wants 1, and 2 more decks \\u00b7 3 free");
          assert.equal(words({holds: [], wants: many.slice(0, 5)}), "In decks: D0 wants 1, D1 wants 1, D2 wants 1, D3 wants 1, and 1 more deck \\u00b7 3 free");
          assert.equal(words({holds: [], wants: many, more: true}), "In decks: D0 wants 1, D1 wants 1, D2 wants 1, D3 wants 1, and 2+ more decks \\u00b7 3 free");
          answers[path("Forest")] = {name: "Forest", space: "home", basic: true, holds: [], wants: [], owned: null, free: null};
          show([{name: "Forest", type_line: "Basic Land — Forest"}]);
          await flush();
          assert.equal(shown(), "Basic land: its copies in decks aren't tracked.");
        """)

    def test_a_members_deck_and_collection_page_ask_for_their_own_space(self):
        self.run_js("""
          state.profile = state.profiles[1];
          state.may = {see_inventory: ["user2"]};
          location.hash = "#/deck?id=user2/casual/r-elves";
          answers[path("Llanowar Elves", "user2")] = answer({space: "user2", holds: [], wants: []});
          show([elves]);
          await flush();
          assert.deepEqual(reads, [path("Llanowar Elves", "user2")]);
          shut();
          location.hash = "#/collection?view=rows";
          show([elves]);
          await flush();
          assert.deepEqual(reads, [path("Llanowar Elves", "user2"), path("Llanowar Elves", "user2")]);
          assert.equal(shown(), "In no decks \\u00b7 3 free");
        """)

    def test_no_request_without_the_spaces_inventory_or_off_the_two_pages(self):
        self.run_js("""
          // A public deck of a space whose inventory the viewer can't see: nothing asked, nothing shown.
          state.may = {see_inventory: ["user2"]};
          location.hash = "#/deck?id=casual/gruul-test";
          show([elves]);
          await flush();
          assert.deepEqual(reads, []);
          assert.equal(shown(), null);
          shut();
          state.may = {see_inventory: ["home"]};
          for (const hash of ["#/library", "#/wishlist", "#/shopping", "#/edit?id=casual/gruul-test"]) {
            location.hash = hash;
            show([elves]);
            await flush();
            shut();
          }
          assert.deepEqual(reads, []);
        """)

    def test_a_quick_swipe_never_shows_another_cards_decks(self):
        self.run_js("""
          location.hash = "#/deck?id=casual/gruul-test";
          let release;
          api = (p) => { if (p.startsWith("/api/cards/rulings")) return Promise.resolve({available: true, rulings: []});
            reads.push(p); return p === path("Llanowar Elves")
            ? new Promise((resolve) => { release = () => resolve(answer()); })
            : Promise.resolve(answer({name: "Black Lotus", holds: [], wants: [], owned: 1, free: 1})); };
          show([elves, lotus]);
          goViewer(1);
          await flush();
          assert.equal(shown(), "In no decks \\u00b7 1 free");
          release();
          await flush();
          assert.equal(shown(), "In no decks \\u00b7 1 free", "the slow answer for the card swiped away is dropped");
        """)

    def test_refusals_show_nothing_and_failures_say_so_and_are_asked_again(self):
        self.run_js("""
          location.hash = "#/deck?id=casual/gruul-test";
          answers[path("Llanowar Elves")] = new ApiError(403, "That collection isn't public.");
          show([elves]);
          await flush();
          assert.equal(shown(), null);
          shut();
          answers[path("Black Lotus")] = new ApiError(503, "The card data isn't ready yet.");
          show([lotus]);
          await flush();
          assert.equal(shown(), "Which decks use this card couldn't load.");
          answers[path("Black Lotus")] = answer({name: "Black Lotus", holds: [], wants: [], owned: 1, free: 1});
          drawViewer();
          await flush();
          assert.equal(shown(), "In no decks \\u00b7 1 free");
        """)


if __name__ == "__main__":
    unittest.main()
