"""Owner-only controls, readiness and one fail-closed snapshot per request."""
from unittest import mock

from decklab.lib import access, permissions, server_http, state, visibility
from decklab.lib.api import guard, visibility as api
from decklab.lib.state import visibility as values
from decklab.tests.test_api_permissions import PermissionTestCase


class VisibilityApiTests(PermissionTestCase):
    def setUp(self):
        super().setUp()
        self._ready = mock.patch.object(visibility, "READY_THINGS", frozenset(values.THINGS))
        self._ready.start()
        self.addCleanup(self._ready.stop)

    def change(self, profile="matt", owner="home", thing="decks", public=True):
        return api.change(self.body(profile, owner=owner, thing=thing, public=public))

    def test_controls_are_owned_and_an_admin_cannot_see_or_flip_a_members_switches(self):
        for profile, expected in (("matt", {"home", "matt", "shared"}),
                                  ("user1", {"home", "user1", "shared"}), ("user2", {"user2"})):
            with self.subTest(profile=profile), access.viewing(profile):
                rows = api.view()["switches"]
                self.assertEqual({row["owner"] for row in rows}, expected)
                self.assertFalse(any(row["public"] for row in rows))
        self.box.state.down = True
        with access.viewing("matt"):
            for owner in ("user2", "no-such-space", "user1"):
                with self.subTest(owner=owner):
                    error = self.assertApiError(403, lambda: self.change(owner=owner))
                    self.assertEqual(error.message, api.OWNER_ONLY)

    def test_readiness_hides_controls_and_is_enforced_before_storage(self):
        with mock.patch.object(visibility, "READY_THINGS", frozenset({"collection"})), access.viewing("matt"):
            self.assertEqual(api.view()["switches"], [{"owner": "home", "thing": "collection", "public": False}])
            self.assertApiError(409, lambda: self.change(thing="decks"))
            self.assertEqual(self.box.state.changes(), [])
            self.change(thing="collection")
        self.assertEqual(set(self.box.state.visibility()), {("home", "collection")})

    def test_home_and_tunnel_flips_are_one_audited_change_with_fixed_words(self):
        with access.viewing("matt"):
            self.change()
        with access.using({"profile": "user1", "email": "", "remote": True}):
            self.change("user1", public=False)
            self.change("user1", "user1", "accessories", True)
        changes = self.box.state.changes()
        self.assertEqual([(c["actor"], c["source"], c["via"], c["message"]) for c in changes],
                         [("matt", "web", "home", "Make the home decks public"),
                          ("user1", "web", "tunnel", "Make the home decks private"),
                          ("user1", "web", "tunnel", "Make User1's sleeves, deck boxes and playmats public")])
        self.assertEqual([c["rows"][0]["op"] for c in changes], ["INSERT", "DELETE", "INSERT"])

    def test_identity_cannot_be_borrowed_and_malformed_requests_write_nothing(self):
        with access.viewing("user1"):
            self.assertApiError(403, self.change)
        with access.using({"profile": "user2", "email": "", "remote": True}):
            self.assertApiError(403, self.change)
        with access.viewing("matt"):
            for body in (b"[]", b"null", b"{}", self.body("matt", owner="home", thing="decks", public="on"),
                         self.body("matt", owner="home", thing="decks", public=1),
                         self.body("matt", owner="home", thing="decks", public=True, extra=True)):
                with self.subTest(body=body):
                    self.assertApiError(400, api.change, body)
            self.assertApiError(413, api.change, b" " * (4096 + 1))
        self.assertEqual(self.box.state.changes(), [])

    def test_everything_starts_private_and_me_refreshes_for_the_home_viewer(self):
        with access.answering(False), access.viewing("user1"):
            before = access.me(None)
            self.assertEqual(before["profile"], "user1")
            self.assertEqual(len(before["may"]["visibility"]), 5)
            self.assertFalse(any(r["public"] for r in before["may"]["visibility"]))
            self.change("user1", thing="games")
            after = access.me(None)
            self.assertEqual([r for r in after["may"]["visibility"] if r["public"]],
                             [{"owner": "home", "thing": "games", "public": True}])

    def test_one_request_keeps_one_snapshot_and_a_committed_flip_replaces_it(self):
        with access.viewing("matt"), visibility.pinned(), mock.patch.object(
                self.box.state, "visibility", wraps=self.box.state.visibility) as read:
            self.assertEqual(guard.public_deck_spaces(), frozenset())
            self.assertEqual(guard.public_spaces("games"), frozenset())
            self.assertEqual(read.call_count, 1)
            self.change()
            self.assertEqual(guard.public_deck_spaces(), {"home"})
            self.assertEqual(read.call_count, 1)
            saved = guard.visibility()
            saved.clear()
            self.assertEqual(guard.public_deck_spaces(), {"home"})
        self.assertEqual(guard.public_deck_spaces(), {"home"})

    def test_different_requests_observe_new_values_and_outage_defaults_private(self):
        with visibility.pinned():
            self.assertEqual(guard.public_deck_spaces(), frozenset())
            self.change()
        with visibility.pinned():
            self.assertEqual(guard.public_deck_spaces(), {"home"})
        self.box.state.down = True
        self.box.state._clock = lambda: float("inf")
        with visibility.pinned():
            self.assertEqual(guard.public_deck_spaces(), frozenset())
        self.assertApiError(503, self.change)

    def test_unpicked_home_reader_sees_only_public_and_gets_no_owner_controls(self):
        self.change()
        with access.answering(False), access.viewing(None):
            self.assertTrue(guard.sees_deck("casual/one"))
            self.assertFalse(guard.sees_deck("user2/casual/one"))
            self.assertEqual(api.view(), {"switches": []})

    def test_public_does_not_widen_write_rights_and_orphan_switches_never_grant_access(self):
        self.change()
        self.box.state.visibility_set("removed-space", "decks", True, state.Actor("test", "Test"), "Fixture")
        with access.viewing("user2"):
            self.assertTrue(guard.sees_deck("casual/one"))
            self.assertFalse(guard.allowed(guard.viewer(), "deck.edit", {"space": "home", "player": "user"}))
            self.assertNotIn("removed-space", guard.public_deck_spaces())
            self.assertEqual({r["owner"] for r in api.view()["switches"]}, {"user2"})

    def test_http_get_head_and_put_dispatch_without_a_live_server(self):
        handler = object.__new__(server_http.Handler)
        handler.path = "/api/visibility"
        handler.identity = None
        handler._send_json = mock.Mock()
        handler._write_body = mock.Mock(return_value=self.body("matt", owner="home", thing="decks", public=True))
        with access.viewing("matt"):
            for method in ("GET", "HEAD"):
                handler.command = method
                handler._route()
                self.assertEqual(handler._send_json.call_args.args[0], 200)
                self.assertFalse(any(row["public"] for row in handler._send_json.call_args.args[1]["switches"]))
            handler.command = "PUT"
            handler._route()
            handler._write_body.assert_called_once_with(4096)
            self.assertTrue(any(row["public"] for row in handler._send_json.call_args.args[1]["switches"]))
            handler.command = "POST"
            self.assertApiError(405, handler._route)
            handler.command = "GET"
            handler.path += "?owner=user2"
            self.assertApiError(400, handler._route)


if __name__ == "__main__":
    import unittest
    unittest.main()
