"""Tests for decklab.lib.permissions: who may change what (HISTORY.md, "Accounts
and member collections"). Pure functions, so plain dicts stand in for
profiles and library summaries.

Run from the repo root: python scripts/test_fixtures.py
"""
import unittest
from unittest import mock

from decklab.lib import permissions, profiles
from decklab.lib.decks import parse_deck

MATT, USER1, USER2, USER3 = profiles.parse([
    {"id": "matt", "name": "Matt", "plays_as": "user", "role": "admin"},
    {"id": "user1", "name": "User1", "plays_as": "wife", "role": "member"},
    {"id": "user2", "name": "User2", "role": "member", "space": "user2"},
    {"id": "user3", "name": "User3", "role": "member", "space": "user3"}])
SPACES = ["home", "user2", "user3"]


def deck(space="home", player=None):
    return {"id": "x", "space": space, "player": player}


HIS, HERS, EITHER, NOBODYS = deck(player="user"), deck(player="wife"), deck(player="either"), deck()
USER2S, USER3S = deck("user2"), deck("user3")


class DeckTests(unittest.TestCase):

    def test_a_script_changes_every_deck_and_an_admin_only_his_own_spaces(self):
        for d in (HIS, HERS, EITHER, NOBODYS, USER2S, USER3S):
            self.assertTrue(permissions.can(None, "deck.edit", d, script=True))
            self.assertTrue(permissions.can(None, "tables.update", d, script=True))
        # E10-S29: the admin role opens no other space, at home as through the tunnel.
        for script in (False, True):
            for d in (HIS, HERS, EITHER, NOBODYS):
                for action in ("deck.edit", "tables.update"):
                    self.assertTrue(permissions.can(MATT, action, d, script=script))
            for d in (USER2S, USER3S):
                for action in ("deck.edit", "tables.update"):
                    with self.subTest(deck=d, action=action, script=script):
                        self.assertEqual(permissions.reason(MATT, action, d, script=script),
                                         "That deck is in someone else's collection.")
        # An admin of a person's space changes that space's decks, and no home deck.
        user5 = {**USER2, "role": "admin"}
        self.assertTrue(permissions.can(user5, "deck.edit", USER2S))
        self.assertFalse(permissions.can(user5, "deck.edit", HIS))
        self.assertFalse(permissions.can(user5, "deck.edit", USER3S))

    def test_a_profile_named_at_home_has_its_own_rights(self):
        # E10-S03: the home network no longer makes whoever is picked an admin.
        for who in (USER1, USER2):
            for d in (HIS, HERS, EITHER, NOBODYS, USER2S, USER3S):
                for action in ("deck.edit", "tables.update"):
                    with self.subTest(who=who["id"], deck=d, action=action):
                        self.assertEqual(permissions.reason(who, action, d, script=True),
                                         permissions.reason(who, action, d))
        self.assertEqual(permissions.reason(USER1, "deck.edit", HIS, script=True),
                         "You can change the home decks played by you.")
        self.assertTrue(permissions.can(USER1, "deck.edit", HERS, script=True))
        self.assertFalse(permissions.can(USER2, "deck.edit", HERS, script=True))
        self.assertTrue(permissions.can(USER2, "deck.edit", USER2S, script=True))
        self.assertFalse(permissions.can(USER1, "deck.create", {"space": "home", "player": "user"}, script=True))
        self.assertFalse(permissions.can(USER1, "play.record", [HIS, EITHER], script=True))

    def test_a_home_member_changes_the_home_decks_played_by_them(self):
        self.assertTrue(permissions.can(USER1, "deck.edit", HERS))
        self.assertTrue(permissions.can(USER1, "tables.update", HERS))
        for d in (HIS, EITHER, NOBODYS, USER2S):
            with self.subTest(deck=d):
                self.assertFalse(permissions.can(USER1, "deck.edit", d))
                self.assertFalse(permissions.can(USER1, "tables.update", d))
        self.assertEqual(permissions.reason(USER1, "deck.edit", EITHER), "You can change the home decks played by you.")

    def test_a_person_changes_only_their_own_space(self):
        self.assertTrue(permissions.can(USER2, "deck.edit", USER2S))
        for d in (HIS, HERS, EITHER, USER3S):
            self.assertFalse(permissions.can(USER2, "deck.edit", d))

    def test_a_deck_file_works_as_the_target(self):
        text = b"# T\n\n- **Played by:** wife\n\n## Decklist\n\n```\nDeck\n1 Sol Ring\n```\n"
        hers = parse_deck(text, "t", "casual")
        self.assertTrue(permissions.can(USER1, "deck.edit", hers))
        self.assertFalse(permissions.can(USER2, "deck.edit", hers))
        self.assertTrue(permissions.can(USER2, "deck.edit", parse_deck(text, "t", "casual", space="user2")))

    def test_creating_decks(self):
        self.assertFalse(permissions.can(MATT, "deck.create", {"space": "user2", "player": None}))   # E10-S29
        self.assertTrue(permissions.can(MATT, "deck.create", {"space": "home", "player": "wife"}))
        self.assertTrue(permissions.can(None, "deck.create", {"space": "user2", "player": None}, script=True))
        self.assertTrue(permissions.can(USER1, "deck.create", {"space": "home", "player": "wife"}))
        self.assertTrue(permissions.can(USER1, "deck.create", {"space": "home", "player": None}))
        self.assertFalse(permissions.can(USER1, "deck.create", {"space": "home", "player": "either"}))
        self.assertFalse(permissions.can(USER1, "deck.create", {"space": "user2"}))
        self.assertTrue(permissions.can(USER2, "deck.create", {"space": "user2"}))
        self.assertFalse(permissions.can(USER2, "deck.create", {"space": "home", "player": None}))
        self.assertFalse(permissions.can(USER2, "deck.create", {"space": "user3"}))

    def test_play_records_need_one_of_their_decks(self):
        self.assertTrue(permissions.can(USER1, "play.record", [HIS, HERS]))
        self.assertFalse(permissions.can(USER1, "play.record", [HIS, EITHER]))
        self.assertTrue(permissions.can(USER2, "play.record", [HIS, USER2S]))
        self.assertFalse(permissions.can(USER2, "play.record", [HIS, USER3S]))
        self.assertFalse(permissions.can(USER2, "play.record", []))
        # An admin records only games with one of his own space's decks (E10-S29).
        self.assertFalse(permissions.can(MATT, "play.record", [USER2S, USER3S]))
        self.assertTrue(permissions.can(MATT, "play.record", [EITHER, USER2S]))
        self.assertTrue(permissions.can(None, "play.record", [USER2S, USER3S], script=True))

    def test_a_member_picked_at_home_cant_record_a_game_of_two_home_decks(self):
        # The write rule matches the Game log's read rule (sees_play_record): User2 would be refused
        # seeing such a game, so he can't save one either, at home as through the tunnel (E10-S03).
        for local in (False, True):
            self.assertFalse(permissions.can(USER2, "play.record", [HIS, HERS], script=local))
            self.assertTrue(permissions.can(USER2, "play.record", [HIS, USER2S], script=local))
        self.assertTrue(permissions.can(None, "play.record", [HIS, HERS], script=True))


