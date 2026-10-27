"""The inventory's pure rules: the columns of each file, how rows are told apart, sorted,
merged, checked and turned into bytes. No file is opened here and nothing is written; callers
give text streams or rows (decklab/PLAN.md, "Moving storage to a database", phase 3).

These used to live in scripts/merge_cards.py, scripts/receive_order.py and
scripts/receipt_transaction.py (all deleted; its lock and journal became lib/inventory/journal.py,
which phase 5 deleted), lib/tokens/rows.py and lib/api/collection_edit.py; the last two re-export them under their old
names (the same objects, so `except` clauses written for those names still catch what this
module raises). Both inventory backends and every writer use these,
so the texts they raise are the ones the pages and the command lines have always shown.

Collection rows (collection.csv, card order payloads, product lists read as cards):
    FIELDS, FINISHES, REQUIRED, PRODUCT_FIELDS, BASIC_LANDS, SPECIAL_BASIC, InvalidCards,
    ident, sort_key, ordinary_basic, merge_notes, parse_cards, merge_rows, collection_csv_bytes
Token rows (tokens.csv, token order payloads):
    TOKEN_FIELDS, TOKEN_SORT, UNVERIFIED, token_sort_key, token_identity, token_uncertain,
    token_known, validate_token_row, merge_tokens, and the Tokens page's limits: NAME_MAX,
    NUMBER_MAX, DETAILS_MAX, NOTES_MAX, QTY_MAX, token_extra, token_rules, token_page_row,
    tokens_csv_bytes, token_label
products/status.csv: STATUS_FIELDS, LEGACY_STATUS_FIELDS, parse_status, set_intact
accessories.csv (phase 4): ACCESSORY_FIELDS, ACCESSORY_KINDS, accessory_sort_key
Any CSV or JSON: csv_bytes, json_bytes, parse_csv, record_lines
Receipts: SLUG, valid_date
Order records' audit_notes: EXTRA_COPIES, EXTRA_COPIES_RE, extra_copies, with_extra_copies (the
    acknowledgement that a pending component is extra copies of printings already owned)
"""
import csv
import io
import json
import re
from datetime import date

# How a refusal ends when a row or a deck can't be read strictly, so nothing can rewrite it
# without losing what it holds ("magic/tokens.csv line 3: ...; it can't be changed until that's put
# right"). tokens.check strips it to match a lenient read's problem with the strict one's.
UNTIL_PUT_RIGHT = "; it can't be changed until that's put right"

# ------------------------------------------------------------------ collection rows

FIELDS = ["name", "set", "collector_number", "finish", "quantity",
          "condition", "language", "notes"]
FINISHES = {"nonfoil", "foil", "etched"}
REQUIRED = {"name", "set", "collector_number", "finish", "quantity"}
PRODUCT_FIELDS = {"section", "deck", "rarity", "in_play_boosters"}
BASIC_LANDS = {"Plains", "Island", "Swamp", "Mountain", "Forest", "Wastes"}
BASIC_LANDS |= {"Snow-Covered " + name for name in BASIC_LANDS}
SPECIAL_BASIC = re.compile(r"\b(?:full[ -]art|special basic)\b", re.IGNORECASE)


class InvalidCards(ValueError):
    """Input or existing inventory cannot be safely merged."""


def ident(row):
    return (row["set"], row["collector_number"], row["finish"])


def sort_key(row):
    cn = row["collector_number"]
    digits = "".join(ch for ch in cn if ch.isdigit())
    return (row["set"], int(digits) if digits else 0, cn, row["finish"])


def ordinary_basic(row):
    return (row["name"] in BASIC_LANDS and row["finish"] == "nonfoil"
            and not SPECIAL_BASIC.search(row.get("notes", "")))


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


