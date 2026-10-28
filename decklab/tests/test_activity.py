"""Tests for the Activity page's answers (lib/api/activity.py): who sees which changes of the audit
trail, through which fields, with which message, and the paging and summaries.

Most run on a MemoryStore, whose rows have the audit trail's shape, and on fixture rows shaped
exactly like to_jsonb's (the tables a MemoryStore never writes: space, profile, profile_email, and
tables of later phases). ActivityDbTests writes real audit rows through PgStore and profiles_sync;
it needs the local PostgreSQL server and skips without it (db_support.py).

Run from the repo root: python -m unittest decklab.tests.test_activity
"""
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from decklab.lib import access, permissions, state
from decklab.lib.api import activity, guard, settings
from decklab.lib.api.common import ApiError
from decklab.lib.state import rules
from decklab.lib.state.memory import MemoryStore
from decklab.tests import db_support

PROFILES = [
    {"id": "matt", "name": "Matt", "plays_as": "user", "role": "admin", "space": "home"},
    {"id": "user1", "name": "User1", "plays_as": "wife", "role": "member", "space": "home"},
    {"id": "user2", "name": "User2", "plays_as": None, "role": "member", "space": "user2"},
]
BY_ID = {p["id"]: p for p in PROFILES}
MATT = state.Actor("matt", "Matt", "home")
USER1 = state.Actor("user1", "User1", "home")
USER2 = state.Actor("user2", "User2", "tunnel")
CLAUDE = state.Actor("claude", "Claude", None, "cli")
ALL, HOME, USER2S = "all", {"space": "home", "profile": "user1"}, {"space": "user2", "profile": "user2"}
ADMIN = {"space": "home", "profile": "matt", "system": True}


def _entry(name, set_code="", number="", notes="", source=""):
    return {"name": name, "set": set_code, "number": number, "notes": notes, "source": source}


def _game(record_id, a, b, result="a", revision=1):
    return {"version": 1, "id": record_id, "kind": "games", "revision": revision,
            "created_on": "2026-10-11T01:02:03+00:00", "updated_on": "2026-10-11T01:02:03+00:00",
            "updated_by": "Matt", "date": "2026-10-11", "result": result, "notes": "",
            "sides": [{"id": a[0], "title": a[1]}, {"id": b[0], "title": b[1]}]}


def _change(rows, actor="system", source="sync", message="Something private", reason=None, change_id=1):
    return {"id": change_id, "at": "2026-10-11T01:02:03+00:00", "actor": actor, "source": source, "via": None,
            "message": message, "reason": reason, "rows": rows}


def _row(table, op, key, before=None, after=None):
    return {"table": table, "op": op, "key": key, "before": before, "after": after}


# Rows as to_jsonb gives them for the tables only profiles_sync writes.
EMAIL_ROW = _row("profile_email", "INSERT", {"email": "user1@example.com", "profile_id": "user1"},
                 after={"email": "user1@example.com", "profile_id": "user1"})
SPACE_ROW = _row("space", "INSERT", {"id": "user2"}, after={"id": "user2"})
PROFILE_ROW = _row("profile", "UPDATE", {"id": "user1"},
                   before={"id": "user1", "name": "User1", "role": "member", "position": 1, "plays_as": "wife",
                           "space_id": "home"},
                   after={"id": "user1", "name": "User1", "role": "admin", "position": 1, "plays_as": "wife",
                          "space_id": "home"})
FUTURE_ROW = _row("deck_line", "INSERT", {"id": 7}, after={"id": 7, "secret": "x"})


class _Store(unittest.TestCase):
    """A MemoryStore installed as the active store, with config.json's profiles faked."""

    def setUp(self):
        self.store = MemoryStore()
        self.addCleanup(state.use(self.store))
        patcher = mock.patch.object(settings, "_config_profiles", return_value=[dict(p) for p in PROFILES])
        self.profiles = patcher.start()
        self.addCleanup(patcher.stop)

    def view(self, who=None, *, tunnel=False, **params):
        """activity_view() as who sees it: on the home network naming who, or through the tunnel as who."""
        if tunnel:
            with access.using({"profile": who, "email": "", "remote": True}):
                return activity.activity_view(**params)
        with access.viewing(who):
            return activity.activity_view(**params)

    def write_everything(self):
        """One change of each kind: Matt's and User2's wishlists, User1's settings, the simulations
        mode, a home game and one of User2's, the command line on User1's wishlist, and a wishlist
        of a profile config.json doesn't list."""
        s = self.store
        s.wishlist_add("matt", _entry("Plains", "sld", "1513", notes="for the dogs"), MATT,
                       "Add Plains to Matt's wishlist")
        s.settings_put("user1", {"theme": "dark"}, USER1, "Change User1's settings: theme")
        s.wishlist_add("user2", _entry("Llanowar Elves", "fdn", "227"), USER2,
                       "Add Llanowar Elves to User2's wishlist")
        s.simulation_mode_set("admins", MATT, "Set simulations to admins")
        s.play_put("games", _game("a" * 32, ("casual/gruul", "Gruul"), ("casual/otters", "Otters")), None, MATT,
                   "Save game Gruul vs Otters")
        s.play_put("games", _game("b" * 32, ("user2/casual/elves", "Elves"), ("user2/casual/goblins", "Goblins"),
                                  "draw"), None, USER2, "Save game Elves vs Goblins")
        s.wishlist_add("user1", _entry("Island"), CLAUDE, "Add Island: a secret birthday plan")
        s.wishlist_remove("user1", "Island", CLAUDE, "Remove Island again", reason="bought it as a present")
        s.wishlist_add("user4", _entry("Swamp"), CLAUDE, "Add Swamp to User4's wishlist")

    @staticmethod
    def messages(answer):
        return [c["message"] for c in answer["changes"]]


