"""Stand-ins for missing cards (E2-S07): GET and POST /api/deck/swaps (lib/api/swaps.py) and the
deck page's "swaps".

Runs in test_editor's EditorTestCase (test_api's Sandbox, with the files backend): home's
collection has 5 Llanowar Elves, 1 Elvish Mystic and 1 Black Lotus; the Beginner Box is kept
intact (holding 2 Llanowar Elves and the Elvish Mystic), and the preordered precon brings a Sol
Ring. Nothing here writes to a database.
"""
import json
from unittest import mock

from decklab.lib import api, permissions
from decklab.lib.api import guard, swaps
from decklab.tests.test_api import _write
from decklab.tests.test_collection_edit import ROLES
from decklab.tests.test_deck_privacy_readers import _as
from decklab.tests.test_editor import EditorTestCase

SWAP_ID = "casual/swap-test"
HEADER = """# {title}

- **Format:** {format}
- **Played by:** {player}
- **Status:** {status}

## Decklist

```
{deck}
```
{rest}
## Owned vs needed

| Card | Need | Owned | Missing | ~AUD each | ~AUD missing | Notes |
|---|---|---|---|---|---|---|
"""
DECK = "Deck\n2 Llanowar Elves (FDN) 227\n2 Elvish Mystic (CMM) 648\n2 Black Lotus (LEA) 232\n20 Forest"


def deck_text(deck=DECK, title="Swap Test", status="building", player="user", fmt="Casual 60-card, 1v1", rest=""):
    return HEADER.format(title=title, format=fmt, player=player, status=status, deck=deck, rest=rest)


def editor_list(text):
    """A decklist block's lines as the editor sends them ({section: [{qty, name}]})."""
    out, section = {}, "Deck"
    for line in text.split("\n"):
        if line in ("Deck", "Sideboard", "Commander"):
            section = line
            continue
        qty, name = line.split(" ", 1)
        out.setdefault(section, []).append({"qty": int(qty), "name": name.split(" (")[0]})
    return out


class SwapsTestCase(EditorTestCase):

    def setUp(self):
        super().setUp()
        self.write("swap-test", deck_text())

    def write(self, slug, text, kind="casual", space=None):
        where = self.box.magic / "people" / space / "decks" if space else self.box.magic / "decks"
        _write(where / kind / f"{slug}.md", text)

    def entry(self, answer, name):
        return next(c for c in answer["cards"] if c["name"] == name)


