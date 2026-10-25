"""Advisory checks before a Collection page change removes physical copies.

The caller authorises the space and simulates its collection operation first. These
helpers only read those snapshots: no incoming cards count as physically available,
and the pool remains the authority on which list a built deck or intact product holds.
"""
from collections import Counter

from decklab.lib import cards, decks, inventory, pool, spaces
from decklab.lib.inventory import ops_collection as collection_ops


class ReductionCheckError(ValueError):
    """The caller should offer an acknowledgeable unknown-demand warning.

    The public words deliberately contain no inventory paths. ``detail`` is for the
    server log; failure to check demand must not silently mean that nothing is held.
    """

    def __init__(self, detail):
        super().__init__("Cards held by built decks and intact products couldn't be checked. "
                         "Review those decks before removing copies.")
        self.detail = str(detail)


def _raw_counts(inv, space):
    sheet = inv.collection(space)
    problem = collection_ops.unreadable(sheet)
    if problem:
        raise ReductionCheckError(problem)
    counts = Counter()
    for row in sheet.rows:
        name = row.text("name").strip()
        quantity = int(row.text("quantity"))
        if not name or quantity <= 0:
            raise ReductionCheckError("The collection has an invalid card name or quantity")
        if not decks.is_basic_land(name):
            counts[name] += quantity
    return counts


def _physical_counts(inv, space):
    sheet = inv.collection(space)
    if not sheet.exists:
        return Counter()
    unresolved = {}
    counts = pool.read_card_csv(sheet, unresolved)
    if unresolved:
        raise ReductionCheckError("The collection contains unresolved card names")
    return counts


def _intact_stems(inv, space):
    if space != spaces.HOME:
        return set()
    products = {product.file for product in inv.products}
    sheet = inv.status
    if not products and not sheet.exists:
        return set()
    if not sheet.exists or sheet.error or sheet.strict_error:
        raise ReductionCheckError("The products' kept-intact choices can't be read")
    statuses = {}
    for row in sheet.rows:
        filename = row.text("file")
        status, intact = row.text("status"), row.text("intact")
        if filename in products and (status not in pool.PRODUCT_STATUSES or intact not in ("", "yes", "no")):
            raise ReductionCheckError("A product's kept-intact choice is unknown")
        statuses[filename] = (status, intact)
    if products - statuses.keys():
        raise ReductionCheckError("A product has no kept-intact choice")
    intact = {filename.removesuffix(".csv") for filename, choice in statuses.items()
              if choice == ("owned", "yes")}
    if {f"{stem}.csv" for stem in intact} - products:
        raise ReductionCheckError("An intact product's card list is missing")
    return intact


def _check_holders(inv, space, held_pool):
    """Pool reads tolerate broken lists; an advisory removal check must say it couldn't check."""
    intact = _intact_stems(inv, space)
    found, expected = set(), set()
    for summary in decks.list_decks():
        if summary.get("space", spaces.HOME) != space:
            continue
        deck_id = summary["id"]
        product = deck_id.split("/")[1] if deck_id.startswith("product/") else None
        if product:
            if product not in intact:
                continue
            found.add(product)
        elif summary.get("status") != "built":
            if summary.get("error") and summary.get("status") is None:
                raise ReductionCheckError("A deck's built status can't be read")
            continue
        if summary.get("error"):
            raise ReductionCheckError("A held decklist can't be read")
        expected.add(deck_id)
    if intact - found or expected - {holder.id for holder in held_pool.in_use}:
        raise ReductionCheckError("A held decklist couldn't be counted")
    if any(cards.resolve(name) is None for holder in held_pool.in_use for name in holder.cards):
        raise ReductionCheckError("A held decklist contains unresolved card names")


def reduction_warnings(before, after, space):
    """Warnings for reduced card totals that leave fewer physical copies than are held.

    Returns ``[{name, before, after, in_use, shortage, holders: [{id, title, qty}]}]``
    sorted by name. Existing shortages are warned about when a further reduction
    worsens them. Printing/finish corrections, basic lands, and metadata-only changes
    lose no playable copies and produce no warning. ``ReductionCheckError`` means the
    page must offer an explicit unknown-demand warning rather than assume no demand.
    """
    try:
        old_raw, new_raw = _raw_counts(before, space), _raw_counts(after, space)
        if all(new_raw[name] >= quantity for name, quantity in old_raw.items()):
            return []
        old, new = _physical_counts(before, space), _physical_counts(after, space)
        reduced = [name for name in old if new[name] < old[name]]
        if not reduced:
            return []
        with inventory.pinned(before):
            held_pool = pool.load_pool(space)
            _check_holders(before, space, held_pool)
        warnings = []
        for name in sorted(reduced, key=str.casefold):
            holders = [{"id": holder.id, "title": holder.title, "qty": holder.cards[name]}
                       for holder in sorted(held_pool.in_use, key=lambda holder: holder.id)
                       if holder.cards[name]]
            held = sum(holder["qty"] for holder in holders)
            if new[name] < held:
                warnings.append({"name": name, "before": old[name], "after": new[name],
                                 "in_use": held, "shortage": held - new[name], "holders": holders})
        return warnings
    except ReductionCheckError:
        raise
    except Exception as error:  # An unavailable or damaged source is an unknown-demand warning.
        raise ReductionCheckError(error) from error
