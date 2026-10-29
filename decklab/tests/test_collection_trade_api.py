"""The Collection page's Record a trade (E7-S22): POST /api/collection/trade/preview and
/api/collection/trade (lib/api/collection_trade.py), in test_collection_edit's sandbox. A trade's
preview writes nothing and names the built decks that would lose cards and the tables it would leave
out of date; its save is one write naming both sides and the who-with note, with the reason
"Traded", refused while held copies aren't confirmed, and only by the space's own people.

Run from the repo root: python scripts/test_fixtures.py decklab.tests.test_collection_trade_api
"""
from decklab.lib.api import collection_trade as ct
from decklab.tests import test_collection_edit as tce
from decklab.tests import test_collection_reduction_api as reduction
from decklab.tests.test_api import _write

ELVES = {"set": "fdn", "collector_number": "227", "finish": "nonfoil"}
LOTUS = {"name": "black lotus", "set": "LEA", "collector_number": "232", "finish": "nonfoil", "quantity": 1,
         "condition": "NM", "language": "en", "notes": ""}


class TradeApiTestCase(tce.CollectionEditTestCase):

    def trade(self, function, space="home", profile="matt", **data):
        data.setdefault("sha256", self.rows(space)["sha256"])
        data.setdefault("gave", [{**ELVES, "quantity": 1}])
        data.setdefault("got", [LOTUS])
        return self.call(function, profile, space=space, **data)

    def preview(self, **data):
        return self.trade(ct.preview_trade, **data)

    def save(self, **data):
        return self.trade(ct.save_trade, **data)


class TradeTests(TradeApiTestCase):

    def test_the_preview_names_both_sides_and_writes_nothing(self):
        before = self.magic_files()
        answer = self.preview(**{"with": "User3", "message": "Swapped at the shop"})
        self.assertEqual(self.magic_files(), before)
        self.assertEqual(self.writes, [])
        self.assertEqual(answer["gave"], [{"name": "Llanowar Elves", **ELVES, "quantity": 1, "before": 5, "after": 4}])
        self.assertEqual([(r["name"], r["set"], r["quantity"]) for r in answer["got"]], [("Black Lotus", "lea", "1")])
        self.assertEqual(answer["in_use"], [])
        self.assertIsNone(answer["confirm_in_use"])
        self.assertEqual(answer["stale_tables"], [])
        self.assertEqual(answer["message"], "Swapped at the shop. Trade with User3: gave 1 Llanowar Elves (FDN 227); "
                                            "got 1 Black Lotus (LEA 232)")
        self.assertEqual(answer["reason"], "Traded with User3")
        self.assertNotIn("aud", str(answer))

    def test_a_trade_is_one_write_naming_both_sides(self):
        answer = self.save(**{"with": "User3"})
        self.assertTrue(answer["ok"])
        self.assertEqual((answer["gave"], answer["got"]), (1, 1))
        self.assertEqual(len(self.writes), 1)
        self.assertEqual(self.last_write(), ("Trade with User3: gave 1 Llanowar Elves (FDN 227); "
                                             "got 1 Black Lotus (LEA 232)", "Matt"))
        self.assertEqual(self.reason(), "Traded with User3")
        rows = {(r["set"], r["collector_number"]): r["quantity"] for r in answer["rows"]}
        self.assertEqual(rows["fdn", "227"], "4")
        self.assertEqual(answer["rows"], self.rows()["rows"])
        self.assertEqual(answer["stale_tables"], [])
        self.assertIn("prices", answer)

    def test_giving_every_copy_removes_the_row_and_a_message_comes_first(self):
        gave = [{**ELVES, "quantity": "5"}]
        token = self.preview(gave=gave, message="Birthday swap")["confirm_in_use"]     # the sandbox's decks hold some
        self.save(gave=gave, message="Birthday swap", confirm_in_use=token)
        self.assertNotIn(("fdn", "227"), {(r["set"], r["collector_number"]) for r in self.rows()["rows"]})
        self.assertTrue(self.last_write()[0].startswith("Birthday swap. Trade: gave 5 Llanowar Elves"))
        self.assertEqual(self.reason(), "Traded")

    def test_only_the_space_s_own_people_may(self):
        with self.as_("user2"):
            self.assertApiError(403, self.preview, profile="user2", sha256="0" * 64)
            answer = self.trade(ct.save_trade, "user2", "user2")
        self.assertEqual(self.last_write()[1], "User2")
        self.assertEqual(answer["gave"], 1)
        # Matt is an admin, but User2's collection isn't his to change (or see).
        self.assertApiError(403, self.trade, ct.preview_trade, "user2", "matt", sha256="0" * 64)
        self.assertApiError(403, self.trade, ct.save_trade, "user2", "matt", sha256="0" * 64)
        # User1 records home's trades, as she edits home's collection.
        with self.as_("user1"):
            self.assertTrue(self.trade(ct.save_trade, profile="user1")["ok"])

    def test_a_stale_sha_is_409_with_the_rows_now(self):
        for function in (ct.preview_trade, ct.save_trade):
            error = self.assertApiError(409, self.trade, function, sha256="0" * 64)
            self.assertEqual(error.extra["sha256"], self.rows()["sha256"])
            self.assertEqual(len(error.extra["rows"]), 3)
        self.assertEqual(self.writes, [])

    def test_a_row_given_that_isnt_listed_is_409_with_the_rows(self):
        error = self.assertApiError(409, self.save, gave=[{**ELVES, "collector_number": "1", "quantity": 1}])
        self.assertEqual(len(error.extra["rows"]), 3)

    def test_bad_requests_are_400_and_write_nothing(self):
        for data, words in (
                ({"gave": []}, "gave must list"),
                ({"got": []}, "got must list"),
                ({"gave": [{**ELVES, "quantity": 6}]}, "so 6 can't be given"),
                ({"gave": [{**ELVES, "quantity": 0}]}, "quantity must be"),
                ({"gave": [{**ELVES, "quantity": 1}] * 2}, "given twice"),
                ({"gave": [{**ELVES, "finish": "shiny", "quantity": 1}]}, "set code, collector number and finish"),
                ({"got": [{**LOTUS, "name": "Blak Lotus"}]}, "no card named"),
                ({"got": [{**LOTUS, "finish": "foil"}]}, "wasn't printed foil"),
                ({"got": [{**LOTUS, "notes": "=SUM(A1)"}]}, "formula"),
                ({"got": [{"name": "Llanowar Elves", **ELVES, "quantity": 1}]}, "both given and got"),
                ({"with": "x" * 81}, "with must be one line"),
                ({"with": "two\nlines"}, "with must be one line"),
                ({"message": "y" * 201}, "message must be one line"),
                ({"price": 5}, "Unknown key")):
            with self.subTest(data=data):
                self.assertApiError(400, self.save, **data, contains=words)
        self.assertApiError(400, self.preview, confirm_in_use="0" * 64, contains="Unknown key")
        self.assertEqual(self.writes, [])

    def test_ordinary_basics_got_are_left_out(self):
        forest = {"name": "Forest", "set": "fdn", "collector_number": "280", "finish": "nonfoil", "quantity": 5}
        answer = self.preview(got=[LOTUS, forest])
        self.assertEqual(answer["skipped_basics"], 5)
        self.assertEqual([r["name"] for r in answer["got"]], ["Black Lotus"])
        self.save(got=[LOTUS, forest])
        self.assertTrue(self.last_write()[0].endswith("got 1 Black Lotus (LEA 232)"))

    def test_the_preview_names_the_tables_it_would_leave_out_of_date(self):
        table = ("\n## Owned vs needed\n\n| Card | Need | Owned | Missing | ~AUD each | ~AUD missing | Notes |\n"
                 "|---|---|---|---|---|---|---|\n| Llanowar Elves | 4 | 2 | **2** | | | |\n"
                 "| **Total to buy** | | | **2** | | | |\n")
        _write(self.box.magic / "people" / "user2" / "decks" / "casual" / "r-table.md",
               "# R Table\n\n- **Format:** Casual 60-card, 1v1\n- **Status:** idea\n\n## Decklist\n\n"
               "```\nDeck\n4 Llanowar Elves (FDN) 227\n```\n" + table)
        with self.as_("user2"):
            answer = self.trade(ct.preview_trade, "user2", "user2")
            self.assertEqual(answer["stale_tables"], [{"id": "user2/casual/r-table", "title": "R Table"}])
            saved = self.trade(ct.save_trade, "user2", "user2")
        self.assertEqual([s["id"] for s in saved["stale_tables"]], ["user2/casual/r-table"])


