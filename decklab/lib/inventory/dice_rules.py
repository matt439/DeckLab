"""Owned dice and counters (E7-S24): one row per kind of item a space owns, kept apart from its
token cards (dice.csv beside tokens.csv; the database's dice_counter table, migration 0020).

    type      die | counter
    size      a die's size: d4, d6, d8, d10, d12, d20 or spindown (a spindown life counter, a d20);
              blank for a counter
    kind      a counter's kind, as the deck page names it (+1/+1, poison, loyalty, ...); blank for a
              generic counter that stands for any kind, and always blank for a die
    design    its colour or design, one line (blank when not recorded)
    quantity  how many, 0-9999 (0 keeps a used-up row for history)
    notes     one line

Two rows describing the same item (type, size, kind and design, ignoring case) are never kept
apart: change the quantity instead. Rows are kept in DICE_SORT order: dice by size, then
counters by kind (generic first), then design.

Nothing here touches a database, a decklist, the playable pool or a table.
"""
import re

DICE_FIELDS = ["type", "size", "kind", "design", "quantity", "notes"]
TYPES = ("die", "counter")
SIZES = ("d4", "d6", "d8", "d10", "d12", "d20", "spindown")
KIND_MAX = 30
DESIGN_MAX = 60
NOTES_MAX = 200
QUANTITY_MAX = 9999
DICE_REQUIRED = ("Dice and counters need the database's migration 0020 (python -m decklab.db migrate on the PC); "
                 "until then they can't be recorded.")
SAME = "That item is already listed; change its quantity instead."
_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f  ]")
_FORMULA = ("=", "+", "@")          # a spreadsheet would run it (a "+1/+1" kind is the exception)


def _line(value, what, limit, formula_ok=False):
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError(f"{what} must be text")
    if _CONTROL.search(value):
        raise ValueError(f"{what} is one line, with no control characters")
    text = " ".join(value.split())
    if len(text) > limit:
        raise ValueError(f"{what} is at most {limit} characters")
    if text and not formula_ok and text[0] in _FORMULA:
        raise ValueError(f"{what} can't start with {text[0]}")
    return text


def clean_kind(value):
    """A counter kind as the deck page's needs name it: lower case, single spaces, a minus sign as
    "-", and no trailing "counter(s)" ("+1/+1 Counters" -> "+1/+1"); "" for a generic counter."""
    text = _line(value, "A counter's kind", KIND_MAX + 9, formula_ok=True).lower().replace("−", "-")
    text = re.sub(r"\s*\bcounters?$", "", text).strip()
    if len(text) > KIND_MAX:
        raise ValueError(f"A counter's kind is at most {KIND_MAX} characters")
    if text and text[0] in ("=", "@"):
        raise ValueError(f"A counter's kind can't start with {text[0]}")
    if text.startswith("+") and not re.fullmatch(r"\+\d+/[+-]\d+", text):
        raise ValueError("A counter's kind starting with + is a P/T such as +1/+1")
    return text


def clean_row(row):
    """row (a mapping of DICE_FIELDS, quantity text or a whole number) as it's kept: every field
    text, checked and tidied. ValueError with the words to show otherwise."""
    if not isinstance(row, dict):
        raise ValueError("A dice or counters row must be an object")
    unknown = sorted(set(row) - set(DICE_FIELDS))
    if unknown:
        raise ValueError(f"Unknown column {unknown[0]!r}; a row has {', '.join(DICE_FIELDS)}")
    kind_of = str(row.get("type") or "").strip().lower()
    if kind_of not in TYPES:
        raise ValueError("The type must be die or counter")
    size = str(row.get("size") or "").strip().lower()
    kind = clean_kind(row.get("kind"))
    if kind_of == "die":
        if size not in SIZES:
            raise ValueError(f"A die's size must be one of {', '.join(SIZES)}")
        if kind:
            raise ValueError("A die stands for any kind of counter: leave its kind blank")
    elif size:
        raise ValueError("Only a die has a size")
    quantity = row.get("quantity")
    if isinstance(quantity, bool):
        raise ValueError("The quantity must be a whole number")
    text = str(quantity if quantity is not None else "").strip()
    if not text.isdigit() or int(text) > QUANTITY_MAX:
        raise ValueError(f"The quantity must be a whole number from 0 to {QUANTITY_MAX}")
    return {"type": kind_of, "size": size, "kind": kind,
            "design": _line(row.get("design"), "The colour or design", DESIGN_MAX),
            "quantity": str(int(text)), "notes": _line(row.get("notes"), "The notes", NOTES_MAX)}


def identity(row):
    """What makes two rows the same item: type, size, kind and design (ignoring case)."""
    return (row.get("type") or "", row.get("size") or "", (row.get("kind") or "").casefold(),
            (row.get("design") or "").casefold())


def sort_key(row):
    """DICE_SORT: dice by size, then counters (generic first) by kind, then design and notes."""
    kind_of = row.get("type") or ""
    size = row.get("size") or ""
    return (TYPES.index(kind_of) if kind_of in TYPES else len(TYPES),
            SIZES.index(size) if size in SIZES else len(SIZES), (row.get("kind") or "").casefold(),
            (row.get("design") or "").casefold(), row.get("notes") or "", row.get("quantity") or "")


def label(row):
    """How messages name a row: "d20 (red)", "spindown", "poison counter (green glass)", "counter"."""
    if row.get("type") == "die":
        words = row.get("size") or "die"
    else:
        words = f"{row['kind']} counter" if row.get("kind") else "counter"
    return f"{words} ({row['design']})" if row.get("design") else words


def problems(rows, where):
    """[the words for each row (dicts of DICE_FIELDS) that breaks the rules], where(n) naming row n
    (from 1); also a row describing the same item as an earlier one."""
    out, seen = [], set()
    for number, row in enumerate(rows, 1):
        try:
            made = clean_row({k: row.get(k) for k in DICE_FIELDS})
        except ValueError as e:
            out.append(f"{where(number)}: {e}")
            continue
        if made != {k: row.get(k) for k in DICE_FIELDS}:
            out.append(f"{where(number)}: isn't written as Deck Lab keeps it")
        if identity(made) in seen:
            out.append(f"{where(number)}: the same item as an earlier row")
        seen.add(identity(made))
    return out
