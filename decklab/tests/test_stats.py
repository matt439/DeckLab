"""Tests for decklab.lib.stats. No network: everything runs on fixture files.

fixtures/stats_cards.jsonl holds 43 real Scryfall cards trimmed to the fields
the index uses: the five basics, mana creatures and rocks, land ramp, a
cycler, modal, adventure and split cards, X, gold and hybrid costs, a
changeling, the "any number" and "up to seven" cards, a banned card, a
not_legal Un-card, Lutri (banned only as a companion), a Game Changer,
lands that enter tapped, can enter untapped, or search for a basic (free,
or for {2}: Myriad Landscape), and two legendary Spacecraft (The Seriema has
power and toughness, The Eternity Elevator doesn't). 19 more are for the
Commander pairing rules (comp-rules 702.124): plain partner, partner with
[name], partner—Friends forever and partner—Survivors, Choose a Background
with a Background, Doctor's companion with a Doctor and with a Time Lord who
isn't one, plus Grist, the Hunger Tide (a creature card off the battlefield)
and Once More with Feeling (only one copy in a deck).
fixtures/stats_tags.jsonl is a made-up tag tree that uses the real slugs
(the role tags, mass-land-denial and extra-turn).

The expected numbers are worked out by hand in the comments, from Karsten's
formulas and tables as lib/stats/constants.py quotes them.

Run from the repo root: python -m unittest discover -s decklab/tests -t .
"""
import importlib
import io
import json
import pkgutil
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from decklab.lib import cards, decks, stats
from decklab.lib.stats import commander as stats_commander     # where TAG_FILE, COMBO_FILE and OFFICIAL_FILE are read

FIXTURES = Path(__file__).parent / "fixtures"
CARDS_FILE = FIXTURES / "stats_cards.jsonl"
TAGS_FILE = FIXTURES / "stats_tags.jsonl"
COMBOS_FILE = FIXTURES / "stats_combos.json"     # a made-up two-card combo list of fixture cards
OFFICIAL_FILE = FIXTURES / "stats_official_lists.json"  # Wizards' latest Commander announcement, as checked

_tmp = None
_patches = []


def setUpModule():
    global _tmp
    _tmp = Path(tempfile.mkdtemp())
    index = cards.build_index(CARDS_FILE, TAGS_FILE, {"default_cards": "2026-09-28"}, log=lambda *a: None)
    cards.write_index(index, _tmp / "index.json.gz")
    cards.load(_tmp / "index.json.gz")
    _patches[:] = [mock.patch.object(stats_commander, "TAG_FILE", TAGS_FILE),
                   mock.patch.object(stats_commander, "COMBO_FILE", COMBOS_FILE),
                   mock.patch.object(stats_commander, "OFFICIAL_FILE", OFFICIAL_FILE)]
    for patch in _patches:
        patch.start()


def tearDownModule():
    for patch in _patches:
        patch.stop()
    cards._index = None
    cards._tag_cache.clear()
    shutil.rmtree(_tmp, ignore_errors=True)


def run(text, kind="constructed"):
    """deck_stats for a decklist written as text (sections as in a deck file)."""
    return stats.deck_stats(decks.parse_decklist(text), kind)


def by(items, key, value):
    matches = [item for item in items if item[key] == value]
    assert len(matches) == 1, (key, value, items)
    return matches[0]


def names(card_list):
    return {c["name"]: c["qty"] for c in card_list}


def check(result, colours, cost, gold=False):
    """The colour check for colours and cost (Karsten's C notation)."""
    summary = by(result["colours"]["colours"], "colours", colours)
    matches = [c for c in summary["checks"] if c["cost"] == cost and c["gold"] == gold]
    assert len(matches) == 1, (colours, cost, summary["checks"])
    return matches[0]


def walk(value):
    """Every value inside a result, to check it's plain JSON."""
    yield value
    if isinstance(value, dict):
        for k, v in value.items():
            yield k
            yield from walk(v)
    elif isinstance(value, list):
        for v in value:
            yield from walk(v)


# A 20-card list covering the curve: 13 nonland cards with mana values
# 4x1 + 2x1 + 7 + 11 + 15 + 1 + 3 + 4 + 3 = 50, so the average is 50/13.
CURVE_DECK = """Deck
4 Llanowar Elves
2 Opt
1 Pelakka Wurm
1 Worldspine Wurm
1 Mox Lotus
1 Fireball
1 Bonecrusher Giant // Stomp
1 Fire // Ice
1 Kazandu Mammoth
7 Forest

Sideboard
3 Serra Angel
"""


class TestCurve(unittest.TestCase):
    def setUp(self):
        self.result = run(CURVE_DECK)
        self.curve = self.result["curve"]

    def test_buckets_split_creatures_and_noncreatures(self):
        buckets = {b["mv"]: (b["creatures"], b["noncreatures"]) for b in self.curve["buckets"]}
        self.assertEqual(buckets, {"0": (0, 0), "1": (4, 3), "2": (0, 0), "3": (2, 0), "4": (0, 1),
                                   "5": (0, 0), "6": (0, 0), "7+": (2, 1)})
        seven = by(self.curve["buckets"], "mv", "7+")
        self.assertEqual(names(seven["cards"]), {"Mox Lotus": 1, "Pelakka Wurm": 1, "Worldspine Wurm": 1})
        self.assertEqual((self.curve["nonland"], self.curve["creatures"], self.curve["noncreatures"]), (13, 8, 5))

    def test_average_mana_value_is_karstens(self):
        self.assertEqual(self.curve["average_mv"], round(50 / 13, 2))
        self.assertEqual(self.result["lands"]["average_mv"], round(50 / 13, 2))
        self.assertIn("Karsten", self.curve["average_mv_definition"])

    def test_multi_face_cards_use_the_front_face(self):
        three = names(by(self.curve["buckets"], "mv", "3")["cards"])
        # The adventure is a 3-mana creature; the modal card is its 3-mana front, not a land.
        self.assertEqual(three, {"Bonecrusher Giant // Stomp": 1, "Kazandu Mammoth // Kazandu Valley": 1})
        # A split card's mana value is both halves added.
        self.assertEqual(names(by(self.curve["buckets"], "mv", "4")["cards"]), {"Fire // Ice": 1})
        types = {t["type"]: t["count"] for t in self.result["types"]}
        self.assertEqual(types["creature"], 8)      # Stomp's Instant type isn't counted
        self.assertEqual(types["instant"], 3)       # 2 Opt + Fire // Ice
        self.assertEqual(types["land"], 7)          # the modal card isn't a land

    def test_x_spells(self):
        self.assertEqual(self.curve["x_spells"], {"count": 1, "cards": [{"name": "Fireball", "qty": 1}]})

    def test_sideboard_is_left_out(self):
        self.assertEqual(self.result["counts"], {"commander": 0, "companion": 0, "deck": 20,
                                                 "sideboard": 3, "main": 20})
        self.assertEqual(self.result["sideboard"]["count"], 3)
        self.assertEqual(self.result["sideboard"]["cards"], [{"name": "Serra Angel", "qty": 3}])
        self.assertNotIn("Flying", [k["keyword"] for k in self.result["keywords"]])
        self.assertNotIn("Angel", [t["type"] for t in self.result["tribes"]["types"]])
        # Its spells are still checked against the main deck's sources.
        self.assertEqual([(c["colours"], c["cost"]) for c in self.result["sideboard"]["checks"]], [("W", "3CC")])

    def test_twenty_cards_have_no_colour_table(self):
        colours = self.result["colours"]
        self.assertIsNone(colours["table"])
        self.assertIsNone(colours["ok"])
        self.assertIn("40 cards", colours["table_note"])
        green = by(colours["colours"], "colours", "G")
        self.assertIsNone(green["ok"])
        self.assertTrue(all(c["needed"] is None and c["ok"] is None for c in green["checks"]))

    def test_plain_json(self):
        json.dumps(self.result, allow_nan=False)
        for value in walk(self.result):
            self.assertIsInstance(value, (dict, list, str, int, float, bool, type(None)))


