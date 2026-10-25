"""Precons: the published card lists of preconstructed decks, from MTGJSON,
for the Collection page's "Add a precon" (lib/api/precons.py).

MTGJSON lists every deck it has in DeckList.json (LIST_URL) and gives each
one's cards in decks/<fileName>.json (DECK_URL), with the set, collector
number and finish of every card and the address of the list it came from
(usually Wizards' own); SetList.json (SETS_URL) gives the sets' names. All
are kept in CACHE (gitignored) for TTL, and what's read from the lists is
kept in memory until their files change. A copy older than TTL is fetched
again; when MTGJSON can't be reached, the old copy is used, and with no
copy at all the call is PreconError. A failed fetch isn't tried again for
RETRY_AFTER, so a slow or broken MTGJSON costs one timeout, not one a
request. Nothing here writes to the repo.

Only DeckList.json's file names are ever fetched (FILE_RE, and listed), and
only types of paper deck (TYPES): Secret Lair drops, online-only decks and
the like are left out. A deck's cards are read defensively:
anything that isn't a sensible name, set, number or count is left out and
reported, never guessed (cards_of()).

    from decklab.lib import precons
    precons.search("keen")              # ([{"file", "name", "code", "set_name", "type", "released", "source"}], more)
    precons.find("KeenEngineering_FDC") # one of those, or None
    precons.cards_of(precons.deck("KeenEngineering_FDC"))
"""
import http.client
import json
import re
import threading
import time
import urllib.error
import urllib.request

from decklab.lib import cards, config

LIST_URL = "https://mtgjson.com/api/v5/DeckList.json"
SETS_URL = "https://mtgjson.com/api/v5/SetList.json"
DECK_URL = "https://mtgjson.com/api/v5/decks/{}.json"
CACHE = None                        # None: config.DATA / "mtgjson" (tests patch this)
# MTGJSON builds about once a day. A deck's file is kept no longer than the
# lists, so one MTGJSON hadn't finished (cards missing) is put right by its next build.
TTL = 24 * 60 * 60                  # seconds
RETRY_AFTER = 10 * 60               # seconds after a failed fetch before MTGJSON is asked again
TIMEOUT = 30                        # seconds per socket operation
MAX_LIST_BYTES = 16 * 1024 * 1024   # DeckList.json was 0.6 MB on 2026-10-10
MAX_SETS_BYTES = 64 * 1024 * 1024   # SetList.json was 11.7 MB on 2026-10-10
MAX_DECK_BYTES = 8 * 1024 * 1024    # a Commander deck's file was 0.2-0.7 MB
MAX_COUNT = 250                     # copies of one card in one deck
FILE_RE = re.compile(r"[A-Za-z0-9_]{1,120}")
SET_RE = re.compile(r"[A-Za-z0-9]{2,8}")
NUMBER_RE = re.compile(r"[A-Za-z0-9★†\-]{1,12}")
WIZARDS_RE = re.compile(r"https?://([a-z0-9-]+\.)*wizards\.com(/|$)", re.IGNORECASE)

# MTGJSON's deck types that are paper decks someone could own and play.
# Left out: Secret Lair drops (not decks), MTGO and Arena decks, land packs,
# Deck Builder's Toolkits, Welcome Boosters and other promo bundles, Brawl
# and Challenge (Horde) decks, which aren't 60-card or Commander decks, and
# World Championship and Pro Tour decks, whose gold-bordered cards a deck
# line can't name (lib/api/card_lookup.py, _pickable).
TYPES = frozenset((
    "Commander Deck", "Jumpstart", "Theme Deck", "Intro Pack", "Box Set", "Welcome Deck", "Duel Deck",
    "Sample Deck", "Planeswalker Deck", "Event Deck", "Challenger Deck",
    "Starter Deck", "Enhanced Deck", "Game Night Deck", "Starter Kit", "Advanced Deck", "Planechase Deck",
    "Guild Kit", "Clash Pack", "Advanced Pack", "Demo Deck", "Archenemy Deck",
    "Pioneer Challenger Deck", "Halfdeck", "Spellslinger Starter Kit", "Premium Deck", "Modern Event Deck",
))
# The parts of a deck file whose cards go into the collection, and the deck
# section each one becomes. DISPLAY is the card in the box's window, not
# part of the deck: from 2022 to mid-2024 a foil-etched copy of the commander,
# a real card for the collection; before that an oversized or thick-stock
# display card, which the caller leaves out (cards_of's "display"). The
# planes and schemes of Planechase and Archenemy decks are only counted.
BOARDS = (("commander", "Commander"), ("mainBoard", "Deck"), ("sideBoard", "Sideboard"))
DISPLAY = "displayCommander"
LEFT_OUT = (("planes", "plane"), ("schemes", "scheme"))

_lock = threading.Lock()            # held for every _load, so one fetch serves everyone waiting for it
_failed = {}                        # url -> time.monotonic() of its last failed fetch
_kept = {}                          # path -> ((mtime_ns, size), what read() made of it), see _copy


