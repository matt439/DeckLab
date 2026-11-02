"""Shared set-up for the gauntlet source and fixing tests: a small synthetic card index (the
cards the fixtures under fixtures/gauntlet/ name), the stats fixtures for brackets, a fake
script table for Forge's AI limits, and a urlopen that fails if anything tries the network."""
import shutil
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest import mock

from decklab.lib import cards, edhrec, precons
from decklab.lib.stats import commander

FIXTURES = Path(__file__).parent / "fixtures"
GAUNTLET = FIXTURES / "gauntlet"

# name: (mana cost, cmc, type line, colour identity, extra fields)
CARDS = {
    "Plains": ("", 0, "Basic Land — Plains", ["W"], {}),
    "Island": ("", 0, "Basic Land — Island", ["U"], {}),
    "Swamp": ("", 0, "Basic Land — Swamp", ["B"], {}),
    "Mountain": ("", 0, "Basic Land — Mountain", ["R"], {}),
    "Forest": ("", 0, "Basic Land — Forest", ["G"], {}),
    "Wastes": ("", 0, "Basic Land", [], {}),
    "Command Tower": ("", 0, "Land", [], {}),
    "Exotic Orchard": ("", 0, "Land", [], {}),
    "Y'shtola, Night's Blessed": ("{1}{W}{U}{B}", 4, "Legendary Creature — Cat Warlock", ["W", "U", "B"], {}),
    "Admiral Brass, Unsinkable": ("{1}{U}{B}{R}", 4, "Legendary Creature — Human Pirate", ["U", "B", "R"], {}),
    "Kozilek, the Great Distortion": ("{8}{C}{C}", 10, "Legendary Creature — Eldrazi", [], {}),
    "Arcane Signet": ("{2}", 2, "Artifact", [], {}),
    "Sol Ring": ("{1}", 1, "Artifact", [], {}),
    "Baleful Strix": ("{U}{B}", 2, "Artifact Creature — Bird", ["U", "B"], {}),
    "Counterspell": ("{U}{U}", 2, "Instant", ["U"], {}),
    "Swords to Plowshares": ("{W}", 1, "Instant", ["W"], {}),
    "Vindicate": ("{1}{W}{B}", 3, "Sorcery", ["W", "B"], {}),
    "Rhystic Study": ("{2}{U}", 3, "Enchantment", ["U"], {"game_changer": True}),
    "Cyclonic Rift": ("{1}{U}", 2, "Instant", ["U"], {"game_changer": True}),
    "Smothering Tithe": ("{3}{W}", 4, "Enchantment", ["W"], {"game_changer": True}),
    "Lightning Bolt": ("{R}", 1, "Instant", ["R"], {}),
    "Black Lotus": ("{0}", 0, "Artifact", [], {"commander_legality": "banned"}),
    "Relentless Rats": ("{1}{B}{B}", 3, "Creature — Rat", ["B"],
                        {"oracle_text": "A deck can have any number of cards named Relentless Rats."}),
    "Gravedigger": ("{3}{B}", 4, "Creature — Zombie", ["B"], {}),
    "Doom Blade": ("{1}{B}", 2, "Instant", ["B"], {}),
    "Mind Rot": ("{2}{B}", 3, "Sorcery", ["B"], {}),
    "Duress": ("{B}", 1, "Sorcery", ["B"], {}),
    "Vampire Nighthawk": ("{1}{B}{B}", 3, "Creature — Vampire Shaman", ["B"], {}),
    "Sign in Blood": ("{B}{B}", 2, "Sorcery", ["B"], {}),
    "Dark Ritual": ("{B}", 1, "Instant", ["B"], {}),
    "Hypnotic Specter": ("{1}{B}{B}", 3, "Creature — Specter", ["B"], {}),
    "Nantuko Shade": ("{B}{B}", 2, "Creature — Insect Shade", ["B"], {}),
    "Hallowed Fountain": ("", 0, "Land — Plains Island", ["W", "U"], {}),
}
for i in range(1, 41):          # filler nonlands for size tests: "Filler Blue 1" ... (U)
    CARDS[f"Filler Blue {i}"] = ("{1}{U}", 2, "Creature — Merfolk", ["U"], {})