class TestResolving(unittest.TestCase):
    def test_basic_land_without_a_set(self):
        result = run("Deck\n10 Forest\n1 Forest (FDN) 291\n9 Grizzly Bears\n")
        self.assertEqual(result["lands"]["lands"], 11)
        self.assertEqual(result["unresolved"], [])
        self.assertEqual(by(result["types"], "type", "land")["cards"], [{"name": "Forest", "qty": 11}])

    def test_unresolved_names_count_towards_size_only(self):
        result = run("Deck\n8 Forest\n10 Grizzly Bears\n2 Not A Real Card\n")
        self.assertEqual(result["unresolved"], [{"name": "Not A Real Card", "qty": 2, "section": "Deck"}])
        self.assertEqual(result["counts"]["main"], 20)
        self.assertEqual(result["curve"]["nonland"], 10)
        self.assertTrue(any("Not A Real Card" in w for w in result["warnings"]))

    def test_names_resolve_loosely(self):
        result = run("Deck\n8 forest\n12 fire\n")
        self.assertEqual(result["unresolved"], [])
        self.assertEqual(names(by(result["types"], "type", "instant")["cards"]), {"Fire // Ice": 12})

    def test_unknown_kind(self):
        with self.assertRaises(ValueError):
            stats.deck_stats({}, "casual")


class TestLandCount(unittest.TestCase):
    def test_sixty_card_formula(self):
        # Nonland: 4 Llanowar Elves (1), 4 Rampant Growth (2), 4 Garruk's Companion (2),
        # 4 Kitchen Finks (3), 20 Grizzly Bears (2): 72 / 36 = 2.0 average.
        # Cheap: 4 Llanowar Elves ("add ") + 4 Rampant Growth (search ... basic) = 8.
        # 19.59 + 1.90 x 2.0 - 0.28 x 8 = 21.15; 24 lands is 2.85 over (more than 2 x 1): high.
        result = run("Deck\n24 Forest\n4 Llanowar Elves\n4 Rampant Growth\n4 Garruk's Companion\n"
                     "4 Kitchen Finks\n20 Grizzly Bears\n")
        lands = result["lands"]
        self.assertEqual((lands["lands"], lands["effective"], lands["average_mv"]), (24, 24.0, 2.0))
        self.assertEqual(lands["cheap"], {"count": 8, "draw": [],
                                          "ramp": [{"name": "Llanowar Elves", "qty": 4},
                                                   {"name": "Rampant Growth", "qty": 4}]})
        self.assertEqual(lands["recommended"], 21.15)
        self.assertEqual((lands["delta"], lands["band"], lands["verdict"]), (2.85, 1.0, "high"))
        self.assertTrue(lands["formula"]["published"])
        self.assertEqual(lands["formula"]["worked"],
                         "(19.59 + 1.9 x 2.00 + 0.27 x 0) - 0.28 x 8 = 21.15")
        self.assertEqual(lands["mana_creatures"], [{"name": "Llanowar Elves", "qty": 4, "mv": 1.0,
                                                    "produces": "G", "cheap": True}])
        self.assertIn("24-25", lands["rule_of_thumb"]["text"])

    def test_forty_cards_use_the_scaled_formula(self):
        # (40/60) x (19.59 + 1.90 x 2) = 15.593; 17 lands is 1.41 over: slightly high.
        lands = run("Deck\n17 Forest\n23 Grizzly Bears\n")["lands"]
        self.assertEqual((lands["recommended"], lands["verdict"]), (15.59, "slightly high"))
        self.assertFalse(lands["formula"]["published"])
        self.assertIn("(40/60)", lands["formula"]["text"])

    def test_twenty_cards(self):
        # (20/60) x 23.39 = 7.797; 8 lands: ok.
        lands = run("Deck\n8 Forest\n12 Grizzly Bears\n")["lands"]
        self.assertEqual((lands["recommended"], lands["verdict"]), (7.8, "ok"))
        self.assertIn("8 lands", lands["rule_of_thumb"]["text"])

    def test_modal_cards_count_as_part_of_a_land(self):
        # Kazandu Valley always enters tapped (0.38); Shatterskull can enter untapped (0.74).
        lands = run("Deck\n20 Forest\n2 Kazandu Mammoth\n1 Shatterskull Smashing\n37 Grizzly Bears\n")["lands"]
        self.assertEqual((lands["lands"], lands["mdfc"]["tapped"], lands["mdfc"]["untapped"]), (20, 2, 1))
        self.assertEqual(lands["effective"], round(20 + 2 * 0.38 + 0.74, 2))
        self.assertEqual({c["name"]: c["land_enters"] for c in lands["mdfc"]["cards"]},
                         {"Kazandu Mammoth // Kazandu Valley": "tapped",
                          "Shatterskull Smashing // Shatterskull, the Hammer Pass": "untapped"})

    def test_cheap_card_rules(self):
        lands = run("Deck\n24 Forest\n2 Opt\n1 Boon of the Wish-Giver\n1 Arcane Signet\n1 Sol Ring\n"
                    "1 Kazandu Mammoth\n1 Kitchen Finks\n29 Grizzly Bears\n")["lands"]
        # Opt draws; Boon (mana value 6) cycles for {1}; the rocks "add"; the modal card and
        # a 3-mana creature don't count.
        self.assertEqual(names(lands["cheap"]["draw"]), {"Opt": 2, "Boon of the Wish-Giver": 1})
        self.assertEqual(names(lands["cheap"]["ramp"]), {"Arcane Signet": 1, "Sol Ring": 1})
        self.assertEqual(lands["cheap"]["count"], 5)
        self.assertEqual([r["name"] for r in lands["mana_rocks"]], ["Arcane Signet", "Sol Ring"])

    def test_nearest_guidance_size(self):
        result = run("Deck\n25 Forest\n36 Grizzly Bears\n")
        self.assertEqual(result["guidance"]["size"], 60)
        self.assertIn("61 cards", result["guidance"]["note"])
        self.assertIn(result["guidance"]["note"], result["warnings"])
        # 30 is as close to 20 as to 40: the larger wins.
        self.assertEqual(run("Deck\n12 Forest\n18 Grizzly Bears\n")["guidance"]["size"], 40)
        self.assertIsNone(run("Deck\n8 Forest\n12 Grizzly Bears\n")["guidance"]["note"])

    def test_commander_formula_and_floor(self):
        # 31.42 + 3.13 x 2.0 = 37.68 (the commander stays out of the average).
        deck = "Commander\n1 Finneas, Ace Archer\n\nDeck\n{lands} Forest\n{bears} Grizzly Bears\n"
        lands = run(deck.format(lands=38, bears=61), "commander")["lands"]
        self.assertEqual((lands["recommended"], lands["band"], lands["verdict"]), (37.68, 1.65, "ok"))
        self.assertEqual(lands["floor"], 37)
        self.assertIn("36-38", lands["rule_of_thumb"]["text"])
        # 36 lands is 1.68 under: "slightly low" by the band, but under 37 is always low.
        lands = run(deck.format(lands=36, bears=63), "commander")["lands"]
        self.assertEqual(lands["verdict"], "low")
        self.assertIn("37", lands["verdict_text"])

    def test_rules_of_thumb_cite_where_each_figure_is(self):
        # Karsten's 24-25 / 26 is in his Commander article, not the Wizards one; the Command
        # Zone post gives no land count, so it isn't cited.
        sixty = run("Deck\n24 Forest\n36 Grizzly Bears\n")["lands"]["rule_of_thumb"]
        self.assertEqual(sixty["sources"], ["wizards-mana", "karsten-commander"])
        hundred = run("Commander\n1 Finneas, Ace Archer\n\nDeck\n38 Forest\n61 Grizzly Bears\n",
                      "commander")["lands"]["rule_of_thumb"]
        self.assertEqual(hundred["sources"], ["edhrec-lands", "karsten-commander"])
        self.assertNotIn("Command Zone", hundred["text"])
        self.assertNotIn("command-zone", stats.SOURCES)
        for rule in stats.LAND_RULES_OF_THUMB.values():
            self.assertTrue(rule["sources"] and set(rule["sources"]) <= set(stats.SOURCES), rule)

    def test_companion_adds_to_the_formula(self):
        # (19.59 + 1.90 x 2 + 0.27 x 1) = 23.66
        lands = run("Companion\n1 Lutri, the Spellchaser\n\nDeck\n24 Forest\n36 Grizzly Bears\n")["lands"]
        self.assertEqual((lands["companions"], lands["recommended"]), (1, 23.66))


