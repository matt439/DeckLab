"""Tests for the server's two listeners (decklab/server.py with lib/access.py):
the tunnel's listener takes only requests with a valid Cloudflare Access
login for a profile's email, and acts as that profile whatever the request
says; the home listener refuses requests that came through Cloudflare.

Both servers run in threads on 127.0.0.1 with free ports (never 8642 or
8644) over test_api's Sandbox, with test_access's fixed test key standing in
for Cloudflare's keys. Nothing reaches the internet.

Run from the repo root: python -m unittest discover -s decklab/tests -t .
"""
import http.client
import json
import threading
import time
import unittest
from unittest import mock

from decklab import server  # noqa: F401 (runs build.start() before the server modules load)
from decklab.lib import access, api, server_http, server_run, tunnel
from decklab.tests.test_access import AUD, TEAM, Fetcher, claims, token
from decklab.tests.test_api import Sandbox
from decklab.tests.test_control import free_port

HOSTS = ("decklab.example.com", "www.decklab.example.com")
WRITE = {"Content-Type": "application/json", "X-Deck-Lab": "1"}
SCRIPT = {"X-Deck-Lab-Script": "1"}     # a script on the PC (access.SCRIPT_HEADER)
PROFILES = [{"id": "matt", "name": "Matt", "plays_as": "user", "role": "admin", "emails": ["matt@example.com"]},
            {"id": "user1", "name": "User1", "plays_as": "wife", "emails": ["user1@example.com"]},
            {"id": "user2", "name": "User2", "role": "member", "space": "user2",
             "emails": ["user2@example.com"]}]


class TwoListenersTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.box = Sandbox().start()
        (cls.box.web / "index.html").parent.mkdir(parents=True, exist_ok=True)
        (cls.box.web / "index.html").write_text("<!doctype html><title>Deck Lab</title>", encoding="utf-8")
        cls.log_patch = mock.patch.object(server_http, "log", lambda text: None)
        cls.log_patch.start()
        cls.fetch = Fetcher()
        # The tokens are made for test_access's NOW: the verifier's clock is the token's time.
        verifier = access.Verifier(TEAM, AUD, fetch=cls.fetch, clock=lambda: 1_800_000_000,
                                   profiles=lambda: PROFILES)
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
            return response.status, response.headers, response.read()
        finally:
            conn.close()

    def remote_request(self, method, path, body=None, email="matt@example.com", headers=None):
        given = {"Host": "decklab.example.com"}
        if email:
            given["Cf-Access-Jwt-Assertion"] = token(claims(email=email))
        if body is not None:
            given.update(WRITE)
        given.update(headers or {})
        return self.request(self.remote, method, path, body, given)

    # ------------------------------------------------------- the tunnel's listener

    def test_no_token_is_refused_everywhere(self):
        for path in ("/api/status", "/api/me", "/", "/img/fdn/1/small", "/nothing"):
            status, headers, body = self.remote_request("GET", path, email=None)
            self.assertEqual(status, 403, path)
            if path.startswith("/api/"):
                self.assertIn("Sign in", json.loads(body)["error"])
            else:
                self.assertTrue(headers["Content-Type"].startswith("text/html"))
                self.assertIn(b"Sign in", body)

    def test_refusals_on_both_listeners_are_marked_as_deck_labs(self):
        # The off page's Worker never replaces Deck Lab's own answers: its refusals carry the header too.
        name, value = server_http.ORIGIN_HEADER
        status, headers, body = self.remote_request("GET", "/", email=None)
        self.assertEqual((status, headers[name]), (403, value))
        self.assertTrue(headers["Content-Type"].startswith("text/html"), body[:100])
        status, headers, _ = self.remote_request("GET", "/api/status")
        self.assertEqual((status, headers[name]), (200, value))
        status, headers, _ = self.request(self.home, "GET", "/api/status", headers={"Host": HOSTS[0]})
        self.assertEqual((status, headers[name]), (421, value))

    def test_a_bad_token_is_refused(self):
        status, _, body = self.remote_request("GET", "/api/status", email=None,
                                              headers={"Cf-Access-Jwt-Assertion": "a.b.c"})
        self.assertEqual(status, 403)
        self.assertIn("isn't valid", json.loads(body)["error"])
        expired = token(claims(exp=1_000_000_000))
        status, _, _ = self.remote_request("GET", "/api/status", email=None,
                                           headers={"Cookie": f"CF_Authorization={expired}"})
        self.assertEqual(status, 403)

    def test_an_email_no_profile_has(self):
        status, _, body = self.remote_request("GET", "/api/status", email="stranger@example.com")
        self.assertEqual(status, 403)
        self.assertEqual(json.loads(body)["error"], "This email isn't set up in Deck Lab")

    def test_the_cookie_works_too(self):
        status, _, _ = self.remote_request("GET", "/api/status", email=None,
                                           headers={"Cookie": f"CF_Authorization={token()}"})
        self.assertEqual(status, 200)

    def test_only_the_tunnels_host_names(self):
        for host in ("127.0.0.1", "localhost", "example.com"):
            status, _, _ = self.remote_request("GET", "/api/status", headers={"Host": host})
            self.assertEqual(status, 400, host)
        status, _, _ = self.remote_request("GET", "/", headers={"Host": "www.decklab.example.com"})
        self.assertEqual(status, 200)

    def test_the_database_block_through_the_tunnel(self):
        # A member's login gets only whether the stores can be used; an admin's the details.
        from decklab.lib import dbstatus
        path = self.box.root / "config.json"
        saved = path.read_bytes()
        self.addCleanup(path.write_bytes, saved)
        path.write_text(json.dumps({"profiles": PROFILES}), encoding="utf-8")
        snapshot = {"ok": False, "usable": False, "error": dbstatus.NOT_REACHABLE, "detail": "connection refused",
                    "pending_migrations": None, "last_backup": None, "backup_stale": None, "stale_hours": 36}
        with mock.patch.object(dbstatus, "_snapshot", snapshot), \
                mock.patch.object(dbstatus.venv, "reason", lambda: None):
            status, _, body = self.remote_request("GET", "/api/status", email="user2@example.com")
            self.assertEqual((status, json.loads(body)["database"]), (200, {"ok": False}))
            status, _, body = self.remote_request("GET", "/api/status", email="matt@example.com")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["database"]["error"], "not reachable")
        self.assertNotIn(b"connection refused", body)

    def test_me_through_the_tunnel(self):
        status, _, body = self.remote_request("GET", "/api/me", email="User1@Example.com")
        self.assertEqual(status, 200)
        self.assertEqual({k: v for k, v in json.loads(body).items() if k != "may"},
                         {"profile": "user1", "name": "User1", "remote": True})

    def test_the_body_profile_is_the_logins(self):
        seen = []

        def parse(body):
            seen.append((json.loads(body), access.current()))
            return {"ok": True}
        with mock.patch.object(api, "parse_list", parse):
            status, _, _ = self.remote_request("POST", "/api/decklist/parse",
                                               json.dumps({"profile": "matt", "text": "x"}).encode(),
                                               email="user1@example.com")
            self.assertEqual(status, 200)
            status, _, _ = self.request(self.home, "POST", "/api/decklist/parse",
                                        json.dumps({"profile": "matt", "text": "x"}).encode(), WRITE)
            self.assertEqual(status, 200)
        self.assertEqual(seen[0][0], {"profile": "user1", "text": "x"})
        self.assertEqual(seen[0][1], {"profile": "user1", "email": "user1@example.com", "remote": True})
        self.assertEqual(seen[1], ({"profile": "matt", "text": "x"}, None))          # home: as sent

    def test_a_body_without_a_profile_is_left_alone(self):
        seen = []
        with mock.patch.object(api, "parse_list", lambda body: seen.append(body) or {}):
            self.remote_request("POST", "/api/decklist/parse", b'{"text": "x"}')
            status, _, _ = self.remote_request("POST", "/api/decklist/parse", b'{"text": ')
        self.assertEqual(seen, [b'{"text": "x"}'])
        self.assertEqual(status, 400)

    def test_the_query_profile_is_the_logins(self):
        seen = []

        def matchup(*args):
            seen.append(args[-1])
            return {"status": "none"}
        with mock.patch.object(api, "matchup", matchup):
            self.remote_request("GET", "/api/matchup?key=" + "0" * 64 + "&profile=matt", email="user1@example.com")
            self.remote_request("GET", "/api/matchup?key=" + "0" * 64, email="user1@example.com")
            self.request(self.home, "GET", "/api/matchup?key=" + "0" * 64 + "&profile=matt")
        self.assertEqual(seen, ["user1", "user1", "matt"])

    def test_another_profiles_settings_and_wishlist_are_refused(self):
        body = json.dumps({"theme": "dark"}).encode()
        status, _, answer = self.remote_request("PUT", "/api/profiles/matt/settings", body, email="user1@example.com")
        self.assertEqual(status, 403, answer)
        status, _, answer = self.remote_request("POST", "/api/profiles/matt/wishlist",
                                                json.dumps({"profile": "matt", "action": "remove", "name": "Not On It"}).encode(),
                                                email="user1@example.com")
        self.assertEqual(status, 403, answer)
        status, _, answer = self.remote_request("PUT", "/api/profiles/user1/settings", body,
                                                email="user1@example.com")
        self.assertEqual(status, 200, answer)
        last = self.box.state.changes()[-1]          # made by the login, through the tunnel
        self.assertEqual((last["actor"], last["via"]), ("user1", "tunnel"))
        # Nor may she look at them: settings are read only by their own profile, an admin's role reads
        # no one else's either, and a profile that doesn't exist answers the same (E10-S34, E10-S38).
        for path, email in (("/api/profiles/matt/settings", "user1@example.com"),
                            ("/api/profiles/user1/settings", "matt@example.com"),
                            ("/api/profiles/user1/settings", "user2@example.com"),
                            ("/api/profiles/nobody/settings", "user1@example.com")):
            status, _, answer = self.remote_request("GET", path, email=email)
            self.assertEqual((status, json.loads(answer)), (403, {"error": api.settings.SETTINGS_HIDDEN}), path)
        status, _, _ = self.remote_request("GET", "/api/profiles/user1/settings", email="user1@example.com")
        self.assertEqual(status, 200)               # her own

    def test_a_wishlist_is_read_only_by_its_owners_login(self):
        for email, status in (("user1@example.com", 200), ("matt@example.com", 403), ("user2@example.com", 403)):
            with self.subTest(email=email):
                code, _, answer = self.remote_request("GET", "/api/profiles/user1/wishlist", email=email)
                self.assertEqual(code, status, answer)
        # The X-Deck-Lab-Viewer header is the home page's: through the tunnel the login decides.
        code, _, _ = self.remote_request("GET", "/api/profiles/user1/wishlist", email="matt@example.com",
                                         headers={"X-Deck-Lab-Viewer": "user1"})
        self.assertEqual(code, 403)

    def test_a_person_space_never_gets_the_accessories(self):
        # The sleeves, deck boxes and playmats are the home's: 403 for User2 (his own space), list and pictures,
        # whatever the picture's name; User1 gets past the check (404: no such picture), as does the home network.
        listed = [{"id": "matt", "name": "Matt", "plays_as": "user", "role": "admin", "space": "home"},
                  {"id": "user1", "name": "User1", "plays_as": "wife", "role": "member", "space": "home"},
                  {"id": "user2", "name": "User2", "plays_as": None, "role": "member", "space": "user2"}]
        with mock.patch.object(api.settings, "_config_profiles", lambda emails=False: listed):
            for path in ("/api/accessories", "/accessory-img/black.png", "/accessory-img/staged/" + "0" * 32 + ".png"):
                status, _, body = self.remote_request("GET", path, email="user2@example.com")
                self.assertEqual(status, 403, path)
                self.assertEqual(json.loads(body)["error"], "The sleeves, deck boxes and playmats are private.")
            status, _, body = self.remote_request("GET", "/api/me", email="user2@example.com")
            self.assertFalse(json.loads(body)["may"]["see_accessories"])
            status, _, _ = self.remote_request("GET", "/accessory-img/black.png", email="user1@example.com")
            self.assertEqual(status, 404)
            # At home only a script naming nobody gets past the check (E10-S35); the page before a pick doesn't.
            self.assertEqual(self.request(self.home, "GET", "/accessory-img/black.png", headers=SCRIPT)[0], 404)
            self.assertEqual(self.request(self.home, "GET", "/accessory-img/black.png")[0], 403)
            # A picture's ?viewer= is the home page's (an <img> sends no header): through the tunnel the
            # login decides, whatever it names; at home it names who's looking.
            for path in ("/accessory-img/black.png?v=0123abcd&viewer=user1",
                         "/accessory-img/staged/" + "0" * 32 + ".png?viewer=matt"):
                self.assertEqual(self.remote_request("GET", path, email="user2@example.com")[0], 403, path)
                self.assertEqual(self.remote_request("GET", path.replace("=user1", "=user2").replace(
                    "=matt", "=user2"), email="user1@example.com")[0], 404, path)
                self.assertEqual(self.request(self.home, "GET", path)[0], 404, path)
                self.assertEqual(self.request(self.home, "GET", path.replace("=user1", "=user2").replace(
                    "=matt", "=user2"))[0], 403, path)

    def test_home_writes_follow_the_profile_picked(self):
        # E10-S03: on the home network a write has its named profile's own rights, as through the tunnel.
        # User1 picked there saving home's collection passes the check (E10-S43: home's is hers as Matt's;
        # here the stale sha256 is its 409). User2 can't be picked there at all (E10-S35: 403 "Sign in
        # through decklab.example.com", by header or body). A body naming another profile than the page's
        # viewer header: 403. A script naming nobody in a header passes the check (here it gets as far as
        # the body's checks: not a 403).
        listed = [{"id": "matt", "name": "Matt", "plays_as": "user", "role": "admin", "space": "home"},
                  {"id": "user1", "name": "User1", "plays_as": "wife", "role": "member", "space": "home"},
                  {"id": "user2", "name": "User2", "plays_as": None, "role": "member", "space": "user2"}]
        save = {"space": "home", "action": "add", "sha256": "0" * 64,
                "row": {"name": "Llanowar Elves", "set": "fdn", "collector_number": "227", "finish": "nonfoil",
                        "quantity": 1}}
        with mock.patch.object(api.settings, "_config_profiles", lambda emails=False: listed):
            for viewer, body, status in (("user2", "user2", 403), ("user1", "user1", 409),
                                         (None, "user2", 403), ("user1", "matt", 403)):
                with self.subTest(viewer=viewer, body=body):
                    headers = {**WRITE, **({"X-Deck-Lab-Viewer": viewer} if viewer else {})}
                    code, _, answer = self.request(self.home, "POST", "/api/collection/save",
                                                   json.dumps({"profile": body, **save}).encode(), headers)
                    self.assertEqual(code, status, answer)
                    if status == 403:
                        self.assertEqual(list(json.loads(answer)), ["error"])
                    if "user2" in (viewer, body):
                        self.assertEqual(json.loads(answer)["error"], access.SIGN_IN_OUTSIDE)
            code, _, answer = self.request(self.home, "POST", "/api/collection/save",
                                           json.dumps({"profile": "user1", **save}).encode(),
                                           {**WRITE, "X-Deck-Lab-Viewer": "matt"})
            self.assertEqual(json.loads(answer)["error"], "You can only make changes as yourself")
            code, _, answer = self.request(self.home, "POST", "/api/collection/save",
                                           json.dumps({"profile": "matt", **save}).encode(), WRITE)
            self.assertNotEqual(code, 403, answer)

    # ---------------------------------------------------------- the home listener

    def test_home_refuses_the_tunnels_host_names(self):
        for host in HOSTS + ("DeckLab.Example.com:443",):
            status, _, body = self.request(self.home, "GET", "/api/status", headers={"Host": host})
            self.assertEqual(status, 421, host)
            self.assertIn("home network", json.loads(body)["error"])

    def test_home_refuses_cloudflares_headers(self):
        for name in ("Cf-Access-Jwt-Assertion", "Cf-Ray", "Cf-Connecting-Ip", "cf-ray"):
            status, _, _ = self.request(self.home, "GET", "/api/status", headers={name: "x"})
            self.assertEqual(status, 421, name)

    def test_home_as_before(self):
        status, _, body = self.request(self.home, "GET", "/api/me")
        self.assertEqual(status, 200)
        self.assertEqual({k: v for k, v in json.loads(body).items() if k != "may"},
                         {"profile": None, "name": None, "remote": False})
        self.assertEqual(self.request(self.home, "GET", "/")[0], 200)
        self.assertEqual(self.request(self.home, "GET", "/api/status", headers={"Host": "example.com"})[0], 400)


