"""Who visits Deck Lab, and which pages they open: the owner's request of 2026-10-13, to see
whether User1, User2, User3 and User4 use it and what they look at (informal user-testing
feedback). An admin reads it on the Settings page's Visits part (api/visits.py) or with
`python -m decklab.db visits`.

    visits.recorder().request("user2", "remote")                     an API request (server_http)
    visits.recorder().page("user2", "remote", "deck", "casual/elves")  the page's beacon (POST /api/visit)

What's recorded, and only that:
- a visit by a known profile (one config.json lists): through the tunnel the Cloudflare Access
  login's ("remote"), on the home network the profile the page's chooser names in
  access.VIEWER_HEADER ("home"). A request naming nobody (a script, the command line, a status
  probe) is never recorded;
- per profile, day (the PC's local date) and channel: the first and last time a page was opened,
  and how many API requests were made. Only the page's beacon makes a day and moves its times: the
  page's own polling (/api/status every 30 seconds, a run's progress) counts as requests but never
  as a visit, so a tab left open isn't "seen" all day. Requests on a day with no page opened (a tab
  left open past midnight) aren't kept;
- the pages opened: the route's path (ROUTES, the page's routes table) and, for a deck's pages
  (DECK_ROUTES), the deck's id (api/visits.py keeps it only for a deck that exists). Nothing else of
  the address (no search text, no filters). At most MAX_PAGES_PER_DAY different pages per profile,
  day and channel; past it, only the pages already there are counted, so one visitor can't flood
  the tables.

The Recorder gathers them in memory and a timer thread writes them every FLUSH_SECONDS (and at
close()), in one transaction (decklab/db/visits.py write()), so a request never waits on the
database and a page load is one upsert a minute, not one per request. It's thread-safe (the
server is a ThreadingHTTPServer). A write that fails is logged once (until one works again) and
its counts are kept for the next try, up to MAX_KEYS rows in memory; nothing is ever raised to a
request. A write gives up after WRITE_TIMEOUT seconds' connecting and has lock and statement
timeouts, and a request's write (the admin's view) or the last one at close() is skipped while the
database is failing, so neither waits on it.

recorder() is the process's Recorder: the one a test installed with use(), else one writing to
the database. With DECKLAB_STATE_EXPLICIT set (the test package), that default records nothing.
"""
import os
import threading
import time
from datetime import datetime

CHANNELS = ("home", "remote")
# The page's routes (web/core.js ROUTES); an unknown one isn't recorded.
ROUTES = frozenset({"library", "collection", "shopping", "matchups", "tokens", "accessories", "assembly", "play",
                    "wishlist", "activity", "settings", "deck", "edit", "new", "history", "variant", "receipt",
                    "matchup", "visibility"})
DECK_ROUTES = frozenset({"deck", "edit", "history"})     # routes whose ?id= is a deck, kept with them
MAX_DECK_ID = 200
FLUSH_SECONDS = 60          # how often the timer writes what was gathered
KNOWN_SECONDS = 60          # how long the list of profile ids is kept before config.json is read again
MAX_KEYS = 5000             # rows kept in memory at most (days and pages together); past it, new ones are dropped
MAX_PAGES_PER_DAY = 200     # different pages kept per profile, day and channel; past it, only those are counted
WRITE_TIMEOUT = 2           # seconds to connect for a write (the server's request timeout)
WRITE_OPTIONS = "-c lock_timeout=2000 -c statement_timeout=5000"
EXPLICIT_ENV = "DECKLAB_STATE_EXPLICIT"     # decklab.lib.state's: the tests' "install what you use"


def valid_deck_id(deck_id):
    """True for something shaped like a deck id (casual/gruul-ramp, user2/commander/x, product/...,
    pairing/a+b): lowercase letters, digits and - _ . + /, at most MAX_DECK_ID long."""
    return (isinstance(deck_id, str) and 0 < len(deck_id) <= MAX_DECK_ID and deck_id.isascii()
            and all(ch.islower() or ch.isdigit() or ch in "-_.+/" for ch in deck_id)
            and deck_id[0].isalnum())


def _log(text):
    from decklab.db import conn as db
    try:
        db.log(text)
    except Exception:
        pass


def _known_profiles():
    """The profile ids config.json lists (profiles.read: entries the page couldn't use are skipped)."""
    from decklab.lib import profiles
    return frozenset(p["id"] for p in profiles.read())


