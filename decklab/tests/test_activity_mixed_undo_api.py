"""The whole-change Undo API over the isolated recording fixture of test_inventory_undo_mixed.

No PostgreSQL, household data or network is used.
"""
import copy
import json
import unittest

from decklab.lib import access
from decklab.lib.api import activity_mixed_undo, activity_undo
from decklab.lib.api.common import ApiError
from decklab.lib.inventory import undo_mixed
from decklab.tests import test_inventory_undo_mixed as mixed

REASON = mixed.REASON


class MixedUndoApiTests(mixed.ReceiptCase):
    """Reuses the receipt fixture's order; imports need no setup of their own."""

    def view(self, change_id):
        return activity_mixed_undo.mixed_undo_view(id=str(change_id))

    def post(self, change_id, expect=None, reason=REASON, profile="matt", **extra):
        if expect is None:
            expect = self.view(change_id)["expect"]
        body = {"profile": profile, "id": change_id, "expect": expect, "reason": reason, **extra}
        return activity_mixed_undo.apply_mixed_undo(json.dumps(body).encode())

    def refused(self, code, call, *args, **kwargs):
        with self.assertRaises(ApiError) as caught:
            call(*args, **kwargs)
        self.assertEqual(caught.exception.status, code, caught.exception.message)
        return caught.exception

    def merge(self, space="home"):
        rows = [mixed.NEW, mixed.BUMP]
        text = mixed.rules.collection_csv_bytes(rows).decode("utf-8")
        return self.write(mixed.inventory.Op("collection.import", {"space": space, "sources": [["upload.csv", rows]],
                                                                  "uploads": [["upload", text]]}))

    def test_import_preview_shows_public_rows_only(self):
        change = self.merge()
        answer = self.view(change)
        self.assertEqual(set(answer), {"available", "id", "expect", "kind", "space", "action", "label", "reason_required",
                                       "cards", "collection", "tokens", "components", "products", "uploads"})
        self.assertEqual((answer["kind"], answer["action"], answer["cards"]), ("mixed", "import_undo", 5))
        self.assertEqual(answer["uploads"], ["upload.csv"])
        self.assertEqual(set(answer["collection"]["removed"][0]), set(mixed.rules.FIELDS))
        self.assertEqual(self.store.writes[-1][2], "fixture change")

    def test_import_apply_saves_one_change_and_confirms_it(self):
        change = self.merge()
        preview = self.view(change)
        answer = self.post(change, preview["expect"])
        self.assertEqual((answer["saved"], answer["source_id"], answer["action"], answer["removed_rows"],
                          answer["restored_rows"]), (True, change, "import_undo", 1, 1))
        op, actor, message, summary, reason = self.store.writes[-1]
        self.assertEqual((op.kind, actor.id, message, reason), ("inventory.undo_mixed", "matt",
                                                                 f"Undo activity change {change}", REASON))
        self.assertEqual(answer["revision"], self.store.snapshot.revision)

    def test_receipt_apply_puts_the_order_back(self):
        change = self.receive()
        answer = self.post(change)
        self.assertEqual((answer["action"], answer["components"], answer["products"]), ("receipt_undo", 3, 1))
        self.assertTrue(all(c.status == "pending" for c in self.store.snapshot.order(mixed.ORDER).components))

    def test_reason_and_receipt_are_checked_before_writing(self):
        change = self.merge()
        expect = self.view(change)["expect"]
        for reason in ("", "  ", None, 3, "x" * 201):
            with self.subTest(reason=reason):
                self.refused(400, self.post, change, expect, reason=reason)
        self.refused(400, self.post, change, "nope")
        self.refused(409, self.post, change, "0" * 64)
        self.refused(400, self.post, change, expect, confirm_owned=True)
        self.assertEqual(self.store.writes[-1][2], "fixture change")

    def test_a_later_change_answers_409_naming_the_row(self):
        change = self.merge()
        self.merge()
        error = self.refused(409, self.view, change)
        self.assertIn("Llanowar Elves", error.message)

    def test_unsupported_changes_explain_themselves_without_writing(self):
        change = self.receive([{"id": "cards", "verified": True, "take": [{"row": 1}]}])
        answer = self.view(change)
        self.assertEqual((answer["available"], answer["id"]), (False, change))
        self.assertIn("whole order parts", answer["reason"])

    def test_receipts_are_home_admins_only(self):
        change = self.receive()
        with access.using({"profile": "user1", "email": "user1@example.com", "remote": True}):
            self.refused(403, self.view, change)
        with access.using({"profile": "user2", "email": "user2@example.com", "remote": True}):
            self.refused(404, self.view, change)

    def test_user1_may_undo_a_home_import(self):
        change = self.merge()
        with access.using({"profile": "user1", "email": "user1@example.com", "remote": True}):
            answer = self.post(change, profile="user1")
        self.assertTrue(answer["saved"])

    def test_a_member_cannot_see_or_undo_another_spaces_import(self):
        self.store.snapshot = self.store.snapshot.with_collection("user2", [mixed.CARD])
        change = self.merge("user2")
        self.refused(404, self.view, change)
        with access.using({"profile": "user2", "email": "user2@example.com", "remote": True}):
            self.assertTrue(self.post(change, profile="user2")["saved"])

    def test_hint_offers_review_for_import_and_receipt_shapes_only(self):
        profile = {"id": "matt", "name": "Matt", "role": "admin", "space": "home"}
        change = self.merge()
        rows = copy.deepcopy(self.store.audit[change])
        listed = {"id": change, "rows": rows, "total": len(rows)}
        self.assertEqual(activity_undo.review_hint(listed, {"id": change}, profile), {"review": True, "kind": "mixed"})
        capped = {"id": change, "rows": rows[:1], "total": len(rows), "more": 1, "past": {undo_mixed.RAW_IMPORT: {}}}
        self.assertEqual(activity_mixed_undo.hint(capped, {"id": change}, profile), {"review": True, "kind": "mixed"})
        receipt = self.receive()
        rows = copy.deepcopy(self.store.audit[receipt])
        self.assertEqual(activity_mixed_undo.hint({"id": receipt, "rows": rows, "total": len(rows)}, {"id": receipt},
                                                  profile), {"review": True, "kind": "mixed"})
        user1 = {"id": "user1", "name": "User1", "role": "member", "space": "home"}
        with access.using({"profile": "user1", "email": "user1@example.com", "remote": True}):
            self.assertIsNone(activity_mixed_undo.hint({"id": receipt, "rows": rows, "total": len(rows)},
                                                       {"id": receipt}, user1))
        other = rows + [{"id": 1, "table": "watchlist_item", "op": "UPDATE", "key": {"id": 1}, "before": {}, "after": {}}]
        self.assertIsNone(activity_mixed_undo.hint({"id": receipt, "rows": other, "total": len(other)}, {"id": receipt}, profile))
        self.assertIsNone(activity_mixed_undo.hint({"id": receipt, "rows": rows, "total": len(rows), "groups": [{}]},
                                                   {"id": receipt}, profile))


if __name__ == "__main__":
    unittest.main()
