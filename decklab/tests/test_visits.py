"""Tests for visits (lib/visits.py, lib/api/visits.py, decklab/db/visits.py and migration 0008):
the in-memory recorder and its timer, the page's beacon (POST /api/visit: the requester's own
profile only, never a data write), the admins' view (GET /api/visits), the server counting API
requests, and the tables (written as decklab_app, summarised, pruned by the owner, outside the
dumps' content digests). The database classes skip without PostgreSQL (db_support).

Run from the repo root: python scripts/test_fixtures.py decklab.tests.test_visits
The fixture runner disables configured PostgreSQL and real Forge; named native
runtime cases also need separate qualification (see AGENTS.md, Tests).
"""
import http.client
import json
import subprocess
import threading
import time
import unittest
from datetime import date, datetime, timedelta, timezone
from unittest import mock

from decklab import server  # noqa: F401 (runs build.start() before the server modules load)
from decklab.lib import access, api, server_http, visits
from decklab.lib.api import visits as visits_api
from decklab.tests import db_support, household_config
from decklab.tests.test_api import ApiTestCase, Sandbox
from decklab.tests.test_shell_ui import SETUP
from decklab.tests.test_workspace_ui import NODE, RUNNER, WEB

KNOWN = frozenset({"matt", "user1", "user2"})
AT = datetime(2026, 10, 13, 9, 30, tzinfo=timezone(timedelta(hours=10)))
PROFILES = [{"id": "matt", "name": "Matt", "plays_as": "user", "role": "admin"},
            {"id": "user1", "name": "User1", "plays_as": "wife", "role": "member"},
            {"id": "user2", "name": "User2", "role": "member", "space": "user2"}]


class Clock:
    def __init__(self, at=AT):
        self.at = at

    def __call__(self):
        return self.at


def recorder(sink=None, clock=None, interval=0, log=None):
    """A Recorder with no timer (interval 0) over KNOWN, writing into sink (a list by default)."""
    written = []
    rec = visits.Recorder(sink=sink or (lambda days, pages: written.append((days, pages))), clock=clock or Clock(),
                          known=lambda: KNOWN, interval=interval, log=log or (lambda text: None))
    rec.written = written
    return rec


