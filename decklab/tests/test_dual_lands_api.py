"""Free dual lands for a colour shortfall (E3-S25, slice 3): GET /api/deck/dual-lands (lib/api/swaps.py
suggest_dual_lands) and its rules (lib/decks/dual_lands.py).

Runs in test_swaps_api's SwapsTestCase (test_api's Sandbox, with the files backend), whose card index is built
again here from the fixture cards plus a few lands (EXTRA): nothing reads this PC's card data. The colour
check is the sandbox's stand-in deck_stats, answering what each test sets (stats(), in the shape of
lib/stats' "colours"). Nothing here writes to a database or plays a game.
"""
import json
from unittest import mock

from decklab.lib import api, cards
from decklab.lib.api import guard
from decklab.lib.decks import dual_lands, swaps
from decklab.tests import test_swaps_api as base
from decklab.tests.test_api import BULK_DATES, FIXTURES, _write
from decklab.tests.test_collection_edit import ROLES
from decklab.tests.test_deck_privacy_readers import _as

DECK_ID = "casual/gruul-short"
GRUUL = "Deck\n4 Llanowar Elves (FDN) 227\n4 Shock (M21) 159\n12 Forest\n4 Mountain"
COLLECTION = ("name,set,collector_number,finish,quantity,condition,language,notes\n"
              "Llanowar Elves,fdn,227,nonfoil,5,NM,en,\nShock,m21,159,nonfoil,4,NM,en,\n"
              "Temple of Abandon,ths,224,nonfoil,2,NM,en,\nCastle Embereth,eld,239,nonfoil,1,NM,en,\n"
              "Sulfur Falls,dka,47,nonfoil,2,NM,en,\nRootbound Crag,xln,256,nonfoil,3,NM,en,\n"
              "Command Tower,cmr,350,nonfoil,1,NM,en,\n")


def _card(name, set_code, number, type_line, text, produced=(), identity=(), colours=(), cost="", cmc=0.0):
    return {"object": "card", "name": name, "layout": "normal", "set": set_code, "set_type": "expansion",
            "collector_number": number, "oracle_id": f"oracle-{set_code}-{number}", "mana_cost": cost, "cmc": cmc,
            "type_line": type_line, "oracle_text": text, "colors": list(colours), "color_identity": list(identity),
            "keywords": [], "produced_mana": list(produced), "legalities": {"commander": "legal"},
            "game_changer": False, "finishes": ["nonfoil"], "games": ["paper"], "digital": False,
            "prices": {"usd": "0.25", "usd_foil": None, "usd_etched": None},
            "image_uris": {"small": f"https://cards.example.com/{set_code}/{number}/small.jpg",
                           "normal": f"https://cards.example.com/{set_code}/{number}/normal.jpg"},
            "released_at": "2020-01-01", "oversized": False}


EXTRA = [
    _card("Shock", "m21", "159", "Instant", "Shock deals 2 damage to any target.", colours="R", identity="R",
          cost="{R}", cmc=1.0),
    _card("Xenagos, God of Revels", "ths", "207", "Legendary Enchantment Creature — God", "Indestructible.",
          colours="RG", identity="RG", cost="{3}{R}{G}", cmc=5.0),
    _card("Rootbound Crag", "xln", "256", "Land",
          "Rootbound Crag enters the battlefield tapped unless you control a Mountain or a Forest.\n"
          "{T}: Add {R} or {G}.", produced="GR", identity="GR"),
    _card("Temple of Abandon", "ths", "224", "Land",
          "Temple of Abandon enters the battlefield tapped.\nWhen Temple of Abandon enters, scry 1.\n"
          "{T}: Add {R} or {G}.", produced="GR", identity="GR"),
    _card("Sulfur Falls", "dka", "47", "Land",
          "Sulfur Falls enters the battlefield tapped unless you control an Island or a Mountain.\n"
          "{T}: Add {U} or {R}.", produced="RU", identity="RU"),
    _card("Castle Embereth", "eld", "239", "Land",
          "Castle Embereth enters the battlefield tapped unless you control a Mountain.\n{T}: Add {R}.",
          produced="R", identity="R"),
    _card("Command Tower", "cmr", "350", "Land",
          "{T}: Add one mana of any color in your commander's color identity.", produced="WUBRG"),
]


