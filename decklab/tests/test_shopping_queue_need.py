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
    def annotate(self, to_buy, result, counted=COUNTED):
        with mock.patch.object(need.shopping_missing, "is_token", return_value=False):
            return need.annotate(to_buy, result, counted, canonical=same_name)

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

    def test_canonical_names_join_and_the_missing_rows_queue_copies_carry_the_mark(self):
        rows = [queued("murderous rider", 1, quantity=3), queued("Opt", 2)]
        result = missing((RIDER, 1, dict(rows[0])))
        with mock.patch.object(need.shopping_missing, "is_token", return_value=False):
            need.annotate(rows, result, COUNTED, canonical=lambda name: RIDER if name.startswith("murd") else name)
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

    def test_overview_marks_only_proven_any_printing_rows_and_writes_nothing(self):
        before = self.backend.load()
        with mock.patch.object(inventory, "apply", side_effect=AssertionError("read only")):
            answer = self.overview()
        self.expected_baseline(answer)
        marks = self.marks(answer)
        # Alpha's seven any-printing Elves against six missing; the exact, unlinked and token rows add nothing.
        self.assertEqual(marks[("Llanowar Elves", "Alpha")],
                         {"state": "fewer", "card": "Llanowar Elves", "missing": 6, "queued": 7, "fewer": 1, "rows": 1})
        self.assertEqual(marks[("Elvish Mystic", "Alpha")]["fewer"], 9)
        self.assertEqual(set(marks), {("Llanowar Elves", "Alpha"), ("Elvish Mystic", "Alpha")})
        elves = next(row for row in answer["missing_cards"]["rows"] if row["name"] == "Llanowar Elves")
        self.assertEqual([copy.get("queue_need") for copy in elves["queue"] if copy["for"] == "Alpha"],
                         [marks[("Llanowar Elves", "Alpha")]])
        self.assertEqual(files.render(self.backend.load(), decks=True), files.render(before, decks=True))

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
        self.assertNotIn(("Llanowar Elves", "Alpha"), self.marks(answer))
        self.assertNotIn(("Elvish Mystic", "Alpha"), self.marks(answer))
        self.assertTrue(json.dumps(answer))


if __name__ == "__main__":
    unittest.main()
