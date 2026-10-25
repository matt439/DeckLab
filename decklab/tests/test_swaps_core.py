"""The rules of stand-ins for missing cards (E2-S07, lib/decks/swaps.py): what fits, the ranking,
the strength note and the swaps a Play-now list makes. No card data or database: the cards are
written out here as cards.card() gives them."""
import unittest

from decklab.lib.decks import DeckLine
from decklab.lib.decks import swaps


def card(name, type_line, cmc=0, colors=(), identity=None, **extra):
    return {"name": name, "type_line": type_line, "cmc": cmc, "colors": list(colors),
            "color_identity": list(identity if identity is not None else colors), "keywords": [], "roles": [],
            "power": None, "toughness": None, "printings": [("fdn", "1")], **extra}


GLORY = card("Glorybringer", "Creature — Dragon", 5, "R", power="4", toughness="4",
             keywords=["Flying", "Haste", "Exert"], roles=["removal"])
VENTMAW = card("Savage Ventmaw", "Creature — Dragon", 6, "RG", power="4", toughness="4", keywords=["Flying"])
GIANT = card("Ravenous Giant", "Creature — Giant", 3, "R", power="5", toughness="1")
WURM = card("Pelakka Wurm", "Creature — Wurm", 7, "G", power="7", toughness="7")
ROBOT = card("Steel Overseer", "Artifact Creature — Construct", 3, (), power="1", toughness="1")
GOLEM = card("Bronze Golem", "Artifact Creature — Golem", 4, (), power="3", toughness="3")
SHOCK = card("Shock", "Instant", 1, "R", roles=["removal", "burn"])
BOLT = card("Lightning Bolt", "Instant", 1, "R", roles=["removal", "burn"])
STRIKE = card("Lightning Strike", "Instant", 2, "R", roles=["removal", "burn"])
BLAST = card("Boltwing Marauder", "Creature — Dragon", 5, "BR", power="5", toughness="4")
SORCERY = card("Volcanic Fallout", "Sorcery", 1, "R")
CRAG = card("Rootbound Crag", "Land", 0, (), "RG")
HIGHLANDS = card("Rugged Highlands", "Land", 0, (), "RG")
WASTES_LAND = card("Rogue's Passage", "Land", 0, ())
ARBOR = card("Dryad Arbor", "Land Creature — Forest Dryad", 0, (), "G")
ADVENTURE = card("Bonecrusher Giant // Stomp", "Creature — Giant // Instant — Adventure", 3, "R",
                 power="4", toughness="3")
MDFC = card("Emeria's Call // Emeria, Shattered Skyclave", "Sorcery // Land", 7, "W")
ENCHANTED = card("Eidolon of Countless Battles", "Enchantment Creature — Eidolon", 2, "W", power="0", toughness="0")
X_SPELL = card("Banefire", "Sorcery", 1, "R")       # {X}{R}: X counts as 0
SPLIT = card("Fire // Ice", "Instant // Instant", 4, "UR")


class TypeTests(unittest.TestCase):

    def test_a_cards_primary_type(self):
        for c, expected in ((ROBOT, "creature"), (ENCHANTED, "creature"), (ARBOR, "land"), (ADVENTURE, "creature"),
                            (MDFC, "sorcery"), (SPLIT, "instant"), (CRAG, "land"), (SHOCK, "instant"),
                            (card("Sol Ring", "Artifact", 1), "artifact"),
                            (card("Tarmogoyf", "Kindred Instant — Elf", 2, "G"), "instant"),
                            (card("Plane", "Plane — Dominaria"), None)):
            with self.subTest(c["name"]):
                self.assertEqual(swaps.primary_type(c), expected)

    def test_instants_and_sorceries_stay_apart(self):
        self.assertTrue(swaps.fits(BOLT, SHOCK, set("R"), "casual"))
        self.assertFalse(swaps.fits(BOLT, SORCERY, set("R"), "casual"))

    def test_a_creature_stands_in_for_an_artifact_creature(self):
        self.assertTrue(swaps.fits(GOLEM, ROBOT, set("R"), "casual"))
        self.assertFalse(swaps.fits(GOLEM, card("Sol Ring", "Artifact", 4), set("R"), "casual"))


