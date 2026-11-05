"""The price settings as Deck Lab uses them (E11-S53): Settings' Prices panel's saved choice laid
over config.json's "currency" and "shops".

A home admin's choice is saved in the database (lib/state/pricing.py, migration 0022), not in
config.json: every other admin setting goes through the state store (a revision, an audit change
set, an Activity row, the export, `db check` and backups), and config.json, the household's file
with its emails and Cloudflare Access settings, is written only by the PC-side updater. So:

    saved non-null field  >  config.json's  >  the default (AUD; every shop)

Before migration 0022, with no store installed (a test) or while the database can't be read, the
last value this process read is used, else config.json's alone: exactly the behaviour before the
setting existed. A read that failed isn't tried again for RETRY_SECONDS, since every price estimate
asks (lib/currency.code(), lib/shops.enabled_adapters()); a save through the page calls forget().
No restart is needed: the store caches a read for its CACHE_SECONDS (60), so another process (the
nightly run, a command) sees a change within a minute, and the server that saved it at once.

    from decklab.lib import pricing_setting
    pricing_setting.settings()          # config.load() with the saved fields laid over it
    pricing_setting.source("currency")  # "saved", "config" or "default"
"""
import sys
import threading
import time
import weakref

from decklab.lib import config

FIELDS = ("currency", "shops")
RETRY_SECONDS = 60
_lock = threading.Lock()
_failed = weakref.WeakKeyDictionary()   # store -> (monotonic time, the fallback record or None)
_said = set()


def _say_once(text):
    if text not in _said:
        _said.add(text)
        if sys.stderr is not None:
            print(text, file=sys.stderr, flush=True)


def _checked(answer):
    """The record in a store's answer, normalized, or None when there's none or it isn't one."""
    from decklab.lib.state import Invalid, pricing
    record = answer.get("pricing") if isinstance(answer, dict) else None
    if not isinstance(record, dict):
        return None
    try:
        return pricing.normalize(record)
    except (Invalid, TypeError, ValueError):
        return None


def forget():
    """Drop the remembered failures, so the next read asks the store again (after a save)."""
    with _lock:
        _failed.clear()


def saved():
    """The saved record {v, currency, shops}, or None when nothing can be read. Never raises."""
    from decklab.lib import state
    try:
        store = state.store()
    except Exception:           # RuntimeError: no store installed (a fixture test's)
        return None
    try:
        with _lock:
            failed = _failed.get(store)
        if failed is not None and time.monotonic() - failed[0] < RETRY_SECONDS:
            return failed[1]
    except TypeError:           # a store that can't be weakly referenced: never remembered
        failed = None
    try:
        record = _checked(store.pricing_setting())
    except Exception as error:
        try:
            fallback = _checked(store.pricing_setting_cached())
        except Exception:
            fallback = None
        try:
            with _lock:
                _failed[store] = (time.monotonic(), fallback)
        except TypeError:
            pass
        if not isinstance(error, (state.Unavailable, AttributeError)):
            _say_once(f"The price settings couldn't be read ({type(error).__name__}); using "
                      f"{'the last ones read' if fallback else 'config.json'} until they can be.")
        return fallback
    if failed is not None:
        with _lock:
            _failed.pop(store, None)
    return record


def overlay(base, record):
    """base (config.load()'s) with record's non-null fields laid over it, as a new dict."""
    out = dict(base)
    for field in FIELDS:
        if record and record.get(field) is not None:
            out[field] = record[field]
    return out


def settings(base=None):
    """config.load() (or base) with the saved choice's non-null fields laid over it. Raises as
    config.load() does when config.json can't be read and no base is given."""
    return overlay(config.load() if base is None else base, saved())


def source(field, base=None, record=None):
    """Where field's value comes from: "saved" (Settings), "config" (config.json) or "default"."""
    record = saved() if record is None else record
    if record and record.get(field) is not None:
        return "saved"
    try:
        value = (config.load() if base is None else base).get(field)
    except Exception:
        return "default"
    if value is None or (isinstance(value, str) and not value.strip()):
        return "default"
    return "config"
