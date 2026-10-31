"""GET /api/search?q=<text>[&group=decks|collection|cards][&limit=<n>]: the top bar's global search (E11-S31).

Decided (Matt, 2026-10-31): three sources, grouped in this order:

- "decks": the decks this request may see (guard.visible_decks: its own space's, plus a space's Public
  decks; a script naming nobody every one), matched on the title (and the id's last part);
- "collection" ("In your collection"): the viewer's own space's collection, only when it may see that
  space's inventory (guard.sees_inventory; home's for a script naming nobody), matched on the card name,
  each with the Collection page's counts (owned, incoming, in_use and free, as pool.load_pool works them
  out; null in_use and free for a tracked basic land) and never a holder's name;
- "cards" ("Other cards"): every Scryfall card in the local card index (cards.search_names, paper cards),
  leaving out the names the collection group already has.

Each group gives at most `limit` items (5 by default), its "total" (counted up to TOTAL_CAP) and "more".
With `group`, only that group comes back, up to 50 items (its See all). The text is at most MAX_QUERY
characters; blank text answers empty groups. Nothing here names a space, person or deck the viewer can't
see: a viewer who sees no collection (a request naming nobody, a login that isn't set up) simply gets no
collection group, and an unreadable collection says only that it couldn't be read. Nothing is written.
"""
import csv

from decklab.lib import cards, decks, permissions, pool, spaces

from . import guard
from .card_lookup import _card_json, _shown_printing
from .carddata import _require_cards
from .common import _CONTROL_RE, ApiError

MAX_QUERY = 100                 # characters of search text
LIMIT = (5, 50)                 # default and largest items per group
TOTAL_CAP = 200                 # a group's total is counted up to this ("200+")
GROUPS = ("decks", "collection", "cards")
LABELS = {"decks": "Decks", "collection": "In your collection", "cards": "Other cards"}
UNREADABLE = "Your collection couldn't be read just now."


def _query(q):
    q = "" if q is None else q
    if not isinstance(q, str) or len(q) > MAX_QUERY or _CONTROL_RE.search(q):
        raise ApiError(400, f"The search text must be at most {MAX_QUERY} characters, with no control characters")
    return q.strip()


def _limit(value, group):
    default, largest = LIMIT
    if value in (None, ""):
        return largest if group else default
    if not isinstance(value, str) or not value.isdigit() or not 1 <= int(value) <= largest:
        raise ApiError(400, f"limit must be a whole number from 1 to {largest}")
    return int(value)


def _rank(key, text):
    """0 when text starts with key, 1 when a word of it does, 2 when it holds key anywhere, else None."""
    pos = text.find(key)
    if pos < 0:
        return None
    if pos == 0:
        return 0
    return 1 if not text[pos - 1].isalnum() else 2


def _viewer():
    """(profile or None, whether that is a script naming nobody); a login that isn't set up is nobody."""
    try:
        profile = guard.viewer()
    except ApiError:
        return None, False
    return profile, profile is None and guard.script()


def _own_space(profile, is_script):
    """The space whose collection this request searches: the viewer's own (home's for a script naming
    nobody), only when it may see that space's inventory; else None."""
    if profile is None and not is_script:
        return None
    space = spaces.HOME if profile is None else permissions._space_of(profile)
    if not isinstance(space, str) or not spaces.exists(space) or not guard.sees_inventory(space):
        return None
    return space


def _group(name, items, total, limit):
    return {"id": name, "label": LABELS[name], "items": items[:limit], "total": min(total, TOTAL_CAP),
            "capped": total > TOTAL_CAP, "more": total > limit}


def _decks(key, limit):
    found = []
    for summary in guard.visible_decks(decks.list_decks()):
        title = summary.get("title") or summary["id"]
        ranks = [r for r in (_rank(key, cards.fold(title)), _rank(key, cards.fold(summary["id"].split("/")[-1])))
                 if r is not None]
        if ranks:
            found.append((min(ranks), title.casefold(), summary))
    found.sort(key=lambda item: (item[0], item[1]))
    items = [{"id": s["id"], "title": s.get("title") or s["id"], "kind": s.get("kind"), "format": s.get("format"),
              "status": s.get("status")} for _, _, s in found[:limit]]
    return _group("decks", items, len(found), limit)


def _collection(space, key, limit):
    """The collection group and the set of its matching names (left out of Other cards)."""
    from .collection import _holders, _special_basics
    try:
        p = pool.load_pool() if space == spaces.HOME else pool.load_pool(space)
        special, special_incoming = _special_basics(space)
    except (ValueError, OSError, csv.Error):
        group = _group("collection", [], 0, limit)
        group.update(space=space, error=UNREADABLE)
        return group, set()
    sees = guard.deck_reader()
    names = set(p.owned) | set(special) | set(special_incoming)
    matched = []
    for name in names:
        rank = _rank(key, cards.fold(name))
        if rank is not None:
            matched.append((rank, name.casefold(), name))
    matched.sort()
    items = []
    for _, _, name in matched[:limit]:
        basic = decks.is_basic_land(name)
        incoming = special_incoming[name] if basic else sum(qty for _, qty in p.on_the_way.get(name, []))
        owned = special[name] if basic else max(0, p.owned[name] - incoming)
        in_use = None if basic else sum(h["quantity"] for h in _holders(p, name, sees))
        card = cards.card(name)
        items.append({"name": name, "owned": owned, "incoming": incoming, "in_use": in_use,
                      "free": None if in_use is None else max(0, owned - in_use), "basic": basic,
                      "card": _card_json(card, _shown_printing(card)) if card else None})
    group = _group("collection", items, len(matched), limit)
    group["space"] = space
    return group, {name for _, _, name in matched}


def _cards(q, skip, limit):
    names = [name for name in cards.search_names(q, TOTAL_CAP + 1 + len(skip)) if name not in skip]
    items = []
    for name in names[:limit]:
        card = cards.card(name)
        items.append({"name": name, "card": _card_json(card, _shown_printing(card)) if card else None})
    return _group("cards", items, len(names), limit)


def search_view(q=None, group=None, limit=None):
    """GET /api/search: {"q", "groups": [...]} as the module's docstring says."""
    q = _query(q)
    if group not in (None, "") and group not in GROUPS:
        raise ApiError(400, "group must be decks, collection or cards")
    group = group or None
    limit = _limit(limit, group)
    if not q:
        return {"q": q, "groups": []}
    _require_cards()
    key = cards.fold(q)
    profile, is_script = _viewer()
    wanted = (group,) if group else GROUPS
    groups, owned = [], set()
    if "decks" in wanted and (profile is not None or is_script):
        groups.append(_decks(key, limit))
    space = _own_space(profile, is_script)
    if space is not None and ("collection" in wanted or "cards" in wanted):
        found, owned = _collection(space, key, limit)
        if "collection" in wanted:
            groups.append(found)
    if "cards" in wanted:
        groups.append(_cards(q, owned, limit))
    return {"q": q, "groups": groups}
