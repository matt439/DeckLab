"""The Receipts page: inspect a recorded delivery, preview its receipt, then record it
(lib/inventory/receive.py's operation, which `python -m decklab.db receive` shares).

    GET  /api/receipt?order=ID      the delivery: {order, seller, ordered_on, notes, components
                                    (each with fields and rows; the board's pictures and decks,
                                    a product's items), fingerprint, today, kits, face_names}
    POST /api/receipt/preview       {profile, order, fingerprint, received_on, components}
    POST /api/receipt/apply         {profile, preview}

fingerprint is the sha256 (hex) of the inventory's revision when the delivery was read. A
preview refuses (409) when the inventory has moved on since, runs the receipt on the snapshot
in memory (inventory.preview: nothing is written) and lists what it would change: the
parts of the inventory and the decks whose tables the receipt refreshes, in plain words
(inventory.changed_labels, not paths), both from the one previewed change, whose deck-table
refresh runs inside it (the receipt is registered with refresh=True: inventory/refresh.py's
in_op); "tables" says which decks' tables it refreshes ({written, skipped, error}). It refuses
(400), as the receipt planner always has, when the deck tables can't be refreshed from that pool
(unknown cards, pool warnings). The preview is kept for 30 minutes as {revision, order, date, the components as
given}, for the profile that made it, and used once: apply runs
the same operation again with expected_revision set to the preview's revision (409 when the
inventory changed in between), so the browser never sends what to write.

Each selected cards/tokens component may include take: [{row, quantity?}], indexing
the full submitted rows (or the stored rows when omitted). A proper subset is
split and received atomically; assignments describes its received and pending
component ids and copy counts. Products remain whole. Apply also returns every
remaining pending component's count and the saved inventory fingerprint; the
page reloads the delivery before continuing with those remaining copies.

Apply: inventory.apply(...) saves the receipt and the deck tables it refreshes as one change
("receive <order>", by the profile). With the database it holds only the inventory's own lock,
so a slow database never holds up deck saves; the files backend also takes saving._save_lock
first (the lock order: _save_lock, then the inventory lock). A preview is still used once: a
second apply of it finds the revision moved. The deck tables' outcome is the change's own
(Summary.extra["tables"]: {written, skipped, error}), in "tables". A refresh that
fails leaves the decks as they were and the receipt saved, the tables on the Decks page's
"Tables out of date" list (GET /api/tables/stale; its Update all refreshes them).
"""
import hashlib
import json
import time
import traceback
import uuid
import zlib
from datetime import datetime, timedelta, timezone
from pathlib import PurePosixPath

from decklab.lib import cards, config, inventory, spaces
from decklab.lib.decks.identity import CardIdentityError, deck_colors
from decklab.lib.inventory import files, receive, rules
from decklab.lib.tokens import details as token_details
from . import common
from .card_lookup import _card_json, _shown_printing, image_url
from .carddata import _index_info, _require_cards
from .common import DATABASE_DOWN, LINE_FINISHES, ApiError, _keys, _parse_body, _public
from . import guard
from .settings import _writer

PREVIEW_LIFETIME = 1800
_ID_LENGTH = 32
_HEX = set("0123456789abcdef")


def _hex(value, length):
    return isinstance(value, str) and len(value) == length and set(value) <= _HEX


def _receipt_today():
    """The household's date (UTC+10), independent of the server's timezone."""
    return datetime.now(timezone(timedelta(hours=10))).date().isoformat()


def fingerprint(revision):
    """What the page sends back to say which inventory it saw: the sha256 of the revision."""
    return hashlib.sha256(revision.encode("utf-8")).hexdigest()


def _folder(name):
    return config.REPO / "decklab/data" / name


def _order(value):
    if not isinstance(value, str) or len(value) > 160 or not rules.SLUG.fullmatch(value):
        raise ApiError(400, "Choose a valid order")
    return value


def _actor(profile):
    """Who receives, for the audit trail: the writer's profile, the listener the request came
    through, by a receipt."""
    return inventory.Actor(profile["id"], profile["name"], "home" if guard.local() else "tunnel", "receipt")


