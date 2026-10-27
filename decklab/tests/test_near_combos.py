"""Tests for combos one card away (E9-S25): decklab.lib.combos.near, near_for_deck and
availability, on the stats fixtures (fixtures/stats_cards.jsonl and the made-up
fixtures/stats_combos.json), with pools built here. No network, no database.

Run from the repo root: python -m unittest discover -s decklab/tests -t .
"""
import io
import json
import shutil
import tempfile
import unittest
from collections import Counter
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from decklab.lib import cards, combos, decks, pool

FIXTURES = Path(__file__).parent / "fixtures"
CARDS_FILE = FIXTURES / "stats_cards.jsonl"
TAGS_FILE = FIXTURES / "stats_tags.jsonl"
COMBOS_FILE = FIXTURES / "stats_combos.json"

_tmp = None


def setUpModule():
    global _tmp
    _tmp = Path(tempfile.mkdtemp())
    index = cards.build_index(CARDS_FILE, TAGS_FILE, {"default_cards": "2026-09-28"}, log=lambda *a: None)
    cards.write_index(index, _tmp / "index.json.gz")
    cards.load(_tmp / "index.json.gz")


def tearDownModule():
    cards._index = None
    cards._tag_cache.clear()
    shutil.rmtree(_tmp, ignore_errors=True)


def oracle(name):
    return cards.card(name)["oracle_id"]


# Finneas (green and white) leads. The list holds one piece of each fixture combo:
#   1-2   Serra Angel + Pelakka Wurm (G): infinite, standalone, floor 3     -> near
#   3-4   Wilson (must be the commander) + Grizzly Bears                   -> not: Wilson can't be added
#   5-6   Garruk's Companion + Changeling Outcast (B)                      -> not: outside the colours
#   7-8   Rampant Growth + Myriad Landscape (colourless): a lock, floor 1   -> near
#   9-10  Fireball + Shatterskull Smashing (R)                             -> not: outside the colours
#   11-12 Opt + Boon of the Wish-Giver (U)                                 -> not: outside the colours
#   13-14 Kitchen Finks + Worldspine Wurm (G): mass land denial, floor 4   -> near
DECK = """Commander
1 Finneas, Ace Archer

Deck
1 Serra Angel
1 Grizzly Bears
1 Garruk's Companion
1 Rampant Growth
1 Kitchen Finks
1 Fireball
1 Opt
40 Forest
"""


def sections(text=DECK):
    return decks.parse_decklist(text)


def make_pool(owned=(), coming=(), held=()):
    """A Pool: owned {name: copies} (coming's copies are added), coming {name: copies} on the way,
    held [(deck id, {name: copies})] built decks."""
    owned = Counter(dict(owned))
    on_the_way = {}
    for name, qty in dict(coming).items():
        owned[name] += qty
        on_the_way[name] = [("order 2026-10-27-shop", qty)]
    in_use = [pool.InUse(deck_id, deck_id, "built", Counter(cards_held)) for deck_id, cards_held in held]
    return pool.Pool(owned=owned, on_the_way=on_the_way, in_use=in_use)


class NearTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def ids(self, result):
        return [m["combo"]["id"] for m in result["matches"]]

    def test_exactly_one_piece_held(self):
        found = combos.near([], [oracle("Serra Angel")], lambda piece: True, COMBOS_FILE)
        self.assertEqual(self.ids(found), ["1-2"])
        match = found["matches"][0]
        self.assertEqual((match["held"]["name"], match["missing"]["name"]), ("Serra Angel", "Pelakka Wurm"))
        self.assertEqual(found["timestamp"], "2026-10-14T03:14:00.560664+00:00")
        # Both pieces held: a complete combo (find's), not a near one.
        self.assertEqual(self.ids(combos.near([], [oracle("Serra Angel"), oracle("Pelakka Wurm")],
                                              lambda piece: True, COMBOS_FILE)), [])

    def test_a_missing_piece_that_must_be_the_commander_is_never_suggested(self):
        self.assertEqual(self.ids(combos.near([], [oracle("Grizzly Bears")], lambda piece: True, COMBOS_FILE)), [])
        # The commander held: the other piece can join the 99.
        self.assertEqual(self.ids(combos.near([oracle("Wilson, Refined Grizzly")], [], lambda piece: True,
                                              COMBOS_FILE)), ["3-4"])
        # A piece that must be the commander, in the 99: held by nothing.
        self.assertEqual(self.ids(combos.near([], [oracle("Wilson, Refined Grizzly")], lambda piece: True,
                                              COMBOS_FILE)), [])

    def test_fits_decides_the_missing_piece(self):
        asked = []

        def fits(piece):
            asked.append(piece["name"])
            return piece["name"] != "Pelakka Wurm"
        self.assertEqual(self.ids(combos.near([], [oracle("Serra Angel"), oracle("Kitchen Finks")], fits,
                                              COMBOS_FILE)), ["13-14"])
        self.assertEqual(sorted(asked), ["Pelakka Wurm", "Worldspine Wurm"])

    def test_most_serious_first(self):
        held = [oracle(n) for n in ("Serra Angel", "Rampant Growth", "Kitchen Finks")]
        self.assertEqual(self.ids(combos.near([], held, lambda piece: True, COMBOS_FILE)), ["13-14", "1-2", "7-8"])

    def test_an_unreadable_list_is_an_error(self):
        with self.assertRaises(combos.ComboListError):
            combos.near([], [oracle("Serra Angel")], lambda piece: True, self.tmp / "missing.json")


class AvailabilityTests(unittest.TestCase):
    def test_states(self):
        p = make_pool(owned={"Pelakka Wurm": 1, "Myriad Landscape": 1, "Sol Ring": 2},
                      coming={"Worldspine Wurm": 1, "Sol Ring": 1},
                      held=[("commander/other", {"Myriad Landscape": 1, "Sol Ring": 2})])
        self.assertEqual(combos.availability("Pelakka Wurm", p),
                         {"state": "free", "free": 1, "on_the_way": 0, "in_use": 0})
        self.assertEqual(combos.availability("Worldspine Wurm", p),
                         {"state": "on_the_way", "free": 0, "on_the_way": 1, "in_use": 0})
        self.assertEqual(combos.availability("Myriad Landscape", p),
                         {"state": "in_use", "free": 0, "on_the_way": 0, "in_use": 1})
        # Two in storage, one coming, two in another deck: the one left is still on the way.
        self.assertEqual(combos.availability("Sol Ring", p),
                         {"state": "on_the_way", "free": 0, "on_the_way": 1, "in_use": 2})
        self.assertEqual(combos.availability("Grizzly Bears", p),
                         {"state": "buy", "free": 0, "on_the_way": 0, "in_use": 0})

    def test_the_decks_own_copies_are_free_for_it(self):
        p = make_pool(owned={"Myriad Landscape": 1}, held=[("commander/finneas", {"Myriad Landscape": 1})])
        self.assertEqual(combos.availability("Myriad Landscape", p, {"commander/finneas"})["state"], "free")


