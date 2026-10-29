"""Free pool cards for each of a Commander deck's roles (E9-S26): GET /api/deck/role-cards, the Stats tab's
"Free cards by role". Writes nothing: a card is added to the deck in the editor, as any other.

What fits is lib/decks/role_pool.py's. The answer counts the deck's space's inventory, so it follows
GET /api/deck/replacements' reading rule (swaps._deck): a deck the viewer may not see is the missing deck's
404, a product or pairing a 400, then a viewer who may not see that space's inventory gets 403 "That
collection isn't public." It names no other deck: a candidate's copies are counted free, never by who
holds the rest.
"""
from decklab.lib import cards, pool
from decklab.lib.decks import role_pool

from .card_lookup import _card_json, _shown_printing
from .common import ApiError, _scrub, _unique
from .swaps import VERSIONS, _colours, _deck, _here, _space_pool

NOT_COMMANDER = "Free cards by role are for Commander decks: their commander's colours say which cards fit."
NO_COMMANDER = "Choose the deck's commander first: its colour identity says which cards fit."


def _tag_counts():
    """{role: oracle cards the card data's role tag holds} (cards.info()'s "roles"); a role missing, or
    with none, had no tag in the oracle_tags file the card data was built from."""
    try:
        recorded = cards.info().get("roles")
    except (KeyError, OSError, RuntimeError, ValueError):
        recorded = None
    if not isinstance(recorded, dict):
        return {}
    return {role: (entry.get("oracle_cards") or 0) if isinstance(entry, dict) else 0
            for role, entry in recorded.items()}


def role_cards(deck_id=None, version=None):
    """GET /api/deck/role-cards?id=<deck id>&version=target|owned: {"deck_id", "version", "colours" (the
    commanders' colour identity, WUBRG order), "tags_available" (False when the card data holds no role
    tag at all: then every role is untagged and lists nothing), "roles": [{"role", "tag" (its Scryfall
    oracle tag), "tagged" (whether the card data holds that tag's cards), "cards": [{"name", "card",
    "free" (copies free for this deck: owned and on the way, less other built decks' and intact products'),
    "here" (of those, copies not on the way)}], "more" (candidates not listed)}] in cards.ROLES' order,
    "warnings"}.

    Only for a Commander deck with a commander (400 otherwise, after the reading rule's 404 and 403); the
    list read is the saved Planned list (target) or Play-now list (owned), whose cards are never offered."""
    summary, deck = _deck(deck_id)          # a hidden deck's 404 comes before any 400
    version = version or "target"
    if version not in VERSIONS:
        raise ApiError(400, f"version must be one of: {', '.join(VERSIONS)}")
    if deck.kind != "commander":
        raise ApiError(400, NOT_COMMANDER)
    source = deck.target if version == "target" else deck.owned
    if not source:
        raise ApiError(404, f"{deck.title} has no {version} list")
    if not (source.get("Commander") or (deck.target or {}).get("Commander")):
        raise ApiError(400, NO_COMMANDER)
    identity = _colours(deck, source)
    warnings = []
    p = _space_pool(deck.space, warnings)
    free = pool.free_copies(p, pool.self_ids(summary["id"]))
    here = _here(p, free)
    # A Play-now list without a Commander section takes its identity from the Planned list's commander
    # (_colours), so that commander counts as in the deck too and is never offered for its own roles.
    sections = list(source.values())
    if not source.get("Commander"):
        sections.append((deck.target or {}).get("Commander") or ())
    in_deck = {cards.resolve(line.name) or line.name for lines in sections for line in lines}
    tagged = _tag_counts()
    found = role_pool.free_by_role(cards.ROLES, identity, in_deck, free, cards.card)
    roles = []
    for role in cards.ROLES:
        listed, more = found[role]
        if not tagged.get(role):
            listed, more = [], 0
        roles.append({"role": role, "tag": cards.ROLE_TAGS[role], "tagged": bool(tagged.get(role)),
                      "cards": [_entry(name, spare, here.get(name, 0)) for name, spare in listed], "more": more})
    return {"deck_id": summary["id"], "version": version,
            "colours": [c for c in "WUBRG" if c in identity],
            "tags_available": any(tagged.get(role) for role in cards.ROLES), "roles": roles,
            "warnings": _unique(_scrub(warnings))}


def _entry(name, spare, here):
    card = cards.card(name)
    return {"name": name, "card": _card_json(card, _shown_printing(card)), "free": spare, "here": here}
