"""E5-S30: the editor's My wishlist tick (lib/api/wishlist_ideas.py, GET /api/deck/wishlist).

Only the signed-in profile's own wishlist is read; a Commander deck takes the wished cards inside its
commander's colour identity and legal in Commander; marks come only to a viewer who may see the deck's
space's inventory; a hidden deck is the missing deck's 404."""
import json
from unittest import mock

from decklab.lib import access, config, inventory
from decklab.lib.api import guard
from decklab.lib.api.common import ApiError
from decklab.lib.api.wishlist_ideas import wishlist_ideas_view
from decklab.lib.inventory.files import FileInventory
from decklab.tests.test_api import ApiTestCase, _write
from decklab.tests.test_collection_edit import ROLES

WISHED = ["Elvish Mystic", "Rhystic Study", "Black Lotus", "Sol Ring", "Forest", "Llanowar Elves",
          "Ghalta, Primal Hunger", "Murderous Rider // Swift End"]


def entry(name, set_code="", number=""):
    return {"name": name, "set": set_code, "number": number, "notes": "", "source": ""}


class WishlistIdeasTests(ApiTestCase):

    def setUp(self):
        super().setUp()
        box = self.box
        _write(box.root / "config.json", json.dumps(ROLES))
        (box.magic / "decks" / "casual" / "broken.md").unlink()
        for target, name, value in ((config, "REPO", box.root), (config, "DATA", box.data)):
            patcher = mock.patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.addCleanup(inventory.use(FileInventory(box.root)))
        box.state.seed_wishlist("user1", [entry(n) for n in WISHED[:-1]] + [entry(WISHED[-1])])
        box.state.seed_wishlist("matt", [entry("Elvish Mystic", "cmm", "648")])

    @staticmethod
    def ask(profile, **params):
        with access.viewing(profile):
            return wishlist_ideas_view(**params)

    def names(self, answer):
        return [c["name"] for c in answer["cards"]]

    def test_a_commander_deck_gets_the_wished_cards_in_its_identity(self):
        answer = self.ask("user1", deck_id="commander/elf-commander")
        # Rhystic Study and the Rider are outside Ghalta's green, Black Lotus is banned, Forest a basic
        # land and Ghalta the commander itself.
        self.assertEqual(self.names(answer), ["Elvish Mystic", "Sol Ring", "Llanowar Elves"])
        self.assertEqual(answer["identity"], "G")
        self.assertEqual(answer["left_out"], 5)
        self.assertTrue(answer["marks"])
        rows = {c["name"]: c for c in answer["cards"]}
        self.assertEqual(rows["Sol Ring"]["status"], "in_deck")
        self.assertTrue(rows["Llanowar Elves"]["in_deck"])
        self.assertIn(rows["Elvish Mystic"]["status"], ("free", "in_use", "to_buy"))

    def test_a_draft_commander_changes_the_identity(self):
        answer = self.ask("user1", deck_id="commander/elf-commander", commander="Rhystic Study")
        self.assertEqual(answer["identity"], "U")
        self.assertEqual(self.names(answer), ["Sol Ring"])

    def test_a_casual_deck_takes_every_wished_card_but_basics(self):
        answer = self.ask("user1", deck_id="casual/gruul-test")
        self.assertIsNone(answer["identity"])
        self.assertEqual(self.names(answer), [n for n in WISHED if n != "Forest"])

    def test_a_new_deck_names_its_kind(self):
        casual = self.ask("user1", kind="casual")
        self.assertEqual(casual["space"], "home")
        self.assertEqual(len(casual["cards"]), len(WISHED) - 1)
        commander = self.ask("user1", kind="commander", commander="Ghalta, Primal Hunger")
        self.assertEqual(self.names(commander), ["Elvish Mystic", "Sol Ring", "Llanowar Elves"])
        # No commander yet: nothing filters on colour.
        self.assertIsNone(self.ask("user1", kind="commander")["identity"])
        with self.assertRaises(ApiError) as caught:
            self.ask("user1", kind="pairing")
        self.assertEqual(caught.exception.status, 400)

    def test_the_wished_printing_goes_with_the_card(self):
        answer = self.ask("matt", deck_id="casual/gruul-test")
        self.assertEqual([(c["name"], c["set"], c["number"]) for c in answer["cards"]],
                         [("Elvish Mystic", "cmm", "648")])
        self.assertEqual(answer["cards"][0]["card"]["name"], "Elvish Mystic")

    def test_only_the_viewers_own_list_is_read(self):
        self.assertEqual(self.names(self.ask("matt", deck_id="casual/gruul-test")), ["Elvish Mystic"])
        with self.assertRaises(ApiError) as caught:
            wishlist_ideas_view(deck_id="casual/gruul-test")
        self.assertEqual(caught.exception.status, 403)

    def test_a_hidden_deck_is_missing_and_marks_follow_the_inventory_rule(self):
        self.box.state.seed_wishlist("user2", [entry("Sol Ring")])
        with self.assertRaises(ApiError) as caught:
            self.ask("user2", deck_id="casual/gruul-test")
        self.assertEqual(caught.exception.status, 404)
        with mock.patch.object(guard, "public_deck_spaces", return_value=frozenset({"home"})):
            answer = self.ask("user2", deck_id="casual/gruul-test")
        self.assertFalse(answer["marks"])
        self.assertNotIn("status", answer["cards"][0])
        self.assertNotIn("free", answer["cards"][0])
