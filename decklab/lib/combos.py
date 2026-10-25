"""Commander Spellbook's two-card combos, for the Commander checks (E9-S23;
design in decklab/design/commander-sources.md).

Usage (from the repo root):
    python -m decklab.lib.cards update [--force]    also refreshes the combo list

`cards.update()` calls update() here as a step of its own: it downloads
Commander Spellbook's public export (variants.json.gz, about 30 MB) into
decklab/data/combos/ when it's missing or more than MAX_BULK_AGE old (or with
--force), asking only for a newer file than the one on the PC (If-None-Match
and If-Modified-Since). A failed download keeps the old file. The export is
then reduced once to two_card.json, about 1 MB: the Commander-legal combos of
exactly two cards (one copy each, no template pieces such as "a creature with
power 4 or more", no unreleased cards).

No decklist is ever sent anywhere: the public list is downloaded and matched
here, on the PC. Spellbook also offers to look up a submitted decklist; Deck
Lab doesn't use that (decks are private to their space).

From code:

    from decklab.lib import combos
    combos.find(commander_ids, deck_ids)   # {"timestamp", "version", "matches": [combo]}
    combos.bracket_floor(combo)            # 1, 3 or 4: what the combo means for the bracket

A combo is {"id", "url", "cards": [{"oracle_id", "name", "must_be_commander"}],
"results": [Spellbook's result names, standalone ones first], "class",
"standalone"}. class is the most serious of its results, one of CLASSES.
standalone is False when every result needs something more to be useful (a
payoff: Gravecrawler + Phyrexian Altar loops, but does nothing alone).
Spellbook marks "Mass Land Denial" and "Lock" as helper results in every
combo, so those two describe the combo whatever their status: a lock needs
no payoff, and a combo that destroys lands counts as mass land denial.
find() raises ComboListError when the list can't be read: the checks then say
combos weren't checked, never that none were found.

The list's credit and link are in decklab/lib/stats/constants.py SOURCES
("commander-spellbook"). Its data has no stated licence; Spellbook's API
guidelines ask for credit and a link back.
"""
import gzip
import json
import os
import threading
import time
import urllib.error
from datetime import datetime
from pathlib import Path

from decklab.lib import card_index, cards
from decklab.lib.config import DATA

COMBOS_DIR = DATA / "combos"
EXPORT_FILE = COMBOS_DIR / "variants.json.gz"   # Spellbook's export, as downloaded
META_FILE = COMBOS_DIR / "meta.json"            # when it was downloaded, its ETag and Last-Modified
TWO_CARD_FILE = COMBOS_DIR / "two_card.json"    # what the checks read
EXPORT_URL = "https://json.commanderspellbook.com/variants.json.gz"
COMBO_URL = "https://commanderspellbook.com/combo/{id}/"
FORMAT = 2                  # two_card.json's layout; a file of another one is reduced again
                            # (2: locks and mass land denial from every result, more wins)
DOWNLOAD_TIMEOUT = 120      # seconds without data before a download gives up
CHUNK = 1 << 20             # characters read from the export at a time
MAX_VALUE = 64 << 20        # characters: one value in the export bigger than this is damage
MAX_MALFORMED = 0.05        # more than this share of combos unreadable: the export is bad

# The result classes, most serious first. A combo's class is its most serious
# result's (its standalone results', when it has some, plus any lock or mass
# land denial result).
CLASSES = ("mass_land_denial", "win", "infinite", "lock", "draw", "near_infinite", "other")


class ComboListError(ValueError):
    """The two-card combo list is missing, damaged or in an older layout."""


# --- Reducing the export -----------------------------------------------------

def result_class(name):
    """The class of one of Spellbook's result names ("Infinite creature ETB": infinite)."""
    text = " ".join(str(name).lower().split())
    if "mass land denial" in text:
        return "mass_land_denial"
    if "win the game" in text or ("loses the game" in text and ("opponent" in text or "player" in text)):
        return "win"
    if "exile" in text and ("opponent's library" in text or "opponents' libraries" in text
                            or "all libraries" in text):
        return "win"        # Helm of Obedience + Rest in Peace: nothing left to draw
    if text.startswith("you control") and "opponent" in text and "each of their turns" in text:
        return "lock"       # Mindslaver + Academy Ruins
    if text.startswith(("infinite ", "infinitely ")):
        return "infinite"
    if text == "lock" or text.endswith(" lock"):
        return "lock"
    if text.startswith("draw the game"):
        return "draw"
    if text.startswith("near-infinite"):
        return "near_infinite"
    return "other"


def _most_serious(classes):
    return min(classes, key=CLASSES.index, default="other")