def parse_cards(stream, where, *, existing=False):
    """Validate the rows of a text stream (opened with newline="") and normalize product
    columns to collection columns; where names the file in messages (merge_cards.read passes
    the path, as it always has).

    Unnumbered ordinary basics are allowed only in incoming data, where the
    caller excludes them before matching printing identities.
    """
    reader = csv.DictReader(stream, strict=True)
    fields = reader.fieldnames or []
    required = set(FIELDS) if existing else REQUIRED
    allowed = set(FIELDS) if existing else set(FIELDS) | PRODUCT_FIELDS
    if len(fields) != len(set(fields)):
        raise InvalidCards(f"{where}: duplicate column names")
    if missing := required - set(fields):
        raise InvalidCards(f"{where}: missing columns: {', '.join(sorted(missing))}")
    if unknown := set(fields) - allowed:
        raise InvalidCards(f"{where}: unknown columns: {', '.join(sorted(unknown))}")
    rows = []
    seen = set()
    for raw in reader:
        line = f"{where} line {reader.line_num}"
        if None in raw or any(value is None for value in raw.values()):
            raise InvalidCards(f"{line}: row has the wrong number of columns")
        row = {key: raw.get(key, "") for key in FIELDS}
        for key in ("name", "set", "collector_number", "finish"):
            if row[key] != row[key].strip() or any(ch in row[key] for ch in "\r\n\0"):
                raise InvalidCards(f"{line}: invalid {key} {row[key]!r}")
        if not row["name"]:
            raise InvalidCards(f"{line}: no card name")
        if not re.fullmatch(r"[a-z0-9]{2,8}", row["set"]):
            raise InvalidCards(f"{line}: invalid lowercase set code {row['set']!r}")
        if row["finish"] not in FINISHES:
            raise InvalidCards(f"{line}: bad finish {row['finish']!r}")
        if not re.fullmatch(r"[0-9]+", row["quantity"]) or int(row["quantity"]) <= 0:
            raise InvalidCards(f"{line}: quantity must be a positive integer, got {row['quantity']!r}")
        if not row["collector_number"] and (existing or not ordinary_basic(row)):
            raise InvalidCards(f"{line}: no collector_number for {row['name']!r}")
        if any(ch.isspace() for ch in row["collector_number"]):
            raise InvalidCards(f"{line}: invalid collector_number {row['collector_number']!r}")
        if existing and ident(row) in seen:
            raise InvalidCards(f"{line}: duplicate inventory identity {ident(row)}")
        seen.add(ident(row))
        rows.append(row)
    return rows


def merge_rows(existing, inputs):
    """Pure merge shared by the importer and transactional receipt planner."""
    rows = [dict(row) for row in existing]
    by_id = {ident(r): r for r in rows}
    added_rows = bumped_rows = cards = skipped_basics = 0

    for path, incoming in inputs:
        for new in incoming:
            qty = int(new["quantity"])
            old = by_id.get(ident(new))
            if old and old["name"] != new["name"]:
                raise InvalidCards(f"{path}: {ident(new)} is {old['name']!r} in the collection, not {new['name']!r}")
            if ordinary_basic(new) and old is None:
                skipped_basics += qty
                continue
            if old:
                old["quantity"] = str(int(old["quantity"]) + qty)
                old["notes"] = merge_notes(old["notes"], new.get("notes", ""))
                for field in ("condition", "language"):
                    if old[field] != new.get(field, ""):
                        old[field] = ""
                        note = f"Merged copies have differing or unreported {field}"
                        old["notes"] = merge_notes(old["notes"], note)
                bumped_rows += 1
            else:
                row = {k: new.get(k, "") or "" for k in FIELDS}
                rows.append(row)
                by_id[ident(row)] = row
                added_rows += 1
            cards += qty

    rows.sort(key=sort_key)
    return rows, {"cards": cards, "added_rows": added_rows,
                  "bumped_rows": bumped_rows, "skipped_basics": skipped_basics}


def collection_csv_bytes(rows):
    """collection.csv's bytes for rows: its header, sorted by set and collector
    number (sort_key), UTF-8 without a BOM, LF line endings."""
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=FIELDS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(sorted(({k: row.get(k, "") or "" for k in FIELDS} for row in rows), key=sort_key))
    return out.getvalue().encode("utf-8")


# ------------------------------------------------------------------ any CSV or JSON

def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def csv_bytes(rows, fields):
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue().encode("utf-8")


def parse_csv(stream, fields, where):
    """The rows of a text stream whose header must be exactly fields (the old receive_order.read_csv's
    rule); ValueError naming where otherwise, or when a row has the wrong number of columns."""
    reader = csv.DictReader(stream, strict=True)
    if reader.fieldnames != fields:
        raise ValueError(f"{where}: expected columns {','.join(fields)}")
    rows = list(reader)
    if any(None in row or None in row.values() for row in rows):
        raise ValueError(f"{where}: a row has the wrong number of columns")
    return rows


