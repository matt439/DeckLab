"""Australian shop prices for the purchase queue (E5-S08; the snapshot reads MTGMate).

The shop-specific part is an adapter (base.py's interface; mtgmate.py and gamesportal.py,
ADAPTERS below): where
a shop's page of a card name is and how to read it. This package does the rest the same for any
shop: asks politely (Session), keeps the snapshot file and matches the queue's rows.

Once a day at most, `snapshot` looks up each distinct card name on the purchase queue
(the watchlist: its rows only). The nightly step also includes confirmed missing names
from saved home decks, in the same request budget, never member decks or wishlists. It keeps
what the shop listed in decklab/data/shops/mtgmate.json (snapshot_path(), gitignored):

    {"version": 1, "shop": "MTGMate", "site": SITE, "started_at": ISO, "fetched_at": ISO,
     "crawl_delay": seconds, "cards": {name: {"status": "ok" | "not_listed" | "error",
       "at": ISO, "listings": [{"set", "number", "finish", "price", "stock", "condition", "url"}],
       "error": words}},
     "previous": {name: {"at": ISO, "listings": [...]}}}

"previous" is the snapshot before (its names that were read), so a row can say it is newly
in stock. Prices are MTGMate's own, in AUD (a listing's price None when it showed none).

How it asks: one request per card name, the shop's page of every printing with that name
(the adapter's name_url; MTGMate's NAME_PATH, the same page its card links lead to), never its
search (MTGMate's robots.txt disallows /cards/search). robots.txt is read first on every run;
a path it disallows is never fetched, and its Crawl-delay (60 seconds when this was written)
spaces the requests, so a queue of 30 names takes about half an hour. A failure, a timeout or an unreadable page leaves that name's
price unknown ("error"), never a converted US price; three failures in a row stop the run
and leave the rest unknown. The nightly task gives a run NIGHTLY_BUDGET of requests at
robots.txt's delay: the names least recently read go first, and those it doesn't reach keep
the earlier run's result with that run's time ("carried"), so a long queue is read over a few
nights rather than the task being stopped partway. Two runs never overlap (an OS lock on
mtgmate.lock, let go however the process ends). Nothing here changes the watchlist, and
Shopping only reads the file (match() below), so a page load never reaches the shop.

    python -m decklab.lib.shops snapshot [--force] [--dry-run]
        look the queue's names up (at most once in MIN_AGE unless --force); --dry-run lists
        the names and the time it would take without asking the shop anything
    python -m decklab.lib.shops show
        the queue's rows beside the snapshot (read only, no network)
    python -m decklab.lib.shops lookup NAME [--shop KEY]
        one name's listings, printed (one request after robots.txt; nothing saved); --shop
        asks another adapter's shop (gamesportal), by hand only: no scheduled run reads it
"""
import argparse
import contextlib
import json
import os
import sys
import time
import urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path

from decklab.lib import config
from decklab.lib.shops import gamesportal, mtgmate
from decklab.lib.shops.base import (FINISHES, LISTING_FIELDS, MAX_PAGE, TIMEOUT, USER_AGENT,  # noqa: F401 (the package's names)
                                    Adapter, Disallowed, ShopError, allowed, fetch_page, robots_rules)
from decklab.lib.shops.mtgmate import NAME_PATH, name_url, parse_name_page  # noqa: F401 (as before the split)

if sys.platform == "win32":
    import msvcrt
else:
    import fcntl

ADAPTERS = {adapter.key: adapter for adapter in (mtgmate.ADAPTER, gamesportal.ADAPTER)}
ADAPTER = ADAPTERS["mtgmate"]               # the shop the snapshot reads (the others only through lookup --shop)
SHOP = ADAPTER.name
SITE = ADAPTER.site
ROBOTS_PATH = ADAPTER.robots_path
SNAPSHOT = None                             # a test's own path; else snapshot_path()
SNAPSHOT_ENV = "DECKLAB_SHOP_SNAPSHOT"      # the test run's (decklab/tests/__init__.py): never the real file
MIN_AGE = timedelta(hours=20)               # "daily": a nightly run a little early still counts
DEFAULT_DELAY = 60                          # seconds between requests when robots.txt names none
MIN_DELAY = 10                              # never faster than this, whatever robots.txt says
MAX_FAILURES = 3                            # failures in a row before the shop counts as down
LOCK_AT = 1 << 20                           # the lock file's byte locked (as lib/forge/slots.py)
NIGHTLY_BUDGET = 45 * 60                    # seconds of requests a night: the task stops after two (schedule.py)
MAX_SNAPSHOT_NAMES = 5000                   # optional queue + home-missing union; never truncates queued intent
MISSING_UNAVAILABLE = "Saved home missing names could not be confirmed; the purchase queue is unchanged."


