"""E10-S35: only scripts read everything, and the home chooser offers home profiles only.

A script is code outside any request (a job thread, a test) or a request on the home listener
from loopback with X-Deck-Lab-Script: 1 and no viewer (access.script(), guard.script()). Any
other request naming nobody sees only what's open to everyone. A home-listener request naming a
profile outside the home gets 403 "Sign in through decklab.example.com" on every route.

Real servers on 127.0.0.1 (the home listener and the tunnel's, as test_server_access runs them)
over test_api's Sandbox, with a config of Matt, User1 and User2; nothing touches the network,
the real decklab/data/ or the live database.
"""
import email.message
import http.client
import json
import re
import threading
import types
import unittest
from unittest import mock

from decklab import server  # noqa: F401 (runs build.start() before the server modules load)
from decklab.lib import access, config, dbstatus, server_http
from decklab.lib.api import commits, guard, history, simulations, visits
from decklab.lib.api.common import ApiError
from decklab.tests.test_access import AUD, TEAM, Fetcher, claims, token
from decklab.tests.test_activity import _Store
from decklab.tests.test_api import Sandbox
from decklab.tests.test_server_access import HOSTS, PROFILES, SCRIPT, WRITE

HOME_ONLY = {"error": access.SIGN_IN_OUTSIDE}
ROLES = [{**p, "role": p.get("role") or ("admin" if p["id"] == "matt" else "member"), "space": p.get("space", "home")}
         for p in PROFILES]


class HomeListenerTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.box = Sandbox().start()
        (cls.box.root / "config.json").write_text(json.dumps({"profiles": ROLES}), encoding="utf-8")
        (cls.box.web / "index.html").parent.mkdir(parents=True, exist_ok=True)
        (cls.box.web / "index.html").write_text("<!doctype html><title>Deck Lab</title>", encoding="utf-8")
        cls.log_patch = mock.patch.object(server_http, "log", lambda text: None)
        cls.log_patch.start()
        verifier = access.Verifier(TEAM, AUD, fetch=Fetcher(), clock=lambda: 1_800_000_000, profiles=lambda: ROLES)
        cls.home = server_http.make_server("127.0.0.1", 0, web_dir=cls.box.web, tunnel_hosts=HOSTS)
        cls.remote = server_http.make_server("127.0.0.1", 0, web_dir=cls.box.web, access=verifier, tunnel_hosts=HOSTS)
        cls.threads = []
        for httpd in (cls.home, cls.remote):
            thread = threading.Thread(target=httpd.serve_forever, daemon=True)
            thread.start()
            cls.threads.append(thread)

    @classmethod
    def tearDownClass(cls):
        for httpd in (cls.home, cls.remote):
            httpd.shutdown()
            httpd.server_close()
        for thread in cls.threads:
            thread.join(5)
        cls.log_patch.stop()
        cls.box.stop()

    def request(self, httpd, method, path, body=None, headers=None):
        """(status, the answer as JSON, or None when it isn't JSON)."""
        conn = http.client.HTTPConnection("127.0.0.1", httpd.server_address[1], timeout=10)
        try:
            headers = dict(headers or {})
            conn.putrequest(method, path, skip_host="Host" in headers, skip_accept_encoding=True)
            for key, value in headers.items():
                conn.putheader(key, value)
            if body is not None:
                conn.putheader("Content-Length", str(len(body)))
            conn.endheaders(body)
            response = conn.getresponse()
            data = response.read()
            is_json = (response.headers.get("Content-Type") or "").startswith("application/json")
            return response.status, json.loads(data) if is_json else None
        finally:
            conn.close()

    def raw_get(self, httpd, path):
        """The answer to a plain GET: its status, headers and body bytes."""
        conn = http.client.HTTPConnection("127.0.0.1", httpd.server_address[1], timeout=10)
        try:
            conn.request("GET", path)
            response = conn.getresponse()
            return types.SimpleNamespace(status=response.status, headers=response.headers, body=response.read())
        finally:
            conn.close()

    def home_get(self, path, headers=None):
        return self.request(self.home, "GET", path, headers=headers)

    def remote_get(self, path, email, headers=None):
        given = {"Host": HOSTS[0], "Cf-Access-Jwt-Assertion": token(claims(email=email)), **(headers or {})}
        return self.request(self.remote, "GET", path, headers=given)

    # ------------------------------------------------------------------ who is a script

    def test_a_script_on_the_pc_is_answered_as_today(self):
        status, answer = self.home_get("/api/collection?space=user2", SCRIPT)
        self.assertEqual(status, 200, answer)
        self.assertEqual(answer["space"], "user2")
        for path in ("/api/collection", "/api/tokens?space=user2", "/api/accessories", "/api/activity"):
            self.assertEqual(self.home_get(path, SCRIPT)[0], 200, path)
        status, me = self.home_get("/api/me", SCRIPT)
        self.assertEqual((status, me["profile"], me["may"]["admin"], me["may"]["see_inventory"]), (200, None, True, None))

    def test_naming_nobody_without_the_header_sees_nothing_private(self):
        # A phone on the Wi-Fi, or the PC's browser before a profile is picked: no script header.
        for headers in ({}, {access.SCRIPT_HEADER: "0"}, {access.SCRIPT_HEADER: "yes"}):
            with self.subTest(headers=headers):
                status, answer = self.home_get("/api/collection?space=user2", headers)
                self.assertEqual(status, 403, answer)
                self.assertEqual(answer["error"], "That collection isn't public.")    # naming no one (E10-S29)
                for path in ("/api/collection", "/api/tokens", "/api/tokens?space=user2", "/api/accessories",
                             "/api/shopping", "/api/profiles/matt/wishlist", "/api/visits"):
                    self.assertEqual(self.home_get(path, headers)[0], 403, path)
        status, me = self.home_get("/api/me")
        self.assertEqual(status, 200)
        self.assertEqual((me["may"]["admin"], me["may"]["see_inventory"], me["may"]["see_accessories"],
                          me["may"]["spaces"], me["may"]["create"]), (False, [], False, [], []))
        status, activity = self.home_get("/api/activity")
        self.assertEqual((status, activity["changes"], activity["everything"]), (200, [], False))
        # The page still works before a pick: its files, status, profiles and the open deck lists.
        for path in ("/", "/api/status", "/api/profiles", "/api/decks"):
            self.assertEqual(self.home_get(path)[0], 200, path)
        status, answer = self.request(self.home, "POST", "/api/collection/save", b'{"space": "home"}', WRITE)
        self.assertEqual(status, 403, answer)       # no profile: a write needs one, as before

    def test_a_viewer_and_the_header_together_is_the_viewer(self):
        # The header counts only for a request naming nobody: User1 named gets her own rights.
        self.assertEqual(self.home_get("/api/collection?space=user2",
                                       {**SCRIPT, access.VIEWER_HEADER: "user1"})[0], 403)
        self.assertEqual(self.home_get("/api/collection", {**SCRIPT, access.VIEWER_HEADER: "user1"})[0], 200)

    def test_the_tunnel_gets_nothing_extra_from_the_header(self):
        # The tunnel's listener is on 127.0.0.1 too, so loopback alone can't make a script.
        for headers in ({}, SCRIPT):
            with self.subTest(headers=headers):
                status, answer = self.remote_get("/api/collection?space=user2", "user1@example.com", headers)
                self.assertEqual(status, 403, answer)
                self.assertEqual(self.remote_get("/api/accessories", "user2@example.com", headers)[0], 403)
                status, me = self.remote_get("/api/me", "user1@example.com", headers)
                self.assertEqual((me["profile"], me["may"]["admin"]), ("user1", False))
        status, _ = self.request(self.remote, "GET", "/api/collection", headers={"Host": HOSTS[0], **SCRIPT})
        self.assertEqual(status, 403)               # no login at all: refused, header or not

    def test_who_counts_as_a_script(self):
        def handler(address, headers=(), remote=False):
            message = email.message.Message()
            for name, value in headers:
                message[name] = value
            return types.SimpleNamespace(server=types.SimpleNamespace(remote=remote), headers=message,
                                         client_address=(address, 1234))
        is_script = server_http.Handler._is_script
        header = [(access.SCRIPT_HEADER, "1")]
        for address in ("127.0.0.1", "::1", "::ffff:127.0.0.1"):
            self.assertTrue(is_script(handler(address, header), None), address)
        self.assertFalse(is_script(handler("192.0.2.10", header), None))    # the PC's own LAN address
        self.assertFalse(is_script(handler("127.0.0.1"), None))                 # no header
        self.assertFalse(is_script(handler("127.0.0.1", header * 2), None))     # given twice
        self.assertFalse(is_script(handler("127.0.0.1", [(access.SCRIPT_HEADER, "true")]), None))
        self.assertFalse(is_script(handler("127.0.0.1", header), "matt"))       # a viewer named
        self.assertFalse(is_script(handler("127.0.0.1", header, remote=True), None))   # the tunnel's

    # ------------------------------------------------------------------ the home chooser

    def test_a_member_named_at_home_is_sent_to_decklab_example(self):
        user2 = {access.VIEWER_HEADER: "user2"}
        # In JSON under /api/; a page address (an old /?profile=user2 bookmark) gets a short page saying so.
        refused = lambda path: (403, HOME_ONLY if path.startswith("/api/") else None)
        for path in ("/api/status", "/api/me", "/api/profiles", "/api/decks", "/api/collection?space=user2",
                     "/", "/nothing", "/api/profiles/user2/settings"):
            self.assertEqual(self.home_get(path, user2), refused(path), path)
            self.assertEqual(self.home_get(path, {**user2, **SCRIPT}), refused(path), path)
        # ?profile= and an accessory picture's ?viewer= name a viewer too, as does a write's body.
        for path in ("/?profile=user2", "/api/matchup?key=" + "0" * 64 + "&profile=user2",
                     "/accessory-img/black.png?v=0123abcd&viewer=user2"):
            self.assertEqual(self.home_get(path), refused(path), path)
        page = self.raw_get(self.home, "/?profile=user2")
        self.assertEqual((page.status, page.headers.get("Content-Type")), (403, "text/html; charset=utf-8"))
        self.assertIn(access.SIGN_IN_OUTSIDE.encode(), page.body)
        body = json.dumps({"profile": "user2", "space": "user2"}).encode()
        for headers in (WRITE, {**WRITE, **SCRIPT}):
            self.assertEqual(self.request(self.home, "POST", "/api/collection/save", body, headers), (403, HOME_ONLY))
        # Home profiles are picked as before, and a name config.json doesn't list is left to the route.
        self.assertEqual(self.home_get("/api/me", {access.VIEWER_HEADER: "user1"})[0], 200)
        self.assertEqual(self.home_get("/?profile=user1")[0], 200)
        self.assertEqual(self.home_get("/api/me", {access.VIEWER_HEADER: "stranger"})[0], 200)
        # Through the tunnel User2's login is his: nothing is refused for naming him.
        self.assertEqual(self.remote_get("/api/collection?space=user2", "user2@example.com")[0], 200)

    def test_me_answers_for_the_profile_picked_at_home(self):
        # The chooser's pick gets its own "may" from /api/me, as the server holds its reads and writes to.
        status, me = self.home_get("/api/me", {access.VIEWER_HEADER: "user1"})
        self.assertEqual((status, me["profile"], me["name"], me["remote"]), (200, "user1", "User1", False))
        self.assertEqual((me["may"]["admin"], me["may"]["see_inventory"], me["may"]["accessory_owners"]),
                         (False, ["home"], ["shared", "user1"]))
        status, me = self.home_get("/api/me", {access.VIEWER_HEADER: "matt"})
        self.assertEqual((status, me["profile"], me["may"]["admin"]), (200, "matt", True))
        status, me = self.home_get("/api/me", {access.VIEWER_HEADER: "stranger"})
        self.assertEqual((status, me["profile"], me["may"]["admin"]), (200, None, False))

    def test_an_unreadable_config_still_answers_status(self):
        # Nobody named can be told apart without config.json, but the footer's /api/status still answers.
        user1 = {access.VIEWER_HEADER: "user1"}
        with mock.patch.object(config, "load", side_effect=ValueError("broken")):
            self.assertEqual(self.home_get("/api/status", user1)[0], 200)
            self.assertEqual(self.home_get("/api/me", user1)[0], 500)

    def test_the_page_offers_only_home_profiles(self):
        app = (config.DECKLAB / "web" / "app.js").read_text(encoding="utf-8")
        self.assertIn("function homeProfiles()", app)
        draw = app[app.index("function drawWho()"):]
        draw = draw[:draw.index("\n}\n")]
        self.assertIn("homeProfiles()", draw)
        self.assertNotIn("[...state.profiles]", draw)
        start = app[app.index("const wanted = params.get(\"profile\")"):]
        self.assertTrue(start.splitlines()[1].strip().startswith("const profile = homeProfiles().find("))


