"""The Accessories page's API: the sleeves, deck boxes and playmats (the inventory's
accessories.csv), their pictures, and which built deck or intact product holds which
(lib/accessories.py reads all of it from the inventory's snapshot). Imported when first needed,
by feature_routes.dispatch and the server's /accessory-img/ route.

    GET  /api/accessories            accessories_view(): rows, products, holders, problems
    POST /api/accessories/fetch      fetch_picture(body): stage a picture from a link
    POST /api/accessories/save       save_accessory(body): add, edit or remove a row
    POST /api/accessories/assign     assign_accessory(body): set a holder's sleeves or deck box
    image_file(name, version), staged_image(name)    the bytes behind /accessory-img/...

Every write is one inventory operation through inventory.apply, whichever backend holds the
inventory (lib/inventory/ops_accessories.py): accessory.add, accessory.edit and accessory.remove
(a new picture's bytes go in the same operation, so a row and its picture are saved together or
not at all), and kit.set, which makes every sleeve and deck-box move between decks and products
in one change. With the database each write is one change set in the audit trail ("<what> (by
<Name>)"'s words without the name, by the profile); with the files backend (tests, rollback) the
files are written under the inventory's lock. Nothing is committed to git.

The list must still have the token the page loaded: GET's sha256 is per writer
(accessories.view_sha256: only the rows that viewer may change, never public read-only rows), and the operation
checks it again under the inventory's lock (409 with "conflict" and "latest", the view as it is
now, otherwise). Who made the change that got in the way comes from the audit trail's last change
of a row the viewer sees (by and when; its words only to whoever made it, since an accessory
change names accessories, which are private from admins too); the files backend keeps no trail,
so then they're None. A holder's holder_sha256 is the sha256 of its deck's text (Deck.sha256) or,
for a product, of status.csv as rendered (accessories.status_sha256); a changed deck's conflict
names its last revision (inventory.last_revision), a changed product's the audit trail's last
change of any product row.

Each row has an owner (lib/accessories.py): a home profile's id or "shared". Every answer shows
the viewer the rows of guard.accessory_readers (own/shared plus Public), each with editable.
Holder titles also need deck visibility; outsiders see "a home deck" and receive no holder or
product options. Writes use guard.accessory_owners (own/shared only). A write may
touch only the writer's own or shared rows (another's is "not found", as if it weren't there),
and a deck or product takes only its owner's or shared ones (guard.holder_owner): Matt's decks
Matt's, User1's User1's, "either" decks and products shared ones. Choosing a deck's kit is also
an edit of that deck (E10-S42): the writer needs deck.edit on every deck an assign touches, a
move's source included, as the deck page's editor save does; a product's kit needs only what the
Products kept intact panel always has (accessories.edit, the shared kit, home's inventory).

Side effect: a kit.set that changes a product's row changes the inventory's revision, so a
receipt previewed before it must be previewed again; a save or a deck's kit changes only the
decks part's revision (Inventory.decks_revision).
"""
import traceback

from decklab.lib import accessories, accessory_fetch, accessory_upload, inventory, spaces
from decklab.lib.inventory import audit, ops_accessories, rules
from decklab.lib.state import StateError
from decklab.lib.state import rules as state_rules

from . import commits, common, guard, saving
from .commits import _when
from .common import MAX_BODY, ApiError, _keys, _parse_body, _public, _scrub, _unique
from .settings import _web_actor, _writer

MAX_SAVE_FIELDS_BODY = 16 * 1024   # bytes: a row and its base copy, with long links
MAX_SAVE_BODY = MAX_SAVE_FIELDS_BODY + accessory_upload.MAX_BASE64
ROW_KEYS = accessories.ROW_KEYS
IMAGE_TYPES = {"jpg": "image/jpeg", "png": "image/png", "webp": "image/webp"}
VIEW_FAILED = "Saved, but the accessories list couldn't be shown again; reload the page"
_KIND_WORDS = {"sleeves": "sleeves", "deck_box": "deck box", "playmat": "playmat"}
_TITLE = "The accessories list"
_STATUS_TITLE = "The products list"


