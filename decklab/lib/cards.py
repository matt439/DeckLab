"""Scryfall card data for Deck Lab: bulk download, lookups, roles, prices, images.

Usage (from the repo root):
    python -m decklab.lib.cards update [--force]    download stale bulk files, rebuild the index
    python -m decklab.lib.cards show "Card Name"    print what the index knows about a card
    python -m decklab.lib.cards search TEXT         try the name autocomplete

`update` downloads Scryfall's `default_cards` and `oracle_tags` bulk files into
decklab/data/scryfall/ when they're missing or more than a week old (--force
downloads them anyway), then rebuilds the small index everything else reads
(decklab/data/scryfall/index.json.gz). Later start-ups only load the index.
It also refreshes Commander Spellbook's combo list (decklab.lib.combos) on the
same schedule, and once a day checks Wizards' sitemap for the newest Commander
announcement (decklab.lib.official_lists), each a separate step whose failure
never fails the update.
When Scryfall can't be reached or a download is cut off, the local files are
kept and used; it only fails when there's no local copy at all. The index
itself is built from the bulk files by decklab.lib.card_index.

From code:

    from decklab.lib import cards
    cards.card("Llanowar Elves")       # card fields, or None (exact Scryfall name only)
    cards.resolve("fire")              # "Fire // Ice": any case, or a front face alone
    cards.printing("fdn", "227")       # one printing, or None
    cards.printing_card("ust", "49a")  # the card a printing is (Un-set variants included)
    cards.search_names("llan", 10)     # autocomplete: prefix matches first
    cards.close_names("Llanowar Elfs")  # "did you mean": ["Llanowar Elves", ...]
    cards.roles("Fire // Ice")         # {"removal", "burn", "draw"}
    cards.game_changers()              # names with Scryfall's game_changer flag
    cards.tag_members(["extra-turn"])  # {"extra-turn": frozenset of oracle ids}, any oracle tag
    cards.cheapest_usd("Thragtusk")    # (0.24, "ncc", "316", "nonfoil")
    cards.price_aud("Thragtusk")       # Price: an AUD estimate plus its rate and dates
    cards.image_path("fdn", "227")     # local .jpg, downloaded the first time
    cards.tokens_for("Hare Apparent")  # ([token entries], [unresolved part names]): what a card makes
    cards.token(oracle_id)             # one token, emblem or reminder entry (plus "id"), or None
    cards.token_face("the monarch")    # "The Monarch": exact token/reminder face name, or None
    cards.token_face_names()           # every token, emblem and reminder face name, sorted
    cards.token_faces_at("tltr", "H13")  # (oracle id, face names) of a token printing, or None

Functions that take a card name accept anything resolve() accepts and raise
KeyError for unknown cards; card() itself only takes exact names.

A multi-face card's type_line and mana_cost are its front face's (the creature
half of an adventure, the front of a transform, modal or flip card), since
that's what it is in the library and in hand; a split card keeps both halves'.
Every face is in card["faces"].

Tokens, emblems and reminder cards (The Monarch, The Ring // The Ring Tempts
You, dungeons) are kept apart from the cards, keyed by oracle id: different
tokens share names (8 Zombies, 23 Spirits). What a card makes comes from
Scryfall's all_parts links, unioned across its printings; it's approximate
(tokens made only through rules text, and most copies, aren't linked).

Prices are estimates: the USD price of the cheapest non-foil paper printing
times the ECB USD->AUD rate from Frankfurter (a foil or etched price only when
no printing has a non-foil one). AGENTS.md requires showing the rate, its date
and the price date with every AUD figure; Price.label() does.
"""
import argparse
import gzip
import http.client
import json
import os
import re
import sys
import tempfile
import threading
import time
import urllib.request
import zlib
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

from decklab.lib import card_index
# Owned by card_index and re-exported (cards.fold, cards.ROLES, cards.build_index...).
from decklab.lib.card_index import FACE_FIELDS, INDEX_VERSION, ROLE_TAGS, ROLES, build_index, fold
from decklab.lib.config import DATA, USER_AGENT

SCRYFALL_DIR = DATA / "scryfall"
INDEX_FILE = SCRYFALL_DIR / "index.json.gz"
BULK_META_FILE = SCRYFALL_DIR / "bulk.json"   # what was downloaded when, and what the index was built from
FX_FILE = DATA / "fx.json"
IMAGES_DIR = DATA / "images"

BULK_LIST_URL = "https://api.scryfall.com/bulk-data"
FX_URL = "https://api.frankfurter.dev/v1/latest?from=USD&to=AUD"
BULK_TYPES = ("default_cards", "oracle_tags")
MAX_BULK_AGE = timedelta(days=7)
IMAGE_SIZES = ("small", "normal", "small-back", "normal-back",
               "large", "art_crop", "large-back", "art_crop-back")
