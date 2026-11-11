"""Complete status-only kit moves are exact, atomic and checked through ordinary kit.set."""
import copy
from dataclasses import replace
import unittest
from unittest import mock

from decklab.lib import inventory, profiles
from decklab.lib.inventory import product_kit_undo as undo, table_rows
from decklab.tests import household_config, product_kit_undo_support as fixture
from decklab.tests import accessory_undo_support as accessory_fixture
from decklab.tests.test_goldfish import setUpModule, tearDownModule  # noqa: F401


class ProductKitTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(mock.patch.object(profiles, "read", return_value=copy.deepcopy(household_config.PROFILES)))
        self.store = fixture.Store()
        self.addCleanup(inventory.use(self.store))

    def review(self):
        return undo.review(fixture.CID, fixture.OWNERS, self.store.snapshot, self.store)

    def test_shared_fixture_is_exactly_representable_by_the_database_writer(self):
        self.assertEqual(table_rows.representable(fixture.snapshot()), [])

    def test_complete_two_product_swap_reproduces_both_rows_without_partial_selection(self):
        before = self.store.snapshot
        plan = self.review()
        self.assertEqual((plan["row_count"], plan["action"], plan["kit_confirmation_required"]), (2, undo.ACTION, True))
        op = undo.Restore(fixture.CID, fixture.OWNERS, plan["expect"], True, self.store)
        after, summary = op.run(before)
        self.assertEqual(undo._status(after), plan["proof"]["expected"])
        self.assertEqual(after.replace(status=before.status), before)
        actual = [{**row, "id": 200 + i, "before": row["after"], "after": row["before"]}
                  for i, row in enumerate(plan["proof"]["source"])]
        receipt = undo.confirm(before, after, summary, actual, None).extra["product_kit_undo"]
        self.assertEqual(receipt["rows"], plan["rows"])
        self.assertEqual(receipt["revision"], "201")
        self.assertEqual(self.store.snapshot, before)

    def test_legacy_blank_token_column_is_the_only_additive_audit_normalization(self):
        for row in self.store.audit[fixture.CID]:
            row["before"].pop("token_cards")
            row["after"].pop("token_cards")
        original = copy.deepcopy(self.store.audit[fixture.CID])
        plan = self.review()
        before = self.store.snapshot
        after, summary = undo.Restore(fixture.CID, fixture.OWNERS, plan["expect"], True, self.store).run(before)
        actual = [{**row, "id": 200+i, "before": {key: value for key, value in row["after"].items() if key != "token_cards"},
                   "after": {key: value for key, value in row["before"].items() if key != "token_cards"}}
                  for i, row in enumerate(plan["proof"]["source"])]
        self.assertTrue(undo.confirm(before, after, summary, actual, None).extra["product_kit_undo"]["saved"])
        self.assertEqual(self.store.audit[fixture.CID], original)
        self.store.snapshot = self.store.snapshot.with_status_rows([{**row.as_dict(), "token_cards": "[]"}
                                                                   for row in self.store.snapshot.status.rows])
        with self.assertRaises(inventory.Conflict):
            self.review()

    def test_stale_or_preview_inventory_cannot_authorize_kit_recovery(self):
        original = self.store.snapshot
        for snapshot in (original.replace(stale="Database unavailable"), original.replace(revision="1~preview")):
            self.store.snapshot = snapshot
            with self.assertRaises(inventory.Conflict):
                self.review()

    def test_mixed_hidden_extra_or_large_sources_refuse_whole_before_product_labels(self):
        original = copy.deepcopy(self.store.audit[fixture.CID])
        for bad in ([*original, {"table": "deck", "op": "UPDATE"}], [*original] * 26, [],
                    [{**original[0], "op": "DELETE"}], [original[0], original[0]]):
            self.store.audit[fixture.CID] = bad
            with self.subTest(rows=len(bad)), self.assertRaises(inventory.Invalid):
                self.review()

    def test_nonkit_status_position_or_unowned_source_is_unsupported(self):
        for field, value in (("notes", "Other"), ("position", 8), ("token_cards", "[]"), ("status", "ordered"), ("intact", "no"), ("file", "other.csv")):
            self.store = fixture.Store()
            self.store.audit[fixture.CID][0]["before"][field] = value
            with self.subTest(field=field), self.assertRaises(inventory.Invalid):
                self.review()

    def test_private_unknown_legacy_wrong_kind_and_missing_shared_kit_refuse(self):
        for value in ("private-sleeves", "old red sleeves", "missing-id", "shared-box-a"):
            self.store = fixture.Store()
            self.store.audit[fixture.CID][0]["before"]["sleeves"] = value
            with self.subTest(value=value), self.assertRaises(inventory.Invalid):
                self.review()

    def test_current_latest_or_stock_capacity_changes_refuse_without_any_write(self):
        for mode in ("current", "latest", "capacity", "product"):
            self.store = fixture.Store()
            if mode == "current":
                self.store.snapshot = self.store.snapshot.with_status_rows([{**row.as_dict(), "notes": "Changed"} for row in self.store.snapshot.status.rows])
            elif mode == "latest":
                self.store.latest["alpha.csv"] += 9
            elif mode == "capacity":
                rows = [row.as_dict() for row in self.store.snapshot.accessories.rows]
                rows = [{**row, "quantity": "0"} if row["id"] == "shared-box-a" else row for row in rows]
                self.store.snapshot = self.store.snapshot.with_accessories(rows)
            else:
                self.store.snapshot = replace(self.store.snapshot, products=())
            with self.subTest(mode=mode), self.assertRaises((inventory.Invalid, inventory.Conflict)):
                self.review()
            self.assertEqual(self.store.writes, [])

    def test_unrelated_private_kit_and_member_deck_changes_do_not_stale_visible_plan(self):
        plan = self.review()
        rows = [{**row.as_dict(), "notes": "Private changed"} if row.accessory_id == "private-sleeves" else row.as_dict()
                for row in self.store.snapshot.accessories.rows]
        self.store.snapshot = self.store.snapshot.with_accessories(rows)
        member = replace(accessory_fixture.build_snapshot().deck("casual/fixture"), space="user2", slug="private", text=None, error="PRIVATE unreadable member deck")
        self.store.snapshot = self.store.snapshot.replace(decks={**self.store.snapshot.decks, member.id: member})
        self.assertEqual(self.review()["expect"], plan["expect"])

    def test_confirmation_and_current_receipt_are_required_on_fresh_review(self):
        plan = self.review()
        for consent in (False, None, 1, "true"):
            with self.subTest(consent=consent), self.assertRaises(inventory.Invalid):
                undo.Restore(fixture.CID, fixture.OWNERS, plan["expect"], consent, self.store).run(self.store.snapshot)
        with self.assertRaises(inventory.Conflict):
            undo.Restore(fixture.CID, fixture.OWNERS, "0" * 64, True, self.store).run(self.store.snapshot)

    def test_selected_product_name_or_contents_are_part_of_current_review_fence(self):
        plan = self.review()
        product = self.store.snapshot.product("alpha")
        changed = replace(product, name="Current renamed product", items=(product.items[0].replace(quantity="61"),))
        self.store.snapshot = self.store.snapshot.replace(products=tuple(changed if row.stem == "alpha" else row for row in self.store.snapshot.products))
        self.assertNotEqual(self.review()["expect"], plan["expect"])
        with self.assertRaises(inventory.Conflict):
            undo.Restore(fixture.CID, fixture.OWNERS, plan["expect"], True, self.store).run(self.store.snapshot)

    def test_wrong_audit_actual_row_ids_reason_or_nonstatus_effects_fail_confirmation(self):
        plan = self.review()
        before = self.store.snapshot
        after, summary = undo.Restore(fixture.CID, fixture.OWNERS, plan["expect"], True, self.store).run(before)
        original = [{**row, "id": 200 + i, "before": row["after"], "after": row["before"]}
                    for i, row in enumerate(plan["proof"]["source"])]
        for mode in ("id", "duplicate-id", "partial", "extra", "row", "reason"):
            actual = copy.deepcopy(original)
            if mode == "id": actual[0]["id"] = 101
            if mode == "duplicate-id": actual[1]["id"] = actual[0]["id"]
            if mode == "partial": actual.pop()
            if mode == "extra": actual.append({"id": 205, "table": "deck"})
            if mode == "row": actual[0]["after"]["notes"] = "Unexpected"
            with self.subTest(mode=mode), self.assertRaises(inventory.Conflict):
                undo.confirm(before, after, summary, actual, "Unexpected reason" if mode == "reason" else None)
