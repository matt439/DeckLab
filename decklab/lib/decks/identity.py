"""A deck list's colour identity, shared by the library and inventory labels."""
from decklab.lib import cards

from .cover import COVER_SECTIONS

COLOR_ORDER = "WUBRG"


class CardIdentityError(ValueError):
    """A returned card-index record has missing or malformed colour identity data."""


def deck_colors(sections):
    """The colour identity of a list ({section: [DeckLine]}), in WUBRG order: its commander's
    when it has a Commander section Scryfall knows, else every Commander, Companion and Deck
    card's ([] for a colourless list). None when no card in it could be read (an unknown name, no
    card data yet), so the library shows no colours rather than a colourless C.
    A known card with damaged identity data raises CardIdentityError; lookup/programming
    errors propagate separately, so optional consumers can omit only that decoration."""
    def identities(names):
        found = []
        for name in names:
            exact = cards.resolve(name)
            card = cards.card(exact) if exact else None
            if card is not None:
                identity = card.get("color_identity") if isinstance(card, dict) else None
                if (not isinstance(identity, list) or any(not isinstance(color, str) or len(color) != 1
                                                        or color not in COLOR_ORDER for color in identity)):
                    raise CardIdentityError("The card index has missing or malformed colour identity data")
                found.append(identity)
        return found

    found = identities(line.name for line in (sections.get("Commander") or []))
    if not found:
        found = identities(line.name for s in COVER_SECTIONS for line in (sections.get(s) or []))
    if not found:
        return None
    colours = set().union(*found)
    return [c for c in COLOR_ORDER if c in colours]