class OtherActionTests(unittest.TestCase):

    def test_collections_and_tokens(self):
        for action in ("collection.edit", "tokens.edit"):
            for script in (False, True):        # the same at home as through the tunnel (E10-S03)
                with self.subTest(action=action, script=script):
                    self.assertTrue(permissions.can(MATT, action, "home", script=script))
                    self.assertFalse(permissions.can(MATT, action, "user2", script=script))   # E10-S29
                    self.assertTrue(permissions.can(USER1, action, "home", script=script))     # E10-S43
                    self.assertFalse(permissions.can(USER1, action, "user2", script=script))
                    self.assertFalse(permissions.can(USER2, action, "home", script=script))
                    self.assertTrue(permissions.can(USER2, action, "user2", script=script))
                    self.assertFalse(permissions.can(USER2, action, "user3", script=script))
            self.assertTrue(permissions.can(None, action, "home", script=True))      # a script
            self.assertTrue(permissions.can(None, action, "user2", script=True))
            self.assertFalse(permissions.can({**USER2, "role": "admin"}, action, "home"))
        self.assertEqual(permissions.reason(MATT, "collection.edit", "user2"),
                         "You can only change your own collection.")
        self.assertEqual(permissions.reason(USER2, "tokens.edit", "home"), "You can only change your own tokens.")

    def test_own_wishlist_and_settings(self):
        for action in ("wishlist.edit", "settings.edit"):
            self.assertTrue(permissions.can(USER1, action, "user1"))
            self.assertFalse(permissions.can(USER1, action, "matt"))
            self.assertTrue(permissions.can(USER2, action, "user2"))
            self.assertTrue(permissions.can(MATT, action, "matt"))
            # An admin also his own space's profiles', none of another's (E10-S29).
            with mock.patch.object(profiles, "find", lambda pid: {"user1": USER1, "user2": USER2}.get(pid)):
                self.assertTrue(permissions.can(MATT, action, "user1"))
                self.assertFalse(permissions.can(MATT, action, "user2"))
                self.assertFalse(permissions.can(MATT, action, "nobody"))
                self.assertFalse(permissions.can({**USER2, "role": "admin"}, action, "user1"))
            self.assertFalse(permissions.can(USER1, action, "matt", script=True))
            self.assertTrue(permissions.can(None, action, "matt", script=True))

    def test_only_the_owner_sees_a_wishlist(self):
        # Not an admin, not someone else at home, not a person, not a request naming nobody.
        self.assertTrue(permissions.sees_wishlist(USER1, "user1"))
        self.assertTrue(permissions.sees_wishlist(USER1, "user1", script=True))
        self.assertTrue(permissions.sees_wishlist(USER2, "user2"))
        for profile, local in ((MATT, False), (MATT, True), (USER2, False), (USER3, True), (None, True),
                               (None, False)):
            with self.subTest(profile=profile and profile["id"], local=local):
                self.assertFalse(permissions.sees_wishlist(profile, "user1", script=local))
        self.assertFalse(permissions.sees_wishlist(USER1, None))

    def test_admin_only_and_runs(self):
        for action in ("receipts.apply", "products.edit", "orders.edit"):
            self.assertTrue(permissions.can(MATT, action))
            self.assertTrue(permissions.can(MATT, action, script=True))
            self.assertTrue(permissions.can(None, action, script=True))
            self.assertFalse(permissions.can(USER1, action, script=True))
            self.assertEqual(permissions.reason(USER1, action, script=True), permissions.reason(USER1, action))
            self.assertFalse(permissions.can(USER1, action))
            self.assertFalse(permissions.can(USER2, action))
            # Home's records are home's: an admin of another space doesn't change them (E10-S29).
            self.assertFalse(permissions.can({**USER2, "role": "admin"}, action))
        for who in (MATT, USER1, USER2, None):
            self.assertTrue(permissions.can(who, "run"))

    def test_only_the_home_sees_the_accessories(self):
        # Seeing: Matt and User1 (home profiles, any role) see theirs; a person with their own space
        # sees none, even as an admin or on the home network; a local request naming nobody sees all.
        self.assertTrue(permissions.sees_accessories(MATT))
        self.assertTrue(permissions.sees_accessories(USER1))
        self.assertFalse(permissions.sees_accessories(USER2))
        self.assertFalse(permissions.sees_accessories(USER3))
        self.assertFalse(permissions.sees_accessories(None))
        self.assertFalse(permissions.sees_accessories(USER2, script=True))
        self.assertTrue(permissions.sees_accessories(None, script=True))
        self.assertFalse(permissions.sees_accessories({**USER2, "role": "admin"}))

    def test_each_home_profile_sees_its_own_and_the_shared_accessories(self):
        for local in (False, True):
            with self.subTest(local=local):
                self.assertEqual(permissions.accessory_owners(MATT, script=local), {"matt", "shared"})
                self.assertEqual(permissions.accessory_owners(USER1, script=local), {"user1", "shared"})
                self.assertEqual(permissions.accessory_owners(USER2, script=local), frozenset())
        self.assertIsNone(permissions.accessory_owners(None, script=True))
        self.assertEqual(permissions.accessory_owners(None), frozenset())

    def test_any_home_profile_edits_accessories(self):
        # Which rows is the route's check (the owner); the action only needs some of its own.
        self.assertTrue(permissions.can(MATT, "accessories.edit"))
        self.assertTrue(permissions.can(USER1, "accessories.edit"))
        self.assertTrue(permissions.can(None, "accessories.edit", script=True))
        for who, local in ((USER2, False), (USER2, True), ({**USER2, "role": "admin"}, False)):
            with self.subTest(who=who["id"], local=local):
                self.assertFalse(permissions.can(who, "accessories.edit", script=local))
        self.assertEqual(permissions.reason(None, "accessories.edit"), "Choose who you are first.")

    def test_no_profile_and_unknown_actions(self):
        self.assertEqual(permissions.reason(None, "deck.edit", HERS), "Choose who you are first.")
        with self.assertRaises(ValueError):
            permissions.can(MATT, "deck.delete", HERS)

    def test_a_config_without_roles_keeps_everyone_editing(self):
        old = profiles.parse([{"id": "user1", "name": "User1", "plays_as": "wife"}])[0]
        self.assertTrue(permissions.can(old, "accessories.edit"))
        self.assertTrue(permissions.can(old, "deck.edit", HIS))
        self.assertTrue(permissions.can(old, "collection.edit", "home", script=True))   # an admin by its role


