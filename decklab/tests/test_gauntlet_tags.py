"""Tagging gauntlet decks (lib/gauntlet/tags.py, design decklab/design/gauntlet.md section 4): the
identity and colours, the metrics, one deck for each primary style, and the tribal, tokens, spells
and lifegain tags, with EDHREC's themes beside them.

The card index is a fake (CARDS below, in the index's own fields): cards.resolve and cards.card are
replaced, and so is Commander Spellbook's list (combos.find). Nothing is fetched.

Run from the repo root: python scripts/test_fixtures.py decklab.tests.test_gauntlet_tags
"""
import unittest
from unittest import mock

from decklab.lib import cards, combos
from decklab.lib.gauntlet import tags

CARDS = {}


def card(name, cost, cmc, type_line, text="", roles=(), identity=None):
    """A card index entry with the fields tags reads."""
    letters = [c for c in "WUBRG" if c in cost]
    CARDS[name] = {"name": name, "oracle_id": "oid-" + name, "mana_cost": cost, "cmc": float(cmc),
                   "type_line": type_line, "oracle_text": text, "keywords": [],
                   "colors": letters, "color_identity": letters if identity is None else list(identity),
                   "roles": list(roles)}
    return name


MOUNTAIN = card("Mountain", "", 0, "Basic Land — Mountain", identity="R")
ISLAND = card("Island", "", 0, "Basic Land — Island", identity="U")
FOREST = card("Forest", "", 0, "Basic Land — Forest", identity="G")
SWAMP = card("Swamp", "", 0, "Basic Land — Swamp", identity="B")
PLAINS = card("Plains", "", 0, "Basic Land — Plains", identity="W")
GOBLIN = card("Goblin Raider", "{R}", 1, "Creature — Goblin Warrior")
ORC = card("Orc Brute", "{1}{R}", 2, "Creature — Orc Berserker")
BOLT = card("Shock Bolt", "{R}", 1, "Instant", "Shock Bolt deals 3 damage to any target.", ("removal", "burn"))
COUNTER = card("Deny", "{U}{U}", 2, "Instant", "Counter target spell.", ("counterspell",))
BOUNCE = card("Sweep Away", "{2}{U}", 3, "Sorcery", "Return all creatures to hand.", ("board wipe",))
SPHINX = card("Old Sphinx", "{4}{U}", 5, "Creature — Sphinx")
GROWTH = card("Grow Wild", "{1}{G}", 2, "Sorcery",
              "Search your library for a basic land card, put it onto the battlefield.", ("ramp",))
WURM = card("Huge Wurm", "{5}{G}", 6, "Creature — Wurm")
BEAR = card("Grizzly Pal", "{1}{G}{G}", 3, "Creature — Bear")
TROLL = card("Hill Troll", "{2}{G}{G}", 4, "Creature — Troll")
CHARM = card("Plain Charm", "{1}{G}", 3, "Enchantment", "Whenever a creature enters, scry 1.")
TUTOR = card("Dark Tutor", "{1}{B}", 2, "Sorcery", "Search your library for a card, put it into your hand.")
SHADE = card("Night Shade", "{2}{B}", 3, "Creature — Shade")
ELF = card("Leaf Elf", "{G}", 1, "Creature — Elf Druid")
ELF_LORD = card("Elf Chief", "{1}{G}", 2, "Creature — Elf Warrior")
MUSTER = card("Muster Call", "{2}{W}", 3, "Sorcery", "Create two 1/1 white Soldier creature tokens.")
KNIGHT = card("Field Knight", "{2}{W}", 3, "Creature — Human Knight")
DRINK = card("Drink Deep", "{1}{W}", 2, "Instant", "You gain 4 life.", ("lifegain",))
HYBRID = card("Split Mind", "{W/U}{B/P}", 2, "Instant", "Draw a card.")
COMMANDER = card("Rot Mother", "{2}{B}{G}", 4, "Legendary Creature — Elf Shaman",
                 "Whenever a creature dies, create a 1/1 green Elf creature token.")


