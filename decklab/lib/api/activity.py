"""GET /api/activity: the Activity page's view of the database's audit trail (decklab/PLAN.md,
"Moving storage to a database", phase 2): who changed what, when, and from where.

    activity_view(before=None, limit=None)  -> {"changes": [...], "next": id or None, "everything": bool}

The trail (audit.change_set and audit.row_change, through state.store().activity()) holds every
row as it was written, private data included: email addresses, other people's settings. So each
row is shown only to those its table's rule allows (permissions.activity_scope says who sees
what) and only through its table's allow-list of fields, never the raw row:

    table             who sees it                                      fields sent
    wishlist_entry    its owner only (not even an admin)               name, set_code, collector_number
    profile_setting   everyone in the profile's space (an admin too:   key, value
                      only his own space's, E10-S29)
    simulation_mode   everyone                                         mode, set_by_name
    visibility        its space (all accessory flips: home)             owner, thing, set_by_name
    play_record       everyone in the space of one of a game's sides,  the summary only, a deck the
                      of a plan's deck only (permissions.sees_play_    viewer may not see named
                      record, as the Game log, an admin's too; a deck  "one of the home decks"; the
                      id that can't be read: a script's only)          message only when it sees all
    packing_tick      home viewers only (including admin/script)       the summary only, no task hashes
    commander_night   home viewers only, no outsider admin override     the summary only, no note content
    space, profile    admins                                           the summary only
    profile_email     admins                                           "An email address changed" only
    collection_card,  the space's people only (home: Matt and User1;  INVENTORY_FIELDS' (never notes,
    token_card,       scope_spaces, no admin override,                  a token's details, an order's
    collection_import E10-S29; an orphan space's rows: a script's)     audit notes or prices)
    the orders,       home profiles                                    (sleeves and deck box of an
    products, status,                                                  intact product: home viewers only)
    watchlist
    product_item,     home profiles                                    a count per product or payload
    order_*_item                                                       ("Added 12 card rows to order X (cards)")
    deck              the deck's space's people                        id, title, status, played_by (never
                      (scope_spaces, as the inventory)                 its kit: the table holds none)
    accessory         whoever's accessories it is, before and after    id, kind, name, colour, quantity
                      (permissions.accessory_owners: not by role,      (never brand, link, image_source,
                      so not an admin's unless it's theirs or shared)  notes, owner)
    anything else     admins                                           "changed" only

Inventory rows are filtered by space and capped in SQL (inventory_spec): at most ROW_CAP rows
plus "and N more"; position-only moves are omitted. Kit changes (rules.kit_changed) show their
message and reason only to their actor, since the words can name private sleeves or boxes.
Orphan settings are scripts' only, orphan wishlists nobody's. Hidden-only changes are
omitted; empty changes are admins' only. Messages and reasons require every row to be visible,
then are shown for web changes, to admins and to their actor. Kit and mixed-game rules may
hide them further. Public collections, decks and games never widen Activity. CLI and SQL read all.

Every row has a summary in plain words ("Added Plains (SLD 1513) to your wishlist", "Matt's
theme: system → dark", "Simulations: admins → everyone"), and each change the actor's name, read
from config.json now rather than when it was written. The rows speak as the headline does: "your"
for the viewer's own wishlist, settings and (a member's) space; spaces and orders by name ("Added
User2's space", "the Ronin Games order (cards)"); an order payload removed and written again in
one change as one row; and the receipt or cancellation the headline already names left out. The
copies added or removed by rows past the cap are counted by the store ("past"), so a headline's
total is exact rather than "at least".

visible_change() is the rule itself, pure (no request, no config, no store), for the tests.

The rows' words (and the inventory's table names) are activity_summaries.py's, the headlines
(describe, KINDS, SOMEONE) activity_headlines.py's; this module re-exports the names its callers
read. OrderFacts, _load_orders, row_cards and ROW_CAP stay here, where the tests patch them.
"""
import re

