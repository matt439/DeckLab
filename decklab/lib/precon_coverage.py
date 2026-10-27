"""Precon coverage (E1-S24): MTGJSON's published precons (lib/precons.py) ranked
by how much of each one a space's free pool already covers, to pick the next
deck to build with the fewest purchases.

A precon's coverage is the share of its cards, plain basics left out (as the
pool leaves them out everywhere), that have a copy free for a new deck: owned
or on the way, less what built decks and intact products hold
(pool.free_copies). Every section counts, commander and sideboard included;
the display commander (the box's window card) doesn't.

Ranking every precon needs every precon's list, and fetching MTGJSON's deck
files one by one would be about 1,800 requests (and 0.2-0.7 MB each). So the
lists are kept here in a compact index, INDEX in precons' cache folder
(gitignored), with only each deck's card names and counts:

    {"version": 1, "archive_at": <when the archive was last read>,
     "decks": {<file>: {"at": <when read>, "cards": [[name, count], ...], "total": cards}}}

It's filled from MTGJSON's AllDeckFiles archive (ARCHIVE_URL, one download of
about 150 MB, streamed and never saved), read again after ARCHIVE_TTL. A
deck listed since then, or one released in the last RECENT_DAYS (MTGJSON
fills a new set's lists in over its first weeks), is read on its own
(DECK_URL, or the copy Add a precon cached) once its entry is older than
precons.TTL, up to SINGLES a refresh. A refresh runs in a background thread
(one at a time) started by the ranking when something is due; meanwhile the
ranking shows the decks already read, and says how many there are. A failed
refresh isn't tried again for RETRY_AFTER. Nothing here writes to the repo.

    from decklab.lib import pool, precon_coverage
    precon_coverage.rank(pool.load_pool("user2"), kind="commander")   # {"decks", "date", "status"}

Command line (from the repo root; the first slice of E1-S24, read only):

    python -m decklab.lib.precons coverage [--space S] [--format commander|casual] [--limit N]
        the precons best covered by the space's free pool, best first (it reads the lists
        first when the index needs it, in the foreground)
"""
import argparse
import http.client
import json
import lzma
import tarfile
import threading
import time
import urllib.error
import urllib.request
from collections import Counter
from datetime import date, timedelta

from decklab.lib import cards, config, decks, precons

INDEX = "coverage.json"
VERSION = 1
ARCHIVE_URL = "https://mtgjson.com/api/v5/AllDeckFiles.tar.xz"
ARCHIVE_TTL = 30 * 24 * 60 * 60     # seconds: published precon lists rarely change once complete
MAX_ARCHIVE_BYTES = 512 * 1024 * 1024   # AllDeckFiles.tar.xz was 147.5 MB on 2026-10-28
ARCHIVE_TIMEOUT = 120               # seconds per socket operation of the archive's download
RECENT_DAYS = 120                   # a deck released since (or not yet): its list is read again after precons.TTL
SINGLES = 60                        # decks read on their own in one refresh
PAUSE = 0.2                         # seconds between them, to be gentle with MTGJSON
RETRY_AFTER = 60 * 60               # seconds after a failed refresh before another
SAVE_EVERY = 25                     # decks read on their own between saves of the index
FORMATS = ("commander", "casual")

_lock = threading.Lock()            # the index in memory, _state and the index's file
_state = {"running": False, "failed": None, "error": None}
_kept = {}                          # path -> ((mtime_ns, size), index)
_needs = {}                         # (file, at) -> Counter of canonical non-basic names, see _need


def _path():
    return precons._cache_dir() / INDEX


def _empty():
    return {"version": VERSION, "archive_at": None, "decks": {}}


