"""Guarded retirement and exact restoration of unbuilt saved decks.

Retirement uses deck.delete; restoration uses deck.create, so the database keeps
the same id's complete A/M/D history and existing matchup identities.
"""
import re
from urllib.parse import quote

from decklab.lib import inventory, permissions
from decklab.lib.inventory import ops_decks

from . import deck_aliases, guard, history
from .commits import _deck_file
from .common import ApiError, _CONTROL_RE, _keys, _parse_body
from .saving import _refused, inventory_write_lock
from .settings import _web_actor, _writer

_SHA = re.compile(r"[0-9a-f]{64}")
NO_HISTORY = "Retirement needs saved revision history so this deck can be restored."


def _physical(parsed):
    if parsed.status == "built":
        return "Take this deck apart before retiring or restoring it."
    if any(ops_decks.kit_of(parsed)):
        return "Clear this deck's sleeves and deck box through its owner before retiring or restoring it."
    return None


def _current(deck_id, profile=False):
    _deck_file(deck_id)
    guard.require_sees_deck(deck_id, profile)   # before any lookup: a hidden deck answers as a missing one
    space, kind, slug, stored = history._deck(deck_id)
    parsed = history._parse(stored.data, kind, slug, space, deck_id)
    return stored, parsed


def retirement_view(deck_id=None):
    stored, parsed = _current(deck_id)
    why = permissions.reason(guard.viewer(), "deck.edit", parsed, script=guard.script())
    why = why or _physical(parsed) or (NO_HISTORY if stored.revision < 1 else None)
    return deck_aliases.metadata({"id": stored.id, "title": parsed.title, "sha256": stored.sha256,
            "revision": stored.revision, "status": parsed.status, "may_retire": why is None, "why_not": why},
            deck_id, stored.id)


def _revision(value, name):
    if type(value) is not int or not 1 <= value <= 10 ** 9:
        raise ApiError(400, f"{name} must be the saved revision number shown by Deck Lab")
    return value


class _Retire:
    kind = "deck.delete"

    def __init__(self, deck_id, sha, revision, profile):
        self.params = {"deck_id": deck_id, "base_sha256": sha, "revision": revision}
        self.profile = profile

    def run(self, inv):
        p = self.params
        held = ops_decks._current(inv, p["deck_id"], p["base_sha256"])
        parsed = ops_decks.parsed_deck(held)
        guard.require(self.profile, "deck.edit", parsed)
        if held.revision != p["revision"]:
            raise inventory.Conflict("This deck changed after the retirement confirmation was opened. Open it again.")
        why = _physical(parsed)
        if why:
            raise ApiError(409, why)
        return inventory.Op("deck.delete", {"deck_id": held.id, "base_sha256": held.sha256}).run(inv)


def _apply(operation, profile, message, reason=None, expected_revision=None):
    try:
        with inventory_write_lock():
            return inventory.apply(operation, _web_actor(profile), message, reason=reason,
                                   expected_revision=expected_revision)
    except ops_decks.DeckRefused as error:
        if error.code == 404 and error.ids:
            moved = deck_aliases.after_refusal(error.ids[0], profile)
            if moved is not None:
                raise moved from None
        raise ApiError(error.code, str(error), **(getattr(error, "extra", None) or {})) from None
    except (inventory.Invalid, inventory.Conflict, inventory.Unavailable) as error:
        raise _refused(error) from None


def retire_deck(body):
    data = _parse_body(body)
    profile = _writer(data)
    _keys(data, ("profile", "id", "sha256", "revision", "reason"))
    deck_aliases.reject_alias(data["id"], profile)
    stored, parsed = _current(data["id"], profile)
    guard.require(profile, "deck.edit", parsed)
    why = _physical(parsed)
    if why:
        raise ApiError(409, why)
    reason = data["reason"]
    if not isinstance(reason, str) or not reason.strip() or len(reason) > 1000 or _CONTROL_RE.search(reason):
        raise ApiError(400, "Give a reason for retiring this deck (up to 1000 characters).")
    if not isinstance(data["sha256"], str) or not _SHA.fullmatch(data["sha256"]):
        raise ApiError(400, "Read this deck's current sha256 before retiring it.")
    revision = _revision(data["revision"], "revision")
    if stored.revision < 1:
        raise ApiError(503, NO_HISTORY)
    if stored.sha256 != data["sha256"] or stored.revision != revision:
        from .commits import _conflict
        raise _conflict(stored.id, parsed.title, viewer=profile)
    _apply(_Retire(stored.id, stored.sha256, revision, profile), profile, f"Retire {parsed.title}", reason.strip())
    return {"retired": True, "id": stored.id, "title": parsed.title,
            "history": f"#/history?id={quote(stored.id, safe='')}"}


class _Restore:
    kind = "deck.create"

    def __init__(self, deck_id, text, before, profile):
        self.params = {"deck_id": deck_id, "text": text, "decks_revision": before.decks_revision}
        self.profile = profile

    def run(self, inv):
        p = self.params
        if inv.decks_revision != p["decks_revision"]:
            raise inventory.Conflict("Decks changed after this retirement was read. Open its history again.")
        if inv.deck(p["deck_id"]) is not None:
            raise inventory.Conflict("This deck id is already in use. Nothing was restored.")
        from decklab.lib import decks
        space, kind, slug = decks.split_id(p["deck_id"])
        parsed = decks.parse_deck(p["text"].encode("utf-8"), slug, kind, None, space)
        guard.require(self.profile, "deck.edit", parsed)
        guard.require(self.profile, "deck.create", parsed)
        why = _physical(parsed)
        if why:
            raise ApiError(409, why)
        return inventory.Op("deck.create", {"space": space, "kind": kind, "slug": slug, "text": p["text"],
                                             "owners": guard.accessory_owners(self.profile)}).run(inv)


def restore_deck(body):
    data = _parse_body(body)
    profile = _writer(data)
    _keys(data, ("profile", "id", "retired_revision"))
    deck_aliases.reject_alias(data["id"], profile)      # asks guard.sees_deck of the id first (E10-S30)
    expected = _revision(data["retired_revision"], "retired_revision")
    before = inventory.current()
    space, kind, slug, revision, parsed, retired = history.retired_record(data["id"])
    guard.require(profile, "deck.edit", parsed)
    guard.require(profile, "deck.create", parsed)
    if retired != expected:
        raise ApiError(409, "This deck's retirement changed. Open its history again before restoring it.")
    why = _physical(parsed)
    if why:
        raise ApiError(409, why)
    _apply(_Restore(data["id"], revision.text, before, profile), profile, f"Restore {parsed.title} after retirement",
           expected_revision=before.revision)
    return {"restored": True, "id": data["id"], "title": parsed.title}
