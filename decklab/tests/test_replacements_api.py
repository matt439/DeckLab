"""Free pool replacements for a card a list holds (E3-S25): GET /api/deck/replacements
(lib/api/swaps.py suggest_replacements) and the ranking it shares with the stand-ins for missing
cards (lib/decks/swaps.py ranked).

Runs in test_swaps_api's SwapsTestCase (test_api's Sandbox, with the files backend): home's
collection has 5 Llanowar Elves, 1 Elvish Mystic and 1 Black Lotus; the Beginner Box is kept
intact (holding 2 Llanowar Elves and the Elvish Mystic), and the preordered precon brings a Sol
Ring. Nothing here writes to a database or plays a game.
"""
import json
from unittest import mock

from decklab.lib import api, cards
from decklab.lib.api import guard
from decklab.lib.decks import swaps
from decklab.tests import test_swaps_api as base
from decklab.tests.test_api import RATE, _write
from decklab.tests.test_collection_edit import ROLES
from decklab.tests.test_deck_privacy_readers import _as

DECK_ID = "casual/never-cast"
MYSTICS = "Deck\n2 Elvish Mystic (CMM) 648\n1 Black Lotus (LEA) 232\n20 Forest"
COLLECTION_HEAD = "name,set,collector_number,finish,quantity,condition,language,notes\n"


class ReplacementsTestCase(base.SwapsTestCase):

    def setUp(self):
        super().setUp()
        self.write("never-cast", base.deck_text(MYSTICS, title="Never Cast"))

    def names(self, answer):
        return [(c["name"], c["free"], c["here"], c["max_qty"]) for c in answer["candidates"]]


