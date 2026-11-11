"""Counted observations within the existing collection row's notes, never copy identities.

Only complete, positive breakdowns matching a row's quantity are reusable evidence.
An explicitly set condition/language takes precedence over historical notes (the
bulk sheet deliberately leaves those notes alone). Older general notes cannot
recover a breakdown, so their copies remain not recorded on a later merge.
"""
import json
import re
from collections import Counter

PREFIX = "Copies: "
UNKNOWN = "not recorded"
FIELDS = ("condition", "language")
FLAGS = ("misprint", "altered", "signed")
_COUNTS = re.compile(r"Copies: (condition|language) (.+)\Z")
# More than a trillion physical copies is not count evidence. Bound conversion
# before int(), including notes from an untrusted upload with thousands of digits.
_FLAG = re.compile(r"Copies: ([1-9][0-9]{0,11}) (misprint|altered|signed)\Z")
_PAIR = re.compile(r"([1-9][0-9]{0,11}) (.+)\Z")
_SIMPLE = re.compile(r"[A-Za-z][A-Za-z0-9 _-]*\Z")


def merge_notes(existing, incoming):
    """Keep existing prose and append distinct semicolon-separated observations."""
    seen = {part.strip() for part in existing.split(";") if part.strip()}
    additions = []
    for part in incoming.split(";"):
        part = part.strip()
        if part and part not in seen:
            additions.append(part)
            seen.add(part)
    return "; ".join(filter(None, (existing, *additions)))


def _label(value):
    if _SIMPLE.fullmatch(value) and value != UNKNOWN:
        return value
    # Keep separators escaped so the note is still one semicolon observation,
    # even for legacy command-line condition text outside the page's choices.
    return json.dumps(value, ensure_ascii=False).replace(";", r"\u003b").replace(",", r"\u002c")


def _breakdown(part):
    match = _COUNTS.fullmatch(part)
    if not match:
        return None
    counts = Counter()
    for entry in match[2].split(", "):
        pair = _PAIR.fullmatch(entry)
        if not pair:
            return None
        word = pair[2]
        if word.startswith('"'):
            try:
                word = json.loads(word)
            except (ValueError, TypeError):
                return None
            if not isinstance(word, str) or not word:
                return None
        elif word == UNKNOWN:
            word = ""
        elif not _SIMPLE.fullmatch(word):
            return None
        if word in counts:
            return None
        counts[word] = int(pair[1])
    return match[1], counts


def _parts(row):
    return [part.strip() for part in row.get("notes", "").split(";") if part.strip()]


def _counts(row, field):
    qty = int(row["quantity"])
    if row.get(field):
        return Counter({row[field]: qty})
    candidates = [parsed[1] for part in _parts(row) if (parsed := _breakdown(part)) and parsed[0] == field]
    if len(candidates) == 1 and sum(candidates[0].values()) == qty:
        return candidates[0]
    return Counter({"": qty})


def _flag_counts(row):
    qty = int(row["quantity"])
    counts = Counter()
    for flag in FLAGS:
        values = {int(match[1]) for part in _parts(row) if (match := _FLAG.fullmatch(part)) and match[2] == flag}
        if len(values) == 1 and (value := next(iter(values))) <= qty:
            counts[flag] = value
    return counts


def flag_notes(quantity, *flags):
    """Positive source flags only; a missing/false flag never claims a copy is unmarked."""
    return "; ".join(f"{PREFIX}{int(quantity)} {flag}" for flag in FLAGS if flag in flags)


def source_flags(values, fmt, quantity):
    """Vendor flags as counted notes, or a review problem for an unfamiliar value."""
    columns = {"manabox": {"misprint": "misprint", "altered": "altered"},
               "deckbox": {"misprint": "misprint", "altered art": "altered", "signed": "signed"},
               "moxfield": {"alter": "altered"}}.get(fmt, {})
    flags = []
    for column, flag in columns.items():
        value = str(values.get(column, "") or "").strip().casefold()
        if value in ("", "false", "no", "0"):
            continue
        if value not in ("true", "yes", "1", flag, column):
            return "", f"The {column} mark isn't a known yes/no value. Check this row."
        flags.append(flag)
    try:
        qty = int(quantity)
    except (ValueError, TypeError):
        return "", None                 # the existing quantity check gives the problem
    return (flag_notes(qty, *flags) if qty > 0 else ""), None