def _now():
    return datetime.now(timezone.utc).astimezone().replace(microsecond=0)


def _iso(moment):
    return moment.isoformat()


def _parse_iso(value):
    try:
        moment = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    return moment if moment.tzinfo else None


# --- fetching ----------------------------------------------------------------------------

def _fetch(url, shop=SHOP):
    """The page's text (the tests replace this). ShopError for anything that isn't a page."""
    return fetch_page(url, shop)


class Session:
    """One shop's robots.txt read once, then requests spaced by its crawl delay."""

    def __init__(self, fetch=None, sleep=None, clock=None, adapter=None):
        self.adapter = adapter or ADAPTER
        self.fetch = fetch or (lambda url: _fetch(url, self.adapter.name))
        self.sleep, self.clock = sleep or time.sleep, clock or time.monotonic
        self.rules, self.delay, self.last = None, DEFAULT_DELAY, None

    def _wait(self):
        if self.last is not None:
            left = self.delay - (self.clock() - self.last)
            if left > 0:
                self.sleep(left)
        self.last = self.clock()

    def start(self):
        self._wait()
        self.rules = robots_rules(self.fetch(self.adapter.robots_url()))
        delay = self.rules[2]
        self.delay = max(MIN_DELAY, delay if delay is not None else DEFAULT_DELAY)

    def listings(self, name):
        if self.rules is None:
            self.start()
        url = self.adapter.name_url(name)
        if not allowed(urllib.parse.urlsplit(url).path, self.rules):
            raise Disallowed(f"{self.adapter.name}'s robots.txt doesn't allow {urllib.parse.urlsplit(url).path}")
        self._wait()
        return self.adapter.parse_name_page(self.fetch(url), name)


# --- the snapshot file ---------------------------------------------------------------------

def snapshot_path():
    """decklab/data/shops/mtgmate.json (the adapter's key) in this checkout (gitignored), worked
    out at call time; DECKLAB_SHOP_SNAPSHOT names another file (the test run's own, which
    doesn't exist, so no test reads the PC's real snapshot)."""
    if SNAPSHOT:
        return Path(SNAPSHOT)
    if os.environ.get(SNAPSHOT_ENV):
        return Path(os.environ[SNAPSHOT_ENV])
    return Path(config.REPO) / "decklab" / "data" / "shops" / f"{ADAPTER.key}.json"


def load(path=None):
    """The snapshot, or None when there's none or it can't be read (Shopping then shows nothing)."""
    path = path or snapshot_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("version") != 1 or not isinstance(data.get("cards"), dict):
        return None
    return data


def _write(data, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(data, indent=1, sort_keys=True), encoding="utf-8")
    os.replace(temp, path)


def fresh(data, now):
    """True when the snapshot finished less than MIN_AGE ago."""
    finished = _parse_iso((data or {}).get("fetched_at"))
    return finished is not None and timedelta(0) <= now - finished < MIN_AGE


def queue_names(rows):
    """The distinct card names of the queue's rows, in queue order."""
    seen, names = set(), []
    for row in rows:
        name = str(row.get("name") or "").strip()
        if name and name.casefold() not in seen:
            seen.add(name.casefold())
            names.append(name)
    return names


def _last_read(previous):
    """{casefolded name: when the snapshot before read it} for its names that were read."""
    return {name.casefold(): str(entry.get("at") or "") for name, entry in ((previous or {}).get("cards") or {}).items()
            if isinstance(entry, dict) and entry.get("status") in ("ok", "not_listed")}