class TestColours(unittest.TestCase):
    def test_hand_checked_mono_colour_requirement(self):
        # Garruk's Companion GG is "CC by turn 2": 21 sources in 60 cards; Grizzly Bears 1G is
        # "1C by turn 2": 13. 12 Forests make 12 green sources: both short, CC the hardest.
        result = run("Deck\n12 Forest\n12 Mountain\n4 Garruk's Companion\n32 Grizzly Bears\n")
        green = by(result["colours"]["colours"], "colours", "G")
        self.assertFalse(green["ok"])
        hardest = green["hardest"]
        self.assertEqual((hardest["cost"], hardest["cost_in_colours"], hardest["turn"], hardest["pips"]),
                         ("CC", "GG", 2, 2))
        self.assertEqual((hardest["needed"], hardest["have"], hardest["margin"]), (21, 12.0, -9.0))
        self.assertEqual(hardest["cards"], [{"name": "Garruk's Companion", "qty": 4}])
        bears = check(result, "G", "1C")
        self.assertEqual((bears["needed"], bears["ok"]), (13, False))
        self.assertEqual([c["cost"] for c in green["short"]], ["CC", "1C"])
        self.assertFalse(result["colours"]["ok"])
        self.assertEqual(result["colours"]["table"], 60)

    def test_gold_card_karstens_teferi_example(self):
        # Karsten: Teferi, Time Raveler (1WU) in 60 cards needs 13 white, 13 blue and
        # 19 white-or-blue sources (2W -> 12, 2U -> 12, 1CC -> 18, each + 1).
        result = run("Deck\n10 Plains\n10 Island\n4 Hallowed Fountain\n4 Teferi, Time Raveler\n"
                     "32 Mox Lotus\n")
        white, blue, both = check(result, "W", "2C", True), check(result, "U", "2C", True), \
            check(result, "WU", "1CC", True)
        self.assertEqual((white["needed"], white["have"], white["ok"]), (13, 14.0, True))
        self.assertEqual((blue["needed"], blue["have"]), (13, 14.0))
        self.assertEqual((both["needed"], both["have"], both["ok"]), (19, 24.0, True))
        # The colours together show Teferi's printed cost, not hybrid {W/U} symbols, and
        # every gold check says where its +1 comes from.
        self.assertEqual((white["cost_in_colours"], both["cost_in_colours"]), ("2W", "{1}{W}{U}"))
        self.assertIn("gold card: Karsten adds 1 to the table's 12", white["notes"])
        self.assertTrue(any("either colour" in n and "adds 1 to the table's 18" in n for n in both["notes"]))
        h = stats.headline(run("Deck\n10 Plains\n10 Island\n4 Teferi, Time Raveler\n36 Mox Lotus\n"))
        self.assertIn("W 2C (gold card, +1): 10 of 13", h["colour_short"])

    def test_gold_card_splash_gets_no_extra(self):
        # Every land makes white, so only blue is in doubt: Teferi is checked as a 2U card.
        result = run("Deck\n20 Plains\n4 Hallowed Fountain\n4 Teferi, Time Raveler\n32 Mox Lotus\n")
        blue = check(result, "U", "2C")
        self.assertEqual((blue["needed"], blue["have"], blue["ok"]), (12, 4.0, False))
        self.assertNotIn("WU", [s["colours"] for s in result["colours"]["colours"]])

    def test_hybrid_needs_either_colour(self):
        # Kitchen Finks {1}{G/W}{G/W}: "1CC by turn 3" from white or green sources, 18 needed.
        result = run("Deck\n12 Forest\n12 Plains\n4 Kitchen Finks\n32 Mox Lotus\n")
        finks = check(result, "WG", "1CC")
        self.assertEqual((finks["needed"], finks["have"], finks["ok"]), (18, 24.0, True))
        self.assertEqual([s["colours"] for s in result["colours"]["colours"]], ["WG"])
        self.assertEqual(finks["cost_in_colours"], "1{W/G}{W/G}")
        self.assertIn("hybrid symbols: sources of either colour count", finks["notes"])

    def test_partial_sources(self):
        # 14 Forest, 2 Plains, 4 Uncharted Haven (enters tapped), 2 Evolving Wilds (finds a
        # tapped Forest or Plains), 2 Kazandu Mammoth (0.8, tapped), 4 Llanowar Elves (0.5 from
        # turn 2), 2 Arcane Signet (0.75 from turn 3).
        result = run("Deck\n14 Forest\n2 Plains\n4 Uncharted Haven\n2 Evolving Wilds\n"
                     "4 Llanowar Elves\n2 Kazandu Mammoth\n2 Arcane Signet\n4 Garruk's Companion\n"
                     "4 Pelakka Wurm\n1 Serra Angel\n21 Mox Lotus\n")
        # Turn 1 (Llanowar Elves, needs 14): only the untapped Forests.
        self.assertEqual(check(result, "G", "C")["have"], 14.0)
        # Turn 2 (GG): 14 + 4 Haven + 2 Wilds + 2 x 0.8 + 4 x 0.5 = 23.6.
        self.assertEqual(check(result, "G", "CC")["have"], 23.6)
        # Turn 7 (4GGG): 21.6 + 2 + 2 x 0.75 = 25.1.
        self.assertEqual(check(result, "G", "4CCC")["have"], 25.1)
        # Serra Angel 3WW (15 needed): 2 Plains + 4 Haven + 2 Wilds + 1.5 = 9.5.
        angel = check(result, "W", "3CC")
        self.assertEqual((angel["needed"], angel["have"], angel["have_lands"]), (15, 9.5, 8.0))
        sources = {s["name"]: s for s in result["colours"]["sources"]}
        self.assertEqual((sources["Uncharted Haven"]["kind"], sources["Uncharted Haven"]["turn_one"]),
                         ("land", False))
        self.assertEqual((sources["Evolving Wilds"]["kind"], sources["Evolving Wilds"]["colours"],
                          sources["Evolving Wilds"]["turn_one"]), ("fetch", "WG", False))
        self.assertEqual((sources["Kazandu Mammoth // Kazandu Valley"]["kind"],
                          sources["Kazandu Mammoth // Kazandu Valley"]["weight"]), ("mdfc", 0.8))
        self.assertEqual((sources["Llanowar Elves"]["from_turn"], sources["Llanowar Elves"]["counted"]), (2, True))
        self.assertEqual((sources["Arcane Signet"]["kind"], sources["Arcane Signet"]["from_turn"]), ("rock", 3))

    def test_a_land_whose_search_costs_mana_finds_colours_late(self):
        # Myriad Landscape makes {C} and enters tapped; its search costs {2}, which takes two
        # other lands, so it's used on turn 3 at the earliest and its tapped basics help from
        # turn 4. Hare Apparent (1W, turn 2): 16 Plains, not 20. Serra Angel (3WW, turn 5): 20.
        result = run("Deck\n16 Plains\n4 Myriad Landscape\n4 Hare Apparent\n4 Serra Angel\n32 Mox Lotus\n")
        hare, angel = check(result, "W", "1C"), check(result, "W", "3CC")
        self.assertEqual((hare["have"], hare["have_lands"]), (16.0, 16.0))
        self.assertEqual((angel["have"], angel["have_lands"]), (20.0, 20.0))
        myriad = by(result["colours"]["sources"], "name", "Myriad Landscape")
        self.assertEqual((myriad["kind"], myriad["colours"], myriad["weight"], myriad["turn_one"],
                          myriad["found_from_turn"]), ("fetch", "WC", 1.0, False, 4))
        self.assertIn("{2}", myriad["note"])
        self.assertEqual(stats.search_cost("{2}, {t}, sacrifice this land: search your library for a "
                                            "basic land card"), (2, "{2}"))
        # A search that costs no mana is still a full source at once (Karsten's rule).
        wilds = run("Deck\n16 Plains\n4 Evolving Wilds\n4 Hare Apparent\n36 Mox Lotus\n")
        self.assertEqual(check(wilds, "W", "1C")["have"], 20.0)
        self.assertIsNone(by(wilds["colours"]["sources"], "name", "Evolving Wilds")["found_from_turn"])
        self.assertEqual(stats.search_cost("{t}, sacrifice this land: search your library for a basic "
                                            "land card"), (0, ""))

    def test_lands_untapped_on_turn_one(self):
        untapped = stats.untapped_on_turn_one
        self.assertTrue(untapped("({T}: Add {W} or {U}.)\nAs this land enters, you may pay 2 life. "
                                 "If you don't, it enters tapped."))                    # shock land
        self.assertTrue(untapped("This land enters tapped unless you control two or fewer other lands."))
        self.assertTrue(untapped("This land enters tapped unless it's your first, second, or third "
                                 "turn of the game."))
        self.assertFalse(untapped("This land enters tapped unless you control a Forest or a Plains."))
        self.assertFalse(untapped("This land enters tapped unless you control two or more basic lands."))
        bond = "This land enters tapped unless you have two or more opponents."
        self.assertFalse(untapped(bond))
        self.assertTrue(untapped(bond, multiplayer=True))       # Commander's table assumes a pod
        # In a deck: the check lands can't be untapped on turn 1, the shock land can.
        result = run("Deck\n12 Forest\n4 Sunpetal Grove\n4 Cinder Glade\n4 Hallowed Fountain\n"
                     "4 Llanowar Elves\n32 Mox Lotus\n")
        turn_one = {s["name"]: s["turn_one"] for s in result["colours"]["sources"]}
        self.assertEqual((turn_one["Sunpetal Grove"], turn_one["Cinder Glade"], turn_one["Hallowed Fountain"]),
                         (False, False, True))
        self.assertEqual(check(result, "G", "C")["have"], 12.0)

    def test_mana_creature_the_deck_cant_cast_isnt_counted(self):
        # 13 Forests: Llanowar Elves needs 14 untapped green sources on turn 1.
        result = run("Deck\n13 Forest\n11 Mountain\n4 Llanowar Elves\n4 Garruk's Companion\n28 Mox Lotus\n")
        elves = by(result["colours"]["sources"], "name", "Llanowar Elves")
        self.assertFalse(elves["counted"])
        self.assertEqual(check(result, "G", "CC")["have"], 13.0)

    def test_land_ramp_and_cantrips(self):
        # 16 Forest, 4 Rampant Growth (castable: 16 >= 13; 0.75 from turn 3), 4 Opt (cast with
        # 8 Islands? no: needs 14 untapped blue, so it's not counted).
        result = run("Deck\n16 Forest\n8 Island\n4 Rampant Growth\n4 Opt\n4 Pelakka Wurm\n24 Mox Lotus\n")
        sources = {s["name"]: s for s in result["colours"]["sources"]}
        self.assertEqual((sources["Rampant Growth"]["kind"], sources["Rampant Growth"]["from_turn"],
                          sources["Rampant Growth"]["colours"]), ("ramp", 3, "UG"))
        self.assertFalse(sources["Opt"]["counted"])
        # Pelakka Wurm 4GGG: 16 + 4 x 0.75 = 19.
        self.assertEqual(check(result, "G", "4CCC")["have"], 19.0)

    def test_cantrip_digs_for_every_colour(self):
        # 16 Islands cast Opt (needs 14). Each Opt adds (8 Forests / 60) = 0.13 -> 0 quarters of
        # green, and (16 / 60) = 0.27 -> 0.25 of blue, for spells from turn 2.
        result = run("Deck\n16 Island\n8 Forest\n4 Opt\n4 Garruk's Companion\n28 Mox Lotus\n")
        self.assertEqual(check(result, "G", "CC")["have"], 8.0)
        self.assertEqual(check(result, "U", "C")["have"], 16.0)      # turn 1: no digging yet
        self.assertTrue(by(result["colours"]["sources"], "name", "Opt")["counted"])

    def test_x_and_turns_past_seven(self):
        result = run("Deck\n24 Mountain\n12 Forest\n4 Fireball\n1 Pelakka Wurm\n1 Worldspine Wurm\n18 Mox Lotus\n")
        fireball = check(result, "R", "1C")       # X counted as 1: {1}{R} by turn 2 = 13
        self.assertEqual((fireball["turn"], fireball["needed"]), (2, 13))
        self.assertIn("X counted as 1", fireball["notes"])
        wurms = check(result, "G", "4CCC")        # 11 mana checked on the 7-mana row: 16
        self.assertEqual(names(wurms["cards"]), {"Pelakka Wurm": 1, "Worldspine Wurm": 1})
        self.assertEqual(wurms["needed"], 16)
        self.assertTrue(any("turn 11" in note for note in wurms["notes"]))

    def test_multi_face_requirements(self):
        result = run("Deck\n12 Mountain\n12 Island\n2 Bonecrusher Giant\n2 Fire // Ice\n"
                     "2 Shatterskull Smashing\n30 Mox Lotus\n")
        red = by(result["colours"]["colours"], "colours", "R")
        costs = {(c["cost"], c["turn"]): names(c["cards"]) for c in red["checks"]}
        self.assertEqual(costs, {
            ("2C", 3): {"Bonecrusher Giant // Stomp (Bonecrusher Giant)": 2},
            ("1C", 2): {"Bonecrusher Giant // Stomp (Stomp)": 2, "Fire // Ice (Fire)": 2},
            ("1CC", 3): {"Shatterskull Smashing // Shatterskull, the Hammer Pass": 2}})   # X as 1
        self.assertEqual(names(check(result, "U", "1C")["cards"]), {"Fire // Ice (Ice)": 2})
        # Shatterskull's land counts as a full red source that can enter untapped.
        smash = by(result["colours"]["sources"], "name", "Shatterskull Smashing // Shatterskull, the Hammer Pass")
        self.assertEqual((smash["kind"], smash["weight"], smash["turn_one"]), ("mdfc", 1.0, True))

    def test_commander_uses_the_99_card_table(self):
        result = run("Commander\n1 Finneas, Ace Archer\n\nDeck\n20 Forest\n16 Plains\n63 Mox Lotus\n",
                     "commander")
        self.assertEqual(result["colours"]["table"], 99)
        # Finneas {G}{W}, a gold 2-drop: 1C by turn 2 is 19, +1.
        self.assertEqual(check(result, "G", "1C", True)["needed"], 20)
        self.assertIn("multiplayer", result["colours"]["land_note"])
        self.assertIn("41 lands", result["colours"]["land_note"])


