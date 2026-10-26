"""Bounded collection metadata Undo batches use complete global audit-shaped fixtures.

The fixture deliberately preserves the production single-reader LIMIT 2 and adds
a separate max-51-row reader. No database, card-index update or real data is used.
"""
import copy
import unittest
from unittest import mock

from decklab.lib import cards, inventory, pool
from decklab.lib.inventory import ops_collection, rules, undo
from decklab.lib.state import Invalid
from decklab.tests import test_activity_undo_api as fixture
from decklab.tests import test_inventory_undo_insert as insert_fixture


KEY_FIELDS = ("space_id", "set_code", "collector_number", "finish")


class BatchMetadataUndoTests(unittest.TestCase):
    def setUp(self):
        self.case = insert_fixture.InsertUndoTests()
        self.addCleanup(self.case.doCleanups)
        self.case.setUp()
        self.store = self.case.store
        # Instance-only adapters: the shared existing fixture is left unchanged.
        self.store.undo_audit = lambda change_id: copy.deepcopy(self.store.audit.get(change_id, [])[:2])
        self.store.undo_audit_batch = lambda change_id: copy.deepcopy(self.store.audit.get(change_id, [])[:51])
        self.store.undo_latest = lambda table, key: self.latest.get(tuple(key[field] for field in KEY_FIELDS))
        self.untouched = {**fixture.CARD, "collector_number": "900", "quantity": 7,
                          "condition": "LP", "language": "ja", "notes": "Unchanged unrelated stock"}
        self.seed()

    def seed(self, count=2):
        source, current = [], []
        self.latest = {}
        for index in range(count):
            row = {**fixture.CARD, "collector_number": str(1000 + index), "quantity": 2 + index % 5,
                   "condition": "NM", "language": "en", "notes": "Unchanged note " + str(index)}
            old = {**row, "condition": "" if index % 2 == 0 else "legacy condition",
                   "language": "" if index % 2 == 0 else "de"}
            def raw(value):
                return {"space_id": "home", **{"set_code" if key == "set" else key: item for key, item in value.items()}}
            before, after = raw(old), raw(row)
            key = {field: after[field] for field in KEY_FIELDS}
            row_id = fixture.ROW_ID + index
            source.append({"id": row_id, "table": undo.COLLECTION, "op": "UPDATE", "key": key,
                           "before": before, "after": after})
            self.latest[tuple(key[field] for field in KEY_FIELDS)] = row_id
            current.append(row)
        self.store.audit[fixture.CHANGE_ID] = source
        self.store.snapshot = self.store.snapshot.with_collection("home", [self.untouched, *current])
        return source

    def source(self):
        return self.store.audit[fixture.CHANGE_ID]

    def note_batch(self, notes, *, mixed=False):
        """Record exact former notes, optionally beside condition/language edits."""
        self.seed(len(notes))
        for record, note in zip(self.source(), notes):
            if not mixed:
                record["before"] = copy.deepcopy(record["after"])
            record["before"]["notes"] = note

    def review(self):
        return inventory.undo_review(fixture.CHANGE_ID, "home", self.store.snapshot)

    def apply(self, plan=None):
        plan = self.review() if plan is None else plan
        return inventory.Op("inventory.undo", {"change_id": fixture.CHANGE_ID, "space": "home",
                                               "expect": plan["expect"]}).run(self.store.snapshot)

    @staticmethod
    def receipts(plan):
        return [{"key": {field: item["restore"][field] for field in ("set", "collector_number", "finish")},
                 "row": item["restore"]} for item in plan["rows"]]

    def test_two_rows_review_full_changes_without_mutating_source_or_current_stock(self):
        snapshot, original = self.store.snapshot, copy.deepcopy(self.store.audit)
        plan = self.review()
        self.assertEqual(plan["action"], "batch_metadata")
        self.assertEqual(plan["row_count"], 2)
        self.assertEqual((plan["kind"], plan["space"]), ("collection", "home"))
        self.assertEqual(len(plan["rows"]), 2)
        self.assertEqual([item["row_change_id"] for item in plan["rows"]], [row["id"] for row in self.source()])
        for item in plan["rows"]:
            self.assertEqual({field["field"] for field in item["fields"]}, {"condition", "language"})
            self.assertEqual(item["current"]["notes"], item["restore"]["notes"])
            self.assertEqual(item["current"]["quantity"], item["restore"]["quantity"])
            self.assertEqual(item["key"]["space_id"], "home")
        self.assertRegex(plan["expect"], r"^[a-f0-9]{64}$")
        self.assertEqual(self.store.audit, original)
        self.assertEqual(self.store.snapshot, snapshot)

    def test_fifty_is_supported_and_the_fifty_first_row_refuses_without_disclosing_scope(self):
        self.seed(50)
        self.assertEqual(len(self.store.undo_audit(fixture.CHANGE_ID)), 2)
        self.assertEqual(self.review()["row_count"], 50)
        self.seed(51)
        self.source()[-1]["before"]["space_id"] = self.source()[-1]["after"]["space_id"] = "user2"
        with self.assertRaises(undo.UndoMissing) as caught:
            self.review()
        self.assertEqual(str(caught.exception), "That change is not available to undo.")

    def test_single_metadata_row_retains_the_existing_single_row_contract(self):
        self.seed(1)
        with mock.patch.object(self.store, "undo_audit_batch", side_effect=AssertionError("unneeded batch read")):
            plan = self.review()
        self.assertNotEqual(plan.get("action"), "batch_metadata")
        self.assertIsInstance(plan["current"], dict)
        self.assertIsInstance(plan["restore"], dict)

    def test_complete_reader_is_required_and_a_shorter_reply_cannot_authorize_a_subset(self):
        reader = self.store.undo_audit_batch
        for replacement in (None, lambda _: None, lambda _: copy.deepcopy(self.source()[:1])):
            self.store.undo_audit_batch = replacement
            with self.subTest(replacement=type(replacement).__name__), self.assertRaises(undo.UndoMissing):
                self.review()
        self.store.undo_audit_batch = reader

    def test_late_hidden_row_is_checked_before_bad_first_row_schema_or_labels(self):
        self.source()[0]["before"]["unsupported_schema"] = "Own row detail"
        self.source()[-1]["before"]["space_id"] = self.source()[-1]["after"]["space_id"] = "user2"
        self.source()[-1]["before"]["name"] = self.source()[-1]["after"]["name"] = "Hidden member card"
        with self.assertRaises(undo.UndoMissing) as caught:
            self.review()
        self.assertEqual(str(caught.exception), "That change is not available to undo.")

    def test_other_table_or_incomplete_global_row_cannot_be_ignored(self):
        for replacement in ({"table": "profile_email", "op": "UPDATE", "before": {"email": "hidden@example.com"},
                             "after": {"email": "other@example.com"}},
                            {"table": undo.COLLECTION, "op": "INSERT", "before": None,
                             "after": copy.deepcopy(self.source()[0]["after"])}):
            self.seed()
            self.source()[-1] = replacement
            with self.subTest(table=replacement["table"]), self.assertRaises(undo.UndoMissing):
                self.review()

    def test_duplicate_original_identity_or_audit_id_never_authorizes_a_batch(self):
        for duplicate in ("key", "id"):
            self.seed()
            if duplicate == "key":
                self.source()[1] = {**copy.deepcopy(self.source()[0]), "id": self.source()[1]["id"]}
            else:
                self.source()[1]["id"] = self.source()[0]["id"]
                key = self.source()[1]["key"]
                self.latest[tuple(key[field] for field in KEY_FIELDS)] = self.source()[0]["id"]
            with self.subTest(duplicate=duplicate), self.assertRaises((undo.UndoMissing, undo.UndoUnsupported, undo.UndoConflict)):
                self.review()

    def test_quantity_identity_names_and_noops_are_outside_this_metadata_slice(self):
        for field in ("quantity", "finish", "name", "noop"):
            self.seed()
            first = self.source()[0]
            if field == "noop":
                first["before"] = copy.deepcopy(first["after"])
            else:
                first["before"][field] = 1 if field == "quantity" else "Different historical fact"
            with self.subTest(field=field), self.assertRaises(undo.UndoUnsupported):
                self.review()

    def test_one_full_current_row_change_prevents_every_inverse(self):
        before, original = self.store.snapshot, copy.deepcopy(self.store.audit)
        rows = [row.as_dict() for row in before.collection("home").rows]
        rows[-1]["notes"] = "Changed after the selected audit"
        self.store.snapshot = before.with_collection("home", rows)
        current = self.store.snapshot
        with self.assertRaises(undo.UndoConflict):
            self.review()
        self.assertEqual(self.store.snapshot, current)
        self.assertEqual(self.store.audit, original)

    def test_one_later_audit_touch_refuses_even_when_current_values_returned_to_source(self):
        plan = self.review()
        key = self.source()[-1]["key"]
        self.latest[tuple(key[field] for field in KEY_FIELDS)] += 1
        with self.assertRaises(undo.UndoConflict):
            self.review()
        with self.assertRaises(undo.UndoConflict):
            self.apply(plan)

    def test_inventory_and_deck_revisions_both_bind_the_complete_batch(self):
        plan = self.review()
        for field in ("revision", "decks_revision"):
            before = self.store.snapshot
            self.store.snapshot = before.replace(**{field: "later"})
            with self.subTest(field=field), self.assertRaises(undo.UndoConflict):
                self.apply(plan)
            self.store.snapshot = before

    def test_apply_restores_blanks_and_legacy_values_exactly_in_one_ordinary_batch(self):
        plan = self.review()
        original, snapshot = copy.deepcopy(self.store.audit), self.store.snapshot
        after, summary = self.apply(plan)
        self.assertEqual(summary.counts["edited"], 2)
        self.assertEqual(summary.counts["removed"], 0)
        self.assertEqual(summary.counts["undo"], 1)
        self.assertEqual(summary.extra["undo_of"], fixture.CHANGE_ID)
        self.assertEqual(undo.restored_rows(after, plan), self.receipts(plan))
        untouched = next(row for row in after.collection("home").rows if row.collector_number == "900")
        self.assertEqual(untouched.as_dict(), snapshot.collection("home").rows[0].as_dict())
        self.assertEqual(self.store.snapshot, snapshot)
        self.assertEqual(self.store.audit, original)

    def test_notes_only_restores_empty_and_quoted_unicode_text_exactly(self):
        notes = ["", 'Stored separately; "gift", café — 日本語 <b>literal text</b>']
        self.note_batch(notes)
        plan = self.review()
        self.assertEqual([item["fields"] for item in plan["rows"]],
                         [[{"field": "notes", "before": "Unchanged note " + str(index), "after": note}]
                          for index, note in enumerate(notes)])
        with mock.patch.object(ops_collection, "apply_rows", wraps=ops_collection.apply_rows) as ordinary:
            after, summary = self.apply(plan)
        self.assertEqual(ordinary.call_count, 2)  # fresh review plus one inverse under apply
        self.assertEqual(summary.counts["edited"], 2)
        self.assertEqual(summary.counts["removed"], 0)
        self.assertEqual([item["row"]["notes"] for item in undo.restored_rows(after, plan)], notes)
        self.assertEqual(undo.restored_rows(after, plan), self.receipts(plan))

    def test_notes_and_other_metadata_can_change_in_different_combinations(self):
        self.note_batch(["Old first note", "Old second note", "Old third note"], mixed=True)
        self.source()[0]["before"]["condition"] = self.source()[0]["after"]["condition"]
        self.source()[0]["before"]["language"] = self.source()[0]["after"]["language"]
        self.source()[1]["before"]["language"] = self.source()[1]["after"]["language"]
        plan = self.review()
        self.assertEqual([[field["field"] for field in item["fields"]] for item in plan["rows"]],
                         [["notes"], ["condition", "notes"], ["condition", "language", "notes"]])
        after, _ = self.apply(plan)
        self.assertEqual(undo.restored_rows(after, plan), self.receipts(plan))

    def test_historical_text_is_not_trimmed_limited_or_interpreted_as_fresh_input(self):
        notes = [" \t ", '  Quoted "gift", café 日本語; repeated; prose  ',
                 "First\r\nSecond\rThird\nFourth\twith a tab", "Long historical note " + "é" * 600,
                 "=literal historical note", "+literal historical note", "-literal historical note", "@literal historical note"]
        for note in notes:
            self.note_batch([note, "Other unchanged historical meaning"])
            before, original = self.store.snapshot, copy.deepcopy(self.store.audit)
            with self.subTest(note=note):
                plan = self.review()
                after, _ = self.apply(plan)
                self.assertEqual([item["row"]["notes"] for item in undo.restored_rows(after, plan)],
                                 [note, "Other unchanged historical meaning"])
                self.assertEqual(undo.restored_rows(after, plan), self.receipts(plan))
            self.assertEqual(self.store.snapshot, before)
            self.assertEqual(self.store.audit, original)

    def test_nontext_historical_notes_refuse_the_whole_batch_without_changes(self):
        for note in (None, 1, True, [], {}):
            self.note_batch(["Valid first note", note])
            before, original = self.store.snapshot, copy.deepcopy(self.store.audit)
            with self.subTest(note=note), self.assertRaises(undo.UndoUnsupported):
                self.review()
            self.assertEqual(self.store.snapshot, before)
            self.assertEqual(self.store.audit, original)

    def test_unpersistable_note_text_refuses_before_ordinary_edits_or_receipt_hashing(self):
        for note in ("Embedded\0NUL", "Unpaired\ud800surrogate", "Unpaired\udfffsurrogate"):
            for side in ("before", "after"):
                self.note_batch(["Valid first note", "Valid second note"])
                self.source()[-1][side]["notes"] = note
                before, original = self.store.snapshot, copy.deepcopy(self.store.audit)
                with self.subTest(note=repr(note), side=side), \
                        mock.patch.object(ops_collection, "apply_rows", side_effect=AssertionError("Unpersistable edit")), \
                        self.assertRaises(undo.UndoUnsupported):
                    self.review()
                self.assertEqual(self.store.snapshot, before)
                self.assertEqual(self.store.audit, original)

    def test_one_candidate_note_rewrite_refuses_the_entire_batch(self):
        self.note_batch(["Former first note", "Former second note"])
        before, original = self.store.snapshot, copy.deepcopy(self.store.audit)
        original_apply = ops_collection.apply_rows
        def rewritten(*args, **kwargs):
            after, summary = original_apply(*args, **kwargs)
            rows = [row.as_dict() for row in after.collection("home").rows]
            rows[-1]["notes"] += " silently rewritten"
            return after.with_collection("home", rows), summary
        with mock.patch.object(ops_collection, "apply_rows", side_effect=rewritten), self.assertRaises(undo.UndoConflict):
            self.review()
        self.assertEqual(self.store.snapshot, before)
        self.assertEqual(self.store.audit, original)

    def test_receipt_follows_audit_plan_order_even_when_collection_sort_order_differs(self):
        self.store.audit[fixture.CHANGE_ID].reverse()
        for index, row in enumerate(self.source()):
            row["id"] = fixture.ROW_ID + index
            self.latest[tuple(row["key"][field] for field in KEY_FIELDS)] = row["id"]
        plan = self.review()
        after, _ = self.apply(plan)
        self.assertEqual(undo.restored_rows(after, plan), self.receipts(plan))
        self.assertNotEqual([item["row"]["collector_number"] for item in undo.restored_rows(after, plan)],
                            [row.collector_number for row in after.collection("home").rows if row.collector_number != "900"])

    def test_missing_actual_restored_row_cannot_produce_a_success_receipt(self):
        plan = self.review()
        after, _ = self.apply(plan)
        key = rules.ident(plan["rows"][-1]["restore"])
        rows = [row.as_dict() for row in after.collection("home").rows if rules.ident(row.as_dict()) != key]
        with self.assertRaises(undo.UndoConflict):
            undo.restored_rows(after.with_collection("home", rows), plan)

    def test_candidate_normalization_or_partial_edit_count_refuses_without_mutating_stock(self):
        original_apply = ops_collection.apply_rows
        before = self.store.snapshot
        for mode in ("metadata", "counts"):
            def changed(*args, **kwargs):
                after, summary = original_apply(*args, **kwargs)
                if mode == "metadata":
                    rows = [row.as_dict() for row in after.collection("home").rows]
                    rows[-1]["language"] = "Normalized instead of restored"
                    return after.with_collection("home", rows), summary
                return after, inventory.Summary(summary.text, {**summary.counts, "edited": 1}, summary.changed, summary.extra)
            with self.subTest(mode=mode), mock.patch.object(ops_collection, "apply_rows", side_effect=changed), \
                    self.assertRaises((undo.UndoUnsupported, undo.UndoConflict)):
                self.review()
            self.assertEqual(self.store.snapshot, before)

    def test_metadata_inverse_needs_no_card_index_or_physical_holder_lookup(self):
        with mock.patch.object(cards, "resolve", side_effect=AssertionError("card lookup")), \
                mock.patch.object(cards, "printing", side_effect=AssertionError("printing lookup")), \
                mock.patch.object(cards, "printing_card", side_effect=AssertionError("printing lookup")), \
                mock.patch.object(pool, "load_pool", side_effect=AssertionError("physical holder lookup")):
            plan = self.review()
            after, _ = self.apply(plan)
        self.assertEqual(undo.restored_rows(after, plan), self.receipts(plan))

    def test_failure_after_an_intermediate_pure_edit_leaves_current_stock_and_audit_unchanged(self):
        plan = self.review()
        before, original = self.store.snapshot, copy.deepcopy(self.store.audit)
        edit = ops_collection.edit
        calls = []
        def fail_second(*args, **kwargs):
            calls.append(True)
            if len(calls) == 2:
                raise Invalid("Synthetic second-row failure")
            return edit(*args, **kwargs)
        with mock.patch.object(ops_collection, "edit", side_effect=fail_second), self.assertRaises(Invalid):
            self.apply(plan)
        self.assertEqual(self.store.snapshot, before)
        self.assertEqual(self.store.audit, original)
