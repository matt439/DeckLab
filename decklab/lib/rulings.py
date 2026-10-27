"""Scryfall's rulings for the card viewer (E1-S25).

Usage (from the repo root):
    python -m decklab.lib.cards update [--force]    also refreshes the rulings

`cards.update()` calls update() here as a step of its own, so nothing it
raises fails the update or holds up the card index. It downloads Scryfall's
`rulings` bulk file when the rulings on the PC are missing or more than
cards.MAX_BULK_AGE old (or with --force), and only when Scryfall lists a newer
file than the one they were made from. The download is reduced at once to
decklab/data/scryfall/rulings.json.gz, the rulings of each card by its oracle
id, and then deleted. A failed download or a file that can't be read keeps
the rulings already on the PC.

From code:

    from decklab.lib import rulings
    rulings.for_card(cards.card("Thragtusk"))   # [{"date", "source", "text"}], oldest first;
                                                # None when there's no rulings file yet
    rulings.updated()                           # Scryfall's date of the file, or None

Rulings are Scryfall's: Wizards of the Coast's ("wotc") and Scryfall's own
notes ("scryfall"), dated, as Scryfall gives them. Deck Lab never writes its
own explanations (E4-S07 isn't wanted).
"""
import gzip
import json
import os
import threading
import zlib
from datetime import datetime

from decklab.lib import card_index, cards

KIND = "rulings"            # Scryfall's bulk type, and its key in cards.BULK_META_FILE
FORMAT = 1                  # rulings.json.gz's layout; a file of another one counts as missing
SOURCES = ("wotc", "scryfall")

READ_ERRORS = (OSError, EOFError, ValueError, KeyError, TypeError, zlib.error)

_loaded = None              # (path, mtime_ns, data) of the file read last
_lock = threading.Lock()


def index_path():
    return cards.SCRYFALL_DIR / "rulings.json.gz"


def _download_path():
    return cards.SCRYFALL_DIR / "rulings.download"


# --- Reducing the bulk file -------------------------------------------------

def _open_bulk(path):
    """The bulk file as text, gunzipped when it's gzip whatever its name says."""
    with open(path, "rb") as f:
        gzipped = f.read(2) == b"\x1f\x8b"
    return gzip.open(path, "rt", encoding="utf-8") if gzipped else open(path, encoding="utf-8")


def _entries(path):
    """Each ruling in a bulk file: one JSON array (download_uri) or one object a line (jsonl_download_uri)."""
    with _open_bulk(path) as f:
        start = f.read(1)
        while start and start.isspace():
            start = f.read(1)
        if start == "[":
            yield from json.loads(start + f.read())
            return
        first = start + f.readline()
        for line in [first, *f]:
            if line.strip():
                yield json.loads(line)


def reduce(path):
    """The rulings of a bulk file by oracle id: {oracle id: [[date, source, text], ...]}, each card's oldest
    first (in the file's order on the same date). An entry that can't be read raises ValueError, so a damaged
    file never replaces good rulings."""
    by_card = {}
    for entry in _entries(path):
        if not isinstance(entry, dict):
            raise ValueError("a ruling that isn't an object")
        oracle_id, text = entry.get("oracle_id"), entry.get("comment")
        if not isinstance(oracle_id, str) or not oracle_id or not isinstance(text, str):
            raise ValueError("a ruling without an oracle id or text")
        if not text.strip():
            continue
        source = entry.get("source") if entry.get("source") in SOURCES else ""
        date = entry.get("published_at") if isinstance(entry.get("published_at"), str) else ""
        by_card.setdefault(oracle_id, []).append([date[:10], source, text.strip()])
    for found in by_card.values():
        found.sort(key=lambda ruling: ruling[0])
    return by_card


