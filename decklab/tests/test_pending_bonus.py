"""Bonus-printing cautions are exact, home-scoped and never a purchase refusal."""
import json
import unittest
from unittest import mock

from decklab.lib import access, config, inventory, pool
from decklab.lib.api import shopping, shopping_queue
from decklab.lib.api.common import ApiError
from decklab.lib.inventory import bonus_warnings, files, model, orders, paths, rules
from decklab.tests import test_inventory_contract as contract
from decklab.tests import test_inventory_orders as support
from decklab.tests import test_shopping_orders as order_api
from decklab.tests import test_shopping_queue_manage_ui as queue_ui


COLUMNS = ("section", "name", "set", "collector_number", "finish", "quantity", "notes")
BONUS = {"section": "extras", "name": "Pick Your Poison", "set": "mkm", "collector_number": "170",
         "finish": "nonfoil", "quantity": "1", "notes": "bonus card in Fixture box"}


def snapshot(status="ordered", component="pending"):
    product = model.Product("bonus", COLUMNS, (model.ProductItem.make(BONUS, COLUMNS),), name="Fixture bonus box")
    return model.Inventory("bonus-fixture", products=(product,),
        collections={"home": model.Sheet("magic/collection.csv", tuple(rules.FIELDS), (), True)},
        watchlist=model.Sheet(paths.WATCHLIST, model.QUEUE_FIELDS, (), True),
        status=model.Sheet(paths.STATUS, tuple(rules.STATUS_FIELDS),
                           (model.StatusRow.make(file="bonus.csv", status=status),), True),
        orders=(model.Order.build("2026-11-11-box", components=[model.Component.build("box", "product", "bonus.csv", component)]),))


def product_csv():
    return rules.csv_bytes([BONUS], COLUMNS).decode("utf-8")


class BonusOperationTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(contract.fixture_world())
        self.inv = snapshot()

    def test_only_exact_pending_bonus_printings_match_not_other_finishes_any_or_display_cards(self):
        row = support.card("Pick Your Poison", "mkm", "170", 1)
        self.assertIn("expected as the bonus card in Fixture bonus box", bonus_warnings.messages(self.inv, [row])[0])
        for changed in ({"finish": "foil"}, {"collector_number": "171"}, {"printing": "any"}, {"set": ""}):
            self.assertEqual(bonus_warnings.messages(self.inv, [{**row, **changed}]), [])
        for inv in (snapshot("owned", "received"), snapshot("cancelled", "cancelled"), snapshot("ordered", "received")):
            self.assertEqual(bonus_warnings.messages(inv, [row]), [])
        display = self.inv.product("bonus")
        changed = self.inv.with_product(model.Product("bonus", COLUMNS,
            (model.ProductItem.make({**BONUS, "notes": "display commander"}, COLUMNS),), name=display.name))
        self.assertEqual(bonus_warnings.messages(changed, [row]), [])

    def test_queue_preview_and_save_add_the_same_rows_despite_the_warning(self):
        values = {"name": "Pick Your Poison", "set": "mkm", "collector_number": "170", "finish": "nonfoil",
                  "printing": "exact", "quantity": "2", "state": "ready"}
        after, summary = orders.set_queue(self.inv, add=True, values=values)
        self.assertEqual(after.watchlist.rows[0].quantity, "2")
        self.assertEqual(len(summary.extra["warnings"]), 1)
        self.assertEqual(after.orders, self.inv.orders)
        self.assertEqual(after.products, self.inv.products)
        self.assertEqual(after.collection(), self.inv.collection())

    def test_order_warns_for_a_pending_product_and_one_being_ordered_with_the_single(self):
        row = support.card("Pick Your Poison", "mkm", "170", 1)
        after, summary = orders.add_order(self.inv, record={"id": "2026-11-11-singles"}, cards={"rows": [row]},
            product={"stem": "second-box", "name": "Second bonus box", "columns": list(COLUMNS),
                     "rows": [BONUS], "status": "ordered"}, check_cards=False)
        self.assertEqual(len(summary.extra["warnings"]), 2)
        self.assertTrue(any("Second bonus box" in words for words in summary.extra["warnings"]))
        self.assertIsNotNone(after.order("2026-11-11-singles"))
        self.assertFalse(rules.extra_copies(after.order("2026-11-11-singles").audit_notes))
        self.assertEqual(summary.counts["cards"], 1)

    def test_pool_already_owned_warning_explains_bonus_and_keeps_extra_copies_explicit(self):
        inv = snapshot("owned", "received")
        inv = inv.with_collection("home", [model.CardRow.make({key: BONUS.get(key, "") for key in rules.FIELDS})])
        order = model.Order.build("2026-11-11-singles", components=[model.Component.build("cards", "cards", "2026-11-11-singles.csv")])
        inv = inv.with_order(order).set_component_rows(order.id, "cards", [support.card("Pick Your Poison", "mkm", "170", 1)])
        with inventory.pinned(inv):
            words = "\n".join(pool.load_pool().warnings)
        self.assertIn("also listed as the bonus card in Fixture bonus box", words)
        self.assertIn("order extra-copies 2026-11-11-singles cards", words)
        self.assertIn("nothing is marked automatically", words)
        self.assertFalse(rules.extra_copies(inv.order(order.id).audit_notes))

    def test_optional_unreadable_source_never_changes_the_operation_result(self):
        with mock.patch.object(bonus_warnings, "printing_map", side_effect=RuntimeError("private error")):
            after, summary = orders.set_queue(self.inv, add=True, values={"name": "Pick Your Poison", "quantity": "1", "state": "ready"})
        self.assertEqual(after.watchlist.rows[0].name, "Pick Your Poison")
        self.assertNotIn("private", summary.text)


