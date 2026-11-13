"""A space's storage setting as Deck Lab uses it (E8-S25): the saved record (state.space_storage)
over the built-in default. state/space_storage.py has the record's rules and match().

    read(space)   -> {space, revision, ready, source, storage}; raises state's errors
    current(space) -> the same, but never raises: a store that can't be read (the database down,
                     no store installed) answers as "nothing saved", so home keeps its built-in
                     box and the Card list's count still shows (source "default", revision None)

source is "saved" (the space's own record), "default" (home's built-in box, its capacity
config.json's storage_box_capacity or 2,400: Q6, a seed only until home's first save) or "none"
(any other space with nothing saved: no containers).
"""
from decklab.lib import config, state
from decklab.lib.state import space_storage as rules


def capacity_seed():
    """config.json's storage_box_capacity when it's a whole number from 1 to 100,000, else None."""
    try:
        value = config.load().get("storage_box_capacity")
    except (OSError, ValueError):
        return None
    if isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= rules.MAX_CAPACITY:
        return value
    return None


def _view(space, saved, seed=True):
    record, source = rules.effective(space, saved["storage"], capacity_seed() if seed else None)
    return {"space": space, "revision": saved["revision"], "ready": saved["ready"], "source": source,
            "storage": record}


def read(space, *, seed=True):
    """The space's storage as it applies now (the module docstring); state errors propagate.
    seed False leaves config.json unread (the built-in box then holds BUILTIN_CAPACITY), for a
    caller that needs only the containers and their sections."""
    return _view(space, state.store().space_storage(space), seed)


def current(space, *, seed=True):
    """read(space), or the built-in answer when the store can't be read (never raises)."""
    try:
        return read(space, seed=seed)
    except (state.StateError, RuntimeError, OSError):
        return _view(space, {"revision": None, "storage": None, "ready": None}, seed)
