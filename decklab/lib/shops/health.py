"""Nightly shop health, retaining only public shop keys and dates/statuses, never card data."""
from datetime import date, timedelta
import json
import os
from pathlib import Path
import tempfile
import threading

MAX_BYTES = 32 * 1024
THRESHOLD = 3
_lock = threading.RLock()


def path():
    from . import snapshot_path
    return snapshot_path().with_name("health.json")


def _date(value):
    try:
        return date.fromisoformat(value[:10]) if isinstance(value, str) else None
    except ValueError:
        return None


def _read():
    from . import ADAPTERS
    try:
        with path().open("rb") as stream:
            raw = stream.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            return {}, False
        found = json.loads(raw)
    except FileNotFoundError:
        return {}, True
    except (OSError, ValueError, RecursionError):
        return {}, False
    if not isinstance(found, dict) or found.get("version") != 1 or not isinstance(found.get("shops"), dict):
        return {}, False
    out = {}
    for key, value in found["shops"].items():
        if key not in ADAPTERS:
            continue
        if not isinstance(value, dict) or _date(value.get("night")) is None:
            return {}, False
        count = value.get("failed_nights")
        if type(count) is not int or not 0 <= count <= 9999 or value.get("outcome") not in ("ok", "failed", "idle", "unverified"):
            return {}, False
        out[key] = {"night": _date(value["night"]).isoformat(), "failed_nights": count, "outcome": value["outcome"],
                    "last_read": _date(value.get("last_read")).isoformat() if _date(value.get("last_read")) else None,
                    "successful_night": _date(value.get("successful_night")).isoformat()
                    if _date(value.get("successful_night")) else None}
    return out, True


def read():
    return _read()[0]


def record(key, outcome, night, last_read=None):
    """A calendar night counts once; a successful read during it prevents an unreadable-night claim."""
    from . import ADAPTERS
    if key not in ADAPTERS or outcome not in ("ok", "failed", "idle", "unverified") or not isinstance(night, date):
        raise ValueError("Invalid shop-health outcome")
    target = path()
    with _lock:
        shops, ready = _read()
        if not ready:
            raise OSError("Shop-health receipts cannot be read")
        previous = shops.get(key, {})
        successful = previous.get("successful_night")
        if outcome == "ok":
            successful, failed = night.isoformat(), 0
        elif outcome == "failed" and successful != night.isoformat():
            old_night = _date(previous.get("night"))
            if old_night == night and previous.get("outcome") == "failed":
                failed = previous.get("failed_nights", 1)
            elif old_night == night - timedelta(days=1) and previous.get("outcome") == "failed":
                failed = min(9999, previous.get("failed_nights", 0) + 1)
            else:
                failed = 1
        else:
            failed = 0
        readable = max(filter(None, (_date(last_read), _date(previous.get("last_read")))), default=None)
        shops[key] = {"night": night.isoformat(), "outcome": outcome, "failed_nights": failed,
                      "last_read": readable.isoformat() if readable else None, "successful_night": successful}
        data = json.dumps({"version": 1, "shops": shops}, sort_keys=True, separators=(",", ":")).encode()
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=".health-", suffix=".tmp", dir=target.parent)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
            os.replace(temporary, target)
        finally:
            Path(temporary).unlink(missing_ok=True)


def observe(adapter, code, before, after, raised, night):
    """Reduce a refresh result to health metadata; raw names, listings and errors are never retained."""
    entries = [entry for entry in ((after or {}).get("cards") or {}).values() if isinstance(entry, dict)]
    readable = [entry for entry in entries if entry.get("status") in ("ok", "not_listed") and not entry.get("carried")]
    dates = [_date(entry.get("at")) for snapshot in (before, after) for section in ("cards", "previous")
             for entry in ((snapshot or {}).get(section) or {}).values() if isinstance(entry, dict)
             and (section == "previous" or entry.get("status") in ("ok", "not_listed"))]
    latest = max(filter(None, dates), default=None)
    changed = after is not None and (after or {}).get("fetched_at") != (before or {}).get("fetched_at")
    if raised:
        outcome = "failed"
    elif code == 2:
        outcome = "unverified"
    elif (changed and readable) or (latest == night and code == 0):
        outcome = "ok"
    elif changed and any(entry.get("status") == "error" for entry in entries):
        outcome = "failed"
    else:
        outcome = "idle" if code == 0 else "unverified"
    record(adapter.key, outcome, night, latest.isoformat() if latest else None)


def warning():
    from . import ADAPTERS, enabled_adapters
    records, ready = _read()
    if not ready:
        return "Shop-price health cannot be verified; its receipt file cannot be read."
    if not any(value["failed_nights"] >= THRESHOLD for value in records.values()):
        return None
    try:
        enabled = {adapter.key for adapter in enabled_adapters()}
    except Exception:
        return "Shop-price health cannot be verified while its settings are unavailable."
    words = []
    for key, value in sorted(records.items()):
        if key in enabled and value["failed_nights"] >= THRESHOLD:
            last = value["last_read"] or "no successful reading recorded"
            words.append(f"{ADAPTERS[key].name} price checks failed for {value['failed_nights']} nights in a row "
                         f"(latest check {value['night']}; last readable prices: {last}).")
    return " ".join(words) or None


def heartbeat_steps(night):
    if not _read()[1]:
        return {"shop health": False}
    return {"shop_" + key: value["outcome"] == "ok" for key, value in read().items()
            if value["night"] == night.isoformat() and value["outcome"] in ("ok", "failed")}