from decklab.lib import inventory, permissions, spaces, state
from decklab.lib import profiles as profiles_module
from decklab.lib.state import rules

from . import activity_aliases, activity_home, guard
from .activity_counts import _whole
from .activity_headlines import KINDS, SOMEONE, describe
from .activity_home import home_viewer as _home_viewer, own_space as _own_space
from .activity_summaries import (INVENTORY_FIELDS, INVENTORY_SUMMARIES, ITEM_TABLES, PROFILE_FIELDS,  # noqa: F401
                                 SPACE_TABLES, _accessory_summary, _accessory_visible, _component_summary, _deck_space,
                                 _deck_summary, _dict, _group, _group_rows, _inventory_space, _mode_summary,
                                 _only_position, _play_owners, _play_recorder, _play_summary, _profile_summary,
                                 _setting_summary, _space_summary, _text, _whose, _wishlist_summary)
from .common import ApiError, state_errors

DEFAULT_LIMIT = 50
_NUMBER_RE = re.compile(r"[0-9]{1,18}")     # a bigint, with room to spare

# The audit trail's own actors (profiles.RESERVED_IDS), by the name shown.
ACTOR_NAMES = {"claude": "Claude", "system": "System", "home": "someone at home", "test": "a test"}

# The fields of each table's rows that may be sent (the module docstring's table).
FIELDS = {
    "wishlist_entry": ("name", "set_code", "collector_number"),
    "profile_setting": ("key", "value"),
    "simulation_mode": ("mode", "set_by_name"),
    "visibility": ("owner", "thing", "set_by_name"),
}
PROFILE_TABLES = ("wishlist_entry", "profile_setting")
FIELDS.update(INVENTORY_FIELDS)
# Phase 4's rows, each with a rule of its own in _row (the module docstring's table).
FIELDS.update({rules.DECK_TABLE: ("id", "title", "status", "played_by"),
               rules.ACCESSORY_TABLE: ("id", "kind", "name", "colour", "quantity")})
INVENTORY_TABLES = tuple(INVENTORY_FIELDS) + ITEM_TABLES
KIT_FIELDS = rules.KIT_FIELDS          # an intact product's accessories (accessories' privacy)
ROW_CAP = 50                            # inventory rows listed per change; the rest are "and N more"
EMAIL_CHANGED = "An email address changed"
UNKNOWN_CHANGED = "changed"


def activity_view(before=None, limit=None, kind=None, actor=None):
    """GET /api/activity: one page of the changes this request may see, newest first.

    before: only change sets older than this id (the "next" of the page before); limit: how
    many changes at most, 1 to 100 (50 by default); kind: only changes of one of KINDS (a
    change's "kinds"); actor: only changes made by that actor (the "actor" a change is shown
    with, so an actor hidden from this viewer can't be asked for). All come as text from the
    address. Each change is {id, at (ISO, UTC), actor, actor_name, source, via ("home",
    "tunnel" or None), message, reason, headline, kinds, link, rows: [{table, op, summary[,
    before, after]}]} (headline, kinds, link: describe()). "next" is the before for the next
    page, None at the end; "everything" is whether this viewer sees every change; "cards" the
    card data (card_lookup's) of the rows naming a card, by card_key(), for the card viewer
    ({} while the card index can't be loaded). ApiError 400 for bad paging or filter values,
    503 when the database can't be reached."""
    before = _number(before, "before", "a change set ID (a whole number above 0)")
    limit_words = f"a whole number from 1 to {rules.MAX_LIMIT}"
    limit = DEFAULT_LIMIT if limit is None else _number(limit, "limit", limit_words)
    if limit > rules.MAX_LIMIT:
        raise ApiError(400, f"limit must be {limit_words}")
    if kind is not None and kind not in KINDS:
        raise ApiError(400, f"kind must be one of {', '.join(KINDS)}")
    if actor is not None and not profiles_module.valid_id(actor):
        raise ApiError(400, "actor must be a profile id")
    viewer = guard.viewer()
    scope = permissions.activity_scope(viewer, script=guard.script())
    if scope is None:               # a safeguard: guard.visitor() already refuses the tunnel with no profile
        return {"changes": [], "next": None, "everything": False, "cards": {}}
    from .settings import _config_profiles
    profiles = {p["id"]: p for p in _config_profiles()}
    seen = scope_spaces(scope)     # public collections and decks never widen Activity
    orders = OrderFacts()

    def visible(change):
        shown = visible_change(change, scope, profiles, me=_id(viewer), spaces=seen, orders=orders)
        if shown is None or (kind is not None and kind not in shown["kinds"]):
            return None
        if actor is not None and shown["actor"] != actor:
            return None
        return shown

    with state_errors():
        page = state.store().activity(before, limit, visible=visible, inventory=inventory_spec(seen))
    return {"changes": page["changes"], "next": page["next"], "everything": scope == "all",
            "cards": row_cards(page["changes"])}


