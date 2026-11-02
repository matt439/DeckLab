"""One card's decks and free copies for the card viewer, GET /api/cards/decks (E1-S29's first slice,
lib/api/card_decks.py): holders and wanters in order, the counts, basic lands, and the inventory and deck
privacy rules (R6d, E10-S29, E10-S30).

Run from the repo root: python scripts/test_fixtures.py decklab.tests.test_card_decks
"""
import json
from unittest import mock

from decklab.lib import feature_routes
from decklab.lib.api import card_decks as cd
from decklab.lib.api import collection, guard
from decklab.tests.test_api import _write
from decklab.tests.test_global_search import GlobalSearchTestCase
from decklab.tests.test_inventory_privacy import hides_every_deck

BUILT = """# Elf Stompy

- **Format:** casual
- **Played by:** user
- **Status:** built

## Decklist

```
Deck
1 Llanowar Elves (FDN) 227
```

## Considering

```
2 Black Lotus (LEA) 232
```

## Owned vs needed

| Card | Need | Owned | Missing | ~AUD each | ~AUD missing | Notes |
|---|---|---|---|---|---|---|
"""


def two_lists(title, status, planned, play_now, built_version=None):
    """A deck whose Planned and Play-now lists differ, both in the fixture's card index."""
    header = f"- **Format:** casual\n- **Played by:** user\n- **Status:** {status}\n"
    if built_version:
        header += f"- **Built version:** {built_version}\n"
    return (f"# {title}\n\n{header}\n## Decklist\n\n```\nDeck\n{planned}\n```\n\n"
            f"### Substitute version (owned and incoming cards)\n\n```\nDeck\n{play_now}\n```\n\n"
            "## Owned vs needed\n\n| Card | Need | Owned | Missing | ~AUD each | ~AUD missing | Notes |\n"
            "|---|---|---|---|---|---|---|\n")


class CardDecksTestCase(GlobalSearchTestCase):

    def ask(self, profile, name="Llanowar Elves", space=None):
        with self.at_home(profile):
            return cd.card_decks(name, space)


