"""Read-only eligibility for one latest deleted physical token-card record.

This does not construct an inverse or allocate a replacement id. A later supported
restoration must use ordinary Add's fresh database identity and explicit whole-count
ownership confirmation. Existing stock and every recorded packing allocation stay put.
"""
import hashlib
import json
import re

from decklab.lib import cards, decks, inventory, tokens
from decklab.lib.tokens import names, products

from . import files, rules
from .undo import TOKEN_FIELDS, TOKENS, UndoConflict, UndoMissing, UndoUnsupported, _cells, _identifier, _ordinary
from .undo_tokens import _packing, ordered_rows

ACTION = "token_restore_review"
READ_ONLY = "set transaction isolation level read committed, read only"
IDENTITY_POLICY = "fresh_id_on_future_add"
NO_APPLY = "This token restoration is a read-only review. Nothing can be restored here yet."
MAX_STOCK = 10_000
MAX_HOLDERS = 1_000
MAX_MATCHES = 1_000_000
MAX_DECK_TEXT = 4 * 1024 * 1024


def is_delete(rows):
    return isinstance(rows, list) and len(rows) == 1 and isinstance(rows[0], dict) \
        and rows[0].get("table") == TOKENS and rows[0].get("op") == "DELETE"


def source_record(rows, space):
    """Prove complete private scope before inspecting a historical fact or label."""
    if not is_delete(rows):
        raise UndoMissing()
    source = rows[0]
    old = source.get("before")
    if not isinstance(old, dict) or old.get("space_id") != space:
        raise UndoMissing()
    if set(source) != {"id", "table", "op", "key", "before", "after"} or source.get("after") is not None \
            or set(old) != TOKEN_FIELDS:
        raise UndoUnsupported("The deleted token row has an unsupported schema.")
    _identifier(source["id"])
    _identifier(old["id"])
    if not isinstance(source["key"], dict) or set(source["key"]) != {"id"} \
            or type(source["key"]["id"]) is not int or source["key"]["id"] != old["id"] \
            or type(old["position"]) is not int or not 0 <= old["position"] <= 2 ** 31 - 1:
        raise UndoUnsupported("The original token identity and position cannot be checked.")
    restored = _ordinary(old, TOKENS)
    try:
        for key, value in restored.items():
            if key != "quantity":
                value.encode("utf-8", errors="strict")
                if any(ord(char) < 32 or ord(char) == 127 for char in value):
                    raise ValueError("Unsupported historical text")
        rules.validate_token_row(_cells(restored), "Token review", incoming=True)
        if not rules.token_known(restored):
            raise ValueError("Unknown physical printing")
    except (ValueError, UnicodeError):
        raise UndoUnsupported("Check the removed card's printing and physical pairing in Tokens first.") from None
    return source, restored


def _verified_printing(restored):
    """Use existing local card data, never fetch it or tidy the saved historical row."""
    try:
        cells = _cells(restored)
        checked, warnings = names.check_names(cells)
        if warnings or checked != cells:
            raise ValueError("Names are not exact")
        for side in ("front", "back"):
            if not restored[side]:
                continue
            printing = cards.printing(restored["set"], restored[side + "_collector_number"])
            if not isinstance(printing, dict) or printing.get("digital") is not False \
                    or not isinstance(printing.get("games"), list) or "paper" not in printing["games"] \
                    or not isinstance(printing.get("finishes"), list) or restored["finish"] not in printing["finishes"]:
                raise ValueError("Printing cannot be checked")
    except Exception:
        raise UndoUnsupported("The exact removed token facts cannot be checked with the current card data.") from None


def _face_names(row):
    return tuple(sorted(cards.fold(row[side]) for side in ("front", "back") if row[side]))


def _printing_key(row):
    return row["set"], row["finish"], tuple(sorted(row[side + "_collector_number"]
           for side in ("front", "back") if row[side]))


def _stock(snapshot, source, restored, store, space):
    sheet = snapshot.token_set(space)
    if len(sheet.rows) > MAX_STOCK:
        raise ValueError("Token stock exceeds the review bound")
    stock = ordered_rows(sheet)
    if not sheet.sorted or [row.id for row in sorted(sheet.rows, key=rules.token_sort_key)] != [row["id"] for row in stock]:
        raise ValueError("Token order is not settled")
    reader = getattr(store, "undo_token_positions", None)
    layout = reader(space) if callable(reader) else None
    if not isinstance(layout, list) or len(layout) != len(stock):
        raise ValueError("Incomplete token layout")
    previous = -1
    for position, row in zip(layout, stock):
        if not isinstance(position, dict) or set(position) != {"id", "position"} \
                or type(position["id"]) is not int or position["id"] != row["id"] \
                or type(position["position"]) is not int or not previous < position["position"] <= 2 ** 31 - 1:
            raise ValueError("Ambiguous token positions")
        previous = position["position"]
    if any(row["id"] == source["before"]["id"] for row in stock):
        raise ValueError("The removed id is present")
    for item in stock:
        row = item["row"]
        if rules.token_identity(row) == rules.token_identity(restored) \
                or _printing_key(row) == _printing_key(restored) \
                or not rules.token_known(row) and set(_face_names(row)) & set(_face_names(restored)):
            raise ValueError("A physical card may already be recorded")
    return stock, layout


