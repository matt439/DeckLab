"""Identity of the saved game files compared by a paired test of a change."""


def key(record):
    """Two source rows share evidence when both point to the same base and paired files."""
    base, paired = record.get("base_key"), record.get("paired_key")
    if isinstance(base, str) and base and isinstance(paired, str) and paired:
        return base, paired
    return None


def distinct(members):
    """One member per known pair within this group. Keep unresolved entries separate."""
    seen = set()
    for record, difference in members:
        pair = key(record)
        if pair is not None:
            if pair in seen:
                continue
            seen.add(pair)
        yield record, difference


def read_summary(summary):
    """V1 looks lack a record of participating matchups at each stage, including drops.

    When any recorded pair was shared, an old stopping decision can't be recovered
    from those aggregates. The saved game files remain available for a fresh check.
    """
    if summary.get("version", 1) != 1:
        return summary
    pairs = [pair for row in summary["opponents"] if isinstance(row, dict) and (pair := key(row))]
    if len(set(pairs)) == len(pairs):
        return summary
    outcome = summary.get("outcome")
    if not summary.get("looks") and not summary.get("decision") and outcome in (None, "stopped", "error"):
        return summary
    return dict(summary, needs_recheck=True, looks=[], decision=None, games_per_opponent=0,
                outcome=outcome if outcome in ("stopped", "error") else None,
                starter_mismatch={"games": 0, "of": 0})


def recheck_covers(summary, matched):
    """A fresh check must still cover each active saved opponent, including unplayed ones."""
    def identity(row):
        return key(row) or (row["id"], row["version"], row["card_sha"])

    available = {identity(row) for row in matched if row is not None and not row.get("dropped")}
    return all(row.get("dropped") or identity(row) in available for row in summary["opponents"])