# ---- reading

def _holder_rows(found):
    """The holders lib/accessories._scan found, as the page lists them."""
    inv = inventory.current()
    products = None
    out = []
    for h in found:
        if h["kind"] == "product":
            if products is None:        # every product shares status.csv's sha, from the inventory
                products = accessories.status_sha256()
            sha = products
        else:
            deck = inv.deck(h["holder"])
            sha = deck.sha256 if deck is not None and deck.error is None else None
        out.append({"id": h["holder"], "title": h["title"], "kind": h["kind"], "owner": h["owner"],
                    "need": accessories.sleeve_need(h["sections"]), "sleeves": h["sleeves"] or None,
                    "deck_box": h["deck_box"] or None, "holder_sha256": sha})
    return out


def _sees_holder(holder):
    """A public row never publishes its private deck or a home's product."""
    if holder["kind"] == "product":
        return guard.sees_home_records()
    return guard.sees_deck(holder["holder"])


def _hidden_holder(holder):
    return (accessories.hidden_title(holder["owner"], holder["kind"]) if guard.sees_home_records()
            else "a home deck")


def _shown_users(users, owners):
    """Only a readable kit owner and a readable holder may reveal its title/id."""
    return [{k: h[k] for k in ("holder", "title", "kind", "need")}
            if accessories.visible(h["owner"], owners) and _sees_holder(h)
            else {"holder": None, "title": _hidden_holder(h), "kind": "deck", "need": h["need"]}
            for h in users]


def read_kit(holder, sections=None, **kwargs):
    """A kit's computed words with both kit-owner and deck visibility applied."""
    return accessories.kit(holder, sections, owners=guard.accessory_readers(),
                           holder_reader=_sees_holder, hidden=_hidden_holder, **kwargs)


def _owner_choices(owners):
    """[{id, name}]: the owners the viewer may give a row (its own and shared; every one for None)."""
    return [{"id": o, "name": accessories.owner_name(o)} for o in accessories.owner_ids()
            if accessories.visible(o, owners)]


def _short(row, users):
    """Sleeves missing for the neediest holder, or deck boxes missing for their holders."""
    if row["kind"] == "sleeves":
        return max([0, *(h["need"] - row["quantity"] for h in users)])
    if row["kind"] == "deck_box":
        return max(0, len(users) - row["quantity"])
    return 0


def accessories_view():
    """GET /api/accessories: {sha256 (the viewer's token, accessories.view_sha256; None while it
    sees no rows), exists (whether the list has a row the viewer sees; for a viewer who sees
    every owner's, whether there's a list at all), items: [row + label, owner_name, image_url, used_by [{holder (None
    for a holder the viewer can't see), title, kind, need}], short], owners ([{id, name}] a row
    may be given), products (owned intact ones: {file, holder, title, sleeves: Ref, deck_box:
    Ref, need, holder_sha256}), holders_options (every built deck and intact product: {id,
    title, kind, owner, need, sleeves, deck_box, holder_sha256}), problems}. ApiError 403 for a
    visitor who may not see the accessories (guard.sees_accessories). Only the rows, holders and
    products whose owner the viewer sees are listed (guard.accessory_owners)."""
    guard.require_sees_accessories()
    owners = guard.accessory_owners()
    readers = guard.accessory_readers()
    warnings = []
    try:
        with common.state_errors():         # the inventory: the database may be down
            snapshot = inventory.current()
            inv = accessories.read()
            found, _ = accessories._scan(warnings)
            options = [o for o in _holder_rows(found) if accessories.visible(o["owner"], owners)]
    except OSError as e:
        raise ApiError(500, f"The accessories list can't be read: {_public(e)}") from None
    usage = accessories._usage(found, inv)
    items = []
    for row in sorted(inv.rows_by_id.values(), key=accessories._sort_key):
        if not accessories.visible(row["owner"], readers):
            continue
        users = accessories.used_by(usage, row)
        items.append({**row, "label": accessories.label(row), "owner_name": accessories.owner_name(row["owner"]),
                      "editable": accessories.visible(row["owner"], owners),
                      "image_url": accessories.image_url(row, snapshot), "used_by": _shown_users(users, readers),
                      "short": _short(row, users)})
    products = [{"file": f"{o['id'].split('/', 1)[1]}.csv", "holder": o["id"], "title": o["title"],
                 "sleeves": accessories.resolve(o["sleeves"], "sleeves", inv),
                 "deck_box": accessories.resolve(o["deck_box"], "deck_box", inv),
                 "need": o["need"], "holder_sha256": o["holder_sha256"]}
                for o in options if o["kind"] == "product"]
    exists = snapshot.accessories.exists if owners is None else any(i["editable"] for i in items)
    problems = _unique(_scrub(inv.problems + warnings))
    if readers is not None:
        problems = ["Some accessory rows or holders can't be read."] if problems and owners else []
    return {"sha256": accessories.view_sha256(inv, owners), "exists": exists,
            "items": items, "owners": _owner_choices(owners), "products": products,
            "holders_options": options, "problems": problems}


