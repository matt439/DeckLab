"""Correct an ordinary home built deck's recorded physical build from a reviewed box check.

A preview shows the corrected build, the real cards it frees for other decks or newly
holds (with any the collection can't cover), and the packed token cards, which stay as
written. Confirming saves the corrected Assembled snapshot, installed stand-ins and the
check date in one revision-checked deck save, bound to the previewed result.
Intended lists, the collection, kit and packed token cards are never changed here.
"""
from decklab.lib import cards, decks, inventory, tokens
from decklab.lib.decks import assembled, boxcheck, boxrepair

from . import assembly_takeapart, box_check
from .box_check import SHA, checked, physical, recipe_sha256
from .common import ApiError, _flag, _keys, _parse_body, _public
from .library import _load_pool
from .saving import _deck_refused, _stale_after, apply_op
from .settings import _writer


def _counts(counter):
    return [{"name": name, "quantity": quantity} for name, quantity in sorted(counter.items(), key=lambda i: (i[0].casefold(), i[0]))]


def _held(deck_id, held, after):
    """Each newly held card with what the pool records: owned (on the way included) and held elsewhere."""
    warnings = []
    p = _load_pool(warnings)
    answer = []
    for name, quantity in sorted(held.items(), key=lambda i: (i[0].casefold(), i[0])):
        row = {"name": name, "quantity": quantity, "owned": None, "elsewhere": None, "short": None}
        if p is not None:
            owned = p.owned.get(name, 0)
            elsewhere = sum(holder.cards.get(name, 0) for holder in p.in_use if holder.id != deck_id)
            here = sum(r["quantity"] for rows in after.values() for r in rows if r["name"] == name)
            row.update(owned=owned, elsewhere=elsewhere, short=max(0, elsewhere + here - owned))
        answer.append(row)
    return answer, p is None


def _token_names(sections):
    try:
        return {need["name"] for need in tokens.deck_tokens(sections, inv=tokens.read(), incoming_rows=[])["needs"]}
    except (RuntimeError, ValueError, OSError, *cards.INDEX_ERRORS):
        return None


def _tokens(deck, before, after):
    packed = decks.token_cards(deck)
    old, new = _token_names(before), _token_names(after)
    return {"recorded": decks.has_token_cards(deck), "cards": [line.text() for line in packed],
            "no_longer_made": sorted(old - new) if old is not None and new is not None else [],
            "newly_made": sorted(new - old) if old is not None and new is not None else []}


def repair_box(body):
    """POST /api/deck/box-repair {profile,id,expect,recipe_sha256,rows,extras,confirm?,result_sha256?}.

    Without confirm: a preview, writing nothing. With confirm, result_sha256 must be the
    preview's: the recipe hash of the corrected physical rows. One deck.save writes the
    corrected build and Box checked; other decks whose tables are now out of date are
    returned as stale_tables."""
    data = _parse_body(body)
    profile = _writer(data)
    _keys(data, ("profile", "id", "expect", "recipe_sha256", "rows", "extras"), ("confirm", "result_sha256"))
    confirm = _flag(data, "confirm")
    stored, deck, version, before, recipe, result = checked(data, profile)
    if not result["missing"] and not result["extra"]:
        raise ApiError(400, "The box matches its recorded build: there is nothing to correct.")
    logical_before = assembled.sections(deck)
    # compare() accepted only exact names for extras, so data["extras"] is canonical already.
    try:
        changed = boxrepair.repair(deck, before, data["rows"], data["extras"], canonical=assembly_takeapart._name,
                                   rederive=lambda d: physical(d)[1])
        _, after = physical(deck)
    except boxrepair.BoxRepairError as error:
        raise ApiError(400, str(error)) from None
    except (ValueError, decks.DeckFileError) as error:
        raise ApiError(400, "The corrected build can't be recorded: " + _public(error)) from None
    except cards.INDEX_ERRORS:
        raise ApiError(503, "The local card data cannot be checked. Try again when it is ready.") from None
    if not changed:
        raise ApiError(400, "The box matches its recorded build: there is nothing to correct.")
    outcome = recipe_sha256(version, after)
    freed, held = boxrepair.reservations(before, after)
    if not confirm:
        held_rows, unknown = _held(stored.id, held, after)
        return {"preview": True, "id": stored.id, "version": version, "recipe_sha256": recipe,
                "result_sha256": outcome, "sections": after,
                "card_count": sum(r["quantity"] for rows in after.values() for r in rows),
                "freed": _counts(freed), "held": held_rows, "pool_unknown": unknown,
                "tokens": _tokens(deck, logical_before, assembled.sections(deck)), **result}
    if not isinstance(data.get("result_sha256"), str) or not SHA.fullmatch(data["result_sha256"]):
        raise ApiError(400, "result_sha256 must be the corrected build hash from the preview")
    if data["result_sha256"] != outcome:
        raise ApiError(409, "The corrected build changed since its preview. Review it again before saving.")
    try:
        checked_on = box_check._box_check_today()
        boxcheck.record_date(deck, checked_on)
        text = decks.render_deck_file(deck)
    except (ValueError, decks.DeckFileError) as error:
        raise ApiError(400, _public(error)) from None
    # The corrected build is this save's whole purpose, so it may change the physical recipe.
    op = inventory.Op("deck.save", {"deck_id": stored.id, "text": text, "base_sha256": stored.sha256,
                                    "allow_assembled": True})
    after_inv, _ = apply_op(op, profile, f"Correct the recorded box for {deck.title}",
                            _deck_refused(stored.id, deck.title, profile))
    held_record = after_inv.deck(stored.id)
    stale = _stale_after({stored.id}, [])
    return {"saved": True, "id": stored.id, "revision": held_record.revision, "sha256": held_record.sha256,
            "checked_on": checked_on, "recipe_sha256": recipe, "result_sha256": outcome,
            "freed": _counts(freed), "held": _counts(held), "stale_tables": stale, **result}
