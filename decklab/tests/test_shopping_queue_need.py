"""Queued cards the home decks no longer miss (E5-S37): the pure mark and Shopping's read."""
import copy
import csv
import io
import json
import unittest
from unittest import mock

from decklab.lib import inventory, pool
from decklab.lib.api import shopping_queue_need as need
from decklab.lib.inventory import files
from decklab.lib.inventory.model import QUEUE_FIELDS
from decklab.tests.test_shopping_missing import RIDER, _Fixture, queue_row

ALPHA = {"id": "casual/alpha", "title": "Alpha"}
BETA = {"id": "casual/beta", "title": "Beta"}
COUNTED = ("casual/alpha", "casual/beta")


def queued(name, number, quantity=1, deck=ALPHA, **fields):
    return {"name": name, "quantity": quantity, "printing": "any", "state": "ready", "for": "",
            "set": "", "collector_number": "", "finish": "nonfoil", "queue_row": number,
            "deck": dict(deck) if deck else None, **fields}


def missing(*rows, ready=True, errors=()):
    return {"ready": ready, "rows": [{"name": name, "missing": count, "decks": [], "queue": list(queue)}
                                     for name, count, *queue in rows],
            "warnings": [], "errors": list(errors), "totals": {}}


def same_name(name):
    return name


class AnnotateTests(unittest.TestCase):
    def annotate(self, to_buy, result, counted=COUNTED, players=None):
        # By default each card is needed by Alpha alone, so its count is exact.
        if players is None:
            players = {row["name"]: ["casual/alpha"] for row in to_buy}
        with mock.patch.object(need.shopping_missing, "is_token", return_value=False):
            return need.annotate(to_buy, result, counted, players=players, canonical=same_name)

    def test_any_printing_row_no_deck_misses_now_is_covered(self):
        row = queued("Opt", 1, quantity=2)
        marks = self.annotate([row], missing(("Llanowar Elves", 3)))
        self.assertEqual(row["queue_need"], {"state": "covered", "card": "Opt", "missing": 0, "queued": 2,
                                             "fewer": 2, "rows": 1})
        self.assertEqual(marks, {1: row["queue_need"]})

    def test_decks_missing_fewer_than_queued_say_how_many_fewer(self):
        row = queued("Llanowar Elves", 4, quantity=5)
        self.annotate([row], missing(("Llanowar Elves", 3)))
        self.assertEqual((row["queue_need"]["state"], row["queue_need"]["missing"], row["queue_need"]["queued"],
                          row["queue_need"]["fewer"]), ("fewer", 3, 5, 2))

    def test_enough_or_more_missing_says_nothing(self):
        for count in (3, 4):
            with self.subTest(missing=count):
                row = queued("Llanowar Elves", 1, quantity=3)
                self.assertEqual(self.annotate([row], missing(("Llanowar Elves", count))), {})
                self.assertNotIn("queue_need", row)

    def test_rows_of_one_card_are_compared_together_across_decks_and_states(self):
        rows = [queued("Llanowar Elves", 1, quantity=2), queued("Llanowar Elves", 2, quantity=2, deck=BETA,
                                                                  state="long_term")]
        self.annotate(rows, missing(("Llanowar Elves", 3)))
        for row in rows:
            self.assertEqual((row["queue_need"]["state"], row["queue_need"]["fewer"], row["queue_need"]["rows"]),
                             ("fewer", 1, 2))
        rows = [queued("Llanowar Elves", 1, quantity=2), queued("Llanowar Elves", 2, quantity=2, deck=BETA)]
        self.annotate(rows, missing(("Llanowar Elves", 4)))
        self.assertFalse(any("queue_need" in row for row in rows))

    def test_exact_token_unlinked_uncounted_and_unknown_rows_say_nothing_and_add_no_copies(self):
        rows = [queued("Opt", 1, printing="exact", set="xln", collector_number="65"),
                queued("Opt", 2, is_token=True),
                queued("Opt", 3, deck=None),
                queued("Opt", 4, deck={"id": "casual/trial", "title": "Trial"}),
                queued("Opt", 5, quantity="2"),
                queued("Opt", 6, quantity=0)]
        self.assertEqual(self.annotate(rows, missing()), {})
        self.assertFalse(any("queue_need" in row for row in rows))
        # Those copies never join an eligible row's total: one copy queued, one missing.
        rows.append(queued("Llanowar Elves", 7))
        rows += [queued("Llanowar Elves", 8, quantity=4, printing="exact", set="fdn", collector_number="227"),
                 queued("Llanowar Elves", 9, quantity=4, deck=None)]
        self.assertEqual(self.annotate(rows, missing(("Llanowar Elves", 1))), {})

    def test_positive_token_evidence_without_the_flag_says_nothing(self):
        row = queued("The Monarch", 1)
        with mock.patch.object(need.shopping_missing, "is_token", return_value=True):
            self.assertEqual(need.annotate([row], missing(), COUNTED, canonical=same_name), {})
        self.assertNotIn("queue_need", row)

    def test_an_unproven_count_marks_nothing(self):
        for result in (missing(ready=False), missing(errors=[{"message": "Deck failed"}]),
                       {"ready": True, "rows": [], "errors": [{"message": "x"}]}, None,
                       missing(("Llanowar Elves", 1), ready=False)):
            with self.subTest(result=result):
                row = queued("Opt", 1)
                self.assertEqual(self.annotate([row], result), {})
                self.assertNotIn("queue_need", row)
        row = queued("Opt", 1)
        with mock.patch.object(need.shopping_missing, "is_token", return_value=False):
            self.assertEqual(need.annotate([row], missing(), COUNTED, canonical=same_name), {})
        self.assertNotIn("queue_need", row)

    def test_a_card_two_counted_decks_need_says_nothing(self):
        # Each deck's count sees the same free copy, so neither misses it, yet both together still do.
        row = queued("Opt", 1, deck=BETA)
        self.assertEqual(self.annotate([row], missing(), players={"Opt": ["casual/alpha", "casual/beta"]}), {})
        self.assertNotIn("queue_need", row)
        rows = [queued("Llanowar Elves", 1, quantity=4)]
        self.assertEqual(self.annotate(rows, missing(("Llanowar Elves", 1)),
                                       players={"llanowar elves": ["casual/alpha", "casual/beta"]}), {})
        # No deck needing the card at all is still proven covered; one deck listed twice is one deck.
        row = queued("Opt", 2)
        self.assertEqual(self.annotate([row], missing(), players={})[2]["state"], "covered")
        row = queued("Opt", 3)
        self.assertEqual(self.annotate([row], missing(), players={"Opt": ["casual/alpha", "casual/alpha"]})[3]["state"],
                         "covered")

    def test_canonical_names_join_and_the_missing_rows_queue_copies_carry_the_mark(self):
        rows = [queued("murderous rider", 1, quantity=3), queued("Opt", 2)]
        result = missing((RIDER, 1, dict(rows[0])))
        with mock.patch.object(need.shopping_missing, "is_token", return_value=False):
            need.annotate(rows, result, COUNTED, players={RIDER: ["casual/alpha"]},
                          canonical=lambda name: RIDER if name.startswith("murd") else name)
        self.assertEqual((rows[0]["queue_need"]["card"], rows[0]["queue_need"]["fewer"]), (RIDER, 2))
        self.assertEqual(result["rows"][0]["queue"][0]["queue_need"], rows[0]["queue_need"])
        self.assertIsNot(result["rows"][0]["queue"][0]["queue_need"], rows[0]["queue_need"])

    def test_the_mark_reads_only_and_changes_nothing_else(self):
        rows = [queued("Opt", 1), queued("Llanowar Elves", 2, quantity=4)]
        result = missing(("Llanowar Elves", 1))
        before_rows, before_result = copy.deepcopy(rows), copy.deepcopy(result)
        self.annotate(rows, result)
        for before, after in zip(before_rows, rows):
            after = dict(after)
            after.pop("queue_need")
            self.assertEqual(after, before)
        self.assertEqual(result, before_result)


