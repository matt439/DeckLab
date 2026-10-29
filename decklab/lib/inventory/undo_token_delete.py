"""Review and restore one latest deleted physical token-card record under a fresh id.

The review never allocates or guesses a replacement id. Restoration is ordinary Add,
after explicit whole-count ownership confirmation; the database assigns the new id and
the same write transaction proves one exact INSERT (confirm). Existing stock, persisted
positions and every recorded packing allocation stay put; earlier packing is not reconnected.
"""
import hashlib
import json
import re

from decklab.lib import cards, decks, inventory, tokens
from decklab.lib.tokens import names, products

from . import Summary, changes, files, rules
from .undo import TOKEN_FIELDS, TOKENS, UndoConflict, UndoMissing, UndoUnsupported, _cells, _identifier, _ordinary
from .undo_tokens import _packing, ordered_rows

ACTION = "token_add"
READ_ONLY = "set transaction isolation level read committed, read only"
IDENTITY_POLICY = "fresh_id"
UNCONFIRMED = "The restored token-card row could not be confirmed. Nothing was saved."
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
    # proof stays internal: the API projects only the historical facts and the fixed policy.
    proof = {"deleted_id": source["before"]["id"], "stock": stock, "layout": layout,
             "allocations": allocations, "capacities": capacities}
    return {"change_id": change_id, "row_change_id": source["id"], "kind": "tokens", "space": space,
            "action": ACTION, "current": None, "restore": restored, "label": label, "expect": digest,
            "identity_policy": IDENTITY_POLICY, "physical_confirmation_required": True, "packing_restored": False,
            "proof": proof}


def apply(snapshot, plan, change_id, space):
    """Ordinary Add of the reviewed facts; every survivor keeps its id, facts and order.

    The new row has no database id until the database assigns one. Its INSERT, the persisted
    layout and the packing are proved again before commit (confirm)."""
    label, wanted, proof = plan["label"], plan["restore"], plan["proof"]
    try:
        sheet = snapshot.token_set(space)
        stock = ordered_rows(sheet)
        if stock != proof["stock"]:
            raise ValueError("Token stock changed after the review")
        after, summary = tokens.ops.add(snapshot, space=space, row=_cells(wanted),
                                        sha256=files.rendered_sha256(sheet) if sheet.exists else None)
        settled = changes.prepare(snapshot, after)
        rows = settled.token_set(space).rows
        # Its snapshot id (0, or a line number in a list that had none) is not the database's.
        known = {item["id"] for item in stock}
        fresh = [row for row in rows if row.id not in known]
        kept = [{"id": row.id, "row": {**row.as_dict(), "quantity": int(row.as_dict()["quantity"])}}
                for row in rows if row.id in known]
        if len(fresh) != 1 or len(rows) != len(stock) + 1 or kept != stock \
                or {**fresh[0].as_dict(), "quantity": int(fresh[0].as_dict()["quantity"])} != wanted:
            raise ValueError("Unexpected token addition effect")
        if settled != snapshot.replace(tokens=settled.tokens) or set(settled.tokens) != set(snapshot.tokens) | {space}:
            raise ValueError("Unexpected source change")
        _other_tokens(snapshot, settled, space)
        cards = sum(row["row"]["quantity"] for row in stock) + wanted["quantity"]
        counts, extra = summary.counts or {}, summary.extra or {}
        if type(counts.get("cards")) is not int or counts["cards"] != cards or extra.get("resorted") is not False:
            raise ValueError("Unexpected physical total or ordering")
    except inventory.Unavailable:
        raise
    except Exception:
        raise UndoConflict("The deleted token row cannot safely be restored here. Check its physical pairing and packed cards in Tokens.", label) from None
    return settled, Summary(f"Undo change #{change_id}: restore deleted token card {label} as a new row",
                            {**counts, "added_rows": 1, "undo": 1}, {settled.token_set(space).path: ["add"]},
                            {"undo_of": change_id, "space": space, "kind": "tokens", "row_change_id": plan["row_change_id"],
                             "action": ACTION, "confirmed_owned": True,
                             "token_restore": {**proof, "restore": wanted, "label": label}})