class TestTypesRolesTribes(unittest.TestCase):
    def setUp(self):
        self.result = run("Deck\n4 Llanowar Elves\n2 Changeling Outcast\n3 Serra Angel\n1 Fire // Ice\n"
                          "1 Kitchen Finks\n1 Bonecrusher Giant\n1 Fireball\n1 Sol Ring\n1 Opt\n5 Forest\n")

    def test_types(self):
        types = {t["type"]: t["count"] for t in self.result["types"]}
        self.assertEqual(types, {"creature": 11, "instant": 2, "sorcery": 1, "artifact": 1,
                                 "enchantment": 0, "planeswalker": 0, "battle": 0, "land": 5})

    def test_roles(self):
        roles = {r["role"]: names(r["cards"]) for r in self.result["roles"]}
        self.assertEqual(roles["removal"], {"Bonecrusher Giant // Stomp": 1, "Fire // Ice": 1})
        self.assertEqual(roles["burn"], {"Bonecrusher Giant // Stomp": 1, "Fire // Ice": 1, "Fireball": 1})
        self.assertEqual(roles["ramp"], {"Llanowar Elves": 4, "Sol Ring": 1})
        self.assertEqual(roles["draw"], {"Fire // Ice": 1, "Opt": 1})
        self.assertEqual(roles["lifegain"], {"Kitchen Finks": 1})
        self.assertEqual(by(self.result["roles"], "role", "counterspell")["count"], 0)
        self.assertEqual([r["role"] for r in self.result["roles"]], list(cards.ROLES))

    def test_tribes_and_changelings(self):
        tribes = {t["type"]: t["count"] for t in self.result["tribes"]["types"]}
        self.assertEqual(tribes, {"Elf": 4, "Druid": 4, "Angel": 3, "Shapeshifter": 2, "Ouphe": 1, "Giant": 1})
        self.assertEqual(self.result["tribes"]["types"][0]["type"], "Druid")   # 4 each: by name
        changelings = self.result["tribes"]["changelings"]
        self.assertEqual((changelings["count"], changelings["cards"]),
                         (2, [{"name": "Changeling Outcast", "qty": 2}]))

    def test_keywords(self):
        keywords = {k["keyword"]: k["count"] for k in self.result["keywords"]}
        self.assertEqual(keywords, {"Flying": 3, "Vigilance": 3, "Changeling": 2, "Persist": 1, "Scry": 1})
        self.assertEqual(self.result["keywords"][0]["keyword"], "Flying")


