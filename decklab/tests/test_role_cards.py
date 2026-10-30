"""Free pool cards for each of a Commander deck's Stats roles (E9-S26): GET /api/deck/role-cards
(lib/api/role_cards.py) and the rules it uses (lib/decks/role_pool.py free_by_role).

The API tests run in test_swaps_api's SwapsTestCase (test_api's Sandbox, with the files backend and its
fixture card index built from tests/fixtures' default_cards and oracle_tags: ramp holds Llanowar Elves,
Elvish Mystic and Sol Ring, removal Pick Your Poison, Wrath of God and Fire // Ice, draw Rhystic Study and
Fire // Ice; no fixture card is a counterspell). The Beginner Box is kept intact (holding 2 Llanowar Elves,
the Elvish Mystic and a Pick Your Poison) and the preordered precon brings a Sol Ring. Nothing here writes
to a database or needs the PC's card data.
"""
import json
import unittest
from unittest import mock

from decklab.lib import cards
from decklab.lib.api import guard, role_cards
from decklab.lib.decks import role_pool
from decklab.tests import test_swaps_api as base
from decklab.tests.test_api import _write
from decklab.tests.test_collection_edit import ROLES
from decklab.tests.test_deck_privacy_readers import _as

GHALTA_ID = "commander/ghalta"
GHALTA = "Commander\n1 Ghalta, Primal Hunger (RIX) 130\n\nDeck\n1 Llanowar Elves (FDN) 227\n98 Forest"
COLLECTION = ("name,set,collector_number,finish,quantity,condition,language,notes\n"
              "Fire // Ice,apc,128,nonfoil,1,NM,en,\n"
              "Llanowar Elves,fdn,227,nonfoil,5,NM,en,\n"
              "Elvish Mystic,cmm,648,nonfoil,1,NM,en,\n"
              "Pick Your Poison,mkm,170,nonfoil,2,NM,en,\n"
              "Rhystic Study,wot,25,nonfoil,1,NM,en,\n"
              "Wrath of God,8ed,58,nonfoil,1,NM,en,\n")


def commander_text(deck=GHALTA, title="Ghalta"):
    return base.deck_text(deck, title=title, fmt="Commander")


class RoleCardsTestCase(base.SwapsTestCase):

    def setUp(self):
        super().setUp()
        _write(self.box.magic / "collection.csv", COLLECTION)
        self.write("ghalta", commander_text(), kind="commander")

    def listed(self, answer):
        """{role: [(name, free, here)]} of the roles that list something, and their "more"."""
        return {r["role"]: [(c["name"], c["free"], c["here"]) for c in r["cards"]]
                for r in answer["roles"] if r["cards"] or r["more"]}


