"""Pending product corrections under the Shopping page's DOM double."""
import unittest

from decklab.tests import test_shopping_order_edit_ui
from decklab.tests.test_workspace_ui import NODE


@unittest.skipUnless(NODE, "Node.js isn't installed")
class ShoppingProductInteractionTests(unittest.TestCase):
    run_js = test_shopping_order_edit_ui.ShoppingOrderEditInteractionTests.run_js
    edit_js = test_shopping_order_edit_ui.ShoppingOrderEditInteractionTests.edit_js

    def product_js(self, scenario):
        self.edit_js("""
          const product = {name: "Old precon", format: "Commander", status: "preordered", notes: "  Keep this note  ",
            columns: ["name", "set", "collector_number", "finish", "quantity", "section", "deck", "notes"],
            rows: [{name: "Llanowar Elves", set: "fdn", collector_number: "227", finish: "nonfoil", quantity: "2",
              section: "deck", deck: "Elves", notes: '  Keep, "quotes"\\r\\nand lines  '}]};
          pending.components = [component({id: "precon", kind: "product", name: product.name,
            edit_product: product, extra_copies: false, checks: ["Inspect the tokens"]})];
          const productField = (sheet, key) => {const input = sheet.body.querySelector(`[data-order-product-field=${key}]`);
            assert(input, `Product field ${key}`); return input;};
          const productType = (sheet, key, value) => {const input = productField(sheet, key); input.value = value; input.fire("input");};
          const openProduct = () => {const parent = openEdit(); button(parent.body, "Correct product…").click(); return latest();};
          const writes = [];
          const productAnswer = body => ({...previewAnswer, summary: "Correct the pending product",
            component: {id: "precon", kind: "product", extra_copies: false, product: {...product, ...body.values}},
            checks: [{component: "precon", checks: ["Inspect the tokens"]}],
            tables: {written: [{id: "casual/elves", title: "Elves"}], skipped: [], error: null}});
          apiWrite = async (path, body) => {writes.push([path, body]); return path.endsWith("/preview") ? productAnswer(body) : {saved: true};};
        """ + scenario)

    def test_metadata_only_correction_preserves_list_and_shows_full_result_before_token_only_save(self):
        self.product_js("""
          const sheet = openProduct();
          assert.equal(productField(sheet, "status").value, "preordered");
          assert(productField(sheet, "csv").value.includes('"  Keep, ""quotes""\\r\\nand lines  "'));
          action(sheet, "Preview change").click(); await settle(); assert.equal(writes.length, 0);
          productType(sheet, "name", "Correct precon"); productType(sheet, "format", ""); productType(sheet, "status", "ordered");
          action(sheet, "Preview change").click(); await settle();
          same(writes[0][1], {expect: "revision-1", order: pending.id, action: "product", component: "precon",
            values: {name: "Correct precon", format: "", status: "ordered"}});
          const preview = sheet.body.querySelector(".shop-order-preview");
          for (const text of ["Correct precon", "Not recorded", "ordered", product.notes, "Llanowar Elves", "227",
              product.rows[0].notes, "Inspect the tokens", "Elves"]) assert(preview.textContent.includes(text), text);
          action(sheet, "Save change").click(); await settle();
          same(writes[1], ["/api/shopping/order/change/apply", {preview: "signed-change"}]); assert(sheet.closed);
          assert.equal(product.name, "Old precon"); assert.equal(product.format, "Commander");
        """)

    def test_replacement_csv_is_sent_exactly_and_empty_list_cannot_preview(self):
        self.product_js("""
          const sheet = openProduct(); productType(sheet, "csv", "  ");
          action(sheet, "Preview change").click(); await settle(); assert.equal(writes.length, 0);
          const csv = 'name,set,collector_number,finish,quantity,section,deck,notes\\nSol Ring,cmm,396,nonfoil,1,deck,New,"  quoted, note  "';
          productType(sheet, "csv", csv); action(sheet, "Preview change").click(); await settle();
          same(writes[0][1], {expect: "revision-1", order: pending.id, action: "product", component: "precon", values: {}, csv});
          action(sheet, "Back to edit").click(); productType(sheet, "notes", "Corrected note");
          action(sheet, "Preview change").click(); await settle(); assert.equal(writes[1][1].csv, csv);
          same(writes[1][1].values, {notes: "Corrected note"});
        """)

    def test_native_textarea_newline_normalization_does_not_replace_untouched_list_or_notes(self):
        self.product_js("""
          Object.defineProperty(Node.prototype, "value", {configurable: true, get() {return this.testValue || "";},
            set(value) {this.testValue = this.tag === "textarea" ? String(value).replace(/\\r\\n?/g, "\\n") : String(value);}});
          product.notes = "  first\\r\\nsecond  "; const sheet = openProduct();
          assert.equal(productField(sheet, "notes").value, "  first\\nsecond  ");
          assert(!productField(sheet, "csv").value.includes("\\r"));
          productType(sheet, "status", "ordered"); action(sheet, "Preview change").click(); await settle();
          same(writes[0][1].values, {status: "ordered"}); assert(!("csv" in writes[0][1]));
        """)

    def test_product_control_protects_dirty_order_and_pending_only_permissions(self):
        self.product_js("""
          const parent = openEdit(); type(parent, "seller", "Unsaved seller");
          button(parent.body, "Correct product…").click(); assert.equal(sheets.length, 1);
          assert(parent.body.textContent.includes("Save or undo the order details before changing a component"));
          type(parent, "seller", ""); state.may.orders = false; state.may.admin = false;
          button(parent.body, "Correct product…").click();
          assert.equal(sheets.length, 1); parent.close(); state.may.orders = true; state.may.admin = true;
          for (const status of ["received", "cancelled"]) {
            pending.components[0].status = status; const sheet = openEdit();
            assert(!sheet.body.textContent.includes("Correct product…")); sheet.close();
          }
        """)

    def test_failed_save_retains_product_draft_and_invalidates_preview(self):
        self.product_js("""
          for (const status of [503, 409]) {
            clear(main); apiWrite = async (path, body) => {writes.push([path, body]);
              if (path.endsWith("/preview")) return productAnswer(body); throw new ApiError(status, "Save unavailable");};
            const sheet = openProduct(); productType(sheet, "notes", "Retain my draft");
            action(sheet, "Preview change").click(); await settle(); action(sheet, "Save change").click(); await settle();
            assert(!sheet.closed); assert.equal(productField(sheet, "notes").value, "Retain my draft");
            assert.equal(action(sheet, "Preview change").disabled, status === 409);
            assert.equal(productField(sheet, "csv").disabled, status === 409);
            assert(!sheet.foot.textContent.includes("Save change")); shopCloseQueueSheets();
          }
        """)


if __name__ == "__main__":
    unittest.main()
