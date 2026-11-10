"""Offline vendor CSV layouts; no identifiers are fetched and spending columns are ignored.

Archidekt: original collection-export header (public export, 2024-12-26):
https://github.com/AtkinsonKevin/mtgArchidekt/blob/main/archidekt-collection-export-2024-12-26.csv
Dragon Shield: current public client export/condition definitions, checked 2026-11-11:
https://mtg.dragonshield.com/main.d2f3de1f82ee2e60.js
TCGplayer: published inventory headings and configurable app CSV fields:
https://help.tcgplayer.com/hc/en-us/articles/115002358027
https://help.tcgplayer.com/hc/en-us/articles/115010308788
Delver Lens supplies configurable presets, including Archidekt/Moxfield/Deckbox/TCGplayer:
https://www.delverlab.com/ (developer changelog and export tutorial).

Only identifying columns are mapped; raw source/provenance remains the upload's owner.
"""
import re

FORMATS = ("archidekt", "dragonshield", "delver", "tcgplayer")


def detect(names):
    if {"quantity", "name", "edition code", "collector number"} <= names:
        return "archidekt"
    if {"quantity", "card name", "set code", "card number"} <= names and names.intersection({"folder name", "trade quantity"}):
        return "dragonshield"
    if (({"product name", "set name", "number", "total quantity"} <= names)
            or ({"quantity", "set code", "card number"} <= names and names.intersection({"simple name", "product id", "sku"}))
            or ({"quantity", "product id", "variant"} <= names)):
        return "tcgplayer"
    # Delver's custom CSVs are configurable; its named site presets use those
    # layouts above or the existing ManaBox/Moxfield/Deckbox detector. Never guess
    # column positions from an unfamiliar header or use a paid-price field as quantity.
    if {"quantity", "name", "collector number"} <= names and names.intersection({"set", "edition", "edition code"}):
        return "delver"
    if {"quantity", "card name", "set code", "card number"} <= names:
        return "dragonshield"     # same public card-manager layout without its optional folder columns
    return None


def convert(values, fmt, *, finish, condition, language):
    get = values.get
    if fmt == "archidekt":
        name, code, number, set_name = get("name", ""), get("edition code", ""), get("collector number", ""), get("edition name")
    elif fmt == "dragonshield":
        name, code, number, set_name = get("card name", ""), get("set code", ""), get("card number", ""), get("set name")
    elif fmt == "delver":
        name, code, number, set_name = get("name", ""), get("set", get("edition code", get("edition", ""))), get("collector number", ""), get("set name")
    else:
        name = get("simple name") or get("product name") or get("card name") or get("name", "")
        code, number = get("set code", ""), get("card number", get("number", ""))
        set_name = get("set name") or get("set")
    raw_condition = get("condition", "")
    raw_finish = get("finish", get("printing", get("foil", get("variant", "")))).replace("_", " ")
    finish_problem = None
    if fmt == "tcgplayer":
        # The seller CSV encodes foil in Condition when no Printing field exists.
        raw_condition = re.sub(r"([a-z])([A-Z])", r"\1 \2", raw_condition)
        raw_condition = re.sub(r"^(NM|LP|MP|HP|DMG)(?=foil|etched)", r"\1 ", raw_condition, flags=re.I)
        found = re.search(r"\s+(non[ -]?foil|foil(?:[ -]?etched)?|etched(?:[ -]?foil)?)\s*$", raw_condition, re.I)
        if found:
            words = re.sub(r"[ -]", "", found.group(1)).casefold()
            derived = {"nonfoil": "nonfoil", "foil": "foil", "etched": "etched", "foiletched": "etched", "etchedfoil": "etched"}[words]
            if not raw_finish:
                raw_finish = derived
            elif finish(raw_finish, fmt) != derived:
                finish_problem = "The Printing and Condition columns disagree about finish. Check this row."
            raw_condition = raw_condition[:found.start()].strip()
    if fmt == "dragonshield":
        if raw_condition.casefold() == "nearmint":
            raw_condition = "near mint"
        elif raw_condition.casefold() in ("lightplayed", "light played", "played"):
            # These are grades on Dragon Shield's seven-step scale, not TCGplayer
            # condition labels; leave an uncertain cross-scale conversion unknown.
            raw_condition = ""
    row = {"name": name, "set": code.lower(), "collector_number": number,
           "finish": finish(raw_finish, fmt), "quantity": get("quantity", get("total quantity", "")),
           "condition": condition(raw_condition, fmt), "language": language(get("language")), "notes": ""}
    product_line = get("product line", "").casefold()
    problem = "This import is for Magic cards only." if product_line and product_line not in ("magic", "magic: the gathering") else finish_problem
    if not name and fmt == "tcgplayer":
        problem = "This ID-only export has no card name. Export Name or Product Name and printing columns; no identifier lookup is performed."
    return row, set_name, problem
