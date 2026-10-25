"""Order record/check corrections previewed on Shopping, with no live inventory access."""
import contextlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from decklab.lib import access, config, inventory
from decklab.lib.api import carddata, settings, shopping_order_changes as api
from decklab.lib.api.common import ApiError
from decklab.lib.inventory import files, orders, refresh
from decklab.lib.inventory.files import FileInventory
from decklab.tests import db_support, test_inventory_contract as contract
from decklab.tests.test_inventory_orders import CLAUDE
from decklab.tests.test_shopping_orders import order_tree


ORDER = "2026-10-07-shop-a"
EMPTY_TABLES = {"written": [], "skipped": [], "error": None}


def changes_tree(case):
    order_tree(case)
    path = case.magic / f"orders/records/{ORDER}.json"
    record = json.loads(path.read_text(encoding="utf-8"))
    record["audit_notes"] = "Keep provenance. Extra copies of owned printings: cards."
    path.write_text(json.dumps(record), encoding="utf-8")


class OrderChangeApiTests:
    def start(self, case):
        self.root = case.inventory.root
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(contract.fixture_world())
        stack.enter_context(mock.patch.object(config, "REPO", self.root))
        stack.enter_context(inventory.use(self.backend))
        stack.enter_context(access.using({"profile": "matt", "email": "", "remote": True}))
        api._previews.clear()
        self.addCleanup(api._previews.clear)

    def request(self, **changes):
        data = {"profile": "matt", "expect": self.backend.load().revision, "order": ORDER,
                "action": "record", "values": {"seller": "Correct shop", "ordered_on": "2026-10-06",
                                                 "notes": "Check the envelope",
                                                 "sources": ["magic/buylists/2026-10-12-plan.md"]}}
        data.update(changes)
        return data

    def preview(self, **changes):
        return api.preview_order_change(json.dumps(self.request(**changes)))

    def checks(self, component="cards", **changes):
        data = self.request(action="checks", component=component, **changes)
        data.pop("values")
        return api.preview_order_change(json.dumps(data))

    def save(self, token, **changes):
        return api.apply_order_change(json.dumps({"profile": "matt", "preview": token, **changes}))

    def refused(self, status, data):
        before = self.backend.load()
        with self.assertRaises(ApiError) as caught:
            api.preview_order_change(json.dumps(data))
        self.assertEqual(caught.exception.status, status, caught.exception.message)
        self.assertEqual(files.render(self.backend.load()), files.render(before))
        self.assertEqual(self.backend.load().revision, before.revision)

    def test_record_preview_is_read_only_and_apply_preserves_every_uneditable_field(self):
        before = self.backend.load()
        result = self.preview()
        self.assertEqual(result["order"], ORDER)
        self.assertEqual(result["revision"], before.revision)
        self.assertEqual(result["record"], self.request()["values"])
        self.assertEqual(result["checks"], [{"component": "cards", "checks": ["Record conditions", "Check languages"]},
                                            {"component": "tokens", "checks": []}])
        self.assertEqual(result["tables"], EMPTY_TABLES)
        self.assertEqual(files.render(self.backend.load()), files.render(before))
        real_apply = inventory.apply
        with mock.patch.object(inventory, "apply", wraps=real_apply) as apply:
            saved = self.save(result["preview"])
        apply.assert_called_once()
        args, kwargs = apply.call_args
        self.assertEqual((args[1].id, args[1].via, args[1].source), ("matt", "tunnel", "web"))
        self.assertEqual(kwargs["expected_revision"], before.revision)
        self.assertTrue(saved["saved"])
        after = self.backend.load()
        self.assertEqual(saved["revision"], after.revision)
        self.assertEqual(saved["record"], result["record"])
        expected = before.order(ORDER).record()
        expected.update(result["record"])
        self.assertEqual(after.order(ORDER).record(), expected)
        rendered_before, rendered_after = files.render(before), files.render(after)
        changed = {path for path in rendered_before.keys() | rendered_after.keys()
                   if rendered_before.get(path) != rendered_after.get(path)}
        self.assertEqual(changed, {f"magic/orders/records/{ORDER}.json"})

    def test_partial_record_updates_and_explicit_clears_keep_other_metadata(self):
        self.save(self.preview(values={"notes": "Only notes changed"})["preview"])
        after = self.backend.load().order(ORDER)
        self.assertEqual((after.seller, after.ordered_on, after.notes),
                         ("MTGMate", "2026-10-07", "Only notes changed"))
        cleared = {"seller": "", "ordered_on": "", "notes": "", "sources": []}
        self.save(self.preview(values=cleared)["preview"])
        self.assertEqual({key: self.backend.load().order(ORDER).record()[key] for key in cleared}, cleared)

    def test_record_updates_accept_received_orders_without_altering_receipt_facts(self):
        order = "2026-10-01-shop"
        before = self.backend.load().order(order)
        self.save(self.preview(order=order, values={"seller": "Correct historic shop"})["preview"])
        after = self.backend.load().order(order)
        self.assertEqual(after.seller, "Correct historic shop")
        self.assertEqual([c.record() for c in after.components], [c.record() for c in before.components])

    def test_historical_deck_sources_resolve_from_the_inventory_without_repo_files(self):
        source = "magic/decks/casual/shopping-test.md"
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(config, "REPO", Path(folder)):
            result = self.preview(values={"sources": [source]})
            self.save(result["preview"])
        self.assertEqual(list(self.backend.load().order(ORDER).sources), [source])

    def test_metadata_and_checks_do_not_need_card_data_or_refresh_deck_tables(self):
        with mock.patch.object(carddata, "_require_cards", side_effect=AssertionError("card data needed")), \
                mock.patch.object(orders, "check_card_rows", side_effect=AssertionError("card rows checked")), \
                mock.patch.object(refresh, "plan_refresh", side_effect=AssertionError("tables refreshed")):
            self.save(self.preview(values={"notes": "No card changes"})["preview"])
            self.save(self.checks(add=["Inspect finish"])["preview"])

    def test_pending_checks_add_and_withdraw_preserve_duplicates_and_order(self):
        added = self.checks(add=["Inspect printing"])
        self.assertEqual(list(self.backend.load().order(ORDER).components[0].checks),
                         ["Record conditions", "Check languages"])
        self.save(added["preview"])
        self.save(self.checks(add=["Record conditions"])["preview"])
        self.save(self.checks(withdraw=[1])["preview"])
        result = self.checks(withdraw=[2])
        self.assertEqual(result["checks"][0]["checks"], ["Check languages", "Record conditions"])
        self.save(result["preview"])
        component = self.backend.load().order(ORDER).components[0]
        self.assertEqual(list(component.checks), ["Check languages", "Record conditions"])
        self.assertEqual(component.status, "pending")
        self.assertFalse(component.verified_checks)

    def test_pending_product_and_token_checks_use_the_same_correction_flow(self):
        self.save(self.checks(component="tokens", add=["Inspect token pairing"])["preview"])
        self.assertEqual(list(self.backend.load().order(ORDER).components[1].checks), ["Inspect token pairing"])
        result = self.checks(order="2026-10-02-precon", component="precon", add=["Inspect product tokens"])
        self.save(result["preview"])
        self.assertEqual(list(self.backend.load().order("2026-10-02-precon").components[0].checks),
                         ["Inspect product tokens"])

    def test_received_or_cancelled_checks_and_unknown_records_are_refused(self):
        for changes in ({"order": "2026-10-01-shop"}, {"order": "missing"}, {"component": "missing"}):
            data = self.request(action="checks", component="cards", add=["Inspect"], **{
                key: value for key, value in changes.items() if key != "component"})
            data.pop("values")
            data.update(changes)
            self.refused(400, data)
        inventory.apply(inventory.Op("order.cancel", {"order": ORDER, "component": "cards", "reason": "Not sent"}),
                        CLAUDE, "Cancel fixture", reason="Not sent")
        data = self.request(action="checks", component="cards", add=["Inspect"])
        data.pop("values")
        self.refused(400, data)

    def test_stale_preview_and_transaction_race_cannot_overwrite_newer_corrections(self):
        first = self.preview(values={"notes": "First"})
        second = self.preview(values={"notes": "Second"})
        self.save(second["preview"])
        with self.assertRaises(ApiError) as caught:
            self.save(first["preview"])
        self.assertEqual(caught.exception.status, 409)
        self.assertEqual(self.backend.load().order(ORDER).notes, "Second")
        preview = self.preview(values={"notes": "Stale transaction"})
        concurrent_preview = self.preview(values={"notes": "Concurrent"})
        concurrent_operation = api._previews[concurrent_preview["preview"]]["operation"]
        real_apply = inventory.apply

        def concurrent(operation, *args, **kwargs):
            real_apply(concurrent_operation, CLAUDE, "Concurrent correction")
            return real_apply(operation, *args, **kwargs)

        with mock.patch.object(inventory, "apply", concurrent), self.assertRaises(ApiError) as caught:
            self.save(preview["preview"])
        self.assertEqual(caught.exception.status, 409)
        self.assertEqual(self.backend.load().order(ORDER).notes, "Concurrent")

    def test_exact_revision_is_required_before_order_lookup(self):
        for expect in ("stale", self.backend.load().revision + "-stale", " " + self.backend.load().revision):
            with self.subTest(expect=expect):
                self.refused(409, self.request(expect=expect, order="missing"))
        for expect in ("", None, True, [], "a" * 257):
            self.refused(400, self.request(expect=expect))

    def test_stale_check_numbers_cannot_withdraw_a_newly_renumbered_check(self):
        first = self.checks(withdraw=[1])
        second = self.checks(withdraw=[1])
        self.save(second["preview"])
        with self.assertRaises(ApiError) as caught:
            self.save(first["preview"])
        self.assertEqual(caught.exception.status, 409)
        self.assertEqual(list(self.backend.load().order(ORDER).components[0].checks), ["Check languages"])

    def test_preview_tokens_are_bound_to_writer_and_listener_and_consumed_once(self):
        preview = self.preview()["preview"]
        for identity, viewer, writer in (({"profile": "user1", "remote": True}, None, "user1"),
                                         (None, "matt", "matt")):
            with access.using(identity), access.viewing(viewer), self.assertRaises(ApiError) as caught:
                self.save(preview, profile=writer)
            self.assertEqual(caught.exception.status, 409)
        self.save(preview)
        with self.assertRaises(ApiError) as caught:
            self.save(preview)
        self.assertEqual(caught.exception.status, 409)

    def test_cache_expiry_bound_and_busy_tokens(self):
        with mock.patch.object(api, "MAX_PREVIEWS", 2):
            first, second, third = [self.preview()["preview"] for _ in range(3)]
        self.assertEqual(set(api._previews), {second, third})
        with self.assertRaises(ApiError) as caught:
            self.save(first)
        self.assertEqual(caught.exception.status, 409)
        cached = api._previews[second]
        cached["busy"] = True
        with self.assertRaises(ApiError) as caught:
            self.save(second)
        self.assertEqual(caught.exception.status, 409)
        cached["busy"] = False
        cached["created"] -= api.PREVIEW_LIFETIME + 1
        with self.assertRaises(ApiError) as caught:
            self.save(second)
        self.assertEqual(caught.exception.status, 409)

    def test_members_are_refused_on_both_listeners_before_inventory_or_token_lookup(self):
        listed = [dict(profile, role="member") if profile["id"] == "user1" else profile
                  for profile in contract.FIXTURE_PROFILES]
        with mock.patch.object(settings, "_config_profiles", return_value=listed):
            for person in ("user1", "user2"):
                for remote in (False, True):
                    with self.subTest(person=person, remote=remote), \
                            access.using({"profile": person, "remote": True} if remote else None), \
                            access.viewing(None if remote else person), mock.patch.object(inventory, "current") as read:
                        for writer in (person, "matt"):
                            for function, data in ((api.preview_order_change, self.request(profile=writer, expect="x")),
                                                   (api.apply_order_change, {"profile": writer, "preview": "0" * 32})):
                                with self.assertRaises(ApiError) as caught:
                                    function(json.dumps(data))
                                self.assertEqual(caught.exception.status, 403)
                        read.assert_not_called()

    def test_invalid_shapes_fields_and_check_actions_never_write(self):
        bad = [{"action": "delete"}, {"action": []}, {"order": []}, {"values": []}, {"values": {}},
               {"values": {"id": "replacement"}}, {"values": {"audit_notes": "Lost provenance"}},
               {"values": {"components": []}}, {"values": {"paid": "1.00"}},
               {"values": {"seller": "two\nlines"}}, {"values": {"ordered_on": "2026-02-30"}},
               {"values": {"sources": "file.md"}}, {"values": {"sources": ["../outside.md"]}},
               {"values": {"sources": ["magic/buylists/missing.md"]}}, {"force": True}]
        for changes in bad:
            with self.subTest(changes=changes):
                self.refused(400, self.request(**changes))
        bad_checks = [{}, {"add": []}, {"add": "Inspect"}, {"add": [""]}, {"add": ["two\nlines"]},
                      {"add": ["First", "Second"]},
                      {"withdraw": []}, {"withdraw": [True]}, {"withdraw": [0]}, {"withdraw": [3]},
                      {"withdraw": [1, 1]}, {"add": ["Inspect"], "withdraw": [1]},
                      {"resolve": 1}, {"clear": True}]
        for changes in bad_checks:
            with self.subTest(checks=changes):
                data = self.request(action="checks", component="cards", **changes)
                data.pop("values")
                self.refused(400, data)
        for preview in (None, "", [], "x" * 32):
            with self.assertRaises(ApiError) as caught:
                self.save(preview)
            self.assertEqual(caught.exception.status, 400)
        with self.assertRaises(ApiError) as caught:
            self.save("0" * 32, force=True)
        self.assertEqual(caught.exception.status, 400)

    def test_database_failure_writes_nothing_and_a_preview_can_be_retried(self):
        with mock.patch.object(inventory, "current", side_effect=inventory.Unavailable("down")):
            self.refused(503, self.request())
        preview = self.preview()["preview"]
        before = self.backend.load()
        with mock.patch.object(inventory, "apply", side_effect=inventory.Unavailable("down")), \
                self.assertRaises(ApiError) as caught:
            self.save(preview)
        self.assertEqual(caught.exception.status, 503)
        self.assertFalse(api._previews[preview]["busy"])
        self.assertEqual(files.render(self.backend.load()), files.render(before))
        self.assertTrue(self.save(preview)["saved"])


