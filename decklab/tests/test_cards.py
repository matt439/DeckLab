"""Tests for decklab.lib.cards. No network: everything runs on the fixture files.

fixtures/default_cards.jsonl holds real Scryfall objects trimmed to the fields
the index uses, including a Llanowar Elves token listed before the real card,
an Un-set Pick Your Poison listed before the real one, a split card, a
transform card, an adventure, a modal double-faced card, a flip card, a
reversible printing, a digital-only card, a card with no USD price, a card
printed only in etched foil (Abaddon the Despoiler) and two versions of the
Un-set Very Cryptic Command (49d listed before 49a). The Llanowar Elves prices
are made up so the cheapest printing is known: its digital, memorabilia and
foil-only printings are cheaper than m19 and must be skipped.
fixtures/oracle_tags.jsonl is a made-up tag tree that uses real slugs; it has
no lifegain tag, to check a missing tag is only a warning.
fixtures/tokens_cards.jsonl (made by a one-off script from the 2026-10-07 bulk
file) holds real objects with their ids and all_parts
links: cards that make tokens, emblems and reminders, the objects they link
to, Hornet Queen also in a printing without links, Gala Greeters and Kaya
the Inexorable linking to printings not in the file (one Treasure fits; two
Spirits do), Role, checklist, dungeon, minigame and memorabilia objects. One
link is made up: Scryfall no longer links Llanowar Elves to its own token
printing (ttsr 12), so the fixture's fdn 227 does, for the self-name rule.

Run from the repo root: python scripts/test_fixtures.py
"""
import gzip
import http.client
import io
import json
import os
import shutil
import tempfile
import threading
import time
import unittest
import urllib.error
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

from decklab.lib import card_index, cards
from decklab.lib.config import USER_AGENT

FIXTURES = Path(__file__).parent / "fixtures"
CARDS_FILE = FIXTURES / "default_cards.jsonl"
TAGS_FILE = FIXTURES / "oracle_tags.jsonl"
TOKENS_FILE = FIXTURES / "tokens_cards.jsonl"
BULK_DATES = {"default_cards": "2026-09-28T21:05:39.249+00:00",
              "oracle_tags": "2026-09-28T21:00:42.364+00:00"}

LLANOWAR = "68954295-54e3-4303-a6bc-fc4547a4e3a3"
LLANOWAR_TOKEN = "eaddc7cf-5d58-422a-ba00-6708dee2d853"
PICK_YOUR_POISON = "9af4a832-d634-47aa-91ed-79d44fe08864"
RABBIT = "fee35fc4-a5b5-4c2c-8c6a-62dad166ea72"
MONARCH = "7c934091-1bc7-4458-acef-fdac62ec3df1"
THE_RING = "98737456-ac2a-420d-aa0e-778ba3a22cec"
TREASURE = "3c549374-6c37-42e0-8d88-a8555d46732d"


