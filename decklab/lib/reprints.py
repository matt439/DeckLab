"""Read-only reprint follow-ups from the locally cached Scryfall card index.

The cache contains printings Scryfall knows about, not every announcement. A
listed release date passing is a reason to look again, never evidence of shop
stock or a lower price. Nothing here fetches data or changes a purchase intent.
"""
import re
from datetime import date
from urllib.parse import quote, urlencode

from decklab.lib import cards


MAX_GROUPS = 8
COVERAGE = "Only paper printings already in the cached Scryfall data; other announcements may be missing."
DATE_NOTE = "Listed release dates may change. A reprint does not guarantee lower prices or shop stock."
_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}\Z")


def _date(value):
    """Strict calendar dates only: blanks, partial dates and invalid days stay unknown."""
    if not isinstance(value, str) or not _DATE.fullmatch(value):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _source(name):
    escaped = name.replace("\\", "\\\\").replace('"', '\\"')
    return "https://scryfall.com/search?" + urlencode(
        {"q": f'!"{escaped}" game:paper', "unique": "prints", "order": "released"})


def _physical(printing):
    """Normal-size physical cards, including casual cards regardless of format legality."""
    return (printing is not None and not printing.get("digital")
            and "paper" in (printing.get("games") or ()) and not printing.get("oversized")
            and printing.get("set_type") not in cards.UNPLAYABLE_PRICE_SET_TYPES)


def _number(value):
    """Stable representative among a set's alternate arts: ordinary collector numbers first."""
    value = str(value)
    match = re.match(r"[0-9]+", value)
    return (int(match.group()) if match else float("inf"), value)


def _groups(printings, as_of, notes):
    physical = [printing for printing in printings if _physical(printing)]
    dated = [(printing, _date(printing.get("released_at"))) for printing in physical]
    undated = sum(released is None for _, released in dated)
    if undated:
        notes.append(f"{undated} paper printing(s) have no usable release date in this cache.")
    # An earlier physical release proves this is a reprint rather than another
    # variant of the card's first release. An original card still in previews
    # must not turn a later preview into an already-existing card's reprint.
    earlier = [released for _, released in dated if released is not None and released <= as_of]
    if not earlier:
        return [], undated
    first = min(earlier)
    grouped = {}
    for printing, released in dated:
        if released is None or released <= first:
            continue
        set_code, number = printing["set"], str(printing["collector_number"])
        key = (set_code, released.isoformat())
        previous = grouped.get(key)
        if previous is not None and _number(previous["collector_number"]) <= _number(number):
            continue
        grouped[key] = {"set": set_code, "set_name": printing.get("set_name") or set_code.upper(),
                        "released_at": released.isoformat(), "collector_number": number,
                        "source_url": f"https://scryfall.com/card/{quote(set_code, safe='')}/{quote(number, safe='')}"}
    return sorted(grouped.values(), key=lambda item: (item["released_at"], item["set"])), undated


def for_card(name, *, checked=None, waiting=False, today=None):
    """Describe known upcoming reprints and a waiting row's manual price-check offer.

    `checked` is the queue's saved observation date, returned without replacing
    it. Only a valid past/present date can identify printings whose listed date
    has passed since that check. Missing, invalid or future dates offer a manual
    review for waiting rows, with no claim that an old printing is newly out.
    `today` accepts a date (or ISO date) for deterministic callers and fixtures.
    Upcoming releases are soonest first and past releases newest first. Lists
    are capped independently, with explicit overflow counts.
    """
    as_of = date.today() if today is None else (_date(today) if isinstance(today, str) else today)
    if type(as_of) is not date:
        raise ValueError("today must be a calendar date")
    source_name = name if isinstance(name, str) else ""
    check_date = _date(checked)
    known_check = check_date is not None and check_date <= as_of
    notes = [DATE_NOTE]
    answer = {"ready": False, "as_of": as_of.isoformat(), "data_date": None, "coverage": COVERAGE,
              "upcoming": [], "released": [], "upcoming_more": 0, "released_more": 0,
              "price_check": {"offered": bool(waiting and not known_check),
                              "reason": "check_date_unknown" if waiting and not known_check else None,
                              "checked": checked},
              "notes": notes, "source_url": _source(source_name)}
    if waiting and not known_check:
        if checked in (None, ""):
            notes.append("No price-check date is recorded; review current prices without assuming which reprint was awaited.")
        elif check_date is not None:
            notes.append(f"The recorded price-check date ({checked}) is in the future; review it before relying on it.")
        else:
            notes.append(f"The recorded price-check date ({checked}) is not a usable calendar date; review it before relying on it.")

    def unavailable(message):
        notes.append(message)
        if waiting and known_check:
            answer["price_check"].update(offered=True, reason="data_unavailable")
        return answer

    try:
        exact = cards.resolve(source_name)
        if exact is None:
            return unavailable("This card is not known in the cached card data, so reprint details are unavailable.")
        answer["source_url"] = _source(exact)
        info = cards.info()
        stamp = info.get("bulk", {}).get("default_cards")
        data_date = _date(stamp[:10]) if isinstance(stamp, str) else None
        answer["data_date"] = data_date.isoformat() if data_date else None
        if data_date is None:
            notes.append("The date of the cached Scryfall card data is unknown.")
        grouped, undated = _groups(cards.printings(exact), as_of, notes)
    except cards.INDEX_ERRORS:
        return unavailable("The cached card data could not be read, so reprint details are unavailable.")
    upcoming = [item for item in grouped if item["released_at"] > as_of.isoformat()]
    released = ([item for item in grouped if check_date.isoformat() < item["released_at"] <= as_of.isoformat()]
                if waiting and known_check else [])
    released.sort(key=lambda item: item["released_at"], reverse=True)
    # Collector numbers are useful only for selecting the source link: the UI
    # describes one release per set/date, not each alternate art as a reprint.
    def shown(items):
        return [{key: value for key, value in item.items() if key != "collector_number"}
                for item in items[:MAX_GROUPS]]
    answer.update(ready=True, upcoming=shown(upcoming), released=shown(released),
                  upcoming_more=max(0, len(upcoming) - MAX_GROUPS),
                  released_more=max(0, len(released) - MAX_GROUPS), undated_printings=undated)
    if released:
        answer["price_check"].update(offered=True, reason="release_due")
    return answer
