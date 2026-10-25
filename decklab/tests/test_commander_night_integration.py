"""Commander-night notes stay private across deck pages, audit rows and HTTP."""
import copy
import json
import unittest
from unittest import mock

from decklab.lib import api, permissions, state
from decklab.lib.api import activity, commander_night, deck_page, guard
from decklab.tests import test_activity as activity_fixture
from decklab.tests import test_permissions as people
from decklab.tests.test_api import ApiTestCase
from decklab.tests.test_server import ServerTestCase, WRITE


NIGHT = {"name": "Fixture night", "venue": "Fictional venue", "target_bracket": 2,
         "published_min": 1, "published_max": 4, "house_rules": "Fixture-only private note.", "checked_on": ""}
ACTOR = state.Actor("matt", "Matt", "home")


class NightPermissionTests(unittest.TestCase):
    def test_home_readers_and_home_admin_writers_follow_the_same_rule_on_both_listeners(self):
        outsider_admin = dict(people.USER2, role="admin")
        for profile, read, write in ((people.MATT, True, True), (people.USER1, True, False),
                                     (people.USER2, False, False), (outsider_admin, False, False)):
            for local in (False, True):
                with self.subTest(profile=profile, local=local):
                    self.assertEqual(permissions.sees_commander_night(profile, script=local), read)
                    self.assertEqual(permissions.can(profile, "commander_night.edit", script=local), write)
        self.assertTrue(permissions.sees_commander_night(None, script=True))
        self.assertTrue(permissions.can(None, "commander_night.edit", script=True))
        self.assertFalse(permissions.sees_commander_night(None))
        self.assertFalse(permissions.can(None, "commander_night.edit"))


class NightDeckProjectionTests(ApiTestCase):
    def save_night(self):
        return self.box.state.commander_night_put(copy.deepcopy(NIGHT), 0, ACTOR, "Fixture night")

    def test_empty_is_quiet_and_recorded_notes_leave_the_rest_of_the_deck_unchanged(self):
        before = api.deck_view("commander/elf-commander", omit={"matchups"})
        self.assertNotIn("commander_night", before)
        self.save_night()
        after = api.deck_view("commander/elf-commander", omit={"matchups"})
        self.assertEqual(after.pop("commander_night"), {"night": NIGHT, "revision": 1, "can_edit": True})
        self.assertEqual(after, before)

    def test_notes_are_independent_of_inventory_visibility_and_never_added_to_casual_decks(self):
        self.save_night()
        with mock.patch.object(guard, "viewer", return_value=people.USER1), \
                mock.patch.object(guard, "sees_inventory", return_value=False):
            shown = api.deck_view("commander/elf-commander", omit={"matchups"})
        self.assertNotIn("owned", shown)
        self.assertEqual(shown["commander_night"]["night"], NIGHT)
        self.assertFalse(shown["commander_night"]["can_edit"])
        with mock.patch.object(commander_night, "projection") as lookup:
            casual = api.deck_view("casual/gruul-test", omit={"matchups"})
        lookup.assert_not_called()
        self.assertNotIn("commander_night", casual)

    def test_home_decks_do_not_relay_notes_to_a_member_even_an_admin(self):
        self.save_night()
        for profile in (people.USER2, dict(people.USER2, role="admin")):
            with self.subTest(profile=profile), mock.patch.object(guard, "viewer", return_value=profile), \
                    mock.patch.object(self.box.state, "commander_night", side_effect=AssertionError("Private read")):
                # The deck itself is home's alone (E10-S30)...
                with self.assertRaises(api.ApiError) as hidden:
                    api.deck_view("commander/elf-commander", omit={"matchups"})
                self.assertEqual(hidden.exception.status, 404)
                # ...and made public (as E10-S28's switches will), its notes still stay home's.
                with mock.patch.object(guard, "public_deck_spaces", return_value=frozenset({"home"})):
                    answer = api.deck_view("commander/elf-commander", omit={"matchups"})
            self.assertNotIn("commander_night", answer)

    def test_another_spaces_commander_deck_does_not_get_home_notes(self):
        original = deck_page._deck_sections

        def elsewhere(*args):
            summary, sections = original(*args)
            return {**summary, "id": "user2/commander/fixture", "space": "user2"}, sections

        with mock.patch.object(deck_page, "_deck_sections", side_effect=elsewhere), \
                mock.patch.object(guard, "sees_inventory", return_value=False), \
                mock.patch.object(commander_night, "projection") as lookup:
            answer = api.deck_view("commander/elf-commander", omit={"matchups"})
        lookup.assert_not_called()
        self.assertNotIn("commander_night", answer)

    def test_unavailable_optional_notes_do_not_turn_a_deck_read_into_an_empty_claim(self):
        with mock.patch.object(self.box.state, "commander_night", side_effect=state.Unavailable("private database detail")):
            shown = api.deck_view("commander/elf-commander", omit={"matchups"})
        self.assertEqual(shown["commander_night"], {"unavailable": True})
        self.assertNotIn("private database detail", json.dumps(shown))