def record_lines(stream):
    """The line each data record of a CSV text stream starts on (the header is line 1),
    skipping blank lines as csv.DictReader does; a quoted cell may span lines."""
    lines = []
    reader = csv.reader(stream)
    next(reader, None)
    start = reader.line_num + 1
    for record in reader:
        if record:
            lines.append(start)
        start = reader.line_num + 1
    return lines


# ------------------------------------------------------------------ accessories.csv

# lib/accessories.py's FIELDS and KINDS (that module reads and checks the rows; the inventory
# keeps them raw, in this order and sort).
ACCESSORY_FIELDS = ["id", "kind", "owner", "brand", "name", "colour", "quantity", "capacity", "image", "crop",
                    "link", "image_source", "notes"]
ACCESSORY_KINDS = ("sleeves", "deck_box", "playmat")


def accessory_sort_key(row):
    """accessories.csv's row order (lib/accessories.csv_bytes): by kind (ACCESSORY_KINDS' order,
    any other kind last), then id."""
    kind = row.get("kind") or ""
    return (ACCESSORY_KINDS.index(kind) if kind in ACCESSORY_KINDS else len(ACCESSORY_KINDS), row.get("id") or "")


# ------------------------------------------------------------------ products/status.csv

# sleeves and deck_box hold an accessory id or free text and mean something only while the
# product is owned and kept intact.
STATUS_FIELDS = ["file", "status", "intact", "sleeves", "deck_box", "notes", "token_cards"]
KIT_STATUS_FIELDS = ["file", "status", "intact", "sleeves", "deck_box", "notes"]
LEGACY_STATUS_FIELDS = ["file", "status", "intact", "notes"]


def parse_status(text, where):
    """status.csv's text as STATUS_FIELDS rows; legacy 4/6-column files get blank new columns
    (the old receive_order.read_status_csv's rule). ValueError naming where for any other header."""
    fields = next(csv.reader(io.StringIO(text, newline="")), None)
    if fields == LEGACY_STATUS_FIELDS:
        return [{**row, "sleeves": "", "deck_box": "", "token_cards": ""}
                for row in parse_csv(io.StringIO(text, newline=""), LEGACY_STATUS_FIELDS, where)]
    if fields == KIT_STATUS_FIELDS:
        return [{**row, "token_cards": ""}
                for row in parse_csv(io.StringIO(text, newline=""), KIT_STATUS_FIELDS, where)]
    return parse_csv(io.StringIO(text, newline=""), STATUS_FIELDS, where)


def set_intact(row, intact):
    """Set a status row's intact choice; a broken-up product's cards go back unsleeved."""
    row["intact"] = intact
    if intact == "no":
        row["sleeves"] = row["deck_box"] = row["token_cards"] = ""


# ------------------------------------------------------------------ token rows

TOKEN_FIELDS = ["front", "back", "set", "front_collector_number", "back_collector_number",
                "finish", "quantity", "front_details", "back_details", "notes"]
UNVERIFIED = re.compile(r"reverse face unconfirmed|reverse.*(?:unknown|unconfirmed)|"
                        r"pairing.*(?:unknown|unconfirmed)|check physical pairing", re.I)
# The order tokens.csv is kept in, shared by receipts and Deck Lab's Tokens page
# so that neither writer reorders the other's rows.
TOKEN_SORT = ("set", "front_collector_number", "back_collector_number", "front", "back",
              "front_details", "back_details", "finish")


def token_sort_key(row):
    return tuple(row[key] for key in TOKEN_SORT)


def token_identity(row):
    """A token card's identity: every column except quantity and notes."""
    return tuple(row[key] for key in TOKEN_FIELDS if key not in ("quantity", "notes"))


def token_uncertain(row):
    """Whether the notes or details say something about the card is unconfirmed."""
    return bool(re.search(r"\b(?:unconfirmed|unknown|unspecified)\b", " ".join(
        row[key] for key in ("notes", "front_details", "back_details")), re.I))


def token_known(row):
    """Whether the printing and both faces are identified, so equal rows may merge."""
    return (all(row[key] for key in ("set", "front_collector_number", "finish")) and (
        not row["back"] or bool(row["back_collector_number"])) and not token_uncertain(row))