def _database_sink(days, pages):
    from decklab.db import visits
    visits.write(days, pages, timeout=WRITE_TIMEOUT, options=WRITE_OPTIONS)


class Recorder:
    """Gathers visits in memory and writes them every interval seconds (the module docstring).

    sink(days, pages): writes what was gathered (decklab.db.visits.write's arguments); None
    records nothing. clock(): now, an aware datetime. known(): the profile ids that may be
    recorded. log(text): where a failed write is said."""

    def __init__(self, sink=None, clock=None, known=None, interval=FLUSH_SECONDS, log=None):
        self.sink = sink
        self.interval = interval
        self._clock = clock or (lambda: datetime.now().astimezone())
        self._known_source = known or _known_profiles
        self._log = log or _log
        self._lock = threading.Lock()           # guards _days, _pages, _known, _thread
        self._flush_lock = threading.Lock()     # one write at a time
        self._days = {}             # (profile, day, channel) -> [first_at, last_at, requests]; times None
                                    # until a page is opened (requests alone: write() only adds to a day)
        self._pages = {}            # (profile, day, channel, route, deck) -> [opens, last_at]
        self._page_keys = {}        # (profile, day, channel) -> {(route, deck)} seen today, written or not
                                    # (MAX_PAGES_PER_DAY); earlier days are let go at a write
        self._known = (frozenset(), None)       # (ids, time.monotonic() when read)
        self._thread = None
        self._stop = threading.Event()
        self._failing = False       # the last write failed (logged once until one works)
        self._full = False          # MAX_KEYS was reached (logged once until a write empties it)

    # ------------------------------------------------------------ gathering

    def _known_ids(self):
        ids, when = self._known
        now = time.monotonic()
        if when is not None and now - when < KNOWN_SECONDS:
            return ids
        try:
            ids = frozenset(self._known_source())
        except Exception:           # config.json unreadable: nobody is recorded until it's read again
            ids = frozenset()
        self._known = (ids, now)
        return ids

    def _accepts(self, profile_id, channel):
        return (self.sink is not None and channel in CHANNELS and isinstance(profile_id, str)
                and profile_id in self._known_ids())

    def _room(self, new_keys):
        if len(self._days) + len(self._pages) + new_keys <= MAX_KEYS:
            return True
        if not self._full:
            self._full = True
            self._log(f"Visits: more than {MAX_KEYS} rows waiting to be written; new ones are dropped until a "
                      "write works.")
        return False

    def _touch(self, key, at, requests):
        """Add to (profile, day, channel)'s row; hold _lock. at None: requests only, which don't
        move its times. False when there's no room for it."""
        row = self._days.get(key)
        if row is None:
            if not self._room(1):
                return False
            self._days[key] = [at, at, requests]
            return True
        if at is not None:
            row[0], row[1] = (at, at) if row[0] is None else (min(row[0], at), max(row[1], at))
        row[2] += requests
        return True

    def request(self, profile_id, channel):
        """Count one API request by profile_id ("home" or "remote"): only a count, never a visit
        (the module docstring). False when it isn't counted. Never raises."""
        try:
            with self._lock:
                if not self._accepts(profile_id, channel):
                    return False
                counted = self._touch((profile_id, self._clock().date(), channel), None, 1)
                if counted:
                    self._start()
            return counted
        except Exception as e:      # a request must never fail over its visit
            self._log(f"Visits: a request couldn't be counted ({type(e).__name__}: {e})")
            return False

    def page(self, profile_id, channel, route, deck_id=None):
        """Note a page opened (the beacon): route one of ROUTES, deck_id kept only for DECK_ROUTES
        (and only when it looks like a deck id), at most MAX_PAGES_PER_DAY different pages per
        profile, day and channel. False when it isn't recorded. Never raises."""
        try:
            if route not in ROUTES:
                return False
            deck = deck_id if route in DECK_ROUTES and valid_deck_id(deck_id) else ""
            with self._lock:
                if not self._accepts(profile_id, channel):
                    return False
                at = self._clock()
                day = (profile_id, at.date(), channel)
                key = (*day, route, deck)
                row = self._pages.get(key)
                if row is None:
                    seen = self._page_keys.get(day, ())
                    if (route, deck) not in seen and len(seen) >= MAX_PAGES_PER_DAY:
                        return False
                    if not self._room(1 + (day not in self._days)):
                        return False
                self._touch(day, at, 0)
                if row is None:
                    self._pages[key] = [1, at]
                    self._page_keys.setdefault(day, set()).add((route, deck))
                else:
                    row[0], row[1] = row[0] + 1, max(row[1], at)
                self._start()
            return True
        except Exception as e:
            self._log(f"Visits: a page couldn't be noted ({type(e).__name__}: {e})")
            return False

    def pending(self):
        """What's waiting to be written: (days, pages), copies in write()'s form."""
        with self._lock:
            return ({k: tuple(v) for k, v in self._days.items()}, {k: tuple(v) for k, v in self._pages.items()})

    # ------------------------------------------------------------ writing

    def flush(self, wait=None):
        """Write what was gathered (sink). True when it was written (or there was nothing);
        False when the write failed: its counts go back for the next try. Never raises.

        wait: None waits for a write already under way (the timer's); a number of seconds is for a
        caller that mustn't be held up (a request, close()): it waits at most that long for one, and
        doesn't try while the last write failed (the timer goes on trying)."""
        if wait is not None:
            if self._failing:
                return False
            if not self._flush_lock.acquire(timeout=wait):
                return False
        else:
            self._flush_lock.acquire()
        try:
            return self._flush()
        finally:
            self._flush_lock.release()

    def _flush(self):
        """flush()'s write; hold _flush_lock."""
        with self._lock:
            days, pages = self._days, self._pages
            self._days, self._pages = {}, {}
            today = self._clock().date()
            for day in [d for d in self._page_keys if d[1] < today]:     # the cap's earlier days
                del self._page_keys[day]
        if not days and not pages:
            return True
        try:
            self.sink({k: tuple(v) for k, v in days.items()}, {k: tuple(v) for k, v in pages.items()})
        except Exception as e:
            with self._lock:
                self._merge_back(days, pages)
            if not self._failing:
                self._failing = True
                self._log(f"Visits: couldn't be written ({type(e).__name__}: {str(e).strip()[:300]}); "
                          f"trying again every {self.interval} seconds")
            return False
        if self._failing:
            self._failing = False
            self._log("Visits: written again.")
        with self._lock:
            self._full = False
        return True

    def _merge_back(self, days, pages):
        """Put a failed write's rows back under the ones gathered meanwhile; hold _lock."""
        for key, (first, last, requests) in days.items():
            if self._days.get(key) is not None or self._room(1):
                self._touch(key, first, requests)
                if last is not None:
                    self._touch(key, last, 0)
        for key, (opens, last) in pages.items():
            row = self._pages.get(key)
            if row is not None:
                row[0], row[1] = row[0] + opens, max(row[1], last)
            elif key[:3] in self._days and self._room(1):
                self._pages[key] = [opens, last]

    def _start(self):
        """Start the timer thread, if it isn't running; hold _lock."""
        if self._thread is None and self.interval and not self._stop.is_set():
            self._thread = threading.Thread(target=self._run, name="visits", daemon=True)
            self._thread.start()

    def _run(self):
        while not self._stop.wait(self.interval):
            self.flush()

    def close(self, timeout=5):
        """Stop the timer and write what's left (the server stopping): skipped while the database is
        failing, and given at most timeout seconds to wait for the timer's write. Never raises."""
        self._stop.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout)
        self.flush(wait=timeout)


# ------------------------------------------------------------ the process's recorder

_lock = threading.Lock()
_active = []                # recorders installed by use(), innermost last
_default = None


def recorder():
    """The active Recorder: the innermost one use() installed, else the process's, which writes to
    the database (or records nothing with DECKLAB_STATE_EXPLICIT set)."""
    global _default
    with _lock:
        if _active:
            return _active[-1]
        if _default is None:
            _default = Recorder(sink=None if os.environ.get(EXPLICIT_ENV) else _database_sink)
        return _default


def use(rec):
    """Install rec as recorder() until the returned function is called."""
    with _lock:
        _active.append(rec)

    def undo():
        with _lock:
            if rec in _active:
                _active.remove(rec)
    return undo


def close():
    """Write what the process's recorder holds and stop its timer (the server's shutdown)."""
    with _lock:
        rec = _default
    if rec is not None:
        rec.close()
