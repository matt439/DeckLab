"""Commanders we could build (E9-S28, first slice): GET /api/commanders/candidates
(lib/api/commander_candidates.py) and the ranking it uses (lib/decks/commander_pool.py candidates).

The API tests run in test_role_cards' sandbox (test_api's Sandbox with the fixture card index: ramp holds
Llanowar Elves, Elvish Mystic and Sol Ring, removal Pick Your Poison, Wrath of God and Fire // Ice, draw
Rhystic Study and Fire // Ice, the sweeper tag Wrath of God; no fixture card is a counterspell). The fixture
commanders are Ghalta, Primal Hunger (G) and Abaddon the Despoiler (U B R). The Beginner Box is kept intact
(holding 2 Llanowar Elves, the Elvish Mystic and a Pick Your Poison) and the preordered precon brings a Sol
Ring. Nothing here writes to a database or needs the PC's card data.

Run from the repo root: python scripts/test_fixtures.py decklab.tests.test_commander_candidates
"""
import json
import unittest
from unittest import mock

from decklab.lib.api import commander_candidates as api
from decklab.lib.api import guard
from decklab.lib.decks import commander_pool
from decklab.lib.stats import role_targets
from decklab.tests import test_role_cards as roles
from decklab.tests import test_swaps_api as base
from decklab.tests.test_api import _write
from decklab.tests.test_collection_edit import ROLES
from decklab.tests.test_deck_privacy_readers import _as

COLLECTION = roles.COLLECTION + ('"Ghalta, Primal Hunger",rix,130,nonfoil,1,NM,en,\n'
                                 "Abaddon the Despoiler,40k,319,nonfoil,1,NM,en,\n")


class CandidatesTestCase(base.SwapsTestCase):

    def setUp(self):
        super().setUp()
        _write(self.box.magic / "collection.csv", COLLECTION)

    @staticmethod
    def counts(row):
        return {p["category"]: p["count"] for p in row["categories"]}


class CandidatesApiTests(CandidatesTestCase):

    def test_free_commanders_ranked_by_the_role_targets_they_cover(self):
        answer = api.candidates_view()
        self.assertEqual((answer["space"], answer["total"], answer["tags_available"]), ("home", 2, True))
        self.assertEqual([c["name"] for c in answer["candidates"]], ["Abaddon the Despoiler", "Ghalta, Primal Hunger"])
        abaddon, ghalta = answer["candidates"]
        # Abaddon (U B R): the coming Sol Ring, Rhystic Study and Fire // Ice draw, Fire // Ice removal.
        self.assertEqual(abaddon["colours"], ["U", "B", "R"])
        self.assertEqual(self.counts(abaddon), {"lands": 0, "ramp": 1, "card advantage": 2, "targeted disruption": 1,
                                                "mass disruption": 0, "plan": None})
        self.assertEqual((abaddon["covered"], abaddon["of"], abaddon["share"]), (4, 40, 0.1))
        # One owned, one coming with the preordered precon (its commander).
        self.assertEqual((abaddon["cards"], abaddon["lands"], abaddon["free"]), (3, 0, 2))
        # Ghalta (G): 3 free Llanowar Elves (the box holds 2) and the Sol Ring; 1 of the 2 Pick Your Poisons.
        # The Elvish Mystic is the box's; Wrath of God is white.
        self.assertEqual(self.counts(ghalta)["ramp"], 2)
        self.assertEqual(self.counts(ghalta)["targeted disruption"], 1)
        self.assertEqual((ghalta["covered"], ghalta["cards"]), (3, 3))
        self.assertEqual(ghalta["short"], ["Ramp", "Card advantage", "Targeted disruption", "Mass disruption"])
        self.assertEqual(ghalta["card"]["name"], "Ghalta, Primal Hunger")
        self.assertEqual(answer["source"]["id"], role_targets.SOURCE_ID)

    def test_a_commander_a_built_deck_holds_isnt_a_candidate(self):
        self.write("holder", base.deck_text(roles.GHALTA, title="Secret Holder", fmt="Commander", status="built"),
                   kind="commander")
        names = [c["name"] for c in api.candidates_view()["candidates"]]
        self.assertEqual(names, ["Abaddon the Despoiler"])
        self.assertNotIn("Secret Holder", json.dumps(api.candidates_view()))

    def test_limit_and_bad_requests(self):
        answer = api.candidates_view(limit="1")
        self.assertEqual((len(answer["candidates"]), answer["total"]), (1, 2))
        self.assertApiError(400, api.candidates_view, None, "0")
        self.assertApiError(400, api.candidates_view, None, "201")

    def test_the_route(self):
        from decklab.lib import feature_routes
        handler = mock.Mock(command="GET")
        handler._query.return_value = {}
        self.assertTrue(feature_routes.dispatch(handler, ["commanders", "candidates"], ""))
        status, answer = handler._send_json.call_args[0]
        self.assertEqual((status, answer["total"]), (200, 2))


