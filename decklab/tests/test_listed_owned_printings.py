"""Which printing the space has of a card whose Planned list names one (E2-S30):
lib/listed_prices.py's annotate_owned, the fields pool.compare adds to the live owned-vs-needed rows,
and the deck page's answer, which carries them only for a viewer who may see the space's inventory.

Names and printings come from the fixture card index (fixtures/default_cards.jsonl): Llanowar Elves is
FDN 227 (non-foil and foil) and M19 314.

Run from the repo root: python scripts/test_fixtures.py decklab.tests.test_listed_owned_printings
"""
import copy
import json
import unittest
from unittest import mock

from decklab.lib import access, api, decks, inventory, listed_prices, pool
from decklab.lib.api import guard
from decklab.tests import test_pool
from decklab.tests.test_api import ApiTestCase, _write
from decklab.tests.test_collection_edit import ROLES
from decklab.tests.test_pool import PoolTestCase, deck_md

OWN_KEYS = {"own_printing", "own_printing_label", "own_printing_more", "own_printing_on_the_way"}
ELVES = "Llanowar Elves"


def setUpModule():
    test_pool.setUpModule()


def tearDownModule():
    test_pool.tearDownModule()


def note(row):
    return {key: row[key] for key in sorted(OWN_KEYS & set(row))}


class CompareTests(PoolTestCase):
    def rows(self, decklist, *owned, status="idea", prices=False):
        self.cards_csv("collection.csv", *owned)
        self.deck("a", "A", status, decklist)
        return self.check("casual/a", prices=prices)

    def test_only_another_printing_is_owned(self):
        _, rows = self.rows("Deck\n2 Llanowar Elves (FDN) 227 *F*\n1 Sol Ring\n",
                            (ELVES, "m19", "314", "nonfoil", 2), ("Sol Ring", "ecc", "57", "nonfoil", 1))
        self.assertEqual(note(rows[ELVES]), {"own_printing": "other", "own_printing_label": "M19 314",
                                             "own_printing_more": 0, "own_printing_on_the_way": False})
        self.assertFalse(OWN_KEYS & set(rows["Sol Ring"]))         # its line names no printing

    def test_the_listed_printing_is_owned(self):
        _, rows = self.rows("Deck\n2 Llanowar Elves (FDN) 227 *F*\n",
                            (ELVES, "fdn", "227", "foil", 1), (ELVES, "m19", "314", "nonfoil", 3))
        self.assertEqual(note(rows[ELVES]), {"own_printing": "listed", "own_printing_label": "FDN 227 foil",
                                             "own_printing_more": 0, "own_printing_on_the_way": False})

    def test_the_finish_is_part_of_the_printing(self):
        # The list names the foil; the non-foil of the same set and number is another printing.
        _, rows = self.rows("Deck\n1 Llanowar Elves (FDN) 227 *F*\n",
                            (ELVES, "fdn", "227", "nonfoil", 1), (ELVES, "m19", "314", "nonfoil", 4))
        self.assertEqual(note(rows[ELVES]), {"own_printing": "other", "own_printing_label": "M19 314",
                                             "own_printing_more": 1, "own_printing_on_the_way": False})

    def test_copies_on_the_way(self):
        self.cards_csv("orders/2026-09-29-test.csv", (ELVES, "fdn", "227", "nonfoil", 1))
        _, rows = self.rows("Deck\n1 Llanowar Elves (FDN) 227\n")
        self.assertEqual(note(rows[ELVES]), {"own_printing": "listed", "own_printing_label": "FDN 227",
                                             "own_printing_more": 0, "own_printing_on_the_way": True})
        _, rows = self.rows("Deck\n1 Llanowar Elves (M19) 314\n")
        self.assertEqual(note(rows[ELVES]), {"own_printing": "other", "own_printing_label": "FDN 227",
                                             "own_printing_more": 0, "own_printing_on_the_way": True})
        # A copy in the collection is named before one still on the way.
        _, rows = self.rows("Deck\n1 Llanowar Elves (WC00) nl239\n", (ELVES, "m19", "314", "nonfoil", 1))
        self.assertEqual(note(rows[ELVES]), {"own_printing": "other", "own_printing_label": "M19 314",
                                             "own_printing_more": 0, "own_printing_on_the_way": False})

    def test_no_note_without_copies_one_named_printing_or_this_card(self):
        for decklist, owned in (
                ("Deck\n2 Llanowar Elves (FDN) 227\n", ()),                                 # none owned
                ("Deck\n2 Llanowar Elves\n", ((ELVES, "m19", "314", "nonfoil", 2),)),       # no printing named
                ("Deck\n1 Llanowar Elves (FDN) 227\n1 Llanowar Elves (M19) 314\n",          # two printings
                 ((ELVES, "m19", "314", "nonfoil", 2),)),
                ("Deck\n1 Llanowar Elves (FDN) 227\n\nSideboard\n1 Llanowar Elves\n",       # one line names none
                 ((ELVES, "m19", "314", "nonfoil", 2),)),
                ("Deck\n1 Sol Ring (FDN) 227\n", (("Sol Ring", "ecc", "57", "nonfoil", 1),))):  # another card's
            with self.subTest(decklist):
                _, rows = self.rows(decklist, *owned)
                for row in rows.values():
                    self.assertFalse(OWN_KEYS & set(row))

    def test_the_note_changes_no_count_table_or_text(self):
        owned = ((ELVES, "m19", "314", "nonfoil", 1),)
        self.cards_csv("collection.csv", *owned)
        self.deck("a", "A", "idea", "Deck\n3 Llanowar Elves (FDN) 227 *F*\n")
        before = (self.magic / "decks/casual/a.md").read_bytes()
        sections = decks.load_deck("casual/a", "target")
        plain = pool.compare(sections, pool.load_pool(), pool.self_ids("casual/a"), prices=False)
        noted = pool.compare(sections, pool.load_pool(), pool.self_ids("casual/a"), prices=False, listed=True)
        self.assertFalse(OWN_KEYS & set(plain["rows"][0]))          # only a Planned-list (listed) compare
        self.assertEqual(note(noted["rows"][0])["own_printing"], "other")
        stripped = copy.deepcopy(noted)
        for row in stripped["rows"]:
            for key in OWN_KEYS:
                row.pop(key, None)
        self.assertEqual(stripped, plain)                           # every count, total and warning as it was
        self.assertEqual(pool.table_rows(noted), pool.table_rows(plain))    # the saved table's rows too
        self.assertEqual((self.magic / "decks/casual/a.md").read_bytes(), before)
        # Never the Play-now list.
        self.deck("b", "B", "idea", "Deck\n1 Sol Ring\n", owned="Deck\n1 Llanowar Elves (FDN) 227\n")
        _, rows = self.check("casual/b", "owned")
        self.assertFalse(OWN_KEYS & set(rows[ELVES]))

    def test_with_prices_the_missing_copies_keep_their_listed_price(self):
        _, rows = self.rows("Deck\n3 Llanowar Elves (FDN) 227 *F*\n", (ELVES, "m19", "314", "nonfoil", 1),
                            prices=True)
        row = rows[ELVES]
        self.assertEqual((row["missing"], row["listed_printing"], row["listed_aud_missing"]), (2, "FDN 227 foil", 7.08))
        self.assertEqual((row["own_printing"], row["own_printing_label"]), ("other", "M19 314"))

    def test_a_card_the_printings_in_box_record_names_has_no_note(self):
        self.cards_csv("collection.csv", (ELVES, "m19", "314", "nonfoil", 1), ("Sol Ring", "ecc", "57", "nonfoil", 1))
        text = deck_md("A", "built", "Deck\n1 Llanowar Elves (FDN) 227\n1 Sol Ring (FDN) 227\n")
        recorded = text.replace("- **Status:** built\n",
                                "- **Status:** built\n- **Printings in box:** 1 Llanowar Elves (M19) 314\n")
        self.write("decks/casual/a.md", recorded)
        holder = next(d for d in pool.load_pool().in_use if d.id == "casual/a")
        self.assertEqual(dict(holder.recorded), {(ELVES, "m19", "314", "nonfoil"): 1})
        _, rows = self.check("casual/a")
        self.assertFalse(OWN_KEYS & set(rows[ELVES]))
        # Without the record the same deck's card is noted.
        self.write("decks/casual/a.md", text)
        _, rows = self.check("casual/a")
        self.assertEqual(note(rows[ELVES])["own_printing"], "other")

    def test_a_failed_count_leaves_the_rows_and_no_field_says_free(self):
        with mock.patch.object(pool, "printing_counts", side_effect=RuntimeError("no counts")):
            result, rows = self.rows("Deck\n1 Llanowar Elves (FDN) 227\n", (ELVES, "m19", "314", "nonfoil", 1))
        self.assertFalse(OWN_KEYS & set(rows[ELVES]))
        self.assertEqual((rows[ELVES]["owned"], rows[ELVES]["missing"]), (1, 0))
        _, rows = self.rows("Deck\n1 Llanowar Elves (FDN) 227\n", (ELVES, "m19", "314", "nonfoil", 1))
        self.assertNotIn("free", json.dumps(note(rows[ELVES])).lower())