class ColourTests(unittest.TestCase):

    def test_sharing_a_colour(self):
        self.assertTrue(swaps.fits(GLORY, VENTMAW, set("RG"), "casual"))
        self.assertFalse(swaps.fits(GLORY, card("Big Wurm", "Creature — Wurm", 5, "G"), set("RG"), "casual"))

    def test_colourless_matches_only_colourless(self):
        self.assertTrue(swaps.fits(GOLEM, ROBOT, set(), "casual"))
        self.assertFalse(swaps.fits(GOLEM, GIANT, set("R"), "casual"))
        self.assertFalse(swaps.fits(GIANT, ROBOT, set("R"), "casual"))

    def test_a_stand_in_must_be_castable(self):
        # Boltwing Marauder is black and red: not in a red-green deck.
        self.assertFalse(swaps.fits(GLORY, BLAST, set("RG"), "casual"))
        self.assertTrue(swaps.fits(GLORY, BLAST, set("BRG"), "casual"))
        # Commander: the colour identity within the commander's.
        hybrid = card("Hybrid Dragon", "Creature — Dragon", 5, "R", identity="RW")
        self.assertFalse(swaps.fits(GLORY, hybrid, set("RG"), "commander"))
        self.assertTrue(swaps.fits(GLORY, hybrid, set("RGW"), "commander"))

    def test_deck_colours(self):
        sections = {"Deck": [DeckLine(4, "Glorybringer"), DeckLine(2, "Rootbound Crag"), DeckLine(9, "Forest"),
                             DeckLine(1, "Unknown")], "Sideboard": [DeckLine(1, "Pelakka Wurm")]}
        lookup = {c["name"]: c for c in (GLORY, CRAG, WURM)}.get
        self.assertEqual(swaps.deck_colours(sections, "casual", lookup), set("RG"))
        commander = {"Commander": [DeckLine(1, "Hybrid")], "Deck": [DeckLine(1, "Glorybringer")]}
        hybrid = card("Hybrid", "Legendary Creature — Elf", 3, "G", identity="GW")
        self.assertEqual(swaps.deck_colours(commander, "commander", {"Hybrid": hybrid, "Glorybringer": GLORY}.get),
                         set("GW"))


class LandAndManaValueTests(unittest.TestCase):

    def test_lands_match_only_lands(self):
        self.assertTrue(swaps.fits(CRAG, HIGHLANDS, set("RG"), "casual"))
        self.assertFalse(swaps.fits(CRAG, VENTMAW, set("RG"), "casual"))
        self.assertFalse(swaps.fits(GIANT, ARBOR, set("RG"), "casual"))
        self.assertTrue(swaps.fits(card("Forest Arbor", "Land — Forest", 0, (), "G"), ARBOR, set("G"), "casual"))
        self.assertTrue(swaps.fits(card("Mutavault", "Land", 0), WASTES_LAND, set("R"), "casual"))
        self.assertFalse(swaps.fits(CRAG, WASTES_LAND, set("RG"), "casual"))

    def test_basics_are_offered_for_a_land(self):
        self.assertEqual(swaps.basics_for(CRAG, set("RG"), "casual"), ["Mountain", "Forest"])
        self.assertEqual(swaps.basics_for(CRAG, set("R"), "casual"), ["Mountain"])
        self.assertEqual(swaps.basics_for(GIANT, set("R"), "casual"), [])
        self.assertEqual(swaps.basics_for(WASTES_LAND, set("R"), "casual"), [])
        self.assertEqual(swaps.basics_for(WASTES_LAND, set(), "commander"), ["Wastes"])
        self.assertFalse(swaps.fits(CRAG, card("Forest", "Basic Land — Forest", 0, (), "G"), set("RG"), "casual"))

    def test_a_lands_colours_are_the_mana_it_makes(self):
        # Command Tower's identity is none, but it makes every colour: not a colourless land.
        tower = card("Command Tower", "Land", 0, (), (), produced_mana=list("WUBRG"))
        passage = card("Rogue's Passage", "Land", 0, (), (), produced_mana=["C"])
        self.assertEqual(swaps.colours_of(tower), set("WUBRG"))
        self.assertEqual(swaps.colours_of(passage), set())
        self.assertFalse(swaps.fits(tower, passage, set("RG"), "commander"))
        self.assertTrue(swaps.fits(tower, CRAG, set("RG"), "commander"))
        self.assertEqual(swaps.basics_for(tower, set("RG"), "commander"), ["Mountain", "Forest"])
        # The note counts only the deck's colours: a red-green land loses nothing there.
        self.assertEqual(swaps.swap_note(tower, CRAG, set("RG"))["words"], "Close to even")
        self.assertEqual(swaps.basic_note(tower, "Forest", set("RG"))["text"], "A little weaker: makes no red mana.")

    def test_a_casual_decks_land_makes_only_its_colours(self):
        foundry = card("Sacred Foundry", "Land — Mountain Plains", 0, (), "RW", produced_mana=["R", "W"])
        brass = card("City of Brass", "Land", 0, (), (), produced_mana=list("WUBRG"))
        self.assertFalse(swaps.fits(CRAG, foundry, set("RG"), "casual"))
        self.assertTrue(swaps.fits(CRAG, foundry, set("RGW"), "casual"))
        self.assertTrue(swaps.fits(CRAG, brass, set("RG"), "casual"))       # every colour, the deck's too
        self.assertFalse(swaps.fits(CRAG, brass, set(), "casual"))

    def test_mana_value_within_one(self):
        self.assertTrue(swaps.fits(GLORY, VENTMAW, set("RG"), "casual"))            # 6 for 5
        self.assertFalse(swaps.fits(GLORY, GIANT, set("R"), "casual"))              # 3 for 5
        self.assertTrue(swaps.fits(STRIKE, X_SPELL.copy() | {"type_line": "Instant"}, set("R"), "casual"))
        self.assertFalse(swaps.fits(card("Three", "Sorcery", 3, "R"), X_SPELL, set("R"), "casual"))

    def test_the_missing_card_is_never_its_own_stand_in(self):
        self.assertFalse(swaps.fits(GLORY, GLORY, set("R"), "casual"))