def _index():
    """The index (see the module's docstring), read from its file once a change of it; an
    empty one when there's none or it can't be read."""
    path = _path()
    with _lock:
        try:
            stat = path.stat()
        except OSError:
            return _kept.get(path, (None, _empty()))[1]
        key = (stat.st_mtime_ns, stat.st_size)
        kept = _kept.get(path)
        if kept and kept[0] == key:
            return kept[1]
        try:
            index = json.loads(path.read_text(encoding="utf-8"))
            if not (isinstance(index, dict) and index.get("version") == VERSION
                    and isinstance(index.get("decks"), dict)):
                raise ValueError("not an index")
        except (OSError, ValueError):
            index = _empty()
        _kept[path] = (key, index)
        return index


def _save(index):
    """Write index as the index's file (and keep it in memory). Callers hold _lock."""
    path = _path()
    data = json.dumps(index, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_bytes(data)
        tmp.replace(path)
        stat = path.stat()
        _kept[path] = ((stat.st_mtime_ns, stat.st_size), index)
    except OSError:
        _kept[path] = (None, index)         # used now, saved by the next refresh


def _entry(data, now):
    """A deck's index entry from its MTGJSON data: every readable card of its boards (not the
    display commander), counted by name."""
    counts = Counter()
    for line in precons.cards_of(data)["lines"]:
        counts[line["name"]] += line["count"]
    return {"at": now, "cards": sorted([name, n] for name, n in counts.items()), "total": sum(counts.values())}


def _recent(deck, today):
    return not deck["released"] or deck["released"] >= (today - timedelta(days=RECENT_DAYS)).isoformat()


def _due(index, listed, now, today):
    """The listed decks to read on their own: not in the index, or recent and older than precons.TTL."""
    have = index["decks"]
    return [d["file"] for d in listed if d["file"] not in have
            or (_recent(d, today) and now - have[d["file"]].get("at", 0) >= precons.TTL)]


def _archive_due(index, now):
    return not index.get("archive_at") or now - index["archive_at"] >= ARCHIVE_TTL


def _open_archive():
    """The archive's download, as a file object (the tests replace it)."""
    request = urllib.request.Request(ARCHIVE_URL, headers={"User-Agent": config.USER_AGENT})
    return urllib.request.urlopen(request, timeout=ARCHIVE_TIMEOUT)


class _Capped:
    """A file object read up to limit bytes, then an error (a stream has no size to check first)."""

    def __init__(self, raw, limit):
        self.raw, self.left = raw, limit

    def read(self, size=-1):
        data = self.raw.read(size if size is not None and size >= 0 else self.left + 1)
        self.left -= len(data)
        if self.left < 0:
            raise precons.PreconError(f"MTGJSON's deck archive is bigger than {MAX_ARCHIVE_BYTES // (1024 * 1024)} MB")
        return data


def _read_archive(files, now):
    """{file: entry} for the listed files the archive holds, streamed member by member."""
    found = {}
    response = _open_archive()
    try:
        with tarfile.open(fileobj=_Capped(response, MAX_ARCHIVE_BYTES), mode="r|xz") as archive:
            for member in archive:
                name = member.name.rsplit("/", 1)[-1]
                file = name[:-5] if name.endswith(".json") else None
                if file not in files or not member.isfile() or member.size > precons.MAX_DECK_BYTES:
                    continue
                handle = archive.extractfile(member)
                try:
                    data = json.loads(handle.read()).get("data")
                except (ValueError, AttributeError):
                    continue
                if isinstance(data, dict):
                    found[file] = _entry(data, now)
    finally:
        close = getattr(response, "close", None)
        if close:
            close()
    return found


def _read_one(file, now):
    """One deck's entry: from the copy Add a precon cached while it's fresh, else fetched (and
    not kept: the index is what's kept)."""
    path = precons._cache_dir() / "decks" / f"{file}.json"
    try:
        if now - path.stat().st_mtime < precons.TTL:
            data = json.loads(path.read_text(encoding="utf-8")).get("data")
            if isinstance(data, dict):
                return _entry(data, now)
    except (OSError, ValueError, AttributeError):
        pass
    raw = json.loads(precons._fetch(precons.DECK_URL.format(file), precons.MAX_DECK_BYTES))
    data = raw.get("data") if isinstance(raw, dict) else None
    if not isinstance(data, dict):
        raise ValueError(f"MTGJSON's file for {file} isn't a deck")
    return _entry(data, now)


_FAILURES = (OSError, ValueError, EOFError, lzma.LZMAError, tarfile.TarError, urllib.error.URLError,
             http.client.HTTPException, precons.PreconError)


def refresh(listed=None, now=None, today=None):
    """Bring the index up to date for listed (deck_list()'s decks; read when None): the archive
    when it's due, then up to SINGLES due decks on their own. Returns the problems met, in words
    (a deck that couldn't be read is left as it was, and tried again next time)."""
    now = time.time() if now is None else now
    today = date.today() if today is None else today
    listed = precons.deck_list()["decks"] if listed is None else listed
    problems = []
    index = _index()
    index = {**index, "decks": dict(index["decks"])}    # a copy: readers keep the one they have
    if _archive_due(index, now):
        try:
            index["decks"].update(_read_archive({d["file"] for d in listed}, now))
            index["archive_at"] = now
        except _FAILURES as e:
            problems.append(f"MTGJSON's deck archive couldn't be read ({precons._text(str(e), 300) or type(e).__name__})")
        with _lock:
            _save(dict(index, decks=dict(index["decks"])))    # a copy: the singles below add to index
    for n, file in enumerate(_due(index, listed, now, today)[:SINGLES]):
        if n:
            time.sleep(PAUSE)
        try:
            index["decks"][file] = _read_one(file, now)
        except _FAILURES as e:
            problems.append(f"{file} couldn't be read ({precons._text(str(e), 300) or type(e).__name__})")
            if isinstance(e, (OSError, urllib.error.URLError, http.client.HTTPException)):
                break                       # MTGJSON is down: the rest would fail the same way
        if n % SAVE_EVERY == SAVE_EVERY - 1:
            with _lock:
                _save(dict(index, decks=dict(index["decks"])))
    with _lock:
        _save(index)
    return problems


def _start(work):
    """Run work in a daemon thread (the tests run it straight away)."""
    threading.Thread(target=work, name="precon-coverage", daemon=True).start()


def ensure(listed, index=None, now=None, today=None):
    """Start a background refresh when the index needs one and none is running or resting
    after a failure. Returns whether one is running."""
    now = time.time() if now is None else now
    today = date.today() if today is None else today
    index = _index() if index is None else index
    with _lock:
        resting = _state["failed"] is not None and time.monotonic() - _state["failed"] < RETRY_AFTER
        if _state["running"] or resting or not (_archive_due(index, now) or _due(index, listed, now, today)):
            return _state["running"]
        _state["running"] = True

    def work():
        try:
            problems = refresh(listed)
        except Exception as e:      # a background thread has no caller to tell: kept for the page
            problems = [f"The precon lists couldn't be read ({type(e).__name__})"]
        with _lock:
            _state.update(running=False, error=problems[0] if problems else None,
                          failed=time.monotonic() if problems else None)

    try:
        _start(work)
    except RuntimeError:            # no thread could be started: tried again by the next ranking
        with _lock:
            _state["running"] = False
    with _lock:
        return _state["running"]


def _canonical(name):
    """The exact Scryfall name (as the pool counts it), or the name as MTGJSON wrote it."""
    if decks.is_basic_land(name):
        return name
    return cards.resolve(name) or name


def _need(file, entry):
    """Copies of each non-basic card the deck lists, by canonical name (kept per entry)."""
    key = (file, entry.get("at"))
    need = _needs.get(key)
    if need is None:
        need = Counter()
        for name, count in entry.get("cards", []):
            name = _canonical(name)
            if not decks.is_basic_land(name):
                need[name] += count
        if len(_needs) > 20000:
            _needs.clear()
        _needs[key] = need
    return need


def kind_of(deck):
    """"commander" for a Commander precon, else "casual" (the format the ranking filters by)."""
    return "commander" if deck["type"] == "Commander Deck" else "casual"


def coverage(need, free):
    """(cards, covered) of a Counter of needed cards against free copies."""
    return sum(need.values()), sum(min(n, free.get(name, 0)) for name, n in need.items())


def rank(p, kind=None, deck_type=None, background=True):
    """The listed precons the index has read, best covered by p's free copies first:
    {"date" (MTGJSON's build), "decks": [deck_list() entry plus "kind", "cards" (non-basic
    cards), "covered", "missing", "share" (covered / cards)], "types" (the deck types of
    that format), "status": {"listed", "indexed" (of those, the decks read), "updating", "error"
    (the last refresh's first problem, or None), "read_at" (when the archive was read)}}. kind: "commander" or
    "casual" (None: both); deck_type: one of precons.TYPES (None: every one). background: start
    a refresh when one is due. PreconError when MTGJSON's deck list can't be had."""
    listed = precons.deck_list()
    updating = ensure(listed["decks"]) if background else False
    index = _index()
    free = _free(p)
    rows, types = [], set()
    shown = [d for d in listed["decks"] if kind in (None, kind_of(d))]
    for d in shown:
        types.add(d["type"])
        entry = index["decks"].get(d["file"])
        if deck_type not in (None, d["type"]) or entry is None:
            continue
        total, covered = coverage(_need(d["file"], entry), free)
        if total:
            rows.append({**d, "kind": kind_of(d), "cards": total, "covered": covered, "missing": total - covered,
                         "share": round(covered / total, 4)})
    rows.sort(key=lambda r: (r["released"], r["name"]), reverse=True)
    rows.sort(key=lambda r: (-r["covered"] / r["cards"], r["missing"]))
    with _lock:
        error = _state["error"]
    return {"date": listed["date"], "decks": rows, "types": sorted(types),
            "status": {"listed": len(shown), "indexed": sum(1 for d in shown if d["file"] in index["decks"]),
                       "updating": updating, "error": error,
                       "read_at": index.get("archive_at")}}


def _free(p):
    from decklab.lib import pool
    return pool.free_copies(p)


def main(argv=None):
    import sys

    from decklab.lib import inventory, pool, spaces
    from decklab.lib.inventory import entry
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    parser = argparse.ArgumentParser(prog="python -m decklab.lib.precons coverage",
                                     description="Precons ranked by how much of each the space's free pool covers.")
    parser.add_argument("--space", default=spaces.HOME, help="whose pool: home (default) or a person's space")
    parser.add_argument("--format", choices=FORMATS, dest="kind", help="only Commander or only 60-card precons")
    parser.add_argument("--limit", type=int, default=20, help="how many to print (default 20)")
    args = parser.parse_args(argv)
    try:
        listed = precons.deck_list()["decks"]
        now = time.time()
        index = _index()
        if _archive_due(index, now) or _due(index, listed, now, date.today()):
            print("Reading MTGJSON's precon lists (the first time downloads about 150 MB)...", flush=True)
            for problem in refresh(listed):
                print(f"  {problem}")
        with entry.command():       # the venv, and one inventory snapshot for the command
            result = rank(pool.load_pool(args.space), args.kind, background=False)
    except (precons.PreconError, inventory.Unavailable) as e:
        print(e, file=sys.stderr)
        return 2
    except (spaces.SpaceNotFound, FileNotFoundError, RuntimeError, ValueError) as e:
        print(e, file=sys.stderr)   # an unknown space, no card index yet, an unreadable pool
        return 1
    for d in result["decks"][:max(args.limit, 0)]:
        released = f", {d['released'][:4]}" if d["released"] else ""
        print(f"{d['share']:5.0%}  {d['covered']:3}/{d['cards']:<3} {d['name']} "
              f"({d['set_name'] or d['code'].upper()}, {d['type']}{released})")
    status = result["status"]
    print(f"{status['indexed']} of {status['listed']} precons' lists read; MTGJSON's lists of "
          f"{result['date'] or 'an unknown date'}.")
    return 0