# Sizes the card index doesn't store: their Scryfall URL is the stored normal one's with the size's
# folder in place of /normal/ (cards.scryfall.io/normal/front/... -> /large/front/...), so the index
# needn't be rebuilt for them. large is 672 x 936; art_crop is the art alone, about 626 x 457.
DERIVED_IMAGE_SIZES = {"large": "normal", "art_crop": "normal", "large-back": "normal-back",
                       "art_crop-back": "normal-back"}
MIN_REQUEST_GAP = 0.1   # seconds between requests, so at most ~10 per second overall
FX_RETRY_GAP = 300      # seconds between rate fetches while no rate is cached at all

# What a failed or cut-off request raises. A response that ends early raises
# http.client.IncompleteRead, which isn't an OSError; bad JSON is a ValueError.
NETWORK_ERRORS = (OSError, ValueError, http.client.HTTPException)

# What reading a missing, cut-off, damaged or out-of-date index can raise: a
# damaged gzip stream raises zlib.error, which isn't an OSError.
INDEX_ERRORS = (OSError, EOFError, ValueError, RuntimeError, KeyError, zlib.error)

# The image cache is capped, so requests for every printing (118,000 of them,
# about 12 GB) can't fill the disk. Decks need a few hundred images; the cap
# holds about 10,000 cards in both sizes. Past it, the images used least
# recently are deleted until the cache is back under IMAGE_CACHE_KEEP of it.
IMAGE_CACHE_MAX = 1_000_000_000         # bytes
IMAGE_CACHE_KEEP = 0.9
IMAGE_TOUCH_AGE = 24 * 60 * 60          # seconds: a cached image used again is marked as used

# Left out when finding the cheapest printing: memorabilia is gold-bordered
# World Championship decks, Collectors' Edition and 30th Anniversary cards
# (non-standard backs), Heroes of the Realm and the like. Oversized cards are
# left out too. Without this about 230 cards would be "cheapest" in one of them.
UNPLAYABLE_PRICE_SET_TYPES = {"memorabilia"}

# Price fields of a printing, in the order they're preferred (AGENTS.md: non-foil).
PRICE_FINISHES = (("nonfoil", "usd"), ("foil", "usd_foil"), ("etched", "usd_etched"))


# --- HTTP -----------------------------------------------------------------

_request_lock = threading.Lock()
_last_request = 0.0


def _open_url(url, accept="application/json", timeout=60, headers=None):
    """Open url with the Deck Lab User-Agent, spacing requests MIN_REQUEST_GAP apart.
    headers adds more request headers (a conditional request's If-None-Match)."""
    global _last_request
    with _request_lock:
        wait = _last_request + MIN_REQUEST_GAP - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _last_request = time.monotonic()
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": accept,
                                                   **(headers or {})})
    return urllib.request.urlopen(request, timeout=timeout)


def _get_json(url, timeout=60):
    with _open_url(url, timeout=timeout) as response:
        return json.load(response)


