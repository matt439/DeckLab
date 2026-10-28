"""Whole-change Undo of a trade (E7-S22) over test_inventory_undo_mixed's isolated recording fixture.

A trade lowers or removes the rows whose copies left and adds the copies that came in, as one
change saved with the reason "Traded" (or "Traded with T"). Undo puts every row back as one new
change, refused when anything the trade touched has changed since or the cards that came in may
be held. No PostgreSQL, household data or network is used; test_collection_trade.py runs it
through the real audit trail.
"""
import copy
import unittest

from decklab.lib import inventory
from decklab.lib.inventory import ops_collection, undo, undo_mixed
from decklab.tests import test_inventory_undo_mixed as mixed

CARD = mixed.CARD                                       # 2 Llanowar Elves (FDN 227), NM, English
MYSTIC = {"name": "Elvish Mystic", "set": "cmm", "collector_number": "648", "finish": "nonfoil",
          "quantity": "1", "condition": "", "language": "", "notes": "Reign of Dragons precon"}
M19 = {**mixed.NEW, "quantity": "1"}                    # 1 Llanowar Elves (M19 314)
SOL = {"name": "Sol Ring", "set": "ecc", "collector_number": "57", "finish": "nonfoil",
       "quantity": "1", "condition": "LP", "language": "ja", "notes": ""}
GAVE = [["fdn", "227", "nonfoil", 1], ["cmm", "648", "nonfoil", 1]]
GOT = [SOL, {**M19, "quantity": "2"}]


class TradeUndoCase(mixed.MixedUndoCase):
    def setUp(self):
        super().setUp()
        self.store.snapshot = self.store.snapshot.with_collection("home", [CARD, MYSTIC, M19])

    def trade(self, gave=GAVE, got=GOT, space="home", reason="Traded with User3"):
        inventory.apply(inventory.Op("collection.trade", {"space": space, "gave": gave, "got": got}),
                        mixed.ACTOR, "fixture trade", reason=reason)
        return self.store.next_change


