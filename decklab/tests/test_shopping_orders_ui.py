"""Placed-order interactions under Node's DOM double; no device or live-data writes."""
import unittest

from decklab.tests import test_shopping_ui
from decklab.tests.test_workspace_ui import NODE


@unittest.skipUnless(NODE, "Node.js isn't installed")
class ShoppingOrderInteractionTests(unittest.TestCase):
    run_js = test_shopping_ui.ShoppingInteractionTests.run_js

    def order_js(self, scenario):
        self.run_js("""
          state.profile = {id: "matt", name: "Matt", role: "admin", space: "home"};
          state.may = {admin: true, orders: true, see_inventory: ["home"]};
          const data = {...empty, queue_revision: "revision-1", to_buy: [row("Alpha", {quantity: 3, queue_row: 1})]};
          const sheets = [], realSheet = openSheet;
          openSheet = (...args) => {const sheet = realSheet(...args); sheets.push(sheet); return sheet;};
          const latest = () => sheets.at(-1);
          const field = (sheet, key) => {
            const input = sheet.body.querySelector(`[data-order-field=${key}]`);
            assert(input, `Order field ${key}`); return input;
          };
          const type = (sheet, key, value) => {const input = field(sheet, key); input.value = value; input.fire("input");};
          const button = (node, text) => {const found = node.querySelectorAll("button").find(item => item.textContent === text);
            assert(found, `Button ${text}`); return found;};
          const action = (sheet, text) => button(sheet.foot, text);
          const settle = async () => {await null; await null; await null; await null;};
          const openOrder = () => {drawShopping(data); const button = main.querySelector(".shop-order-add");
            assert(button, "Record order button"); button.click(); return latest();};
          const paste = (sheet, text = "2 Alpha (FDN) 2 foil") => {type(sheet, "cards_text", text); button(sheet.body, "Add pasted cards").click();};
          const previewAnswer = {preview: "signed-preview", order: "2026-10-15-shop", revision: "revision-1",
            summary: "Order: 2 cards, 2 token cards, a product", counts: {cards: 2},
            checks: [{component: "cards", checks: ["Check the art"]}],
            watchlist_reduced: [{name: "Alpha", for: "Otters", quantity: 2, left: 1}],
            changes: ["Record pending cards"], tables: {written: [{id: "casual/otters", title: "Otters"}], skipped: [], error: null}, warnings: []};
          toast = () => {};
        """ + scenario)

    def test_order_form_needs_admin_home_permission_and_revision(self):
        self.order_js("""
          apiWrite = async () => {throw new Error("Must not write");};
          for (const profile of [{id: "user1", role: "member", space: "home"}, {id: "user2", role: "member", space: "user2"}]) {
            clear(main); state.profile = profile;
            state.may = {admin: false, orders: true, see_inventory: ["home"]}; drawShopping(data);
            assert.equal(main.querySelector(".shop-order-add"), null);
          }
          state.profile = {id: "matt", role: "admin", space: "home"};
          state.may = {admin: true, orders: true, see_inventory: ["home"]};
          clear(main); drawShopping({...data, queue_revision: null});
          assert.equal(main.querySelector(".shop-order-add"), null);
          clear(main); const sheet = openOrder();
          assert.equal(field(sheet, "ordered_on").value, "", "Don't guess the date of an existing order");
          assert.equal(sheet.foot.querySelectorAll("button").some(button => button.textContent === "Save order"), false);
        """)

    def test_search_printing_is_added_with_blank_condition_language(self):
        self.order_js("""
          const requests = [], writes = [];
          api = async path => {requests.push(path); return {cards: [{name: "Alpha"}]};};
          pickPrinting = async name => ({set: "fdn", number: "2", finish: "etched"});
          apiWrite = async (path, body) => {writes.push([path, body]); return previewAnswer;};
          const sheet = openOrder();
          type(sheet, "seller", "Card Shop"); type(sheet, "ordered_on", "2026-10-12");
          type(sheet, "card_name", "Alpha"); type(sheet, "card_quantity", "2"); flushTimers(); await settle();
          assert(requests.some(path => path.includes("/api/cards/search?q=Alpha")));
          button(sheet.body, "Choose printing and add…").click(); await settle();
          assert(sheet.body.textContent.includes("FDN 2 · etched"));
          type(sheet, "cards_checks", "Check the art");
          action(sheet, "Preview order").click(); await settle();
          assert.equal(writes[0][0], "/api/shopping/order/preview");
          const body = writes[0][1];
          same(body.cards.rows, [{name: "Alpha", set: "fdn", collector_number: "2", finish: "etched", quantity: 2,
            condition: "", language: "", notes: ""}]);
          assert.equal(body.expect, "revision-1");
          assert.equal(body.record.id, "2026-10-12-card-shop");
          assert(sheet.body.textContent.includes("Ordered 12 Oct"));
          assert(sheet.body.textContent.includes("2 × Alpha · FDN 2 · etched"));
          assert(sheet.body.textContent.includes("Check the art"));
          assert(sheet.body.textContent.includes("2 ordered, 1 left queued"));
          assert(sheet.body.textContent.includes("Otters"));
          assert(action(sheet, "Save order"));
        """)

    def test_paste_without_printing_needs_choice_and_invalid_quantities_keep_input(self):
        self.order_js("""
          const writes = []; apiWrite = async (path, body) => {writes.push(body); return previewAnswer;};
          const sheet = openOrder();
          type(sheet, "notes", "Keep this delivery note");
          paste(sheet, "2 Alpha");
          action(sheet, "Preview order").click(); await settle();
          assert.equal(writes.length, 0); assert(sheet.body.textContent.includes("Choose the ordered printing of Alpha"));
          pickPrinting = async () => ({set: "fdn", number: "2", finish: "nonfoil"});
          button(sheet.body, "Printing…").click(); await settle();
          const quantity = sheet.body.querySelector("[data-order-card-quantity=0]");
          quantity.value = "0"; quantity.fire("input"); action(sheet, "Preview order").click(); await settle();
          assert.equal(writes.length, 0); assert.equal(field(sheet, "notes").value, "Keep this delivery note");
          quantity.value = "2"; quantity.fire("input"); action(sheet, "Preview order").click(); await settle();
          assert.equal(writes.length, 1); assert.equal(writes[0].cards.rows[0].quantity, 2);
        """)

    def test_product_tokens_and_queue_confirm_together_then_save_only_preview(self):
        self.order_js("""
          const writes = [], messages = []; let refreshes = 0;
          route = () => {refreshes++;}; toast = words => messages.push(words);
          apiWrite = async (path, body) => {writes.push([path, body]); return path.endsWith("/preview") ? previewAnswer : {saved: true, tables: {error: null}};};
          const sheet = openOrder(); paste(sheet);
          type(sheet, "seller", "Shop"); type(sheet, "id", "2026-10-15-shop");
          const tokenCSV = "front,back,set,front_collector_number,back_collector_number,finish,quantity,front_details,back_details,notes\\nDog,Beast,,,,,2,,3/3,";
          const productCSV = "name,set,collector_number,finish,quantity,section,deck\\nAlpha,fdn,2,nonfoil,1,deck,First";
          type(sheet, "tokens_csv", tokenCSV); type(sheet, "tokens_checks", "Check the reverse");
          type(sheet, "product_stem", "fdc-product"); type(sheet, "product_name", "The Product");
          type(sheet, "product_csv", productCSV); field(sheet, "product_status").value = "preordered";
          field(sheet, "cards_extra").checked = true; field(sheet, "product_extra").checked = true;
          const chosen = sheet.body.querySelector("[data-order-fulfils=1]"); chosen.checked = true; chosen.fire("change");
          const quantity = sheet.body.querySelector("[data-order-fulfils-quantity=1]"); quantity.value = "2"; quantity.fire("input");
          action(sheet, "Preview order").click(); await settle();
          const body = writes[0][1];
          same(body.fulfils, [{row: 1, quantity: 2}]); same(body.extra_copies, ["cards", "fdc-product"]);
          same(body.tokens, {csv: tokenCSV, checks: ["Check the reverse"]});
          same(body.product, {stem: "fdc-product", name: "The Product", status: "preordered", csv: productCSV, checks: []});
          assert(sheet.body.textContent.includes("Dog,Beast")); assert(sheet.body.textContent.includes("The Product · preordered"));
          assert(sheet.body.textContent.includes("deck,First")); assert(!sheet.body.textContent.includes("null"));
          action(sheet, "Save order").click(); action(sheet, "Save order").click(); await settle();
          same(writes[1], ["/api/shopping/order/apply", {preview: "signed-preview"}]);
          assert.equal(writes.length, 2); assert(sheet.closed); assert.equal(refreshes, 1);
          assert(messages[0].includes("On the way"));
        """)

    def test_editing_invalidates_preview_and_stale_preview_cannot_save(self):
        self.order_js("""
          const writes = []; apiWrite = async (path, body) => {writes.push([path, body]); return previewAnswer;};
          const sheet = openOrder(); paste(sheet); action(sheet, "Preview order").click(); await settle();
          action(sheet, "Edit order").click();
          assert.equal(sheet.foot.querySelectorAll("button").some(button => button.textContent === "Save order"), false);
          type(sheet, "notes", "Changed after preview"); action(sheet, "Preview order").click(); await settle();
          field(sheet, "notes").value = "Changed without an event";
          action(sheet, "Save order").click(); await settle();
          assert.equal(writes.length, 2); assert(sheet.body.textContent.includes("Preview it again"));
          assert.equal(sheet.foot.querySelectorAll("button").some(button => button.textContent === "Save order"), false);
        """)

    def test_late_preview_and_profile_changes_cannot_save(self):
        self.order_js("""
          let resolve, writes = 0;
          apiWrite = () => {writes++; return new Promise(done => {resolve = done;});};
          const sheet = openOrder(); paste(sheet); action(sheet, "Preview order").click();
          type(sheet, "notes", "While waiting"); resolve(previewAnswer); await settle();
          assert.equal(sheet.foot.querySelectorAll("button").some(button => button.textContent === "Save order"), false);
          assert.equal(field(sheet, "notes").value, "While waiting");
          action(sheet, "Preview order").click(); state.profile = {id: "user1", role: "member", space: "home"};
          resolve(previewAnswer); await settle();
          assert.equal(writes, 2);
          assert.equal(sheet.foot.querySelectorAll("button").some(button => button.textContent === "Save order"), false);
        """)

    def test_failed_apply_keeps_fields_and_requires_new_preview_conflict_blocks_writes(self):
        self.order_js("""
          for (const code of [503, 409]) {
            clear(main); const writes = [];
            apiWrite = async (path, body) => {writes.push([path, body]);
              if (path.endsWith("/preview")) return previewAnswer;
              throw new ApiError(code, code === 409 ? "Inventory changed" : "Database unavailable");};
            const sheet = openOrder(); paste(sheet); type(sheet, "notes", "Don't discard this");
            action(sheet, "Preview order").click(); await settle(); action(sheet, "Save order").click(); await settle();
            assert(!sheet.closed); assert.equal(field(sheet, "notes").value, "Don't discard this");
            assert(sheet.body.textContent.includes("couldn't be saved"));
            assert.equal(sheet.foot.querySelectorAll("button").some(button => button.textContent === "Save order"), false);
            assert.equal(action(sheet, "Preview order").disabled, code === 409);
            if (code === 409) assert(button(sheet.body, "Refresh Shopping"));
            assert.equal(writes.length, 2); sheet.close();
          }
        """)

    def test_closing_pending_preview_releases_shopping_controls(self):
        self.order_js("""
          let resolve; apiWrite = () => new Promise(done => {resolve = done;});
          const sheet = openOrder(); paste(sheet); action(sheet, "Preview order").click();
          assert(main.querySelector(".shop-order-add").disabled);
          sheet.close(); resolve(previewAnswer); await settle();
          assert.equal(main.querySelector(".shop-order-add").disabled, false);
          assert.equal(document.body.querySelector(".shop-order-preview"), null);
          main.querySelector(".shop-order-add").click(); assert(!latest().closed);
        """)

    def test_csv_quoted_names_details_and_unclosed_quotes(self):
        self.order_js('''
          same(shopOrderCards('quantity,name,set,collector_number,finish,condition,language,notes\\n2,"Alpha, the Great",fdn,2,foil,,,"Check ""art"""'),
            [{name: "Alpha, the Great", set: "fdn", collector_number: "2", finish: "foil", quantity: "2", condition: "", language: "", notes: 'Check "art"'}]);
          assert.throws(() => shopOrderCSV('name,quantity\\n"Alpha,2'), /isn't closed/);
          assert.throws(() => shopOrderCSV('name,quantity\\nAlpha,2,extra'), /fields/);
        ''')


if __name__ == "__main__":
    unittest.main()
