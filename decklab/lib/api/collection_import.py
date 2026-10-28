"""Collection upload detection, conversion and Scryfall matching orchestration.

The HTTP handlers, preview lifecycle and mutable validation limits stay in
collection_edit. Read that module's attributes at call time so existing callers
and test patches retain one owner; importing this module does not read them.
The original parser names remain available through collection_edit.
"""
import csv
import io
import re

from decklab.lib.inventory import rules

from .common import ApiError, _public


def _norm(header):
    return " ".join(str(header or "").replace("﻿", "").strip().lower().replace("_", " ").split())


def detect(headers):
    """The FORMATS name of an upload's header row, or None."""
    names = {_norm(h) for h in headers}
    if {"name", "set", "collector number", "finish", "quantity"} <= names:
        return "collection"
    if {"name", "set code", "collector number", "quantity"} <= names:
        return "manabox"
    if {"count", "name", "edition", "card number"} <= names:
        return "deckbox"
    if {"count", "name", "edition", "collector number"} <= names:
        return "moxfield"
    return None


def _condition(value, fmt):
    word = " ".join(str(value or "").strip().lower().replace("_", " ").replace("-", " ").split())
    if not word:
        return ""
    if fmt == "collection" and value.strip().upper() in owner.CONDITIONS:
        return value.strip().upper()
    return owner._CONDITION_FORMAT.get(fmt, {}).get(word) or owner._CONDITION_WORDS.get(word, "")


def _language(value):
    word = str(value or "").strip().lower()
    return owner._LANGUAGE_WORDS.get(word, "") if word else ""


def _finish(value, fmt):
    word = str(value or "").strip().lower()
    if fmt == "collection":
        return word
    if word in ("", "normal", "nonfoil", "non-foil", "false", "no", "0"):
        return "nonfoil"
    if word in ("etched", "etched foil", "foil etched"):
        return "etched"
    if word in ("foil", "true", "yes", "1", "pre-release foil", "prerelease foil", "promo foil"):
        return "foil"
    return word


def _too_many_rows():
    return ApiError(400, f"That file has more than {owner.MAX_IMPORT_ROWS:,} rows of cards, and an import is limited to "
                         f"{owner.MAX_IMPORT_ROWS:,}: split it into smaller files and import each one.")


def _source_rows(text, fmt, reader):
    """[(line, row, set_name, problem)] of an upload in fmt: collection.csv's
    columns as text, before Scryfall matching. ApiError 400 for more than
    MAX_IMPORT_ROWS rows (reading stops at the first one over)."""
    out = []
    for raw in reader:
        line = reader.line_num
        values = {_norm(k): (v or "").strip() for k, v in raw.items() if k is not None}
        if not any(values.values()):
            continue
        if len(out) >= owner.MAX_IMPORT_ROWS:
            raise _too_many_rows()
        get = values.get
        if fmt == "collection":
            row = {"name": get("name", ""), "set": get("set", "").lower(),
                   "collector_number": get("collector number", ""), "finish": _finish(get("finish"), fmt),
                   "quantity": get("quantity", ""), "condition": _condition(get("condition"), fmt),
                   "language": _language(get("language")), "notes": get("notes", "")}
            set_name = None
        elif fmt == "manabox":
            row = {"name": get("name", ""), "set": get("set code", "").lower(),
                   "collector_number": get("collector number", ""), "finish": _finish(get("foil"), fmt),
                   "quantity": get("quantity", ""), "condition": _condition(get("condition"), fmt),
                   "language": _language(get("language")), "notes": ""}
            set_name = get("set name")
        else:
            code = get("edition code", "") if fmt == "deckbox" else get("edition", "")
            row = {"name": get("name", ""), "set": code.lower(),
                   "collector_number": get("card number" if fmt == "deckbox" else "collector number", ""),
                   "finish": _finish(get("foil"), fmt), "quantity": get("count", ""),
                   "condition": _condition(get("condition"), fmt), "language": _language(get("language")),
                   "notes": ""}
            set_name = get("edition") if fmt == "deckbox" else None
        problem = None
        if not re.fullmatch(r"\d{1,4}", row["quantity"]) or not 1 <= int(row["quantity"]) <= owner.MAX_QUANTITY:
            problem = f"quantity {row['quantity']!r} isn't a whole number from 1 to {owner.MAX_QUANTITY}"
        elif row["finish"] not in owner.FINISHES:
            problem = f"unknown finish {row['finish']!r}"
        elif row["set"] and not owner.SET_RE.fullmatch(row["set"]):
            problem = f"unknown set code {row['set']!r}"
        elif row["collector_number"] and not owner.NUMBER_RE.fullmatch(row["collector_number"]):
            problem = f"unknown collector number {row['collector_number']!r}"
        elif len(row["name"]) > owner.MAX_NAME or any(owner._CONTROL_RE.search(v) for v in (*row.values(), set_name or "")):
            problem = ("a field has a control character (a tab or line break inside a cell, say), "
                       "or the name is too long")
        elif row["notes"].startswith(owner.FORMULA_STARTS):
            problem = "the notes start with = + - or @, which a spreadsheet would run as a formula"
        else:
            row["quantity"] = str(int(row["quantity"]))
        for key in ("condition", "language", "notes"):
            row[key] = row[key][:owner.MAX_TEXT[key]]
        out.append((line, row, set_name, problem))
    return out


def read_upload(text, existing=()):
    """(format, rows, problems, dropped_basics) of an upload's text: rows
    [{the eight columns, "line", "problem"}] matched to Scryfall, ordinary
    basics dropped (dropped_basics: their cards) unless existing (identity
    keys already in the collection) has them, rows naming one identity key
    merged (at the first one's line). problems [{"line", "message"}].
    ApiError 400 for an upload that isn't one of FORMATS."""
    text = text.lstrip("﻿")
    try:
        reader = csv.DictReader(io.StringIO(text, newline=""), strict=True)
        headers = reader.fieldnames or []
        fmt = detect(headers)
        if fmt is None:
            raise ApiError(400, "That file isn't a ManaBox, Moxfield, Deckbox or collection-columns export: its first "
                                "line should name the columns (Name, Set code, Collector number, Quantity, ...)")
        source = _source_rows(text, fmt, reader)
    except csv.Error as e:
        raise ApiError(400, f"That file can't be read as CSV: {_public(e)}") from None
    existing = set(existing)
    rows, by_key, dropped = [], {}, 0
    for line, row, set_name, problem in source:
        # Basics first: they're dropped whatever their printing (rules.merge_rows' rule).
        if problem is None and rules.ordinary_basic(row) and rules.ident(row) not in existing:
            dropped += int(row["quantity"])
            continue
        if problem is None:
            row, problem = owner.match(row, set_name)
        if problem is None and rules.ident(row) in by_key:
            first = by_key[rules.ident(row)]
            first["quantity"] = str(int(first["quantity"]) + int(row["quantity"]))
            first["notes"] = rules.merge_notes(first["notes"], row["notes"])
            for key in ("condition", "language"):
                if first[key] != row[key]:
                    first[key] = ""
                    first["notes"] = rules.merge_notes(
                        first["notes"], f"Merged copies have differing or unreported {key}")
            continue
        entry = {**{k: row.get(k, "") for k in owner.FIELDS}, "line": line, "problem": problem}
        rows.append(entry)
        if problem is None:
            by_key[rules.ident(entry)] = entry
    problems = [{"line": r["line"], "message": r["problem"]} for r in rows if r["problem"]]
    return fmt, rows, problems, dropped


# Define the re-exported functions before importing their mutable owner, so
# either module can be imported first without reading a partial definition.
from . import collection_edit as owner