def oldest_first(names, previous):
    """names with those not read last time first, then the longest since read, so a run cut
    short by its time budget reaches the rest next time."""
    read = _last_read(previous)
    return sorted(names, key=lambda name: (name.casefold() in read, read.get(name.casefold(), "")))


OUT_OF_TIME = "out of time"


def take(names, *, session=None, previous=None, now=None, progress=None, budget=None, started=None):
    """A new snapshot of names. previous is the snapshot before (or None). budget: the most
    seconds of requests after robots.txt; a name the run can't reach in it keeps what the
    snapshot before read, with its time ("carried"), else is unknown. started(delay) is told
    the delay robots.txt gave, once it's read."""
    session = session or Session()
    shop = getattr(session, "adapter", ADAPTER)
    now = now or _now
    begun = now()
    cards_out, failures, stop = {}, 0, None
    try:
        session.start()
    except ShopError as error:
        stop = str(error)
    else:
        if started:
            started(session.delay)
    first = session.clock()
    before = (previous or {}).get("cards")
    for count, name in enumerate(names, 1):
        if stop is None and budget is not None and session.clock() - first + session.delay > budget:
            stop = OUT_OF_TIME
        if stop == OUT_OF_TIME:
            old = _by_name(before, name)
            if old is not None and old.get("status") in ("ok", "not_listed"):
                cards_out[name] = {"status": old["status"], "at": old.get("at"), "listings": old.get("listings") or [],
                                   "carried": True}
            else:
                cards_out[name] = {"status": "error", "at": _iso(now()), "listings": [],
                                   "error": "Not checked: this run's time ran out"}
            if progress:
                progress(count, len(names), name, cards_out[name])
            continue
        if stop is not None:
            cards_out[name] = {"status": "error", "at": _iso(now()), "listings": [],
                               "error": f"Not checked: {stop}"}
            continue
        try:
            listings = session.listings(name)
        except Disallowed as error:
            cards_out[name] = {"status": "error", "at": _iso(now()), "listings": [], "error": str(error)}
            continue
        except ShopError as error:
            failures += 1
            cards_out[name] = {"status": "error", "at": _iso(now()), "listings": [], "error": str(error)}
            if failures >= MAX_FAILURES:
                stop = f"{shop.name} failed {failures} times in a row"
        else:
            failures = 0
            cards_out[name] = {"status": "ok" if listings else "not_listed", "at": _iso(now()), "listings": listings}
        if progress:
            progress(count, len(names), name, cards_out[name])
    kept = {}
    for name, entry in ((previous or {}).get("cards") or {}).items():
        if isinstance(entry, dict) and entry.get("status") in ("ok", "not_listed"):
            kept[name] = {"at": entry.get("at"), "listings": entry.get("listings") or []}
    return {"version": 1, "shop": shop.name, "site": shop.site, "started_at": _iso(begun), "fetched_at": _iso(now()),
            "crawl_delay": session.delay, "cards": cards_out, "previous": kept}


# --- matching a queue row --------------------------------------------------------------------

def _by_name(section, name):
    if not isinstance(section, dict):
        return None
    found = section.get(name)
    if found is None:
        folded = name.casefold()
        found = next((entry for key, entry in section.items() if key.casefold() == folded), None)
    return found if isinstance(found, dict) else None


def _cheapest(listings):
    def key(item):
        price = item.get("price")
        return (price is None, float(price) if price is not None else 0.0, item.get("set", ""), item.get("number", ""))
    return min(listings, key=key) if listings else None


def pick(row, listings):
    """(the listing that answers the row, how many listings in its scope are in stock), or (None, 0).

    An exact row wants its printing and finish (nonfoil when blank). Any other row wants the
    cheapest in-stock nonfoil, else the cheapest in-stock listing of any finish, else the cheapest
    nonfoil out of stock (AGENTS.md: the cheapest printing, non-foil, unless asked)."""
    listings = [item for item in listings or () if isinstance(item, dict)]
    finish = (row.get("finish") or "nonfoil").lower()
    if row.get("printing") == "exact" and row.get("set") and row.get("collector_number"):
        scope = [item for item in listings if item.get("set") == str(row["set"]).lower()
                 and str(item.get("number", "")).casefold() == str(row["collector_number"]).casefold()
                 and item.get("finish") == finish]
        stocked = [item for item in scope if item.get("stock", 0) > 0]
        return (_cheapest(stocked) or _cheapest(scope)), len(stocked)
    stocked = [item for item in listings if item.get("stock", 0) > 0]
    plain = [item for item in stocked if item.get("finish") == "nonfoil"]
    choice = _cheapest(plain) or _cheapest(stocked) or _cheapest(
        [item for item in listings if item.get("finish") == "nonfoil"]) or _cheapest(listings)
    return choice, len(stocked)