class NearForDeckTests(unittest.TestCase):
    def near(self, p=None, minimum=None, text=DECK, **kwargs):
        return combos.near_for_deck(sections(text), p, {"commander/finneas"}, minimum, COMBOS_FILE, **kwargs)

    def test_only_cards_in_the_commanders_colours(self):
        result = self.near()
        self.assertTrue(result["checked"])
        self.assertEqual(result["total"], 3)
        self.assertEqual([m["names"] for m in result["matches"]],
                         [["Kitchen Finks", "Worldspine Wurm"], ["Serra Angel", "Pelakka Wurm"],
                          ["Rampant Growth", "Myriad Landscape"]])
        first = result["matches"][0]
        self.assertEqual((first["held"], first["missing"], first["class"], first["floor"]),
                         ("Kitchen Finks", "Worldspine Wurm", "mass_land_denial", 4))
        self.assertEqual(first["url"], "https://commanderspellbook.com/combo/13-14/")
        self.assertEqual(result["list_date"], "2026-10-14T03:14:00.560664+00:00")
        # No pool: nothing about the inventory at all.
        self.assertTrue(all("availability" not in m for m in result["matches"]))
        json.dumps(result)

    def test_a_banned_card_is_never_suggested(self):
        data = json.loads(COMBOS_FILE.read_text(encoding="utf-8"))
        data["combos"].append({"id": "15-16", "url": "https://commanderspellbook.com/combo/15-16/",
                               "cards": [{"oracle_id": oracle("Llanowar Elves"), "name": "Llanowar Elves",
                                          "must_be_commander": False},
                                         {"oracle_id": oracle("Primeval Titan"), "name": "Primeval Titan",
                                          "must_be_commander": False}],
                               "results": ["Infinite mana"], "class": "infinite", "standalone": True})
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        (tmp / "combos.json").write_text(json.dumps(data), encoding="utf-8")
        result = combos.near_for_deck(sections(DECK + "1 Llanowar Elves\n"), path=tmp / "combos.json")
        self.assertNotIn("Primeval Titan", [m["missing"] for m in result["matches"]])
        self.assertEqual(result["total"], 3)

    def test_bracket(self):
        raised = {m["missing"]: m["raises_to"] for m in self.near(minimum=1)["matches"]}
        self.assertEqual(raised, {"Worldspine Wurm": 4, "Pelakka Wurm": 3, "Myriad Landscape": None})
        raised = {m["missing"]: m["raises_to"] for m in self.near(minimum=3)["matches"]}
        self.assertEqual(raised, {"Worldspine Wurm": 4, "Pelakka Wurm": None, "Myriad Landscape": None})
        self.assertTrue(all(m["raises_to"] is None for m in self.near()["matches"]))

    def test_with_a_pool_free_cards_come_first(self):
        p = make_pool(owned={"Pelakka Wurm": 1, "Myriad Landscape": 1}, coming={"Worldspine Wurm": 1},
                      held=[("commander/other", {"Myriad Landscape": 1})])
        result = self.near(p)
        self.assertEqual([(m["missing"], m["availability"]["state"]) for m in result["matches"]],
                         [("Pelakka Wurm", "free"), ("Worldspine Wurm", "on_the_way"),
                          ("Myriad Landscape", "in_use")])
        # Nothing owned: all to buy, most serious first.
        result = self.near(make_pool())
        self.assertEqual([(m["missing"], m["availability"]["state"]) for m in result["matches"]],
                         [("Worldspine Wurm", "buy"), ("Pelakka Wurm", "buy"), ("Myriad Landscape", "buy")])

    def test_limit_keeps_the_total(self):
        result = self.near(make_pool(owned={"Myriad Landscape": 1}), limit=1)
        self.assertEqual((result["total"], [m["missing"] for m in result["matches"]]), (3, ["Myriad Landscape"]))

    def test_no_commander_or_no_list_is_not_checked(self):
        result = self.near(text="Deck\n1 Serra Angel\n")
        self.assertFalse(result["checked"])
        self.assertIn("no commander", result["reason"])
        result = combos.near_for_deck(sections(), path=Path(tempfile.gettempdir()) / "no-such-combos.json")
        self.assertFalse(result["checked"])
        self.assertIn("combo list", result["reason"])


class CommandLineTests(unittest.TestCase):
    def test_prints_each_combo_with_its_availability_and_bracket(self):
        p = make_pool(owned={"Pelakka Wurm": 1})
        result = combos.near_for_deck(sections(), p, (), 1, COMBOS_FILE)
        out = io.StringIO()
        with redirect_stdout(out):
            combos._print_near("commander/finneas", result, 2)
        text = out.getvalue()
        self.assertIn("commander/finneas: 3 two-card combos one card away (Commander Spellbook's two-card "
                      "combos, list of 2026-10-14)", text)
        self.assertIn("[free]", text)
        self.assertIn("add Pelakka Wurm (with Serra Angel): Infinite damage, Infinite lifegain; raises the "
                      "minimum bracket to 3, above the target 2", text)
        self.assertIn("[to buy]", text)
        self.assertIn("https://commanderspellbook.com/combo/7-8/", text)

    def test_a_deck_that_isnt_commander_is_refused(self):
        summary = {"id": "casual/elves", "kind": "casual"}
        out = io.StringIO()
        with mock.patch.object(decks, "find_summary", return_value=summary), redirect_stdout(out):
            self.assertEqual(combos.main(["near", "casual/elves"]), 1)
        self.assertIn("isn't a Commander deck", out.getvalue())


if __name__ == "__main__":
    unittest.main()
