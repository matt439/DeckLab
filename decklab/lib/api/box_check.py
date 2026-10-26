"""Check an ordinary home deck's physical box; only its historical date is saved.

Observed quantities and differences are transient owner-only answers. Neither a check
nor its date changes a physical reservation, intended list, collection or printing fact.
"""
from datetime import date
import hashlib
import json
import re

from decklab.lib import cards, decks, inventory, spaces
from decklab.lib.decks import assembled, boxcheck

from . import assembly_takeapart, guard
from .carddata import _require_cards
from .commits import _conflict, _deck_file, _parse_file, _stored
from .common import ApiError, _keys, _parse_body, _public
from .saving import _deck_refused, apply_op
from .settings import _writer

SHA = re.compile(r"[a-f0-9]{64}")


def _today():
    return date.today().isoformat()


def recipe_sha256(version, sections):
    """Bind row indices to these exact canonical names, roles, quantities and section order."""
    value = json.dumps({"version": version, "sections": sections}, ensure_ascii=False,
                       sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def project(deck, stored, checklist, profile=False):
    """Build-decks metadata after its existing physical-content and inventory guards."""
    if deck is None or stored is None or deck.space != spaces.HOME or deck.kind not in decks.KINDS or deck.status != "built":
        return None
    profile = guard.viewer() if profile is False else profile
    if not guard.sees_home_records(profile) or not guard.sees_deck(deck, profile):
        return None
    available = checklist is not None and checklist.get("available") is True
    editable = available and guard.allowed(profile, "deck.edit", deck)
    reason = (checklist.get("reason") if checklist else None) if not available else None
    return {"expect": stored.sha256, "checked_on": boxcheck.checked_on(deck), "editable": bool(editable),
            "why_not": reason or (None if editable else "You cannot record a box check for this deck."),
            "recipe_sha256": recipe_sha256(checklist["version"], checklist["sections"]) if available else None}


def _exact_name(name):
    try:
        exact = assembly_takeapart._name(name)
    except (*cards.INDEX_ERRORS, decks.DeckFileError):
        raise ValueError("Extra cards need exact recognized card names; check the name before recording them.") from None
    if exact != name:
        raise ValueError("Use the card's exact name for extra cards; check capitalization and the full card name.")
    return exact


def save_box_check(body):
    """POST /api/deck/box-check {profile,id,expect,recipe_sha256,rows,extras}.

    rows enumerate every server-derived physical section row exactly once, with the
    observed quantity. extras name additional cards explicitly. Both original text and
    canonical recipe receipts must match before row indices are interpreted. One normal
    deck.save writes only Box checked; quantities never enter text or the audit message.
    """
    data = _parse_body(body)
    profile = _writer(data)
    _keys(data, ("profile", "id", "expect", "recipe_sha256", "rows", "extras"))
    kind, slug, path = _deck_file(data["id"])
    stored = _stored(data["id"], viewer=profile)
    guard.require_sees_home_records(profile)
    if stored.space != spaces.HOME:
        raise ApiError(403, "Box checks are for the home decks.")
    deck = _parse_file(stored.data, kind, slug, path, stored.id)
    guard.require(profile, "deck.edit", deck)
    if not isinstance(data["expect"], str) or not SHA.fullmatch(data["expect"]):
        raise ApiError(400, "expect must be the full deck hash from the physical checklist")
    if data["expect"] != stored.sha256:
        raise _conflict(stored.id, deck.title, viewer=profile)
    if deck.status != "built":
        raise ApiError(400, "Only a built deck has a physical box to check.")
    _require_cards()
    try:
        assembled.get(deck)
        assembled.generation(deck)
        decks.token_cards(deck)  # Match the existing take-apart checklist's physical-metadata validity.
        version = assembled.version(deck)
        sections = assembly_takeapart._physical_rows(deck, assembled.sections(deck), version)
    except (ValueError, decks.DeckFileError) as error:
        raise ApiError(409, "The saved physical build cannot be checked: " + _public(error)) from None
    except cards.INDEX_ERRORS:
        raise ApiError(503, "The local card data cannot be checked. Try again when it is ready.") from None
    recipe = recipe_sha256(version, sections)
    if not isinstance(data["recipe_sha256"], str) or not SHA.fullmatch(data["recipe_sha256"]):
        raise ApiError(400, "recipe_sha256 must be the physical recipe hash from the checklist")
    if data["recipe_sha256"] != recipe:
        raise ApiError(409, "The physical checklist changed. Refresh the plan before saving this box check.")
    try:
        result = boxcheck.compare(sections, data["rows"], data["extras"], canonical_name=_exact_name)
        checked_on = _today()
        boxcheck.record_date(deck, checked_on)
        text = decks.render_deck_file(deck)
    except (ValueError, decks.DeckFileError) as error:
        raise ApiError(400, _public(error)) from None
    # A same-day check still verifies its original SHA under the normal write lock.
    # An unchanged deck.save creates neither a row change nor another audit/revision.
    op = inventory.Op("deck.save", {"deck_id": stored.id, "text": text, "base_sha256": stored.sha256})
    after, summary = apply_op(op, profile, f"Record a box check for {deck.title}", _deck_refused(stored.id, deck.title, profile))
    held = after.deck(stored.id)
    return {"saved": bool(summary.changed), "id": stored.id, "revision": held.revision, "sha256": held.sha256,
            "checked_on": checked_on, "recipe_sha256": recipe, **result}
