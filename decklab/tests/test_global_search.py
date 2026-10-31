"""The top bar's global search, GET /api/search (E11-S31, lib/api/global_search.py): the three groups in order,
their bounds, and what each viewer is told (a member, User1, a home page naming nobody, a script).

Run from the repo root: python scripts/test_fixtures.py decklab.tests.test_global_search
"""
import json
from unittest import mock

from decklab.lib import access, feature_routes
from decklab.lib.api import collection, global_search as gs, guard
from decklab.lib.api import variant_queue  # noqa: F401  (feature_routes.dispatch imports it: load it before a sandbox)
from decklab.tests.test_api import _write
from decklab.tests.test_collection_edit import CollectionEditTestCase
from decklab.tests.test_inventory_privacy import R_BUILT


class GlobalSearchTestCase(CollectionEditTestCase):

    def setUp(self):
        super().setUp()
        _write(self.box.magic / "people" / "user2" / "decks" / "casual" / "r-elves.md", R_BUILT)

    def at_home(self, profile):
        """A home-network request whose chooser names profile (None: naming nobody, not a script)."""
        class Both:
            def __enter__(inner):
                inner.parts = [access.answering(False), access.viewing(profile)]
                for part in inner.parts:
                    part.__enter__()

            def __exit__(inner, *exc):
                for part in reversed(inner.parts):
                    part.__exit__(*exc)
        return Both()

    @staticmethod
    def groups(answer):
        return {g["id"]: g for g in answer["groups"]}


class GroupsTests(GlobalSearchTestCase):

    def test_three_groups_in_order_with_collection_counts(self):
        with self.at_home("matt"):
            answer = gs.search_view("elv")
        self.assertEqual([g["id"] for g in answer["groups"]], ["decks", "collection", "cards"])
        with self.at_home("matt"):
            self.assertEqual([d["id"] for d in self.groups(gs.search_view("elf"))["decks"]["items"]],
                             ["commander/elf-commander"])
        self.assertEqual([g["label"] for g in answer["groups"]], ["Decks", "In your collection", "Other cards"])
        groups = self.groups(answer)
        self.assertEqual([d["id"] for d in groups["decks"]["items"]], ["product/fdn-beginner-box/elves"])
        mine = {i["name"]: i for i in groups["collection"]["items"]}
        self.assertEqual(sorted(mine), ["Elvish Mystic", "Llanowar Elves"])
        elves = mine["Llanowar Elves"]
        with self.at_home("matt"):         # the Collection page's counts, as the pool works them out
            page = next(c for c in collection.collection_view(q="Llanowar")["cards"] if c["name"] == "Llanowar Elves")
        self.assertEqual((elves["owned"], elves["incoming"], elves["in_use"], elves["free"], elves["basic"]),
                         (page["owned"], page["incoming"], page["held"], page["free_now"], False))
        self.assertEqual((elves["owned"], elves["in_use"], elves["free"]), (5, 2, 3))
        self.assertEqual(elves["card"]["name"], "Llanowar Elves")
        self.assertNotIn("holders", elves)
        others = [i["name"] for i in groups["cards"]["items"]]
        self.assertNotIn("Llanowar Elves", others)          # already in the collection group
        self.assertEqual(groups["collection"]["space"], "home")

    def test_title_starts_rank_first_and_limits_bound_each_group(self):
        with self.at_home("matt"):
            answer = gs.search_view("e", limit="1")
        for group in answer["groups"]:
            self.assertLessEqual(len(group["items"]), 1)
            self.assertEqual(group["more"], group["total"] > 1)
        with self.at_home("matt"):
            only = gs.search_view("e", group="cards")
        self.assertEqual([g["id"] for g in only["groups"]], ["cards"])
        self.assertLessEqual(len(only["groups"][0]["items"]), 50)

    def test_owned_cards_match_as_other_cards_do_and_never_show_as_other_cards(self):
        # "llan elv" finds Llanowar Elves by its words' starts, as cards.search_names does: an owned card is in
        # the collection group, never listed under Other cards as if it weren't owned.
        with self.at_home("matt"):
            groups = self.groups(gs.search_view("llan elv"))
        self.assertIn("Llanowar Elves", [i["name"] for i in groups["collection"]["items"]])
        self.assertNotIn("Llanowar Elves", [i["name"] for i in groups["cards"]["items"]])

    def test_decks_match_the_title_as_the_library_does(self):
        # The library's title filter (NFKC, lower case, the title only), so See all's total is what it shows:
        # a deck's slug alone doesn't match.
        with self.at_home("matt"):
            decks = self.groups(gs.search_view("fdn-beginner-box"))["decks"]
        self.assertEqual(decks["items"], [])
        self.assertEqual(gs._title_rank(gs._title_key("ＥＬＶ"), gs._title_key("Elves")), 0)

    def test_bad_input_is_refused_and_blank_text_answers_nothing(self):
        self.assertEqual(gs.search_view("   "), {"q": "", "groups": []})
        self.assertApiError(400, gs.search_view, "x" * 101)
        self.assertApiError(400, gs.search_view, "a\x00b")
        self.assertApiError(400, gs.search_view, "elf", group="wishlists")
        for limit in ("0", "51", "two", "-1"):
            self.assertApiError(400, gs.search_view, "elf", limit=limit)

    def test_the_route_is_a_get_with_only_its_parameters(self):
        sent = {}

        class Handler:
            command = "GET"

            def _allow(self, *methods):
                sent["allow"] = methods

            def _query(self, query, names):
                sent["names"] = names
                return {"q": "elv"}

            def _send_json(self, status, body):
                sent["answer"] = (status, body)
        self.assertTrue(feature_routes.dispatch(Handler(), ["search"], "q=elv"))
        self.assertEqual(sent["names"], ("q", "group", "limit"))
        self.assertEqual(sent["answer"][0], 200)