class FixtureIndex(unittest.TestCase):
    """Builds the fixture index, writes it and loads it back with cards.load()."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        cls.log = []
        cls.index = cards.build_index(CARDS_FILE, TAGS_FILE, BULK_DATES, log=cls.log.append)
        cards.write_index(cls.index, cls.tmp / "index.json.gz")
        cards.load(cls.tmp / "index.json.gz")

    @classmethod
    def tearDownClass(cls):
        cards._index = None
        shutil.rmtree(cls.tmp, ignore_errors=True)


class TestIndex(FixtureIndex):
    def test_token_doesnt_shadow_real_card(self):
        elves = cards.card("Llanowar Elves")
        self.assertEqual(elves["oracle_id"], LLANOWAR)
        self.assertEqual(elves["type_line"], "Creature — Elf Druid")
        # The token keeps its printing, so a (set, number) lookup still works.
        token = cards.printing("ttsr", "12")
        self.assertEqual(token["oracle_id"], LLANOWAR_TOKEN)
        self.assertNotIn(["ttsr", "12"], elves["printings"])

    def test_shared_name_goes_to_the_real_card(self):
        poison = cards.card("Pick Your Poison")
        self.assertEqual(poison["oracle_id"], PICK_YOUR_POISON)
        self.assertEqual(poison["printings"], [["mkm", "170"]])   # not the Un-set cmb2 card

    def test_reversible_printing_links_to_card_without_a_name(self):
        self.assertIsNone(cards.card("Ghalta, Primal Hunger // Ghalta, Primal Hunger"))
        self.assertIn(["sld", "1124"], cards.card("Ghalta, Primal Hunger")["printings"])

    def test_card_fields(self):
        elves = cards.card("Llanowar Elves")
        self.assertEqual(elves["mana_cost"], "{G}")
        self.assertEqual(elves["cmc"], 1.0)
        self.assertEqual(elves["color_identity"], ["G"])
        self.assertEqual(elves["produced_mana"], ["G"])
        self.assertEqual((elves["power"], elves["toughness"]), ("1", "1"))
        self.assertEqual(elves["commander_legality"], "legal")
        self.assertFalse(elves["game_changer"])
        self.assertTrue(elves["paper"])
        self.assertNotIn("faces", elves)
        dates = [cards.printing(s, n)["released_at"] for s, n in elves["printings"]]
        self.assertEqual(dates, sorted(dates, reverse=True))
        self.assertEqual(len(dates), 5)

    def test_split_card(self):
        fire_ice = cards.card("Fire // Ice")
        self.assertEqual(fire_ice["mana_cost"], "{1}{R} // {1}{U}")
        self.assertEqual([f["name"] for f in fire_ice["faces"]], ["Fire", "Ice"])
        self.assertIn("Draw a card", fire_ice["faces"][1]["oracle_text"])

    def test_transform_card_uses_front_face(self):
        delver = cards.card("Delver of Secrets // Insectile Aberration")
        self.assertEqual(delver["mana_cost"], "{U}")
        self.assertEqual(delver["type_line"], "Creature — Human Wizard")
        self.assertEqual(delver["colors"], ["U"])
        self.assertEqual((delver["power"], delver["toughness"]), ("1", "1"))
        self.assertEqual(delver["faces"][1]["name"], "Insectile Aberration")
        self.assertEqual(delver["faces"][1]["power"], "3")
        self.assertIn("\n//\nFlying", delver["oracle_text"])

    def test_other_multi_face_cards_use_the_front_face(self):
        # Scryfall's top-level fields join both faces; in the library these
        # cards are only their front face (a split card is both halves).
        expected = {
            "Murderous Rider // Swift End": ("Creature — Zombie Knight", "{1}{B}{B}", 3.0),       # adventure
            "Emeria's Call // Emeria, Shattered Skyclave": ("Sorcery", "{4}{W}{W}{W}", 7.0),       # modal DFC
            "Bushi Tenderfoot // Kenzo the Hardhearted": ("Creature — Human Soldier", "{W}", 1.0),  # flip
        }
        for name, (type_line, mana_cost, cmc) in expected.items():
            card = cards.card(name)
            self.assertEqual((card["type_line"], card["mana_cost"], card["cmc"]), (type_line, mana_cost, cmc))
            self.assertEqual(len(card["faces"]), 2)
        self.assertEqual(cards.card("Emeria's Call // Emeria, Shattered Skyclave")["faces"][1]["type_line"],
                         "Land")
        self.assertEqual(cards.card("Fire // Ice")["type_line"], "Instant // Instant")

    def test_digital_only_card(self):
        self.assertFalse(cards.card("Oracle of the Alpha")["paper"])

    def test_printing_lookup(self):
        p = cards.printing("FDN", 227)
        self.assertEqual((p["set"], p["collector_number"], p["name"]), ("fdn", "227", "Llanowar Elves"))
        self.assertEqual((p["usd"], p["usd_foil"], p["usd_etched"]), (0.25, 1.77, None))
        self.assertEqual(p["finishes"], ["nonfoil", "foil"])
        self.assertIn("/small/", p["image_small"])
        self.assertIsNone(cards.printing("fdn", "9999"))
        self.assertIsNone(cards.printing("zzz", "1"))
        self.assertEqual(cards.printing("pdmu", "1★")["usd_foil"], 0.03)

    def test_double_faced_printing_image_is_front_face(self):
        self.assertIn("/normal/front/", cards.printing("isd", "51")["image_normal"])

    def test_printings_of_a_card(self):
        keys = [(p["set"], p["collector_number"]) for p in cards.printings("fire")]
        self.assertEqual(keys, [("apc", "128")])

    def test_game_changers(self):
        self.assertEqual(cards.game_changers(), ["Rhystic Study"])

    def test_dates(self):
        self.assertEqual(cards.price_date(), "2026-09-28")
        self.assertEqual(cards.info()["bulk"], BULK_DATES)

    def test_loaded_index_matches_built_one(self):
        self.assertEqual(cards.card("Fire // Ice"), self.index["cards"]["Fire // Ice"])


class TestVariants(FixtureIndex):
    """Un-set cards printed in several versions under one name."""

    def test_the_name_goes_to_the_lowest_collector_number(self):
        # 49d comes first in the file; the choice mustn't depend on that.
        vcc = cards.card("Very Cryptic Command")
        self.assertEqual(vcc["printings"], [["ust", "49a"]])

    def test_printing_card_finds_each_version(self):
        a, d = cards.printing_card("ust", "49a"), cards.printing_card("UST", "49d")
        self.assertIs(a, cards.card("Very Cryptic Command"))
        self.assertEqual(d["name"], "Very Cryptic Command")
        self.assertNotEqual(d["oracle_id"], a["oracle_id"])
        self.assertEqual(d["printings"], [["ust", "49d"]])
        self.assertEqual(d["oracle_id"], cards.printing("ust", "49d")["oracle_id"])

    def test_printing_card_for_ordinary_printings(self):
        self.assertIs(cards.printing_card("fdn", "227"), cards.card("Llanowar Elves"))
        self.assertIs(cards.printing_card("sld", "1124"), cards.card("Ghalta, Primal Hunger"))   # reversible
        self.assertIsNone(cards.printing_card("ttsr", "12"))      # a token, not a deck card
        self.assertIsNone(cards.printing_card("zzz", "1"))


class TokenIndexTests(unittest.TestCase):
    """The token table and what each card makes, built from fixtures/tokens_cards.jsonl."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        cls.log = []
        cls.index = cards.build_index(TOKENS_FILE, TAGS_FILE, BULK_DATES, log=cls.log.append)
        cards.write_index(cls.index, cls.tmp / "index.json.gz")
        cards.load(cls.tmp / "index.json.gz")

    @classmethod
    def tearDownClass(cls):
        cards._index = None
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def makes(self, name):
        """[(token name, P/T, colours, kind)] a card makes, and its unresolved names."""
        found, unresolved = cards.tokens_for(name)
        return sorted((t["name"], f"{t['power']}/{t['toughness']}", "".join(t["colors"]), t["kind"])
                      for t in found), unresolved

    def test_a_card_and_what_it_makes(self):
        found, unresolved = cards.tokens_for("hare apparent")       # any name resolve() takes
        self.assertEqual(unresolved, [])
        [rabbit] = found
        self.assertEqual(rabbit["id"], RABBIT)
        self.assertEqual({k: rabbit[k] for k in ("name", "kind", "layout", "type_line", "power", "toughness",
                                                 "colors", "keywords", "faces", "face_names", "image")},
                         {"name": "Rabbit", "kind": "token", "layout": "token",
                          "type_line": "Token Creature — Rabbit", "power": "1", "toughness": "1",
                          "colors": ["W"], "keywords": [], "faces": [], "face_names": ["Rabbit"],
                          "image": ["tfdn", "5"]})
        self.assertEqual(rabbit["printings"], [["tfdn", "5"]])
        self.assertEqual(cards.card("Hare Apparent")["tokens"], [RABBIT])
        self.assertEqual(cards.tokens_for("Not A Card"), ([], []))
        self.assertEqual(cards.tokens_for("Delver of Secrets"), ([], []))     # makes nothing
        self.assertNotIn("tokens", cards.card("Delver of Secrets // Insectile Aberration"))

    def test_tokens_emblems_and_reminders(self):
        self.assertEqual(self.makes("Court of Grace"),
                         ([("Angel", "4/4", "W", "token"), ("Spirit", "1/1", "W", "token"),
                           ("The Monarch", "None/None", "", "reminder")], []))
        self.assertEqual(self.makes("Elspeth, Sun's Champion"),
                         ([("Elspeth, Sun's Champion Emblem", "None/None", "", "emblem"),
                           ("Soldier", "1/1", "W", "token")], []))
        self.assertEqual([name for name, *_ in self.makes("Shortcut Seeker")[0]],
                         ["Dungeon of the Mad Mage", "Lost Mine of Phandelver", "Tomb of Annihilation"])
        self.assertEqual({t["kind"] for t in cards.tokens_for("Shortcut Seeker")[0]}, {"reminder"})
        self.assertEqual(cards.token(TREASURE)["text"], "{T}, Sacrifice this token: Add one mana of any color.")
        self.assertEqual(cards.token("Wicked // Cursed"), None)          # keyed by oracle id only

    def test_a_double_faced_reminder(self):
        [ring] = cards.tokens_for("Galadriel, Elven-Queen")[0]
        self.assertEqual((ring["id"], ring["kind"], ring["type_line"]), (THE_RING, "reminder", "Emblem // Card"))
        self.assertEqual(ring["face_names"], ["The Ring", "The Ring Tempts You"])
        self.assertEqual([(f["name"], f["type_line"]) for f in ring["faces"]],
                         [("The Ring", "Emblem"), ("The Ring Tempts You", "Card")])

    def test_tokens_with_the_same_name_stay_apart(self):
        self.assertEqual(self.makes("Gisa, the Hellraiser")[0], [("Zombie Rogue", "2/2", "BU", "token")])
        self.assertEqual(self.makes("Army of the Damned")[0], [("Zombie", "2/2", "B", "token")])
        # Mitotic Slime makes two different Oozes; the Cats of Prideful Parent and
        # Regal Caracal differ by lifelink.
        self.assertEqual(self.makes("Mitotic Slime")[0], [("Ooze", "1/1", "G", "token"), ("Ooze", "2/2", "G", "token")])
        parent, = cards.tokens_for("Prideful Parent")[0]
        caracal, = cards.tokens_for("Regal Caracal")[0]
        self.assertNotEqual(parent["id"], caracal["id"])
        self.assertEqual((parent["keywords"], caracal["keywords"]), ([], ["Lifelink"]))

    def test_links_are_unioned_across_printings(self):
        # One Hornet Queen printing has no links; the card still makes its Insect.
        lines = [json.loads(line) for line in TOKENS_FILE.read_text(encoding="utf-8").splitlines()]
        queens = [o for o in lines if o["name"] == "Hornet Queen"]
        self.assertEqual(sorted(bool(o.get("all_parts")) for o in queens), [False, True])
        self.assertEqual(len(cards.card("Hornet Queen")["printings"]), 2)
        [insect] = cards.tokens_for("Hornet Queen")[0]
        self.assertEqual((insect["name"], insect["keywords"]), ("Insect", ["Deathtouch", "Flying"]))

    def test_a_cards_own_token_printing_isnt_something_it_makes(self):
        self.assertEqual(cards.tokens_for("Llanowar Elves"), ([], []))
        # ...unless it makes tokens: Coruscation Mage's offspring is a token named after it.
        self.assertEqual(self.makes("Coruscation Mage")[0], [("Coruscation Mage", "1/1", "R", "token")])
        self.assertEqual(cards.tokens_for("Coruscation Mage")[0][0]["type_line"], "Token Creature — Otter Wizard")

    def test_helpers_checklists_and_real_cards_are_dropped(self):
        self.assertEqual(cards.tokens_for("Brazen Borrower"), ([], []))       # On an Adventure: a helper
        self.assertEqual(cards.token_faces_at("thob", "15")[1], ["On an Adventure"])
        self.assertEqual(cards.token(cards.token_faces_at("thob", "15")[0])["kind"], "helper")
        self.assertIsNone(cards.token_faces_at("tisd", "13"))                 # Innistrad Checklist
        self.assertIsNone(cards.token_face("Innistrad Checklist"))
        # Links to real cards (Hare Apparent's link to itself, Llanowar Elves'
        # to Marwyn's Kindred) match no token and are only counted.
        self.assertTrue(any("matched no token" in line for line in self.log), self.log)

    def test_memorabilia_and_minigames_arent_tokens(self):
        self.assertIsNone(cards.token_faces_at("fj22", "36"))      # the Jumpstart front card named Treasure
        self.assertIsNone(cards.token_faces_at("mkhm", "2"))       # Booster Blitz, a minigame
        self.assertIsNone(cards.token_faces_at("ptc", "0"))        # a blank memorabilia card
        names = cards.token_face_names()
        self.assertNotIn("Booster Blitz", names)
        self.assertNotIn("Blank Card", names)
        self.assertEqual(cards.token_faces_at("tmh2", "21"), (TREASURE, ["Treasure"]))

    def test_role_printed_as_a_flip_card_is_a_token_not_a_card(self):
        self.assertIsNone(cards.card("Wicked // Cursed"))
        self.assertIsNone(cards.resolve("Wicked"))
        oracle_id, faces = cards.token_faces_at("plst", "TWOE-17")
        self.assertEqual(faces, ["Wicked", "Cursed"])
        self.assertEqual(cards.token(oracle_id)["kind"], "token")
        self.assertEqual(cards.token_face("WICKED"), "Wicked")

    def test_the_representative_printing(self):
        # The newest token set's paper printing with a picture wins over a newer Secret Lair one.
        treasure = cards.token(TREASURE)
        self.assertEqual(treasure["image"], ["tblb", "29"])          # the newest token set
        self.assertEqual(treasure["printings"], [["sld", "2820"], ["tblb", "29"], ["tmh2", "21"]])   # newest first
        copy = cards.tokens_for("Gandalf, Westward Voyager")[0][0]
        self.assertEqual((copy["name"], copy["image"]), ("Copy", ["tmsc", "17"]))      # not The List's

    def test_a_link_to_another_printing_falls_back_to_name_and_type(self):
        # Gala Greeters links a Treasure printing that isn't in the data; one token fits.
        self.assertEqual([t["id"] for t in cards.tokens_for("Gala Greeters")[0]], [TREASURE])
        # Kaya links a Spirit that isn't in the data either, and two Spirits fit:
        # Deck Lab doesn't guess.
        self.assertEqual(cards.tokens_for("Kaya the Inexorable"), ([], ["Spirit"]))
        self.assertEqual(cards.card("Kaya the Inexorable")["token_names"], ["Spirit"])
        self.assertNotIn("tokens", cards.card("Kaya the Inexorable"))

    def test_face_names_fold(self):
        self.assertEqual(cards.token_face("the ring tempts you"), "The Ring Tempts You")
        self.assertEqual(cards.token_face("THE RING//the ring tempts you"), "The Ring // The Ring Tempts You")
        self.assertEqual(cards.token_face("  the   monarch "), "The Monarch")
        self.assertIsNone(cards.token_face("Sprit"))
        self.assertIsNone(cards.token_face("Llanowar Mentor"))
        names = cards.token_face_names()
        self.assertEqual(names, sorted(set(names)))
        for name in ("The Ring", "The Ring // The Ring Tempts You", "Spirit", "Wicked // Cursed",
                     "Elspeth, Sun's Champion Emblem", "Tomb of Annihilation"):
            self.assertIn(name, names)

    def test_token_faces_at(self):
        self.assertEqual(cards.token_faces_at("TLTR", "H13"), (THE_RING, ["The Ring", "The Ring Tempts You"]))
        self.assertEqual(cards.token_faces_at("tcmr", "14"), (MONARCH, ["The Monarch"]))
        self.assertIsNone(cards.token_faces_at("fdn", "227"))       # a card, not a token
        self.assertIsNone(cards.token_faces_at("zzz", "1"))

    def test_token_returns_a_copy(self):
        rabbit = cards.token(RABBIT)
        rabbit["name"] = "Hare"
        self.assertEqual(cards.token(RABBIT)["name"], "Rabbit")
        self.assertIsNone(cards.token("no-such-id"))

    def test_info_counts_tokens(self):
        self.assertEqual(cards.info()["tokens"], len(self.index["tokens"]))
        self.assertEqual(len(self.index["tokens"]), 27)

    def test_show_prints_what_a_card_makes(self):
        out = io.StringIO()
        with mock.patch("sys.stdout", out), mock.patch.object(cards, "usd_to_aud", return_value=(1.5, "2026-10-09")):
            self.assertEqual(cards._show("Court of Grace"), 0)
            cards._show("Kaya the Inexorable")
        self.assertIn("Makes: Angel (Token Creature — Angel 4/4 W), The Monarch (reminder), "
                      "Spirit (Token Creature — Spirit 1/1 W)\n", out.getvalue())
        self.assertIn("Makes: Spirit (several tokens have this name)\n", out.getvalue())

    def test_old_fixtures_without_links_build_as_before(self):
        # Objects without ids or all_parts (the other fixture files) build the same
        # cards as before: no card makes anything, and only the one token is in the table.
        index = cards.build_index(CARDS_FILE, TAGS_FILE, BULK_DATES, log=lambda *a: None)
        self.assertEqual((len(index["cards"]), len(index["variants"])), (18, 2))
        self.assertFalse(any("tokens" in c or "token_names" in c for c in index["cards"].values()))
        self.assertEqual([t["name"] for t in index["tokens"].values()], ["Llanowar Elves"])
        for name, tags, count in (("goldfish_cards.jsonl", TAGS_FILE, 81), ("stats_cards.jsonl", "stats_tags.jsonl", 62)):
            index = cards.build_index(FIXTURES / name, FIXTURES / tags, BULK_DATES, log=lambda *a: None)
            self.assertEqual((len(index["cards"]), index["tokens"]), (count, {}), name)


