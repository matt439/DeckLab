"""Review and atomically rename a saved deck's title and derived identity.

The preview binds the deck's bytes, revision and the library revision. The
operation repeats permissions and identity checks inside the database lock;
historical records and their old links remain part of the same lineage.
"""
from decklab.lib import decks, inventory, permissions, spaces
from decklab.lib.inventory import ops_decks, ops_rename

from . import common, guard
from .commits import _conflict, _deck_file, _stored
from .common import ApiError, _CONTROL_RE, _keys, _parse_body, _sha
from .deck_aliases import canonical_id, metadata, reject_alias
from .retirement import _revision
from .saving import _refused, inventory_write_lock
from .settings import _web_actor, _writer

CHANGED = "The decks changed after this rename was reviewed. Review the rename again."
NOTES = ["Earlier deck links, saved history and matchup results will still open this deck.",
         "The cards, build status, sleeves and deck box stay as they are.",
         "Packing-plan checks must be confirmed again after a rename."]


def _current(deck_id, profile=False, *, writing=False):
    _deck_file(deck_id)
    guard.require_sees_deck(deck_id, profile)   # first: a hidden deck answers as a missing one (E10-S30)
    if writing:
        reject_alias(deck_id, profile)
    else:
        deck_id = canonical_id(deck_id)
    guard.require_sees_deck(deck_id, profile)
    stored = _stored(deck_id, viewer=profile)
    parsed = ops_decks.parsed_deck(stored)
    if writing:
        guard.require(profile, "deck.edit", parsed)
    return stored, parsed


def rename_view(deck_id=None):
    requested = deck_id
    with common.state_errors():
        stored, parsed = _current(deck_id)
        before = inventory.current()
    why = permissions.reason(guard.viewer(), "deck.edit", parsed, script=guard.script())
    why = why or (ops_rename.MIGRATE if not before.aliases_ready else None)
    why = why or ("Renaming needs saved revision history." if stored.revision < 1 else None)
    return metadata({"id": stored.id, "title": parsed.title, "sha256": stored.sha256,
                     "revision": stored.revision, "may_rename": why is None, "why_not": why}, requested)


def _title(value):
    title = decks.clean_title(value) if isinstance(value, str) and not _CONTROL_RE.search(value) else None
    if not title or len(title) > ops_rename.MAX_TITLE:
        raise ApiError(400, f"The title must be one line of 1-{ops_rename.MAX_TITLE} characters.")
    slug = decks.title_slug(title)
    if not decks.valid_slug(slug):
        raise ApiError(400, "The title needs letters or digits for the deck's id, and cannot be a device name.")
    return title, slug


class _Rename:
    kind = "deck.rename"

    def __init__(self, stored, title, slug, profile, decks_revision=None):
        self.params = {"deck_id": stored.id, "new_slug": slug, "title": title,
                       "base_sha256": stored.sha256, "revision": stored.revision}
        self.profile = profile
        self.decks_revision = decks_revision

    def run(self, snapshot):
        with inventory.pinned(snapshot):
            reject_alias(self.params["deck_id"], self.profile)
            held = snapshot.deck(self.params["deck_id"])
            if held is None:
                raise inventory.Conflict(CHANGED)
            guard.require(self.profile, "deck.edit", ops_decks.parsed_deck(held))
            if self.decks_revision is not None and snapshot.decks_revision != self.decks_revision:
                raise inventory.Conflict(CHANGED)
            return inventory.Op(self.kind, self.params).run(snapshot)


def _refusal(error):
    if isinstance(error, ops_decks.DeckRefused):
        return ApiError(error.code, str(error), **(getattr(error, "extra", None) or {}))
    if isinstance(error, inventory.Unavailable) and str(error) == ops_rename.MIGRATE:
        return ApiError(503, ops_rename.MIGRATE, reason="migration")
    return _refused(error)


def _plan(body, *, applying=False):
    data = _parse_body(body)
    profile = _writer(data)
    keys = ("profile", "id", "title", "sha256", "revision")
    _keys(data, keys + (("new_id", "decks_revision") if applying else ()))
    with common.state_errors():
        stored, parsed = _current(data["id"], profile, writing=True)
        snapshot = inventory.current()
    sha = _sha(data["sha256"])
    revision = _revision(data["revision"], "revision")
    title, slug = _title(data["title"])
    if not snapshot.aliases_ready:
        raise ApiError(503, ops_rename.MIGRATE, reason="migration")
    if stored.revision < 1:
        raise ApiError(503, "Renaming needs saved revision history.")
    if stored.sha256 != sha or stored.revision != revision:
        raise _conflict(stored.id, parsed.title, viewer=profile)
    new_id = spaces.join_deck_id(stored.space, stored.kind, slug)
    if applying:
        if data["new_id"] != new_id:
            raise ApiError(409, "The proposed deck id changed. Review the rename again.")
        if not isinstance(data["decks_revision"], str) or not data["decks_revision"]:
            raise ApiError(400, "Review the rename before confirming it.")
        if data["decks_revision"] != snapshot.decks_revision:
            raise ApiError(409, CHANGED)
    operation = _Rename(stored, title, slug, profile, data.get("decks_revision"))
    return data, profile, stored, parsed, snapshot, title, new_id, operation


def preview_rename(body):
    data, profile, stored, parsed, snapshot, title, new_id, operation = _plan(body)
    try:
        after, _ = inventory.preview(operation)
    except (ops_decks.DeckRefused, inventory.Invalid, inventory.Conflict, inventory.Unavailable) as error:
        raise _refusal(error) from None
    changed = new_id != stored.id or after.deck(new_id).text != stored.text
    return {"id": stored.id, "old_title": parsed.title, "title": title, "new_id": new_id,
            "sha256": stored.sha256, "revision": stored.revision, "decks_revision": snapshot.decks_revision,
            "changed": changed, "notes": list(NOTES)}


def rename_deck(body):
    data, profile, stored, parsed, snapshot, title, new_id, operation = _plan(body, applying=True)
    try:
        with inventory_write_lock():
            after, summary = inventory.apply(operation, _web_actor(profile), f"Rename {parsed.title} to {title}")
    except (ops_decks.DeckRefused, inventory.Invalid, inventory.Conflict, inventory.Unavailable) as error:
        raise _refusal(error) from None
    saved = after.deck(new_id)
    return {"renamed": bool(summary.counts), "id": new_id, "previous_id": stored.id, "title": title,
            "sha256": saved.sha256, "revision": saved.revision}
