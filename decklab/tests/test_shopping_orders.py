"""Shopping's order previews and commits over fixtures and a throwaway database."""
import contextlib
import csv
import io
import json
import unittest
from unittest import mock

from decklab.db import inv_orders
from decklab.lib import access, config, inventory
from decklab.lib.api import shopping, shopping_orders
from decklab.lib.api.common import ApiError
from decklab.lib.inventory import files, orders, refresh, rules
from decklab.lib.inventory.files import FileInventory
from decklab.tests import db_support, test_inventory_contract as contract
from decklab.tests.test_inventory_orders import (CLAUDE, ELVES, PRODUCT_COLUMNS, card, fake_refresh,
                                                  orders_tree, product_rows, tables_answer, token)


def order_tree(case):
    orders_tree(case)
    case.product("precon.csv", ("deck", "Elvish Mystic", 1), column="section")
    case.deck("shopping-test", "Shopping test", "idea", "Deck\n4 Elvish Mystic\n", table="\n")


def csv_text(rows, fields):
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fields, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue()


class OrderApiTests:
    def start(self, case):
        self.root = case.inventory.root
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(contract.fixture_world())
        stack.enter_context(mock.patch.object(config, "REPO", self.root))
        stack.enter_context(inventory.use(self.backend))
        stack.enter_context(access.using({"profile": "matt", "email": "", "remote": True}))
        shopping_orders._previews.clear()
        self.addCleanup(shopping_orders._previews.clear)

    def request(self, **changes):
        data = {"profile": "matt", "expect": self.backend.load().revision,
                "record": {"id": "2026-10-15-fixture", "seller": "Fixture shop", "ordered_on": "2026-10-15",
                           "sources": ["magic/buylists/2026-10-12-plan.md"], "notes": "Check the delivery"},
                "cards": {"rows": [card("Elvish Mystic", "cmm", "648", 2),
                                    card("Pick Your Poison", "mkm", "170", 1)], "checks": ["Check language"]},
                "fulfils": [{"row": 1, "quantity": 2}, {"row": 2}]}
        data.update(changes)
        return data

    def preview(self, **changes):
        return shopping_orders.preview_order(json.dumps(self.request(**changes)))

    def save(self, preview, **changes):
        return shopping_orders.apply_order(json.dumps({"profile": "matt", "preview": preview, **changes}))

    def refused(self, status, **changes):
        before = self.backend.load()
        with self.assertRaises(ApiError) as caught:
            self.preview(**changes)
        self.assertEqual(caught.exception.status, status, caught.exception.message)
        self.assertEqual(files.render(self.backend.load()), files.render(before))
        self.assertEqual(self.backend.load().revision, before.revision)

    def mixed_request(self):
        return self.request(tokens={"csv": csv_text([token("Llanowar Elves", 1, details="1/1; green",
                                                          notes="Check the unreported back")], rules.TOKEN_FIELDS),
                                   "checks": ["Inspect front and back"]},
                            product={"stem": "fixture-precon", "name": "Fixture precon", "format": "Casual",
                                     "status": "preordered", "checks": ["Inspect product tokens"],
                                     "csv": csv_text(product_rows(("Main", "Sol Ring", "ecc", "57", 1)),
                                                     PRODUCT_COLUMNS)})

    def test_mixed_preview_matches_cli_operation_without_writes_and_save_uses_one_operation(self):
        before = self.backend.load()
        data = self.mixed_request()
        operation = shopping_orders._operation(data)
        with inventory.pinned(before):
            self.assertIsNone(inv_orders._refresh_refusal(inventory, operation))
            expected, summary = inventory.preview(operation)
        result = shopping_orders.preview_order(json.dumps(data))
        self.assertEqual(result["summary"], summary.text)
        self.assertEqual(result["counts"], summary.counts)
        self.assertEqual(result["tables"], summary.extra["tables"])
        self.assertEqual(result["changes"], inventory.changed_labels(before, expected))
        self.assertEqual(result["watchlist_reduced"], [
            {"name": "Elvish Mystic", "for": "Elves", "quantity": 2, "left": 1},
            {"name": "Pick Your Poison", "for": "Cats", "quantity": 1, "left": 0}])
        self.assertEqual(result["checks"], [{"component": "cards", "checks": ["Check language"]},
                                            {"component": "tokens", "checks": ["Inspect front and back"]},
                                            {"component": "fixture-precon", "checks": ["Inspect product tokens"]}])
        self.assertEqual(self.backend.load().revision, before.revision)
        self.assertEqual(files.render(self.backend.load()), files.render(before))
        real_apply = inventory.apply
        with mock.patch.object(inventory, "apply", wraps=real_apply) as apply:
            saved = self.save(result["preview"])
        apply.assert_called_once()
        args, kwargs = apply.call_args
        self.assertEqual((args[0], args[1].id, args[1].via, args[1].source), (operation, "matt", "tunnel", "web"))
        self.assertEqual(kwargs["expected_revision"], before.revision)
        after = self.backend.load()
        self.assertTrue(saved["saved"])
        self.assertEqual(saved["revision"], after.revision)
        self.assertEqual(files.render(after), files.render(expected))
        self.assertEqual(after.collection(), before.collection())
        self.assertEqual(after.tokens, before.tokens)
        self.assertEqual(after.order(saved["order"]).components[0].status, "pending")
        with inventory.pinned(after), mock.patch.object(shopping, "_cards_ready", return_value=False), \
                mock.patch.object(shopping, "_home_decks", return_value=[]):
            overview = shopping.shopping_overview()
        found = next(order for order in overview["orders"] if order["id"] == saved["order"])
        self.assertEqual(found["status"], "pending")

    def test_cards_csv_keeps_unknown_condition_and_language_blank(self):
        rows = [{key: value for key, value in card("Elvish Mystic", "cmm", "648", 2).items()
                 if key not in ("condition", "language", "notes")}]
        result = self.preview(cards={"csv": csv_text(rows, list(rows[0]))}, fulfils=[{"row": 1, "quantity": 2}])
        self.save(result["preview"])
        row = self.backend.load().payloads["magic/orders/2026-10-15-fixture.csv"].rows[0]
        self.assertEqual((row.text("condition"), row.text("language"), row.text("notes")), ("", "", ""))

    def test_typed_names_and_product_names_are_canonical_before_queue_fulfilment(self):
        result = self.preview(cards={"rows": [card("elvish mystic", "cmm", "648", 2)]},
                              fulfils=[{"row": 1, "quantity": 2}],
                              product={"stem": "fixture-product", "columns": list(PRODUCT_COLUMNS),
                                       "rows": product_rows(("Main", "sol ring", "ecc", "57", 1))})
        self.save(result["preview"])
        after = self.backend.load()
        self.assertEqual(after.payloads["magic/orders/2026-10-15-fixture.csv"].rows[0].name, "Elvish Mystic")
        self.assertEqual(after.product("fixture-product").items[0].text("name"), "Sol Ring")
        self.assertEqual(after.watchlist.rows[0].qty, 1)

    def test_token_only_and_product_only_orders_allow_blank_unknown_metadata(self):
        data = self.request(record={"id": "2026-10-15-tokens"}, fulfils=[],
                            tokens={"csv": csv_text([token("Llanowar Elves", 1)], rules.TOKEN_FIELDS)})
        data.pop("cards")
        preview = shopping_orders.preview_order(json.dumps(data))
        self.assertEqual(preview["counts"], {"tokens": 1, "watchlist_reduced": 0})
        self.save(preview["preview"])
        data = self.request(record={"id": "2026-10-15-product", "seller": "", "ordered_on": "", "notes": ""},
                            fulfils=[], product={"stem": "fixture-precon", "status": "ordered",
                                                "csv": csv_text(product_rows(("Main", "Sol Ring", "ecc", "57", 1)),
                                                                PRODUCT_COLUMNS)})
        data.pop("cards")
        preview = shopping_orders.preview_order(json.dumps(data))
        self.assertEqual(preview["counts"], {"product": 1, "watchlist_reduced": 0})
        self.save(preview["preview"])
        after = self.backend.load()
        self.assertEqual(after.order("2026-10-15-product").seller, "")
        self.assertEqual(after.order("2026-10-15-product").ordered_on, "")
        self.assertEqual(after.product("fixture-precon").items[0].text("deck"), "Main")

    def test_card_and_token_errors_never_save(self):
        for row in (card("Not a card", "cmm", "648", 1), card("Elvish Mystic", "mkm", "170", 1),
                    card("Elvish Mystic", "cmm", "648", 1, finish="etched"),
                    card("Elvish Mystic", "cmm", "648", 0)):
            with self.subTest(row=row):
                self.refused(400, cards={"rows": [row]}, fulfils=[])
        self.refused(400, tokens={"rows": [token("Not a token", 1)]})
        self.refused(400, tokens={"rows": [token("Llanowar Elves", 0)]})

    def test_fulfilment_must_be_present_in_the_order_and_match_exact_printings(self):
        self.refused(400, fulfils=[{"row": 1, "quantity": 4}])
        self.refused(400, fulfils=[{"row": 3}])
        self.refused(400, cards={"rows": [card("Pick Your Poison", "mkm", "170", 1, finish="foil")]},
                     fulfils=[{"row": 2}])
        self.refused(400, fulfils=[{"row": 1, "quantity": 1}, {"row": 1, "quantity": 1}])
        self.refused(400, fulfils=[{"row": 999}])

    def test_exact_revision_is_required_before_name_lookup_or_queue_selection(self):
        for expect in ("stale", self.backend.load().revision + "-stale", " " + self.backend.load().revision):
            with self.subTest(expect=expect), mock.patch.object(shopping_orders, "_require_cards") as cards:
                self.refused(409, expect=expect, fulfils=[{"row": 999}])
                cards.assert_not_called()
        for expect in ("", None, True, [], "a" * 257):
            self.refused(400, expect=expect)

    def test_apply_rejects_stale_inventory_and_concurrent_change_transactionally(self):
        preview = self.preview()
        inventory.apply(inventory.Op("watchlist.set", {"select": "#1", "values": {"notes": "Changed"},
                                                       "repo": str(self.root)}), CLAUDE, "Fixture queue edit")
        before = self.backend.load()
        with self.assertRaises(ApiError) as caught:
            self.save(preview["preview"])
        self.assertEqual(caught.exception.status, 409)
        self.assertEqual(self.backend.load().revision, before.revision)
        preview = self.preview()
        real_apply = inventory.apply

        def concurrent(operation, *args, **kwargs):
            real_apply(inventory.Op("watchlist.set", {"select": "#1", "values": {"notes": "Concurrent"},
                                                       "repo": str(self.root)}), CLAUDE, "Concurrent edit")
            return real_apply(operation, *args, **kwargs)

        with mock.patch.object(inventory, "apply", concurrent), self.assertRaises(ApiError) as caught:
            self.save(preview["preview"])
        self.assertEqual(caught.exception.status, 409)
        self.assertIsNone(self.backend.load().order("2026-10-15-fixture"))

    def test_preview_is_bound_to_writer_and_listener_and_cannot_be_reused(self):
        preview = self.preview()["preview"]
        for identity, writer in (({"profile": "user1", "remote": True}, "user1"), (None, "matt")):
            with access.using(identity), self.assertRaises(ApiError) as caught:
                self.save(preview, profile=writer)
            self.assertEqual(caught.exception.status, 409)
        self.save(preview)
        with self.assertRaises(ApiError) as caught:
            self.save(preview)
        self.assertEqual(caught.exception.status, 409)

    def test_preview_cache_expires_and_is_bounded_and_busy_tokens_cannot_apply(self):
        with mock.patch.object(shopping_orders, "MAX_PREVIEWS", 2):
            first = self.preview()["preview"]
            second = self.preview()["preview"]
            third = self.preview()["preview"]
        self.assertEqual(set(shopping_orders._previews), {second, third})
        with self.assertRaises(ApiError) as caught:
            self.save(first)
        self.assertEqual(caught.exception.status, 409)
        cached = shopping_orders._previews[second]
        cached["busy"] = True
        with self.assertRaises(ApiError) as caught:
            self.save(second)
        self.assertEqual(caught.exception.status, 409)
        cached["busy"] = False
        cached["created"] -= shopping_orders.PREVIEW_LIFETIME + 1
        with self.assertRaises(ApiError) as caught:
            self.save(second)
        self.assertEqual(caught.exception.status, 409)

    def test_new_refresh_failure_refuses_as_cli_and_existing_failure_is_reported(self):
        tables = mock.Mock(return_value=tables_answer(error="New pool problem"))
        plan = mock.Mock(return_value=[])
        with contextlib.ExitStack() as stack:
            fake_refresh(stack, tables, plan)
            operation = shopping_orders._operation(self.request())
            self.assertEqual(inv_orders._refresh_refusal(inventory, operation), "New pool problem")
            self.refused(400)
            plan.side_effect = ValueError("Old pool problem")
            result = self.preview()
            self.assertEqual(result["tables"]["error"], "New pool problem")
            tables.return_value = tables_answer(error="Refresh failed after preview")
            saved = self.save(result["preview"])
        self.assertTrue(saved["saved"])
        self.assertEqual(saved["tables"]["error"], "Refresh failed after preview")

    def test_extra_copy_acknowledgment_uses_normal_operation(self):
        data = {"cards": {"rows": [card("Llanowar Elves", "fdn", "227", 1)]}, "fulfils": []}
        # The only printing in this new component is already owned. The normal
        # order operation preserves its explicit acknowledgement in audit_notes.
        result = self.preview(extra_copies=["cards"], **data)
        self.save(result["preview"])
        after = self.backend.load()
        self.assertEqual(rules.extra_copies(after.order(result["order"]).audit_notes), ("cards",))

    def test_members_and_outsiders_are_refused_before_inventory_or_preview_lookup(self):
        for identity, viewer in (({"profile": "user2", "remote": True}, None), (None, "user2")):
            with access.using(identity), access.viewing(viewer), mock.patch.object(inventory, "current") as read:
                for writer in ("user2", "matt"):
                    for function, body in ((shopping_orders.preview_order, self.request(profile=writer, expect="x")),
                                           (shopping_orders.apply_order, {"profile": writer, "preview": "0" * 32})):
                        with self.assertRaises(ApiError) as caught:
                            function(json.dumps(body))
                        self.assertEqual(caught.exception.status, 403)
                read.assert_not_called()

    def test_bad_shapes_csv_and_unsupported_fields_are_refused(self):
        bad = [{"record": []}, {"record": {"id": "bad id"}}, {"record": {"id": "x", "seller": "two\nlines"}},
               {"record": {"id": "x", "ordered_on": "2026-02-30"}},
               {"record": {"id": "x", "sources": ["../outside.md"]}},
               {"record": {"id": "x", "paid": "1.00"}}, {"force": True}, {"check_cards": False},
               {"cards": []}, {"cards": {"rows": []}}, {"cards": {"rows": [{}] * 501}},
               {"cards": {"csv": "a,b\n1\n"}}, {"cards": {"csv": 2}},
               {"cards": {"rows": [{"name": "Elvish Mystic", "quantity": True}]}},
               {"cards": {"rows": [{"name": "Elvish Mystic", "quantity": 1.2}]}},
               {"cards": {"rows": [{"name": "Elvish Mystic", "quantity": "1" * 5000}]}},
               {"cards": {"rows": [{"name": ["Elvish Mystic"]}]}},
               {"product": {"stem": "x", "csv": "name,name\nSol Ring,Sol Ring\n"}},
               {"product": {"stem": "x", "columns": "name", "rows": [{}]}},
               {"tokens": {"csv": "front,back,quantity\nDog,,1\n"}},
               {"fulfils": [{"row": True}]}, {"fulfils": [{"row": 1, "quantity": False}]},
               {"fulfils": [{"row": 1, "extra": "unknown"}]}, {"extra_copies": "cards"}]
        for changes in bad:
            with self.subTest(changes=str(changes)[:100]):
                self.refused(400, **changes)

    def test_database_and_card_data_failures_write_nothing_and_allow_retry(self):
        with mock.patch.object(inventory, "current", side_effect=inventory.Unavailable("down")):
            self.refused(503)
        with mock.patch.object(shopping_orders, "_require_cards", side_effect=ApiError(503, "No cards")):
            self.refused(503)
        preview = self.preview()["preview"]
        with mock.patch.object(inventory, "apply", side_effect=inventory.Unavailable("down")), \
                self.assertRaises(ApiError) as caught:
            self.save(preview)
        self.assertEqual(caught.exception.status, 503)
        self.assertFalse(shopping_orders._previews[preview]["busy"])
        self.assertTrue(self.save(preview)["saved"])