class InventoryRuleTests(unittest.TestCase):
    # E10-S29: a space's collection and tokens are seen only in that space, an admin's role opening none;
    # home's records only by home's profiles.

    def test_each_space_only_by_its_own_people(self):
        for script in (False, True):
            self.assertTrue(permissions.sees_inventory(MATT, "home", script=script))
            self.assertTrue(permissions.sees_inventory(USER1, "home", script=script))
            self.assertFalse(permissions.sees_inventory(MATT, "user2", script=script))
            self.assertFalse(permissions.sees_inventory(MATT, "zed", script=script))     # an orphan space too
            self.assertFalse(permissions.sees_inventory(USER2, "home", script=script))
            self.assertTrue(permissions.sees_inventory(USER2, "user2", script=script))
            self.assertFalse(permissions.sees_inventory(USER2, "user3", script=script))
            self.assertEqual(permissions.inventory_spaces(MATT, script=script), ["home"])
        self.assertIsNone(permissions.inventory_spaces(None, script=True))
        self.assertEqual(permissions.inventory_spaces(None), [])
        self.assertFalse(permissions.sees_inventory({**USER2, "role": "admin"}, "user3"))

    def test_home_records_never_leave_home(self):
        self.assertTrue(permissions.sees_home_records(MATT))
        self.assertTrue(permissions.sees_home_records(USER1))
        self.assertTrue(permissions.sees_home_records(None, script=True))
        for who, script in ((USER2, False), (USER2, True), ({**USER2, "role": "admin"}, False), (None, False)):
            self.assertFalse(permissions.sees_home_records(who, script=script))


