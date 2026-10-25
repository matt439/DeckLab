"""Pending Shopping payload edits and extra-copy flags, on files and disposable PostgreSQL."""
import contextlib
import csv
import json
import unittest
from unittest import mock

from decklab.lib import inventory
from decklab.lib.api import shopping, shopping_order_changes as api
from decklab.lib.api.common import ApiError
from decklab.lib.inventory import files, orders, rules
from decklab.lib.inventory.files import FileInventory
from decklab.tests import db_support, test_inventory_contract as contract
from decklab.tests.test_inventory_orders import CLAUDE, card, fake_refresh, tables_answer, token
from decklab.tests.test_shopping_order_changes import ORDER, OrderChangeApiTests, changes_tree


class OrderRowsApiTests:
    start = OrderChangeApiTests.start
    request = OrderChangeApiTests.request
    save = OrderChangeApiTests.save
    refused = OrderChangeApiTests.refused

    def rows(self, component="cards", order=ORDER):
        before = self.backend.load()
        found = orders._component(before, order, component)[1]
        return [{key: row.text(key) for key in orders.PAYLOAD_FIELDS[found.kind]}
                for row in before.payloads[found.path].rows]

    def change(self, action="edit", component="cards", **values):
        data = self.request(action=action, component=component, **values)
        data.pop("values")
        if action == "edit" and "rows" not in data:
            data["rows"] = self.rows(component, data["order"])
            data["rows"][0]["notes"] = "Verified printing"
        return data

    def preview(self, **values):
        return api.preview_order_change(json.dumps(self.change(**values)))

    def overview(self):
        with inventory.pinned(), mock.patch.object(shopping, "_cards_ready", return_value=False), \
                mock.patch.object(shopping, "_home_decks", return_value=[]):
            return shopping.shopping_overview()

    def test_overview_exposes_exact_pending_rows_and_flags_without_card_cache(self):
        overview = self.overview()
        records = {order["id"]: order for order in overview["orders"]}
        cards, tokens = records[ORDER]["components"]
        self.assertEqual(cards["edit_rows"], self.rows())
        self.assertEqual(tokens["edit_rows"], self.rows("tokens"))
        self.assertTrue(cards["extra_copies"])
        self.assertNotIn("extra_copies", tokens)
        product = records["2026-10-02-precon"]["components"][0]
        self.assertFalse(product["extra_copies"])
        self.assertNotIn("edit_rows", product)
        received = records["2026-10-01-shop"]["components"][0]
        self.assertNotIn("edit_rows", received)
        self.assertNotIn("extra_copies", received)

    def test_card_rows_split_finish_preserve_unknowns_metadata_and_checks(self):
        before = self.backend.load()
        rows = [card("Elvish Mystic", "cmm", "648", 1, notes="Printing confirmed"),
                card("Elvish Mystic", "cmm", "648", 1, finish="foil", condition="LP", language="en"),
                self.rows()[1]]
        preview = self.preview(rows=rows)
        expected = sorted(rows, key=rules.sort_key)
        self.assertEqual(preview["component"], {"id": "cards", "kind": "cards", "rows": expected,
                                               "extra_copies": True})
        self.assertEqual(files.render(self.backend.load()), files.render(before))
        self.assertIn({"id": "casual/shopping-test", "title": "Shopping test"}, preview["tables"]["written"])
        saved = self.save(preview["preview"])
        after = self.backend.load()
        self.assertEqual(saved["component"], preview["component"])
        self.assertEqual(self.rows(), expected)
        self.assertEqual(after.order(ORDER).record(), before.order(ORDER).record())
        self.assertEqual(after.collection(), before.collection())
        self.assertEqual(after.tokens, before.tokens)
        self.assertEqual(after.watchlist, before.watchlist)
        self.assertEqual(after.order(ORDER).components[0].status, "pending")

    def test_token_pairings_details_and_unknown_fields_survive_edit_and_save(self):
        rows = [token("llanowar elves", 1, back="Llanowar Elves", details="1/1; green",
                      notes="Keep the physical pairing"),
                token("Llanowar Elves", 1, details="P/T unknown", notes="Unreported back")]
        rows[0]["back_details"] = "1/1; green; abilities unspecified"
        preview = self.preview(component="tokens", rows=rows)
        expected = [dict(row, front="Llanowar Elves") for row in rows]
        self.assertEqual(preview["component"], {"id": "tokens", "kind": "tokens", "rows": expected,
                                               "extra_copies": False})
        self.save(preview["preview"])
        self.assertEqual(self.rows("tokens"), expected)
        self.assertEqual(list(self.backend.load().order(ORDER).components[0].checks),
                         ["Record conditions", "Check languages"])

    def test_invalid_rows_printings_totals_and_shapes_write_nothing(self):
        original = self.rows()
        bad_rows = [[], {}, [None], [dict(original[0], quantity=True), original[1]],
                    [dict(original[0], quantity=0), original[1]],
                    [dict(original[0], quantity=3), original[1]],
                    [dict(original[0], name="Not a card"), original[1]],
                    [dict(original[0], name="Llanowar Elves", set="fdn", collector_number="227"), original[1]],
                    [dict(original[0], set="mkm", collector_number="170"), original[1]],
                    [dict(original[0], finish="etched"), original[1]],
                    [dict(original[0], notes="with\0NUL"), original[1]],
                    [dict(original[0], paid="1.00"), original[1]],
                    [{key: value for key, value in original[0].items() if key != "condition"}, original[1]]]
        for rows in bad_rows:
            with self.subTest(rows=rows):
                self.refused(400, self.change(rows=rows))
        for row in (token("Not a token", 2), dict(token("Llanowar Elves", 2), set="fdn",
                                                 front_collector_number="227")):
            self.refused(400, self.change(component="tokens", rows=[row]))
        for extra in ({"check_cards": False}, {"force": True}, {"csv": "anything"}, {"undo": False}):
            self.refused(400, self.change(**extra))

    def test_multiline_and_whitespace_metadata_roundtrip_when_another_field_changes(self):
        for component in ("cards", "tokens"):
            rows = self.rows(component)
            rows[0]["notes"] = "  Preserve notes\nsecond line\r\n\t" + "long notes " * 300 + "  "
            if component == "tokens":
                rows[0]["front_details"] = "1/1; green\nabilities unspecified"
            else:
                rows[0]["condition"] = "  unreported  "
            first = self.preview(component=component, rows=rows)
            self.save(first["preview"])
            restored = self.rows(component)
            self.assertEqual(restored, rows)
            restored[0]["finish"] = "foil" if component == "cards" else "nonfoil"
            preview = self.preview(component=component, rows=restored)
            self.assertEqual(preview["component"]["rows"], restored)
            self.save(preview["preview"])
            self.assertEqual(self.rows(component), restored)

    def test_rows_require_cache_but_extra_copy_toggle_does_not(self):
        with mock.patch.object(api, "_require_cards", side_effect=ApiError(503, "Card data unavailable")) as ready:
            self.refused(503, self.change())
            self.refused(503, self.change(component="tokens"))
            result = self.preview(action="extra_copies", undo=True)
            self.save(result["preview"])
        self.assertEqual(ready.call_count, 2)

    def test_only_pending_cards_and_tokens_can_change_rows(self):
        for values in ({"order": "2026-10-02-precon", "component": "precon", "rows": self.rows()},
                       {"order": "2026-10-01-shop", "rows": self.rows()},
                       {"order": "missing", "rows": self.rows()}, {"component": "missing", "rows": self.rows()}):
            self.refused(400, self.change(**values))
        inventory.apply(inventory.Op("order.cancel", {"order": ORDER, "component": "cards", "reason": "Not sent"}),
                        CLAUDE, "Cancel fixture", reason="Not sent")
        self.refused(400, self.change(rows=[card("Elvish Mystic", "cmm", "648", 2)]))

    def test_noop_rows_leave_revision_tables_and_payload_unchanged(self):
        before = self.backend.load()
        preview = self.preview(rows=self.rows())
        self.assertEqual(preview["changes"], [])
        self.assertEqual(preview["tables"], tables_answer())
        saved = self.save(preview["preview"])
        self.assertEqual(saved["revision"], before.revision)
        self.assertEqual(files.render(self.backend.load()), files.render(before))

    def test_extra_copy_mark_and_unmark_preserve_provenance_and_component_fields(self):
        before = self.backend.load()
        for undo in (True, False):
            preview = self.preview(action="extra_copies", undo=undo)
            self.assertEqual(preview["component"]["extra_copies"], not undo)
            self.save(preview["preview"])
            after = self.backend.load().order(ORDER)
            self.assertIn("Keep provenance.", after.audit_notes)
            self.assertEqual([component.record() for component in after.components],
                             [component.record() for component in before.order(ORDER).components])
            self.assertEqual(self.rows(), [{key: row.text(key) for key in rules.FIELDS}
                                           for row in before.payloads[after.components[0].path].rows])
        self.assertEqual(self.backend.load().order(ORDER).audit_notes, before.order(ORDER).audit_notes)
        for undo in (False, True):
            preview = self.preview(action="extra_copies", component="precon", order="2026-10-02-precon", undo=undo)
            self.assertEqual(preview["component"], {"id": "precon", "kind": "product", "rows": [],
                                                   "extra_copies": not undo})
            self.save(preview["preview"])

    def test_extra_copy_invalid_boolean_kind_and_status_are_refused(self):
        for undo in (0, 1, "false", None, [], {}):
            self.refused(400, self.change(action="extra_copies", undo=undo))
        self.refused(400, self.change(action="extra_copies"))
        self.refused(400, self.change(action="extra_copies", component="tokens", undo=False))
        self.refused(400, self.change(action="extra_copies", order="2026-10-01-shop", undo=False))

    def test_unmark_refuses_an_actual_new_owned_printing_pool_blocker(self):
        from decklab.lib.inventory import ops_collection  # noqa: F401 (registers collection.import)
        self.save(self.preview(action="extra_copies", order="2026-10-02-precon",
                               component="precon", undo=False)["preview"])
        inventory.apply(inventory.Op("collection.import", {
            "space": "home", "sources": [("Fixture owned copies", self.rows())]}), CLAUDE, "Add fixture copies")
        self.refused(400, self.change(action="extra_copies", undo=True))
        self.assertTrue(self.backend.load().order(ORDER).audit_notes.endswith("cards."))

    def test_refresh_refuses_new_blockers_but_reports_existing_failures_for_edit_and_unmark(self):
        for values in ({}, {"action": "extra_copies", "undo": True}):
            with self.subTest(values=values), contextlib.ExitStack() as stack:
                tables = mock.Mock(return_value=tables_answer(error="New pool problem"))
                plan = mock.Mock(return_value=[])
                fake_refresh(stack, tables, plan)
                self.refused(400, self.change(**values))
                plan.side_effect = ValueError("Existing pool problem")
                preview = self.preview(**values)
                self.assertEqual(preview["tables"]["error"], "New pool problem")
                saved = self.save(preview["preview"])
                self.assertEqual(saved["tables"]["error"], "New pool problem")

    def test_edit_and_toggle_previews_cannot_overwrite_a_transaction_race(self):
        for values in ({}, {"action": "extra_copies", "undo": True}):
            preview = self.preview(**values)
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
            self.assertEqual(after.order(ORDER).audit_notes, before.order(ORDER).audit_notes)
            self.assertEqual(after.order(ORDER).notes, "Concurrent")
            # Ensure the second iteration also introduces a real concurrent change.
            actual(inventory.Op("order.record", {"order": ORDER, "values": {"notes": "Reset"}}), CLAUDE, "Reset")

    def test_csv_errors_are_sanitized_and_warning_paths_are_scrubbed(self):
        with mock.patch.object(orders, "card_rows", side_effect=csv.Error(r"Bad C:\Users\private\cards.csv")):
            self.refused(400, self.change())
        with mock.patch.object(orders, "check_card_rows", return_value=[r"Check C:\Users\private\cards.csv"]):
            preview = self.preview()
            self.assertEqual(preview["warnings"], ["Check cards.csv"])


class FileOrderRowsApiTests(OrderRowsApiTests, unittest.TestCase):
    def setUp(self):
        case = contract.build_tree(changes_tree, adapted=True)
        self.addCleanup(case.doCleanups)
        self.backend = FileInventory(case.inventory.root)
        self.start(case)


@unittest.skipIf(db_support.unavailable(), db_support.unavailable() or "")
class PgOrderRowsApiTests(OrderRowsApiTests, db_support.DbTestCase):
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

    def test_edit_and_refreshed_table_share_one_audited_change_and_transaction(self):
        from decklab.lib.inventory import pg
        preview = self.preview()
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
        self.save(preview["preview"])
        with self.connect() as connection:
            changes = connection.execute("select id, actor, source, via from audit.change_set order by id").fetchall()
            tables = {row[0] for row in connection.execute(
                "select table_name from audit.row_change where change_set_id = %s", (changes[-1][0],)).fetchall()}
        self.assertEqual(len(changes), count + 1)
        self.assertEqual(changes[-1][1:], ("matt", "web", "tunnel"))
        self.assertTrue({"order_card_item", "deck"} <= tables, tables)
