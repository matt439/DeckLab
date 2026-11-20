"""Compare two independent build choices (E5-S42) against one home's inventory and saved shop checks."""
import contextlib
from functools import cache

from decklab.lib import inventory, pool, shops, spaces

from . import common, guard, shop_baskets, shop_postage, shop_prices, shopping_combined
from .carddata import _require_cards
from .common import DATABASE_DOWN, ApiError, _public


def _evidence(adapter, snapshot, demand):
    entries = [shops._by_name(snapshot.get("cards"), row["name"]) if snapshot else None for row in demand]
    checked = [entry for entry in entries if isinstance(entry, dict)]
    return {"shop": adapter.name, "read": bool(snapshot), "fetched_at": (snapshot or {}).get("fetched_at"),
            "unchecked": len(entries) - len(checked), "failed": sum(entry.get("status") == "error" for entry in checked),
            "partial": any(entry.get("partial") for entry in checked), "carried": any(entry.get("carried") for entry in checked)}


def _basket_row(row):
    fields = ("name", "copies", "known_aud", "unpriced_copies", "fetched_at", "partial", "carried")
    offer_fields = ("set", "collector_number", "finish", "copies", "price_aud")
    printings = [{field: offer.get(field) for field in offer_fields} for offer in [row["listing"], *row["more"]]]
    return {**{field: row.get(field) for field in fields}, "printings": printings}


def _price(rows, captured, rules, adapters):
    demand = [{"queue_row": i, "name": row["name"], "quantity": row["buy"],
               "state": "ready", "printing": "any"} for i, row in enumerate(rows, 1)]
    wanted = sum(row["quantity"] for row in demand)
    by_shop = {key: data for key, data in shop_prices.by_shop(captured).items() if isinstance(data, dict)}
    snapshots = [_evidence(adapter, by_shop.get(adapter.key), demand) for adapter in adapters]
    result = {"shops": [], "snapshots": snapshots, "search_ran": False,
              "partial_shops": [shop["shop"] for shop in snapshots if shop["partial"]],
              "carried_shops": [shop["shop"] for shop in snapshots if shop["carried"]],
              "wanted": wanted, "covered": 0, "known_aud": "0.00",
              "delivered_aud": None if wanted else "0.00", "unpriced_copies": 0,
              "postage_unknown": [], "stock_unknown": [], "availability_only": [], "uncovered": [],
              "search_complete": not wanted, "weighed": not wanted}
    if not wanted:
        return result
    try:
        built = shop_baskets.build(demand, captured, rules=rules, adapters=adapters, guaranteed_only=True)
    except Exception as error:
        common._log(f"Shop comparison could not price the saved checks: {type(error).__name__}")
        built = None
    if not built:
        result["uncovered"] = [{"name": row["name"], "copies": row["quantity"],
                                "shops": [{"shop": adapter.name, "status": "unknown" if adapter.key in by_shop
                                           else "unread"} for adapter in adapters]} for row in demand]
        return result
    plan = built["plan"]
    chosen = plan["recommended"]
    covered = chosen["cards"]
    complete_cost = covered == wanted and not chosen["unpriced_copies"] and not chosen["postage_unknown"]
    uncounted = {adapter.name for adapter in adapters if not adapter.counts_stock}
    unknown = sorted({fact["shop"] for row in chosen["uncovered"] for fact in row["shops"]
                      if fact["shop"] in uncounted and fact["status"] in ("short", "allocated", "outside_plan")})

    breakdown = [{"shop": shop["shop"], "copies": shop["cards"], "cards_aud": shop["subtotal_aud"],
                  "postage_aud": shop["postage"]["charged_aud"], "unpriced_copies": shop["unpriced_copies"],
                  "rows": [_basket_row(row) for row in shop["rows"]]}
                 for shop in chosen["shops"]]
    return {**result, "shops": breakdown, "search_ran": True,
            "covered": covered, "delivered_aud": chosen["total_aud"] if complete_cost else None,
            "known_aud": chosen["total_aud"], "unpriced_copies": chosen["unpriced_copies"],
            "uncovered": chosen["uncovered"], "postage_unknown": chosen["postage_unknown"],
            "stock_unknown": unknown, "availability_only": chosen["stock_unknown"], "search_complete": plan["search_complete"],
            "weighed": plan["weighed"]}


def _choice(combined, captured, rules, adapters):
    result = {key: combined[key] for key in ("ready", "decks", "errors", "warnings")}
    if not combined["ready"]:
        return {**result, "required": None, "here_now": None, "cards": [], "today_missing": None, "incoming": None, "buy": None, "pricing": None}
    buy = combined["totals"]["copies"]
    incoming = combined["totals"]["on_the_way"]
    cards = []
    for row in combined["rows"]:
        waiting = sum(source["copies"] for source in row["on_the_way"])
        cards.append({"name": row["name"], "today_missing": waiting + row["missing"], "incoming": waiting,
                      "buy": row["missing"], "on_the_way": row["on_the_way"]})
    demand = [row for row in cards if row["buy"]]
    try:
        pricing = _price(demand, captured, rules, adapters)
    except Exception as error:  # malformed optional evidence cannot suppress the inventory result
        common._log(f"Shop comparison evidence unavailable: {type(error).__name__}")
        pricing = _price(demand, None, None, adapters)
    required = combined["totals"]["required"]
    return {**result, "required": required, "here_now": required - buy - incoming, "cards": cards, "today_missing": buy + incoming, "incoming": incoming, "buy": buy,
            "pricing": pricing}


def compare_view(left=None, right=None):
    guard.require_sees_home_records()
    guard.require_sees_inventory(spaces.HOME)
    ids = [shopping_combined._chosen(value) for value in (left, right)]
    _require_cards()
    try:
        with contextlib.nullcontext() if inventory.is_pinned() else inventory.pinned():
            groups = [shopping_combined._summaries(group) for group in ids]
            if {d["id"] for d in groups[0]} == {d["id"] for d in groups[1]}:
                raise ApiError(400, "Choose two different sets of decks.")
            load_supply = cache(pool.load_pool)
            choices = [shopping_combined._count(group, load_supply, include_incoming=True) for group in groups]
            adapters, captured, rules = [], None, None
            try:
                adapters = list(shops.enabled_adapters())
                captured = shop_prices.capture()
                rules = shop_postage.rules() if shop_prices.by_shop(captured) else None
            except Exception as error:  # retain any evidence already read
                common._log(f"Shop comparison inputs unavailable: {type(error).__name__}")
            return {side: _choice(choice, captured, rules, adapters)
                    for side, choice in zip(("left", "right"), choices)}
    except inventory.Unavailable:
        raise ApiError(503, DATABASE_DOWN, reason="database") from None
    except (inventory.StateError, ValueError, OSError) as error:
        raise ApiError(400, "The decks could not be compared: " + _public(error)) from None