class CandidatesPrivacyTests(CandidatesTestCase):

    def setUp(self):
        super().setUp()
        _write(self.box.root / "config.json", json.dumps(ROLES))
        _write(self.box.magic / "people" / "user2" / "collection.csv",
               "name,set,collector_number,finish,quantity,condition,language,notes\n"
               '"Ghalta, Primal Hunger",rix,130,nonfoil,1,NM,en,\n'
               "Elvish Mystic,cmm,648,nonfoil,2,NM,en,\n")

    def test_only_the_spaces_own_people_see_it(self):
        with _as("user2"):
            error = self.assertApiError(403, api.candidates_view, "home")
            self.assertEqual(error.message, guard.COLLECTION_HIDDEN)
            answer = api.candidates_view("user2")
        self.assertEqual([c["name"] for c in answer["candidates"]], ["Ghalta, Primal Hunger"])
        self.assertEqual(self.counts(answer["candidates"][0])["ramp"], 1)       # one Elvish Mystic counts once
        for profile in ("matt", "user1"):
            with self.subTest(profile), _as(profile):
                self.assertApiError(403, api.candidates_view, "user2")
                self.assertEqual(api.candidates_view()["total"], 2)


def _card(name, identity="", roles=(), legality="legal", type_line="Creature", leads=False):
    return {"name": name, "color_identity": list(identity), "roles": list(roles), "commander_legality": legality,
            "type_line": type_line, "leads": leads}


class RankingTests(unittest.TestCase):

    def rank(self, known, free):
        return commander_pool.candidates(free, known.get, lambda c: c["leads"], role_targets.CATEGORIES,
                                         lambda c: ["partner"] if c["name"] == "Pair" else [])

    def test_the_rules(self):
        known = {c["name"]: c for c in (
            _card("Green Lead", "G", leads=True), _card("Red Lead", "R", leads=True),
            _card("Banned Lead", "G", legality="banned", leads=True), _card("Pair", "", leads=True),
            _card("Elf", "G", ("ramp",)), _card("Bolt", "R", ("removal",)), _card("Wipe", "R", ("removal", "board wipe")),
            _card("Rock", "", ("ramp",)), _card("Grove", "G", type_line="Land — Forest"),
            _card("Gruul Thing", "RG", ("ramp", "draw")), _card("Banned Ramp", "G", ("ramp",), legality="banned"))}
        free = {name: 1 for name in known} | {"Elf": 4, "Not A Card": 1, "Zero": 0}
        ranked = self.rank(known, free)
        self.assertEqual([c["name"] for c in ranked], ["Red Lead", "Green Lead", "Pair"])
        red, green, pair = ranked
        # Red covers 3, Green 2. Green: Elf (4 copies count once), Rock; Grove a land; Gruul Thing fits neither.
        # The other leads are creatures that fit too: Pair (colourless) is a card for both.
        self.assertEqual({p["category"]: p["count"] for p in green["categories"]}["ramp"], 2)
        self.assertEqual((green["lands"], green["cards"], green["covered"]), (1, 3, 2))
        # Red: Rock's ramp, Bolt targeted, Wipe only mass.
        counts = {p["category"]: p["count"] for p in red["categories"]}
        self.assertEqual((counts["ramp"], counts["targeted disruption"], counts["mass disruption"]), (1, 1, 1))
        self.assertEqual(red["covered"], 3)
        self.assertEqual((pair["colours"], pair["partner"], pair["covered"]), ([], ["partner"], 1))
        self.assertTrue(all(c["of"] == 40 for c in ranked))
        self.assertFalse(next(p for p in green["categories"] if p["category"] == "lands")["in_coverage"])
        self.assertIsNone(next(p for p in green["categories"] if p["category"] == "plan")["count"])

    def test_a_target_met_caps_its_share(self):
        known = {"Lead": _card("Lead", "G", leads=True)}
        known.update({f"Ramp {i}": _card(f"Ramp {i}", "G", ("ramp",)) for i in range(15)})
        row = self.rank(known, {name: 1 for name in known})[0]
        ramp = next(p for p in row["categories"] if p["category"] == "ramp")
        self.assertEqual((ramp["count"], ramp["short"], row["covered"]), (15, False, 10))
        self.assertNotIn("Ramp", row["short"])