class PrivacyTests(GlobalSearchTestCase):

    def test_a_member_sees_only_their_own_space(self):
        with self.as_("user2"):
            answer = gs.search_view("elv")
        groups = self.groups(answer)
        self.assertEqual([d["id"] for d in groups["decks"]["items"]], ["user2/casual/r-elves"])
        self.assertEqual(groups["collection"]["space"], "user2")
        elves = groups["collection"]["items"][0]
        self.assertEqual((elves["name"], elves["owned"], elves["in_use"], elves["free"]), ("Llanowar Elves", 2, 2, 0))
        text = json.dumps(answer)
        for secret in ("fdn-beginner-box", "product/", "home", "one of"):
            self.assertNotIn(secret, text)

    def test_user1_sees_home_and_nothing_of_a_members(self):
        with self.as_("user1"):
            answer = gs.search_view("elv")
        groups = self.groups(answer)
        self.assertEqual([d["id"] for d in groups["decks"]["items"]], ["product/fdn-beginner-box/elves"])
        self.assertEqual(groups["collection"]["space"], "home")
        text = json.dumps(answer)
        for secret in ("user2", "User2", "r-elves"):
            self.assertNotIn(secret, text)

    def test_matt_as_an_admin_has_no_override(self):
        with self.as_("matt"):
            text = json.dumps(gs.search_view("elv"))
        for secret in ("user2", "User2", "r-elves"):
            self.assertNotIn(secret, text)

    def test_a_home_page_naming_nobody_gets_only_other_cards(self):
        with self.at_home(None):
            answer = gs.search_view("elv")
        self.assertEqual([g["id"] for g in answer["groups"]], ["cards"])
        self.assertIn("Llanowar Elves", [i["name"] for i in answer["groups"][0]["items"]])

    def test_a_login_that_isnt_set_up_gets_only_other_cards(self):
        with access.using({"profile": "stranger", "email": "", "remote": True}):
            answer = gs.search_view("elv")
        self.assertEqual([g["id"] for g in answer["groups"]], ["cards"])

    def test_another_space_s_public_decks_stay_out(self):
        # Matt's decision of 2026-10-31: nothing outside the viewer's own space, Public decks included.
        with self.as_("matt"), mock.patch.object(guard, "public_deck_spaces", return_value=frozenset({"user2"})):
            text = json.dumps(gs.search_view("elv"))
        self.assertNotIn("r-elves", text)
        with self.as_("user2"), mock.patch.object(guard, "public_deck_spaces", return_value=frozenset({"home"})):
            groups = self.groups(gs.search_view("elv"))
        self.assertEqual([d["id"] for d in groups["decks"]["items"]], ["user2/casual/r-elves"])

    def test_a_script_sees_home_s_decks_and_collection(self):
        answer = gs.search_view("elv")          # outside a request: a script naming nobody, home's space
        groups = self.groups(answer)
        self.assertEqual([d["id"] for d in groups["decks"]["items"]], ["product/fdn-beginner-box/elves"])
        self.assertEqual(groups["collection"]["space"], "home")

    def test_an_unreadable_collection_names_nothing(self):
        with self.as_("user2"), mock.patch.object(gs.pool, "load_pool", side_effect=OSError("C:/Users/x/secret.csv")):
            groups = self.groups(gs.search_view("elv"))
        self.assertEqual(groups["collection"]["error"], gs.UNREADABLE)
        self.assertEqual(groups["collection"]["items"], [])
        self.assertNotIn("secret", json.dumps(groups))
