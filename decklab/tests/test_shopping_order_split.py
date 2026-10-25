"""Pending Shopping shipment splits over fixtures and disposable PostgreSQL."""
import contextlib
import json
import unittest
from unittest import mock

from decklab.lib import access, inventory
from decklab.lib.api import settings, shopping_order_changes as api
from decklab.lib.api.common import ApiError
from decklab.lib.inventory import files, orders, rules
from decklab.lib.inventory.files import FileInventory
from decklab.tests import db_support, test_inventory_contract as contract
from decklab.tests.test_inventory_orders import CLAUDE, card, fake_refresh, tables_answer, token
from decklab.tests.test_shopping_order_changes import ORDER, OrderChangeApiTests, changes_tree


def split_tree(case):
    changes_tree(case)
    path = case.magic / f"orders/records/{ORDER}.json"
    record = json.loads(path.read_text(encoding="utf-8"))
    record["components"][0]["checks"].append("Inspect packaging")
    record["components"][1]["checks"] = ["Inspect both faces", "Confirm quantity", "Keep the pairing"]
    path.write_text(json.dumps(record), encoding="utf-8")
    row = token("Llanowar Elves", 3, back="Llanowar Elves", details="1/1; green",
                notes="  Keep the physical pairing\nUnreported printing  ")
    row["back_details"] = "1/1; green; abilities unspecified"
    case.write(f"orders/tokens/{ORDER}.csv", rules.csv_bytes([row], rules.TOKEN_FIELDS).decode("utf-8"))


