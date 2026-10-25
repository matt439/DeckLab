"""Destructive order changes, with the reviewed revisions and kit owners rechecked.

The command line's inventory operations own cancellation, removal and queue
restoration. This wrapper adds the web viewer's private-kit boundary and binds
the table preview to both inventory and deck revisions inside the write lock.
"""
from dataclasses import dataclass

from decklab.lib import inventory
from decklab.lib.inventory import orders

from . import guard, products
from .common import ApiError, _keys
from .settings import _writer
from .shopping_orders import _text


@dataclass(frozen=True)
class Change:
    kind: str
    params: dict
    expected: tuple
    owners: object

    def run(self, snapshot):
        if (snapshot.revision, snapshot.decks_revision) != self.expected:
            raise inventory.Conflict("Shopping or its deck tables changed after the preview.")
        order = orders._order(snapshot, self.params["order"])
        components = order.components
        if self.kind == "order.cancel":
            components = [part for part in components if part.id == self.params["component"]]
        for component in components:
            if component.kind != "product":
                continue
            for row in snapshot.status.rows:
                if row.text("file") == component.file_name:
                    _, error = products._kit(snapshot, row, self.owners)
                    if error:
                        raise ApiError(403, error)
        return inventory.Op(self.kind, self.params).run(snapshot)


def operation(data, before):
    """Require an explicit reason and cancellation queue choice; removal restores by default."""
    action = data["action"]
    required = ("profile", "expect", "order", "action", "reason")
    if action == "cancel":
        _keys(data, (*required, "component", "restore_queue"))
        if not isinstance(data["restore_queue"], bool):
            raise ApiError(400, "Choose whether to return the recorded copies to the purchase queue.")
    else:
        _keys(data, required)
    params = {"order": _text(data["order"], "order", blank=False, limit=100),
              "reason": _text(data["reason"], "reason", blank=False, limit=2000),
              "restore_queue": data["restore_queue"] if action == "cancel" else True}
    if action == "cancel":
        params["component"] = _text(data["component"], "component", blank=False, limit=100)
    return Change(f"order.{action}", params, (before.revision, before.decks_revision),
                  guard.accessory_owners(_writer(data)))


def result(before, after, summary, operation):
    """Report queue deltas and the original record even after an order has been removed."""
    action = operation.kind.removeprefix("order.")
    details = {"action": action, "removed": action == "remove",
               "queue_restoration": (summary.extra or {}).get("queue")
                   or {"known": False, "offered": [], "restored": [], "warnings": []}}
    if action == "cancel":
        _, component = orders._component(after, operation.params["order"], operation.params["component"])
        details["component"] = {"id": component.id, "kind": component.kind, "status": component.status}
        remaining = after.order(operation.params["order"])
        details["checks"] = [{"component": part.id, "checks": list(part.checks or [])}
                             for part in remaining.components if part.status != "cancelled"]
    return details
