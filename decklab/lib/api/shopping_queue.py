"""Add, edit, remove or move a purchase queue row as one audited change.

POST /api/shopping/queue keeps its original {profile, row, state, expect}
state-change contract. An explicit action add/edit takes values; remove takes
a reason. Row numbers always need the exact inventory revision Shopping gave.
While MTGMate's snapshot exists, a kept row's answer carries its "shop_snapshot" again
(shop_prices.py), since a changed printing or state changes what the snapshot says about it.
"""
from decklab.lib import cards, config, inventory, purchases
from decklab.lib.inventory import orders as order_ops  # registers watchlist.set/remove

from . import guard
from .card_lookup import _pickable
from .carddata import _require_cards
from .common import (DATABASE_DOWN, MAX_NAME, NUMBER_RE, SET_RE, _CONTROL_RE,
                     ApiError, _keys, _parse_body, _public)
from .settings import _web_actor, _writer


CHANGED = "Shopping changed meanwhile. Reload it and try again."
EDIT_FIELDS = ("name", "state", "quantity", "for", "source", "printing", "set",
               "collector_number", "finish", "notes")
IDENTITY_FIELDS = {"name", "set", "collector_number", "finish"}


def _values(value):
    if not isinstance(value, dict) or not value:
        raise ApiError(400, "values must give the purchase queue details to save")
    _keys(value, (), EDIT_FIELDS)
    result = {}
    for key, item in value.items():
        if key == "quantity":
            if (isinstance(item, bool) or not isinstance(item, (str, int))
                    or not str(item).isascii() or not str(item).isdigit()):
                raise ApiError(400, "quantity must be a positive whole number")
            try:
                quantity = int(item)
            except ValueError:
                raise ApiError(400, "quantity must be a positive whole number") from None
            if quantity < 1:
                raise ApiError(400, "quantity must be a positive whole number")
            result[key] = str(quantity)
        else:
            if not isinstance(item, str) or _CONTROL_RE.search(item):
                raise ApiError(400, f"{key} must be single-line text with no control characters")
            result[key] = item.strip()
    if "state" in result and result["state"] not in purchases.STATES:
        raise ApiError(400, f"state must be one of: {', '.join(purchases.STATES)}")
    if "name" in result and (not result["name"] or len(result["name"]) > MAX_NAME):
        raise ApiError(400, f"Give a card name of at most {MAX_NAME} characters")
    return result


def _card_values(values, old=None):
    """Check changed card identity locally, including token/reminder singles.

    Quantity, notes and state changes still work while card data is unavailable.
    Existing retailer observations are not fields the page may overwrite.
    """
    if old is not None and not IDENTITY_FIELDS.intersection(values):
        return values
    candidate = {key: old.text(key) if old else "" for key in EDIT_FIELDS}
    candidate.update(values)
    name, set_code, number = (candidate[key] for key in ("name", "set", "collector_number"))
    if not name or len(name) > MAX_NAME:
        raise ApiError(400, f"Give a card name of at most {MAX_NAME} characters")
    if (bool(set_code) != bool(number)
            or set_code and (not SET_RE.fullmatch(set_code) or not NUMBER_RE.fullmatch(number))):
        raise ApiError(400, "Give both set and collector_number for a printing, or leave both empty")
    _require_cards()
    exact, token = cards.resolve(name), cards.token_face(name)
    if exact is None and token is None:
        raise ApiError(404, f"No Scryfall card or token named {name!r}; choose a card from the search results")
    if set_code:
        printing = cards.printing(set_code, number)
        printed = cards.printing_card(set_code, number)
        faces = cards.token_faces_at(set_code, number)
        if printed and printed["name"] == exact:
            pass
        elif faces and token in [*faces[1], " // ".join(faces[1])]:
            exact = token
        else:
            raise ApiError(400, "That printing doesn't match the card or token name")
        if not _pickable(printing):
            raise ApiError(400, "Choose a physical paper printing")
        if candidate["finish"] and candidate["finish"] not in printing["finishes"]:
            raise ApiError(400, "That finish isn't available for this printing")
    elif exact is not None:
        card = cards.card(exact)
        if not any(_pickable(cards.printing(s, n)) for s, n in card["printings"]):
            raise ApiError(400, "The purchase queue is for physical cards; choose a card with a paper printing")
    return {**values, "name": exact or token}


