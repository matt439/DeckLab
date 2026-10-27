"""Exact batch restoration of deleted collection rows over isolated audit fixtures.

Composition collects only these tests, without inheriting the existing DELETE
TestCase. No database, real household data, network or process checks are used.
"""
import copy
import unittest
from unittest import mock

from decklab.lib import cards, inventory
from decklab.lib.inventory import changes, model, ops_collection, rules, undo
from decklab.lib.state import Invalid
from decklab.tests import test_activity_undo_api as fixture
from decklab.tests import test_inventory_undo_delete as delete_fixture


KEY_FIELDS = ("space_id", "set_code", "collector_number", "finish")
DEFAULT_ROWS = [copy.deepcopy(fixture.CARD),
                {**fixture.CARD, "set": "m19", "collector_number": "314", "quantity": 3,
                 "condition": "", "language": "", "notes": "Another recorded printing"}]


class BatchDeleteUndoTests(unittest.TestCase):
    def setUp(self):
        self.case = delete_fixture.DeleteUndoTests()
        self.addCleanup(self.case.doCleanups)
        self.case.setUp()
        self.store = self.case.store
        self.store.undo_audit = lambda change_id: copy.deepcopy(self.store.audit.get(change_id, [])[:2])
        self.store.undo_audit_batch = lambda change_id: copy.deepcopy(self.store.audit.get(change_id, [])[:51])
        self.store.undo_latest = lambda table, key: self.latest.get(tuple(key[field] for field in KEY_FIELDS))
        self.seed()

    def seed(self, count=2, rows=None):
        if rows is None:
            rows = copy.deepcopy(DEFAULT_ROWS[:count])
            rows += [{**fixture.CARD, "collector_number": str(1000 + index)} for index in range(2, count)]
        source = []
        self.latest = {}
        for index, row in enumerate(copy.deepcopy(rows)):
            before = {"space_id": "home", **{"set_code" if key == "set" else key: value for key, value in row.items()}}
            key = {field: before[field] for field in KEY_FIELDS}
            row_id = fixture.ROW_ID + index
            source.append({"id": row_id, "table": undo.COLLECTION, "op": "DELETE", "key": key,
                           "before": before, "after": None})
            self.latest[tuple(key[field] for field in KEY_FIELDS)] = row_id
        self.store.audit[fixture.CHANGE_ID] = source
        self.store.snapshot = self.store.snapshot.with_collection("home", [])
        return source

    def source(self):
        return self.store.audit[fixture.CHANGE_ID]

    def review(self):
        return inventory.undo_review(fixture.CHANGE_ID, "home", self.store.snapshot)

    def apply(self, plan=None, **extra):
        plan = self.review() if plan is None else plan
        return inventory.Op("inventory.undo", {"change_id": fixture.CHANGE_ID, "space": "home",
            "expect": plan["expect"], "confirm_owned": True, **extra}).run(self.store.snapshot)

    @staticmethod
    def receipts(plan):
        return [{"key": {field: item["restore"][field] for field in ("set", "collector_number", "finish")},
                 "row": item["restore"]} for item in plan["rows"]]

    def unchanged(self, snapshot, audit):
        self.assertEqual(self.store.snapshot, snapshot)
        self.assertEqual(self.store.audit, audit)

    def test_empty_collection_review_and_restore_are_exact_and_require_all_copy_confirmation(self):
        snapshot, audit = self.store.snapshot, copy.deepcopy(self.store.audit)
        plan = self.review()
        self.assertEqual((plan["action"], plan["kind"], plan["space"], plan["row_count"]),
                         ("batch_add", "collection", "home", 2))
        self.assertIs(plan["physical_confirmation_required"], True)
        self.assertNotIn("fields", plan)
        self.assertRegex(plan["expect"], r"^[a-f0-9]{64}$")
        for item, source in zip(plan["rows"], self.source()):
            self.assertIsNone(item["current"])
            self.assertNotIn("fields", item)
            self.assertEqual((item["key"], item["row_change_id"]), (source["key"], source["id"]))
        after, summary = self.apply(plan)
        self.assertEqual(undo.restored_rows(after, plan), self.receipts(plan))
        self.assertEqual(summary.counts, {"added_rows": 2, "bumped_rows": 0, "skipped_basics": 0,
                                        "merged": False, "cards": 5, "undo": 1})
        self.assertEqual((summary.extra["action"], summary.extra["row_count"]), ("batch_add", 2))
        self.assertIs(summary.extra["confirmed_owned"], True)
        self.assertEqual(summary.extra["row_change_ids"], [item["id"] for item in self.source()])
        self.unchanged(snapshot, audit)

    def test_other_printings_spaces_and_all_noncollection_namespaces_are_preserved(self):
        home = {**fixture.CARD, "finish": "foil", "quantity": 19, "notes": "Existing other finish"}
        member = {**fixture.CARD, "quantity": 7, "notes": "Synthetic member stock stays private"}
        self.store.snapshot = self.store.snapshot.with_collection("home", [home]).with_collection("user2", [member])
        before = self.store.snapshot
        plan = self.review()
        after, summary = self.apply(plan)
        stored = {rules.ident(row.as_dict()): row.as_dict() for row in after.collection("home").rows}
        self.assertEqual(stored[rules.ident(home)], before.collection("home").rows[0].as_dict())
        self.assertEqual(after.collection("user2"), before.collection("user2"))
        self.assertEqual(set(after.collections), {"home", "user2"})
        self.assertEqual(after, before.replace(collections=after.collections))
        self.assertEqual(summary.counts["cards"], 5)  # Restored units, not all 24 home copies.
        # The namespace may also be created when only another space has stock.
        self.store.snapshot = before.with_collection("home", [])
        after, _ = self.apply()
        self.assertEqual(set(after.collections), {"home", "user2"})
        self.assertEqual(after.collection("user2"), before.collection("user2"))

    def test_fifty_complete_deletes_are_supported_and_fifty_first_never_truncates_authority(self):
        self.seed(50)
        catalog = {(record["before"]["set_code"], record["before"]["collector_number"]):
                   {"name": record["before"]["name"], "digital": False, "games": ["paper"], "finishes": ["nonfoil"]}
                   for record in self.source()}
        with mock.patch.object(cards, "printing", side_effect=lambda set_code, number: catalog.get((set_code, number))), \
                mock.patch.object(cards, "printing_card", side_effect=lambda set_code, number: catalog.get((set_code, number))):
            self.assertEqual(len(self.store.undo_audit(fixture.CHANGE_ID)), 2)
            plan = self.review()
            self.assertEqual(plan["row_count"], 50)
            after, summary = self.apply(plan)
            self.assertEqual(len(undo.restored_rows(after, plan)), 50)
            self.assertEqual(summary.counts["added_rows"], 50)
        self.seed(51)
        self.source()[-1]["before"]["space_id"] = "user2"
        with mock.patch.object(cards, "printing", side_effect=AssertionError("truncated batch read")), \
                self.assertRaises(undo.UndoMissing) as caught:
            self.review()
        self.assertEqual(str(caught.exception), "That change is not available to undo.")

    def test_complete_batch_reader_is_required_and_cannot_return_a_single_row(self):
        reader = self.store.undo_audit_batch
        for replacement in (None, lambda _: None, lambda _: [], lambda _: copy.deepcopy(self.source()[:1])):
            self.store.undo_audit_batch = replacement
            with self.subTest(reader=type(replacement).__name__), self.assertRaises(undo.UndoMissing):
                self.review()
        self.store.undo_audit_batch = reader
        self.seed(1)
        with mock.patch.object(self.store, "undo_audit_batch", side_effect=AssertionError("single row used batch reader")):
            self.assertEqual(self.review()["action"], "add")

    def test_later_hidden_source_wins_before_bad_own_schema_labels_or_cached_card_reads(self):
        self.source()[0]["before"]["unknown_schema"] = "Own unsupported fact"
        self.source()[-1]["before"]["space_id"] = "user2"
        self.source()[-1]["before"]["name"] = "Hidden synthetic member card"
        with mock.patch.object(undo, "_label", side_effect=AssertionError("private label read")), \
                mock.patch.object(cards, "printing", side_effect=AssertionError("private card read")), \
                self.assertRaises(undo.UndoMissing) as caught:
            self.review()
        self.assertEqual(str(caught.exception), "That change is not available to undo.")

    def test_mixed_operations_tables_and_incomplete_global_records_never_authorize_a_subset(self):
        for mode in ("update", "insert", "other-table", "missing-before", "non-null-after", "not-object"):
            self.seed()
            record = self.source()[-1]
            if mode == "update":
                record["op"], record["after"] = "UPDATE", copy.deepcopy(record["before"])
            elif mode == "insert":
                record["op"], record["after"], record["before"] = "INSERT", record["before"], None
            elif mode == "other-table":
                record.update(table="profile_email", before={"email": "hidden@example.com"})
            elif mode == "missing-before":
                record["before"] = None
            elif mode == "non-null-after":
                record["after"] = {}
            else:
                self.source()[-1] = None
            with self.subTest(mode=mode), self.assertRaises(undo.UndoMissing):
                self.review()

    def test_duplicate_source_keys_and_audit_ids_refuse_before_any_label_or_add(self):
        for mode in ("key", "id"):
            self.seed()
            if mode == "key":
                self.source()[1] = {**copy.deepcopy(self.source()[0]), "id": self.source()[1]["id"]}
            else:
                self.source()[1]["id"] = self.source()[0]["id"]
            with self.subTest(mode=mode), mock.patch.object(undo, "_label", side_effect=AssertionError("duplicate label")), \
                    mock.patch.object(ops_collection, "add", side_effect=AssertionError("duplicate add")), \
                    self.assertRaises(undo.UndoUnsupported):
                self.review()

    def test_each_deleted_source_requires_exact_schema_key_id_and_positive_integer_quantity(self):
        for mode in ("missing-column", "extra-column", "bad-key", "bad-id", "boolean-quantity", "zero", "nontext"):
            self.seed()
            record = self.source()[-1]
            if mode == "missing-column":
                del record["before"]["notes"]
            elif mode == "extra-column":
                record["before"]["future"] = "Unsupported"
            elif mode == "bad-key":
                record["key"]["finish"] = "foil"
            elif mode == "bad-id":
                record["id"] = True
            elif mode == "boolean-quantity":
                record["before"]["quantity"] = True
            elif mode == "zero":
                record["before"]["quantity"] = 0
            else:
                record["before"]["notes"] = None
            with self.subTest(mode=mode), self.assertRaises((undo.UndoMissing, undo.UndoUnsupported)):
                self.review()

    def test_one_existing_target_printing_never_merges_even_when_old_facts_match(self):
        for existing in (DEFAULT_ROWS[1], {**DEFAULT_ROWS[1], "quantity": 9},
                         {**DEFAULT_ROWS[1], "name": "Elvish Mystic"}):
            self.seed()
            self.store.snapshot = self.store.snapshot.with_collection("home", [existing])
            with self.subTest(existing=existing), mock.patch.object(ops_collection, "add", side_effect=AssertionError("existing key add")), \
                    self.assertRaises(undo.UndoConflict):
                self.review()

    def test_one_later_key_touch_refuses_even_when_every_target_is_currently_absent(self):
        plan = self.review()
        key = self.source()[-1]["key"]
        self.latest[tuple(key[field] for field in KEY_FIELDS)] += 2
        with self.assertRaises(undo.UndoConflict):
            self.review()
        with self.assertRaises(undo.UndoConflict):
            self.apply(plan)
        self.assertEqual(self.store.snapshot.collection("home").rows, ())

    def test_both_revisions_bind_all_restored_rows_and_repeat_application_conflicts(self):
        plan = self.review()
        for field in ("revision", "decks_revision"):
            snapshot = self.store.snapshot
            self.store.snapshot = snapshot.replace(**{field: "later"})
            with self.subTest(field=field), self.assertRaises(undo.UndoConflict):
                self.apply(plan)
            self.store.snapshot = snapshot
        after, _ = self.apply(plan)
        self.store.snapshot = after
        with self.assertRaises(undo.UndoConflict):
            self.apply(plan)

    def test_confirmation_is_exact_boolean_true_for_every_copy_and_cannot_be_omitted(self):
        plan = self.review()
        snapshot, audit = self.store.snapshot, copy.deepcopy(self.store.audit)
        for value in (None, False, 0, 1, "true", "yes", [], {}):
            with self.subTest(value=repr(value)), self.assertRaises(Invalid):
                self.apply(plan, confirm_owned=value)
        with self.assertRaises(Invalid):
            inventory.Op("inventory.undo", {"change_id": fixture.CHANGE_ID, "space": "home", "expect": plan["expect"]}).run(snapshot)
        self.unchanged(snapshot, audit)

    def test_noncanonical_unknown_or_unsupported_printing_facts_refuse_the_whole_batch(self):
        variants = [{"name": "llanowar elves"}, {"name": "Unknown synthetic card"},
                    {"collector_number": "9999"}, {"set": "ttsr", "collector_number": "12"},
                    {"finish": "foil"}]
        for variant in variants:
            self.seed(rows=[DEFAULT_ROWS[0], {**DEFAULT_ROWS[1], **variant}])
            with self.subTest(variant=variant), mock.patch.object(ops_collection, "add", side_effect=AssertionError("unverified batch add")), \
                    self.assertRaises(undo.UndoUnsupported):
                self.review()
        with self.case.case.case.box.no_index(), mock.patch.object(cards, "update", side_effect=AssertionError("network update")), \
                self.assertRaises(undo.UndoUnsupported):
            self.review()

    def test_plain_basics_refuse_but_verified_foil_or_special_basics_restore_exactly(self):
        basic = {**fixture.CARD, "name": "Forest", "set": "tst", "collector_number": "1", "notes": ""}
        original_resolve, original_printing, original_card = cards.resolve, cards.printing, cards.printing_card
        printed = {"name": "Forest", "digital": False, "games": ["paper"], "finishes": ["nonfoil", "foil"]}
        def printing(set_code, number):
            return printed if (set_code, number) == ("tst", "1") else original_printing(set_code, number)
        def printing_card(set_code, number):
            return {"name": "Forest"} if (set_code, number) == ("tst", "1") else original_card(set_code, number)
        with mock.patch.object(cards, "resolve", side_effect=lambda name: "Forest" if name == "Forest" else original_resolve(name)), \
                mock.patch.object(cards, "printing", side_effect=printing), mock.patch.object(cards, "printing_card", side_effect=printing_card):
            self.seed(rows=[DEFAULT_ROWS[0], basic])
            with self.assertRaises(undo.UndoUnsupported):
                self.review()
            for variant in ({"finish": "foil"}, {"notes": "Full-art basic"}):
                self.seed(rows=[DEFAULT_ROWS[0], basic | variant])
                plan = self.review()
                after, _ = self.apply(plan)
                self.assertEqual(undo.restored_rows(after, plan), self.receipts(plan))

    def test_historical_metadata_is_preserved_without_trimming_merging_or_normalization(self):
        rows = [DEFAULT_ROWS[0] | {"condition": " legacy condition ", "language": " legacy language ",
                                  "notes": '  Repeated; repeated; "gift", caf\u00e9\nNext line\tlast  '},
                DEFAULT_ROWS[1] | {"condition": "", "language": "", "notes": "first\rsecond"}]
        self.seed(rows=rows)
        plan = self.review()
        after, _ = self.apply(plan)
        self.assertEqual([item["row"] for item in undo.restored_rows(after, plan)], rows)
        for notes in (None, 1, True, [], {}, "Invalid\0database text", "Invalid\ud800Unicode"):
            self.seed(rows=[DEFAULT_ROWS[0], DEFAULT_ROWS[1] | {"notes": notes}])
            with self.subTest(type=type(notes).__name__), self.assertRaises(undo.UndoUnsupported):
                self.review()

    def test_each_ordinary_add_must_report_exact_nonmerged_counts(self):
        original_add = ops_collection.add
        snapshot, audit = self.store.snapshot, copy.deepcopy(self.store.audit)
        for field, wrong in (("added_rows", 0), ("bumped_rows", 1), ("skipped_basics", 1),
                             ("merged", True), ("cards", True), ("cards", 99)):
            def changed(*args, **kwargs):
                after, summary = original_add(*args, **kwargs)
                return after, inventory.Summary(summary.text, {**summary.counts, field: wrong}, summary.changed, summary.extra)
            with self.subTest(field=field, value=wrong), mock.patch.object(ops_collection, "add", side_effect=changed), \
                    self.assertRaises(undo.UndoConflict):
                self.review()
            self.unchanged(snapshot, audit)

    def test_late_failure_after_an_intermediate_pure_add_leaves_source_and_stock_unchanged(self):
        plan = self.review()
        snapshot, audit = self.store.snapshot, copy.deepcopy(self.store.audit)
        original_add, calls = ops_collection.add, []
        def failing(*args, **kwargs):
            calls.append(True)
            if len(calls) == 4:  # fresh review's two adds, then failure on the second inverse add
                raise Invalid("Synthetic late pure add failure")
            return original_add(*args, **kwargs)
        with mock.patch.object(ops_collection, "add", side_effect=failing), self.assertRaises(Invalid):
            self.apply(plan)
        self.assertEqual(len(calls), 4)
        self.unchanged(snapshot, audit)

    def test_final_settling_cannot_rewrite_a_target_other_stock_or_another_namespace(self):
        other = {**fixture.CARD, "finish": "foil", "quantity": 19, "notes": "Keep unrelated printing"}
        self.store.snapshot = self.store.snapshot.with_collection("home", [other]).with_collection("user2", [fixture.CARD])
        snapshot, audit = self.store.snapshot, copy.deepcopy(self.store.audit)
        original_prepare = changes.prepare
        for mode in ("target", "unrelated", "space", "decks"):
            def changed(*args, **kwargs):
                after = original_prepare(*args, **kwargs)
                if mode == "space":
                    return after.with_collection("user2", [fixture.CARD | {"notes": "Unexpected change"}])
                if mode == "decks":
                    return after.replace(decks={})
                rows = [row.as_dict() for row in after.collection("home").rows]
                index = next(i for i, row in enumerate(rows) if (row["finish"] == "foil") == (mode == "unrelated"))
                rows[index]["notes"] += " silently rewritten"
                return after.with_collection("home", rows)
            # Give a nonempty deck mapping so removing it is a material outside-source mutation.
            deck = model.Deck("home", "casual", "untouched", "# Untouched\n")
            self.store.snapshot = snapshot.with_deck(deck)
            current = self.store.snapshot
            with self.subTest(mode=mode), mock.patch.object(changes, "prepare", side_effect=changed), \
                    self.assertRaises(undo.UndoConflict):
                self.review()
            self.unchanged(current, audit)

    def test_receipt_uses_actual_rows_by_key_in_audit_order_and_refuses_a_missing_row(self):
        self.source().reverse()
        plan = self.review()
        after, _ = self.apply(plan)
        expected = self.receipts(plan)
        self.assertEqual(undo.restored_rows(after, plan), expected)
        self.assertNotEqual([item["row"]["set"] for item in expected], [row.set for row in after.collection("home").rows])
        keep = [row.as_dict() for row in after.collection("home").rows if rules.ident(row.as_dict()) != rules.ident(plan["rows"][-1]["restore"])]
        with self.assertRaises(undo.UndoConflict):
            undo.restored_rows(after.with_collection("home", keep), plan)

    def test_an_unreadable_or_false_missing_collection_is_not_treated_as_empty(self):
        for issue in ("error", "strict_error", "csv_error", "false-missing"):
            sheet = model.Sheet("magic/collection.csv", tuple(rules.FIELDS), (), True, **({issue: "Private fixture detail"} if issue != "false-missing" else {}))
            if issue == "false-missing":
                sheet = model.Sheet(sheet.path, sheet.columns, (model.CardRow.make(fixture.CARD),), False)
            self.store.snapshot = self.store.snapshot.replace(collections={"home": sheet})
            with self.subTest(issue=issue), self.assertRaises(undo.UndoConflict) as caught:
                self.review()
            self.assertNotIn("Private fixture detail", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