def _packing_evidence(snapshot, space, stock, restored):
    from .undo import _home_products, _known_decks
    lines = []
    def extend(found):
        if not isinstance(found, list) or len(found) > MAX_STOCK - len(lines):
            raise ValueError("Too many packed lines")
        lines.extend(found)
    with inventory.pinned(snapshot):
        count = text_size = 0
        for stored in snapshot.decks.values():
            if stored.space != space:
                continue
            count += 1
            if not isinstance(stored.text, str):
                raise ValueError("Unreadable possible holder")
            text_size += len(stored.text)
            if count > MAX_HOLDERS or text_size > MAX_DECK_TEXT:
                raise ValueError("Too many possible holders")
        listed = _known_decks(snapshot, space)
        if len(listed) > MAX_HOLDERS:
            raise ValueError("Too many possible holders")
        for deck in listed:
            if deck.status == "built":
                if not decks.has_token_cards(deck):
                    raise ValueError("Unknown deck packing")
                extend(decks.token_cards(deck))
        if space == "home" and (len(snapshot.products) > MAX_HOLDERS or len(snapshot.status.rows) > MAX_HOLDERS):
            raise ValueError("Too many possible product holders")
        intact = _home_products(snapshot, space)
        if len(intact) > MAX_HOLDERS:
            raise ValueError("Too many possible product holders")
        if space == "home":
            warnings = []
            records = products.records(warnings, snapshot)
            if warnings or set(records) != {"product/" + stem for stem in intact}:
                raise ValueError("Unknown product packing")
            for record in records.values():
                if not record.get("written") or record.get("error") or not isinstance(record.get("lines"), list):
                    raise ValueError("Unknown product packing")
                extend(record["lines"])
        if len(lines) > MAX_STOCK or len(lines) * len(stock) > MAX_MATCHES \
                or any(tokens.reserve.matches(line, restored) for line in lines):
            raise ValueError("A packed reference may claim the restored cards")
        # No matching packed line means adding these facts could neither claim a
        # card nor divert an existing allocation. No hypothetical replacement id
        # is constructed to make the candidate pass the stable-id checks.
        return _packing(snapshot, space, stock)


def review(change_id, space, snapshot, store, rows=None):
    _identifier(change_id)
    rows = store.undo_audit(change_id) if rows is None else rows
    source, restored = source_record(rows, space)
    label = rules.token_label(restored)
    if snapshot.stale or not snapshot.persisted or not isinstance(snapshot.revision, str) or not snapshot.revision \
            or not isinstance(snapshot.decks_revision, str) or not snapshot.decks_revision:
        raise UndoConflict("The current token cards cannot be checked. Reload Tokens.", label)
    latest_reader = getattr(store, "undo_token_latest", None)
    if not callable(latest_reader):
        raise UndoUnsupported("This token review needs a complete current token audit fence.")
    latest = latest_reader(space)
    if type(latest) is not int or latest != source["id"] \
            or store.undo_latest(TOKENS, source["key"]) != source["id"]:
        raise UndoConflict("The token cards were touched after that removal. Nothing was restored.", label)
    _verified_printing(restored)
    try:
        stock, layout = _stock(snapshot, source, restored, store, space)
        allocations, capacities, held = _packing_evidence(snapshot, space, stock, _cells(restored))
        receipt = [change_id, source, latest, files.rendered_sha256(snapshot.token_set(space)), stock, layout,
                   allocations, capacities, held, snapshot.revision, snapshot.decks_revision, IDENTITY_POLICY]
        digest = hashlib.sha256(json.dumps(receipt, ensure_ascii=False, sort_keys=True,
                                           separators=(",", ":")).encode("utf-8")).hexdigest()
    except inventory.Unavailable:
        raise
    except Exception:
        raise UndoConflict("The removed token record cannot safely be reviewed here. Check its identity and packed cards in Tokens.", label) from None
    return {"change_id": change_id, "kind": "tokens", "space": space, "action": ACTION, "read_only": True,
            "current": None, "restore": restored, "label": label, "expect": digest,
            "identity_policy": IDENTITY_POLICY, "physical_confirmation_required": True, "packing_restored": False}


def latest(cur, space):
    """One own-space audit id, never a change message, reason or projected row."""
    found = cur.execute("select id from audit.row_change where table_name='token_card' and "
                        "(before->>'space_id'=%s or after->>'space_id'=%s) order by id desc limit 1",
                        (space, space)).fetchone()
    return found[0] if found else None


def read_review(store, change_id, space, lock):
    """Collect one fresh review under the ordinary inventory claim; no audit/DML."""
    from decklab.db import space_members
    _identifier(change_id)
    if not isinstance(space, str) or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", space):
        raise UndoMissing()
    def work(connection):
        with connection.transaction():
            connection.execute(READ_ONLY)
            lock(connection)
            # Admission's FOR KEY SHARE cannot run in a READ ONLY transaction.
            # The exclusive inventory claim also serializes member departures;
            # plain membership reads under it establish the same target boundary.
            if space_members.departed(connection, {space}):
                raise UndoMissing()
            found = connection.execute("select exists(select 1 from space where id=%s), "
                "(%s='home' or exists(select 1 from profile where id=%s and space_id=%s))",
                (space, space, space, space)).fetchone()
            if not isinstance(found, tuple) or len(found) != 2 or any(value is not True for value in found):
                raise UndoMissing()
            previous = getattr(store._applying, "connection", None)
            store._applying.connection = connection
            try:
                snapshot = store.load(conn=connection)
                return review(change_id, space, snapshot, store)
            finally:
                store._applying.connection = previous
    return store._call(work)