# A Commander deck with one of each problem: 1 + 2 + 1 + 1 + 1 + 1 + 1 + 3 + 8 + 1 + 80 = 100.
PROBLEM_DECK = """Commander
1 Finneas, Ace Archer

Companion
1 Lutri, the Spellchaser

Deck
2 Grizzly Bears
1 Fireball
1 Primeval Titan
1 Smothering Tithe
1 Armageddon
1 Time Warp
3 Relentless Rats
8 Seven Dwarves
1 Mox Lotus
80 Forest
"""


class TestCommander(unittest.TestCase):
    def setUp(self):
        self.result = run(PROBLEM_DECK, "commander")
        self.checks = self.result["commander"]

    def test_size_counts_commander_not_companion(self):
        self.assertEqual(self.checks["size"]["cards"], 100)
        self.assertTrue(self.checks["size"]["ok"])
        self.assertEqual(self.checks["size"]["companion"], 1)
        self.assertEqual(self.checks["commanders"], ["Finneas, Ace Archer"])
        self.assertEqual(self.checks["colour_identity"], "WG")

    def test_singleton(self):
        singleton = self.checks["singleton"]
        self.assertFalse(singleton["ok"])
        self.assertEqual(singleton["duplicates"], [{"name": "Grizzly Bears", "copies": 2, "limit": 1},
                                                   {"name": "Seven Dwarves", "copies": 8, "limit": 7}])
        self.assertEqual(singleton["allowed"], [{"name": "Relentless Rats", "copies": 3, "rule": "any number"}])

    def test_colour_identity(self):
        outside = {o["name"]: o["outside"] for o in self.checks["identity"]["outside"]}
        self.assertEqual(outside, {"Fireball": "R", "Time Warp": "U", "Relentless Rats": "B",
                                   "Seven Dwarves": "R", "Lutri, the Spellchaser": "UR"})

    def test_ban_list(self):
        legality = self.checks["legality"]
        self.assertEqual(legality["banned"], [{"name": "Primeval Titan", "qty": 1}])
        self.assertEqual(legality["banned_as_companion"], [{"name": "Lutri, the Spellchaser", "qty": 1}])
        self.assertEqual(legality["not_legal"], [{"name": "Mox Lotus", "qty": 1}])
        self.assertFalse(self.checks["ok"])
        self.assertTrue(any("Primeval Titan" in p for p in self.checks["problems"]))

    def test_bracket(self):
        bracket = self.checks["bracket"]
        self.assertEqual(bracket["game_changers"], [{"name": "Smothering Tithe", "qty": 1}])
        self.assertEqual(bracket["mass_land_denial"], [{"name": "Armageddon", "qty": 1}])
        self.assertEqual(bracket["extra_turns"], [{"name": "Time Warp", "qty": 1}])
        self.assertEqual((bracket["minimum"], bracket["label"]), (4, "Bracket 4 or higher (4 or 5 by intent)"))
        self.assertTrue(any("combo" in note for note in bracket["not_automatic"]))
        self.assertEqual([b["number"] for b in bracket["brackets"]], [1, 2, 3, 4, 5])

    def test_clean_deck(self):
        result = run("Commander\n1 Finneas, Ace Archer\n\nDeck\n10 Hare Apparent\n1 Kitchen Finks\n88 Forest\n",
                     "commander")
        checks = result["commander"]
        self.assertTrue(checks["ok"], checks["problems"])
        self.assertEqual(checks["singleton"]["allowed"], [{"name": "Hare Apparent", "copies": 10,
                                                           "rule": "any number"}])
        self.assertEqual((checks["bracket"]["minimum"], checks["bracket"]["label"]),
                         (1, "Bracket 1 or 2 (theme and intent decide)"))

    def test_min_bracket_thresholds(self):
        self.assertEqual(stats.min_bracket(0, 0, 0), 1)
        self.assertEqual(stats.min_bracket(0, 0, 1), 2)
        self.assertEqual(stats.min_bracket(1, 0, 0), 3)
        self.assertEqual(stats.min_bracket(3, 0, 2), 3)
        self.assertEqual(stats.min_bracket(4, 0, 0), 4)
        self.assertEqual(stats.min_bracket(0, 1, 0), 4)
        # Standalone infinite or game-ending two-card combos: at least Bracket 3.
        self.assertEqual(stats.min_bracket(0, 0, 0, 1), 3)
        self.assertEqual(stats.min_bracket(0, 0, 1, 2), 3)
        self.assertEqual(stats.min_bracket(4, 0, 0, 1), 4)
        self.assertEqual(stats.min_bracket(0, 0, 0, two_card_combos=0), 1)

    def test_eligibility_and_size(self):
        result = run("Commander\n1 Grizzly Bears\n1 Finneas, Ace Archer\n\nDeck\n97 Forest\n", "commander")
        checks = result["commander"]
        self.assertFalse(checks["eligibility"]["ok"])
        self.assertTrue(any("Grizzly Bears can't be a commander" in p for p in checks["problems"]))
        self.assertTrue(any("partner" in p for p in checks["problems"]))
        self.assertEqual(checks["size"]["cards"], 99)
        self.assertFalse(checks["size"]["ok"])
        self.assertIn("99 cards", result["guidance"]["note"])

    def test_a_spacecraft_needs_power_and_toughness_to_be_a_commander(self):
        # CR 903.3: "a Spacecraft card with one or more power/toughness boxes". The Eternity
        # Elevator has none; The Seriema has 5/5.
        deck = "Commander\n1 {commander}\n\nDeck\n99 Plains\n"
        elevator = run(deck.format(commander="The Eternity Elevator"), "commander")["commander"]
        self.assertFalse(elevator["eligibility"]["ok"])
        self.assertTrue(any("The Eternity Elevator can't be a commander" in p for p in elevator["problems"]))
        seriema = run(deck.format(commander="The Seriema"), "commander")["commander"]
        self.assertTrue(seriema["eligibility"]["ok"], seriema["eligibility"]["problems"])

    def test_casual_decks_get_no_legality_checks(self):
        result = run("Deck\n24 Forest\n4 Primeval Titan\n4 Armageddon\n4 Mox Lotus\n24 Grizzly Bears\n")
        self.assertIsNone(result["commander"])
        self.assertFalse(any("banned" in w.lower() for w in result["warnings"]))

    def test_without_tag_data(self):
        with mock.patch.object(stats_commander, "TAG_FILE", FIXTURES / "no-such-tags.jsonl"):
            result = run(PROBLEM_DECK, "commander")
        bracket = result["commander"]["bracket"]
        self.assertIsNone(bracket["mass_land_denial"])
        self.assertIsNone(bracket["extra_turns"])
        self.assertEqual(bracket["minimum"], 3)       # the Game Changer alone
        self.assertTrue(any("oracle tags" in w for w in result["warnings"]))

    def test_plain_json(self):
        json.dumps(self.result, allow_nan=False)