class RoleCardsTests(RoleCardsTestCase):

    def test_free_cards_in_the_commanders_colours_for_each_role(self):
        answer = role_cards.role_cards(GHALTA_ID)
        self.assertEqual((answer["deck_id"], answer["version"], answer["colours"], answer["tags_available"]),
                         (GHALTA_ID, "target", ["G"], True))
        self.assertEqual([r["role"] for r in answer["roles"]], list(cards.ROLES))
        # Llanowar Elves is in the list, the only Elvish Mystic in the intact Beginner Box: the Sol Ring
        # coming with the preordered precon is free, not here yet. One of the 2 Pick Your Poisons is the
        # box's. Rhystic Study (U), Wrath of God (W) and Fire // Ice (U R) are outside Ghalta's colours.
        self.assertEqual(self.listed(answer), {"ramp": [("Sol Ring", 1, 0)],
                                               "removal": [("Pick Your Poison", 1, 1)]})
        ring = next(r for r in answer["roles"] if r["role"] == "ramp")["cards"][0]
        self.assertEqual((ring["card"]["name"], ring["card"]["roles"]), ("Sol Ring", ["ramp"]))
        wipe = next(r for r in answer["roles"] if r["role"] == "board wipe")
        self.assertEqual((wipe["tag"], wipe["tagged"], wipe["cards"], wipe["more"]), ("sweeper", True, [], 0))
        # The fixture tag file has no counterspell cards: that role is untagged, the rest still answer.
        counter = next(r for r in answer["roles"] if r["role"] == "counterspell")
        self.assertEqual((counter["tagged"], counter["cards"]), (False, []))

    def test_a_wider_identity_and_the_play_now_list(self):
        deck = "Commander\n1 Abaddon the Despoiler (40K) 319\n\nDeck\n1 Rhystic Study (WOT) 25\n98 Island"
        rest = ("\n## Substitutes\n\n### Substitute version (owned and incoming cards)\n\n```\n"
                "Commander\n1 Abaddon the Despoiler (40K) 319\n\nDeck\n1 Fire // Ice (APC) 128\n98 Island\n```\n")
        self.write("abaddon", base.deck_text(deck, title="Abaddon", fmt="Commander", rest=rest), kind="commander")
        answer = role_cards.role_cards("commander/abaddon")
        self.assertEqual(answer["colours"], ["U", "B", "R"])
        self.assertEqual(self.listed(answer), {"ramp": [("Sol Ring", 1, 0)], "removal": [("Fire // Ice", 1, 1)],
                                               "draw": [("Fire // Ice", 1, 1)], "burn": [("Fire // Ice", 1, 1)]})
        # The Play-now list plays Fire // Ice and not the Rhystic Study, so the Study is offered instead.
        owned = role_cards.role_cards("commander/abaddon", "owned")
        self.assertEqual(self.listed(owned), {"ramp": [("Sol Ring", 1, 0)], "draw": [("Rhystic Study", 1, 1)]})

    def test_a_play_now_list_without_its_commander_never_offers_the_planned_commander(self):
        # The Planned list's commander (a ramp card here, so it would fit its own role) gives the identity
        # of a Play-now list with no Commander section, and counts as in that list too.
        deck = "Commander\n1 Llanowar Elves (FDN) 227\n\nDeck\n1 Elvish Mystic (CMM) 648\n98 Forest"
        rest = ("\n## Substitutes\n\n### Substitute version (owned and incoming cards)\n\n```\n"
                "Deck\n1 Pick Your Poison (MKM) 170\n98 Forest\n```\n")
        self.write("elves", base.deck_text(deck, title="Elves", fmt="Commander", rest=rest), kind="commander")
        owned = role_cards.role_cards("commander/elves", "owned")
        self.assertEqual(owned["colours"], ["G"])
        self.assertEqual(self.listed(owned), {"ramp": [("Sol Ring", 1, 0)]})

    def test_copies_other_built_decks_hold_are_left_out(self):
        self.write("holder", base.deck_text("Deck\n1 Pick Your Poison (MKM) 170\n20 Forest", title="Holder",
                                            status="built"))
        self.assertEqual(self.listed(role_cards.role_cards(GHALTA_ID)), {"ramp": [("Sol Ring", 1, 0)]})

    def test_tags_unavailable(self):
        for recorded in ({}, {"roles": {role: {"tag": tag, "oracle_cards": 0} for role, tag in cards.ROLE_TAGS.items()}},
                         {"roles": None}):
            with self.subTest(recorded=recorded), mock.patch.object(cards, "info", return_value=recorded):
                answer = role_cards.role_cards(GHALTA_ID)
                self.assertFalse(answer["tags_available"])
                self.assertEqual(self.listed(answer), {})
                self.assertTrue(all(r["tagged"] is False for r in answer["roles"]))

    def test_bad_requests(self):
        self.assertApiError(400, role_cards.role_cards, None, contains="id is required")
        self.assertApiError(400, role_cards.role_cards, GHALTA_ID, "both")
        self.assertApiError(404, role_cards.role_cards, GHALTA_ID, "owned")
        self.assertApiError(400, role_cards.role_cards, base.SWAP_ID, contains="for Commander decks")
        self.write("no-commander", commander_text("Deck\n1 Llanowar Elves (FDN) 227\n98 Forest", "No Commander"),
                   kind="commander")
        self.assertApiError(400, role_cards.role_cards, "commander/no-commander", contains="commander first")
        for deck_id in ("product/fdc-test-precon", "pairing/cats+elves"):
            with self.subTest(deck_id):
                self.assertApiError(400, role_cards.role_cards, deck_id, contains="Only a deck")
        self.assertApiError(404, role_cards.role_cards, "commander/nowhere")

    def test_the_route(self):
        from decklab.lib import feature_routes
        handler = mock.Mock(command="GET")
        handler._query.return_value = {"id": GHALTA_ID}
        handler._deck_id.return_value = GHALTA_ID
        self.assertTrue(feature_routes.dispatch(handler, ["deck", "role-cards"], f"id={GHALTA_ID}"))
        status, answer = handler._send_json.call_args[0]
        self.assertEqual((status, answer["colours"]), (200, ["G"]))