def validate_token_row(row, where, *, incoming=False):
    """Raise ValueError naming `where` when a tokens.csv row breaks the file's rules."""
    if not row["front"] or not re.fullmatch(r"[0-9]+", row["quantity"]) or int(row["quantity"]) < 1:
        raise ValueError(f"{where}: tokens need a front name and positive physical quantity")
    if row["finish"] not in ("", *FINISHES):
        raise ValueError(f"{where}: invalid token finish")
    if row["set"] and not re.fullmatch(r"[a-z0-9]{2,8}", row["set"]):
        raise ValueError(f"{where}: invalid lowercase token set")
    for key in ("front", "back", "front_collector_number", "back_collector_number"):
        if row[key] != row[key].strip() or any(char in row[key] for char in "\r\n\0"):
            raise ValueError(f"{where}: invalid token {key}")
    if any(char.isspace() for key in ("front_collector_number", "back_collector_number") for char in row[key]):
        raise ValueError(f"{where}: invalid token collector number")
    if incoming and UNVERIFIED.search(row["notes"]):
        raise ValueError(f"{where}: unresolved token pairing; edit the CSV to verified facts first")
    if incoming and not row["back"] and "single-sided verified" not in row["notes"].lower():
        raise ValueError(f"{where}: blank token reverse requires the note 'single-sided verified'")


def merge_tokens(existing, incoming):
    rows = [dict(row) for row in existing]
    added = bumped = quantity = 0
    for row in incoming:
        # Unidentified printing or incomplete physical face identity stays separate.
        known = token_known(row)
        old = next((old for old in rows if known and token_identity(old) == token_identity(row)
                    and not token_uncertain(old)), None)
        if old is None:
            rows.append(dict(row))
            added += 1
        else:
            old["quantity"] = str(int(old["quantity"]) + int(row["quantity"]))
            if row["notes"] and row["notes"] not in old["notes"]:
                old["notes"] = "; ".join(filter(None, (old["notes"], row["notes"])))
            bumped += 1
        quantity += int(row["quantity"])
    rows.sort(key=token_sort_key)
    return rows, {"cards": quantity, "added_rows": added, "bumped_rows": bumped}


# The Tokens page's limits on top of validate_token_row (lib/tokens/rows.py re-exports these).
NAME_MAX, NUMBER_MAX, DETAILS_MAX, NOTES_MAX, QTY_MAX = 80, 16, 300, 500, 9999


def token_extra(row, where):
    """The page's limits on top of validate_token_row: lengths, a
    quantity of at most QTY_MAX, and one-line details and notes."""
    for key, limit in (("front", NAME_MAX), ("back", NAME_MAX), ("set", NUMBER_MAX),
                       ("front_collector_number", NUMBER_MAX), ("back_collector_number", NUMBER_MAX),
                       ("front_details", DETAILS_MAX), ("back_details", DETAILS_MAX), ("notes", NOTES_MAX)):
        if len(row[key]) > limit:
            raise ValueError(f"{where}: {key} is longer than {limit} characters")
    for key in ("front_details", "back_details", "notes"):
        if any(ord(ch) < 32 or ord(ch) == 127 for ch in row[key]):
            raise ValueError(f"{where}: {key} must be one line")
    if int(row["quantity"]) > QTY_MAX:
        raise ValueError(f"{where}: quantity must be at most {QTY_MAX}")


def token_rules(row, where):
    """Every rule a tokens.csv row read by Deck Lab must meet: validate_token_row's and the
    page's (token_extra)."""
    validate_token_row(row, where)
    token_extra(row, where)