def _other_tokens(before, after, space):
    for owner in set(before.tokens) | set(after.tokens):
        if owner != space:
            old, new = before.token_set(owner), after.token_set(owner)
            if [(row.id, row.as_dict()) for row in old.rows] != [(row.id, row.as_dict()) for row in new.rows]:
                raise ValueError("Other token stock changed")


def restoring(summary):
    extra = summary.extra or {}
    return extra.get("action") == ACTION and extra.get("kind") == "tokens" and isinstance(extra.get("token_restore"), dict)


def confirm(before, saved, summary, actual, layout):
    """Prove the saved effect from the transaction's own audit rows and token layout.

    actual: this change set's audit rows; layout: the space's persisted id/position rows,
    both read on the write connection before commit. Any difference raises, so the
    transaction rolls back. Returns the summary with the new id in place of the proof."""
    extra = dict(summary.extra)
    proof, space = extra.pop("token_restore"), extra["space"]
    wanted = proof["restore"]
    try:
        if not isinstance(actual, list) or len(actual) != 1:
            raise ValueError("Not exactly one audited row")
        row = actual[0]
        new = row.get("after")
        if row.get("table") != TOKENS or row.get("op") != "INSERT" or row.get("before") is not None \
                or not isinstance(new, dict) or set(new) != TOKEN_FIELDS or new["space_id"] != space:
            raise ValueError("Not one own-space token INSERT")
        rid = new["id"]
        if type(rid) is not int or not 1 <= rid < 10 ** 18 or row.get("key") != {"id": rid} \
                or rid == proof["deleted_id"] or any(item["id"] == rid for item in proof["stock"]) \
                or _ordinary(new, TOKENS) != wanted:
            raise ValueError("Reused id or changed facts")
        stock = ordered_rows(saved.token_set(space))
        if [item for item in stock if item["id"] != rid] != proof["stock"] \
                or [item["row"] for item in stock if item["id"] == rid] != [wanted]:
            raise ValueError("Survivors or the restored row changed")
        if not isinstance(layout, list) or [item.get("id") for item in layout] != [item["id"] for item in stock] \
                or [item for item in layout if item.get("id") != rid] != proof["layout"] \
                or [item.get("position") for item in layout if item.get("id") == rid] != [new["position"]]:
            raise ValueError("Persisted positions moved")
        allocations, capacities, held = _packing(saved, space, stock)
        if allocations != proof["allocations"] or held.get(rid) != 0 \
                or {key: value for key, value in capacities.items() if key != rid} != proof["capacities"]:
            raise ValueError("Packed cards would move")
        _other_tokens(before, saved, space)
    except inventory.Unavailable:
        raise
    except Exception:
        raise UndoConflict(UNCONFIRMED, proof.get("label")) from None
    return Summary(summary.text, summary.counts, summary.changed, {**extra, "added_token_row_id": rid})


def confirm_in_transaction(cur, change_set, before, saved, summary):
    """PgInventory.apply's hook: this change set's rows and layout, on its own cursor."""
    actual = [{"id": rid, "table": table, "op": op, "key": key, "before": old, "after": new}
              for rid, table, op, key, old, new in cur.execute(
                  "select id,table_name,op,row_key,before,after from audit.row_change "
                  "where change_set_id=%s order by id limit 2", (change_set,)).fetchall()]
    layout = [{"id": rid, "position": position} for rid, position in cur.execute(
        "select id,position from token_card where space_id=%s order by position,id",
        (summary.extra["space"],)).fetchall()]
    return confirm(before, saved, summary, actual, layout)


def latest(cur, space):
    """One own-space audit id, never a change message, reason or projected row."""
    found = cur.execute("select id from audit.row_change where table_name='token_card' and "
                        "(before->>'space_id'=%s or after->>'space_id'=%s) order by id desc limit 1",
                        (space, space)).fetchone()
    return found[0] if found else None


def read_review(store, change_id, space, lock):
    """Collect one fresh preview under the ordinary inventory claim; no audit/DML."""
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