class AnswerTests(CardDecksTestCase):

    def test_holders_then_wanters_with_copies_and_the_card_lists_free_count(self):
        answer = self.ask("matt")
        self.assertEqual((answer["name"], answer["space"], answer["basic"], answer["more"]),
                         ("Llanowar Elves", "home", False, False))
        # The intact Beginner Box's two decks hold one each; the unbuilt decks' Planned lists want it.
        self.assertEqual([(d["id"], d["why"], d["copies"]) for d in answer["holds"]],
                         [("product/fdn-beginner-box/cats", "intact product", 1),
                          ("product/fdn-beginner-box/elves", "intact product", 1)])
        self.assertEqual([(d["id"], d["status"], d["copies"]) for d in answer["wants"]],
                         [("casual/gruul-test", "building", 6), ("commander/elf-commander", "idea", 1)])
        with self.at_home("matt"):         # the Collection page's counts, which the Card list's column shares
            page = next(c for c in collection.collection_view(q="Llanowar")["cards"] if c["name"] == "Llanowar Elves")
        self.assertEqual((answer["owned"], answer["incoming"], answer["free"]),
                         (page["owned"], page["incoming"], page["free_now"]))
        self.assertEqual((answer["owned"], answer["free"]), (5, 3))

    def test_built_decks_come_first_and_a_considering_list_is_not_a_want(self):
        _write(self.box.magic / "decks" / "casual" / "elf-stompy.md", BUILT)
        answer = self.ask("matt")
        self.assertEqual((answer["holds"][0]["id"], answer["holds"][0]["why"]), ("casual/elf-stompy", "built"))
        self.assertEqual(answer["free"], 2)
        lotus = self.ask("matt", "Black Lotus")
        self.assertEqual(lotus["holds"], [])
        self.assertEqual([d["id"] for d in lotus["wants"]], ["casual/gruul-test"])     # not elf-stompy's Considering
        self.assertEqual(lotus["free"], 1)

    def test_a_built_deck_whose_built_list_lacks_the_card_wants_it_last(self):
        # Built from its Play-now list (Elvish Mystic), it holds no Llanowar Elves; its Planned list wants 4.
        _write(self.box.magic / "decks" / "casual" / "a-mystic-build.md",
               two_lists("A Mystic Build", "built", "4 Llanowar Elves", "1 Elvish Mystic", "owned-only"))
        answer = self.ask("matt")
        self.assertNotIn("casual/a-mystic-build", [d["id"] for d in answer["holds"]])
        self.assertEqual([(d["id"], d["status"], d["copies"]) for d in answer["wants"]],
                         [("casual/gruul-test", "building", 6), ("commander/elf-commander", "idea", 1),
                          ("casual/a-mystic-build", "built", 4)])
        self.assertEqual(answer["free"], 3)            # its built list holds none of them
        mystic = self.ask("matt", "Elvish Mystic")
        self.assertIn(("casual/a-mystic-build", "built", 1), [(d["id"], d["why"], d["copies"]) for d in mystic["holds"]])
        self.assertNotIn("casual/a-mystic-build", [d["id"] for d in mystic["wants"]])

    def test_the_play_now_list_counts_when_the_planned_list_lacks_the_card(self):
        _write(self.box.magic / "decks" / "casual" / "a-stand-in.md",
               two_lists("A Stand-in", "building", "3 Elvish Mystic", "2 Llanowar Elves"))
        wants = {d["id"]: d["copies"] for d in self.ask("matt")["wants"]}
        self.assertEqual(wants["casual/a-stand-in"], 2)
        self.assertEqual({d["id"]: d["copies"] for d in self.ask("matt", "Elvish Mystic")["wants"]}["casual/a-stand-in"], 3)

    def test_each_list_stops_at_max_decks_and_more_says_so(self):
        with mock.patch.object(cd, "MAX_DECKS", 1):
            answer = self.ask("matt")
        self.assertEqual([d["id"] for d in answer["holds"]], ["product/fdn-beginner-box/cats"])
        self.assertEqual([d["id"] for d in answer["wants"]], ["casual/gruul-test"])
        self.assertTrue(answer["more"])
        self.assertEqual(answer["free"], 3, "a cut list still counts every holder's copies")
        with mock.patch.object(cd, "MAX_DECKS", 2):
            self.assertFalse(self.ask("matt")["more"])

    def test_a_basic_land_says_its_copies_in_decks_arent_tracked(self):
        answer = self.ask("matt", "Forest")
        self.assertTrue(answer["basic"])
        self.assertEqual((answer["holds"], answer["wants"], answer["owned"], answer["free"]), ([], [], None, None))

    def test_bad_and_unknown_names(self):
        self.assertApiError(400, self.ask, "matt", "")
        self.assertApiError(400, self.ask, "matt", "a\x00b")
        self.assertApiError(400, self.ask, "matt", "x" * 151)
        self.assertApiError(404, self.ask, "matt", "Not A Real Card Name")

    def test_the_route_is_a_get_with_only_its_parameters(self):
        sent = {}

        class Handler:
            command = "GET"

            def _allow(self, *methods):
                sent["allow"] = methods

            def _query(self, query, names):
                sent["names"] = names
                return {"name": "Llanowar Elves"}

            def _send_json(self, status, body):
                sent["answer"] = (status, body)
        self.assertTrue(feature_routes.dispatch(Handler(), ["cards", "decks"], "name=Llanowar%20Elves"))
        self.assertEqual(sent["names"], ("name", "space"))
        self.assertEqual(sent["allow"], ("GET", "HEAD"))
        self.assertEqual(sent["answer"][0], 200)
        self.assertEqual(sent["answer"][1]["name"], "Llanowar Elves")


