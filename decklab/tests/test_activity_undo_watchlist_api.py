"""Activity restores 1-50 purchase-queue rows' updated values: home's order editors only, exact packets and receipts."""
import copy
import json
import unittest
from unittest import mock

from decklab.lib import access
from decklab.lib.api import activity_undo as api, activity_watchlist_undo as queue_api, guard, saving
from decklab.lib.api.common import ApiError
from decklab.lib.inventory import files, undo_watchlist as queue
from decklab.tests import test_activity_undo_api as fixture
from decklab.tests.test_inventory_undo_watchlist import WatchlistUndoFixture, pairs

PACKET = {"action", "available", "expect", "id", "kind", "label", "row_count", "rows", "space"}
RECEIPT = {"saved", "source_id", "expect", "kind", "space", "action", "row_count", "restored_rows", "sha256", "revision", "summary"}
USER1 = {"profile": "user1", "email": "user1@example.com", "remote": True}
USER2 = {"profile": "user2", "email": "user2@example.com", "remote": True}


class WatchlistUndoApiTests(WatchlistUndoFixture):
    def view(self):
        return api.undo_view(id=str(fixture.CHANGE_ID))

    def apply(self, profile="matt", **extra):
        return api.apply_undo(json.dumps({"profile": profile, "id": fixture.CHANGE_ID, "expect": "0" * 64, **extra}).encode())

    def refused(self, status, call, *args, **kwargs):
        with self.assertRaises(ApiError) as caught:
            call(*args, **kwargs)
        self.assertEqual(caught.exception.status, status, caught.exception.message)
        return caught.exception

    def listed(self, **extra):
        rows = copy.deepcopy(self.store.audit[fixture.CHANGE_ID])
        return {"id": fixture.CHANGE_ID, "rows": rows, "total": len(rows), **extra}

    def test_packet_lists_every_row_its_stable_id_and_exactly_the_changed_fields_without_writing(self):
        answer = self.view()
        self.assertEqual(set(answer), PACKET)
        self.assertEqual((answer["kind"], answer["space"], answer["action"], answer["row_count"], answer["label"]),
                         ("watchlist", "home", queue.ACTION, 2, "Updates to 2 purchase-queue rows"))
        self.assertEqual([set(item) for item in answer["rows"]], [{"current", "fields", "label", "restored", "watch_row_id"}] * 2)
        self.assertEqual([(item["current"], item["restored"]) for item in answer["rows"]], self.changed)
        self.assertEqual([item["watch_row_id"] for item in answer["rows"]], [7, 8])
        self.assertEqual(answer["rows"][0]["fields"][0], {"field": "quantity", "before": "1", "after": "3"})
        self.assertNotIn("proof", json.dumps(answer))
        self.assertEqual(self.store.writes, [])

    def test_save_restores_every_row_and_returns_an_exact_receipt(self):
        preview = self.view()
        answer = self.apply(expect=preview["expect"])
        self.assertEqual(set(answer), RECEIPT)
        self.assertEqual((answer["kind"], answer["space"], answer["action"], answer["row_count"]), ("watchlist", "home", queue.ACTION, 2))
        self.assertEqual(answer["restored_rows"], [{"watch_row_id": 7, "row": self.changed[0][1]},
                                                   {"watch_row_id": 8, "row": self.changed[1][1]}])
        self.assertEqual(answer["sha256"], files.rendered_sha256(self.store.snapshot.watchlist))
        self.assertEqual(answer["revision"], self.store.snapshot.revision)
        op, actor, _, summary, reason = self.store.writes[0]
        self.assertEqual(dict(op.params), {"change_id": fixture.CHANGE_ID, "space": "home", "expect": preview["expect"]})
        self.assertEqual((actor.id, reason), ("matt", None))
        self.refused(400, self.apply, expect=preview["expect"])  # Its rows were touched by the Undo itself.
        self.assertEqual(len(self.store.writes), 1)

    def test_user1_is_refused_after_review_and_a_member_sees_no_change(self):
        with access.using(USER1):
            self.assertIn("orders", self.refused(403, self.view).message)
            self.refused(403, self.apply, profile="user1")
        with access.using(USER2), mock.patch.object(self.store, "undo_audit_rows", side_effect=AssertionError("Member read")):
            self.refused(404, self.view)
            self.refused(404, self.apply, profile="user2")
        self.assertEqual(self.store.writes, [])

    def test_a_reason_a_confirmation_or_a_stale_receipt_refuses_before_any_write(self):
        preview = self.view()
        with mock.patch.object(saving, "apply_op", side_effect=AssertionError("No write entry point")):
            for extra in ({"reason": "Not wanted"}, {"confirm_owned": True}, {"confirm_owned": False}):
                with self.subTest(extra=extra):
                    self.refused(400, self.apply, expect=preview["expect"], **extra)
            self.refused(409, self.apply, expect="0" * 64)
            self.refused(400, self.apply, expect="short")
        self.assertEqual(self.store.writes, [])

    def test_an_unproved_backend_result_is_never_reported_as_saved(self):
        preview = self.view()
        self.store.apply = fixture.AuditInventory.apply.__get__(self.store)  # No transaction-local proof.
        self.refused(503, self.apply, expect=preview["expect"])

    def test_refusals_name_only_counts_and_fixed_reasons(self):
        self.seed(pairs(51))
        answer = self.view()
        self.assertEqual(set(answer), {"available", "id", "reason"})
        self.assertIn("51 purchase-queue rows", answer["reason"])
        self.seed()
        self.touched[7] += 10
        answer = self.view()
        self.assertIn(queue.EDITED + ": 1", answer["reason"])
        for words in ("Fixture card", "queue note", "0.50", "Fixture shop"):
            self.assertNotIn(words, answer["reason"])

    def test_a_malformed_plan_is_never_projected(self):
        plan = api._review(fixture.CHANGE_ID, guard.viewer())
        self.assertEqual(set(queue_api.project(plan)), PACKET)
        mutations = (lambda p: p.update(kind="tokens"), lambda p: p.update(space="user2"), lambda p: p.update(row_count=3),
                     lambda p: p.update(label="Updates"), lambda p: p.update(expect="x"), lambda p: p.update(rows=[]),
                     lambda p: p["rows"][1].update(watch_row_id=7), lambda p: p["rows"][0].update(watch_row_id="7"),
                     lambda p: p["rows"][0]["restore"].update(quantity="0"), lambda p: p["rows"][0]["restore"].update(quantity=3),
                     lambda p: p["rows"][0]["current"].update(extra="x"), lambda p: p["rows"][0]["fields"].pop(),
                     lambda p: p["rows"][0].update(fields=[]), lambda p: p["rows"][0].update(restore=dict(p["rows"][0]["current"])),
                     lambda p: p["rows"][0].update(label=" "))
        for mutate in mutations:
            changed = copy.deepcopy(plan)
            mutate(changed)
            with self.subTest(mutate=mutate):
                self.assertEqual(self.refused(503, api._project, changed).message, queue_api.UNCONFIRMED)

    def test_a_backend_receipt_without_the_proof_is_unconfirmed(self):
        preview = self.view()
        def unproved(op, profile, message, refused, **kwargs):
            return op.run(self.store.snapshot)  # The plan's proof is still there; no restored ids.
        with mock.patch.object(saving, "apply_op", side_effect=unproved):
            self.refused(503, self.apply, expect=preview["expect"])

    def test_hint_offers_review_only_for_whole_queue_updates_to_an_order_editor(self):
        profile = guard.viewer()
        shown = {"id": fixture.CHANGE_ID}
        self.assertEqual(api.review_hint(self.listed(), shown, profile), {"review": True})
        self.seed(pairs(1))
        self.assertEqual(api.review_hint(self.listed(), shown, profile), {"review": True})
        self.seed()
        for extra in ({"more": 1}, {"groups": [{"table": "watchlist_item"}]}, {"total": 3}, {"total": 51}):
            self.assertIsNone(api.review_hint(self.listed(**extra), shown, profile), extra)
        mixed = self.listed()
        mixed["rows"].append({"id": 900, "table": "order_component", "op": "UPDATE", "key": {"order_id": "x"},
                              "before": {}, "after": {}})
        mixed["total"] = 3
        self.assertIsNone(api.review_hint(mixed, shown, profile))
        moved = self.listed()
        moved["rows"][0]["before"]["position"] += 1
        self.assertIsNone(api.review_hint(moved, shown, profile))
        self.assertIsNone(api.review_hint(self.listed(), {"id": 99}, profile))
        user1 = {"id": "user1", "name": "User1", "role": "member", "space": "home"}
        user2 = {"id": "user2", "name": "User2", "role": "member", "space": "user2"}
        with access.using(USER1):
            self.assertIsNone(api.review_hint(self.listed(), shown, user1))
        with access.using(USER2):
            self.assertIsNone(api.review_hint(self.listed(), shown, user2))


if __name__ == "__main__":
    unittest.main()
