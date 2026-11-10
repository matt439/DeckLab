"""Remembered card categories from the viewer's actual own space, never other Public spaces."""
from collections import Counter, defaultdict

from decklab.lib import cards, decks, inventory, permissions
from decklab.lib.inventory import pg_decks

from . import common, guard
from .card_decks import _name
from .card_lookup import _resolve
from .carddata import _require_cards
from .collection import space_param
from .common import ApiError

MAX_CHOICES = 30


def choices_view(name=None, space=None, exclude=None):
    space = space_param(space)
    viewer = guard.viewer()
    # Deliberately the private permission: publishing a collection/deck never
    # publishes category habits derived from all the space's other private decks.
    if not permissions.sees_inventory(viewer, space, script=guard.script()):
        raise ApiError(403, guard.COLLECTION_HIDDEN)
    name = _name(name)
    if exclude is not None and (not isinstance(exclude, str) or len(exclude) > 150 or common._CONTROL_RE.search(exclude)):
        raise ApiError(400, "Use a current deck id to exclude it")
    _require_cards()
    exact = _resolve(name)
    if not exact:
        raise ApiError(404, "That card isn't in the current card data")
    counts, spellings = Counter(), defaultdict(Counter)
    with common.state_errors():
        source = inventory.current()
    for saved in source.decks.values():
        if saved.space != space or saved.id == exclude or saved.error or saved.text is None:
            continue
        parsed = pg_decks.parsed(saved.id, saved.text)
        if parsed is None:
            continue
        lines = [line for sections in (parsed.target, parsed.owned) if sections for found in sections.values() for line in found]
        lines += parsed.considering or []
        seen = set()
        for line in lines:
            if line.category and (cards.resolve(line.name) or line.name) == exact:
                key = line.category.casefold()
                spellings[key][line.category] += 1
                seen.add(key)
        counts.update(seen)             # one deck votes once, independent of copies/lists
    labels = {key: sorted(found, key=lambda label: (-found[label], label.casefold(), label))[0]
              for key, found in spellings.items()}
    ordered = sorted(counts, key=lambda key: (-counts[key], labels[key].casefold(), labels[key]))
    return {"name": exact, "categories": [labels[key] for key in ordered[:MAX_CHOICES]], "more": len(ordered) > MAX_CHOICES}