class TestDeckRules(unittest.TestCase):
    """deck_rules: the editor's warnings (they never block a save)."""

    def rules(self, text, kind="constructed"):
        return stats.deck_rules(decks.parse_decklist(text), kind)

    def test_a_legal_casual_deck(self):
        result = self.rules("Deck\n4 Llanowar Elves\n4 Grizzly Bears\n30 Relentless Rats\n22 Forest\n\n"
                            "Sideboard\n4 Opt\n")
        self.assertEqual((result["kind"], result["problems"], result["commander"]), ("constructed", [], None))

    def test_casual_size_and_copies(self):
        result = self.rules("Deck\n3 Llanowar Elves\n1 Llanowar Elves (FDN) 227\n8 Seven Dwarves\n"
                            "30 Forest\n\nSideboard\n2 Llanowar Elves\n1 Mystery Card\n4 Mystery Card\n")
        # "(deck and sideboard together)" only for a card with copies in the sideboard.
        self.assertEqual(result["problems"], [
            "42 cards; a casual deck has at least 60.",
            "6 copies of Llanowar Elves (deck and sideboard together); a deck can have at most 4.",
            "5 copies of Mystery Card (deck and sideboard together); a deck can have at most 4.",
            "8 copies of Seven Dwarves; a deck can have at most 7."])

    def test_a_card_that_allows_only_one(self):
        # "A deck can have only one card named Once More with Feeling."
        self.assertEqual(self.rules("Deck\n2 Once More with Feeling\n58 Forest\n")["problems"],
                         ["2 copies of Once More with Feeling; a deck can have at most 1."])
        self.assertEqual(self.rules("Deck\n1 Once More with Feeling\n59 Forest\n")["problems"], [])

    def test_one_card_is_singular(self):
        # A deck just started in the editor: "1 card", not "1 cards".
        self.assertEqual(self.rules("Deck\n1 Llanowar Elves\n")["problems"], ["1 card; a casual deck has at least 60."])
        commander = self.rules("Commander\n1 Finneas, Ace Archer\n", "commander")["problems"]
        self.assertIn("1 card with the commander; a Commander deck has exactly 100.", commander)

    def test_commander_wording(self):
        # No "with the commander" when there's none, and no rule numbers or jargon.
        problems = self.rules("Deck\n99 Forest\n", "commander")["problems"]
        self.assertEqual(problems, ["99 cards; a Commander deck has exactly 100, its commander included.",
                                    "There's no Commander section."])
        two = self.rules("Commander\n1 Akiri, Line-Slinger\n1 Bruse Tarl, Boorish Herder\n\nDeck\n97 Plains\n",
                         "commander")["problems"]
        self.assertEqual(two, ["99 cards with the commanders; a Commander deck has exactly 100."])
        text = "Commander\n1 Grizzly Bears\n\nCompanion\n1 Lutri, the Spellchaser\n\nDeck\n1 Lutri, the Spellchaser\n1 Mox Lotus\n"
        for problem in self.rules(text, "commander")["problems"]:
            self.assertNotRegex(problem, r"\bCR\b|\bpod\b")


    def test_each_problem_names_its_cards(self):
        # The editor marks the rows a warning is about: one list of names per problem,
        # [] for one about the whole deck; colours in words, not letters.
        result = self.rules(PROBLEM_DECK, "commander")
        self.assertEqual(list(zip(result["problems"], result["problem_cards"])), [
            ("2 copies of Grizzly Bears; a Commander deck has one of each card.", ["Grizzly Bears"]),
            ("8 copies of Seven Dwarves; its text allows 7.", ["Seven Dwarves"]),
            ("5 cards outside the commander's colour identity (white and green): Fireball, Relentless Rats, "
             "Seven Dwarves, Time Warp, Lutri, the Spellchaser.",
             ["Fireball", "Relentless Rats", "Seven Dwarves", "Time Warp", "Lutri, the Spellchaser"]),
            ("Banned in Commander: Primeval Titan.", ["Primeval Titan"]),
            ("Lutri, the Spellchaser is banned as a companion (it's fine in the deck or as the commander).",
             ["Lutri, the Spellchaser"]),
            ("Not legal in Commander (Bracket 1 may allow them if the other players agree): Mox Lotus.",
             ["Mox Lotus"])])
        self.assertEqual(result["commander"]["problem_cards"], result["problem_cards"])
        casual = self.rules("Deck\n3 Llanowar Elves\n8 Seven Dwarves\n30 Forest\n\nSideboard\n2 Llanowar Elves\n"
                            "5 Mystery Card\n")
        self.assertEqual(casual["problem_cards"], [[], ["Llanowar Elves"], ["Mystery Card"], ["Seven Dwarves"]])
        three = self.rules("Commander\n1 Akiri, Line-Slinger\n1 Grizzly Bears\n1 Mystery Commander\n\n"
                           "Deck\n2 Mystery Card\n1 mystery card\n97 Plains\n", "commander")
        self.assertEqual(three["problem_cards"], [
            [], ["Grizzly Bears"], ["Akiri, Line-Slinger", "Grizzly Bears", "Mystery Commander"],
            ["Mystery Card", "mystery card"]])      # a name the card data lacks: as the list spells it
        self.assertEqual(three["commander"]["eligibility"]["problem_cards"], three["problem_cards"][1:3])
        pair = self.rules("Commander\n1 Akiri, Line-Slinger\n1 Finneas, Ace Archer\n\nDeck\n98 Plains\n", "commander")
        self.assertEqual(pair["problem_cards"], [["Akiri, Line-Slinger", "Finneas, Ace Archer"]])

    def test_colours_in_words(self):
        self.assertEqual([stats.colour_words(c) for c in ("GW", ["B"], "", "WUBRG", "UR")],
                         ["white and green", "black", "colourless", "white, blue, black, red and green",
                          "blue and red"])
        colourless = self.rules("Commander\n1 The Eternity Elevator\n\nDeck\n1 Fireball\n", "commander")
        self.assertIn("1 card outside the commander's colour identity (colourless): Fireball.",
                      colourless["problems"])

    def test_commander_rules_are_deck_stats_own(self):
        text = "Commander\n1 Finneas, Ace Archer\n\nDeck\n2 Sol Ring\n1 Fireball\n1 Armageddon\n"
        result = self.rules(text, "commander")
        full = run(text, "commander")["commander"]
        self.assertEqual(result["commander"], full)
        self.assertEqual(result["problems"], full["problems"])
        self.assertTrue(any("2 copies of Sol Ring" in p for p in result["problems"]))
        self.assertEqual(result["commander"]["bracket"]["minimum"], 4)          # mass land denial
        with self.assertRaises(ValueError):
            stats.deck_rules({}, "casual")