def stats(short="R", ok="G", table=True):
    """deck_stats' answer with a "colours" part: each colour of short short by 4, each of ok 3 to spare
    (no verdict at all without Karsten's table)."""
    rows = []
    for colour, margin in [(c, -4) for c in short] + [(c, 3) for c in ok]:
        rows.append({"colours": colour, "name": swaps.COLOUR_WORDS[colour], "ok": (margin >= 0) if table else None,
                     "hardest": {"have": 8 + margin, "needed": 8 if table else None,
                                 "margin": margin if table else None}})
    return {"kind": "constructed", "colours": {"table": 60 if table else None, "colours": rows}}


class DualLandsTestCase(base.SwapsTestCase):

    def setUp(self):
        super().setUp()
        cards_file = self.box.root / "cards.jsonl"
        _write(cards_file, (FIXTURES / "default_cards.jsonl").read_text(encoding="utf-8").rstrip("\n") + "\n"
               + "".join(json.dumps(c) + "\n" for c in EXTRA))
        index = cards.build_index(cards_file, FIXTURES / "oracle_tags.jsonl", BULK_DATES, log=lambda *a: None)
        cards.write_index(index, cards.INDEX_FILE)
        cards._index = None                 # the sandbox's patch puts the old value back afterwards
        _write(self.box.magic / "collection.csv", COLLECTION)
        self.write("gruul-short", base.deck_text(GRUUL, title="Gruul Short"))
        self.colours = stats()
        self.box.stats.side_effect = lambda sections, kind: self.colours

    def names(self, answer):
        return [(c["name"], c["free"], c["here"], c["max_qty"], c["replaces"]["name"]) for c in answer["lands"]]