def _view_after_write(warnings):
    """accessories_view() for a write that has succeeded, or None with a warning when the list
    can't be shown again (the page reloads it)."""
    try:
        return accessories_view()
    except ApiError as e:
        warnings.append(f"{VIEW_FAILED} ({e.message})")
    except Exception:
        common._log(f"Couldn't show the accessories list after a save:\n{traceback.format_exc()}")
        warnings.append(f"{VIEW_FAILED}; the server log says why")
    return None


# ---- fetch

def fetch_picture(body):
    """POST /api/accessories/fetch {"profile", "url"}: download the picture
    behind a pasted link and stage it (lib/accessory_fetch.py). Returns
    {token, preview_url, width, height, image_source, final_url, guess}."""
    data = _parse_body(body, MAX_BODY)
    _keys(data, ("profile", "url"), ("id",))
    profile = _writer(data)
    guard.require(profile, "accessories.edit")
    if data.get("id") is not None:
        with common.state_errors():
            _require_writable_row(data["id"], accessories.read(), profile)
    if not isinstance(data["url"], str) or not data["url"].strip():
        raise ApiError(400, accessory_fetch.BAD_LINK)
    found = accessory_fetch.fetch(data["url"])
    return {"token": found["token"], "preview_url": f"/accessory-img/staged/{found['token']}.{found['ext']}",
            "width": found["width"], "height": found["height"], "image_source": found["image_source"],
            "final_url": found["final_url"], "guess": found["guess"]}


# ---- who changed it

def _actor_name(actor):
    """A change's actor as the pages name it: the profile's name, else Activity's words."""
    from .activity import ACTOR_NAMES
    from .settings import _config_profiles
    try:
        names = {p["id"]: p["name"] for p in _config_profiles()}
    except ApiError:
        names = {}
    return names.get(actor) or ACTOR_NAMES.get(actor) or actor


def _conflict_keys(change, viewer_id, kit):
    """The "conflict" keys of a 409 (reason, by, deck_lab, when, subject) and the words saying
    who changed it, from an audit change ({at, actor, source, message}) or a deck revision; its
    words (subject) only to its actor when kit (accessories are private, from admins too)."""
    conflict = {"reason": "changed", "by": None, "deck_lab": False, "when": None, "subject": None}
    if change is None:
        return conflict, "it was changed"
    by = _actor_name(change["actor"])
    moment = change["at"]
    message = change["message"] if not kit or change["actor"] == viewer_id else None
    conflict.update(by=by, deck_lab=change["source"] == "web", when=moment.isoformat(),
                    subject=message.splitlines()[0] if message else None)
    if conflict["deck_lab"]:
        return conflict, f"{by} saved it in Deck Lab {_when(moment)}"
    if message:
        return conflict, f"{by} changed it {_when(moment)} (\"{conflict['subject']}\")"
    return conflict, f"{by} changed it {_when(moment)}"


