"""An optional take-along list for selected, authenticated physical home builds.

Only the existing privacy-filtered take-apart projection supplies kit and token details.
Task contexts are bounded hashes of visible reminders and the existing physical receipts;
the ordinary shared packing-tick store owns their checks, never an inventory operation.
"""
import hashlib
import json
import traceback

from decklab.lib import accessories
from . import common, guard

FAILED = "The take-along list couldn't be checked; the rest of the plan still works."
PLAYMATS_FAILED = "Some playmat details couldn't be checked."
PHYSICAL_REQUIRED = "Choose each deck's built list to use its take-along list."


def _key(value):
    data = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def _kit_lines(kit):
    if kit is None:
        return ["Sleeves and deck box details are unavailable in this view."]
    out = []
    for field, title in (("deck_box", "Deck box"), ("sleeves", "Sleeves")):
        ref = kit.get(field)
        if ref is None:
            words = "Not recorded"
        elif ref.get("state") == "linked":
            words = ref["label"]
        elif ref.get("state") == "text":
            words = ref["value"]
        else:
            words = "Check the saved record"
        out.append(f"{title}: {words}")
    return out


def _token_words(row):
    name = row["front"] + (f" / {row['back']}" if row.get("back") else "")
    printing = f" ({row['set'].upper()}) {row['number']}" if row.get("set") else ""
    return f"{row['quantity']} {name}{printing}"


def _deck_row(deck):
    physical = deck["take_apart"]
    lines = _kit_lines(physical.get("kit"))
    words = ("; ".join(_token_words(row) for row in physical["tokens"]) or "None recorded") \
        if physical["tokens_recorded"] else "Packing not recorded"
    lines.append(f"Token cards: {words}")
    receipt = [deck["id"], deck.get("rename_version", 0), physical["version"], physical["sha256"]]
    return {"task": f"take-along|deck|{deck['id']}", "context": _key([receipt, lines]),
            "title": deck["title"], "lines": lines, "receipt": receipt}


def _playmats(inv, profile):
    """Own/shared reminders only; another owner's Public kit isn't suggested to take."""
    owners = guard.accessory_owners(profile)
    members = accessories.member_owners() if owners is None else frozenset()
    rows = [] if inv is None else inv.rows_by_id.values()
    shown = sorted((row for row in rows if row["kind"] == "playmat" and row["quantity"] > 0
                    and accessories.visible(row["owner"], owners) and row["owner"] not in members),
                   key=accessories._sort_key)
    # Global parse diagnostics can concern another owner's private row. Absence here never
    # claims no playmats are owned, so omit unreadable rows without exposing those diagnostics.
    return [accessories.label(row) for row in shown], PLAYMATS_FAILED if inv is None else None


def project(plan, inv, profile=False):
    """None outside an all-built ordinary home selection; otherwise a safe optional list or reason."""
    decks = plan.get("decks") or []
    if not decks or any(deck.get("completion", {}).get("status") != "built"
                        or not deck["id"].startswith(("casual/", "commander/")) for deck in decks):
        return None
    if any(not deck["completion"].get("already_built") for deck in decks):
        return {"available": False, "reason": PHYSICAL_REQUIRED}
    if any(not (deck.get("take_apart") or {}).get("available") for deck in decks):
        return {"available": False, "reason": FAILED}
    try:
        deck_rows = [_deck_row(deck) for deck in decks]
        receipts = {deck["id"]: row.pop("receipt") for deck, row in zip(decks, deck_rows)}
        summary = plan.get("counters") or {}
        counter_rows = []
        for need in summary.get("needs", []):
            lines = ["Used by " + ", ".join(source["title"] + (" (sideboard only)" if source.get("sideboard_only") else "")
                                           for source in need["decks"])]
            if need.get("cover", {}).get("words"):
                lines.append(need["cover"]["words"])
            sources = sorted((receipts[source["id"]] for source in need["decks"]), key=lambda item: item[0])
            counter_rows.append({"task": f"take-along|counter|{need['key']}",
                                 "context": _key([need["key"], sources, lines]), "title": need["name"], "lines": lines})
        playmats, playmats_error = _playmats(inv, profile)
        return {"available": True, "decks": deck_rows, "counters": counter_rows,
                "counter_note": summary.get("note"), "counter_error": summary.get("error"),
                "playmats": playmats, "playmats_error": playmats_error}
    except Exception:
        common._log("The take-along list couldn't be worked out:\n" + traceback.format_exc())
        return {"available": False, "reason": FAILED}