def match(row, data):
    """What the snapshot says about one queue row, or None when there is no snapshot:
    {"shop", "status": "in_stock" | "out_of_stock" | "not_listed" | "unknown" | "not_checked",
     "fetched_at", "price_aud", "stock", "set", "collector_number", "finish", "url",
     "in_stock_printings", "error", "back_in_stock", "newly_in_stock", "carried"}.
    back_in_stock: a waiting_for_stock row the snapshot finds in stock (E5-S19's highlight);
    newly_in_stock: in stock now and not in the snapshot before; carried: a name the last run
    didn't reach in its time, shown as an earlier run read it (fetched_at is then that run's)."""
    if not data:
        return None
    name = str(row.get("name") or "")
    entry = _by_name(data.get("cards"), name)
    shown = {"shop": data.get("shop") or SHOP, "status": "not_checked", "fetched_at": None, "price_aud": None,
             "stock": None, "set": None, "collector_number": None, "finish": None, "url": None,
             "in_stock_printings": 0, "error": None, "back_in_stock": False, "newly_in_stock": False,
             "carried": False}
    if entry is None:
        return shown
    shown["fetched_at"] = entry.get("at") or data.get("fetched_at")
    shown["carried"] = bool(entry.get("carried"))
    status = entry.get("status")
    if status == "error":
        shown.update(status="unknown", error=str(entry.get("error") or f"{SHOP} couldn't be read"))
        return shown
    choice, stocked = pick(row, entry.get("listings"))
    if choice is None:
        shown["status"] = "not_listed"
        return shown
    in_stock = choice.get("stock", 0) > 0
    shown.update(status="in_stock" if in_stock else "out_of_stock", price_aud=choice.get("price"),
                 stock=choice.get("stock", 0), set=choice.get("set"), collector_number=choice.get("number"),
                 finish=choice.get("finish"), url=choice.get("url"), in_stock_printings=stocked)
    shown["back_in_stock"] = in_stock and row.get("state") == "waiting_for_stock"
    before = _by_name(data.get("previous"), name)
    if in_stock and before is not None:
        old, _ = pick(row, before.get("listings"))
        shown["newly_in_stock"] = old is None or old.get("stock", 0) <= 0
    return shown


def summary(data):
    """The snapshot's own facts for Shopping, or None: {"shop", "site", "fetched_at", "started_at"}."""
    if not data:
        return None
    return {"shop": data.get("shop") or SHOP, "site": data.get("site") or SITE,
            "fetched_at": data.get("fetched_at"), "started_at": data.get("started_at")}


# --- the command line -------------------------------------------------------------------------

def _queue():
    """The watchlist's rows as dicts, read as saved (purchases.read_queue would also insist
    every source file exists, which a name lookup doesn't need)."""
    from decklab.lib import inventory, purchases
    with contextlib.nullcontext() if inventory.is_pinned() else inventory.pinned():
        return [{key: row.text(key) for key in purchases.QUEUE_FIELDS} for row in inventory.current().watchlist.rows]


def _lock_path():
    return snapshot_path().with_name(f"{ADAPTER.key}.lock")