def _conflict_error(profile, owners, reason="changed"):
    """The 409 for a list that changed since the page loaded it (as far as this viewer sees it),
    with the view as it is now: who changed it from the audit trail's last change of a row the
    viewer sees (None with the files backend). The request's pinned snapshot is let go first: a
    write that lost a race was refused inside the operation, after the snapshot was loaded, so
    "latest" must be read again to carry the token that will save."""
    inventory.invalidate()
    try:
        change = audit.last_owned_change(state_rules.ACCESSORY_TABLE, owners)
    except StateError as e:
        common._log(f"Can't read the audit trail for the accessories list: {e}")
        change = None
    conflict, detail = _conflict_keys(change, profile["id"], kit=True)
    conflict["reason"] = reason
    error = ApiError(409, f"{_TITLE} changed after you opened it: {detail}. Your changes weren't saved.",
                     conflict=conflict)
    error.title = _TITLE
    error.extra["latest"] = _view_after_write([])
    return error


def _status_conflict(profile):
    """The 409 for a product holder whose status.csv changed since the page loaded it: who
    changed it from the audit trail's last change of any product's row (the sha the page sent
    covers all of status.csv), its words only to its actor when that change set a kit."""
    try:
        change = audit.last_change("product_status")
        kit = change is not None and audit.is_kit_change(change["id"])
    except StateError as e:
        common._log(f"Can't read the audit trail for the products list: {e}")
        change, kit = None, False
    conflict, detail = _conflict_keys(change, profile["id"], kit)
    error = ApiError(409, f"{_STATUS_TITLE} changed after you opened it: {detail}. Your changes weren't saved.",
                     conflict=conflict)
    error.title = _STATUS_TITLE
    return error


def _deck_conflict(profile, deck_id):
    """The 409 for a deck holder changed since the page loaded it: who changed it from the deck's
    last revision (inventory.last_revision; None with the files backend), its message only as
    DeckRevision.message_for shows it to the writer; "Deck Lab" only for a change the pages
    made (audit.change_source), not a command line's)."""
    inventory.invalidate()          # the deck as it is now, not the request's snapshot
    try:
        rev = inventory.last_revision(deck_id)
        source = audit.change_source(rev.change_set_id) if rev is not None else None
    except StateError as e:
        common._log(f"Can't read {deck_id}'s history: {e}")
        rev, source = None, None
    change = None
    if rev is not None:
        change = {"actor": rev.actor, "at": rev.at, "source": source or "git",
                  "message": rev.message_for(profile["id"]) or ""}
    conflict, detail = _conflict_keys(change, profile["id"], kit=False)
    deck = inventory.current().deck(deck_id)
    title = (ops_accessories.parsed_deck(deck).title if deck is not None and ops_accessories.parsed_deck(deck)
             else deck_id)
    if deck is None:
        conflict["reason"] = "deleted"
    error = ApiError(409, f"{title} changed after you opened it: {detail}. Your changes weren't saved.",
                     conflict=conflict)
    error.title = title
    return error


# ---- save

def _request_sha(value):
    if value is None or isinstance(value, str) and common._SHA_RE.fullmatch(value):
        return value
    raise ApiError(400, "sha256 must be the 64-character hash /api/accessories gave (null before the list exists)")


def _row_input(value):
    if not isinstance(value, dict):
        raise ApiError(400, "row must be an object")
    unknown = sorted(set(value) - set(ROW_KEYS))
    if unknown:
        raise ApiError(400, f"Unknown row key {unknown[0]!r}; a row takes: {', '.join(ROW_KEYS)}")
    for key, item in value.items():
        if key == "quantity":
            if isinstance(item, bool) or not isinstance(item, (int, str)):
                raise ApiError(400, "quantity must be a whole number")
        elif key == "capacity":
            if isinstance(item, bool) or not (item is None or isinstance(item, (int, str))):
                raise ApiError(400, "capacity must be a whole number, or blank")
        elif not isinstance(item, str):
            raise ApiError(400, f"{key} must be text")
    return value


