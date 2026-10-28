"""MTGMate's daily snapshot (lib/shops.py) beside the purchase queue's rows (E5-S08, E5-S19).

Shopping's answer is home's records, so only Matt and User1 get here (shopping.py's guard).
Only the cached file is read: a page load never reaches the shop, and a missing or unreadable
snapshot just leaves the rows as they were.
"""
from decklab.lib import shops

from . import common


def _snapshot():
    try:
        return shops.load()
    except Exception as error:  # optional evidence: Shopping still answers without it
        common._log(f"Shop snapshot could not be read: {type(error).__name__}: {error}")
        return None


def for_row(row, data=None):
    """One queue row's snapshot match, or None when there's no snapshot."""
    data = _snapshot() if data is None else data
    return shops.match(row, data) if data else None


def enrich(answer):
    """Each queued card's "shop_snapshot" and the answer's "shop_snapshot" (the snapshot's
    shop and fetch time), only while there is a snapshot: without one the answer stays exactly
    as it was. The queue itself never changes."""
    data = _snapshot()
    if not data:
        return answer
    answer["shop_snapshot"] = shops.summary(data)
    for row in answer.get("to_buy", []):
        row["shop_snapshot"] = shops.match(row, data)
    return answer