class DualLandTests(DualLandsTestCase):

    def test_free_duals_making_the_short_colour_and_another(self):
        answer = api.swaps.suggest_dual_lands(DECK_ID)
        self.assertEqual((answer["deck_id"], answer["version"], answer["kind"], answer["colours"], answer["checked"]),
                         (DECK_ID, "target", "casual", ["R", "G"], True))
        self.assertEqual(answer["short"], [{"colour": "R", "name": "red", "have": 4, "needed": 8}])
        self.assertEqual(answer["basics"], 16)
        # Sulfur Falls makes blue (not castable here), Castle Embereth only red, Command Tower needs a commander:
        # the two red-green lands, each for a Forest (green isn't short), the one only maybe tapped first.
        self.assertEqual(self.names(answer), [("Rootbound Crag", 3, 3, 3, "Forest"),
                                              ("Temple of Abandon", 2, 2, 2, "Forest")])
        crag, temple = answer["lands"]
        self.assertEqual((crag["makes"], crag["fixes"], crag["tapped"], crag["basic"]), (["R", "G"], ["R"], "maybe", False))
        self.assertEqual(crag["replaces"], {"name": "Forest", "qty": 12})
        self.assertEqual(crag["note"]["text"], "A little weaker: makes red mana, which the deck is short of; "
                                               "keeps the green a Forest makes; may enter tapped.")
        self.assertEqual(temple["tapped"], "always")
        self.assertEqual((crag["default"]["set"], crag["default"]["number"]), ("xln", "256"))
        self.assertEqual(answer["more"], 0)
        self.assertEqual(tuple(answer[k] for k in ("rate", "rate_date")),
                         tuple(api.swaps.suggest_replacements(DECK_ID, card="Shock")[k] for k in ("rate", "rate_date")))
        # The colour check is the saved list's.
        sections, kind = self.box.stats.call_args[0]
        self.assertEqual((sorted(sections), kind), (["Deck"], "constructed"))

    def test_nothing_without_a_shortfall_or_a_verdict(self):
        self.colours = stats(short="", ok="RG")
        answer = api.swaps.suggest_dual_lands(DECK_ID)
        self.assertEqual((answer["checked"], answer["short"], answer["lands"]), (True, [], []))
        self.colours = stats(table=False)
        answer = api.swaps.suggest_dual_lands(DECK_ID)
        self.assertEqual((answer["checked"], answer["short"], answer["lands"]), (False, [], []))
        # Stats that fail say so, and offer nothing.
        self.box.stats.side_effect = RuntimeError("boom")
        answer = api.swaps.suggest_dual_lands(DECK_ID)
        self.assertEqual((answer["checked"], answer["lands"]), (False, []))
        self.assertTrue(any("stats couldn't be worked out" in w for w in answer["warnings"]))
        self.assertNotIn("boom", json.dumps(answer))

    def test_held_and_listed_copies_and_the_four_copy_cap(self):
        self.write("holder", base.deck_text("Deck\n3 Rootbound Crag (XLN) 256\n20 Forest", title="Holder",
                                            status="built"))
        self.write("gruul-short", base.deck_text(GRUUL + "\n2 Temple of Abandon (THS) 224", title="Gruul Short"))
        answer = api.swaps.suggest_dual_lands(DECK_ID)
        # The Crags are all in a built deck, the Temples all in the list itself.
        self.assertEqual(answer["lands"], [])
        _write(self.box.magic / "collection.csv", COLLECTION.replace("Temple of Abandon,ths,224,nonfoil,2",
                                                                     "Temple of Abandon,ths,224,nonfoil,6"))
        self.assertEqual(self.names(api.swaps.suggest_dual_lands(DECK_ID)), [("Temple of Abandon", 4, 4, 2, "Forest")])

    def test_which_basic_each_replaces(self):
        # Both colours short: the Forest's green stays, the red is gained.
        self.colours = stats(short="RG", ok="")
        crag = api.swaps.suggest_dual_lands(DECK_ID)["lands"][0]
        self.assertEqual((crag["replaces"]["name"], crag["fixes"]), ("Forest", ["R"]))
        self.assertIn("keeps the green a Forest makes", crag["note"]["text"])
        # Only Plains to swap out in a white, red and green deck: red is gained, a white source lost.
        self.write("gruul-short", base.deck_text("Deck\n2 Aerie Mystics (CON) 1\n4 Shock (M21) 159\n"
                                                 "4 Llanowar Elves (FDN) 227\n10 Plains", title="Gruul Short"))
        self.colours = stats(short="R", ok="WG")
        answer = api.swaps.suggest_dual_lands(DECK_ID)
        crag = answer["lands"][0]
        self.assertEqual((crag["name"], crag["replaces"], crag["note"]["severity"]),
                         ("Rootbound Crag", {"name": "Plains", "qty": 10}, 2))
        self.assertIn("no white mana in place of a Plains", crag["note"]["text"])
        # Only Mountains, of the short colour itself: replacing one gains nothing short, so nothing is offered.
        self.write("gruul-short", base.deck_text("Deck\n4 Llanowar Elves (FDN) 227\n4 Shock (M21) 159\n10 Mountain",
                                                 title="Gruul Short"))
        self.colours = stats()
        self.assertEqual(api.swaps.suggest_dual_lands(DECK_ID)["lands"], [])
        # No basics at all: nothing to replace.
        self.write("gruul-short", base.deck_text("Deck\n4 Llanowar Elves (FDN) 227\n4 Shock (M21) 159",
                                                 title="Gruul Short"))
        answer = api.swaps.suggest_dual_lands(DECK_ID)
        self.assertEqual((answer["basics"], answer["lands"]), (0, []))

    def test_a_commander_deck_one_copy_and_its_command_tower(self):
        deck = ("Commander\n1 Xenagos, God of Revels (THS) 207\n\nDeck\n1 Llanowar Elves (FDN) 227\n"
                "1 Shock (M21) 159\n60 Forest\n37 Mountain")
        self.write("xenagos", base.deck_text(deck, title="Xenagos", fmt="Commander"), kind="commander")
        answer = api.swaps.suggest_dual_lands("commander/xenagos")
        self.assertEqual((answer["kind"], answer["colours"]), ("commander", ["R", "G"]))
        self.assertEqual(self.box.stats.call_args[0][1], "commander")
        # Untapped first: the Tower, then the Crag that may enter tapped, then the Temple; one copy each.
        self.assertEqual(self.names(answer), [("Command Tower", 1, 1, 1, "Forest"), ("Rootbound Crag", 3, 3, 1, "Forest"),
                                              ("Temple of Abandon", 2, 2, 1, "Forest")])
        with mock.patch.object(swaps, "MAX_REPLACEMENTS", 1):
            answer = api.swaps.suggest_dual_lands("commander/xenagos")
        self.assertEqual((len(answer["lands"]), answer["more"]), (1, 2))

    def test_the_play_now_list_and_bad_requests(self):
        rest = ("\n## Substitutes\n\n### Substitute version (owned and incoming cards)\n\n```\n"
                "Deck\n4 Llanowar Elves (FDN) 227\n4 Shock (M21) 159\n1 Rootbound Crag (XLN) 256\n11 Forest\n"
                "4 Mountain\n```\n")
        self.write("gruul-short", base.deck_text(GRUUL, title="Gruul Short", rest=rest))
        answer = api.swaps.suggest_dual_lands(DECK_ID, "owned")
        self.assertEqual(answer["version"], "owned")
        self.assertEqual(self.names(answer)[0], ("Rootbound Crag", 2, 2, 2, "Forest"))
        self.assertEqual(answer["lands"][0]["replaces"], {"name": "Forest", "qty": 11})
        self.assertApiError(400, api.swaps.suggest_dual_lands, DECK_ID, "both")
        self.assertApiError(400, api.swaps.suggest_dual_lands, None)
        self.write("gruul-short", base.deck_text(GRUUL, title="Gruul Short"))
        self.assertApiError(404, api.swaps.suggest_dual_lands, DECK_ID, "owned")
        for deck_id in ("product/fdc-test-precon", "pairing/cats+elves"):
            with self.subTest(deck_id):
                self.assertApiError(400, api.swaps.suggest_dual_lands, deck_id, contains="Only a deck")

    def test_the_route(self):
        from decklab.lib import feature_routes
        handler = mock.Mock(command="GET")
        handler._query.return_value = {"id": DECK_ID, "version": "target"}
        handler._deck_id.return_value = DECK_ID
        self.assertTrue(feature_routes.dispatch(handler, ["deck", "dual-lands"], f"id={DECK_ID}&version=target"))
        status, answer = handler._send_json.call_args[0]
        self.assertEqual((status, answer["lands"][0]["name"]), (200, "Rootbound Crag"))


