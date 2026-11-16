"""Staged private collection-batch HTTP adapter; NOT registered in feature_routes.

Plain functions follow normal server same-origin/body guards when a future route
registers them. Currently only isolated tests dispatch them. No config/env flag or
normal startup path enables this module, even when the staged table exists.
"""
from contextlib import contextmanager

from decklab.db import space_members
from decklab.lib import inventory, state
from decklab.lib.inventory import batch_import
from decklab.lib.inventory.pg import PgInventory
from decklab.lib.state import pg_collection_batches as batches

from . import guard, saving
from .collection import space_param
from .common import ApiError, _keys, _parse_body, _public
from .settings import _web_actor, _writer

MAX_BODY = 278528
OWN_ONLY = "Choose who you are first. Collection batches belong only to that person."
UNCONFIRMED = ("Could not confirm this batch request. Reload the saved batch or retry with the same batch ID. "
               "Do not start a new batch to repeat this addition.")


@contextmanager
def _errors():
    try:
        yield
    except batches.MissingSchema:
        raise ApiError(503, "Resumable collection batches are not enabled on this server.",
                       code="batch_not_installed", available=False) from None
    except state.Unavailable:
        raise ApiError(503, UNCONFIRMED, code="batch_unconfirmed", retry="same_batch") from None
    except state.Conflict as error:
        raise ApiError(409, _public(error), code="batch_conflict", reload=True) from None
    except state.Invalid as error:
        if str(error) == batches.DENIED:
            raise ApiError(404, "This batch is not available.", code="batch_unavailable") from None
        if str(error) == space_members.REFUSED:
            raise ApiError(403, "This profile is no longer permitted to use collection batches.") from None
        raise ApiError(400, _public(error), code="batch_invalid") from None


def _owner(space, data=None):
    profile = guard.viewer()
    if profile is None:
        raise ApiError(403, OWN_ONLY)
    if data is not None and _writer(data)["id"] != profile["id"]:
        raise ApiError(403, "You can only change your own collection batches.")
    space = space_param(space)
    guard.require_space_write(profile, "collection.edit", space)
    return profile, space


def _backend():
    backend = inventory.backend()
    if not isinstance(backend, PgInventory):
        raise state.Unavailable("Batches require PostgreSQL.")
    return backend


def _transaction(backend, function):
    def work(connection):
        with connection.transaction(), connection.cursor() as cur:
            return function(cur)
    return backend._call(work)


def _answer(space, batch_id, row):
    return {"available": True, "draft_contract": batches.DRAFT_CONTRACT_VERSION, "space": space,
            "batch_id": batches._identity(batch_id),
            "revision": row["revision"], "status": row["status"], "draft": row["content"],
            "review": row["review"], "receipt": row["receipt"]}


def view(space=None, batch_id=None):
    """GET candidate: own recovery index or an exact private batch/receipt."""
    profile, space = _owner(space)
    with _errors():
        backend = _backend()
        if batch_id is None:
            result = _transaction(backend, lambda cur: batches.listing(cur, profile["id"], space))
            return {"available": True, "draft_contract": batches.DRAFT_CONTRACT_VERSION, "space": space, **result}
        row = _transaction(backend, lambda cur: batches.read(cur, profile["id"], space, batch_id))
        return _answer(space, batch_id, row)


def change(body):
    """POST candidate: explicit create/save/review/discard/complete; no autosave side effects.

    Each write requires profile, space, batch_id, action. Create takes draft; save
    takes expect+draft; review/discard take expect; complete takes the exact review
    object. Expect is an integer revision. Client-generated UUIDs survive retries.
    """
    data = _parse_body(body, MAX_BODY)
    action = data.get("action")
    fields = {"create": ("draft",), "save": ("expect", "draft"), "review": ("expect",),
              "discard": ("expect",), "complete": ("review",)}
    if not isinstance(action, str) or action not in fields:
        raise ApiError(400, "Choose create, save, review, discard or complete.")
    _keys(data, ("profile", "space", "batch_id", "action", *fields[action]))
    profile, space = _owner(data["space"], data)
    bid = data["batch_id"]
    with _errors():
        backend = _backend()
        if action == "complete":
            with saving.inventory_write_lock():
                _, summary = inventory.apply(batch_import.BatchImport(space, bid, data["review"]),
                                             _web_actor(profile), "Add a reviewed collection batch", refresh=False)
            return {"available": True, "draft_contract": batches.DRAFT_CONTRACT_VERSION, "space": space,
                    "batch_id": batches._identity(bid), "status": "committed", "receipt": summary.extra["collection_batch"]}
        def work(cur):
            args = (cur, profile["id"], space, bid)
            if action == "create":
                row = batches.create(*args, data["draft"])
            elif action == "save":
                row = batches.save(*args, data["expect"], data["draft"])
            elif action == "discard":
                row = batches.discard(*args, data["expect"])
            else:
                token = batches.review(*args, data["expect"])
                pending, _ = batches.claim(*args, token)
                # Validate and describe the actual merge under the same inventory lock.
                # A refusal rolls back the new review token as well.
                _, summary = batch_import.run(pending, backend.load(conn=cur.connection))
                return {"available": True, "draft_contract": batches.DRAFT_CONTRACT_VERSION, "space": space,
                        "batch_id": batches._identity(bid), "status": "reviewed", "review": token, "summary": dict(summary.counts)}
            return _answer(space, bid, row)
        return _transaction(backend, work)
