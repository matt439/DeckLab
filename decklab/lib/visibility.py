"""One fail-closed visibility snapshot per request, and publication readiness.

The state store owns persistence. This layer pins its complete snapshot beside
the inventory's snapshot, so every reader in an answer uses the same switches.
Nothing here seeds a Public row or overrides an owner's choice.
"""
import copy
import threading
from contextlib import contextmanager

from decklab.lib import state

# Each category joins this set only after its complete public readers pass their
# fixture checks (member-template section 4). The API enforces this same gate.
READY_THINGS = frozenset({"collection", "decks", "games", "accessories"})
_local = threading.local()


def _read():
    try:
        store = state.store()
    except Exception:
        return {}
    try:
        return store.visibility()
    except Exception:
        try:
            return store.visibility_cached()
        except Exception:
            return {}


def snapshot():
    """A caller-owned snapshot; never raises. With no recent database view, Private."""
    pin = getattr(_local, "pin", None)
    if pin is None:
        return _read()
    if pin[0] is None:
        pin[0] = _read()
    return copy.deepcopy(pin[0])


@contextmanager
def pinned():
    """Lazily read switches once during this request; nested scopes remain independent."""
    previous = getattr(_local, "pin", None)
    _local.pin = [None]
    try:
        yield
    finally:
        _local.pin = previous


def replace(snapshot):
    """A successful flip's response sees its committed value immediately."""
    pin = getattr(_local, "pin", None)
    if pin is not None:
        pin[0] = copy.deepcopy(snapshot)