class VisibilityTests(_Store):

    def test_an_admin_sees_own_space_while_a_script_also_sees_the_members_changes(self):
        self.write_everything()
        # A named admin no longer sees another space's games or settings (E10-S29); a script does.
        for who, theirs, own in (("matt", [], ["Add Plains to Matt's wishlist"]),
                                 (None, ["Save game Elves vs Goblins"], [])):
            with self.subTest(who=who):
                answer = self.view(who)
                self.assertEqual(answer["everything"], who is None)
                self.assertEqual(self.messages(answer), [
                    *theirs, "Save game Gruul vs Otters", "Set simulations to admins",
                    "Change User1's settings: theme", *own])
                text = json.dumps(answer)
                for private in ("Island", "Swamp", "Llanowar", "secret", "present", "User1's wishlist"):
                    self.assertNotIn(private, text)
                self.assertIsNone(answer["next"])

    def test_user1_sees_the_home_space_her_own_wishlist_and_the_simulations_setting(self):
        self.write_everything()
        answer = self.view("user1")
        self.assertFalse(answer["everything"])
        self.assertEqual(self.messages(answer), [
            None, None,                                     # the command line's words are left out
            "Save game Gruul vs Otters", "Set simulations to admins",
            "Change User1's settings: theme"])             # not Matt's wishlist
        self.assertEqual([c["rows"][0]["summary"] for c in answer["changes"][:2]],
                         ["Removed Island from your wishlist", "Added Island to your wishlist"])
        self.assertIsNone(answer["changes"][0]["reason"])
        self.assertNotIn("secret", json.dumps(answer))
        self.assertNotIn("present", json.dumps(answer))
        self.assertNotIn("User4", json.dumps(answer))
        self.assertNotIn("User2", json.dumps(answer))
        self.assertNotIn("Plains", json.dumps(answer))

    def test_user2_sees_his_own_space_and_the_simulations_setting(self):
        self.write_everything()
        for tunnel in (False, True):
            with self.subTest(tunnel=tunnel):
                answer = self.view("user2", tunnel=tunnel)
                self.assertEqual(self.messages(answer), ["Save game Elves vs Goblins", "Set simulations to admins",
                                                         "Add Llanowar Elves to User2's wishlist"])
                self.assertEqual(answer["changes"][0]["rows"][0]["summary"],
                                 "Saved a game: Elves vs Goblins, a draw")

    def test_a_viewer_config_no_longer_lists_counts_as_nobody_at_home(self):
        # A decision: at home, a chooser naming a profile since removed from config.json is a
        # request naming nobody. Outside a request (as here) that's a script, which sees
        # everything; a real request naming it isn't a script and sees nothing (E10-S35,
        # test_script_rule).
        self.write_everything()
        answer = self.view("nobody-known")
        self.assertTrue(answer["everything"])
        self.assertEqual(len(answer["changes"]), 4)        # no wishlist: they're their owners' only

    def test_through_the_tunnel_nobody_sees_nothing(self):
        self.write_everything()
        with access.using({"profile": "user4", "email": "", "remote": True}), self.assertRaises(ApiError) as e:
            activity.activity_view()
        self.assertEqual(e.exception.status, 403)
        with access.using({"profile": None, "email": "", "remote": True}), \
                mock.patch.object(guard, "viewer", return_value=None):
            self.assertEqual(activity.activity_view(),
                             {"changes": [], "next": None, "everything": False, "cards": {}})

    def test_the_actor_sees_their_own_messages_and_names_come_from_config_now(self):
        self.store.wishlist_add("user1", _entry("Forest"), state.Actor("user1", "User1", None, "cli"),
                                "Add Forest: for the elves deck")
        self.store.settings_put("user1", {"theme": "dark"}, state.Actor("user1", "User1", None, "cli"),
                                "Dark: easier at night")
        self.assertEqual(self.messages(self.view("user1")), ["Dark: easier at night", "Add Forest: for the elves deck"])
        self.profiles.return_value = [dict(p, name="User1 H") if p["id"] == "user1" else p for p in PROFILES]
        change = self.view("user1")["changes"][1]
        self.assertEqual((change["actor"], change["actor_name"]), ("user1", "User1 H"))
        self.assertEqual(change["rows"][0]["summary"], "Added Forest to your wishlist")      # only hers to see
        change = self.view("matt")["changes"][0]
        self.assertEqual((change["actor"], change["actor_name"]), ("user1", "User1 H"))
        self.assertEqual(change["rows"][0]["summary"], "User1 H's theme: dark")

    def test_fields_outside_the_allow_list_are_never_sent(self):
        self.write_everything()
        for who in ("matt",):                               # only Matt sees his wishlist
            answer = self.view(who)
            text = json.dumps(answer)
            self.assertNotIn("for the dogs", text)          # wishlist notes
            self.assertNotIn("profile_id", text)
            plains = answer["changes"][-1]["rows"][0]
            self.assertEqual(plains, {"table": "wishlist_entry", "op": "INSERT",
                                      "summary": "Added Plains (SLD 1513) to your wishlist", "before": None,
                                      "after": {"name": "Plains", "set_code": "sld", "collector_number": "1513"}})
            game = next(c for c in answer["changes"] if c["message"] == "Save game Gruul vs Otters")["rows"][0]
            self.assertEqual(game, {"table": "play_record", "op": "INSERT",
                                    "summary": "Saved a game: Gruul vs Otters, Gruul won"})

    def test_paging_with_nothing_visible(self):
        for i in range(5):
            self.store.settings_put("matt", {"theme": "dark" if i % 2 else "light"}, MATT, f"Change {i}")
        nothing = {"changes": [], "next": None, "everything": False, "cards": {}}
        self.assertEqual(self.view("user2", limit="2"), nothing)
        with mock.patch.object(rules, "SCAN_CAP", 3):
            self.assertEqual(self.view("user2", limit="2"), dict(nothing, next=3))
            self.assertEqual(self.view("user2", before="3", limit="2"),
                             {"changes": [], "next": None, "everything": False, "cards": {}})

    def test_paging_through_visible_changes(self):
        for i in range(5):
            self.store.settings_put("user1", {"theme": "dark" if i % 2 else "light"}, USER1, f"Change {i}")
        first = self.view("user1", limit="2")
        self.assertEqual((self.messages(first), first["next"]), (["Change 4", "Change 3"], 4))
        second = self.view("user1", before=str(first["next"]), limit="2")
        self.assertEqual((self.messages(second), second["next"]), (["Change 2", "Change 1"], 2))
        self.assertEqual(self.messages(self.view("user1", before="2")), ["Change 0"])

    def test_bad_paging_values(self):
        for params in ({"before": "abc"}, {"before": "0"}, {"before": "-1"}, {"limit": "0"}, {"limit": "101"},
                       {"limit": "1.5"}, {"limit": ""}, {"before": "9" * 19}):
            with self.subTest(params=params), self.assertRaises(ApiError) as e:
                self.view("matt", **params)
            self.assertEqual(e.exception.status, 400)

    def test_a_database_that_is_down_answers_503(self):
        self.store.down = True
        with self.assertRaises(ApiError) as e:
            self.view("matt")
        self.assertEqual((e.exception.status, e.exception.extra), (503, {"reason": "database"}))


