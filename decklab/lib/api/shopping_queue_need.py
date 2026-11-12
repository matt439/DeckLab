"""Queued cards the home decks no longer miss (E5-S37): a read-only mark on To buy.

annotate() compares the purchase queue with shopping_missing.gather's summed home
shortfalls, after that pass, from the same pinned snapshot. It writes nothing: the
queue changes only through Shopping's Edit or Remove. A mark is offered only where
the comparison is proven, so silence never means "covered":

  - the missing-cards answer must be ready, with no deck or pool error (an
    unreadable deck could be the one still missing the card);
  - only rows with printing "any", that aren't token or reminder cards, and whose
    linked home deck ("deck", from shopping._link_decks) was one of the decks
    counted. An exact-printing row (bought for its art), a token row and a row
    whose deck can't be found (or is a trial, or wasn't counted) get nothing,
    and their copies don't count towards the queued total either.

Each deck's shortfall is counted against the whole free pool (buying_needs: not a
simultaneous allocation), so two decks needing one card may each see the same free
copy and miss none between them. A card is therefore compared only when at most one
counted deck's planned list needs it (players, from shopping_missing.gather); with
two or more, or without players, it says nothing. The comparison is per card,
across every eligible queued row of it: "covered" when no counted home deck misses the card now,
"fewer" when the decks miss fewer copies than those rows queue. Every state is
compared, long-term rows included. Each marked row (and its copy in the missing
card's "queue" list) gets "queue_need": {"state", "card", "missing", "queued",
"fewer", "rows"}; a row with nothing to say is left exactly as it was.
"""
from . import shopping_missing

COVERED = "covered"
FEWER = "fewer"


def _quantity(row):
    value = row.get("quantity")
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        return None
    return value


def _eligible(row, counted):
    if row.get("printing") != "any" or row.get("is_token") or shopping_missing.is_token(row):
        return False
    deck = row.get("deck")
    if not isinstance(deck, dict) or deck.get("id") not in counted:
        return False
    return _quantity(row) is not None


def annotate(to_buy, missing_cards, counted_decks, *, players=None, canonical=None):
    """Mark to_buy's rows in place; return {queue_row: mark} for the rows marked.

    to_buy: Shopping's queue rows (each with "deck" linked and "queue_row" numbered).
    missing_cards: shopping_missing.gather's first value. counted_decks: the ids of
    the home decks whose planned lists were counted. players: card name -> the
    counted decks needing it (gather's players); None marks nothing. canonical: the card-name
    resolver (shopping_missing's by default). Nothing is marked when the count
    isn't proven complete, and nothing is ever written anywhere.
    """
    if not isinstance(missing_cards, dict) or missing_cards.get("ready") is not True or missing_cards.get("errors"):
        return {}
    if not isinstance(players, dict):
        return {}
    shared = {name.casefold(): len(set(ids)) for name, ids in players.items()}
    resolve = canonical or shopping_missing._canonical
    counted = set(counted_decks)
    missing = {}
    for row in missing_cards.get("rows") or ():
        missing[row["name"].casefold()] = row.get("missing", 0)
    groups = {}
    for row in to_buy:
        if _eligible(row, counted):
            key = resolve(row["name"])
            groups.setdefault(key.casefold(), (key, []))[1].append(row)
    marks = {}
    for folded, (name, rows) in groups.items():
        if shared.get(folded, 0) > 1:
            continue        # two decks' counts may share one free copy: unproven
        queued = sum(_quantity(row) for row in rows)
        wanted = missing.get(folded, 0)
        if wanted >= queued:
            continue
        mark = {"state": COVERED if wanted == 0 else FEWER, "card": name, "missing": wanted,
                "queued": queued, "fewer": queued - wanted, "rows": len(rows)}
        for row in rows:
            row["queue_need"] = dict(mark)
            if row.get("queue_row") is not None:
                marks[row["queue_row"]] = row["queue_need"]
    for row in missing_cards.get("rows") or ():
        for copy in row.get("queue") or ():
            found = marks.get(copy.get("queue_row"))
            if found is not None:
                copy["queue_need"] = dict(found)
    return marks