class SuggestTests(SwapsTestCase):

    def test_free_copies_here_and_on_the_way(self):
        answer = api.swaps.suggest_swaps(SWAP_ID)
        self.assertEqual((answer["deck_id"], answer["version"], answer["kind"], answer["colours"]),
                         (SWAP_ID, "target", "casual", ["G"]))
        mystic = self.entry(answer, "Elvish Mystic")
        self.assertEqual((mystic["section"], mystic["missing"], mystic["type"], mystic["colours"], mystic["mv"]),
                         ("Deck", 2, "creature", ["G"], 1))
        # 5 owned, 2 in the intact Beginner Box, 2 already in the list: 1 free, here.
        [elves] = mystic["candidates"]
        self.assertEqual((elves["name"], elves["free"], elves["here"], elves["max_qty"], elves["basic"]),
                         ("Llanowar Elves", 1, 1, 1, False))
        self.assertEqual((elves["default"]["set"], elves["default"]["number"]), ("fdn", "227"))
        self.assertEqual(elves["note"]["words"], "Close to even")
        self.assertEqual(elves["card"]["name"], "Llanowar Elves")
        # The Lotus: the only colourless artifact within 1 is the Sol Ring on the way (no copy here).
        lotus = self.entry(answer, "Black Lotus")
        self.assertEqual([(c["name"], c["free"], c["here"], c["max_qty"]) for c in lotus["candidates"]],
                         [("Sol Ring", 1, 0, 1)])
        self.assertEqual(lotus["candidates"][0]["note"]["text"], "A little weaker: costs 1 more (1 vs 0); gains ramp.")

    def test_other_built_decks_hold_copies_and_the_decks_own_dont(self):
        self.write("holder", deck_text("Deck\n1 Llanowar Elves (FDN) 227\n20 Forest", title="Holder", status="built"))
        mystic = self.entry(api.swaps.suggest_swaps(SWAP_ID), "Elvish Mystic")
        self.assertEqual(mystic["candidates"], [])
        # No candidate first: the card most worth buying.
        self.assertEqual(api.swaps.suggest_swaps(SWAP_ID)["cards"][0]["name"], "Elvish Mystic")
        self.write("holder", deck_text("Deck\n20 Forest", title="Holder", status="built"))
        # Built itself, the deck's own copies are free for its lists.
        self.write("swap-test", deck_text(status="built"))
        mystic = self.entry(api.swaps.suggest_swaps(SWAP_ID), "Elvish Mystic")
        self.assertEqual([(c["name"], c["free"]) for c in mystic["candidates"]], [("Llanowar Elves", 1)])

    def test_the_four_copy_cap_and_the_play_now_list(self):
        _write(self.box.magic / "collection.csv", "name,set,collector_number,finish,quantity,condition,language,notes\n"
               "Llanowar Elves,fdn,227,nonfoil,10,NM,en,\nBlack Lotus,lea,232,nonfoil,1,NM,en,\n")

        def play_now(elves):
            rest = ("\n## Substitutes\n\n### Substitute version (owned and incoming cards)\n\n```\n"
                    f"Deck\n{elves} Llanowar Elves (FDN) 227\n2 Elvish Mystic (CMM) 648\n20 Forest\n```\n")
            self.write("swap-test", deck_text(rest=rest))
            return self.entry(api.swaps.suggest_swaps(SWAP_ID), "Elvish Mystic")

        # Counted against the Play-now list: 4 Llanowar Elves there leave no room, 3 room for 1.
        self.assertEqual(play_now(4)["candidates"], [])
        mystic = play_now(3)
        self.assertEqual((mystic["in_list"], [(c["name"], c["free"], c["max_qty"]) for c in mystic["candidates"]]),
                         (2, [("Llanowar Elves", 5, 1)]))
        owned = api.swaps.suggest_swaps(SWAP_ID, "owned")
        self.assertEqual([c["name"] for c in owned["cards"]], ["Elvish Mystic"])

    def test_whether_the_play_now_list_is_short_too(self):
        # The Planned list is short of a Black Lotus; the Play-now list plays the one owned and a Sol Ring.
        deck = "Deck\n2 Llanowar Elves (FDN) 227\n2 Elvish Mystic (CMM) 648\n2 Black Lotus (LEA) 232\n20 Forest"
        rest = ("\n## Substitutes\n\n### Substitute version (owned and incoming cards)\n\n```\n"
                "Deck\n2 Llanowar Elves (FDN) 227\n2 Elvish Mystic (CMM) 648\n1 Black Lotus (LEA) 232\n"
                "1 Sol Ring (ECC) 57\n20 Forest\n```\n")
        self.write("swap-test", deck_text(deck, rest=rest))
        lotus = self.entry(api.swaps.suggest_swaps(SWAP_ID), "Black Lotus")
        self.assertEqual((lotus["missing"], lotus["in_list"], lotus["list_missing"]), (1, 1, 0))
        # The Mystic: 1 owned and free (2 in the intact Beginner Box), so both lists are short of it.
        mystic = self.entry(api.swaps.suggest_swaps(SWAP_ID), "Elvish Mystic")
        self.assertEqual(mystic["list_missing"], self.entry(api.swaps.suggest_swaps(SWAP_ID, "owned"),
                                                            "Elvish Mystic")["missing"])

    def test_a_card_filter(self):
        answer = api.swaps.suggest_swaps(SWAP_ID, card="elvish mystic")
        self.assertEqual([c["name"] for c in answer["cards"]], ["Elvish Mystic"])
        self.assertApiError(400, api.swaps.suggest_swaps, SWAP_ID, None, "Llanowar Elves")
        self.assertApiError(400, api.swaps.suggest_swaps, SWAP_ID, "both")
        self.assertApiError(400, api.swaps.suggest_swaps, None)

    def test_a_land_gets_lands_and_basics(self):
        self.write("swap-test", deck_text("Deck\n2 Llanowar Elves (FDN) 227\n1 Emeria's Call (ZNR) 12\n20 Forest"))
        answer = api.swaps.suggest_swaps(SWAP_ID)
        # Emeria's Call is a sorcery on its front face: no land stands in, and no basic either.
        call = self.entry(answer, "Emeria's Call // Emeria, Shattered Skyclave")
        self.assertEqual((call["type"], call["candidates"]), ("sorcery", []))

    def test_commander_singleton_and_identity(self):
        deck = "Commander\n1 Ghalta, Primal Hunger (RIX) 130\n\nDeck\n1 Elvish Mystic (CMM) 648\n98 Forest"
        self.write("ghalta", deck_text(deck, title="Ghalta", fmt="Commander"), kind="commander")
        answer = api.swaps.suggest_swaps("commander/ghalta")
        self.assertEqual((answer["kind"], answer["colours"]), ("commander", ["G"]))
        mystic = self.entry(answer, "Elvish Mystic")
        self.assertEqual([(c["name"], c["max_qty"]) for c in mystic["candidates"]], [("Llanowar Elves", 1)])
        # Already in the list: a Commander deck has one copy of a card.
        deck += "\n1 Llanowar Elves (FDN) 227"
        self.write("ghalta", deck_text(deck, title="Ghalta", fmt="Commander"), kind="commander")
        self.assertEqual(self.entry(api.swaps.suggest_swaps("commander/ghalta"), "Elvish Mystic")["candidates"], [])

    def test_products_and_pairings_have_no_play_now_list(self):
        for deck_id in ("product/fdc-test-precon", "pairing/cats+elves"):
            with self.subTest(deck_id):
                self.assertApiError(400, api.swaps.suggest_swaps, deck_id, contains="Only a deck")

    def test_the_draft(self):
        sent = editor_list("Deck\n3 Llanowar Elves (FDN) 227\n2 Elvish Mystic (CMM) 648\n20 Forest")
        answer = api.swaps.suggest_draft_swaps(self.body(id=SWAP_ID, list=sent))
        self.assertEqual(answer["version"], "owned")
        # Its own 3 Llanowar Elves leave none free.
        self.assertEqual(self.entry(answer, "Elvish Mystic")["candidates"], [])
        one = api.swaps.suggest_draft_swaps(self.body(id=SWAP_ID, list=editor_list(DECK), card="Black Lotus"))
        self.assertEqual([c["name"] for c in one["cards"]], ["Black Lotus"])
        for bad in ({"list": []}, {"list": {"Main": []}}, {"list": {"Deck": [{"name": "Forest", "qty": 0}]}},
                    {"list": {"Deck": [{"qty": 1}]}}, {"list": {}, "extra": 1}):
            with self.subTest(bad=bad):
                self.assertApiError(400, api.swaps.suggest_draft_swaps, self.body(id=SWAP_ID, **bad))
        self.assertApiError(403, api.swaps.suggest_draft_swaps, self.body(None, id=SWAP_ID, list={}))
        # An unknown name is skipped, not a 500.
        odd = api.swaps.suggest_draft_swaps(self.body(id=SWAP_ID, list={"Deck": [{"qty": 1, "name": "Not A Card"}]}))
        self.assertEqual(odd["cards"], [])

    def test_routes(self):
        from decklab.lib import feature_routes
        handler = mock.Mock(command="GET")
        handler._query.return_value = {"id": SWAP_ID}
        handler._deck_id.return_value = SWAP_ID
        self.assertTrue(feature_routes.dispatch(handler, ["deck", "swaps"], f"id={SWAP_ID}"))
        status, answer = handler._send_json.call_args[0]
        self.assertEqual((status, answer["deck_id"]), (200, SWAP_ID))
        handler = mock.Mock(command="POST")
        handler._write_body.return_value = self.body(id=SWAP_ID, list=editor_list(DECK))
        self.assertTrue(feature_routes.dispatch(handler, ["deck", "swaps"], ""))
        self.assertEqual(handler._send_json.call_args[0][1]["version"], "owned")


