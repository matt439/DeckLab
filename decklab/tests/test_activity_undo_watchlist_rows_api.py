"""Activity removes added purchase-queue rows or restores removed ones: home's order editors only, exact packets and receipts."""
import copy
import json
import unittest
from types import SimpleNamespace
from unittest import mock

from decklab.lib import access
from decklab.lib.api import activity_undo as api, activity_watchlist_undo as queue_api, guard, saving
from decklab.lib.api.common import ApiError
from decklab.lib.inventory import files, undo_watchlist_rows as rows_undo
from decklab.tests import test_activity_undo_api as fixture
from decklab.tests.test_inventory_undo_watchlist_rows import FRESH, WatchlistRowsFixture, queued

REMOVE_PACKET = {"action", "available", "expect", "id", "kind", "label", "reason_required", "row_count", "rows", "space"}
ADD_PACKET = REMOVE_PACKET - {"reason_required"}
REMOVE_RECEIPT = {"saved", "source_id", "expect", "kind", "space", "action", "row_count", "removed_watch_row_ids", "sha256",
                  "revision", "summary"}
ADD_RECEIPT = REMOVE_RECEIPT - {"removed_watch_row_ids"} | {"restored_rows"}
USER1 = {"profile": "user1", "email": "user1@example.com", "remote": True}
USER2 = {"profile": "user2", "email": "user2@example.com", "remote": True}


class WatchlistRowsApiFixture(WatchlistRowsFixture):
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

    def access_rules(self, **extra):
        with access.using(USER1):
            self.assertIn("orders", self.refused(403, self.view).message)
            self.refused(403, self.apply, profile="user1", **extra)
        with access.using(USER2), mock.patch.object(self.store, "undo_audit_rows", side_effect=AssertionError("Member read")):
            self.refused(404, self.view)
            self.refused(404, self.apply, profile="user2", **extra)
        self.assertEqual(self.store.writes, [])