def inventory_spec(spaces):
    """The state store's inventory argument for a viewer who sees spaces' inventory rows
    (scope_spaces: None for a script's), ROW_CAP listed per change."""
    return {"tables": INVENTORY_TABLES, "items": ITEM_TABLES,
            "spaces": None if spaces is None else list(spaces), "cap": ROW_CAP}


def scope_spaces(scope):
    """Only the viewer's own space; every space for a script naming nobody.
    Activity's scope is independent from public collection, deck and game readers."""
    return None if scope == "all" else [scope["space"]]


def _id(profile):
    return profile.get("id") if profile else None


def _number(value, what, words):
    """A paging value from the address as a whole number above 0 (None stays None)."""
    if value is None:
        return None
    if isinstance(value, int) and not isinstance(value, bool):
        number = value
    elif isinstance(value, str) and _NUMBER_RE.fullmatch(value):
        number = int(value)
    else:
        raise ApiError(400, f"{what} must be {words}")
    if number < 1:
        raise ApiError(400, f"{what} must be {words}")
    return number


# ------------------------------------------------------------------ the rule

def visible_change(change, scope, profiles, space_of=_deck_space, *, me=None, spaces=False, orders=None):
    """change (from state's activity(): {id, at, actor, source, via, message, reason, rows}) as
    a viewer of scope (permissions.activity_scope, not None) may see it, or None to leave it
    out. profiles: {id: profile} of config.json, for names and spaces; space_of: a deck id's
    space, None when it can't be read (_deck_space); me: the viewer's profile id, for the
    wishlist rows only its owner sees (scope's "profile" when scope names one; None, nobody's,
    for a script naming nobody); spaces: the spaces whose inventory rows the viewer sees
    (scope_spaces, independent from public readers); orders: the sellers and contents for the headline
    (OrderFacts; None words an order by its id)."""
    everything = scope == "all"
    system = everything or scope.get("system", False)
    if spaces is False:
        spaces = scope_spaces(scope)
    if not everything:
        me = scope["profile"]
    raw = change.get("rows") or ()
    own = _own_space(scope, profiles, me)
    rows = [shown for shown in (_row(row, scope, profiles, space_of, me, spaces, own=own, orders=orders)
                                for row in raw)
            if shown is not None]
    # A game or plan naming a deck the viewer may not see: its words ("Save game A vs B") may
    # name that deck, so they show only to viewers who see every deck it names (E10-S32).
    masked = any([row.pop("_masked", False) for row in rows])
    anonymous = any([row.pop("_anonymous", False) for row in rows])
    seen = len(rows)
    shown_groups, counted = [], []
    for group in change.get("groups") or ():
        if _group(group, spaces) is not None:
            counted.append(group)
            shown_groups.append((group.get("table"), _dict(group.get("key"))))
            seen += group.get("count") or 0
    rows += _group_rows(counted, orders)
    more = change.get("more") or 0
    if more:                        # the inventory rows past the cap, which the database didn't send
        rows.append({"table": None, "op": None, "summary": f"and {more} more"})
        seen += more
    total = change.get("total", len(raw))
    # A change set whose every row the store or projection hid is omitted, including for
    # admins. A truly empty change set is a system event, which admins still see.
    if not rows and (raw or not system or total > 0):
        return None
    actor = change.get("actor")
    known = actor in profiles or actor in ACTOR_NAMES
    if actor in profiles:
        name = profiles[actor]["name"]
    else:
        name = ACTOR_NAMES.get(actor) or (actor if system else SOMEONE)
    if anonymous and (me is None or actor != me):
        # a game another space recorded: its saver is that space's to know (E10-S32)
        known, name = False, SOMEONE
    # Page messages can name every deck rewritten by a mixed-space Update all too. The
    # actor and an admin must satisfy this rule exactly as every other viewer does.
    as_written = (system or change.get("source") == "web" or actor == me) and seen == total
    if masked:
        as_written = False
    if change["kit"] if "kit" in change else any(rules.kit_changed(row) for row in raw):
        # an intact product's sleeves or deck box changed (any row of the change set, hidden or
        # past the cap: the store's "kit"): the words may name the deck they came from, which
        # only that deck's owner may see (accessories' privacy holds for admins too)
        as_written = as_written and ((me is not None and actor == me) or (everything and me is None))
    packing = [row for row in rows if row.get("table") == "packing_tick"]
    if packing:
        rows = [row for row in rows if row.get("table") != "packing_tick"] + packing[:1]
    headline, kinds, link = describe(rows, name, orders, shown_groups, profiles, own=own, past=change.get("past"))
    return {"id": change["id"], "at": change["at"], "actor": actor if known or (system and not anonymous) else None,
            "actor_name": name, "source": change.get("source"), "via": change.get("via"),
            "message": change.get("message") if as_written else None,
            "reason": change.get("reason") if as_written else None,
            "headline": headline, "kinds": kinds, "link": link, "rows": _beyond_headline(rows, link)}


