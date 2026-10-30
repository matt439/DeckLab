"""Activity undoes a purchase-queue change that mixed updated, added and removed rows: home's order editors only, exact packets and receipts."""
import copy
import json
import unittest
from types import SimpleNamespace
from unittest import mock

from decklab.lib.api import activity_undo as api, activity_watchlist_mixed_undo as mixed_api, activity_watchlist_undo as queue_api
from decklab.lib.api import guard, saving
from decklab.lib.inventory import files, undo_watchlist_mixed as mixed
from decklab.tests import test_activity_undo_api as fixture
from decklab.tests.test_activity_undo_watchlist_rows_api import WatchlistRowsApiFixture
from decklab.tests.test_inventory_undo_watchlist_mixed import WatchlistMixedFixture
from decklab.tests.test_inventory_undo_watchlist_rows import FRESH

PACKET = {"action", "available", "counts", "expect", "id", "kind", "label", "reason_required", "row_count", "rows", "space"}
RECEIPT = {"saved", "source_id", "expect", "kind", "space", "action", "row_count", "restored_rows", "removed_watch_row_ids",
           "new_rows", "sha256", "revision", "summary"}


class WatchlistMixedApiTests(WatchlistMixedFixture, WatchlistRowsApiFixture):
    def test_packet_lists_every_row_by_its_effect_without_the_proof_or_writing(self):
        answer = self.view()
        self.assertEqual(set(answer), PACKET)
        self.assertEqual((answer["kind"], answer["space"], answer["action"], answer["row_count"], answer["label"], answer["reason_required"]),
                         ("watchlist", "home", mixed.ACTION, 3, "Changes to 3 purchase-queue rows", True))
        self.assertEqual(answer["counts"], {"updated": 1, "added": 1, "removed": 1})
        updated, added, removed = answer["rows"]
        self.assertEqual(set(updated), {"change", "label", "watch_row_id", "current", "restored", "fields"})
        self.assertEqual((updated["change"], updated["watch_row_id"], updated["current"], updated["restored"]), ("updated", 7, *self.updates[0]))
        self.assertEqual(added, {"change": "added", "label": "Added card 1", "watch_row_id": 100, "current": self.added[0]})
        self.assertEqual(removed, {"change": "removed", "label": "Removed card 1", "restored": self.removed[0]})
        self.assertNotIn("proof", json.dumps(answer))
        self.assertEqual(self.store.writes, [])

    def test_save_needs_the_reason_and_returns_an_exact_receipt(self):
        preview = self.view()
        with mock.patch.object(saving, "apply_op", side_effect=AssertionError("No write entry point")):
            for extra in ({}, {"reason": " "}, {"reason": "Not wanted", "confirm_owned": True}, {"reason": "Not wanted", "confirm_owned": False}):
                with self.subTest(extra=extra):
                    self.refused(400, self.apply, expect=preview["expect"], **extra)
            self.refused(409, self.apply, reason="Not wanted")
        answer = self.apply(expect=preview["expect"], reason=" Shop  check mistake ")
        self.assertEqual(set(answer), RECEIPT)
        self.assertEqual((answer["action"], answer["row_count"], answer["removed_watch_row_ids"]), (mixed.ACTION, 3, [100]))
        self.assertEqual(answer["restored_rows"], [{"watch_row_id": 7, "row": self.updates[0][1]}])
        self.assertEqual(answer["new_rows"], [{"watch_row_id": FRESH, "row": self.removed[0]}])
        self.assertEqual((answer["sha256"], answer["revision"]), (files.rendered_sha256(self.store.snapshot.watchlist), self.store.snapshot.revision))
        self.assertEqual(self.names(), ["Sol Ring", "Removed card 1", "Fixture card 1", "Arcane Signet"])
        op, actor, _, summary, reason = self.store.writes[0]
        self.assertEqual(dict(op.params), {"change_id": fixture.CHANGE_ID, "space": "home", "expect": preview["expect"],
                                           "reason": "Shop check mistake"})
        self.assertEqual((actor.id, reason, summary.extra["undo_reason"]), ("matt", "Shop check mistake", "Shop check mistake"))
        self.refused(400, self.apply, expect=preview["expect"], reason="Again")   # Its rows have changed.
        self.assertEqual(len(self.store.writes), 1)

    def test_a_mix_that_removes_no_row_takes_no_reason(self):
        self.mix(1, 0, 1)
        preview = self.view()
        self.assertNotIn("reason_required", preview)
        with mock.patch.object(saving, "apply_op", side_effect=AssertionError("No write entry point")):
            for extra in ({"reason": "Not wanted"}, {"confirm_owned": False}):
                with self.subTest(extra=extra):
                    self.refused(400, self.apply, expect=preview["expect"], **extra)
        answer = self.apply(expect=preview["expect"])
        self.assertEqual((answer["removed_watch_row_ids"], len(answer["restored_rows"]), len(answer["new_rows"])), ([], 1, 1))
        self.assertEqual(self.store.writes[0][4], None)

    def test_user1_is_refused_after_review_and_a_member_sees_no_change(self):
        self.access_rules(reason="Not wanted")

    def test_an_unproved_or_wrong_backend_result_is_never_reported_as_saved(self):
        preview = self.view()
        def unproved(op, profile, message, refused, **kwargs):
            return op.run(self.store.snapshot)   # The plan's proof is still there; no ids.
        with mock.patch.object(saving, "apply_op", side_effect=unproved):
            self.refused(503, self.apply, expect=preview["expect"], reason="Not wanted")
        plan = api._review(fixture.CHANGE_ID, guard.viewer())
        good = {"undo_of": fixture.CHANGE_ID, "kind": "watchlist", "space": "home", "action": mixed.ACTION, "row_count": 3,
                "row_change_ids": [item["row_change_id"] for item in plan["rows"]], "undo_reason": "Not wanted",
                "restored_watch_row_ids": [7], "removed_watch_row_ids": [100], "added_watch_row_ids": [FRESH]}
        for change in ({"added_watch_row_ids": [200]}, {"added_watch_row_ids": [1]}, {"added_watch_row_ids": []},
                       {"removed_watch_row_ids": []}, {"restored_watch_row_ids": [8]}, {"undo_reason": "Other"}, {"row_count": 2}):
            with self.subTest(change=change):
                fake = SimpleNamespace(changed={"watchlist.csv": ["add"]}, counts={"edited": 1, "removed_rows": 1, "added_rows": 1, "undo": 1},
                                       text="x", extra={**good, **change})
                self.assertEqual(self.refused(503, mixed_api.saved, self.store.snapshot, plan, plan["expect"], fake, "Not wanted").message,
                                 queue_api.UNCONFIRMED)

    def test_refusals_name_only_counts_and_fixed_reasons(self):
        self.mix(20, 20, 11)
        answer = self.view()
        self.assertEqual(set(answer), {"available", "id", "reason"})
        self.assertIn("touched 51 purchase-queue rows", answer["reason"])
        self.mix()
        self.touched[100] += 10
        answer = self.view()
        self.assertIn(mixed.EDITED + ": 1", answer["reason"])
        for words in ("Fixture card", "Added card", "Removed card", "Queue note", "0.50", "Fixture shop"):
            self.assertNotIn(words, answer["reason"])

    def test_a_malformed_plan_is_never_projected(self):
        plan = api._review(fixture.CHANGE_ID, guard.viewer())
        self.assertEqual(set(queue_api.project(plan)), PACKET)
        mutations = (lambda p: p.update(kind="tokens"), lambda p: p.update(space="user2"), lambda p: p.update(row_count=4),
                     lambda p: p.update(label="Changes to 3 rows"), lambda p: p.update(expect="x"), lambda p: p.update(rows=[]),
                     lambda p: p.pop("reason_required"), lambda p: p["counts"].update(added=0),
                     lambda p: p.update(counts={"updated": 3, "added": 0, "removed": 0}),
                     lambda p: p["rows"].reverse(), lambda p: p["rows"][1].update(watch_row_id=7),
                     lambda p: p["rows"][0].update(fields=[]), lambda p: p["rows"][0]["restore"].update(quantity="0"),
                     lambda p: p["rows"][1]["current"].update(extra="x"), lambda p: p["rows"][2]["restore"].pop("notes"),
                     lambda p: p["rows"][2].update(label=" "), lambda p: p["rows"][1].update(watch_row_id="100"))
        for mutate in mutations:
            changed = copy.deepcopy(plan)
            mutate(changed)
            with self.subTest(mutate=mutate):
                self.assertEqual(self.refused(503, api._project, changed).message, queue_api.UNCONFIRMED)
        self.mix(1, 0, 1)
        plan = api._review(fixture.CHANGE_ID, guard.viewer())
        plan["reason_required"] = True
        self.assertEqual(self.refused(503, api._project, plan).message, queue_api.UNCONFIRMED)

    def test_hint_offers_review_only_for_whole_queue_mixes_to_an_order_editor(self):
        profile, shown = guard.viewer(), {"id": fixture.CHANGE_ID}
        self.assertEqual(api.review_hint(self.listed(), shown, profile), {"review": True})
        for extra in ({"more": 1}, {"groups": [{"table": "watchlist_item"}]}, {"total": 4}):
            self.assertIsNone(api.review_hint(self.listed(**extra), shown, profile), extra)
        other = self.listed()
        other["rows"].append({"id": 999, "table": "order_component", "op": "UPDATE", "key": {"order_id": "x", "component_id": "cards"},
                              "before": {"status": "pending"}, "after": {"status": "received"}})
        other["total"] = 4
        self.assertIsNone(api.review_hint(other, shown, profile))
        with mock.patch.object(guard, "allowed", return_value=False):
            self.assertIsNone(api.review_hint(self.listed(), shown, profile))
        self.assertIsNone(api.review_hint(self.listed(), shown, {"id": "user2", "name": "User2", "role": "member", "space": "user2"}))


if __name__ == "__main__":
    unittest.main()
