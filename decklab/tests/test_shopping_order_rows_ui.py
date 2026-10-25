"""Pending order corrections exercise the real page under Node's DOM double."""
import unittest

from decklab.tests import test_shopping_order_edit_ui
from decklab.tests.test_workspace_ui import NODE


@unittest.skipUnless(NODE, "Node.js isn't installed")
class ShoppingOrderRowsInteractionTests(unittest.TestCase):
    run_js = test_shopping_order_edit_ui.ShoppingOrderEditInteractionTests.run_js
    edit_js = test_shopping_order_edit_ui.ShoppingOrderEditInteractionTests.edit_js

    def rows_js(self, scenario):
        self.edit_js("""
          const originalCard = {name: "Llanowar Elves", set: "fdn", collector_number: "227", finish: "nonfoil",
            quantity: "2", condition: "", language: "", notes: "  Original, quoted note\\nSecond line  "};
          const originalToken = {front: "Rabbit", back: "Dog", set: "", front_collector_number: "",
            back_collector_number: "", finish: "", quantity: "2", front_details: "1/1; green; no lifelink",
            back_details: "colour unconfirmed; abilities unspecified", notes: "pairing reported, printing unconfirmed"};
          pending.components = [component({edit_rows: [originalCard], extra_copies: false, checks: ["Inspect the foil"]}),
            component({id: "tokens", kind: "tokens", edit_rows: [originalToken], quantity: 2, checks: []}),
            component({id: "precon", kind: "product", name: "Precon", extra_copies: true, checks: []})];
          const rowField = (sheet, key, row = 0) => {const input = sheet.body.querySelector(`[data-order-row=${row}][data-order-row-field=${key}]`);
            assert(input, `Row ${row} field ${key}`); return input;};
          const rowType = (sheet, key, value, row = 0) => {const input = rowField(sheet, key, row); input.value = value; input.fire("input");};
          const openRows = (label = "Correct card details…") => {const parent = openEdit(); button(parent.body, label).click(); return latest();};
          const correctionAnswer = (body) => ({...previewAnswer, summary: "Correct the pending card details",
            checks: pending.components.map(part => ({component: part.id, checks: part.checks})),
            component: {id: body.component, kind: body.component === "tokens" ? "tokens" : "cards",
              rows: body.rows, extra_copies: body.action === "extra_copies" ? !body.undo : false},
            warnings: ["Inspect the revised printing on arrival"],
            tables: {written: [{id: "casual/elves", title: "Elves"}], skipped: [{id: "casual/old", title: "Old list"}], error: null}});
        """ + scenario)

    def test_card_corrections_preserve_all_fields_and_show_exact_result_before_token_only_save(self):
        self.rows_js("""
          const writes = []; let refreshes = 0; route = () => {refreshes++;};
          apiWrite = async (path, body) => {writes.push([path, body]); return path.endsWith("/preview") ? correctionAnswer(body) : {saved: true};};
          const sheet = openRows();
          assert.equal(button(sheet.body, "Remove row").disabled, true);
          assert.equal(rowField(sheet, "condition").value, ""); assert.equal(rowField(sheet, "language").value, "");
          assert.equal(rowField(sheet, "notes").value, originalCard.notes);
          assert.equal(sheet.body.querySelector("[data-order-row-field=name]"), null);
          action(sheet, "Preview change").click(); await settle(); assert.equal(writes.length, 0);
          rowType(sheet, "condition", "LP"); action(sheet, "Preview change").click(); await settle();
          same(writes[0][1], {expect: "revision-1", order: pending.id, action: "edit", component: "cards",
            rows: [{...originalCard, quantity: 2, condition: "LP"}]});
          const preview = sheet.body.querySelector(".shop-order-preview");
          for (const text of [originalCard.notes, "collector number", "227", "LP", "Not recorded", "Inspect the foil", "Elves", "Old list",
              "Inspect the revised printing on arrival"]) assert(preview.textContent.includes(text), text);
          action(sheet, "Save change").click(); await settle();
          same(writes[1], ["/api/shopping/order/change/apply", {preview: "signed-change"}]);
          assert.equal(writes.length, 2); assert(sheet.closed); assert.equal(refreshes, 1);
          assert.equal(originalCard.condition, ""); assert.equal(originalCard.quantity, "2");
        """)

    def test_cards_can_split_printings_and_must_preserve_each_name_and_total(self):
        self.rows_js("""
          pending.components[0].edit_rows.push({...originalCard, name: "Sol Ring", collector_number: "1", quantity: "1"});
          const writes = []; apiWrite = async (path, body) => {writes.push([path, body]); return correctionAnswer(body);};
          const picks = []; pickPrinting = async (name, options) => {picks.push([name, options.current]);
            return {set: "m19", number: "314", finish: "foil"};};
          const sheet = openRows(); rowType(sheet, "condition", "LP");
          assert(sheet.body.querySelectorAll("button").filter(item => item.textContent === "Remove row").every(item => item.disabled));
          button(sheet.body, "Another printing…").click();
          assert.equal(sheet.body.querySelectorAll("[data-order-correction-row]").length, 3);
          assert.equal(rowField(sheet, "condition", 1).value, "LP");
          action(sheet, "Preview change").click(); await settle(); assert.equal(writes.length, 0);
          assert(sheet.body.textContent.includes("Keep the same total: 3 physical copies"));
          rowType(sheet, "quantity", "1"); rowType(sheet, "quantity", "2", 2);
          button(sheet.body, "Remove row").click();
          action(sheet, "Preview change").click(); await settle(); assert.equal(writes.length, 0);
          assert(sheet.body.textContent.includes("same total quantity of each card name"));
          rowType(sheet, "quantity", "2"); rowType(sheet, "quantity", "1", 1);
          button(sheet.body, "Another printing…").click(); rowType(sheet, "quantity", "1");
          sheet.body.querySelectorAll("button").filter(item => item.textContent === "Printing…")[1].click(); await settle();
          action(sheet, "Preview change").click(); await settle();
          assert.equal(writes.length, 1); const rows = writes[0][1].rows;
          assert.equal(rows.length, 3); same(rows.map(row => [row.name, row.quantity]), [["Llanowar Elves", 1], ["Llanowar Elves", 1], ["Sol Ring", 1]]);
          assert.equal(rows[1].set, "m19"); assert.equal(rows[1].collector_number, "314"); assert.equal(rows[1].finish, "foil");
          assert.equal(rows[1].notes, originalCard.notes); assert.equal(rows[1].language, "");
          same(picks, [["Llanowar Elves", {set: "fdn", number: "227", finish: "nonfoil"}]]);
        """)

    def test_token_pairing_printing_characteristics_and_notes_remain_exact(self):
        self.rows_js("""
          const writes = []; apiWrite = async (path, body) => {writes.push([path, body]); return correctionAnswer(body);};
          const sheet = openRows("Correct token details…");
          for (const key of Object.keys(originalToken).filter(key => key !== "quantity")) assert.equal(rowField(sheet, key).value, originalToken[key]);
          button(sheet.body, "Another row…").click(); rowType(sheet, "quantity", "1");
          rowType(sheet, "back", "Cat", 1); rowType(sheet, "front_details", "1/1; green; no lifelink", 1);
          rowType(sheet, "back_details", "P/T unknown; colour unconfirmed; abilities unspecified", 1);
          rowType(sheet, "notes", "  retain this\\nand this  ", 1);
          action(sheet, "Preview change").click(); await settle();
          const rows = writes[0][1].rows; assert.equal(writes[0][1].component, "tokens");
          same(rows[0], {...originalToken, quantity: 1});
          same(rows[1], {...originalToken, quantity: 1, back: "Cat",
            back_details: "P/T unknown; colour unconfirmed; abilities unspecified", notes: "  retain this\\nand this  "});
          assert(sheet.body.querySelector(".shop-order-preview").textContent.includes("no lifelink"));
          assert(sheet.body.querySelector(".shop-order-preview").textContent.includes("Cat"));
          action(sheet, "Back to edit").click(); rowType(sheet, "quantity", "1.5");
          action(sheet, "Preview change").click(); await settle(); assert.equal(writes.length, 1);
          assert(sheet.body.textContent.includes("whole number of physical copies"));
        """)

    def test_native_textarea_normalization_cannot_rewrite_untouched_stored_notes_or_details(self):
        self.rows_js("""
          Object.defineProperty(Node.prototype, "value", {configurable: true, get() {return this.testValue || "";},
            set(value) {this.testValue = this.tag === "textarea" ? String(value).replace(/\\r\\n?/g, "\\n") : String(value);}});
          originalCard.notes = "  first line\\r\\nsecond line  ";
          originalToken.front_details = "1/1; green; no lifelink\\r\\ncolour unconfirmed";
          originalToken.notes = "  reported pairing\\r\\nprinting not checked  ";
          const writes = []; apiWrite = async (path, body) => {writes.push(body); return correctionAnswer(body);};
          pickPrinting = async () => ({set: "m19", number: "314", finish: "foil"});
          const cards = openRows(); assert.equal(rowField(cards, "notes").value, "  first line\\nsecond line  ");
          button(cards.body, "Printing…").click(); await settle(); action(cards, "Preview change").click(); await settle();
          assert.equal(writes[0].rows[0].notes, originalCard.notes); shopCloseQueueSheets(); clear(main);
          const tokens = openRows("Correct token details…"); rowType(tokens, "back", "Cat");
          action(tokens, "Preview change").click(); await settle();
          assert.equal(writes[1].rows[0].front_details, originalToken.front_details);
          assert.equal(writes[1].rows[0].notes, originalToken.notes);
          action(tokens, "Back to edit").click(); rowType(tokens, "notes", "  corrected\\nnotes  ");
          action(tokens, "Preview change").click(); await settle(); assert.equal(writes[2].rows[0].notes, "  corrected\\nnotes  ");
        """)

    def test_additional_copy_mark_and_unmark_are_distinct_reviewed_actions(self):
        self.rows_js("""
          const writes = []; apiWrite = async (path, body) => {writes.push([path, body]); return correctionAnswer(body);};
          const sheet = openEdit(); button(sheet.body, "Confirm additional copies…").click(); const mark = latest();
          assert(mark.body.textContent.includes("rather than the same cards already added to the collection"));
          action(mark, "Preview change").click(); await settle();
          same(writes[0][1], {expect: "revision-1", order: pending.id, action: "extra_copies", component: "cards", undo: false});
          assert(mark.body.querySelector(".shop-order-preview").textContent.includes("Confirmed as additional physical copies"));
          mark.close(); button(sheet.body, "Unmark additional copies…").click(); const undo = latest();
          action(undo, "Preview change").click(); await settle();
          same(writes[1][1], {expect: "revision-1", order: pending.id, action: "extra_copies", component: "precon", undo: true});
          assert(undo.body.querySelector(".shop-order-preview").textContent.includes("Not confirmed as additional copies"));
          assert.equal(sheet.body.querySelectorAll("button").filter(item => item.textContent === "Confirm additional copies…").length, 1);
        """)

    def test_every_component_action_protects_dirty_record_and_pending_only_permissions(self):
        self.rows_js("""
          const sheet = openEdit(); type(sheet, "seller", "Unsaved details");
          for (const label of ["Correct card details…", "Correct token details…", "Confirm additional copies…", "Unmark additional copies…"]) {
            button(sheet.body, label).click(); assert.equal(sheets.length, 1);
            assert.equal(field(sheet, "seller").value, "Unsaved details");
            assert(sheet.body.textContent.includes("Save or undo the order details before changing a component"));
          }
          sheet.close(); pending.components.forEach(part => {part.status = "received";});
          const received = openEdit(); assert.equal(received.body.querySelector("[data-order-check-component]"), null); received.close();
          pending.components.forEach(part => {part.status = "pending";});
          const forbidden = openEdit(); state.may.admin = false; state.may.orders = false;
          button(forbidden.body, "Correct card details…").click(); assert.equal(latest(), forbidden);
          button(forbidden.body, "Confirm additional copies…").click(); assert.equal(latest(), forbidden);
        """)

    def test_async_picker_blocks_preview_invalidates_it_and_ignores_late_profile_route_or_close(self):
        self.rows_js("""
          for (const leave of [() => {state.profile = {id: "user1", role: "member", space: "home"};},
              () => {routeToken++;}, () => {latest().close();}, () => {state.may.admin = false; state.may.orders = false;}]) {
            state.profile = {id: "matt", role: "admin", space: "home"}; state.may.admin = true; state.may.orders = true; clear(main);
            const writes = []; apiWrite = async (path, body) => {writes.push([path, body]); return correctionAnswer(body);};
            let resolve; pickPrinting = () => new Promise(done => {resolve = done;});
            const sheet = openRows(); rowType(sheet, "notes", "Keep this draft"); button(sheet.body, "Printing…").click();
            assert.equal(action(sheet, "Preview change").disabled, true); action(sheet, "Preview change").click();
            assert.equal(writes.length, 0); leave(); resolve({set: "m19", number: "314", finish: "foil"}); await settle();
            assert.equal(sheet.body.querySelectorAll("button").some(item => item.textContent === "Save change"), false);
            assert.equal(rowField(sheet, "notes").value, "Keep this draft"); assert(!sheet.body.textContent.includes("m19 314")); sheet.close();
          }
          state.profile = {id: "matt", role: "admin", space: "home"}; state.may.admin = true; state.may.orders = true; clear(main);
          const writes = []; apiWrite = async (path, body) => {writes.push([path, body]); return correctionAnswer(body);};
          pickPrinting = async () => ({set: "m19", number: "314", finish: "foil"});
          const sheet = openRows(); rowType(sheet, "condition", "LP"); action(sheet, "Preview change").click(); await settle();
          action(sheet, "Back to edit").click(); button(sheet.body, "Printing…").click(); await settle();
          assert.equal(sheet.foot.querySelectorAll("button").some(item => item.textContent === "Save change"), false);
          action(sheet, "Preview change").click(); await settle(); assert.equal(writes[1][1].rows[0].set, "m19");
          rowField(sheet, "notes").value = "eventless draft"; action(sheet, "Save change").click(); await settle();
          assert.equal(writes.length, 2); assert(sheet.body.textContent.includes("Preview it again"));
        """)

    def test_failed_row_apply_retains_draft_and_stale_conflict_disables_all_component_controls(self):
        self.rows_js("""
          for (const code of [503, 409]) {
            clear(main); apiWrite = async (path, body) => {if (path.endsWith("/preview")) return correctionAnswer(body);
              throw new ApiError(code, "Database changed or unavailable");};
            const sheet = openRows("Correct token details…"); rowType(sheet, "back_details", "3/3; green; trample");
            action(sheet, "Preview change").click(); await settle(); action(sheet, "Save change").click(); await settle();
            assert(!sheet.closed); assert.equal(rowField(sheet, "back_details").value, "3/3; green; trample");
            assert.equal(action(sheet, "Preview change").disabled, code === 409);
            assert.equal(button(sheets.at(-2).body, "Correct card details…").disabled, code === 409);
            assert.equal(button(sheet.body, "Another row…").disabled, code === 409);
            if (code === 409) assert(button(sheet.body, "Refresh Shopping"));
            shopCloseQueueSheets();
          }
        """)


if __name__ == "__main__":
    unittest.main()
