"""Pending product corrections on Shopping, using fixtures and disposable PostgreSQL."""
import contextlib
import dataclasses
import json
import unittest
from unittest import mock

from decklab.lib import access, inventory
from decklab.lib.api import settings, shopping, shopping_order_changes as api
from decklab.lib.api.common import ApiError
from decklab.lib.inventory import files
from decklab.lib.inventory.files import FileInventory
from decklab.tests import db_support, test_inventory_contract as contract
from decklab.tests.test_inventory_orders import CLAUDE, fake_refresh, tables_answer
from decklab.tests.test_shopping_order_changes import OrderChangeApiTests, changes_tree
from decklab.tests.test_shopping_orders import csv_text


ORDER = "2026-10-02-precon"
OWNED_ORDER = "product-fdn-beginner-box"


class ProductApiTests:
    start = OrderChangeApiTests.start
    save = OrderChangeApiTests.save
    refused = OrderChangeApiTests.refused

    def request(self, **changes):
        data = {"profile": "matt", "expect": self.backend.load().revision, "order": ORDER,
                "action": "product", "component": "precon", "values": {"notes": "Corrected product details"}}
        data.update(changes)
        return data

    def preview(self, **changes):
        return api.preview_order_change(json.dumps(self.request(**changes)))

    def product(self):
        before = self.backend.load()
        return shopping._editable_product(before, before.order(ORDER).components[0])

    def overview(self):
        with inventory.pinned(), mock.patch.object(shopping, "_cards_ready", return_value=False), \
                mock.patch.object(shopping, "_home_decks", return_value=[]):
            return shopping.shopping_overview()

    def replacement(self):
        columns = ["section", "name", "set", "collector_number", "finish", "quantity", "rarity",
                   "condition", "language", "in_play_boosters", "notes"]
        rows = [{key: "" for key in columns}]
        rows[0].update(section="deck", name="Elvish Mystic", set="cmm", collector_number="648",
                       finish="nonfoil", quantity="2", rarity=" common ", condition=" unreported ",
                       notes='  Keep "quoted", notes\nsecond line\r\n\t' + "long notes " * 300 + "  ")
        return columns, rows

    def test_overview_offers_exact_pending_product_to_admin_without_card_data(self):
        before = self.backend.load()
        records = {order["id"]: order for order in self.overview()["orders"]}
        shown = records[ORDER]["components"][0]
        self.assertEqual(shown["edit_product"], self.product())
        self.assertEqual(shown["edit_product"]["status"], "preordered")
        self.assertEqual(shown["edit_product"]["notes"], "due soon")
        self.assertNotIn("edit_product", records[OWNED_ORDER]["components"][0])
        self.assertEqual(files.render(self.backend.load()), files.render(before))
        listed = [dict(profile, role="member") if profile["id"] == "user1" else profile
                  for profile in contract.FIXTURE_PROFILES]
        with mock.patch.object(settings, "_config_profiles", return_value=listed), \
                access.using({"profile": "user1", "remote": True}):
            for order in self.overview()["orders"]:
                self.assertTrue(all("edit_product" not in component for component in order["components"]))

    def test_metadata_preview_needs_no_card_cache_and_only_supplied_fields_change(self):
        before = self.backend.load()
        with mock.patch.object(api, "_require_cards", side_effect=ApiError(503, "Card data unavailable")) as ready:
            preview = self.preview(values={"name": "Correct display name", "format": "Casual precon",
                                           "status": "ordered", "notes": "Expected delivery details"})
        ready.assert_not_called()
        shown = preview["component"]
        self.assertEqual(shown["id"], "precon")
        self.assertEqual(shown["kind"], "product")
        self.assertEqual(shown["product"], {**self.product(), "name": "Correct display name",
                                           "format": "Casual precon", "status": "ordered",
                                           "notes": "Expected delivery details"})
        self.assertEqual(files.render(self.backend.load()), files.render(before))
        saved = self.save(preview["preview"])
        self.assertEqual(saved["component"]["product"]["status"], "ordered")
        self.assertEqual(self.product()["notes"], "Expected delivery details")
        self.assertEqual(self.backend.load().order(ORDER).record(), before.order(ORDER).record())
        self.assertEqual(self.backend.load().product("precon").items, before.product("precon").items)

    def test_name_only_preview_reports_product_change_and_refreshes_tables(self):
        before = self.backend.load()
        preview = self.preview(values={"name": "corrected-name"})
        self.assertIn("Product corrected-name", preview["changes"])
        self.assertIn({"id": "casual/shopping-test", "title": "Shopping test"}, preview["tables"]["written"])
        self.assertEqual(preview["component"]["product"], {**self.product(), "name": "corrected-name"})
        self.assertEqual(files.render(self.backend.load()), files.render(before))

    def test_csv_replacement_preserves_optional_fields_and_atomically_refreshes_tables(self):
        before = self.backend.load()
        columns, rows = self.replacement()
        preview = self.preview(values={}, csv="\ufeff" + csv_text(rows, columns))
        expected = {**self.product(), "columns": columns, "rows": rows}
        self.assertEqual(preview["component"]["product"], expected)
        self.assertIn({"id": "casual/shopping-test", "title": "Shopping test"}, preview["tables"]["written"])
        self.assertEqual(files.render(self.backend.load()), files.render(before))
        real_apply = inventory.apply
        with mock.patch.object(inventory, "apply", wraps=real_apply) as apply:
            saved = self.save(preview["preview"])
        apply.assert_called_once()
        self.assertEqual(apply.call_args.kwargs["expected_revision"], before.revision)
        self.assertEqual(saved["component"]["product"], expected)
        self.assertEqual(self.product(), expected)
        after = self.backend.load()
        self.assertEqual(after.order(ORDER).record(), before.order(ORDER).record())
        self.assertEqual(after.collection(), before.collection())
        self.assertEqual(after.watchlist, before.watchlist)
        self.assertEqual(after.tokens, before.tokens)

    def test_structured_replacement_and_notes_clear_retain_exact_columns(self):
        columns, rows = self.replacement()
        preview = self.preview(values={"notes": ""}, columns=columns, rows=rows)
        self.save(preview["preview"])
        self.assertEqual(self.product()["rows"], rows)
        self.assertEqual(self.product()["columns"], columns)
        self.assertEqual(self.product()["notes"], "")

    def test_invalid_replacements_metadata_and_uneditable_statuses_write_nothing(self):
        columns, rows = self.replacement()
        bad = [{"values": {}}, {"values": []}, {"values": {"status": "owned"}},
               {"values": {"status": "cancelled"}}, {"values": {"name": "two\nlines"}},
               {"values": {"paid": "1.00"}}, {"values": {"intact": "yes"}}, {"force": True},
               {"check_cards": False}, {"csv": ""}, {"csv": "name,name\nA,A\n"},
               {"csv": 'name,quantity\n"unterminated,1\n'}, {"csv": "name,quantity\nElvish Mystic\n"},
               {"csv": "name,quantity\nElvish Mystic,1,extra\n"},
               {"csv": csv_text(rows, columns), "columns": columns, "rows": rows},
               {"columns": columns}, {"rows": rows}, {"columns": columns, "rows": []},
               {"columns": [*columns, "paid"], "rows": [{**rows[0], "paid": "1.00"}]},
               {"columns": columns, "rows": [{**rows[0], "name": "Not a card"}]},
               {"columns": columns, "rows": [{**rows[0], "quantity": True}]},
               {"columns": columns, "rows": [{**rows[0], "quantity": "0"}]},
               {"columns": columns, "rows": [{**rows[0], "notes": "NUL\0"}]},
               {"columns": columns, "rows": [{key: value for key, value in rows[0].items() if key != "notes"}]},
               {"order": "missing"}, {"component": "missing"},
               {"order": "2026-10-07-shop-a", "component": "cards"},
               {"order": OWNED_ORDER, "component": OWNED_ORDER}]
        for values in bad:
            with self.subTest(values=str(values)[:100]):
                self.refused(400, self.request(**values))
        before = self.backend.load()
        component = before.order(ORDER).components[0].record()
        component["status"] = "cancelled"
        record = before.order(ORDER).record()
        record["components"] = [component]
        cancelled = before.with_order(dataclasses.replace(before.order(ORDER), data=record))
        with mock.patch.object(inventory, "current", return_value=cancelled):
            self.refused(400, self.request(expect=cancelled.revision))

    def test_list_requires_card_data_and_new_table_failures_are_refused(self):
        columns, rows = self.replacement()
        with mock.patch.object(api, "_require_cards", side_effect=ApiError(503, "No card data")):
            self.refused(503, self.request(values={}, columns=columns, rows=rows))
        with contextlib.ExitStack() as stack:
            tables = mock.Mock(return_value=tables_answer(error="New pool problem"))
            plan = mock.Mock(return_value=[])
            fake_refresh(stack, tables, plan)
            self.refused(400, self.request(columns=columns, rows=rows))
            plan.side_effect = ValueError("Existing pool problem")
            preview = self.preview(columns=columns, rows=rows)
            self.assertEqual(preview["tables"]["error"], "New pool problem")

    def test_product_preview_keeps_writer_listener_and_exact_revision_guards(self):
        preview = self.preview()
        for identity, viewer, writer in (({"profile": "user1", "remote": True}, None, "user1"),
                                         (None, "matt", "matt")):
            with access.using(identity), access.viewing(viewer), self.assertRaises(ApiError) as caught:
                self.save(preview["preview"], profile=writer)
            self.assertEqual(caught.exception.status, 409)
        self.save(self.preview(values={"notes": "Newer correction"})["preview"])
        with self.assertRaises(ApiError) as caught:
            self.save(preview["preview"])
        self.assertEqual(caught.exception.status, 409)
        self.assertEqual(self.product()["notes"], "Newer correction")
        self.refused(409, self.request(expect="stale"))

    def test_home_and_person_space_members_are_refused_before_inventory_lookup(self):
        listed = [dict(profile, role="member") if profile["id"] == "user1" else profile
                  for profile in contract.FIXTURE_PROFILES]
        for person in ("user1", "user2"):
            for remote in (False, True):
                with self.subTest(person=person, remote=remote), \
                        mock.patch.object(settings, "_config_profiles", return_value=listed), \
                        access.using({"profile": person, "remote": True} if remote else None), \
                        access.viewing(None if remote else person):
                    data = self.request(profile=person, expect="x")
                    with mock.patch.object(inventory, "current") as read:
                        for function, body in ((api.preview_order_change, data),
                                               (api.apply_order_change, {"profile": person, "preview": "0" * 32})):
                            with self.assertRaises(ApiError) as caught:
                                function(json.dumps(body))
                            self.assertEqual(caught.exception.status, 403)
                        read.assert_not_called()

    def test_unchanged_product_keeps_inventory_revision_and_tables(self):
        before = self.backend.load()
        preview = self.preview(values={"notes": self.product()["notes"]})
        self.assertEqual(preview["changes"], [])
        self.assertEqual(preview["tables"], tables_answer())
        saved = self.save(preview["preview"])
        self.assertEqual(saved["revision"], before.revision)
        self.assertEqual(files.render(self.backend.load()), files.render(before))


