"""Pure validation of the separately versioned three- or four-seat game format.

The containing play-record envelope remains version 1. Only an exact pair of
content markers opts into pods; a partial or unknown pair is never an old game.
Selectors are allowed here so the API can validate before reading snapshots.
The API additionally checks the captured lists and their hashes.
"""
import re
from datetime import date

from decklab.lib import spaces

from . import Invalid

SEAT_IDS = frozenset({"s1", "s2", "s3", "s4"})
SHA256 = re.compile(r"[a-f0-9]{64}")
SNAPSHOT_KEYS = frozenset({"id", "version", "sha256", "title", "sections"})
SELECTOR_KEYS = frozenset({"id", "version", "sha256"})


def mode(content):
    """Return 'legacy' or 'pod'; malformed or unknown markers raise Invalid."""
    if not isinstance(content, dict):
        raise Invalid("A game record must be an object")
    marked = ("mode" in content, "game_version" in content)
    if not any(marked):
        return "legacy"
    if (all(marked) and content["mode"] == "pod"
            and type(content["game_version"]) is int and content["game_version"] == 2):
        return "pod"
    raise Invalid("A game record has an unknown game format")


def _text(value, label, limit, *, required=False, multiline=False):
    if not isinstance(value, str) or len(value) > limit:
        raise Invalid(f"{label} must be text of at most {limit} characters")
    try:
        value.encode("utf-8")
    except UnicodeError:
        raise Invalid(f"{label} must contain valid text") from None
    if any((ord(c) < 32 and (not multiline or c not in "\n\t")) or ord(c) == 127 for c in value):
        raise Invalid(f"{label} contains a control character")
    if required and not value.strip():
        raise Invalid(f"{label} is required")
    if not multiline and value != value.strip():
        raise Invalid(f"{label} must have no spaces around it")
    return value


def _deck_space(deck_id):
    """Validate identity syntax without looking up any configured space or deck."""
    _text(deck_id, "Deck ID", 200, required=True)
    try:
        owner, kind, rest = spaces.split_deck_id(deck_id)
    except ValueError:
        raise Invalid("A pod deck needs a valid deck ID") from None
    parts = rest.split("/")
    if len(parts) > (2 if kind == "product" else 1) or any(
            not part or part.startswith(".") or "\\" in part or ":" in part for part in parts):
        raise Invalid("A pod deck needs a valid deck ID")
    return owner


def _snapshot(value, owner):
    if (not isinstance(value, dict) or not SELECTOR_KEYS <= value.keys()
            or not value.keys() <= SNAPSHOT_KEYS):
        raise Invalid("A pod deck needs its recorded list selection")
    if _deck_space(value["id"]) != owner:
        raise Invalid("A pod's decks must belong to its recording collection")
    if value["version"] not in ("target", "owned"):
        raise Invalid("A pod deck needs a known list version")
    if not isinstance(value["sha256"], str) or not SHA256.fullmatch(value["sha256"]):
        raise Invalid("A pod deck needs its list SHA-256")
    if "title" in value:
        _text(value["title"], "Deck title", 500, required=True)
    return value["id"]


def record_deck_ids(content):
    """Validate pod identity and private seat text, returning its real deck IDs.

    External seats carry labels only and never participate in deck ownership,
    snapshots or the indexed deck IDs. No returned value changes the input.
    """
    if mode(content) != "pod":
        raise Invalid("A pod record needs its game format markers")
    if "sides" in content:
        raise Invalid("A pod record uses seats, not two-player sides")
    owner = content.get("space")
    # split_deck_id checks the same member-space syntax without reading config.
    if owner != spaces.HOME and (not isinstance(owner, str) or _deck_space(f"{owner}/commander/pod") != owner):
        raise Invalid("A pod needs its recording collection")
    _text(content.get("notes"), "Notes", 2000, multiline=True)
    played_on = content.get("date")
    if not isinstance(played_on, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", played_on):
        raise Invalid("A pod needs a date in YYYY-MM-DD form")
    try:
        date.fromisoformat(played_on)
    except ValueError:
        raise Invalid("A pod needs a valid date") from None
    seats = content.get("seats")
    if not isinstance(seats, list) or not 3 <= len(seats) <= 4:
        raise Invalid("A pod needs three or four seats")
    seen, deck_ids = set(), []
    for seat in seats:
        if not isinstance(seat, dict):
            raise Invalid("Each pod seat must be an object")
        seat_id = seat.get("seat_id")
        if not isinstance(seat_id, str) or seat_id not in SEAT_IDS or seat_id in seen:
            raise Invalid("Each pod seat needs a distinct seat ID")
        seen.add(seat_id)
        _text(seat.get("player"), "Player name", 80, required=True)
        if seat.get("type") == "deck":
            if set(seat) != {"seat_id", "type", "player", "deck"}:
                raise Invalid("A deck seat needs only its player and recorded deck")
            deck_ids.append(_snapshot(seat["deck"], owner))
        elif seat.get("type") == "external":
            if set(seat) != {"seat_id", "type", "player", "commander"}:
                raise Invalid("An external seat needs only player and commander labels")
            _text(seat["commander"], "Commander label", 300)
        else:
            raise Invalid("A pod seat needs a deck or an external player")
    if not deck_ids:
        raise Invalid("A pod needs at least one deck from its recording collection")
    result = content.get("result")
    if not isinstance(result, str) or result not in seen | {"draw"}:
        raise Invalid("Choose a pod seat as winner, or draw")
    return deck_ids
