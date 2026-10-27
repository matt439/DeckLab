"""Strict removal of whole audited collection INSERT batches over isolated fixtures.

Every source is an audit-shaped test double. Tests never claim that the source
was an import, inspect real data or processes, or contact a database or network.
"""
import copy
import json
import unittest
from unittest import mock

from decklab.lib import inventory
from decklab.lib.inventory import changes, model, ops_collection, rules, undo
from decklab.lib.state import Invalid
from decklab.tests import test_activity_undo_api as fixture
from decklab.tests import test_inventory_undo_insert as insert_fixture


KEY_FIELDS = ("space_id", "set_code", "collector_number", "finish")
REASON = "Correct accidental restoration."
DEFAULT_ROWS = [copy.deepcopy(fixture.CARD),
                {**fixture.CARD, "set": "m19", "collector_number": "314", "quantity": 3,
                 "condition": "", "language": "", "notes": "Another recorded printing"}]


class BatchInsertUndoTests(unittest.TestCase):
    def setUp(self):
        self.case = insert_fixture.InsertUndoTests()
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
        rows = copy.deepcopy(rows)
        source, self.latest = [], {}
        for index, row in enumerate(rows):
            after = {"space_id": "home", **{"set_code" if key == "set" else key: value for key, value in row.items()}}
            key = {field: after[field] for field in KEY_FIELDS}
            row_id = fixture.ROW_ID + index
            source.append({"id": row_id, "table": undo.COLLECTION, "op": "INSERT", "key": key,
                           "before": None, "after": after})
            self.latest[tuple(key[field] for field in KEY_FIELDS)] = row_id
        self.store.audit[fixture.CHANGE_ID] = source
        self.store.snapshot = self.store.snapshot.with_collection("home", rows)
        return source

    def source(self):
        return self.store.audit[fixture.CHANGE_ID]

    def review(self):
        return inventory.undo_review(fixture.CHANGE_ID, "home", self.store.snapshot)

    def apply(self, plan=None, **extra):
        plan = self.review() if plan is None else plan
        return inventory.Op("inventory.undo", {"change_id": fixture.CHANGE_ID, "space": "home",
            "expect": plan["expect"], "reason": REASON, **extra}).run(self.store.snapshot)

    @staticmethod
    def keys(plan):
        return [{field: item["current"][field] for field in ("set", "collector_number", "finish")}
                for item in plan["rows"]]

    @staticmethod
    def receipts(plan):
        return BatchInsertUndoTests.keys(plan)

    def extra_stock(self):
        rows = [row.as_dict() for row in self.store.snapshot.collection("home").rows]
        extra = {**fixture.CARD, "collector_number": "900", "quantity": 100, "notes": "Untouched surplus printing"}
        self.store.snapshot = self.store.snapshot.with_collection("home", [extra, *rows])
        return extra

    def unchanged(self, snapshot, audit):
        self.assertEqual(self.store.snapshot, snapshot)
        self.assertEqual(self.store.audit, audit)

    def test_whole_batch_review_and_last_rows_removal_have_exact_scope_and_reason(self):
        snapshot, audit = self.store.snapshot, copy.deepcopy(self.store.audit)
        plan = self.review()
        self.assertEqual((plan["action"], plan["kind"], plan["space"], plan["row_count"]),
                         ("batch_remove", "collection", "home", 2))
        self.assertIs(plan["reason_required"], True)
        self.assertNotIn("fields", plan)
        self.assertEqual(self.keys(plan), [{"set": "fdn", "collector_number": "227", "finish": "nonfoil"},
                                          {"set": "m19", "collector_number": "314", "finish": "nonfoil"}])
        for item, source in zip(plan["rows"], self.source()):
            self.assertIsNone(item["restore"])
            self.assertNotIn("fields", item)
            self.assertEqual((item["key"], item["row_change_id"]), (source["key"], source["id"]))
        after, summary = self.apply(plan)
        self.assertEqual(after.collection("home").rows, ())
        self.assertNotIn("home", after.collections)
        self.assertEqual({key: summary.counts[key] for key in ("edited", "removed", "undo")},
                         {"edited": 0, "removed": 2, "undo": 1})
        self.assertEqual((summary.extra["action"], summary.extra["row_count"], summary.extra["undo_reason"]),
                         ("batch_remove", 2, REASON))
        self.assertEqual(summary.extra["row_change_ids"], [item["id"] for item in self.source()])
        self.unchanged(snapshot, audit)

    def test_survivor_facts_other_spaces_and_noncollection_sources_are_unchanged(self):
        extra = self.extra_stock()
        self.store.snapshot = self.store.snapshot.with_collection("user2", [fixture.CARD | {"notes": "Synthetic private stock"}])
        before = self.store.snapshot
        plan = self.review()
        after, _ = self.apply(plan)
        survivor = next(row.as_dict() for row in before.collection("home").rows if rules.ident(row.as_dict()) == rules.ident(extra))
        self.assertEqual([row.as_dict() for row in after.collection("home").rows],
                         [survivor])
        self.assertEqual(rules.ident(after.collection("home").rows[0].as_dict()), rules.ident(extra))
        self.assertEqual(after.collection("user2"), before.collection("user2"))
        self.assertEqual(set(after.collections), set(before.collections))
        self.assertEqual(after, before.replace(collections=after.collections))

    def test_complete_fifty_row_source_is_supported_but_fifty_first_never_truncates(self):
        self.seed(50)
        self.assertEqual(len(self.store.undo_audit(fixture.CHANGE_ID)), 2)
        plan = self.review()
        self.assertEqual(plan["row_count"], 50)
        after, summary = self.apply(plan)
        self.assertEqual(after.collection("home").rows, ())
        self.assertEqual(summary.counts["removed"], 50)
        self.seed(51)
        self.source()[-1]["after"]["space_id"] = "user2"
        with mock.patch.object(undo, "_insert_removal", side_effect=AssertionError("capped source used holder reads")), \
                self.assertRaises(undo.UndoMissing) as caught:
            self.review()
        self.assertEqual(str(caught.exception), "That change is not available to undo.")

    def test_full_batch_reader_is_required_and_one_insert_keeps_its_single_row_contract(self):
        reader = self.store.undo_audit_batch
        for replacement in (None, lambda _: None, lambda _: [], lambda _: copy.deepcopy(self.source()[:1])):
            self.store.undo_audit_batch = replacement
            with self.subTest(reader=type(replacement).__name__), self.assertRaises(undo.UndoMissing):
                self.review()
        self.store.undo_audit_batch = reader
        self.seed(1)
        with mock.patch.object(self.store, "undo_audit_batch", side_effect=AssertionError("single used batch reader")):
            self.assertEqual(self.review()["action"], "remove")

    def test_late_hidden_row_is_checked_before_bad_own_schema_labels_or_physical_reads(self):
        self.source()[0]["after"]["unknown_schema"] = "Own unsupported fact"
        self.source()[-1]["after"]["space_id"] = "user2"
        self.source()[-1]["after"]["name"] = "Hidden synthetic card"
        with mock.patch.object(undo, "_label", side_effect=AssertionError("hidden label")), \
                mock.patch.object(undo, "_insert_removal", side_effect=AssertionError("hidden holder read")), \
                self.assertRaises(undo.UndoMissing) as caught:
            self.review()
        self.assertEqual(str(caught.exception), "That change is not available to undo.")

    def test_mixed_operations_other_tables_and_raw_imports_never_authorize_partial_removal(self):
        for mode in ("update", "delete", "other-table", "raw-import", "raw-content", "missing-after", "not-object"):
            self.seed()
            record = self.source()[-1]
            if mode == "update":
                record["op"], record["before"] = "UPDATE", copy.deepcopy(record["after"])
            elif mode == "delete":
                record["op"], record["before"], record["after"] = "DELETE", record["after"], None
            elif mode in ("other-table", "raw-import", "raw-content"):
                record["table"] = {"other-table": "profile_email", "raw-import": "collection_import",
                                   "raw-content": "collection_import_content"}[mode]
            elif mode == "missing-after":
                record["after"] = None
            else:
                self.source()[-1] = None
            with self.subTest(mode=mode), self.assertRaises(undo.UndoMissing):
                self.review()

    def test_duplicate_original_keys_or_audit_ids_refuse_before_labels_or_removal(self):
        for mode in ("key", "id"):
            self.seed()
            if mode == "key":
                self.source()[1] = {**copy.deepcopy(self.source()[0]), "id": self.source()[1]["id"]}
            else:
                self.source()[1]["id"] = self.source()[0]["id"]
            with self.subTest(mode=mode), mock.patch.object(undo, "_label", side_effect=AssertionError("duplicate label")), \
                    mock.patch.object(ops_collection, "apply_rows", side_effect=AssertionError("duplicate removal")), \
                    self.assertRaises(undo.UndoUnsupported):
                self.review()

    def test_source_requires_null_before_full_exact_schema_key_id_and_positive_quantity(self):
        for mode in ("non-null-before", "missing-column", "extra-column", "bad-key", "bad-id", "quantity", "notes"):
            self.seed()
            record = self.source()[-1]
            if mode == "non-null-before":
                record["before"] = copy.deepcopy(record["after"])
            elif mode == "missing-column":
                del record["after"]["notes"]
            elif mode == "extra-column":
                record["after"]["future"] = "Unsupported"
            elif mode == "bad-key":
                record["key"]["finish"] = "foil"
            elif mode == "bad-id":
                record["id"] = True
            elif mode == "quantity":
                record["after"]["quantity"] = True
            else:
                record["after"]["notes"] = None
            with self.subTest(mode=mode), self.assertRaises((undo.UndoMissing, undo.UndoUnsupported)):
                self.review()

    def test_every_current_full_row_and_readable_collection_must_still_match(self):
        for mode in ("notes", "quantity", "missing", "duplicate", "error", "strict_error", "csv_error"):
            self.seed()
            if mode in ("error", "strict_error", "csv_error"):
                sheet = self.store.snapshot.collection("home")
                broken = model.Sheet(sheet.path, sheet.columns, sheet.rows, True, **{mode: "Private fixture detail"})
                self.store.snapshot = self.store.snapshot.replace(collections={"home": broken})
            else:
                rows = [row.as_dict() for row in self.store.snapshot.collection("home").rows]
                if mode == "missing":
                    rows.pop()
                elif mode == "duplicate":
                    rows.append(dict(rows[-1]))
                else:
                    rows[-1][mode] = "Later note" if mode == "notes" else "4"
                self.store.snapshot = self.store.snapshot.with_collection("home", rows)
            with self.subTest(mode=mode), self.assertRaises(undo.UndoConflict) as caught:
                self.review()
            self.assertNotIn("Private fixture detail", str(caught.exception))

    def test_latest_key_proof_blocks_aba_even_when_all_values_returned_and_blocks_repeated_removal(self):
        plan = self.review()
        key = self.source()[-1]["key"]
        self.latest[tuple(key[field] for field in KEY_FIELDS)] += 2
        with self.assertRaises(undo.UndoConflict):
            self.apply(plan)
        self.seed()
        plan = self.review()
        self.store.snapshot = self.apply(plan)[0]
        with self.assertRaises(undo.UndoConflict):
            self.apply(plan)

    def test_inventory_and_deck_revisions_bind_the_entire_batch(self):
        plan = self.review()
        for field in ("revision", "decks_revision"):
            snapshot = self.store.snapshot
            self.store.snapshot = snapshot.replace(**{field: "later"})
            with self.subTest(field=field), self.assertRaises(undo.UndoConflict):
                self.apply(plan)
            self.store.snapshot = snapshot

    def test_whole_batch_needs_one_normalized_reason_of_at_most_two_hundred_characters(self):
        plan = self.review()
        snapshot, audit = self.store.snapshot, copy.deepcopy(self.store.audit)
        for reason in (None, "", " \n\t ", 1, [], {}, "x" * 201, "NUL\0", "DEL\x7f"):
            with self.subTest(reason=repr(reason)), self.assertRaises(Invalid):
                self.apply(plan, reason=reason, confirm_owned=True)
        with self.assertRaises(Invalid):
            inventory.Op("inventory.undo", {"change_id": fixture.CHANGE_ID, "space": "home", "expect": plan["expect"]}).run(snapshot)
        with self.assertRaises(TypeError):
            self.apply(plan, allow_in_use=True)
        after, summary = self.apply(plan, reason="  " + REASON + "  ")
        self.assertEqual(summary.extra["undo_reason"], REASON)
        self.assertEqual(after.collection("home").rows, ())
        self.assertEqual(self.apply(plan, reason="x" * 200)[1].extra["undo_reason"], "x" * 200)
        self.unchanged(snapshot, audit)

    def test_every_basic_printing_is_refused_even_foil_or_recorded_full_art(self):
        for name in ("Forest", "Snow-Covered Island", "Wastes"):
            for finish, notes in (("nonfoil", ""), ("foil", "Full-art fixture")):
                self.seed(rows=[DEFAULT_ROWS[0], DEFAULT_ROWS[1] | {"name": name, "finish": finish, "notes": notes}])
                with self.subTest(name=name, finish=finish), self.assertRaises((undo.UndoUnsupported, undo.UndoConflict)):
                    self.review()

    def test_any_built_use_of_the_canonical_name_refuses_other_printings_despite_surplus(self):
        self.extra_stock()
        self.case.built("1 Llanowar Elves\n59 Forest")
        with self.assertRaises(undo.UndoConflict):
            self.review()

    def test_named_anonymous_duplicate_wrong_version_and_frozen_holder_facts_refuse(self):
        self.extra_stock()
        for mode in ("named", "anonymous", "duplicate", "wrong-version", "frozen"):
            self.store.snapshot = self.store.snapshot.replace(decks={})
            installed = self.case.standins(using=None if mode == "anonymous" else "Llanowar Elves",
                                            version="owned" if mode == "wrong-version" else "target")
            headers = "- **Stand-ins:** " + json.dumps(installed) + "\n"
            if mode == "duplicate":
                headers = '- **Stand-ins:** {"target": [], "owned": [], "built": null}\n' + headers
            elif mode == "frozen":
                headers = '- **Assembled:** ' + json.dumps({"version": "target", "sections": {"Deck": ["1 Llanowar Elves", "59 Forest"]}}) + "\n"
            self.case.built("1 Opt\n59 Forest", headers)
            with self.subTest(mode=mode), self.assertRaises(undo.UndoConflict):
                self.review()

    def test_intact_product_holds_unknown_storage_and_ambiguous_deck_status_never_mean_free(self):
        self.extra_stock()
        snapshot = self.store.snapshot
        product = next(item for item in self.case.products if item.file == "fdn-beginner-box.csv")
        status = model.StatusRow.make({"file": product.file, "status": "owned", "intact": "yes"})
        self.store.snapshot = snapshot.replace(products=(product,),
            status=model.Sheet("magic/products/status.csv", tuple(rules.STATUS_FIELDS), (status,), True))
        with self.assertRaises(undo.UndoConflict):
            self.review()
        self.store.snapshot = snapshot.replace(products=(product,))
        with self.assertRaises(undo.UndoConflict):
            self.review()
        self.store.snapshot = snapshot
        self.case.built(headers="- **Status:** idea\n")
        with self.assertRaises(undo.UndoConflict):
            self.review()

    def test_every_strict_target_check_receives_the_one_complete_removal_candidate(self):
        extra = self.extra_stock()
        before = self.store.snapshot
        original, calls = undo._insert_removal, []
        def checked(snapshot, after, wanted, space, label, source):
            calls.append((snapshot, after, wanted))
            self.assertEqual(snapshot, before)
            self.assertEqual([rules.ident(row.as_dict()) for row in after.collection("home").rows], [rules.ident(extra)])
            return original(snapshot, after, wanted, space, label, source)
        with mock.patch.object(undo, "_insert_removal", side_effect=checked):
            plan = self.review()
            after, _ = self.apply(plan)
        self.assertGreaterEqual(len(calls), 2)
        self.assertEqual({rules.ident(wanted) for _, _, wanted in calls}, {tuple(key[field] for field in ("set", "collector_number", "finish")) for key in self.keys(plan)})
        self.assertEqual([rules.ident(row.as_dict()) for row in after.collection("home").rows], [rules.ident(extra)])

    def test_ordinary_removal_counts_must_cover_every_source_row_and_no_edits(self):
        original = ops_collection.apply_rows
        before, audit = self.store.snapshot, copy.deepcopy(self.store.audit)
        for field, wrong in (("removed", 1), ("removed", True), ("edited", 1)):
            def changed(*args, **kwargs):
                after, summary = original(*args, **kwargs)
                return after, inventory.Summary(summary.text, summary.counts | {field: wrong}, summary.changed, summary.extra)
            with self.subTest(field=field, value=wrong), mock.patch.object(ops_collection, "apply_rows", side_effect=changed), \
                    self.assertRaises(undo.UndoConflict):
                self.review()
            self.unchanged(before, audit)

    def test_late_pure_failure_after_first_removal_leaves_original_stock_and_audit_unchanged(self):
        plan = self.review()
        before, audit = self.store.snapshot, copy.deepcopy(self.store.audit)
        original, calls = ops_collection.remove, []
        def failed(*args, **kwargs):
            calls.append(True)
            if len(calls) == 4:  # fresh review's two removals, then second apply removal
                raise Invalid("Synthetic late pure removal failure")
            return original(*args, **kwargs)
        with mock.patch.object(ops_collection, "remove", side_effect=failed), self.assertRaises(Invalid):
            self.apply(plan)
        self.assertEqual(len(calls), 4)
        self.unchanged(before, audit)

    def test_final_settlement_cannot_leave_a_target_rewrite_survivors_or_change_other_namespaces(self):
        self.extra_stock()
        self.store.snapshot = self.store.snapshot.with_collection("user2", [fixture.CARD])
        text = "# Untouched\n\n- **Format:** Casual 60-card, 1v1\n- **Status:** idea\n\n## Decklist\n\n```\nDeck\n1 Opt\n59 Forest\n```\n"
        self.store.snapshot = self.store.snapshot.with_deck(model.Deck("home", "casual", "untouched", text))
        before, audit = self.store.snapshot, copy.deepcopy(self.store.audit)
        original = changes.prepare
        for mode in ("target", "survivor", "space", "decks"):
            def changed(*args, **kwargs):
                after = original(*args, **kwargs)
                if mode == "decks":
                    return after.replace(decks={})
                if mode == "space":
                    return after.with_collection("user2", [fixture.CARD | {"notes": "Unexpected mutation"}])
                rows = [row.as_dict() for row in after.collection("home").rows]
                if mode == "target":
                    rows.append(DEFAULT_ROWS[0])
                else:
                    rows[0]["notes"] += " silently rewritten"
                return after.with_collection("home", rows)
            with self.subTest(mode=mode), mock.patch.object(changes, "prepare", side_effect=changed) as settled, \
                    self.assertRaises(undo.UndoConflict):
                self.review()
            settled.assert_called()
            self.unchanged(before, audit)


if __name__ == "__main__":
    unittest.main()
