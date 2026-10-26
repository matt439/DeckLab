"""Which token cards built decks and intact products pack, against a space's rows.

A built deck's Token cards line (lib/decks/tokencards.py) names the token cards in its deck box.
holds() matches each line to the space's token rows and shares the copies out, deck by deck in
id order, so two decks each packing "1 Treasure" take one card each from two Treasure rows rather
than both from the first. A line with more cards than its rows have left still takes them (from
the last matching row), so the over-use shows as a row with more held than it has (shared_rows
in __init__ warns about it); a line no row matches is "unmatched". held_elsewhere() is what one
deck sees: the cards every other built deck or intact product holds, which deck_tokens doesn't count
as free.
"""
from decklab.lib import cards, decks, inventory, spaces


def _same(a, b):
    return cards.fold(a or "") == cards.fold(b or "")


def matches(line, row):
    """True when a TokenCardLine names this token row: the same faces (in order) and, when the line
    gives a printing, the row's set and front collector number."""
    if not (_same(line.front, row["front"]) and _same(line.back, row["back"])):
        return False
    return not line.set or (_same(line.set, row["set"]) and _same(line.number, row["front_collector_number"]))


def allocate(inv, lines, taken=None):
    """({row index: cards}, [unmatched line text]): lines (TokenCardLine) shared out over inv's rows
    in their order, each row giving what taken ({row index: cards already held}, updated in place)
    leaves of it; what's left of a line goes to its last matching row."""
    taken = {} if taken is None else taken
    rows, unmatched = {}, []
    for line in lines:
        found = [i for i, row in enumerate(inv.rows) if matches(line, row)]
        if not found:
            unmatched.append(line.text())
            continue
        left = line.quantity
        for i in found:
            free = int(inv.rows[i]["quantity"]) - taken.get(i, 0)
            give = min(left, max(free, 0))
            if give:
                rows[i] = rows.get(i, 0) + give
                taken[i] = taken.get(i, 0) + give
                left -= give
            if not left:
                break
        if left:
            rows[found[-1]] = rows.get(found[-1], 0) + left
            taken[found[-1]] = taken.get(found[-1], 0) + left
    return rows, unmatched


def holds(inv, space=spaces.HOME, warnings=None, extra=None):
    """{deck id: {"title", "rows": {row index: cards}, "unmatched": [line text]}}: the built decks of
    space whose text has a Token cards line (an empty one holds nothing), matched against inv (allocate, deck by deck in id
    order). extra ({deck id: (title, [TokenCardLine])}) adds or replaces decks' lines, for a save
    that hasn't happened yet (Finish building). Home's explicit intact-product records are added
    once per actual product. A line that can't be read is a warning; invalid product records also
    carry an error so automatic planning cannot silently free unknown reservations."""
    warnings = [] if warnings is None else warnings
    from decklab.lib.inventory.ops_decks import parsed_deck
    found = {}
    snapshot = inventory.current()
    for summary in decks.list_decks():
        deck_id = summary["id"]
        if (deck_id.startswith(("product/", "pairing/")) or summary.get("space", spaces.HOME) != space
                or summary.get("status") != "built" or summary.get("error")):
            continue
        try:
            parsed = parsed_deck(snapshot.deck(deck_id))
            if parsed is None or not decks.has_token_cards(parsed):
                continue
            lines = decks.token_cards(parsed)
        except decks.DeckFileError as e:
            warnings.append(f"{summary['title']}'s Token cards line can't be read: {e}")
            continue
        found[deck_id] = (summary["title"], lines)
    found.update(extra or {})
    product_records = {}
    if space == spaces.HOME:
        from . import products
        product_records = products.records(warnings, snapshot)
        for holder, record in product_records.items():
            if record["written"]:
                found[holder] = (record["title"], record["lines"])
    taken, out = {}, {}
    for deck_id in sorted(found):
        title, lines = found[deck_id]
        rows, unmatched = allocate(inv, lines, taken)
        out[deck_id] = {"title": title, "rows": rows, "unmatched": unmatched}
        if deck_id in product_records:
            record = product_records[deck_id]
            out[deck_id].update(link=record["link"], error=record["error"])
    return out


def held_elsewhere(all_holds, deck_id):
    """{row index: [{"deck", "title", "quantity"}]}: the cards of each row the built decks of
    all_holds other than deck_id hold."""
    out = {}
    from . import products
    deck_id = products.holder_id(deck_id)
    for other in sorted(all_holds):
        if other == deck_id:
            continue
        hold = all_holds[other]
        for i, qty in hold["rows"].items():
            out.setdefault(i, []).append({"deck": other, "title": hold["title"], "quantity": qty})
    return out


def line_for(row, quantity):
    """The TokenCardLine naming quantity cards of a token row: its faces and, when the row records
    one, its printing (set and front collector number)."""
    printed = bool(row["set"] and row["front_collector_number"])
    return decks.TokenCardLine(quantity, row["front"], row["back"] or "",
                               row["set"].lower() if printed else "",
                               row["front_collector_number"] if printed else "")
