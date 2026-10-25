"""Personal Magic wishlists, stored separately from owned and incoming cards.

The lists live in the state store (decklab/lib/state: PostgreSQL, or memory in
the tests). One operation changes one card, and the store serialises each
profile's writes, so two phones never replace each other's list. A card name
is the list identity; the optional printing only chooses its picture. There
is no runtime seeding, quantity, price or collection mutation here.

A wishlist is private: only its owner reads it here or changes it
(permissions.sees_wishlist, lib/api/guard.py). The PC's command line reads
and changes any list.

validated_entry() is the one check of a new entry, shared with the command
line (python -m decklab.db wishlist ..., decklab/db/wishlist_cli.py).
"""
from decklab.lib import access, cards, inventory, spaces, state
from decklab.lib.inventory import paths
from decklab.lib.state import rules

from . import common, guard
from .card_lookup import _card_json, _pickable, _shown_printing
from .carddata import _INDEX_ERRORS, _require_cards
from .common import (MAX_BODY, MAX_NAME, NUMBER_RE, SET_RE, _CONTROL_RE, ApiError,
                     _keys, _parse_body, _scrub, _unique)
from .library import _load_pool
from .settings import _config_profiles, _require_profile, _writer


def _name(value):
    if (not isinstance(value, str) or not value.strip() or len(value) > MAX_NAME
            or _CONTROL_RE.search(value)):
        raise ApiError(400, f"Give a card name of at most {MAX_NAME} characters, with no control characters")
    return value.strip()


def _printing(set_code, number):
    if (not isinstance(set_code, str) or not isinstance(number, str)
            or bool(set_code) != bool(number)
            or set_code and (not SET_RE.fullmatch(set_code) or not NUMBER_RE.fullmatch(number))):
        raise ApiError(400, "Give both set and number for a printing, or leave both empty")
    return set_code, number


def validated_entry(name, set="", number="", notes="", source="", check_cards=True):
    """A new wishlist entry {name, set, number, notes, source}, checked: the
    name's and printing's forms, notes and source as the store keeps them,
    and (check_cards) the card itself: the name resolved to its exact
    Scryfall name, the printing one of that card's paper printings or, with
    none given, a card that has a paper printing at all. ApiError otherwise:
    400 for a bad form, 404 for an unknown card, 503 while the card index
    isn't ready."""
    name = _name(name)
    set_code, number = _printing(set, number)
    if check_cards:
        _require_cards()
        exact = cards.resolve(name)
        card = cards.card(exact) if exact else None
        if card is None:
            raise ApiError(404, f"No Scryfall card named {name!r}; choose a card from the search results")
        if set_code:
            printed = cards.printing_card(set_code, number)
            if not printed or printed["name"] != exact:
                raise ApiError(400, "That printing doesn't match the card name")
            if not _pickable(cards.printing(set_code, number)):
                raise ApiError(400, "Choose a paper printing of this card")
        elif not any(_pickable(cards.printing(s, n)) for s, n in card["printings"]):
            raise ApiError(400, "This wishlist is for physical cards; choose a card with a paper printing")
        name = exact
    with common.state_errors():
        return rules.entry({"name": name, "set": set_code, "number": number, "notes": notes, "source": source})


def _source_deck(source, inv):
    """{id, title} of the deck a wishlist entry's source names by its old file path
    (magic/decks/<kind>/<slug>.md, magic/people/<id>/decks/...), when that deck is in Deck Lab;
    None for any other source (a buylist) or a deck that's gone. Deck lists and titles are
    shown to everyone, so the title says nothing private."""
    if not source or inv is None:
        return None
    try:
        found = paths.classify(source)
    except (TypeError, ValueError):
        return None
    if not found or found[0] != "deck":
        return None
    space, kind, slug = found[1]
    deck_id = f"{kind}/{slug}" if space == spaces.HOME else f"{space}/{kind}/{slug}"
    deck_id = inventory.resolve_deck_id(deck_id, inv)
    deck = inv.deck(deck_id)
    if deck is None or deck.text is None:
        return None
    if not guard.sees_deck({"id": deck_id, "space": deck.space}):
        return None
    title = next((line[2:].strip() for line in deck.text.splitlines() if line.startswith("# ")), "") or slug
    return {"id": deck_id, "title": title}


def _view(profile_id, entries, warnings):
    """Card enrichment can fail without taking the saved list away. "have"
    counts the profile's own space (lib/spaces.py): home's pool for Matt and
    User1, a person's own collection for someone with their own space."""
    ready = True
    try:
        _require_cards()
    except ApiError as error:
        ready = False
        warnings.append(f"Card pictures, details and collection counts are unavailable. {error.message}")
    profile = next((p for p in _config_profiles() if p["id"] == profile_id), None)
    p = _load_pool(warnings, profile["space"] if profile else spaces.HOME) if ready else None
    try:
        inv = inventory.current() if any(entry.get("source") for entry in entries) else None
    except Exception as error:          # the decks can't be read: sources show as written
        common._log(f"Can't read the decks for wishlist sources: {error}")
        inv = None
    out = []
    for entry in entries:
        item = dict(entry, card=None, have={"owned": None, "on_the_way": None},
                    source_deck=_source_deck(entry.get("source"), inv))
        if ready:
            try:
                exact = cards.resolve(entry["name"])
                card = cards.card(exact) if exact else None
                if card is None:
                    warnings.append(f"No card details for {entry['name']!r}; it stays on your wishlist.")
                else:
                    shown = None
                    if entry["set"]:
                        printed = cards.printing_card(entry["set"], entry["number"])
                        if printed and printed["name"] == card["name"]:
                            card = printed
                            shown = cards.printing(entry["set"], entry["number"])
                        else:
                            warnings.append(f"The saved printing for {entry['name']} is unavailable; showing another.")
                    item["card"] = _card_json(card, shown or _shown_printing(card))
                    if p is not None:
                        incoming = sum(qty for _, qty in p.on_the_way.get(exact, []))
                        item["have"] = {"owned": max(0, p.owned.get(exact, 0) - incoming),
                                        "on_the_way": incoming}
            except _INDEX_ERRORS as error:
                common._log(f"Can't enrich wishlist card {entry['name']}: {error}")
                warnings.append(f"Card details for {entry['name']} are unavailable; it stays on your wishlist.")
        out.append(item)
    return {"profile": profile_id, "entries": out, "warnings": _unique(_scrub(warnings))}


