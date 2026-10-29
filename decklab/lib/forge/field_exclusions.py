"""Bounded, optional metadata from the selector's existing decisions.

This observer neither chooses lists nor reads anything. A complete actual pass,
including its existing configuration read, is required before zero is meaningful.
Raw configuration names and list identities remain internal to the calculation.
"""

MAX_LISTS = 1000


def observation(visible=None):
    try:
        return Observation(visible)
    except Exception:
        return None


def count(observer):
    try:
        value = observer.count
        return value if type(value) is int and 0 <= value <= MAX_LISTS else None
    except Exception:
        return None


def removals(observer):
    try:
        names = observer.removals
        return names if isinstance(names, (list, tuple)) and all(isinstance(name, str) for name in names) else ()
    except Exception:
        return ()


def notify(observer, method, *args):
    """Metadata failures must not change legacy selection or its exception types."""
    if observer is None:
        return
    try:
        getattr(observer, method)(*args)
    except Exception:
        try:
            observer.unavailable()
        except Exception:
            try:
                if isinstance(observer, Observation):
                    object.__setattr__(observer, "_complete", False)
            except Exception:
                pass


class Observation:
    def __init__(self, visible=None):
        self.visible = visible
        self._started = self._finished = self._configured = False
        self._complete = True
        self._keys = set()
        self._removals = None

    def begin(self):
        if self._started:
            self.unavailable()
        self._started = True

    def unavailable(self):
        self._complete = False
        self._keys.clear()

    def configuration(self, remove, valid=True):
        self._configured = True
        # Keep the legacy parser's normalized names for the existing prose even
        # when malformed neighboring values make the complete count unknown.
        # This retains its list, without another read or arbitrarily large copy.
        self._removals = remove
        if not valid:
            self.unavailable()

    def removed(self, summary, version, raw_id, visible):
        if not self._complete:
            return
        # The selector supplied a current summary. Check both the configured raw
        # alias and that canonical identity, without another alias lookup.
        gates = [self.visible]
        if visible is not self.visible:
            gates.append(visible)
        if any(gate is not None and (not gate(raw_id) or not gate(summary["id"])) for gate in gates):
            return
        key = (summary["id"], version)
        if key not in self._keys and len(self._keys) >= MAX_LISTS:
            self.unavailable()
            return
        self._keys.add(key)

    def finish(self):
        self._finished = True

    @property
    def count(self):
        return len(self._keys) if self._started and self._finished and self._configured and self._complete else None

    @property
    def removals(self):
        """Private parsed names for existing exclusion prose; never a public field."""
        return self._removals if self._configured and self._removals is not None else ()
