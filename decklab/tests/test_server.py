"""Tests for decklab/server.py: a real server on 127.0.0.1 with a free port.

The server runs in a thread over test_api's Sandbox (a temp magic/ tree,
data folder, config and the fixture card index, with a stand-in stats module)
and a temp web/ folder, so nothing touches the network or the real
decklab/data/. Requests go through http.client, which sends paths exactly as
written, so traversal attempts like /%2e%2e/ reach the server unchanged.

MainTests run main() itself in a thread, and BackgroundServerTests run
pythonw.exe decklab/server.py as a real background server, each on a free
port (never 8642, where the real server may be running), with a temp state
file (control.STATE_FILE, or DECKLAB_STATE_FILE for the real processes) and
temp log files, so the real decklab/data/server.json and logs are never
touched and the real server is never signalled.

Run from the repo root: python -m unittest discover -s decklab/tests -t .
Process startup, shutdown and direct-script checks live in test_server_lifecycle.py;
HTTP endpoint and protocol checks remain here.
"""
import contextlib
import errno
import http.client
import io
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from decklab import server
from decklab.lib import access, api, config, control, server_http
from decklab.lib.forge import overrides as forge_overrides
from decklab.lib.forge import pool as forge_pool
from decklab.lib.forge import slots as forge_slots
from decklab.tests.test_api import W3_SETTINGS, Sandbox
from decklab.tests.test_control import NO_WINDOW, WINDOWS, free_port, now_iso, sleeper, wait_until

if WINDOWS:
    from decklab.tests.test_control import send_message, user32

REAL_LOG = server_http.log      # before any test replaces it

WEB_FILES = {
    "index.html": "<!doctype html><title>Deck Lab</title>",
    "app.js": "console.log('Deck Lab – ok');",
    "style.css": "body { margin: 0 }",
    "manifest.webmanifest": '{"name": "Deck Lab"}',
    "icons/icon-192.png": "\x89PNG",
    "fonts/figtree.woff2": "wOF2",
    # Never served: not a known type, hidden, or in another folder.
    "notes.txt": "private",
    ".hidden.js": "private",
    "other/extra.js": "private",
}


# What Deck Lab's page sends with every write (server.check_write).
WRITE = {"Content-Type": "application/json", "X-Deck-Lab": "1"}
# What a script on the PC sends to read and write as the command line does (access.SCRIPT_HEADER).
# request() adds it to every request that names no viewer, so these tests act as a script unless
# they say otherwise (script=False: a phone on the Wi-Fi naming nobody).
SCRIPT = {"X-Deck-Lab-Script": "1"}