class FileOrderChangeApiTests(OrderChangeApiTests, unittest.TestCase):
    def setUp(self):
        case = contract.build_tree(changes_tree, adapted=True)
        self.addCleanup(case.doCleanups)
        self.backend = FileInventory(case.inventory.root)
        self.start(case)


@unittest.skipIf(db_support.unavailable(), db_support.unavailable() or "")
class PgOrderChangeApiTests(OrderChangeApiTests, db_support.DbTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from decklab.db import profiles_sync
        profiles_sync.sync(listed=contract.FIXTURE_PROFILES, dbname=cls.dbname)

    def setUp(self):
        from decklab.lib.inventory import pg
        from decklab.lib.state import pg as state_pg
        db_support.reset(self.dbname, db_support.INVENTORY_TABLES)
        case = contract.build_tree(changes_tree, adapted=True)
        self.addCleanup(case.doCleanups)
        pg.write_model(case.inventory.load(), CLAUDE, "Import fixture", dbname=self.dbname, decks=True)
        self.backend = pg.PgInventory(dbname=self.dbname, breaker=state_pg.Breaker())
        self.start(case)

    def test_each_correction_is_one_audited_change_with_its_writer_and_no_deck_changes(self):
        with self.connect() as connection:
            before = connection.execute("select count(*) from audit.change_set").fetchone()[0]
        self.save(self.preview()["preview"])
        self.save(self.checks(add=["Inspect finish"])["preview"])
        self.save(self.checks(withdraw=[1])["preview"])
        with self.connect() as connection:
            rows = connection.execute(
                "select id, actor, source, via, message from audit.change_set order by id").fetchall()
            for change in rows[-3:]:
                tables = {row[0] for row in connection.execute(
                    "select table_name from audit.row_change where change_set_id = %s", (change[0],)).fetchall()}
                self.assertEqual(change[1:4], ("matt", "web", "tunnel"))
                self.assertIn(ORDER, change[4])
                self.assertTrue(tables <= {"purchase_order", "order_component"}, tables)
                self.assertTrue(tables)
        self.assertEqual(len(rows), before + 3)