def receipt_view(order=None):
    """GET /api/receipt?order=ID. No card cache is needed to inspect deliveries: without it the
    pictures and decks are None and the page draws text tiles. The deliveries are home's: 403 for
    anyone outside the home (guard.require_sees_home_records).

    Besides receive.delivery's {order, seller, ordered_on, notes, components} and the fingerprint,
    for the check-off board (read side only; the preview and apply contract doesn't change):
    - today: the household's date (the Arrived control's default and its latest choice);
    - each cards or tokens component's "pictures", aligned with its rows and kept out of them
      (receive._edited wants exactly the payload's columns back): _card_picture's or
      _token_picture's, None for a row with no card match; the list is None while the card
      data isn't ready;
    - each product component's "product" ({name, format}) and "items" (its card list: name, set,
      collector_number, finish, quantity, section, deck), with "pictures" aligned with the items;
    - each cards or product component's "decks", aligned with its rows (or items): the home decks
      whose planned list names that card ([{id, title, status, uses, waiting, colors}]: uses the copies
      the list names, waiting the copies it counts on from this component, pool.row_labels');
      a row is None when its logical card name cannot be resolved, and [] means the known
      card has no matching deck; the whole list is None for tokens, while the card data isn't
      ready, or when the decks can't be read; colors is the same Planned identity as the library,
      from the target sections already read (None unknown, [] known colourless);
    - "kits": {deck id: {"sleeves": name}} for the built decks those name, only where this viewer
      sees that deck's sleeves (guard.sees_kit, the accessories' owner rule), for "Where these go";
    - "face_names": Scryfall's token face names when the order has a tokens component ([] while
      the card data isn't ready), for the token sheet's suggestions;
    - "keywords": the keywords a token's details may list (lower case), for its "Read as" line,
      as the server's parse_details reads them."""
    guard.require_sees_home_records()
    _order(order)
    try:
        inv = inventory.current()
        view = receive.delivery(inv, order)
        record = receive.record(inv, order)
    except inventory.Unavailable:
        raise ApiError(503, DATABASE_DOWN, reason="database") from None
    except (inventory.Invalid, ValueError, KeyError, TypeError) as error:
        raise ApiError(409, f"The delivery couldn't be read: {_public(error)}") from None
    with inventory.pinned(inv):         # the decks and the pool from the same snapshot, loaded once
        return _board(inv, dict(view, fingerprint=fingerprint(inv.revision)), record)


# ------------------------------------------------------------------ the board's read side

def _board(inv, view, record):
    """The check-off board's additions to a delivery view (see receipt_view), in place."""
    view.update(today=_receipt_today(), kits={}, face_names=[], keywords=sorted(token_details._keywords()))
    ready = _index_info()[0] is not None
    by_id = {component.id: component for component in record.components}
    from . import arrival_checks
    target_support = arrival_checks.supported()
    for item in view["components"]:
        component = by_id.get(item["id"])
        if component is not None:
            item.pop("check_links", None)  # Only authoritative projected proofs leave this boundary.
            item.update(arrival_checks.projection(component, item.get("rows", []), item.get("fields", []), target_support))
    for item in view["components"]:
        if item["kind"] == "product":
            _product_items(inv, by_id.get(item["id"]), item)
        rows = item["items"] if item["kind"] == "product" else item["rows"]
        item["pictures"] = _pictures(item["kind"], rows) if ready else None
        item["decks"] = None
    if ready:
        if any(item["kind"] == "tokens" for item in view["components"]):
            view["face_names"] = cards.token_face_names()
        _deck_uses(inv, view, by_id)
    return view


def _product_items(inv, component, item):
    """A product component's card list and display name, put in item (no items when it can't be read)."""
    product = inv.product(component.product_stem) if component is not None and component.product_stem else None
    item["product"] = {"name": getattr(product, "name", None), "format": getattr(product, "format", None)}
    item["items"] = []
    if product is None or product.error is not None:
        return
    for row in product.items:
        item["items"].append({key: (row.get(key) or "") for key in
                              ("name", "set", "collector_number", "finish", "quantity", "section", "deck")})


