"""The private member-email panel refuses hidden readers before storage or payloads."""
import copy
import json
import unittest
from unittest import mock

from decklab.db import conn as db, profile_edits
from decklab.lib import access, permissions
from decklab.lib.api import guard, members
from decklab.lib.api.common import ApiError
from decklab.tests import test_permissions as people
from decklab.tests.test_server import ServerTestCase, WRITE

SNAPSHOT = {"editable": True, "config_sha256": "a" * 64, "membership_sha256": "b" * 64,
            "members": [{"id": "user2", "name": "User2", "emails": ["user2@example.com", "alias@example.com"]}]}
REQUEST = {"profile": "matt", "member_id": "user2", "old_email": "user2@example.com",
           "new_email": "replacement@example.com", "config_sha256": "a" * 64, "membership_sha256": "b" * 64}
SAVED = {"saved": True, "noop": False, "member": {"id": "user2", "name": "User2",
         "emails": ["replacement@example.com", "alias@example.com"]},
         "replaced": {"old_email": "user2@example.com", "new_email": "replacement@example.com"},
         "config_sha256": "c" * 64, "membership_sha256": "d" * 64,
         "change_set_id": 42, "access_policy_required": True}
CREATE = {"profile": "matt", "member_id": "user3", "name": "User3", "email": "user3@example.com",
          "config_sha256": "a" * 64, "membership_sha256": "b" * 64}
CREATED = {key: value for key, value in SAVED.items() if key != "replaced"}
CREATED["member"] = {"id": "user3", "name": "User3", "emails": ["user3@example.com"]}


class MembersApiTests(unittest.TestCase):
    def setUp(self):
        self.viewer = mock.patch.object(guard, "viewer", return_value=people.MATT).start()
        self.preview = mock.patch.object(profile_edits, "preview", return_value=copy.deepcopy(SNAPSHOT)).start()
        self.apply = mock.patch.object(profile_edits, "apply", return_value=copy.deepcopy(SAVED)).start()
        self.create = mock.patch.object(profile_edits, "create", return_value=copy.deepcopy(CREATED)).start()
        self.addCleanup(mock.patch.stopall)

    def refused(self, status, call, *args, **kwargs):
        with self.assertRaises(ApiError) as caught:
            call(*args, **kwargs)
        self.assertEqual(caught.exception.status, status)
        return caught.exception.message

    def send(self, **changes):
        return members.change(json.dumps({**REQUEST, **changes}).encode())

    def test_explicit_home_admin_is_required_even_for_an_unnamed_script(self):
        for viewer in (None, people.USER1, people.USER2, {**people.USER2, "role": "admin"}):
            for script in (False, True):
                with self.subTest(viewer=viewer, script=script), mock.patch.object(guard, "script", return_value=script):
                    self.viewer.return_value = viewer
                    first = self.refused(403, members.view)
                    self.assertEqual(self.refused(403, members.change, b"private malformed payload"), first)
                    self.assertEqual(self.refused(403, members.create, b"private malformed payload"), first)
        self.preview.assert_not_called()
        self.apply.assert_not_called()
        self.create.assert_not_called()

    def test_permission_has_no_script_bypass_and_needs_a_named_home_admin(self):
        for script in (False, True):
            self.assertTrue(permissions.can(people.MATT, "members.edit", script=script))
            for who in (None, people.USER1, people.USER2, {**people.USER2, "role": "admin"},
                        {**people.MATT, "id": ""}):
                self.assertFalse(permissions.can(who, "members.edit", script=script))

    def test_private_preview_and_confirmed_receipt_are_returned_only_to_admin(self):
        self.assertEqual(members.view(), SNAPSHOT)
        self.assertEqual(self.preview.call_args.kwargs["actor"].id, "matt")
        self.assertEqual(self.preview.call_args.kwargs["actor"].source, "web")
        with access.using(None):
            self.assertEqual(self.send(), SAVED)
        args, kwargs = self.apply.call_args
        self.assertEqual(args, ("user2", "user2@example.com", "replacement@example.com"))
        self.assertEqual(kwargs["actor"].id, "matt")
        self.assertEqual(kwargs["actor"].source, "web")
        self.assertEqual(kwargs["config_sha256"], "a" * 64)
        self.assertEqual(kwargs["membership_sha256"], "b" * 64)

    def test_actor_spoofing_is_refused_before_backend(self):
        self.refused(403, self.send, profile="user1")
        self.apply.assert_not_called()

    def test_unknown_or_missing_fields_never_reach_backend(self):
        for value in (None, [], {}, {**REQUEST, "role": "admin"}, {k: v for k, v in REQUEST.items() if k != "old_email"}):
            self.refused(400, members.change, json.dumps(value).encode())
        self.apply.assert_not_called()

    def test_malformed_repeated_keys_and_large_payloads_are_refused(self):
        for value in (b"not json", b'{"profile":"matt","profile":"user1"}', b"\xff"):
            self.refused(400, members.change, value)
        self.refused(413, members.change, b" " * (members.MAX_BODY + 1))
        self.apply.assert_not_called()

    def test_stale_preview_or_save_requires_reload_without_exposing_receipts(self):
        self.preview.side_effect = profile_edits.StaleProfileEdit("private detail")
        self.assertNotIn("private detail", self.refused(409, members.view))
        self.apply.side_effect = profile_edits.StaleProfileEdit("private detail")
        self.assertIn("Reload", self.refused(409, self.send))

    def test_pending_recovery_does_not_claim_a_failed_save(self):
        self.apply.side_effect = profile_edits.PendingProfileEdit("private operation")
        text = self.refused(503, self.send)
        self.assertIn("local recovery", text)
        self.assertNotIn("private operation", text)
        self.assertNotIn("nothing", text)

    def test_validation_and_database_outage_have_distinct_statuses(self):
        self.apply.side_effect = profile_edits.InvalidProfileEdit("Choose a valid email address.")
        self.assertEqual(self.refused(400, self.send), "Choose a valid email address.")
        self.apply.side_effect = db.DbUnavailable("private database address")
        self.assertNotIn("private database address", self.refused(503, self.send))

    def test_file_failure_hides_absolute_paths_and_requires_reload(self):
        self.apply.side_effect = PermissionError("C:\\private\\config.json")
        text = self.refused(503, self.send)
        self.assertNotIn("private", text)
        self.assertIn("Reload", text)

    def test_noop_is_not_relabelled_as_a_new_audited_change(self):
        receipt = {**SAVED, "saved": False, "noop": True, "change_set_id": None}
        self.apply.return_value = receipt
        self.assertEqual(self.send(), receipt)
        self.apply.assert_called_once()

    def test_creation_forwards_only_reviewed_identity_and_the_current_web_actor(self):
        self.assertEqual(members.create(json.dumps(CREATE).encode()), CREATED)
        args, kwargs = self.create.call_args
        self.assertEqual(args, ("user3", "User3", "user3@example.com"))
        self.assertEqual(kwargs["actor"].id, "matt")
        self.assertEqual(kwargs["actor"].source, "web")
        self.assertEqual(kwargs["config_sha256"], CREATE["config_sha256"])
        self.apply.assert_not_called()

    def test_creation_cannot_change_role_space_or_impersonate_an_actor(self):
        for extra in ({"role": "admin"}, {"space": "home"}, {"plays_as": "user"}, {"public": True}):
            self.refused(400, members.create, json.dumps({**CREATE, **extra}).encode())
        self.refused(403, members.create, json.dumps({**CREATE, "profile": "user1"}).encode())
        self.create.assert_not_called()

    def test_creation_has_no_implicit_email_edit_or_payload_fallback(self):
        for value in (REQUEST, None, [], {k: v for k, v in CREATE.items() if k != "member_id"}):
            self.refused(400, members.create, json.dumps(value).encode())
        self.refused(413, members.create, b" " * (members.MAX_BODY + 1))
        self.create.assert_not_called()


