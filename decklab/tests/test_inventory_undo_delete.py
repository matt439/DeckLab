"""A deleted collection row is restored from exact audit facts after ownership confirmation.

Composition reuses the isolated INSERT fixture without collecting its TestCase
again. Nothing here reads a real collection, database or remote card source.
"""
import copy
import unittest
from unittest import mock

from decklab.lib import cards, inventory
from decklab.lib.inventory import model, ops_collection, rules, undo
from decklab.lib.state import Invalid
from decklab.tests import test_activity_undo_api as fixture
from decklab.tests import test_inventory_undo_insert as insert_fixture


class DeleteUndoTests(unittest.TestCase):
    def setUp(self):
        self.case = insert_fixture.InsertUndoTests()
        self.addCleanup(self.case.doCleanups)
        self.case.setUp()
        self.store = self.case.store
        self.seed()

    def seed(self, row=None, space="home"):
        restored = copy.deepcopy(fixture.CARD if row is None else row)
        raw = {"set_code" if key == "set" else key: value for key, value in restored.items()}
        raw["space_id"] = space
        self.store.audit[fixture.CHANGE_ID] = [{"id": fixture.ROW_ID, "table": undo.COLLECTION,
            "op": "DELETE", "key": {key: raw[key] for key in undo.COLLECTION_KEYS}, "before": raw, "after": None}]
        self.store.snapshot = self.store.snapshot.with_collection(space, [])
        self.store.latest = fixture.ROW_ID
        return restored

    def source(self):
        return self.store.audit[fixture.CHANGE_ID][0]

    def review(self):
        return inventory.undo_review(fixture.CHANGE_ID, "home", self.store.snapshot)

    def apply(self, plan=None, **extra):
        plan = self.review() if plan is None else plan
        return inventory.Op("inventory.undo", {"change_id": fixture.CHANGE_ID, "space": "home",
            "expect": plan["expect"], "confirm_owned": True, **extra}).run(self.store.snapshot)

    def test_review_shows_exact_old_row_and_requires_physical_ownership_confirmation(self):
        snapshot, original = self.store.snapshot, copy.deepcopy(self.store.audit)
        plan = self.review()
        self.assertEqual(plan["action"], "add")
        self.assertIs(plan["physical_confirmation_required"], True)
        self.assertIsNone(plan["current"])
        self.assertEqual(plan["restore"], fixture.CARD)
        self.assertEqual(plan["key"], self.source()["key"])
        self.assertEqual(plan["row_change_id"], fixture.ROW_ID)
        self.assertRegex(plan["expect"], r"^[a-f0-9]{64}$")
        self.assertEqual(self.store.audit, original)
        self.assertEqual(self.store.snapshot, snapshot)

    def test_empty_collection_restore_is_one_exact_add_without_merging(self):
        plan = self.review()
        snapshot, original = self.store.snapshot, copy.deepcopy(self.store.audit)
        after, summary = self.apply(plan)
        self.assertEqual(undo.restored_row(after, plan), fixture.CARD)
        self.assertEqual(len(after.collection("home").rows), 1)
        for key, expected in (("cards", 2), ("added_rows", 1), ("bumped_rows", 0), ("skipped_basics", 0), ("merged", False)):
            self.assertEqual(summary.counts[key], expected, key)
        self.assertEqual(summary.counts["undo"], 1)
        self.assertEqual(summary.extra["undo_of"], fixture.CHANGE_ID)
        self.assertEqual(summary.extra["row_change_id"], fixture.ROW_ID)
        self.assertTrue(summary.changed)
        self.assertEqual(self.store.audit, original)
        self.assertEqual(self.store.snapshot, snapshot)

    def test_nonempty_collection_preserves_other_printings_and_restores_exact_quantity(self):
        other = {**fixture.CARD, "set": "m19", "collector_number": "314", "quantity": 20, "notes": "Other printing"}
        self.store.snapshot = self.store.snapshot.with_collection("home", [other])
        before = self.store.snapshot.collection("home").rows[0].as_dict()
        plan = self.review()
        after, summary = self.apply(plan)
        self.assertEqual(undo.restored_row(after, plan), fixture.CARD)
        self.assertEqual(next(row.as_dict() for row in after.collection("home").rows if row.set == "m19"), before)
        self.assertEqual(summary.counts["cards"], fixture.CARD["quantity"])

    def test_confirmation_must_be_exact_boolean_true_and_cannot_be_omitted(self):
        plan = self.review()
        for value in (None, False, 0, 1, "true", "yes", [], {}):
            with self.subTest(value=repr(value)), self.assertRaises(Invalid):
                self.apply(plan, confirm_owned=value)
        with self.assertRaises(Invalid):
            inventory.Op("inventory.undo", {"change_id": fixture.CHANGE_ID, "space": "home",
                "expect": plan["expect"]}).run(self.store.snapshot)
        self.assertEqual(self.store.snapshot.collection("home").rows, ())

    def test_existing_target_key_is_a_conflict_even_when_every_fact_matches_history(self):
        self.store.snapshot = self.store.snapshot.with_collection("home", [fixture.CARD])
        with self.assertRaises(undo.UndoConflict):
            self.review()

    def test_existing_key_with_other_name_or_quantity_is_never_merged(self):
        for row in ({**fixture.CARD, "quantity": 1}, {**fixture.CARD, "name": "Elvish Mystic"}):
            self.store.snapshot = self.store.snapshot.with_collection("home", [row])
            with self.subTest(row=row), self.assertRaises(undo.UndoConflict):
                self.review()

    def test_latest_row_proof_refuses_later_add_remove_aba_even_when_key_absent(self):
        plan = self.review()
        self.store.latest += 2
        with self.assertRaises(undo.UndoConflict):
            self.review()
        with self.assertRaises(undo.UndoConflict):
            self.apply(plan)

    def test_both_revisions_bind_the_preview_and_repeated_restore_conflicts(self):
        plan = self.review()
        for field in ("revision", "decks_revision"):
            original = self.store.snapshot
            self.store.snapshot = original.replace(**{field: "later"})
            with self.subTest(field=field), self.assertRaises(undo.UndoConflict):
                self.apply(plan)
            self.store.snapshot = original
        after, _ = self.apply(plan)
        self.store.snapshot = after
        self.store.latest += 1
        with self.assertRaises(undo.UndoConflict):
            self.apply(plan)

    def test_hidden_missing_and_mixed_sources_do_not_reveal_the_old_row(self):
        for mode in ("hidden", "missing", "mixed"):
            self.seed()
            if mode == "hidden":
                self.source()["before"]["space_id"] = "user2"
            elif mode == "missing":
                self.store.audit.clear()
            else:
                self.store.audit[fixture.CHANGE_ID].append({"table": "profile_email", "op": "DELETE",
                    "before": {"email": "hidden@example.com"}, "after": None})
            with self.subTest(mode=mode), self.assertRaises(undo.UndoMissing) as caught:
                self.review()
            self.assertEqual(str(caught.exception), "That change is not available to undo.")

    def test_source_requires_complete_schema_key_and_null_after(self):
        for mode in ("new-row", "missing-column", "extra-column", "bad-key", "bad-quantity", "bad-notes"):
            self.seed()
            if mode == "new-row":
                self.source()["after"] = copy.deepcopy(self.source()["before"])
            elif mode == "missing-column":
                del self.source()["before"]["notes"]
            elif mode == "extra-column":
                self.source()["before"]["future_field"] = "Unconfirmed"
            elif mode == "bad-key":
                self.source()["key"]["finish"] = "foil"
            elif mode == "bad-quantity":
                self.source()["before"]["quantity"] = True
            else:
                self.source()["before"]["notes"] = None
            with self.subTest(mode=mode), self.assertRaises((undo.UndoMissing, undo.UndoUnsupported)):
                self.review()

    def test_unknown_and_noncanonical_names_are_refused_without_silent_renaming(self):
        for name in ("No such fixture card", "llanowar elves", " Llanowar Elves "):
            self.seed({**fixture.CARD, "name": name})
            with self.subTest(name=name), self.assertRaises((undo.UndoUnsupported, undo.UndoConflict)):
                self.review()

    def test_unknown_wrong_card_digital_or_unsupported_finish_printings_are_refused(self):
        variants = [{"collector_number": "9999"}, {"set": "ttsr", "collector_number": "12"},
                    {"set": "pana", "collector_number": "4"}, {"finish": "etched"},
                    {"set": "m19", "collector_number": "314", "finish": "foil"}]
        for variant in variants:
            self.seed({**fixture.CARD, **variant})
            with self.subTest(variant=variant), self.assertRaises((undo.UndoUnsupported, undo.UndoConflict)):
                self.review()
        printed = cards.printing("fdn", "227")
        for malformed in ({"games": "paper"}, {"games": ["paper", None]},
                          {"finishes": "nonfoil"}, {"finishes": {"foil": True}},
                          {"finishes": ["foil", False]}):
            self.seed({**fixture.CARD, "finish": "foil"})
            with self.subTest(malformed=malformed), \
                    mock.patch.object(cards, "printing", return_value={**printed, **malformed}), \
                    self.assertRaises((undo.UndoUnsupported, undo.UndoConflict)):
                self.review()
        for malformed in (False, [], "not card metadata"):
            self.seed()
            with self.subTest(card_type=type(malformed).__name__), \
                    mock.patch.object(cards, "printing_card", return_value=malformed), \
                    self.assertRaises((undo.UndoUnsupported, undo.UndoConflict)):
                self.review()

    def test_missing_cached_index_is_an_honest_refusal_without_an_update_attempt(self):
        with self.case.case.box.no_index(), mock.patch.object(cards, "update", side_effect=AssertionError("network update")):
            with self.assertRaises((undo.UndoUnsupported, undo.UndoConflict)):
                self.review()

    def test_unknown_and_historical_metadata_are_preserved_exactly(self):
        for metadata in ({"condition": "", "language": "", "notes": "Unknown physical facts"},
                         {"condition": " legacy condition ", "language": " legacy language ",
                          "notes": "First line; repeated; repeated\nSecond line with Unicode é and trailing spaces  "},
                         {"notes": "first\rsecond"}):
            restored = self.seed({**fixture.CARD, **metadata})
            plan = self.review()
            after, _ = self.apply(plan)
            self.assertEqual(undo.restored_row(after, plan), restored)

    def test_source_that_cannot_roundtrip_csv_exactly_is_refused_before_writing(self):
        self.seed({**fixture.CARD, "notes": "  Keep these exact spaces  "})
        original = rules.collection_csv_bytes
        def tidied(rows):
            changed = [{**row, "notes": row["notes"].strip()} for row in rows]
            return original(changed)
        with mock.patch.object(rules, "collection_csv_bytes", side_effect=tidied), \
                self.assertRaises((undo.UndoUnsupported, undo.UndoConflict)):
            self.review()

    def test_ordinary_add_cannot_silently_change_a_recorded_field(self):
        original = ops_collection.add
        def tidied(*args, **kwargs):
            after, summary = original(*args, **kwargs)
            rows = [{**row.as_dict(), "notes": "Normalized instead of restored"} for row in after.collection("home").rows]
            return after.with_collection("home", rows), summary
        with mock.patch.object(ops_collection, "add", side_effect=tidied), \
                self.assertRaises((undo.UndoUnsupported, undo.UndoConflict)):
            self.review()

    def test_unreadable_current_collection_is_not_treated_as_an_empty_target(self):
        for issue in ("error", "strict_error", "csv_error"):
            sheet = model.Sheet("magic/collection.csv", tuple(rules.FIELDS), (), True, **{issue: "Private fixture detail"})
            self.store.snapshot = self.store.snapshot.replace(collections={"home": sheet})
            with self.subTest(issue=issue), self.assertRaises(undo.UndoConflict) as caught:
                self.review()
            self.assertNotIn("Private fixture detail", str(caught.exception))

    def test_plain_basics_refuse_but_verified_foil_and_special_basics_can_be_restored(self):
        basic = {**fixture.CARD, "name": "Forest", "set": "tst", "collector_number": "1",
                 "finish": "nonfoil", "notes": ""}
        printed = {"name": "Forest", "oracle_id": "fixture-forest", "set": "tst", "collector_number": "1",
                   "finishes": ["nonfoil", "foil"], "games": ["paper"], "digital": False, "oversized": False,
                   "set_type": "expansion"}
        card = {"name": "Forest", "oracle_id": "fixture-forest", "paper": True}
        resolve = cards.resolve
        with mock.patch.object(cards, "resolve", side_effect=lambda name: "Forest" if name == "Forest" else resolve(name)), \
                mock.patch.object(cards, "printing", return_value=printed), \
                mock.patch.object(cards, "printing_card", return_value=card), \
                mock.patch.object(cards, "card", return_value=card):
            self.seed(basic)
            with self.assertRaises(undo.UndoUnsupported):
                self.review()
            for change in ({"finish": "foil"}, {"notes": "Full-art basic"}):
                restored = self.seed({**basic, **change})
                plan = self.review()
                after, _ = self.apply(plan)
                self.assertEqual(undo.restored_row(after, plan), restored)