class TestResolve(FixtureIndex):
    def test_exact_and_any_case(self):
        self.assertEqual(cards.resolve("Llanowar Elves"), "Llanowar Elves")
        self.assertEqual(cards.resolve("LLANOWAR elves"), "Llanowar Elves")
        self.assertEqual(cards.resolve("  llanowar   elves "), "Llanowar Elves")

    def test_front_face_alone(self):
        self.assertEqual(cards.resolve("fire"), "Fire // Ice")
        self.assertEqual(cards.resolve("Delver of Secrets"), "Delver of Secrets // Insectile Aberration")
        self.assertEqual(cards.resolve("fire//ice"), "Fire // Ice")

    def test_accents_and_curly_quotes(self):
        self.assertEqual(cards.resolve("Lim-Dul's Vault"), "Lim-Dûl's Vault")
        self.assertEqual(cards.resolve("lim-dûl’s vault"), "Lim-Dûl's Vault")

    def test_reversible_printing_name(self):
        self.assertEqual(cards.resolve("Ghalta, Primal Hunger // Ghalta, Primal Hunger"), "Ghalta, Primal Hunger")

    def test_unknown(self):
        self.assertIsNone(cards.resolve("Fire // Nonsense"))
        self.assertIsNone(cards.resolve("Llanowar Elvez"))
        self.assertIsNone(cards.resolve(""))

    def test_card_is_exact_only(self):
        self.assertIsNone(cards.card("fire"))
        self.assertIsNone(cards.card("llanowar elves"))


