"""Order cancellation/removal previews over temporary files and disposable PostgreSQL."""
import json
import unittest
from unittest import mock

from decklab.lib import access, accessories, inventory
from decklab.lib.api import settings, shopping_order_changes as api
from decklab.lib.api.common import ApiError
from decklab.lib.inventory import files, orders, rules
from decklab.lib.inventory.files import FileInventory
from decklab.lib.inventory.model import QUEUE_FIELDS
from decklab.tests import db_support, test_inventory_contract as contract
from decklab.tests import test_server_access as access_http
from decklab.tests.test_inventory_orders import CLAUDE, OrderOps, component, record_json
from decklab.tests.test_shopping_order_changes import ORDER, OrderChangeApiTests, changes_tree
from decklab.tests.test_server import ServerTestCase, WRITE


KNOWN = "2026-10-12-goodgames"
PRODUCT_ORDER = "2026-10-02-precon"
PRIVATE = "2026-10-15-private-precon"
REASON = "The shop confirmed that this shipment will not be sent."


def retire_tree(case):
    changes_tree(case)
    case.write("accessories.csv", ",".join(accessories.FIELDS) + "\n"
               "black-sleeves,sleeves,shared,DS,Matte,black,100,,,,,,\n"
               "private-sleeves,sleeves,user1,Private,Secret,pink,100,,,,,,\n"
               "shared-box,deck_box,shared,UG,Boulder,black,1,100,,,,,\n")
    case.product("private-precon.csv", ("deck", "Pick Your Poison", 1), column="section")
    path = case.magic / "products/status.csv"
    case.write("products/status.csv", path.read_text(encoding="utf-8")
               + "private-precon.csv,ordered,,,,Fixture product\n")
    case.write(f"orders/records/{PRIVATE}.json", record_json(PRIVATE, "Fixture shop", "2026-10-15", [
        component("private-precon", "product", "magic/products/private-precon.csv")]))