class RecorderTests(unittest.TestCase):

    def test_requests_and_pages_gather_per_profile_day_and_channel(self):
        clock = Clock()
        rec = recorder(clock=clock)
        self.assertTrue(rec.request("user2", "remote"))
        clock.at = AT + timedelta(minutes=5)
        rec.request("user2", "remote")
        rec.request("user2", "home")
        self.assertTrue(rec.page("user2", "remote", "deck", "user2/casual/elves"))
        rec.page("user2", "remote", "deck", "user2/casual/elves")
        rec.page("user2", "remote", "library")
        days, pages = rec.pending()
        # Only the pages make the day's times; the requests are a count.
        self.assertEqual(days[("user2", AT.date(), "remote")], (AT + timedelta(minutes=5), AT + timedelta(minutes=5), 2))
        self.assertEqual(days[("user2", AT.date(), "home")], (None, None, 1))
        self.assertEqual(pages[("user2", AT.date(), "remote", "deck", "user2/casual/elves")][0], 2)
        self.assertEqual(pages[("user2", AT.date(), "remote", "library", "")], (1, AT + timedelta(minutes=5)))

    def test_only_known_profiles_channels_and_routes(self):
        rec = recorder()
        self.assertFalse(rec.request("stranger", "remote"))
        self.assertFalse(rec.request(None, "home"))
        self.assertFalse(rec.request("matt", "elsewhere"))
        self.assertFalse(rec.page("matt", "home", "not-a-page"))
        self.assertFalse(rec.page("matt", "home", "deck?id=x"))
        self.assertEqual(rec.pending(), ({}, {}))

    def test_only_a_decks_id_is_kept_and_only_on_a_decks_pages(self):
        rec = recorder()
        rec.page("matt", "home", "collection", "casual/gruul-ramp")        # not a deck's page: no id kept
        rec.page("matt", "home", "deck", "Search text with spaces")       # not shaped like a deck id
        rec.page("matt", "home", "history", "pairing/cats+vampires")
        rec.page("matt", "home", "edit", "x" * 500)
        keys = {k[3:] for k in rec.pending()[1]}
        self.assertEqual(keys, {("collection", ""), ("deck", ""), ("history", "pairing/cats+vampires"), ("edit", "")})

    def test_a_page_makes_its_day_without_counting_a_request(self):
        rec = recorder()
        rec.page("user1", "home", "wishlist")
        self.assertEqual(rec.pending()[0][("user1", AT.date(), "home")], (AT, AT, 0))

    def test_requests_alone_are_never_a_visit(self):
        # The page's own polling (/api/status every 30 seconds) counts, but never makes a day or
        # moves its times: a tab left open isn't "seen" all day.
        clock = Clock()
        rec = recorder(clock=clock)
        rec.page("user1", "home", "library")
        clock.at = AT + timedelta(hours=3)
        for _ in range(360):
            rec.request("user1", "home")
        self.assertEqual(rec.pending()[0][("user1", AT.date(), "home")], (AT, AT, 360))
        clock.at = AT + timedelta(days=1)
        rec.request("user1", "home")
        self.assertEqual(rec.pending()[0][("user1", AT.date() + timedelta(days=1), "home")], (None, None, 1))

    def test_one_visitor_cant_flood_the_pages(self):
        # At most MAX_PAGES_PER_DAY different pages per profile, day and channel, across writes;
        # pages already there still count, and nobody else is crowded out.
        clock = Clock()
        rec = recorder(clock=clock)
        with mock.patch.object(visits, "MAX_PAGES_PER_DAY", 3):
            for n in range(3):
                self.assertTrue(rec.page("user2", "remote", "deck", f"casual/x{n}"))
            rec.flush()
            self.assertFalse(rec.page("user2", "remote", "deck", "casual/x9"))
            self.assertTrue(rec.page("user2", "remote", "deck", "casual/x1"))
            self.assertTrue(rec.page("user2", "home", "deck", "casual/x9"))       # another channel
            self.assertTrue(rec.page("user1", "remote", "library"))
            clock.at = AT + timedelta(days=1)
            rec.flush()                                                           # yesterday let go
            self.assertTrue(rec.page("user2", "remote", "deck", "casual/x9"))
        self.assertEqual(set(rec._page_keys), {("user2", AT.date() + timedelta(days=1), "remote")})

    def test_a_request_with_no_room_says_so(self):
        logs = []
        rec = recorder(log=logs.append)
        with mock.patch.object(visits, "MAX_KEYS", 2):
            rec.page("matt", "home", "library")
            self.assertFalse(rec.request("user1", "home"))
        self.assertEqual(len(logs), 1)

    def test_flush_writes_and_empties(self):
        rec = recorder()
        rec.request("matt", "home")
        self.assertTrue(rec.flush())
        self.assertEqual(len(rec.written), 1)
        self.assertEqual(rec.pending(), ({}, {}))
        self.assertTrue(rec.flush())                    # nothing to write: no call
        self.assertEqual(len(rec.written), 1)

    def test_a_failed_write_keeps_the_counts_and_logs_once(self):
        logs, calls = [], []

        def failing(days, pages):
            calls.append((days, pages))
            raise OSError("database down")
        rec = recorder(sink=failing, log=logs.append)
        rec.request("matt", "home")
        rec.page("matt", "home", "library")
        self.assertFalse(rec.flush())
        rec.request("matt", "home")
        self.assertFalse(rec.flush())
        self.assertEqual(len(logs), 1)
        self.assertIn("database down", logs[0])
        days, pages = rec.pending()
        self.assertEqual(days[("matt", AT.date(), "home")][2], 2)
        self.assertEqual(pages[("matt", AT.date(), "home", "library", "")][0], 1)
        rec.sink = lambda days, pages: None
        self.assertTrue(rec.flush())
        self.assertIn("written again", logs[-1])

    def test_nothing_is_kept_past_max_keys(self):
        logs = []
        rec = recorder(log=logs.append)
        with mock.patch.object(visits, "MAX_KEYS", 3):
            rec.page("matt", "home", "library")              # a day and a page
            rec.page("matt", "home", "shopping")             # a third row
            self.assertFalse(rec.page("matt", "home", "tokens"))
            self.assertTrue(rec.request("matt", "home"))     # its day is already there
        self.assertEqual(sum(map(len, rec.pending())), 3)
        self.assertEqual(len(logs), 1)

    def test_a_request_or_close_doesnt_wait_on_a_failing_database(self):
        calls = []

        def failing(days, pages):
            calls.append(1)
            raise OSError("database down")
        rec = recorder(sink=failing)
        rec.page("matt", "home", "library")
        self.assertFalse(rec.flush())                   # the timer's: tries
        self.assertFalse(rec.flush(wait=1))             # a request's: not while failing
        rec.close()
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(rec.pending()[1]), 1)
        # A write under way: a request's waits at most `wait`.
        rec = recorder()
        rec.page("matt", "home", "library")
        with rec._flush_lock:
            started = time.monotonic()
            self.assertFalse(rec.flush(wait=0.05))
            self.assertLess(time.monotonic() - started, 2)
        self.assertTrue(rec.flush(wait=0.05))

    def test_no_sink_records_nothing(self):
        rec = visits.Recorder(sink=None, known=lambda: KNOWN, interval=0)
        self.assertFalse(rec.request("matt", "home"))
        self.assertFalse(rec.page("matt", "home", "library"))

    def test_an_unreadable_config_records_nobody(self):
        def broken():
            raise ValueError("bad json")
        rec = visits.Recorder(sink=lambda d, p: None, known=broken, interval=0)
        self.assertFalse(rec.request("matt", "home"))

    def test_threads_count_every_request(self):
        rec = recorder()

        def hammer():
            for _ in range(500):
                rec.request("matt", "home")
                rec.page("matt", "home", "library")
        threads = [threading.Thread(target=hammer) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        days, pages = rec.pending()
        self.assertEqual(days[("matt", AT.date(), "home")][2], 4000)
        self.assertEqual(pages[("matt", AT.date(), "home", "library", "")][0], 4000)

    def test_the_timer_writes_and_close_writes_the_rest(self):
        written = threading.Event()
        rec = visits.Recorder(sink=lambda d, p: written.set(), clock=Clock(), known=lambda: KNOWN, interval=0.05)
        rec.request("matt", "home")
        self.assertTrue(written.wait(5))
        written.clear()
        rec.request("matt", "home")
        rec.close()
        self.assertTrue(written.is_set())
        self.assertFalse(rec._thread.is_alive())

    def test_the_default_records_nothing_in_the_tests(self):
        # The test package sets DECKLAB_STATE_EXPLICIT: the process's recorder has no sink.
        self.assertIsNone(visits.recorder().sink)
        rec = recorder()
        undo = visits.use(rec)
        self.assertIs(visits.recorder(), rec)
        undo()
        self.assertIsNot(visits.recorder(), rec)


class BeaconTests(unittest.TestCase):
    """POST /api/visit's rules (api/visits.py beacon): the requester's own visit only."""

    def setUp(self):
        household_config.use(self)
        self.rec = recorder()
        self.addCleanup(visits.use(self.rec))
        decks = mock.patch.object(visits_api, "deck_exists", lambda deck_id: deck_id == "user2/casual/elves")
        decks.start()
        self.addCleanup(decks.stop)

    def body(self, **data):
        return json.dumps(data).encode()

    def test_through_the_tunnel_it_is_the_logins(self):
        with access.using({"profile": "user2", "email": "r@example.com", "remote": True}):
            self.assertEqual(visits_api.beacon(self.body(route="deck", deck="user2/casual/elves")), {"recorded": True})
            # The server makes the body's profile the login's; any other is refused here too.
            with self.assertRaises(api.ApiError) as caught:
                visits_api.beacon(self.body(route="library", profile="matt"))
            self.assertEqual(caught.exception.status, 403)
        self.assertEqual(list(self.rec.pending()[1]), [("user2", AT.date(), "remote", "deck", "user2/casual/elves")])

    def test_at_home_it_is_the_chosen_profiles(self):
        with access.viewing("user1"):
            self.assertTrue(visits_api.beacon(self.body(route="wishlist", profile="user1"))["recorded"])
            with self.assertRaises(api.ApiError) as caught:
                visits_api.beacon(self.body(route="wishlist", profile="matt"))
            self.assertEqual(caught.exception.status, 403)
        self.assertEqual(list(self.rec.pending()[0]), [("user1", AT.date(), "home")])

    def test_a_request_naming_nobody_records_nothing(self):
        self.assertEqual(visits_api.beacon(self.body(route="library")), {"recorded": False})
        with access.viewing("stranger"):
            self.assertEqual(visits_api.beacon(self.body(route="library")), {"recorded": False})
        self.assertEqual(self.rec.pending(), ({}, {}))

    def test_a_deck_that_doesnt_exist_isnt_kept(self):
        with access.using({"profile": "user2", "email": "r@example.com", "remote": True}):
            self.assertTrue(visits_api.beacon(self.body(route="deck", deck="casual/made-up-1"))["recorded"])
            visits_api.beacon(self.body(route="library", deck="user2/casual/elves"))   # not a deck's page
        self.assertEqual({k[3:] for k in self.rec.pending()[1]}, {("deck", ""), ("library", "")})

    def test_bad_bodies(self):
        with access.viewing("matt"):
            for body in (self.body(), self.body(route="library", q="search text"), self.body(route=3),
                         self.body(route="deck", deck=["x"]), b"[]"):
                with self.subTest(body=body), self.assertRaises(api.ApiError) as caught:
                    visits_api.beacon(body)
                self.assertEqual(caught.exception.status, 400)
            self.assertEqual(visits_api.beacon(self.body(route="nowhere")), {"recorded": False})


class DeckExistsTests(unittest.TestCase):
    """deck_exists(): the library's ids, read again at most every DECKS_SECONDS (DECKS_MISS_SECONDS
    for an id not among them)."""

    def setUp(self):
        self.reads = []
        self.ids = {"casual/elves"}
        read = mock.patch.object(visits_api, "_read_deck_ids", lambda: self.reads.append(1) or frozenset(self.ids))
        read.start()
        self.addCleanup(read.stop)
        cache = mock.patch.object(visits_api, "_deck_ids", (frozenset(), None))
        cache.start()
        self.addCleanup(cache.stop)

    def test_cached(self):
        now = [1000.0]
        with mock.patch.object(visits_api.time, "monotonic", lambda: now[0]):
            self.assertTrue(visits_api.deck_exists("casual/elves"))
            for n in range(50):
                visits_api.deck_exists("casual/elves")
                visits_api.deck_exists(f"casual/made-up-{n}")
            self.assertEqual(len(self.reads), 1)
            self.ids.add("casual/new")
            now[0] += visits_api.DECKS_MISS_SECONDS
            self.assertTrue(visits_api.deck_exists("casual/new"))           # a deck just made
            self.assertEqual(len(self.reads), 2)

    def test_unreadable_keeps_no_ids(self):
        def broken():
            raise OSError("database down")
        with mock.patch.object(visits_api, "_read_deck_ids", broken):
            self.assertFalse(visits_api.deck_exists("casual/elves"))


class ViewTests(ApiTestCase):
    """GET /api/visits: an admin's only."""

    SEEN = [{"profile": "user2", "first_seen": date(2026, 10, 1), "last_seen": AT, "last_channel": "remote",
             "days": 3, "requests": 40,
             "recent": [{"route": "deck", "deck": "casual/gruul-test", "at": AT}],
             "often": [{"route": "library", "deck": None, "opens": 7}]}]

    def setUp(self):
        super().setUp()
        (self.box.root / "config.json").write_text(json.dumps({"profiles": PROFILES}), encoding="utf-8")
        self.rec = recorder()
        self.addCleanup(visits.use(self.rec))
        read = mock.patch.object(visits_api, "_read", return_value=self.SEEN)
        self.read = read.start()
        self.addCleanup(read.stop)

    def test_admins_and_a_home_request_naming_nobody(self):
        answer = visits_api.visits_view()
        self.assertEqual(answer["days"], 30)
        self.assertEqual([p["profile"] for p in answer["people"]], ["user2", "matt", "user1"])
        user2 = answer["people"][0]
        self.assertEqual((user2["seen"], user2["days"], user2["last_channel"], user2["first_seen"]),
                         (True, 3, "remote", "2026-10-01"))
        self.assertEqual(user2["recent"][0]["title"], "Gruul Test")
        self.assertEqual(user2["often"], [{"route": "library", "deck": None, "title": None, "opens": 7}])
        self.assertFalse(answer["people"][1]["seen"])
        with access.viewing("matt"):
            visits_api.visits_view(days="7", who="user2")
        self.read.assert_called_with(7, "user2")
        with access.using({"profile": "matt", "email": "m@example.com", "remote": True}):
            self.assertEqual(len(visits_api.visits_view()["people"]), 3)

    def test_anyone_else_is_refused(self):
        for who in ("user1", "user2"):
            with self.subTest(home=who), access.viewing(who):
                self.assertApiError(403, visits_api.visits_view)
            with self.subTest(tunnel=who), access.using({"profile": who, "email": "x@example.com", "remote": True}):
                self.assertApiError(403, visits_api.visits_view)

    def test_what_is_waiting_is_written_first(self):
        self.rec.request("matt", "home")
        visits_api.visits_view()
        self.assertEqual(len(self.rec.written), 1)

    def test_bad_queries_and_a_database_down(self):
        self.assertApiError(400, visits_api.visits_view, "0")
        self.assertApiError(400, visits_api.visits_view, "abc")
        self.assertApiError(404, visits_api.visits_view, None, "stranger")
        self.read.side_effect = OSError("down")
        self.assertApiError(503, visits_api.visits_view)


class ServerTests(unittest.TestCase):
    """The home listener counts a request in the visits of the profile it names, and the beacon
    needs the page's write headers like any POST."""

    @classmethod
    def setUpClass(cls):
        cls.box = Sandbox().start()
        (cls.box.root / "config.json").write_text(json.dumps({"profiles": PROFILES}), encoding="utf-8")
        cls.log_patch = mock.patch.object(server_http, "log", lambda text: None)
        cls.log_patch.start()
        cls.httpd = server_http.make_server("127.0.0.1", 0, web_dir=cls.box.web)
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.thread.join(5)
        cls.log_patch.stop()
        cls.box.stop()

    def setUp(self):
        self.rec = recorder()
        self.addCleanup(visits.use(self.rec))

    def request(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.httpd.server_address[1], timeout=10)
        try:
            conn.request(method, path, body=body, headers=headers or {})
            response = conn.getresponse()
            return response.status, response.read()
        finally:
            conn.close()

    def test_requests_naming_a_profile_are_counted(self):
        self.request("GET", "/api/profiles", headers={access.VIEWER_HEADER: "user1"})
        self.request("GET", "/api/status", headers={access.VIEWER_HEADER: "user1"})    # the page's poll
        self.request("GET", "/api/profiles")                                     # nobody named
        self.request("GET", "/api/profiles", headers={access.VIEWER_HEADER: "stranger"})
        days, _ = self.rec.pending()
        self.assertEqual(list(days), [("user1", AT.date(), "home")])
        self.assertEqual(days[("user1", AT.date(), "home")], (None, None, 2))      # counted, not a visit

    def test_the_beacon(self):
        exists = mock.patch.object(visits_api, "deck_exists", lambda deck_id: True)
        exists.start()
        self.addCleanup(exists.stop)
        headers = {access.VIEWER_HEADER: "user1", "Content-Type": "application/json"}
        body = json.dumps({"route": "deck", "deck": "casual/elves", "profile": "user1"})
        status, _ = self.request("POST", "/api/visit", body, headers)
        self.assertEqual(status, 403)                                          # no X-Deck-Lab header
        status, answer = self.request("POST", "/api/visit", body, {**headers, "X-Deck-Lab": "1"})
        self.assertEqual((status, json.loads(answer)), (200, {"recorded": True}))
        status, _ = self.request("GET", "/api/visit", headers=headers)
        self.assertEqual(status, 405)
        self.assertIn(("user1", AT.date(), "home", "deck", "casual/elves"), self.rec.pending()[1])
        # A member isn't picked at home (E10-S35): they visit through the tunnel, so nothing is recorded.
        theirs = json.dumps({"route": "deck", "deck": "user2/casual/elves", "profile": "user2"})
        status, answer = self.request("POST", "/api/visit", theirs,
                                      {**headers, access.VIEWER_HEADER: "user2", "X-Deck-Lab": "1"})
        self.assertEqual((status, json.loads(answer)), (403, {"error": access.SIGN_IN_OUTSIDE}))
        self.assertNotIn("user2", [key[0] for key in self.rec.pending()[1]])

    def test_visits_is_an_admins(self):
        with mock.patch.object(visits_api, "_read", return_value=[]):
            status, _ = self.request("GET", "/api/visits", headers={access.VIEWER_HEADER: "user1"})
            self.assertEqual(status, 403)
            status, answer = self.request("GET", "/api/visits?days=7", headers={access.VIEWER_HEADER: "matt"})
            self.assertEqual(status, 200)
            self.assertEqual(json.loads(answer)["days"], 7)
            status, _ = self.request("GET", "/api/visits?q=x", headers={access.VIEWER_HEADER: "matt"})
            self.assertEqual(status, 400)


class VisitsDbTests(db_support.DbTestCase):
    """The tables of migration 0008, on a throwaway database."""

    def setUp(self):
        with self.connect("owner") as c:
            c.execute("delete from ops.visit_day")
        db_support.reset(self.dbname)
        db_support.seed_membership(self.dbname, PROFILES)

    def write(self, days, pages=None):
        from decklab.db import visits as db_visits
        db_visits.write(days, pages or {}, dbname=self.dbname)

    def test_writes_add_up_and_the_summary_reads_them(self):
        from decklab.db import visits as db_visits
        today = date(2026, 10, 13)
        earlier = AT - timedelta(days=20)
        self.write({("user2", earlier.date(), "home"): (earlier, earlier, 4)},
                   {("user2", earlier.date(), "home", "library", ""): (2, earlier)})
        self.write({("user2", AT.date(), "remote"): (AT, AT, 3)},
                   {("user2", AT.date(), "remote", "deck", "user2/casual/elves"): (1, AT),
                    ("user2", AT.date(), "remote", "library", ""): (1, AT - timedelta(minutes=1))})
        later = AT + timedelta(hours=1)
        self.write({("user2", AT.date(), "remote"): (later, later, 2)},
                   {("user2", AT.date(), "remote", "deck", "user2/casual/elves"): (2, later)})
        # A page whose day the write doesn't name adds the day, with no requests.
        self.write({}, {("user1", AT.date(), "home", "wishlist", ""): (1, AT)})
        people = db_visits.summary(30, today=today, dbname=self.dbname)
        self.assertEqual([p["profile"] for p in people], ["user2", "user1"])
        user2 = people[0]
        self.assertEqual((user2["first_seen"], user2["days"], user2["requests"], user2["last_channel"]),
                         (earlier.date(), 2, 9, "remote"))
        self.assertEqual(user2["last_seen"], later)
        self.assertEqual([(p["route"], p["deck"]) for p in user2["recent"]],
                         [("deck", "user2/casual/elves"), ("library", None)])
        self.assertEqual([(p["route"], p["opens"]) for p in user2["often"]], [("deck", 3), ("library", 3)])
        week = db_visits.summary(7, "user2", today=today, dbname=self.dbname)
        self.assertEqual((len(week), week[0]["days"], week[0]["requests"]), (1, 1, 5))
        self.assertEqual([(p["route"], p["opens"]) for p in week[0]["often"]], [("deck", 3), ("library", 1)])
        lines = db_visits.lines(people, 30, {"matt": "Matt", "user2": "User2", "user1": "User1"},
                                {"user2/casual/elves": "Elves"})
        self.assertTrue(lines[0].startswith("User2 (user2): first seen"))
        self.assertIn("  recently: deck Elves, library", lines)
        self.assertEqual(lines[-1], "Matt (matt): not seen yet")

    def test_requests_alone_add_to_a_day_and_never_make_one(self):
        from decklab.db import visits as db_visits
        self.write({("matt", AT.date(), "home"): (AT, AT, 1)})
        later = AT + timedelta(hours=2)
        self.write({("matt", AT.date(), "home"): (None, None, 5), ("user1", AT.date(), "home"): (None, None, 3)})
        # In one write with a page that makes the day, they're added to it.
        self.write({("user2", AT.date(), "remote"): (None, None, 2)},
                   {("user2", AT.date(), "remote", "library", ""): (1, later)})
        with self.connect("ro") as c:
            rows = c.execute("select profile_id, first_at, last_at, requests from ops.visit_day "
                             "order by profile_id").fetchall()
        self.assertEqual(rows, [("matt", AT, AT, 6), ("user2", later, later, 2)])
        self.assertEqual([p["profile"] for p in db_visits.summary(30, today=AT.date(), dbname=self.dbname)],
                         ["user2", "matt"])

    def test_ties_come_back_in_a_fixed_order(self):
        from decklab.db import visits as db_visits
        pages = {("matt", AT.date(), "home", route, ""): (2, AT) for route in ("tokens", "library", "deck", "play")}
        self.write({("matt", AT.date(), "home"): (AT, AT, 1)}, pages)
        for _ in range(3):
            matt, = db_visits.summary(30, today=AT.date(), dbname=self.dbname)
            self.assertEqual([p["route"] for p in matt["often"]], ["deck", "library", "play", "tokens"])
            self.assertEqual([p["route"] for p in matt["recent"]], ["deck", "library", "play", "tokens"])

    def test_the_app_writes_but_never_deletes_and_the_owner_prunes(self):
        import psycopg
        from decklab.db import visits as db_visits
        old = AT - timedelta(days=500)
        self.write({("matt", old.date(), "home"): (old, old, 1), ("matt", AT.date(), "home"): (AT, AT, 1)},
                   {("matt", old.date(), "home", "library", ""): (1, old)})
        with self.connect("app") as c, self.assertRaises(psycopg.errors.InsufficientPrivilege):
            c.execute("delete from ops.visit_day")
        with self.connect("app") as c, self.assertRaises(psycopg.errors.InsufficientPrivilege):
            c.execute("insert into ops.backup_run (kind, started_at) values ('dump', now())")
        self.assertEqual(db_visits.prune(dbname=self.dbname, today=date(2026, 10, 13)), 1)
        with self.connect("ro") as c:
            self.assertEqual(c.execute("select count(*) from ops.visit_day").fetchone()[0], 1)
            self.assertEqual(c.execute("select count(*) from ops.visit_page").fetchone()[0], 0)    # cascaded

    def test_no_change_set_and_left_out_of_the_digests_and_the_export(self):
        from decklab.db import backup, export
        self.write({("matt", AT.date(), "home"): (AT, AT, 1)})
        with self.connect("ro") as c:
            self.assertEqual(c.execute("select count(*) from audit.change_set").fetchone()[0], 0)
        with self.connect("owner") as c:
            counts = backup.count_rows(c)
            digests = backup.digest_rows(c)
        self.assertEqual(counts["ops.visit_day"], 1)        # counted in a dump like ops.backup_run
        self.assertNotIn("ops.visit_day", digests)
        self.assertFalse(any("visit" in name for name, _ in export.TABLES))

    def test_the_servers_read(self):
        self.write({("user1", AT.date(), "home"): (AT, AT, 2)}, {("user1", AT.date(), "home", "tokens", ""): (1, AT)})
        people = visits_api._read(30, "user1")
        self.assertEqual([(p["profile"], p["requests"]) for p in people], [("user1", 2)])

    def test_the_tables_checks(self):
        import psycopg
        # Missing profiles are discarded before their buffered counts reach SQL.
        self.write({("Not An Id", AT.date(), "home"): (AT, AT, 1)})
        with self.connect("ro") as c:
            self.assertEqual(c.execute("select count(*) from ops.visit_day").fetchone()[0], 0)
        with self.assertRaises(psycopg.errors.CheckViolation):
            self.write({("matt", AT.date(), "tunnel"): (AT, AT, 1)})
        with self.assertRaises(psycopg.errors.CheckViolation):
            self.write({}, {("matt", AT.date(), "home", "deck?id=x", ""): (1, AT)})

    def test_departed_or_missing_buffered_profiles_are_dropped_without_losing_other_visits(self):
        from decklab.db import conn as db
        with self.connect("owner") as c:
            with db.change("test", "test", "Departed visit fixture", conn=c) as (cur, change_id):
                cur.execute("insert into space_departure (space_id,operation,change_set_id) "
                            "values ('user2','00000000-0000-4000-8000-000000000001',%s)", (change_id,))
        self.write({("user2", AT.date(), "remote"): (AT, AT, 2),
                    ("missing", AT.date(), "remote"): (None, None, 4),
                    ("matt", AT.date(), "home"): (AT, AT, 1)},
                   {("user2", AT.date(), "remote", "library", ""): (3, AT),
                    ("missing", AT.date(), "remote", "library", ""): (1, AT),
                    ("matt", AT.date(), "home", "library", ""): (1, AT)})
        with self.connect("ro") as c:
            self.assertEqual(c.execute("select profile_id,requests from ops.visit_day").fetchall(), [("matt", 1)])
            self.assertEqual(c.execute("select profile_id,opens from ops.visit_page").fetchall(), [("matt", 1)])

    def test_a_queued_visit_batch_checks_departure_after_the_removal_claim_commits(self):
        from decklab.db import conn as db, space_members
        started, finished = threading.Event(), threading.Event()
        errors = []
        original = space_members.shared

        def waiting(cur):
            started.set()
            return original(cur)

        def write():
            try:
                self.write({("user2", AT.date(), "remote"): (AT, AT, 1)})
            except Exception as error:
                errors.append(error)
            finally:
                finished.set()

        with self.connect("owner") as c:
            with db.change("test", "test", "Queued visit departure", conn=c) as (cur, change_id):
                cur.execute("select pg_advisory_xact_lock(hashtext('inventory'))")
                with mock.patch.object(space_members, "shared", side_effect=waiting):
                    worker = threading.Thread(target=write)
                    worker.start()
                    self.assertTrue(started.wait(5))
                    self.assertFalse(finished.is_set())
                    cur.execute("insert into space_departure (space_id,operation,change_set_id) "
                                "values ('user2','00000000-0000-4000-8000-000000000002',%s)", (change_id,))
            worker.join(5)
        self.assertFalse(worker.is_alive())
        self.assertEqual(errors, [])
        with self.connect("ro") as c:
            self.assertEqual(c.execute("select count(*) from ops.visit_day").fetchone()[0], 0)


@unittest.skipUnless(NODE, "Node.js isn't installed")
class VisitsUiTests(unittest.TestCase):
    """The page's side: the router's beacon (app.js noteVisit) and the Settings page's Visits part."""

    def run_js(self, scenario):
        result = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), SETUP + scenario, True]),
                                capture_output=True, text=True, encoding="utf-8", timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")

    def test_the_router_sends_the_route_and_a_decks_id_only(self):
        self.run_js("""
          const sent = [];
          apiWrite = async (path, body) => { sent.push([path, body]); return { recorded: true }; };
          showLibrary = () => {}; showTokens = () => {};
          as("user1", false);
          location.hash = "#/library?format=casual"; route();
          route();                                      // drawn again at once: not sent twice
          location.hash = "#/tokens?q=goblin"; route();
          noteVisit("deck", new URLSearchParams("id=casual/gruul-ramp&v=owned"));
          noteVisit("collection", new URLSearchParams("q=secret&space=home"));
          noteVisit("nowhere", new URLSearchParams("id=x"));
          same(sent, [["/api/visit", { route: "library" }], ["/api/visit", { route: "tokens" }],
            ["/api/visit", { route: "deck", deck: "casual/gruul-ramp" }], ["/api/visit", { route: "collection" }],
            ["/api/visit", { route: "library" }]]);
          // A failure is ignored, thrown or rejected.
          apiWrite = () => { throw new Error("offline"); };
          noteVisit("shopping", new URLSearchParams());
          apiWrite = async () => { throw new ApiError(0, "offline"); };
          noteVisit("play", new URLSearchParams()); await flush();
        """)

    def test_the_settings_page_lists_each_profile(self):
        self.run_js("""
          showFooter = () => {};
          const plain = api;
          api = async (path) => {
            if (path === "/api/visits?days=30") return { days: 30, people: [
              { profile: "user2", name: "User2", seen: true, first_seen: "2026-10-01",
                last_seen: "2026-10-13T09:30:00+10:00", last_channel: "remote", days: 3, requests: 40,
                recent: [{ route: "deck", deck: "user2/casual/elves", title: "Elves", at: "2026-10-13T09:30:00+10:00" }],
                often: [{ route: "library", deck: null, title: null, opens: 7 }] },
              { profile: "user1", name: "User1", seen: false, first_seen: null, last_seen: null, last_channel: null,
                days: 0, requests: 0, recent: [], often: [] }] };
            return plain(path);
          };
          as("matt", false);
          showSettings(new URLSearchParams(), routeToken); await flush();
          const people = main.querySelectorAll(".visits-person");
          same(people.map((p) => p.dataset.profile), ["user2", "user1"]);
          const user2 = people[0].textContent;
          assert(user2.includes("from outside the home"), user2);
          assert(user2.includes("3 of the last 30 days"), user2);
          assert(user2.includes("Recently: Deck: Elves"), user2);
          assert(user2.includes("Most opened: Decks (7)"), user2);
          assert(people[1].textContent.includes("Not seen yet"));
          // A refusal (or the database down) is said in the part, not across the page.
          api = async (path) => { if (path.startsWith("/api/visits")) throw new ApiError(403, "Visits are for admins"); return plain(path); };
          showSettings(new URLSearchParams(), routeToken); await flush();
          assert(main.querySelector("#visits-list").textContent.includes("Visits are for admins"));
        """)


if __name__ == "__main__":
    unittest.main()
