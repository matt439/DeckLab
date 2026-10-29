"""Home's saved field choices (E3-S23): a home admin's reviewed preview, then one audited save.

    POST /api/field/policy/preview  {"profile", "id", "version", "mode"}: writes nothing
    POST /api/field/policy          {"profile", "format", "revision", "proof", "mode", "reason"?}

- Both need field.edit (permissions: a home admin), checked first, so a member or a
  request naming nobody is refused as the simulations and Commander-night writes refuse
  them, before any deck, policy or list is read. A hidden deck then answers as a missing one.
- mode is "include" (pin the reviewed list), "exclude" (leave the deck out; reason needed,
  kept only in home's audit trail) or "rules" (follow the field rules, masking older hand
  edits of the settings file). Only a home house deck's list (casual/..., commander/...) has one.
- The preview reads the format's policy and the list's current proof (the store's
  field_policy_review: its checked incarnation, text receipt and card hash) and answers
  {"format", "deck": {"id", "version"}, "current", "proposed", "changed", "reason_required",
  "ready", "message", "expect": {"revision", "proof"}}. current is {"mode": "legacy"} when the
  deck has no saved choice. revision is a decimal string (policy revisions exceed
  JavaScript's exact integers). Before migration 0017 the policy reads as empty, "ready" is
  false and "message" names the migrate command.
- The save sends the preview's expect back: the store checks the revision and recomputes the
  proof in its own write transaction (409 when either changed), then saves one audited change.
  Its answer is {"changed", "format", "revision"}. Before migration 0017 it answers 503 with the
  migrate command. Nothing here starts games; the field view reads the new choice next time.
"""
import re
from contextlib import contextmanager

from decklab.lib import state
from decklab.lib.inventory import deck_epoch
from decklab.lib.state import field_policy

from . import guard
from .common import DATABASE_DOWN, ApiError, _keys, _parse_body
from .settings import _web_actor

MAX_BODY = 8192             # a proof, a format and a reason of at most 1000 characters fit
MODES = ("include", "exclude", "rules")
VERSIONS = ("target", "owned")
FORMATS = {"casual": "Constructed", "commander": "Commander"}
MIGRATE = "Field choices need the database migration: python -m decklab.db migrate"
HOME_ONLY = "Only a home deck's Planned or Play-now list can have a saved field choice."
_REVISION = re.compile(r"0|[1-9][0-9]{0,18}")
_LABELS = {"target": "Planned", "owned": "Play-now"}


def _missing_schema(error):
    """True for the database's refusal before migration 0017 (pg_field_policy's)."""
    try:
        from decklab.lib.state import pg_field_policy
        return pg_field_policy.missing_schema(error)
    except Exception:
        return False


def _confirm_words():
    from decklab.lib.state import field_policy_source
    words = {field_policy_source.UNAVAILABLE}
    try:
        from decklab.lib.state import pg_field_policy
        words.add(pg_field_policy.UNAVAILABLE)
    except Exception:
        pass
    return words


@contextmanager
def _errors():
    """state_errors(), except that a missing policy table names the migrate command."""
    try:
        yield
    except state.Unavailable as e:
        if _missing_schema(e):
            raise ApiError(503, MIGRATE, reason="database") from None
        # The policy stores' own fixed words name no deck or database detail; any other
        # unavailability (a raw database error included) gets the usual words.
        raise ApiError(503, str(e) if str(e) in _confirm_words() else DATABASE_DOWN, reason="database") from None
    except state.Invalid as e:
        raise ApiError(400, str(e)) from None
    except state.Conflict as e:
        raise ApiError(409, str(e)) from None


def _choice(value, name, allowed):
    if type(value) is not str or value not in allowed:
        raise ApiError(400, f"{name} must be one of: {', '.join(allowed)}")
    return value


def _home_list(deck_id):
    """(canonical-looking id, format) for a home house deck the viewer may see; 404 as a
    missing deck for a hidden one, 400 for any other kind of list."""
    if type(deck_id) is not str or not deck_id:
        raise ApiError(400, "id must be a deck id")
    guard.require_sees_deck(deck_id)
    if not deck_epoch.home_id(deck_id):
        raise ApiError(400, HOME_ONLY)
    return deck_id, FORMATS[deck_id.partition("/")[0]]


