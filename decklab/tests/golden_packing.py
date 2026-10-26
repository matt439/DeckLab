"""Narrow compatibility for old inventory goldens and additive packing metadata.

The old physical counts, steps, holders, kit and token results still compare.
Dedicated product-source, take-apart and product-token tests cover the new UI
projections. Only an unrecorded product's clean default picker is omitted;
written token records and malformed metadata remain evidence in comparisons.
Product status receipts changed when the canonical status sheet gained a blank
token_cards column, so only valid hashes on actual product summaries are omitted.
Default box-check receipts must match the physical checklist before omission;
their representative art is restricted to those physical names. Only a null
historical date on an ordinary home deck page is omitted. Written dates,
malformed metadata and existing packing counts/differences remain comparable.
At the Library index, only a clean null check date on a readable ordinary home
built summary is omitted, for the fixture's home viewers and top-level script.
"""
import copy
import hashlib
import json
import math
import re

SHA = re.compile(r"[0-9a-f]{64}")
PRODUCT_SOURCE = re.compile(r"magic/products/([a-z0-9]+(?:-[a-z0-9]+)*)\.csv")
PICKER_KEYS = {"tokens_sha256", "expect", "product", "editable", "written", "lines", "choices"}
CHOICE_KEYS = {"row", "front", "back", "set", "number", "quantity", "free", "packed"}
BOX_KEYS = {"expect", "checked_on", "editable", "why_not", "recipe_sha256"}
SECTIONS = ("Commander", "Companion", "Deck", "Sideboard")
DECK_ID = re.compile(r"(casual|commander)/[a-z0-9]+(?:-[a-z0-9]+)*")
ART_KEYS = {"name", "mana_cost", "cmc", "type_line", "colors", "color_identity", "roles", "img", "img_small",
            "oracle_text", "power", "toughness", "loyalty", "defense", "produced_mana"}
FACE_KEYS = {"name", "mana_cost", "type_line", "oracle_text", "colors", "power", "toughness", "loyalty", "defense",
             "img", "img_small"}


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


def _named(value):
    return isinstance(value, str) and bool(value) and len(value) <= 200 and value == value.strip() and not any(c in value for c in "\r\n\0")


def _default_box_check(deck):
    """Named physical rows only after both default receipts match the checklist."""
    check, physical = deck.get("box_check"), deck.get("take_apart")
    if (not isinstance(check, dict) or set(check) != BOX_KEYS or check["checked_on"] is not None
            or check["editable"] is not True or check["why_not"] is not None
            or not _hash(check["expect"]) or not _hash(check["recipe_sha256"])
            or not isinstance(deck.get("id"), str) or DECK_ID.fullmatch(deck["id"]) is None
            or not isinstance(physical, dict) or physical.get("available") is not True
            or physical.get("can_take_apart") is not True or physical.get("why_not") is not None
            or physical.get("reason") is not None or physical.get("source") not in ("assembled", "built-list")
            or physical.get("sha256") != check["expect"] or physical.get("version") not in ("target", "owned")):
        return None
    sections = physical.get("sections")
    if not isinstance(sections, dict) or set(sections) - set(SECTIONS) or not sections.get("Deck"):
        return None
    names, quantity, count = set(), 0, 0
    for rows in sections.values():
        if not isinstance(rows, list):
            return None
        identities = set()
        for row in rows:
            if (not isinstance(row, dict) or set(row) != {"kind", "name", "quantity", "basic", "for"}
                    or type(row["quantity"]) is not int or not 1 <= row["quantity"] <= 9999):
                return None
            if row["kind"] == "card":
                valid = _named(row["name"]) and row["for"] is None and type(row["basic"]) is bool
            elif row["kind"] == "marker":
                valid = (_named(row["for"]) and (row["name"] is None and row["basic"] is None
                         or _named(row["name"]) and row["basic"] is False))
            else:
                valid = False
            if not valid:
                return None
            identity = row["kind"], row["name"], row["for"]
            if identity in identities:
                return None
            identities.add(identity)
            count += 1
            if count > 2000:
                return None
            quantity += row["quantity"]
            if row["name"] is not None:
                names.add(row["name"])
    if type(physical.get("card_count")) is not int or physical["card_count"] != quantity:
        return None
    recipe = json.dumps({"version": physical["version"], "sections": sections}, ensure_ascii=False,
                        sort_keys=True, separators=(",", ":"))
    return names if hashlib.sha256(recipe.encode("utf-8")).hexdigest() == check["recipe_sha256"] else None