class SummaryTests(unittest.TestCase):

    def test_what_each_profile_may_change(self):
        # An admin's rights are his own space's only (E10-S29), with home's records.
        matts = {"admin": True, "runs": True, "accessories": True, "receipts": True, "products": True,
                 "orders": True, "see_accessories": True, "accessory_owners": ["matt", "shared"],
                 "accessory_readers": ["matt", "shared"], "visibility": [],
                 "see_inventory": ["home"], "see_home_records": True,
                 "spaces": ["home"], "deck_spaces": ["home"], "home_player": None,
                 "create": [{"space": "home", "player": None}]}
        self.assertEqual(permissions.summary(MATT, space_ids=SPACES), matts)
        self.assertEqual(permissions.summary(MATT, script=True, space_ids=SPACES), matts)
        self.assertEqual(permissions.summary(None, script=True, space_ids=SPACES),
                         {**matts, "accessory_owners": None, "accessory_readers": None, "see_inventory": None, "spaces": SPACES,
                          "deck_spaces": SPACES, "create": [{"space": s, "player": None} for s in SPACES]})
        member = {"admin": False, "runs": True, "accessories": False, "receipts": False, "products": False,
                  "orders": False, "accessory_owners": [], "accessory_readers": [], "visibility": [], "see_home_records": False}
        self.assertEqual(permissions.summary(USER1, space_ids=SPACES),
                         {**member, "accessories": True, "accessory_owners": ["shared", "user1"], "accessory_readers": ["shared", "user1"],
                          "see_accessories": True, "see_inventory": ["home"], "see_home_records": True,
                          "spaces": ["home"], "deck_spaces": [],                  # home's collection (E10-S43)
                          "home_player": "wife",
                          "create": [{"space": "home", "player": "wife"}]})
        self.assertEqual(permissions.summary(USER2, space_ids=SPACES),
                         {**member, "see_accessories": False, "see_inventory": ["user2"], "spaces": ["user2"],
                          "deck_spaces": ["user2"], "home_player": None,
                          "create": [{"space": "user2", "player": None}]})
        # An admin of a person's space: that space only, and none of home's records.
        self.assertEqual(permissions.summary({**USER2, "role": "admin"}, space_ids=SPACES),
                         {**member, "admin": True, "see_accessories": False, "see_inventory": ["user2"],
                          "spaces": ["user2"], "deck_spaces": ["user2"], "home_player": None,
                          "create": [{"space": "user2", "player": None}]})
        self.assertEqual(permissions.summary(None, space_ids=SPACES),
                         {**member, "see_accessories": False, "see_inventory": [], "spaces": [], "deck_spaces": [],
                          "home_player": None, "create": []})
        # A profile named at home gets the same answer as through the tunnel (E10-S03).
        for who in (MATT, USER1, USER2, USER3):
            with self.subTest(who=who["id"]):
                self.assertEqual(permissions.summary(who, script=True, space_ids=SPACES),
                                 permissions.summary(who, space_ids=SPACES))


