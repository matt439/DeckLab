"""The Shopping page: the purchase queue, the deliveries on the way, the checks
left open, and the home decks still missing cards. It reads without the Scryfall
card cache (the pictures and the decks' counts are then left out). It also marks
a received delivery's follow-up check done; shopping_queue.py edits purchase-queue rows.

    GET  /api/shopping           shopping_overview()
    POST /api/shopping/check     resolve_check(): {profile, order, component, check}
"""
import contextlib
import csv
import re

from decklab.lib import cards, decks, inventory, purchases, spaces
from decklab.lib.inventory import orders as order_ops       # registers order.checks
from decklab.lib.inventory import rules

from . import common, guard, shopping_missing
from .common import DATABASE_DOWN, ApiError, _keys, _parse_body, _public
from .settings import _web_actor, _writer

MAX_CHECK = 2000                # characters of a check's text in a request
_DECK_SOURCE = re.compile(r"magic/(?:people/([a-z0-9-]+)/)?decks/([a-z]+)/([a-z0-9-]+)\.md")


def shopping_overview():
    """GET /api/shopping: a read-only view of purchase and receipt records:
    home's, so 403 for anyone outside the home (guard.require_sees_home_records).

    purchases.overview()'s answer, plus:
      - "queue_revision", the exact inventory revision, and each queued card's
        "queue_row", its one-based position, for shopping_queue.py's guarded write;
      - "queue_decks", the home deck ids and titles offered when adding a card;
      - the items of each order still on the way, and each queued card, get "card": the
        card's JSON (card_lookup._card_json, for its picture and the card viewer) or None,
        and each cards or product item its "set", "collector_number" and "finish";
      - each queued card gets "deck": {"id", "title"} of the home deck it's for (its
        source naming a deck, or its "for" naming one by title), or None;
      - each product component's "product_status" (status.csv's: owned, ordered, preordered);
      - "decks_missing": the home decks whose planned list still misses cards;
      - "missing_cards": {ready, rows, warnings, errors, totals}, one canonical card
        per row with summed individual deck shortfalls, wanting decks and every matching
        queued intent. An incomplete calculation is explicit, including absent card data.
    Pictures remain best effort; purchase/receipt records still show without card data."""
    guard.require_sees_home_records()
    # One inventory snapshot for the records, the product statuses and the payload rows (the HTTP
    # dispatcher already pins one per request; a direct caller gets one here).
    with contextlib.nullcontext() if inventory.is_pinned() else inventory.pinned():
        return _overview()


def _overview():
    try:
        answer = purchases.overview()
    except (ValueError, OSError, csv.Error) as error:
        common._log(f"Shopping overview: {error}")
        raise common.ApiError(500, f"The shopping records couldn't be read: {common._public(error)}") from None
    answer["queue_revision"] = inventory.current().revision
    for number, row in enumerate(answer.get("to_buy", []), 1):
        row["queue_row"] = number
    answer["warnings"] = common._scrub(answer.get("warnings", []))
    _editable_components(answer.get("orders", []))
    _product_statuses(answer.get("orders", []))
    deck_errors = []
    summaries = _home_decks(deck_errors)
    answer["queue_decks"] = [{"id": row["id"], "title": row["title"]} for row in summaries]
    _link_decks(answer.get("to_buy", []), summaries)
    from . import reprints
    reprint_cache = {}
    reprints.enrich(answer.get("to_buy", []), queued=True, cache=reprint_cache)
    if _cards_ready():
        _add_pictures(answer)
        answer["missing_cards"], answer["decks_missing"] = shopping_missing.gather(
            summaries, answer.get("to_buy", []), _card_for, errors=deck_errors)
    else:
        answer["decks_missing"] = []
        answer["missing_cards"] = shopping_missing.unavailable(
            "The card data is not ready yet, so missing cards cannot be counted. Try again after it finishes loading.",
            errors=deck_errors)
    reprints.enrich(answer["missing_cards"].get("rows", []), cache=reprint_cache)
    return answer


def _editable_components(orders):
    """Exact pending payload rows and extra-copy flags from this request's snapshot.

    Editing must retain condition, language, notes and physical token pairings,
    even when pictures and deck counts cannot be read from the card cache.
    """
    snapshot = inventory.current()
    edits_products = guard.allowed(guard.viewer(), "orders.edit")
    for record in orders:
        order = snapshot.order(record.get("id"))
        if order is None:
            continue
        marked = rules.extra_copies(order.audit_notes)
        components = {component.id: component for component in order.components}
        for shown in record.get("components", []):
            component = components.get(shown.get("id"))
            if component is None or component.status != "pending":
                continue
            if component.kind in ("cards", "product"):
                shown["extra_copies"] = component.id in marked
            if component.kind in order_ops.PAYLOAD_FIELDS:
                sheet = snapshot.payloads.get(component.path)
                if sheet is not None and sheet.readable:
                    fields = order_ops.PAYLOAD_FIELDS[component.kind]
                    shown["edit_rows"] = [{key: row.text(key) for key in fields} for row in sheet.rows]
            elif component.kind == "product" and edits_products:
                product = _editable_product(snapshot, component)
                if product is not None:
                    shown["edit_product"] = product


