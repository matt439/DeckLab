"""Moving purchase-queue cards between Shopping's existing categories."""
import unittest

from decklab.tests import test_shopping_ui
from decklab.tests.test_workspace_ui import NODE


@unittest.skipUnless(NODE, "Node.js isn't installed")
class ShoppingQueueInteractionTests(unittest.TestCase):
    run_js = test_shopping_ui.ShoppingInteractionTests.run_js

    def run_queue_js(self, scenario):
        self.run_js("""
          state.may = {admin: true, orders: true, see_inventory: ["home"]};
          const queueRow = (n, extra = {}) => row(`Card ${n}`, {queue_row: n, ...extra});
          const queueData = rows => ({...empty, queue_revision: "queue-v1", to_buy: rows});
          const moveButton = n => main.querySelectorAll(".shop-category-move")
            .find(button => Number(button.dataset.queueRow) === n);
          const moveChoice = (n, label) => {
            const button = moveButton(n);
            assert(button, `Move control for queue row ${n}`);
            button.click();
            const menu = document.getElementById(button.getAttribute("aria-controls"));
            assert.equal(menu.hidden, false);
            const choice = menu.querySelectorAll("[role=menuitem]").find(item => item.textContent === label);
            assert(choice, `Move destination ${label}`);
            return choice;
          };
          const moveTo = async (n, label) => {moveChoice(n, label).click(); await null; await null;};
        """ + scenario)

    def test_moves_both_directions_preserve_card_details_and_viewer(self):
        self.run_queue_js("""
          const writes = [], messages = [];
          toast = text => messages.push(text);
          apiWrite = async (path, body) => {
            writes.push([path, body]);
            return {saved: true, row: body.row, state: body.state, revision: `queue-v${writes.length + 1}`};
          };
          const card = queueRow(3, {name: "Alpha", quantity: 4, for: "Old deck title", printing: "exact",
            set: "fdn", collector_number: "2", finish: "foil", listed_aud: "0.50", listed_at: "Card shop",
            in_stock: "no", checked: "2026-10-08", notes: "Keep this note", source: "magic/buylists/research.md",
            card: {name: "Alpha", type_line: "Creature", mana_cost: "", img_small: "/img/fdn/2/small"},
            deck: {id: "casual/otters", title: "Izzet Otters"}});
          const before = JSON.parse(JSON.stringify(card));
          drawShopping(queueData([card]));
          const viewer = main.querySelector("#shop-to-buy").closest("section").querySelector(".card-row"), control = moveButton(3);
          assert.equal(control.closest(".card-row"), null);
          assert.equal(control.closest(".shop-queue-row").querySelector(".card-row"), viewer);
          viewer.click();
          assert.equal(inspections.at(-1).card.name, "Alpha");
          const menu = moveChoice(3, "Long-term plan");
          assert.equal(inspections.length, 1);
          same(menu.parentNode.querySelectorAll("[role=menuitem]").map(item => item.textContent),
            ["Waiting for stock", "Waiting for reprint", "Deferred", "Long-term plan"]);
          menu.click(); await null; await null;
          assert.equal(main.querySelector("#shop-to-buy"), null);
          const later = main.querySelector("#shop-long-term").closest("section");
          assert(later.textContent.includes("Alpha"));
          assert(later.textContent.includes("4 cards"));
          assert(later.textContent.includes("Exact: FDN 2 foil"));
          assert(later.textContent.includes("A$0.50 at Card shop"));
          assert.equal(document.activeElement, moveButton(3));
          same({...card, state: before.state}, before);
          await moveTo(3, "Ready to buy");
          assert.equal(main.querySelector("#shop-long-term"), null);
          const immediate = main.querySelector("#shop-to-buy").closest("section");
          assert(immediate.textContent.includes("Izzet Otters"));
          assert(!immediate.textContent.includes("Ready to buy"));
          same(card, before);
          same(writes, [["/api/shopping/queue", {row: 3, state: "long_term", expect: "queue-v1"}],
            ["/api/shopping/queue", {row: 3, state: "ready", expect: "queue-v2"}]]);
          same(messages, ["Alpha moved to Long-term plan.", "Alpha moved to Ready to buy."]);
        """)

    def test_existing_states_update_chips_and_use_latest_revision(self):
        self.run_queue_js("""
          const writes = [];
          apiWrite = async (path, body) => {
            writes.push(body);
            return {saved: true, row: body.row, state: body.state, revision: `queue-v${writes.length + 1}`};
          };
          drawShopping(queueData([queueRow(1), queueRow(2)]));
          await moveTo(1, "Waiting for stock");
          assert(moveButton(1).closest(".shop-queue-row").querySelector(".card-row-chips").textContent.includes("Waiting for stock"));
          await moveTo(2, "Waiting for reprint");
          assert(moveButton(2).closest(".shop-queue-row").querySelector(".card-row-chips").textContent.includes("Waiting for reprint"));
          await moveTo(1, "Deferred");
          const moved = moveButton(1).closest(".shop-queue-row");
          assert(moved.querySelector(".card-row-chips").textContent.includes("Deferred"));
          assert(!moved.querySelector(".card-row-chips").textContent.includes("Waiting for stock"));
          same(writes, [{row: 1, state: "waiting_for_stock", expect: "queue-v1"},
            {row: 2, state: "waiting_for_reprint", expect: "queue-v2"},
            {row: 1, state: "deferred", expect: "queue-v3"}]);
        """)

    def test_only_authorized_viewers_with_revision_can_move(self):
        self.run_queue_js("""
          apiWrite = async () => {throw new Error("Must not write");};
          for (const may of [{admin: false, orders: false}, {admin: false, orders: true}, {admin: true, orders: false}]) {
            clear(main);
            state.may = may;
            drawShopping(queueData([queueRow(1), queueRow(2, {state: "long_term"})]));
            assert.equal(main.querySelectorAll(".shop-category-move").length, may.admin || may.orders ? 2 : 0);
            assert.equal(main.querySelector("#shop-to-buy").closest("section").querySelectorAll(".card-row").length, 1);
            assert.equal(main.querySelector("#shop-long-term").closest("section").querySelectorAll(".card-row").length, 1);
            assert.equal(main.querySelector("#shop-by-shop").closest("section").querySelectorAll(".shop-category-move").length, 0);
          }
          clear(main);
          drawShopping({...empty, to_buy: [queueRow(1)]});
          assert.equal(main.querySelector(".shop-category-move"), null);
          clear(main);
          drawShopping(queueData([row("No row identifier")]));
          assert.equal(main.querySelector(".shop-category-move"), null);
        """)

    def test_pending_move_serializes_other_rows_and_repeated_choices(self):
        self.run_queue_js("""
          const writes = [];
          let finish;
          apiWrite = (path, body) => {writes.push(body); return new Promise(resolve => {finish = resolve;});};
          const first = queueRow(1), second = queueRow(2);
          drawShopping(queueData([first, second]));
          const repeated = moveChoice(1, "Long-term plan");
          const other = moveChoice(2, "Deferred");
          repeated.click();
          assert(main.querySelectorAll(".shop-category-move").every(button => button.disabled));
          repeated.click(); other.click();
          same(writes, [{row: 1, state: "long_term", expect: "queue-v1"}]);
          assert.equal(first.state, "ready");
          assert.equal(second.state, "ready");
          finish({saved: true, row: 1, state: "long_term", revision: "queue-v2"});
          await null; await null;
          assert(main.querySelectorAll(".shop-category-move").every(button => !button.disabled));
          assert.equal(first.state, "long_term");
          assert.equal(second.state, "ready");
        """)

    def test_conflict_and_failure_keep_card_with_inline_refresh(self):
        self.run_queue_js("""
          let refreshes = 0;
          route = async () => {refreshes += 1;};
          for (const code of [409, 500]) {
            clear(main);
            const card = queueRow(1, {quantity: 2, notes: "Do not lose this"});
            const before = JSON.parse(JSON.stringify(card));
            const writes = [];
            apiWrite = async (path, body) => {writes.push(body); throw new ApiError(code, "Shopping changed meanwhile.");};
            drawShopping(queueData([card]));
            await moveTo(1, "Long-term plan");
            assert(main.querySelector("#shop-to-buy").closest("section").textContent.includes("Card 1"));
            assert.equal(main.querySelector("#shop-long-term"), null);
            same(card, before);
            const message = moveButton(1).closest(".shop-queue-row").querySelector("[role=alert]");
            assert.equal(message.hidden, false);
            assert(message.textContent.includes("Shopping changed meanwhile."));
            assert.equal(message.querySelector("button").textContent, "Refresh Shopping");
            assert.equal(document.activeElement, message.querySelector("button"));
            assert.equal(moveButton(1).disabled, code === 409);
            if (code === 409) {
              moveButton(1).click();
              assert.equal(writes.length, 1);
            }
            message.querySelector("button").click();
          }
          assert.equal(refreshes, 2);
        """)

    def test_late_move_success_and_failure_leave_navigation_alone(self):
        self.run_queue_js("""
          const messages = [];
          toast = text => messages.push(text);
          for (const fail of [false, true]) {
            clear(main);
            let finish, reject;
            const card = queueRow(1);
            apiWrite = () => new Promise((resolve, failure) => {finish = resolve; reject = failure;});
            drawShopping(queueData([card]));
            moveChoice(1, "Long-term plan").click();
            routeToken += 1;
            clear(main).append(el("p", {text: "Another page"}));
            if (fail) reject(new ApiError(409, "Changed elsewhere"));
            else finish({saved: true, row: 1, state: "long_term", revision: "queue-v2"});
            await null; await null;
            assert.equal(main.textContent, "Another page");
            assert.equal(card.state, "ready");
          }
          same(messages, []);
        """)

    def test_moves_preserve_expanded_long_term_groups_and_pending_followup_undo(self):
        self.run_queue_js("""
          const writes = [];
          apiWrite = async (path, body) => {
            writes.push([path, body]);
            return {saved: true, row: body.row, state: body.state, revision: `queue-v${writes.length + 1}`};
          };
          const deck = {id: "commander/alela", title: "Alela"};
          const planned = Array.from({length: 14}, (_, i) => queueRow(i + 1, {state: "long_term", deck}));
          drawShopping({...queueData([...planned, queueRow(15, {deck})]),
            orders: [order({id: "old", status: "received", components: [component({status: "received"})]})],
            checks: [{order_id: "old", component_id: "cards", status: "received", text: "Check the token"}],
            decks_missing: [{...deck, kind: "commander", player: "user", status: "idea", missing: 20, on_the_way: 0}]});
          const followup = main.querySelector(".shop-followup"), history = main.querySelector(".shop-history");
          history.setAttribute("open", "");
          followup.querySelector("button").click();
          assert.equal(followup.hidden, true);
          const undo = document.getElementById("toast-undo").querySelector("button");
          const group = main.querySelector(".shop-group");
          assert.equal(group.querySelectorAll(".card-row").length, 12);
          group.querySelectorAll("button").find(button => button.textContent === "Show all 14").click();
          assert.equal(group.querySelectorAll(".card-row").length, 14);
          await moveTo(15, "Long-term plan");
          assert.equal(main.querySelector(".shop-group").querySelectorAll(".card-row").length, 15);
          assert(main.querySelector(".shop-deck").textContent.includes("15 in the long-term plan"));
          assert.equal(main.querySelector(".shop-followup"), followup);
          assert.equal(followup.hidden, true);
          assert.equal(main.querySelector(".shop-history"), history);
          assert.equal(history.getAttribute("open"), "");
          assert.equal(document.getElementById("toast-undo").querySelector("button"), undo);
          undo.click();
          assert.equal(followup.hidden, false);
          assert.equal(document.activeElement, followup.querySelector("button"));
          await moveTo(1, "Ready to buy");
          assert.equal(main.querySelector(".shop-group").querySelectorAll(".card-row").length, 14);
          assert(main.querySelector(".shop-deck").textContent.includes("14 in the long-term plan"));
          flushTimers(); await null; await null;
          assert.equal(writes.length, 2);
          assert(writes.every(([path]) => path === "/api/shopping/queue"));
        """)


if __name__ == "__main__":
    unittest.main()
