"""A space's storage setup (E8-S25, decklab/design/storage-setting.md): its containers (a storage
box, a binder...), their capacities, sections and order, and where loose cards with no location go.

    GET /api/storage?space=   view(space): {space, revision, ready, source, storage, can_edit,
                              kinds, orders, limits}. Whoever may see the space's inventory
                              (guard.require_sees_inventory: its own people, and everyone signed
                              in once its collection is Public, read-only: Q7); anyone else the
                              collection's 403, which names no space.
    PUT /api/storage          change(body): {"profile", "space"? (home by default), "expect": the
                              revision read (0 before the space saved one), "storage": {default,
                              containers}}: storage.edit on the space (its own people, no admin
                              override, as collection.edit). The whole record is replaced after
                              checking its revision (409 with "latest" when it changed since);
                              409 with reason "migration" before migration 0028.
    POST /api/storage/preview preview(body): {"profile", "space"?, "storage"}: storage.edit as the
                              save. Writes nothing: the Collection page's Storage setup… sheet
                              (storage-setup.js) shows it before Save. {space, storage (checked),
                              now, after (each collection_locations.storage_setup's counts, for the
                              setup that applies now and the proposed one), moves: [{from, to,
                              locations}] (recorded locations whose container would change, by
                              count, never naming a row; from/to a container's name, or None for
                              "somewhere else"), counts_error}. counts_error is set (and now/after
                              hold no counts) when the collection couldn't be read.

storage is the record that applies now: the space's saved one (source "saved"), else home's
built-in storage box (source "default") or no containers (source "none"); revision is the saved
record's (0 when none). Each save is one change set ("storage.set"), shown on Activity only to the
space's own people, as "Storage setup updated" without any container's name or sections.
"""
from decklab.lib import spaces, state, storage_setting
from decklab.lib.state import space_storage as rules

from . import guard
from .collection import space_param
from .common import ApiError, _load_json, state_errors
from .settings import _web_actor

MAX_BODY = 32 * 1024


def _answer(view):
    return {**view, "can_edit": guard.allowed(guard.viewer(), "storage.edit", view["space"]),
            "kinds": list(rules.KINDS), "orders": list(rules.ORDERS),
            "limits": {"containers": rules.MAX_CONTAINERS, "sections": rules.MAX_SECTIONS,
                       "name": rules.MAX_NAME, "capacity": rules.MAX_CAPACITY}}


def _read(space):
    with state_errors():
        return storage_setting.read(space)


def view(space=None):
    """GET /api/storage[?space=<id>]."""
    space = space_param(space)
    guard.require_sees_inventory(space)
    return _answer(_read(space))


def message(space):
    """The change set's words: which space, never the containers."""
    return ("Set the home storage setup" if space == spaces.HOME
            else f"Set {spaces.get(space).name}'s storage setup")


def _body(body, fields, what):
    if isinstance(body, str):
        body = body.encode("utf-8")
    if len(body) > MAX_BODY:
        raise ApiError(413, f"The storage setup is limited to {MAX_BODY} bytes")
    data = _load_json(body, "The storage setup")
    if not isinstance(data, dict):
        raise ApiError(400, "The storage setup must be a JSON object")
    from .settings import _writer
    profile = _writer(data)
    space = space_param(data.get("space"))
    guard.require_space_write(profile, "storage.edit", space)
    if set(data) - ({"profile", "space"} | set(fields)) or any(f not in data for f in fields):
        raise ApiError(400, what)
    return data, profile, space


def _moves(space, before, after):
    """[{from, to, locations}]: how many recorded locations would change container (by name; None is
    "somewhere else"), largest first. Never names a row."""
    from decklab.lib import inventory
    names = lambda record: {c["id"]: c["name"] for c in record["containers"]}       # noqa: E731
    old, new = names(before), names(after)
    counted = {}
    for location in inventory.current().locations_of(space).values():
        if not str(location or "").strip():
            continue
        a, b = rules.match(before, location), rules.match(after, location)
        if a == b:
            continue                        # the same container (perhaps renamed), or still nowhere
        key = (old.get(a), new.get(b))
        counted[key] = counted.get(key, 0) + 1
    return [{"from": f, "to": t, "locations": n}
            for (f, t), n in sorted(counted.items(), key=lambda item: (-item[1], str(item[0])))]


def preview(body):
    """POST /api/storage/preview: what saving body's storage would change (the module docstring)."""
    data, _profile, space = _body(body, ("storage",), "The storage preview must have storage (and space), and nothing else")
    with state_errors():
        record = rules.normalize(data["storage"])
    current = storage_setting.current(space)
    proposed = {**current, "source": "saved", "storage": record}
    from . import collection_edit as ce, collection_locations as places
    from decklab.lib import inventory
    answer = {"space": space, "storage": record, "now": None, "after": None, "moves": [], "counts_error": None}
    try:
        with state_errors():
            rows, _sha = ce._view(inventory.current().collection(space))
        shown = ce._rows_json(rows)
        held = ce._storage(space, shown, ce._prices(shown))
        answer["now"] = places.storage_setup(space, shown, held, ce._picture_key, current)
        answer["after"] = places.storage_setup(space, shown, held, ce._picture_key, proposed)
        answer["moves"] = _moves(space, current["storage"], record)
    except ApiError as e:
        if e.status in (400, 403, 413):
            raise
        answer["counts_error"] = "The collection couldn't be read, so the counts aren't shown."
    return answer


def change(body):
    """PUT /api/storage: the space's whole record, after checking its revision."""
    data, profile, space = _body(body, ("expect", "storage"),
                                 "The storage request must have expect and storage (and space), and nothing else")
    try:
        with state_errors():
            expect = rules.expectation(data["expect"])
            record = rules.normalize(data["storage"])
            try:
                saved = state.store().space_storage_put(space, record, expect, _web_actor(profile), message(space))
            except state.Unavailable as e:
                if str(e) == rules.MIGRATE:
                    raise ApiError(409, rules.MIGRATE, reason="migration") from None
                raise
    except ApiError as e:
        if e.status == 409 and getattr(e, "extra", {}).get("reason") != "migration":
            raise ApiError(409, e.message, latest=_answer(_read(space))) from None
        raise
    return _answer(storage_setting._view(space, saved))
