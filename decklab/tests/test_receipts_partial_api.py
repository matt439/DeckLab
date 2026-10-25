"""Partial receipt HTTP contracts over disposable files and PostgreSQL fixtures only."""
import json
from unittest import mock

from decklab.lib import inventory
from decklab.lib.api import receipts
from decklab.lib.api.common import ApiError
from decklab.lib.inventory import receive
from decklab.tests import db_support, test_receipts_api as support

setUpModule = support.setUpModule
tearDownModule = support.tearDownModule


class PartialReceiptContract:
    request_data = support.WebReceiptTests.request_data
    prepare = support.WebReceiptTests.prepare
    record_web = support.WebReceiptTests.record_web

    def partial(self, component="cards"):
        data = self.request_data((component,))
        data["components"][0]["take"] = [{"row": 1, "quantity": 1}]
        return data

    def owned(self):
        return sum(row.qty for row in inventory.current().collection().rows if row.name == "Llanowar Elves")

    def test_preview_is_read_only_and_apply_reports_saved_remainder(self):
        before = inventory.current()
        preview = self.prepare(self.partial())
        self.assertEqual(inventory.current().revision, before.revision)
        assignment = {"source": "cards", "received": "cards-received-1", "pending": "cards",
                      "received_quantity": 1, "pending_quantity": 1}
        self.assertEqual(preview["assignments"], [assignment])
        self.assertEqual(preview["components"], ["cards-received-1"])
        self.assertEqual(preview["totals"][0][1]["cards"], 1)
        saved = self.record_web(preview)
        self.assertTrue(saved["received"])
        self.assertEqual(saved["assignments"], [assignment])
        self.assertEqual(saved["remaining"], [{"id": "cards", "kind": "cards", "quantity": 1},
                                              {"id": "tokens", "kind": "tokens", "quantity": 2},
                                              {"id": "kit", "kind": "product", "quantity": 10}])
        view = receipts.receipt_view("test")
        self.assertEqual(saved["fingerprint"], view["fingerprint"])
        self.assertNotEqual(saved["fingerprint"], receipts.fingerprint(before.revision))
        self.assertEqual(view["components"][0]["rows"][0]["quantity"], "1")
        self.assertEqual(self.owned(), 1)
        order = inventory.current().order("test")
        pending = next(c for c in order.components if c.id == "cards")
        arrived = next(c for c in order.components if c.id == "cards-received-1")
        self.assertEqual(pending.checks, ["Record the condition"])
        self.assertFalse(arrived.checks)
        self.assertEqual(arrived.verified_checks, ["Record the condition"])

    def test_fresh_preview_receives_the_remaining_copy_once(self):
        first = self.prepare(self.partial())
        self.record_web(first)
        second = self.prepare(self.request_data())
        self.assertEqual(second["assignments"], [{"source": "cards", "received": "cards", "pending": None,
                                                 "received_quantity": 1, "pending_quantity": 0}])
        result = self.record_web(second)
        self.assertNotIn("cards", [c["id"] for c in result["remaining"]])
        self.assertEqual(self.owned(), 2)
        for preview in (first, second):
            with self.assertRaises(ApiError) as caught:
                self.record_web(preview)
            self.assertEqual(caught.exception.status, 409)
        self.assertEqual(self.owned(), 2)

    def test_partial_token_receipt_counts_physical_cards_and_keeps_the_pairing(self):
        preview = self.prepare(self.partial("tokens"))
        result = self.record_web(preview)
        self.assertEqual(result["totals"][0][0], "physical tokens")
        self.assertEqual(result["totals"][0][1]["cards"], 1)
        self.assertEqual(next(c["quantity"] for c in result["remaining"] if c["id"] == "tokens"), 1)
        rows = inventory.current().token_set().rows
        self.assertEqual([(r.front, r.back, r.qty) for r in rows], [("Rabbit", "Rabbit", 1)])
        self.assertEqual(self.owned(), 0)

    def test_invalid_selections_leave_inventory_unchanged(self):
        revision = inventory.current().revision
        bad = [None, [], True, [1], [{}], [{"row": True}], [{"row": 0}], [{"row": "1"}],
               [{"row": 2}], [{"row": 1}, {"row": 1}], [{"row": 1, "quantity": 0}],
               [{"row": 1, "quantity": 3}], [{"row": 1, "quantity": True}],
               [{"row": 1, "quantity": "1"}], [{"row": 1, "unknown": 1}]]
        for take in bad:
            with self.subTest(take=take):
                data = self.partial()
                data["components"][0]["take"] = take
                with self.assertRaises(ApiError) as caught:
                    self.prepare(data)
                self.assertEqual(caught.exception.status, 400)
                self.assertEqual(inventory.current().revision, revision)
        self.assertEqual(self.owned(), 0)

    def test_partial_receipt_still_requires_component_inspection(self):
        data = self.partial()
        data["components"][0]["verified"] = False
        result = self.prepare(data)
        self.assertFalse(result["ready"])
        self.assertTrue(result["blockers"])
        self.assertEqual(self.owned(), 0)

    def test_products_are_indivisible_and_full_row_selection_needs_no_split(self):
        product = self.request_data(("kit",))
        product["components"][0]["take"] = [{"row": 1}]
        with self.assertRaises(ApiError) as caught:
            self.prepare(product)
        self.assertEqual(caught.exception.status, 400)
        data = self.request_data()
        data["components"][0]["take"] = [{"row": 1}]
        preview = self.prepare(data)
        self.assertEqual(preview["components"], ["cards"])
        self.assertIsNone(preview["assignments"][0]["pending"])
        self.record_web(preview)
        self.assertEqual(self.owned(), 2)

    def test_database_unavailability_leaves_preview_reusable(self):
        preview = self.prepare(self.partial())
        with mock.patch.object(inventory, "apply", side_effect=inventory.Unavailable("fixture outage")):
            with self.assertRaises(ApiError) as caught:
                self.record_web(preview)
        self.assertEqual(caught.exception.status, 503)
        self.assertEqual(self.owned(), 0)
        self.assertTrue((receipts._folder("receipt-previews") / (preview["preview"] + ".json")).exists())
        self.record_web(preview)
        self.assertEqual(self.owned(), 1)

    def test_inventory_change_rejects_old_form_and_preview_without_taking_rows(self):
        data = self.partial()
        preview = self.prepare(data)
        inventory.apply(receive.op("test", [{"id": "kit", "verified": False, "intact": "no"}], "2026-10-08"),
                        inventory.Actor("matt", "Matt", "home", "receipt"), "Fixture concurrent arrival")
        for action in (lambda: self.prepare(data), lambda: self.record_web(preview)):
            with self.assertRaises(ApiError) as caught:
                action()
            self.assertEqual(caught.exception.status, 409)
        self.assertEqual(self.owned(), 0)
        self.assertEqual(receipts.receipt_view("test")["components"][0]["rows"][0]["quantity"], "2")

    def test_profile_bound_preview_cannot_be_applied_by_another_admin(self):
        preview = self.prepare(self.partial())
        with self.assertRaises(ApiError) as caught:
            self.record_web(preview, profile="user1")
        self.assertEqual(caught.exception.status, 409)
        self.assertEqual(self.owned(), 0)

    def test_member_cannot_preview_or_apply_an_admins_partial_receipt(self):
        preview = self.prepare(self.partial())
        member = {"id": "user1", "name": "User1", "role": "member", "space": "home"}
        with mock.patch.object(receipts, "_writer", return_value=member):
            for action in (lambda: self.prepare(self.partial()), lambda: self.record_web(preview)):
                with self.assertRaises(ApiError) as caught:
                    action()
                self.assertEqual(caught.exception.status, 403)
        self.assertEqual(self.owned(), 0)


class FilesPartialReceiptTests(PartialReceiptContract, support.FilesReceiptCase):
    pass


class DatabasePartialReceiptTests(PartialReceiptContract, db_support.DbTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from decklab.db import profiles_sync
        from decklab.tests import test_inventory_contract as contract
        cls.contract = contract
        profiles_sync.sync(listed=contract.FIXTURE_PROFILES, dbname=cls.dbname)

    def setUp(self):
        from decklab.lib.inventory import pg
        from decklab.lib.state import pg as state_pg
        db_support.reset(self.dbname, db_support.INVENTORY_TABLES)
        case = support.FilesReceiptCase()
        case.setUp()
        self.addCleanup(case.doCleanups)
        self.contract._rewrite_adapted(case)
        pg.write_model(case.inventory.load(), self.contract.CLAUDE, "Import the fixture inventory",
                       contents=self.contract.import_contents(case.inventory.root), dbname=self.dbname,
                       decks=True)
        self.inventory = pg.PgInventory(dbname=self.dbname, breaker=state_pg.Breaker())
        self.addCleanup(inventory.use(self.inventory))
