"""Read-only deck identity helpers. Writes always address Inventory.deck's exact key.

Aliases are flattened and retained through retirement. Unknown/product/pairing IDs are
returned unchanged; no caller needs a database lookup beyond its pinned snapshot.
"""


def resolve_deck_id(deck_id, inv=None):
    if inv is None:
        from . import current
        inv = current()
    return inv.deck_aliases.get(deck_id, deck_id)


def deck_lineage(deck_id, inv=None):
    if inv is None:
        from . import current
        inv = current()
    canonical = resolve_deck_id(deck_id, inv)
    return tuple(sorted({canonical, *(alias for alias, target in inv.deck_aliases.items() if target == canonical)}))


def same_deck_id(first, second, inv=None):
    if inv is None:
        from . import current
        inv = current()
    return resolve_deck_id(first, inv) == resolve_deck_id(second, inv)