def _image_input(value, action):
    """None, "keep", a staged picture's Path, or checked inline upload bytes."""
    if value is None:
        return None
    if value == "keep" and action == "edit":
        return "keep"
    if isinstance(value, dict) and set(value) == {"token"}:
        path = accessory_fetch.staged_file(value["token"])
        if path is None:
            raise ApiError(409, "That picture has expired (pictures are kept for an hour): find it again, "
                                "or save without a picture.")
        return path
    if isinstance(value, dict) and set(value) == {"upload"}:
        return accessory_upload.decode(value["upload"])
    raise ApiError(400, "image must be {\"token\": ...} from /api/accessories/fetch, "
                        "{\"upload\": base64 bytes}, \"keep\" or null")


def _save_body(body):
    """Only the inline picture gets a larger budget; ordinary row/base fields keep theirs."""
    data = _parse_body(body, MAX_SAVE_BODY)
    picture = data.get("image")
    encoded = picture.get("upload") if isinstance(picture, dict) and set(picture) == {"upload"} else None
    size = len(body.encode("utf-8")) if isinstance(body, str) else len(body)
    if size - (len(encoded) if isinstance(encoded, str) else 0) > MAX_SAVE_FIELDS_BODY:
        raise ApiError(413, f"Accessory fields are limited to {MAX_SAVE_FIELDS_BODY} bytes, apart from the picture.")
    return data


def _apply(op, profile, message, conflict):
    """inventory.apply(op) as the profile, its refusals as the page's answers: conflict(reason)
    gives the 409 for a list or holder changed since the page loaded it."""
    try:
        # saving._save_lock first with the files backend (the lock order), so a write waits for
        # another page's save in this server; nothing with the database.
        with saving.inventory_write_lock():
            return inventory.apply(op, _web_actor(profile), message)
    except ops_accessories.AccessoryRefused as e:
        if e.reason in ("changed", "deleted"):
            raise conflict(e) from None
        raise ApiError(e.code, _public(str(e)), **e.extra) from None
    except ops_accessories.DeckRefused as e:
        if e.code == 404 and e.ids:
            from .deck_aliases import after_refusal
            moved = after_refusal(e.ids[0], profile, kit=True)
            if moved is not None:
                raise moved from None
        if e.reason == "changed":
            raise conflict(e) from None
        raise ApiError(e.code, _public(str(e))) from None
    except inventory.Unavailable:
        raise ApiError(503, common.DATABASE_DOWN, reason="database") from None
    except inventory.Invalid as e:
        raise ApiError(400, _public(str(e))) from None
    except inventory.Conflict as e:
        raise ApiError(409, _public(str(e))) from None
    except OSError as e:
        raise ApiError(500, f"The accessories list can't be read: {_public(e)}") from None