if __name__ == "__main__":
    unittest.main()


class RunStartTests(unittest.TestCase):
    # Starting a Forge run follows the simulations setting, by role even on the home network.

    def test_everyone(self):
        for who in (MATT, USER1, USER2):
            self.assertTrue(permissions.can(who, "run.start", "everyone"))
            self.assertTrue(permissions.can(who, "run.start", "everyone", script=True))

    def test_admins_only(self):
        self.assertTrue(permissions.can(MATT, "run.start", "admins"))
        for local in (False, True):
            self.assertEqual(permissions.reason(USER1, "run.start", "admins", script=local), permissions.RUNS_ADMINS)
            self.assertFalse(permissions.can(USER2, "run.start", "admins", script=local))

    def test_paused(self):
        for who in (MATT, USER1, USER2):
            self.assertEqual(permissions.reason(who, "run.start", "paused", script=True), permissions.RUNS_PAUSED)

    def test_a_script_naming_nobody_at_home(self):
        for mode in permissions.RUN_MODES:
            self.assertTrue(permissions.can(None, "run.start", mode, script=True))
            self.assertFalse(permissions.can(None, "run.start", mode))
        self.assertRaises(ValueError, permissions.reason, MATT, "run.start", "nobody")

    def test_only_an_admin_changes_the_setting(self):
        self.assertTrue(permissions.can(MATT, "simulations.edit"))
        self.assertFalse(permissions.can(USER1, "simulations.edit", script=True))
        self.assertTrue(permissions.can(None, "simulations.edit", script=True))


