"""Optional queue-only reference receipts and dated low/target annotations."""
from datetime import datetime

from decklab.lib import inventory, shop_references, shop_reference_source, shops
from decklab.lib.inventory import watchlist_targets

from . import guard, shop_prices


def _now():
    return datetime.now().astimezone()


def enrich(answer, captured):
    rows = answer.get("to_buy", [])
    if not rows:
        return answer
    preference = shop_prices.preference(captured)
    data = shop_prices.by_shop(captured)
    source = {"preference": preference, "data": data,
              "adapters": {adapter.key: adapter for adapter in shops.enabled_adapters()}}
    original = inventory.current().watchlist.rows
    may_write = guard.allowed(guard.viewer(), "orders.edit")
    histories, lows = {}, {}
    now = _now()
    for row in rows:
        number = row.get("queue_row")
        if type(number) is not int or not 1 <= number <= len(original):
            continue
        raw = {key: original[number - 1].text(key) for key in original[number - 1].COLUMNS}
        raw["is_token"] = shops._rows.is_token(raw)
        for snap in row.get("shop_snapshots", []):
            adapter = next((item for item in source["adapters"].values() if item.name == snap.get("shop")), None)
            if adapter is None:
                continue
            try:
                quote = shop_references.observation(raw, data.get(adapter.key), adapter, preference=preference,
                                                      confirm_printing=shop_reference_source.confirm_printing)
            except Exception:
                continue                      # optional evidence never breaks the queue
            if may_write:
                snap["reference_receipt"] = quote["receipt"]
                snap["shop_key"] = adapter.key
            try:
                at = datetime.fromisoformat(quote["source"]["fetched_at"])
                if quote["fields"]["in_stock"] == "yes" and at.astimezone(now.tzinfo).date() == now.date() and not quote["source"]["partial"]:
                    if adapter.key not in histories:
                        histories[adapter.key] = {"history": shops.load_history(adapter)}
                    scope = (adapter.key, raw["name"], raw["printing"], raw["set"], raw["collector_number"], raw["finish"],
                             quote["fields"]["listed_aud"], quote["source"]["fetched_at"])
                    if scope not in lows:
                        lows[scope] = shop_references.lowest_kept(raw, quote, data[adapter.key], histories[adapter.key], adapter,
                                                                 preference=preference, now=now)
                    if lows[scope]:
                        snap["lowest_kept"] = lows[scope]
            except Exception:
                pass
            try:
                hit = watchlist_targets.reached(row.get("buy_under_aud"), snap)
                if hit is not None:
                    snap["target_comparison"] = {"amount_aud": row["buy_under_aud"], "at_or_below": hit}
            except ValueError:
                pass
    return answer