def _reduce_variant(variant):
    """One export entry as a two-card combo, or None when it isn't one. Raises
    KeyError, TypeError or ValueError for an entry that can't be read."""
    if variant.get("status", "OK") != "OK" or variant.get("spoiler") is True:
        return None
    uses, requires = variant["uses"], variant["requires"]
    if not isinstance(uses, list) or not isinstance(requires, list):
        raise TypeError("uses and requires must be lists")
    if len(uses) != 2 or requires or variant["legalities"]["commander"] is not True:
        return None
    pieces = []
    for use in uses:
        if use["quantity"] != 1:
            return None
        card = use["card"]
        oracle_id, name = card["oracleId"], card["name"]
        if not (isinstance(oracle_id, str) and oracle_id and isinstance(name, str) and name):
            raise ValueError("a card without an oracle id or name")
        zones = use.get("zoneLocations") or []
        # "C" alone: it works only from the command zone. "C" beside other
        # zones (a hand, the battlefield) means it works from either.
        pieces.append({"oracle_id": oracle_id, "name": name,
                       "must_be_commander": use.get("mustBeCommander") is True or list(zones) == ["C"]})
    if pieces[0]["oracle_id"] == pieces[1]["oracle_id"]:
        return None
    results = []            # (name, status): S standalone, C contextual, H helper
    for produced in variant["produces"]:
        feature = produced["feature"]
        if not isinstance(feature["name"], str):
            raise ValueError("a result without a name")
        results.append((feature["name"], feature.get("status")))
    if not results:
        return None
    standalone = any(status == "S" for _, status in results)
    order = {"S": 0, "C": 1}
    names = list(dict.fromkeys(name for name, status in sorted(results, key=lambda r: order.get(r[1], 2))))
    classes = {result_class(name) for name, status in results if status == "S" or not standalone}
    # Spellbook marks "Mass Land Denial" and "Lock" as helper results
    # everywhere, so they count whatever their status.
    classes |= {result_class(name) for name, _ in results} & {"mass_land_denial", "lock"}
    combo_id = variant["id"]
    if not isinstance(combo_id, str) or not combo_id:
        raise ValueError("a combo without an id")
    return {"id": combo_id, "url": COMBO_URL.format(id=combo_id), "cards": pieces, "results": names,
            "class": _most_serious(classes), "standalone": standalone}


def _open_export(path):
    """The export as text: gzipped as downloaded, or plain JSON."""
    with open(path, "rb") as f:
        magic = f.read(2)
    if magic == b"\x1f\x8b":
        return gzip.open(path, "rt", encoding="utf-8")
    return open(path, encoding="utf-8")


def _stream_export(path, each):
    """Read the export without loading all 700 MB of it: every entry of its
    "variants" list goes to each(entry) as it's read, and the other top-level
    fields are returned (except "aliases", which isn't needed)."""
    decoder = json.JSONDecoder()
    top = {}
    with _open_export(path) as f:
        buf, pos, eof = "", 0, False

        def more():
            nonlocal buf, pos, eof
            chunk = f.read(CHUNK)
            if not chunk:
                eof = True
                return False
            buf, pos = buf[pos:] + chunk, 0
            if len(buf) > MAX_VALUE:
                raise ValueError("a value in the combo export is too large; the file may be damaged")
            return True

        def peek():
            nonlocal pos
            while True:
                while pos < len(buf) and buf[pos] in " \t\r\n":
                    pos += 1
                if pos < len(buf) or not more():
                    return buf[pos] if pos < len(buf) else ""

        def expect(char):
            nonlocal pos
            if peek() != char:
                raise ValueError(f"the combo export isn't in the expected layout (expected {char!r})")
            pos += 1

        def value():
            nonlocal pos
            peek()
            while True:
                try:
                    found, end = decoder.raw_decode(buf, pos)
                except json.JSONDecodeError:
                    if not more():
                        raise
                    continue
                if end == len(buf) and not eof and more():
                    continue        # a number at the end of a chunk may go on in the next
                pos = end
                return found

        expect("{")
        while peek() != "}":
            key = value()
            if not isinstance(key, str):
                raise ValueError("the combo export isn't in the expected layout")
            expect(":")
            if key == "variants":
                expect("[")
                while peek() != "]":
                    each(value())
                    if peek() == ",":
                        pos += 1
                expect("]")
            elif key == "aliases":
                value()
            else:
                top[key] = value()
            if peek() == ",":
                pos += 1
        expect("}")
    return top