class ActivityScopeTests(unittest.TestCase):
    # Activity stays in the viewer's own space. Only scripts naming nobody get every space.

    def test_admins_see_own_space_and_system_rows(self):
        for local in (False, True):
            self.assertEqual(permissions.activity_scope(MATT, script=local),
                             {"space": "home", "profile": "matt", "system": True})
            self.assertEqual(permissions.activity_scope({**USER2, "role": "admin"}, script=local),
                             {"space": "user2", "profile": "user2", "system": True})
        self.assertEqual(permissions.activity_scope(None, script=True), "all")

    def test_anyone_else_sees_their_own_space_even_at_home(self):
        for local in (False, True):
            self.assertEqual(permissions.activity_scope(USER1, script=local),
                             {"space": "home", "profile": "user1", "system": False})
            self.assertEqual(permissions.activity_scope(USER2, script=local),
                             {"space": "user2", "profile": "user2", "system": False})

    def test_nobody_through_the_tunnel_sees_nothing(self):
        self.assertIsNone(permissions.activity_scope(None))
        self.assertIsNone(permissions.activity_scope({}, script=False))


class PlayRecordTests(unittest.TestCase):
    # Who sees a game or sideboard plan (the Game log, and the play_record rows on the Activity page).
    HOME_GAME = ["casual/gruul", "commander/giada-angels"]
    MIXED = ["casual/gruul", "user2/casual/elves"]
    MEMBERS = ["user2/casual/elves", "user3/commander/goblins"]

    def test_a_script_sees_every_record_and_an_admin_only_his_spaces(self):
        for ids in (self.HOME_GAME, self.MIXED, self.MEMBERS, ["???"], [None], []):
            self.assertTrue(permissions.sees_play_record(None, ids, script=True))
        # E10-S29: the admin role opens no other space's games.
        for local in (False, True):
            self.assertTrue(permissions.sees_play_record(MATT, self.HOME_GAME, script=local))
            self.assertTrue(permissions.sees_play_record(MATT, self.MIXED, script=local))
            for ids in (self.MEMBERS, ["???"], [None], []):
                self.assertFalse(permissions.sees_play_record(MATT, ids, script=local))

    def test_home_profiles_see_the_games_with_a_home_deck(self):
        for local in (False, True):
            self.assertTrue(permissions.sees_play_record(USER1, self.HOME_GAME, script=local))
            self.assertTrue(permissions.sees_play_record(USER1, self.MIXED, script=local))
            self.assertFalse(permissions.sees_play_record(USER1, self.MEMBERS, script=local))

    def test_a_member_sees_only_the_records_with_their_own_decks(self):
        for local in (False, True):         # at home too: the chooser names User2
            self.assertFalse(permissions.sees_play_record(USER2, self.HOME_GAME, script=local))
            self.assertTrue(permissions.sees_play_record(USER2, self.MIXED, script=local))
            self.assertTrue(permissions.sees_play_record(USER2, self.MEMBERS, script=local))
            self.assertTrue(permissions.sees_play_record(USER3, self.MEMBERS, script=local))
            self.assertFalse(permissions.sees_play_record(USER3, self.MIXED, script=local))

    def test_an_unreadable_deck_id_counts_only_for_admins(self):
        # Not home's, as spaces.space_of would say: a record of unknown owner isn't shown at home.
        for ids in (["???"], ["product"], [None], [42], [], None):
            self.assertFalse(permissions.sees_play_record(USER1, ids))
            self.assertFalse(permissions.sees_play_record(USER2, ids))
        self.assertTrue(permissions.sees_play_record(USER1, ["???", "casual/gruul"]))

    def test_a_given_space_of_is_used(self):
        self.assertTrue(permissions.sees_play_record(USER2, ["x"], space_of=lambda d: "user2"))
        self.assertFalse(permissions.sees_play_record(USER2, ["x"], space_of=lambda d: None))

    def test_nobody_through_the_tunnel_sees_none(self):
        self.assertFalse(permissions.sees_play_record(None, self.HOME_GAME))
        self.assertFalse(permissions.sees_play_record({}, self.HOME_GAME, script=False))
