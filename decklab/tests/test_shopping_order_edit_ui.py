"""Correct order records and arrival checks under Node's DOM double."""
import unittest

from decklab.tests import test_shopping_ui
from decklab.tests.test_workspace_ui import NODE


@unittest.skipUnless(NODE, "Node.js isn't installed")
class ShoppingOrderEditInteractionTests(unittest.TestCase):
    run_js = test_shopping_ui.ShoppingInteractionTests.run_js

    def edit_js(self, scenario):
        self.run_js("""
          state.profile = {id: "matt", name: "Matt", role: "admin", space: "home"};
          state.may = {admin: true, orders: true, see_inventory: ["home"]};
          const pending = order({seller: "", ordered_on: "", notes: "Original notes", sources: ["magic/buylists/old.md"],
            components: [component({checks: ["Confirm the art", "Check the reverse"]}),
              component({id: "tokens", kind: "tokens", status: "received", checks: ["Inspect token"]})]});
          const data = {...empty, queue_revision: "revision-1", orders: [pending]};
          const sheets = [], realSheet = openSheet;
          openSheet = (...args) => {const sheet = realSheet(...args); sheets.push(sheet); return sheet;};
          const latest = () => sheets.at(-1);
          const field = (sheet, key) => {const input = sheet.body.querySelector(`[data-order-change-field=${key}]`);
            assert(input, `Order field ${key}`); return input;};
          const type = (sheet, key, value) => {const input = field(sheet, key); input.value = value; input.fire("input");};
          const button = (node, text) => {const found = node.querySelectorAll("button").find(item => item.textContent === text);
            assert(found, `Button ${text}`); return found;};
          const action = (sheet, text) => button(sheet.foot, text);
          const settle = async () => {await null; await null; await null; await null;};
          const openEdit = (other = data) => {drawShopping(other); button(main, "Edit order…").click(); return latest();};
          const previewAnswer = {preview: "signed-change", revision: "revision-1", order: pending.id,
            summary: "Correct this order's record", changes: ["Order record"],
            record: {seller: "", ordered_on: "", notes: "Updated delivery note", sources: ["magic/buylists/new.md"]},
            checks: [{component: "cards", checks: ["Confirm the art", "Check the reverse"]}],
            tables: {written: [], skipped: [], error: null}};
          toast = () => {};
        """ + scenario)

    def test_button_requires_admin_permission_home_inventory_and_exact_revision(self):
        self.edit_js("""
          for (const may of [{admin: false, orders: false, see_inventory: ["home"]},
              {admin: true, orders: true, see_inventory: ["user2"]}]) {
            clear(main); state.may = may; drawShopping(data); assert.equal(main.querySelector(".shop-order-edit"), null);
          }
          state.may = {admin: true, orders: true, see_inventory: ["home"]};
          clear(main); drawShopping({...data, queue_revision: null}); assert.equal(main.querySelector(".shop-order-edit"), null);
          clear(main); state.profile = {id: "user1", role: "member", space: "home"}; drawShopping(data);
          assert.equal(main.querySelector(".shop-order-edit"), null);
          state.profile = {id: "matt", role: "admin", space: "home"}; clear(main);
          drawShopping({...data, orders: [pending, order({id: "past", status: "received", components: [component({status: "received"})]}),
            order({id: "cancelled", status: "cancelled", components: [component({status: "cancelled"})]})]});
          assert.equal(main.querySelectorAll(".shop-order-edit").length, 3);
          const history = main.querySelector(".shop-history"); history.querySelector(".shop-order-edit").click();
          assert.equal(latest().body.querySelector("[data-order-check-component]"), null);
        """)

    def test_record_fields_preserve_unknowns_and_preview_all_effects_before_save(self):
        self.edit_js("""
          const writes = [], messages = []; let refreshes = 0;
          route = () => {refreshes++;}; toast = words => messages.push(words);
          apiWrite = async (path, body) => {writes.push([path, body]); return path.endsWith("/preview") ? previewAnswer : {saved: true};};
          const sheet = openEdit();
          assert.equal(field(sheet, "seller").value, ""); assert.equal(field(sheet, "ordered_on").value, "");
          assert.equal(field(sheet, "sources").value, "magic/buylists/old.md");
          type(sheet, "notes", "Updated delivery note");
          type(sheet, "sources", "magic/buylists/new.md\\n\\nmagic/decks/casual/otters.md");
          action(sheet, "Preview change").click(); await settle();
          same(writes[0], ["/api/shopping/order/change/preview", {expect: "revision-1", order: pending.id, action: "record",
            values: {notes: "Updated delivery note", sources: ["magic/buylists/new.md", "magic/decks/casual/otters.md"]}}]);
          assert(sheet.body.querySelector(".shop-order-preview").textContent.includes("Not recorded"));
          assert(sheet.body.querySelector(".shop-order-preview").textContent.includes("Updated delivery note"));
          assert(sheet.body.querySelector(".shop-order-preview").textContent.includes("magic/buylists/new.md"));
          assert(sheet.body.querySelector(".shop-order-preview").textContent.includes("Confirm the art"));
          action(sheet, "Save change").click(); action(sheet, "Saving…").click(); await settle();
          same(writes[1], ["/api/shopping/order/change/apply", {preview: "signed-change"}]);
          assert.equal(writes.length, 2); assert(sheet.closed); assert.equal(refreshes, 1); same(messages, ["Order updated."]);
        """)

    def test_check_add_and_numbered_withdraw_are_separate_pending_only_operations(self):
        self.edit_js("""
          const writes = []; apiWrite = async (path, body) => {writes.push([path, body]); return previewAnswer;};
          const sheet = openEdit();
          assert.equal(sheet.body.querySelectorAll("[data-order-check-component]").length, 1);
          button(sheet.body, "Add check…").click(); const add = latest();
          action(add, "Preview change").click(); await settle(); assert.equal(writes.length, 0);
          type(add, "check", "Inspect the finish"); action(add, "Preview change").click(); await settle();
          same(writes[0][1], {expect: "revision-1", order: pending.id, action: "checks", component: "cards", add: ["Inspect the finish"]});
          add.close();
          sheet.body.querySelectorAll("button").filter(item => item.textContent === "Withdraw…")[1].click();
          const withdraw = latest(); assert(withdraw.body.textContent.includes("Check 2: Check the reverse"));
          action(withdraw, "Preview change").click(); await settle();
          same(writes[1][1], {expect: "revision-1", order: pending.id, action: "checks", component: "cards", withdraw: [2]});
          assert.equal(field(sheet, "seller").value, "");
        """)

    def test_edit_invalidates_preview_and_eventless_edits_cannot_reuse_it(self):
        self.edit_js("""
          const writes = []; apiWrite = async (path, body) => {writes.push([path, body]); return previewAnswer;};
          const sheet = openEdit(); type(sheet, "notes", "First change"); action(sheet, "Preview change").click(); await settle();
          action(sheet, "Back to edit").click();
          assert.equal(sheet.foot.querySelectorAll("button").some(item => item.textContent === "Save change"), false);
          type(sheet, "notes", "Changed"); action(sheet, "Preview change").click(); await settle();
          field(sheet, "notes").value = "Changed without an event"; action(sheet, "Save change").click(); await settle();
          assert.equal(writes.length, 2); assert(sheet.body.textContent.includes("Preview it again"));
          assert.equal(action(sheet, "Preview change").disabled, false);
        """)

    def test_record_preview_sends_only_changed_fields_and_keeps_raw_values(self):
        self.edit_js("""
          const writes = []; apiWrite = async (path, body) => {writes.push([path, body]); return previewAnswer;};
          const sheet = openEdit({...data, orders: [{...pending, notes: "  old note  ", seller: " old seller "}]});
          action(sheet, "Preview change").click(); await settle();
          assert.equal(writes.length, 0); assert(sheet.body.textContent.includes("No order details have changed"));
          type(sheet, "seller", "  corrected seller  "); action(sheet, "Preview change").click(); await settle();
          same(writes[0][1].values, {seller: "  corrected seller  "});
          action(sheet, "Back to edit").click();
          type(sheet, "seller", ""); action(sheet, "Preview change").click(); await settle();
          same(writes[1][1].values, {seller: ""});
          assert.equal(field(sheet, "notes").value, "  old note  ");
        """)

    def test_check_actions_preserve_dirty_record_draft_until_saved_or_undone(self):
        self.edit_js("""
          const writes = []; let refreshes = 0;
          route = () => {refreshes++;};
          apiWrite = async (path, body) => {writes.push([path, body]); return path.endsWith("/preview") ? previewAnswer : {saved: true};};
          const sheet = openEdit(); type(sheet, "seller", "Unsaved correction");
          for (const label of ["Add check…", "Withdraw…"]) {
            button(sheet.body, label).click(); assert.equal(sheets.length, 1);
            assert(sheet.body.textContent.includes("Save or undo the order details before changing arrival checks"));
            assert.equal(field(sheet, "seller").value, "Unsaved correction");
          }
          assert.equal(writes.length, 0);
          type(sheet, "seller", ""); button(sheet.body, "Add check…").click(); const child = latest();
          assert.equal(sheets.length, 2); type(child, "check", "Check the finish");
          action(child, "Preview change").click(); await settle(); action(child, "Save change").click(); await settle();
          assert.equal(writes.length, 2); assert(child.closed); assert(sheet.closed); assert.equal(refreshes, 1);
          assert.equal(writes[0][1].action, "checks");
        """)

    def test_late_preview_profile_route_and_sheet_close_cannot_enable_save(self):
        self.edit_js("""
          for (const leave of [() => {state.profile = {id: "user1", role: "member", space: "home"};},
              () => {routeToken++;}, () => {latest().close();}]) {
            state.profile = {id: "matt", role: "admin", space: "home"}; clear(main);
            let resolve; apiWrite = () => new Promise(done => {resolve = done;});
            const sheet = openEdit(); type(sheet, "notes", "To preview"); action(sheet, "Preview change").click();
            assert.equal(main.querySelector(".shop-order-edit").disabled, true);
            leave(); resolve(previewAnswer); await settle();
            assert.equal(sheet.foot.querySelectorAll("button").some(item => item.textContent === "Save change"), false);
            assert.equal(main.querySelector(".shop-order-edit").disabled, false); sheet.close();
          }
          clear(main); let resolve; apiWrite = () => new Promise(done => {resolve = done;});
          const sheet = openEdit(); type(sheet, "notes", "To preview"); action(sheet, "Preview change").click(); type(sheet, "notes", "Edited while waiting");
          resolve(previewAnswer); await settle();
          assert.equal(sheet.foot.querySelectorAll("button").some(item => item.textContent === "Save change"), false);
          assert.equal(field(sheet, "notes").value, "Edited while waiting");
        """)

    def test_failed_writes_keep_drafts_and_conflict_blocks_every_order_control(self):
        self.edit_js("""
          for (const code of [503, 409]) {
            clear(main); const writes = [];
            apiWrite = async (path, body) => {writes.push([path, body]);
              if (path.endsWith("/preview")) return previewAnswer;
              throw new ApiError(code, code === 409 ? "Inventory changed" : "Database unavailable");};
            const sheet = openEdit(); type(sheet, "notes", "Keep my draft");
            action(sheet, "Preview change").click(); await settle(); action(sheet, "Save change").click(); await settle();
            assert(!sheet.closed); assert.equal(field(sheet, "notes").value, "Keep my draft");
            assert(sheet.body.textContent.includes("couldn't be saved"));
            assert.equal(sheet.foot.querySelectorAll("button").some(item => item.textContent === "Save change"), false);
            assert.equal(action(sheet, "Preview change").disabled, code === 409);
            assert.equal(main.querySelector(".shop-order-edit").disabled, code === 409);
            if (code === 409) assert(button(sheet.body, "Refresh Shopping"));
            assert.equal(writes.length, 2); sheet.close();
          }
        """)


if __name__ == "__main__":
    unittest.main()