class RankAndNoteTests(unittest.TestCase):

    def test_ranking(self):
        # Shared roles first, then subtypes, then the same mana value before cheaper before dearer.
        plain = card("Plain Bolt", "Instant", 1, "R")
        order = sorted([plain, STRIKE, SHOCK], key=lambda c: swaps.rank_key(BOLT, c, 1))
        self.assertEqual([c["name"] for c in order], ["Shock", "Lightning Strike", "Plain Bolt"])
        dragon = card("Red Dragon", "Creature — Dragon", 5, "R")
        beast = card("Red Beast", "Creature — Beast", 5, "R")
        self.assertLess(swaps.rank_key(GLORY, dragon, 1), swaps.rank_key(GLORY, beast, 1))
        cheaper = card("Cheap", "Creature — Beast", 4, "R")
        dearer = card("Dear", "Creature — Beast", 6, "R")
        names = sorted([dearer, cheaper, beast], key=lambda c: swaps.rank_key(GLORY, c, 1))
        self.assertEqual([c["name"] for c in names], ["Red Beast", "Cheap", "Dear"])
        # A copy here before one only on the way.
        self.assertLess(swaps.rank_key(GLORY, beast, 1), swaps.rank_key(GLORY, beast, 0))

    def test_the_note(self):
        note = swaps.swap_note(GLORY, VENTMAW)
        self.assertEqual(note["text"], "Clearly weaker: costs 1 more (6 vs 5); loses haste, exert and its removal.")
        self.assertEqual((note["severity"], note["words"]), (5, "Clearly weaker"))
        self.assertEqual(swaps.swap_note(BOLT, SHOCK), {"severity": 0, "words": "Close to even",
                                                        "text": "Close to even: the same job at the same cost."})
        small = swaps.swap_note(card("Big", "Creature — Wurm", 4, "G", power="5", toughness="5"),
                                card("Small", "Creature — Wurm", 3, "G", power="3", toughness="3",
                                     keywords=["Trample"]))
        self.assertEqual(small["text"], "A little weaker: costs 1 less (3 vs 4); 3/3 instead of 5/5; gains trample.")
        self.assertEqual(swaps.swap_note(CRAG, HIGHLANDS)["words"], "Close to even")
        self.assertEqual(swaps.basic_note(CRAG, "Forest")["text"], "A little weaker: makes no red mana.")
        self.assertEqual(swaps.severity_words(3), "Clearly weaker")

    def test_mechanics_arent_strengths(self):
        delver = card("Delver of Secrets // Insectile Aberration", "Creature — Human Wizard // Creature — Human Insect",
                      1, "U", power="1", toughness="1", keywords=["Flying", "Transform"])
        sailor = card("Spectral Sailor", "Creature — Spirit Pirate", 1, "U", power="1", toughness="1",
                      keywords=["Flying", "Flash"])
        self.assertEqual(swaps.swap_note(delver, sailor)["text"], "Close to even: gains flash.")
        goose = card("Gilded Goose", "Creature — Bird", 1, "G", power="0", toughness="2", keywords=["Flying", "Food"])
        self.assertNotIn("food", swaps.swap_note(card("Bird", "Creature — Bird", 1, "G", power="0", toughness="2",
                                                       keywords=["Flying"]), goose)["text"])


