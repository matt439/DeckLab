"""Order cancellation/removal CLI contracts, over an isolated inventory fixture only."""
import contextlib
import io
import unittest
from unittest import mock

from decklab.db import __main__ as cli, inv_orders
from decklab.lib import inventory
from decklab.tests import test_inventory_orders as existing


class _Fixture(unittest.TestCase):
    setUp = existing.CommandLineTests.setUp
    run_cli = existing.CommandLineTests.run_cli
    file = existing.CommandLineTests.file

    def queue(self):
        return [(r.text("name"), r.text("quantity"), r.text("for")) for r in self.backend.load().watchlist.rows]

    def tracked(self):
        cards = self.file("cards.csv", existing.CARD_HEADER + "Elvish Mystic,cmm,648,nonfoil,2,,,\n")
        code, _, err = self.run_cli("order", "add", "--id", "2026-10-15-tracked", "--cards", str(cards),
                                   "--fulfils", "Elvish Mystic=2", "-m", "Order queued copies")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.queue()[0], ("Elvish Mystic", "1", "Elves"))
        return "2026-10-15-tracked"


class ParserAndReportTests(_Fixture):
    def test_cancel_opt_in_and_remove_mandatory_restoration_reach_the_shared_operations(self):
        for flag, restore in (([], False), (["--restore-queue"], True)):
            with self.subTest(restore=restore), mock.patch.object(inv_orders, "_run", return_value=1) as run:
                code, _, err = self.run_cli("order", "cancel", "2026-10-07-shop-a", "cards", "-m", "Cancel",
                                           "--reason", "Unavailable", *flag)
                self.assertEqual(code, 1, err)
                op = run.call_args.args[1]
                self.assertEqual(op.kind, "order.cancel")
                self.assertEqual(dict(op.params), {"order": "2026-10-07-shop-a", "component": "cards",
                                                  "reason": "Unavailable", "restore_queue": restore})
                self.assertTrue(run.call_args.kwargs["refresh"])
        with mock.patch.object(inv_orders, "_run", return_value=1) as run:
            self.run_cli("order", "remove", "2026-10-07-shop-a", "-m", "Remove", "--reason", "Duplicate")
        op = run.call_args.args[1]
        self.assertEqual(op.kind, "order.remove")
        self.assertEqual(dict(op.params), {"order": "2026-10-07-shop-a", "reason": "Duplicate", "restore_queue": True})
        self.assertTrue(run.call_args.kwargs["refresh"])

    def test_new_remove_accepts_actor_dry_run_force_and_requires_audit_fields(self):
        parser = cli.parser()
        args = parser.parse_args(["order", "remove", "x", "-m", "Duplicate", "--reason", "Wrong shop",
                                  "--actor", "matt", "--dry-run", "--force"])
        self.assertEqual(args.actor, "matt")
        self.assertTrue(args.dry_run and args.force)
        self.assertIs(args.func, inv_orders.order_remove)
        with contextlib.redirect_stderr(io.StringIO()):
            for argv in (("order", "remove", "x", "-m", "Remove"),
                         ("order", "remove", "x", "--reason", "Duplicate"),
                         ("order", "remove", "x", "-m", "Remove", "--reason", "Duplicate", "--no-restore-queue")):
                with self.subTest(argv=argv), self.assertRaises(SystemExit) as raised:
                    parser.parse_args(argv)
                self.assertEqual(raised.exception.code, 2)

    def test_blank_audit_messages_are_refused_even_for_dry_run(self):
        before = self.backend.load()
        for action in (("cancel", "2026-10-07-shop-a", "cards"), ("remove", "2026-10-07-shop-a")):
            for flags in ((), ("--dry-run",)):
                with self.subTest(action=action, flags=flags), mock.patch.object(inventory, "apply") as apply:
                    code, _, err = self.run_cli("order", *action, "-m", "  ", "--reason", "Duplicate", *flags)
                    self.assertEqual(code, 1, err)
                    self.assertIn("-m needs a message", err)
                    apply.assert_not_called()
        self.assertEqual(self.backend.load(), before)

    def said(self, queue, preview=False):
        out, err = io.StringIO(), io.StringIO()
        summary = inventory.Summary("Order changed", extra={"queue": queue})
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            inv_orders._report(summary, preview=preview)
        return out.getvalue(), err.getvalue()

    def test_known_restoration_reports_exact_rows_without_a_blanket_warning(self):
        row = {"name": "Pick Your Poison", "quantity": "2", "for": "Cats", "printing": "exact",
               "set": "mkm", "collector_number": "170", "finish": "nonfoil"}
        queue = {"known": True, "offered": [row], "restored": [row], "warnings": []}
        out, err = self.said(queue)
        self.assertIn("Restored to the queue: 2 x Pick Your Poison for Cats (exact: mkm 170 nonfoil)", out)
        self.assertEqual(err, "")
        out, err = self.said(queue, preview=True)
        self.assertIn("Would restore to the queue", out)
        self.assertNotIn("Restored", out)
        self.assertEqual(err, "")

    def test_offered_rows_and_unknown_history_are_described_without_guessing(self):
        row = {"name": "Elvish Mystic", "quantity": "2", "for": "Elves", "printing": "any"}
        out, err = self.said({"known": True, "offered": [row], "restored": [], "warnings": []})
        self.assertIn("Not restored to the queue: 2 x Elvish Mystic for Elves", out)
        self.assertIn("watchlist set", err)
        self.assertNotIn("--restore-queue", err)
        self.assertNotIn("no recorded", err)
        out, err = self.said({"known": True, "offered": [row], "restored": [], "warnings": []}, preview=True)
        self.assertIn("Available to restore to the queue", out)
        self.assertIn("--restore-queue", err)
        out, err = self.said({"known": False, "offered": [], "restored": [], "warnings": ["Check the old order."]})
        self.assertNotIn(" x ", out)
        self.assertIn("Review the queue manually", err)
        self.assertIn("no historical copies were inferred", err)
        self.assertIn("Check the old order", err)


