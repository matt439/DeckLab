"""A read-only whole-deck take-apart checklist from the saved physical build.

Rows count card names, never certified printing assignments. The final explicit action
uses the ordinary revision-checked deck save; reading or checking this list changes nothing.
"""
from collections import Counter
import copy
from dataclasses import replace

from decklab.lib import cards, decks, pool, spaces
from decklab.lib.decks import assembled, standins
from decklab.lib.decks.decklist import BASIC_LANDS

from . import common, guard


def _name(name):
    basic = next((basic for basic in BASIC_LANDS if cards.fold(basic) == cards.fold(name)), None)
    if basic is not None:
        return basic
    unresolved = {}
    result = pool._canonical(name, "the saved physical build", unresolved)
    if unresolved:
        raise ValueError(f"The saved physical card name {name!r} cannot be checked.")
    return result


def _physical_rows(deck, sections, version):
    canonical = {section: [replace(line, name=_name(line.name)) for line in lines]
                 for section, lines in decks.clean_sections(sections).items()}
    if not canonical.get("Deck"):
        raise ValueError("The saved physical build has no main deck.")
    if sum(field.key.casefold() == standins.STAND_INS_FIELD.casefold() for field in deck.header) > 1:
        raise ValueError("The deck has more than one Stand-ins header.")
    installed = standins.installed_for(deck)
    if installed is not None and installed["version"] != version:
        raise ValueError("The installed stand-ins belong to another physical list version.")
    mappings = [{"for": _name(row["for"]), "using": _name(row["using"]) if row["using"] else None,
                 "qty": row["qty"]} for row in (installed or {}).get("cards", [])]
    mappings = standins.validate_rows(mappings, canonical)
    real = {section: Counter() for section in canonical}
    for section, lines in canonical.items():
        for line in lines:
            real[section][line.name] += line.quantity
    markers = {section: Counter() for section in canonical}
    # Installed mappings are per name. Consume each copy once, using the same canonical section order as packing.
    for mapping in mappings:
        remaining = mapping["qty"]
        for section in decks.SECTIONS:
            count = min(remaining, real.get(section, {}).get(mapping["for"], 0))
            if count:
                real[section][mapping["for"]] -= count
                markers[section][(mapping["using"], mapping["for"])] += count
                remaining -= count
    result = {}
    for section in decks.SECTIONS:
        rows = [{"kind": "card", "name": name, "quantity": quantity,
                 "basic": decks.is_basic_land(name), "for": None}
                for name, quantity in sorted(real.get(section, {}).items()) if quantity]
        rows += [{"kind": "marker", "name": name, "quantity": quantity, "basic": None if name is None else False, "for": target}
                 for (name, target), quantity in markers.get(section, {}).items()]
        if rows:
            result[section] = rows
    return result


def project(deck, stored, kit, profile=False):
    """Optional participant.take_apart, after ordinary deck/inventory visibility checks.

    ``kit`` is only the caller's existing privacy-filtered kit projection. Never read the
    raw Sleeves/Deck box header here. A malformed physical record is explicitly unavailable;
    it cannot silently become the mutable intended list or an empty successful checklist.
    """
    if deck is None or stored is None or deck.space != spaces.HOME or deck.kind not in decks.KINDS or deck.status != "built":
        return None
    profile = guard.viewer() if profile is False else profile
    editable = guard.allowed(profile, "deck.edit", deck)
    denied = None if editable else "You cannot change this deck."
    answer = {"available": False, "reason": None, "can_take_apart": False, "why_not": denied,
              "sha256": stored.sha256, "source": None, "version": None, "sections": {}, "card_count": None,
              "tokens_recorded": None, "tokens": [], "token_count": None,
              "kit": {field: copy.deepcopy(kit.get(field)) for field in ("sleeves", "deck_box")}
              if kit is not None else None,
              "kit_reason": None if kit is not None else "The sleeves and deck box details are not available in this view."}
    try:
        snapshot = assembled.get(deck)
        assembled.generation(deck)  # An invalid history cannot authenticate the saved physical recipe.
        version = assembled.version(deck)
        sections = _physical_rows(deck, assembled.sections(deck), version)
        packed_tokens = decks.token_cards(deck)
        answer.update(available=True, can_take_apart=editable, source="assembled" if snapshot else "built-list",
                      version=version, sections=sections,
                      card_count=sum(row["quantity"] for rows in sections.values() for row in rows),
                      tokens_recorded=decks.has_token_cards(deck),
                      tokens=[{"quantity": line.quantity, "front": line.front, "back": line.back,
                               "set": line.set, "number": line.number} for line in packed_tokens],
                      token_count=sum(line.quantity for line in packed_tokens))
    except Exception as error:  # Optional guidance cannot replace or silently repair malformed assembly evidence.
        answer["reason"] = "The saved physical build cannot be checked: " + common._public(error)
        answer["why_not"] = answer["reason"]
    return answer
