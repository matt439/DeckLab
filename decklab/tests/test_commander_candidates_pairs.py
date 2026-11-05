"""Commanders we could build, E9-S28's third slice: pairs of commanders counted together and a held
commander's row naming the deck holding it (lib/decks/commander_pool.py pairs and held,
lib/api/commander_candidates.py).

The API tests run in test_commander_candidates' sandbox (its fixture collection, Ghalta, Primal Hunger (G)
and Abaddon the Despoiler (U B R) its commanders), with a few invented cards added to the card lookup and
the free copies: two partners, a Choose a Background commander, a Background and a Friends forever pair.
The pairing rules are lib/stats/commander.py's own (_pairing, _can_be_commander), read from the invented
cards' text. Nothing here writes to a database or needs the PC's card data.

Run from the repo root: python scripts/test_fixtures.py decklab.tests.test_commander_candidates_pairs
"""
import json
import unittest
from collections import Counter
from unittest import mock

from decklab.lib import pool
from decklab.lib.api import commander_candidates as api
from decklab.lib.decks import commander_pool
from decklab.lib.stats import role_targets
from decklab.tests import test_commander_candidates as base
from decklab.tests import test_role_cards as roles
from decklab.tests.test_api import _write
from decklab.tests.test_collection_edit import ROLES
from decklab.tests.test_deck_privacy_readers import _as


def _invented(name, identity, type_line, text, roles_=()):
    return {"name": name, "type_line": type_line, "oracle_text": text, "layout": "normal",
            "color_identity": list(identity), "colors": list(identity), "roles": list(roles_),
            "commander_legality": "legal", "mana_cost": "", "cmc": 3.0, "printings": [],
            "power": "2" if "Creature" in type_line else None, "toughness": "2" if "Creature" in type_line else None}


INVENTED = {c["name"]: c for c in (
    _invented("Green Partner", "G", "Legendary Creature — Elf", "Partner"),
    _invented("Blue Partner", "U", "Legendary Creature — Merfolk", "Flying\nPartner (You can have two commanders if both have partner.)"),
    _invented("Red Chooser", "R", "Legendary Creature — Human", "Haste\nChoose a Background"),
    _invented("White Background", "W", "Legendary Enchantment — Background", "Commander creatures you own have lifelink."),
    _invented("Black Friend", "B", "Legendary Creature — Human", "Friends forever"),
    _invented("White Friend", "W", "Legendary Creature — Human", "Friends forever"),
)}