class RemoveAddedRowsApiTests(WatchlistRowsApiFixture):
    def test_packet_lists_every_added_row_by_stable_id_and_needs_a_reason_without_writing(self):
        answer = self.view()
        self.assertEqual(set(answer), REMOVE_PACKET)
        self.assertEqual((answer["kind"], answer["space"], answer["action"], answer["row_count"], answer["label"], answer["reason_required"]),
                         ("watchlist", "home", rows_undo.REMOVE, 2, "2 added purchase-queue rows", True))
        self.assertEqual(answer["rows"], [{"label": f"Fixture card {n}", "watch_row_id": 6 + n, "current": self.changed[n - 1]}
                                          for n in (1, 2)])
        self.assertNotIn("proof", json.dumps(answer))
        self.assertEqual(self.store.writes, [])

    def test_save_needs_the_reason_and_returns_an_exact_receipt(self):
        preview = self.view()
        with mock.patch.object(saving, "apply_op", side_effect=AssertionError("No write entry point")):
            for extra in ({}, {"reason": " "}, {"reason": "Not wanted", "confirm_owned": True}, {"reason": "Not wanted", "confirm_owned": False}):
                with self.subTest(extra=extra):
                    self.refused(400, self.apply, expect=preview["expect"], **extra)
            self.refused(409, self.apply, reason="Not wanted")
        answer = self.apply(expect=preview["expect"], reason=" Added  by mistake ")
        self.assertEqual(set(answer), REMOVE_RECEIPT)
        self.assertEqual((answer["action"], answer["row_count"], answer["removed_watch_row_ids"]), (rows_undo.REMOVE, 2, [7, 8]))
        self.assertEqual(answer["sha256"], files.rendered_sha256(self.store.snapshot.watchlist))
        self.assertEqual(self.names(), ["Sol Ring", "Arcane Signet"])
        op, actor, _, summary, reason = self.store.writes[0]
        self.assertEqual(dict(op.params), {"change_id": fixture.CHANGE_ID, "space": "home", "expect": preview["expect"],
                                           "reason": "Added by mistake"})
        self.assertEqual((actor.id, reason, summary.extra["undo_reason"]), ("matt", "Added by mistake", "Added by mistake"))
        self.refused(400, self.apply, expect=preview["expect"], reason="Again")  # Its rows are gone.
        self.assertEqual(len(self.store.writes), 1)

    def test_user1_is_refused_after_review_and_a_member_sees_no_change(self):
        self.access_rules(reason="Not wanted")

    def test_an_unproved_backend_result_is_never_reported_as_saved(self):
        preview = self.view()
        def unproved(op, profile, message, refused, **kwargs):
            return op.run(self.store.snapshot)  # The plan's proof is still there; no removed ids.
        with mock.patch.object(saving, "apply_op", side_effect=unproved):
            self.refused(503, self.apply, expect=preview["expect"], reason="Not wanted")

    def test_refusals_name_only_counts_and_fixed_reasons(self):
        self.seed(queued(51))
        answer = self.view()
        self.assertEqual(set(answer), {"available", "id", "reason"})
        self.assertIn("added 51 purchase-queue rows", answer["reason"])
        self.seed()
        self.touched[7] += 10
        answer = self.view()
        self.assertIn(rows_undo.EDITED + ": 1", answer["reason"])
        for words in ("Fixture card", "Queue note", "0.50", "Fixture shop"):
            self.assertNotIn(words, answer["reason"])

    def test_a_malformed_plan_is_never_projected(self):
        plan = api._review(fixture.CHANGE_ID, guard.viewer())
        self.assertEqual(set(queue_api.project(plan)), REMOVE_PACKET)
        mutations = (lambda p: p.update(kind="tokens"), lambda p: p.update(space="user2"), lambda p: p.update(row_count=3),
                     lambda p: p.update(label="2 added rows"), lambda p: p.update(expect="x"), lambda p: p.update(rows=[]),
                     lambda p: p.pop("reason_required"), lambda p: p["rows"][1].update(watch_row_id=7),
                     lambda p: p["rows"][0].update(watch_row_id="7"), lambda p: p["rows"][0]["current"].update(quantity="0"),
                     lambda p: p["rows"][0]["current"].update(extra="x"), lambda p: p["rows"][0].update(label=" "))
        for mutate in mutations:
            changed = copy.deepcopy(plan)
            mutate(changed)
            with self.subTest(mutate=mutate):
                self.assertEqual(self.refused(503, api._project, changed).message, queue_api.UNCONFIRMED)

    def test_hint_offers_review_only_for_whole_queue_additions_to_an_order_editor(self):
        profile, shown = guard.viewer(), {"id": fixture.CHANGE_ID}
        self.assertEqual(api.review_hint(self.listed(), shown, profile), {"review": True})
        for extra in ({"more": 1}, {"groups": [{"table": "watchlist_item"}]}, {"total": 3}):
            self.assertIsNone(api.review_hint(self.listed(**extra), shown, profile), extra)
        mixed = self.listed()
        mixed["rows"][1] = {**mixed["rows"][1], "op": "DELETE", "before": mixed["rows"][1]["after"], "after": None}
        self.assertEqual(api.review_hint(mixed, shown, profile), {"review": True})   # A mixed queue change's review.
        mixed["rows"][1] = {**mixed["rows"][1], "table": "order_component"}
        self.assertIsNone(api.review_hint(mixed, shown, profile))
        with access.using(USER2):
            self.assertIsNone(api.review_hint(self.listed(), shown, {"id": "user2", "name": "User2", "role": "member", "space": "user2"}))