def _lock():
    """The open lock file's descriptor once this process holds its OS lock, else None. The OS
    lets go of it however the process ends (a nightly task stopped at its time limit too), so a
    killed run never blocks the next; the file itself stays."""
    lock = _lock_path()
    lock.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(lock, os.O_RDWR | os.O_CREAT | getattr(os, "O_BINARY", 0), 0o666)
    try:
        if sys.platform == "win32":
            os.lseek(fd, LOCK_AT, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        else:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(fd)
        return None
    return fd


def _unlock(fd):
    try:
        if sys.platform == "win32":
            os.lseek(fd, LOCK_AT, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        else:
            fcntl.flock(fd, fcntl.LOCK_UN)
    except OSError:
        pass
    os.close(fd)


def _describe(shown):
    if shown is None:
        return "no snapshot"
    if shown["status"] in ("in_stock", "out_of_stock"):
        where = f"{shown['set'].upper()} {shown['collector_number']} {shown['finish']}"
        price = f"A${shown['price_aud']}" if shown["price_aud"] else "price not shown"
        stock = f"{shown['stock']} in stock" if shown["status"] == "in_stock" else "out of stock"
        flags = " BACK IN STOCK" if shown["back_in_stock"] else (" new" if shown["newly_in_stock"] else "")
        when = f", as read {shown['fetched_at']}" if shown.get("carried") else ""
        return f"{price}, {stock} ({where}){flags}{when}"
    return {"not_listed": "not listed", "not_checked": "not in the snapshot"}.get(
        shown["status"], f"price unknown: {shown['error']}")


def _minutes(names, delay=DEFAULT_DELAY):
    return max(1, round(len(names) * delay / 60))


def refresh(*, force=False, say=print, progress=True, session=None, budget=None, include_missing=False):
    """Take and save a new snapshot of the queue's names, unless the last one is less than
    MIN_AGE old (or force). budget: take()'s, the most seconds of requests (the names least
    recently read go first, so the rest come next time). say(words) reports; 0 done or nothing
    due, 1 refused (another run going) or every name unknown, 2 the purchase queue couldn't be read.
    include_missing is the nightly opt-in: one frozen union of queued names and proven saved-home
    shortfalls. A failed optional scan keeps every original queue name and reports fixed wording.
    Caller pins survive; a pin opened here is released before any retailer request."""
    from decklab.lib import inventory
    now = _now()
    with contextlib.ExitStack() as capture:
        if include_missing and not inventory.is_pinned():
            capture.enter_context(inventory.pinned())
        try:
            queued = _queue()
            names = tuple(queue_names(queued))
        except (inventory.Unavailable, ValueError) as error:
            say(f"The purchase queue couldn't be read: {error}")
            return 2
        previous = load()
        if not force and fresh(previous, now):
            _not_due(previous, say)
            return 0
        if not names and not include_missing:
            say("The purchase queue is empty; nothing to look up.")
            return 0
        lock = _lock()
        if lock is None:
            say(f"Another {SHOP} snapshot is running ({_lock_path()}).")
            return 1
        try:
            if include_missing:
                # A different run may have finished between the early age check and this
                # lock. Use its latest data for both the age gate and carried timestamps.
                previous = load()
                if not force and fresh(previous, _now()):
                    _not_due(previous, say)
                    return 0
                try:
                    from decklab.lib import shop_needs
                    plan = shop_needs.names(queued, inventory.current())
                    notice = shop_needs.NOTICES[plan.status]
                    selected = tuple(plan.names)
                except Exception:           # optional proof never blocks a queued lookup
                    say(MISSING_UNAVAILABLE)
                else:
                    names = selected
                    if notice:
                        say(notice)
            # Only names and cached shop facts survive this point. No counting,
            # inventory read or card lookup is deferred into Session/robots work.
            capture.close()
            if not names:
                say("The purchase queue is empty; nothing to look up.")
                return 0
            names = tuple(oldest_first(names, previous))

            def started(delay):
                fits = "" if budget is None or len(names) * delay <= budget else (
                    f"; this run stops after about {round(budget / 60)} minutes and the rest keep their last results")
                say(f"Looking up {len(names)} names on {SHOP}, one request each, {delay:g} seconds apart as its "
                    f"robots.txt asks (about {_minutes(names, delay)} minutes{fits}).")

            def step(count, total, name, entry):
                words = {"ok": f"{len(entry['listings'])} listings", "not_listed": "not listed"}.get(
                    entry["status"], entry.get("error", "error"))
                if entry.get("carried"):
                    words = f"not reached; kept the result read {entry.get('at')}"
                say(f"  {count}/{total} {name}: {words}")
            data = take(names, session=session, previous=previous, progress=step if progress else None,
                        budget=budget, started=started)
            _write(data, snapshot_path())
        finally:
            _unlock(lock)
    entries = list(data["cards"].values())
    failed = sum(entry["status"] == "error" for entry in entries)
    carried = sum(bool(entry.get("carried")) for entry in entries)
    kept = f", {carried} not reached and kept from before" if carried else ""
    say(f"Saved {snapshot_path()} ({len(names) - failed - carried} read{kept}, {failed} unknown).")
    return 1 if failed == len(names) else 0


def _not_due(previous, say):
    say(f"The {SHOP} snapshot of {previous['fetched_at']} is less than {int(MIN_AGE.total_seconds() // 3600)} "
        "hours old; nothing fetched (--force to fetch anyway).")


def nightly(log):
    """The nightly job's step (decklab/db/nightly.py): refresh() with its words in log. Always 0:
    a shop that can't be reached is no failure of the database's night, and the log says why."""
    try:
        refresh(say=lambda words: log(f"Nightly: {SHOP} prices: {words.strip()}"), progress=False,
                budget=NIGHTLY_BUDGET, include_missing=True)
    except Exception as error:  # a broken shop page must not mark the backup night failed
        log(f"Nightly: {SHOP} prices failed: {type(error).__name__}: {error}")
    return 0


def _snapshot(args):
    if args.dry_run:
        from decklab.lib.inventory import Unavailable
        try:
            names = queue_names(_queue())
        except (Unavailable, ValueError) as error:
            print(f"The purchase queue couldn't be read: {error}", file=sys.stderr)
            return 2
        print(f"{len(names)} names on the purchase queue; at {DEFAULT_DELAY} seconds a request that's about "
              f"{_minutes(names)} minutes.")
        for name in names:
            print(f"  {name}")
        return 0
    return refresh(force=args.force, say=lambda words: print(words, flush=True))


def _show(_args):
    from decklab.lib.inventory import Unavailable
    data = load()
    if data is None:
        print(f"No {SHOP} snapshot yet: python -m decklab.lib.shops snapshot")
        return 0
    try:
        rows = _queue()
    except Unavailable as error:
        print(f"The purchase queue couldn't be read: {error}", file=sys.stderr)
        return 2
    print(f"{SHOP} snapshot of {data.get('fetched_at')}")
    for number, row in enumerate(rows, 1):
        reference = f"ref A${row['listed_aud']} at {row['listed_at']}" if row.get("listed_aud") else "no reference"
        print(f"#{number} {row['name']} [{row.get('state')}] {reference}; {SHOP}: {_describe(match(row, data))}")
    return 0


def _lookup(args):
    adapter = ADAPTERS[args.shop]
    try:
        listings = Session(adapter=adapter).listings(args.name)
    except ShopError as error:
        print(error, file=sys.stderr)
        return 1
    if not listings:
        print(f"{adapter.name} lists nothing named {args.name}.")
    for item in listings:
        price = f"A${item['price']}" if item["price"] else "no price"
        print(f"{item['set'].upper()} {item['number']} {item['finish']} {item['condition']}: {price}, {item['stock']} in stock")
    return 0


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    parser = argparse.ArgumentParser(prog="python -m decklab.lib.shops",
                                     description=f"{SHOP} prices and stock for the purchase queue (a daily snapshot).")
    sub = parser.add_subparsers(dest="command", required=True)
    snap = sub.add_parser("snapshot", help="look the queue's names up and save the snapshot")
    snap.add_argument("--force", action="store_true", help="fetch even when the snapshot is less than a day old")
    snap.add_argument("--dry-run", action="store_true", help="list the names and the time it would take; fetch nothing")
    snap.set_defaults(func=_snapshot)
    sub.add_parser("show", help="the queue beside the snapshot (no network)").set_defaults(func=_show)
    look = sub.add_parser("lookup", help="one name's listings, printed (nothing saved)")
    look.add_argument("name")
    look.add_argument("--shop", choices=sorted(ADAPTERS), default=ADAPTER.key,
                      help=f"the shop to ask (default {ADAPTER.key}); the snapshot reads only {ADAPTER.key}")
    look.set_defaults(func=_lookup)
    args = parser.parse_args(argv)
    return args.func(args)