def _pictures(kind, rows):
    """The pictures aligned with rows (see receipt_view); a row that fails is None."""
    out = []
    for row in rows:
        try:
            out.append(_token_picture(row) if kind == "tokens" else _card_picture(row))
        except (KeyError, TypeError, ValueError):
            out.append(None)
    return out


def _card_picture(row):
    """{card (card_lookup._card_json of the recorded printing, or of the card's usual one), exact,
    why (None, "not recorded" or "not in card data"), set_name, finishes (the recorded printing's)}
    for a cards row, or None when no card has its name."""
    exact_name = _exact(row.get("name"))
    card = cards.card(exact_name) if exact_name else None
    if card is None:
        return None
    set_code, number = (row.get("set") or "").lower(), row.get("collector_number") or ""
    p = cards.printing(set_code, number) if set_code and number else None
    printed = cards.printing_card(set_code, number) if p else None
    exact = printed is not None and printed["name"] == card["name"]
    if exact:
        card = printed
    shown = p if exact else _shown_printing(card, (set_code,))
    why = None if exact else ("not recorded" if not (set_code and number) else "not in card data")
    return {"card": _card_json(card, shown), "exact": exact, "why": why,
            "set_name": (p.get("set_name") or set_code.upper()) if exact else None,
            "finishes": [f for f in p["finishes"] if f in LINE_FINISHES] if exact else []}


_token_images = {"built": None, "faces": {}}


def _token_image(name):
    """(set, number) of a picture of a token face by name (the first token with that face and a
    picture), or None."""
    built = cards.info()["built_at"]
    if _token_images["built"] != built:
        faces = {}
        for entry in cards._get().data["tokens"].values():
            if entry.get("image"):
                for face in (*entry["face_names"], entry["name"]):
                    faces.setdefault(face, tuple(entry["image"]))
        _token_images.update(built=built, faces=faces)
    exact = cards.token_face(name) if isinstance(name, str) and name else None
    return _token_images["faces"].get(exact) if exact else None


def _token_picture(row):
    """{img, img_small, back_img, back_img_small, exact, why} for a tokens row: the recorded
    printing's front picture and, when the back is its own printing, the back's (a double-faced
    printing's back side otherwise); without a recorded printing, a picture of a token with the
    front's name (exact False, why "not recorded" or "not in card data"). None when nothing can be
    shown."""
    set_code = (row.get("set") or "").lower()
    front, back = row.get("front_collector_number") or "", row.get("back_collector_number") or ""
    out = {"img": None, "img_small": None, "back_img": None, "back_img_small": None, "exact": False, "why": None}
    if set_code and front and cards.token_faces_at(set_code, front) is not None:
        out.update(img=image_url(set_code, front, "normal"), img_small=image_url(set_code, front, "small"), exact=True)
        if row.get("back"):
            if back and back != front and cards.token_faces_at(set_code, back) is not None:
                out.update(back_img=image_url(set_code, back, "normal"),
                           back_img_small=image_url(set_code, back, "small"))
            elif (cards.printing(set_code, front) or {}).get("image_normal-back"):
                out.update(back_img=image_url(set_code, front, "normal-back"),
                           back_img_small=image_url(set_code, front, "small-back"))
        return out
    found = _token_image(row.get("front"))
    if found is None:
        return None
    out.update(img=image_url(*found, "normal"), img_small=image_url(*found, "small"),
               why="not recorded" if not (set_code and front) else "not in card data")
    other = _token_image(row.get("back"))
    if other is not None:
        out.update(back_img=image_url(*other, "normal"), back_img_small=image_url(*other, "small"))
    return out


def _planned_colors(sections):
    """Optional Planned/library identity from the target sections already read for a visible deck."""
    try:
        return deck_colors(sections)
    except (CardIdentityError, OSError, EOFError, UnicodeError, json.JSONDecodeError, zlib.error):
        return None