class WishlistPrivacyTests(_Store):
    # A wishlist is its owner's only (permissions.sees_wishlist): on the Activity page too.

    def setUp(self):
        super().setUp()
        self.profiles.return_value = [dict(p) for p in PROFILES] + [
            {"id": "user4", "name": "User4", "plays_as": None, "role": "member", "space": "user4"}]

    def test_the_matrix(self):
        self.store.wishlist_add("user1", _entry("Plains", "sld", "1513"), USER1, "Add Plains to User1's wishlist")
        self.store.wishlist_remove("user1", "Plains", CLAUDE, "Remove Plains: a present", reason="bought it")
        viewers = (("user1", False, ["Add Plains to User1's wishlist"]),        # the owner (CLI words hidden)
                   ("user1", True, ["Add Plains to User1's wishlist"]),         # the owner through the tunnel
                   ("matt", False, []), ("matt", True, []),                       # an admin
                   ("user2", False, []), ("user4", True, []),                  # people with their own space
                   (None, False, []))                                             # home, naming nobody
        for who, tunnel, messages in viewers:
            with self.subTest(who=who, tunnel=tunnel):
                answer = self.view(who, tunnel=tunnel)
                text = json.dumps(answer)
                if who == "user1":
                    self.assertEqual(self.messages(answer), [None, *messages])
                    self.assertEqual([c["rows"][0]["summary"] for c in answer["changes"]],
                                     ["Removed Plains (SLD 1513) from your wishlist",
                                      "Added Plains (SLD 1513) to your wishlist"])
                    self.assertIsNone(answer["changes"][0]["reason"])
                else:
                    self.assertEqual(answer["changes"], [])
                    self.assertNotIn("Plains", text)
                self.assertNotIn("present", text)
                self.assertNotIn("bought", text)

    def test_a_mixed_change_set_shows_only_the_visible_rows_and_no_words(self):
        wish = _row("wishlist_entry", "INSERT", {"position": 0, "profile_id": "user1"},
                    after={"name": "Island", "set_code": None, "collector_number": None, "profile_id": "user1",
                           "notes": "", "source": "", "position": 0})
        theme = _row("profile_setting", "INSERT", {"key": "theme", "profile_id": "matt"},
                     after={"key": "theme", "value": "dark", "profile_id": "matt"})
        change = _change([wish, theme], actor="matt", source="web", message="Import: Island for User1", reason="r")
        for scope, me, words in ((ALL, "matt", "Your theme: dark"), (ALL, None, "Matt's theme: dark"),
                                 ({"space": "home", "profile": "matt"}, None, "Your theme: dark")):
            shown = activity.visible_change(change, scope, BY_ID, me=me)
            self.assertEqual([r["summary"] for r in shown["rows"]], [words])
            self.assertEqual((shown["message"], shown["reason"]), (None, None))
        shown = activity.visible_change(change, HOME, BY_ID)           # User1 sees both rows
        self.assertEqual(len(shown["rows"]), 2)
        self.assertEqual(shown["message"], "Import: Island for User1")
        self.assertIsNone(activity.visible_change(change, USER2S, BY_ID))

    def test_only_wishlist_rows_hidden_leaves_the_change_out(self):
        wish = _row("wishlist_entry", "DELETE", {"position": 0, "profile_id": "user2"},
                    before={"name": "Forest", "profile_id": "user2", "position": 0})
        change = _change([wish, wish], actor="claude", source="cli", message="Clear User2's wishlist")
        for scope, me in ((ALL, "matt"), (ALL, None), (HOME, None)):
            self.assertIsNone(activity.visible_change(change, scope, BY_ID, me=me))
        self.assertEqual(len(activity.visible_change(change, USER2S, BY_ID)["rows"]), 2)

    def test_an_orphan_wishlist_is_nobodys(self):
        wish = _row("wishlist_entry", "INSERT", {"position": 0, "profile_id": "user3"},
                    after={"name": "Forest", "profile_id": "user3", "position": 0})
        for scope, me in ((ALL, "matt"), (ALL, None), ({"space": "user3", "profile": "user3"}, None)):
            self.assertIsNone(activity.visible_change(_change([wish]), scope, BY_ID, me=me))


class SummaryTests(_Store):

    def test_summaries_in_plain_words(self):
        s = self.store
        s.settings_put("matt", {"theme": "system"}, MATT, "Set")
        s.settings_put("matt", {"theme": "dark"}, MATT, "Change")
        s.settings_put("matt", {"theme": None}, MATT, "Clear")
        s.simulation_mode_set("admins", MATT, "Admins")
        s.simulation_mode_set("everyone", MATT, "Everyone")
        s.wishlist_add("matt", _entry("Plains", "sld", "1513"), CLAUDE, "Add")
        s.wishlist_set("matt", "Plains", CLAUDE, "Edit", set="", number="", notes="cheaper")
        s.play_put("sideboards", {"version": 1, "id": "c" * 32, "kind": "sideboards", "revision": 1,
                                  "created_on": "2026-10-11T01:02:03+00:00", "updated_on": "2026-10-11T01:02:03+00:00",
                                  "updated_by": "Matt", "deck": {"id": "casual/gruul", "title": "Gruul"},
                                  "opponent": {"id": "casual/otters", "title": "Otters"}, "out": [], "in": [],
                                  "after": {}, "notes": ""}, None, MATT, "Plan")
        summaries = [c["rows"][0]["summary"] for c in reversed(self.view("matt")["changes"])]
        self.assertEqual(summaries, [
            "Your theme: system", "Your theme: system → dark", "Your theme: dark → the default",
            "Simulations: admins", "Simulations: admins → everyone",
            "Added Plains (SLD 1513) to your wishlist",
            "Changed Plains on your wishlist: printing SLD 1513 → any, notes",
            "Saved a sideboard plan: Gruul vs Otters"])

    def test_actor_names(self):
        s = self.store
        s.settings_put("matt", {"theme": "dark"}, state.Actor("home", "someone at home", "home"), "A")
        s.settings_put("matt", {"theme": "light"}, CLAUDE, "B")
        s.settings_put("matt", {"theme": "system"}, state.Actor("user4", "User4", "home"), "C")
        names = [(c["actor"], c["actor_name"]) for c in self.view("matt")["changes"]]
        self.assertEqual(names, [("user4", "user4"), ("claude", "Claude"), ("home", "someone at home")])
        names = [(c["actor"], c["actor_name"]) for c in self.view("user1")["changes"]]
        self.assertEqual(names, [(None, "someone"), ("claude", "Claude"), ("home", "someone at home")])