class TestRoles(FixtureIndex):
    def test_roles_include_child_and_grandchild_tags(self):
        # removal -> removal-creature -> removal-burn; burn -> removal-burn and burn-player
        self.assertEqual(cards.roles("Fire // Ice"), {"removal", "burn", "draw"})
        self.assertEqual(cards.roles("Sol Ring"), {"ramp"})          # ramp -> mana-producer -> mana-rock
        self.assertEqual(cards.roles("Llanowar Elves"), {"ramp"})
        self.assertEqual(cards.roles("Wrath of God"), {"removal", "board wipe"})

    def test_parent_tag_cards_dont_flow_down(self):
        # Delver is tagged card-advantage, the parent of draw, so it isn't draw.
        self.assertEqual(cards.roles("Delver of Secrets"), set())

    def test_role_counts_deduplicate(self):
        counts = {role: info["oracle_cards"] for role, info in self.index["roles"].items()}
        self.assertEqual(counts, {"removal": 3, "ramp": 3, "draw": 2, "counterspell": 0,
                                  "board wipe": 1, "burn": 1, "lifegain": 0})

    def test_missing_tag_is_a_warning(self):
        self.assertTrue(any("lifegain" in line for line in self.log))

    def test_unknown_card(self):
        with self.assertRaises(KeyError):
            cards.roles("Not A Card")


