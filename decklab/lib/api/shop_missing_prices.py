"""Strict nonfoil unit-price facts for generic missing needs, from supplied data.

No I/O or queue matching lives here. The caller supplies one saved snapshot and
the already-loaded card index's resolver. An incomplete scope cannot claim a
cheapest price or absence, and an old record keeps its own original timestamp.
"""
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from urllib.parse import unquote, urlsplit

from decklab.lib import shops

MAX_NAMES = 5000
MAX_ROWS = 2000
MAX_LISTINGS = 1000
MAX_STOCK = 1_000_000_000
UNKNOWN = "Saved MTGMate nonfoil evidence could not be confirmed."


def _text(value, limit):
    if (not isinstance(value, str) or not 0 < len(value) <= limit or value != value.strip() or
            any(ord(char) < 32 or ord(char) == 127 for char in value)):
        return False
    try:
        value.encode("utf-8")
    except UnicodeError:
        return False
    return True


def _at(value):
    if not _text(value, 64) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})", value):
        return None
    if not value.endswith("Z") and (int(value[-5:-3]) > 23 or int(value[-2:]) > 59):
        return None
    try:
        moment = datetime.fromisoformat(value)
        return value if moment.tzinfo is not None and moment.utcoffset() is not None else None
    except ValueError:
        return None


def _price(value):
    if isinstance(value, bool) or not isinstance(value, (str, int, float)) or len(str(value)) > 32:
        return None
    try:
        price = Decimal(str(value))
        if not price.is_finite() or not 0 < price < Decimal("1000000000") or price.as_tuple().exponent < -2:
            return None
        return format(price, ".2f")
    except (InvalidOperation, ValueError):
        return None


def _url(value):
    if not _text(value, 2048) or "\\" in value:
        return False
    try:
        parts = urlsplit(value)
        path = unquote(parts.path, errors="strict")
        return (parts.scheme == "https" and parts.netloc == "www.mtgmate.com.au" and
                path.startswith("/cards/") and len(path) > len("/cards/") and not parts.query and
                not parts.fragment and "\\" not in path and
                all(ord(char) >= 32 and ord(char) != 127 for char in path) and
                not any(part in (".", "..") for part in path.split("/")))
    except ValueError:
        return False


def _listing(item):
    """A selected nonfoil listing's complete facts, or None for any unsafe fact."""
    price = _price(item.get("price"))
    stock, set_code, number = item.get("stock"), item.get("set"), item.get("number")
    if (price is None or type(stock) is not int or not 0 <= stock <= MAX_STOCK or
            not isinstance(set_code, str) or not re.fullmatch(r"[a-z0-9]{1,12}", set_code) or
            not _text(number, 64) or any(char in number for char in "/\\?#") or not _url(item.get("url"))):
        return None
    return {"price_aud": price, "stock": stock, "set": set_code,
            "collector_number": number, "finish": "nonfoil", "url": item["url"]}


def _empty(status="not_checked", at=None, carried=False):
    return {"shop": shops.SHOP, "scope": "nonfoil", "status": status, "fetched_at": at,
            "price_aud": None, "stock": None, "set": None, "collector_number": None,
            "finish": None, "url": None, "in_stock_printings": 0,
            "error": UNKNOWN if status == "unknown" else None,
            "back_in_stock": False, "newly_in_stock": False, "carried": carried}


class Projection:
    def __init__(self, data, resolve):
        self.absent = data is None
        self.failed = False
        self.resolve = resolve
        self.resolved = {}
        self.entries = {}
        self.raw = {}
        if self.absent:
            return
        if (not isinstance(data, dict) or type(data.get("version")) is not int or data["version"] != 1 or
                data.get("shop") != shops.SHOP or data.get("site") != shops.SITE or
                not isinstance(data.get("cards"), dict) or len(data["cards"]) > MAX_NAMES):
            self.failed = True
            return
        try:
            for name, entry in data["cards"].items():
                if not _text(name, 200):
                    self.failed = True
                    return
                canonical = self._resolve(name) if resolve is not None else name
                self.raw.setdefault(name.casefold(), []).append(canonical)
                if canonical is not None:
                    self.entries.setdefault(canonical.casefold(), []).append(entry)
        except Exception:
            self.failed = True

    def _resolve(self, name):
        if name not in self.resolved:
            value = self.resolve(name)
            self.resolved[name] = value if _text(value, 200) else None
        return self.resolved[name]

    def for_row(self, row):
        if self.absent:
            return _empty()
        if self.failed:
            return _empty("unknown")
        try:
            name = row.get("name")
            if not _text(name, 200):
                return _empty("unknown")
            # gather() supplies canonical missing names. Exact canonical equality
            # needs no index read; aliases require the already-loaded resolver.
            canonical = self._resolve(name) if self.resolve is not None else name
            if canonical is None:
                return _empty("unknown")
            # A historical front-only key must resolve to this full identity.
            # Ambiguous aliases cannot prove either a check or its absence.
            possible = {name.casefold(), canonical.casefold(), canonical.split(" // ", 1)[0].casefold()}
            if any(value is None or value.casefold() != canonical.casefold()
                   for alias in possible for value in self.raw.get(alias, ())):
                return _empty("unknown")
            entries = self.entries.get(canonical.casefold(), [])
            if not entries:
                return _empty("unknown") if self.resolve is None and self.entries else _empty()
            if len(entries) != 1:
                return _empty("unknown")
            return self._entry(entries[0])
        except Exception:
            return _empty("unknown")

    def _entry(self, entry):
        if not isinstance(entry, dict):
            return _empty("unknown")
        at = _at(entry.get("at"))
        carried = entry.get("carried", False)
        if at is None or type(carried) is not bool:
            return _empty("unknown")
        shown = _empty("unknown", at, carried)
        status, listings = entry.get("status"), entry.get("listings")
        if status not in ("ok", "not_listed") or not isinstance(listings, list) or len(listings) > MAX_LISTINGS:
            return shown
        if status == "not_listed" and listings:
            return shown
        scope = []
        for item in listings:
            if not isinstance(item, dict) or item.get("finish") not in shops.FINISHES:
                return shown
            if item["finish"] != "nonfoil":
                continue  # Known to be outside this scope; no foil fallback.
            checked = _listing(item)
            if checked is None:
                return shown  # Cannot claim another listing is cheapest.
            scope.append(checked)
        if not scope:
            return _empty("not_listed", at, carried)
        stocked = [item for item in scope if item["stock"] > 0]
        choice = min(stocked or scope, key=lambda item: (Decimal(item["price_aud"]), item["set"],
                                                       item["collector_number"], item["url"]))
        return {**_empty("in_stock" if stocked else "out_of_stock", at, carried), **choice,
                "in_stock_printings": len({(item["set"], item["collector_number"])
                                           for item in stocked})}


def enrich(rows, data, resolve):
    """Annotate only the generic rows, retaining their exact queue copies and counts."""
    if not rows:
        return
    try:
        projection = Projection(data, resolve)
    except Exception:
        projection = None
    for number, row in enumerate(rows):
        row["shop_snapshot"] = (projection.for_row(row) if projection is not None and number < MAX_ROWS
                                else _empty("unknown"))