class BonusApiTests(unittest.TestCase):
    start = order_api.OrderApiTests.start
    request = order_api.OrderApiTests.request
    preview = order_api.OrderApiTests.preview
    save = order_api.OrderApiTests.save

    def setUp(self):
        order_api.FileOrderApiTests.setUp(self)
        (self.root / "magic/products/precon.csv").write_text(product_csv(), encoding="utf-8")

    def test_order_preview_warns_without_writing_and_apply_still_succeeds(self):
        before = self.backend.load()
        shown = self.preview(cards={"rows": [support.card("Pick Your Poison", "mkm", "170", 1)]}, fulfils=[])
        self.assertTrue(any("expected as the bonus card in Precon" in text for text in shown["warnings"]))
        self.assertEqual(files.render(self.backend.load()), files.render(before))
        self.assertTrue(self.save(shown["preview"])["saved"])

    def test_catalog_is_only_returned_to_home_record_readers(self):
        configured = json.loads(config.CONFIG_FILE.read_text(encoding="utf-8"))
        for profile in configured["profiles"]:
            if profile["id"] == "user1":
                profile["role"] = "member"
            elif profile["id"] == "user2":
                profile["role"] = "admin"
        config.CONFIG_FILE.write_text(json.dumps(configured), encoding="utf-8")
        with access.using({"profile": "user1", "email": "", "remote": True}):
            shown = shopping.shopping_overview()
        self.assertEqual(shown["bonus_printings"][0]["products"], ["Precon"])
        with access.using({"profile": "user2", "email": "", "remote": True}), \
                mock.patch.object(bonus_warnings, "public_rows", side_effect=AssertionError("home source read")):
            with self.assertRaises(ApiError) as caught:
                shopping.shopping_overview()
        self.assertEqual(caught.exception.status, 403)

    def test_queue_add_returns_advice_and_retains_success_and_counts(self):
        body = {"profile": "matt", "action": "add", "expect": self.backend.load().revision,
                "values": {"name": "Pick Your Poison", "quantity": 1, "state": "ready", "for": "Bonus check",
                           "printing": "exact", "set": "mkm", "collector_number": "170", "finish": "nonfoil"}}
        answer = shopping_queue.save_queue_state(json.dumps(body))
        self.assertTrue(answer["saved"])
        self.assertIn("expected as the bonus card in Precon", answer["warnings"][0])
        self.assertEqual(answer["item"]["quantity"], 1)