class OrderRetireApiTests:
    start = OrderChangeApiTests.start
    save = OrderChangeApiTests.save
    refused = OrderChangeApiTests.refused

    def request(self, **changes):
        data = {"profile": "matt", "expect": self.backend.load().revision, "order": ORDER,
                "action": "cancel", "component": "cards", "reason": REASON, "restore_queue": False}
        if changes.get("action") == "remove":
            data.pop("component")
            data.pop("restore_queue")
        data.update(changes)
        return data

    def preview(self, **changes):
        return api.preview_order_change(json.dumps(self.request(**changes)))

    def known_order(self):
        params = OrderOps.add_params(self, fulfils=[{"select": "Elvish Mystic", "quantity": 2},
                                                   {"select": "Pick Your Poison", "quantity": 1}])
        inventory.apply(inventory.Op("order.add", params), CLAUDE, "Record fixture fulfilment")
        return KNOWN

    def queue(self):
        return {(row.name, row.text("for")): row.qty for row in self.backend.load().watchlist.rows}

    def test_cancel_preview_is_read_only_and_each_pending_kind_saves_once(self):
        for order_id, component_id in ((ORDER, "cards"), (ORDER, "tokens"), (PRODUCT_ORDER, "precon")):
            with self.subTest(component=component_id):
                before = self.backend.load()
                answer = self.preview(order=order_id, component=component_id)
                self.assertEqual((answer["action"], answer["removed"]), ("cancel", False))
                self.assertEqual(answer["component"]["status"], "cancelled")
                self.assertEqual(files.render(self.backend.load()), files.render(before))
                with mock.patch.object(inventory, "apply", wraps=inventory.apply) as apply:
                    saved = self.save(answer["preview"])
                self.assertEqual(apply.call_count, 1)
                args, kwargs = apply.call_args
                self.assertEqual((args[0].kind, args[1].id, args[1].source, args[1].via),
                                 ("order.cancel", "matt", "web", "tunnel"))
                self.assertEqual(kwargs["expected_revision"], before.revision)
                self.assertEqual(kwargs["reason"], REASON)
                self.assertTrue(saved["saved"])
                after = self.backend.load()
                order, part = orders._component(after, order_id, component_id)
                self.assertEqual(part.status, "cancelled")
                self.assertIn(REASON.rstrip("."), order.audit_notes)
                self.assertEqual((after.collection(), after.tokens), (before.collection(), before.tokens))
                self.assertEqual(after.watchlist, before.watchlist)
                if part.kind == "product":
                    status = next(row for row in after.status.rows if row.text("file") == "precon.csv")
                    self.assertEqual(status.text("status"), "cancelled")
                    self.assertEqual([status.text(field) for field in ("intact", "sleeves", "deck_box")], ["", "", ""])
                    self.assertIsNotNone(after.product("precon"))
                else:
                    self.assertIn("/cancelled/", part.path)

    def test_known_cancel_offers_only_its_claims_and_restores_without_historic_prices(self):
        self.known_order()
        self.assertEqual(self.queue()[("Elvish Mystic", "Elves")], 1)
        answer = self.preview(order=KNOWN, restore_queue=True)
        restoration = answer["queue_restoration"]
        self.assertTrue(restoration["known"])
        self.assertEqual({(row["name"], row["for"], row["quantity"]) for row in restoration["offered"]},
                         {("Elvish Mystic", "Elves", "2"), ("Pick Your Poison", "Cats", "1")})
        self.assertEqual(restoration["restored"], restoration["offered"])
        for row in restoration["restored"]:
            self.assertEqual(set(row), set(QUEUE_FIELDS))
            self.assertTrue(all(row[key] == "" for key in ("listed_aud", "listed_at", "in_stock", "checked")))
        self.save(answer["preview"])
        self.assertEqual((self.queue()[("Elvish Mystic", "Elves")], self.queue()[("Pick Your Poison", "Cats")]), (3, 1))
        self.refused(400, self.request(order=KNOWN, restore_queue=True))

    def test_declining_cancel_restoration_is_not_undone_by_later_removal(self):
        self.known_order()
        queue = self.backend.load().watchlist
        answer = self.preview(order=KNOWN, restore_queue=False)
        self.assertTrue(answer["queue_restoration"]["known"])
        self.assertTrue(answer["queue_restoration"]["offered"])
        self.assertEqual(answer["queue_restoration"]["restored"], [])
        self.save(answer["preview"])
        removal = self.preview(order=KNOWN, action="remove")
        self.assertEqual(removal["queue_restoration"]["offered"], [])
        self.assertEqual(removal["queue_restoration"]["restored"], [])
        self.save(removal["preview"])
        self.assertEqual(self.backend.load().watchlist, queue)

    def test_split_cancel_and_remove_restore_each_recorded_copy_once(self):
        self.known_order()
        split = api.preview_order_change(json.dumps({"profile": "matt", "expect": self.backend.load().revision,
            "order": KNOWN, "action": "split", "component": "cards", "new_id": "later",
            "take": [{"row": 1, "quantity": 1}]}))
        self.save(split["preview"])
        cancelled = self.preview(order=KNOWN, component="later", restore_queue=True)
        self.assertEqual([(row["name"], row["quantity"]) for row in cancelled["queue_restoration"]["restored"]],
                         [("Elvish Mystic", "1")])
        self.save(cancelled["preview"])
        self.assertEqual(self.queue()[("Elvish Mystic", "Elves")], 2)
        removal = self.preview(order=KNOWN, action="remove")
        self.assertEqual({(row["name"], row["quantity"]) for row in removal["queue_restoration"]["restored"]},
                         {("Elvish Mystic", "1"), ("Pick Your Poison", "1")})
        self.save(removal["preview"])
        self.assertEqual((self.queue()[("Elvish Mystic", "Elves")], self.queue()[("Pick Your Poison", "Cats")]), (3, 1))

    def test_remove_restores_known_claims_and_returns_original_record_after_it_is_gone(self):
        self.known_order()
        before = self.backend.load()
        order = before.order(KNOWN)
        expected_record = {"seller": order.seller, "ordered_on": order.ordered_on,
                           "notes": order.notes, "sources": list(order.sources)}
        answer = self.preview(order=KNOWN, action="remove")
        self.assertEqual((answer["removed"], answer["action"], answer["checks"]), (True, "remove", []))
        self.assertEqual(answer["record"], expected_record)
        self.assertTrue(answer["queue_restoration"]["restored"])
        self.assertEqual(files.render(self.backend.load()), files.render(before))
        saved = self.save(answer["preview"])
        self.assertEqual((saved["saved"], saved["removed"], saved["order"], saved["checks"]), (True, True, KNOWN, []))
        self.assertEqual(saved["record"], expected_record)
        after = self.backend.load()
        self.assertIsNone(after.order(KNOWN))
        self.assertFalse(any(KNOWN in path for path in after.payloads))
        self.assertEqual((after.collection(), after.tokens), (before.collection(), before.tokens))
        self.assertEqual((self.queue()[("Elvish Mystic", "Elves")], self.queue()[("Pick Your Poison", "Cats")]), (3, 1))

    def test_product_removal_deletes_its_record_list_and_status_without_touching_owned_cards(self):
        before = self.backend.load()
        answer = self.preview(order=PRODUCT_ORDER, action="remove")
        self.save(answer["preview"])
        after = self.backend.load()
        self.assertIsNone(after.order(PRODUCT_ORDER))
        self.assertIsNone(after.product("precon"))
        self.assertFalse(any(row.text("file") == "precon.csv" for row in after.status.rows))
        self.assertEqual((after.collection(), after.tokens), (before.collection(), before.tokens))

    def test_unknown_historic_provenance_warns_without_inventing_queue_restorations(self):
        before = self.backend.load().watchlist
        for action in ("cancel", "remove"):
            answer = self.preview(action=action)
            restoration = answer["queue_restoration"]
            self.assertFalse(restoration["known"])
            self.assertEqual((restoration["offered"], restoration["restored"]), ([], []))
            self.assertTrue(restoration["warnings"])
            self.save(answer["preview"])
            self.assertEqual(self.backend.load().watchlist, before)

    def test_private_legacy_product_kit_is_refused_even_when_guard_viewer_is_unnamed(self):
        snapshot = self.backend.load()
        legacy = snapshot.with_status_rows([
            {**row.as_dict(), "sleeves": "private-sleeves"} if row.text("file") == "private-precon.csv"
            else row.as_dict() for row in snapshot.status.rows])
        with mock.patch.object(inventory, "current", return_value=legacy):
            for identity in ({"profile": "matt", "remote": True}, None):
                with self.subTest(identity=identity), access.using(identity), access.viewing(None):
                    for action in ("cancel", "remove"):
                        changes = {"order": PRIVATE, "action": action}
                        if action == "cancel":
                            changes["component"] = "private-precon"
                        self.refused(403, self.request(**changes))

    def test_received_orders_and_owned_products_cannot_be_cancelled_or_removed(self):
        for order_id, component_id in (("2026-10-01-shop", "cards"),
                                       ("product-fdn-beginner-box", "product-fdn-beginner-box")):
            for action in ("cancel", "remove"):
                with self.subTest(order=order_id, action=action):
                    changes = {"order": order_id, "action": action}
                    if action == "cancel":
                        changes["component"] = component_id
                    self.refused(400, self.request(**changes))

    def test_reasons_shapes_and_explicit_cancel_restoration_choice_are_required(self):
        for action in ("cancel", "remove"):
            for reason in (None, "", "  ", True, [], "bad\0reason", "x" * 2001):
                with self.subTest(action=action, reason=str(reason)[:30]):
                    self.refused(400, self.request(action=action, reason=reason))
            missing = self.request(action=action)
            missing.pop("reason")
            self.refused(400, missing)
        missing = self.request()
        missing.pop("restore_queue")
        self.refused(400, missing)
        for value in (None, 0, 1, "yes", []):
            self.refused(400, self.request(restore_queue=value))
        for flag in (True, False):
            self.refused(400, self.request(action="remove", restore_queue=flag))
        self.refused(400, self.request(component="missing"))

    def test_only_home_admin_can_preview_or_apply_on_either_listener(self):
        profiles = [dict(profile, role="member") if profile["id"] == "user1" else profile
                    for profile in contract.FIXTURE_PROFILES]
        with mock.patch.object(settings, "_config_profiles", return_value=profiles):
            for person in ("user1", "user2"):
                for remote in (False, True):
                    with self.subTest(person=person, remote=remote), \
                            access.using({"profile": person, "remote": True} if remote else None), \
                            access.viewing(None if remote else person), mock.patch.object(inventory, "current") as read:
                        for action in ("cancel", "remove"):
                            for writer in (person, "matt"):
                                data = self.request(action=action, profile=writer, expect="not read")
                                with self.assertRaises(ApiError) as caught:
                                    api.preview_order_change(json.dumps(data))
                                self.assertEqual(caught.exception.status, 403)
                        with self.assertRaises(ApiError) as caught:
                            self.save("0" * 32, profile=person)
                        self.assertEqual(caught.exception.status, 403)
                        read.assert_not_called()

    def test_preview_token_is_writer_listener_bound_expiring_busy_and_single_use(self):
        token = self.preview()["preview"]
        for identity, viewer, writer in (({"profile": "user1", "remote": True}, None, "user1"),
                                         (None, "matt", "matt")):
            with access.using(identity), access.viewing(viewer), self.assertRaises(ApiError) as caught:
                self.save(token, profile=writer)
            self.assertEqual(caught.exception.status, 409)
        cached = api._previews[token]
        cached["busy"] = True
        with self.assertRaises(ApiError) as caught:
            self.save(token)
        self.assertEqual(caught.exception.status, 409)
        cached["busy"] = False
        created = cached["created"]
        with mock.patch.object(api.time, "monotonic", return_value=created + api.PREVIEW_LIFETIME + 1), \
                self.assertRaises(ApiError) as caught:
            self.save(token)
        self.assertEqual(caught.exception.status, 409)
        self.assertTrue(self.save(token)["saved"])
        with self.assertRaises(ApiError) as caught:
            self.save(token)
        self.assertEqual(caught.exception.status, 409)

    def test_exact_inventory_and_deck_revisions_are_checked_before_save_and_inside_transaction(self):
        self.refused(409, self.request(expect=self.backend.load().revision + "stale", order="missing"))
        for deck_race in (False, True):
            token = self.preview()["preview"]
            before = self.backend.load()
            real_apply = inventory.apply

            def concurrent(operation, *args, **kwargs):
                if deck_race:
                    deck = self.backend.load().deck("casual/shopping-test")
                    changed = inventory.Op("deck.save", {"deck_id": deck.id, "text": deck.text + "\nConcurrent note.\n",
                                                         "base_sha256": deck.sha256})
                else:
                    changed = inventory.Op("order.record", {"order": ORDER, "values": {"notes": "Concurrent correction"},
                                                            "repo": str(self.root)})
                real_apply(changed, CLAUDE, "Concurrent fixture correction")
                return real_apply(operation, *args, **kwargs)

            with mock.patch.object(inventory, "apply", side_effect=concurrent), self.assertRaises(ApiError) as caught:
                self.save(token)
            self.assertEqual(caught.exception.status, 409)
            self.assertEqual(self.backend.load().order(ORDER).components[0].status, "pending")
            self.assertEqual(self.backend.load().watchlist, before.watchlist)

    def test_database_unavailable_never_writes_and_a_preview_can_be_retried(self):
        data = self.request()
        with mock.patch.object(inventory, "current", side_effect=inventory.Unavailable("down")):
            self.refused(503, data)
        token = self.preview()["preview"]
        before = self.backend.load()
        with mock.patch.object(inventory, "apply", side_effect=inventory.Unavailable("down")), \
                self.assertRaises(ApiError) as caught:
            self.save(token)
        self.assertEqual(caught.exception.status, 503)
        self.assertFalse(api._previews[token]["busy"])
        self.assertEqual(files.render(self.backend.load()), files.render(before))
        self.assertTrue(self.save(token)["saved"])