def _editable_product(snapshot, component):
    """Exact product metadata and rows, so a correction retains optional columns."""
    product = snapshot.product(component.product_stem)
    if product is None or product.error is not None or product.columns is None:
        return None
    status = next((row for row in snapshot.status.rows if row.text("file") == product.file), None)
    if status is None or status.text("status") not in ("ordered", "preordered"):
        return None
    return {"name": product.name or "", "format": product.format or "", "status": status.text("status"),
            "notes": status.text("notes"), "columns": list(product.columns),
            "rows": [{key: row.text(key) for key in product.columns} for row in product.items]}


def _product_statuses(orders):
    """Each product component's "product_status" (status.csv's: owned, ordered or preordered), so the
    page can say a delivery is preordered. Left out when the statuses can't be read."""
    try:
        rows = purchases._csv(purchases.paths.STATUS, ("file", "status"))
    except (ValueError, OSError, csv.Error):
        return
    found = {row["file"]: row["status"] for row in rows}
    for order in orders:
        for component in order.get("components", []):
            if component.get("kind") == "product":
                stem = (component.get("path") or "").rsplit("/", 1)[-1]
                if stem in found:
                    component["product_status"] = found[stem]


def _cards_ready():
    from .carddata import _require_cards
    try:
        _require_cards()
    except ApiError:
        return False
    return True


def _home_decks(errors=None):
    """The home deck files' library summaries (no products, pairings or decks that can't be read)."""
    try:
        found = decks.list_decks()
    except Exception as error:          # the records still show; the log has the details
        common._log(f"Shopping: the decks couldn't be listed: {error}")
        if errors is not None:
            errors.append({"message": "The home decks could not be listed. Try reloading Shopping."})
        return []
    home = []
    for summary in found:
        try:
            space, kind, _ = spaces.split_deck_id(summary.get("id"))
        except ValueError:
            continue
        if space == spaces.HOME and kind in decks.KINDS and summary.get("space", spaces.HOME) == spaces.HOME:
            home.append(summary)
    if errors is not None:
        errors.extend({"id": s["id"], "title": s["title"],
                       "message": "This deck could not be read: " + _public(s["error"])}
                      for s in home if s.get("error"))
    return [s for s in home if not s.get("error")]


def _link_decks(queue, summaries):
    """Each queued card's "deck": the home deck its source names (magic/decks/<kind>/<slug>.md, a
    deck's old path), else the one whose title its "for" names, else None."""
    summaries = [item for item in summaries if guard.sees_deck(item)]
    by_id = {s["id"]: s for s in summaries}
    by_title = {}
    for s in summaries:
        by_title.setdefault((s.get("title") or "").casefold(), s)
    for row in queue:
        found = None
        match = _DECK_SOURCE.fullmatch(row.get("source") or "")
        if match and not match.group(1):
            found = by_id.get(inventory.resolve_deck_id(f"{match.group(2)}/{match.group(3)}"))
        if found is None:
            found = by_title.get((row.get("for") or "").strip().casefold())
        row["deck"] = {"id": found["id"], "title": found["title"]} if found else None


def _card_for(name, set_code="", number="", cache=None):
    """The card JSON (card_lookup._card_json) of name in that printing (or the one a decklist line
    naming none shows), or None for a name the card data doesn't know."""
    from .card_lookup import _card_json, _shown_printing
    key = (name, set_code or "", number or "")
    if cache is not None and key in cache:
        return cache[key]
    found = None
    try:
        exact = cards.resolve(name) or name
        card = cards.card(exact)
        if card is not None:
            p = cards.printing(set_code, number) if set_code and number else None
            if p is not None and p.get("name") != card["name"]:
                printed = cards.printing_card(set_code, number)
                p = p if printed is not None and printed["name"] == card["name"] else None
            if p is None:
                p = _shown_printing(card, (set_code,) if set_code else ())
            found = _card_json(card, p)
    except Exception as error:          # a picture is never worth failing the page for
        common._log(f"Shopping: no card data for {name!r}: {error}")
        found = None
    if cache is not None:
        cache[key] = found
    return found


