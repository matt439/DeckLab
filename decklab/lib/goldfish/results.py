"""The goldfish package's results: a run's integer counts become the
JSON-safe result for one setup (_summary), and headline() picks the few
numbers a deck list shows.
"""
from decklab.lib import stats

from .common import (ALWAYS_KEEP, BIG_SPELL, COLOUR_TURNS, FLOOD_FROM_TURN, FLOOD_GAME_TURNS, MISSED_DROP_TURNS,
                     SETUPS, STUCK_TURNS, _colours_text)

SHARE_DIGITS = 6            # chances are rounded to this many places (1 game in 1,000,000)


def _share(n, d, digits=SHARE_DIGITS):
    """n / d as a chance rounded to digits places, or None when d is 0. A
    chance that isn't exactly 0 or 1 never rounds to 0 or 1, so the page can
    say "<0.1%" or ">99.9%" rather than a flat 0% or 100%."""
    if not d:
        return None
    share = round(n / d, digits)
    if 0 < n < d and share in (0, 1):
        share = n / d
    return share


def _average(n, d, digits):
    return round(n / d, digits) if d else None


def _summary(counts, setup, turns, E_colours, big_in_deck):
    g = counts["games"]
    kept = [{"cards": size, "share": _share(counts["kept"][size], g)}
            for size in range(7, -1, -1) if counts["kept"][size] or size >= ALWAYS_KEEP]
    last_colour = min(COLOUR_TURNS, turns)
    stuck_turns = [t for t in STUCK_TURNS if t <= turns]
    flood_turns = max(0, turns - FLOOD_FROM_TURN + 1)
    by_turn = []
    for t in range(1, turns + 1):
        by_turn.append({"turn": t, "share": _share(counts["spent"][t], counts["avail"][t]),
                        "all_used": _share(counts["all_used"][t], counts["had_mana"][t])})
    first_big = None
    if big_in_deck:
        cast = g - counts["big_never"]
        turn_sum = sum(t * counts["big"][t] for t in range(turns + 1))
        first_big = {
            "by_turn": [{"turn": t, "share": _share(counts["big"][t], g)} for t in range(1, turns + 1)],
            "never": _share(counts["big_never"], g),
            "average_turn": round(turn_sum / cast, 2) if cast else None,
            "by_turn_4": _share(sum(counts["big"][1:BIG_SPELL + 1]), g) if turns >= BIG_SPELL else None,
        }
    return {
        "id": setup, "label": SETUPS[setup]["label"],
        "mulligans": {"rate": _share(counts["mulligan"], g),
                      "free_rate": _share(counts["free"], g) if SETUPS[setup]["free_mulligan"] else None,
                      "kept": kept},
        "land_drops": {
            "on_time": [{"land": t, "turn": t, "chance": _share(counts["drop"][t], g)}
                        for t in range(1, turns + 1)],
            "mana": [{"turn": t, "at_least": t, "chance": _share(counts["mana"][t], g),
                      "average": _average(counts["mana_sum"][t], g, 2)} for t in range(1, turns + 1)],
        },
        "stuck": {"games": _share(counts["stuck"], g) if stuck_turns else None,
                  "turns": stuck_turns,
                  "missed_drops": _average(counts["missed"], g, 3),
                  "missed_turns": min(MISSED_DROP_TURNS, turns)},
        "flood": {"turns": _share(counts["flood_turns"], g * flood_turns) if flood_turns else None,
                  "games": _share(counts["flood_games"], g) if flood_turns else None,
                  "from_turn": FLOOD_FROM_TURN, "to_turn": turns, "game_turns": FLOOD_GAME_TURNS},
        "colours": {
            "by_turn": [{"colour": _colours_text(bit), "name": stats.COLOUR_NAMES[_colours_text(bit)],
                         "chances": [_share(counts["colour"][i][t], g) for t in range(1, last_colour + 1)]}
                        for i, bit in enumerate(E_colours)],
            "screw_turns": _share(counts["screw"], g * turns),
            "screw_wasted_turns": _share(counts["screw_wasted"], g * turns),
        },
        "mana_used": {
            "by_turn": by_turn,
            "share": _share(sum(counts["spent"]), sum(counts["avail"])),
            "all_used": _share(sum(counts["all_used"]), sum(counts["had_mana"])),
        },
        "first_big": {"min_mv": BIG_SPELL, "in_deck": big_in_deck,
                      "note": None if big_in_deck else "The deck has no spells with mana value 4 or more.",
                      **(first_big or {"by_turn": None, "never": None, "average_turn": None,
                                       "by_turn_4": None})},
    }


# ============================================================ summaries

def headline(result, setup=None):
    """The few numbers a deck list shows, for one setup: by default the
    games the deck is played in, multiplayer for a Commander deck (the
    shop's Commander nights) and on the play otherwise. Mulligan rate, 3rd
    land on turn 3, 4th land on turn 4, colour screw turns, flood turns,
    first 4-drop by turn 4."""
    if setup is None:
        setup = "multiplayer" if result["kind"] == "commander" else "play"
    r = result["results"][setup]
    drops = {d["land"]: d["chance"] for d in r["land_drops"]["on_time"]}
    return {
        "setup": setup,
        "mulligan_rate": r["mulligans"]["rate"],
        "land_3_by_3": drops.get(3),
        "land_4_by_4": drops.get(4),
        "colour_screw": r["colours"]["screw_turns"],
        "flood_turns": r["flood"]["turns"],
        "big_by_4": r["first_big"]["by_turn_4"],
    }