def _deck_uses(inv, view, by_id):
    """Fill each cards and product component's "decks" and the view's "kits" (see receipt_view).
    Any failure leaves them None and {} (logged): the board still works without them."""
    try:
        from decklab.lib import decks, pool
        wanted = set()
        for item in view["components"]:
            if item["kind"] in ("cards", "product"):
                rows = item["items"] if item["kind"] == "product" else item["rows"]
                wanted.update(_exact(row.get("name")) for row in rows)
        wanted.discard(None)
        summaries = []
        if wanted:
            sees = guard.deck_reader()
            for summary in decks.list_decks():
                try:
                    space, kind, _ = decks.split_id(summary.get("id"))
                except ValueError:
                    continue
                if (space == spaces.HOME and summary.get("space", space) == spaces.HOME
                        and kind in ("casual", "commander") and summary.get("kind") == kind
                        and not summary.get("error") and sees(summary)):
                    summaries.append(summary)
        found = pool.load_pool() if summaries else None
        uses = {}           # name -> [(summary, owned-vs-needed row)]
        for summary in summaries:
            try:
                sections = decks.load_deck(summary["id"], "target")
            except (decks.DeckNotFound, decks.DeckFileError, OSError):
                continue
            if not {_exact(line.name) for lines in sections.values() for line in lines} & wanted:
                continue
            result = pool.owned_vs_needed(summary["id"], "target", pool=found, prices=False)
            summary = dict(summary, colors=_planned_colors(sections))
            for r in result["rows"]:
                if r["name"] in wanted:
                    uses.setdefault(r["name"], []).append((summary, r))
        for item in view["components"]:
            if item["kind"] not in ("cards", "product"):
                continue
            label = _incoming_label(inv, by_id.get(item["id"]))
            rows = item["items"] if item["kind"] == "product" else item["rows"]
            item["decks"] = []
            for row in rows:
                exact = _exact(row.get("name"))
                # Unknown logical names cannot establish that no deck is waiting. Printing and
                # picture availability are independent of this logical-card confidence.
                item["decks"].append(None if exact is None else [
                    {"id": summary["id"], "title": summary["title"], "status": summary["status"],
                     "colors": None if summary["colors"] is None else list(summary["colors"]),
                     "uses": r["need"],
                     "waiting": sum(qty for source, qty in pool.row_labels(r)["on_the_way"]
                                    if source == label)}
                    for summary, r in uses.get(exact, [])])
        view["kits"] = _kits(uses)
    except Exception:           # the board still shows; the log has the details
        common._log("A delivery's decks couldn't be worked out:\n" + traceback.format_exc())
        for item in view["components"]:
            item["decks"] = None
        view["kits"] = {}


def _exact(name):
    return cards.resolve(name) if isinstance(name, str) and name else None


def _incoming_label(inv, component):
    """How the pool names this component's copies on the way (pool._load_pool's labels), or None."""
    if component is None or not isinstance(component.path, str):
        return None
    if component.kind != "product":
        return f"order {PurePosixPath(component.path).stem}"
    from decklab.lib import pool
    status = pool.read_status([]).get(component.file_name)
    return f"{pool._product_name(component.file_name)}, {status.status}" if status is not None else None


def _kits(uses):
    """{deck id: {"sleeves": name}} of the built decks in uses whose sleeves this viewer sees
    (guard.sees_kit); none for a viewer who sees no accessories."""
    built = {summary["id"]: summary for found in uses.values() for summary, _ in found
             if summary["status"] == "built"}
    owners = guard.accessory_readers()
    if not built or (owners is not None and not owners):
        return {}
    from .deck_page import _index_kits
    kits = _index_kits(list(built.values()))
    out = {}
    for deck_id, summary in built.items():
        if not guard.sees_kit(summary, owners):
            continue
        sleeves = (kits(summary) or {}).get("sleeves")
        if sleeves and sleeves.get("name"):
            out[deck_id] = {"sleeves": sleeves["name"]}
    return out


