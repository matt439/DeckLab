"""Real games of this exact deck pair and the cards Forge actually played.

Play-record hashes include identity, printings and unused sections. Forge hashes
instead describe its executed main deck and commander. Recreate only that cheap
fingerprint from each visible historical played snapshot, never today's deck or
the base list before a sideboard plan. Observations remain separate from Forge.
"""
from datetime import date
import re

from decklab.lib import decks, inventory, spaces, state
from decklab.lib.state import pods

from . import guard, play_records
from .common import ApiError

MINIMUM_GAMES = 10
UNAVAILABLE = "The real-game comparison is unavailable. Try again later."
UNSUPPORTED = "A real-game comparison is not available for these two lists."
SHA = re.compile(r"[a-f0-9]{64}")
DAY = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")


def _status(status, reason):
    return {"status": status, "reason": reason, "minimum_games": MINIMUM_GAMES}


def _same_id(first, second, snapshot):
    def ordered(deck_id):
        return "pairing/" + "+".join(sorted(deck_id[8:].split("+"))) if deck_id.startswith("pairing/") else deck_id
    return inventory.same_deck_id(ordered(first), ordered(second), snapshot)


def _pair(sides, fmt, profile):
    """Validate already-visible Forge sides without looking up current cards."""
    if not isinstance(sides, list) or len(sides) != 2 or fmt not in ("Constructed", "Commander"):
        return None
    reads = guard.deck_reader(profile)
    for side in sides:
        if not isinstance(side, dict) or side.get("hidden") or side.get("removed"):
            return None
        try:
            play_records.check_deck_id(side.get("id"))
            _, kind, _ = spaces.split_deck_id(side["id"])
        except (ApiError, ValueError):
            return None
        if side.get("kind") != kind or not reads(side["id"]) or not isinstance(side.get("card_sha"), str) \
                or not SHA.fullmatch(side["card_sha"]):
            return None
        if kind in ("casual", "commander") and (kind == "commander") != (fmt == "Commander"):
            return None
    # Different deck identities with identical cards still have an unambiguous winner.
    # One identity against the very same fingerprint has no distinguishable orientation.
    snapshot = inventory.current()
    if _same_id(sides[0]["id"], sides[1]["id"], snapshot) \
            and sides[0]["card_sha"] == sides[1]["card_sha"]:
        return None
    return snapshot, "commander" if fmt == "Commander" else "constructed"


def _orders(played, sides, snapshot):
    """The two possible seat orientations of these exact identities, before card matching."""
    if not isinstance(played, list) or len(played) != 2 or any(
            not isinstance(side, dict) or side.get("hidden") or side.get("removed")
            or not isinstance(side.get("id"), str) for side in played):
        return []
    return [order for order in ((0, 1), (1, 0)) if all(
        _same_id(played[order[index]]["id"], sides[index]["id"], snapshot) for index in (0, 1))]


def _fingerprint(side, kind):
    from decklab.lib.forge.lists import card_sha
    if set(side["sections"]) - set(decks.SECTIONS):
        raise ValueError("Unknown recorded section")
    sections = {section: [decks.DeckLine(line["qty"], line["name"], line.get("set"),
                                         line.get("number"), line["finish"]) for line in rows]
                for section, rows in side["sections"].items()}
    return card_sha(sections, kind)


def _summary(sides, fmt, profile, script):
    pair = _pair(sides, fmt, profile)
    if pair is None:
        return _status("unsupported", UNSUPPORTED)
    snapshot, kind = pair
    records = state.store().play_list("games")
    if not isinstance(records, list):
        raise ValueError("Invalid game listing")
    wins, draws, days = [0, 0], 0, []
    for record in records:
        try:
            if pods.mode(record) != "legacy":
                continue
        except state.Invalid:
            continue
        if not isinstance(record, dict) or not play_records._sees_record("games", record, profile, script):
            continue
        # Malformed records without two readable sides cannot identify this exact pair.
        if not isinstance(record.get("sides"), list) or len(record["sides"]) != 2:
            continue
        viewed = play_records._view("games", record, profile, script)
        played = viewed["sides"]
        orders = _orders(played, sides, snapshot)
        if not orders:
            continue
        # A damaged visible candidate must not silently produce a partial or zero record.
        play_records._checked("games", record.get("id"), record)
        day = viewed["date"]
        if not isinstance(day, str) or not DAY.fullmatch(day) or date.fromisoformat(day).isoformat() != day:
            raise ValueError("Invalid recorded day")
        hashes = [_fingerprint(side, kind) for side in played]
        matches = [order for order in orders if all(hashes[order[index]] == sides[index]["card_sha"] for index in (0, 1))]
        if not matches:
            continue
        if len(matches) != 1:
            return _status("unsupported", UNSUPPORTED)
        days.append(day)
        if viewed["result"] == "draw":
            draws += 1
        else:
            winner = 0 if viewed["result"] == "a" else 1
            wins[matches[0].index(winner)] += 1
    return {"status": "ready", "games": len(days), "wins": wins, "draws": draws,
            "first_date": min(days) if days else None, "last_date": max(days) if days else None,
            "minimum_games": MINIMUM_GAMES}


def summarize(sides, fmt, *, profile=False, script=None):
    """An optional, read-only pair summary; failures never hide the Forge result.

    Only aggregate counts and dates escape. Neither unavailable nor unsupported
    claims zero games or includes stored record names, ids, players or errors.
    """
    try:
        profile = guard.viewer() if profile is False else profile
        script = guard.script() if script is None else script
        return _summary(sides, fmt, profile, script)
    except Exception:
        return _status("unavailable", UNAVAILABLE)