class OrderSplitApiTests:
    start = OrderChangeApiTests.start
    save = OrderChangeApiTests.save
    refused = OrderChangeApiTests.refused

    def request(self, **changes):
        data = {"profile": "matt", "expect": self.backend.load().revision, "order": ORDER,
                "action": "split", "component": "cards", "new_id": "later",
                "take": [{"row": 1, "quantity": 1}], "move_checks": [], "keep_checks": []}
        data.update(changes)
        return data

    def preview(self, **changes):
        return api.preview_order_change(json.dumps(self.request(**changes)))

    def rows(self, snapshot, component):
        found = orders._component(snapshot, ORDER, component)[1]
        return [{key: row.text(key) for key in orders.PAYLOAD_FIELDS[found.kind]}
                for row in snapshot.payloads[found.path].rows]

    def test_card_split_preview_and_save_match_cli_and_keep_exact_metadata(self):
        before = self.backend.load()
        data = self.request(take=[{"row": 1, "quantity": 1}, {"row": 2, "quantity": 1}],
                            move_checks=[2], keep_checks=[3])
        operation = inventory.Op("order.split", {key: data[key] for key in
                                  ("order", "component", "new_id", "take", "move_checks", "keep_checks")})
        with inventory.pinned(before):
            expected, summary = inventory.preview(operation)
        preview = api.preview_order_change(json.dumps(data))
        original_rows = self.rows(before, "cards")
        self.assertEqual(preview["components"], [
            {"id": "cards", "kind": "cards", "rows": [dict(original_rows[0], quantity="1")],
             "extra_copies": True},
            {"id": "later", "kind": "cards", "rows": [dict(original_rows[0], quantity="1"), original_rows[1]],
             "extra_copies": False}])
        self.assertEqual(preview["checks"][:2], [
            {"component": "cards", "checks": ["Record conditions", "Inspect packaging"]},
            {"component": "later", "checks": ["Record conditions", "Check languages"]}])
        self.assertEqual(preview["summary"], summary.text)
        self.assertEqual(preview["tables"], summary.extra["tables"])
        self.assertTrue(any("later is not marked" in message for message in preview["warnings"]))
        self.assertEqual(files.render(self.backend.load()), files.render(before))
        real_apply = inventory.apply
        with mock.patch.object(inventory, "apply", wraps=real_apply) as apply:
            saved = self.save(preview["preview"])
        apply.assert_called_once()
        self.assertEqual(apply.call_args.args[0], operation)
        self.assertEqual(apply.call_args.kwargs["expected_revision"], before.revision)
        self.assertEqual(saved["components"], preview["components"])
        self.assertEqual(saved["checks"], preview["checks"])
        after = self.backend.load()
        self.assertEqual(files.render(after), files.render(expected))
        self.assertEqual([part.id for part in after.order(ORDER).components], ["cards", "later", "tokens"])
        self.assertTrue(all(part.status == "pending" for part in after.order(ORDER).components))
        self.assertEqual(after.collection(), before.collection())
        self.assertEqual(after.tokens, before.tokens)
        self.assertEqual(after.watchlist, before.watchlist)
        self.assertEqual(after.order(ORDER).audit_notes, before.order(ORDER).audit_notes)

    def test_token_split_preserves_physical_pairings_unknowns_and_all_unspecified_checks(self):
        before = self.backend.load()
        row = self.rows(before, "tokens")[0]
        preview = self.preview(component="tokens", take=[{"row": 1, "quantity": 2}])
        self.assertEqual(preview["components"], [
            {"id": "tokens", "kind": "tokens", "rows": [dict(row, quantity="1")], "extra_copies": False},
            {"id": "later", "kind": "tokens", "rows": [dict(row, quantity="2")], "extra_copies": False}])
        self.assertEqual(preview["checks"][1]["checks"], preview["checks"][2]["checks"])
        self.assertEqual(len(preview["checks"][1]["checks"]), 3)
        self.assertEqual(preview["warnings"], [])
        saved = self.save(preview["preview"])
        self.assertEqual(saved["components"], preview["components"])
        after = self.backend.load()
        self.assertEqual(self.rows(after, "tokens"), [dict(row, quantity="1")])
        self.assertEqual(self.rows(after, "later"), [dict(row, quantity="2")])
        self.assertEqual(after.tokens, before.tokens)

    def test_numbered_rows_distinguish_two_printings_of_the_same_card(self):
        order_id = "2026-10-15-multiple"
        rows = [card("Llanowar Elves", "m19", "314", 2, notes="First printing"),
                card("Llanowar Elves", "wc00", "nl239", 3, condition="LP", language="en",
                     notes="Second printing")]
        inventory.apply(inventory.Op("order.add", {"record": {"id": order_id}, "cards": {"rows": rows}}),
                        CLAUDE, "Add fixture printings")
        preview = self.preview(order=order_id, take=[{"row": 2, "quantity": 2}])
        self.assertEqual(preview["components"][0]["rows"], [rows[0], dict(rows[1], quantity="1")])
        self.assertEqual(preview["components"][1]["rows"], [dict(rows[1], quantity="2")])
        saved = self.save(preview["preview"])
        self.assertEqual(saved["components"], preview["components"])

    def test_invalid_shapes_indices_quantities_and_check_routes_write_nothing(self):
        bad = [{"take": value} for value in (None, {}, [], [None], [1], [{"row": 1}],
               [{"row": 1, "quantity": 1, "notes": "extra"}],
               [{"row": 1, "quantity": 1}, {"row": 1, "quantity": 1}],
               [{"row": 3, "quantity": 1}], [{"row": 1, "quantity": 3}],
               [{"row": 1, "quantity": 2}, {"row": 2, "quantity": 1}])]
        for key in ("row", "quantity"):
            for value in (True, False, 0, -1, "1", 1.5, None, [], {}):
                bad.append({"take": [{"row": 1, "quantity": 1, key: value}]})
        for key in ("move_checks", "keep_checks"):
            for value in (None, 1, "1", [True], [0], ["1"], [1.5], [4], [1, 1]):
                bad.append({key: value})
        bad += [{"move_checks": [1], "keep_checks": [1]}, {"new_id": "cards"}, {"new_id": "bad id"},
                {"new_id": ""}, {"new_id": None}, {"component": []}, {"copy_checks": [1]},
                {"rows": []}, {"undo": False}, {"force": True}, {"values": {}},
                {"take": [{"row": 1, "quantity": 1}] * 501}]
        for changes in bad:
            with self.subTest(changes=changes):
                self.refused(400, self.request(**changes))
        data = self.request()
        for required in ("new_id", "take", "component"):
            missing = dict(data)
            del missing[required]
            self.refused(400, missing)

    def test_products_received_cancelled_or_missing_parts_cannot_be_split(self):
        for changes in ({"order": "2026-10-02-precon", "component": "precon"},
                        {"order": "2026-10-01-shop"}, {"order": "missing"}, {"component": "missing"}):
            self.refused(400, self.request(**changes))
        inventory.apply(inventory.Op("order.cancel", {"order": ORDER, "component": "cards", "reason": "Not sent"}),
                        CLAUDE, "Cancel fixture", reason="Not sent")
        self.refused(400, self.request())

    def test_new_refresh_failure_refuses_split_but_existing_failure_is_reported(self):
        with contextlib.ExitStack() as stack:
            tables = mock.Mock(return_value=tables_answer(error="New pool problem"))
            plan = mock.Mock(return_value=[])
            fake_refresh(stack, tables, plan)
            self.refused(400, self.request())
            plan.side_effect = ValueError("Existing pool problem")
            preview = self.preview()
            self.assertEqual(preview["tables"]["error"], "New pool problem")
            self.assertEqual(self.save(preview["preview"])["tables"]["error"], "New pool problem")

    def test_split_of_marked_component_refuses_a_new_actual_owned_printing_blocker(self):
        from decklab.lib.inventory import ops_collection  # noqa: F401 (register collection.import)
        inventory.apply(inventory.Op("order.extra_copies", {"order": "2026-10-02-precon",
                        "component": "precon"}), CLAUDE, "Mark fixture precon as extra copies")
        inventory.apply(inventory.Op("collection.import", {
            "space": "home", "sources": [("Fixture owned copies", self.rows(self.backend.load(), "cards"))]}),
            CLAUDE, "Add fixture copies")
        self.refused(400, self.request())
        self.assertTrue(self.backend.load().order(ORDER).audit_notes.endswith("cards."))

    def test_exact_revision_and_preview_identity_protect_row_and_check_numbers(self):
        preview = self.preview(move_checks=[1])
        self.refused(409, self.request(expect=preview["revision"] + "stale", order="missing"))
        for identity, viewer, writer in (({"profile": "user1", "remote": True}, None, "user1"),
                                         (None, "matt", "matt")):
            with access.using(identity), access.viewing(viewer), self.assertRaises(ApiError) as caught:
                self.save(preview["preview"], profile=writer)
            self.assertEqual(caught.exception.status, 409)
        inventory.apply(inventory.Op("order.checks", {"order": ORDER, "component": "cards", "withdraw": 1}),
                        CLAUDE, "Change numbered fixture checks")
        before = self.backend.load()
        with self.assertRaises(ApiError) as caught:
            self.save(preview["preview"])
        self.assertEqual(caught.exception.status, 409)
        self.assertEqual(files.render(self.backend.load()), files.render(before))

    def test_transaction_race_cannot_apply_a_split_to_newer_inventory(self):
        preview = self.preview()
        actual = inventory.apply

        def concurrent(operation, *args, **kwargs):
            actual(inventory.Op("order.record", {"order": ORDER, "values": {"notes": "Concurrent"}}),
                   CLAUDE, "Concurrent correction")
            return actual(operation, *args, **kwargs)

        before = self.backend.load()
        with mock.patch.object(inventory, "apply", concurrent), self.assertRaises(ApiError) as caught:
            self.save(preview["preview"])
        self.assertEqual(caught.exception.status, 409)
        after = self.backend.load()
        self.assertEqual(after.payloads, before.payloads)
        self.assertEqual(after.order(ORDER).notes, "Concurrent")
        self.assertEqual([part.id for part in after.order(ORDER).components], ["cards", "tokens"])

    def test_members_are_refused_before_inventory_access_on_each_listener(self):
        listed = [dict(profile, role="member") if profile["id"] == "user1" else profile
                  for profile in contract.FIXTURE_PROFILES]
        data = self.request()
        with mock.patch.object(settings, "_config_profiles", return_value=listed):
            for person in ("user1", "user2"):
                for remote in (False, True):
                    with self.subTest(person=person, remote=remote), \
                            access.using({"profile": person, "remote": True} if remote else None), \
                            access.viewing(None if remote else person), mock.patch.object(inventory, "current") as read:
                        with self.assertRaises(ApiError) as caught:
                            api.preview_order_change(json.dumps(dict(data, profile=person)))
                        self.assertEqual(caught.exception.status, 403)
                        with self.assertRaises(ApiError) as caught:
                            self.save("0" * 32, profile=person)
                        self.assertEqual(caught.exception.status, 403)
                        read.assert_not_called()