if __name__ == "__main__":
    unittest.main()


class CandidateCardsApiTests(CandidatesTestCase):
    """E9-S28's second slice: GET /api/commanders/candidate, one candidate's free cards by name."""

    @staticmethod
    def names(part):
        return [c["name"] for c in part["cards"]]

    def test_each_categorys_free_cards_by_name(self):
        answer = api.candidate_view("Abaddon the Despoiler")
        self.assertEqual((answer["space"], answer["name"], answer["colours"]), ("home", "Abaddon the Despoiler", ["U", "B", "R"]))
        parts = {p["category"]: p for p in answer["categories"]}
        self.assertNotIn("plan", parts)
        self.assertEqual(self.names(parts["ramp"]), ["Sol Ring"])
        self.assertEqual(sorted(self.names(parts["card advantage"])), ["Fire // Ice", "Rhystic Study"])
        self.assertEqual(self.names(parts["targeted disruption"]), ["Fire // Ice"])
        self.assertEqual((parts["mass disruption"]["count"], parts["mass disruption"]["short"]), (0, True))
        self.assertEqual(parts["ramp"]["cards"][0]["card"]["name"], "Sol Ring")
        self.assertEqual(answer["others"]["count"], 0)
        self.assertEqual(answer["source"]["id"], role_targets.SOURCE_ID)

    def test_a_name_in_any_case_resolves(self):
        self.assertEqual(api.candidate_view("ghalta, primal hunger")["name"], "Ghalta, Primal Hunger")

    def test_not_a_candidate(self):
        self.assertApiError(400, api.candidate_view, None)
        self.assertApiError(400, api.candidate_view, "x" * 151)
        self.assertApiError(404, api.candidate_view, "Sol Ring")              # may not lead
        self.write("holder", base.deck_text(roles.GHALTA, title="Secret Holder", fmt="Commander", status="built"),
                   kind="commander")
        error = self.assertApiError(404, api.candidate_view, "Ghalta, Primal Hunger")
        self.assertNotIn("Secret Holder", error.message)

    def test_the_route(self):
        from decklab.lib import feature_routes
        handler = mock.Mock(command="GET")
        handler._query.return_value = {"name": "Abaddon the Despoiler"}
        self.assertTrue(feature_routes.dispatch(handler, ["commanders", "candidate"], ""))
        status, answer = handler._send_json.call_args[0]
        self.assertEqual((status, answer["name"]), (200, "Abaddon the Despoiler"))

    def test_only_the_spaces_own_people(self):
        _write(self.box.root / "config.json", json.dumps(ROLES))
        with _as("user2"):
            error = self.assertApiError(403, api.candidate_view, "Ghalta, Primal Hunger", "home")
        self.assertEqual(error.message, guard.COLLECTION_HIDDEN)


class CardsForTests(unittest.TestCase):

    def test_lists_capped_and_others(self):
        known = {"Lead": _card("Lead", "G", leads=True), "Grove": _card("Grove", "G", type_line="Land — Forest"),
                 "Bear": _card("Bear", "G"), "Red": _card("Red", "R", ("ramp",))}
        known.update({f"Ramp {i}": _card(f"Ramp {i}", "G", ("ramp",)) for i in range(5)})
        free = {name: 1 for name in known} | {"Ramp 0": 3}
        found = commander_pool.cards_for("Lead", free, known.get, lambda c: c["leads"], role_targets.CATEGORIES, limit=3)
        parts = {p["category"]: p for p in found["categories"]}
        self.assertEqual((parts["ramp"]["count"], len(parts["ramp"]["cards"]), parts["ramp"]["more"]), (5, 3, 2))
        self.assertEqual(parts["ramp"]["cards"][0], {"name": "Ramp 0", "free": 3})
        self.assertEqual([c["name"] for c in parts["lands"]["cards"]], ["Grove"])
        self.assertFalse(parts["lands"]["in_coverage"])
        self.assertEqual(found["others"], {"cards": [{"name": "Bear", "free": 1}], "more": 0, "count": 1})
        self.assertIsNone(commander_pool.cards_for("Bear", free, known.get, lambda c: c["leads"], role_targets.CATEGORIES))
        self.assertIsNone(commander_pool.cards_for("Nope", free, known.get, lambda c: c["leads"], role_targets.CATEGORIES))
