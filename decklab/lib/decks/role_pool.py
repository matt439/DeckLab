"""Free pool cards for each of a Commander deck's roles (E9-S26): the cards the space owns, with a copy free
for the deck, that carry a role's Scryfall oracle tag and fit the commander's colour identity, so a thin role
on the Stats tab can be topped up from what's already owned.

The roles are the Stats tab's (cards.ROLES, each a tag and every tag below it, as the card index records
them on each card's "roles"), so a card listed here is one the role's bar would count once it's in the deck.
A candidate:

- has a copy free for the deck (pool.free_copies: owned and on the way, less what other built decks and
  intact products hold; basic lands are never pool cards);
- isn't already in the list (any section, the commander included);
- has a colour identity within the commanders' (colourless always fits) and is legal in Commander (its
  card data's commander_legality is "legal": banned and not-legal cards are left out, as the near combos'
  pieces are).

Each role lists at most MAX_PER_ROLE, most-printed first (a stand-in for how much a card is played, as the
editor's finder ranks), then by name; the rest are counted. Nothing here reads the inventory or the card
data itself: the caller passes the free copies and a card lookup, so the rules are tested on their own.
"""

MAX_PER_ROLE = 10       # candidates listed for one role (the rest are counted)


def fits(card, identity):
    """Whether card may join a Commander deck of this colour identity (a set of WUBRG letters)."""
    return (card is not None and card.get("commander_legality") == "legal"
            and set(card.get("color_identity") or ()) <= identity)


def free_by_role(roles, identity, in_deck, free, card_of, limit=MAX_PER_ROLE):
    """{role: (candidates, more)} for each of roles, in that order: candidates [(name, free copies)], at
    most limit of them, and more the count of the rest.

    identity is the commanders' colour identity (a set of WUBRG letters), in_deck the exact names the list
    already plays (left out), free {name: copies free for the deck} (pool.free_copies, less nothing: names
    in the list are dropped here) and card_of(name) the card (None for a name that isn't one: skipped)."""
    found = {role: [] for role in roles}
    for name, spare in free.items():
        if spare <= 0 or name in in_deck:
            continue
        card = card_of(name)
        if not fits(card, identity):
            continue
        for role in card.get("roles") or ():
            if role in found:
                found[role].append((-len(card.get("printings") or ()), name.casefold(), name, spare))
    out = {}
    for role, rows in found.items():
        rows.sort()
        out[role] = ([(name, spare) for _, _, name, spare in rows[:limit]], max(len(rows) - limit, 0))
    return out