def save_accessory(body):
    """POST /api/accessories/save {"profile", "sha256", "action": "add" |
    "edit" | "remove", "id"? (edit, remove), "base"? (the row as the page
    loaded it; the page merges with it after a 409), "row"? (add, edit: kind,
    owner (the writer's id or "shared"; a new row is the writer's unless it
    says), brand, name, colour, quantity, capacity (a deck box's, blank or null when
    not known; cleared when the kind isn't deck_box and the row doesn't say),
    crop (the part of the picture shown, "x,y,w,h" or blank; cleared with a
    new or removed picture unless the row gives one for it), link,
    image_source, notes), "image"?
    ({"token"} from fetch, {"upload": base64 bytes} from a local file, "keep" or null)}.

    A new row's id is made from its brand, name and colour and never
    changes. A row a deck or product uses can't be removed or change kind
    (409 with "blocks"), nor go to an owner one of its holders can't use.
    A row whose owner the writer doesn't see is 404, as if it weren't there.
    A staged picture is saved with the row in the same change, as
    <id>.<ext>, replacing (and removing) the old one, and leaves the staging
    folder once saved. Local uploads are checked and saved directly with the
    row, without staging; a cancelled form has sent nothing. Returns {saved, changed_id, data (accessories_view),
    warnings}."""
    data = _save_body(body)
    profile = _writer(data)
    guard.require(profile, "accessories.edit")
    owners = guard.accessory_owners(profile)
    action = data.get("action")
    if action not in ("add", "edit", "remove"):
        raise ApiError(400, "action must be add, edit or remove")
    required = {"add": ("row",), "edit": ("id", "row"), "remove": ("id",)}[action]
    _keys(data, ("profile", "sha256", "action", *required), ("base", "image") if action != "remove" else ("base",))
    sha = _request_sha(data["sha256"])
    rid = data.get("id")
    if action != "add" and not (isinstance(rid, str) and accessories.valid_id(rid)):
        raise ApiError(400, "id must be an accessory id from /api/accessories")
    if "base" in data and data["base"] is not None and not isinstance(data["base"], dict):
        raise ApiError(400, "base must be the row as the page loaded it")
    row_in = dict(_row_input(data["row"])) if "row" in data else None
    try:
        with common.state_errors():
            before = accessories.read()     # the operation checks again, under the inventory's lock
    except OSError as e:
        raise ApiError(500, f"The accessories list can't be read: {_public(e)}") from None
    if action != "add":
        _require_writable_row(rid, before, profile, strict=False)
    if accessories.view_sha256(before, owners) != sha:
        row = before.rows_by_id.get(rid) if action != "add" else None
        gone = action != "add" and (row is None or not accessories.visible(row["owner"], owners))
        raise _conflict_error(profile, owners, "deleted" if gone else "changed")
    shown = before.rows_by_id.get(rid) if action != "add" else None
    if action != "add" and (shown is None or not accessories.visible(shown["owner"], owners)):
        raise ApiError(404, f"No accessory {rid} in the accessories list")
    if row_in is not None:
        if action == "add":
            row_in.setdefault("owner", profile["id"])
        if "owner" in row_in and not accessories.visible(row_in["owner"], owners):
            raise ApiError(403, "An accessory you save is yours or shared: choose yourself or Shared as its owner.")
    picture = _image_input(data.get("image"), action) if action != "remove" else None
    if action == "edit" and "image" not in data:
        picture = "keep"
    content = None
    if picture is not None and picture != "keep":
        try:
            content = picture if isinstance(picture, bytes) else picture.read_bytes()
        except OSError:
            raise ApiError(409, "That picture has expired: find it again, or save without a picture.") from None
        accessory_fetch.check_image(content)
    if action == "add":
        params = {"row": row_in, "sha256": sha, "owners": owners, "image": content}
    elif action == "edit":
        params = {"id": rid, "row": row_in, "sha256": sha, "owners": owners,
                  "image": "keep" if picture == "keep" else content}
    else:
        params = {"id": rid, "sha256": sha, "owners": owners}
    label_row = {**(shown or {}), **(row_in or {})}
    kind = label_row.get("kind") if label_row.get("kind") in _KIND_WORDS else "sleeves"
    message = f"{action} {_KIND_WORDS[kind]} {accessories.label(label_row)}"
    _, summary = _apply(inventory.Op(f"accessory.{action}", params), profile, message,
                        lambda e: _conflict_error(profile, owners, e.reason))
    if picture is not None and picture != "keep" and not isinstance(picture, bytes):
        picture.unlink(missing_ok=True)
    warnings = []
    return {"saved": True, "changed_id": (summary.extra or {}).get("id") or rid,
            "data": _view_after_write(warnings), "warnings": _unique(_scrub(warnings))}


# ---- assign

def _holder_id(value, what):
    if not isinstance(value, str):
        raise ApiError(400, f"{what} must be a deck id or product/<file>")
    if value.startswith("product/"):
        stem = value.split("/")[1] if value.count("/") <= 2 else ""
        if not rules.SLUG.fullmatch(stem):
            raise ApiError(400, f"Bad {what} {value!r}")
        return f"product/{stem}"
    commits._deck_file(value)
    if spaces.space_of(value) != spaces.HOME:
        raise ApiError(400, f"{value} is in a person's own space: sleeves and deck boxes are recorded only for "
                            f"the home decks")
    return value