class ReplacementTests(ReplacementsTestCase):

    def test_a_never_cast_creature_gets_free_castable_creatures(self):
        answer = api.swaps.suggest_replacements(DECK_ID, card="elvish mystic")
        self.assertEqual((answer["deck_id"], answer["version"], answer["kind"], answer["colours"]),
                         (DECK_ID, "target", "casual", ["G"]))
        card = answer["card"]
        self.assertEqual((card["name"], card["qty"], card["type"], card["colours"], card["mv"]),
                         ("Elvish Mystic", 2, "creature", ["G"], 1))
        # 5 Llanowar Elves owned, 2 in the intact Beginner Box: 3 free, and both Mystics' slots to fill.
        self.assertEqual(self.names(answer), [("Llanowar Elves", 3, 3, 2)])
        elves = answer["candidates"][0]
        self.assertEqual((elves["note"]["words"], elves["basic"]), ("Close to even", False))
        self.assertEqual((elves["default"]["set"], elves["default"]["number"]), ("fdn", "227"))
        self.assertEqual(answer["more"], 0)
        # The AUD estimates come with their rate and dates, as the stand-ins' answer gives them.
        self.assertEqual((answer["rate"], answer["rate_date"]), RATE)
        swaps_answer = api.swaps.suggest_swaps(DECK_ID)
        self.assertEqual([answer[k] for k in ("rate", "rate_date", "price_date")],
                         [swaps_answer[k] for k in ("rate", "rate_date", "price_date")])
        self.assertIsNotNone(answer["price_date"])
        # An artifact on the way counts, marked as not here yet.
        lotus = api.swaps.suggest_replacements(DECK_ID, "target", "Black Lotus")
        self.assertEqual(self.names(lotus), [("Sol Ring", 1, 0, 1)])

    def test_copies_held_by_built_decks_or_the_list_itself_are_not_offered(self):
        self.write("holder", base.deck_text("Deck\n3 Llanowar Elves (FDN) 227\n20 Forest", title="Holder",
                                            status="built"))
        self.assertEqual(api.swaps.suggest_replacements(DECK_ID, card="Elvish Mystic")["candidates"], [])
        # The list's own copies use the pool too, and the four-copy cap leaves room for 1 more.
        self.write("holder", base.deck_text("Deck\n20 Forest", title="Holder", status="built"))
        self.write("never-cast", base.deck_text("Deck\n3 Llanowar Elves (FDN) 227\n" + MYSTICS[5:],
                                                title="Never Cast"))
        _write(self.box.magic / "collection.csv", COLLECTION_HEAD + "Llanowar Elves,fdn,227,nonfoil,10,NM,en,\n")
        answer = api.swaps.suggest_replacements(DECK_ID, card="Elvish Mystic")
        self.assertEqual(self.names(answer), [("Llanowar Elves", 5, 5, 1)])

    def test_only_cards_castable_in_the_deck(self):
        _write(self.box.magic / "collection.csv", COLLECTION_HEAD + "Fire // Ice,apc,128,nonfoil,2,NM,en,\n")
        self.write("never-cast", base.deck_text("Deck\n2 Very Cryptic Command (UST) 49a\n20 Island",
                                                title="Never Cast"))
        # A mono-blue deck can't cast the red half's colours: nothing offered.
        self.assertEqual(api.swaps.suggest_replacements(DECK_ID, card="Very Cryptic Command")["candidates"], [])
        self.write("never-cast", base.deck_text("Deck\n2 Very Cryptic Command (UST) 49a\n"
                                                "1 Abaddon the Despoiler (40K) 319\n20 Island", title="Never Cast"))
        answer = api.swaps.suggest_replacements(DECK_ID, card="Very Cryptic Command")
        self.assertEqual(answer["colours"], ["U", "B", "R"])
        self.assertEqual(self.names(answer), [("Fire // Ice", 2, 2, 2)])

    def test_at_most_max_replacements_and_the_rest_counted(self):
        with mock.patch.object(swaps, "MAX_REPLACEMENTS", 0):
            answer = api.swaps.suggest_replacements(DECK_ID, card="Elvish Mystic")
        self.assertEqual((answer["candidates"], answer["more"]), ([], 1))
        self.assertEqual(swaps.MAX_REPLACEMENTS, 5)

    def test_commander_singleton_and_the_commander_itself(self):
        deck = "Commander\n1 Ghalta, Primal Hunger (RIX) 130\n\nDeck\n1 Elvish Mystic (CMM) 648\n98 Forest"
        self.write("ghalta", base.deck_text(deck, title="Ghalta", fmt="Commander"), kind="commander")
        answer = api.swaps.suggest_replacements("commander/ghalta", card="Elvish Mystic")
        self.assertEqual((answer["kind"], answer["colours"]), ("commander", ["G"]))
        self.assertEqual(self.names(answer), [("Llanowar Elves", 3, 3, 1)])
        self.assertApiError(400, api.swaps.suggest_replacements, "commander/ghalta", None,
                            "Ghalta, Primal Hunger", contains="isn't in the Deck section")

    def test_the_play_now_list(self):
        rest = ("\n## Substitutes\n\n### Substitute version (owned and incoming cards)\n\n```\n"
                "Deck\n1 Elvish Mystic (CMM) 648\n1 Llanowar Elves (FDN) 227\n20 Forest\n```\n")
        self.write("never-cast", base.deck_text(MYSTICS, title="Never Cast", rest=rest))
        answer = api.swaps.suggest_replacements(DECK_ID, "owned", "Elvish Mystic")
        # Counted against the Play-now list: its own Llanowar Elves leaves 2 free, for its 1 Mystic.
        self.assertEqual((answer["version"], answer["card"]["qty"]), ("owned", 1))
        self.assertEqual(self.names(answer), [("Llanowar Elves", 2, 2, 1)])
        self.assertApiError(400, api.swaps.suggest_replacements, DECK_ID, "owned", "Black Lotus")

    def test_cards_that_cant_be_replaced_and_bad_requests(self):
        for card, words in ((None, "card is required"), ("", "card is required"), ("x" * 201, "card is required"),
                            ("Not A Card", "card is required"), ("Forest", "isn't in the Deck section"),
                            ("Sol Ring", "isn't in the Deck section")):
            with self.subTest(card=card):
                self.assertApiError(400, api.swaps.suggest_replacements, DECK_ID, None, card, contains=words)
        self.write("never-cast", base.deck_text(MYSTICS + "\n\nSideboard\n1 Sol Ring (ECC) 57", title="Never Cast"))
        self.assertApiError(400, api.swaps.suggest_replacements, DECK_ID, None, "Sol Ring",
                            contains="isn't in the Deck section")
        self.assertApiError(400, api.swaps.suggest_replacements, DECK_ID, "both", "Elvish Mystic")
        self.assertApiError(404, api.swaps.suggest_replacements, DECK_ID, "owned", "Elvish Mystic")
        self.assertApiError(400, api.swaps.suggest_replacements, None, None, "Elvish Mystic")
        for deck_id in ("product/fdc-test-precon", "pairing/cats+elves"):
            with self.subTest(deck_id):
                self.assertApiError(400, api.swaps.suggest_replacements, deck_id, None, "Elvish Mystic",
                                    contains="Only a deck")

    def test_the_route(self):
        from decklab.lib import feature_routes
        handler = mock.Mock(command="GET")
        handler._query.return_value = {"id": DECK_ID, "card": "Elvish Mystic"}
        handler._deck_id.return_value = DECK_ID
        self.assertTrue(feature_routes.dispatch(handler, ["deck", "replacements"],
                                                f"id={DECK_ID}&card=Elvish%20Mystic"))
        status, answer = handler._send_json.call_args[0]
        self.assertEqual((status, answer["card"]["name"]), (200, "Elvish Mystic"))


