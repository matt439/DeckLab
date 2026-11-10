"""What a purchase-queue row asks a shop's listings for (E5-S33): its own printing and finish.

A row is a watchlist row as a dict (name, set, collector_number, finish, printing, ...). The
shops name printings their own way, so an exact row's printing is compared with a little
tolerance and nothing more: set codes ignoring case and spaces, collector numbers ignoring case,
spaces and leading zeros ("0212" is 212). A shop that lists the card only under set codes that
still don't match is "listed, but not matched to your printing" (the package's match()), never
"not listed".

A token or reminder row (is_token) is never looked up: the shops' name pages are of playable
cards, and a token's name ("Treasure", "Soldier") finds other cards or nothing.
"""
FINISHES = ("nonfoil", "foil", "etched")


def fold_set(value):
    return "".join(str(value or "").split()).casefold()


def fold_number(value):
    text = "".join(str(value or "").split()).casefold()
    return text.lstrip("0") or text[-1:]


def finish(row):
    """The finish the row wants: nonfoil when blank."""
    return str(row.get("finish") or "nonfoil").strip().lower() or "nonfoil"


def exact(row):
    """True when only the row's own printing answers it: printing exact, with a set and number."""
    return row.get("printing") == "exact" and bool(row.get("set")) and bool(row.get("collector_number"))


def same_printing(row, listing):
    """True when the listing is of the row's set and collector number (not its finish)."""
    return (fold_set(listing.get("set")) == fold_set(row.get("set"))
            and fold_number(listing.get("number")) == fold_number(row.get("collector_number")))


def own(row, listings):
    """The listings of an exact row's own printing and finish."""
    wanted = finish(row)
    return [item for item in listings if same_printing(row, item) and item.get("finish") == wanted]


def shop_sets(listings):
    """The distinct set codes the shop lists the card under, lowercase and sorted."""
    return sorted({fold_set(item.get("set")) for item in listings if isinstance(item, dict)} - {""})


def history_scope(row, listings):
    """(the row to pick as, the listings to pick from) for a price history of row's own printing
    and finish: an exact row as itself; any other row wanting foil or etched only that finish's
    listings, of any printing; any other row every listing, as an any-printing row. row None (no
    row named) is an any-printing row."""
    listings = [item for item in listings or () if isinstance(item, dict)]
    if row is None:
        return {"printing": "any"}, listings
    if exact(row):
        return row, listings
    wanted = finish(row)
    if wanted in ("foil", "etched"):
        listings = [item for item in listings if item.get("finish") == wanted]
    return {"printing": "any"}, listings


def scope_words(row):
    """A history's scope in words: "LTC 12 foil", "any foil printing", "any printing"."""
    if row is None:
        return "any printing"
    wanted = finish(row)
    if exact(row):
        return f"{str(row['set']).strip().upper()} {str(row['collector_number']).strip()} {wanted}"
    return f"any {wanted} printing" if wanted in ("foil", "etched") else "any printing"


def is_token(row):
    """True for a token or reminder row: one already marked (is_token), else by positive evidence
    in the card index (its printing is a token's, or its name is only a token face's), as
    Shopping's own test (lib/api/shopping_missing.is_token). False without the card data."""
    if row.get("is_token"):
        return True
    from decklab.lib import cards
    try:
        set_code, number = row.get("set"), row.get("collector_number")
        if set_code and number:
            if cards.token_faces_at(set_code, number) is not None:
                return True
            if cards.printing_card(set_code, number) is not None:
                return False
        name = str(row.get("name") or "")
        return bool(name) and cards.resolve(name) is None and cards.token_face(name) is not None
    except cards.INDEX_ERRORS:
        return False


def flag_tokens(rows):
    """rows, each token or reminder row marked is_token True (in place)."""
    for row in rows:
        if is_token(row):
            row["is_token"] = True
    return rows
