"""Bounded cached-shop inputs for explicit reference/target reviews; never a shop request."""
import hashlib
import json
import os

from decklab.lib import cards, config, pricing_setting, shops, state
from decklab.lib.inventory.model import QUEUE_FIELDS
from decklab.lib.state import pricing as pricing_rules

from .shop_references import Unconfirmed


def context(*, fresh=True):
    """Freshness affects only the pricing cache key; last-good fallbacks aren't erased."""
    try:
        provider = state.store()
    except RuntimeError:
        if not os.environ.get(state.EXPLICIT_ENV):
            raise Unconfirmed("The household listing preference couldn't be confirmed") from None
        record = dict(pricing_rules.EMPTY)      # protected, isolated file fixtures only
    else:
        try:
            answer = provider.pricing_setting(fresh=fresh)
            record = pricing_rules.normalize(answer["pricing"])
        except Exception:
            raise Unconfirmed("The household listing preference couldn't be confirmed") from None
        if fresh:
            pricing_setting.forget()          # discard failed-read retry receipts, not verified store values
    try:
        merged = pricing_setting.overlay(config.load(), record)
        enabled = shops.enabled_adapters(merged)
        data = {adapter.key: shops.load(adapter=adapter) for adapter in enabled}
    except Exception:
        raise Unconfirmed("The saved shop inputs couldn't be confirmed") from None
    return {"preference": record.get("listing_preferences"), "adapters": {adapter.key: adapter for adapter in enabled},
            "data": data}


def receipt(row, source):
    """Even a target without an eligible quote reviews the actual unchanged cache context."""
    name = str(row.get("name") or "").casefold()
    entries = {}
    for key, snapshot in source["data"].items():
        if snapshot is None:
            entries[key] = None
            continue
        if not isinstance(snapshot, dict) or not isinstance(snapshot.get("cards"), dict):
            raise Unconfirmed("The saved shop inputs couldn't be confirmed")
        entries[key] = {"shop": snapshot.get("shop"), "site": snapshot.get("site"), "version": snapshot.get("version"),
                        "entries": {written: entry for written, entry in snapshot["cards"].items()
                                    if isinstance(written, str) and written.casefold() == name}}
    value = {"row": {key: str(row.get(key) or "") for key in QUEUE_FIELDS}, "sources": entries,
             "preference": source["preference"], "enabled": sorted(source["adapters"])}
    try:
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (ValueError, TypeError, UnicodeError):
        raise Unconfirmed("The saved shop inputs couldn't be confirmed") from None
    return hashlib.sha256(raw).hexdigest()


def confirm_printing(name, code, number, finish):
    """Exact paper proof from the already-loaded index; no load/update or identifier lookup."""
    if cards._index is None or finish not in shops.FINISHES:
        return None
    exact = cards.resolve(name)
    card = cards.card(exact) if exact else None
    if card is None:
        return None
    matches = {(set_code, printed_number) for set_code, printed_number in card.get("printings", [])
               if shops._rows.fold_set(set_code) == shops._rows.fold_set(code)
               and shops._rows.fold_number(printed_number) == shops._rows.fold_number(number)}
    if len(matches) != 1:
        return None
    set_code, printed_number = next(iter(matches))
    printing = cards.printing(set_code, printed_number)
    printed = cards.printing_card(set_code, printed_number)
    if (not printing or not printed or cards.resolve(printed["name"]) != exact or printing.get("digital")
            or "paper" not in printing.get("games", []) or printing.get("oversized")
            or printing.get("set_type") in cards.UNPLAYABLE_PRICE_SET_TYPES or finish not in printing.get("finishes", [])):
        return None
    return {"name": exact, "set": set_code, "collector_number": str(printed_number), "finish": finish}
