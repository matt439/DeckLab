"""A queued card's price history on Shopping (E5-S29): GET /api/shopping/price-history?name=<card name>.

The nightly snapshot keeps each day's reading of every queued name at each shop for 90 days, in each
shop's history file beside its snapshot (lib/shops/history.py). This answers one name's readings, the
way `python -m decklab.lib.shops history NAME --json` prints them: each shop's days, oldest first, each
with its price and stock as an any-printing row would pick them, and the day(s) with that shop's lowest
in-stock price marked "lowest". Shopping asks only when a row's Price history is opened; its overview never
reads the history files.

Only Shopping's readers (home's record readers, guard.require_sees_home_records) may ask, before anything
else, and only for a name on the purchase queue (a name that isn't answers with no days, as the history
keeps nothing for it): the history is about cards still to buy, never owned ones. A history file that
can't be read is an empty history. Nothing is written and no shop is asked.
"""
import contextlib

from decklab.lib import inventory, shops
from decklab.lib.shops import history as _history

from . import common, guard
from .common import ApiError

MAX_NAME = 200


def price_history_view(name=None):
    """{"name", "queued", "shops": [{"shop", "counts_stock", "days": [{"on", "at", "price", "stock",
    "in_stock", "set", "number", "finish", "listed", "lowest", ...}]}]}."""
    guard.require_sees_home_records()
    if not isinstance(name, str) or not name.strip() or len(name) > MAX_NAME or common._CONTROL_RE.search(name):
        raise ApiError(400, f"name must be a card name of 1-{MAX_NAME} characters")
    name = name.strip()
    try:
        with contextlib.nullcontext() if inventory.is_pinned() else inventory.pinned():
            queued = {queued.casefold(): queued for queued in shops.queue_names(shops._queue())}
    except inventory.Unavailable:
        raise
    except (ValueError, OSError) as error:
        common._log(f"Price history: the purchase queue couldn't be read: {error}")
        raise ApiError(500, "The purchase queue couldn't be read, so its price history can't be shown.") from None
    exact = queued.get(name.casefold())
    if exact is None:
        return {"name": name, "queued": False, "shops": []}
    # load_history reads a missing or unreadable file as an empty history.
    snapshots = [(adapter, {"history": shops.load_history(adapter)}) for adapter in shops.SNAPSHOT_ADAPTERS]
    answer = _history.report(exact, snapshots, shops.pick)
    answer["queued"] = True
    return answer