class DeriveTests(unittest.TestCase):
    TARGET = {"Deck": [DeckLine(2, "Glorybringer"), DeckLine(2, "Rootbound Crag"), DeckLine(2, "Lightning Bolt"),
                       DeckLine(9, "Forest")],
              "Sideboard": [DeckLine(1, "Pelakka Wurm")]}

    def owned(self, deck, sideboard=()):
        return {"Deck": [DeckLine(q, n) for q, n in deck], "Sideboard": [DeckLine(q, n) for q, n in sideboard]}

    def test_pairing_from_a_hand_written_table(self):
        prose = ("| Buy (target list) | Play until it arrives (owned list) | What the swap costs |\n|---|---|---|\n"
                 "| 2 Glorybringer | Tajuru Pathwarden + Savage Ventmaw | Both are big, but no haste. |\n"
                 "| 2 Rootbound Crag | 2 Rugged Highlands | Highlands enter tapped. |")
        owned = self.owned([(1, "Tajuru Pathwarden"), (1, "Savage Ventmaw"), (2, "Rugged Highlands"),
                            (2, "Lightning Bolt"), (9, "Forest")], [(1, "Pelakka Wurm")])
        found = swaps.derive_swaps(self.TARGET, owned, prose)
        self.assertEqual([(s["for"], s["out_qty"], [u["name"] for u in s["using"]], s["note"]) for s in found["swaps"]],
                         [("Glorybringer", 2, ["Tajuru Pathwarden", "Savage Ventmaw"], "Both are big, but no haste."),
                          ("Rootbound Crag", 2, ["Rugged Highlands"], "Highlands enter tapped.")])
        self.assertEqual(found["unpaired"], [])

    def test_moving_between_deck_and_sideboard_isnt_a_swap(self):
        owned = self.owned([(2, "Glorybringer"), (2, "Rootbound Crag"), (1, "Lightning Bolt"), (9, "Forest"),
                            (1, "Pelakka Wurm")], [(1, "Lightning Bolt")])
        self.assertEqual(swaps.derive_swaps(self.TARGET, owned, ""), {"swaps": [], "unpaired": []})

    def test_bullets_unpaired_cards_and_whole_words(self):
        prose = "- **2 Lightning Bolt → 2 Shock:** Close to even.\nBolt is great but Boltwing Marauder is not."
        owned = self.owned([(2, "Glorybringer"), (2, "Rootbound Crag"), (2, "Shock"), (1, "Boltwing Marauder"),
                            (9, "Forest")], [(1, "Pelakka Wurm")])
        found = swaps.derive_swaps(self.TARGET, owned, prose)
        self.assertEqual([(s["for"], [u["name"] for u in s["using"]], s["note"]) for s in found["swaps"]],
                         [("Lightning Bolt", ["Shock"], "Close to even.")])
        self.assertEqual(found["unpaired"], [{"name": "Boltwing Marauder", "qty": 1}])
        self.assertFalse(swaps.names_card("Boltwing Marauder is not.", "Bolt"))
        self.assertTrue(swaps.names_card("Play a Bolt.", "Bolt"))
        self.assertTrue(swaps.names_card("Fire is fine.", "Fire // Ice"))
        self.assertIsNone(swaps.find_note("|---|---|", "Bolt"))

    def test_a_longer_card_name_doesnt_name_a_shorter_one(self):
        target = {"Deck": [DeckLine(2, "Anger"), DeckLine(2, "Anger of the Gods")]}
        owned = {"Deck": [DeckLine(2, "Slagstorm"), DeckLine(2, "Anger of the Gods")]}
        prose = "- **2 Anger of the Gods → 2 Pyroclasm:** old note\n- **2 Anger → 2 Slagstorm:** x"
        found = swaps.derive_swaps(target, owned, prose)
        self.assertEqual([(s["for"], s["using"], s["note"]) for s in found["swaps"]],
                         [("Anger", [{"name": "Slagstorm", "qty": 2}], "x")])
        self.assertEqual(found["unpaired"], [])
        self.assertTrue(swaps.names_card("Anger of the Gods", "Anger"))
        self.assertFalse(swaps.names_card("Anger of the Gods", "Anger", ["Anger of the Gods"]))
        self.assertTrue(swaps.names_card("Anger of the Gods, then Anger", "Anger", ["Anger of the Gods"]))

    def test_a_stand_in_for_two_cards_is_shared_out(self):
        target = {"Deck": [DeckLine(2, "Lightning Bolt"), DeckLine(2, "Lightning Strike")]}
        owned = {"Deck": [DeckLine(4, "Shock")]}
        prose = "| Buy | Play now | Note |\n|---|---|---|\n| 2 Lightning Bolt | 2 Shock | a |\n| 2 Lightning Strike | 2 Shock | b |"
        found = swaps.derive_swaps(target, owned, prose)
        self.assertEqual([(s["for"], s["using"]) for s in found["swaps"]],
                         [("Lightning Bolt", [{"name": "Shock", "qty": 2}]),
                          ("Lightning Strike", [{"name": "Shock", "qty": 2}])])
        # Lines that don't say how many: each takes what's left, up to the copies it swaps out.
        target = {"Deck": [DeckLine(3, "Shineshadow Snarl"), DeckLine(2, "Caves of Koilos"), DeckLine(10, "Plains")]}
        owned = {"Deck": [DeckLine(3, "Swamp"), DeckLine(1, "Temple of Silence"), DeckLine(11, "Plains")]}
        prose = ("- Shineshadow Snarl: Swamp and Temple of Silence for now.\n"
                 "- Caves of Koilos: Swamp or Plains.")
        found = swaps.derive_swaps(target, owned, prose)
        self.assertEqual([(s["for"], s["using"]) for s in found["swaps"]],
                         [("Shineshadow Snarl", [{"name": "Swamp", "qty": 3}, {"name": "Temple of Silence", "qty": 1}]),
                          ("Caves of Koilos", [{"name": "Plains", "qty": 1}])])
        self.assertEqual(found["unpaired"], [])
        # More than a line states stays unpaired, never counted twice.
        found = swaps.derive_swaps({"Deck": [DeckLine(2, "Lightning Bolt")]}, {"Deck": [DeckLine(4, "Shock")]},
                                   "- **2 Lightning Bolt → 2 Shock:** fine.")
        self.assertEqual((found["swaps"][0]["using"], found["unpaired"]),
                         ([{"name": "Shock", "qty": 2}], [{"name": "Shock", "qty": 2}]))

    def test_no_note_yet(self):
        owned = self.owned([(2, "Glorybringer"), (2, "Rootbound Crag"), (2, "Lightning Bolt"), (8, "Forest")],
                           [(1, "Pelakka Wurm")])
        found = swaps.derive_swaps(self.TARGET, owned, None)
        self.assertEqual([(s["for"], s["note"], s["note_line"]) for s in found["swaps"]], [("Forest", None, None)])

    def test_names_as_written_are_made_exact(self):
        target = {"Deck": [DeckLine(1, "Murderous Rider")]}
        owned = {"Deck": [DeckLine(1, "Murderous Rider // Swift End")]}
        exact = {"Murderous Rider": "Murderous Rider // Swift End"}.get
        self.assertEqual(swaps.derive_swaps(target, owned, "", lambda n: exact(n) or n), {"swaps": [], "unpaired": []})
        self.assertEqual(len(swaps.derive_swaps(target, owned, "")["swaps"]), 1)

    def test_note_of(self):
        self.assertEqual(swaps.note_of("| 2 A | 2 B | It costs. |"), "It costs.")
        self.assertEqual(swaps.note_of("- **2 A → 2 B:** Fine."), "Fine.")
        self.assertEqual(swaps.note_of("- A for B: slower."), "slower.")
        self.assertEqual(swaps.note_of("A is out for now"), "A is out for now")


if __name__ == "__main__":
    unittest.main()
