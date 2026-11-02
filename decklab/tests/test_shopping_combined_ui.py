"""Shopping's Build decks together (E5-S28): choosing decks, the read-only combined list and late answers.
Run with python scripts/test_fixtures.py decklab.tests.test_shopping_combined_ui."""
import unittest

from decklab.tests import test_shopping_ui
from decklab.tests.test_workspace_ui import NODE


@unittest.skipUnless(NODE, "Node.js isn't installed")
class ShoppingCombinedTests(unittest.TestCase):
    run_js = test_shopping_ui.ShoppingInteractionTests.run_js

    def run_combined_js(self, scenario):
        self.run_js("""
          state.may = {admin: true, orders: true, see_inventory: ["home"]};
          const decks = [{id: "casual/alpha", title: "Alpha"}, {id: "casual/beta", title: "Beta"},
            {id: "commander/gamma", title: "Gamma"}];
          const data = (extra = {}) => ({...empty, queue_revision: "q1", to_buy: [], queue_decks: decks,
            decks_missing: [{id: "casual/alpha", title: "Alpha", kind: "casual", status: "building", missing: 7}],
            missing_cards: {ready: true, rows: [], errors: [], warnings: [], totals: {}}, ...extra});
          const answer = {ready: true, errors: [], warnings: [],
            decks: [{id: "casual/alpha", title: "Alpha", missing_alone: 7}, {id: "casual/beta", title: "Beta", missing_alone: 2}],
            rows: [{name: "Llanowar Elves", need: 8, available: 1, missing: 7, missing_alone: 6,
              on_the_way: [{source: "order incoming", copies: 1}], held_elsewhere: [{title: "Holding", copies: 1}],
              decks: [{id: "casual/alpha", title: "Alpha", need: 5, missing_alone: 4},
                      {id: "casual/beta", title: "Beta", need: 3, missing_alone: 2}], card: null}],
            totals: {cards: 1, copies: 7, copies_alone: 6, on_the_way: 1}};
          const section = () => main.querySelector("#shop-combined")?.closest("section");
          const sheet = () => document.body.querySelectorAll(".sheet").at(-1);
          const tick = id => {
            const box = sheet().querySelectorAll("input").find(input => input.getAttribute("data-combined-deck") === id);
            box.checked = !box.checked; box.fire("change");
          };
          const primary = () => sheet().querySelector(".btn-primary");
          apiWrite = async () => {throw new Error("Must not write");};
        """ + scenario)

    def test_choose_two_decks_then_show_the_combined_list(self):
        self.run_combined_js("""
          const reads = [];
          api = async path => {reads.push(path); return answer;};
          drawShopping(data());
          assert(section(), "the section shows with two or more decks to choose");
          section().querySelector(".shop-combined-choose").click();
          assert.equal(sheet().querySelectorAll("input").length, 3);
          assert(sheet().textContent.includes("7 cards missing on its own"));
          tick("casual/alpha");
          // One deck isn't enough: the primary can't act yet and says why.
          assert.equal(primary().getAttribute("aria-disabled"), "true");
          primary().click();
          same(reads, []);
          // ...and its click moves focus to the first deck still to tick.
          assert.equal(document.activeElement.getAttribute("data-combined-deck"), "casual/beta");
          tick("casual/beta");
          assert.equal(primary().getAttribute("aria-disabled"), null);
          primary().click();
          await null; await null; await null;
          same(reads, ["/api/shopping/combined?decks=" + encodeURIComponent("casual/alpha,casual/beta")]);
          const text = section().textContent;
          assert(text.includes("7 copies to buy"), text);
          assert(text.includes("1 more than the decks miss one at a time (6)"), text);
          const card = section().querySelector(".shop-combined-card");
          assert.equal(card.getAttribute("data-combined-card"), "Llanowar Elves");
          same(card.querySelector(".shop-missing-decks").querySelectorAll("li").map(li => li.textContent),
               ["Alpha ×5", "Beta ×3"]);
          assert(card.textContent.includes("1 more because the decks share it"));
          assert(card.textContent.includes("1 on the way (order incoming)"));
          assert(card.textContent.includes("Held by Holding ×1"));
          // Read-only: no queue action in the combined list.
          assert.equal(section().querySelectorAll(".shop-queue-write").length, 0);
          // A local redraw keeps the answer; Change decks… reopens with the choice ticked.
          section().querySelector(".shop-combined-choose").click();
          same(sheet().querySelectorAll("input").filter(input => input.checked).map(input => input.value),
               ["casual/alpha", "casual/beta"]);
        """)

    def test_fewer_than_two_decks_hides_the_section(self):
        self.run_combined_js("""
          drawShopping(data({queue_decks: [decks[0]]}));
          assert(!section());
        """)

    def test_unready_and_failed_answers_are_explicit(self):
        self.run_combined_js("""
          api = async () => ({...answer, ready: false, rows: [],
            errors: [{id: "casual/beta", title: "Beta", message: "This deck could not be read."}]});
          drawShopping(data());
          section().querySelector(".shop-combined-choose").click();
          tick("casual/alpha"); tick("casual/beta"); primary().click();
          await null; await null; await null;
          assert(section().textContent.includes("These decks could not be counted together."));
          assert(section().textContent.includes("This deck could not be read."));
          api = async () => {throw new ApiError(404, "No deck 'casual/beta'");};
          section().querySelector(".shop-combined-choose").click();
          primary().click();
          await null; await null; await null;
          assert(section().querySelector(".load-failed"), section().textContent);
          assert(section().textContent.includes("No deck 'casual/beta'"));
        """)

    def test_focus_moves_to_the_redrawn_change_decks_after_show_and_after_retry(self):
        self.run_combined_js("""
          const isChoose = () => document.activeElement && document.activeElement.isConnected
            && (document.activeElement.getAttribute("class") || "").includes("shop-combined-choose");
          let fail = true;
          api = async () => { if (fail) throw new ApiError(500, "Broken"); return answer; };
          drawShopping(data());
          section().querySelector(".shop-combined-choose").click();
          tick("casual/alpha"); tick("casual/beta"); primary().click();
          assert(isChoose(), "focus is on the busy section's button, not the body");
          await null; await null; await null;
          assert(section().querySelector(".load-failed"));
          assert(isChoose(), "focus survives the failed answer's redraw");
          fail = false;
          const retry = section().querySelector(".load-failed").querySelector("button");
          retry.focus(); retry.click();
          await null; await null; await null;
          assert(section().textContent.includes("7 copies to buy"));
          assert(isChoose(), "focus survives Retry and the answer's redraw");
          assert.equal(section().querySelector(".shop-combined-choose").textContent, "Change decks…");
        """)

    def test_an_answer_does_not_take_focus_moved_elsewhere(self):
        self.run_combined_js("""
          let finish;
          api = () => new Promise(resolve => {finish = resolve;});
          drawShopping(data());
          section().querySelector(".shop-combined-choose").click();
          tick("casual/alpha"); tick("casual/beta"); primary().click();
          const elsewhere = main.querySelector("#shop-on-the-way") || main.querySelector("a");
          elsewhere.focus();
          finish(answer);
          await null; await null; await null;
          assert(section().textContent.includes("7 copies to buy"));
          assert.equal(document.activeElement, elsewhere);
        """)

    def test_deck_links_filter_to_missing_only_where_the_deck_misses_something_alone(self):
        self.run_combined_js("""
          api = async () => ({...answer,
            decks: [{id: "casual/alpha", title: "Alpha", missing_alone: 7}, {id: "casual/beta", title: "Beta", missing_alone: 0}],
            rows: [{...answer.rows[0], decks: [{id: "casual/alpha", title: "Alpha", need: 5, missing_alone: 4},
                                                {id: "casual/beta", title: "Beta", need: 3, missing_alone: 0}]}]});
          drawShopping(data());
          section().querySelector(".shop-combined-choose").click();
          tick("casual/alpha"); tick("casual/beta"); primary().click();
          await null; await null; await null;
          const hrefs = node => node.querySelectorAll("a").map(a => a.getAttribute("href"));
          same(hrefs(section().querySelector(".shop-combined-decks")),
               [deckHref("casual/alpha") + "&tab=cards&filter=missing", deckHref("casual/beta") + "&tab=cards"]);
          same(hrefs(section().querySelector(".shop-missing-decks")),
               [deckHref("casual/alpha") + "&tab=cards&filter=missing", deckHref("casual/beta") + "&tab=cards"]);
        """)

    def test_an_otherwise_empty_page_keeps_its_empty_state_with_a_way_in(self):
        self.run_combined_js("""
          api = async () => answer;
          drawShopping(data({decks_missing: []}));
          assert(main.textContent.includes("Nothing to buy, and nothing on the way."));
          assert.equal(main.querySelector(".empty").querySelector("a").getAttribute("href"), "#/wishlist");
          assert(!section(), "no two-pane layout for the chooser alone");
          assert(!main.querySelectorAll("a").some(a => a.getAttribute("href") === "#shop-combined"));
          const start = main.querySelector(".shop-combined-start");
          assert.equal(start.textContent, "Build decks together…");
          start.focus(); start.click();
          tick("casual/alpha"); tick("casual/beta"); primary().click();
          await null; await null; await null;
          assert(section().textContent.includes("7 copies to buy"));
          assert.equal(main.querySelector(".empty").hidden, true);
          assert((document.activeElement.getAttribute("class") || "").includes("shop-combined-choose"));
        """)

    def test_a_late_answer_after_navigation_draws_nothing(self):
        self.run_combined_js("""
          let finish;
          api = () => new Promise(resolve => {finish = resolve;});
          drawShopping(data());
          section().querySelector(".shop-combined-choose").click();
          tick("casual/alpha"); tick("commander/gamma"); primary().click();
          routeToken += 1;
          clear(main).append(el("p", {text: "Another page"}));
          finish(answer);
          await null; await null;
          assert.equal(main.textContent, "Another page");
        """)


if __name__ == "__main__":
    unittest.main()