class TestCommanderPairs(unittest.TestCase):
    """Two commanders, Backgrounds and cards that are creatures only off the
    battlefield, by comp-rules 702.124 and 903.3 (checked 2026-09-30 against
    the Comprehensive Rules of 2026-09-25)."""

    def problems(self, *commanders):
        text = "Commander\n" + "".join(f"1 {name}\n" for name in commanders)
        text += f"\nDeck\n{100 - len(commanders)} Forest\n"
        return stats.deck_rules(decks.parse_decklist(text), "commander")["commander"]["eligibility"]["problems"]

    def test_legal_pairs(self):
        for pair in (("Akiri, Line-Slinger", "Bruse Tarl, Boorish Herder"),            # partner (702.124h)
                     ("Pir, Imaginative Rascal", "Toothy, Imaginary Friend"),          # partner with (702.124j)
                     ("Merry, Warden of Isengard", "Pippin, Warden of Isengard"),      # ... a name with a comma
                     ("Bjorna, Nightfall Alchemist", "Cecily, Haunted Mage"),          # partner—Friends forever
                     ("Abby, Merciless Soldier", "Ellie, Brick Master"),               # partner—Survivors
                     ("Wilson, Refined Grizzly", "Raised by Giants"),                  # Choose a Background
                     ("Raised by Giants", "Wilson, Refined Grizzly"),
                     ("Rose Tyler", "The Tenth Doctor")):                              # Doctor's companion
            with self.subTest(pair):
                self.assertEqual(self.problems(*pair), [])

    def test_partner_abilities_only_pair_with_their_own_kind(self):
        # 702.124f: every card here has a keyword Scryfall calls "Partner",
        # which used to be enough.
        for pair in (("Pir, Imaginative Rascal", "Krav, the Unredeemed"),              # each names another card
                     ("Pir, Imaginative Rascal", "Akiri, Line-Slinger"),               # partner with + partner
                     ("Akiri, Line-Slinger", "Abby, Merciless Soldier"),               # partner + partner—Survivors
                     ("Bjorna, Nightfall Alchemist", "Akiri, Line-Slinger"),           # Friends forever + partner
                     ("Bjorna, Nightfall Alchemist", "Ellie, Brick Master"),           # two different partner—[text]
                     ("Rose Tyler", "River Song"),                                     # a Time Lord, but not a Doctor
                     ("Wilson, Refined Grizzly", "Akiri, Line-Slinger")):
            with self.subTest(pair):
                problems = self.problems(*pair)
                self.assertEqual(len(problems), 1, problems)
                self.assertIn("can't be commanders together", problems[0])
        self.assertEqual(self.problems("Pir, Imaginative Rascal", "Krav, the Unredeemed"), [
            "Krav, the Unredeemed and Pir, Imaginative Rascal can't be commanders together: Krav, the Unredeemed "
            "has partner with Regna, the Redeemer, and Pir, Imaginative Rascal has partner with Toothy, Imaginary "
            "Friend. Two commanders need matching partner abilities."])

    def test_a_background_needs_a_commander_that_chooses_one(self):
        expected = ('Raised by Giants is a Background: it can only be a commander alongside a commander that has '
                    '"Choose a Background".')
        self.assertEqual(self.problems("Raised by Giants"), [expected])
        self.assertEqual(self.problems("Akiri, Line-Slinger", "Raised by Giants"), [expected])

    def test_grist_is_a_creature_card_off_the_battlefield(self):
        # "As long as Grist isn't on the battlefield, it's a 1/1 Insect
        # creature in addition to its other types."
        self.assertEqual(self.problems("Grist, the Hunger Tide"), [])