def _default_box_art(value, names):
    """Only representative card JSON for verified physical names, never extra facts."""
    if not isinstance(value, dict) or set(value) - names:
        return False
    for name, card in value.items():
        if not isinstance(card, dict) or set(card) not in (ART_KEYS, ART_KEYS | {"faces"}) or card.get("name") != name:
            return False
        if (not all(isinstance(card[k], str) for k in ("mana_cost", "type_line", "oracle_text"))
                or type(card["cmc"]) not in (int, float)
                or not math.isfinite(card["cmc"]) or card["cmc"] < 0
                or not all(isinstance(card[k], list) and all(isinstance(item, str) for item in card[k])
                           for k in ("colors", "color_identity", "roles", "produced_mana"))
                or not all(card[k] is None or isinstance(card[k], str)
                           for k in ("img", "img_small", "power", "toughness", "loyalty", "defense"))):
            return False
        if "faces" in card:
            if not isinstance(card["faces"], list) or not card["faces"]:
                return False
            for face in card["faces"]:
                if (not isinstance(face, dict) or set(face) != FACE_KEYS or not _named(face["name"])
                        or not (face["colors"] is None or isinstance(face["colors"], list)
                                and all(isinstance(item, str) for item in face["colors"]))
                        or not all(face[k] is None or isinstance(face[k], str) for k in FACE_KEYS - {"name", "colors"})):
                    return False
    return True


def _ordinary_home_summary(summary):
    if not isinstance(summary, dict) or summary.get("space") != "home" or summary.get("read_only") is not False:
        return False
    deck_id = summary.get("id")
    match = DECK_ID.fullmatch(deck_id) if isinstance(deck_id, str) else None
    return match is not None and summary.get("kind") == match[1] \
        and summary.get("source") in (deck_id, f"magic/decks/{deck_id}.md")


def _default_library_box_check(summary):
    return (_ordinary_home_summary(summary) and summary.get("status") == "built" and "error" not in summary
            and summary.get("versions") in (["target"], ["target", "owned"])
            and type(summary.get("card_count")) is int and summary["card_count"] > 0
            and type(summary.get("sideboard_count")) is int and summary["sideboard_count"] >= 0
            and isinstance(summary.get("box_check"), dict) and summary["box_check"] == {"checked_on": None})


def normalise(dump):
    out = copy.deepcopy(dump)
    for viewer, mine in [(None, out), *((out.get("by_viewer") or {}).items())]:
        if not isinstance(mine, dict):
            continue
        # These are golden_dump's synthetic home identities, never live config.
        # A date exposed in any outside/unknown viewer remains comparable.
        if viewer in (None, "matt", "user1", "(local)"):
            index = mine.get("decks_index")
            summaries = index.get("decks") if isinstance(index, dict) else None
            if isinstance(summaries, list):
                for summary in summaries:
                    if _default_library_box_check(summary):
                        summary.pop("box_check")
        for plan in (mine.get("assembly") or {}).values():
            if not isinstance(plan, dict):
                continue
            default_boxes, names, all_default = 0, set(), True
            for deck in plan.get("decks", []):
                if isinstance(deck, dict):
                    if "box_check" in deck:
                        named = _default_box_check(deck)
                        if named is None:
                            all_default = False
                        else:
                            default_boxes += 1
                            names.update(named)
                            deck.pop("box_check")
                    deck.pop("take_apart", None)
            if default_boxes and all_default and _default_box_art(plan.get("box_check_cards"), names):
                plan.pop("box_check_cards")
            for row in plan.get("rows", []):
                if isinstance(row, dict):
                    for holder in row.get("held_elsewhere", []):
                        if isinstance(holder, dict):
                            holder.pop("intact_product", None)
        for view in (mine.get("deck_view") or {}).values():
            if not isinstance(view, dict):
                continue
            summary = view.get("summary")
            if view.get("box_checked_on", False) is None and _ordinary_home_summary(summary):
                view.pop("box_checked_on")
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
