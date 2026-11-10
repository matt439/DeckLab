"""Private loose-card loan list and audited lend/whole-return actions."""
import re

from decklab.lib import inventory, permissions
from decklab.lib.inventory import loan_rules, ops_loans

from . import collection_edit as ce
from . import guard
from .collection import space_param
from .common import ApiError, _keys, _parse_body, _public
from .settings import _web_actor, _writer

PAGE = 100


def require_private_reader(space, profile=False):
    viewer = guard.viewer() if profile is False else profile
    if not permissions.sees_inventory(viewer, space, script=guard.script()):
        raise ApiError(403, guard.COLLECTION_HIDDEN)


def loans_view(space=None, before=None, include_returned=None):
    space = space_param(space)
    require_private_reader(space)
    if include_returned not in (None, "", "0", "1"):
        raise ApiError(400, "include_returned must be 0 or 1")
    try:
        records = ops_loans.rows_of(inventory.current(), space)
    except inventory.Invalid as error:
        raise ApiError(409, _public(error)) from None
    records = sorted((row for row in records if include_returned == "1" or not row["returned_on"]),
                     key=loan_rules.sort_key, reverse=True)
    if before:
        positions = [index for index, row in enumerate(records) if row["id"] == before]
        if not positions:
            raise ApiError(400, "Refresh the loan list before changing pages")
        records = records[positions[0] + 1:]
    shown = records[:PAGE]
    return {"space": space, "loans": shown, "next": shown[-1]["id"] if len(records) > PAGE else None,
            "ready": inventory.current().loans_ready}


def _request(body, returning=False):
    data = _parse_body(body)
    profile = _writer(data)
    space = space_param(data.get("space"))
    guard.require_space_write(profile, "collection.edit", space)
    require_private_reader(space, profile)
    required = ("profile", "loan_id", "returned_on") if returning else ("profile", "sha256", "row")
    _keys(data, required, ("space",))
    if returning:
        if not isinstance(data["loan_id"], str) or not re.fullmatch(r"[0-9a-f]{32}", data["loan_id"]):
            raise ApiError(400, "Use a loan ID from the current loan list")
        params = {key: data[key] for key in ("loan_id", "returned_on")}
    else:
        if not isinstance(data["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", data["sha256"]):
            raise ApiError(400, "Use the current collection's receipt")
        params = {"sha256": data["sha256"], "row": data["row"]}
    return profile, space, ops_loans.op("return" if returning else "lend", space=space, **params)


def _save(body, returning=False):
    profile, space, operation = _request(body, returning)
    if not returning:
        ce._require_cards()
    try:
        before = inventory.current()
        _, planned = operation.run(before)
        after, summary = inventory.apply(operation, _web_actor(profile), planned.text)
    except ce.ops.Stale:
        raise ce._stale(space) from None
    except inventory.Conflict as error:
        raise ApiError(409, _public(error)) from None
    except inventory.Invalid as error:
        raise ApiError(400, _public(error)) from None
    with inventory.pinned(after):
        stale = ce._stale_tables(space)
        rows = ce.rows_view(space)
    return {**rows, "ok": True, "loan": summary.extra["loan"], "stale_tables": stale}


def lend(body):
    return _save(body)


def return_loan(body):
    return _save(body, returning=True)