class RankedTests(ReplacementsTestCase):

    def test_the_stand_ins_and_the_replacements_share_one_ranking(self):
        mystic, elves = cards.card("Elvish Mystic"), cards.card("Llanowar Elves")
        spares = [("Llanowar Elves", 3, elves), ("Sol Ring", 1, cards.card("Sol Ring")), ("Elvish Mystic", 1, mystic)]
        # The slot's own name never, a colourless artifact never for a green creature.
        self.assertEqual([(n, spare, take) for _, n, spare, take in
                          swaps.ranked(mystic, spares, {"G"}, "casual", 2, {"Llanowar Elves": 3}, {})],
                         [("Llanowar Elves", 3, 1)])
        self.assertEqual(swaps.ranked(mystic, spares, {"G"}, "commander", 1, {"Llanowar Elves": 1}, {}), [])
        self.assertEqual(swaps.ranked(mystic, spares, {"U"}, "casual", 2, {}, {}), [])


class ReplacementPrivacyTests(ReplacementsTestCase):

    def setUp(self):
        super().setUp()
        _write(self.box.root / "config.json", json.dumps(ROLES))
        _write(self.box.magic / "people" / "user2" / "collection.csv",
               COLLECTION_HEAD + "Llanowar Elves,fdn,227,nonfoil,3,NM,en,\n")
        self.write("r-elves", base.deck_text("Deck\n2 Elvish Mystic (CMM) 648\n20 Forest", title="User2 Elves"),
                   space="user2")

    def test_a_hidden_deck_is_missing_before_anything_else(self):
        with _as("user1"):
            self.assertApiError(404, api.swaps.suggest_replacements, "user2/casual/r-elves", None, "Elvish Mystic",
                                contains="No deck")
            self.assertApiError(404, api.swaps.suggest_replacements, "user2/casual/r-elves", "both", None)
        with _as("user2"):
            self.assertApiError(404, api.swaps.suggest_replacements, DECK_ID, None, "Elvish Mystic")

    def test_a_public_deck_without_its_inventory_shows_no_replacements(self):
        with mock.patch.object(guard, "public_deck_spaces", return_value={"user2"}), _as("user1"):
            error = self.assertApiError(403, api.swaps.suggest_replacements, "user2/casual/r-elves", None,
                                        "Elvish Mystic")
            self.assertEqual(error.message, guard.COLLECTION_HIDDEN)
            # Nor a card that isn't there: the inventory refusal comes before the card is looked at.
            self.assertApiError(403, api.swaps.suggest_replacements, "user2/casual/r-elves", None, "Not A Card")

    def test_a_members_space_uses_its_own_pool(self):
        with _as("user2"):
            answer = api.swaps.suggest_replacements("user2/casual/r-elves", card="Elvish Mystic")
        # User2's 3 Llanowar Elves, none held: home's copies and intact Beginner Box don't count here.
        self.assertEqual(self.names(answer), [("Llanowar Elves", 3, 3, 2)])
        # A script naming nobody sees every space.
        self.assertTrue(api.swaps.suggest_replacements("user2/casual/r-elves", card="Elvish Mystic")["candidates"])

    def test_no_other_decks_title_in_the_answer(self):
        self.write("holder", base.deck_text("Deck\n1 Llanowar Elves (FDN) 227\n20 Forest", title="Secret Holder",
                                            status="built"))
        with _as("matt"):
            answer = api.swaps.suggest_replacements(DECK_ID, card="Elvish Mystic")
        self.assertEqual(self.names(answer), [("Llanowar Elves", 2, 2, 2)])
        text = json.dumps(answer)
        for hidden in ("Secret Holder", "casual/holder", "Beginner Box", "Test Precon", "User2"):
            self.assertNotIn(hidden, text)