class ShoppingQueueNeedTests(_Fixture, unittest.TestCase):
    def marks(self, answer):
        return {(row["name"], row["for"]): row["queue_need"] for row in answer["to_buy"] if "queue_need" in row}

    def write_queue(self, *rows):
        stream = io.StringIO(newline="")
        writer = csv.DictWriter(stream, QUEUE_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
        self.case.write("watchlist.csv", stream.getvalue())

    def test_overview_marks_only_proven_any_printing_rows_and_writes_nothing(self):
        # Pick Your Poison is needed only by Gamma, which misses one; three any-printing copies are queued for it.
        self.write_queue(queue_row("Pick Your Poison", "Gamma", "deferred", source="magic/decks/commander/gamma.md",
                                   quantity="3"),
                         queue_row("Pick Your Poison", "Gamma", printing="exact", set="cmb2", collector_number="97", finish="nonfoil",
                                   source="magic/decks/commander/gamma.md", quantity="4"),
                         queue_row("Llanowar Elves", "Alpha", source="magic/decks/casual/alpha.md", quantity="9"))
        before = self.backend.load()
        with mock.patch.object(inventory, "apply", side_effect=AssertionError("read only")):
            answer = self.overview()
        marks = self.marks(answer)
        self.assertEqual(marks, {("Pick Your Poison", "Gamma"): {
            "state": "fewer", "card": "Pick Your Poison", "missing": 1, "queued": 3, "fewer": 2, "rows": 1}})
        poison = next(row for row in answer["missing_cards"]["rows"] if row["name"] == "Pick Your Poison")
        self.assertEqual([copy.get("queue_need") for copy in poison["queue"]],
                         [marks[("Pick Your Poison", "Gamma")], None])
        self.assertEqual(files.render(self.backend.load(), decks=True), files.render(before, decks=True))

    def test_cards_two_decks_need_say_nothing_even_when_neither_misses_one(self):
        # The baseline's Elves and Mystics are needed by both Alpha and Beta: their summed shortfalls prove nothing.
        answer = self.overview()
        self.expected_baseline(answer)
        self.assertNotIn(("Llanowar Elves", "Alpha"), self.marks(answer))
        self.assertNotIn(("Elvish Mystic", "Alpha"), self.marks(answer))
        # Two idea decks each play one Wrath of God and one free copy is stored: each deck's count sees that
        # copy and misses none, yet together they still need the queued one.
        self.case.cards_csv("collection.csv", ("Elvish Mystic", "cmm", "648", "nonfoil", 1),
                            (RIDER, "eld", "97", "nonfoil", 1),
                            ("Llanowar Elves", "fdn", "227", "nonfoil", 3),
                            ("Ghalta, Primal Hunger", "rix", "130", "nonfoil", 1),
                            ("Wrath of God", "8ed", "58", "nonfoil", 1))
        self.case.deck("delta", "Delta", "idea", "Deck\n1 Wrath of God\n20 Plains\n")
        self.case.deck("epsilon", "Epsilon", "idea", "Deck\n1 Wrath of God\n20 Plains\n")
        self.write_queue(queue_row("Wrath of God", "Epsilon", source="magic/decks/casual/epsilon.md"))
        answer = self.overview()
        self.assertTrue(answer["missing_cards"]["ready"])
        self.assertNotIn("Wrath of God", [row["name"] for row in answer["missing_cards"]["rows"]])
        self.assertEqual(answer["to_buy"][0]["deck"]["id"], "casual/epsilon")
        self.assertEqual(self.marks(answer), {})

    def test_a_failed_mark_leaves_shopping_answering_unmarked(self):
        from decklab.lib.api import shopping_queue_need
        with mock.patch.object(shopping_queue_need, "annotate", side_effect=ValueError("Fixture mark failed")):
            answer = self.overview()
        self.expected_baseline(answer)
        self.assertEqual(self.marks(answer), {})
        self.assertFalse(any("queue_need" in copy for row in answer["missing_cards"]["rows"] for copy in row["queue"]))
        self.assertTrue(any("Fixture mark failed" in line for line in self.logs))
        self.assertTrue(json.dumps(answer))

    def test_a_card_no_deck_misses_is_covered(self):
        rows = [queue_row("Ghalta, Primal Hunger", "Gamma", "long_term", source="magic/decks/commander/gamma.md"),
                queue_row("Opt", "Alpha", source="magic/decks/casual/alpha.md", quantity="2")]
        stream = io.StringIO(newline="")
        writer = csv.DictWriter(stream, QUEUE_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
        self.case.write("watchlist.csv", stream.getvalue())
        marks = self.marks(self.overview())
        self.assertEqual(marks[("Opt", "Alpha")]["state"], "covered")
        self.assertEqual(marks[("Opt", "Alpha")]["queued"], 2)
        self.assertEqual(marks[("Ghalta, Primal Hunger", "Gamma")]["state"], "covered")

    def test_one_unreadable_deck_or_missing_card_data_marks_nothing(self):
        compare = pool.owned_vs_needed

        def fail_one(deck_id, *args, **kwargs):
            if deck_id == "casual/beta":
                raise ValueError("Fixture planned list failed")
            return compare(deck_id, *args, **kwargs)

        with mock.patch.object(pool, "owned_vs_needed", side_effect=fail_one):
            answer = self.overview()
        self.assertFalse(answer["missing_cards"]["ready"])
        self.assertEqual(self.marks(answer), {})
        from decklab.lib.api import shopping
        with mock.patch.object(shopping, "_cards_ready", return_value=False):
            self.assertEqual(self.marks(self.overview()), {})

    def test_a_trial_deck_is_never_a_counted_deck(self):
        from decklab.lib import decks
        found = decks.list_decks()
        trial = [{**summary, "trial": "SomePrecon_FDC"} if summary["id"] == "casual/alpha" else summary
                 for summary in found]
        with mock.patch.object(decks, "list_decks", return_value=trial):
            answer = self.overview()
        self.assertNotIn(("Pick Your Poison", "Gamma"), self.marks(answer))
        self.assertTrue(json.dumps(answer))


if __name__ == "__main__":
    unittest.main()