def _beyond_headline(rows, link):
    """rows without those the headline already says: the receipt or cancellation of the order it
    names (its link), whose row would only repeat it ("Received order X (cards) on ...")."""
    order = (link or {}).get("order")
    if not order:
        return rows
    return [row for row in rows if not (
        row.get("table") == "order_component" and row.get("op") == "UPDATE"
        and _dict(row.get("after")).get("order_id") == order
        and _dict(row.get("after")).get("status") in ("received", "cancelled")
        and _dict(row.get("before")).get("status") != _dict(row.get("after")).get("status"))]


def _space_id(profile):
    return profile.get("space") or permissions.HOME


def _named_space(profiles, me):
    """The space of the profile me names (a named admin's, whose scope is "all"), None for one
    config.json doesn't list (so it matches no space)."""
    profile = profiles.get(me)
    return _space_id(profile) if profile else None


def _row(row, scope, profiles, space_of, me=None, spaces=None, *, own=None, orders=None):
    """One row_change as the viewer may see it ({table, op, summary} plus the table's fields in
    before and after), or None when it's hidden. me, spaces, orders: as visible_change's; own:
    the viewer's own space when it isn't home's (_own_space), said as "your"."""
    everything = scope == "all"
    table, op = row.get("table"), row.get("op")
    before, after = _dict(row.get("before")), _dict(row.get("after"))
    record = after or before
    if table in PROFILE_TABLES:
        pid = record.get("profile_id")
        if not isinstance(pid, str):
            pid = _dict(row.get("key")).get("profile_id")
        profile = profiles.get(pid) if isinstance(pid, str) else None
        if table == "wishlist_entry":
            if profile is None or not permissions.sees_wishlist(profiles.get(me), pid):
                return None             # private, even to an admin
        elif not everything and (profile is None or (profile.get("space") or permissions.HOME) != scope["space"]):
            return None
        elif everything and me is not None and (profile is None or _space_id(profile) != _named_space(profiles, me)):
            return None                 # another space's settings: not even to a named admin (E10-S29)
        # A wishlist row is only ever its owner's to see: "your wishlist", as the headline says.
        whose = "your" if pid == me and me is not None else f"{profile['name'] if profile else pid}'s"
        summary = (_wishlist_summary if table == "wishlist_entry" else _setting_summary)(op, before, after, whose)
        return _shown(table, op, summary, before, after)
    if table in INVENTORY_FIELDS:
        space = _inventory_space(table, row)
        if spaces is not None and space not in spaces:
            return None             # another space's inventory (an orphan space's: a script's only)
        if _only_position(op, before, after):
            return None             # a row that only moved in its list
        if table == "order_component":
            summary = _component_summary(op, before, after, None, orders)
        else:
            summary = INVENTORY_SUMMARIES[table](op, before, after, _whose(space, profiles, own))
        shown = _shown(table, op, summary, before, after)
        if table == "product_status" and not _home_viewer(scope, profiles, me):
            for part in (shown["before"], shown["after"]):
                for key in KIT_FIELDS:
                    (part or {}).pop(key, None)
        return shown
    if table == "deck_alias":
        return activity_aliases.row(row, spaces)
    if table == rules.DECK_TABLE:
        space = _text(record.get("space_id") or _dict(row.get("key")).get("space_id"), permissions.HOME)
        if spaces is not None and space not in spaces:
            return None             # another space's decks (whose inventory the viewer doesn't see)
        return _shown(table, op, _deck_summary(op, before, after, _whose(space, profiles, own)), before, after)
    if table == rules.ACCESSORY_TABLE:
        owners = permissions.accessory_owners(profiles.get(me) if me else None, script=everything and me is None)
        if any(r and not _accessory_visible(r.get("owner"), owners) for r in (before, after)):
            return None             # someone else's (accessories are private from admins too)
        return _shown(table, op, _accessory_summary(op, before, after), before, after)
    if table == "simulation_mode":
        return _shown(table, op, _mode_summary(op, before, after), before, after)
    if table == "visibility":
        summary = activity_home.visibility_row(row, scope, profiles, me)
        return _shown(table, op, summary, before, after) if summary else None
    if table == "commander_night":
        return activity_home.commander_night_row(row, scope, profiles, me)
    if table == "packing_tick":
        return ({"table": table, "op": op, "summary": "Packing progress updated"}
                if _home_viewer(scope, profiles, me) else None)
    if table == "play_record":
        decks = [d for r in (before, after) for d in (r.get("deck_ids") or ())]
        # The Game log's rule (permissions.sees_play_record, over a game's sides and a plan's deck
        # only, E10-S32), for the viewer scope stands for; a named admin only his own space's
        # games too (E10-S29). A script naming nobody sees every one.
        viewer = None
        if not everything:
            viewer = {"id": scope["profile"], "space": scope["space"]}
        elif me is not None:
            viewer = {"id": me, "space": _named_space(profiles, me)}
        if viewer is not None and not permissions.sees_play_record(
                viewer, [d for r in (before, after) for d in _play_owners(r)], space_of=space_of):
            return None
        public = guard.public_deck_spaces()
        seen = (lambda d: True) if viewer is None else (   # noqa: E731
            lambda d: isinstance(d, str) and viewer["space"] is not None
            and permissions.sees_deck(viewer, space_of(d), public=public))
        shown = {"table": table, "op": op, "summary": _play_summary(op, record, seen, profiles, space_of)}
        if any(not seen(d) for d in decks):
            shown["_masked"] = True     # names a deck the viewer may not see: no words (visible_change)
        if viewer is not None and any(r and _play_recorder(r, space_of) != viewer["space"] for r in (before, after)):
            # who saved a game goes only to the space that recorded it, as the Game log's
            # "updated_by" does (play_records._view, E10-S32): anyone else is told "someone"
            shown["_anonymous"] = True
        return shown
    if not everything and not scope.get("system", False):
        return None
    if table == "profile_email":
        return {"table": table, "op": op, "summary": EMAIL_CHANGED}
    if table == "space":
        return {"table": table, "op": op, "summary": _space_summary(op, record, profiles)}
    if table == "profile":
        return {"table": table, "op": op, "summary": _profile_summary(op, before, after)}
    return {"table": table, "op": op, "summary": UNKNOWN_CHANGED}