class SwapPrivacyTests(SwapsTestCase):

    def setUp(self):
        super().setUp()
        _write(self.box.root / "config.json", json.dumps(ROLES))
        _write(self.box.magic / "people" / "user2" / "collection.csv",
               "name,set,collector_number,finish,quantity,condition,language,notes\n"
               "Llanowar Elves,fdn,227,nonfoil,3,NM,en,\n")
        self.write("r-elves", deck_text("Deck\n2 Elvish Mystic (CMM) 648\n20 Forest", title="User2 Elves"),
                   space="user2")

    def test_a_hidden_deck_is_missing_before_anything_else(self):
        with _as("user1"):
            self.assertApiError(404, api.swaps.suggest_swaps, "user2/casual/r-elves", contains="No deck")
            self.assertApiError(404, api.swaps.suggest_swaps, "user2/casual/r-elves", "both")
            self.assertApiError(404, api.swaps.suggest_draft_swaps,
                                self.body("user1", id="user2/casual/r-elves", list={}))
        with _as("user2"):
            self.assertApiError(404, api.swaps.suggest_swaps, SWAP_ID)        # no admin needed to hide home

    def test_a_public_deck_without_its_inventory(self):
        with mock.patch.object(guard, "public_deck_spaces", return_value={"user2"}), _as("user1"):
            error = self.assertApiError(403, api.swaps.suggest_swaps, "user2/casual/r-elves")
            self.assertEqual(error.message, guard.COLLECTION_HIDDEN)
            view = api.deck_view("user2/casual/r-elves")
            self.assertNotIn("owned", view)
            self.assertIn("swaps", view)

    def test_a_members_space_uses_its_own_pool(self):
        with _as("user2"):
            answer = api.swaps.suggest_swaps("user2/casual/r-elves")
        mystic = self.entry(answer, "Elvish Mystic")
        # User2's 3 Llanowar Elves, none held: home's intact Beginner Box doesn't count here.
        self.assertEqual([(c["name"], c["free"], c["max_qty"]) for c in mystic["candidates"]],
                         [("Llanowar Elves", 3, 2)])
        # A script naming nobody sees every space.
        self.assertTrue(api.swaps.suggest_swaps("user2/casual/r-elves")["cards"])
        self.assertTrue(permissions.sees_inventory(None, "user2", script=True))

    def test_no_other_decks_title_in_the_answer(self):
        self.write("holder", deck_text("Deck\n1 Llanowar Elves (FDN) 227\n20 Forest", title="Secret Holder",
                                       status="built"))
        with _as("matt"):
            answer = api.swaps.suggest_swaps(SWAP_ID)
        text = json.dumps(answer)
        for hidden in ("Secret Holder", "casual/holder", "Beginner Box", "Test Precon", "User2"):
            self.assertNotIn(hidden, text)


