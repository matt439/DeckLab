"""Counts for Activity headlines, including inventory rows beyond the display cap."""


def _dict(value):
    return value if isinstance(value, dict) else {}


def _whole(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _n(count, one, many=None):
    return f"{count} {one if count == 1 else (many or one + 's')}"


def _record(row):
    return _dict(row.get("after")) or _dict(row.get("before"))


def _quantity_change(row):
    """How many copies a collection, token or watchlist row's change added (negative: removed),
    or None when a quantity can't be read."""
    before = _whole(_dict(row.get("before")).get("quantity"))
    after = _whole(_dict(row.get("after")).get("quantity"))
    if row.get("op") == "INSERT":
        return after
    if row.get("op") == "DELETE":
        return None if before is None else -before
    return None if before is None or after is None else after - before


def _copies(rows, more, noun, where, one_name, past=None):
    """A phrase for collection, token or watchlist rows: what was added, removed or changed.
    where: (to, from, in) words such as ("to the collection", "from the collection", "in the
    collection"), each "" for none. more: whether the change has rows past the cap; past: what
    those of this table did ({"added", "removed", "unknown"}, the store's "past"; {} for none),
    or None when the store didn't say, so the copies counted are "at least" so many."""
    to, from_, in_ = where
    if past is not None:
        more = bool(past)               # this table's own rows past the cap, if any

    def tail(words):
        return f" {words}" if words else ""

    if len(rows) == 1 and not more:
        row = rows[0]
        delta = _quantity_change(row)
        name = one_name(_record(row))
        if row.get("op") == "INSERT":
            return f"added {delta} × {name}{tail(to)}" if delta and delta > 1 else f"added {name}{tail(to)}"
        if row.get("op") == "DELETE":
            return f"removed {name}{tail(from_)}"
        if delta and delta > 0:
            return f"added {_n(delta, 'more copy', 'more copies')} of {name}{tail(to)}"
        if delta and delta < 0:
            return f"removed {_n(-delta, 'copy', 'copies')} of {name}{tail(from_)}"
        return f"changed {name}{tail(in_)}"
    added = removed = 0
    unknown = False
    for row in rows:
        delta = _quantity_change(row)
        if delta is None:
            unknown = unknown or row.get("op") != "UPDATE"
        elif delta > 0:
            added += delta
        else:
            removed -= delta
    if past:                            # the store counted them: the totals are exact
        added += past.get("added") or 0
        removed += past.get("removed") or 0
        unknown = unknown or bool(past.get("unknown"))
        more = False
    at_least = "at least " if more or unknown else ""
    if added and not removed:
        return f"added {at_least}{_n(added, noun)}{tail(to)}"
    if removed and not added:
        return f"removed {at_least}{_n(removed, noun)}{tail(from_)}"
    if added and removed:
        return f"added {added} and removed {_n(removed, noun)}{tail(in_)}"
    return f"changed {_n(len(rows), noun)}{tail(in_)}"