def token_page_row(row):
    """A row as written to the CSV: every field cleaned to one line
    (decks.clean_title), set and finish lower case, quantity a string of a
    whole number from 1 to QTY_MAX. Raises ValueError saying what's wrong.
    Names aren't checked (see tokens.check_names)."""
    from decklab.lib.decks import clean_title
    quantity = row.get("quantity")
    if isinstance(quantity, bool) or not isinstance(quantity, (int, str, type(None))):
        raise ValueError(f"Quantity {quantity!r} must be a whole number from 1 to {QTY_MAX}")
    out = {key: clean_title("" if row.get(key) is None else row.get(key)) for key in TOKEN_FIELDS}
    out["set"], out["finish"] = out["set"].lower(), out["finish"].lower()
    if not re.fullmatch(r"[0-9]+", out["quantity"]) or not 1 <= int(out["quantity"]) <= QTY_MAX:
        raise ValueError(f"Quantity {row.get('quantity')!r} must be a whole number from 1 to {QTY_MAX}")
    out["quantity"] = str(int(out["quantity"]))
    try:
        token_rules(out, "\0")
    except ValueError as e:
        text = str(e).removeprefix("\0: ")
        raise ValueError(text[:1].upper() + text[1:]) from None
    return out


def tokens_csv_bytes(rows):
    """The CSV file for rows: sorted by token_sort_key; UTF-8 without
    a byte order mark, LF line endings."""
    rows = [{k: "" if row.get(k) is None else str(row.get(k)) for k in TOKEN_FIELDS} for row in rows]
    return csv_bytes(sorted(rows, key=token_sort_key), TOKEN_FIELDS)


def token_label(row):
    """How messages name a card: "Zombie / Zombie Knight", or "Goblin" when single-sided."""
    return f"{row['front']} / {row['back']}" if row.get("back") else row["front"]


# ------------------------------------------------------------------ receipts

SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")


def valid_date(value):
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError("Receipt date must be YYYY-MM-DD")
    date.fromisoformat(value)
    return value


# ------------------------------------------------------------------ order records' audit_notes

# The acknowledgement that a pending component is extra copies of printings already owned (an
# order for a second copy of a printing in the collection), kept in the order record's audit_notes
# as one sentence: "Extra copies of owned printings: cards, extras." (component ids, ", "-separated).
# Only extra_copies() reads it and only with_extra_copies() writes it; the rest of audit_notes is
# never touched. pool._load_pool skips its "every card ... is already in the collection" warning for
# a pending component named here. Stored in the text, not a column, so it needed no migration.
EXTRA_COPIES = "Extra copies of owned printings"
_ID = r"[a-z0-9]+(?:-[a-z0-9]+)*"
EXTRA_COPIES_RE = re.compile(rf"(?<![^ ]){EXTRA_COPIES}: ({_ID}(?:, {_ID})*)\.(?![^ ])")


def _extra_copies_matches(text):
    """Human acknowledgements only: captured watchlist notes are inert ledger data."""
    from .order_fulfilment import audit_span
    span = audit_span(text)
    return [m for m in EXTRA_COPIES_RE.finditer(text)
            if span is None or m.end() <= span[0] or m.start() >= span[1]]


def extra_copies(audit_notes):
    """The component ids an order record's audit_notes acknowledges as extra copies of owned
    printings (EXTRA_COPIES_RE), in order; () when it names none or isn't text."""
    if not isinstance(audit_notes, str):
        return ()
    found = []
    for m in _extra_copies_matches(audit_notes):
        found += [cid for cid in m.group(1).split(", ") if cid not in found]
    return tuple(found)


def with_extra_copies(audit_notes, ids):
    """audit_notes with its acknowledgement naming exactly ids (in that order; none: the sentence
    removed with the one space that joined it to the rest). The sentence is kept where it was when
    there was one, else added at the end after a space (as a cancellation's reason is); every other
    character stays as it was. None when nothing would be left (the record then has no audit_notes)."""
    text = audit_notes if isinstance(audit_notes, str) else ""
    ids = list(dict.fromkeys(ids))
    sentence = f"{EXTRA_COPIES}: {', '.join(ids)}." if ids else ""
    spans = [m.span() for m in _extra_copies_matches(text)]
    if not spans:
        return (f"{text} {sentence}" if text else sentence) if sentence else (text or None)
    out, at = [], 0
    for n, (start, end) in enumerate(spans):
        if n == 0 and sentence:                     # the first sentence rewritten where it is
            out.append(text[at:start] + sentence)
        else:                                       # any other removed, with one joining space
            if start > at and text[start - 1] == " ":
                start -= 1
            elif end < len(text) and text[end] == " " and (n + 1 == len(spans) or spans[n + 1][0] > end + 1):
                end += 1
            out.append(text[at:start])
        at = end
    out.append(text[at:])
    return "".join(out) or None
