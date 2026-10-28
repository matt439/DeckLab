"""A trade's whole-change Undo through Activity's API (E7-S22), over the isolated recording fixture.

GET /api/activity/mixed-undo previews it with both sides; POST saves it as one new change for
the space's own people only. No PostgreSQL, household data or network is used.
"""
import copy
import unittest

from decklab.lib import access, inventory
from decklab.lib.api import activity_mixed_undo, activity_undo
from decklab.tests import test_activity_mixed_undo_api as api_tests
from decklab.tests import test_inventory_undo_trade as trades


class TradeUndoApiTests(trades.TradeUndoCase):
    view = api_tests.MixedUndoApiTests.view
    post = api_tests.MixedUndoApiTests.post
    refused = api_tests.MixedUndoApiTests.refused

    def seed(self, space="home"):
        self.store.snapshot = self.store.snapshot.with_collection(space, [trades.CARD, trades.MYSTIC, trades.M19])

    def test_trade_preview_shows_both_sides(self):
        self.seed()
        change = self.trade()
        answer = self.view(change)
        self.assertEqual(set(answer), {"available", "id", "expect", "kind", "space", "action", "label", "reason_required",
                                       "cards", "collection", "tokens", "components", "products", "uploads",
                                       "returned", "returned_cards"})
        self.assertEqual((answer["action"], answer["label"], answer["cards"], answer["returned_cards"]),
                         ("trade_undo", "Trade: gave 2 cards, got 3 cards", 3, 2))
        self.assertEqual([row["name"] for row in answer["returned"]["added"]], ["Elvish Mystic"])
        self.assertEqual(len(answer["returned"]["raised"]), 1)
        self.assertEqual(self.store.writes[-1][2], trades.words("Traded with User3"))

    def test_trade_apply_saves_one_change_and_confirms_both_sides(self):
        self.seed()
        before = self.collection()
        change = self.trade()
        answer = self.post(change)
        self.assertEqual((answer["saved"], answer["action"], answer["removed_rows"], answer["restored_rows"],
                          answer["returned_rows"], answer["returned_cards"], answer["cards"]),
                         (True, "trade_undo", 1, 1, 2, 2, 3))
        self.assertEqual(self.collection(), before)
        op, actor, message, summary, reason = self.store.writes[-1]
        self.assertEqual((op.kind, actor.id, reason), ("inventory.undo_mixed", "matt", api_tests.REASON))

    def test_a_changed_trade_answers_409_naming_the_row(self):
        self.seed()
        change = self.trade()
        self.write(inventory.Op("collection.import", {"space": "home", "sources": [["again.csv", [trades.MYSTIC]]]}))
        error = self.refused(409, self.view, change)
        self.assertIn("Elvish Mystic", error.message)

    def test_a_trade_is_its_own_spaces_people_only(self):
        self.seed()
        change = self.trade()
        with access.using({"profile": "user1", "email": "user1@example.com", "remote": True}):
            self.assertTrue(self.post(change, profile="user1")["saved"])
        self.seed("user2")
        member = self.trade(space="user2", gave=[["cmm", "648", "nonfoil", 1]], got=[trades.SOL])
        self.refused(404, self.view, member)          # Matt doesn't see a member's trade, as a missing change
        with access.using({"profile": "user2", "email": "user2@example.com", "remote": True}):
            self.refused(404, self.view, self.trade(gave=[["fdn", "227", "nonfoil", 1]], got=[trades.SOL]))
            self.assertTrue(self.post(member, profile="user2")["saved"])

    def test_hint_offers_a_trade_review_only_with_its_reason_and_words(self):
        profile = {"id": "matt", "name": "Matt", "role": "admin", "space": "home"}
        self.seed()
        change = self.trade()
        rows = copy.deepcopy(self.store.audit[change])
        listed = {"id": change, "rows": rows, "total": len(rows), "reason": "Traded with User3",
                  "message": trades.words("Traded with User3")}
        self.assertEqual(activity_undo.review_hint(listed, {"id": change}, profile), {"review": True, "kind": "mixed"})
        self.assertIsNone(activity_mixed_undo.hint({**listed, "reason": "Sold"}, {"id": change}, profile))
        # a collection apply saved with a trade's reason isn't offered as a trade
        self.assertIsNone(activity_mixed_undo.hint({**listed, "message": "Remove traded cards"}, {"id": change}, profile))
        user2 = {"id": "user2", "name": "User2", "role": "member", "space": "user2"}
        with access.using({"profile": "user2", "email": "user2@example.com", "remote": True}):
            self.assertIsNone(activity_mixed_undo.hint(listed, {"id": change}, user2))



if __name__ == "__main__":
    unittest.main()
