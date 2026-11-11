"""Descriptive caution thresholds, not changes to win-rate estimators or run scheduling."""
from collections import Counter

STALL_SHARE = .10
MIN_GROUP_OPPONENTS = 3
MIN_GROUP_GAMES = 300       # three of the gauntlet's default100-game opponents


def stalled(games, perspective=0):
    counts = Counter()
    starts = {key: {"games": 0, "stalled": 0} for key in ("on_play", "on_draw", "unknown")}
    for game in games:
        reason = game.get("r")
        stopped = reason in ("draw", "timeout", "error")
        if stopped:
            counts[reason] += 1
        first = game.get("first")
        key = "on_play" if first == perspective else "on_draw" if first == 1-perspective else "unknown"
        starts[key]["games"] += 1
        starts[key]["stalled"] += int(stopped)
    n, count = len(games), sum(counts.values())
    found = {"games": n, "stalled": count, "share": count/n if n else None, "threshold": STALL_SHARE,
             "caution": bool(n and count/n > STALL_SHARE), **dict.fromkeys(("draw", "timeout", "error"), 0), **counts, **starts}
    found["words"] = words(found)
    return found


def words(found):
    if not found or not found.get("caution"):
        return None
    p, d, u = (found[key] for key in ("on_play", "on_draw", "unknown"))
    unknown = f"; unknown starter {u['stalled']}/{u['games']}" if u["games"] else ""
    return (f"Stalled games: {found['stalled']}/{found['games']} ({100*found['share']:.1f}%), "
            f"above the {100*found['threshold']:g}% caution threshold. "
            f"Going first {p['stalled']}/{p['games']}; going second {d['stalled']}/{d['games']}{unknown}. "
            f"Draws {found['draw']}, time limits {found['timeout']}, errors {found['error']}. Treat the figure cautiously.")


def merge_stalled(rows):
    found = {"games": 0, "stalled": 0, "draw": 0, "timeout": 0, "error": 0,
             **{key: {"games": 0, "stalled": 0} for key in ("on_play", "on_draw", "unknown")}}
    for row in rows:
        item = row.get("stalled_all")
        if not item:
            continue
        for key in ("games", "stalled", "draw", "timeout", "error"):
            found[key] += item[key]
        for key in ("on_play", "on_draw", "unknown"):
            for count in ("games", "stalled"):
                found[key][count] += item[key][count]
    found.update(share=found["stalled"]/found["games"] if found["games"] else None, threshold=STALL_SHARE)
    found["caution"] = bool(found["games"] and found["share"] > STALL_SHARE)
    found["words"] = words(found)
    return found
