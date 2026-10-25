"""Old deck links resolve on reads; writes require the current exact identity.

Source paths, captured games and saved simulation provenance keep the id they
originally named. These helpers decorate responses only after normal visibility
checks and refuse an alias write before it can turn into a canonical save.
"""
from decklab.lib import decks, inventory

from . import guard
from .common import ApiError


def canonical_id(deck_id):
    """A validated read id, with aliases resolved and visibility checked first."""
    from .library import check_deck_id
    check_deck_id(deck_id)
    guard.require_sees_deck(deck_id)
    current = inventory.resolve_deck_id(deck_id)
    if not guard.sees_deck(current):
        raise guard.no_deck(deck_id)
    return current


def metadata(answer, requested_id, deck_id=None):
    """Add canonical-link and draft-recovery metadata to an already visible read."""
    current = deck_id or answer.get("id") or answer.get("summary", {}).get("id")
    if current is None:
        return answer
    aliases = [item for item in inventory.deck_lineage(current) if item != current]
    if aliases:
        answer["aliases"] = aliases
    if requested_id in aliases:
        answer["requested_id"] = requested_id
    return answer


def reject_alias(deck_id, profile=False, *, action="deck.edit", kit=False):
    """Reject a stale write after the current deck's visibility and permission checks.

    A rename alone need not change a text hash. Never let an old editor's valid
    hash authorize a write to the new id, including a no-op metadata save.
    """
    from .library import check_deck_id
    check_deck_id(deck_id)
    if profile is False:
        profile = guard.viewer()
    guard.require_sees_deck(deck_id, profile)       # a hidden deck answers as a missing one, first
    current = inventory.resolve_deck_id(deck_id)
    if current == deck_id:
        return
    summary = decks.find_summary(current)
    if not guard.sees_deck(summary or current, profile):
        raise guard.no_deck(deck_id)
    if summary is None:
        from .history import retired_record
        target = retired_record(current)[4]
    else:
        target = summary
    guard.require(profile, action, target)
    if kit:
        guard.require_kit_choice(profile, target, {})
    raise ApiError(409, "This deck was renamed. Reload its current page before making changes.",
                   canonical_id=current, requested_id=deck_id,
                   conflict={"reason": "renamed", "canonical_id": current})


def after_refusal(deck_id, profile, *, kit=False):
    """An actionable rename refusal when the deck moved during a failed write.

    Reload independently of the request's earlier pinned snapshot. Recheck the
    current visibility and rights before disclosing the new identity. If this
    extra read is unavailable, leave the caller's original refusal intact.
    """
    try:
        snapshot = inventory.backend().load()
        with inventory.pinned(snapshot):
            reject_alias(deck_id, profile, kit=kit)
    except ApiError as error:
        return error
    except (inventory.StateError, OSError, RuntimeError, ValueError):
        return None
    return None