class FixtureRowTests(unittest.TestCase):
    # visible_change on rows shaped like to_jsonb's, including the tables only profiles_sync writes.

    def test_profile_emails_are_redacted_and_only_admins_see_profiles_and_spaces(self):
        change = _change([EMAIL_ROW, SPACE_ROW, PROFILE_ROW])
        shown = activity.visible_change(change, ALL, BY_ID)
        self.assertEqual(shown["rows"], [
            {"table": "profile_email", "op": "INSERT", "summary": "An email address changed"},
            {"table": "space", "op": "INSERT", "summary": "Added User2's space"},     # by name, not its id
            {"table": "profile", "op": "UPDATE", "summary": "Changed the profile User1: role member → admin"}])
        self.assertNotIn("example.com", json.dumps(shown))
        self.assertEqual(shown["actor_name"], "System")
        for scope in (HOME, USER2S):
            self.assertIsNone(activity.visible_change(change, scope, BY_ID))

    def test_unknown_tables_are_admin_only_and_say_only_changed(self):
        change = _change([FUTURE_ROW])
        self.assertEqual(activity.visible_change(change, ALL, BY_ID)["rows"],
                         [{"table": "deck_line", "op": "INSERT", "summary": "changed"}])
        self.assertIsNone(activity.visible_change(change, HOME, BY_ID))

    def test_change_sets_without_rows_are_admin_only(self):
        change = _change([])
        self.assertEqual(activity.visible_change(change, ALL, BY_ID)["rows"], [])
        self.assertIsNone(activity.visible_change(change, HOME, BY_ID))

    def test_orphan_profile_rows_are_admin_only(self):
        row = _row("profile_setting", "INSERT", {"key": "theme", "profile_id": "user4"},
                   after={"key": "theme", "value": "dark", "profile_id": "user4"})
        change = _change([row], actor="user4", source="web", message="Change User4's settings: theme")
        shown = activity.visible_change(change, ALL, BY_ID)
        self.assertEqual(shown["rows"][0]["summary"], "user4's theme: dark")
        self.assertEqual(shown["actor_name"], "user4")
        for scope in (HOME, USER2S):
            self.assertIsNone(activity.visible_change(change, scope, BY_ID))

    def test_the_allow_list_ignores_extra_columns(self):
        row = _row("wishlist_entry", "DELETE", {"position": 0, "profile_id": "user1"},
                   before={"name": "Plains", "notes": "a present", "source": "magic/buylists/x.md", "position": 0,
                           "set_code": None, "profile_id": "user1", "collector_number": None, "added_later": "x"})
        mode = _row("simulation_mode", "UPDATE", {"id": True},
                    before={"id": True, "mode": "admins", "since": "2026-10-11T11:02:03.5+10:00", "set_by": "matt",
                            "set_by_name": "Matt"},
                    after={"id": True, "mode": "paused", "since": "2026-10-11T12:02:03+10:00", "set_by": "matt",
                           "set_by_name": "Matt", "added_later": "x"})
        shown = activity.visible_change(_change([row, mode], actor="user1", source="web", message="M"), HOME, BY_ID)
        self.assertEqual(shown["rows"], [
            {"table": "wishlist_entry", "op": "DELETE", "summary": "Removed Plains from your wishlist",
             "before": {"name": "Plains", "set_code": None, "collector_number": None}, "after": None},
            {"table": "simulation_mode", "op": "UPDATE", "summary": "Simulations: admins → paused",
             "before": {"mode": "admins", "set_by_name": "Matt"}, "after": {"mode": "paused", "set_by_name": "Matt"}}])

    def test_play_records_follow_any_of_their_decks(self):
        row = _row("play_record", "UPDATE", {"id": "a" * 32, "kind": "games"},
                   before={"id": "a" * 32, "kind": "games", "content": {"sides": [{"id": "casual/gruul", "title": "Gruul"},
                                                                                   {"id": "casual/otters", "title": "Otters"}]},
                           "deck_ids": ["casual/gruul", "casual/otters"], "revision": 1},
                   after={"id": "a" * 32, "kind": "games", "content": {"result": "b", "sides": [
                       {"id": "casual/gruul", "title": "Gruul"}, {"id": "user2/casual/elves", "title": "Elves"}]},
                       "deck_ids": ["casual/gruul", "user2/casual/elves"], "revision": 2})
        change = _change([row], actor="matt", source="web", message="Save game Gruul vs Elves")
        # Each viewer reads the other space's side only by its space, and the message (which names
        # both decks) only when it sees every deck the record names (E10-S32).
        for scope, summary, message in (
                (ALL, "Changed a game: Gruul vs Elves, Elves won", "Save game Gruul vs Elves"),
                (HOME, "Changed a game: Gruul vs one of User2's decks, one of User2's decks won", None),
                (USER2S, "Changed a game: one of the home decks vs Elves, Elves won", None)):
            with self.subTest(scope=scope):
                shown = activity.visible_change(change, scope, BY_ID)
                self.assertEqual(shown["rows"], [{"table": "play_record", "op": "UPDATE", "summary": summary}])
                self.assertEqual(shown["message"], message)
                if scope is USER2S:
                    self.assertNotIn("Gruul", json.dumps(shown))
                    self.assertNotIn("Otters", json.dumps(shown))
        self.assertIsNone(activity.visible_change(change, {"space": "user3", "profile": "user3"}, BY_ID))
        # Who saved it goes only to the space that recorded it (home's, a game saved before
        # E10-S32 with a home side), as the Game log's updated_by: User2 is told "someone".
        self.assertEqual({k: activity.visible_change(change, USER2S, BY_ID)[k] for k in ("actor", "actor_name")},
                         {"actor": None, "actor_name": activity.SOMEONE})
        self.assertNotIn("Matt", json.dumps(activity.visible_change(change, USER2S, BY_ID)))
        self.assertEqual(activity.visible_change(change, HOME, BY_ID)["actor"], "matt")
        self.assertEqual(activity.visible_change(change, ALL, BY_ID)["actor"], "matt")
        # A game User2's space recorded: User2's saver is named to him, never to home.
        theirs = _row("play_record", "UPDATE", {"id": "c" * 32, "kind": "games"},
                      after={"id": "c" * 32, "kind": "games", "content": {"space": "user2", "result": "a", "sides": [
                          {"id": "user2/casual/elves", "title": "Elves"}, {"id": "casual/gruul", "title": "Gruul"}]},
                          "deck_ids": ["user2/casual/elves", "casual/gruul"], "revision": 2})
        for actor in ("user2", "user1"):
            with self.subTest(actor=actor):
                saved = _change([theirs], actor=actor, source="web", message="Save game Elves vs Gruul")
                mine = activity.visible_change(saved, USER2S, BY_ID)
                home = activity.visible_change(saved, HOME, BY_ID)
                if actor == "user2":
                    self.assertEqual(mine["actor"], "user2")
                    self.assertEqual((home["actor"], home["actor_name"]), (None, activity.SOMEONE))
                else:   # User1 saving home's side: she sees her own name, User2 (the recorder) sees hers
                    self.assertEqual(home["actor"], "user1")
                    self.assertEqual(mine["actor"], "user1")
        # A named admin is kept to his own space's decks too.
        shown = activity.visible_change(change, ALL, BY_ID, me="matt", spaces=["home"])
        self.assertEqual((shown["rows"][0]["summary"], shown["message"]),
                         ("Changed a game: Gruul vs one of User2's decks, one of User2's decks won", None))
        # A game of home's decks alone keeps its words for home.
        home_only = _row("play_record", "INSERT", {"id": "b" * 32, "kind": "games"},
                         after={"id": "b" * 32, "kind": "games", "content": {"result": "a", "sides": [
                             {"id": "casual/gruul", "title": "Gruul"}, {"id": "casual/otters", "title": "Otters"}]},
                             "deck_ids": ["casual/gruul", "casual/otters"], "revision": 1})
        shown = activity.visible_change(_change([home_only], actor="matt", source="web", message="Save game Gruul vs Otters"),
                                        HOME, BY_ID)
        self.assertEqual(shown["message"], "Save game Gruul vs Otters")

    def test_sideboard_plans_belong_to_their_decks_space(self):
        # A plan of User2's deck against a home deck: User2's alone, the opponent by its space only.
        row = _row("play_record", "INSERT", {"id": "d" * 32, "kind": "sideboards"},
                   after={"id": "d" * 32, "kind": "sideboards", "revision": 1,
                          "content": {"deck": {"id": "user2/casual/elves", "title": "Elves"},
                                      "opponent": {"id": "casual/gruul", "title": "Gruul"}},
                          "deck_ids": ["user2/casual/elves", "casual/gruul"]})
        change = _change([row], actor="user2", source="web", message="Save sideboard plan Elves vs Gruul")
        self.assertIsNone(activity.visible_change(change, HOME, BY_ID))
        self.assertIsNone(activity.visible_change(change, ALL, BY_ID, me="matt", spaces=["home"]))
        shown = activity.visible_change(change, USER2S, BY_ID)
        self.assertEqual((shown["rows"][0]["summary"], shown["message"]),
                         ("Saved a sideboard plan: Elves vs one of the home decks", None))
        self.assertEqual(activity.visible_change(change, ALL, BY_ID)["message"], "Save sideboard plan Elves vs Gruul")

    def test_play_records_with_unreadable_deck_ids_are_admin_only(self):
        row = _row("play_record", "INSERT", {"id": "c" * 32, "kind": "games"},
                   after={"id": "c" * 32, "kind": "games", "content": {}, "deck_ids": ["???"], "revision": 1})
        change = _change([row], actor="matt", source="web", message="Save game")
        self.assertEqual(activity.visible_change(change, ALL, BY_ID)["rows"][0]["summary"],
                         "Saved a game: a deck vs a deck")
        for scope in (HOME, USER2S):
            self.assertIsNone(activity.visible_change(change, scope, BY_ID))

    def test_play_records_ask_the_game_logs_rule(self):
        # One rule for the Game log and the Activity page (permissions.sees_play_record).
        row = _row("play_record", "INSERT", {"id": "a" * 32, "kind": "games"},
                   after={"id": "a" * 32, "kind": "games", "content": {}, "revision": 1,
                          "deck_ids": ["casual/gruul", "user2/casual/elves"]})
        change = _change([row], actor="matt", source="web", message="Save game")
        with mock.patch.object(activity.permissions, "sees_play_record", return_value=False) as rule:
            self.assertIsNone(activity.visible_change(change, HOME, BY_ID))
        profile, ids = rule.call_args.args
        self.assertEqual((profile["id"], profile["space"], ids), ("user1", "home", ["casual/gruul", "user2/casual/elves"]))
        self.assertIsNotNone(activity.visible_change(change, ALL, BY_ID))      # an admin's "all" sees every one

    def test_the_message_rule(self):
        rows = [_row("simulation_mode", "INSERT", {"id": True}, after={"id": True, "mode": "everyone",
                                                                        "set_by": None, "set_by_name": "Matt"})]
        for scope, source, actor, expected in (
                (HOME, "web", "matt", ("Words", "why")), (HOME, "migration", "system", (None, None)),
                (ALL, "migration", "system", ("Words", "why")), (HOME, "cli", "user1", ("Words", "why"))):
            with self.subTest(scope=scope, source=source, actor=actor):
                shown = activity.visible_change(_change(rows, actor, source, "Words", "why"), scope, BY_ID)
                self.assertEqual((shown["message"], shown["reason"]), expected)

    def test_scopes_from_permissions(self):
        self.assertEqual(permissions.activity_scope(BY_ID["matt"]), ADMIN)
        self.assertEqual(permissions.activity_scope(BY_ID["user1"], script=True), dict(HOME, system=False))
        self.assertEqual(permissions.activity_scope(BY_ID["user2"]), dict(USER2S, system=False))


