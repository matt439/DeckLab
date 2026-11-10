"""One CAS-checked audited review of queue references or explicit market targets."""
from decklab.lib import shop_references, shop_reference_source, shops
from decklab.lib.state import Conflict, Invalid

from . import Op, Summary, register, watchlist_targets
from .model import QUEUE_FIELDS

MAX_ROWS = 100
CHANGED = "Shopping changed meanwhile. Reload it and review the references again."
SOURCE_CHANGED = "The saved shop reading or household preference changed. Nothing was saved; prepare a fresh review."


def rows_of(inv):
    if inv.watchlist.error or inv.watchlist.csv_error:
        raise Invalid("The purchase queue needs checking before its prices can be changed")
    return [{key: row.text(key) for key in QUEUE_FIELDS} for row in inv.watchlist.rows]


def plan(inv, *, expect, requests, kind, source=None):
    """Validate all requests before constructing any changed rows."""
    if inv.revision != expect:
        raise Conflict(CHANGED)
    if kind not in ("reference", "target") or not isinstance(requests, (list, tuple)) or not 1 <= len(requests) <= MAX_ROWS:
        raise Invalid(f"Review 1 to {MAX_ROWS} queue rows at once")
    source = shop_reference_source.context(fresh=True) if source is None else source
    rows = rows_of(inv)
    changes, seen = [], set()
    for request in requests:
        required = {"row", "receipt", "shop"} if kind == "reference" else {"row", "receipt", "value"}
        if not isinstance(request, dict) or set(request) != required:
            raise Invalid("Use the row and source receipt from the current price review")
        number = request["row"]
        if type(number) is not int or not 1 <= number <= len(rows) or number in seen:
            raise Conflict(CHANGED)
        seen.add(number)
        row = rows[number - 1]
        if not isinstance(request["receipt"], str) or len(request["receipt"]) != 64:
            raise Invalid("Use the source receipt from the current Shopping page")
        if kind == "reference":
            if not isinstance(request["shop"], str):
                raise Invalid("Use the shop from the current Shopping page")
            adapter = source["adapters"].get(request["shop"])
            if adapter is None:
                raise Conflict(SOURCE_CHANGED)
            check = {**row, "is_token": shops._rows.is_token(row)}
            quote = shop_references.observation(check, source["data"].get(adapter.key), adapter,
                       preference=source["preference"], confirm_printing=shop_reference_source.confirm_printing)
            digest, new = quote["receipt"], quote["fields"]
            old = {key: row[key] for key in shop_references.FIELDS}
            detail = {"printing": quote["printing"], "source": quote["source"]}
        else:
            value = watchlist_targets.normalize(request["value"])
            if value is not None and not inv.targets_ready:
                raise Invalid(watchlist_targets.MIGRATE)
            digest = shop_reference_source.receipt(row, source)
            old, new = {watchlist_targets.FIELD: row[watchlist_targets.FIELD]}, {watchlist_targets.FIELD: value or ""}
            detail = {}
        if digest != request["receipt"]:
            raise Conflict(SOURCE_CHANGED)
        changes.append({"row": number, "name": row["name"], "old": old, "new": new, **detail})
    return changes


@register("watchlist.reference_review")
def apply_review(inv, *, expect, requests, kind, repo="."):
    from .orders import set_queue
    try:
        changes = plan(inv, expect=expect, requests=requests, kind=kind)
    except shop_references.Unconfirmed as error:
        raise Conflict(str(error)) from None
    except ValueError as error:
        raise Invalid(str(error)) from None
    after = inv
    for change in changes:
        after, _ = set_queue(after, select=f"#{change['row']}", values=change["new"], repo=repo)
    changed = sum(change["old"] != change["new"] for change in changes)
    text = (f"Update {changed} purchase queue reference observations from saved shop readings" if kind == "reference"
            else f"Set {changed} purchase queue AUD unit-price targets")
    return after, Summary(text, {"changed": changed}, extra={"review": changes})


def _target_changes(before, after):
    from .orders import queue_key
    old = {queue_key(row): row for row in rows_of(before)}
    return [(number, row) for number, row in enumerate(rows_of(after), 1)
            if row[watchlist_targets.FIELD] != old.get(queue_key(row), {}).get(watchlist_targets.FIELD, "")]


def guard_cli(operation, before):
    """Keep legacy CLI writes, adding CAS/source review only when a market target changes."""
    after, _ = operation.run(before)
    changed = _target_changes(before, after)
    if not changed:
        return operation
    source = shop_reference_source.context(fresh=True)
    receipts = [{"row": number, "receipt": shop_reference_source.receipt(row, source)} for number, row in changed]
    return Op("watchlist.target_edit", {"expect": before.revision, "kind": operation.kind,
                                       "params": dict(operation.params), "receipts": receipts})


@register("watchlist.target_edit")
def apply_cli(inv, *, expect, kind, params, receipts):
    if inv.revision != expect or kind not in ("watchlist.set", "watchlist.replace"):
        raise Conflict(CHANGED)
    after, summary = Op(kind, params).run(inv)
    source = shop_reference_source.context(fresh=True)
    current = [{"row": number, "receipt": shop_reference_source.receipt(row, source)}
               for number, row in _target_changes(inv, after)]
    if current != receipts:
        raise Conflict(SOURCE_CHANGED)
    return after, summary
