"""Shopping's one write, POST /api/shopping/check (lib/api/shopping.py resolve_check): a received
delivery's follow-up check marked done through the inventory's order.checks operation (the same as
`python -m decklab.db order checks ID C --resolve N`), as one change by the profile, over a
disposable temp folder with the files backend. The permission side (an admin who sees home's
inventory) is in test_api_permissions."""
import json
from unittest import mock

from decklab.lib import inventory
from decklab.lib.api import shopping
from decklab.lib.api.common import ApiError
from decklab.lib.inventory import receive as receive_ops
from decklab.tests import test_receipts_api as receipts_support
from decklab.tests import test_receive_order as support

setUpModule = support.setUpModule
tearDownModule = support.tearDownModule

CHECKS = ["Record the condition", "Confirm the set symbol", "Record the condition"]


class ResolveCheckTests(receipts_support.FilesReceiptCase):

    def setUp(self):
        super().setUp()
        patcher = mock.patch.object(shopping, "_writer", lambda data: {"id": data.get("profile"), "name": "Tester", "role": "admin"})
        patcher.start()
        self.addCleanup(patcher.stop)
        # The cards arrive (their checks verified), then follow-ups are added to them, as on the PC.
        inventory.apply(receive_ops.op("test", [{"id": "cards", "verified": True,
                                                 "rows": receipts_support.receipts.receipt_view("test")["components"][0]["rows"]}],
                                       "2026-10-02"), support.TESTER, "receive test")
        for text in CHECKS:
            inventory.apply(inventory.Op("order.checks", {"order": "test", "component": "cards", "add": text}),
                            support.TESTER, "add a check")

    def resolve(self, check, component="cards", order="test", **extra):
        return shopping.resolve_check(json.dumps({"profile": "matt", "order": order, "component": component,
                                                  "check": check, **extra}))

    def record(self):
        return json.loads((self.magic / "orders/records/test.json").read_text(encoding="utf-8"))

    def component(self, component_id="cards"):
        return next(c for c in self.record()["components"] if c["id"] == component_id)

    def assertRefused(self, status, call, contains=""):
        with self.assertRaises(ApiError) as caught:
            call()
        self.assertEqual(caught.exception.status, status)
        self.assertIn(contains, str(caught.exception))

    def test_a_check_is_resolved_into_verified_checks_as_one_change(self):
        real, calls = inventory.apply, []

        def apply(op, actor, message, **kwargs):
            calls.append((op.kind, dict(op.params), actor, message, kwargs))
            return real(op, actor, message, **kwargs)
        with mock.patch.object(inventory, "apply", apply):
            answer = self.resolve("Confirm the set symbol")
        self.assertEqual(answer, {"resolved": True, "order": "test", "component": "cards",
                                  "checks": ["Record the condition", "Record the condition"]})
        self.assertEqual(len(calls), 1)
        kind, params, actor, message, kwargs = calls[0]
        # The command line's operation, by the check's number in the list as it was read.
        self.assertEqual((kind, params), ("order.checks", {"order": "test", "component": "cards", "resolve": 2}))
        self.assertEqual((actor.id, actor.source), ("matt", "web"))
        self.assertIn("order test", message)
        self.assertIsNotNone(kwargs.get("expected_revision"))
        component = self.component()
        self.assertEqual(component["checks"], ["Record the condition", "Record the condition"])
        self.assertEqual(component["verified_checks"], ["Record the condition", "Confirm the set symbol"])

    def test_the_same_text_twice_resolves_one_at_a_time(self):
        self.resolve("Record the condition")
        self.assertEqual(self.component()["checks"], ["Confirm the set symbol", "Record the condition"])
        self.resolve("Record the condition")
        self.assertEqual(self.component()["checks"], ["Confirm the set symbol"])
        self.assertEqual(self.component()["verified_checks"],
                         ["Record the condition", "Record the condition", "Record the condition"])

    def test_a_check_already_done_or_changed_is_a_conflict_and_writes_nothing(self):
        before = (self.magic / "orders/records/test.json").read_bytes()
        self.assertRefused(409, lambda: self.resolve("Record the conditions"), "already done")
        self.assertEqual((self.magic / "orders/records/test.json").read_bytes(), before)

    def test_the_inventory_moving_meanwhile_is_a_conflict(self):
        with mock.patch.object(inventory, "apply", side_effect=inventory.Conflict("moved on")):
            self.assertRefused(409, lambda: self.resolve("Confirm the set symbol"), "changed meanwhile")

    def test_a_pending_components_checks_wait_for_its_receipt(self):
        self.assertRefused(400, lambda: self.resolve("Check physical pairs", component="tokens"),
                           "hasn't been received")
        self.assertEqual(self.component("tokens")["checks"], ["Check physical pairs"])

    def test_a_cancelled_components_checks_say_it_was_cancelled(self):
        inventory.apply(inventory.Op("order.cancel", {"order": "test", "component": "tokens", "reason": "Not sent"}),
                        support.TESTER, "cancel the tokens")
        before = (self.magic / "orders/records/test.json").read_bytes()
        self.assertRefused(400, lambda: self.resolve("Check physical pairs", component="tokens"), "was cancelled")
        self.assertEqual((self.magic / "orders/records/test.json").read_bytes(), before)

    def test_unknown_orders_and_components_and_bad_bodies_are_refused(self):
        self.assertRefused(400, lambda: self.resolve("Record the condition", order="nope"))
        self.assertRefused(400, lambda: self.resolve("Record the condition", component="nope"))
        for bad in ("", "   ", 3, None, "x" * (shopping.MAX_CHECK + 1)):
            with self.subTest(check=bad):
                self.assertRefused(400, lambda: self.resolve(bad))
        self.assertRefused(400, lambda: self.resolve("Record the condition", extra="field"))

    def test_the_database_being_down_is_a_503(self):
        with mock.patch.object(inventory, "apply", side_effect=inventory.Unavailable("down")):
            self.assertRefused(503, lambda: self.resolve("Confirm the set symbol"))
