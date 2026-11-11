"""Optional versioned round histograms. Missing/invalid data never changes existing card statistics."""
import copy

VERSION = 1
ROUNDS = 10
MAX_VALUE = 100000
MAX_BINS = 2000


def empty():
    return {"v": VERSION, "games": 0, "bad": 0, "rounds": [{}, {}]}


def _count(value):
    return type(value) is int and value >= 0


def valid(value, games=None):
    if (not isinstance(value, dict) or set(value) != {"v", "games", "bad", "rounds"}
            or type(value["v"]) is not int or value["v"] != VERSION
            or not _count(value["games"]) or not _count(value["bad"])
            or games is not None and value["games"]+value["bad"] > games
            or not isinstance(value["rounds"], list) or len(value["rounds"]) != 2):
        return False
    for side in value["rounds"]:
        if not isinstance(side, dict) or len(side) > ROUNDS:
            return False
        if any(key not in {str(i) for i in range(1, ROUNDS+1)} for key in side):
            return False
        if side and set(side) != {str(i) for i in range(1, max(map(int, side))+1)}:
            return False
        previous = value["games"]
        for key in sorted(side, key=int):
            row = side[key]
            if (not isinstance(row, dict) or set(row) != {"n", "lands", "drawn"}
                    or not _count(row["n"]) or not 0 < row["n"] <= previous):
                return False
            previous = row["n"]
            for field in ("lands", "drawn"):
                histogram = row[field]
                if not isinstance(histogram, dict) or len(histogram) > MAX_BINS:
                    return False
                if any(not isinstance(bin, str) or not bin.isascii() or not bin.isdigit() or len(bin) > 6
                       or str(int(bin)) != bin or not 0 <= int(bin) <= MAX_VALUE
                       or not _count(count) or not count for bin, count in histogram.items()):
                    return False
                if sum(histogram.values()) != row["n"]:
                    return False
    if set(value["rounds"][0]) != set(value["rounds"][1]) or any(
            row["n"] != value["rounds"][1][round]["n"] for round, row in value["rounds"][0].items()):
        return False
    return True


def merge(into, value):
    """Add known histograms; callers distinguish missing records through outer game counts."""
    if not valid(value):
        return into
    into = empty() if into is None else into
    into["games"] += value["games"]
    into["bad"] += value["bad"]
    for side in (0, 1):
        for round, row in value["rounds"][side].items():
            target = into["rounds"][side].setdefault(round, {"n": 0, "lands": {}, "drawn": {}})
            target["n"] += row["n"]
            for field in ("lands", "drawn"):
                for bin, count in row[field].items():
                    target[field][bin] = target[field].get(bin, 0)+count
    return into


def less(now, before=None):
    if not valid(now):
        return None
    before = before if valid(before) else empty()
    result = empty()
    for key in ("games", "bad"):
        result[key] = now[key]-before[key]
    if result["games"] < 0 or result["bad"] < 0:
        return None
    for side in (0, 1):
        for round, row in now["rounds"][side].items():
            old = before["rounds"][side].get(round, {"n": 0, "lands": {}, "drawn": {}})
            count = row["n"]-old["n"]
            if not count:
                continue
            target = {"n": count}
            for field in ("lands", "drawn"):
                target[field] = {bin: n-old[field].get(bin, 0) for bin, n in row[field].items() if n != old[field].get(bin, 0)}
            result["rounds"][side][round] = target
    return result if valid(result) else None


def game(rounds, side_of):
    """Only a complete pair of seat observations may contribute a round."""
    value = empty()
    if (not isinstance(rounds, dict) or set(rounds) != {1, 2}
            or set(rounds[1]) != set(rounds[2]) or {side_of(1), side_of(2)} != {0, 1}):
        return None
    keys = sorted(rounds[1])
    if keys and keys != list(range(1, max(keys)+1)):
        return None
    value["games"] = 1
    for seat in (1, 2):
        for round, (lands, drawn) in rounds[seat].items():
            if type(round) is not int or not 1 <= round <= ROUNDS or not _count(lands) or not _count(drawn):
                return None
            value["rounds"][side_of(seat)][str(round)] = {"n": 1, "lands": {str(lands): 1}, "drawn": {str(drawn): 1}}
    return value if valid(value) else None


def pooled():
    return {"games": 0, "bad": 0, "untallied": 0, "rounds": {}}


def add_side(into, record, side, games):
    if not valid(record, games):
        into["untallied"] += games
        return
    into["games"] += record["games"]
    into["bad"] += record["bad"]
    into["untallied"] += games-record["games"]-record["bad"]
    for round, row in record["rounds"][side].items():
        target = into["rounds"].setdefault(round, {"n": 0, "lands": {}, "drawn": {}})
        target["n"] += row["n"]
        for field in ("lands", "drawn"):
            for bin, count in row[field].items():
                target[field][bin] = target[field].get(bin, 0)+count


def _middle(histogram, n):
    def at(index):
        seen = 0
        for bin, count in sorted(histogram.items(), key=lambda pair: int(pair[0])):
            seen += count
            if index < seen:
                return int(bin)
        raise ValueError("Incomplete histogram")
    return (at((n-1)//2)+at(n//2))/2


def summary(value):
    out = {key: value[key] for key in ("games", "bad", "untallied")}
    rows = []
    for round in range(1, ROUNDS+1):
        recorded = value["rounds"].get(str(round))
        row = {"round": round, "games": recorded["n"] if recorded else 0}
        for field in ("lands", "drawn"):
            histogram = recorded[field] if recorded else {}
            row[field] = ({"median": _middle(histogram, recorded["n"]), "low": min(map(int, histogram)),
                           "high": max(map(int, histogram))} if histogram else None)
        rows.append(row)
    out["rounds"] = rows
    return copy.deepcopy(out)