def _shown(table, op, summary, before, after):
    """A row with only its table's allowed fields (FIELDS) in before and after."""
    keep = FIELDS[table]
    project = lambda r: {k: r[k] for k in keep if k in r} if r else None   # noqa: E731
    return {"table": table, "op": op, "summary": summary, "before": project(before), "after": project(after)}


# ------------------------------------------------------------------ the orders the headlines name

_UNREAD = (inventory.Unavailable, inventory.Invalid, OSError, ValueError, KeyError, TypeError, AttributeError)


class OrderFacts:
    """The orders' sellers and what each component holds, read from the inventory once and only
    when a headline needs them: get(order_id) -> {"seller": str or None, "components": {id:
    {"kind", "quantity" (int or None), "label" (a product's name, else None)}}} or None. A
    headline only asks about an order that a row the viewer may see names (orders are home's)."""

    def __init__(self, load=None):
        self._load = load or _load_orders
        self._found = None

    def get(self, order_id):
        if self._found is None:
            try:
                self._found = self._load() or {}
            except _UNREAD:
                self._found = {}        # the headline names the order by its id instead
        return self._found.get(order_id)


def _load_orders():
    inv = inventory.current()
    found = {}
    for order in inv.orders:
        if not isinstance(order.id, str):
            continue
        parts = {}
        for component in order.components:
            quantity = label = None
            if component.kind == "product":
                stem = component.product_stem
                product = inv.product(stem) if stem else None
                label = product.label("shopping") if product is not None else stem
            else:
                sheet = inv.payloads.get(component.path)
                if sheet is not None and sheet.rows:
                    counts = [_whole(row.get("quantity")) for row in sheet.rows]
                    quantity = None if None in counts else sum(counts)
            parts[component.id] = {"kind": component.kind, "quantity": quantity, "label": label}
        seller = order.seller if isinstance(order.seller, str) and order.seller.strip() else None
        found[order.id] = {"seller": seller, "components": parts}
    return found