class FileProductApiTests(ProductApiTests, unittest.TestCase):
    def setUp(self):
        case = contract.build_tree(changes_tree, adapted=True)
        self.addCleanup(case.doCleanups)
        self.backend = FileInventory(case.inventory.root)
        self.start(case)


@unittest.skipIf(db_support.unavailable(), db_support.unavailable() or "")
class PgProductApiTests(ProductApiTests, db_support.DbTestCase):
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

    def test_product_fields_rows_and_table_are_one_audited_transaction(self):
        from decklab.lib.inventory import pg
        columns, rows = self.replacement()
        metadata = {"name": "Correct product", "format": "Casual", "status": "ordered", "notes": "Confirmed list"}
        preview = self.preview(values=metadata, columns=columns, rows=rows)
        before = self.backend.load()
        with self.connect() as connection:
            count = connection.execute("select count(*) from audit.change_set").fetchone()[0]
        real_diff = pg._diff

        def fail_after_inventory_write(*args):
            real_diff(*args)
            raise RuntimeError("Transaction failed after product write")

        with mock.patch.object(pg, "_diff", fail_after_inventory_write), self.assertRaises(ApiError) as caught:
            self.save(preview["preview"])
        self.assertEqual(caught.exception.status, 400)
        self.assertEqual(self.backend.load(), before)
        with self.connect() as connection:
            self.assertEqual(connection.execute("select count(*) from audit.change_set").fetchone()[0], count)
        saved = self.save(preview["preview"])
        self.assertEqual(saved["component"]["product"], {**metadata, "columns": columns, "rows": rows})
        self.assertEqual(self.product(), saved["component"]["product"])
        with self.connect() as connection:
            changes = connection.execute("select id, actor, source, via from audit.change_set order by id").fetchall()
            tables = {row[0] for row in connection.execute(
                "select table_name from audit.row_change where change_set_id = %s", (changes[-1][0],)).fetchall()}
        self.assertEqual(len(changes), count + 1)
        self.assertEqual(changes[-1][1:], ("matt", "web", "tunnel"))
        self.assertTrue({"product", "product_item", "product_status", "deck"} <= tables, tables)

    def test_display_metadata_can_be_cleared_without_changing_the_list(self):
        self.save(self.preview(values={"name": "Correct name", "format": "Casual"})["preview"])
        rows = self.product()["rows"]
        saved = self.save(self.preview(values={"name": "", "format": ""})["preview"])
        self.assertEqual(saved["component"]["product"]["name"], "")
        self.assertEqual(self.product()["format"], "")
        self.assertEqual(self.product()["rows"], rows)


if __name__ == "__main__":
    unittest.main()
