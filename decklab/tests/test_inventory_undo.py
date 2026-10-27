"""Conservative Undo rules over audit-shaped, explicit in-memory test doubles only."""
import copy
import unittest
from unittest import mock

from decklab.lib import inventory
from decklab.lib.inventory import model, rules, undo
from decklab.tests import test_activity_undo_api as fixture


class UndoCoreTests(unittest.TestCase):
    def setUp(self):
        self.case = fixture.ActivityUndoApiTests()
        self.addCleanup(self.case.doCleanups)
        self.case.setUp()
        self.store = self.case.backend

    def review(self):
        return inventory.undo_review(fixture.CHANGE_ID, "home", self.store.snapshot)

    def source(self):
        return self.store.audit[fixture.CHANGE_ID][0]

    def test_inverse_preserves_inputs_and_reports_actual_row_path_and_fields(self):
        before = self.store.snapshot
        original = copy.deepcopy(self.store.audit)
        plan = self.review()
        after, summary = inventory.Op("inventory.undo", {"change_id": fixture.CHANGE_ID, "space": "home", "expect": plan["expect"]}).run(before)
        self.assertEqual(summary.counts["undo"], 1)
        self.assertEqual(summary.extra["undo_of"], fixture.CHANGE_ID)
        self.assertEqual(summary.changed, {after.collection("home").path: [field["field"] for field in plan["fields"]]})
        self.assertEqual(undo.restored_row(after, plan), plan["restore"])
        self.assertEqual(self.store.audit, original)
        self.assertEqual(self.store.snapshot, before)

    def test_token_inverse_preserves_stable_id_and_ordinary_values(self):
        self.case.seed("tokens")
        plan = self.review()
        after, summary = inventory.Op("inventory.undo", {"change_id": fixture.CHANGE_ID, "space": "home", "expect": plan["expect"]}).run(self.store.snapshot)
        self.assertEqual(after.token_set("home").rows[0].id, 7)
        self.assertEqual(undo.restored_row(after, plan), plan["restore"])
        self.assertTrue(summary.changed)

    def test_missing_hidden_mixed_and_extra_source_rows_never_reveal_details(self):
        for mode in ("missing", "hidden", "mixed", "other-table"):
            self.case.seed()
            if mode == "missing":
                self.store.audit.clear()
            if mode == "hidden":
                self.source()["before"]["space_id"] = self.source()["after"]["space_id"] = "user2"
            if mode == "mixed":
                self.store.audit[fixture.CHANGE_ID].append({"table": "profile_email", "after": {"email": "hidden@example.com"}})
            if mode == "other-table":
                self.source()["table"] = "profile_email"
            with self.subTest(mode=mode), self.assertRaises(undo.UndoMissing) as caught:
                self.review()
            self.assertEqual(str(caught.exception), "That change is not available to undo.")

    def test_identity_fact_insert_delete_noop_and_schema_changes_are_unsupported(self):
        for mode in ("name", "set_code", "op-insert", "op-delete", "noop", "extra-column", "missing-column", "bad-key"):
            self.case.seed()
            row = self.source()
            if mode in ("name", "set_code"):
                row["before"][mode] = "Other"
            elif mode.startswith("op-"):
                row["op"] = mode[3:].upper()
            elif mode == "noop":
                row["before"] = copy.deepcopy(row["after"])
            elif mode == "extra-column":
                row["before"]["unknown"] = "x"
            elif mode == "missing-column":
                del row["before"]["notes"]
            else:
                row["key"]["finish"] = "foil"
            with self.subTest(mode=mode), self.assertRaises(undo.UndoUnsupported):
                self.review()

    def test_token_faces_printing_details_id_and_position_are_immutable(self):
        for field in ("front", "back", "set_code", "front_details", "id", "position"):
            self.case.seed("tokens")
            self.source()["before"][field] = 8 if field in ("id", "position") else "different"
            with self.subTest(field=field), self.assertRaises(undo.UndoUnsupported):
                self.review()

    def test_latest_audit_row_not_values_alone_refuses_aba_and_repeated_undo(self):
        self.store.latest += 1
        with self.assertRaises(undo.UndoConflict) as caught:
            self.review()
        self.assertIn("touched", str(caught.exception))
        self.assertTrue(caught.exception.conflicts)

    def test_changed_or_deleted_current_collection_row_refuses(self):
        for rows in ([], [{**fixture.CARD, "notes": "Later edit"}]):
            self.store.snapshot = self.store.snapshot.with_collection("home", rows)
            with self.subTest(rows=rows), self.assertRaises(undo.UndoConflict):
                self.review()

    def test_identical_token_rows_or_replaced_id_are_never_selected_by_first_match(self):
        for duplicate in (False, True):
            self.case.seed("tokens")
            rows = [model.TokenRow.make(fixture.TOKEN, id=8)]
            if duplicate:
                rows.insert(0, model.TokenRow.make(fixture.TOKEN, id=7))
            self.store.snapshot = self.store.snapshot.with_tokens("home", rows)
            with self.subTest(duplicate=duplicate), self.assertRaises(undo.UndoConflict):
                self.review()

    def test_both_revision_counters_bind_the_preview_even_when_target_row_is_unchanged(self):
        for field in ("revision", "decks_revision"):
            self.case.seed()
            plan = self.review()
            self.store.snapshot = self.store.snapshot.replace(**{field: "changed"})
            with self.subTest(field=field), self.assertRaises(undo.UndoConflict):
                inventory.Op("inventory.undo", {"change_id": fixture.CHANGE_ID, "space": "home", "expect": plan["expect"]}).run(self.store.snapshot)

    def test_no_database_audit_backend_is_an_honest_unsupported_result(self):
        with inventory.use(self.case.box.inventory), self.assertRaises(undo.UndoUnsupported):
            inventory.undo_review(fixture.CHANGE_ID, "home")

    def reduction_source(self, kind="collection"):
        self.case.seed(kind)
        self.source()["before"]["quantity"] = 1
        return self.store.snapshot

    def test_collection_shortage_or_unknown_holder_check_refuses_inverse_reduction(self):
        self.reduction_source()
        from decklab.lib.api import collection_guards
        for side_effect in (None, RuntimeError("private source path")):
            with self.subTest(side_effect=side_effect), \
                    mock.patch.object(collection_guards, "reduction_warnings", return_value=[{"name": "held"}], side_effect=side_effect), \
                    self.assertRaises(undo.UndoConflict) as caught:
                self.review()
            self.assertNotIn("private source path", str(caught.exception))

    def test_collection_physical_fallback_warning_is_not_certified_as_free(self):
        self.reduction_source()
        from decklab.lib import pool
        from decklab.lib.api import collection_guards
        with mock.patch.object(collection_guards, "reduction_warnings", return_value=[]), \
                mock.patch.object(pool, "load_pool", return_value=type("Pool", (), {"warning_decks": {"a": "uncertain"}, "in_use": []})()), \
                self.assertRaises(undo.UndoConflict):
            self.review()

    def test_token_reduction_with_unknown_built_packing_is_refused(self):
        self.reduction_source("tokens")
        text = "# Built\n\n- **Status:** built\n\n## Decklist\n\n```\nDeck\n4 Llanowar Elves\n```\n"
        self.store.snapshot = self.store.snapshot.with_deck(model.Deck("home", "casual", "built", text))
        with self.assertRaises(undo.UndoConflict) as caught:
            self.review()
        self.assertIn("Packed token", str(caught.exception))

    def test_product_missing_duplicate_or_unknown_storage_never_means_no_hold(self):
        self.reduction_source()
        # The helper needs only the actual file identity here, not invented deck routes.
        product = type("Product", (), {"file": "fixture.csv"})()
        for rows in ([], [{"file": "fixture.csv", "status": "owned", "intact": ""}],
                     [{"file": "fixture.csv", "status": "owned", "intact": "no"}] * 2):
            sheet = model.Sheet("magic/products/status.csv", tuple(rules.STATUS_FIELDS),
                                tuple(model.StatusRow.make(row) for row in rows), True)
            snapshot = self.store.snapshot.replace(products=(product,), status=sheet)
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                undo._home_products(snapshot, "home")

    def test_unknown_or_duplicate_status_is_not_proof_a_deck_holds_nothing(self):
        for status in ("", "- **Status:** unknown\n", "- **Status:** idea\n- **Status:** built\n"):
            for kind in ("collection", "tokens"):
                self.reduction_source(kind)
                text = "# Possibly built\n\n" + status + "\n## Decklist\n\n```\nDeck\n4 Llanowar Elves\n```\n"
                self.store.snapshot = self.store.snapshot.with_deck(model.Deck("home", "casual", "possible", text))
                with self.subTest(status=status, kind=kind), self.assertRaises(undo.UndoConflict):
                    self.review()

    def test_currently_held_token_row_cannot_be_reduced_by_reallocating_to_a_free_matching_row(self):
        self.reduction_source("tokens")
        current = {**fixture.TOKEN, "quantity": 3}
        self.source()["after"]["quantity"] = 3
        other = {**fixture.TOKEN, "quantity": 4, "notes": "Different physical fixture row"}
        self.store.snapshot = self.store.snapshot.with_tokens("home", [model.TokenRow.make(current, id=7), model.TokenRow.make(other, id=8)])
        text = "# Built\n\n- **Status:** built\n- **Token cards:** 3 Dog\n\n## Decklist\n\n```\nDeck\n4 Llanowar Elves\n```\n"
        self.store.snapshot = self.store.snapshot.with_deck(model.Deck("home", "casual", "built", text))
        with self.assertRaises(undo.UndoConflict):
            self.review()

    def test_unheld_token_and_collection_reductions_can_be_reviewed(self):
        for kind in ("collection", "tokens"):
            self.reduction_source(kind)
            self.store.snapshot = self.store.snapshot.replace(decks={}, products=(),
                status=model.Sheet("magic/products/status.csv", tuple(rules.STATUS_FIELDS), (), True))
            plan = self.review()
            self.assertEqual((plan["kind"], plan["restore"]["quantity"]), (kind, 1))

    def test_restore_receipt_is_read_from_actual_after_row(self):
        plan = self.review()
        after = self.store.snapshot.with_collection("home", [{**plan["restore"], "notes": "Different actual note"}])
        self.assertEqual(undo.restored_row(after, plan)["notes"], "Different actual note")
