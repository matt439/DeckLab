"""Split shipments through the real Shopping sheets; no browser or live data."""
import json
import subprocess
import unittest

from decklab.tests import test_shopping_order_edit_ui
from decklab.tests.test_workspace_ui import NODE, RUNNER, WEB


@unittest.skipUnless(NODE, "Node.js isn't installed")
class ShoppingOrderSplitInteractionTests(unittest.TestCase):
    edit_js = test_shopping_order_edit_ui.ShoppingOrderEditInteractionTests.edit_js

    def run_js(self, scenario):
        # Loading index.html's registered scripts also verifies the new sheet is
        # available in the production load order, without changing shared fixtures.
        setup = """
          clear(main);
          state.profiles = [{id: "user1", name: "User1", plays_as: "wife"}, {id: "matt", name: "Matt", plays_as: "user"}];
          state.profile = state.profiles[0]; location.hash = "#/shopping";
          closeEditor = () => {}; stopMatchupRefresh = () => {};
          const empty = {to_buy: [], orders: [], checks: [], warnings: []};
          const component = (extra = {}) => ({id: "cards", kind: "cards", status: "pending",
            quantity: 3, rows: 2, path: "magic/orders/private.csv", ...extra});
          const order = (extra = {}) => ({id: "2026-10-08-order", seller: "Card shop",
            ordered_on: "2026-10-08", status: "pending", components: [component()], ...extra});
        """
        result = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), setup + scenario, True]),
                                capture_output=True, text=True, encoding="utf-8", timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")

    def split_js(self, scenario):
        self.edit_js("""
          const originalCard = {name: "Llanowar Elves", set: "fdn", collector_number: "227", finish: "nonfoil",
            quantity: "3", condition: "", language: "", notes: "  Check, quoted notes\\nSecond line  "};
          const otherCard = {...originalCard, collector_number: "429", quantity: "1", finish: "foil", condition: "LP", language: "ja"};
          const originalToken = {front: "Rabbit", back: "Dog", set: "", front_collector_number: "",
            back_collector_number: "", finish: "", quantity: "2", front_details: "1/1; green; no lifelink",
            back_details: "colour unconfirmed; abilities unspecified", notes: "  pairing reported\\nprinting unconfirmed  "};
          pending.components = [component({edit_rows: [originalCard, otherCard], quantity: 4, extra_copies: true,
            checks: ["Inspect the art", "Original only check", "New only check"]}),
            component({id: "tokens", kind: "tokens", edit_rows: [originalToken], quantity: 2, checks: ["Check both faces"]}),
            component({id: "precon", kind: "product", checks: []})];
          const splitField = (sheet, key = "new_id") => {const input = sheet.body.querySelector(`[data-order-split-field=${key}]`);
            assert(input, `Split field ${key}`); return input;};
          const splitName = (sheet, value = "second-parcel") => {const input = splitField(sheet); input.value = value; input.fire("input");};
          const quantity = (sheet, row = 0) => {const input = sheet.body.querySelector(`[data-order-split-quantity=${row}]`);
            assert(input, `Split row ${row}`); return input;};
          const take = (sheet, value = "1", row = 0) => {const input = quantity(sheet, row); input.value = value; input.fire("input");};
          const check = (sheet, row, value) => {const input = sheet.body.querySelector(`[data-order-split-check=${row}]`);
            assert(input, `Split check ${row}`); input.value = value; input.fire("change");};
          const openSplit = (id = "cards") => {const parent = openEdit();
            parent.body.querySelector(`[data-order-check-component=${id}]`).querySelectorAll("button")
              .find(item => item.textContent === "Split shipment…").click(); return latest();};
          const splitAnswer = body => {
            const source = pending.components.find(part => part.id === body.component), remaining = [], moved = [];
            source.edit_rows.forEach((row, index) => {
              const amount = (body.take.find(item => item.row === index + 1) || {}).quantity || 0;
              if (Number(row.quantity) > amount) remaining.push({...row, quantity: String(Number(row.quantity) - amount)});
              if (amount) moved.push({...row, quantity: String(amount)});
            });
            return {...previewAnswer, summary: "Split the pending shipment", components: [
              {id: source.id, kind: source.kind, rows: remaining, extra_copies: source.extra_copies || false},
              {id: body.new_id, kind: source.kind, rows: moved, extra_copies: false}],
              checks: [{component: source.id, checks: source.checks.filter((_, i) => !body.move_checks.includes(i + 1))},
                {component: body.new_id, checks: source.checks.filter((_, i) => !body.keep_checks.includes(i + 1))}],
              tables: {written: [{id: "casual/elves", title: "Elves"}], skipped: [{id: "casual/old", title: "Old list"}], error: "Existing table needs attention"},
              warnings: ["Check the resulting parts before saving"]};
          };
        """ + scenario)

    def test_cards_checks_both_resulting_parts_and_tables_preview_before_token_only_save(self):
        self.split_js("""
          const writes = []; let refreshes = 0; route = () => {refreshes++;};
          apiWrite = async (path, body) => {writes.push([path, body]); return path.endsWith("/preview") ? splitAnswer(body) : {saved: true};};
          const sheet = openSplit();
          assert.equal(quantity(sheet).value, "0"); assert.equal(quantity(sheet).getAttribute("max"), "3");
          const details = sheet.body.querySelectorAll("[data-order-split-row]"); assert.equal(details.length, 2);
          for (const text of ["fdn", "227", "nonfoil", "Condition", "Language", "Not recorded", originalCard.notes])
            assert(details[0].textContent.includes(text), text);
          for (const text of ["429", "foil", "LP", "ja"]) assert(details[1].textContent.includes(text), text);
          assert(sheet.body.textContent.includes("new part will not have that confirmation"));
          assert.equal(sheet.body.querySelector("[data-order-split-check=0]").value, "both");
          splitName(sheet); take(sheet, "2"); take(sheet, "1", 1); check(sheet, 1, "original"); check(sheet, 2, "new");
          action(sheet, "Preview change").click(); await settle();
          same(writes[0], ["/api/shopping/order/change/preview", {expect: "revision-1", order: pending.id, action: "split",
            component: "cards", new_id: "second-parcel", take: [{row: 1, quantity: 2}, {row: 2, quantity: 1}], move_checks: [3], keep_checks: [2]}]);
          const preview = sheet.body.querySelector(".shop-order-preview"), sections = preview.querySelectorAll(".shop-order-section");
          assert(sections[0].textContent.includes("Remaining in original part"));
          assert(sections[0].textContent.includes("Confirmed as additional physical copies"));
          assert(sections[1].textContent.includes("New part")); assert(sections[1].textContent.includes("Component: second-parcel"));
          assert(sections[1].textContent.includes("Not confirmed as additional copies"));
          assert(sections[0].textContent.includes("Original only check")); assert(!sections[0].textContent.includes("New only check"));
          assert(sections[1].textContent.includes("New only check")); assert(!sections[1].textContent.includes("Original only check"));
          for (const section of sections) assert(section.textContent.includes("Inspect the art"));
          for (const text of [originalCard.notes, "Elves", "Old list", "Existing table needs attention", "Check the resulting parts"])
            assert(preview.textContent.includes(text), text);
          action(sheet, "Save change").click(); action(sheet, "Save change").click(); await settle();
          same(writes[1], ["/api/shopping/order/change/apply", {preview: "signed-change"}]);
          assert.equal(writes.length, 2); assert(sheet.closed); assert.equal(refreshes, 1);
          assert.equal(originalCard.quantity, "3"); assert.equal(otherCard.quantity, "1");
        """)

    def test_tokens_keep_complete_pairing_and_unknown_details_with_default_checks_on_both(self):
        self.split_js("""
          const writes = []; apiWrite = async (path, body) => {writes.push(body); return splitAnswer(body);};
          const sheet = openSplit("tokens"), details = sheet.body.querySelector("[data-order-split-row]");
          assert(sheet.body.textContent.includes("2 × Rabbit // Dog"));
          for (const text of ["Front face", "Back face", "Front collector number", "Back collector number", "Finish", "Not recorded",
              originalToken.front_details, originalToken.back_details, originalToken.notes]) assert(details.textContent.includes(text), text);
          splitName(sheet, "tokens-later"); take(sheet); action(sheet, "Preview change").click(); await settle();
          same(writes[0], {expect: "revision-1", order: pending.id, action: "split", component: "tokens", new_id: "tokens-later",
            take: [{row: 1, quantity: 1}], move_checks: [], keep_checks: []});
          const sections = sheet.body.querySelector(".shop-order-preview").querySelectorAll(".shop-order-section");
          for (const section of sections) for (const text of ["Rabbit", "Dog", originalToken.front_details, originalToken.back_details, "Check both faces"])
            assert(section.textContent.includes(text), text);
          assert.equal(originalToken.quantity, "2");
        """)

    def test_invalid_names_quantities_and_empty_parts_never_request_preview(self):
        self.split_js("""
          const writes = []; apiWrite = async (path, body) => {writes.push(body); return splitAnswer(body);};
          const sheet = openSplit(); take(sheet);
          for (const value of ["", "Second-Parcel", "two--parts", "two parts", "../part", " part", "part "]) {
            splitName(sheet, value); action(sheet, "Preview change").click(); await settle();
            assert.equal(writes.length, 0); assert(sheet.body.textContent.includes("lowercase letters"));
          }
          for (const value of ["cards", "tokens", "precon"]) {
            splitName(sheet, value); action(sheet, "Preview change").click(); await settle();
            assert.equal(writes.length, 0); assert(sheet.body.textContent.includes("already used"));
          }
          splitName(sheet);
          for (const value of ["", "-1", "1.5", "4", "Infinity", "1e0", " 1"]) {
            take(sheet, value); action(sheet, "Preview change").click(); await settle();
            assert.equal(writes.length, 0); assert(sheet.body.textContent.includes("whole number from 0 to 3"));
          }
          take(sheet, "0"); action(sheet, "Preview change").click(); await settle();
          assert(sheet.body.textContent.includes("Move at least one")); assert.equal(writes.length, 0);
          take(sheet, "3"); take(sheet, "1", 1); action(sheet, "Preview change").click(); await settle();
          assert(sheet.body.textContent.includes("Leave at least one")); assert.equal(writes.length, 0);
          take(sheet, "1"); check(sheet, 0, "invalid"); action(sheet, "Preview change").click(); await settle();
          assert(sheet.body.textContent.includes("which part needs each arrival check")); assert.equal(writes.length, 0);
        """)

    def test_pending_readable_rows_only_and_dirty_order_permission_guards(self):
        self.split_js("""
          const parent = openEdit(); type(parent, "seller", "Unsaved correction");
          button(parent.body, "Split shipment…").click(); assert.equal(sheets.length, 1);
          assert.equal(field(parent, "seller").value, "Unsaved correction");
          assert(parent.body.textContent.includes("Save or undo the order details before changing a component"));
          type(parent, "seller", "");
          for (const revoke of [() => {state.may.orders = false; state.may.admin = false;}, () => {state.may.see_inventory = [];},
              () => {state.profile = {id: "user1", role: "member", space: "home"};}]) {
            revoke(); button(parent.body, "Split shipment…").click(); assert.equal(sheets.length, 1);
            state.profile = {id: "matt", role: "admin", space: "home"}; state.may = {admin: true, orders: true, see_inventory: ["home"]};
          }
          parent.close();
          pending.components = [component({status: "received", edit_rows: [originalCard]}),
            component({id: "cancelled", status: "cancelled", edit_rows: [originalCard]}),
            component({id: "unreadable", edit_rows: null}), component({id: "empty", edit_rows: []}),
            component({id: "product", kind: "product", edit_rows: [originalCard]})];
          const sheet = openEdit(); assert(!sheet.body.textContent.includes("Split shipment…"));
        """)

    def test_eventless_edits_and_check_changes_require_a_new_preview(self):
        self.split_js("""
          const writes = []; apiWrite = async (path, body) => {writes.push(body); return splitAnswer(body);};
          const sheet = openSplit(); splitName(sheet); take(sheet); action(sheet, "Preview change").click(); await settle();
          quantity(sheet).value = "2"; action(sheet, "Save change").click(); await settle();
          assert.equal(writes.length, 1); assert(sheet.body.textContent.includes("Preview it again"));
          action(sheet, "Preview change").click(); await settle(); action(sheet, "Back to edit").click();
          check(sheet, 0, "new"); assert(!sheet.foot.textContent.includes("Save change"));
          action(sheet, "Preview change").click(); await settle(); same(writes[2].move_checks, [1]);
          splitField(sheet).value = "another-parcel"; action(sheet, "Save change").click(); await settle();
          assert.equal(writes.length, 3); assert(!sheet.foot.textContent.includes("Save change"));
        """)

    def test_late_preview_profile_route_close_and_edit_cannot_enable_save(self):
        self.split_js("""
          for (const leave of [() => {state.profile = {id: "user1", role: "member", space: "home"};},
              () => {routeToken++;}, () => {latest().close();}, () => {state.may.orders = false; state.may.admin = false;},
              () => {take(latest(), "2");}]) {
            state.profile = {id: "matt", role: "admin", space: "home"}; state.may.orders = true; state.may.admin = true; clear(main);
            let resolve; apiWrite = (path, body) => new Promise(done => {resolve = () => done(splitAnswer(body));});
            const sheet = openSplit(); splitName(sheet); take(sheet); action(sheet, "Preview change").click();
            assert(main.querySelector(".shop-order-edit").disabled); leave(); resolve(); await settle();
            assert(!sheet.foot.textContent.includes("Save change")); assert(!main.querySelector(".shop-order-edit").disabled);
            shopCloseQueueSheets();
          }
        """)

    def test_failed_save_keeps_split_draft_and_conflict_blocks_every_sheet(self):
        self.split_js("""
          for (const status of [503, 409]) {
            clear(main); const writes = [];
            apiWrite = async (path, body) => {writes.push([path, body]);
              if (path.endsWith("/preview")) return splitAnswer(body); throw new ApiError(status, "Save unavailable");};
            const sheet = openSplit(); splitName(sheet); take(sheet, "2"); check(sheet, 2, "new");
            action(sheet, "Preview change").click(); await settle(); action(sheet, "Save change").click(); await settle();
            assert(!sheet.closed); assert.equal(splitField(sheet).value, "second-parcel"); assert.equal(quantity(sheet).value, "2");
            assert.equal(sheet.body.querySelector("[data-order-split-check=2]").value, "new");
            assert.equal(action(sheet, "Preview change").disabled, status === 409);
            assert.equal(button(sheets.at(-2).body, "Split shipment…").disabled, status === 409);
            assert.equal(quantity(sheet).disabled, status === 409); assert(!sheet.foot.textContent.includes("Save change"));
            if (status === 409) assert(button(sheet.body, "Refresh Shopping"));
            assert.equal(writes.length, 2); shopCloseQueueSheets();
          }
        """)


if __name__ == "__main__":
    unittest.main()