class PrivacyTests(CardDecksTestCase):

    def test_a_member_gets_their_own_space_and_nothing_of_home(self):
        with self.as_("user2"):
            answer = cd.card_decks("Llanowar Elves", "user2")
        self.assertEqual([(d["id"], d["copies"]) for d in answer["holds"]], [("user2/casual/r-elves", 2)])
        self.assertEqual((answer["wants"], answer["owned"], answer["free"]), ([], 2, 0))
        text = json.dumps(answer)
        for secret in ("fdn-beginner-box", "product/", "gruul", "elf-commander", "one of"):
            self.assertNotIn(secret, text)

    def test_home_s_inventory_is_refused_to_a_member_as_the_collection_page_refuses_it(self):
        with self.as_("user2"):
            refused = self.assertApiError(403, cd.card_decks, "Llanowar Elves", "home")
        self.assertEqual(refused.message, guard.COLLECTION_HIDDEN)
        with self.as_("user2"):         # left out, the space is home's: the same refusal
            self.assertApiError(403, cd.card_decks, "Llanowar Elves")

    def test_matt_as_an_admin_has_no_override(self):
        with self.as_("matt"):
            refused = self.assertApiError(403, cd.card_decks, "Llanowar Elves", "user2")
        self.assertEqual(refused.message, guard.COLLECTION_HIDDEN)
        self.assertNotIn("user2", refused.message)

    def test_a_missing_space_answers_as_a_hidden_one_except_to_a_script(self):
        with self.as_("matt"):
            refused = self.assertApiError(403, cd.card_decks, "Llanowar Elves", "nobody-here")
        self.assertEqual(refused.message, guard.COLLECTION_HIDDEN)
        self.assertApiError(404, cd.card_decks, "Llanowar Elves", "nobody-here")       # a script naming nobody

    def test_the_refusal_comes_before_the_card_is_looked_up(self):
        with self.as_("user2"):
            self.assertApiError(403, cd.card_decks, "Not A Real Card Name", "home")

    def test_a_home_page_naming_nobody_and_a_login_not_set_up_are_refused(self):
        self.assertApiError(403, self.ask, None)
        from decklab.lib import access
        with access.using({"profile": "stranger", "email": "", "remote": True}):
            self.assertApiError(403, cd.card_decks, "Llanowar Elves")

    def test_a_deck_the_viewer_may_not_see_is_never_named_or_counted(self):
        # A collection public apart from its decks: the decks aren't named, counted or summed as "one of";
        # their copies are still off the shelf, so free stays the Card list's.
        public = mock.patch.object(guard, "inventory_spaces", lambda profile=False: ["home", "user2"])
        with self.as_("user2"), public, mock.patch.object(guard, "deck_reader", hides_every_deck):
            answer = cd.card_decks("Llanowar Elves", "home")
        self.assertEqual((answer["holds"], answer["wants"], answer["free"]), ([], [], 3))
        text = json.dumps(answer)
        for secret in ("fdn-beginner-box", "product/", "gruul", "elf-commander", "one of", "Beginner"):
            self.assertNotIn(secret, text)

    def test_user1_sees_home_s_decks(self):
        answer = self.ask("user1")
        self.assertEqual(len(answer["holds"]), 2)
        self.assertEqual([d["id"] for d in answer["wants"]], ["casual/gruul-test", "commander/elf-commander"])
        self.assertNotIn("r-elves", json.dumps(answer))

    def test_a_script_sees_home_s(self):
        answer = cd.card_decks("Llanowar Elves")
        self.assertEqual(answer["space"], "home")
        self.assertEqual(len(answer["holds"]), 2)

    def test_an_unreadable_pool_names_no_path_to_a_viewer_outside_home_s_records(self):
        public = mock.patch.object(guard, "inventory_spaces", lambda profile=False: ["home", "user2"])
        with self.as_("user2"), public, \
                mock.patch.object(cd.pool, "load_pool", side_effect=OSError("C:/Users/x/secret.csv")):
            refused = self.assertApiError(409, cd.card_decks, "Llanowar Elves", "home")
        self.assertEqual(refused.message, "The collection couldn't be read.")


if __name__ == "__main__":
    import unittest
    unittest.main()
