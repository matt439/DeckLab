"""Where each piece of the inventory lives as a file: repo-relative POSIX paths, worked out
from what the piece is (a space, an order component's kind, status and file name, a product's
stem), never read from disk.

FileInventory (files.py) reads and writes these paths. With the database backend nothing lives
there, but the paths stay the keys the snapshot, pool labels and the gate use (a component's
"path" in Shopping, an unknown card's place), so both backends say the same thing. Messages name a
source in the database's words instead (describe, row_of, place: "Row 3 of the home collection:
...", "Product x's card list", "Order x's cards"; E11-S12), never its old file and line.

    paths.collection("home")                      # "magic/collection.csv"
    paths.collection("user2")                   # "magic/people/user2/collection.csv"
    paths.payload("cards", "received", "2026-10-07-shop-a.csv")
                                                  # "magic/orders/received/2026-10-07-shop-a.csv"
    paths.classify("magic/orders/tokens/x.csv")   # ("payload", ("tokens", "pending", "x.csv"))
    paths.deck("user2", "casual", "elves")      # "magic/people/user2/decks/casual/elves.md"
    paths.classify("magic/decks/casual/x.md")     # ("deck", ("home", "casual", "x"))

Phase 4 adds the deck parts (DECK_PARTS): the deck files (home's magic/decks/<kind>/<slug>.md
and a person's magic/people/<id>/decks/<kind>/<slug>.md), magic/accessories.csv and its
pictures (magic/accessories/images/<name>). classify() names them as kinds of their own, but
they aren't inventory files (is_inventory() stays the inventory's alone, so the inventory's
revision never counts them); is_deck_part() says which paths they are.
"""
import re
from pathlib import PurePosixPath

HOME = "home"                       # spaces.HOME
MAGIC = "magic"
PEOPLE = "magic/people"
WATCHLIST = "magic/watchlist.csv"
PRODUCTS = "magic/products"
STATUS = "magic/products/status.csv"
STATUS_NAME = "status.csv"
ORDERS = "magic/orders"
RECORDS = "magic/orders/records"
KINDS = ("cards", "tokens", "product")
STATUSES = ("pending", "received", "cancelled")
# Every folder an order payload can be in, as purchases._coverage lists them.
PAYLOAD_FOLDERS = ("magic/orders", "magic/orders/received", "magic/orders/cancelled",
                   "magic/orders/tokens", "magic/orders/tokens/received", "magic/orders/tokens/cancelled")
DECKS = "magic/decks"
DECK_KINDS = ("casual", "commander")                # decks.KINDS: the deck file folders
ACCESSORIES = "magic/accessories.csv"
IMAGES = "magic/accessories/images"
DECK_PARTS = ("deck", "accessories", "image")       # classify()'s kinds that aren't inventory
_SPACE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")


def _space(space):
    if space != HOME and not (isinstance(space, str) and _SPACE.match(space)):
        raise ValueError(f"not a space id: {space!r}")
    return space


def space_root(space):
    """The folder holding a space's collection and tokens: magic, or magic/people/<id>."""
    return MAGIC if _space(space) == HOME else f"{PEOPLE}/{space}"


def collection(space=HOME):
    return f"{space_root(space)}/collection.csv"


def tokens(space=HOME):
    return f"{space_root(space)}/tokens.csv"


def locations(space=HOME):
    """A space's storage locations (E8-S22): locations.csv beside its collection.csv."""
    return f"{space_root(space)}/locations.csv"


def imports_dir(space=HOME):
    """A space's raw scanner/app exports: magic/imports or magic/people/<id>/imports."""
    return f"{space_root(space)}/imports"


def product(stem):
    return f"{PRODUCTS}/{stem}.csv"


def record(order_id):
    return f"{RECORDS}/{order_id}.json"


def payload_folder(kind, status):
    """The folder an order component's file is in, for its kind and status (purchases'
    read_records rule): products are always in magic/products; cards and tokens payloads move
    to received/ or cancelled/ beside the pending ones (tokens under orders/tokens)."""
    if kind not in KINDS or status not in STATUSES:
        raise ValueError(f"no payload folder for kind {kind!r} and status {status!r}")
    if kind == "product":
        return PRODUCTS
    folder = ORDERS + ("/tokens" if kind == "tokens" else "")
    return folder if status == "pending" else f"{folder}/{status}"