class FileOrderApiTests(OrderApiTests, unittest.TestCase):
    def setUp(self):
        case = contract.build_tree(order_tree, adapted=True)
        self.addCleanup(case.doCleanups)
        self.backend = FileInventory(case.inventory.root)
        self.start(case)


@unittest.skipIf(db_support.unavailable(), db_support.unavailable() or "")
class PgOrderApiTests(OrderApiTests, db_support.DbTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from decklab.db import profiles_sync
        profiles_sync.sync(listed=contract.FIXTURE_PROFILES, dbname=cls.dbname)

    def setUp(self):
        from decklab.lib.inventory import pg
        from decklab.lib.state import pg as state_pg
        db_support.reset(self.dbname, db_support.INVENTORY_TABLES)
        case = contract.build_tree(order_tree, adapted=True)
        self.addCleanup(case.doCleanups)
        pg.write_model(case.inventory.load(), CLAUDE, "Import fixture", dbname=self.dbname, decks=True)
        self.backend = pg.PgInventory(dbname=self.dbname, breaker=state_pg.Breaker())
        self.start(case)

    def test_mixed_order_is_one_audited_change_by_its_writer_including_the_deck_table(self):
        with self.connect() as connection:
            before = connection.execute("select count(*) from audit.change_set").fetchone()[0]
        preview = shopping_orders.preview_order(json.dumps(self.mixed_request()))
        self.assertIsNone(preview["tables"]["error"], preview["tables"])
        self.assertEqual(preview["tables"]["written"], [{"id": "casual/shopping-test", "title": "Shopping test"}])
        self.save(preview["preview"])
        with self.connect() as connection:
            changes = connection.execute("select id, actor, source, via, message from audit.change_set order by id").fetchall()
            tables = {row[0] for row in connection.execute(
                "select table_name from audit.row_change where change_set_id = %s", (changes[-1][0],)).fetchall()}
        self.assertEqual(len(changes), before + 1)
        self.assertEqual(changes[-1][1:4], ("matt", "web", "tunnel"))
        self.assertIn("2026-10-15-fixture", changes[-1][4])
        self.assertTrue({"purchase_order", "order_component", "order_card_item", "order_token_item", "product",
                         "product_item", "product_status", "watchlist_item", "deck"} <= tables, tables)