def _validate_request(data):
    _keys(data, ("profile", "order", "fingerprint", "received_on", "components"))
    profile = _writer(data)
    guard.require(profile, "receipts.apply")
    guard.require_sees_home_records(profile)     # nor a person named on the home network
    _order(data["order"])
    if not _hex(data["fingerprint"], 64):
        raise ApiError(400, "Reload the delivery before preparing a receipt")
    try:
        if not isinstance(data["received_on"], str):
            raise ValueError("Receipt date must be YYYY-MM-DD")
        rules.valid_date(data["received_on"])
        if data["received_on"] > _receipt_today():
            raise ValueError("An actual arrival date cannot be in the future (home time)")
    except ValueError as error:
        raise ApiError(400, str(error)) from None
    components = data["components"]
    if not isinstance(components, list) or not 1 <= len(components) <= 30:
        raise ApiError(400, "Select at least one arrived component (up to 30)")
    seen = set()
    for item in components:
        if not isinstance(item, dict):
            raise ApiError(400, "Each arrived component must be an object")
        _keys(item, ("id", "verified"), ("rows", "intact", "take"))
        if not isinstance(item["id"], str) or len(item["id"]) > 160 or item["id"] in seen:
            raise ApiError(400, "Each component must be selected once")
        seen.add(item["id"])
        if not isinstance(item["verified"], bool):
            raise ApiError(400, "verified must be true or false")
        if "intact" in item and item["intact"] not in ("yes", "no"):
            raise ApiError(400, "Choose whether the product is kept intact")
        if "take" in item:
            take = item["take"]
            if not isinstance(take, list) or not 1 <= len(take) <= 500:
                raise ApiError(400, "Select 1 to 500 arrived rows")
            selected = set()
            for choice in take:
                if not isinstance(choice, dict):
                    raise ApiError(400, "Each arrived selection must be an object")
                _keys(choice, ("row",), ("quantity",))
                number = choice["row"]
                if type(number) is not int or number < 1 or number in selected:
                    raise ApiError(400, "Arrived row numbers must be distinct positive integers")
                selected.add(number)
                if "quantity" in choice and (type(choice["quantity"]) is not int or choice["quantity"] < 1):
                    raise ApiError(400, "Arrived quantities must be positive integers")
        if "rows" in item:
            if not isinstance(item["rows"], list) or not 1 <= len(item["rows"]) <= 500:
                raise ApiError(400, "A component must have 1 to 500 card rows")
            for row in item["rows"]:
                if not isinstance(row, dict) or any(not isinstance(value, str) or len(value) > 2000
                                                  or "\0" in value for value in row.values()):
                    raise ApiError(400, "Card fields must be text of at most 2000 characters")
    return profile


def preview_receipt(body):
    data = _parse_body(body)
    profile = _validate_request(data)
    _require_cards()
    operation = receive.op(data["order"], data["components"], data["received_on"])
    try:
        before = inventory.current()
        if fingerprint(before.revision) != data["fingerprint"]:
            raise ApiError(409, "Delivery or inventory changed. Reload the delivery and inspect it again.")
        found = receive.blockers(before, operation)
        if found:
            return {"ready": False, "blockers": found, "totals": [], "changes": []}
        after, summary = inventory.preview(operation)
        tables = _tables(summary)
        if tables["error"] and tables["error"] != inventory.DECK_SAVES_PAUSED:
            raise ApiError(400, f"Receipt preview couldn't be prepared: {tables['error']}")
    except ApiError:
        raise
    except inventory.Unavailable:
        raise ApiError(503, DATABASE_DOWN, reason="database") from None
    except inventory.Conflict as e:
        raise ApiError(409, f"The receipt couldn't be prepared: {_public(e)}") from None
    except (inventory.Invalid, ValueError, OSError) as e:
        raise ApiError(400, f"Receipt preview couldn't be prepared: {_public(e)}") from None
    token = uuid.uuid4().hex
    cached = {"version": 2, "created": time.time(), "profile": profile["id"], "by": profile["name"],
              "order": data["order"], "received_on": data["received_on"], "revision": before.revision,
              "components": operation.params["components"], "totals": summary.extra["totals"]}
    try:
        files.atomic_write(_folder("receipt-previews") / f"{token}.json", rules.json_bytes(cached))
    except OSError as e:
        raise ApiError(500, f"The receipt preview couldn't be kept: {_public(e)}") from None
    return {"ready": True, "preview": token, "order": data["order"], "received_on": data["received_on"],
            "totals": summary.extra["totals"], "changes": inventory.changed_labels(before, after), "blockers": [],
            "components": summary.extra["components"],
            "assignments": summary.extra["assignments"],
            "tables": {key: tables[key] for key in ("written", "skipped", "error")}}


