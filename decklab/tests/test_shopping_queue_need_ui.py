"""To buy's read-only mark on queued cards the home decks no longer miss (E5-S37).

Runtime interaction checks with the shared DOM double: the words, the Edit and Remove
controls, no write from the mark itself, and marks dropped after a queue write.
"""
import unittest

from decklab.tests import test_shopping_ui
from decklab.tests.test_workspace_ui import NODE


@unittest.skipUnless(NODE, "Node.js isn't installed")
class ShoppingQueueNeedInteractionTests(unittest.TestCase):
    run_js = test_shopping_ui.ShoppingInteractionTests.run_js

    def run_need_js(self, scenario):
        self.run_js("""
          state.may = {admin: true, orders: true, see_inventory: ["home"]};
          toast = () => {};
          const covered = (extra = {}) => ({state: "covered", card: "Card 1", missing: 0, queued: 2, fewer: 2, rows: 1, ...extra});
          const fewer = (extra = {}) => ({state: "fewer", card: "Card 2", missing: 1, queued: 4, fewer: 3, rows: 1, ...extra});
          const queueRow = (n, extra = {}) => row(`Card ${n}`, {queue_row: n, source: "", ...extra});
          const queueData = rows => ({...empty, queue_revision: "queue-v1", to_buy: rows});
          const sheets = [], actualOpenSheet = openSheet;
          openSheet = (...args) => {const sheet = actualOpenSheet(...args); sheets.push(sheet); return sheet;};
          const latestSheet = () => sheets.at(-1);
          const notes = () => main.querySelectorAll(".shop-queue-need");
          const noteFor = n => notes().find(note => note.closest(".shop-queue-row").getAttribute("data-shop-queue") === String(n));
          const action = (sheet, text) => {
            const button = sheet.foot.querySelectorAll("button").find(item => item.textContent === text);
            assert(button, `Sheet action ${text}`);
            return button;
          };
          const settle = async () => {await null; await null; await null; await null;};
        """ + scenario)

    def test_covered_and_fewer_words_with_edit_and_remove_and_no_write(self):
        self.run_need_js("""
          apiWrite = async () => {throw new Error("The mark must not write");};
          drawShopping(queueData([queueRow(1, {queue_need: covered()}), queueRow(2, {quantity: 4, queue_need: fewer()}),
            queueRow(3)]));
          assert.equal(notes().length, 2);
          assert(noteFor(1).textContent.includes("No deck is missing this now"));
          assert(noteFor(2).textContent.includes("Decks now miss 3 fewer than queued: 1 copy of 4"));
          assert.equal(noteFor(3), undefined);
          const buttons = noteFor(1).querySelectorAll("button").map(button => button.textContent);
          same(buttons, ["Edit…", "Remove…"]);
          assert.equal(noteFor(1).closest(".card-row"), null, "The controls sit outside the card viewer");
          noteFor(1).querySelectorAll("button")[0].click();
          assert.equal(latestSheet().heading.textContent, "Card 1");
          assert(latestSheet().body.querySelector("[data-queue-field=quantity]"), "Edit opens the row's Details sheet");
          latestSheet().close();
          noteFor(2).querySelectorAll("button")[1].click();
          assert(latestSheet().heading.textContent.includes("Remove Card 2"));
        """)

    def test_several_rows_name_the_total_and_unknown_states_say_nothing(self):
        self.run_need_js("""
          drawShopping(queueData([queueRow(1, {queue_need: covered({rows: 2, queued: 3})}),
            queueRow(2, {queue_need: fewer({rows: 2})}), queueRow(4, {queue_need: {state: "other"}}), queueRow(5, {queue_need: null})]));
          assert(noteFor(1).textContent.includes("No deck is missing this now (3 queued across 2 rows)"));
          assert(noteFor(2).textContent.includes("1 copy of 4 across 2 rows"));
          assert.equal(notes().length, 2);
        """)

    def test_viewers_who_cannot_change_the_queue_see_the_words_only(self):
        self.run_need_js("""
          state.may = {admin: false, orders: false, see_inventory: ["home"]};
          drawShopping(queueData([queueRow(1, {queue_need: covered()})]));
          assert(noteFor(1).textContent.includes("No deck is missing this now"));
          assert.equal(noteFor(1).querySelectorAll("button").length, 0);
          clear(main);
          state.may = {admin: true, orders: true, see_inventory: ["home"]};
          drawShopping({...empty, to_buy: [queueRow(1, {queue_need: covered()})]});
          assert.equal(noteFor(1).querySelectorAll("button").length, 0, "No revision, no write controls");
        """)

    def test_remove_from_the_mark_saves_and_drops_that_cards_other_marks(self):
        self.run_need_js("""
          const writes = [];
          apiWrite = async (path, body) => {writes.push([path, body]);
            return {saved: true, action: body.action, row: body.row, revision: "queue-v2"};};
          drawShopping(queueData([queueRow(1, {name: "Opt", queue_need: covered({card: "Opt", rows: 2})}),
            queueRow(2, {name: "Opt", queue_need: covered({card: "Opt", rows: 2})}),
            queueRow(3, {queue_need: fewer({card: "Card 3"})})]));
          noteFor(1).querySelectorAll("button")[1].click();
          const confirm = latestSheet();
          confirm.body.querySelector("[data-queue-field=reason]").value = "A friend gave me one";
          action(confirm, "Remove card").click(); await settle();
          same(writes, [["/api/shopping/queue", {action: "remove", row: 1, reason: "A friend gave me one", expect: "queue-v1"}]]);
          assert(confirm.closed);
          assert.equal(notes().length, 1, "The other Opt row's mark waits for the next read");
          assert(noteFor(2).textContent.includes("Decks now miss"));
        """)

    def test_the_table_density_keeps_the_mark_in_the_name_cell(self):
        self.run_need_js("""
          const card = queueRow(1, {queue_need: covered()});
          const casual = shopQueueRow(card, "to-buy", true, null);
          const record = shopQueueTableRecord(card, casual, true, {data: {}});
          record.project(true);
          assert(record.tr.querySelector(".shop-q-name").querySelector(".shop-queue-need"));
          record.project(false);
          assert.equal(casual.querySelector(".shop-queue-need").parentNode, casual);
        """)


if __name__ == "__main__":
    unittest.main()
