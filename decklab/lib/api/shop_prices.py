"""The shops' daily snapshots (lib/shops/) beside the purchase queue's rows (E5-S08, E5-S19).

Shopping's answer is home's records, so only Matt and User1 get here (shopping.py's guard).
Only the cached files are read: a page load never reaches a shop. Each shop's file is read
on its own (MTGMate's and Games Portal's), so one missing or unreadable file leaves only that
shop out; with none, queue facts stay unchanged, and generic missing needs retain an explicit
state without a saved check.

A capture is {shop key: snapshot} of the shops with one, or None when no shop has. The
answers keep their first, single-shop form for MTGMate ("shop_snapshot") and give every shop
in "shop_snapshots", a list in lib/shops' SNAPSHOT_ADAPTERS order.
"""
from decklab.lib import shops

from . import common

_NOT_CAPTURED = object()


def capture():
    """One optional capture of every shop's snapshot; explicit None is an already-captured absence."""
    return _snapshot()


def _snapshot():
    found = {}
    for adapter in shops.SNAPSHOT_ADAPTERS:
        try:
            data = shops.load(adapter=adapter)
        except Exception as error:  # optional evidence: Shopping still answers without it
            common._log(f"{adapter.name} snapshot could not be read: {type(error).__name__}: {error}")
            continue
        if data and (not isinstance(data, dict) or data.get("shop", adapter.name) == adapter.name):
            found[adapter.key] = data
    return found or None


def by_shop(data):
    """A capture as {key: snapshot}; one bare snapshot (an older caller's) counts as MTGMate's."""
    if not isinstance(data, dict) or not data:
        return {}
    if "version" in data or "cards" in data:
        return {shops.ADAPTER.key: data}
    return {key: value for key, value in data.items() if key in shops.ADAPTERS and value}


def _present(data):
    found = by_shop(data)
    return [(adapter, found[adapter.key]) for adapter in shops.SNAPSHOT_ADAPTERS if adapter.key in found]


def for_row(row, data=None):
    """One queue row's MTGMate match, or None when there's no MTGMate snapshot."""
    first = by_shop(_snapshot() if data is None else data).get(shops.ADAPTER.key)
    return shops.match(row, first) if first else None


def for_row_shops(row, data=None):
    """One queue row's match at every shop with a snapshot, in order, or None when none has one."""
    present = _present(_snapshot() if data is None else data)
    return [shops.match(row, snapshot) for _, snapshot in present] or None


def enrich(answer, *, data=_NOT_CAPTURED):
    """Each queued card's "shop_snapshot" (MTGMate's) and "shop_snapshots" (every shop's), and the
    answer's (each snapshot's shop and fetch time), only while some shop has a snapshot: without
    one the answer stays exactly as it was. The queue itself never changes."""
    data = capture() if data is _NOT_CAPTURED else data
    present = _present(data)
    if not present:
        return answer
    try:
        summaries = [shops.summary(snapshot) for _, snapshot in present]
        matches = [[shops.match(row, snapshot) for _, snapshot in present] for row in answer.get("to_buy", [])]
    except Exception as error:
        common._log(f"Shop snapshot queue projection failed: {type(error).__name__}")
        return answer
    first = present[0][0].key == shops.ADAPTER.key
    if first:
        answer["shop_snapshot"] = summaries[0]
    answer["shop_snapshots"] = summaries
    for row, matched in zip(answer.get("to_buy", []), matches):
        if first:
            row["shop_snapshot"] = matched[0]
        row["shop_snapshots"] = matched
    return answer


def enrich_missing(answer, *, data):
    """Generic nonfoil facts from the same capture, with no implicit reload."""
    from . import shop_missing_prices
    # Missing-card gathering already uses the index. Optional shop evidence must
    # never trigger its load/update on another path or when it is unavailable.
    resolve = _loaded_resolver()
    shop_missing_prices.enrich_shops(answer.get("missing_cards", {}).get("rows", []), by_shop(data), resolve)
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