class RuleTests(DualLandsTestCase):

    def test_short_colours_reads_single_colours_only(self):
        summary = stats(short="R", ok="G")
        summary["colours"]["colours"].append({"colours": "RG", "name": "red or green", "ok": False,
                                              "hardest": {"have": 1, "needed": 2, "margin": -1}})
        short, margins = dual_lands.short_colours(summary)
        self.assertEqual(([s["colour"] for s in short], margins), (["R"], {"R": -4, "G": 3}))
        self.assertEqual(dual_lands.short_colours(None), ([], {}))
        self.assertEqual(dual_lands.short_colours({"colours": None}), ([], {}))

    def test_the_replaced_basic_prefers_no_loss_then_the_most_to_spare(self):
        basics = {"Plains": 5, "Island": 8, "Forest": 2}
        self.assertEqual(dual_lands.replaced_basic({"R", "G"}, {"R"}, basics, {}), ("Forest", 0))
        self.assertEqual(dual_lands.replaced_basic({"R", "B"}, {"R"}, basics, {"W": 1, "U": 4}), ("Island", 2))
        self.assertEqual(dual_lands.replaced_basic({"R", "B"}, {"R"}, basics, {"W": 6, "U": 4}), ("Plains", 2))
        self.assertEqual(dual_lands.replaced_basic({"R", "G"}, {"R", "W", "U"}, {"Mountain": 3, "Plains": 4}, {}),
                         (None, None))
        self.assertEqual(dual_lands.tapped({"oracle_text": "{T}: Add {R} or {G}."}), None)

    def test_a_land_making_only_colourless_is_no_dual(self):
        # Kessig Wolf Run's identity is red and green (its ability's cost), but it taps only for colourless.
        wolf_run = _card("Kessig Wolf Run", "isd", "243", "Land",
                         "{T}: Add {C}.\n{X}{R}{G}, {T}: Target creature gets +X/+0 and gains trample until end "
                         "of turn.", produced="C", identity="RG")
        crag = next(c for c in EXTRA if c["name"] == "Rootbound Crag")
        self.assertEqual(dual_lands.makes_colours(wolf_run), set())
        found = dual_lands.dual_lands([("Kessig Wolf Run", 2, wolf_run), ("Rootbound Crag", 1, crag)],
                                      {"R", "G"}, "casual", {"R"}, {"Forest": 12, "Mountain": 4}, {"G": 3},
                                      {}, {"Kessig Wolf Run": 2, "Rootbound Crag": 1})
        self.assertEqual([entry["name"] for _, entry in found], ["Rootbound Crag"])
        self.assertEqual(dual_lands.tapped({"card_faces": [{"oracle_text": "This land enters tapped."}]}), "always")


