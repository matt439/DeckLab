"""Commander-note API identity, uncertainty and optimistic edits in isolated fixtures."""
import copy
import json
from datetime import date, timedelta
from unittest import mock

from decklab.lib import access, state
from decklab.lib.api import commander_night
from decklab.tests.test_api_permissions import PermissionTestCase
from decklab.tests.test_commander_night_state import NIGHT


class CommanderNightApiTests(PermissionTestCase):
    def save(self, *, profile="matt", expect=0, night=NIGHT, **other):
        return commander_night.change(self.body(profile, expect=expect, night=night, **other))

    def test_home_admin_saves_one_change_home_member_reads_and_unknowns_stay_unknown(self):
        with access.viewing("matt"):
            self.assertEqual(commander_night.view(), {"night": None, "revision": 0, "can_edit": True})
            saved = self.save(night={"name": "Fixture night"})
        self.assertEqual(saved["night"], {"name": "Fixture night", "venue": "", "target_bracket": None,
                                         "published_min": None, "published_max": None,
                                         "house_rules": "", "checked_on": ""})
        for remote in (False, True):
            identity = {"profile": "user1", "email": "", "remote": True} if remote else None
            with access.using(identity), access.viewing("user1"):
                shown = commander_night.view()
                self.assertEqual(shown, {**saved, "can_edit": False})
                self.assertEqual(commander_night.projection(), shown)
                self.assertApiError(403, lambda: self.save(profile="user1", expect=1))
        change, = self.box.state.changes()
        self.assertEqual(change["actor"], "matt")
        self.assertEqual(change["message"], "Save the household's Commander-night notes")
        self.assertNotIn("Fixture night", change["message"])

    def test_read_and_write_permissions_precede_storage_even_when_it_is_down(self):
        self.box.state.down = True
        for remote in (False, True):
            identity = {"profile": "user2", "email": "", "remote": True} if remote else None
            with access.using(identity), access.viewing("user2"), \
                    mock.patch.object(self.box.state, "commander_night", side_effect=AssertionError("private read")), \
                    mock.patch.object(self.box.state, "commander_night_put", side_effect=AssertionError("private write")):
                self.assertApiError(403, commander_night.view)
                self.assertIsNone(commander_night.projection())
                self.assertApiError(403, lambda: self.save(profile="user2"))

    def test_home_chooser_and_tunnel_writer_cannot_impersonate_matt(self):
        for remote in (False, True):
            identity = {"profile": "user1", "email": "", "remote": True} if remote else None
            with access.using(identity), access.viewing("user1"):
                self.assertApiError(403, lambda: self.save(profile="matt"))
        self.assertEqual(self.box.state.changes(), [])

    def test_clear_is_intentional_audited_and_keeps_conflict_protection(self):
        self.save()
        self.assertApiError(400, lambda: self.save(expect=1, night=None))
        cleared = self.save(expect=1, night=None, reason="Fixture night no longer used")
        self.assertEqual(cleared, {"night": None, "revision": 2, "can_edit": True})
        self.assertIsNone(commander_night.projection())
        self.assertApiError(409, lambda: self.save(expect=1))
        recreated = self.save(expect=2)
        self.assertEqual(recreated["revision"], 3)
        self.assertApiError(409, lambda: self.save(expect=1))
        self.assertEqual(self.box.state.changes()[1]["reason"], "Fixture night no longer used")

    def test_future_and_malformed_dates_are_refused_without_changing_saved_observations(self):
        self.save()
        before = copy.deepcopy(self.box.state.commander_night())
        for checked in ((date.today() + timedelta(days=1)).isoformat(), "2026-02-29", "20261013"):
            with self.subTest(checked=checked):
                self.assertApiError(400, lambda: self.save(expect=1, night={**NIGHT, "checked_on": checked}))
        self.assertEqual(self.box.state.commander_night(), before)
        self.assertEqual(len(self.box.state.changes()), 1)

    def test_invalid_bodies_and_oversize_never_write(self):
        for body in (b"[]", b"null", b'{"profile":"matt","expect":0}',
                     self.body("matt", expect=True, night=NIGHT),
                     self.body("matt", expect=0, night=NIGHT, unknown=1),
                     self.body("matt", expect=0, night={**NIGHT, "target_bracket": "2"}),
                     b'{"profile":"matt","expect":0,"expect":1,"night":null}'):
            with self.subTest(body=body[:90]):
                self.assertApiError(400, commander_night.change, body)
        self.assertApiError(413, commander_night.change, b" " * (commander_night.MAX_BODY + 1))
        self.assertEqual(self.box.state.changes(), [])

    def test_optional_projection_distinguishes_unavailable_from_absent_and_does_not_write(self):
        self.assertIsNone(commander_night.projection())
        self.save()
        self.box.state.down = True
        self.assertEqual(commander_night.projection(), {"unavailable": True})
        self.assertApiError(503, commander_night.view)
        self.assertApiError(503, lambda: self.save(expect=1, night={**NIGHT, "venue": "Other fixture"}))
        self.box.state.down = False
        self.assertEqual(self.box.state.commander_night(), {"night": NIGHT, "revision": 1})
        self.assertEqual(len(self.box.state.changes()), 1)

    def test_a_matching_save_is_quiet_and_cannot_rewrite_unrelated_state(self):
        self.box.state.settings_put("user1", {"theme": "dark"}, state.Actor("user1", "User1"), "Fixture preference")
        saved = self.save()
        before = self.box.state.changes()
        self.assertEqual(self.save(expect=1), saved)
        self.assertEqual(self.box.state.changes(), before)
        self.assertEqual(self.box.state.settings("user1"), {"theme": "dark"})

    def test_complete_unicode_notes_fit_the_request_body_limit(self):
        night = {**NIGHT, "name": "🌙" * 120, "venue": "🏠" * 120, "house_rules": "🃏" * 1500}
        body = json.dumps({"profile": "matt", "expect": 0, "night": night}, ensure_ascii=False).encode("utf-8")
        self.assertGreater(len(body), 4096)
        self.assertLess(len(body), commander_night.MAX_BODY)
        self.assertEqual(commander_night.change(body)["night"], night)
