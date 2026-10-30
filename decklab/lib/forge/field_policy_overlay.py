"""HOME's saved field choices (E3-S23) laid over the legacy field selector.

field._field reads simulation.json's directives, then asks prepare() for a plan
before its add/remove passes, so the membership trace, the exclusion observer and
the notes see only the effective directives; plan.apply() runs after those passes.

- Only HOME's field (space "home") reads the policy. Member fields, and therefore
  home lists seen through a public space, keep legacy selection in this slice.
- A current house deck whose proved incarnation has no entry keeps its legacy
  selection exactly. An entry masks every legacy directive naming that deck (any
  version, through its aliases): include pins its Planned or Play-now list, exclude
  takes it out (a manual exclusion, counted and explained as the file's are), and
  "rules" keeps the automatic choice. A recreated deck never inherits an entry.
- No store installed (a fixture without field policies), a store without the
  method, or migration 0017 not applied: no policy, so today's field exactly.
- A failed policy read fails closed: the saved choices may hold an exclusion, so it
  never reads as an empty policy. The plan's refused (REFUSED) stops field runs
  from starting (field.opponents(fail_closed=True), field.run_field), and views
  keep legacy selection with the UNREADABLE note and an unavailable membership
  trace and exclusion count. That's any failed read except the proved missing 0017
  table, and the missing table too once this store has read the format's policy.
- A deck whose incarnation can't be proved while rules exist keeps legacy
  selection, with a note naming no deck and the counts unavailable (not refused).

Incarnations come from one read-only database transaction per call
(inventory/pg_deck_epoch.read_many), cached by inventory revision for ready
results only, and each receipt must match the pinned snapshot's deck revision
and text. Nothing here writes, starts games or checks request permissions.
"""
import hashlib
import threading
import weakref

from decklab.lib import inventory, state
from decklab.lib.inventory import deck_epoch
from decklab.lib.state import field_policy

from . import deck_identity, field_exclusions

UNREADABLE = ("Home's saved field choices can't be read now, so this field follows its rules without them "
              "and field runs wait until they can be read.")
REFUSED = ("Home's saved field choices can't be read now, so the field can't be played: a list they leave out "
           "could come back. Try again later.")
UNPROVED = "Some decks' saved field choices can't be checked now, so those decks follow the field's rules."
MISSING_VERSION = ("{title} has a saved choice of its {label} list, which it no longer has, "
                   "so the field uses the list its rules choose.")
LABELS = {"target": "Planned", "owned": "Play-now"}
_KINDS = {"Constructed": "casual", "Commander": "commander"}
_CACHE_SIZE = 8
_cache = {}                     # (inventory revision, decks revision) -> {deck id: Resolution}
_cache_lock = threading.Lock()
_read_ok = weakref.WeakKeyDictionary()     # store -> formats whose policy it has read: the table exists


class _Unknown(Exception):
    pass


class Plan:
    """rules: {current canonical deck id: saved rule} for the incarnations prepare() proved;
    refused: REFUSED when the saved choices couldn't be read (no field run may start), else None."""

    def __init__(self, rules=None, refused=None):
        self.rules = dict(rules or {})
        self.refused = refused

    def directives(self, add, remove, exclusions=None):
        """(add, remove) without the legacy names of decks that have an entry.

        The observer's parsed removals become the effective ones, policy exclusions
        included, so Rankings explains a policy exclusion as it does the file's.
        """
        if not self.rules:
            return add, remove
        add = [name for name in add if not self._masked(name)]
        remove = [name for name in remove if not self._masked(name)]
        excluded = [deck_id for deck_id, rule in sorted(self.rules.items()) if rule["mode"] == "exclude"]
        field_exclusions.notify(exclusions, "configuration", [*remove, *excluded], True)
        return add, remove

    def _masked(self, name):
        return deck_identity.canonical(name.partition("@")[0].strip()) in self.rules

    def apply(self, chosen, notes, *, trace=None, exclusions=None, visible=None):
        """chosen ([(summary, version)]) after the legacy passes, with each entry applied."""
        if not self.rules:
            return chosen
        out = []
        for summary, selected in chosen:
            rule = self.rules.get(summary["id"])
            if rule is None or rule["mode"] == "rules":
                out.append((summary, selected))
            elif rule["mode"] == "exclude":
                if trace is not None:
                    trace.removed(summary, selected)
                field_exclusions.notify(exclusions, "removed", summary, selected, summary["id"], visible)
            elif rule["version"] not in summary.get("versions", []):
                notes.append(MISSING_VERSION.format(title=summary.get("title") or summary["id"],
                                                    label=LABELS[rule["version"]]))
                out.append((summary, selected))
            else:
                if trace is not None:
                    trace.candidate(summary, rule["version"], "configured_add")
                out.append((summary, rule["version"]))
        return out