def _require_holder_rights(profile, holder_id):
    """ApiError 403 unless profile may change this holder's kit: for a deck, deck.edit on it as
    stored (permissions: a member changes only the home decks Played by them); for a product, home's
    inventory to see (the product storage panel's read; accessories.edit and the shared kit are
    checked for every holder). A deck that isn't there or can't be read is left to kit.set's
    refusal, which checks deck.edit again under the lock."""
    if holder_id.startswith("product/"):
        guard.require_sees_home_records(profile)
        return
    deck = ops_accessories.parsed_deck(inventory.current().deck(holder_id))
    if deck is not None:
        guard.require(profile, "deck.edit", deck)


def _title_of(holder_id):
    """A holder's title in the snapshot now (for the change's message), else its id."""
    inv = inventory.current()
    if holder_id.startswith("product/"):
        return accessories._product_title(inv, f"{holder_id.split('/', 1)[1]}.csv")
    parsed = ops_accessories.parsed_deck(inv.deck(holder_id))
    return parsed.title if parsed is not None else holder_id


def assign_accessory(body):
    """POST /api/accessories/assign {"profile", "holder" (a deck id, or
    "product/<file stem>"), "field": "sleeves" | "deck_box", "id" (an
    accessory of that kind, or null to clear), "holder_sha256" (the deck's
    text's sha256, or for a product status.csv's as rendered from the
    inventory, as the page loaded it), "move_from"?
    (the holder those sleeves are taken from, cleared in the same change)}.

    One kit.set operation: only a built deck or an owned product kept intact
    takes sleeves or a deck box (clearing works on any), and only its owner's
    or shared ones (guard.holder_owner); the writer must see the holder's
    owner, the row's and move_from's (403, or 400 for the row, otherwise),
    and may edit each deck named, holder and move_from (deck.edit, 403 with
    its reason; _require_holder_rights for a product).
    Sleeves other holders use are chosen as they are, and both keep them
    (one design may sleeve several decks; move_from takes them off that
    holder instead). A deck box held by as many holders as there are boxes
    is 409 with "taken_by" unless move_from names one of them. Only the deck's header line (or the status.csv row)
    changes. Returns {data (accessories_view), holder (accessories.kit of the
    holder), warnings}."""
    data = _parse_body(body, MAX_BODY)
    profile = _writer(data)
    guard.require(profile, "accessories.edit")
    owners = guard.accessory_owners(profile)
    _keys(data, ("profile", "holder", "field", "id", "holder_sha256"), ("move_from",))
    holder_id = _holder_id(data["holder"], "holder")
    field = data["field"]
    if field not in accessories.HOLDER_FIELDS:
        raise ApiError(400, "field must be sleeves or deck_box")
    value = data["id"]
    if value is not None and not (isinstance(value, str) and accessories.valid_id(value)):
        raise ApiError(400, "id must be an accessory id from /api/accessories, or null")
    sha = data["holder_sha256"]
    if not (isinstance(sha, str) and common._SHA_RE.fullmatch(sha)):
        raise ApiError(400, "holder_sha256 must be the 64-character hash the page loaded")
    move_from = data.get("move_from")
    if move_from is not None:
        move_from = _holder_id(move_from, "move_from")
        if move_from == holder_id:
            raise ApiError(400, "move_from must be another deck or product")
    from .deck_aliases import reject_alias
    reject_alias(holder_id, profile, kit=True)
    if move_from is not None:
        reject_alias(move_from, profile, kit=True)
    what = _KIND_WORDS[field]
    holders = [{"id": holder_id, "expected": sha}]
    changes = [{"holder": holder_id, "field": field, "value": value}]
    if move_from is not None and value is not None:
        holders.append({"id": move_from, "expected": None})
        changes.insert(0, {"holder": move_from, "field": field, "value": None, "expect": value})
    try:
        with common.state_errors():
            for hid in (holder_id, move_from):      # before anything is worked out: E10-S42
                if hid is not None:
                    _require_holder_rights(profile, hid)
            title = _title_of(holder_id)
            source = _title_of(move_from) if move_from is not None and value is not None else None
    except OSError as e:
        raise ApiError(500, f"The accessories list can't be read: {_public(e)}") from None
    if source is not None:
        message = f"move {what} from {source} to {title}"
    elif value is None:
        message = f"clear {what} for {title}"
    else:
        message = f"set {what} for {title}"

    def conflict(e):
        changed = e.ids[0] if e.ids else holder_id
        if changed.startswith("product/"):
            return _status_conflict(profile)
        return _deck_conflict(profile, changed)
    _apply(inventory.Op("kit.set", {"holders": holders, "changes": changes, "owners": owners,
                                    "editor": profile}), profile, message, conflict)
    warnings = []
    try:
        with common.state_errors():
            kit = accessories.kit(holder_id, owners=owners)
    except ApiError:
        raise
    except Exception:           # saved; the page reloads what it can't show
        common._log(f"Couldn't work out {holder_id}'s kit after a save:\n{traceback.format_exc()}")
        kit = None
        warnings.append(f"{VIEW_FAILED}; the server log says why")
    view = _view_after_write(warnings)
    return {"data": view, "holder": common._jsonable(kit) if kit is not None else None,
            "warnings": _unique(_scrub(warnings + (kit["warnings"] if kit else [])))}


