"""Shopping's Build decks together (E5-S28): choosing decks, the combined list with each card's queue rows,
Queue these and late answers.
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
          assert(card.querySelectorAll('.shop-missing-count').every(count => count.closest('a')),
            'combined per-deck demand stays inside its deck link');
          assert(card.textContent.includes("1 more because the decks share it"));
          assert(card.textContent.includes("1 on the way (order incoming)"));
          assert(card.textContent.includes("Held by Holding ×1"));
          // Nothing queued for it yet; an admin is offered Queue these… (the only write control here).
          assert(card.textContent.includes("Not queued"));
          same(section().querySelectorAll(".shop-queue-write").map(button => button.textContent), ["Queue these…"]);
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

    def test_compare_groups_validates_choices_shows_partial_cost_and_reviews_only_one_group(self):
        self.run_combined_js("""
          const price = {covered: 1, wanted: 2, known_aud: "3.50", delivered_aud: null,
            shops: [{shop: "Test Shop", cards_aud: "3.50", postage_aud: null, rows: [{name: "Opt", copies: 1,
              printings: [{set: "TST", collector_number: "42", finish: "etched", copies: 1, price_aud: "3.50"}]}]}],
            weighed: false, search_ran: true, search_complete: false, postage_unknown: ["Test Shop"],
            uncovered: [{name: "Opt", copies: 1, shops: [{shop: "Test Shop", status: "short"}]}],
            snapshots: [{shop: "Test Shop", read: true, fetched_at: "2026-11-01T10:00:00Z"}]};
          const left = {ready: true, decks: decks.slice(0, 2), today_missing: 2, incoming: 2, buy: 0,
            cards: [{name: "Opt", incoming: 2, buy: 0, on_the_way: [{source: "Delivery A", copies: 2}]}]};
          const right = {ready: true, decks: [decks[0], decks[2]], today_missing: 2, incoming: 0, buy: 2, pricing: price};
          const urls = [], reviews = [];
          api = async url => {urls.push(url); return {left, right};};
          openQueueCombinedSheet = chosen => reviews.push(chosen.map(deck => deck.id));
          drawShopping(data({decks_missing: []}));
          main.querySelector(".shop-compare-choose").click();
          const boxes = sheet().querySelectorAll("fieldset").map(group => group.querySelectorAll("input"));
          const toggle = box => {box.checked = !box.checked; box.fire("change");};
          toggle(boxes[0][0]); toggle(boxes[0][1]);
          sheet().querySelectorAll("button").find(b => b.textContent === "Copy first group to second").click();
          assert.equal(primary().getAttribute("aria-disabled"), "true");
          assert(sheet().textContent.includes("Choose two different groups."));
          primary().click();
          same(urls, []);
          toggle(boxes[1][1]); toggle(boxes[1][2]);
          primary().click();
          await null; await null;
          same(urls, ["/api/shopping/compare?left=" + encodeURIComponent("casual/alpha,casual/beta")
            + "&right=" + encodeURIComponent("casual/alpha,commander/gamma")]);
          const cards = section().querySelectorAll(".shop-pair-card");
          assert.equal(cards.length, 2);
          assert(section().textContent.includes("Alpha + Beta only needs cards already on the way."));
          assert(cards[0].textContent.includes("Delivery A"));
          assert(cards[0].textContent.includes("2 on the way"));
          assert(cards[1].textContent.includes("Cost to finish unknown"));
          assert(cards[1].textContent.includes("1 of 2 copies covered"));
          assert(cards[1].textContent.includes("A$3.50"));
          assert(cards[1].textContent.includes("TST 42 etched"));
          assert(cards[1].textContent.includes("Queue review requests nonfoil copies."));
          assert(cards[1].textContent.includes("Postage unknown at Test Shop"));
          assert(cards[1].textContent.includes("Another basket could cost less."));
          assert(cards[1].textContent.includes("Opt"));
          assert.equal(cards[1].querySelector("time").getAttribute("datetime"), "2026-11-01T10:00:00Z");
          same(reviews, []);
          assert(!cards[0].querySelector("button"));
          cards[1].querySelector("button").click();
          same(reviews, [["casual/alpha", "commander/gamma"]]);
        """)

    def test_compare_summary_requires_comparable_delivered_quotes(self):
        self.run_combined_js("""
          const pricing = {delivered_aud: "12.30", weighed: true, search_complete: true, snapshots: [{read: true}]};
          const left = {ready: true, decks: decks.slice(0, 2), today_missing: 1, buy: 1, pricing};
          const right = {...left, decks: [decks[0], decks[2]], pricing: {...pricing, delivered_aud: "12.50"}};
          const summary = extra => shopCompareSummary([left, {...right, ...extra}]);
          assert(summary({}).includes("Alpha + Beta costs A$0.20 less"));
          for (const patch of [{weighed: false}, {search_complete: false}, {delivered_aud: null},
            {partial_shops: ["Test Shop"]}, {snapshots: [{read: true, unchecked: 1}]}]) {
            assert(summary({pricing: {...right.pricing, ...patch}}).includes("do not establish which costs less"));
          }
          assert(summary({buy: 0, today_missing: 0}).includes("Alpha + Gamma can be built now."));
          assert(summary({ready: false}).includes("could not be counted"));
        """)

    def test_late_comparison_cannot_replace_retry_or_redraw_after_navigation(self):
        self.run_combined_js("""
          const view = drawShopping(data()), ids = [decks.slice(0, 2).map(d => d.id), [decks[0].id, decks[2].id]];
          const pending = [];
          api = () => new Promise((resolve, reject) => pending.push({resolve, reject}));
          const first = shopCompareLoad(view, ids), second = shopCompareLoad(view, ids.slice().reverse());
          pending[1].reject(new ApiError(503, "Unavailable")); await second;
          pending[0].resolve({}); await first;
          assert(section().textContent.includes("Unavailable"));
          section().querySelector(".shop-compare-choose").click();
          same(sheet().querySelectorAll("fieldset")[0].querySelectorAll("input").filter(b => b.checked).map(b => b.value), ids[1]);
          const retry = shopCompareLoad(view, ids);
          routeToken++;
          clear(main).append(el("p", {text: "Another screen"}));
          pending[2].resolve({}); await retry;
          assert.equal(main.textContent, "Another screen");
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

    def test_each_card_shows_its_matching_queue_rows(self):
        self.run_combined_js("""
          api = async () => answer;
          drawShopping(data({to_buy: [row("Llanowar Elves", {quantity: 2, for: "Alpha", state: "long_term"}),
            row("Llanowar Elves", {quantity: 1, for: "Beta + Gamma"}), row("Opt", {for: "Alpha"})]}));
          section().querySelector(".shop-combined-choose").click();
          tick("casual/alpha"); tick("casual/beta"); primary().click();
          await null; await null; await null;
          const card = section().querySelector(".shop-combined-card");
          assert(card.textContent.includes("3 queued"), card.textContent);
          same(card.querySelector(".shop-missing-queue").querySelectorAll("li").map(li => li.textContent),
               ["2 queued · Long-term plan · Alpha · Any printing", "1 queued · Ready to buy · Beta + Gamma · Any printing"]);
        """)

    def test_queue_these_reviews_saves_once_and_reloads_with_the_same_decks(self):
        self.run_combined_js("""
          const reads = [], writes = [], toasts = [];
          toast = text => toasts.push(text);
          api = async path => {reads.push(path); return path === "/api/shopping" ? data() : answer;};
          const review = {ready: true, decks: answer.decks.map(({id, title}) => ({id, title})), for: "Alpha + Beta",
            revision: "rev-1", states: ["ready", "long_term"], totals: {cards: 1, copies: 3},
            rows: [{name: "Llanowar Elves", missing: 7, queued: 4, copies: 3, joins: null, decks: ["Alpha", "Beta"], card: null},
                   {name: "Elvish Mystic", missing: 2, queued: 2, copies: 0, joins: null, decks: ["Alpha"], card: null}]};
          apiWrite = async (path, body) => {
            writes.push([path, body]);
            return path === "/api/shopping/queue/combined" ? review
              : {saved: true, action: "add_combined", cards: 1, copies: 3, for: "Alpha + Beta", decks: ["casual/alpha", "casual/beta"]};
          };
          drawShopping(data());
          section().querySelector(".shop-combined-choose").click();
          tick("casual/alpha"); tick("casual/beta"); primary().click();
          await null; await null; await null;
          section().querySelector(".shop-combined-queue").click();
          await null; await null; await null;
          same(writes, [["/api/shopping/queue/combined", {decks: ["casual/alpha", "casual/beta"]}]]);
          const text = sheet().textContent;
          assert(text.includes("Queue these: Alpha + Beta"), text);
          assert(text.includes("3 copies to queue · 7 missing · 4 already queued for these decks · for Alpha, Beta"), text);
          assert(text.includes("Already queued (1)"), text);
          sheet().querySelectorAll("button").find(b => b.textContent === "Long-term").click();
          primary().click();
          for (let i = 0; i < 12; i++) await null;
          same(writes[1], ["/api/shopping/queue", {action: "add_combined", expect: "rev-1", decks: ["casual/alpha", "casual/beta"],
            state: "long_term", cards: [{name: "Llanowar Elves", copies: 3, joins: null}]}]);
          same(writes.map(w => w[0]).filter(path => path !== "/api/visit"), ["/api/shopping/queue/combined", "/api/shopping/queue"]);
          same(toasts, ["Queued 3 copies of 1 card for Alpha + Beta."]);
          // Shopping reloads (its queue now holds the rows) and works the same decks out again, once.
          same(reads, ["/api/shopping/combined?decks=" + encodeURIComponent("casual/alpha,casual/beta"), "/api/shopping",
                       "/api/shopping/combined?decks=" + encodeURIComponent("casual/alpha,casual/beta")]);
          assert(section().textContent.includes("7 copies to buy"));
          same(shopCombinedCarry, null);
        """)

    def test_queue_these_is_not_offered_without_the_queue_right_or_a_ready_answer(self):
        self.run_combined_js("""
          api = async () => answer;
          state.may = {admin: false, orders: false, see_inventory: ["home"]};
          state.profile.role = "admin";
          drawShopping(data());
          section().querySelector(".shop-combined-choose").click();
          tick("casual/alpha"); tick("casual/beta"); primary().click();
          await null; await null; await null;
          assert(section().textContent.includes("7 copies to buy"));
          assert(!section().querySelector(".shop-combined-queue"));
          state.may = {admin: true, orders: true, see_inventory: ["home"]};
          api = async () => ({...answer, ready: false, rows: [], errors: [{message: "Not ready."}]});
          section().querySelector(".shop-combined-choose").click();
          primary().click();
          await null; await null; await null;
          assert(!section().querySelector(".shop-combined-queue"));
        """)


if __name__ == "__main__":
    unittest.main()
