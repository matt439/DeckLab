"""Each day's shop reading of a queued card, kept 90 days (E5-S29's first slice).

Each shop's history file beside its snapshot (decklab/lib/shops/__init__.py's history_path(),
mtgmate.history.json; written compact, and never read by Shopping or deck pages) keeps one
reading a day for each card name still on the purchase queue:

    "history": {name: [{"on": "YYYY-MM-DD", "at": ISO, "listings": [{"set", "number", "finish",
                         "condition", "price", "stock"}]}, ...]}      # days in order, oldest first

A reading is what a run read of that name ("ok" or "not_listed", the latter with no listings);
a name the run couldn't read or didn't reach adds nothing that day. A second run on the same day
replaces that day's reading. Each snapshot drops readings older than KEEP_DAYS and every name no
longer on the queue (a card bought or removed loses its history with the next snapshot; the
nightly step's saved-home missing names, never queued, get none; a run that finds the queue
empty prunes it too). Listings keep only what a price trend needs: no links. Games Portal's
stock is only 1 or 0 (in stock or not). A missing history file is an empty history.
"""
from datetime import date, timedelta

KEEP_DAYS = 90
FIELDS = ("set", "number", "finish", "condition", "price", "stock")


def _day(value):
    try:
        return date.fromisoformat(str(value or "")[:10])
    except ValueError:
        return None


def _compact(listings):
    return [{key: item.get(key) for key in FIELDS} for item in listings or () if isinstance(item, dict)]


def _readings(value):
    """A name's valid readings, one a day, oldest first."""
    by_day = {}
    for reading in value if isinstance(value, list) else ():
        if isinstance(reading, dict) and _day(reading.get("on")) is not None:
            by_day[str(reading["on"])[:10]] = reading
    return [by_day[day] for day in sorted(by_day)]


def of(data):
    """The snapshot's history ({name: readings}), {} when it has none (an older file)."""
    history = (data or {}).get("history")
    return history if isinstance(history, dict) else {}


def find(data, name):
    """name's readings in the snapshot (case-insensitively), oldest first; [] when none."""
    history = of(data)
    found = history.get(name)
    if found is None:
        folded = name.casefold()
        found = next((value for key, value in history.items() if key.casefold() == folded), None)
    return _readings(found)


def record(previous, cards, queued, today):
    """The history to save with a new snapshot: previous's (a snapshot dict or None), plus each
    of cards' ({name: entry}) fresh readings, for queued's names only, within KEEP_DAYS of today."""
    wanted = {}
    for name in queued:
        wanted.setdefault(str(name).casefold(), str(name))
    old = {}
    for name, value in of(previous).items():
        if isinstance(name, str) and name.casefold() in wanted:
            old.setdefault(name.casefold(), []).extend(_readings(value))
    for name, entry in (cards or {}).items():
        folded = name.casefold()
        if folded not in wanted or not isinstance(entry, dict) or entry.get("carried"):
            continue
        if entry.get("status") not in ("ok", "not_listed"):
            continue
        on = _day(entry.get("at")) or today
        reading = {"on": on.isoformat(), "at": entry.get("at"), "listings": _compact(entry.get("listings"))}
        old[folded] = [item for item in old.get(folded, []) if str(item["on"])[:10] != reading["on"]] + [reading]
    oldest = today - timedelta(days=KEEP_DAYS - 1)
    history = {}
    for folded, readings in old.items():
        kept = [item for item in _readings(readings) if oldest <= _day(item["on"]) <= today]
        if kept:
            history[wanted[folded]] = kept
    return history


def _price(item):
    try:
        return float(item.get("price"))
    except (TypeError, ValueError):
        return None


def day_summary(reading, pick):
    """One reading's answer for an any-printing row (pick: the package's pick()):
    {"on", "at", "price", "stock", "in_stock", "set", "number", "finish", "in_stock_printings"}."""
    choice, stocked = pick({"printing": "any"}, reading.get("listings"))
    shown = {"on": reading.get("on"), "at": reading.get("at"), "price": None, "stock": None, "in_stock": False,
             "set": None, "number": None, "finish": None, "in_stock_printings": stocked, "listed": choice is not None}
    if choice is not None:
        shown.update(price=choice.get("price"), stock=choice.get("stock", 0), in_stock=(choice.get("stock") or 0) > 0,
                     set=choice.get("set"), number=choice.get("number"), finish=choice.get("finish"))
    return shown


def report(name, snapshots, pick):
    """{"name", "shops": [{"shop", "counts_stock", "days": [day_summary + "lowest"]}]} for each
    (adapter, data) in snapshots. lowest marks the day (or days) with that shop's lowest price a
    copy could be bought at: only days whose chosen listing was in stock count, never an
    out-of-stock fallback's price."""
    out = []
    for adapter, data in snapshots:
        days = [day_summary(reading, pick) for reading in find(data, name)]
        prices = [_price(day) for day in days if day["in_stock"] and _price(day) is not None]
        low = min(prices) if prices else None
        for day in days:
            day["lowest"] = low is not None and day["in_stock"] and _price(day) == low
        out.append({"shop": adapter.name, "counts_stock": adapter.counts_stock, "days": days})
    return {"name": name, "shops": out}


def lines(answer):
    """report()'s answer as printed lines."""
    said = []
    for shop in answer["shops"]:
        if not shop["days"]:
            said.append(f"{shop['shop']}: no history for {answer['name']}")
            continue
        said.append(f"{shop['shop']}: {len(shop['days'])} days")
        for day in shop["days"]:
            if not day["listed"]:
                said.append(f"  {day['on']}  not listed")
                continue
            # A$ whatever the configured currency (E11-S53): the shops list in AUD, never converted.
            price = f"A${day['price']}" if day["price"] else "price not shown"
            if not day["in_stock"]:
                stock = "out of stock"
            elif shop["counts_stock"]:
                stock = f"{day['stock']} in stock"
            else:
                stock = "in stock"
            where = f"{str(day['set'] or '').upper()} {day['number']} {day['finish']}"
            said.append(f"  {day['on']}  {price}, {stock} ({where}){'  lowest in stock' if day['lowest'] else ''}")
    return said
