"""GET /api/search?q=<text>[&group=decks|collection|cards][&limit=<n>]: the top bar's global search (E11-S31).

Decided (Matt, 2026-10-31): three sources, grouped in this order:

- "decks": the decks of the viewer's own space this request may see (guard.visible_decks, then only its own
  space's: Matt's decision says nothing outside the viewer's own space, so another space's Public decks stay
  out; home's for a script naming nobody), matched on the title as the library's title filter matches it
  (NFKC, lower case, anywhere in the title), so the group's See all total is what the library shows;
- "collection" ("In your collection"): the viewer's own space's collection, only when it may see that
  space's inventory (guard.sees_inventory; home's for a script naming nobody), matched on the card name,
  matched as "cards" matches a name (cards.search_names' order: starts, word starts, the words typed in
  order, anywhere), each with the Collection page's counts (owned, incoming, in_use and free, as pool.load_pool works them
  out; null in_use and free for a tracked basic land) and never a holder's name;
- "cards" ("Other cards"): every Scryfall card in the local card index (cards.search_names, paper cards),
  leaving out every name the viewer's collection holds, so an owned card never shows as another card.

Each group gives at most `limit` items (5 by default), its "total" (counted up to TOTAL_CAP) and "more".
With `group`, only that group comes back, up to 50 items (its See all). The text is at most MAX_QUERY
characters; blank text answers empty groups. Nothing here names a space, person or deck the viewer can't
see: a viewer who sees no collection (a request naming nobody, a login that isn't set up) simply gets no
collection group, and an unreadable collection says only that it couldn't be read. Nothing is written.
"""
import csv
import unicodedata

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


def _title_key(text):
    """The library's title filter's form of text (library.js libTitleQuery): NFKC, lower case."""
    return unicodedata.normalize("NFKC", text or "").lower()


def _title_rank(key, title):
    """0 when the title starts with key, 1 when a word of it does, 2 when it holds key anywhere, else None."""
    pos = title.find(key)
    if pos < 0:
        return None
    if pos == 0:
        return 0
    return 1 if not title[pos - 1].isalnum() else 2


def _name_rank(key, typed, name):
    """A card name's place as cards.search_names orders it (0 starts, 1 a word starts, 2 the words typed in
    order, 3 anywhere), else None: the collection matches exactly the names Other cards would."""
    folded = cards.fold(name)
    pos = folded.find(key)
    if pos == 0:
        return 0
    if pos > 0 and folded[pos - 1] in " -":
        return 1
    if typed and cards._starts_words(typed, cards._words(folded)):
        return 2
    return 3 if pos > 0 else None


def _viewer():
    """(profile or None, whether that is a script naming nobody); a login that isn't set up is nobody."""
    try:
        profile = guard.viewer()
    except ApiError:
        return None, False
    return profile, profile is None and guard.script()


def _own_space(profile, is_script):
    """The viewer's own space (home's for a script naming nobody), else None."""
    if profile is None and not is_script:
        return None
    space = spaces.HOME if profile is None else permissions._space_of(profile)
    return space if isinstance(space, str) and spaces.exists(space) else None


def _group(name, items, total, limit):
    return {"id": name, "label": LABELS[name], "items": items[:limit], "total": min(total, TOTAL_CAP),
            "capped": total > TOTAL_CAP, "more": total > limit}


def _decks(space, q, limit):
    key, found = _title_key(q), []
    for summary in guard.visible_decks(decks.list_decks()):
        if space is None or spaces.space_of(summary["id"]) != space:
            continue
        title = summary.get("title") or summary["id"]
        rank = _title_rank(key, _title_key(summary.get("title")))
        if rank is not None:
            found.append((rank, title.casefold(), summary))
    found.sort(key=lambda item: (item[0], item[1]))
    items = [{"id": s["id"], "title": s.get("title") or s["id"], "kind": s.get("kind"), "format": s.get("format"),
              "status": s.get("status")} for _, _, s in found[:limit]]
    return _group("decks", items, len(found), limit)


def _collection(space, key, limit):
    """The collection group and every name the collection holds (left out of Other cards)."""
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
    typed = cards._words(key)
    for name in names:
        rank = _name_rank(key, typed, name)
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
    return group, names


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
    space = _own_space(profile, is_script)
    if "decks" in wanted and space is not None:
        groups.append(_decks(space, q, limit))
    if space is not None and not guard.sees_inventory(space):
        space = None
    if space is not None and ("collection" in wanted or "cards" in wanted):
        found, owned = _collection(space, key, limit)
        if "collection" in wanted:
            groups.append(found)
    if "cards" in wanted:
        groups.append(_cards(q, owned, limit))
    return {"q": q, "groups": groups}