class ServeTests(unittest.TestCase):
    """_serve opens the tunnel's listener beside the home one, and closes both."""

    def setUp(self):
        self.box = Sandbox().start()
        self.addCleanup(self.box.stop)
        self.logged = []
        for patch in (mock.patch.object(server_http, "log", self.logged.append),
                      mock.patch.object(server_run, "_start_pool", lambda: None),
                      mock.patch.object(server_run, "_wait_for_matchup", lambda: None),
                      mock.patch.object(server_run, "_stop_pool", lambda wait=0: None),
                      mock.patch.object(server_run, "_record_state", lambda *a: None),
                      mock.patch.object(server_run.control, "clear_state", lambda pid: None),
                      mock.patch.object(server_run.control, "listen_for_stop", mock.Mock(side_effect=OSError("no"))),
                      mock.patch.object(server_run.control, "watch_session_end", mock.Mock(side_effect=OSError("no"))),
                      mock.patch.object(server_run, "_stop_jobs_on_ctrl_c", lambda port=None: None),
                      mock.patch.object(server_run, "_load_index", lambda: None),
                      mock.patch.object(server_run, "_database_check", lambda background: lambda: None),
                      mock.patch.object(tunnel, "usual_server", lambda port, configured: True)):
            patch.start()
            self.addCleanup(patch.stop)

    def test_both_listeners_start_and_stop(self):
        port, remote_port = free_port(), free_port()
        settings = {"port": port, "allowed_hosts": list(HOSTS),
                    "access": {"team": TEAM, "aud": AUD, "port": remote_port}}
        made, calls, codes = [], [], []
        real_make = server_http.make_server

        def make(*args, **kwargs):
            calls.append(kwargs)
            made.append(real_make(*args, **kwargs))
            return made[-1]
        done = threading.Thread(target=lambda: codes.append(
            server_run._serve("127.0.0.1", port, True, settings, None, False)), daemon=True)
        with mock.patch.object(server_http, "make_server", make):
            done.start()
            deadline = time.monotonic() + 10
            while len(made) < 2 and time.monotonic() < deadline:
                time.sleep(0.05)
            home, remote = made
            self.assertFalse(home.remote)
            self.assertEqual(calls[0]["allowed_hosts"], [])         # the tunnel's names aren't the home's
            self.assertEqual(home.tunnel_hosts, frozenset(HOSTS))
            self.assertTrue(remote.remote)
            self.assertEqual(remote.server_address, ("127.0.0.1", remote_port))
            self.assertEqual(tunnel.check_listener(remote_port, "decklab.example.com", 5)[0], "refuses")
            home.shutdown()                 # what a stop request does: both listeners close
            done.join(10)
        self.assertFalse(done.is_alive())
        self.assertEqual(codes, [0])
        self.assertEqual(tunnel.check_listener(remote_port, "decklab.example.com", 2)[0], "closed")
        self.assertTrue(any(f"listening on 127.0.0.1:{remote_port}" in line for line in self.logged))

    def test_the_home_listener_refuses_the_tunnels_names_without_access_too(self):
        tunnel_block = {"config": "~/.cloudflared/config.yml", "hostname": "DeckLab.Example.com"}
        allowed = ["decklab.example.com", "www.decklab.example.com", "deckpc.lan"]
        for extra in ({}, {"access": {"team": "x"}}, {"access": "wrong"}):
            settings = {"port": 1, "allowed_hosts": allowed, "tunnel": tunnel_block, **extra}
            calls = []

            def make(*args, **kwargs):
                calls.append(kwargs)
                raise OSError("not listening in this test")
            with self.subTest(extra=extra), mock.patch.object(server_http, "make_server", make):
                self.assertEqual(server_run._serve("127.0.0.1", 1, True, settings, None, False), 1)
                self.assertEqual(calls[0]["tunnel_hosts"], frozenset(HOSTS))
                self.assertEqual(calls[0]["allowed_hosts"], ["deckpc.lan"])     # not a tunnel name
        # With a valid "access", every allowed host is the tunnel's (as before).
        valid = {"allowed_hosts": allowed, "tunnel": tunnel_block, "access": {"team": TEAM, "aud": AUD, "port": 2}}
        self.assertEqual(access.home_refused_hosts(valid), frozenset(allowed))
        self.assertEqual(access.home_refused_hosts({"allowed_hosts": allowed}), frozenset())

    def test_a_tunnel_name_is_421_on_the_home_listener(self):
        refused = access.home_refused_hosts({"tunnel": {"config": "x", "hostname": "decklab.example.com"},
                                             "allowed_hosts": list(HOSTS)})
        home = server_http.make_server("127.0.0.1", 0, web_dir=self.box.web, tunnel_hosts=refused)
        thread = threading.Thread(target=home.serve_forever, daemon=True)
        thread.start()
        try:
            for host in HOSTS:
                conn = http.client.HTTPConnection("127.0.0.1", home.server_address[1], timeout=5)
                conn.request("GET", "/api/status", headers={"Host": host})
                self.assertEqual(conn.getresponse().status, 421, host)
                conn.close()
        finally:
            home.shutdown()
            home.server_close()
            thread.join(5)

    def test_a_wrong_access_block_opens_no_listener(self):
        self.assertIsNone(server_run._start_remote({"access": {"team": "x"}}, 1, 1))
        self.assertIn("ACCESS:", self.logged[-1])

    def test_a_taken_port_is_logged(self):
        taken = server_http.make_server("127.0.0.1", 0)
        self.addCleanup(taken.server_close)
        settings = {"access": {"team": TEAM, "aud": AUD, "port": taken.server_address[1]}}
        self.assertIsNone(server_run._start_remote(settings, 1, 1))
        self.assertIn("can't listen for the tunnel", self.logged[-1])


if __name__ == "__main__":
    unittest.main()