class TradeInUseTests(TradeApiTestCase):
    """Home: 4 Llanowar Elves, all of them held by the built deck "Held"."""

    def setUp(self):
        super().setUp()
        reduction.prepare(self.box)

    def test_held_copies_are_named_and_need_the_review_token(self):
        preview = self.preview()
        self.assertEqual(preview["in_use"], [{"name": "Llanowar Elves", "before": 4, "after": 3, "in_use": 4,
                                              "shortage": 1, "holders": [
                                                  {"id": "casual/gruul-test", "title": "Held", "qty": 4}]}])
        self.assertRegex(preview["confirm_in_use"], r"^[0-9a-f]{64}$")
        before = self.magic_files()
        error = self.assertApiError(409, self.save)
        self.assertEqual(error.extra["confirm_in_use"], preview["confirm_in_use"])
        self.assertEqual(error.extra["in_use"], preview["in_use"])
        self.assertEqual(self.magic_files(), before)
        # A token for another trade (two copies, not one) isn't this one's.
        self.assertApiError(409, self.save, gave=[{**ELVES, "quantity": 2}], confirm_in_use=preview["confirm_in_use"])
        self.assertEqual(self.writes, [])
        answer = self.save(confirm_in_use=preview["confirm_in_use"])
        self.assertTrue(answer["ok"])
        self.assertEqual(len(self.writes), 1)
        self.assertEqual(self.reason(), "Traded")

    def test_a_changed_deck_needs_a_new_review(self):
        token = self.preview()["confirm_in_use"]
        _write(self.box.magic / "decks" / "casual" / "gruul-test.md", reduction.held_text(5))
        error = self.assertApiError(409, self.save, confirm_in_use=token)
        self.assertNotEqual(error.extra["confirm_in_use"], token)
        self.assertEqual(self.writes, [])
