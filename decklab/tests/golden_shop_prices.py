"""One additive absent-check default in authorized synthetic home deck readers.

The caller has already copied its golden dump. Real saved price facts and every
other path remain evidence; this helper never captures or reads a shop cache.
"""
import re

ABSENT_MISSING_SNAPSHOT = {
    "shop": "MTGMate", "scope": "nonfoil", "status": "not_checked", "fetched_at": None,
    "price_aud": None, "stock": None, "set": None, "collector_number": None, "finish": None,
    "url": None, "in_stock_printings": 0, "error": None,
    "back_in_stock": False, "newly_in_stock": False, "carried": False,
}
# Every snapshot shop's absent default, in order (E5-S08's second shop, 2026-10-31).
ABSENT_MISSING_SNAPSHOTS = [ABSENT_MISSING_SNAPSHOT, {**ABSENT_MISSING_SNAPSHOT, "shop": "Games Portal"}]


def _home_selector(value):
    if not isinstance(value, str) or value.count("@") != 1:
        return False
    deck_id, version = value.rsplit("@", 1)
    if version not in ("target", "owned") or not 3 <= len(deck_id) <= 200:
        return False
    parts = deck_id.split("/")
    if parts[0] not in ("casual", "commander", "product", "pairing"):
        return False
    if not 2 <= len(parts) <= (3 if parts[0] == "product" else 2):
        return False
    try:
        value.encode("utf-8")
    except UnicodeError:
        return False
    return all(part and part == part.strip() and not part.startswith(".")
               and not re.search(r"[\\:\x00-\x1f\x7f]", part) for part in parts[1:])


def _absent(value, default=ABSENT_MISSING_SNAPSHOT):
    return (type(value) is dict and value.keys() == default.keys()
            and all(type(value[key]) is type(expected) and value[key] == expected
                    for key, expected in default.items()))


def _all_absent(value):
    return (type(value) is list and len(value) == len(ABSENT_MISSING_SNAPSHOTS)
            and all(_absent(item, default) for item, default in zip(value, ABSENT_MISSING_SNAPSHOTS)))


def _deck_views(mine):
    if not isinstance(mine, dict) or not isinstance(mine.get("deck_view"), dict):
        return
    for selector, answer in mine["deck_view"].items():
        if not _home_selector(selector) or not isinstance(answer, dict):
            continue
        deck_id, version = selector.rsplit("@", 1)
        if "summary" in answer:
            summary = answer["summary"]
            if (not isinstance(summary, dict) or summary.get("id") != deck_id
                    or "space" in summary and summary["space"] != "home"):
                continue
        if "version" in answer and answer["version"] != version:
            continue
        owned = answer.get("owned")
        rows = owned.get("rows") if isinstance(owned, dict) else None
        for row in rows if isinstance(rows, list) else ():
            if (isinstance(row, dict) and type(row.get("missing")) is int and row["missing"] > 0
                    and _absent(row.get("shop_snapshot")) and _all_absent(row.get("shop_snapshots", ABSENT_MISSING_SNAPSHOTS))):
                row.pop("shop_snapshot")
                row.pop("shop_snapshots", None)


def normalise(dump, profiles):
    """Strip only the exact absent default in this copied fixture's authorized home views."""
    _deck_views(dump)  # top-level reader is the fixture's raw script
    viewers = dump.get("by_viewer") if isinstance(dump, dict) else None
    if not isinstance(viewers, dict):
        return
    profiles = profiles if isinstance(profiles, dict) else {}
    for viewer, mine in viewers.items():
        profile = profiles.get(viewer)
        if (viewer == "(local)" or isinstance(viewer, str) and isinstance(profile, dict) and profile.get("id") == viewer
                and profile.get("space") == "home"):
            _deck_views(mine)