def _accessory(owner, quantity=100, **more):
    return {"id": f"{owner}-sleeves", "kind": "sleeves", "owner": owner, "brand": "DS", "name": "Matte",
            "colour": "pink", "quantity": quantity, "capacity": "", "image": "", "crop": "", "link": "https://x",
            "image_source": "", "notes": "a present", **more}


def _deck(space="home", deck_id="casual/gruul", kit_version=0, **more):
    return {"id": deck_id, "space_id": space, "kind": "casual", "slug": deck_id.rsplit("/", 1)[1], "title": "Gruul",
            "status": "idea", "played_by": "user", "revision": 1, "kit_version": kit_version, **more}


class DeckAndAccessoryRowTests(unittest.TestCase):
    """Phase 4's deck and accessory rows (the phase 4 design's R6a)."""

    def test_an_accessory_row_is_its_owners_only_admins_included(self):
        row = _row("accessory", "INSERT", {"id": "user1-sleeves"}, after=_accessory("user1"))
        change = _change([row], actor="user1", source="web", message="Deck Lab: add sleeves DS Matte (pink)")
        mine = activity.visible_change(change, HOME, BY_ID)
        self.assertEqual(mine["rows"], [{"table": "accessory", "op": "INSERT",
                                         "summary": "Added the sleeves Matte (pink)",
                                         "before": None, "after": {"id": "user1-sleeves", "kind": "sleeves",
                                                                   "name": "Matte", "colour": "pink",
                                                                   "quantity": 100}}])
        self.assertEqual(mine["message"], "Deck Lab: add sleeves DS Matte (pink)")
        self.assertIsNone(activity.visible_change(change, ALL, BY_ID, me="matt"))          # not by role
        self.assertIsNone(activity.visible_change(change, USER2S, BY_ID))
        self.assertEqual(len(activity.visible_change(change, ALL, BY_ID)["rows"]), 1)       # a script at home
        shared = _change([_row("accessory", "UPDATE", {"id": "shared-sleeves"}, before=_accessory("shared"),
                               after=_accessory("shared", 80, notes="moved"))], actor="user1", source="cli",
                         message="Words of hers")
        shown = activity.visible_change(shared, ALL, BY_ID, me="matt")
        self.assertEqual(shown["rows"][0]["summary"], "Changed the sleeves Matte (pink): quantity 100 → 80, details")
        self.assertEqual((shown["message"], shown["reason"]), (None, None))         # a kit change: its actor's only
        self.assertEqual(activity.visible_change(shared, HOME, BY_ID)["message"], "Words of hers")
        given = _change([_row("accessory", "UPDATE", {"id": "user1-sleeves"}, before=_accessory("user1"),
                              after=_accessory("shared"))], actor="user1", source="web", message="M")
        self.assertIsNone(activity.visible_change(given, ALL, BY_ID, me="matt"))    # before and after must be his

    def test_deck_rows_follow_the_space_and_never_show_a_kit(self):
        row = _row("deck", "UPDATE", {"id": "user2/casual/elves"},
                   before=_deck("user2", "user2/casual/elves"),
                   after=_deck("user2", "user2/casual/elves", status="built"))
        change = _change([row], actor="user2", source="web", message="Deck Lab: save Elves (edited by User2)")
        shown = activity.visible_change(change, USER2S, BY_ID)
        self.assertEqual(shown["rows"], [{"table": "deck", "op": "UPDATE",
                                          "summary": "Changed your deck Gruul: status idea → built",
                                          "before": {"id": "user2/casual/elves", "title": "Gruul", "status": "idea",
                                                     "played_by": "user"},
                                          "after": {"id": "user2/casual/elves", "title": "Gruul",
                                                    "status": "built", "played_by": "user"}}])
        self.assertEqual(shown["message"], "Deck Lab: save Elves (edited by User2)")
        self.assertIsNone(activity.visible_change(change, HOME, BY_ID))
        self.assertEqual(len(activity.visible_change(change, ALL, BY_ID, me="matt")["rows"]), 1)
        home = _change([_row("deck", "INSERT", {"id": "casual/gruul"}, after=_deck())], actor="matt", source="web",
                       message="M")
        self.assertEqual(activity.visible_change(home, HOME, BY_ID)["rows"][0]["summary"], "Added the deck Gruul")

    def test_a_deck_kit_change_hides_the_words_from_everyone_but_its_actor(self):
        row = _row("deck", "UPDATE", {"id": "casual/gruul"}, before=_deck(), after=_deck(kit_version=1))
        self.assertTrue(rules.kit_changed(row))
        self.assertFalse(rules.kit_changed(_row("deck", "UPDATE", {"id": "casual/gruul"}, before=_deck(),
                                                after=_deck(status="built"))))
        self.assertTrue(rules.kit_changed(_row("deck", "INSERT", {"id": "casual/gruul"}, after=_deck(kit_version=2))))
        self.assertTrue(rules.kit_changed(_row("accessory", "DELETE", {"id": "x"}, before=_accessory("matt"))))
        change = _change([row], actor="user1", source="web", message="Deck Lab: set sleeves of Gruul (by User1)")
        self.assertIsNone(activity.visible_change(change, ALL, BY_ID, me="matt")["message"])
        self.assertEqual(activity.visible_change(change, HOME, BY_ID)["message"],
                         "Deck Lab: set sleeves of Gruul (by User1)")
        self.assertEqual(activity.visible_change(change, HOME, BY_ID)["rows"][0]["summary"],
                         "Changed the deck Gruul")


