"""A receipt that corrected its order rows, undone through the real audit trail in disposable DBs (E11-S08)."""
from decklab.lib import inventory
from decklab.lib.inventory import order_fulfilment
from decklab.tests import test_inventory_undo_mixed as mixed
from decklab.tests import test_inventory_undo_mixed_pg as mixed_pg
from decklab.tests.test_inventory_undo_receipt_rows import SPLIT
from decklab.tests.test_order_fulfilment import queue

ORDER = mixed_pg.ORDER


class CorrectedReceiptUndoPgTests(mixed_pg.MixedUndoPgTests):
    """The mixed Undo tests' disposable database and helpers; their own tests aren't run again here."""

    def change(self, fn, message):
        inventory.apply(mixed._Set(fn), mixed_pg.ACTOR, message)

    def ledger(self):
        """Give the seeded order a fulfilment ledger, as order add --fulfils keeps one."""
        def give(inv):
            queued = inv.with_watchlist([queue("Treasure", 2, **{"for": "Tokens"})])
            return inv.with_order(order_fulfilment.record(queued, queued, inv.order(ORDER), [{"select": "#1", "quantity": 2}]))
        self.change(give, "Fixture ledger")

    def test_real_corrected_receipt_undo_puts_the_ordered_rows_and_ledger_back(self):
        self.ledger()
        before = self.persisted()
        change = self.receive([{"id": "tokens", "verified": True, "rows": SPLIT}])
        touched = {(row[0], row[1]) for row in self.sql(
            "select distinct table_name, op from audit.row_change where change_set_id=%s", (change,))}
        self.assertTrue({("order_token_item", "DELETE"), ("order_token_item", "INSERT"), ("purchase_order", "UPDATE")} <= touched)
        preview, answer = self.api(change)
        self.assertEqual(preview["components"][0]["corrected"], {"ordered": 1, "received": 2})
        self.assertEqual((answer["action"], answer["components"]), ("receipt_undo", 1))
        self.assertEqual(self.persisted(), before)
        again = self.receive([{"id": "tokens", "verified": True, "rows": SPLIT}])
        self.api(again)
        self.assertEqual(self.persisted(), before)

    def test_a_later_correction_refuses_and_writes_nothing(self):
        change = self.receive([{"id": "tokens", "verified": True, "rows": SPLIT}])
        self.change(lambda inv: inv.set_component_rows(ORDER, "tokens", [SPLIT[1], SPLIT[0]]), "Later correction")
        before, sets = self.persisted(), self.latest()
        with mixed_pg.access.using({"profile": "matt", "email": "matt@example.com", "remote": True}):
            with self.assertRaises(mixed_pg.activity_mixed_undo.ApiError) as caught:
                mixed_pg.activity_mixed_undo.mixed_undo_view(id=str(change))
        self.assertEqual(caught.exception.status, 409)
        self.assertEqual((self.persisted(), self.latest()), (before, sets))


for _name in dir(mixed_pg.MixedUndoPgTests):
    if _name.startswith("test_"):
        setattr(CorrectedReceiptUndoPgTests, _name, None)