def save_queue_state(body):
    """Save a queue operation while preserving the original state-change API.

    Needs orders.edit and access to home's inventory. Both the early comparison
    and the backend's transactional expected_revision check are exact: a stale
    row number must never select another purchase request.
    """
    data = _parse_body(body)
    action = data.get("action", "state")
    if not isinstance(action, str) or action not in ("state", "add", "edit", "remove"):
        raise ApiError(400, "action must be add, edit, remove or state")
    required = {"state": ("row", "state"), "add": ("values",),
                "edit": ("row", "values"), "remove": ("row", "reason")}[action]
    _keys(data, ("profile", "expect", *required), ("action",))
    profile = _writer(data)
    guard.require(profile, "orders.edit")
    guard.require_sees_home_records(profile)
    row, expect = data.get("row"), data["expect"]
    if action != "add" and (not isinstance(row, int) or isinstance(row, bool) or row < 1):
        raise ApiError(400, "row must be a positive whole number")
    if not isinstance(expect, str) or not expect.strip() or len(expect) > 256 or "\0" in expect:
        raise ApiError(400, "expect must be the inventory revision Shopping gave")
    if action == "state":
        values = _values({"state": data["state"]})
    elif action != "remove":
        values = _values(data["values"])
    reason = None
    if action == "remove":
        reason = data["reason"]
        if not isinstance(reason, str) or not reason.strip() or _CONTROL_RE.search(reason):
            raise ApiError(400, "Give a single-line reason why this card is removed from the purchase queue")
        reason = reason.strip()
    try:
        inv = inventory.current()
        if inv.revision != expect:
            raise ApiError(409, CHANGED)
        if action != "add" and row > len(inv.watchlist.rows):
            raise ApiError(400, "That purchase queue row doesn't exist. Reload Shopping to see it as it is.")
        if action == "remove":
            op = inventory.Op("watchlist.remove", {"select": f"#{row}"})
            message = "Remove a card from the purchase queue"
        else:
            if action == "add":
                values = {"state": "ready", "quantity": "1", "printing": "any", "finish": "nonfoil", **values}
                values = _card_values(values)
                row = len(inv.watchlist.rows) + 1
                params = {"add": True, "values": values, "repo": str(config.REPO)}
                message = "Add a card to the purchase queue"
            else:
                if action == "edit":
                    values = _card_values(values, inv.watchlist.rows[row - 1])
                params = {"select": f"#{row}", "values": values, "repo": str(config.REPO)}
                message = (f"Change a purchase queue card to {values['state']}" if action == "state"
                           else "Edit a card in the purchase queue")
            op = inventory.Op("watchlist.set", params)
        from .saving import inventory_write_lock
        with inventory_write_lock():
            kwargs = {"expected_revision": expect}
            if reason is not None:
                kwargs["reason"] = reason
            after, _ = inventory.apply(op, _web_actor(profile), message, **kwargs)
    except ApiError:
        raise
    except inventory.Unavailable:
        raise ApiError(503, DATABASE_DOWN, reason="database") from None
    except inventory.Conflict:
        raise ApiError(409, CHANGED) from None
    except (inventory.Invalid, ValueError) as error:
        raise ApiError(400, f"The purchase queue couldn't be changed: {_public(error)}") from None
    result = {"saved": True, "row": row, "revision": after.revision}
    if action != "remove":
        current_item = after.watchlist.rows[row - 1]
        from .reprints import evidence
        result["reprints"] = evidence({key: current_item.text(key) for key in purchases.QUEUE_FIELDS}, queued=True)
        from .shop_prices import for_row
        shown = for_row({key: current_item.text(key) for key in purchases.QUEUE_FIELDS})
        if shown is not None:
            result["shop_snapshot"] = shown
    if action == "state":
        return {**result, "state": values["state"]}
    result["action"] = action
    if action != "remove":
        item = after.watchlist.rows[row - 1]
        result["item"] = {key: item.text(key) for key in purchases.QUEUE_FIELDS}
        result["item"]["quantity"] = int(item.text("quantity"))
        if result["reprints"] is not None:
            result["item"]["reprints"] = result["reprints"]
        if "shop_snapshot" in result:
            result["item"]["shop_snapshot"] = result["shop_snapshot"]
        from .shopping_missing import is_token
        if is_token(result["item"]):
            result["item"]["is_token"] = True
        result["state"] = item.state
        if action == "add":
            from .shopping import _card_for, _token_for
            try:
                token = cards.token_faces_at(item.set, item.collector_number) if item.set and item.collector_number else None
            except cards.INDEX_ERRORS:
                token = None
            result["item"]["card"] = (_token_for({"front": item.name, "set": item.set,
                                                 "front_collector_number": item.collector_number})
                                      if token else _card_for(item.name, item.set, item.collector_number))
    return result