# ------------------------------------------------------------------ headlines, kinds, links and filters

def _card_row(space, name, number, qty=1, op="INSERT", before_qty=None):
    after = {"space_id": space, "name": name, "set_code": "fdn", "collector_number": str(number),
             "finish": "nonfoil", "quantity": qty, "position": 1}
    before = dict(after, quantity=before_qty) if before_qty is not None else None
    if op == "DELETE":
        return _row("collection_card", op, {"id": 1}, before=after)
    return _row("collection_card", op, {"id": 1}, before=before, after=after)


def _component(order_id, before_status, after_status, cid="cards", kind="cards"):
    record = {"order_id": order_id, "id": cid, "kind": kind, "status": before_status, "received_on": ""}
    return _row("order_component", "UPDATE", {"order_id": order_id, "id": cid}, before=record,
                after=dict(record, status=after_status, received_on="2026-10-12" if after_status == "received" else ""))


ORDERS = {"2026-10-05-shop-c": {"seller": "Ronin Games", "components": {
              "cards": {"kind": "cards", "quantity": 16, "label": None},
              "tokens": {"kind": "tokens", "quantity": 3, "label": None}}},
          "2026-10-08-shop-a": {"seller": "MTGMate", "components": {
              "cards": {"kind": "cards", "quantity": 12, "label": None},
              "wretched": {"kind": "product", "quantity": None, "label": "Wretched Ranks"}}}}


