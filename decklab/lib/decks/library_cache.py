"""The library's reads memoised on one inventory snapshot (E11-S90).

A snapshot (lib/inventory's Inventory) never changes in place: a write makes a new one, a pinned
request keeps one, and the database backend hands back the same object while nothing changed. So
whatever the library works out from a snapshot (each deck's parse, list_decks()'s summaries, the
product decks and the Beginner Box pairings) is kept on that snapshot object and worked out at most
once, however many find_summary() and load_deck() lookups a Game log or Build decks request makes.
A write's new snapshot starts with nothing kept, so the next read sees it.

What is kept is never handed out: every reader gets its own copy (copied() for summaries and
product decks, sections() for a decklist), so a caller changing what it was given changes no
other caller's copy. A preview's snapshot is kept on like any other, since it's keyed by the
object, never by revision.
"""
import copy
import threading

_ATTR = "_decklab_library_cache"
_lock = threading.Lock()
_MISSING = object()


def store(snapshot):
    """The dict kept on snapshot (made on first use), or None for an object that can't hold one."""
    found = getattr(snapshot, "__dict__", {}).get(_ATTR)
    if found is not None:
        return found
    with _lock:
        found = snapshot.__dict__.get(_ATTR) if hasattr(snapshot, "__dict__") else None
        if found is None:
            found = {}
            try:
                object.__setattr__(snapshot, _ATTR, found)     # a frozen dataclass: not one of its fields
            except (AttributeError, TypeError):
                return None
    return found


def kept(snapshot, key, work):
    """work()'s answer for key on snapshot: worked out once, then the same object each time.
    An exception isn't kept (the next call works it out again)."""
    cache = store(snapshot)
    if cache is None:
        return work()
    found = cache.get(key, _MISSING)
    if found is _MISSING:
        found = work()
        cache.setdefault(key, found)
        found = cache[key]
    return found


def copied(value):
    """A caller's own copy of a kept summary, product deck or list of them."""
    return copy.deepcopy(value)


def sections(found):
    """A caller's own copy of a kept decklist {section: [DeckLine]}."""
    return {name: [copy.copy(line) for line in lines] for name, lines in found.items()}