class CancellationAndRemovalTests(_Fixture):
    def test_cancel_without_opt_in_reports_unrestored_rows_but_keeps_the_queue(self):
        oid = self.tracked()
        before = self.queue()
        code, out, err = self.run_cli("order", "cancel", oid, "cards", "-m", "Cancel", "--reason", "Sold out")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.queue(), before)
        self.assertIn("Not restored to the queue: 2 x Elvish Mystic for Elves", out)
        self.assertIn("watchlist set", err)
        self.assertNotIn("no recorded queue", err)

    def test_cancel_opt_in_restores_recorded_quantities_in_the_same_apply(self):
        oid = self.tracked()
        with mock.patch.object(inventory, "apply", wraps=inventory.apply) as apply:
            code, out, err = self.run_cli("order", "cancel", oid, "cards", "--restore-queue",
                                        "-m", "Cancel and requeue", "--reason", "Sold out", "--actor", "matt")
        self.assertEqual(code, 0, err)
        self.assertEqual(apply.call_count, 1)
        self.assertEqual(apply.call_args.args[1].id, "matt")
        self.assertEqual(self.queue()[0], ("Elvish Mystic", "3", "Elves"))
        self.assertIn("Restored to the queue: 2 x Elvish Mystic for Elves", out)
        self.assertNotIn("left unchanged", err)
        self.assertNotIn("Review the queue manually", err)

    def test_tracked_removal_restores_and_removes_record_and_payload(self):
        oid = self.tracked()
        self.file("magic/buylists/remove.md", f"[Order](../orders/records/{oid}.json)\n[Cards](../orders/{oid}.csv)\n")
        with mock.patch.object(inventory, "apply", wraps=inventory.apply) as apply:
            code, out, err = self.run_cli("order", "remove", oid, "-m", "Remove duplicate", "--reason", "Duplicate entry")
        self.assertEqual(code, 0, err)
        self.assertEqual(apply.call_count, 1)
        self.assertIsNone(self.backend.load().order(oid))
        self.assertNotIn(f"magic/orders/{oid}.csv", self.backend.load().payloads)
        self.assertEqual(self.queue()[0], ("Elvish Mystic", "3", "Elves"))
        self.assertIn("Restored to the queue: 2 x Elvish Mystic for Elves", out)
        self.assertIn(f"orders/records/{oid}.json", err)
        self.assertIn(f"orders/{oid}.csv", err)
        self.assertIn("was removed with the order", err)

    def test_historical_product_cancellation_keeps_list_but_removal_deletes_it(self):
        oid = "2026-10-02-precon"
        before = self.queue()
        code, _, err = self.run_cli("order", "cancel", oid, "precon", "--restore-queue",
                                  "-m", "Cancel precon", "--reason", "Shop cancelled")
        self.assertEqual(code, 0, err)
        self.assertIn("Review the queue manually", err)
        self.assertEqual(self.queue(), before)
        found = self.backend.load()
        self.assertEqual(found.order(oid).components[0].status, "cancelled")
        self.assertIsNotNone(found.product("precon"))
        self.assertEqual(next(r for r in found.status.rows if r.text("file") == "precon.csv").text("status"), "cancelled")
        code, _, err = self.run_cli("order", "remove", oid, "-m", "Remove erroneous order", "--reason", "Entered by mistake")
        self.assertEqual(code, 0, err)
        self.assertIn("Review the queue manually", err)
        found = self.backend.load()
        self.assertIsNone(found.order(oid))
        self.assertIsNone(found.product("precon"))
        self.assertNotIn("precon.csv", [r.text("file") for r in found.status.rows])
        self.assertEqual(self.queue(), before)

    def test_received_order_removal_and_blank_reason_refuse_without_changes(self):
        for oid, reason in (("2026-10-01-shop", "Duplicate"), ("2026-10-07-shop-a", "  ")):
            with self.subTest(order=oid):
                before = self.backend.load()
                code, _, err = self.run_cli("order", "remove", oid, "-m", "Remove", "--reason", reason)
                self.assertEqual(code, 1, err)
                self.assertEqual(self.backend.load(), before)

    def test_dry_run_reports_future_restoration_without_mutation_or_link_warning(self):
        oid = self.tracked()
        self.file("magic/buylists/dry.md", f"[Cards](../orders/{oid}.csv)\n")
        before = self.backend.load()
        with mock.patch.object(inventory, "apply", wraps=inventory.apply) as apply:
            code, out, err = self.run_cli("order", "remove", oid, "-m", "Try remove", "--reason", "Duplicate", "--dry-run")
        self.assertEqual(code, 0, err)
        apply.assert_not_called()
        self.assertEqual(self.backend.load(), before)
        self.assertIn("Would restore to the queue: 2 x Elvish Mystic for Elves", out)
        self.assertIn("Dry run: nothing saved", out)
        self.assertNotIn("was removed", err)

    def test_saved_but_refresh_failed_still_reports_restored_queue_and_link_followup(self):
        oid = self.tracked()
        self.file("magic/buylists/follow.md", f"[Cards](../orders/{oid}.csv)\n")
        self.refresh.side_effect = [existing.tables_answer(), existing.tables_answer(error="Fixture refresh failed")]
        code, out, err = self.run_cli("order", "remove", oid, "-m", "Remove", "--reason", "Duplicate")
        self.assertEqual(code, inv_orders.FOLLOW_UP_FAILED, err)
        self.assertIsNone(self.backend.load().order(oid))
        self.assertEqual(self.queue()[0], ("Elvish Mystic", "3", "Elves"))
        self.assertIn("Restored to the queue", out)
        self.assertIn("Fixture refresh failed", err)
        self.assertIn("was removed with the order", err)
