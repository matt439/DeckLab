"""Each downloaded source's last good fetch and last failure (E11-S85's Data sources), kept in
decklab/data/sources.json: fixed source keys and UTC times only, never an error's words, a URL,
a card or deck name, a path or a response.

The code that fetches calls record(key, ok) once per attempt that reached for the network (a copy
still fresh on the PC records nothing): Scryfall's bulk files (cards.download_bulk), the exchange
rate (cards.usd_to_aud), Scryfall's rulings (rulings.update), Commander Spellbook's combo export
(combos.update), MTGJSON (precons._fetch, which the precon, sealed-product and coverage readers
share), EDHREC (edhrec._request: an answer counts, a page EDHREC doesn't have is neither) and the
gauntlet catalogue's build (gauntlet/catalogue.build). record never raises: a receipt that can't
be written is no reason for a fetch to fail.

Settings' Data sources panel reads them (GET /api/settings/data-sources, lib/api/data_sources.py).
"""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
import threading

from decklab.lib import config

SOURCES = (("scryfall", "Scryfall card data"), ("fx", "Exchange rate (ECB)"), ("rulings", "Scryfall rulings"),
           ("spellbook", "Commander Spellbook combos"), ("mtgjson", "MTGJSON precons and products"),
           ("edhrec", "EDHREC"), ("gauntlet", "Gauntlet catalogue"))
KEYS = frozenset(key for key, _ in SOURCES)
MAX_BYTES = 16 * 1024
VERSION = 1
_lock = threading.RLock()


def path():
    return config.DATA / "sources.json"


def _now():
    return datetime.now(timezone.utc)


def _time(value):
    """An aware ISO time as UTC, or None."""
    if not isinstance(value, str) or len(value) > 40:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def _read():
    """({key: {"last_ok", "last_failure"}}, readable). A missing file is readable and empty; a
    damaged, oversized or foreign one is unreadable (nothing in it is trusted)."""
    try:
        with path().open("rb") as stream:
            raw = stream.read(MAX_BYTES + 1)
    except FileNotFoundError:
        return {}, True
    except OSError:
        return {}, False
    if len(raw) > MAX_BYTES:
        return {}, False
    try:
        found = json.loads(raw)
    except (ValueError, RecursionError):
        return {}, False
    if not isinstance(found, dict) or found.get("version") != VERSION or not isinstance(found.get("sources"), dict):
        return {}, False
    out = {}
    for key, value in found["sources"].items():
        if key not in KEYS:
            continue
        if not isinstance(value, dict):
            return {}, False
        ok, failed = _time(value.get("last_ok")), _time(value.get("last_failure"))
        out[key] = {"last_ok": ok.isoformat(timespec="seconds") if ok else None,
                    "last_failure": failed.isoformat(timespec="seconds") if failed else None}
    return out, True


def read():
    return _read()[0]


def record(key, ok, at=None):
    """Note one fetch of a source: ok True for a good answer, False for a failure. Never raises;
    an unknown key or a non-bool outcome is ignored, and an unreadable receipt file is left as it is."""
    try:
        if key not in KEYS or type(ok) is not bool:
            return False
        when = (at or _now()).astimezone(timezone.utc).isoformat(timespec="seconds")
        target = path()
        with _lock:
            sources, readable = _read()
            if not readable:
                return False
            entry = dict(sources.get(key) or {"last_ok": None, "last_failure": None})
            entry["last_ok" if ok else "last_failure"] = when
            sources[key] = entry
            data = json.dumps({"version": VERSION, "sources": sources}, sort_keys=True,
                              separators=(",", ":")).encode()
            target.parent.mkdir(parents=True, exist_ok=True)
            fd, temporary = tempfile.mkstemp(prefix=".sources-", suffix=".tmp", dir=target.parent)
            try:
                with os.fdopen(fd, "wb") as stream:
                    stream.write(data)
                os.replace(temporary, target)
            finally:
                Path(temporary).unlink(missing_ok=True)
        return True
    except Exception:       # noqa: BLE001 (a receipt never fails the fetch it describes)
        return False


def state(entry):
    """"never" (no fetch recorded), "failing" (the newest attempt failed) or "ok"."""
    ok, failed = _time((entry or {}).get("last_ok")), _time((entry or {}).get("last_failure"))
    if ok is None and failed is None:
        return "never"
    if failed is not None and (ok is None or failed > ok):
        return "failing"
    return "ok"


def view():
    """{"readable", "sources": [{"key", "label", "last_ok", "last_failure", "state"}]} in SOURCES'
    order, every source listed (an unrecorded one as never)."""
    records, readable = _read()
    rows = []
    for key, label in SOURCES:
        entry = records.get(key) or {"last_ok": None, "last_failure": None}
        rows.append({"key": key, "label": label, "last_ok": entry["last_ok"],
                     "last_failure": entry["last_failure"], "state": state(entry)})
    return {"readable": readable, "sources": rows}