# ---- pictures

def _require_writable_row(rid, inv, profile, *, strict=True):
    row = inv.rows_by_id.get(rid) if isinstance(rid, str) else None
    if row and accessories.visible(row["owner"], guard.accessory_readers(profile)) \
            and not accessories.visible(row["owner"], guard.accessory_owners(profile)):
        raise ApiError(403, "You can only change your own and shared accessories.")
    if strict and (row is None or not accessories.visible(row["owner"], guard.accessory_owners(profile))):
        raise ApiError(404, f"No accessory {rid} in the accessories list")


def image_file(name, version):
    """(bytes, content type) for GET /accessory-img/<name>?v=<version>: a picture the inventory
    has and some row of accessories.csv names, of a row the viewer sees, whose first bytes match
    its extension; version must be the first 8 hex digits of its sha256
    (accessories.image_version), so an address names one picture's bytes.
    ApiError 404 otherwise, so an orphan or any other picture is never served; 403 for a visitor
    who may not see the accessories (guard.sees_accessories)."""
    guard.require_sees_accessories()
    if not isinstance(name, str) or not accessories.IMAGE_RE.match(name):
        raise ApiError(404, "Not found")
    try:
        with common.state_errors():
            snapshot = inventory.current()
            inv = accessories.read()
    except OSError:
        raise ApiError(404, "Not found") from None
    owners = guard.accessory_readers()
    if not any(row["image"] == name and accessories.visible(row["owner"], owners)
               for row in inv.rows_by_id.values()):
        raise ApiError(404, "Not found")
    meta = snapshot.image_meta(name)
    if meta is None or version != accessories.image_version(meta):
        raise ApiError(404, "Not found")
    with common.state_errors():
        data = inventory.image(name, meta.sha256)
    if data is None:
        raise ApiError(404, "Not found")
    ext = name.rsplit(".", 1)[1]
    if accessory_fetch.sniff(data) != ext:
        raise ApiError(404, "Not found")
    return data, IMAGE_TYPES[ext]


def staged_image(name):
    """(bytes, content type) for GET /accessory-img/staged/<token>.<ext>: a
    picture fetched within the hour, not saved yet. ApiError 404 otherwise
    (403 for a visitor who may not see the accessories)."""
    guard.require(guard.viewer(), "accessories.edit")
    if not isinstance(name, str) or not accessory_fetch.STAGED_NAME_RE.fullmatch(name):
        raise ApiError(404, "Not found")
    path = accessory_fetch.staged_file(name.split(".", 1)[0])
    if path is None or path.name != name:
        raise ApiError(404, "Not found")
    try:
        if path.is_symlink() or not path.resolve().is_relative_to(accessory_fetch.STAGED.resolve()) \
                or not path.is_file():
            raise ApiError(404, "Not found")
        data = path.read_bytes()
    except OSError:
        raise ApiError(404, "Not found") from None
    ext = name.rsplit(".", 1)[1]
    if accessory_fetch.sniff(data) != ext:
        raise ApiError(404, "Not found")
    return data, IMAGE_TYPES[ext]