def card_entry(name, cost, cmc, type_line, identity, extra):
    entry = {"name": name, "oracle_id": str(uuid.uuid5(uuid.NAMESPACE_URL, name)), "layout": "normal",
             "mana_cost": cost, "cmc": float(cmc), "type_line": type_line, "oracle_text": "",
             "colors": [c for c in "WUBRG" if "{" + c + "}" in cost], "color_identity": identity,
             "keywords": [], "power": None, "toughness": None, "loyalty": None, "defense": None,
             "produced_mana": [], "commander_legality": "legal", "game_changer": False,
             "paper": True, "roles": []}
    entry.update(extra)
    return entry


def index_data():
    return {"version": None, "built_at": "2026-11-01T00:00:00+00:00",
            "bulk": {"default_cards": "2026-11-01T09:00:00+00:00", "oracle_tags": "2026-11-01T09:00:00Z"},
            "roles": {}, "tokens": {}, "printings": {}, "variants": {},
            "cards": {name: card_entry(name, *row) for name, row in CARDS.items()}}


def no_network(*args, **kwargs):
    raise AssertionError("The gauntlet tests make no network calls")


def no_mtgjson(*args, **kwargs):
    """precons._fetch's stand-in: MTGJSON can't be reached (precons.py falls back on its cache)."""
    raise precons.PreconError("no network in the gauntlet tests")


class GauntletCase(unittest.TestCase):
    """Patches the card index, the stats fixtures, the gauntlet's data folder and every way out."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="gauntlet-test-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        from decklab.lib import gauntlet
        self.patch(cards, "_index", cards._prepare(index_data()))
        self.patch(cards, "_tag_cache", {})
        self.patch(commander, "TAG_FILE", FIXTURES / "stats_tags.jsonl")
        self.patch(commander, "COMBO_FILE", FIXTURES / "stats_combos.json")
        self.patch(commander, "OFFICIAL_FILE", FIXTURES / "stats_official_lists.json")
        self.patch(gauntlet, "DATA", self.tmp / "gauntlet")
        self.patch(edhrec, "CACHE", self.tmp / "edhrec")
        self.patch(edhrec, "MIN_GAP", 0)
        self.patch(edhrec, "_failed", {})
        self.patch(precons, "CACHE", self.tmp / "mtgjson")
        self.patch(precons, "_failed", {})
        self.patch(precons, "_kept", {})
        self.patch(precons, "_fetch", no_mtgjson)
        self.patch(cards, "_open_url", no_network)
        p = mock.patch("urllib.request.urlopen", no_network)
        p.start()
        self.addCleanup(p.stop)

    def patch(self, target, name, value):
        p = mock.patch.object(target, name, value)
        p.start()
        self.addCleanup(p.stop)


def fake_limits(cannot=(), unknown=(), commander=(), poor=False, problem=None, calls=None, screened=True):
    """A stand-in for forge.ai.ai_limits over a fake script table: cards named in cannot are
    AI:RemoveDeck:All, those in unknown have no script, commander names unplayable commanders."""
    def limits(sections, kind):
        if calls is not None:
            calls.append(kind)
        rows = [(line.quantity, line.name) for part in sections.values() for line in part]
        names = {line.name for line in sections.get("Commander", [])}
        return {"cannot_play": [{"name": n, "qty": q, "why": "script"} for q, n in rows if n in cannot],
                "unknown": [{"name": n, "qty": q} for q, n in rows if n in unknown],
                "commander_unplayable": kind == "commander" and bool(names & set(commander)),
                "pilot": {"poor": poor, "why": "fixture" if poor else None}, "team_pump": None,
                "problem": problem, "games": 0, "screened": screened}
    return limits