class NightActivityTests(unittest.TestCase):
    def setUp(self):
        self.profiles = {**activity_fixture.BY_ID, "outside_admin": dict(people.USER2, id="outside_admin", role="admin")}
        self.note = {"table": "commander_night", "op": "UPDATE", "key": {"id": True},
                     "before": None, "after": {"id": True, "revision": 1, "content": NIGHT}}

    def change(self, rows, **values):
        return {"id": 1, "at": "2026-10-16T00:00:00Z", "actor": "matt", "source": "web", "via": "home",
                "message": "Private fixture venue", "reason": "Private fixture reason", "rows": rows, **values}

    def test_only_home_sees_note_changes_and_rows_contain_only_a_generic_summary(self):
        change = self.change([self.note])
        for scope, me in (("all", "matt"), ("all", None), (activity_fixture.HOME, "user1")):
            with self.subTest(scope=scope, me=me):
                shown = activity.visible_change(change, scope, self.profiles, me=me)
                self.assertEqual(shown["headline"], "Matt updated Commander-night notes")
                self.assertEqual(shown["kinds"], ["settings"])
                self.assertEqual(shown["rows"], [{"table": "commander_night", "op": "UPDATE",
                                                   "summary": "Commander-night notes updated"}])
                self.assertNotIn("house_rules", json.dumps(shown))
        for scope, me in ((activity_fixture.USER2S, "user2"), ("all", "outside_admin"), ("all", "removed_profile")):
            with self.subTest(scope=scope, me=me):
                self.assertIsNone(activity.visible_change(change, scope, self.profiles, me=me))

    def test_hidden_note_words_stay_hidden_in_mixed_changes_even_with_kit_actor_override(self):
        public = {"table": "simulation_mode", "op": "UPDATE", "before": {"mode": "admins"},
                  "after": {"mode": "everyone", "set_by_name": "Outside admin"}}
        for kit in (False, True):
            change = self.change([self.note, public], actor="outside_admin", kit=kit)
            shown = activity.visible_change(change, "all", self.profiles, me="outside_admin")
            self.assertIsNotNone(shown)
            self.assertIsNone(shown["message"])
            self.assertIsNone(shown["reason"])
            self.assertNotIn("Private", json.dumps(shown))
            self.assertNotIn("commander_night", json.dumps(shown))

    def test_cleared_tombstone_gets_a_clear_summary_without_content_or_revision(self):
        self.note["after"] = {"id": True, "revision": 2, "content": None}
        shown = activity.visible_change(self.change([self.note]), "all", self.profiles, me="matt")
        self.assertEqual(shown["headline"], "Matt cleared Commander-night notes")
        self.assertNotIn("revision", json.dumps(shown))


class NightRouteTests(ServerTestCase):
    def test_get_head_and_put_dispatch_with_the_existing_write_guards(self):
        with mock.patch.object(api, "commander_night_view", return_value={"night": None, "revision": 0}) as read:
            self.assertEqual(self.get_json("/api/commander-night"), {"night": None, "revision": 0})
            code, headers, body = self.request("HEAD", "/api/commander-night")
            self.assertEqual((code, body), (200, b""))
            self.assertEqual(read.call_count, 2)
            self.assertError("/api/commander-night?unexpected=yes", 400)
        payload = json.dumps({"profile": "matt", "expect": 0, "night": NIGHT}).encode()
        with mock.patch.object(api, "change_commander_night", return_value={"revision": 1}) as write:
            self.assertEqual(self.get_json("/api/commander-night", method="PUT", body=payload, headers=WRITE), {"revision": 1})
            write.assert_called_once_with(payload)
            write.reset_mock()
            self.assertError("/api/commander-night", 403, method="PUT", body=payload,
                             headers={"Content-Type": "application/json"})
            self.assertError("/api/commander-night", 403, method="PUT", body=payload,
                             headers=dict(WRITE, Origin="http://untrusted.example"))
            self.assertError("/api/commander-night?unexpected=yes", 400, method="PUT", body=payload, headers=WRITE)
            self.assertError("/api/commander-night", 405, method="POST", body=payload, headers=WRITE)
            write.assert_not_called()

    def test_http_accepts_full_unicode_notes_within_the_dedicated_body_limit(self):
        night = {**NIGHT, "name": "夜" * 120, "venue": "界" * 120, "house_rules": "😀" * 1500}
        payload = json.dumps({"profile": "matt", "expect": 0, "night": night}, ensure_ascii=False).encode()
        self.assertGreater(len(payload), api.MAX_BODY)
        self.assertLess(len(payload), api.MAX_COMMANDER_NIGHT_BODY)
        with mock.patch.object(api, "change_commander_night", return_value={"revision": 1}) as write:
            self.get_json("/api/commander-night", method="PUT", body=payload, headers=WRITE)
        write.assert_called_once_with(payload)