class FileOrderSplitApiTests(OrderSplitApiTests, unittest.TestCase):
    def setUp(self):
        case = contract.build_tree(split_tree, adapted=True)
        self.addCleanup(case.doCleanups)
        self.backend = FileInventory(case.inventory.root)
        self.start(case)


@unittest.skipIf(db_support.unavailable(), db_support.unavailable() or "")
class PgOrderSplitApiTests(OrderSplitApiTests, db_support.DbTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from decklab.db import profiles_sync
        profiles_sync.sync(listed=contract.FIXTURE_PROFILES, dbname=cls.dbname)

    def setUp(self):
        from decklab.lib.inventory import pg
        from decklab.lib.state import pg as state_pg
        db_support.reset(self.dbname, db_support.INVENTORY_TABLES)
        case = contract.build_tree(split_tree, adapted=True)
        self.addCleanup(case.doCleanups)
        pg.write_model(case.inventory.load(), CLAUDE, "Import fixture", dbname=self.dbname, decks=True)
        self.backend = pg.PgInventory(dbname=self.dbname, breaker=state_pg.Breaker())
        self.start(case)

    def test_split_and_refreshed_table_commit_atomically_in_one_audited_change(self):
        from decklab.lib.inventory import pg
        preview = self.preview(move_checks=[2])
        before = self.backend.load()
        with self.connect() as connection:
            count = connection.execute("select count(*) from audit.change_set").fetchone()[0]
        real_diff = pg._diff

        def fail_after_inventory_write(*args):
            real_diff(*args)
            raise RuntimeError("Transaction failed after inventory write")

        with mock.patch.object(pg, "_diff", fail_after_inventory_write), self.assertRaises(ApiError) as caught:
            self.save(preview["preview"])
        self.assertEqual(caught.exception.status, 400)
        self.assertEqual(files.render(self.backend.load()), files.render(before))
        with self.connect() as connection:
            self.assertEqual(connection.execute("select count(*) from audit.change_set").fetchone()[0], count)
        self.assertTrue(self.save(preview["preview"])["saved"])
        with self.connect() as connection:
            changes = connection.execute("select id, actor, source, via from audit.change_set order by id").fetchall()
            tables = {row[0] for row in connection.execute(
                "select table_name from audit.row_change where change_set_id = %s", (changes[-1][0],)).fetchall()}
        self.assertEqual(len(changes), count + 1)
        self.assertEqual(changes[-1][1:], ("matt", "web", "tunnel"))
        self.assertTrue({"order_card_item", "order_component", "deck"} <= tables, tables)