def _download(url, dest, accept="*/*", timeout=60, headers=None, response_headers=None):
    """Stream url to dest through a temp file, so a failed download never leaves
    half a file behind. Returns the number of bytes written. headers adds request
    headers; response_headers, a dict, gets the response's headers. A 304 (Not
    Modified) answer to a conditional request raises urllib.error.HTTPError,
    leaving dest as it was."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=dest.parent, prefix=dest.name + ".", suffix=".part")
    try:
        with os.fdopen(fd, "wb") as out, _open_url(url, accept, timeout=timeout, headers=headers) as response:
            if response_headers is not None:
                response_headers.update(response.headers.items())
            expected = response.headers.get("Content-Length")
            size = 0
            while chunk := response.read(1 << 20):
                out.write(chunk)
                size += len(chunk)
        if expected and int(expected) != size:
            raise OSError(f"{url}: got {size} bytes, expected {expected}")
        os.replace(tmp, dest)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return size


def _read_json(path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp, path)


# --- Bulk download ----------------------------------------------------------

def bulk_path(kind):
    return SCRYFALL_DIR / f"{kind}.jsonl.gz"


def _is_stale(kind, meta):
    info = meta.get(kind)
    if not info or not bulk_path(kind).exists():
        return True
    return card_index._now() - datetime.fromisoformat(info["downloaded_at"]) > MAX_BULK_AGE


def _no_data_error(url, error):
    return RuntimeError(f"Couldn't download Scryfall's card data ({url}): {error}. There's no "
                        f"local copy yet, so connect to the internet and run: "
                        f"python -m decklab.lib.cards update")


def download_bulk(force=False, log=print):
    """Download each bulk file that is missing or over a week old (all of them
    with force). Returns the kinds that were downloaded.

    When Scryfall can't be reached or a download is cut off, the local file is
    kept (a failed download never replaces it) and the next update tries
    again. Raises RuntimeError only when a file has no local copy to fall back on."""
    meta = _read_json(BULK_META_FILE, {})
    wanted = [kind for kind in BULK_TYPES if force or _is_stale(kind, meta)]
    for kind in BULK_TYPES:
        if kind not in wanted:
            log(f"{kind}: fresh (Scryfall {meta[kind]['updated_at'][:10]}, "
                f"downloaded {meta[kind]['downloaded_at'][:10]})")
    if not wanted:
        return []

    try:
        listing = {entry["type"]: entry for entry in _get_json(BULK_LIST_URL)["data"]}
    except NETWORK_ERRORS + (KeyError, TypeError) as e:
        if not all(bulk_path(kind).exists() for kind in BULK_TYPES):
            raise _no_data_error(BULK_LIST_URL, e) from e
        log(f"Couldn't reach Scryfall ({e}); keeping the local bulk files.")
        return []

    downloaded = []
    for kind in wanted:
        entry = listing.get(kind) or {}
        old = meta.get(kind, {})
        if (not force and entry.get("updated_at") and old.get("updated_at") == entry["updated_at"]
                and bulk_path(kind).exists()):
            # Scryfall hasn't published anything newer; just restart the clock.
            old["downloaded_at"] = card_index._now().isoformat(timespec="seconds")
            log(f"{kind}: unchanged on Scryfall since {entry['updated_at'][:10]}")
            continue
        uri = entry.get("jsonl_download_uri")
        try:
            if not uri:
                raise ValueError(f"{BULK_LIST_URL} doesn't list a {kind} file")
            log(f"{kind}: downloading {uri}")
            started = time.monotonic()
            size = _download(uri, bulk_path(kind))
        except NETWORK_ERRORS as e:
            if not bulk_path(kind).exists():
                raise _no_data_error(uri or BULK_LIST_URL, e) from e
            log(f"{kind}: download failed ({e}); keeping the local file.")
            continue
        meta[kind] = {"updated_at": entry["updated_at"], "uri": uri,
                      "downloaded_at": card_index._now().isoformat(timespec="seconds")}
        _write_json(BULK_META_FILE, meta)     # saved per file, in case the next one fails
        log(f"  {size / 1e6:.1f} MB in {time.monotonic() - started:.0f} s")
        downloaded.append(kind)
    _write_json(BULK_META_FILE, meta)
    return downloaded


def _update_combos(force, log):
    """Commander Spellbook's combo list (decklab.lib.combos), a step of its own:
    it isn't one of BULK_TYPES, and nothing it raises fails the update or keeps
    the card index from being built. Tests patch this out."""
    try:
        from decklab.lib import combos
        combos.update(force=force, log=log)
    except Exception as e:      # noqa: BLE001 (the card index matters more)
        log(f"Combo list: not updated ({type(e).__name__}: {e}); keeping what's on the PC.")


def _update_official_lists(force, log):
    """The newest Commander announcement in Wizards' sitemap
    (decklab.lib.official_lists), a step of its own like _update_combos: nothing
    it raises fails the update. Tests patch this out."""
    try:
        from decklab.lib import official_lists
        official_lists.update(force=force, log=log)
    except Exception as e:      # noqa: BLE001 (the card index matters more)
        log(f"Official lists: not checked ({type(e).__name__}: {e}); keeping the last result.")


def write_index(index, path=INDEX_FILE):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with gzip.open(tmp, "wt", encoding="utf-8", compresslevel=6) as f:
        json.dump(index, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, path)


def update(force=False, log=print):
    """Download stale bulk files, then rebuild the index if it's missing or
    older than them. Returns True when the index was rebuilt. The combo list
    and the official lists' check come after the index (they don't need it), so
    their downloads never hold it up."""
    downloaded = download_bulk(force, log)
    try:
        return _update_index(force, downloaded, log)
    finally:
        _update_combos(force, log)
        _update_official_lists(force, log)


def _update_index(force, downloaded, log):
    """update()'s index step: rebuild the index if it's missing or older than
    the bulk files. Returns True when it was rebuilt."""
    global _index
    meta = _read_json(BULK_META_FILE, {})
    bulk_dates = {kind: meta.get(kind, {}).get("updated_at", "unknown") for kind in BULK_TYPES}
    stamp = {"version": INDEX_VERSION, **bulk_dates}
    if not force and not downloaded and INDEX_FILE.exists() and meta.get("index") == stamp:
        try:
            _get()          # an index that's damaged on disk is rebuilt, not kept
        except INDEX_ERRORS as e:
            log(f"The index can't be read ({e}); rebuilding it.")
        else:
            log(f"Index is up to date ({INDEX_FILE}).")
            return False

    log("Building the index...")
    started = time.monotonic()
    index = build_index(bulk_path("default_cards"), bulk_path("oracle_tags"), bulk_dates, log)
    write_index(index, INDEX_FILE)
    meta["index"] = stamp
    _write_json(BULK_META_FILE, meta)
    _index = None     # the next lookup loads the new index

    n_printings = sum(len(numbers) for numbers in index["printings"].values())
    log(f"Index: {len(index['cards']):,} cards, {n_printings:,} printings, "
        f"{INDEX_FILE.stat().st_size / 1e6:.1f} MB, built in {time.monotonic() - started:.0f} s")
    for role, info in index["roles"].items():
        in_index = sum(1 for c in index["cards"].values() if role in c["roles"])
        log(f"  {role:<13} tag {info['tag']:<13} {info['oracle_cards']:>6,} oracle cards "
            f"({in_index:,} names in the index)")
    changers = sum(1 for c in index["cards"].values() if c["game_changer"])
    log(f"  game changers: {changers}")
    makers = sum(1 for c in index["cards"].values() if "tokens" in c or "token_names" in c)
    log(f"  tokens, emblems and reminders: {len(index['tokens']):,} ({makers:,} cards make some)")
    return True


# --- Loading and lookups ----------------------------------------------------

@dataclass
class _Loaded:
    data: dict            # the index as stored
    by_key: dict          # fold(name) -> exact name, plus front faces of multi-face cards
    search_keys: list     # (fold(name), name, has a paper printing), sorted by name
    search_words: list    # for each search key: (its words joined by spaces, the words), see _words
    token_by_face: dict = field(default_factory=dict)   # fold(token face or full name) -> exact name
    token_names: list = field(default_factory=list)     # every token face and full name, sorted


_index = None
_index_lock = threading.Lock()

_WORD_RE = re.compile(r"[^\W_]+")


def _prepare(data):
    cards = data["cards"]
    by_key = {}
    for name in cards:                  # full names first, so a face never hides a card
        by_key.setdefault(fold(name), name)
    for name, card in cards.items():
        if " // " in name and card.get("faces"):
            by_key.setdefault(fold(card["faces"][0]["name"]), name)
    search_keys = [(fold(name), name, card["paper"]) for name, card in cards.items()]
    search_words = []
    for key, _, _ in search_keys:
        words = tuple(_words(key))
        search_words.append((" ".join(words), words))
    names = set()
    for entry in data.get("tokens", {}).values():
        names.update(entry["face_names"])
        names.add(entry["name"])
    token_names = sorted(names)
    token_by_face = {}
    for name in token_names:
        token_by_face.setdefault(fold(name), name)
    return _Loaded(data, by_key, search_keys, search_words, token_by_face, token_names)


def _words(folded):
    """The words of fold()ed text, apostrophes dropped ("lim-dul's vault":
    lim, duls, vault), so "ajanis" and "ajani's" are the same word."""
    return _WORD_RE.findall(folded.replace("'", ""))


def _starts_words(typed, words):
    """True if each typed word starts one of words, in order, not
    necessarily next to each other ("llan elv", "jace sculptor")."""
    i = 0
    for word in words:
        if word.startswith(typed[i]):
            i += 1
            if i == len(typed):
                return True
    return False


def _read_index(path):
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"No card index at {path}. Run: python -m decklab.lib.cards update")
    with gzip.open(path, "rt", encoding="utf-8") as f:
        data = json.load(f)
    if data.get("version") != INDEX_VERSION:
        raise RuntimeError(f"{path} is an older index format. Run: python -m decklab.lib.cards update")
    return _prepare(data)


def load(path=INDEX_FILE):
    """(Re)load the index from path; lookups use it from then on. Returns the index data."""
    global _index
    loaded = _read_index(path)
    with _index_lock:
        _index = loaded
    return loaded.data


def _get():
    """The loaded index, reading INDEX_FILE on first use."""
    global _index
    if _index is None:
        with _index_lock:
            if _index is None:
                _index = _read_index(INDEX_FILE)
    return _index


def info():
    """When the data was built and pulled, and the role tag counts."""
    data = _get().data
    return {"built_at": data["built_at"], "bulk": data["bulk"], "roles": data["roles"],
            "cards": len(data["cards"]), "tokens": len(data["tokens"])}


def card(name):
    """The card with this exact Scryfall name, or None. Treat the dict as read-only."""
    return _get().data["cards"].get(name)


def resolve(name):
    """Return the exact Scryfall name for name, or None if there's no such card.

    Accepts any case, missing accents, curly quotes, a multi-face card's front
    face alone ("fire" -> "Fire // Ice") and the doubled names Scryfall gives
    reversible printings ("Ghalta, Primal Hunger // Ghalta, Primal Hunger")."""
    loaded = _get()
    if name in loaded.data["cards"]:
        return name
    key = fold(name)
    if key in loaded.by_key:
        return loaded.by_key[key]
    # "A // B // C": accept it if some leading part is a card and every part
    # after it is a face (or the name) of that same card.
    parts = key.split(" // ")
    for i in range(len(parts) - 1, 0, -1):
        head = loaded.by_key.get(" // ".join(parts[:i]))
        if head is None:
            continue
        entry = loaded.data["cards"][head]
        faces = {fold(head)} | {fold(face["name"]) for face in entry.get("faces", [])}
        if all(part in faces for part in parts[i:]):
            return head
    return None


def _require(name):
    exact = resolve(name)
    if exact is None:
        raise KeyError(f"Unknown card: {name!r}")
    return _get().data["cards"][exact]


def printing(set_code, collector_number):
    """The printing with this set code and collector number, or None."""
    set_code, number = set_code.lower(), str(collector_number)
    entry = _get().data["printings"].get(set_code, {}).get(number)
    return None if entry is None else dict(entry, set=set_code, collector_number=number)


def printing_card(set_code, collector_number):
    """The card fields of the card a printing is, or None for an unknown
    printing or one that isn't a card you put in a deck (a token, an art card).

    Usually that's card(name). It differs for Un-set cards printed in several
    versions under one name: printing_card("ust", "49a") is that version of
    Very Cryptic Command, with its own text and roles."""
    p = printing(set_code, collector_number)
    if p is None:
        return None
    data = _get().data
    name = resolve(p["name"])       # a reversible printing is named "X // X"
    if name is not None and data["cards"][name]["oracle_id"] == p["oracle_id"]:
        return data["cards"][name]
    return data["variants"].get(p["oracle_id"])


def printings(name):
    """Every printing of a card (all games and finishes), newest first."""
    return [printing(s, n) for s, n in _require(name)["printings"]]


def token(oracle_id):
    """The token, emblem or reminder with this oracle id (a copy, plus "id"), or None.

    Its fields: name, kind ("token", "emblem", "reminder" or "helper"), layout,
    type_line (every face's), power, toughness and colors (the front face's),
    keywords, text, faces (each face of a double-faced, reversible or flip
    card, else []), face_names, image ([set, number] of a printing with a
    picture, or None) and printings (paper only, newest first)."""
    entry = _get().data["tokens"].get(oracle_id)
    return None if entry is None else dict(entry, id=oracle_id)


def tokens_for(name):
    """(token entries, unresolved part names): what a card makes, from
    Scryfall's links between cards and tokens. A name is unresolved when
    several tokens share its name and type line and the link doesn't say
    which. ([], []) for an unknown card or one that makes nothing."""
    exact = resolve(name)
    if exact is None:
        return [], []
    found = _get().data["cards"][exact]
    entries = [token(oracle_id) for oracle_id in found.get("tokens", [])]
    return [entry for entry in entries if entry is not None], list(found.get("token_names", []))


def token_face(name):
    """The exact Scryfall name of a token, emblem or reminder face (or of a
    double-faced one's full name) matching name loosely, or None."""
    return _get().token_by_face.get(fold(name))


def token_face_names():
    """Every token, emblem and reminder face name, plus double-faced ones' full names, sorted."""
    return list(_get().token_names)


def token_faces_at(set_code, collector_number):
    """(oracle id, face names) of the printing with this set code and
    collector number, or None when it isn't a token, emblem or reminder."""
    data = _get().data
    entry = data["printings"].get(str(set_code).lower(), {}).get(str(collector_number))
    if entry is None or entry["oracle_id"] not in data["tokens"]:
        return None
    return entry["oracle_id"], list(data["tokens"][entry["oracle_id"]]["face_names"])


def search_names(text, limit=20, paper_only=True):
    """Card names for autocomplete. Names that start with text come first,
    then names with a word starting with it, then names whose words start
    with the words typed, in order ("llan elv" finds Llanowar Elves, "jace
    sculptor" Jace, the Mind Sculptor, "fire/ice" Fire // Ice), then any
    other name containing it; alphabetical within each group. paper_only
    skips digital-only cards."""
    key = fold(text)
    if not key:
        return []
    typed = _words(key)
    loaded = _get()
    starts, word_starts, in_order, others = [], [], [], []
    for (folded, name, paper), (joined, words) in zip(loaded.search_keys, loaded.search_words):
        if paper_only and not paper:
            continue
        pos = folded.find(key)
        if pos == 0:
            starts.append(name)
        elif pos > 0 and folded[pos - 1] in " -":
            word_starts.append(name)
        elif typed and typed[0] in joined and _starts_words(typed, words):
            in_order.append(name)
        elif pos > 0:
            others.append(name)
    return (sorted(starts) + sorted(word_starts) + sorted(in_order) + sorted(others))[:limit]


def card_names(paper_only=True):
    """Every card name, in the index's order (paper_only skips digital-only cards): the editor's finder
    browses these when only filters are given."""
    return [name for _, name, paper in _get().search_keys if paper or not paper_only]


def close_names(text, limit=3, paper_only=True):
    """Card names that look like text, for "did you mean" after a name that
    isn't a card: search_names' matches first, then close misspellings
    ("Llanowar Elfs" -> "Llanowar Elves"; difflib, about 0.1 s)."""
    found = search_names(text, limit, paper_only)
    if len(found) < limit:
        import difflib
        loaded = _get()
        cards = loaded.data["cards"]
        # by_key has the full names and multi-face cards' front faces ("murderous rider").
        keys = {key: name for key, name in loaded.by_key.items() if cards[name]["paper"] or not paper_only}
        for key in difflib.get_close_matches(fold(text), list(keys), n=limit, cutoff=0.75):
            if keys[key] not in found:
                found.append(keys[key])
    return found[:limit]


def roles(name):
    """The set of ROLES a card has (from Scryfall oracle tags, including child tags)."""
    return set(_require(name)["roles"])


def game_changers():
    """Names of the cards Scryfall flags as Commander Game Changers, sorted."""
    return sorted(name for name, c in _get().data["cards"].items() if c["game_changer"])


_tag_cache = {}         # (path, mtime_ns, size) -> {slug: frozenset of oracle ids}
_tag_lock = threading.Lock()


def tag_members(slugs, path=None):
    """{slug: frozenset of oracle ids} for any Scryfall oracle tags, each
    with the cards of every tag below it, as the roles are counted.

    Compare the ids with a card's "oracle_id". Reads the oracle_tags bulk file
    (path, by default the downloaded one) once for all the slugs asked for,
    and keeps the answers in memory until the file changes. Raises KeyError
    for a slug the file doesn't have, and OSError (FileNotFoundError) when
    there's no tag file."""
    path = Path(path) if path is not None else bulk_path("oracle_tags")
    stat = path.stat()
    key = (str(path.resolve()), stat.st_mtime_ns, stat.st_size)
    slugs = list(dict.fromkeys(slugs))
    with _tag_lock:
        known = _tag_cache.get(key, {})
        missing = [slug for slug in slugs if slug not in known]
        if missing:
            tags, by_slug = card_index._read_tag_tree(path)
            unknown = [slug for slug in missing if slug not in by_slug]
            if unknown:
                raise KeyError(f"No oracle tag {', '.join(map(repr, unknown))} in {path}")
            known = dict(known)
            for slug in missing:
                known[slug] = frozenset(card_index._tag_closure(tags, by_slug[slug]))
            _tag_cache.clear()          # an older version of the file isn't needed again
            _tag_cache[key] = known
    return {slug: known[slug] for slug in slugs}


def price_date():
    """The date Scryfall's prices in the index were pulled (default_cards updated_at)."""
    return _get().data["bulk"].get("default_cards", "")[:10]


# --- Prices -----------------------------------------------------------------

def cheapest_usd(name):
    """(usd, set, collector_number, finish) of the card's cheapest paper printing,
    or None when no printing has a USD price.

    The cheapest non-foil price wins, as AGENTS.md asks. Only when no printing
    has a non-foil price is the cheapest foil or etched one used (about 110
    cards, e.g. Ajani, Inspiring Leader, printed only in foil). Skips digital,
    oversized and memorabilia printings (see UNPLAYABLE_PRICE_SET_TYPES)."""
    all_printings = _get().data["printings"]
    best = {}       # finish -> (usd, set, number, finish)
    for set_code, number in _require(name)["printings"]:
        p = all_printings[set_code][number]
        if (p["digital"] or "paper" not in p["games"]
                or p["oversized"] or p["set_type"] in UNPLAYABLE_PRICE_SET_TYPES):
            continue
        for finish, key in PRICE_FINISHES:
            usd = p[key]
            if usd is not None and (finish not in best or usd < best[finish][0]):
                best[finish] = (usd, set_code, number, finish)
    if "nonfoil" in best:
        return best["nonfoil"]
    others = [best[f] for f in ("foil", "etched") if f in best]
    return min(others) if others else None


_fx = None              # the rate in use: {"rate", "date", "fetched_on"}
_fx_tried_on = None     # the day of the last network attempt
_fx_tried_at = None     # time.monotonic() of the last network attempt
_fx_lock = threading.Lock()


def usd_to_aud():
    """(rate, rate_date): AUD per USD, the ECB reference rate from Frankfurter.

    Fetched at most once a day and cached in decklab/data/fx.json. When the
    fetch fails the cached rate is used, and it's tried again the next day.
    With nothing cached it raises RuntimeError, and tries again after
    FX_RETRY_GAP seconds (the server may start before the network is up)."""
    global _fx, _fx_tried_on, _fx_tried_at
    today = date.today().isoformat()
    with _fx_lock:
        cached = _fx or _read_json(FX_FILE, None)
        if cached is None:
            due = _fx_tried_at is None or time.monotonic() - _fx_tried_at >= FX_RETRY_GAP
        else:
            due = cached.get("fetched_on") != today and _fx_tried_on != today
        if due:
            _fx_tried_on, _fx_tried_at = today, time.monotonic()
            try:
                data = _get_json(FX_URL, timeout=15)
                cached = {"rate": float(data["rates"]["AUD"]), "date": data["date"],
                          "fetched_on": today, "source": FX_URL}
                _write_json(FX_FILE, cached)
            except NETWORK_ERRORS + (KeyError, TypeError) as e:
                if cached is None:
                    raise RuntimeError(f"No USD->AUD rate: {e}, and nothing cached in {FX_FILE}") from e
        if cached is None:
            raise RuntimeError(f"No USD->AUD rate: the last try failed and nothing is cached in "
                               f"{FX_FILE}; trying again within {FX_RETRY_GAP // 60} minutes")
        _fx = cached
    return cached["rate"], cached["date"]


@dataclass
class Price:
    """An AUD estimate for one card, with what's needed to label it as one."""
    name: str
    aud: float              # usd x rate, rounded to cents
    usd: float              # Scryfall's USD price for the printing and finish below
    rate: float             # AUD per USD
    rate_date: str          # ECB reference date of the rate
    price_date: str         # date Scryfall's prices were pulled
    set: str                # the printing that was priced
    collector_number: str
    finish: str = "nonfoil"     # foil or etched only when no non-foil price exists

    def label(self):
        finish = "" if self.finish == "nonfoil" else f" {self.finish}"
        return (f"~A${self.aud:.2f} est. (US${self.usd:.2f}{finish}, {self.set.upper()} "
                f"{self.collector_number}, Scryfall {self.price_date}; 1 USD = {self.rate} AUD, "
                f"ECB {self.rate_date})")


def price_aud(name):
    """AUD estimate for the card's cheapest paper printing (see cheapest_usd),
    or None when no printing has a USD price."""
    cheapest = cheapest_usd(name)
    if cheapest is None:
        return None
    usd, set_code, number, finish = cheapest
    rate, rate_date = usd_to_aud()
    return Price(resolve(name), round(usd * rate, 2), usd, rate, rate_date,
                 price_date(), set_code, number, finish)


# --- Images -----------------------------------------------------------------

_WINDOWS_RESERVED = {"con", "prn", "aux", "nul"} | {f"{p}{n}" for p in ("com", "lpt") for n in range(10)}

# One lock per image path. Without it, two phones asking for the same new image
# both download it, and on Windows the second os.replace() fails while the
# first file is open to be sent (WinError 5).
_image_locks = {}
_image_locks_lock = threading.Lock()


def _safe_part(text):
    """Make text safe as one path component: letters, digits and '-' stay, any
    other character becomes _<hex> (so '.', '/' and '\\' can't escape the
    folder), and Windows device names like "con" (Conflux) get a trailing _."""
    safe = "".join(ch if (ch.isascii() and ch.isalnum()) or ch == "-" else f"_{ord(ch):x}"
                   for ch in text)
    return safe + "_" if safe.lower() in _WINDOWS_RESERVED else safe


_image_bytes = {}       # IMAGES_DIR -> bytes of images in it, counted on the first download
_image_bytes_lock = threading.Lock()


def _image_files():
    """[(modified time, size, path)] of every image in the cache."""
    out = []
    for path in IMAGES_DIR.glob("*/*/*.jpg"):
        try:
            stat = path.stat()
        except OSError:
            continue
        out.append((stat.st_mtime, stat.st_size, path))
    return out


def _count_image(path):
    """Add a new image to the cache's size; past IMAGE_CACHE_MAX, delete the
    images used least recently (never path) until it's under IMAGE_CACHE_KEEP of it."""
    with _image_bytes_lock:
        total = _image_bytes.get(IMAGES_DIR)
        if total is None:
            total = sum(size for _, size, _ in _image_files())      # path included
        else:
            try:
                total += path.stat().st_size
            except OSError:
                pass
        if total > IMAGE_CACHE_MAX:
            files = sorted(_image_files(), key=lambda f: f[0])
            total = sum(size for _, size, _ in files)
            for _, size, old in files:
                if total <= IMAGE_CACHE_MAX * IMAGE_CACHE_KEEP:
                    break
                if old == path:
                    continue
                try:
                    old.unlink()
                except OSError:         # being sent right now (Windows): leave it
                    continue
                total -= size
        _image_bytes[IMAGES_DIR] = total


def image_source(p, size):
    """The Scryfall URL of a printing's (p, as printing() gives it) image of size, or None: the
    stored URL, or for a size in DERIVED_IMAGE_SIZES the stored one's with its folder swapped."""
    base = DERIVED_IMAGE_SIZES.get(size)
    if base is None:
        return p.get("image_" + size) or None
    url = p.get("image_" + base) or ""
    folder = "/" + base.removesuffix("-back") + "/"
    if folder not in url:
        return None
    return url.replace(folder, "/" + size.removesuffix("-back") + "/", 1)


def image_path(set_code, collector_number, size="normal"):
    """Local path of a printing's image (small/normal/large/art_crop, optionally -back), downloaded
    from Scryfall the first time. None when Scryfall has no image; KeyError for an
    unknown printing. The cache is capped at IMAGE_CACHE_MAX bytes."""
    if size not in IMAGE_SIZES:
        raise ValueError(f"size must be one of {IMAGE_SIZES}, not {size!r}")
    p = printing(set_code, collector_number)
    if p is None:
        raise KeyError(f"Unknown printing: {set_code} {collector_number}")
    url = image_source(p, size)
    if not url:
        return None
    path = IMAGES_DIR / size / _safe_part(p["set"]) / (_safe_part(p["collector_number"]) + ".jpg")
    with _image_locks_lock:
        lock = _image_locks.setdefault(path, threading.Lock())
    with lock:
        try:
            age = time.time() - path.stat().st_mtime
        except FileNotFoundError:
            _download(url, path, accept="image/*")
            _count_image(path)
        else:
            if age > IMAGE_TOUCH_AGE:       # keep images in use away from the cap's clean-up
                try:
                    os.utime(path)
                except OSError:
                    pass
    return path


# --- Command line -----------------------------------------------------------

def _token_words(t):
    """"Rabbit (Token Creature — Rabbit 1/1 W)", or "The Monarch (reminder)"."""
    if t["kind"] != "token":
        return f"{t['name']} ({t['kind']})"
    words = [t["type_line"]]
    if t["power"] is not None:
        words.append(f"{t['power']}/{t['toughness']}")
    if t["colors"]:
        words.append("".join(t["colors"]))
    return f"{t['name']} ({' '.join(words)})"


def _show(name):
    exact = resolve(name)
    if exact is None:
        print(f"No card named {name!r}.")
        suggestions = search_names(name, 8)
        if suggestions:
            print("Did you mean: " + "; ".join(suggestions))
        return 1
    c = card(exact)
    print(f"{c['name']}  {c['mana_cost']}  (mana value {c['cmc']:g})")
    print(c["type_line"])
    if c["oracle_text"]:
        print(c["oracle_text"])
    if c["power"] is not None:
        print(f"{c['power']}/{c['toughness']}")
    print(f"Colours: {''.join(c['colors']) or 'colourless'}   "
          f"Identity: {''.join(c['color_identity']) or 'colourless'}   Layout: {c['layout']}")
    if c["keywords"]:
        print("Keywords: " + ", ".join(c["keywords"]))
    if c["produced_mana"]:
        print("Produces: " + "".join(c["produced_mana"]))
    print("Roles: " + (", ".join(c["roles"]) or "none"))
    print(f"Commander: {c['commander_legality']}   Game Changer: {'yes' if c['game_changer'] else 'no'}"
          f"   Paper: {'yes' if c['paper'] else 'no (digital only)'}")
    print(f"Printings: {len(c['printings'])}")
    made, unresolved = tokens_for(exact)
    if made or unresolved:
        print("Makes: " + ", ".join([_token_words(t) for t in made]
                                    + [f"{n} (several tokens have this name)" for n in unresolved]))
    cheapest = cheapest_usd(exact)
    if cheapest is None:
        print("Price: no USD price for a paper printing")
    else:
        try:
            print("Price: " + price_aud(exact).label())
        except RuntimeError as e:
            usd, set_code, number, finish = cheapest
            print(f"Price: US${usd:.2f} {finish} ({set_code.upper()} {number}); no AUD rate: {e}")
    return 0


def main(argv=None):
    sys.stdout.reconfigure(errors="replace")    # card text has characters a cp1252 pipe can't show
    parser = argparse.ArgumentParser(prog="python -m decklab.lib.cards",
                                     description="Scryfall card data for Deck Lab.")
    commands = parser.add_subparsers(dest="command", required=True)
    up = commands.add_parser("update", help="download stale bulk files and rebuild the index")
    up.add_argument("--force", action="store_true", help="download the bulk files even if fresh")
    show = commands.add_parser("show", help="print a card")
    show.add_argument("name")
    search = commands.add_parser("search", help="autocomplete a card name")
    search.add_argument("text")
    search.add_argument("--limit", type=int, default=20)
    args = parser.parse_args(argv)

    try:
        if args.command == "update":
            update(force=args.force)
            return 0
        if args.command == "show":
            return _show(args.name)
        for name in search_names(args.text, args.limit):
            print(name)
        return 0
    except (RuntimeError, FileNotFoundError) as e:     # no data yet, or offline with none
        print(e, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