class HeadlineTests(unittest.TestCase):
    """describe(): a plain sentence from the rows a viewer may see, the kinds, and what it links to."""

    def show(self, rows, scope=ALL, actor="matt", source="web", orders=ORDERS, **kw):
        facts = activity.OrderFacts(lambda: orders)
        return activity.visible_change(_change(rows, actor, source, "words"), scope, BY_ID, orders=facts, **kw)

    def test_a_receipt_names_its_seller_and_what_arrived(self):
        rows = [_component("2026-10-05-shop-c", "pending", "received"),
                *(_card_row("home", f"Card {i}", i) for i in range(3)),
                _row("deck", "UPDATE", {"id": "casual/gruul"}, before=_deck(), after=_deck())]
        shown = self.show(rows)
        self.assertEqual(shown["headline"], "Matt received the Ronin Games order: 16 cards")
        self.assertEqual(shown["kinds"], ["collection", "shopping"])          # the deck's table refresh doesn't count
        self.assertEqual(shown["link"], {"order": "2026-10-05-shop-c"})
        both = rows + [_component("2026-10-05-shop-c", "pending", "received", "tokens", "tokens")]
        self.assertEqual(self.show(both)["headline"],
                         "Matt received the Ronin Games order: 16 cards and 3 token cards")
        # Without the inventory's facts, the order is named by its id and nothing is counted.
        self.assertEqual(self.show(rows, orders={})["headline"], "Matt received the order 2026-10-05-shop-c")

        def unreadable():
            raise ValueError("unreadable")
        shown = activity.visible_change(_change(rows, "matt", "web", "w"), ALL, BY_ID,
                                        orders=activity.OrderFacts(unreadable))
        self.assertEqual(shown["headline"], "Matt received the order 2026-10-05-shop-c")

    def test_orders_recorded_cancelled_and_changed(self):
        added = [_row("purchase_order", "INSERT", {"id": "2026-10-08-shop-a"},
                      after={"id": "2026-10-08-shop-a", "seller": "MTGMate", "ordered_on": "2026-10-08"}),
                 _row("order_component", "INSERT", {"id": "cards"},
                      after={"order_id": "2026-10-08-shop-a", "id": "cards", "kind": "cards", "status": "pending"}),
                 _row("watchlist_item", "DELETE", {"id": 4}, before={"name": "Shock", "quantity": 2, "set_code": "",
                                                                    "collector_number": ""})]
        shown = self.show(added, actor="claude", source="cli")
        self.assertEqual(shown["headline"], "Claude recorded the MTGMate order: 12 cards and Wretched Ranks, "
                                            "and removed Shock from the watchlist")
        self.assertEqual(shown["link"], {"order": "2026-10-08-shop-a"})
        cancelled = self.show([_component("2026-10-08-shop-a", "pending", "cancelled")])
        self.assertEqual(cancelled["headline"], "Matt cancelled 12 cards of the MTGMate order")
        record = {"order_id": "2026-10-08-shop-a", "id": "cards", "status": "pending", "checks": []}
        checks = self.show([_row("order_component", "UPDATE", {"id": "cards"}, before=record,
                                 after=dict(record, checks=["Is it near mint?"]))])
        self.assertEqual(checks["headline"], "Matt changed the MTGMate order")

    def test_collection_tokens_and_watchlist_counts(self):
        self.assertEqual(self.show([_card_row("home", "Llanowar Elves", 227, 2)])["headline"],
                         "Matt added 2 × Llanowar Elves to the collection")
        self.assertEqual(self.show([_card_row("home", "Opt", 60, 3, "UPDATE", 1)])["headline"],
                         "Matt added 2 more copies of Opt to the collection")
        self.assertEqual(self.show([_card_row("user2", "Opt", 60, 1, "DELETE")], scope=USER2S,
                                   actor="user2")["headline"], "User2 removed Opt from your collection")
        many = [_card_row("home", f"Card {i}", i, 2) for i in range(3)] + [_card_row("home", "Gone", 9, 1, "DELETE")]
        self.assertEqual(self.show(many)["headline"], "Matt added 6 and removed 1 card in the collection")
        token = {"space_id": "home", "front": "Zombie", "back": "", "quantity": 2}
        self.assertEqual(self.show([_row("token_card", "INSERT", {"id": 1}, after=token)])["headline"],
                         "Matt added 2 × the token card Zombie")
        self.assertEqual(self.show([_row("token_card", "INSERT", {"id": 1}, after=token)] * 2)["headline"],
                         "Matt added 4 token cards")

    def test_rows_past_the_cap_are_counted_exactly_when_the_store_says(self):
        rows = [_card_row("user2", f"Card {i}", i, 2) for i in range(3)]
        change = dict(_change(rows, "system", "migration", "words"), more=40,
                      past={"collection_card": {"added": 90, "removed": 0, "unknown": 0}})
        shown = activity.visible_change(change, ALL, BY_ID)
        self.assertEqual(shown["headline"], "System added 96 cards to User2's collection")
        self.assertEqual(activity.visible_change(change, USER2S, BY_ID)["headline"],
                         "System added 96 cards to your collection")
        # A row whose quantity can't be read, past the cap: "at least" again.
        change["past"]["collection_card"]["unknown"] = 1
        self.assertEqual(activity.visible_change(change, ALL, BY_ID)["headline"],
                         "System added at least 96 cards to User2's collection")
        # A store that doesn't count them (no "past"): "at least" as before.
        del change["past"]
        self.assertEqual(activity.visible_change(change, ALL, BY_ID)["headline"],
                         "System added at least 6 cards to User2's collection")
        # Rows past the cap of another table don't make this one's count uncertain.
        change["past"] = {"token_card": {"added": 4, "removed": 0, "unknown": 0}}
        self.assertEqual(activity.visible_change(change, ALL, BY_ID)["headline"],
                         "System added 6 cards to User2's collection")

    def test_a_receipt_row_the_headline_says_is_left_out_and_rows_name_orders(self):
        rows = [_component("2026-10-05-shop-c", "pending", "received"),
                *(_card_row("home", f"Card {i}", i) for i in range(3))]
        shown = self.show(rows)
        summaries = [r["summary"] for r in shown["rows"]]
        self.assertEqual(len(summaries), 3)
        self.assertFalse(any("Received" in words for words in summaries), summaries)
        # Two orders received: the headline can't link either, so each row stays, named by its seller.
        two = rows + [_component("2026-10-08-shop-a", "pending", "received")]
        shown = self.show(two)
        self.assertIsNone(shown["link"])
        self.assertIn("Received the Ronin Games order (cards) on 2026-10-12", [r["summary"] for r in shown["rows"]])
        self.assertIn("Received the MTGMate order (cards) on 2026-10-12", [r["summary"] for r in shown["rows"]])
        # Without the inventory's facts, the id.
        self.assertIn("Received order 2026-10-08-shop-a (cards) on 2026-10-12",
                      [r["summary"] for r in self.show(two, orders={})["rows"]])

    def test_an_order_s_rewritten_rows_are_one_row(self):
        key = {"order_id": "2026-10-05-shop-c", "component_id": "cards"}
        change = dict(_change([_component("2026-10-05-shop-c", "pending", "received")], "matt", "receipt", "w"),
                      groups=[{"table": "order_card_item", "op": "DELETE", "key": key, "count": 16},
                              {"table": "order_card_item", "op": "INSERT", "key": key, "count": 15},
                              {"table": "product_item", "op": "INSERT", "key": {"product_stem": "box"}, "count": 3}])
        shown = activity.visible_change(change, ALL, BY_ID, orders=activity.OrderFacts(lambda: ORDERS))
        self.assertEqual([r["summary"] for r in shown["rows"]],
                         ["Replaced the card rows of the Ronin Games order (cards): 16 → 15",
                          "Added 3 card rows to the product box's list"])
        alone = dict(change, groups=change["groups"][:1])
        self.assertEqual([r["summary"] for r in activity.visible_change(alone, ALL, BY_ID)["rows"]],
                         ["Removed 16 card rows from order 2026-10-05-shop-c (cards)"])

    def test_spaces_by_name(self):
        for record, words in (({"id": "user2"}, "Added User2's space"), ({"id": "zed"}, "Added the space zed"),
                              ({"id": "home"}, "Added the home space")):
            shown = activity.visible_change(_change([_row("space", "INSERT", record, after=record)]), ALL, BY_ID)
            self.assertEqual(shown["rows"][0]["summary"], words)

    def test_decks_wishlists_games_settings_and_sleeves(self):
        self.assertEqual(self.show([_row("deck", "UPDATE", {"id": "casual/gruul"}, before=_deck(),
                                         after=_deck(status="built"))])["headline"], "Matt marked Gruul as built")
        saved = self.show([_row("deck", "UPDATE", {"id": "casual/gruul"}, before=_deck(), after=_deck())])
        self.assertEqual((saved["headline"], saved["kinds"], saved["link"]),
                         ("Matt saved Gruul", ["decks"], {"deck": "casual/gruul"}))
        self.assertEqual(self.show([_row("deck", "INSERT", {"id": "casual/gruul"}, after=_deck())])["headline"],
                         "Matt added the deck Gruul")
        wish = _row("wishlist_entry", "INSERT", {"profile_id": "user1", "name": "Island"},
                    after={"profile_id": "user1", "name": "Island", "set_code": "", "collector_number": ""})
        self.assertEqual(self.show([wish], scope=HOME, actor="user1")["headline"],
                         "User1 added Island to your wishlist")
        game = _row("play_record", "INSERT", {"id": "a" * 32}, after={
            "kind": "games", "deck_ids": ["casual/gruul"],
            "content": {"sides": [{"title": "Gruul"}, {"title": "Otters"}], "result": "b"}})
        self.assertEqual(self.show([game])["headline"], "Matt recorded a game: Gruul vs Otters, Otters won")
        setting = _row("profile_setting", "UPDATE", {"profile_id": "user1", "key": "theme"},
                       before={"profile_id": "user1", "key": "theme", "value": "light"},
                       after={"profile_id": "user1", "key": "theme", "value": "dark"})
        self.assertEqual(self.show([setting], actor="user1")["headline"], "User1 set the theme to dark")
        # An arrival notice's parts (E6-S19) read as one notice, never as settings or their JSON.
        def part(op, key, value):
            row = {"profile_id": "user1", "key": key, "value": value}
            return _row("profile_setting", op, {"profile_id": "user1", "key": key},
                        before=row if op == "DELETE" else None, after=None if op == "DELETE" else row)
        first = '{"o":"2026-10-07-shop-a","on":"","d":[["casual/gruul",1]],"x":0,"t":1}'
        kept = [part("INSERT", "arrival_abcdefghij_a", first), part("INSERT", "arrival_abcdefghij_b", '{"d":[]}'),
                part("DELETE", "arrival_klmnopqrst_a", first)]
        self.assertEqual(self.show(kept, actor="user1")["headline"],
                         "User1 kept an arrival notice for order 2026-10-07-shop-a")
        gone = [part("DELETE", "arrival_abcdefghij_a", first), part("DELETE", "arrival_abcdefghij_b", '{"d":[]}'),
                part("DELETE", "arrival_klmnopqrst_a", first)]
        self.assertEqual(self.show(gone, actor="user1")["headline"], "User1 dismissed 2 arrival notices")
        mode = _row("simulation_mode", "UPDATE", {"id": True}, before={"mode": "admins"}, after={"mode": "paused"})
        self.assertEqual(self.show([mode])["headline"], "Matt set simulations to paused")
        kit = [_row("accessory", "INSERT", {"id": f"s{i}"}, after=_accessory("shared")) for i in range(2)]
        self.assertEqual(self.show(kit + [_row("deck", "INSERT", {"id": "casual/gruul"}, after=_deck())],
                                   actor="system", source="migration")["headline"],
                         "System added the deck Gruul and 2 sleeves, boxes and playmats")
        self.assertEqual(self.show([], actor="zed", scope=ALL)["headline"], "Zed made a change")

    def test_a_headline_never_words_a_hidden_row(self):
        rows = [_card_row("user2", "Secret Card", 1),
                _row("wishlist_entry", "INSERT", {"profile_id": "matt", "name": "Hidden Wish"},
                     after={"profile_id": "matt", "name": "Hidden Wish", "set_code": "", "collector_number": ""}),
                _row("accessory", "INSERT", {"id": "m"}, after=_accessory("matt", name="Private Sleeves")),
                _row("deck", "UPDATE", {"id": "casual/gruul"}, before=_deck(), after=_deck(status="built"))]
        shown = self.show(rows, scope=HOME, actor="claude", source="cli")
        self.assertEqual(shown["headline"], "Claude marked Gruul as built")
        self.assertEqual(shown["kinds"], ["decks"])
        for hidden in ("Secret", "Hidden Wish", "Private", "User2"):
            self.assertNotIn(hidden, json.dumps(shown))


