"""MTGMate's daily snapshot (lib/shops/) beside the purchase queue's rows (E5-S08, E5-S19).

Shopping's answer is home's records, so only Matt and User1 get here (shopping.py's guard).
Only the cached file is read: a page load never reaches the shop. A missing or
unreadable snapshot leaves queue facts unchanged; generic missing needs retain
an explicit state without a saved check.
"""
from decklab.lib import shops

from . import common

_NOT_CAPTURED = object()


def capture():
    """One optional snapshot capture; explicit None is an already-captured absence."""
    return _snapshot()


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


def enrich(answer, *, data=_NOT_CAPTURED):
    """Each queued card's "shop_snapshot" and the answer's "shop_snapshot" (the snapshot's
    shop and fetch time), only while there is a snapshot: without one the answer stays exactly
    as it was. The queue itself never changes."""
    data = capture() if data is _NOT_CAPTURED else data
    if not data:
        return answer
    try:
        summary = shops.summary(data)
        matches = [shops.match(row, data) for row in answer.get("to_buy", [])]
    except Exception as error:
        common._log(f"Shop snapshot queue projection failed: {type(error).__name__}")
        return answer
    answer["shop_snapshot"] = summary
    for row, matched in zip(answer.get("to_buy", []), matches):
        row["shop_snapshot"] = matched
    return answer


def enrich_missing(answer, *, data):
    """Generic nonfoil facts from the same capture, with no implicit reload."""
    from . import shop_missing_prices
    # Missing-card gathering already uses the index. Optional shop evidence must
    # never trigger its load/update on another path or when it is unavailable.
    resolve = _loaded_resolver()
    shop_missing_prices.enrich(answer.get("missing_cards", {}).get("rows", []), data, resolve)
    return answer


def _loaded_resolver():
    """Capture prepared identity maps; invalidating the global index cannot load a file."""
    from decklab.lib import cards
    loaded = cards._index
    if loaded is None:
        return None
    try:
        known, aliases = loaded.data["cards"], loaded.by_key
        if not isinstance(known, dict) or not isinstance(aliases, dict):
            return None
    except (AttributeError, KeyError, TypeError):
        return None
    def resolve(name):
        return name if name in known else aliases.get(cards.fold(name))
    return resolve