def _store():
    store = state.store()
    if not all(callable(getattr(store, name, None))
               for name in ("field_policy", "field_policy_apply", "field_policy_review")):
        raise ApiError(503, DATABASE_DOWN, reason="database")
    return store


def _view(rule):
    if rule is None:
        return {"mode": "legacy"}
    return {"mode": rule["mode"], **({"version": rule["version"]} if rule["mode"] == "include" else {})}


def _rule(proof, mode):
    rule = {"epoch": proof["epoch"], "mode": mode}
    if mode == "include":
        rule["version"] = proof["version"]
    return rule


def preview(body):
    """POST /api/field/policy/preview (the module docstring); nothing is written."""
    data = _parse_body(body, MAX_BODY)
    guard.writer(data, "field.edit")
    _keys(data, ("profile", "id", "version", "mode"))
    deck_id, fmt = _home_list(data["id"])
    version = _choice(data["version"], "version", VERSIONS)
    mode = _choice(data["mode"], "mode", MODES)
    store = _store()
    ready, message = True, None
    with _errors():
        try:
            policy = store.field_policy(fmt)
        except state.Unavailable as e:
            if not _missing_schema(e):
                raise
            policy, ready, message = field_policy.empty(fmt), False, MIGRATE
        proof = store.field_policy_review(fmt, deck_id, version)
        desired = _rule(proof, mode)
        current = field_policy.lookup(policy, proof["epoch"])
        changed = field_policy.transition(policy, policy["revision"], desired)["changed"]
    return {"format": fmt, "deck": {"id": proof["receipt"]["deck_id"], "version": version},
            "current": _view(current), "proposed": _view(desired), "changed": changed,
            "reason_required": mode == "exclude", "ready": ready, "message": message,
            "expect": {"revision": str(policy["revision"]), "proof": proof}}


def _revision(value):
    if type(value) is not str or not _REVISION.fullmatch(value) or int(value) > field_policy.MAX_REVISION:
        raise ApiError(400, "revision must be the policy revision the preview gave, as a decimal string")
    return int(value)


def _message(fmt, deck_id, mode, version):
    if mode == "include":
        return f"Include {deck_id}'s {_LABELS[version]} list in the {fmt} field"
    if mode == "exclude":
        return f"Leave {deck_id} out of the {fmt} field"
    return f"Let the field rules choose {deck_id}'s list in the {fmt} field"


def save(body):
    """POST /api/field/policy (the module docstring): one audited, revision-checked change."""
    data = _parse_body(body, MAX_BODY)
    profile = guard.writer(data, "field.edit")
    _keys(data, ("profile", "format", "revision", "proof", "mode"), ("reason",))
    fmt = _choice(data["format"], "format", tuple(FORMATS.values()))
    revision = _revision(data["revision"])
    mode = _choice(data["mode"], "mode", MODES)
    proof = data["proof"]
    receipt = proof.get("receipt") if isinstance(proof, dict) else None
    if not isinstance(receipt, dict) or not isinstance(proof.get("epoch"), dict) \
            or proof.get("version") not in VERSIONS:
        raise ApiError(400, "proof must be the one the preview gave")
    deck_id, deck_fmt = _home_list(receipt.get("deck_id"))
    if deck_fmt != fmt:
        raise ApiError(400, "proof must be the one the preview gave")
    reason = data.get("reason")
    store = _store()
    with _errors():
        result = store.field_policy_apply(fmt, revision, proof, _rule(proof, mode), _web_actor(profile),
                                          _message(fmt, deck_id, mode, proof["version"]), reason)
    return {"changed": result["changed"], "format": fmt, "revision": str(result["snapshot"]["revision"])}


def editable(space):
    """Whether this request's named viewer may change the field of a deck of space (home's only)."""
    try:
        profile = guard.viewer()
    except ApiError:
        return False
    return bool(profile) and space == "home" and guard.allowed(profile, "field.edit")