class PairsApiTests(base.CandidatesTestCase):

    def setUp(self):
        super().setUp()
        real_card, real_free = api.cards.card, pool.free_copies
        self.enterContext(mock.patch.object(api.cards, "card", lambda name: INVENTED.get(name) or real_card(name)))
        self.enterContext(mock.patch.object(api.pool, "free_copies",
                                            lambda p, exclude=(): real_free(p, exclude) + Counter(dict.fromkeys(INVENTED, 1))))

    def by_name(self, rows):
        return {r["name"]: r for r in rows}

    def test_pairs_rank_with_the_singles_over_both_colours(self):
        answer = api.candidates_view(limit="200")
        rows = self.by_name(answer["candidates"])
        pair = rows["Blue Partner and Green Partner"]
        self.assertEqual((pair["kind"], pair["names"], pair["colours"], pair["pairing"]),
                         ("pair", ["Blue Partner", "Green Partner"], ["U", "G"], "partner"))
        self.assertEqual([f["name"] for f in pair["faces"]], ["Blue Partner", "Green Partner"])
        self.assertEqual([f["free"] for f in pair["faces"]], [1, 1])
        # Green alone: Ghalta's green cards; with blue, Rhystic Study draws too.
        green = rows["Green Partner"]
        self.assertEqual((green["kind"], green["partner"]), ("single", ["partner"]))
        self.assertEqual(self.counts(pair)["card advantage"], self.counts(green)["card advantage"] + 1)
        self.assertEqual(self.counts(pair)["ramp"], self.counts(green)["ramp"])
        self.assertGreater(pair["covered"], green["covered"])
        background = rows["Red Chooser and White Background"]
        self.assertEqual((background["names"], background["colours"], background["pairing"]),
                         (["Red Chooser", "White Background"], ["W", "R"], "Choose a Background"))
        friends = rows["Black Friend and White Friend"]
        self.assertEqual(friends["pairing"], "partner—Friends forever")
        # A Background never leads alone, and only matching abilities pair.
        self.assertNotIn("White Background", rows)
        for name in ("Green Partner and White Background", "Black Friend and Green Partner",
                     "Blue Partner and Red Chooser", "Red Chooser and White Friend"):
            self.assertNotIn(name, rows)
        self.assertEqual(answer["pairs"], {"found": 3, "left_out": 0, "untried": 0})
        self.assertEqual(answer["total"], len(answer["candidates"]))
        # The same coverage figure ranks them all together, best first.
        shares = [r["share"] for r in answer["candidates"]]
        self.assertEqual(shares, sorted(shares, reverse=True))

    def test_one_pairs_free_cards(self):
        found = api.candidate_view("Green Partner", None, "Blue Partner")
        self.assertEqual((found["names"], found["name"], found["colours"], found["pairing"], found["held_by"]),
                         (["Green Partner", "Blue Partner"], "Green Partner and Blue Partner", ["U", "G"], "partner", []))
        parts = {p["category"]: p for p in found["categories"]}
        self.assertIn("Rhystic Study", [c["name"] for c in parts["card advantage"]["cards"]])
        self.assertIn("Sol Ring", [c["name"] for c in parts["ramp"]["cards"]])
        self.assertNotIn("Green Partner", json.dumps(parts))           # the commanders aren't their own cards
        background = api.candidate_view("Red Chooser", None, "White Background")
        self.assertEqual(background["pairing"], "Choose a Background")

    def test_pairs_that_arent_one(self):
        for name, partner in (("Green Partner", "White Background"), ("White Background", "White Background"),
                              ("Black Friend", "Green Partner"), ("Ghalta, Primal Hunger", "Green Partner")):
            with self.subTest(name=name, partner=partner):
                error = self.assertApiError(404, api.candidate_view, name, None, partner)
                self.assertIn("commanders together", error.message)
        self.assertApiError(404, api.candidate_view, "White Background")        # never alone
        self.assertApiError(400, api.candidate_view, "Green Partner", None, "x" * 151)

    def test_the_route_takes_a_partner(self):
        from decklab.lib import feature_routes
        handler = mock.Mock(command="GET")
        handler._query.return_value = {"name": "Green Partner", "partner": "Blue Partner"}
        self.assertTrue(feature_routes.dispatch(handler, ["commanders", "candidate"], ""))
        status, answer = handler._send_json.call_args[0]
        self.assertEqual((status, answer["names"]), (200, ["Green Partner", "Blue Partner"]))

    def test_the_pair_caps_are_said(self):
        with mock.patch.object(commander_pool, "MAX_PAIRS", 1):
            answer = api.candidates_view(limit="200")
        self.assertEqual(answer["pairs"], {"found": 3, "left_out": 2, "untried": 0})
        self.assertEqual(sum(r["kind"] == "pair" for r in answer["candidates"]), 1)


class HeldApiTests(base.CandidatesTestCase):

    def setUp(self):
        super().setUp()
        self.write("holder", base.base.deck_text(roles.GHALTA, title="Ghalta Stompy", fmt="Commander", status="built"),
                   kind="commander")

    def test_a_held_commander_is_a_row_naming_its_deck(self):
        answer = api.candidates_view()
        self.assertNotIn("Ghalta, Primal Hunger", [c["name"] for c in answer["candidates"]])
        self.assertEqual(answer["held_total"], 1)
        ghalta = answer["held"][0]
        self.assertEqual((ghalta["kind"], ghalta["name"], ghalta["free"], ghalta["colours"]),
                         ("held", "Ghalta, Primal Hunger", 0, ["G"]))
        self.assertEqual(ghalta["held_by"], [{"id": "commander/holder", "title": "Ghalta Stompy", "quantity": 1}])
        # Counted against the free pool as a candidate is: the green ramp still there.
        self.assertEqual(self.counts(ghalta)["ramp"], 2)
        found = api.candidate_view("Ghalta, Primal Hunger")
        self.assertEqual(found["held_by"], ghalta["held_by"])
        self.assertIn("Sol Ring", [c["name"] for p in found["categories"] for c in p["cards"]])

    def test_a_deck_the_viewer_may_not_see_isnt_named(self):
        with mock.patch.object(api.guard, "deck_reader", lambda profile=False: lambda target: False):
            answer = api.candidates_view()
            found = api.candidate_view("Ghalta, Primal Hunger")
        hidden = [{"id": None, "title": "one of the home decks", "quantity": 1}]
        self.assertEqual(answer["held"][0]["held_by"], hidden)
        self.assertEqual(found["held_by"], hidden)
        self.assertNotIn("Ghalta Stompy", json.dumps(answer) + json.dumps(found))


