"""Shopping's token add-ons (E5-S38): the token cards home's built decks make but have no card for,
listed beside each basket as add-ons to look for at that shop.

GET /api/shopping's answer gets "token_addons": [{"name", "kind", "decks"}], one entry per token name
(case folded), "kind" token, emblem or the like (the first need's; a reminder card is a token kind in
lib/tokens), "decks" how many built home decks or intact products want it, the most wanted first.
It comes from lib/tokens.built_gaps over one inventory snapshot: built holders only (decks being built
don't count), state none only (a token with a card on order is on the way, so it isn't listed), and
never a token only the opponent gets (E7-S23).

It's evidence only: nothing here queues a card, adds one to Record this order, looks a token up at a
shop or claims a price or stock. It's worked out only beside baskets (the answer has "baskets"), only
for a viewer who sees home's records (Shopping's guard already refused anyone else; this checks again),
and any failure of the token reader, the card data still loading included, leaves the field out while
the baskets answer as before.
"""
from decklab.lib import cards, spaces, tokens

from . import common, guard


def summarise(gaps):
    """[{name, kind, decks}] from tokens.built_gaps' list: tokens of one folded name merged, each deck
    counted once, the most wanted first, then by name. Deck ids and titles are never passed on."""
    merged = {}
    for gap in gaps or ():
        name = str(gap.get("name") or "").strip()
        if not name:
            continue
        item = merged.setdefault(cards.fold(name), {"name": name, "kind": gap.get("kind") or "token", "ids": set()})
        item["ids"].update(deck.get("id") for deck in gap.get("decks") or () if deck.get("id"))
    out = [{"name": item["name"], "kind": item["kind"], "decks": len(item["ids"])}
           for item in merged.values() if item["ids"]]
    return sorted(out, key=lambda item: (-item["decks"], cards.fold(item["name"]), item["name"]))


def gather():
    """summarise(tokens.built_gaps(...)) over home's token cards and pending token orders. Raises as the
    token reader does (RuntimeError while the card index isn't ready)."""
    warnings = []
    inv = tokens.read(space=spaces.HOME)
    incoming_rows, _problems = tokens.incoming()
    return summarise(tokens.built_gaps(inv, incoming_rows, warnings, spaces.HOME))


def enrich(answer, *, cards_ready=True):
    """answer["token_addons"] beside the baskets, for home-record readers only; left out otherwise."""
    if "baskets" not in answer or not cards_ready or not guard.sees_home_records():
        return answer
    try:
        answer["token_addons"] = gather()
    except RuntimeError:
        pass                    # the card index is still loading: the baskets answer without it
    except Exception as error:  # optional evidence: Shopping still answers without it
        common._log(f"Shopping's token add-ons could not be worked out: {type(error).__name__}: {error}")
    return answer