LEGACY = Plan()
CLOSED = Plan(refused=REFUSED)  # legacy selection for views; field runs refused


def prepare(fmt, space, chosen, notes, *, trace=None, exclusions=None):
    """The plan for this selection pass: LEGACY where no saved choice applies, CLOSED when the
    saved choices can't be read."""
    if space != "home" or fmt not in _KINDS:
        return LEGACY
    try:
        policy = _policy(fmt)
    except _Unknown:
        _unknown(UNREADABLE, notes, trace, exclusions)
        return CLOSED
    if policy is None or not policy["rules"]:
        return LEGACY
    by_epoch = {_key(rule["epoch"]): rule for rule in policy["rules"]}
    house = [summary["id"] for summary, _ in chosen
             if deck_epoch.home_id(summary["id"]) and summary["id"].partition("/")[0] == _KINDS[fmt]]
    proved = _epochs(house)
    rules = {}
    for deck_id in house:
        if deck_id not in proved:
            continue
        rule = by_epoch.get(proved[deck_id])
        if rule is not None:
            rules[deck_id] = rule
    if len(proved) != len(set(house)):
        _unknown(UNPROVED, notes, trace, exclusions)
    return Plan(rules) if rules else LEGACY


def _key(epoch):
    return epoch["kind"], epoch["deck_id"], epoch["revision"]


def _unknown(note, notes, trace, exclusions):
    notes.append(note)
    if trace is not None:
        trace.unavailable()
    field_exclusions.notify(exclusions, "unavailable")


def _policy(fmt):
    """The checked policy, None for "no policy here", or _Unknown for a failed read. Only the
    proved missing 0017 table is "no policy", and only until this store has read fmt's policy:
    after that a missing table is a failed read too, never a lapsed saved exclusion."""
    try:
        store = state.store()
    except RuntimeError:
        return None
    read = getattr(store, "field_policy", None)
    if not callable(read):
        return None
    try:
        policy = field_policy.normalize(read(fmt))
    except state.Unavailable as error:
        if _missing_schema(error) and fmt not in _formats_read(store):
            return None
        raise _Unknown from None
    except Exception:
        raise _Unknown from None
    try:
        with _cache_lock:
            _read_ok.setdefault(store, set()).add(fmt)
    except TypeError:
        pass            # a store that can't be weakly referenced isn't remembered
    return policy


def _formats_read(store):
    try:
        with _cache_lock:
            return set(_read_ok.get(store, ()))
    except TypeError:
        return set()


def _missing_schema(error):
    try:
        from decklab.lib.state import pg_field_policy
        return pg_field_policy.missing_schema(error)
    except Exception:
        return False


def _epochs(deck_ids):
    """{deck id: epoch key} for the ids whose incarnation is proved and matches the pinned
    snapshot's revision and text; any other id is left out (unproved)."""
    if not deck_ids:
        return {}
    try:
        inv = inventory.current()
        if inv.backend != "db" or inv.stale is not None or not inv.persisted:
            return {}
        backend = inventory.backend()
    except Exception:
        return {}
    expected = {}
    for deck_id in dict.fromkeys(deck_ids):
        deck = inv.decks.get(deck_id)
        if deck is None or deck.error is not None or type(deck.text) is not str or deck.revision < 1:
            continue
        try:
            expected[deck_id] = (deck.revision, hashlib.sha256(deck.text.encode("utf-8")).hexdigest())
        except UnicodeError:
            continue
    key = (inv.revision, inv.decks_revision)
    with _cache_lock:
        known = dict(_cache.get(key, {}))
    missing = [deck_id for deck_id in expected if deck_id not in known]
    if missing:
        from decklab.lib.inventory import pg_deck_epoch
        found = pg_deck_epoch.read_many(backend, missing)
        fresh = {deck_id: found[deck_id] for deck_id in missing
                 if deck_id in found and found[deck_id].status == "ready"}
        known.update(fresh)
        if fresh:
            with _cache_lock:
                _cache.setdefault(key, {}).update(fresh)
                while len(_cache) > _CACHE_SIZE:
                    _cache.pop(next(iter(_cache)))
    out = {}
    for deck_id, (revision, sha) in expected.items():
        resolution = known.get(deck_id)
        receipt = getattr(resolution, "receipt", None)
        if (resolution is None or resolution.status != "ready" or receipt is None
                or (receipt.deck_id, receipt.revision, receipt.sha256) != (deck_id, revision, sha)):
            continue
        epoch = resolution.epoch
        out[deck_id] = (epoch.kind, epoch.deck_id, epoch.revision)
    return out


def clear_cache():
    """Forget cached incarnations and which stores have read a policy (tests)."""
    with _cache_lock:
        _cache.clear()
        _read_ok.clear()