class TestCommandLine(unittest.TestCase):
    def run_main(self, argv):
        """(exit code, stdout, stderr) of stats.main(argv), as test_goldfish_runs's."""
        out = io.TextIOWrapper(io.BytesIO(), encoding="utf-8")
        err = io.StringIO()
        with mock.patch("sys.stdout", out), mock.patch("sys.stderr", err):
            code = stats.main(argv)
            out.flush()
        return code, out.buffer.getvalue().decode("utf-8"), err.getvalue()

    def test_a_pairing_id_with_its_halves_in_either_order(self):
        # Milestone 7: the command line finds a deck through decks.find_summary, as
        # goldfish's and forge's do, so "pairing/elves+cats" no longer gives "No deck".
        pairing = {"id": "pairing/cats+elves", "kind": "casual", "versions": ["target"]}
        with mock.patch.object(decks, "list_decks", return_value=[]), \
                mock.patch.object(decks, "beginner_box_pairings", return_value=[pairing]), \
                mock.patch.object(decks, "load_deck", return_value={"Deck": []}) as load, \
                mock.patch.object(stats, "deck_stats", return_value={"cards": 0}) as deck_stats:
            code, out, _ = self.run_main(["pairing/elves+cats", "--json"])
            self.assertEqual(code, 0)
            self.assertEqual(load.call_args.args, ("pairing/cats+elves", "target"))
            self.assertEqual(deck_stats.call_args.args, ({"Deck": []}, "constructed"))
            self.assertEqual(json.loads(out), {"cards": 0})
            code, _, err = self.run_main(["pairing/elves+goblins"])
            self.assertEqual((code, err), (1, "No deck 'pairing/elves+goblins'\n"))


class TestHeadline(unittest.TestCase):
    def test_headline(self):
        result = run("Deck\n12 Forest\n12 Mountain\n4 Garruk's Companion\n32 Grizzly Bears\n")
        h = stats.headline(result)
        self.assertEqual((h["cards"], h["lands"], h["verdict"], h["colours_ok"], h["min_bracket"]),
                         (60, 24.0, "ok", False, None))
        self.assertEqual(h["colour_short"], ["G CC: 12 of 21", "G 1C: 12 of 13"])


class TestPackage(unittest.TestCase):
    """Milestone 7 split lib/stats.py into a package. A name the tests patch
    must have one binding, where the code reads it: a copy anywhere else
    would let a patch silently miss."""

    def test_patched_names_have_one_binding(self):
        holders = {name: [] for name in ("TAG_FILE", "COMBO_FILE", "OFFICIAL_FILE", "deck_stats")}
        for info in pkgutil.iter_modules(stats.__path__):
            if info.name.startswith("__"):
                continue
            module = importlib.import_module(f"decklab.lib.stats.{info.name}")
            for name, found in holders.items():
                if name in vars(module):
                    found.append(info.name)
        # TAG_FILE: read by commander._commander_checks and patched there; the
        # package doesn't offer it, so a patch on decklab.lib.stats fails loudly.
        self.assertEqual(holders["TAG_FILE"], ["commander"])
        self.assertFalse(hasattr(stats, "TAG_FILE"))
        self.assertEqual(holders["COMBO_FILE"], ["commander"])
        self.assertFalse(hasattr(stats, "COMBO_FILE"))
        self.assertEqual(holders["OFFICIAL_FILE"], ["commander"])
        self.assertFalse(hasattr(stats, "OFFICIAL_FILE"))
        # deck_stats: defined in the package itself, beside main, which reads it
        # there (TestCommandLine patches stats.deck_stats; api reads it there too).
        self.assertEqual(holders["deck_stats"], [])
        self.assertEqual(stats.deck_stats.__module__, "decklab.lib.stats")
        self.assertIs(stats.main.__globals__, vars(stats))


if __name__ == "__main__":
    unittest.main()