def _write(by_card, updated_at, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with gzip.open(tmp, "wt", encoding="utf-8", compresslevel=6) as f:
        json.dump({"format": FORMAT, "updated_at": updated_at, "rulings": by_card}, f,
                  ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, path)


# --- Downloading -------------------------------------------------------------

def _is_stale(meta):
    info = meta.get(KIND)
    if not info or not index_path().exists():
        return True
    try:
        return card_index._now() - datetime.fromisoformat(info["downloaded_at"]) > cards.MAX_BULK_AGE
    except (KeyError, TypeError, ValueError):
        return True


def update(force=False, log=print):
    """Download and reduce the rulings when they're due. Returns True when rulings.json.gz was rewritten.
    Raises nothing for a failed download or a bad file: the rulings on the PC are kept."""
    meta = cards._read_json(cards.BULK_META_FILE, {})
    if not force and not _is_stale(meta):
        log(f"{KIND}: fresh (Scryfall {meta[KIND]['updated_at'][:10]}, "
            f"downloaded {meta[KIND]['downloaded_at'][:10]})")
        return False
    try:
        listing = {entry["type"]: entry for entry in cards._get_json(cards.BULK_LIST_URL)["data"]}
    except cards.NETWORK_ERRORS + (KeyError, TypeError) as e:
        log(f"{KIND}: couldn't reach Scryfall ({e}); keeping the rulings on the PC.")
        return False
    entry = listing.get(KIND) or {}
    old = meta.get(KIND) or {}
    now = card_index._now().isoformat(timespec="seconds")
    if (not force and entry.get("updated_at") and old.get("updated_at") == entry["updated_at"]
            and index_path().exists()):
        old["downloaded_at"] = now      # Scryfall hasn't published anything newer: restart the clock
        meta[KIND] = old
        cards._write_json(cards.BULK_META_FILE, meta)
        log(f"{KIND}: unchanged on Scryfall since {entry['updated_at'][:10]}")
        return False
    uri = entry.get("jsonl_download_uri") or entry.get("download_uri")
    if not uri or not entry.get("updated_at"):
        log(f"{KIND}: {cards.BULK_LIST_URL} doesn't list a rulings file; keeping the rulings on the PC.")
        return False
    download = _download_path()
    try:
        log(f"{KIND}: downloading {uri}")
        cards._download(uri, download)
        by_card = reduce(download)
        _write(by_card, entry["updated_at"], index_path())
    except cards.NETWORK_ERRORS + READ_ERRORS as e:
        log(f"{KIND}: not updated ({type(e).__name__}: {e}); keeping the rulings on the PC.")
        return False
    finally:
        download.unlink(missing_ok=True)
    meta = cards._read_json(cards.BULK_META_FILE, {})     # the card files' own steps may have written it
    meta[KIND] = {"updated_at": entry["updated_at"], "uri": uri, "downloaded_at": now}
    cards._write_json(cards.BULK_META_FILE, meta)
    log(f"  rulings for {len(by_card):,} cards")
    return True


# --- Reading -----------------------------------------------------------------

def _data():
    """rulings.json.gz as read, or None when it's missing, damaged or in another layout. Read again when the
    file changes (an update in the server's background thread)."""
    global _loaded
    path = index_path()
    try:
        mtime = path.stat().st_mtime_ns
    except OSError:
        return None
    with _lock:
        if _loaded and _loaded[0] == path and _loaded[1] == mtime:
            return _loaded[2]
        try:
            with gzip.open(path, "rt", encoding="utf-8") as f:
                data = json.load(f)
            if data.get("format") != FORMAT or not isinstance(data.get("rulings"), dict):
                data = None
        except READ_ERRORS:
            data = None
        _loaded = (path, mtime, data)
        return data


def available():
    return _data() is not None


def updated():
    """The date (YYYY-MM-DD) of Scryfall's rulings file the PC's rulings came from, or None."""
    data = _data()
    return str(data.get("updated_at") or "")[:10] or None if data else None


def for_card(card):
    """A card's rulings ([{"date", "source", "text"}], oldest first; [] for none), or None when there's no
    rulings file yet. card is a cards.card() entry (its oracle_id)."""
    data = _data()
    if data is None:
        return None
    found = data["rulings"].get((card or {}).get("oracle_id") or "") or []
    return [{"date": date, "source": source, "text": text} for date, source, text in found]