class AnnotateTests(unittest.TestCase):
    def test_a_row_whose_printings_cannot_be_told_gets_none(self):
        line = decks.DeckLine(1, ELVES, "fdn", "227")
        rows = [{"name": ELVES, "owned": 1, "missing": 0}]
        listed_prices.annotate_owned(rows, {"Deck": [line]}, lambda n: n, {})
        self.assertEqual(rows, [{"name": ELVES, "owned": 1, "missing": 0}])


class DeckPageTests(ApiTestCase):
    def setUp(self):
        super().setUp()
        _write(self.box.root / "config.json", json.dumps(ROLES))
        _write(self.box.magic / "collection.csv",
               "name,set,collector_number,finish,quantity\nLlanowar Elves,m19,314,nonfoil,1\n")
        _write(self.box.magic / "decks/casual/printed.md",
               "# Printed\n\n- **Status:** building\n\n## Decklist\n\n```\nDeck\n1 Llanowar Elves (FDN) 227\n```\n")

    def view(self):
        with inventory.pinned():
            return api.deck_view("casual/printed", omit={"matchups"})

    def test_only_inventory_readers_get_the_note(self):
        for who in ("matt", "user1"):
            with self.subTest(viewer=who), access.viewing(who), access.using(None):
                row = self.view()["owned"]["rows"][0]
                self.assertEqual(note(row), {"own_printing": "other", "own_printing_label": "M19 314",
                                             "own_printing_more": 0, "own_printing_on_the_way": False})
        # A home deck made public, its inventory not: no owned rows, so no such fields anywhere.
        public = mock.patch.object(guard, "public_deck_spaces", return_value=frozenset({"home"}))
        with public, access.viewing("user2"), access.using({"profile": "user2", "email": "", "remote": True}):
            with mock.patch.object(pool, "printing_counts", side_effect=AssertionError("private counts read")):
                answer = self.view()
        self.assertNotIn("owned", answer)
        self.assertNotIn("own_printing", json.dumps(answer))


if __name__ == "__main__":
    unittest.main()