class DeckViewSwapsTests(SwapsTestCase):

    def test_the_play_now_lists_swaps_with_their_notes(self):
        rest = ("\n## Substitutes\n\n| Buy | Play now | What the swap costs |\n|---|---|---|\n"
                "| 2 Elvish Mystic | 1 Llanowar Elves | Close to even. |\n\n"
                "### Substitute version (owned and incoming cards)\n\n```\n"
                "Deck\n3 Llanowar Elves (FDN) 227\n1 Black Lotus (LEA) 232\n1 Sol Ring (ECC) 57\n20 Forest\n```\n")
        self.write("swap-test", deck_text(rest=rest))
        found = api.deck_view(SWAP_ID)["swaps"]
        self.assertEqual([(s["for"], s["out_qty"], [(u["name"], u["qty"]) for u in s["using"]], s["note"])
                          for s in found["swaps"]],
                         [("Elvish Mystic", 2, [("Llanowar Elves", 1)], "Close to even."),
                          ("Black Lotus", 1, [], None)])
        self.assertEqual([(u["name"], u["qty"]) for u in found["unpaired"]], [("Sol Ring", 1)])
        self.assertEqual(found["swaps"][0]["card"]["name"], "Elvish Mystic")
        self.assertEqual(found["unpaired"][0]["card"]["name"], "Sol Ring")

    def test_none_without_a_play_now_list(self):
        self.assertIsNone(api.deck_view(SWAP_ID)["swaps"])
        self.assertIsNone(api.deck_view("product/fdc-test-precon")["swaps"])
        self.assertIsNone(swaps.view_swaps(None))