def payload(kind, status, file_name):
    return f"{payload_folder(kind, status)}/{file_name}"


def decks_dir(space=HOME):
    """The folder holding a space's casual/ and commander/ deck files."""
    return DECKS if _space(space) == HOME else f"{PEOPLE}/{space}/decks"


def deck(space, kind, slug):
    """A deck file's path: magic/decks/<kind>/<slug>.md, or magic/people/<id>/decks/<kind>/<slug>.md.
    ValueError for a kind that isn't casual or commander, or a slug that can't be a file name."""
    if kind not in DECK_KINDS:
        raise ValueError(f"not a deck kind: {kind!r}")
    if not isinstance(slug, str) or not _deck_name(f"{slug}.md"):
        raise ValueError(f"not a deck file name: {slug!r}")
    return f"{decks_dir(space)}/{kind}/{slug}.md"


def image(name):
    """An accessory picture's path: magic/accessories/images/<name>."""
    if not _image_name(name):
        raise ValueError(f"not a picture's file name: {name!r}")
    return f"{IMAGES}/{name}"


def _deck_name(name):
    """Whether a file name in a kind folder is a deck file: a .md file (any stem, as the folders'
    *.md listing finds it: a hand-named Gruul_Ramp.md is read-only, but it's a deck file), not a
    hidden one (a writer's temporary .x.md.123.tmp never ends in .md anyway)."""
    return _image_name(name) and name.endswith(".md") and len(name) > 3


def _image_name(name):
    """Whether a file name in the pictures folder is one: any file but a hidden one."""
    return isinstance(name, str) and bool(name) and not name.startswith(".") and "/" not in name \
        and "\\" not in name


def classify(rel):
    """What an inventory path is, as (what, detail), or None for a path that isn't inventory:

    ("collection", space), ("tokens", space), ("locations", space), ("import", (space, file name)),
    ("watchlist", None), ("status", None), ("product", stem), ("record", order id),
    ("payload", (kind, status, file name)) where kind is "cards" or "tokens";
    and phase 4's deck parts (DECK_PARTS): ("deck", (space, kind, slug)), ("accessories", None),
    ("image", file name).

    Only the file names FileInventory reads count (a .csv product or payload, a .json record, a
    .md deck file)."""
    path = PurePosixPath(rel)
    parts = path.parts
    if len(parts) < 2 or parts[0] != MAGIC:
        return None
    name = parts[-1]
    if rel == ACCESSORIES:
        return ("accessories", None)
    if len(parts) == 4 and parts[1] == "accessories" and parts[2] == "images" and _image_name(name):
        return ("image", name)
    if len(parts) == 4 and parts[1] == "decks" and parts[2] in DECK_KINDS and _deck_name(name):
        return ("deck", (HOME, parts[2], name[:-3]))
    if rel == WATCHLIST:
        return ("watchlist", None)
    if rel == collection(HOME):
        return ("collection", HOME)
    if rel == tokens(HOME):
        return ("tokens", HOME)
    if rel == locations(HOME):
        return ("locations", HOME)
    if len(parts) == 3 and parts[1] == "imports":
        return ("import", (HOME, name))
    if parts[1] == "people" and len(parts) >= 4 and _SPACE.match(parts[2]) and parts[2] != HOME:
        space = parts[2]
        if len(parts) == 4 and name == "collection.csv":
            return ("collection", space)
        if len(parts) == 4 and name == "tokens.csv":
            return ("tokens", space)
        if len(parts) == 4 and name == "locations.csv":
            return ("locations", space)
        if len(parts) == 5 and parts[3] == "imports":
            return ("import", (space, name))
        if len(parts) == 6 and parts[3] == "decks" and parts[4] in DECK_KINDS and _deck_name(name):
            return ("deck", (space, parts[4], name[:-3]))
        return None
    if path.suffix != ".csv" and not (len(parts) == 4 and rel.startswith(RECORDS + "/")):
        return None
    parent = path.parent.as_posix()
    if parent == PRODUCTS:
        return ("status", None) if name == STATUS_NAME else ("product", path.stem)
    if parent == RECORDS:
        return ("record", path.stem) if path.suffix == ".json" else None
    for folder in PAYLOAD_FOLDERS:
        if parent == folder:
            rest = folder[len(ORDERS):].strip("/").split("/") if folder != ORDERS else []
            kind = "tokens" if rest[:1] == ["tokens"] else "cards"
            rest = rest[1:] if kind == "tokens" else rest
            return ("payload", (kind, rest[0] if rest else "pending", name))
    return None


