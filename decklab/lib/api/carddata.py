"""The card data's state: the background update (update_cards), the 503
that everything needing card data raises until the index can be loaded
(_require_cards), and GET /api/status.

UPDATE lives here only: the server reads api.carddata.UPDATE, and tests
patch it here.
"""
import json
import math
import threading
import traceback
from pathlib import Path

from decklab.lib import cards

from . import common
from .common import ApiError, _public

# What the background card update is doing, for status() and the 503 message.
# The server's update thread changes it through update_cards().
UPDATE = {"running": False, "error": None}
_update_lock = threading.Lock()

# What reading a missing, cut-off, damaged or out-of-date card index can raise.
_INDEX_ERRORS = cards.INDEX_ERRORS
_last_index_error = [None]      # the last reason logged, so a missing index is logged once


def update_cards(force=False, log=None):
    """Run cards.update(), then load the index and the exchange rate, so the
    first page doesn't wait for them. While it runs, status() says updating.
    Returns False without doing anything if an update is already running.
    Any error is logged and kept for status() rather than raised."""
    log = log or common._log
    with _update_lock:
        if UPDATE["running"]:
            return False
        UPDATE["running"] = True
    try:
        cards.update(force=force, log=log)
        cards.info()
        try:
            cards.usd_to_aud()
        except RuntimeError as e:        # offline with no cached rate: prices wait
            log(f"No USD->AUD rate yet: {e}")
        UPDATE["error"] = None
    except Exception as e:              # a background thread: keep it for status()
        UPDATE["error"] = _public(e)
        log("Card data update failed:\n" + traceback.format_exc())
    finally:
        UPDATE["running"] = False
    return True


def _index_info():
    """(cards.info(), None) when the card index can be loaded, else (None, a
    plain reason). The full error goes to the server log, once per reason."""
    try:
        return cards.info(), None
    except _INDEX_ERRORS as e:
        if isinstance(e, FileNotFoundError):
            reason = "There's no card data on the PC yet"
        elif isinstance(e, RuntimeError):
            reason = "The card data on the PC is in an older format and needs rebuilding"
        else:
            reason = "The card data on the PC can't be read (it may be damaged) and needs rebuilding"
        detail = f"{type(e).__name__}: {e}"
        if _last_index_error[0] != detail:
            _last_index_error[0] = detail
            common._log(f"The card index can't be loaded: {detail}")
        return None, reason


def _require_cards():
    """Raise ApiError 503 until the card index can be loaded. The message is
    for the person holding the phone; the details are in the server log."""
    info, reason = _index_info()
    if info is not None:
        return
    if UPDATE["running"]:
        raise ApiError(503, "The card data is still being downloaded from Scryfall and indexed "
                            "(the first start takes a few minutes). Try again shortly.")
    if UPDATE["error"]:
        raise ApiError(503, "There's no card data yet: the last download from Scryfall failed. "
                            "Deck Lab tries again by itself; the server log on the PC says what "
                            "went wrong.")
    raise ApiError(503, f"{reason}. Deck Lab gets it from Scryfall when it starts; the server log "
                        f"on the PC says more.")


def _cached_rate():
    """{"rate", "date"} of the USD->AUD rate cached on disk, or None. Never
    fetches: status() must answer at once."""
    try:
        data = json.loads(Path(cards.FX_FILE).read_text(encoding="utf-8"))
        rate, date = data["rate"], data["date"]
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if isinstance(rate, (int, float)) and math.isfinite(rate) and isinstance(date, str):
        return {"rate": rate, "date": date}
    return None


def status():
    """GET /api/status: whether the card data is ready, and the cached rate.

    cards.error says why the index can't be loaded (None when it can), and
    update_error why the last background update failed."""
    info, error = _index_info()
    return {
        "cards": {
            "ready": info is not None,
            "built_at": info["built_at"] if info else None,
            "price_date": (cards.price_date() or None) if info else None,
            "error": error,
        },
        "updating": UPDATE["running"],
        "update_error": UPDATE["error"],
        "fx": _cached_rate(),
    }