class HeldPrivacyTests(base.CandidatesTestCase):

    def setUp(self):
        super().setUp()
        _write(self.box.root / "config.json", json.dumps(ROLES))
        _write(self.box.magic / "people" / "user2" / "collection.csv",
               "name,set,collector_number,finish,quantity,condition,language,notes\n"
               '"Ghalta, Primal Hunger",rix,130,nonfoil,1,NM,en,\n')
        self.write("stomp", base.base.deck_text(roles.GHALTA, title="Member Stomp", fmt="Commander", status="built"),
                   kind="commander", space="user2")

    def test_a_member_sees_their_own_holder_and_nobody_else_does(self):
        with _as("user2"):
            answer = api.candidates_view("user2")
            self.assertApiError(403, api.candidates_view, "home")
        self.assertEqual(answer["held"][0]["held_by"],
                         [{"id": "user2/commander/stomp", "title": "Member Stomp", "quantity": 1}])
        for profile in ("matt", "user1"):
            with self.subTest(profile), _as(profile):
                self.assertApiError(403, api.candidates_view, "user2")
                self.assertApiError(403, api.candidate_view, "Ghalta, Primal Hunger", "user2")
                self.assertNotIn("Member Stomp", json.dumps(api.candidates_view()))


def _card(name, identity="", roles_=(), type_line="Creature", leads=False, pairs_with=None, printings=1):
    return {**base._card(name, identity, roles_, type_line=type_line, leads=leads), "pairs_with": pairs_with,
            "printings": [("x", str(i)) for i in range(printings)]}


def _rule(a, b):
    return "partner" if a["pairs_with"] and a["pairs_with"] == b["pairs_with"] else None


class PairRankingTests(unittest.TestCase):

    def test_pairs_count_the_union_and_cap(self):
        known = {c["name"]: c for c in (
            _card("P1", "G", leads=True, pairs_with="p", printings=5), _card("P2", "U", leads=True, pairs_with="p", printings=4),
            _card("P3", "R", leads=True, pairs_with="p", printings=3), _card("P4", "B", leads=True, pairs_with="p", printings=2),
            _card("P5", "W", leads=True, pairs_with="p", printings=1), _card("Q", "G", leads=True),
            _card("Elf", "G", ("ramp",)), _card("Study", "U", ("draw",)), _card("Bolt", "R", ("removal",)))}
        free = dict.fromkeys(known, 1)
        rows, caps = commander_pool.pairs(free, known.get, lambda c: c["pairs_with"] is not None, _rule,
                                          role_targets.CATEGORIES)
        self.assertEqual(caps, {"found": 10, "left_out": 0, "untried": 0})
        p12 = next(r for r in rows if r["names"] == ["P1", "P2"])
        counts = {p["category"]: p["count"] for p in p12["categories"]}
        self.assertEqual((counts["ramp"], counts["card advantage"], counts["targeted disruption"]), (1, 1, 0))
        # Q, Elf and Study fit (P1 and P2 are the commanders; the other halves are off colour).
        self.assertEqual((p12["covered"], p12["cards"], p12["colours"]), (2, 3, ["U", "G"]))
        # Capped: the 3 most-printed halves tried (3 pairs), 2 kept.
        rows, caps = commander_pool.pairs(free, known.get, lambda c: c["pairs_with"] is not None, _rule,
                                          role_targets.CATEGORIES, max_pairable=3, max_pairs=2)
        self.assertEqual(caps, {"found": 3, "left_out": 1, "untried": 2})
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(set(r["names"]) <= {"P1", "P2", "P3"} for r in rows))

    def test_a_pair_needs_both_free(self):
        known = {"P1": _card("P1", "G", leads=True, pairs_with="p"), "P2": _card("P2", "U", leads=True, pairs_with="p")}
        rows, caps = commander_pool.pairs({"P1": 1, "P2": 0}, known.get, lambda c: True, _rule, role_targets.CATEGORIES)
        self.assertEqual((rows, caps["found"]), ([], 0))

    def test_held_rows(self):
        known = {"Lead": _card("Lead", "G", leads=True), "Held": _card("Held", "G", leads=True),
                 "Elf": _card("Elf", "G", ("ramp",)), "Held Elf": _card("Held Elf", "G", ("ramp",)),
                 "Banned": {**_card("Banned", "G", leads=True), "commander_legality": "banned"}}
        owned = {"Lead": 1, "Held": 2, "Elf": 1, "Held Elf": 1, "Banned": 1}
        free = {"Lead": 1, "Elf": 1}
        rows = commander_pool.held(owned, free, known.get, lambda c: c["leads"], role_targets.CATEGORIES)
        self.assertEqual([(r["kind"], r["name"]) for r in rows], [("held", "Held")])
        ramp = next(p for p in rows[0]["categories"] if p["category"] == "ramp")
        self.assertEqual((ramp["count"], rows[0]["cards"]), (1, 2))       # the free Elf and the free Lead
        found = commander_pool.cards_for("Held", free, known.get, lambda c: c["leads"], role_targets.CATEGORIES,
                                         held=["Held"])
        self.assertEqual(next(p for p in found["categories"] if p["category"] == "ramp")["cards"],
                         [{"name": "Elf", "free": 1}])
        self.assertIsNone(commander_pool.cards_for("Held", free, known.get, lambda c: c["leads"], role_targets.CATEGORIES))


if __name__ == "__main__":
    unittest.main()