class MembersHttpTests(ServerTestCase):
    def test_member_creation_uses_only_the_guarded_post_endpoint(self):
        with mock.patch.object(members, "create", return_value=CREATED) as save:
            status, _, body = self.request("POST", "/api/settings/member", json.dumps(CREATE).encode(), WRITE)
            self.assertEqual(status, 200)
            self.assertEqual(json.loads(body), CREATED)
            self.assertEqual(json.loads(save.call_args.args[0]), CREATE)
            self.assertEqual(self.request("GET", "/api/settings/member")[0], 405)
            self.assertEqual(self.request("POST", "/api/settings/member?public=1", b"{}", WRITE)[0], 400)
            self.assertEqual(self.request("POST", "/api/settings/member", json.dumps(CREATE).encode(), {})[0], 403)
            save.assert_called_once()

    def test_pending_profile_publication_does_not_return_local_me_rights(self):
        with mock.patch.object(access, "me", side_effect=profile_edits.PendingProfileEdit("private recovery detail")):
            status, _, body = self.request("GET", "/api/me", script=False)
            self.assertEqual(status, 503)
            reply = json.loads(body)
            self.assertEqual(set(reply), {"error"})
            self.assertIn("local recovery", reply["error"])
            self.assertNotIn("private recovery detail", body.decode())

    def test_get_and_head_route_to_the_private_panel_with_no_query(self):
        with mock.patch.object(members, "view", return_value=SNAPSHOT) as lookup:
            for method in ("GET", "HEAD"):
                status, _, body = self.request(method, "/api/settings/members")
                self.assertEqual(status, 200)
                if method == "HEAD":
                    self.assertEqual(body, b"")
                else:
                    self.assertEqual(json.loads(body), SNAPSHOT)
            self.assertEqual(lookup.call_count, 2)
            self.assertEqual(self.request("GET", "/api/settings/members?email=hidden@example.com")[0], 400)
            self.assertEqual(self.request("POST", "/api/settings/members", b"{}", WRITE)[0], 405)
            self.assertEqual(lookup.call_count, 2)

    def test_post_uses_normal_write_guards_and_only_the_email_endpoint(self):
        with mock.patch.object(members, "change", return_value=SAVED) as save:
            status, _, body = self.request("POST", "/api/settings/member-email", json.dumps(REQUEST).encode(), WRITE)
            self.assertEqual(status, 200)
            self.assertEqual(json.loads(body), SAVED)
            self.assertEqual(json.loads(save.call_args.args[0]), REQUEST)
            self.assertEqual(self.request("GET", "/api/settings/member-email")[0], 405)
            self.assertEqual(self.request("POST", "/api/settings/member-email", json.dumps(REQUEST).encode(), {})[0], 403)
            self.assertEqual(save.call_count, 1)


if __name__ == "__main__":
    unittest.main()