def _tables(summary):
    """The deck tables' outcome of a receipt's change (refresh.in_op's Summary.extra["tables"]:
    {written, skipped, error}); one saying nothing was refreshed when there's none."""
    found = (summary.extra or {}).get("tables")
    return dict(found) if isinstance(found, dict) else {"written": [], "skipped": [], "error": None}


def _load_preview(token, profile):
    if not _hex(token, _ID_LENGTH):
        raise ApiError(400, "Prepare a receipt preview first")
    path = _folder("receipt-previews") / f"{token}.json"
    try:
        record = json.loads(path.read_bytes())
    except (OSError, ValueError):
        raise ApiError(409, "This receipt preview is unavailable. Prepare a new preview.") from None
    if not isinstance(record, dict) or record.get("version") != 2 or record.get("profile") != profile["id"] \
            or not isinstance(record.get("created"), (int, float)) \
            or not 0 <= time.time() - record["created"] <= PREVIEW_LIFETIME \
            or not isinstance(record.get("revision"), str) or not isinstance(record.get("components"), list) \
            or not isinstance(record.get("received_on"), str):
        raise ApiError(409, "This preview belongs to another person or has expired. Prepare a new preview.")
    _order(record.get("order"))
    return path, record


def _remaining(inv, order_id):
    """Counts from the saved snapshot; the next delivery view supplies its editable rows."""
    order = inv.order(order_id)
    if order is None:
        return []
    result = []
    for component in order.components:
        if component.status != "pending":
            continue
        if component.kind == "product":
            product = inv.product(component.product_stem)
            rows = product.items if product is not None else ()
        else:
            payload = inv.payloads.get(component.path)
            rows = payload.rows if payload is not None else ()
        quantity = sum(row.qty or 0 for row in rows)
        result.append({"id": component.id, "kind": component.kind, "quantity": quantity})
    return result


def apply_receipt(body):
    from .saving import inventory_write_lock
    data = _parse_body(body)
    _keys(data, ("profile", "preview"))
    profile = _writer(data)
    guard.require(profile, "receipts.apply")
    guard.require_sees_home_records(profile)
    actor = _actor(profile)
    path, record = _load_preview(data["preview"], profile)
    operation = receive.op(record["order"], record["components"], record["received_on"])
    try:
        # The files backend writes the refreshed deck files with it: after any deck save, as before.
        with inventory_write_lock():
            after, summary = inventory.apply(operation, actor, f"receive {record['order']}",
                                         expected_revision=record["revision"])
    except inventory.Unavailable:
        raise ApiError(503, DATABASE_DOWN, reason="database") from None
    except inventory.Conflict as e:
        if str(e) == files.MOVED_MESSAGE:
            raise ApiError(409, "Inventory or delivery records changed since this preview. Reload and preview "
                                "again.") from None
        raise ApiError(409, f"The receipt couldn't finish: {_public(e)}") from None
    except (inventory.Invalid, ValueError, OSError, RuntimeError) as e:
        raise ApiError(409, f"The receipt couldn't finish: {_public(e)}") from None
    path.unlink(missing_ok=True)
    return {"received": True, "order": record["order"], "totals": summary.extra["totals"],
            "assignments": summary.extra["assignments"], "remaining": _remaining(after, record["order"]),
            "fingerprint": fingerprint(after.revision),
            "tables": _tables(summary)}
