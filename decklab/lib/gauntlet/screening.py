"""Public catalogue exclusion counts, retaining unknown provenance on older catalogues."""
from collections import Counter


def summary(catalogue):
    colour, style = Counter(), Counter()
    excluded, other = 0, 0
    unknown = len(catalogue.get("excluded") or [])
    for row in catalogue.get("decks", []):
        if row.get("playable"):
            continue
        if row.get("ai_excluded") is False:
            other += 1
            continue
        if row.get("ai_excluded") is not True:
            unknown += 1
            continue
        excluded += 1
        for key in set(row.get("identity") or "C"):
            colour[key] += 1
        style[(row.get("style") or {}).get("primary") or "unknown"] += 1
    return {"ai_excluded": excluded, "other_excluded": other, "unclassified": unknown,
            "colour": dict(sorted(colour.items())), "style": dict(sorted(style.items()))}