class DualLandPrivacyTests(DualLandsTestCase):

    def setUp(self):
        super().setUp()
        _write(self.box.root / "config.json", json.dumps(ROLES))
        _write(self.box.magic / "people" / "user2" / "collection.csv",
               "name,set,collector_number,finish,quantity,condition,language,notes\n"
               "Temple of Abandon,ths,224,nonfoil,1,NM,en,\n")
        self.write("r-gruul", base.deck_text(GRUUL, title="User2 Gruul"), space="user2")

    def test_a_hidden_deck_is_missing_before_anything_else(self):
        with _as("user1"):
            self.assertApiError(404, api.swaps.suggest_dual_lands, "user2/casual/r-gruul", contains="No deck")
            self.assertApiError(404, api.swaps.suggest_dual_lands, "user2/casual/r-gruul", "both")
        with _as("user2"):
            self.assertApiError(404, api.swaps.suggest_dual_lands, DECK_ID)

    def test_a_public_deck_without_its_inventory_shows_no_lands(self):
        with mock.patch.object(guard, "public_deck_spaces", return_value={"user2"}), _as("user1"):
            error = self.assertApiError(403, api.swaps.suggest_dual_lands, "user2/casual/r-gruul")
            self.assertEqual(error.message, guard.COLLECTION_HIDDEN)
            self.assertApiError(403, api.swaps.suggest_dual_lands, "user2/casual/r-gruul", "both")
        self.box.stats.assert_not_called()          # refused before the colour check is worked out

    def test_a_members_space_uses_its_own_pool(self):
        with _as("user2"):
            answer = api.swaps.suggest_dual_lands("user2/casual/r-gruul")
        # Only User2's one Temple: home's Crags and Temples don't count here.
        self.assertEqual(self.names(answer), [("Temple of Abandon", 1, 1, 1, "Forest")])

    def test_no_other_decks_title_in_the_answer(self):
        self.write("holder", base.deck_text("Deck\n1 Rootbound Crag (XLN) 256\n20 Forest", title="Secret Holder",
                                            status="built"))
        with _as("matt"):
            answer = api.swaps.suggest_dual_lands(DECK_ID)
        self.assertEqual(self.names(answer)[0], ("Rootbound Crag", 2, 2, 2, "Forest"))
        text = json.dumps(answer)
        for hidden in ("Secret Holder", "casual/holder", "Beginner Box", "Test Precon", "User2"):
            self.assertNotIn(hidden, text)
