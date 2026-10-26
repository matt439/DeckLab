"""Narrow compatibility for old inventory goldens and additive packing metadata.

The old physical counts, steps, holders, kit and token results still compare.
Dedicated product-source, take-apart and product-token tests cover the new UI
projections. Only an unrecorded product's clean default picker is omitted;
written token records and malformed metadata remain evidence in comparisons.
Product status receipts changed when the canonical status sheet gained a blank
token_cards column, so only valid hashes on actual product summaries are omitted.
"""
import copy
import re

SHA = re.compile(r"[0-9a-f]{64}")
PRODUCT_SOURCE = re.compile(r"magic/products/([a-z0-9]+(?:-[a-z0-9]+)*)\.csv")
PICKER_KEYS = {"tokens_sha256", "expect", "product", "editable", "written", "lines", "choices"}
CHOICE_KEYS = {"row", "front", "back", "set", "number", "quantity", "free", "packed"}


def _hash(value):
    return isinstance(value, str) and SHA.fullmatch(value) is not None


def _product(summary):
    if not isinstance(summary, dict) or summary.get("read_only") is not True:
        return None
    source = summary.get("source")
    match = PRODUCT_SOURCE.fullmatch(source) if isinstance(source, str) else None
    if match is None:
        return None
    stem = match[1]
    deck_id = summary.get("id")
    if isinstance(deck_id, str) and (deck_id == f"product/{stem}" or deck_id.startswith(f"product/{stem}/")):
        return stem
    return None


def _default_picker(packed, stem, receipt):
    if (not isinstance(packed, dict) or set(packed) != PICKER_KEYS or packed["written"] is not False
            or packed["lines"] != [] or type(packed["editable"]) is not bool
            or not _hash(receipt) or packed["expect"] != receipt or not isinstance(packed["choices"], list)
            or not (packed["tokens_sha256"] is None or _hash(packed["tokens_sha256"]))
            or packed["product"] != {"stem": stem, "status_sha256": packed["expect"]}):
        return False
    seen = set()
    for choice in packed["choices"]:
        if (not isinstance(choice, dict) or set(choice) != CHOICE_KEYS
                or not all(type(choice[k]) is int for k in ("row", "quantity", "free", "packed"))
                or choice["row"] < 0 or choice["row"] in seen or choice["quantity"] < 1
                or not 0 <= choice["free"] <= choice["quantity"] or choice["packed"] != 0
                or not all(isinstance(choice[k], str) for k in ("front", "back", "set", "number"))
                or not choice["front"]):
            return False
        seen.add(choice["row"])
    return True


def normalise(dump):
    out = copy.deepcopy(dump)
    for mine in [out, *((out.get("by_viewer") or {}).values())]:
        if not isinstance(mine, dict):
            continue
        for plan in (mine.get("assembly") or {}).values():
            if not isinstance(plan, dict):
                continue
            for deck in plan.get("decks", []):
                if isinstance(deck, dict):
                    deck.pop("take_apart", None)
            for row in plan.get("rows", []):
                if isinstance(row, dict):
                    for holder in row.get("held_elsewhere", []):
                        if isinstance(holder, dict):
                            holder.pop("intact_product", None)
        for view in (mine.get("deck_view") or {}).values():
            if not isinstance(view, dict):
                continue
            summary = view.get("summary")
            stem = _product(summary)
            if stem is None:
                continue
            receipt = summary.get("holder_sha256")
            if _hash(receipt):
                summary.pop("holder_sha256")
            token_info = view.get("tokens")
            if isinstance(token_info, dict) and _default_picker(token_info.get("packed"), stem, receipt):
                token_info.pop("packed")
    return out