class FilterTests(_Store):
    """activity_view's kind and actor filters, applied to what the viewer may see."""

    def test_kind_and_actor_filters(self):
        self.store.settings_put("user1", {"theme": "dark"}, USER1, "Theme")
        self.store.simulation_mode_set("admins", MATT, "Admins")
        self.store.play_put("games", _game("a" * 32, ("casual/gruul", "Gruul"), ("casual/otters", "Otters")), None,
                            MATT, "Save game")
        answer = self.view("matt", kind="games")
        self.assertEqual([c["headline"] for c in answer["changes"]],
                         ["Matt recorded a game: Gruul vs Otters, Gruul won"])
        self.assertEqual([c["kinds"] for c in self.view("matt")["changes"]], [["games"], ["settings"], ["settings"]])
        self.assertEqual([c["actor"] for c in self.view("matt", actor="user1")["changes"]], ["user1"])
        self.assertEqual(self.view("matt", actor="user1", kind="games")["changes"], [])
        for bad in ({"kind": "everything"}, {"kind": ""}, {"actor": "../x"}, {"actor": "Matt"}, {"actor": ""}):
            with self.subTest(bad=bad), self.assertRaises(ApiError) as e:
                self.view("matt", **bad)
            self.assertEqual(e.exception.status, 400)

    def test_an_actor_hidden_from_a_viewer_cannot_be_asked_for(self):
        self.store.settings_put("user1", {"theme": "dark"}, state.Actor("zed", "Zed", "home"), "By an old profile")
        self.assertEqual(len(self.view("matt", actor="zed")["changes"]), 1)          # an admin sees who it was
        self.assertEqual(self.view("user1", actor="zed")["changes"], [])            # User1 sees "someone"
        self.assertEqual(len(self.view("user1")["changes"]), 1)

    def test_cards_for_the_viewer_are_only_of_rows_it_sees(self):
        self.store.wishlist_add("matt", _entry("Llanowar Elves", "fdn", "227"), MATT, "Add")
        fake = {"name": "Llanowar Elves", "img": "/img/fdn/227/normal"}
        with mock.patch("decklab.lib.api.carddata._index_info", return_value=({"ok": 1}, None)), \
                mock.patch("decklab.lib.api.card_lookup._line_json", return_value={"card": fake}) as lookup:
            self.assertEqual(self.view("matt")["cards"], {"Llanowar Elves|fdn|227": fake})
            self.assertEqual(self.view("user1")["cards"], {})
        self.assertEqual(lookup.call_count, 1)
        with mock.patch("decklab.lib.api.carddata._index_info", return_value=(None, "no card data")):
            self.assertEqual(self.view("matt")["cards"], {})


class KitRuleDbTests(db_support.DbTestCase):
    """The state store's SQL twin of rules.kit_changed (its own class: ActivityDbTests' database
    holds one sync's change set)."""

    def test_the_kit_rule_in_sql_is_rules_kit_changed(self):
        from decklab.db import conn as db
        from decklab.lib.state import pg
        cases = [_row("accessory", "INSERT", {"id": "x"}, after=_accessory("matt")),
                 _row("deck", "UPDATE", {"id": "casual/gruul"}, before=_deck(), after=_deck(kit_version=1)),
                 _row("deck", "UPDATE", {"id": "casual/gruul"}, before=_deck(), after=_deck(status="built")),
                 _row("deck", "INSERT", {"id": "casual/gruul"}, after=_deck(kit_version=1)),
                 _row("deck", "DELETE", {"id": "casual/gruul"}, before=_deck()),
                 _row("product_status", "UPDATE", {"file": "a.csv"}, before={"sleeves": ""}, after={"sleeves": "x"}),
                 _row("product_status", "UPDATE", {"file": "a.csv"}, before={"notes": ""}, after={"notes": "x"})]
        with db.connect("app", dbname=self.dbname) as c:
            for row in cases:
                with self.subTest(row["table"], op=row["op"], after=row["after"]):
                    before = json.dumps(row["before"]) if row["before"] else None
                    after = json.dumps(row["after"]) if row["after"] else None
                    found = c.execute(f"select {pg._KIT_CHANGED} from (select %s::text as table_name, "
                                      "%s::text as op, %s::jsonb as before, %s::jsonb as after) t",
                                      (row["table"], row["op"], before, after)).fetchone()[0]
                    self.assertEqual(bool(found), rules.kit_changed(row))


class ActivityDbTests(db_support.DbTestCase):
    # Real audit rows, written by profiles_sync and PgStore, read back through activity_view().

    def setUp(self):
        from decklab.db import conn as db, profiles_sync
        from decklab.lib.state import pg
        db_support.reset(self.dbname)
        folder = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, folder, True)
        for patcher in (mock.patch.object(db, "LOG_FILE", folder / "db.log"),
                        mock.patch.object(settings, "_config_profiles", return_value=[dict(p) for p in PROFILES])):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.store = pg.PgStore(dbname=self.dbname, breaker=pg.Breaker())
        self.addCleanup(state.use(self.store))
        listed = [dict(p, emails=[f"{p['id']}@example.com"]) for p in PROFILES]
        profiles_sync.sync(listed, dbname=self.dbname)

    def test_visibility_with_real_audit_rows(self):
        self.store.wishlist_add("user1", _entry("Plains", "sld", "1513", notes="private"), USER1,
                                "Add Plains to User1's wishlist")
        self.store.wishlist_add("user2", _entry("Llanowar Elves"), USER2, "Add Llanowar Elves to User2's wishlist")
        self.store.settings_put("matt", {"theme": "dark"}, MATT, "Change Matt's settings: theme")
        with access.viewing("matt"):
            admin = activity.activity_view()
        self.assertEqual([c["message"] for c in admin["changes"]][:1], ["Change Matt's settings: theme"])
        synced = admin["changes"][1]                        # no wishlist: they're their owners' only
        self.assertEqual((synced["actor_name"], synced["source"]), ("System", "sync"))
        emails = [r for r in synced["rows"] if r["table"] == "profile_email"]
        self.assertEqual(len(emails), 3)
        self.assertTrue(all(r == {"table": "profile_email", "op": "INSERT", "summary": "An email address changed"}
                            for r in emails))
        self.assertNotIn("example.com", json.dumps(admin))
        self.assertNotIn("private", json.dumps(admin))
        self.assertNotIn("wishlist", json.dumps(admin))
        with access.viewing("user1"):
            user1 = activity.activity_view()
        self.assertEqual([c["message"] for c in user1["changes"]],
                         ["Change Matt's settings: theme", "Add Plains to User1's wishlist"])
        self.assertEqual(user1["changes"][1]["rows"][0]["after"],
                         {"name": "Plains", "set_code": "sld", "collector_number": "1513"})
        self.assertEqual(user1["changes"][1]["via"], "home")
        with access.using({"profile": "user2", "email": "user2@example.com", "remote": True}):
            user2 = activity.activity_view()
        self.assertEqual([(c["message"], c["via"]) for c in user2["changes"]],
                         [("Add Llanowar Elves to User2's wishlist", "tunnel")])


if __name__ == "__main__":
    unittest.main()