def deck(*rows, commander=None):
    """A catalogue entry's "cards": rows of (qty, name) for Main."""
    out = {"Main": [[q, n] for q, n in rows]}
    if commander:
        out["Commander"] = [[1, commander]]
    return out


AGGRO = deck((24, MOUNTAIN), (16, GOBLIN), (12, ORC), (8, BOLT))
CONTROL = deck((26, ISLAND), (4, SPHINX), (14, COUNTER), (10, BOUNCE), (6, BOLT))
RAMP = deck((22, FOREST), (10, GROWTH), (28, WURM))
MIDRANGE = deck((24, FOREST), (12, BEAR), (12, TROLL), (12, CHARM))
TUTORS = deck((24, SWAMP), (4, TUTOR), (20, SHADE), (12, CHARM))
ELVES = deck((22, FOREST), (16, ELF), (14, ELF_LORD), (8, BOLT))
TOKENS = deck((24, PLAINS), (12, MUSTER), (20, KNIGHT), (4, DRINK))


class TagTests(unittest.TestCase):
    def setUp(self):
        self.combos = {"timestamp": "t", "version": 1, "matches": []}
        patches = [mock.patch.object(cards, "resolve", lambda n: n if n in CARDS else None),
                   mock.patch.object(cards, "card", CARDS.get),
                   mock.patch.object(combos, "find", lambda *a, **k: self.combos)]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def primary(self, cards_by_section, kind="constructed"):
        return tags.tag(kind, cards_by_section)["style"]["primary"]

    def test_one_deck_for_each_style(self):
        self.assertEqual(self.primary(AGGRO), "aggro")
        self.assertEqual(self.primary(CONTROL), "control")
        self.assertEqual(self.primary(RAMP), "ramp")
        self.assertEqual(self.primary(MIDRANGE), "midrange")
        self.assertEqual(self.primary(TUTORS), "combo")
        self.assertEqual(set(tags.STYLES), {"aggro", "midrange", "control", "combo", "ramp"})

    def test_a_game_ending_two_card_combo_is_combo(self):
        self.combos["matches"] = [{"class": "infinite", "standalone": True}]
        result = tags.tag("constructed", MIDRANGE)
        self.assertEqual(result["metrics"]["two_card_combos"], 1)
        self.assertEqual(result["style"]["primary"], "combo")

    def test_a_combo_needing_a_payoff_raises_nothing(self):
        self.combos["matches"] = [{"class": "infinite", "standalone": False}]
        self.assertEqual(self.primary(MIDRANGE), "midrange")

    def test_without_the_combo_list_the_count_is_unknown(self):
        def broken(*a, **k):
            raise combos.ComboListError("no list")
        with mock.patch.object(combos, "find", broken):
            result = tags.tag("constructed", MIDRANGE)
        self.assertIsNone(result["metrics"]["two_card_combos"])
        self.assertEqual(result["style"]["primary"], "midrange")

    def test_a_land_search_is_not_a_tutor(self):
        self.assertEqual(tags.tag("constructed", RAMP)["metrics"]["tutors"], 0)
        self.assertEqual(tags.tag("constructed", TUTORS)["metrics"]["tutors"], 4)

    def test_metrics(self):
        m = tags.tag("constructed", AGGRO)["metrics"]
        self.assertEqual((m["cards"], m["nonland"], m["creatures"], m["unknown"]), (60, 36, 28, 0))
        self.assertAlmostEqual(m["creature_share"], 28 / 36, places=3)
        self.assertAlmostEqual(m["mean_mv"], round((16 + 24 + 8) / 36, 2))
        self.assertEqual(m["low_curve_share"], 1.0)
        self.assertEqual(m["interaction"], 8)
        m = tags.tag("constructed", RAMP)["metrics"]
        self.assertEqual(m["ramp"], 10)

    def test_tribal(self):
        result = tags.tag("constructed", ELVES)
        self.assertIn("tribal:elf", result["style"]["tags"])
        self.assertEqual(result["metrics"]["top_subtype"], "Elf")
        self.assertEqual(result["metrics"]["top_subtype_count"], 30)
        self.assertNotIn("tribal:goblin", tags.tag("constructed", deck((24, MOUNTAIN), (11, GOBLIN),
                                                                     (25, BOLT)))["style"]["tags"])

    def test_tokens_and_lifegain(self):
        found = tags.tag("constructed", TOKENS)["style"]["tags"]
        self.assertIn("tokens", found)
        self.assertNotIn("lifegain", found)
        found = tags.tag("constructed", deck((24, PLAINS), (16, KNIGHT), (20, DRINK)))["style"]["tags"]
        self.assertIn("lifegain", found)

    def test_spells(self):
        self.assertIn("spells", tags.tag("constructed", CONTROL)["style"]["tags"])
        self.assertNotIn("spells", tags.tag("constructed", AGGRO)["style"]["tags"])

    def test_identity_and_colours(self):
        result = tags.tag("constructed", deck((20, ISLAND), (20, MOUNTAIN), (20, GOBLIN)))
        self.assertEqual(result["identity"], "UR")      # the lands count for identity ...
        self.assertEqual(result["colours"], "R")        # ... but only nonland mana costs for colours
        result = tags.tag("constructed", deck((20, MOUNTAIN), (20, HYBRID), (20, GOBLIN)))
        self.assertEqual(result["colours"], "WUBR")     # hybrid and Phyrexian pips count
        self.assertEqual(tags.tag("constructed", deck((60, FOREST)))["colours"], "")

    def test_commander_identity_is_the_commanders(self):
        listed = deck((40, FOREST), (20, SWAMP), (20, ELF), (19, BOLT), commander=COMMANDER)
        result = tags.tag("commander", listed)
        self.assertEqual(result["identity"], "BG")
        self.assertEqual(result["colours"], "BRG")

    def test_commander_thresholds_differ(self):
        listed = deck((36, FOREST), (12, GROWTH), (51, WURM), commander=COMMANDER)
        self.assertEqual(self.primary(listed, "commander"), "ramp")
        listed = deck((36, FOREST), (8, GROWTH), (55, WURM), commander=COMMANDER)
        self.assertEqual(self.primary(listed, "commander"), "midrange")     # 8 ramp is enough only at 60

    def test_themes(self):
        listed = deck((40, FOREST), (20, SWAMP), (20, ELF), (19, CHARM), commander=COMMANDER)
        themes = [{"slug": "elves", "name": "Elves", "decks": 900},
                  {"slug": "tokens", "name": "Tokens", "decks": 400},
                  {"slug": "voltron", "name": "Voltron", "decks": 100},
                  {"slug": "dragons", "name": "Dragons", "decks": 800}]
        style = tags.tag("commander", listed, themes=themes, decks=1000)["style"]
        self.assertEqual(style["themes"], ["Elves", "Tokens", "Dragons"])       # Voltron is under 25%
        self.assertIn("tribal:elf", style["tags"])
        self.assertIn("tokens", style["tags"])
        self.assertNotIn("tribal:dragon", style["tags"])        # no Dragons among its creatures
        self.assertEqual(style["primary"], self.primary(listed, "commander"))     # themes never decide it
        style = tags.tag("commander", listed, themes=["Voltron", "Spellslinger"])["style"]
        self.assertEqual(style["themes"], ["Voltron", "Spellslinger"])
        self.assertIn("voltron", style["tags"])
        self.assertIn("spells", style["tags"])

    def test_unknown_names_are_counted_and_left_out(self):
        m = tags.tag("constructed", deck((24, MOUNTAIN), (30, GOBLIN), (6, "Not A Card")))["metrics"]
        self.assertEqual((m["unknown"], m["cards"], m["nonland"]), (6, 60, 30))

    def test_unknown_format(self):
        with self.assertRaises(ValueError):
            tags.tag("modern", AGGRO)


if __name__ == "__main__":
    unittest.main()