def _prose(row):
    qty = int(row["quantity"])
    kept = []
    for part in _parts(row):
        parsed, flag = _breakdown(part), _FLAG.fullmatch(part)
        if parsed and sum(parsed[1].values()) == qty:
            continue
        if flag and int(flag[1]) <= qty:
            continue
        kept.append(part)
    return "; ".join(kept)


def note_limit(notes, quantity, prose_limit):
    """Allow reusable count evidence in addition to the unchanged prose allowance.

    Counted notes are generated after source validation and can make a normal
    500-character note longer. A CSV export must not silently clip those counts
    when imported again; arbitrary longer prose retains the existing limit.
    """
    try:
        row = {"notes": notes, "quantity": str(int(quantity))}
    except (ValueError, TypeError):
        return prose_limit
    if not isinstance(notes, str) or len(_prose(row)) > prose_limit:
        return prose_limit
    return max(prose_limit, len(notes))


def has_counts(notes, quantity):
    """Whether a row carries reusable counted evidence, independent of prose length."""
    try:
        row = {"notes": notes, "quantity": str(int(quantity))}
    except (ValueError, TypeError):
        return False
    return isinstance(notes, str) and len(_prose(row)) < len("; ".join(_parts(row)))


def split_notes(row, quantity):
    """Notes of a known uniform subset; refuse an unknowable physical allocation."""
    have = int(row["quantity"])
    if quantity == have:
        return row.get("notes", "")
    refusal = ("This row has counted copy differences. Supply separate rows with the actual copy facts "
               "before splitting or receiving part of it.")
    notes = _prose(row)
    for part in _parts(row):
        parsed, flag = _breakdown(part), _FLAG.fullmatch(part)
        if parsed:
            field, counts = parsed
            if sum(counts.values()) != have:
                raise ValueError(refusal)
            current = _counts(row, field)
            if len(current) != 1:
                raise ValueError(refusal)
            word = next(iter(current))
            notes = merge_notes(notes, f"{PREFIX}{field} {quantity} {_label(word) if word else UNKNOWN}")
        elif flag:
            if int(flag[1]) != have:
                raise ValueError(refusal)
            notes = merge_notes(notes, f"{PREFIX}{quantity} {flag[2]}")
    return notes


def merge(old, new):
    """Fields to update on two equal-printing rows, without changing either input."""
    notes = merge_notes(_prose(old), _prose(new))
    result = {"quantity": str(int(old["quantity"]) + int(new["quantity"]))}
    for field in FIELDS:
        counts = _counts(old, field) + _counts(new, field)
        result[field] = next(iter(counts)) if len(counts) == 1 else ""
        # Entirely unreported rows need no new note, unless a counted breakdown
        # already existed and needs its total carried through the merge.
        had_breakdown = any((parsed := _breakdown(part)) and parsed[0] == field
                            for row in (old, new) for part in _parts(row))
        if len(counts) > 1 or (not result[field] and had_breakdown):
            order = {word: index for index, word in enumerate(("NM", "LP", "MP", "HP", "DMG"))}
            keys = sorted(counts, key=lambda word: (not bool(word), order.get(word, 99), word))
            detail = ", ".join(f"{counts[word]} {_label(word) if word else UNKNOWN}" for word in keys)
            notes = merge_notes(notes, f"{PREFIX}{field} {detail}")
    flags = _flag_counts(old) + _flag_counts(new)
    for flag in FLAGS:
        if flags[flag]:
            notes = merge_notes(notes, f"{PREFIX}{flags[flag]} {flag}")
    result["notes"] = notes
    return result