class RoleCardsPrivacyTests(RoleCardsTestCase):

    def setUp(self):
        super().setUp()
        _write(self.box.root / "config.json", json.dumps(ROLES))
        _write(self.box.magic / "people" / "user2" / "collection.csv",
               "name,set,collector_number,finish,quantity,condition,language,notes\n"
               "Elvish Mystic,cmm,648,nonfoil,2,NM,en,\n")
        self.write("r-ghalta", commander_text(title="User2 Ghalta"), kind="commander", space="user2")

    def test_a_hidden_deck_is_missing_before_anything_else(self):
        with _as("user1"):
            self.assertApiError(404, role_cards.role_cards, "user2/commander/r-ghalta", contains="No deck")
            self.assertApiError(404, role_cards.role_cards, "user2/commander/r-ghalta", "both")
        with _as("user2"):
            self.assertApiError(404, role_cards.role_cards, GHALTA_ID)

    def test_a_public_deck_without_its_inventory_lists_nothing(self):
        with mock.patch.object(guard, "public_deck_spaces", return_value={"user2"}), _as("user1"):
            error = self.assertApiError(403, role_cards.role_cards, "user2/commander/r-ghalta")
            self.assertEqual(error.message, guard.COLLECTION_HIDDEN)
            # Nor a bad version: the inventory refusal comes first.
            self.assertApiError(403, role_cards.role_cards, "user2/commander/r-ghalta", "both")

    def test_a_members_space_uses_its_own_pool(self):
        with _as("user2"):
            answer = role_cards.role_cards("user2/commander/r-ghalta")
        # User2's 2 Elvish Mystics, none held: home's cards and its intact Beginner Box don't count here.
        self.assertEqual(self.listed(answer), {"ramp": [("Elvish Mystic", 2, 2)]})
        # A script naming nobody sees every space.
        self.assertEqual(self.listed(role_cards.role_cards("user2/commander/r-ghalta")),
                         {"ramp": [("Elvish Mystic", 2, 2)]})

    def test_home_players_get_home_and_no_holder_is_named(self):
        self.write("holder", base.deck_text("Deck\n1 Pick Your Poison (MKM) 170\n20 Forest", title="Secret Holder",
                                            status="built"))
        for profile in ("matt", "user1"):
            with self.subTest(profile), _as(profile):
                answer = role_cards.role_cards(GHALTA_ID)
                self.assertEqual(self.listed(answer), {"ramp": [("Sol Ring", 1, 0)]})
                text = json.dumps(answer)
                for hidden in ("Secret Holder", "casual/holder", "Beginner Box", "Test Precon", "User2"):
                    self.assertNotIn(hidden, text)


def _card(name, identity="", roles=("ramp",), legality="legal", printings=1):
    return {"name": name, "color_identity": list(identity), "roles": list(roles),
            "commander_legality": legality, "printings": [["set", str(i)] for i in range(printings)]}


class FreeByRoleTests(unittest.TestCase):

    def test_the_rules(self):
        known = {c["name"]: c for c in (
            _card("Ring"), _card("Green Ramp", "G", printings=3), _card("Blue Draw", "U", ("draw",)),
            _card("Banned Ramp", "G", legality="banned"), _card("Silver Ramp", legality="not_legal"),
            _card("In Deck", "G"), _card("Both", "G", ("ramp", "removal")), _card("No Role", "G", ()))}
        free = {"Ring": 1, "Green Ramp": 2, "Blue Draw": 1, "Banned Ramp": 1, "Silver Ramp": 1, "In Deck": 3,
                "Both": 1, "No Role": 4, "Not A Card": 1, "Zero": 0}
        found = role_pool.free_by_role(("ramp", "removal", "draw"), {"G"}, {"In Deck"}, free, known.get)
        # Most printings first, then by name; a card counts for each of its roles.
        self.assertEqual(found, {"ramp": ([("Green Ramp", 2), ("Both", 1), ("Ring", 1)], 0),
                                 "removal": ([("Both", 1)], 0), "draw": ([], 0)})
        limited = role_pool.free_by_role(("ramp",), {"G"}, set(), free, known.get, limit=1)
        self.assertEqual(limited, {"ramp": ([("Green Ramp", 2)], 3)})
        self.assertEqual(role_pool.MAX_PER_ROLE, 10)

    def test_fits(self):
        self.assertTrue(role_pool.fits(_card("Ring"), set()))
        self.assertTrue(role_pool.fits(_card("Gold", "WU"), {"W", "U", "B"}))
        self.assertFalse(role_pool.fits(_card("Gold", "WU"), {"W"}))
        self.assertFalse(role_pool.fits(_card("Banned", "W", legality="banned"), {"W"}))
        self.assertFalse(role_pool.fits(None, {"W"}))


if __name__ == "__main__":
    unittest.main()
