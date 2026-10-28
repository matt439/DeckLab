"""The two-card combos a Commander deck is one card away from, on its deck page (E9-S25).

lib/stats/commander.py finds them (bracket["near_combos"], from combos.find's near mode: the
missing piece in the commander's colours and legal in Commander); annotate() adds what only the
deck page knows, to each match:

- "aud": an AUD estimate of the missing card's cheapest paper printing (cards.price_aud: public
  card data, so every reader of the deck gets it), or None; near_combos["prices"] then says the
  rate and dates it was worked out with ({"rate", "rate_date", "price_date"}), or is None when
  no rate could be had.
- "considering": True when the card is already on the deck's Considering list (E2-S23).
- "availability", only for a viewer who sees the deck's space's inventory (sees, with its pool
  p): "free" (a copy in the collection no other built deck or intact product holds), "on_the_way"
  (the only free copies are on order), "in_use" (every copy is in another built deck or intact
  product, which isn't named) or "to_buy" (none owned or ordered).

Nothing is fetched per card: prices are the card index's, and the exchange rate is cards'
once-a-day cached one; without a rate the prices are left out and the list still shows.
"""
from decklab.lib import cards, pool

from .card_lookup import _resolve


def _availability(name, free, p):
    on_order = sum(qty for _, qty in p.on_the_way.get(name, []))
    spare = free.get(name, 0)
    if spare - on_order > 0:
        return "free"
    if spare > 0:
        return "on_the_way"
    return "in_use" if p.owned.get(name, 0) > 0 else "to_buy"


def annotate(stats, deck_id, p, sees, considering):
    """Add "aud", "considering" and (for sees) "availability" to stats' near combos in place;
    stats is deck_view's (None, or a deck without near combos, is left as it is). considering
    is deck_view's "considering" (None for a product or pairing)."""
    near = ((stats or {}).get("commander") or {}).get("bracket", {}).get("near_combos")
    if not isinstance(near, dict) or not near.get("matches"):
        return
    listed = {_resolve(line["name"]) or line["name"] for line in (considering or {}).get("lines", [])}
    free = pool.free_copies(p, pool.self_ids(deck_id)) if sees and p is not None else None
    prices, rates = {}, None
    for match in near["matches"]:
        name = match["missing"]
        if name not in prices:
            try:
                prices[name] = cards.price_aud(name)
            except (RuntimeError, KeyError):        # no rate yet, or a card the index lost
                prices[name] = None
        price = prices[name]
        match["aud"] = price.aud if price else None
        if price and rates is None:
            rates = {"rate": price.rate, "rate_date": price.rate_date, "price_date": price.price_date}
        match["considering"] = name in listed
        if free is not None:
            match["availability"] = _availability(name, free, p)
    near["prices"] = rates
