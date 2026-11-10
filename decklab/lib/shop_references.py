"""Reviewable retailer observations from supplied saved data; no file, network or database I/O.

The caller supplies one frozen household preference and a local printing proof.
References are dated market observations, never paid prices or live-stock claims.
"""
import hashlib
import json
import re
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from urllib.parse import unquote, urlsplit

from decklab.lib import shops
from decklab.lib.inventory.model import QUEUE_FIELDS
from decklab.lib.shops import history as shop_history, rows as shop_rows

FIELDS = ("listed_aud", "listed_at", "in_stock", "checked")


class Unconfirmed(ValueError):
    pass


def _time(value):
    if not isinstance(value, str) or len(value) > 64 or not re.fullmatch(
            r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})", value):
        raise Unconfirmed("The snapshot's reading time couldn't be confirmed")
    if not value.endswith("Z") and (int(value[-5:-3]) > 23 or int(value[-2:]) > 59):
        raise Unconfirmed("The snapshot's reading time couldn't be confirmed")
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        raise Unconfirmed("The snapshot's reading time couldn't be confirmed") from None


def _money(value):
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)) or len(str(value)) > 32:
        raise Unconfirmed("The snapshot's AUD unit price couldn't be confirmed")
    try:
        number = Decimal(str(value))
        if not number.is_finite() or not 0 <= number < Decimal("1000000000") or number.as_tuple().exponent < -2:
            raise ValueError
        return format(number.quantize(Decimal("0.01")), ".2f")
    except (InvalidOperation, ValueError):
        raise Unconfirmed("The snapshot's AUD unit price couldn't be confirmed") from None


def _url(value, adapter, name):
    if not isinstance(value, str) or len(value) > 2048 or any(ord(char) <= 32 or ord(char) == 127 for char in value) or "\\" in value:
        raise Unconfirmed("The snapshot's own listing page couldn't be confirmed")
    try:
        parsed, site = urlsplit(value), urlsplit(adapter.site)
        path = unquote(parsed.path, errors="strict")
        safe = (parsed.scheme == "https" and parsed.netloc == site.netloc and not parsed.username and not parsed.password
                and not parsed.fragment and "\\" not in path and not any(part in (".", "..") for part in path.split("/"))
                and not any(ord(char) < 32 or ord(char) == 127 for char in path))
        own = (adapter.key == "mtgmate" and path.startswith("/cards/") and len(path) > 7 and not parsed.query
               or adapter.key == "gamesportal" and (path.startswith("/products/") and len(path) > 10
                   and (not parsed.query or re.fullmatch(r"variant=\d{1,20}", parsed.query))
                   or value == adapter.name_url(name)))
        if not safe or not own:
            raise ValueError
    except ValueError:
        raise Unconfirmed("The snapshot's own listing page couldn't be confirmed") from None
    return value


def _entry(row, data, adapter):
    if (not isinstance(data, dict) or type(data.get("version")) is not int or data["version"] != 1
            or data.get("shop") != adapter.name or data.get("site") != adapter.site or not isinstance(data.get("cards"), dict)):
        raise Unconfirmed("That shop has no confirmed saved reading")
    name = row.get("name")
    if not isinstance(name, str) or not name or row.get("is_token"):
        raise Unconfirmed("A reference needs a confirmed physical card, not a token or reminder")
    entries = [value for written, value in data["cards"].items() if isinstance(written, str) and written.casefold() == name.casefold()]
    if len(entries) != 1 or not isinstance(entries[0], dict):
        raise Unconfirmed("That shop has no confirmed saved reading for this row")
    entry = entries[0]
    if entry.get("status") != "ok" or entry.get("carried", False) is not False:
        raise Unconfirmed("Carried or unread shop lines cannot replace a reference")
    _time(entry.get("at"))
    return entry