# ------------------------------------------------------------------ the card viewer's cards

CARD_TABLES = ("collection_card", "watchlist_item", "wishlist_entry")
MAX_CARDS = 600                 # cards looked up per answer (50 changes of at most ROW_CAP rows)


def card_key(record):
    """The key a row's card has in an answer's "cards": "name|set|number" (set and number blank
    when the row names none)."""
    return "|".join(_text(record.get(k), "") for k in ("name", "set_code", "collector_number"))


def row_cards(changes):
    """{card_key: the card's data as the deck page gets it (card_lookup._line_json: the row's
    printing when the card data has it)} for the shown rows naming a card, for the card viewer;
    {} while the card index can't be loaded. Only the names and printings the rows show are
    looked up, so it says nothing the rows don't."""
    from .carddata import _index_info
    if _index_info()[0] is None:
        return {}
    from types import SimpleNamespace
    from .card_lookup import _line_json
    found, tried = {}, set()
    for change in changes:
        for row in change.get("rows") or ():
            if row.get("table") not in CARD_TABLES:
                continue
            record = _dict(row.get("after")) or _dict(row.get("before"))
            key = card_key(record)
            if key in tried or not isinstance(record.get("name"), str) or len(tried) >= MAX_CARDS:
                continue
            tried.add(key)
            line = SimpleNamespace(quantity=1, name=record["name"], set=record.get("set_code") or None,
                                   number=record.get("collector_number") or None, finish="nonfoil")
            try:
                card = _line_json(line, "Deck", [])["card"]
            except (KeyError, TypeError, ValueError):
                card = None
            if card is not None:
                found[key] = card
    return found