def is_inventory(rel):
    """Whether rel is a file the inventory is made of (see classify): never a deck part."""
    found = classify(rel)
    return found is not None and found[0] not in DECK_PARTS


def is_deck_part(rel):
    """Whether rel is a deck file, accessories.csv or one of its pictures (DECK_PARTS)."""
    found = classify(rel)
    return found is not None and found[0] in DECK_PARTS


def space_of(rel):
    """The space a collection, tokens, import or deck path belongs to; HOME for every other
    inventory path (orders, products, the watchlist and the accessories are home's); None for a
    path classify() doesn't know."""
    found = classify(rel)
    if found is None:
        return None
    what, detail = found
    if what in ("collection", "tokens", "locations"):
        return detail
    if what in ("import", "deck"):
        return detail[0]
    return HOME


def payload_owners(orders):
    """{payload path: (order id, component id)} of the cards and tokens components orders' records
    name (model.Order's), for describe(): a payload's file name is its order's id only until a
    split (x-additions.csv) or a merge (the other order's file, kept) says otherwise."""
    out = {}
    for order in orders:
        for component in order.components:
            named = isinstance(component.path, str) and isinstance(order.id, str) and isinstance(component.id, str)
            if named and component.kind in ("cards", "tokens"):
                out.setdefault(component.path, (order.id, component.id))
    return out


def component_words(order_id, component_id, kind, status="pending"):
    """How messages name an order's cards or tokens component (E11-S12): "order x's cards",
    "order x's token cards", "order x's received cards", "order x's additions" (a component
    whose id isn't its kind's)."""
    state = "" if status == "pending" else f"{status} "
    part = {("cards", "cards"): "cards", ("tokens", "tokens"): "token cards"}.get((kind, component_id), component_id)
    return f"order {order_id}'s {state}{part}"


def describe(rel, owners=None):
    """How messages name the inventory source at rel, as the database holds it (E11-S12): "the
    home collection", "user2's token cards", "the products' status list", "product x's card
    list", "order x's cards" or "order x's additions" (a payload, by the order and component
    owners, payload_owners(), says hold it; by its file's stem only when no record names it),
    "the purchase queue". Never an old file such as magic/tokens.csv. A path classify() doesn't
    know (a scratch file the user handed in) is named as it is. A sentence starting with it
    capitalises it (title)."""
    found = classify(rel)
    if found is None:
        return rel
    what, detail = found
    if what in ("collection", "tokens", "locations"):
        owner = "the home" if detail == HOME else f"{detail}'s"
        return f"{owner} {dict(collection='collection', tokens='token cards', locations='storage locations')[what]}"
    if what == "import":
        return f"the import {detail[1]}" + ("" if detail[0] == HOME else f" in {detail[0]}'s space")
    if what == "watchlist":
        return "the purchase queue"
    if what == "status":
        return "the products' status list"
    if what == "product":
        return f"product {detail}'s card list"
    if what == "record":
        return f"order {detail}'s record"
    if what == "payload":
        kind, status, name = detail
        order_id, component_id = (owners or {}).get(rel) or (PurePosixPath(name).stem, kind)
        return component_words(order_id, component_id, kind, status)
    if what == "deck":
        space, kind, slug = detail
        return f"{kind}/{slug}" if space == HOME else f"{space}/{kind}/{slug}"
    return rel


def place(source, owners=None):
    """A deck summary's "source" at the start of a message (E11-S12): a deck's id as it is, a
    product's card list in the database's words ("Product x's card list"), never its file."""
    words = describe(source, owners)
    return source if words == source else title(words)


def title(text):
    """text at the start of a sentence: its first letter capitalised ("The home collection")."""
    return text[:1].upper() + text[1:]


def row_of(rel, n, owners=None):
    """How messages name the nth data row (from 1, as the listings number them) of the source at
    rel: "Row 2 of the home collection" (owners as for describe)."""
    return f"Row {n} of {describe(rel, owners)}"