class RestoreRemovedRowsApiTests(WatchlistRowsApiFixture):
    def setUp(self):
        super().setUp()
        self.seed(op="DELETE")

    def test_packet_lists_every_recorded_row_without_ids_or_reason(self):
        answer = self.view()
        self.assertEqual(set(answer), ADD_PACKET)
        self.assertEqual((answer["action"], answer["row_count"], answer["label"]), (rows_undo.ADD, 2, "2 removed purchase-queue rows"))
        self.assertEqual(answer["rows"], [{"label": f"Fixture card {n}", "restored": self.changed[n - 1]} for n in (1, 2)])
        self.assertNotIn("proof", json.dumps(answer))
        self.assertEqual(self.store.writes, [])

    def test_save_restores_every_row_under_a_fresh_id_and_returns_an_exact_receipt(self):
        preview = self.view()
        with mock.patch.object(saving, "apply_op", side_effect=AssertionError("No write entry point")):
            for extra in ({"reason": "Not wanted"}, {"confirm_owned": True}, {"confirm_owned": False}):
                with self.subTest(extra=extra):
                    self.refused(400, self.apply, expect=preview["expect"], **extra)
        answer = self.apply(expect=preview["expect"])
        self.assertEqual(set(answer), ADD_RECEIPT)
        self.assertEqual(answer["restored_rows"], [{"watch_row_id": FRESH, "row": self.changed[0]},
                                                   {"watch_row_id": FRESH + 1, "row": self.changed[1]}])
        self.assertEqual(self.names(), ["Sol Ring", "Fixture card 1", "Arcane Signet", "Fixture card 2"])
        self.assertEqual((answer["sha256"], answer["revision"]), (files.rendered_sha256(self.store.snapshot.watchlist), self.store.snapshot.revision))
        op, actor, _, _, reason = self.store.writes[0]
        self.assertEqual(dict(op.params), {"change_id": fixture.CHANGE_ID, "space": "home", "expect": preview["expect"]})
        self.assertEqual((actor.id, reason), ("matt", None))
        self.refused(409, self.apply, expect=preview["expect"])  # The queue changed since the removal.
        self.assertEqual(len(self.store.writes), 1)

    def test_user1_is_refused_after_review_and_a_member_sees_no_change(self):
        self.access_rules()

    def test_a_backend_receipt_without_fresh_proved_ids_is_unconfirmed(self):
        preview = self.view()
        def unproved(op, profile, message, refused, **kwargs):
            return op.run(self.store.snapshot)
        with mock.patch.object(saving, "apply_op", side_effect=unproved):
            self.refused(503, self.apply, expect=preview["expect"])
        plan = api._review(fixture.CHANGE_ID, guard.viewer())
        for ids in ([FRESH], [FRESH, FRESH], [7, FRESH], [1, FRESH], ["500", FRESH]):
            with self.subTest(ids=ids):
                fake = SimpleNamespace(changed={"watchlist.csv": ["add"]}, counts={"added_rows": 2, "undo": 1}, text="x",
                                       extra={"undo_of": fixture.CHANGE_ID, "kind": "watchlist", "space": "home",
                                              "action": rows_undo.ADD, "row_count": 2, "restored_watch_row_ids": ids,
                                              "row_change_ids": [item["row_change_id"] for item in plan["rows"]]})
                self.assertEqual(self.refused(503, queue_api.added, self.store.snapshot, plan, plan["expect"], fake).message,
                                 queue_api.UNCONFIRMED)

    def test_a_malformed_plan_is_never_projected(self):
        plan = api._review(fixture.CHANGE_ID, guard.viewer())
        self.assertEqual(set(queue_api.project(plan)), ADD_PACKET)
        mutations = (lambda p: p.update(label="2 added purchase-queue rows"), lambda p: p.update(reason_required=True),
                     lambda p: p.update(row_count=1), lambda p: p["rows"][0]["restore"].update(quantity=1),
                     lambda p: p["rows"][1].update(restore=dict(p["rows"][0]["restore"])), lambda p: p["rows"][0].update(label=""),
                     lambda p: p["rows"][0]["restore"].pop("notes"))
        for mutate in mutations:
            changed = copy.deepcopy(plan)
            mutate(changed)
            with self.subTest(mutate=mutate):
                self.assertEqual(self.refused(503, api._project, changed).message, queue_api.UNCONFIRMED)

    def test_hint_offers_review_for_whole_queue_removals(self):
        self.assertEqual(api.review_hint(self.listed(), {"id": fixture.CHANGE_ID}, guard.viewer()), {"review": True})
        broken = self.listed()
        broken["rows"][0]["key"] = {"id": 99}
        self.assertIsNone(api.review_hint(broken, {"id": fixture.CHANGE_ID}, guard.viewer()))


if __name__ == "__main__":
    unittest.main()