def reduce_export(export=None, dest=None, log=print):
    """Reduce Spellbook's export to the two-card combo list. Returns the number
    of combos. Raises ValueError (or OSError) and leaves dest as it was when the
    export can't be read, has no date or holds no two-card combos."""
    export, dest = Path(export or EXPORT_FILE), Path(dest or TWO_CARD_FILE)
    kept, seen = [], [0, 0]       # combos; [entries, unreadable entries]

    def each(variant):
        seen[0] += 1
        try:
            if not isinstance(variant, dict):
                raise TypeError("an entry that isn't an object")
            combo = _reduce_variant(variant)
        except (KeyError, TypeError, ValueError, AttributeError):
            seen[1] += 1
            return
        if combo is not None:
            kept.append(combo)

    started = time.monotonic()
    top = _stream_export(export, each)
    timestamp, version = top.get("timestamp"), top.get("version")
    if not isinstance(timestamp, str) or not timestamp:
        raise ValueError("the combo export has no timestamp, so its date is unknown")
    if seen[1] > MAX_MALFORMED * max(seen[0], 1):
        raise ValueError(f"{seen[1]:,} of the combo export's {seen[0]:,} entries can't be read")
    if not kept:
        raise ValueError(f"the combo export's {seen[0]:,} entries hold no two-card combos")
    data = {"format": FORMAT, "source": EXPORT_URL, "timestamp": timestamp,
            "version": version if isinstance(version, str) else None, "count": len(kept),
            "combos": kept}
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    os.replace(tmp, dest)
    standalone = sum(1 for c in kept if c["standalone"])
    commander = sum(1 for c in kept if any(p["must_be_commander"] for p in c["cards"]))
    log(f"Combo list: {len(kept):,} two-card combos of {seen[0]:,} ({standalone:,} standalone, "
        f"{commander:,} needing a commander; list of {timestamp[:10]}, version {version}), "
        f"reduced in {time.monotonic() - started:.0f} s")
    if seen[1]:
        log(f"  {seen[1]:,} entries couldn't be read and were left out")
    return len(kept)


# --- Downloading -------------------------------------------------------------

def _now():
    return card_index._now()


def _fresh(meta):
    try:
        downloaded = datetime.fromisoformat(meta["downloaded_at"])
    except (KeyError, TypeError, ValueError):
        return False
    return EXPORT_FILE.exists() and _now() - downloaded <= cards.MAX_BULK_AGE


def _needs_reducing(meta):
    if not EXPORT_FILE.exists():
        return False
    if not TWO_CARD_FILE.exists() or TWO_CARD_FILE.stat().st_mtime < EXPORT_FILE.stat().st_mtime:
        return True
    return meta.get("format") != FORMAT


def update(force=False, log=print):
    """Download the export when it's missing or over MAX_BULK_AGE old (always
    with force), then reduce it when it changed. A failed download keeps the
    local files. Returns True when two_card.json was rewritten."""
    meta = cards._read_json(META_FILE, {})
    if not isinstance(meta, dict):
        meta = {}
    if not force and _fresh(meta):
        log(f"combos: fresh (downloaded {meta['downloaded_at'][:10]})")
    else:
        headers = {"Accept-Encoding": "gzip"}
        if not force and EXPORT_FILE.exists():
            if meta.get("etag"):
                headers["If-None-Match"] = meta["etag"]
            if meta.get("last_modified"):
                headers["If-Modified-Since"] = meta["last_modified"]
        got = {}
        try:
            log(f"combos: downloading {EXPORT_URL}")
            started = time.monotonic()
            size = cards._download(EXPORT_URL, EXPORT_FILE, accept="application/json",
                                   timeout=DOWNLOAD_TIMEOUT, headers=headers, response_headers=got)
        except urllib.error.HTTPError as e:
            e.close()
            if e.code != 304:
                log(f"combos: download failed ({e}); keeping the local file.")
            else:
                meta["downloaded_at"] = _now().isoformat(timespec="seconds")   # restart the clock
                cards._write_json(META_FILE, meta)
                log("combos: unchanged on Commander Spellbook")
        except cards.NETWORK_ERRORS as e:
            log(f"combos: download failed ({e}); keeping the local file." if EXPORT_FILE.exists()
                else f"combos: download failed ({e}); combos can't be checked until it works.")
        else:
            got = {k.lower(): v for k, v in got.items()}
            meta = {"uri": EXPORT_URL, "downloaded_at": _now().isoformat(timespec="seconds"),
                    "etag": got.get("etag"), "last_modified": got.get("last-modified"), "size": size}
            cards._write_json(META_FILE, meta)
            log(f"  {size / 1e6:.1f} MB in {time.monotonic() - started:.0f} s")
    if not _needs_reducing(meta):
        if TWO_CARD_FILE.exists():
            log(f"Combo list is up to date ({TWO_CARD_FILE}).")
        return False
    try:
        reduce_export(EXPORT_FILE, TWO_CARD_FILE, log)
    except (OSError, EOFError, ValueError, gzip.BadGzipFile) as e:
        log(f"Combo list: the export can't be reduced ({type(e).__name__}: {e}); "
            f"keeping the old list." if TWO_CARD_FILE.exists() else
            f"Combo list: the export can't be reduced ({type(e).__name__}: {e}).")
        return False
    try:
        data = load()
        meta.update(format=FORMAT, timestamp=data["timestamp"], version=data["version"])
        cards._write_json(META_FILE, meta)
    except ComboListError as e:
        log(f"Combo list: {e}")
    return True