class ScriptRuleTests(unittest.TestCase):

    def test_outside_any_request_is_a_script(self):
        self.assertTrue(access.script())
        self.assertTrue(guard.script())
        self.assertIsNone(guard.inventory_spaces())
        self.assertIsNone(guard.accessory_owners())
        with access.answering(False):
            self.assertFalse(guard.script())
            self.assertTrue(guard.local())                  # still "not through the tunnel"
            self.assertEqual(guard.inventory_spaces(), [])
            self.assertEqual(guard.accessory_owners(), frozenset())
        self.assertTrue(guard.script())
        with access.using({"profile": "matt", "email": "", "remote": True}):
            self.assertFalse(guard.script())                # a visit through the tunnel never is
            self.assertFalse(guard.local())

    def test_a_job_thread_reads_every_space(self):
        # The Forge coordinator and goldfish run in threads of their own: no request, so a script,
        # even when a request that isn't one started them.
        seen = {}

        def job():
            seen["script"] = guard.script()
            seen["spaces"] = guard.inventory_spaces()
            seen["deck"] = guard.sees_deck("user2/commander/lathliss")
        with access.answering(False), access.viewing(None):
            thread = threading.Thread(target=job)
            thread.start()
            thread.join(5)
        self.assertEqual(seen, {"script": True, "spaces": None, "deck": True})

    def test_the_call_sites_that_meant_naming_nobody_ask_script(self):
        # history, commits, dbstatus, visits, simulations and the editor: each asks guard.script(), and
        # none asks guard.local() for it any more (local() stays for viewer() and the audit "via").
        api_dir = config.DECKLAB / "lib" / "api"
        for name in ("history", "commits", "visits", "simulations", "editor", "activity", "opponents", "rename",
                     "retirement", "commander_night", "play_records"):
            text = (api_dir / f"{name}.py").read_text(encoding="utf-8")
            self.assertIn("guard.script()", text, name)
            self.assertIsNone(re.search(r"local=guard\.local\(\)|is None and guard\.local\(\)", text), name)
        self.assertIn("dbstatus.view(viewer, script=guard.script())",
                      (config.DECKLAB / "lib" / "server_http.py").read_text(encoding="utf-8"))
        for path in (config.DECKLAB / "lib").rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            self.assertIsNone(re.search(r"permissions\.\w+\([^)]*\blocal=", text), path)

    def test_the_call_sites_answer_nobody_by_script(self):
        with mock.patch.object(guard, "viewer", return_value=None):
            self.assertEqual(commits._viewer_id(False), (None, True))
            self.assertEqual(history._viewer(), (None, True))
            self.assertIsNone(visits._require_admin())
            with mock.patch.object(simulations, "_read", return_value=({"mode": "paused"}, False)), \
                    mock.patch.object(simulations, "_slots"), mock.patch.object(simulations, "_max_workers"):
                self.assertTrue(simulations.view()["may_edit"])
                self.assertTrue(simulations.view()["may_start"])        # a script, even while paused
                with access.answering(False):
                    self.assertEqual(simulations.view()["may_edit"], False)
                    self.assertEqual(simulations.view()["may_start"], False)
            with access.answering(False):
                self.assertEqual(commits._viewer_id(False), (None, False))
                self.assertEqual(history._viewer(), (None, False))
                with self.assertRaises(ApiError) as e:
                    visits._require_admin()
                self.assertEqual(e.exception.status, 403)
        snapshot = {"ok": False, "usable": True, "error": dbstatus.MIGRATIONS_PENDING, "detail": "1 pending",
                    "pending_migrations": 1, "last_backup": None, "backup_stale": True, "stale_hours": 36}
        with mock.patch.object(dbstatus, "_snapshot", snapshot), mock.patch.object(dbstatus.venv, "reason", lambda: None):
            self.assertEqual(dbstatus.view(None, script=True)["pending_migrations"], 1)
            self.assertEqual(dbstatus.view(None), {"ok": True})


class ActivityTests(_Store):

    def test_a_home_request_naming_nobody_that_isnt_a_script_sees_nothing(self):
        from decklab.lib.api import activity
        self.write_everything()
        self.assertTrue(self.view()["everything"])                      # a script (no request)
        with access.answering(False):
            for who in (None, "nobody-known"):
                with self.subTest(who=who):
                    self.assertEqual(self.view(who), {"changes": [], "next": None, "everything": False, "cards": {}})
        with access.answering(False), access.viewing(None):
            self.assertEqual(activity.activity_view()["changes"], [])


if __name__ == "__main__":
    unittest.main()