class FileOrderRetireApiTests(OrderRetireApiTests, unittest.TestCase):
    def setUp(self):
        case = contract.build_tree(retire_tree, adapted=True)
        self.addCleanup(case.doCleanups)
        self.backend = FileInventory(case.inventory.root)
        self.start(case)


@unittest.skipIf(db_support.unavailable(), db_support.unavailable() or "")
class PgOrderRetireApiTests(OrderRetireApiTests, db_support.DbTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from decklab.db import profiles_sync
        profiles_sync.sync(listed=contract.FIXTURE_PROFILES, dbname=cls.dbname)

    def setUp(self):
        from decklab.lib.inventory import pg
        from decklab.lib.state import pg as state_pg
        db_support.reset(self.dbname, db_support.INVENTORY_TABLES)
        case = contract.build_tree(retire_tree, adapted=True)
        self.addCleanup(case.doCleanups)
        pg.write_model(case.inventory.load(), CLAUDE, "Import retirement fixture", dbname=self.dbname, decks=True)
        self.backend = pg.PgInventory(dbname=self.dbname, breaker=state_pg.Breaker())
        self.start(case)

    def test_removal_queue_restore_and_deck_tables_are_one_audited_transaction_with_rollback(self):
        from decklab.lib.inventory import pg
        self.known_order()
        preview = self.preview(order=KNOWN, action="remove")
        before = self.backend.load()
        with self.connect() as connection:
            count = connection.execute("select count(*) from audit.change_set").fetchone()[0]
        real_diff = pg._diff

        def fail_after_inventory_write(*args):
            real_diff(*args)
            raise RuntimeError("Refused fixture transaction after inventory writes")

        with mock.patch.object(pg, "_diff", fail_after_inventory_write), self.assertRaises(ApiError) as caught:
            self.save(preview["preview"])
        self.assertEqual(caught.exception.status, 400)
        self.assertEqual(files.render(self.backend.load()), files.render(before))
        with self.connect() as connection:
            self.assertEqual(connection.execute("select count(*) from audit.change_set").fetchone()[0], count)
        self.assertTrue(self.save(preview["preview"])["saved"])
        with self.connect() as connection:
            changes = connection.execute("select id, actor, source, via, reason from audit.change_set order by id").fetchall()
            tables = {row[0] for row in connection.execute(
                "select table_name from audit.row_change where change_set_id = %s", (changes[-1][0],)).fetchall()}
        self.assertEqual((len(changes), changes[-1][1:]), (count + 1, ("matt", "web", "tunnel", REASON)))
        self.assertTrue({"purchase_order", "order_component", "order_card_item", "watchlist_item", "deck"} <= tables, tables)


class OrderRetireHttpTests(ServerTestCase):
    PREVIEW = "/api/shopping/order/change/preview"
    APPLY = "/api/shopping/order/change/apply"

    def test_cancel_remove_envelopes_and_removed_result_pass_through_existing_routes(self):
        for action in ("cancel", "remove"):
            data = {"profile": "matt", "expect": "fixture revision", "order": ORDER,
                    "action": action, "reason": REASON}
            if action == "cancel":
                data.update(component="cards", restore_queue=True)
            body = json.dumps(data).encode()
            answer = {"preview": "a" * 32, "action": action, "removed": action == "remove", "checks": []}
            with mock.patch.object(api, "preview_order_change", return_value=answer) as preview:
                self.assertEqual(self.get_json(self.PREVIEW, method="POST", body=body), answer)
            preview.assert_called_once_with(body)
        body = b'{"profile":"matt","preview":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}'
        answer = {"saved": True, "removed": True, "action": "remove", "order": ORDER, "checks": []}
        with mock.patch.object(api, "apply_order_change", return_value=answer) as apply:
            self.assertEqual(self.get_json(self.APPLY, method="POST", body=body), answer)
        apply.assert_called_once_with(body)

    def test_retirement_routes_keep_same_origin_json_header_method_and_query_guards(self):
        for path, function in ((self.PREVIEW, "preview_order_change"), (self.APPLY, "apply_order_change")):
            with self.subTest(path=path), mock.patch.object(api, function) as handler:
                self.assertError(path, 403, method="POST", body=b"{}", headers={"Content-Type": "application/json"})
                self.assertError(path, 415, method="POST", body=b"{}", headers={"X-Deck-Lab": "1"})
                self.assertError(path, 403, method="POST", body=b"{}", headers=dict(WRITE, Origin="http://other.example"))
                self.assertError(path + "?order=changed", 400, method="POST", body=b"{}")
                for method in ("GET", "HEAD", "PUT", "DELETE"):
                    self.assertEqual(self.request(method, path)[0], 405)
                handler.assert_not_called()


class OrderRetireListenerTests(unittest.TestCase):
    """Existing signed test tokens, with no Cloudflare or external server access."""

    @classmethod
    def setUpClass(cls):
        access_http.TwoListenersTests.setUpClass.__func__(cls)

    @classmethod
    def tearDownClass(cls):
        access_http.TwoListenersTests.tearDownClass.__func__(cls)

    request = access_http.TwoListenersTests.request
    remote_request = access_http.TwoListenersTests.remote_request

    def test_remote_authentication_and_admin_permissions_precede_inventory_and_token_lookup(self):
        with mock.patch.object(settings, "_config_profiles", return_value=access_http.PROFILES), \
                mock.patch.object(inventory, "current", side_effect=AssertionError("permission before inventory")):
            for path in (OrderRetireHttpTests.PREVIEW, OrderRetireHttpTests.APPLY):
                for email in (None, "user1@example.com", "user2@example.com"):
                    with self.subTest(path=path, email=email):
                        data = {"profile": "matt", "expect": "unused", "order": ORDER, "action": "remove", "reason": REASON} \
                            if path.endswith("preview") else {"profile": "matt", "preview": "0" * 32}
                        status, _, body = self.remote_request("POST", path, json.dumps(data).encode(), email=email)
                        self.assertEqual(status, 403, body)
                        self.assertNotIn(b"Traceback", body)

    def test_home_member_cannot_retire_orders_or_impersonate_admin(self):
        with mock.patch.object(settings, "_config_profiles", return_value=access_http.PROFILES), \
                mock.patch.object(inventory, "current", side_effect=AssertionError("permission before inventory")):
            for writer in ("user1", "matt"):
                data = {"profile": writer, "expect": "unused", "order": ORDER,
                        "action": "cancel", "component": "cards", "reason": REASON, "restore_queue": False}
                status, _, body = self.request(self.home, "POST", OrderRetireHttpTests.PREVIEW,
                    json.dumps(data).encode(), {**WRITE, "X-Deck-Lab-Viewer": "user1"})
                self.assertEqual(status, 403, body)