class TestTagMembers(unittest.TestCase):
    """cards.tag_members: any oracle tag, read straight from a tag file."""
    FIRE_ICE = "ae92942b-919c-4ea9-b693-85fcef765d5a"
    SWEEPER_CARD = "34515b16-c9a4-4f98-8c77-416a7a523407"

    def setUp(self):
        cards._tag_cache.clear()
        self.addCleanup(cards._tag_cache.clear)

    def test_tag_includes_child_and_grandchild_tags(self):
        # removal -> removal-creature -> removal-burn / removal-sacrifice, and removal -> sweeper
        members = cards.tag_members(["removal", "sweeper"], TAGS_FILE)
        self.assertEqual(members["removal"], {self.FIRE_ICE, PICK_YOUR_POISON, self.SWEEPER_CARD})
        self.assertEqual(members["sweeper"], {self.SWEEPER_CARD})
        self.assertIsInstance(members["removal"], frozenset)

    def test_same_answers_as_the_roles(self):
        index = cards.build_index(CARDS_FILE, TAGS_FILE, BULK_DATES, log=lambda *a: None)
        members = cards.tag_members(list(cards.ROLE_TAGS.values())[:-1], TAGS_FILE)   # no lifegain tag
        for role, slug in list(cards.ROLE_TAGS.items())[:-1]:
            self.assertEqual(len(members[slug]), index["roles"][role]["oracle_cards"], role)

    def test_tag_with_no_cards_is_empty(self):
        self.assertEqual(cards.tag_members(["counterspell"], TAGS_FILE), {"counterspell": frozenset()})

    def test_unknown_tag_raises(self):
        with self.assertRaises(KeyError):
            cards.tag_members(["removal", "no-such-tag"], TAGS_FILE)

    def test_missing_file_raises(self):
        with self.assertRaises(FileNotFoundError):
            cards.tag_members(["removal"], FIXTURES / "no-such-file.jsonl")

    def test_file_read_once_and_again_when_it_changes(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        path = tmp / "tags.jsonl"
        shutil.copy(TAGS_FILE, path)
        with mock.patch.object(card_index, "_read_tag_tree", wraps=card_index._read_tag_tree) as read:
            cards.tag_members(["removal", "burn"], path)
            cards.tag_members(["burn"], path)
            self.assertEqual(read.call_count, 1)
            cards.tag_members(["sweeper"], path)          # not asked for yet: read again
            self.assertEqual(read.call_count, 2)
            # The file changes: a new tag file means new answers.
            lines = path.read_text(encoding="utf-8").splitlines()
            path.write_text("\n".join(line for line in lines if '"slug": "sweeper"' not in line) + "\n",
                            encoding="utf-8")
            with self.assertRaises(KeyError):
                cards.tag_members(["sweeper"], path)

    def test_tag_tree_readers_have_one_home(self):
        # Tests patch _read_tag_tree on card_index; a second binding on cards
        # would let such a patch silently miss tag_members.
        for name in ("_read_tag_tree", "_tag_closure", "_iter_jsonl", "_now"):
            self.assertTrue(hasattr(card_index, name), name)
            self.assertFalse(hasattr(cards, name), name)

    def test_default_path_is_the_downloaded_file(self):
        with mock.patch.object(cards, "bulk_path", return_value=TAGS_FILE) as bulk:
            self.assertEqual(cards.tag_members(["sweeper"])["sweeper"], {self.SWEEPER_CARD})
        bulk.assert_called_once_with("oracle_tags")


class TestPrices(FixtureIndex):
    def test_cheapest_skips_digital_memorabilia_and_foil_only(self):
        # pdmu 1★ is foil only at US$0.03: a non-foil price always wins.
        self.assertEqual(cards.cheapest_usd("Llanowar Elves"), (0.20, "m19", "314", "nonfoil"))

    def test_foil_or_etched_price_when_there_is_no_non_foil_one(self):
        self.assertEqual(cards.cheapest_usd("Abaddon the Despoiler"), (0.42, "40k", "319", "etched"))
        with mock.patch.object(cards, "usd_to_aud", return_value=(2.0, "2026-09-28")):
            price = cards.price_aud("Abaddon the Despoiler")
        self.assertEqual((price.aud, price.finish), (0.84, "etched"))
        self.assertEqual(price.label(), "~A$0.84 est. (US$0.42 etched, 40K 319, Scryfall 2026-09-28; "
                                        "1 USD = 2.0 AUD, ECB 2026-09-28)")

    def test_no_usd_price(self):
        self.assertIsNone(cards.cheapest_usd("Black Lotus"))    # only the CED printing has one
        self.assertIsNone(cards.cheapest_usd("Oracle of the Alpha"))
        with mock.patch.object(cards, "usd_to_aud") as rate:
            self.assertIsNone(cards.price_aud("Black Lotus"))
            rate.assert_not_called()

    def test_price_aud(self):
        with mock.patch.object(cards, "usd_to_aud", return_value=(1.4237, "2026-09-28")):
            price = cards.price_aud("llanowar elves")
        self.assertEqual(price.name, "Llanowar Elves")
        self.assertEqual(price.aud, 0.28)
        self.assertEqual((price.usd, price.rate, price.rate_date), (0.20, 1.4237, "2026-09-28"))
        self.assertEqual((price.set, price.collector_number, price.price_date, price.finish),
                         ("m19", "314", "2026-09-28", "nonfoil"))
        # AGENTS.md: every AUD figure shows it's an estimate, the rate and its date, and the price date.
        self.assertEqual(price.label(), "~A$0.28 est. (US$0.20, M19 314, Scryfall 2026-09-28; "
                                        "1 USD = 1.4237 AUD, ECB 2026-09-28)")

    def test_unknown_card(self):
        with self.assertRaises(KeyError):
            cards.cheapest_usd("Not A Card")


class TestExchangeRate(unittest.TestCase):
    RESPONSE = {"amount": 1.0, "base": "USD", "date": "2026-09-28", "rates": {"AUD": 1.4237}}

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.fx_file = self.tmp / "fx.json"
        for patcher in (mock.patch.object(cards, "FX_FILE", self.fx_file),
                        mock.patch.object(cards, "_fx", None),
                        mock.patch.object(cards, "_fx_tried_on", None),
                        mock.patch.object(cards, "_fx_tried_at", None)):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def write_cache(self, rate, fetched_on):
        cards._write_json(self.fx_file, {"rate": rate, "date": "2026-09-20", "fetched_on": fetched_on})

    def test_fetches_at_most_once_a_day(self):
        with mock.patch.object(cards, "_get_json", return_value=self.RESPONSE) as get:
            self.assertEqual(cards.usd_to_aud(), (1.4237, "2026-09-28"))
            self.assertEqual(cards.usd_to_aud(), (1.4237, "2026-09-28"))
        self.assertEqual(get.call_count, 1)
        self.assertEqual(cards._read_json(self.fx_file, {})["fetched_on"], date.today().isoformat())

    def test_old_cache_is_refreshed(self):
        self.write_cache(1.40, (date.today() - timedelta(days=1)).isoformat())
        with mock.patch.object(cards, "_get_json", return_value=self.RESPONSE):
            self.assertEqual(cards.usd_to_aud(), (1.4237, "2026-09-28"))

    def test_offline_uses_cached_rate(self):
        self.write_cache(1.40, (date.today() - timedelta(days=3)).isoformat())
        with mock.patch.object(cards, "_get_json", side_effect=OSError("offline")) as get:
            self.assertEqual(cards.usd_to_aud(), (1.40, "2026-09-20"))
            self.assertEqual(cards.usd_to_aud(), (1.40, "2026-09-20"))
        self.assertEqual(get.call_count, 1)      # doesn't retry every call while offline

    def test_offline_without_cache_raises(self):
        with mock.patch.object(cards, "_get_json", side_effect=OSError("offline")):
            with self.assertRaises(RuntimeError):
                cards.usd_to_aud()

    def test_without_a_cache_it_tries_again_after_a_short_gap(self):
        # The server can start before the network is up: that mustn't leave it
        # without prices for the rest of the day.
        get = mock.Mock(side_effect=[OSError("offline"), http.client.IncompleteRead(b"{"), self.RESPONSE])
        with mock.patch.object(cards, "_get_json", get):
            for _ in range(2):
                with self.assertRaises(RuntimeError):
                    cards.usd_to_aud()
            self.assertEqual(get.call_count, 1)              # not again straight away
            cards._fx_tried_at -= cards.FX_RETRY_GAP + 1
            with self.assertRaises(RuntimeError):            # a cut-off response is just another failure
                cards.usd_to_aud()
            cards._fx_tried_at -= cards.FX_RETRY_GAP + 1
            self.assertEqual(cards.usd_to_aud(), (1.4237, "2026-09-28"))
        self.assertEqual(get.call_count, 3)


class TestSearch(FixtureIndex):
    def test_prefix_matches_come_first(self):
        # a prefix, then a later word starting with it, then any other match
        self.assertEqual(cards.search_names("elv"),
                         ["Elvish Mystic", "Llanowar Elves", "Delver of Secrets // Insectile Aberration"])
        found = cards.search_names("l")
        self.assertEqual(found[:2], ["Lim-Dûl's Vault", "Llanowar Elves"])
        self.assertIn("Black Lotus", found[2:])

    def test_matches_later_faces(self):
        self.assertEqual(cards.search_names("ice"), ["Fire // Ice"])

    def test_typed_words_start_the_names_words_in_order(self):
        self.assertEqual(cards.search_names("llan elv"), ["Llanowar Elves"])
        self.assertEqual(cards.search_names("delver secr"), ["Delver of Secrets // Insectile Aberration"])
        self.assertEqual(cards.search_names("fire/ice"), ["Fire // Ice"])          # one slash for the two faces
        self.assertEqual(cards.search_names("lim duls"), ["Lim-Dûl's Vault"])      # apostrophes dropped
        self.assertEqual(cards.search_names("elv llan"), [])                       # in order only
        self.assertEqual(cards.search_names("lan elv"), [])                        # word starts, not middles
        self.assertEqual(cards.search_names("oracle alph"), [])                    # digital only
        self.assertEqual(cards.search_names("oracle alph", paper_only=False), ["Oracle of the Alpha"])
        # After names containing the text at a word start, before names containing it mid-word.
        self.assertEqual(cards.search_names("elv"),
                         ["Elvish Mystic", "Llanowar Elves", "Delver of Secrets // Insectile Aberration"])

    def test_limit(self):
        self.assertEqual(len(cards.search_names("l", 2)), 2)

    def test_loose_matching(self):
        self.assertEqual(cards.search_names("LIM-DUL"), ["Lim-Dûl's Vault"])

    def test_digital_only_cards_are_skipped_by_default(self):
        self.assertEqual(cards.search_names("oracle of"), [])
        self.assertEqual(cards.search_names("oracle of", paper_only=False), ["Oracle of the Alpha"])

    def test_empty_text(self):
        self.assertEqual(cards.search_names("   "), [])

    def test_close_names_for_a_misspelling(self):
        self.assertEqual(cards.close_names("Llanowar Elfs")[0], "Llanowar Elves")
        self.assertEqual(cards.close_names("delver of secret"), ["Delver of Secrets // Insectile Aberration"])
        self.assertEqual(cards.close_names("black lotsu"), ["Black Lotus"])        # front faces and full names
        self.assertEqual(cards.close_names("zzzzqqq"), [])
        self.assertEqual(cards.close_names("oracle of the alpah"), [])             # digital only
        self.assertEqual(len(cards.close_names("l", 2)), 2)


class TestImages(FixtureIndex):
    def setUp(self):
        self.images = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.images, True)
        self.urls = []

        def fake_download(url, dest, accept="*/*"):
            self.urls.append(url)
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(b"jpeg")
            return 4

        for patcher in (mock.patch.object(cards, "IMAGES_DIR", self.images),
                        mock.patch.object(cards, "_download", side_effect=fake_download)):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_downloads_once(self):
        path = cards.image_path("FDN", "227", "small")
        self.assertEqual(path, self.images / "small" / "fdn" / "227.jpg")
        self.assertTrue(path.exists())
        self.assertEqual(cards.image_path("fdn", "227", "small"), path)
        self.assertEqual(len(self.urls), 1)
        self.assertIn("/small/", self.urls[0])

    def test_double_faced_card_uses_front_face(self):
        cards.image_path("isd", "51")
        self.assertIn("/normal/front/", self.urls[0])

    def test_two_requests_for_a_new_image_download_it_once(self):
        # Two phones opening the same deck: the second waits for the first
        # download instead of replacing a file that's being sent (WinError 5).
        def slow_download(url, dest, accept="*/*"):
            self.urls.append(url)
            time.sleep(0.2)
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(b"jpeg")

        results = []
        with mock.patch.object(cards, "_download", side_effect=slow_download):
            threads = [threading.Thread(target=lambda: results.append(cards.image_path("m19", "314")))
                       for _ in range(2)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
        self.assertEqual(len(self.urls), 1)
        self.assertEqual(results, [self.images / "normal" / "m19" / "314.jpg"] * 2)

    def test_awkward_path_parts_are_made_safe(self):
        star = cards.image_path("pdmu", "1★")
        self.assertEqual(star.name, "1_2605.jpg")
        conflux = cards.image_path("con", "1")      # CON is a reserved device name on Windows
        self.assertEqual(conflux.parent.name, "con_")
        for path in (star, conflux):
            path.resolve().relative_to(self.images.resolve())

    def test_the_cache_is_capped(self):
        # Requests for every printing can't fill the disk: past the cap, the images used
        # least recently go, never the one just asked for.
        def download(url, dest, accept="*/*"):
            self.urls.append(url)
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(b"x" * 400)
        with mock.patch.object(cards, "_download", side_effect=download), \
                mock.patch.object(cards, "IMAGE_CACHE_MAX", 1000), \
                mock.patch.dict(cards._image_bytes, clear=True):
            first = cards.image_path("fdn", "227", "small")
            os.utime(first, (time.time() - 100, time.time() - 100))     # used longest ago
            second = cards.image_path("m19", "314", "small")
            self.assertTrue(first.exists() and second.exists())         # 800 bytes: under the cap
            third = cards.image_path("isd", "51", "small")              # 1,200: over it
            self.assertFalse(first.exists())
            self.assertTrue(second.exists() and third.exists())
            self.assertEqual(cards._image_bytes[self.images], 800)
            # A deleted image is downloaded again when it's next asked for.
            self.assertEqual(cards.image_path("fdn", "227", "small"), first)
            self.assertTrue(first.exists())
        self.assertEqual(len(self.urls), 4)

    def test_an_image_used_again_is_marked_as_used(self):
        path = cards.image_path("fdn", "227", "small")
        old = time.time() - 3 * 24 * 60 * 60
        os.utime(path, (old, old))
        cards.image_path("fdn", "227", "small")
        self.assertGreater(path.stat().st_mtime, old + 60)
        self.assertEqual(len(self.urls), 1)

    def test_large_and_art_crop_come_from_the_normal_url(self):
        # Sizes the index doesn't store: the normal URL with its folder swapped, each cached in its own
        # folder, downloaded once like the others.
        large = cards.image_path("fdn", "227", "large")
        art = cards.image_path("fdn", "227", "art_crop")
        self.assertEqual(large, self.images / "large" / "fdn" / "227.jpg")
        self.assertEqual(art, self.images / "art_crop" / "fdn" / "227.jpg")
        normal = cards.printing("fdn", "227")["image_normal"]
        self.assertEqual(self.urls, [normal.replace("/normal/", "/large/"), normal.replace("/normal/", "/art_crop/")])
        cards.image_path("fdn", "227", "art_crop")
        self.assertEqual(len(self.urls), 2)
        # A double-faced card's back: from the stored normal back.
        cards.image_path("isd", "51", "large-back")
        self.assertIn("/large/back/", self.urls[-1])
        # A printing with no normal picture has none of these either.
        self.assertIsNone(cards.image_source({"image_normal": None}, "art_crop"))
        self.assertIsNone(cards.image_source({"image_normal": "https://example.com/x.jpg"}, "large"))

    def test_bad_input(self):
        with self.assertRaises(ValueError):
            cards.image_path("fdn", "227", "huge")
        with self.assertRaises(KeyError):
            cards.image_path("..", "227")
        with self.assertRaises(KeyError):
            cards.image_path("fdn", "../../227")
        self.assertEqual(self.urls, [])

    def test_safe_part(self):
        self.assertEqual(cards._safe_part("ELD-97"), "ELD-97")
        self.assertEqual(cards._safe_part("../x"), "_2e_2e_2fx")
        self.assertEqual(cards._safe_part("a\\b"), "a_5cb")
        self.assertEqual(cards._safe_part("a_b"), "a_5fb")
        self.assertEqual(cards._safe_part("COM1"), "COM1_")


class TestUpdateOffline(unittest.TestCase):
    """update() with fresh local bulk files: builds the index once, never touches the network."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        for kind, source in (("default_cards", CARDS_FILE), ("oracle_tags", TAGS_FILE)):
            with gzip.open(self.tmp / f"{kind}.jsonl.gz", "wb") as out:
                out.write(source.read_bytes())
        now = card_index._now().isoformat(timespec="seconds")
        cards._write_json(self.tmp / "bulk.json", {
            kind: {"updated_at": BULK_DATES[kind], "uri": "fixture", "downloaded_at": now}
            for kind in cards.BULK_TYPES})
        for patcher in (mock.patch.object(cards, "SCRYFALL_DIR", self.tmp),
                        mock.patch.object(cards, "INDEX_FILE", self.tmp / "index.json.gz"),
                        mock.patch.object(cards, "BULK_META_FILE", self.tmp / "bulk.json"),
                        mock.patch.object(cards, "_get_json", side_effect=AssertionError("no network")),
                        mock.patch.object(cards, "_download", side_effect=AssertionError("no network")),
                        # The combo list is decklab.lib.combos' (test_combos); never the PC's here.
                        mock.patch.object(cards, "_update_combos"),
                        mock.patch.object(cards, "_update_official_lists"),
                        mock.patch.object(cards, "_update_rulings"),
                        mock.patch.object(cards, "_index", None)):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_builds_then_skips(self):
        log = []
        self.assertTrue(cards.update(log=log.append))
        self.assertTrue((self.tmp / "index.json.gz").exists())
        self.assertEqual(cards.card("Llanowar Elves")["oracle_id"], LLANOWAR)
        self.assertFalse(cards.update(log=log.append))
        self.assertIn("up to date", log[-1])

    def test_the_combo_list_is_a_step_of_every_update(self):
        cards.update(log=lambda *a: None)
        cards.update(force=False, log=lambda *a: None)      # the index is fresh: still a step
        self.assertEqual(cards._update_combos.call_count, 2)

    def test_the_combo_and_official_steps_come_after_the_index(self):
        # Their downloads never hold up the index; the index is written before either starts.
        seen = []
        cards._update_combos.side_effect = lambda *a: seen.append(("combos", (self.tmp / "index.json.gz").exists()))
        cards._update_official_lists.side_effect = lambda *a: seen.append(("official", bool(seen)))
        self.assertTrue(cards.update(log=lambda *a: None))
        self.assertEqual(seen, [("combos", True), ("official", True)])
        seen.clear()
        self.assertFalse(cards.update(log=lambda *a: None))     # up to date: both steps still run
        self.assertEqual([step for step, _ in seen], ["combos", "official"])

    def test_the_combo_steps_still_run_when_the_index_fails(self):
        with mock.patch.object(cards, "build_index", side_effect=ValueError("bad bulk file")):
            with self.assertRaises(ValueError):
                cards.update(force=False, log=lambda *a: None)
        self.assertEqual((cards._update_combos.call_count, cards._update_official_lists.call_count), (1, 1))

    def test_the_official_lists_check_is_a_step_of_every_update(self):
        cards.update(log=lambda *a: None)
        cards.update(log=lambda *a: None)       # the index is fresh: still a step (it's once a day)
        self.assertEqual([c.args for c in cards._update_official_lists.call_args_list],
                         [(False, mock.ANY), (False, mock.ANY)])

    def test_week_old_file_is_stale(self):
        meta = cards._read_json(self.tmp / "bulk.json", {})
        self.assertFalse(cards._is_stale("default_cards", meta))
        meta["default_cards"]["downloaded_at"] = (card_index._now() - timedelta(days=8)).isoformat()
        self.assertTrue(cards._is_stale("default_cards", meta))
        (self.tmp / "oracle_tags.jsonl.gz").unlink()
        self.assertTrue(cards._is_stale("oracle_tags", meta))

    def test_a_damaged_index_is_rebuilt_even_when_its_stamp_matches(self):
        # A damaged gzip stream raises zlib.error; the daily update must repair it rather
        # than say "up to date" for ever.
        self.assertTrue(cards.update(log=lambda *a: None))
        index = self.tmp / "index.json.gz"
        damaged = bytearray(index.read_bytes())
        for i in range(20, 84):
            damaged[i] ^= 0xFF
        index.write_bytes(bytes(damaged))
        cards._index = None
        with self.assertRaises(cards.INDEX_ERRORS):
            cards.info()
        log = []
        self.assertTrue(cards.update(log=log.append))
        self.assertTrue(any("can't be read" in line for line in log), log)
        self.assertEqual(cards.card("Llanowar Elves")["oracle_id"], LLANOWAR)

    def test_a_new_index_format_is_rebuilt_from_the_local_files(self):
        self.assertTrue(cards.update(log=lambda *a: None))
        meta = cards._read_json(self.tmp / "bulk.json", {})
        meta["index"]["version"] = cards.INDEX_VERSION - 1       # built by older code
        cards._write_json(self.tmp / "bulk.json", meta)
        self.assertTrue(cards.update(log=lambda *a: None))
        self.assertEqual(cards._read_json(self.tmp / "bulk.json", {})["index"]["version"], cards.INDEX_VERSION)
        self.assertEqual(cards.info()["tokens"], 1)         # format 4: the token table (ttsr 12)

    def test_an_index_in_an_older_format_is_refused(self):
        index = cards.build_index(CARDS_FILE, TAGS_FILE, BULK_DATES, log=lambda *a: None)
        index["version"] = cards.INDEX_VERSION - 1
        cards.write_index(index, self.tmp / "old.json.gz")
        with self.assertRaisesRegex(RuntimeError, "older index format"):
            cards.load(self.tmp / "old.json.gz")


class TestUpdateNetwork(unittest.TestCase):
    """update() when the week-old bulk files are due a refresh and Scryfall
    can't be reached, sends a cut-off response, or the download fails."""

    NEWER = "2026-10-05T21:00:00.000+00:00"

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        for kind, source in (("default_cards", CARDS_FILE), ("oracle_tags", TAGS_FILE)):
            with gzip.open(self.tmp / f"{kind}.jsonl.gz", "wb") as out:
                out.write(source.read_bytes())
        week_ago = (card_index._now() - timedelta(days=8)).isoformat(timespec="seconds")
        self.meta = {kind: {"updated_at": BULK_DATES[kind], "uri": "fixture", "downloaded_at": week_ago}
                     for kind in cards.BULK_TYPES}
        cards._write_json(self.tmp / "bulk.json", self.meta)
        self.log = []
        for patcher in (mock.patch.object(cards, "SCRYFALL_DIR", self.tmp),
                        mock.patch.object(cards, "INDEX_FILE", self.tmp / "index.json.gz"),
                        mock.patch.object(cards, "BULK_META_FILE", self.tmp / "bulk.json"),
                        mock.patch.object(cards, "_update_combos"),
                        mock.patch.object(cards, "_update_official_lists"),
                        mock.patch.object(cards, "_update_rulings"),
                        mock.patch.object(cards, "_index", None)):
            patcher.start()
            self.addCleanup(patcher.stop)

    def listing(self, updated_at):
        return {"data": [{"type": kind, "updated_at": updated_at,
                          "jsonl_download_uri": f"https://example.invalid/{kind}.jsonl.gz"}
                         for kind in cards.BULK_TYPES]}

    def update(self, get_json, download=None):
        download = download or mock.Mock(side_effect=AssertionError("no download expected"))
        with mock.patch.object(cards, "_get_json", get_json), mock.patch.object(cards, "_download", download):
            return cards.update(log=self.log.append)

    def assert_local_files_kept(self):
        for kind, source in (("default_cards", CARDS_FILE), ("oracle_tags", TAGS_FILE)):
            with gzip.open(self.tmp / f"{kind}.jsonl.gz", "rb") as f:
                self.assertEqual(f.read(), source.read_bytes())
        self.assertEqual([p.name for p in self.tmp.glob("*.part")], [])

    def test_offline_keeps_the_local_files_and_builds_the_index(self):
        failures = [urllib.error.URLError("offline"), http.client.IncompleteRead(b'{"data": [', 5000),
                    ValueError("not JSON")]
        for error in failures:
            with self.subTest(error=type(error).__name__):
                (self.tmp / "index.json.gz").unlink(missing_ok=True)
                self.assertTrue(self.update(mock.Mock(side_effect=error)))
                self.assertIn("keeping the local bulk files", "\n".join(self.log))
                self.assert_local_files_kept()
                self.assertEqual(cards.card("Llanowar Elves")["oracle_id"], LLANOWAR)

    def test_a_failed_download_keeps_the_old_file(self):
        download = mock.Mock(side_effect=OSError("got 1959 bytes, expected 3919"))
        self.assertTrue(self.update(mock.Mock(return_value=self.listing(self.NEWER)), download))
        self.assertEqual(download.call_count, 2)
        self.assertEqual(sum("download failed" in line for line in self.log), 2)
        self.assert_local_files_kept()
        meta = cards._read_json(self.tmp / "bulk.json", {})
        self.assertEqual(meta["default_cards"]["updated_at"], BULK_DATES["default_cards"])  # tried again next time
        self.assertEqual(cards.card("Llanowar Elves")["oracle_id"], LLANOWAR)
        # With the index in place, a second failed refresh is harmless.
        self.assertFalse(self.update(mock.Mock(return_value=self.listing(self.NEWER)), download))

    def test_one_file_downloads_and_the_other_fails(self):
        def download(url, dest, accept="*/*"):
            if "oracle_tags" in url:
                raise http.client.IncompleteRead(b"", 100)
            shutil.copy(self.tmp / "default_cards.jsonl.gz", self.tmp / "copy.gz")
            (self.tmp / "copy.gz").replace(dest)
            return 1
        self.assertTrue(self.update(mock.Mock(return_value=self.listing(self.NEWER)), download))
        meta = cards._read_json(self.tmp / "bulk.json", {})
        self.assertEqual((meta["default_cards"]["updated_at"], meta["oracle_tags"]["updated_at"]),
                         (self.NEWER, BULK_DATES["oracle_tags"]))

    def test_unchanged_on_scryfall_restarts_the_clock(self):
        listing = {"data": [{"type": kind, "updated_at": BULK_DATES[kind], "jsonl_download_uri": "x"}
                            for kind in cards.BULK_TYPES]}
        self.update(mock.Mock(return_value=listing))
        meta = cards._read_json(self.tmp / "bulk.json", {})
        self.assertFalse(cards._is_stale("default_cards", meta))

    def test_no_local_data_and_offline_is_a_clear_error(self):
        for kind in cards.BULK_TYPES:
            (self.tmp / f"{kind}.jsonl.gz").unlink()
        offline = mock.Mock(side_effect=urllib.error.URLError("[WinError 10061] refused"))
        with self.assertRaisesRegex(RuntimeError, "no local copy yet.*python -m decklab.lib.cards update"):
            self.update(offline)
        stdout, stderr = io.TextIOWrapper(io.BytesIO()), io.StringIO()
        with mock.patch.object(cards, "_get_json", offline), \
                mock.patch("sys.stdout", stdout), mock.patch("sys.stderr", stderr):
            self.assertEqual(cards.main(["update"]), 1)
            self.assertEqual(cards.main(["show", "Llanowar Elves"]), 1)
        self.assertIn("Couldn't download Scryfall's card data (https://api.scryfall.com/bulk-data)",
                      stderr.getvalue())
        self.assertIn("No card index at", stderr.getvalue())

    def test_a_download_with_no_local_file_to_fall_back_on_is_an_error(self):
        (self.tmp / "oracle_tags.jsonl.gz").unlink()

        def download(url, dest, accept="*/*"):
            if "oracle_tags" in url:
                raise OSError("cut off")
            return 1
        with self.assertRaisesRegex(RuntimeError, "oracle_tags.jsonl.gz.*no local copy yet"):
            self.update(mock.Mock(return_value=self.listing(self.NEWER)), download)


class FakeResponse(io.BytesIO):
    def __init__(self, data, length):
        super().__init__(data)
        self.headers = {"Content-Length": str(length)}


class TestDownload(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.dest = self.tmp / "file.gz"
        self.dest.write_bytes(b"old")

    def test_a_short_download_leaves_the_old_file(self):
        with mock.patch.object(cards, "_open_url", return_value=FakeResponse(b"12345", 10)):
            with self.assertRaisesRegex(OSError, "got 5 bytes, expected 10"):
                cards._download("https://example.invalid/x", self.dest)
        self.assertEqual(self.dest.read_bytes(), b"old")
        self.assertEqual([p.name for p in self.tmp.iterdir()], ["file.gz"])

    def test_a_full_download_replaces_it(self):
        with mock.patch.object(cards, "_open_url", return_value=FakeResponse(b"12345", 5)):
            self.assertEqual(cards._download("https://example.invalid/x", self.dest), 5)
        self.assertEqual(self.dest.read_bytes(), b"12345")
        self.assertEqual([p.name for p in self.tmp.iterdir()], ["file.gz"])

    def test_requests_are_spaced_out_and_identify_themselves(self):
        # Scryfall asks for a User-Agent and at most about 10 requests a second.
        with mock.patch.object(cards, "_last_request", time.monotonic()), \
                mock.patch("urllib.request.urlopen") as urlopen, mock.patch("time.sleep") as sleep:
            cards._open_url("https://example.invalid/x")
        sleep.assert_called_once()
        self.assertTrue(0 < sleep.call_args[0][0] <= cards.MIN_REQUEST_GAP)
        request = urlopen.call_args[0][0]
        self.assertEqual(request.get_header("User-agent"), USER_AGENT)


if __name__ == "__main__":
    unittest.main()
