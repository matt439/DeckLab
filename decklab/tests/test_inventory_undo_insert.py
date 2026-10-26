"""A single audited collection INSERT may be undone only as a safe explicit removal.

All records come from the existing isolated audit-shaped fixture. No database,
household inventory, process inspection or network operation is involved.
"""
import copy
import json
import unittest

from decklab.lib import inventory
from decklab.lib.inventory import model, rules, undo
from decklab.lib.state import Invalid
from decklab.tests import test_activity_undo_api as fixture


REASON = "Correct an accidental card addition."


class InsertUndoTests(unittest.TestCase):
    def setUp(self):
        self.case = fixture.ActivityUndoApiTests()
        self.addCleanup(self.case.doCleanups)
        self.case.setUp()
        self.store = self.case.backend
        self.products = self.store.snapshot.products
        self.store.snapshot = self.store.snapshot.replace(decks={}, products=(),
            status=model.Sheet("magic/products/status.csv", tuple(rules.STATUS_FIELDS), (), True))
        self.seed()

    def seed(self, row=None, space="home"):
        card = copy.deepcopy(fixture.CARD if row is None else row)
        self.store.snapshot = self.store.snapshot.with_collection(space, [card])
        raw = {"set_code" if key == "set" else key: value for key, value in card.items()}
        raw["space_id"] = space
        self.store.audit[fixture.CHANGE_ID] = [{"id": fixture.ROW_ID, "table": undo.COLLECTION,
            "op": "INSERT", "key": {key: raw[key] for key in undo.COLLECTION_KEYS}, "before": None, "after": raw}]
        self.store.latest = fixture.ROW_ID
        return card

    def source(self):
        return self.store.audit[fixture.CHANGE_ID][0]

    def review(self):
        return inventory.undo_review(fixture.CHANGE_ID, "home", self.store.snapshot)

    def apply(self, plan=None, **extra):
        plan = self.review() if plan is None else plan
        return inventory.Op("inventory.undo", {"change_id": fixture.CHANGE_ID, "space": "home",
            "expect": plan["expect"], "reason": REASON, **extra}).run(self.store.snapshot)

    def add_other_printing(self):
        self.store.snapshot = self.store.snapshot.with_collection("home", [fixture.CARD,
            {**fixture.CARD, "set": "m19", "collector_number": "314", "quantity": 20}])

    def built(self, main="1 Llanowar Elves\n59 Forest", headers=""):
        text = "# Physical fixture\n\n- **Format:** Casual 60-card, 1v1\n- **Status:** built\n" + headers \
            + "\n## Decklist\n\n```\nDeck\n" + main + "\n```\n"
        self.store.snapshot = self.store.snapshot.with_deck(model.Deck("home", "casual", "physical", text))

    @staticmethod
    def standins(using="Llanowar Elves", version="target"):
        return {"target": [], "owned": [], "built": {"version": version,
            "cards": [{"for": "Opt", "using": using, "qty": 1}]}}

    def test_review_describes_removal_and_does_not_mutate_source_or_snapshot(self):
        original = copy.deepcopy(self.store.audit)
        snapshot = self.store.snapshot
        plan = self.review()
        self.assertEqual(plan["action"], "remove")
        self.assertTrue(plan["reason_required"])
        self.assertEqual(plan["current"], fixture.CARD)
        self.assertIsNone(plan["restore"])
        self.assertEqual(plan["key"], self.source()["key"])
        self.assertEqual(plan["row_change_id"], fixture.ROW_ID)
        self.assertRegex(plan["expect"], r"^[a-f0-9]{64}$")
        self.assertEqual(self.store.audit, original)
        self.assertEqual(self.store.snapshot, snapshot)

    def test_ordinary_removal_can_remove_last_row_and_confirms_actual_absence(self):
        plan = self.review()
        snapshot, original = self.store.snapshot, copy.deepcopy(self.store.audit)
        after, summary = self.apply(plan)
        self.assertEqual(after.collection("home").rows, ())
        self.assertIsNone(undo.restored_row(after, plan))
        self.assertEqual(summary.counts["undo"], 1)
        self.assertEqual(summary.counts["cards"], fixture.CARD["quantity"])
        self.assertEqual(summary.extra["undo_of"], fixture.CHANGE_ID)
        self.assertEqual(summary.extra["row_change_id"], fixture.ROW_ID)
        self.assertTrue(summary.changed)
        self.assertEqual(self.store.snapshot, snapshot)
        self.assertEqual(self.store.audit, original)

    def test_removal_preserves_other_printing_and_unrelated_rows(self):
        self.add_other_printing()
        before = self.store.snapshot
        plan = self.review()
        after, _ = self.apply(plan)
        self.assertEqual([row.as_dict() for row in after.collection("home").rows],
                         [before.collection("home").rows[1].as_dict()])
        self.assertIsNone(undo.restored_row(after, plan))

    def test_absence_receipt_refuses_a_snapshot_that_still_has_target_key(self):
        plan = self.review()
        with self.assertRaises(undo.UndoConflict):
            undo.restored_row(self.store.snapshot, plan)

    def test_removal_requires_a_short_nonblank_text_reason(self):
        plan = self.review()
        for reason in (None, "", " \n\t ", 1, [], {}, "x" * 201):
            with self.subTest(reason=type(reason).__name__), self.assertRaises(Invalid):
                self.apply(plan, reason=reason)
        params = {"change_id": fixture.CHANGE_ID, "space": "home", "expect": plan["expect"]}
        with self.assertRaises(Invalid):
            inventory.Op("inventory.undo", params).run(self.store.snapshot)
        after, _ = self.apply(plan, reason="  " + REASON + "  ")
        self.assertEqual(after.collection("home").rows, ())

    def test_original_update_inverse_still_works_without_a_removal_reason(self):
        self.case.seed()
        plan = self.review()
        self.assertIsNotNone(plan["restore"])
        after, _ = inventory.Op("inventory.undo", {"change_id": fixture.CHANGE_ID, "space": "home",
            "expect": plan["expect"]}).run(self.store.snapshot)
        self.assertEqual(undo.restored_row(after, plan), plan["restore"])

    def test_hidden_missing_and_multirow_source_are_indistinguishable(self):
        for mode in ("hidden", "missing", "mixed"):
            self.seed()
            if mode == "hidden":
                self.source()["after"]["space_id"] = "user2"
            elif mode == "missing":
                self.store.audit.clear()
            else:
                self.store.audit[fixture.CHANGE_ID].append({"table": "profile_email", "op": "INSERT",
                    "before": None, "after": {"profile_id": "user2", "email": "hidden@example.com"}})
            with self.subTest(mode=mode), self.assertRaises(undo.UndoMissing) as caught:
                self.review()
            self.assertEqual(str(caught.exception), "That change is not available to undo.")

    def test_insert_needs_exact_schema_null_before_and_original_key(self):
        for mode in ("old-row", "extra-column", "missing-column", "bad-key", "invalid-quantity"):
            self.seed()
            if mode == "old-row":
                self.source()["before"] = copy.deepcopy(self.source()["after"])
            elif mode == "extra-column":
                self.source()["after"]["future_field"] = "unconfirmed"
            elif mode == "missing-column":
                del self.source()["after"]["notes"]
            elif mode == "bad-key":
                self.source()["key"]["finish"] = "foil"
            else:
                self.source()["after"]["quantity"] = True
            with self.subTest(mode=mode), self.assertRaises((undo.UndoMissing, undo.UndoUnsupported)):
                self.review()

    def test_latest_audit_identity_blocks_aba_recreation_and_repeat_removal(self):
        plan = self.review()
        self.store.latest += 1          # Later UPDATE, DELETE or recreate; values alone cannot authorize Undo.
        with self.assertRaises(undo.UndoConflict):
            self.review()
        with self.assertRaises(undo.UndoConflict):
            self.apply(plan)
        self.seed()
        plan = self.review()
        after, _ = self.apply(plan)
        self.store.snapshot = after
        self.store.latest += 1
        with self.assertRaises(undo.UndoConflict):
            self.apply(plan)

    def test_current_full_row_and_both_revisions_remain_required(self):
        plan = self.review()
        for field in ("revision", "decks_revision"):
            before = self.store.snapshot
            self.store.snapshot = before.replace(**{field: "later"})
            with self.subTest(field=field), self.assertRaises(undo.UndoConflict):
                self.apply(plan)
            self.store.snapshot = before
        self.store.snapshot = self.store.snapshot.with_collection("home", [{**fixture.CARD, "notes": "Later note"}])
        with self.assertRaises(undo.UndoConflict):
            self.review()

    def test_every_basic_land_insert_is_outside_this_conservative_removal_slice(self):
        for name in ("Forest", "Snow-Covered Island", "Wastes"):
            self.seed({**fixture.CARD, "name": name, "finish": "foil", "notes": "Full-art fixture"})
            with self.subTest(name=name), self.assertRaises((undo.UndoUnsupported, undo.UndoConflict)):
                self.review()

    def test_built_use_blocks_removing_another_printing_even_with_surplus_copies(self):
        self.add_other_printing()
        self.built()
        with self.assertRaises(undo.UndoConflict):
            self.review()

    def test_installed_named_marker_is_a_physical_holder_despite_other_copies(self):
        self.add_other_printing()
        self.built("1 Opt\n59 Forest", "- **Stand-ins:** " + json.dumps(self.standins()) + "\n")
        with self.assertRaises(undo.UndoConflict):
            self.review()

    def test_anonymous_installed_marker_cannot_prove_target_printing_is_free(self):
        self.add_other_printing()
        self.built("1 Opt\n59 Forest", "- **Stand-ins:** " + json.dumps(self.standins(using=None)) + "\n")
        with self.assertRaises(undo.UndoConflict):
            self.review()

    def test_duplicate_standin_headers_are_not_proof_that_first_mapping_is_authoritative(self):
        self.add_other_printing()
        headers = "- **Stand-ins:** " + json.dumps({"target": [], "owned": [], "built": None}) + "\n" \
            + "- **Stand-ins:** " + json.dumps(self.standins()) + "\n"
        self.built("1 Opt\n59 Forest", headers)
        with self.assertRaises(undo.UndoConflict):
            self.review()

    def test_frozen_assembly_still_holds_target_after_intended_list_changes(self):
        self.add_other_printing()
        physical = {"version": "target", "sections": {"Deck": ["1 Llanowar Elves", "59 Forest"]}}
        self.built("1 Opt\n59 Forest", "- **Assembled:** " + json.dumps(physical) + "\n")
        with self.assertRaises(undo.UndoConflict):
            self.review()

    def test_intact_product_use_refuses_even_when_other_printing_copies_cover_it(self):
        self.add_other_printing()
        product = next(product for product in self.products if product.file == "fdn-beginner-box.csv")
        status = model.StatusRow.make({"file": product.file, "status": "owned", "intact": "yes"})
        self.store.snapshot = self.store.snapshot.replace(products=(product,),
            status=model.Sheet("magic/products/status.csv", tuple(rules.STATUS_FIELDS), (status,), True))
        with self.assertRaises(undo.UndoConflict):
            self.review()

    def test_unknown_product_storage_and_deck_status_refuse_instead_of_assuming_free(self):
        self.built(headers="- **Status:** idea\n")
        with self.assertRaises(undo.UndoConflict):
            self.review()
        self.store.snapshot = self.store.snapshot.replace(decks={}, products=self.products[:1])
        with self.assertRaises(undo.UndoConflict):
            self.review()
