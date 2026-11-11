"""Read-only counter and dice reminders, covered once across the selected home decks.

Nothing here creates a packing task, reservation or completion requirement. The assembly
routes check home's inventory permission before reading these sources.
"""
from dataclasses import dataclass
import traceback

from decklab.lib import cards, inventory
from decklab.lib.tokens import counters, dice_cover
from . import common

FAILED = "Counters and dice couldn't be checked; the rest of the plan still works."
NOTE = "An estimate of kinds only. Coverage is checked across all chosen decks together."


@dataclass(frozen=True)
class Sources:
    rows: tuple = ()
    ready: bool = False
    failed: bool = False


def read_sources():
    """Home's dice rows from this request's snapshot; a failure never means none owned."""
    try:
        snapshot = inventory.current()
        sheet = snapshot.dice_set()
        if sheet.error is not None:
            raise ValueError("The dice and counters list couldn't be read")
        return Sources(tuple(row.as_dict() for row in sheet.rows), snapshot.dice_ready)
    except Exception:
        common._log("The assembly plan's dice and counters couldn't be read:\n" + traceback.format_exc())
        return Sources(failed=True)


def summary(participants, sources):
    """Unique kinds with their selected deck sources and one plan-wide coverage estimate.

    A generic item covers one kind across the plan, including when several decks use that
    kind. Changing the selection order never changes which kinds receive generic cover.
    """
    needs = {}
    try:
        incomplete = False
        for item in participants:
            token_result = item.get("tokens") or {}
            estimate = token_result.get("counters")
            if token_result.get("error") or token_result.get("unavailable") or not isinstance(estimate, dict):
                incomplete = True
                continue
            for need in estimate.get("needs", []):
                key = need["key"]
                merged = needs.setdefault(key, {"key": key, "name": need["name"], "group": need["group"],
                                                "decks": []})
                merged["decks"].append({"id": item["id"], "title": item["title"],
                                         "sideboard_only": bool(need.get("sideboard_only"))})
        ordered = sorted(needs.values(), key=lambda n: (counters.GROUPS.index(n["group"]),
                         n["key"][:1] not in "+-", int(n["key"][1:]) if n["group"] == "die" else 0,
                         cards.fold(n["name"])))
        result = {"needs": ordered, "note": NOTE, "details": counters.NOTE}
        if sources.failed or incomplete:
            return dict(result, error=FAILED)
        return dice_cover.cover(result, sources.rows, sources.ready)
    except Exception:
        common._log("The assembly plan's counters and dice couldn't be worked out:\n" + traceback.format_exc())
        return {"needs": [], "error": FAILED}
