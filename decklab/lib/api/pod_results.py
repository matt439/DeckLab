"""Pure roll-up of already-visible pod records for one unambiguous deck seat.

Draws are reported apart from the decided-game denominator. Each decided table contributes
1 / seat-count to the fair-share baseline. No record, inventory, card or privacy reader runs
here: the caller supplies its existing projection and pinned alias matcher.
"""
from collections import Counter
import re

from decklab.lib.forge.cardstats import wilson
from .play_comparison import MINIMUM_GAMES

ID = re.compile(r"[a-f0-9]{32}\Z")
SEAT = re.compile(r"s[1-4]\Z")


def summarise(entries, matches, own_space=None):
    wins = decided = draws = excluded = 0
    fair = 0.0
    seen, labels, spellings = set(), Counter(), {}
    for entry in entries:
        record = entry.get("record") if isinstance(entry, dict) else None
        if (not isinstance(record, dict) or record.get("mode") != "pod" or type(record.get("game_version")) is not int
                or record["game_version"] != 2
                or not isinstance(record.get("id"), str) or not ID.fullmatch(record["id"]) or record["id"] in seen):
            continue
        seats = record.get("seats")
        if (not isinstance(seats, list) or len(seats) not in (3, 4)
                or any(not isinstance(seat, dict) or seat.get("type") not in ("deck", "external") or not isinstance(seat.get("seat_id"), str)
                       or not SEAT.fullmatch(seat["seat_id"]) for seat in seats)
                or len({seat["seat_id"] for seat in seats}) != len(seats)):
            continue
        target, unresolved = [], False
        for seat in seats:
            deck = seat.get("deck")
            if seat.get("type") != "deck":
                continue
            if isinstance(deck, dict) and (deck.get("hidden") or deck.get("removed")):
                continue
            if not isinstance(deck, dict) or not isinstance(deck.get("id"), str):
                unresolved = True
                continue
            try:
                if matches(deck["id"]):
                    target.append(seat["seat_id"])
            except (TypeError, ValueError):
                unresolved = True
        if not target:
            continue
        seen.add(record["id"])
        result = record.get("result")
        if unresolved or len(target) != 1 or not isinstance(result, str) or result not in {"draw", *(seat["seat_id"] for seat in seats)}:
            excluded += 1
            continue
        if result == "draw":
            draws += 1
            continue
        decided += 1
        fair += 1 / len(seats)
        if result == target[0]:
            wins += 1
        elif own_space is not None and record.get("space") == own_space:
            winner = next(seat for seat in seats if seat["seat_id"] == result)
            label = winner.get("commander")
            if winner.get("type") == "external" and isinstance(label, str) and 0 < len(label.strip()) <= 300:
                key = label.strip().casefold()
                spellings.setdefault(key, label.strip())
                labels[key] += 1
    if decided < MINIMUM_GAMES:
        return {"status": "insufficient", "minimum_games": MINIMUM_GAMES}
    low, high = wilson(wins, decided)
    return {"status": "ready", "minimum_games": MINIMUM_GAMES, "wins": wins, "decided": decided,
            "draws": draws, "fair_share": fair / decided, "range": {"low": low, "high": high},
            "excluded": excluded,
            "outside_winners": [{"commander": spellings[key], "wins": labels[key]}
                                for key in sorted(labels, key=lambda key: (-labels[key], key))[:3]]}