class PreconError(Exception):
    """MTGJSON couldn't be reached and nothing is cached, or it sent something unreadable."""


def _cache_dir():
    return CACHE if CACHE is not None else config.DATA / "mtgjson"


def _fetch(url, limit):
    request = urllib.request.Request(url, headers={"User-Agent": config.USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        data = response.read(limit + 1)
    if len(data) > limit:
        raise PreconError(f"{url} is bigger than {limit // (1024 * 1024)} MB")
    return data


def _copy(path, read):
    """read(the JSON in path), or the JSON itself without read. With read,
    the result is kept in memory (_kept) and given again while the file's
    time and size stay the same, so a list is read once a build, not once a
    request."""
    stat = path.stat()
    key = (stat.st_mtime_ns, stat.st_size)
    kept = _kept.get(path) if read else None
    if kept and kept[0] == key:
        return kept[1]
    parsed = json.loads(path.read_text(encoding="utf-8"))
    if not read:
        return parsed
    result = read(parsed)
    _kept[path] = (key, result)
    return result


def _load(path, url, ttl, limit, read=None):
    """read(the JSON at url) (see _copy): from path while it's younger than
    ttl seconds, else fetched and saved there; from an older copy when the
    fetch fails, or failed less than RETRY_AFTER ago. Callers hold _lock."""
    try:
        age = time.time() - path.stat().st_mtime
    except OSError:
        age = None                          # no copy
    failed = _failed.get(url)
    resting = failed is not None and time.monotonic() - failed < RETRY_AFTER
    if age is not None and (age < ttl or resting):
        try:
            return _copy(path, read)
        except (OSError, ValueError):
            pass
    if resting:
        raise PreconError("MTGJSON's deck lists couldn't be fetched a few minutes ago; try again later.")
    try:
        data = _fetch(url, limit)
        parsed = json.loads(data)
        if not isinstance(parsed, dict) or not isinstance(parsed.get("data"), (dict, list)):
            raise ValueError("no data")
    except (OSError, ValueError, urllib.error.URLError, http.client.HTTPException, PreconError) as e:
        _failed[url] = time.monotonic()
        if age is not None:
            try:
                return _copy(path, read)
            except (OSError, ValueError):
                pass
        raise PreconError(f"MTGJSON's deck lists couldn't be fetched ({e}); try again later.") from None
    _failed.pop(url, None)
    result = read(parsed) if read else parsed
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_bytes(data)
        tmp.replace(path)                   # can fail on Windows while a virus scanner has the file open
        if read:
            stat = path.stat()
            _kept[path] = ((stat.st_mtime_ns, stat.st_size), result)
    except OSError:
        pass                                # used now, fetched again next time
    return result


def _text(value, limit=200):
    return value.strip() if isinstance(value, str) and value.strip() and len(value) <= limit else None


def _read_set_names(raw):
    names = {}
    for item in raw.get("data") if isinstance(raw.get("data"), list) else []:
        if isinstance(item, dict) and isinstance(item.get("code"), str) and _text(item.get("name")):
            names[item["code"].lower()] = item["name"].strip()
    return names


def _set_names():
    """{set code (lower case): name}, or {} when SetList.json can't be had:
    a deck's set name is only a help for finding it."""
    try:
        with _lock:
            return _load(_cache_dir() / "SetList.json", SETS_URL, TTL, MAX_SETS_BYTES, _read_set_names)
    except PreconError:
        return {}


def _read_deck_list(raw):
    """deck_list() from DeckList.json's JSON, without the set names."""
    decks = []
    for item in raw.get("data") if isinstance(raw.get("data"), list) else []:
        if not isinstance(item, dict) or item.get("type") not in TYPES:
            continue
        file, name, code = _text(item.get("fileName")), _text(item.get("name")), _text(item.get("code"), 8)
        if not (file and FILE_RE.fullmatch(file) and name and code and SET_RE.fullmatch(code)):
            continue
        released = item.get("releaseDate") if isinstance(item.get("releaseDate"), str) \
            and re.fullmatch(r"\d{4}-\d{2}-\d{2}", item["releaseDate"]) else ""
        source = item.get("source") if isinstance(item.get("source"), str) \
            and re.fullmatch(r"https?://[^\s\"<>]{1,500}", item["source"]) else ""
        decks.append({"file": file, "name": name, "code": code.lower(), "type": item["type"],
                      "released": released, "source": source})
    decks.sort(key=lambda d: (d["released"], d["code"], d["name"]), reverse=True)
    meta = raw.get("meta") if isinstance(raw.get("meta"), dict) else {}
    return {"date": meta.get("date") if isinstance(meta.get("date"), str) else "", "decks": decks}


def deck_list():
    """{"date": MTGJSON's build date, "decks": [entry]} of the paper decks
    (TYPES), newest first. An entry is {"file", "name", "code" (the set code,
    lower case), "set_name" (or ""), "type", "released" (YYYY-MM-DD or ""),
    "source" (where MTGJSON's list came from: usually Wizards' page, see
    from_wizards(); or "")}."""
    with _lock:
        listed = _load(_cache_dir() / "DeckList.json", LIST_URL, TTL, MAX_LIST_BYTES, _read_deck_list)
    set_names = _set_names()
    return {"date": listed["date"],
            "decks": [dict(d, set_name=set_names.get(d["code"], "")) for d in listed["decks"]]}


def from_wizards(source):
    """True when a deck's source is a page on Wizards' own site."""
    return bool(source) and WIZARDS_RE.match(source) is not None


def search(query, limit=40):
    """(decks, more, date): the paper decks whose name, set code, set name
    or type hold every word of query (ignoring case and accents), newest
    first; the newest when query is blank. more says whether limit cut the
    list short; date is MTGJSON's build date (deck_list())."""
    words = cards.fold(query or "").split()
    listed = deck_list()
    found = []
    for d in listed["decks"]:
        text = cards.fold(f"{d['name']} {d['code']} {d['set_name']} {d['type']}")
        if all(w in text for w in words):
            found.append(d)
            if len(found) > limit:
                break
    return found[:limit], len(found) > limit, listed["date"]


def find(file):
    """The paper deck with that file name, or None."""
    if not isinstance(file, str) or not FILE_RE.fullmatch(file):
        return None
    return next((d for d in deck_list()["decks"] if d["file"] == file), None)


def deck(file):
    """A listed deck's data (MTGJSON's "data" object). PreconError when it
    can't be fetched or isn't a deck; LookupError for a file not listed."""
    if find(file) is None:
        raise LookupError(file)
    with _lock:
        raw = _load(_cache_dir() / "decks" / f"{file}.json", DECK_URL.format(file), TTL, MAX_DECK_BYTES)
    data = raw.get("data")
    if not isinstance(data, dict):
        raise PreconError(f"MTGJSON's file for {file} isn't a deck")
    return data


def _finish(card):
    if card.get("isEtched") is True:
        return "etched"
    return "foil" if card.get("isFoil") is True else "nonfoil"


def _count(card):
    """A card entry's count when it's a sensible one, else None."""
    count = card.get("count") if isinstance(card, dict) else None
    return count if isinstance(count, int) and not isinstance(count, bool) and 1 <= count <= MAX_COUNT else None


def _line(card):
    """{"name", "set" (lower case), "number", "finish", "count", "full_art"}
    of a card entry, or None when any of it can't be read."""
    card = card if isinstance(card, dict) else {}
    name, code, number, count = _text(card.get("name")), card.get("setCode"), card.get("number"), _count(card)
    if not (name and isinstance(code, str) and SET_RE.fullmatch(code) and isinstance(number, str)
            and NUMBER_RE.fullmatch(number) and count):
        return None
    return {"name": name, "set": code.lower(), "number": number, "finish": _finish(card), "count": count,
            "full_art": card.get("isFullArt") is True}


def _entries(data, board):
    """The board's card entries, or [] when it isn't a list."""
    entries = data.get(board)
    return entries if isinstance(entries, list) else []


def cards_of(data):
    """A deck's data, read: {"lines", "display", "problems", "left_out",
    "tokens"}. lines: [{"section" (Commander, Deck or Sideboard), "name",
    "set" (lower case), "number", "finish", "count", "full_art"}], in
    MTGJSON's order. display: the display commanders, as lines without a
    section (unreadable ones are left out). problems: what couldn't be read,
    in words. left_out: {"plane": 10, ...} for cards not added (LEFT_OUT).
    tokens: [{"name", "count"}]."""
    lines, problems = [], []
    for board, section in BOARDS:
        entries = data.get(board) or []
        if not isinstance(entries, list):
            problems.append(f"MTGJSON's {board} isn't a list of cards")
            continue
        for card in entries:
            line = _line(card)
            if line is None:
                card = card if isinstance(card, dict) else {}
                problems.append(f"A card in MTGJSON's {board} can't be read ({_text(card.get('name')) or 'no name'}, "
                                f"{card.get('setCode')!s:.8} {card.get('number')!s:.12}, "
                                f"count {card.get('count')!s:.6})")
                continue
            lines.append({"section": section, **line})
    display = [line for line in map(_line, _entries(data, DISPLAY)) if line]
    left_out = {}
    for board, words in LEFT_OUT:
        n = sum(_count(c) or 0 for c in _entries(data, board))
        if n:
            left_out[words] = n
    tokens = {}
    for card in _entries(data, "tokens"):
        name, count = _text(card.get("name")) if isinstance(card, dict) else None, _count(card)
        if name and count:
            tokens[name] = tokens.get(name, 0) + count
    return {"lines": lines, "display": display, "problems": problems, "left_out": left_out,
            "tokens": [{"name": n, "count": c} for n, c in sorted(tokens.items())]}
