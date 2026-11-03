"""Global search's short deck use (E1-S29's remainder, lib/api/global_search.py with card_decks.deck_use): each
card shown under "In your collection" and "Other cards" says how many decks hold or want it and its free copies,
only to a viewer who may see the space's inventory, never counting a deck the viewer can't see.

Run from the repo root: python scripts/test_fixtures.py decklab.tests.test_global_search_use
"""
import json
from unittest import mock

from decklab.lib import access
from decklab.lib.api import card_decks as cd
from decklab.lib.api import global_search as gs, guard
from decklab.tests.test_api import _write
from decklab.tests.test_card_decks import two_lists
from decklab.tests.test_global_search import GlobalSearchTestCase
from decklab.tests.test_inventory_privacy import hides_every_deck


class ShortUseTests(GlobalSearchTestCase):

    def search(self, profile, q="elv"):
        with self.at_home(profile):
            return self.groups(gs.search_view(q))

    def test_collection_results_carry_the_card_viewer_s_counts(self):
        groups = self.search("matt")
        mine = {i["name"]: i for i in groups["collection"]["items"]}
        for name, item in mine.items():
            with self.at_home("matt"):
                full = cd.card_decks(name)
            self.assertEqual(item["decks"], len(full["holds"]) + len(full["wants"]), name)
            self.assertEqual(item["free"], full["free"], name)
        # Llanowar Elves: the Beginner Box's two decks hold it, two unbuilt decks want it; 3 free.
        self.assertEqual((mine["Llanowar Elves"]["decks"], mine["Llanowar Elves"]["free"]), (4, 3))

    def test_other_cards_say_their_wanting_decks_and_none_free(self):
        other = self.search("matt")["cards"]["items"][0]
        self.assertEqual((other["decks"], other["free"], other["basic"]), (0, 0, False))
        _write(self.box.magic / "decks" / "casual" / "a-want.md",
               two_lists("A Want", "building", f"2 {other['name']}", f"1 {other['name']}"))
        again = next(i for i in self.search("matt")["cards"]["items"] if i["name"] == other["name"])
        self.assertEqual((again["decks"], again["free"]), (1, 0))

    def test_each_deck_s_lists_are_read_once_for_every_shown_card(self):
        with mock.patch.object(cd, "_lists", wraps=cd._lists) as reads:
            self.search("matt")
        read = [call.args[0]["id"] for call in reads.call_args_list]
        self.assertEqual(len(read), len(set(read)))

    def test_a_basic_land_has_no_deck_count(self):
        groups = [{"id": "cards", "items": [{"name": "Forest", "card": None}]}]
        with self.at_home("matt"):
            p = gs.pool.load_pool()
            gs._deck_use("home", p, groups)
        self.assertEqual(groups[0]["items"][0], {"name": "Forest", "card": None, "basic": True})

    def test_a_member_s_counts_are_their_own_space_s(self):
        with self.as_("user2"):
            groups = self.groups(gs.search_view("elv"))
        elves = groups["collection"]["items"][0]
        self.assertEqual((elves["name"], elves["decks"], elves["free"]), ("Llanowar Elves", 1, 0))
        for item in groups["cards"]["items"]:
            self.assertEqual(item.get("decks"), 0, item["name"])

    def test_a_deck_the_viewer_may_not_see_is_never_counted(self):
        with self.at_home("matt"), mock.patch.object(guard, "deck_reader", hides_every_deck):
            groups = self.groups(gs.search_view("elv"))
        elves = next(i for i in groups["collection"]["items"] if i["name"] == "Llanowar Elves")
        self.assertEqual((elves["decks"], elves["free"]), (0, 3))      # their copies are still off the shelf
        for secret in ("fdn-beginner-box", "product/", "gruul", "elf-commander", "one of"):
            self.assertNotIn(secret, json.dumps(groups))

    def test_no_counts_to_a_viewer_outside_the_space_s_inventory(self):
        with self.at_home(None):
            answer = gs.search_view("elv")
        with access.using({"profile": "stranger", "email": "", "remote": True}):
            stranger = gs.search_view("elv")
        for found in (answer, stranger):
            for group in found["groups"]:
                for item in group["items"]:
                    for field in ("decks", "free", "basic"):
                        self.assertNotIn(field, item)
        with self.as_("user2"), mock.patch.object(guard, "sees_inventory", return_value=False):
            hidden = gs.search_view("elv")
        self.assertEqual([g["id"] for g in hidden["groups"]], ["decks", "cards"])
        for item in self.groups(hidden)["cards"]["items"]:
            self.assertNotIn("decks", item)
            self.assertNotIn("free", item)

    def test_an_unreadable_deck_list_leaves_the_fields_out(self):
        groups = [{"id": "cards", "items": [{"name": "Llanowar Elves", "card": None}]}]
        with self.at_home("matt"):
            p = gs.pool.load_pool()
            with mock.patch.object(gs.decks, "list_decks", side_effect=OSError("x")):
                gs._deck_use("home", p, groups)
        self.assertNotIn("decks", groups[0]["items"][0])


if __name__ == "__main__":
    import unittest
    unittest.main()
