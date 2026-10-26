"""Batch metadata Undo API proofs over complete isolated audit fixtures."""
import copy
import json
import unittest
from unittest import mock

from decklab.lib import inventory
from decklab.lib.api import activity_undo, guard
from decklab.lib.api.common import ApiError
from decklab.lib.inventory import files
from decklab.tests import test_activity_undo_api as original, test_inventory_undo_batch as fixture


class BatchUndoApiTests(unittest.TestCase):
    def setUp(self):
        self.case = fixture.BatchMetadataUndoTests()
        self.addCleanup(self.case.doCleanups)
        self.case.setUp()
        self.backend = self.case.store

    def view(self):
        return activity_undo.undo_view(id=str(original.CHANGE_ID))

    def apply(self, *, expect=None, **extra):
        expect = self.view()["expect"] if expect is None else expect
        return activity_undo.apply_undo(json.dumps({"profile": "matt", "id": original.CHANGE_ID,
                                                   "expect": expect, **extra}).encode())

    def refused(self, code, call, **kwargs):
        with self.assertRaises(ApiError) as caught:
            call(**kwargs)
        self.assertEqual(caught.exception.status, code, caught.exception.message)
        return caught.exception

    def test_complete_preview_lists_every_full_row_and_only_metadata_differences(self):
        result = self.view()
        self.assertEqual(set(result), {"available", "id", "expect", "kind", "space", "label", "action", "row_count", "rows"})
        self.assertEqual((result["action"], result["row_count"], result["kind"]), ("batch_metadata", 2, "collection"))
        for row in result["rows"]:
            self.assertEqual(set(row), {"key", "label", "current", "restored", "fields"})
            self.assertEqual(row["key"], {key: row["current"][key] for key in ("set", "collector_number", "finish")})
            self.assertTrue({field["field"] for field in row["fields"]} <= {"condition", "language", "notes"})
            self.assertEqual(row["current"]["quantity"], row["restored"]["quantity"])
            self.assertEqual(row["current"]["notes"], row["restored"]["notes"])
        self.assertEqual(self.backend.writes, [])

    def test_one_apply_receipt_contains_actual_rows_by_key_and_preserves_original_audit(self):
        preview = self.view()
        history = copy.deepcopy(self.backend.audit)
        untouched = next(row.as_dict() for row in self.backend.snapshot.collection("home").rows if row.collector_number == "900")
        answer = self.apply(expect=preview["expect"])
        self.assertEqual((answer["action"], answer["row_count"]), ("batch_metadata", 2))
        self.assertEqual(answer["restored_rows"], [{"key": item["key"], "row": item["restored"]} for item in preview["rows"]])
        self.assertEqual(answer["sha256"], files.rendered_sha256(self.backend.snapshot.collection("home")))
        self.assertEqual(answer["revision"], self.backend.snapshot.revision)
        self.assertEqual(self.backend.writes[0][0].params, {"change_id": original.CHANGE_ID, "space": "home", "expect": preview["expect"]})
        self.assertEqual(self.backend.audit, history)
        self.assertEqual(next(row.as_dict() for row in self.backend.snapshot.collection("home").rows if row.collector_number == "900"), untouched)
        self.assertEqual(len(self.backend.writes), 1)

    def test_notes_are_explicit_plain_text_fields_and_actual_keyed_receipts(self):
        notes = ["", '<script>throw "literal only"</script> & café']
        self.case.note_batch(notes, mixed=True)
        preview = self.view()
        for index, item in enumerate(preview["rows"]):
            self.assertEqual([field["field"] for field in item["fields"]], ["condition", "language", "notes"])
            self.assertEqual(item["fields"][-1], {"field": "notes", "before": "Unchanged note " + str(index),
                                                "after": notes[index]})
        answer = self.apply(expect=preview["expect"])
        self.assertEqual(answer["restored_rows"], [{"key": item["key"], "row": item["restored"]} for item in preview["rows"]])
        self.assertEqual([item["row"]["notes"] for item in answer["restored_rows"]], notes)
        self.assertEqual(json.loads(json.dumps(answer))["restored_rows"], answer["restored_rows"])
        self.assertEqual(len(self.backend.writes), 1)

    def test_invalid_historical_notes_are_unavailable_before_any_write(self):
        for note in (None, 1, True, [], {}, "Embedded\0NUL", "Unpaired\ud800surrogate"):
            self.case.note_batch(["Valid old note", note])
            with self.subTest(note=note):
                self.assertEqual(self.view(), {"available": False, "id": original.CHANGE_ID, "reason": activity_undo.UNSUPPORTED})
                self.refused(400, self.apply, expect="0" * 64)
        self.assertEqual(self.backend.writes, [])

    def test_historical_whitespace_and_multiline_notes_survive_json_and_receipt(self):
        notes = [" \tOriginal\r\nsecond line\nlast line  ", "=literal note " + "é" * 600]
        self.case.note_batch(notes)
        preview = json.loads(json.dumps(self.view()))
        self.assertEqual([item["fields"][0]["after"] for item in preview["rows"]], notes)
        answer = self.apply(expect=preview["expect"])
        self.assertEqual([item["row"]["notes"] for item in answer["restored_rows"]], notes)
        self.assertEqual(answer["restored_rows"], [{"key": item["key"], "row": item["restored"]} for item in preview["rows"]])

    def test_beyond_limit_and_mixed_source_hide_all_rows_before_bad_expect(self):
        self.case.seed(51)
        errors = [self.refused(404, self.apply, expect="bad")]
        self.case.seed(2)
        self.case.source()[0]["before"]["unknown_schema"] = "Own unsupported detail"
        self.case.source()[-1]["before"]["space_id"] = self.case.source()[-1]["after"]["space_id"] = "user2"
        errors.append(self.refused(404, self.apply, expect="bad"))
        self.assertEqual([error.message for error in errors], [activity_undo.NO_CHANGE] * 2)
        self.assertEqual(self.backend.writes, [])

    def test_quantity_and_other_row_facts_are_not_batch_metadata(self):
        for field, old in (("quantity", 1), ("name", "Other card")):
            self.case.seed()
            self.case.source()[0]["before"][field] = old
            with self.subTest(field=field):
                self.assertEqual(self.view(), {"available": False, "id": original.CHANGE_ID, "reason": activity_undo.UNSUPPORTED})
                self.refused(400, self.apply, expect="0" * 64)
        self.assertEqual(self.backend.writes, [])

    def test_no_row_selection_reason_or_physical_confirmation_is_accepted(self):
        preview = self.view()
        for extra in ({"rows": []}, {"keys": []}, {"reason": "Not a removal"}, {"confirm_owned": True}, {"row_count": 1}):
            with self.subTest(extra=extra):
                self.refused(400, self.apply, expect=preview["expect"], **extra)
        self.assertEqual(self.backend.writes, [])

    def test_bad_stale_and_repeated_receipts_never_apply_a_subset(self):
        self.refused(400, self.apply, expect="bad")
        self.refused(409, self.apply, expect="0" * 64)
        preview = self.view()
        self.apply(expect=preview["expect"])
        self.refused(409, self.apply, expect=preview["expect"])
        self.assertEqual(len(self.backend.writes), 1)

    def test_candidate_requires_all_global_rows_to_be_present_and_owned(self):
        rows = copy.deepcopy(self.case.source())
        change, shown = {"id": original.CHANGE_ID, "rows": rows, "total": len(rows)}, {"id": original.CHANGE_ID}
        self.assertEqual(activity_undo.review_hint(change, shown, guard.viewer()), {"review": True})
        for altered in ({**change, "total": 3}, {**change, "more": 1}, {**change, "groups": [{}]}):
            self.assertIsNone(activity_undo.review_hint(altered, shown, guard.viewer()))
        rows[-1]["after"]["space_id"] = "user2"
        self.assertIsNone(activity_undo.review_hint(change, shown, guard.viewer()))

    def test_wrong_scope_counts_source_ids_or_actual_rows_are_unconfirmed(self):
        preview = self.view()
        after, summary = self.case.apply()
        wrong = after.with_collection("home", [row.as_dict() for row in after.collection("home").rows if row.collector_number != "1000"])
        results = [(wrong, summary),
                   (after, inventory.Summary(summary.text, {**summary.counts, "edited": 1}, summary.changed, summary.extra)),
                   (after, inventory.Summary(summary.text, summary.counts, summary.changed,
                                             {**summary.extra, "row_change_ids": list(reversed(summary.extra["row_change_ids"]))}))]
        for result in results:
            with self.subTest(result=result), mock.patch.object(activity_undo.saving, "apply_op", return_value=result):
                self.refused(503, self.apply, expect=preview["expect"])

    def test_corrupt_backend_preview_rows_do_not_reach_the_page(self):
        plan = self.case.review()
        for mode in ("count", "duplicate", "key", "quantity"):
            corrupt = copy.deepcopy(plan)
            if mode == "count":
                corrupt["row_count"] = True
            elif mode == "duplicate":
                corrupt["rows"][-1] = copy.deepcopy(corrupt["rows"][0])
            elif mode == "key":
                corrupt["rows"][0]["key"]["finish"] = "foil"
            else:
                corrupt["rows"][0]["restore"]["quantity"] += 1
            with self.subTest(mode=mode), mock.patch.object(activity_undo.inventory, "undo_review", return_value=corrupt):
                self.refused(503, self.view)