class ServerTestCase(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.box = Sandbox().start()
        for name, text in WEB_FILES.items():
            path = cls.box.web / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(text.encode("utf-8"))
        (cls.box.root / "secret.txt").write_text("outside web/", encoding="utf-8")
        cls.log = []
        cls.log_patch = mock.patch.object(server_http, "log", cls.log.append)
        cls.log_patch.start()
        cls.httpd = server_http.make_server("127.0.0.1", 0, web_dir=cls.box.web)
        cls.port = cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.thread.join(5)
        cls.log_patch.stop()
        cls.box.stop()

    def request(self, method, path, body=None, headers=None, conn=None, script=True):
        """(status, headers, body bytes) for one request, sent exactly as given.
        A POST or PUT with no headers given gets WRITE's (what the page sends);
        one naming no viewer gets SCRIPT's too unless script is false."""
        own = conn is None
        conn = conn or http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            if headers is None and method in ("POST", "PUT"):
                headers = dict(WRITE)
            headers = dict(headers or {})
            if script and "X-Deck-Lab-Viewer" not in headers:
                headers.update(SCRIPT)
            conn.putrequest(method, path, skip_host="Host" in headers, skip_accept_encoding=True)
            for key, value in headers.items():
                conn.putheader(key, value)
            if body is not None:
                conn.putheader("Content-Length", str(len(body)))
            conn.endheaders(body)
            response = conn.getresponse()
            return response.status, response.headers, response.read()
        finally:
            if own:
                conn.close()

    def get_json(self, path, status=200, method="GET", body=None, headers=None):
        code, headers, data = self.request(method, path, body, headers)
        self.assertEqual(code, status, data[:300])
        self.assertEqual(headers["Content-Type"], "application/json; charset=utf-8")
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
        return json.loads(data)

    def assertError(self, path, status, method="GET", body=None, headers=None):
        data = self.get_json(path, status, method, body, headers)
        self.assertEqual(list(data), ["error"])
        self.assertNotIn("Traceback", data["error"])
        return data["error"]

    def raw(self, data):
        """Send bytes as they are; return the whole answer."""
        with socket.create_connection(("127.0.0.1", self.port), timeout=10) as sock:
            sock.sendall(data)
            chunks = []
            while chunk := sock.recv(65536):
                chunks.append(chunk)
        return b"".join(chunks)


class StaticFileTests(ServerTestCase):

    def test_page_version_is_injected_and_revalidated_after_asset_changes(self):
        path = self.box.web / "index.html"
        original = path.read_bytes()
        try:
            path.write_bytes(b'<meta name="decklab-web-revision" content="__DECKLAB_WEB_REVISION__">'
                             b'<link href="/base.css" rel="stylesheet"><script src="/app.js"></script>')
            with mock.patch.object(server.build, "web_revision", return_value="a" * 64):
                code, headers, body = self.request("GET", "/")
            self.assertEqual(code, 200)
            self.assertIn(b"a" * 64, body)
            self.assertNotIn(b"__DECKLAB", body)
            self.assertIn(b'/base.css?v=' + b"a" * 16 + b'"', body)
            self.assertIn(b'/app.js?v=' + b"a" * 16 + b'"', body)
            with mock.patch.object(server.build, "web_revision", return_value="b" * 64):
                code, fresh, body = self.request("GET", "/", headers={"If-None-Match": headers["ETag"]})
            self.assertEqual(code, 200, "An unchanged index file must still receive a new asset marker")
            self.assertIn(b"b" * 64, body)
            self.assertIn(b'/app.js?v=' + b"b" * 16 + b'"', body)
            self.assertNotEqual(fresh["ETag"], headers["ETag"])
            with mock.patch.object(server.build, "web_revision", return_value="b" * 64):
                code, _, body = self.request("GET", "/", headers={"If-None-Match": fresh["ETag"]})
            self.assertEqual((code, body), (304, b""))
        finally:
            path.write_bytes(original)

    def test_status_preserves_running_and_checkout_versions(self):
        provenance = {"running_commit": "a" * 40, "latest_commit": "b" * 40,
                      "restart_required": True, "running_dirty": False}
        with mock.patch.object(server.build, "status", return_value=provenance):
            answer = self.get_json("/api/status")
        self.assertEqual(answer["build"], provenance)
        self.assertIn("cards", answer)

    def test_the_page_files_with_their_types(self):
        for path, name, content_type in (
                ("/", "index.html", "text/html; charset=utf-8"),
                ("/index.html", "index.html", "text/html; charset=utf-8"),
                ("/app.js", "app.js", "text/javascript; charset=utf-8"),
                ("/style.css", "style.css", "text/css; charset=utf-8"),
                ("/manifest.webmanifest", "manifest.webmanifest", "application/manifest+json; charset=utf-8"),
                ("/icons/icon-192.png", "icons/icon-192.png", "image/png"),
                ("/fonts/figtree.woff2", "fonts/figtree.woff2", "font/woff2"),
                ("/app.js?v=3", "app.js", "text/javascript; charset=utf-8")):
            with self.subTest(path=path):
                status, headers, body = self.request("GET", path)
                self.assertEqual(status, 200)
                self.assertEqual(headers["Content-Type"], content_type)
                self.assertEqual(body, WEB_FILES[name].encode("utf-8"))
                self.assertEqual(headers["Cache-Control"], "no-cache")

    def test_head_and_etag(self):
        status, headers, body = self.request("HEAD", "/app.js")
        self.assertEqual((status, body), (200, b""))
        self.assertEqual(int(headers["Content-Length"]), len(WEB_FILES["app.js"].encode("utf-8")))
        status, _, body = self.request("GET", "/app.js", headers={"If-None-Match": headers["ETag"]})
        self.assertEqual((status, body), (304, b""))

    def test_only_the_allow_list_is_served(self):
        for path in ("/notes.txt", "/.hidden.js", "/other/extra.js", "/other/", "/icons/", "/icons",
                     "/APP.JS", "/app.js/", "/secret.txt", "/../secret.txt", "/..%2fsecret.txt",
                     "/%2e%2e/secret.txt", "/%2e%2e/", "/icons/../app.js", "/icons%2f..%2fapp.js",
                     "/icons/%2e%2e/%2e%2e/secret.txt", "/app.js%00", "/app.js%00.png", "/%ff",
                     "/web/app.js", "/decklab/config.json", "/C:/Windows/win.ini", "/index.html::$DATA"):
            with self.subTest(path=path):
                code, _, data = self.request("GET", path)
                self.assertIn(code, (400, 404))
                self.assertNotIn(b"private", data)
                self.assertNotIn(b"outside web/", data)

    def test_static_files_list(self):
        files = server.static_files(self.box.web)
        self.assertEqual(sorted(files), ["/", "/app.js", "/fonts/figtree.woff2", "/icons/icon-192.png", "/index.html",
                                         "/manifest.webmanifest", "/style.css"])
        self.assertEqual(server.static_files(self.box.root / "no-such-folder"), {})

    def test_the_page_takes_profile_and_theme_for_screenshots(self):
        for path in ("/?profile=matt", "/?profile=user1&theme=dark", "/index.html?theme=light&v=2",
                     "/?profile=matt&theme=light"):
            with self.subTest(path=path):
                status, _, body = self.request("GET", path)
                self.assertEqual((status, body), (200, WEB_FILES["index.html"].encode("utf-8")))
        for path in ("/app.js?profile=matt", "/style.css?theme=dark", "/?profile=matt&profile=user1",
                     "/?user=matt", "/?profile=<script>", "/?theme=", "/?profile=" + "a" * 41):
            with self.subTest(path=path):
                self.assertError(path, 400)

    def test_wrong_methods(self):
        code, headers, _ = self.request("POST", "/app.js", body=b"x")
        self.assertEqual((code, headers["Allow"]), (405, "GET, HEAD"))
        self.assertError("/app.js?x=1", 400)


class ApiEndpointTests(ServerTestCase):

    def test_status_and_profiles(self):
        status = self.get_json("/api/status")
        self.assertEqual(status["cards"]["ready"], True)
        self.assertEqual(status["updating"], False)
        self.assertEqual(self.get_json("/api/profiles"), api.profiles())
        self.assertEqual([p["id"] for p in self.get_json("/api/profiles")["profiles"]], ["matt", "user1"])

    def test_me_gives_the_tunnels_address_for_printed_links(self):
        # E8-S21: a box label's QR code opens the deck page at the tunnel's address, when there is one.
        from decklab.lib import config
        with mock.patch.object(config, "load", return_value={}):
            self.assertIsNone(self.get_json("/api/me")["address"])
        with mock.patch.object(config, "load", return_value={"tunnel": {"config": "x", "hostname": "decklab.example.com"}}):
            self.assertEqual(self.get_json("/api/me")["address"], "https://decklab.example.com")

    def test_status_says_how_the_database_is(self):
        # lib/dbstatus.py's snapshot, answered at once; its own tests cover who sees what.
        from decklab.lib import dbstatus
        with mock.patch.object(dbstatus, "_snapshot", None):
            self.assertEqual(self.get_json("/api/status")["database"], {"ok": None, "checking": True})
        snapshot = {"ok": False, "usable": False, "error": dbstatus.NOT_REACHABLE, "detail": "connection refused",
                    "pending_migrations": None, "last_backup": None, "backup_stale": None, "stale_hours": 36}
        with mock.patch.object(dbstatus, "_snapshot", snapshot), \
                mock.patch.object(dbstatus.venv, "reason", lambda: None):
            database = self.get_json("/api/status", headers={"X-Deck-Lab-Viewer": "user1"})["database"]
        # An admin's block also says what the database holds of the inventory (dbstatus.inventory_view).
        self.assertEqual(database, {"ok": False, "usable": False, "error": "not reachable", "pending_migrations": None,
                                    "last_backup": None, "backup_stale": None, "stale_hours": 36, "checks_warning": None,
                                    "venv": None,
                                    "inventory": {"imported": None, "imported_at": None,
                                                  "not_imported": False, "revision": None, "stale": True}})

    def test_a_member_gets_only_whether_the_database_can_be_used(self):
        # The Sandbox's config has no roles (everyone an admin): give it some for this test.
        from decklab.lib import dbstatus
        path = self.box.root / "config.json"
        saved = path.read_bytes()
        self.addCleanup(path.write_bytes, saved)
        path.write_text(json.dumps({"profiles": [
            {"id": "matt", "name": "Matt", "plays_as": "user", "role": "admin", "space": "home"},
            {"id": "user1", "name": "User1", "plays_as": "wife", "role": "member", "space": "home"}]}),
            encoding="utf-8")
        snapshot = {"ok": False, "usable": True, "error": dbstatus.MIGRATIONS_PENDING, "detail": "1 pending",
                    "pending_migrations": 1, "last_backup": None, "backup_stale": True, "stale_hours": 36}
        with mock.patch.object(dbstatus, "_snapshot", snapshot), \
                mock.patch.object(dbstatus.venv, "reason", lambda: None):
            member = self.get_json("/api/status", headers={"X-Deck-Lab-Viewer": "user1"})["database"]
            admin = self.get_json("/api/status", headers={"X-Deck-Lab-Viewer": "matt"})["database"]
        self.assertEqual(member, {"ok": True})          # a migration the stores don't need isn't news to her
        self.assertEqual((admin["ok"], admin["error"], admin["pending_migrations"]), (False, "migrations pending", 1))

    def test_wave_3s_routes_answer_501_until_built(self):
        # forge-trial/sim-wave3-contract.md sections 10.5 and 11.5: the base's stubs (V builds them).
        for path in ("/api/variant?test=" + "0" * 64,
                     "/api/variant/estimate?id=casual/gruul-ramp&against=field", "/api/variants?id=casual/gruul-ramp"):
            self.assertEqual(self.assertError(path, 501), api.variant_page.NOT_BUILT)
        for path in ("/api/variant/run", "/api/variant/stop", "/api/variant/more"):
            self.assertError(path, 501, "POST", b'{"profile": "user1"}', WRITE)

    def test_the_field_routes(self):
        # Package F built them (section 10.5): the deck must exist, and a write names its deck.
        self.assertIn("No deck", self.assertError("/api/field?id=casual/gruul-ramp&version=target", 404))
        for path in ("/api/field/run", "/api/field/stop"):
            self.assertIn("needs id", self.assertError(path, 400, "POST", b'{"profile": "user1"}', WRITE))
        self.assertError("/api/field/run", 405)

    def test_settings_round_trip(self):
        self.assertEqual(self.get_json("/api/profiles/user1/settings"), {"theme": "system", "matchup_games": "800", **W3_SETTINGS})
        saved = self.get_json("/api/profiles/user1/settings", method="PUT", body=b'{"theme": "light"}',
                              headers=WRITE)
        light = {"theme": "light", "matchup_games": "800", **W3_SETTINGS}
        self.assertEqual(saved, light)
        self.assertEqual(self.get_json("/api/profiles/user1/settings"), light)
        self.assertEqual(self.box.state.settings("user1"), {"theme": "light"})

    def test_settings_while_the_database_is_down(self):
        # The page's theme falls back to the device's: the answer is 503 with reason "database".
        before = self.box.state.settings("user1")
        self.box.state.down = True
        try:
            url = "/api/profiles/user1/settings"
            for method, body in (("GET", None), ("PUT", b'{"theme": "dark"}')):
                with self.subTest(method=method):
                    data = self.get_json(url, 503, method, body)
                    self.assertEqual(data["reason"], "database")
                    self.assertNotIn("Traceback", data["error"])
        finally:
            self.box.state.down = False
        self.assertEqual(self.box.state.settings("user1"), before)          # nothing was saved

    def test_settings_errors(self):
        url = "/api/profiles/matt/settings"
        self.assertIn("valid JSON", self.assertError(url, 400, "PUT", b"{nope"))
        self.assertIn("Unknown setting", self.assertError(url, 400, "PUT", b'{"font": "big"}'))
        self.assertError(url, 413, "PUT", b"{" + b" " * 5000 + b"}")
        self.assertError(url, 411, "PUT")                               # no Content-Length
        self.assertError("/api/profiles/nobody/settings", 404, "PUT", b'{"theme": "dark"}')
        self.assertError("/api/profiles/nobody/settings", 404)
        for path in ("/api/profiles/..%2fmatt/settings", "/api/profiles/../settings",
                     "/api/profiles/%2e%2e/settings", "/api/profiles/MATT/settings"):
            with self.subTest(path=path):
                self.assertIn(self.request("GET", path)[0], (400, 404))
        self.assertError(url + "?theme=dark", 400)
        code, headers, _ = self.request("POST", url, body=b'{"theme": "dark"}')
        self.assertEqual((code, headers["Allow"]), (405, "GET, HEAD, PUT"))
        self.assertError(url, 405, "DELETE")
        self.assertEqual(self.box.state.settings("matt"), {})

    def test_decks(self):
        index = self.get_json("/api/decks")
        self.assertEqual(index, json.loads(json.dumps(api.decks_index())))
        self.assertEqual(len(index["halves"]), 3)
        self.assertError("/api/decks?player=user", 400)
        self.assertError("/api/decks", 405, "PUT", b"{}")

    def test_omit_leaves_out_the_matchups(self):
        # The deck page asks for its matchups (the answer's slowest part) only when its Matchups tab opens:
        # omit=matchups leaves the key out (not None, which says they couldn't be loaded) and never runs them.
        from decklab.lib.api import deck_page
        with mock.patch.object(deck_page, "_deck_matchups", side_effect=AssertionError("asked")) as asked:
            view = self.get_json("/api/deck?id=casual/gruul-test&omit=matchups")
            self.assertNotIn("matchups", view)
            self.assertEqual(view["summary"]["id"], "casual/gruul-test")
            self.assertIn("owned", view)
            asked.assert_not_called()
        with mock.patch.object(deck_page, "_deck_matchups", return_value={"results": []}) as asked:
            self.assertEqual(self.get_json("/api/deck?id=casual/gruul-test")["matchups"], {"results": []})
            self.assertEqual(api.deck_view("casual/gruul-test", omit=frozenset())["matchups"], {"results": []})
            self.assertEqual(asked.call_count, 2)
        for query in ("omit=stats", "omit=matchups,owned", "omit=matchups&omit=matchups"):
            with self.subTest(query=query):
                self.assertError("/api/deck?id=casual/gruul-test&" + query, 400)
        self.assertEqual(deck_page.parse_omit(" matchups, "), frozenset({"matchups"}))
        self.assertEqual(deck_page.parse_omit(""), frozenset())

    def test_deck(self):
        view = self.get_json("/api/deck?id=casual/gruul-test&version=owned")
        self.assertEqual((view["summary"]["id"], view["version"]), ("casual/gruul-test", "owned"))
        view = self.get_json("/api/deck?id=casual%2Fgruul-test")
        self.assertEqual(view["version"], "target")
        self.assertEqual(view["sections"]["Deck"][0]["card"]["img"], "/img/fdn/227/normal")
        # A pairing id's "+", encoded or not (a bare "+" in a query means a space).
        for query in ("id=pairing/cats+elves", "id=pairing%2Fcats%2Belves", "id=pairing/elves%2Bcats"):
            with self.subTest(query=query):
                self.assertEqual(self.get_json("/api/deck?" + query)["summary"]["id"], "pairing/elves+cats")

    def test_deck_errors(self):
        for query, status in (("", 400), ("id=", 400), ("id=../../CLAUDE", 400),
                              ("id=casual/../../CLAUDE", 400), ("id=..%2F..%2FCLAUDE.md", 400),
                              ("id=casual%5C..%5C..%5CCLAUDE", 400), ("id=casual/nope", 404),
                              ("id=casual/gruul-test&version=foil", 400),
                              ("id=commander/elf-commander&version=owned", 404),
                              ("id=casual/gruul-test&id=casual/broken", 400),
                              ("id=casual/gruul-test&extra=1", 400), ("id=%ff", 400),
                              ("id=casual/broken", 500)):
            with self.subTest(query=query):
                self.assertError("/api/deck?" + query, status)

    def test_search(self):
        self.assertEqual(self.get_json("/api/cards/search?q=llan&limit=5"),
                         {"names": ["Llanowar Elves"], "did_you_mean": []})
        self.assertEqual(self.get_json("/api/cards/search?q=fire+%2F%2F"),
                         {"names": ["Fire // Ice"], "did_you_mean": []})
        self.assertEqual(self.get_json("/api/cards/search"), {"names": [], "did_you_mean": []})
        self.assertEqual(self.get_json("/api/cards/search?q=llan+elv"),
                         {"names": ["Llanowar Elves"], "did_you_mean": []})
        self.assertEqual(self.get_json("/api/cards/search?q=black+lotsu")["did_you_mean"], ["Black Lotus"])
        self.assertError("/api/cards/search?q=llan&limit=500", 400)
        self.assertError("/api/cards/search?text=llan", 400)
        detail = self.get_json("/api/cards/search?q=llan&limit=5&detail=1")
        self.assertEqual([c["name"] for c in detail["cards"]], ["Llanowar Elves"])
        self.assertError("/api/cards/search?q=llan&detail=2", 400)

    def test_unknown_api_paths(self):
        for path in ("/api", "/api/", "/api/nope", "/api/decks/", "/api/deck/casual/gruul-test",
                     "/api/profiles/matt", "/api/profiles/matt/settings/x"):
            with self.subTest(path=path):
                self.assertError(path, 404)

    def test_503_until_the_card_index_exists(self):
        with self.box.no_index(), mock.patch.dict(api.carddata.UPDATE, running=True):
            self.assertEqual(self.get_json("/api/status")["updating"], True)
            self.assertEqual(self.get_json("/api/status")["cards"]["ready"], False)
            for path in ("/api/decks", "/api/deck?id=casual/gruul-test", "/api/goldfish?id=casual/gruul-test",
                         "/api/cards/search?q=llan", "/img/fdn/227/small"):
                with self.subTest(path=path):
                    self.assertIn("still being downloaded", self.assertError(path, 503))
            self.get_json("/api/profiles")

    def test_a_crash_is_a_plain_500_and_the_traceback_is_logged(self):
        with mock.patch.object(api, "decks_index", side_effect=RuntimeError("secret detail")):
            message = self.assertError("/api/decks", 500)
        self.assertNotIn("secret detail", message)
        self.assertTrue(any("secret detail" in line and "Traceback" in line for line in self.log))


class GoldfishEndpointTests(ServerTestCase):
    """GET /api/goldfish with the Sandbox's stand-in simulation."""

    def setUp(self):
        runner = mock.patch.object(api.practice, "JOBS", api._job_runner())
        runner.start()
        self.addCleanup(runner.stop)
        self.addCleanup(self.box.wait_for_jobs)
        self.fake = self.box.goldfish
        self.fake.saved.clear()
        self.fake.runs.clear()

    def test_202_while_running_then_200_with_the_result(self):
        self.fake.gate.clear()
        data = self.get_json("/api/goldfish?id=casual/gruul-test&version=target", 202)
        self.assertEqual(data["status"], "running")
        self.assertEqual(self.get_json("/api/goldfish?id=casual/gruul-test", 202)["status"], "running")
        self.box.wait_for_jobs()
        data = self.get_json("/api/goldfish?id=casual/gruul-test")
        self.assertEqual((data["status"], data["result"]["kind"], data["result"]["cached"]),
                         ("done", "constructed", True))
        self.assertEqual(len(self.fake.runs), 1)

    def test_a_pairing_id_and_the_owned_list(self):
        for query in ("id=pairing/cats+elves", "id=pairing%2Felves%2Bcats", "id=casual/gruul-test&version=owned"):
            with self.subTest(query=query):
                code, _, body = self.request("GET", "/api/goldfish?" + query)
                self.assertIn(code, (200, 202), body)
        self.box.wait_for_jobs()
        self.assertEqual(len(self.fake.runs), 2)        # both pairing ids are one list

    def test_a_failed_run_and_retry(self):
        self.fake.error = RuntimeError("worker crashed")
        self.get_json("/api/goldfish?id=casual/gruul-test", 202)
        self.box.wait_for_jobs()
        data = self.get_json("/api/goldfish?id=casual/gruul-test")
        self.assertEqual(data, {"status": "error", "error": api.RUN_FAILED})
        self.fake.error = None
        self.get_json("/api/goldfish?id=casual/gruul-test&retry=1", 202)
        self.box.wait_for_jobs()
        self.assertEqual(self.get_json("/api/goldfish?id=casual/gruul-test")["status"], "done")

    def test_errors(self):
        for query, status in (("", 400), ("id=../../CLAUDE", 400), ("id=casual/nope", 404),
                              ("id=casual/gruul-test&version=foil", 400),
                              ("id=casual/gruul-test&retry=yes", 400),
                              ("id=casual/gruul-test&games=5", 400),
                              ("id=casual/gruul-test&id=casual/broken", 400),
                              ("id=commander/elf-commander&version=owned", 404),
                              ("id=casual/broken", 500)):
            with self.subTest(query=query):
                self.assertError("/api/goldfish?" + query, status)
        self.assertError("/api/goldfish?id=casual/gruul-test", 405, "POST", b"{}")
        self.assertError("/api/goldfish/casual/gruul-test", 404)
        self.assertEqual(self.fake.runs, [])


class MatchupEndpointTests(ServerTestCase):
    """The Forge matchup endpoints with the Sandbox's stand-in forge module."""

    A_B = "a=casual/gruul-test&av=target&b=casual/gruul-test&bv=owned"
    RUN = {"profile": "matt", "a": "casual/gruul-test", "av": "target", "b": "casual/gruul-test", "bv": "owned",
           "mode": "fixed"}     # wave 3: without a mode or games, a run plays the profile's matchup_mode ("assess")

    def setUp(self):
        runner = mock.patch.object(api.forge_runs, "FORGE_JOBS", api._forge_runner())
        runner.start()
        self.addCleanup(runner.stop)
        self.addCleanup(self.box.wait_for_jobs)
        self.fake = self.box.forge
        self.fake.saved.clear()
        self.fake.runs.clear()

    def post(self, path, data, status):
        return self.get_json(path, status, "POST", json.dumps(data).encode("utf-8"), WRITE)

    def test_play_then_202_while_running_then_200(self):
        data = self.get_json("/api/matchup?" + self.A_B)
        self.assertEqual((data["status"], data["result"]), ("none", None))
        self.fake.gate.clear()
        self.fake.started.clear()
        data = self.post("/api/matchup/run", dict(self.RUN, games=400), 202)
        self.assertIn(data["status"], ("queued", "running"))
        self.assertTrue(self.fake.started.wait(5))
        data = self.get_json("/api/matchup?" + self.A_B, 202)
        self.assertEqual((data["status"], data["job"]["total"], data["job"]["by"]), ("running", 400, "Matt"))
        self.assertEqual(self.get_json("/api/matchup?key=" + data["key"], 202)["status"], "running")
        self.assertEqual(len(self.get_json("/api/matchups")["running"]), 1)
        self.box.wait_for_jobs()
        data = self.get_json("/api/matchup?" + self.A_B + "&profile=user1")
        self.assertEqual((data["status"], data["result"]["games"], data["default_games"]), ("done", 400, 800))
        self.assertEqual(self.get_json("/api/matchups")["results"][0]["key"], data["key"])
        self.assertEqual(self.get_json("/api/matchup?key=" + data["key"])["status"], "done")

    def test_stop(self):
        self.fake.gate.clear()
        self.fake.started.clear()
        key = self.post("/api/matchup/run", self.RUN, 202)["key"]
        self.assertTrue(self.fake.started.wait(5))
        data = self.post("/api/matchup/stop", {"profile": "user1", "key": key}, 200)
        self.assertEqual((data["status"], data["notice"]), ("done", "Stopped by User1 after 200 of 800 games."))
        # Nothing playing: a no-op.
        self.assertEqual(self.post("/api/matchup/stop", {"profile": "matt", "key": key}, 200)["notice"],
                         data["notice"])

    def test_a_pairing_id_with_a_plus_typed_as_a_space(self):
        for query in ("a=pairing/cats+elves&b=pairing/cats%2Bgoblins", "a=pairing%2Felves%2Bcats&b=pairing/goblins+cats"):
            with self.subTest(query=query):
                data = self.get_json("/api/matchup?" + query)
                self.assertEqual([s["id"] for s in data["sides"]], ["pairing/elves+cats", "pairing/cats+goblins"])

    def test_errors(self):
        for query, status in (("", 400), ("a=casual/gruul-test", 400), ("a=../../CLAUDE&b=casual/gruul-test", 400),
                              ("a=casual/nope&b=casual/gruul-test", 404),
                              ("a=casual/gruul-test&b=commander/elf-commander", 400),
                              ("a=product/fdn-beginner-box/cats&b=casual/gruul-test", 400),
                              ("a=casual/gruul-test&b=casual/gruul-test&games=800", 400),
                              ("a=casual/gruul-test&a=casual/broken&b=casual/gruul-test", 400),
                              ("key=nope", 400), ("key=" + "0" * 64, 404),
                              (self.A_B + "&profile=nobody", 404)):
            with self.subTest(query=query):
                self.assertError("/api/matchup?" + query, status)
        self.assertError("/api/matchups?x=1", 400)
        self.assertError("/api/matchups?running=yes", 400)
        self.assertEqual(set(self.get_json("/api/matchups?running=1")), {"running", "forge"})   # the top bar's pill
        self.assertError("/api/matchups", 405, "POST", b"{}")
        self.assertError("/api/matchup/run?x=1", 400, "POST", b"{}")
        for method, path, allow in (("GET", "/api/matchup/run", "POST"), ("GET", "/api/matchup/stop", "POST"),
                                    ("POST", "/api/matchup?" + self.A_B, "GET, HEAD")):
            with self.subTest(method=method, path=path):
                code, headers, _ = self.request(method, path, b"{}")
                self.assertEqual((code, headers["Allow"]), (405, allow))
        self.assertIn("games must be one of", self.post("/api/matchup/run", dict(self.RUN, games=100), 400)["error"])
        self.assertIn("Choose who you are", self.post("/api/matchup/run", dict(self.RUN, profile="nobody"), 403)["error"])
        self.assertEqual(self.fake.runs, [])

    def test_both_posts_need_the_write_header_and_json(self):
        for path, data in (("/api/matchup/run", self.RUN), ("/api/matchup/stop", {"profile": "matt", "key": "0" * 64})):
            body = json.dumps(data).encode()
            for headers, status in (({}, 403), ({"Content-Type": "application/json"}, 403),
                                    ({"Content-Type": "text/plain", "X-Deck-Lab": "1"}, 415),
                                    (dict(WRITE, Origin="http://evil.example"), 403)):
                with self.subTest(path=path, headers=headers):
                    code, answer_headers, answer = self.request("POST", path, body, headers)
                    self.assertEqual(code, status, answer[:200])
                    self.assertEqual(answer_headers["Connection"], "close")
            self.assertError(path, 413, "POST", b"{" + b" " * 5000 + b"}", WRITE)
        self.assertEqual(self.fake.runs, [])

    def test_forge_not_ready_and_no_matchup_code(self):
        self.fake.ready = False
        try:
            self.assertIn("isn't installed", self.post("/api/matchup/run", self.RUN, 503)["error"])
            self.assertEqual(self.get_json("/api/matchups")["forge"]["ready"], False)
        finally:
            self.fake.ready = True
        with mock.patch.dict(sys.modules, {"decklab.lib.forge": None}):
            self.assertIn("aren't available", self.assertError("/api/matchups", 500))
            view = self.get_json("/api/deck?id=casual/gruul-test")
            self.assertIsNone(view["matchups"])


class ImageEndpointTests(ServerTestCase):

    def test_images(self):
        status, headers, body = self.request("GET", "/img/fdn/227/small")
        self.assertEqual((status, body), (200, b"\xff\xd8jpeg"))
        self.assertEqual(headers["Content-Type"], "image/jpeg")
        self.assertEqual(headers["Cache-Control"], "public, max-age=604800")
        self.assertEqual(self.request("GET", "/img/pdmu/1%E2%98%85/normal")[0], 200)
        self.assertEqual(self.request("HEAD", "/img/fdn/227/small")[:3:2], (200, b""))
        # The large picture (the card viewer's) and the art alone (the library's covers), cached the same way.
        for size in ("large", "art_crop"):
            status, headers, body = self.request("GET", f"/img/fdn/227/{size}")
            self.assertEqual((status, body, headers["Content-Type"]), (200, b"\xff\xd8jpeg", "image/jpeg"))
            self.assertEqual(headers["Cache-Control"], "public, max-age=604800")

    def test_bad_image_paths(self):
        for path in ("/img/fdn/99999/small", "/img/fdn/227/huge", "/img/FDN/227/small", "/img/../x",
                     "/img/fdn/..%2f..%2fx/small", "/img/fdn/227", "/img/fdn/227/small/x",
                     "/img/%2e%2e/227/small", "/img/fdn/%2e%2e/small", "/img/fdn/227%5c..%5cx/small"):
            with self.subTest(path=path):
                self.assertError(path, 404)
        self.assertError("/img/fdn/227/small?size=big", 400)
        self.assertError("/img/fdn/227/small", 405, "PUT", b"x")


class AccessoryImageTests(ServerTestCase):
    """/accessory-img/: a picture accessories.csv names, or a staged one."""

    def setUp(self):
        from decklab.lib import accessories, accessory_fetch
        from decklab.tests.test_accessory_fetch import jpeg, png
        self.images = self.box.magic / "accessories" / "images"
        self.images.mkdir(parents=True, exist_ok=True)
        staged = self.box.data / "accessories" / "staged"
        for target, name, value in ((accessories, "PATH", self.box.magic / "accessories.csv"),
                                    (accessories, "IMAGES", self.images),
                                    (accessory_fetch, "STAGED", staged)):
            patcher = mock.patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.png = png()
        (self.images / "dragon-shield-matte-black.png").write_bytes(self.png)
        (self.images / "orphan.png").write_bytes(self.png)
        (self.images / "fake.png").write_bytes(b"<svg xmlns='http://www.w3.org/2000/svg'/>")
        (self.box.magic / "accessories.csv").write_text(
            ",".join(accessories.FIELDS) + "\n"
            "dragon-shield-matte-black,sleeves,shared,Dragon Shield,Matte,black,100,,dragon-shield-matte-black.png,,,,\n"
            "fake,sleeves,shared,,Fake,,1,,fake.png,,,,\n", encoding="utf-8")
        self.jpeg = jpeg()
        self.token = accessory_fetch.stage(self.jpeg, "jpg")
        self.addCleanup(shutil.rmtree, self.box.magic / "accessories", True)
        self.addCleanup(shutil.rmtree, staged, True)
        self.addCleanup((self.box.magic / "accessories.csv").unlink, missing_ok=True)

    def url(self, name="dragon-shield-matte-black.png", data=None):
        """The current picture-address epoch, distinct from the old cacheable URL."""
        from decklab.lib import accessories
        from decklab.lib.inventory.model import ImageMeta
        return f"/accessory-img/{name}?v={accessories.image_version(ImageMeta.of(name, self.png if data is None else data))}"

    def test_a_listed_picture(self):
        status, headers, body = self.request("GET", self.url())
        self.assertEqual((status, body), (200, self.png))
        self.assertEqual(headers["Content-Type"], "image/png")
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
        # Private: whether a picture may be seen depends on who asks, so no shared cache may keep it.
        self.assertEqual(headers["Cache-Control"], "private, no-cache")
        self.assertIn("ETag", headers)
        self.assertEqual(self.request("HEAD", self.url())[:3:2], (200, b""))

    def test_public_picture_revalidation_checks_permission_before_returning_304(self):
        from decklab.lib.api import guard
        csv_path = self.box.magic / "accessories.csv"
        csv_path.write_text(csv_path.read_text(encoding="utf-8").replace(
            ",sleeves,shared,Dragon", ",sleeves,user1,Dragon"), encoding="utf-8")
        headers = {"X-Deck-Lab-Viewer": "matt"}
        with mock.patch.object(guard, "public_owners", return_value={"user1"}):
            status, reply, body = self.request("GET", self.url(), headers=headers)
            self.assertEqual((status, body), (200, self.png))
            headers["If-None-Match"] = reply["ETag"]
            status, reply, body = self.request("GET", self.url(), headers=headers)
            self.assertEqual((status, body, reply["Cache-Control"]), (304, b"", "private, no-cache"))
        # The same cache validator must not turn a now-private image into a 304.
        self.assertEqual(self.request("GET", self.url(), headers=headers)[0], 404)

    def test_v_is_required_and_must_be_the_pictures(self):
        # Without v, or with another picture's, an address names no picture (the edge-cache rule).
        for path in ("/accessory-img/dragon-shield-matte-black.png",
                     "/accessory-img/dragon-shield-matte-black.png?v=0123abcd"):
            with self.subTest(path=path):
                self.assertError(path, 404)
        self.assertError("/accessory-img/dragon-shield-matte-black.png?v=0123abc", 400)

    def test_the_home_networks_viewer_header_picks_whose_pictures(self):
        csv_path = self.box.magic / "accessories.csv"
        csv_path.write_text(csv_path.read_text(encoding="utf-8").replace(",sleeves,shared,Dragon",
                                                                          ",sleeves,user1,Dragon"), encoding="utf-8")
        url = self.url()
        self.assertEqual(self.request("GET", url)[0], 200)                                     # nobody named
        self.assertEqual(self.request("GET", url, headers={"X-Deck-Lab-Viewer": "user1"})[0], 200)
        self.assertEqual(self.request("GET", url, headers={"X-Deck-Lab-Viewer": "matt"})[0], 404)
        status, _, body = self.request("GET", "/api/accessories", headers={"X-Deck-Lab-Viewer": "matt"})
        self.assertEqual(status, 200)
        self.assertEqual([i["id"] for i in json.loads(body)["items"]], ["fake"])

    def test_an_img_names_its_viewer_in_the_address(self):
        # E8-S16: an <img> sends no header, so on the home network ?viewer= (or &viewer=) names who's
        # looking: User2 (his own space) gets 403 for every picture, User1 only hers and the shared ones,
        # nobody named everything. A header, when sent, wins over it.
        listed = [{"id": "matt", "name": "Matt", "plays_as": "user", "role": "admin", "space": "home"},
                  {"id": "user1", "name": "User1", "plays_as": "wife", "role": "member", "space": "home"},
                  {"id": "user2", "name": "User2", "plays_as": None, "role": "member", "space": "user2"}]
        patcher = mock.patch.object(api.settings, "_config_profiles", lambda emails=False: listed)
        patcher.start()
        self.addCleanup(patcher.stop)
        csv_path = self.box.magic / "accessories.csv"
        csv_path.write_text(csv_path.read_text(encoding="utf-8").replace(",sleeves,shared,Dragon",
                                                                          ",sleeves,user1,Dragon"), encoding="utf-8")
        user1s, staged = self.url(), f"/accessory-img/staged/{self.token}.jpg"
        for path, viewer, status in ((user1s, None, 200), (user1s, "user1", 200), (user1s, "matt", 404),
                                     (user1s, "user2", 403), (staged, None, 200), (staged, "user1", 200),
                                     (staged, "matt", 200), (staged, "user2", 403)):
            with self.subTest(path=path, viewer=viewer):
                url = path if viewer is None else f"{path}{'&' if '?' in path else '?'}viewer={viewer}"
                got, _, body = self.request("GET", url)
                self.assertEqual(got, status, body[:200])
        status, _, body = self.request("GET", "/accessory-img/missing.png?v=0123abcd&viewer=user2")
        # Before the name is looked at; outside /api/ the refusal is a short page (Refused).
        self.assertEqual(status, 403)
        self.assertIn(access.SIGN_IN_OUTSIDE.encode(), body)
        # The header wins: User1's header with Matt's address sees hers, Matt's header with hers doesn't.
        self.assertEqual(self.request("GET", user1s + "&viewer=matt", headers={"X-Deck-Lab-Viewer": "user1"})[0], 200)
        self.assertEqual(self.request("GET", user1s + "&viewer=user1", headers={"X-Deck-Lab-Viewer": "matt"})[0], 404)
        self.assertEqual(self.request("GET", staged + "?viewer=user1",
                                      headers={"X-Deck-Lab-Viewer": "user2"})[0], 403)
        self.assertError(user1s + "&viewer=user1&viewer=matt", 400)
        self.assertError(staged + "?viewer=user1&v=1", 400)

    def test_a_staged_picture(self):
        status, headers, body = self.request("GET", f"/accessory-img/staged/{self.token}.jpg")
        self.assertEqual((status, body), (200, self.jpeg))
        self.assertEqual(headers["Content-Type"], "image/jpeg")
        self.assertEqual(headers["Cache-Control"], "no-store")

    def test_refusals(self):
        for path in ("/accessory-img/orphan.png", "/accessory-img/fake.png", "/accessory-img/missing.png",
                     self.url("orphan.png"), self.url("fake.png", b"<svg xmlns='http://www.w3.org/2000/svg'/>"),
                     "/accessory-img/dragon-shield-matte-black.gif", "/accessory-img/dragon-shield-matte-black.svg",
                     "/accessory-img/..", "/accessory-img/..%2faccessories.csv",
                     "/accessory-img/%2e%2e%2f%2e%2e%2fconfig.json", "/accessory-img/x%2fdragon-shield-matte-black.png",
                     "/accessory-img/Dragon-Shield-Matte-Black.png", "/accessory-img/", "/accessory-img",
                     f"/accessory-img/staged/{self.token}.png", f"/accessory-img/staged/{'0' * 32}.jpg",
                     f"/accessory-img/staged/..%2f{self.token}.jpg", "/accessory-img/other/x.png",
                     "/accessory-img/staged/x/y.png"):
            with self.subTest(path=path):
                self.assertError(path, 404)
        for path in ("/accessory-img/dragon-shield-matte-black.png?size=big",
                     "/accessory-img/dragon-shield-matte-black.png?v=1&v=2",
                     "/accessory-img/dragon-shield-matte-black.png?v=<script>",
                     f"/accessory-img/staged/{self.token}.jpg?v=1"):
            with self.subTest(path=path):
                self.assertError(path, 400)
        for method in ("PUT", "POST", "DELETE"):
            with self.subTest(method=method):
                self.assertError("/accessory-img/dragon-shield-matte-black.png", 405, method, b"x")


class ProtocolTests(ServerTestCase):

    def test_every_answer_is_marked_as_deck_labs(self):
        # The off page's Worker (decklab/cloudflare/) replaces only 5xx answers without this header:
        # Deck Lab's own (the database down, the card data loading) must always carry it.
        name, value = server_http.ORIGIN_HEADER
        self.assertEqual((name, value), ("X-Deck-Lab-Origin", "1"))
        status, headers, _ = self.request("GET", "/api/status")
        self.assertEqual((status, headers[name]), (200, value))
        status, headers, body = self.request("HEAD", "/app.js")
        self.assertEqual((status, body, headers[name]), (200, b"", value))
        status, headers, _ = self.request("GET", "/app.js", headers={"If-None-Match": headers["ETag"]})
        self.assertEqual((status, headers[name]), (304, value))
        status, headers, _ = self.request("GET", "/?profile=<script>")
        self.assertEqual((status, headers[name]), (400, value))
        status, headers, _ = self.request("GET", "/api/nope")
        self.assertEqual((status, headers[name]), (404, value))
        # http.server's own errors (send_error): an unknown method, two Host headers.
        for raw in (b"FOO / HTTP/1.1\r\nHost: localhost\r\n\r\n",
                    b"GET /api/status HTTP/1.1\r\nHost: 127.0.0.1\r\nHost: evil.example\r\n"
                    b"Connection: close\r\n\r\n"):
            with self.subTest(raw=raw[:20]):
                head = self.raw(raw).partition(b"\r\n\r\n")[0]
                self.assertIn(f"\r\n{name}: {value}".encode(), head)
        self.box.state.down = True
        try:
            status, headers, body = self.request("GET", "/api/profiles/user1/settings")
        finally:
            self.box.state.down = False
        self.assertEqual((status, json.loads(body)["reason"], headers[name]), (503, "database", value))

    def test_keep_alive(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            for path in ("/api/status", "/api/nope", "/app.js", "/api/profiles"):
                self.request("GET", path, conn=conn)
            status, _, body = self.request("GET", "/api/profiles", conn=conn)
            self.assertEqual(status, 200)
            self.assertIn(b"User1", body)
        finally:
            conn.close()

    def test_bad_requests_get_json_too(self):
        answer = self.raw(b"FOO / HTTP/1.1\r\nHost: localhost\r\n\r\n")
        head, _, body = answer.partition(b"\r\n\r\n")
        self.assertTrue(head.startswith(b"HTTP/1.1 501 "), head)
        self.assertIn(b"Content-Type: application/json", head)
        self.assertEqual(list(json.loads(body)), ["error"])
        # Before the request line is understood, http.server answers the
        # HTTP/0.9 way: the body alone.
        for request in (b"GET / HTTP/9.9\r\n\r\n", b"nonsense\r\n\r\n", b"GET /\r\n\r\n"):
            with self.subTest(request=request):
                answer = self.raw(request)
                if answer.startswith(b"HTTP/"):
                    answer = answer.partition(b"\r\n\r\n")[2]
                self.assertEqual(list(json.loads(answer)), ["error"])

    def test_two_host_headers(self):
        answer = self.raw(b"GET /api/status HTTP/1.1\r\nHost: 127.0.0.1\r\nHost: evil.example\r\n"
                          b"Connection: close\r\n\r\n")
        self.assertTrue(answer.startswith(b"HTTP/1.1 400 "), answer[:100])

    def test_host_header(self):
        self.assertError("/api/status", 400, headers={"Host": "evil.example.com"})
        self.assertError("/api/status", 400, headers={"Host": "evil.example.com:8642"})
        for host in ("localhost:8642", "127.0.0.1", f"{socket.gethostname()}:8642",
                     socket.gethostname().upper() + ".local", "[::1]:8642", "192.168.1.20:8642"):
            with self.subTest(host=host):
                self.get_json("/api/status", headers={"Host": host})

    def test_host_allowed(self):
        pc = socket.gethostname()
        self.assertTrue(server.host_allowed(None))
        self.assertTrue(server.host_allowed("10.0.0.5"))
        self.assertTrue(server.host_allowed(f"{pc.lower()}.lan:8642"))
        self.assertTrue(server.host_allowed(f"{pc.upper()}.home.arpa."))
        self.assertTrue(server.host_allowed("decklab.home:8642", extra=["DeckLab.home"]))
        self.assertFalse(server.host_allowed("decklab.home:8642"))
        self.assertFalse(server.host_allowed("attacker.example"))
        # A rebinding domain that starts with the PC's name isn't the PC.
        self.assertFalse(server.host_allowed(f"{pc}.attacker.example"))
        self.assertFalse(server.host_allowed(f"{pc}x.local"))

    def test_errors_keep_the_connection_unless_a_body_is_left_unread(self):
        url = "/api/profiles/matt/settings"
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            status, headers, _ = self.request("PUT", url, body=b'{"theme": 7}', conn=conn)
            self.assertEqual((status, headers["Connection"]), (400, None))
            status, headers, _ = self.request("PUT", url, body=b"x" * 5000, conn=conn)
            self.assertEqual((status, headers["Connection"]), (413, "close"))
        finally:
            conn.close()

    def test_http_0_9_is_refused_without_a_traceback(self):
        # An HTTP/0.9 request has no headers at all; it used to crash the Host check.
        before = len(self.log)
        answer = self.raw(b"GET /api/status\r\n")
        self.assertEqual(json.loads(answer), {"error": "HTTP/0.9 isn't supported"})
        self.assertFalse(any("Traceback" in line for line in self.log[before:]), self.log[before:])

    def test_content_length_must_be_one_plain_number(self):
        before = len(self.log)
        saved = api.get_settings("matt")
        head = (b"PUT /api/profiles/matt/settings HTTP/1.1\r\nHost: 127.0.0.1\r\n"
                b"Connection: close\r\nX-Deck-Lab: 1\r\nContent-Type: application/json\r\n")
        # "²" (superscript 2) passes str.isdigit() but isn't a number.
        answer = self.raw(head + "Content-Length: ²\r\n\r\n{}".encode("latin-1"))
        self.assertTrue(answer.startswith(b"HTTP/1.1 400 "), answer[:100])
        self.assertIn(b"Bad Content-Length", answer)
        answer = self.raw(head + b'Content-Length: 16\r\nContent-length: 0\r\n\r\n{"theme":"dark"}')
        self.assertTrue(answer.startswith(b"HTTP/1.1 400 "), answer[:100])
        self.assertIn(b"More than one Content-Length", answer)
        self.assertEqual(api.get_settings("matt"), saved)            # nothing was saved
        self.assertFalse(any("Traceback" in line for line in self.log[before:]), self.log[before:])

    def test_an_unread_body_closes_the_connection(self):
        # A GET with a body: the body mustn't be read as a second request.
        smuggled = b"GET /api/status HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n"
        answer = self.raw(b"GET /api/profiles HTTP/1.1\r\nHost: 127.0.0.1\r\n"
                          b"Content-Length: %d\r\n\r\n" % len(smuggled) + smuggled)
        self.assertEqual(answer.count(b"HTTP/1.1 "), 1, answer)
        self.assertIn(b"Connection: close", answer)
        self.assertIn(b"User1", answer)

    def test_control_characters_in_the_method_are_escaped_in_the_log(self):
        before = len(self.log)
        answer = self.raw(b"G\x1b[31mET /api/status HTTP/1.1\r\nHost: 127.0.0.1\r\n"
                          b"Connection: close\r\n\r\n")
        self.assertTrue(answer.startswith(b"HTTP/1.1 501 "), answer[:100])
        lines = self.log[before:]
        self.assertTrue(lines)
        self.assertFalse(any("\x1b" in line for line in lines), lines)
        self.assertTrue(any("G\\x1b[31mET /api/status 501" in line for line in lines), lines)

    def test_server_header(self):
        self.assertEqual(self.request("GET", "/api/status")[1]["Server"], "DeckLab")

    def test_one_log_line_per_request(self):
        before = len(self.log)
        self.request("GET", "/api/profiles")
        self.request("GET", "/api/nope?x=%0d%0aFAKE")
        # A request's line is written once its answer has gone, so it may come a moment after the
        # client has it; and other threads (the card data's) may log meanwhile.
        deadline = time.monotonic() + 5
        while True:
            lines = [line for line in self.log[before:] if " GET /api/" in line]
            if len(lines) >= 2 or time.monotonic() > deadline:
                break
            time.sleep(0.01)
        self.assertEqual(len(lines), 2, self.log[before:])
        self.assertRegex(lines[0], r" 127\.0\.0\.1 GET /api/profiles 200 \d+ ms$")
        self.assertRegex(lines[1], r" GET /api/nope\?x=%0d%0aFAKE 404 \d+ ms$")


class WriteTests(ServerTestCase):
    """The editor's endpoints, and the check every POST and PUT goes through."""

    def post(self, path, data, status=200, headers=None, profile="matt"):
        body = json.dumps(dict(data, profile=profile) if profile else data).encode("utf-8")
        return self.get_json(path, status, "POST", body, headers)

    def settings(self):
        return self.get_json("/api/profiles/user1/settings")

    def test_a_write_needs_the_header_and_json(self):
        url, body = "/api/deck/check", json.dumps({"profile": "matt", "kind": "casual"}).encode()
        for headers, status in (({}, 403),
                                ({"Content-Type": "application/json"}, 403),
                                ({"Content-Type": "application/json", "X-Deck-Lab": "2"}, 403),
                                ({"Content-Type": "text/plain", "X-Deck-Lab": "1"}, 415),
                                ({"X-Deck-Lab": "1"}, 415),
                                ({"Content-Type": "application/x-www-form-urlencoded", "X-Deck-Lab": "1"}, 415),
                                ({"Content-Type": "application/json; charset=utf-8", "X-Deck-Lab": "1"}, 200)):
            with self.subTest(headers=headers):
                code, answer_headers, data = self.request("POST", url, body, headers)
                self.assertEqual(code, status, data[:200])
                if status != 200:
                    self.assertEqual(list(json.loads(data)), ["error"])
                    self.assertEqual(answer_headers["Connection"], "close")     # the body was never read
        # The existing settings PUT is protected the same way.
        before = self.settings()
        for headers, status in (({"Content-Type": "application/json"}, 403), ({"X-Deck-Lab": "1"}, 415)):
            with self.subTest(settings=headers):
                self.assertError("/api/profiles/user1/settings", status, "PUT", b'{"theme": "dark"}', headers)
        self.assertEqual(self.settings(), before)

    def test_another_site_is_refused(self):
        url, body = "/api/deck/check", json.dumps({"profile": "matt", "kind": "casual"}).encode()
        own = f"http://127.0.0.1:{self.port}"
        for extra, status in (({"Origin": "http://evil.example"}, 403),
                              ({"Origin": "null"}, 403),
                              ({"Origin": f"http://127.0.0.1:{self.port + 1}"}, 403),
                              ({"Origin": own, "Sec-Fetch-Site": "cross-site"}, 403),
                              ({"Sec-Fetch-Site": "same-site"}, 403),
                              ({"Origin": own}, 200),
                              ({"Origin": own.upper().replace("HTTP", "http"), "Sec-Fetch-Site": "same-origin"}, 200),
                              ({"Sec-Fetch-Site": "none"}, 200)):
            with self.subTest(headers=extra):
                code, _, data = self.request("POST", url, body, dict(WRITE, **extra))
                self.assertEqual(code, status, data[:200])
        # Two Origin headers can't be checked, so they're refused.
        head = (f"POST {url} HTTP/1.1\r\nHost: 127.0.0.1:{self.port}\r\nConnection: close\r\n"
                f"Origin: {own}\r\nOrigin: http://evil.example\r\nX-Deck-Lab: 1\r\n"
                f"Content-Type: application/json\r\nContent-Length: {len(body)}\r\n\r\n").encode()
        self.assertTrue(self.raw(head + body).startswith(b"HTTP/1.1 403 "))
        before = self.settings()
        self.assertError("/api/profiles/user1/settings", 403, "PUT", b'{"theme": "dark"}',
                         dict(WRITE, Origin="http://evil.example"))
        self.assertEqual(self.settings(), before)

    def test_a_preflight_is_never_approved(self):
        for path in ("/api/deck/save", "/api/decks", "/api/profiles/matt/settings", "/api/tables/update"):
            with self.subTest(path=path):
                code, headers, _ = self.request("OPTIONS", path, headers={
                    "Origin": "http://evil.example", "Access-Control-Request-Method": "POST",
                    "Access-Control-Request-Headers": "content-type, x-deck-lab"})
                self.assertEqual(code, 405)
                self.assertFalse([h for h in headers if h.lower().startswith("access-control-")])

    def test_every_write_names_a_profile(self):
        for profile in (None, "nobody", "guest", "../evil"):
            with self.subTest(profile=profile):
                self.assertIn("Choose who you are", self.post("/api/deck/check", {"kind": "casual"}, 403,
                                                              profile=profile)["error"])

    def test_body_limits(self):
        body = json.dumps({"profile": "matt", "text": "1 Forest\n" * 40000}).encode()
        # The answer comes from the headers alone: the body is never waited for.
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            conn.putrequest("POST", "/api/decklist/parse", skip_accept_encoding=True)
            for key, value in dict(WRITE, **{"Content-Length": str(len(body))}).items():
                conn.putheader(key, value)
            conn.endheaders()
            response = conn.getresponse()
            self.assertEqual((response.status, response.headers["Connection"]), (413, "close"))
            self.assertIn("limited to 262144 bytes", json.loads(response.read())["error"])
        finally:
            conn.close()
        # Sent whole, as a page sends it, the client still gets the 413 rather
        # than a reset connection (the server drops the unread body first; on
        # Windows about 1 request in 30 used to fail with ConnectionAbortedError).
        for attempt in range(30):
            with self.subTest(attempt=attempt):
                code, headers, data = self.request("POST", "/api/decklist/parse", body)
                self.assertEqual((code, headers["Connection"]), (413, "close"))
                self.assertIn("limited to 262144 bytes", json.loads(data)["error"])
        self.assertError("/api/profiles/matt/settings", 413, "PUT", b"{" + b" " * 5000 + b"}")

    def test_json_python_cant_take_is_400_not_500(self):
        # A lone surrogate is valid JSON but not a character, so it could never
        # be sent back (the block would echo it); nesting 20,000 deep overflows.
        surrogate = b'{"profile": "matt", "kind": "casual", "lists": {"target": {"Deck": [{"qty": 1, "name": "\\ud800"}]}}}'
        deep = b'{"profile": "matt", "kind": "casual", "lists": ' + b"[" * 20000 + b"]" * 20000 + b"}"
        for body, words in ((surrogate, "isn't valid Unicode"), (deep, "nested too deeply")):
            with self.subTest(words=words):
                self.assertIn(words, self.assertError("/api/deck/check", 400, "POST", body, WRITE))
        self.assertIn("isn't valid Unicode",
                      self.assertError("/api/profiles/user1/settings", 400, "PUT", b'{"\\udfff": "dark"}', WRITE))
        # And should an answer ever hold one, it's escaped rather than a 500.
        with mock.patch.object(api, "status", return_value={"odd": "\ud800"}):
            self.assertEqual(self.get_json("/api/status")["odd"], "\ud800")

    def test_save_conflict_and_blocks(self):
        view = self.get_json("/api/deck/edit?id=casual/gruul-test")
        saved = self.post("/api/deck/save", {"id": "casual/gruul-test", "sha256": view["sha256"],
                                             "fields": {"status": "idea"}})
        self.assertEqual((saved["saved"], saved["changed"]), (True, True))
        self.assertNotIn("commit", saved)
        conflict = self.post("/api/deck/save", {"id": "casual/gruul-test", "sha256": view["sha256"],
                                                "fields": {"status": "built"}}, 409)
        self.assertEqual(set(conflict), {"error", "conflict"})
        self.assertEqual(conflict["conflict"]["reason"], "changed")
        blocked = self.post("/api/deck/save", {"id": "casual/gruul-test", "sha256": saved["sha256"],
                                               "lists": {"target": {"Deck": [{"qty": 1, "name": "Nonsense Card"}]}}},
                            400)
        self.assertEqual(set(blocked), {"error", "blocks"})
        self.assertEqual(blocked["blocks"][0]["name"], "Nonsense Card")
        self.assertEqual(self.get_json("/api/deck/edit?id=casual/gruul-test")["sha256"], saved["sha256"])

    def test_create_and_the_other_endpoints(self):
        created = self.post("/api/decks", {"title": "Server Made", "kind": "casual"}, 201)
        self.assertEqual(created["id"], "casual/server-made")
        again = self.post("/api/decks", {"title": "Server Made", "kind": "casual"}, 409)
        self.assertEqual(again["conflict"]["reason"], "exists")
        printings = self.get_json("/api/cards/printings?name=Llanowar%20Elves")
        self.assertEqual(printings["default"]["set"], "fdn")
        self.assertError("/api/cards/printings?name=Nonsense%20Card", 404)
        self.assertError("/api/cards/printings?name=x&extra=1", 400)
        found = self.get_json("/api/cards/rulings?name=llanowar%20elves")
        self.assertEqual((found["name"], set(found)), ("Llanowar Elves", {"name", "available", "updated", "rulings"}))
        self.assertError("/api/cards/rulings?name=Nonsense%20Card", 404)
        self.assertError("/api/cards/rulings?name=x&extra=1", 400)
        self.assertIn("stale", self.get_json("/api/tables/stale"))
        parsed = self.post("/api/decklist/parse", {"text": "4 Llanowar Elves\n"})
        self.assertEqual(parsed["count"], {"cards": 4, "lines": 1})
        self.post("/api/tables/update", {"decks": []}, 400)
        for method, path, allow in (("GET", "/api/deck/save", "POST"), ("PUT", "/api/deck/check", "POST"),
                                    ("POST", "/api/deck/edit?id=casual/gruul-test", "GET, HEAD"),
                                    ("DELETE", "/api/decks", "GET, HEAD, POST"),
                                    ("POST", "/api/tables/stale", "GET, HEAD")):
            with self.subTest(method=method, path=path):
                code, headers, _ = self.request(method, path, b"{}")
                self.assertEqual((code, headers["Allow"]), (405, allow))
        self.assertError("/api/deck/save?x=1", 400, "POST", b"{}")


if __name__ == "__main__":
    unittest.main()
