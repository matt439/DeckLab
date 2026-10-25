"""Read current deck identities without changing captured Forge evidence.

Result keys, card hashes, ``seen_as`` records and variant summaries keep the identities
they were saved with. Only comparisons and links use the inventory's rename aliases.
An unavailable inventory leaves captured names usable, as before rename support.
"""
from decklab.lib import inventory


def canonical(deck_id):
    if not isinstance(deck_id, str):
        return deck_id
    if deck_id.startswith("pairing/"):
        return "pairing/" + "+".join(sorted(deck_id[8:].split("+")))
    try:
        return inventory.resolve_deck_id(deck_id)
    except (inventory.StateError, OSError, ValueError, RuntimeError):
        return deck_id


def lineage(deck_id):
    try:
        names = inventory.deck_lineage(deck_id)
    except (inventory.StateError, OSError, ValueError, RuntimeError):
        names = (deck_id,)
    current = canonical(deck_id)
    return (current, *sorted(name for name in names if name != current))


def same(first, second):
    return first == second or canonical(first) == canonical(second)