def get_wishlist(profile_id):
    """GET /api/profiles/<id>/wishlist, including empty and offline lists.
    Only its owner sees it (guard.require_sees_wishlist: 403 for anyone else,
    an admin included, and for a script naming nobody), before the id is looked up, so a
    profile that doesn't exist answers as someone else's does (E10-S38)."""
    guard.require_sees_wishlist(profile_id)
    _require_profile(profile_id)
    with common.state_errors():
        entries = state.store().wishlist(profile_id)
    return _view(profile_id, entries, [])


def change_wishlist(profile_id, body):
    """POST one operation, saved at once in the state store, whose audit
    trail records who made it and whether from home or through the tunnel:
    {"profile", "action": "add", "name", "set"?, "number"?, "notes"?,
    "source"?, "at"?} (notes and source put back what a Remove took, and at,
    the index it had, puts it back there, for its Undo; the end without), {"action": "remove", "name"} or {"action": "set", "name",
    "notes"?, "source"?, "set"?, "number"?} (the given fields of a listed
    card; set and number go together, both "" for no printing). The permission is
    checked before the id is looked up, so a profile that doesn't exist is refused as
    someone else's is (E10-S38)."""
    data = _parse_body(body, MAX_BODY)
    profile = _writer(data)
    guard.require(profile, "wishlist.edit", profile_id)
    if profile["id"] != profile_id:
        raise ApiError(403, "Choose that person's profile before changing their wishlist")
    _require_profile(profile_id)
    action = data.get("action")
    if action not in ("add", "remove", "set"):
        raise ApiError(400, "action must be add, remove or set")
    optional = {"add": ("set", "number", "notes", "source", "at"), "remove": (),
                "set": ("set", "number", "notes", "source")}[action]
    _keys(data, ("profile", "action", "name"), optional)
    name = _name(data["name"])
    for key in ("notes", "source"):
        if key in data and not isinstance(data[key], str):
            raise ApiError(400, f"{key} must be text")
    actor = state.Actor(profile["id"], profile["name"], "tunnel" if access.current() is not None else "home")
    store = state.store()
    if action == "set":
        return _set_entry(profile, profile_id, name, data, actor, store)
    if action == "add":
        at = data.get("at")
        if at is not None and (isinstance(at, bool) or not isinstance(at, int) or not 0 <= at <= rules.MAX_ENTRIES):
            raise ApiError(400, "at must be a whole number from 0")
        entry = validated_entry(name, data.get("set", ""), data.get("number", ""),
                                data.get("notes", ""), data.get("source", ""))
        with common.state_errors():
            changed, entries = store.wishlist_add(profile_id, entry, actor,
                                                  f"Add {entry['name']} to {profile['name']}'s wishlist", at=at)
    else:
        with common.state_errors():
            # The message names the card as the list spells it.
            saved = store.wishlist(profile_id)
            i = rules.find(saved, name)
            shown = saved[i]["name"] if i is not None else name
            changed, entries = store.wishlist_remove(profile_id, name, actor,
                                                     f"Remove {shown} from {profile['name']}'s wishlist")
    return dict(_view(profile_id, entries, []), saved=True, changed=changed)


def _set_entry(profile, profile_id, name, data, actor, store):
    """change_wishlist's "set": the notes, source or printing of a listed card (the store's
    wishlist_set, one audited change). A printing must be one of that card's paper printings
    (validated_entry's check); 404 for a card that isn't on the list."""
    with common.state_errors():
        saved = store.wishlist(profile_id)
    i = rules.find(saved, name)
    if i is None:
        raise ApiError(404, f"{name} isn't on {profile['name']}'s wishlist")
    current = saved[i]
    fields = {}
    if "set" in data or "number" in data:
        set_code, number = _printing(data.get("set", ""), data.get("number", ""))
        if set_code:
            validated_entry(current["name"], set_code, number)       # that card's paper printing
        fields.update(set=set_code, number=number)
    for key in ("notes", "source"):
        if key in data:
            fields[key] = data[key].strip() if key == "source" else data[key]
    if not fields:
        raise ApiError(400, "Give notes, source or a printing to change")
    with common.state_errors():
        changed, entries = store.wishlist_set(profile_id, current["name"], actor,
                                              f"Change {current['name']} on {profile['name']}'s wishlist", **fields)
    return dict(_view(profile_id, entries, []), saved=True, changed=changed)