def observation(row, data, adapter, *, preference, confirm_printing):
    """One complete quote and source receipt. Printing proof never comes from the browser."""
    entry = _entry(row, data, adapter)
    try:
        chosen = shops.match(row, data, preference)
    except (ValueError, TypeError, KeyError):
        raise Unconfirmed("The saved listing couldn't be confirmed") from None
    if chosen["status"] not in ("in_stock", "out_of_stock"):
        raise Unconfirmed("No confirmed listing meets this row's printing, finish and household preference")
    if type(chosen.get("stock")) is not int or not 0 <= chosen["stock"] <= 1000000000:
        raise Unconfirmed("The snapshot's stock observation couldn't be confirmed")
    wanted = row.get("finish")
    if wanted and wanted in shop_rows.FINISHES and wanted != chosen.get("finish"):
        raise Unconfirmed("The snapshot listing doesn't match the finish requested by this row")
    proof = confirm_printing(row["name"], chosen.get("set"), chosen.get("collector_number"), chosen.get("finish"))
    if (not isinstance(proof, dict) or set(proof) != {"name", "set", "collector_number", "finish"}
            or not all(isinstance(value, str) and value for value in proof.values())
            or proof["finish"] != chosen.get("finish")
            or shop_rows.fold_set(proof["set"]) != shop_rows.fold_set(chosen.get("set"))
            or shop_rows.fold_number(proof["collector_number"]) != shop_rows.fold_number(chosen.get("collector_number"))):
        raise Unconfirmed("The snapshot printing couldn't be confirmed against the local card index")
    price = _money(chosen.get("price_aud"))
    url = _url(chosen.get("url"), adapter, row["name"])
    fields = {"listed_aud": price, "listed_at": adapter.name,
              "in_stock": "yes" if chosen["status"] == "in_stock" else "no", "checked": _time(entry["at"]).date().isoformat()}
    evidence = {"row": {key: str(row.get(key) or "") for key in dict.fromkeys((*QUEUE_FIELDS, "buy_under_aud"))},
                "shop": adapter.key, "entry": entry, "preference": preference, "printing": proof}
    try:
        content = json.dumps(evidence, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError):
        raise Unconfirmed("The snapshot's source evidence couldn't be confirmed") from None
    return {"fields": fields, "printing": dict(proof), "receipt": hashlib.sha256(content).hexdigest(),
            "source": {"key": adapter.key, "shop": adapter.name, "url": url, "fetched_at": entry["at"],
                       "condition": chosen.get("condition"), "language": chosen.get("language"), "partial": bool(entry.get("partial"))}}


def lowest_kept(row, quote, data, history_data, adapter, *, preference, now):
    """A today's quote is lowest in its queue scope's retained in-stock readings, or None.

    At least one earlier day is needed. Missing/malformed history and a mismatch
    with the row's finish scope withhold the badge rather than invent a low.
    """
    if quote["fields"]["in_stock"] != "yes" or _time(quote["source"]["fetched_at"]).astimezone(now.tzinfo).date() != now.date():
        return None
    entry = _entry(row, data, adapter)
    asked, listings = shop_rows.history_scope(row, entry["listings"])
    scope_choice = shops.pick(asked, listings, preference)[0]
    if scope_choice is None or (shop_rows.fold_set(scope_choice.get("set")), shop_rows.fold_number(scope_choice.get("number")),
                               scope_choice.get("finish"), _money(scope_choice.get("price"))) != (
            shop_rows.fold_set(quote["printing"]["set"]), shop_rows.fold_number(quote["printing"]["collector_number"]),
            quote["printing"]["finish"], quote["fields"]["listed_aud"]):
        return None
    raw = shop_history.of(history_data)
    matches = [readings for name, readings in raw.items() if isinstance(name, str) and name.casefold() == row["name"].casefold()]
    if len(matches) != 1 or not isinstance(matches[0], list) or any(not isinstance(reading, dict) for reading in matches[0]):
        return None
    days, seen = [], set()
    cutoff = now.date() - timedelta(days=89)
    read = shops.selection_reader(preference)
    for reading in matches[0]:
        try:
            day = datetime.strptime(str(reading.get("on")), "%Y-%m-%d").date()
            if day in seen:
                return None
            seen.add(day)
            if not cutoff <= day <= now.date():
                continue
            _time(reading.get("at"))
            if reading.get("partial") or not isinstance(reading.get("listings"), list) or any(
                    not isinstance(item, dict) for item in reading["listings"]):
                return None
            shown = shop_history.day_summary(reading, shops.pick, row, details=read)
            if shown["in_stock"] and shown["listed"]:
                days.append((day, Decimal(_money(shown["price"]))))
        except (ValueError, TypeError, KeyError):
            return None
    if quote["source"]["partial"] or not any(day < now.date() for day, _ in days):
        return None
    amount = Decimal(quote["fields"]["listed_aud"])
    if any(value < amount for _, value in days):
        return None
    return {"days": 90, "readings": len({day for day, _ in days} | {now.date()}), "scope": shop_rows.scope_words(row)}
