"""Shared packing progress: scoped reads and atomic patches, independent of a plan's decks.

The page supplies semantic task ids. Only their SHA-256 hashes are persisted or audited,
and responses echo only the supplied ids, so another owner's private kit cannot be listed.
"""
import copy
import hashlib
import json

from decklab.lib import state
from decklab.lib.state import rules
from . import guard
from .common import ApiError, _CONTROL_RE, _keys, _parse_body, state_errors
from .settings import _web_actor, _writer

MAX_ID = 1000
MAX_BODY = 2 * 1024 * 1024
TOKEN_TASK_FIELDS = ("front", "back", "set", "front_collector_number", "back_collector_number",
                     "finish", "quantity", "front_details", "back_details")


def token_packing_keys(result, rows):
    """A copy with bounded per-need identities for the physical token cards a tick pulls.

    A need may match many long-detail rows. Hash those facts once on the server rather
    than making an unbounded browser task id. Display prose, row positions and notes do
    not change a physical task; printing, pairing, details, quantity and used face do.
    Sorting all ready/check candidates preserves the identity when inventory is reordered.
    A stand-in tick pulls only the first suggested card, as assemblyTokenTasks does.
    """
    answer = copy.deepcopy(result)
    for need in answer.get("needs", []):
        state = need.get("state")
        candidates = (need.get("cards") or []) if state in ("ready", "check") else (
            (need.get("stand_ins") or [])[:1] if state == "differs" else [])
        physical = []
        for candidate in candidates:
            index = candidate.get("row")
            row = rows[index] if isinstance(index, int) and 0 <= index < len(rows) else candidate
            facts = [row.get(field, "") for field in TOKEN_TASK_FIELDS]
            facts[TOKEN_TASK_FIELDS.index("quantity")] = int(row.get("quantity") or 0)
            physical.append(json.dumps([candidate.get("side"), facts], ensure_ascii=False, separators=(",", ":")))
        identity = [need.get(field) for field in ("key", "name", "kind", "state", "pt")]
        identity += [sorted(need.get(field) or []) for field in ("colors", "keywords")]
        payload = json.dumps([identity, sorted(physical)], ensure_ascii=False, separators=(",", ":"))
        need["packing_key"] = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return answer


def _ids(values):
    if not isinstance(values, list) or len(values) > rules.MAX_PACKING_TASKS:
        raise ApiError(400, f"Choose at most {rules.MAX_PACKING_TASKS} packing tasks")
    hashed = {}
    for value in values:
        if not isinstance(value, str) or not value or len(value) > MAX_ID or _CONTROL_RE.search(value):
            raise ApiError(400, f"Each packing task needs text of at most {MAX_ID} characters")
        try:
            hashed[value] = hashlib.sha256(value.encode("utf-8")).hexdigest()
        except UnicodeError:
            raise ApiError(400, "Each packing task must be valid Unicode text") from None
    return hashed


def packing_ticks(body):
    """POST /api/assembly/ticks {ids:[text], changes?:[{id,done}], profile?}.

    Without changes this reads only: no profile or audit entry is needed. A patch requires
    a real home writer and may change only supplied ids. Returns {ticks:[text]} restricted
    to that same scope. Both home players may tick any packing task they can describe;
    this never changes inventory, deck lists or accessories. Same-task edits use the last
    write; independent ticks are kept even when devices started from an older read.
    """
    data = _parse_body(body, limit=MAX_BODY)
    _keys(data, ("ids",), ("profile", "changes"))
    profile = _writer(data) if "changes" in data or "profile" in data else guard.viewer()
    guard.require_sees_home_records(profile)
    hashed = _ids(data["ids"])
    ids = list(hashed.values())
    store = state.store()
    with state_errors():
        if "changes" not in data:
            checked = set(store.packing_ticks(ids))
        else:
            values = data["changes"]
            if not isinstance(values, list) or len(values) > rules.MAX_PACKING_TASKS:
                raise ApiError(400, f"Give at most {rules.MAX_PACKING_TASKS} packing changes")
            changes = {}
            for change in values:
                if not isinstance(change, dict):
                    raise ApiError(400, "Each packing change needs id and done")
                _keys(change, ("id", "done"))
                key = change["id"]
                if not isinstance(key, str) or key not in hashed:
                    raise ApiError(400, "A packing change must name a task in ids")
                if not isinstance(change["done"], bool):
                    raise ApiError(400, "A packing tick must be true or false")
                if hashed[key] in changes:
                    raise ApiError(400, "Change each packing task only once")
                changes[hashed[key]] = change["done"]
            checked = set(store.packing_ticks_put(changes, _web_actor(profile), "Update packing ticks", ids=ids))
    return {"ticks": [key for key, hashed_id in hashed.items() if hashed_id in checked]}