def _token_for(row):
    """A token card's front as a small card JSON with its picture when the card data has that
    printing ({name, type_line, img, img_small, ...}), else None."""
    from .card_lookup import image_url
    set_code, number = row.get("set") or "", row.get("front_collector_number") or ""
    try:
        p = cards.printing(set_code, number) if set_code and number else None
    except Exception:
        p = None
    if not p or not p.get("image_normal"):
        return None
    name = " // ".join(filter(None, (row.get("front"), row.get("back"))))
    return {"name": name, "mana_cost": "", "type_line": p.get("type_line") or "Token", "oracle_text": "",
            "img": image_url(set_code, number, "normal"), "img_small": image_url(set_code, number, "small"),
            "colors": [], "color_identity": [], "roles": [], "cmc": 0}


def _add_pictures(answer):
    """Each order item's and queued card's "card", from the component's own rows (the items are
    in their order) and the queue's printing. Only the orders still on the way get pictures (the
    page shows them); the history's are left as they are, to keep the answer small."""
    cache = {}
    for order in answer.get("orders", []):
        if not any(c.get("status") == "pending" for c in order.get("components", [])):
            continue
        for component in order.get("components", []):
            items = component.get("items") or []
            try:
                kind = component["kind"]
                rows = purchases._csv(component["path"], ("front", "back", "quantity") if kind == "tokens"
                                      else ("name", "quantity"))
            except (KeyError, ValueError, OSError, csv.Error):
                rows = []
            if len(rows) != len(items):
                rows = [{} for _ in items]
            for item, row in zip(items, rows):
                if component.get("kind") == "tokens":
                    item["card"] = _token_for(row)
                    continue
                item["set"] = row.get("set", "") or ""
                item["collector_number"] = row.get("collector_number", "") or ""
                item["finish"] = row.get("finish", "") or ""
                item["card"] = _card_for(item["name"], item["set"], item["collector_number"], cache)
    for row in answer.get("to_buy", []):
        if shopping_missing.is_token(row):
            row["is_token"] = True
        row["card"] = _card_for(row["name"], row.get("set", ""), row.get("collector_number", ""), cache)


# -------------------------------------------------------------- delivery checks

def _text(value, label, limit):
    if not isinstance(value, str) or not value.strip() or len(value) > limit or "\0" in value:
        raise ApiError(400, f"{label} must be text of at most {limit} characters")
    return value


def resolve_check(body):
    """POST /api/shopping/check {"profile", "order", "component", "check"}: mark one open check of
    a received component done: the inventory's order.checks operation with resolve (as `python -m
    decklab.db order checks ID C --resolve N`), so the check moves to the component's
    verified_checks, one change in the audit trail, by the profile. check is the check's text as
    Shopping showed it; the operation resolves the first open check with exactly that text, against
    the inventory as it was read (409 when it changed meanwhile, or the check is gone).

    Needs orders.edit (an admin) and a profile that sees home's inventory (guard.py). A pending
    component's checks are verified at its receipt instead (400), and a cancelled one has none to
    mark (400). Returns {"resolved": True,
    "order", "component", "checks": the checks still open}."""
    data = _parse_body(body)
    _keys(data, ("profile", "order", "component", "check"))
    profile = _writer(data)
    guard.require(profile, "orders.edit")
    guard.require_sees_home_records(profile)
    order = _text(data["order"], "order", 160)
    component = _text(data["component"], "component", 160)
    check = _text(data["check"], "check", MAX_CHECK)
    try:
        inv = inventory.current()
        _, found = order_ops._component(inv, order, component)
        if found.status == "cancelled":
            raise ApiError(400, "This part of the order was cancelled, so it has no checks to mark done.")
        if found.status != "received":
            raise ApiError(400, "This delivery hasn't been received yet: its checks are verified when it's "
                                "received (Receive delivery).")
        open_checks = list(found.checks or [])
        if check not in open_checks:
            raise ApiError(409, "That check is already done or has changed. Reload Shopping to see it as it is.")
        params = {"order": order, "component": component, "resolve": open_checks.index(check) + 1}
        from .saving import inventory_write_lock
        with inventory_write_lock():
            after, _ = inventory.apply(inventory.Op("order.checks", params), _web_actor(profile),
                                       f"Mark a check done on order {order} ({component})",
                                       expected_revision=inv.revision)
        left = list(order_ops._component(after, order, component)[1].checks or [])
    except ApiError:
        raise
    except inventory.Unavailable:
        raise ApiError(503, DATABASE_DOWN, reason="database") from None
    except inventory.Conflict:
        raise ApiError(409, "Shopping changed meanwhile. Reload it and try again.") from None
    except (inventory.Invalid, ValueError) as error:
        raise ApiError(400, f"The check couldn't be marked done: {_public(error)}") from None
    return {"resolved": True, "order": order, "component": component, "checks": left}