class BonusCliTests(unittest.TestCase):
    setUp = support.CommandLineTests.setUp
    run_cli = support.CommandLineTests.run_cli
    file = support.CommandLineTests.file

    def test_watchlist_dry_run_and_save_both_warn_without_changing_exit_code(self):
        (self.root / "magic/products/precon.csv").write_text(product_csv(), encoding="utf-8")
        args = ("watchlist", "set", "--add", "--name", "Pick Your Poison", "--state", "ready", "--quantity", "1",
                "--printing", "exact", "--set", "mkm", "--number", "170", "--finish", "nonfoil", "--for", "Bonus check",
                "-m", "Queue a deliberate extra copy")
        before = self.backend.load().revision
        code, _, err = self.run_cli(*args, "--dry-run")
        self.assertEqual(code, 0, err)
        self.assertIn("expected as the bonus card in Precon", err)
        self.assertEqual(self.backend.load().revision, before)
        code, _, err = self.run_cli(*args)
        self.assertEqual(code, 0, err)
        self.assertIn("expected as the bonus card in Precon", err)

    def test_order_cards_fulfilling_queue_still_warn_and_save_as_requested(self):
        (self.root / "magic/products/precon.csv").write_text(product_csv(), encoding="utf-8")
        cards = self.file("bonus-single.csv", support.CARD_HEADER + "Pick Your Poison,mkm,170,nonfoil,1,,,\n")
        args = ("order", "add", "--id", "2026-11-11-bonus-single", "--cards", cards, "--fulfils", "#2", "-m", "Record deliberate single")
        code, _, err = self.run_cli(*args, "--dry-run")
        self.assertEqual(code, 0, err)
        self.assertIn("expected as the bonus card in Precon", err)
        code, _, err = self.run_cli(*args)
        self.assertEqual(code, 0, err)
        self.assertIn("expected as the bonus card in Precon", err)
        self.assertIsNotNone(self.backend.load().order("2026-11-11-bonus-single"))


@unittest.skipUnless(queue_ui.NODE, "Node.js is not installed")
class BonusUiTests(unittest.TestCase):
    run_js = queue_ui.ShoppingQueueManagementInteractionTests.run_js
    run_queue_js = queue_ui.ShoppingQueueManagementInteractionTests.run_queue_js

    def test_exact_printing_warns_before_add_and_any_printing_clears_it(self):
        self.run_queue_js(r'''
          const data=queueData([]);data.bonus_printings=[{set:'fdn',collector_number:'2',finish:'foil',products:['Fixture bonus box']}];
          pickPrinting=async()=>({set:'fdn',number:'2',finish:'foil'});let writes=0;apiWrite=async()=>{writes++;throw Error('Must not write yet');};
          drawShopping(data);const sheet=openAdd();type(sheet,'name','Alpha');
          const choose=sheet.body.querySelectorAll('button').find(node=>node.textContent.startsWith('Choose exact printing'));
          choose.click();await settle();const note=sheet.body.querySelector('.shop-bonus-warning');
          assert(!note.hidden);assert(note.textContent.includes('Expected as the bonus card in Fixture bonus box'));assert.equal(writes,0);
          sheet.body.querySelectorAll('button').find(node=>node.textContent==='Any printing').click();assert(note.hidden);
        ''')

    def test_other_finish_and_a_viewer_without_home_records_do_not_show_product_names(self):
        self.run_queue_js(r'''
          for(const scenario of ['finish','private']){
            clear(main);shopCloseQueueSheets();
            state.may={admin:true,orders:true,see_inventory:scenario==='private'?['user2']:['home'],see_home_records:scenario!=='private'};
            const data=queueData([]);data.bonus_printings=[{set:'fdn',collector_number:'2',finish:scenario==='finish'?'nonfoil':'foil',products:['Private fixture box']}];
            pickPrinting=async()=>({set:'fdn',number:'2',finish:'foil'});drawShopping(data);const sheet=openAdd();type(sheet,'name','Alpha');
            sheet.body.querySelectorAll('button').find(node=>node.textContent.startsWith('Choose exact printing')).click();await settle();
            assert(sheet.body.querySelector('.shop-bonus-warning').hidden);assert(!sheet.body.textContent.includes('Private fixture box'));
          }
        ''')