# --- Reading and matching ----------------------------------------------------

_cache = {"key": None, "data": None}
_cache_lock = threading.Lock()


def _check(data):
    """The list, checked, plus "by_oracle": {oracle id: [combo index]}."""
    if not isinstance(data, dict) or data.get("format") != FORMAT:
        raise ValueError("it's in an older or unknown layout; run python -m decklab.lib.cards update")
    timestamp, combos = data.get("timestamp"), data.get("combos")
    if not isinstance(timestamp, str) or not timestamp or not isinstance(combos, list):
        raise ValueError("it has no date or no combos")
    by_oracle = {}
    for i, combo in enumerate(combos):
        pieces = combo.get("cards") if isinstance(combo, dict) else None
        if (not isinstance(pieces, list) or len(pieces) != 2
                or not all(isinstance(p, dict) and isinstance(p.get("oracle_id"), str)
                           and isinstance(p.get("name"), str) for p in pieces)
                or combo.get("class") not in CLASSES or not isinstance(combo.get("standalone"), bool)
                or not isinstance(combo.get("results"), list) or not isinstance(combo.get("url"), str)):
            raise ValueError(f"combo {i + 1} can't be read")
        for piece in pieces:
            by_oracle.setdefault(piece["oracle_id"], []).append(i)
    return {"timestamp": timestamp, "version": data.get("version"), "combos": combos,
            "by_oracle": by_oracle}


def load(path=None):
    """The two-card combo list (read once, again when the file changes).
    Raises ComboListError when it's missing or can't be read."""
    path = Path(path or TWO_CARD_FILE)
    try:
        stat = path.stat()
        key = (str(path), stat.st_mtime_ns, stat.st_size)
        with _cache_lock:
            if _cache["key"] == key:
                return _cache["data"]
        data = _check(json.loads(path.read_text(encoding="utf-8")))
    except FileNotFoundError:
        raise ComboListError("Commander Spellbook's combo list isn't on the PC yet "
                             "(python -m decklab.lib.cards update downloads it)") from None
    except (OSError, ValueError) as e:
        raise ComboListError(f"Commander Spellbook's combo list ({path.name}) can't be read: {e}") from None
    with _cache_lock:
        _cache.update(key=key, data=data)
    return data


def bracket_floor(combo):
    """The lowest Commander Bracket a deck holding both pieces fits, by this
    combo alone: 4 for one that destroys lands (mass land denial, standalone
    or not, since Spellbook marks it a helper result everywhere), 3 for a
    standalone infinite or game-ending one (none in Brackets 1-2), else 1.
    Locks, draws, near-infinites and other combos needing a payoff raise
    nothing."""
    if combo["class"] == "mass_land_denial":
        return 4
    if not combo["standalone"]:
        return 1
    return 3 if combo["class"] in ("infinite", "win") else 1


def find(commander_ids, deck_ids, path=None):
    """The two-card combos whose pieces are both among these oracle ids: the
    Commander section's, and the rest of the main deck's (Companion and Deck;
    never the Sideboard). A piece that must be the commander counts only in
    commander_ids. Returns {"timestamp", "version", "matches": [combo]}, most
    serious first. Raises ComboListError when the list can't be read."""
    data = load(path)
    commander_ids = set(commander_ids)
    present = commander_ids | set(deck_ids)
    matches, seen = [], set()
    for oracle_id in present:
        for i in data["by_oracle"].get(oracle_id, ()):
            if i in seen:
                continue
            seen.add(i)
            combo = data["combos"][i]
            if all(p["oracle_id"] in (commander_ids if p["must_be_commander"] else present)
                   for p in combo["cards"]):
                matches.append(combo)
    matches.sort(key=lambda c: (-bracket_floor(c), CLASSES.index(c["class"]),
                                [p["name"] for p in c["cards"]]))
    return {"timestamp": data["timestamp"], "version": data["version"], "matches": matches}