class TradeUndoTests(TradeUndoCase):

    def test_preview_names_both_sides_and_writes_nothing(self):
        change = self.trade()
        snapshot, audit = self.store.snapshot, copy.deepcopy(self.store.audit)
        plan = self.review(change)
        self.assertEqual((plan["kind"], plan["action"], plan["space"], plan["label"]),
                         ("mixed", "trade_undo", "home", "Trade: gave 2 cards, got 3 cards"))
        self.assertEqual((plan["cards"], plan["returned_cards"]), (3, 2))
        self.assertEqual([row["name"] for row in plan["collection"]["removed"]], ["Sol Ring"])
        self.assertEqual([(item["current"]["quantity"], item["restored"]["quantity"]) for item in plan["collection"]["reduced"]],
                         [(3, 1)])
        self.assertEqual(plan["returned"]["added"], [{**MYSTIC, "quantity": 1}])
        self.assertEqual([(item["current"]["quantity"], item["restored"]["quantity"]) for item in plan["returned"]["raised"]],
                         [(1, 2)])
        self.assertEqual((plan["uploads"], plan["components"], plan["products"]), ([], [], []))
        self.assertEqual((self.store.snapshot, self.store.audit), (snapshot, audit))

    def test_undo_puts_the_collection_back_as_one_change(self):
        before = self.collection()
        change = self.trade()
        source = copy.deepcopy(self.store.audit[change])
        self.undo(change)
        self.assertEqual(self.collection(), before)
        self.assertEqual(self.store.audit[change], source)
        op, actor, message, summary, reason = self.store.writes[-1]
        self.assertEqual((op.kind, message, reason), ("inventory.undo_mixed", f"Undo activity change {change}", mixed.REASON))
        self.assertEqual(summary.text, f"Undo change #{change}: Trade: gave 2 cards, got 3 cards")
        self.assertEqual((summary.counts["removed"], summary.counts["edited"], summary.counts["returned"],
                          summary.counts["returned_cards"]), (1, 1, 2, 2))
        self.assertEqual(summary.extra["action"], "trade_undo")
        self.assertIn("tables", summary.extra)          # the deck tables are worked out again

    def test_a_plain_reason_traded_counts_too(self):
        before = self.collection()
        self.undo(self.trade(reason="Traded"))
        self.assertEqual(self.collection(), before)

    def test_the_same_rows_without_a_trades_reason_are_not_a_trade(self):
        for reason in (None, "Sold", "Traded away", "traded"):
            with self.subTest(reason=reason):
                self.store.snapshot = self.store.snapshot.with_collection("home", [CARD, MYSTIC, M19])
                change = self.trade(reason=reason)
                with self.assertRaises(undo.UndoUnsupported):
                    self.review(change)

    def test_a_later_edit_of_a_given_row_refuses_naming_it(self):
        change = self.trade()
        sha = ops_collection.sha256_of(self.store.snapshot.collection("home"))
        self.write(inventory.Op("collection.edit", {"space": "home", "original": ["fdn", "227", "nonfoil"],
                                                    "row": {**CARD, "quantity": "1", "notes": "sorted"}, "sha256": sha}))
        with self.assertRaises(undo.UndoConflict) as caught:
            self.review(change)
        self.assertIn("FDN 227", caught.exception.label)

    def test_a_removed_row_added_again_since_refuses(self):
        change = self.trade()
        self.write(inventory.Op("collection.import", {"space": "home", "sources": [["again.csv", [MYSTIC]]]}))
        with self.assertRaises(undo.UndoConflict) as caught:
            self.review(change)
        self.assertIn("CMM 648", caught.exception.label)

    def test_a_card_that_came_in_since_moved_or_removed_refuses(self):
        change = self.trade()
        self.write(inventory.Op("collection.remove", {"space": "home", "original": ["ecc", "57", "nonfoil"]}))
        with self.assertRaises(undo.UndoConflict):
            self.review(change)

    def test_a_card_that_came_in_used_by_a_built_deck_refuses(self):
        change = self.trade()
        self.built("1 Sol Ring\n59 Forest")
        with self.assertRaises(undo.UndoConflict) as caught:
            self.review(change)
        self.assertIn("ECC 57", caught.exception.label)

    def test_given_copies_a_built_deck_holds_come_back_freely(self):
        self.built("2 Llanowar Elves\n58 Forest")
        before = self.collection()
        change = self.trade(gave=[["fdn", "227", "nonfoil", 1]], got=[SOL])
        self.undo(change)
        self.assertEqual(self.collection(), before)

    def test_a_tracked_basic_land_that_came_in_refuses_but_one_given_comes_back(self):
        forest = {**MYSTIC, "name": "Forest", "set": "unf", "collector_number": "239", "finish": "foil", "notes": ""}
        self.store.snapshot = self.store.snapshot.with_collection("home", [CARD, MYSTIC, M19, forest])
        got_basic = self.trade(gave=[["fdn", "227", "nonfoil", 1]], got=[{**forest, "quantity": "2"}])
        with self.assertRaises(undo.UndoUnsupported):
            self.review(got_basic)
        before = self.collection()
        gave_basic = self.trade(gave=[["unf", "239", "foil", 3]], got=[SOL])
        self.undo(gave_basic)
        self.assertEqual(self.collection(), before)

    def test_another_space_is_missing_and_a_members_trade_undoes_in_its_own_space(self):
        self.store.snapshot = self.store.snapshot.with_collection("user2", [CARD, MYSTIC])
        before = self.collection("user2")
        change = self.trade(gave=[["cmm", "648", "nonfoil", 1]], got=[SOL], space="user2")
        with self.assertRaises(undo.UndoMissing):
            self.review(change, "home")
        self.undo(change, space="user2")
        self.assertEqual(self.collection("user2"), before)

    def test_undoing_twice_refuses(self):
        change = self.trade()
        self.undo(change)
        with self.assertRaises(undo.UndoConflict):
            self.review(change)

    def test_an_altered_record_cannot_pretend_to_be_a_trade(self):
        change = self.trade()
        for row in self.store.audit[change]:
            if row["op"] == "UPDATE" and row["after"]["quantity"] < row["before"]["quantity"]:
                row["after"]["notes"] = "rewritten"     # a given row changes only its count
        with self.assertRaises(undo.UndoUnsupported):
            self.review(change)

    def test_a_record_that_gave_nothing_is_not_a_trade(self):
        change = self.trade()
        self.store.audit[change] = [row for row in self.store.audit[change]
                                    if not undo_mixed._gave(row)]
        with self.assertRaises(undo.UndoUnsupported):
            self.review(change)

    def test_looks_like_needs_the_trade_reason_and_own_rows(self):
        change = self.trade()
        rows = copy.deepcopy(self.store.audit[change])
        self.assertEqual(undo_mixed.looks_like(rows, None, "home", "Traded"), undo_mixed.TRADE)
        self.assertEqual(undo_mixed.looks_like(rows, None, "home", "Traded with User3"), undo_mixed.TRADE)
        self.assertIsNone(undo_mixed.looks_like(rows, None, "home", None))
        self.assertIsNone(undo_mixed.looks_like(rows, None, "user2", "Traded"))
        added = [row for row in rows if not undo_mixed._gave(row)]
        self.assertIsNone(undo_mixed.looks_like(added, None, "home", "Traded"))


if __name__ == "__main__":
    unittest.main()
