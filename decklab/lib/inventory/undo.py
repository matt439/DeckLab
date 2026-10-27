"""Guarded inverse of one supported audited row, never a historical rewrite.

Audit row shape is authoritative; messages cannot prove which command made a change.
Same-identity edits, unheld nonbasic collection insertions and confirmed, verified
collection deletions, metadata batches and unheld verified token insertions are supported. Every check runs again in the ordinary
PostgreSQL inventory transaction before its pure edit helper is called.
"""
import hashlib
import io
import json
import re

from . import Summary, backend, current, files, register, rules
from .model import refuse_unreadable_tokens
from decklab.lib.state import Conflict, Invalid

COLLECTION = "collection_card"
TOKENS = "token_card"
COLLECTION_KEYS = {"space_id", "set_code", "collector_number", "finish"}
COLLECTION_FIELDS = {"name", "set_code", "collector_number", "finish", "quantity", "condition", "language", "notes", "space_id"}
TOKEN_FIELDS = set(rules.TOKEN_FIELDS) - {"set"} | {"set_code", "space_id", "id", "position"}
SUPPORTED = {COLLECTION: ("collection", {"quantity", "condition", "language", "notes"}),
             TOKENS: ("tokens", {"quantity", "notes"})}
SHA = re.compile(r"[a-f0-9]{64}")
BATCH_MAX = 50
BATCH_FIELDS = ("condition", "language", "notes")
BATCH_UPDATE_FIELDS = ("quantity", *BATCH_FIELDS)
BATCH_ACTIONS = ("batch_metadata", "batch_update", "batch_add", "batch_remove")


class UndoMissing(Invalid):
    def __init__(self):
        super().__init__("That change is not available to undo.")


class UndoUnsupported(Invalid):
    pass


class UndoConflict(Conflict):
    def __init__(self, message, label=None):
        super().__init__(message)
        self.label = label
        self.conflicts = [{"label": label, "reason": message}] if label else []


def _identifier(value):
    if type(value) is not int or not 1 <= value < 10 ** 18:
        raise UndoMissing()


def _ordinary(raw, table):
    fields = rules.FIELDS if table == COLLECTION else rules.TOKEN_FIELDS
    out = {field: raw["set_code" if field == "set" else field] for field in fields}
    if any(not isinstance(value, str) for field, value in out.items() if field != "quantity") \
            or type(out["quantity"]) is not int or not 1 <= out["quantity"] <= 9999:
        raise UndoUnsupported("The recorded row cannot be restored by this Undo tool.")
    if table == TOKENS:
        try:
            rendered = rules.token_page_row(out)
        except ValueError:
            raise UndoUnsupported("The recorded token facts require the normal token editor.") from None
        normalized = {**rendered, "quantity": int(rendered["quantity"])}
        if normalized != out:
            raise UndoUnsupported("The recorded token facts require the normal token editor.")
    return out


def _source(rows, space):
    # A capped, grouped or partially visible change is never sufficient evidence.
    if not isinstance(rows, list) or len(rows) != 1:
        raise UndoMissing()
    row = rows[0]
    old, new = row.get("before"), row.get("after")
    if row.get("table") == TOKENS and row.get("op") == "INSERT" and old is None:
        if not isinstance(new, dict) or new.get("space_id") != space:
            raise UndoMissing()
        if set(new) != TOKEN_FIELDS:
            raise UndoUnsupported("The inserted token row has an unsupported schema.")
        _identifier(row.get("id"))
        if not isinstance(row.get("key"), dict) or set(row["key"]) != {"id"} \
                or type(new["id"]) is not int or not 1 <= new["id"] < 10 ** 18 or row["key"]["id"] != new["id"] \
                or type(row["key"]["id"]) is not int or type(new["position"]) is not int or new["position"] < 0:
            raise UndoUnsupported("The original token identity cannot be checked.")
        wanted = _ordinary(new, TOKENS)
        try:
            rules.validate_token_row(_cells(wanted), "Token Undo", incoming=True)
        except ValueError:
            raise UndoUnsupported("Verify the token card's physical pairing in Tokens before undoing its addition.") from None
        return row, wanted, None
    if row.get("table") == COLLECTION and row.get("op") == "INSERT" and old is None:
        if not isinstance(new, dict) or new.get("space_id") != space:
            raise UndoMissing()
        if set(new) != COLLECTION_FIELDS:
            raise UndoUnsupported("The inserted collection row has an unsupported schema.")
        _identifier(row.get("id"))
        if not isinstance(row.get("key"), dict) or set(row["key"]) != COLLECTION_KEYS \
                or any(row["key"][key] != new[key] for key in COLLECTION_KEYS):
            raise UndoUnsupported("The original collection identity cannot be checked.")
        return row, _ordinary(new, COLLECTION), None
    if row.get("table") == COLLECTION and row.get("op") == "DELETE" and new is None:
        if not isinstance(old, dict) or old.get("space_id") != space:
            raise UndoMissing()
        if set(old) != COLLECTION_FIELDS:
            raise UndoUnsupported("The deleted collection row has an unsupported schema.")
        _identifier(row.get("id"))
        if not isinstance(row.get("key"), dict) or set(row["key"]) != COLLECTION_KEYS \
                or any(row["key"][key] != old[key] for key in COLLECTION_KEYS):
            raise UndoUnsupported("The original collection identity cannot be checked.")
        return row, None, _ordinary(old, COLLECTION)
    if row.get("table") not in SUPPORTED or not isinstance(old, dict) or not isinstance(new, dict) \
            or old.get("space_id") != space or new.get("space_id") != space:
        raise UndoMissing()
    table = row["table"]
    fields = COLLECTION_FIELDS if table == COLLECTION else TOKEN_FIELDS
    if row.get("op") != "UPDATE" or set(old) != fields or set(new) != fields:
        raise UndoUnsupported("Only one supported row update can be undone here.")
    _identifier(row.get("id"))
    if not isinstance(row.get("key"), dict):
        raise UndoUnsupported("The original row identity cannot be checked.")
    changed = {key for key in fields if old[key] != new[key]}
    if not changed or changed - SUPPORTED[table][1]:
        raise UndoUnsupported("This update changes facts outside the first Undo slice.")
    if table == COLLECTION:
        if set(row["key"]) != COLLECTION_KEYS or any(row["key"][key] != new[key] for key in COLLECTION_KEYS):
            raise UndoUnsupported("The original collection identity cannot be checked.")
    elif set(row["key"]) != {"id"} or type(new["id"]) is not int or row["key"]["id"] != new["id"] \
            or type(new["position"]) is not int or new["position"] < 0:
        raise UndoUnsupported("The original token identity cannot be checked.")
    return row, _ordinary(new, table), _ordinary(old, table)


def _label(table, row):
    return (f"{row['name']} ({row['set'].upper()} {row['collector_number']}, {row['finish']})"
            if table == COLLECTION else rules.token_label(row))


def _cells(row):
    return {**row, "quantity": str(row["quantity"])}


def restored_row(snapshot, plan):
    """The actual stored inverse row, without SQL identity/position fields, for a receipt."""
    table = COLLECTION if plan["kind"] == "collection" else TOKENS
    sheet = snapshot.collection(plan["space"]) if table == COLLECTION else snapshot.token_set(plan["space"])
    if plan.get("action") == "remove":
        if table == TOKENS:
            from .undo_tokens import ordered_rows
            if ordered_rows(sheet) != plan["token_rows_after"] or any(row.id == plan["token_row_id"] for row in sheet.rows):
                raise UndoConflict("The removed token row's absence cannot be confirmed. Reload Tokens.", plan["label"])
            return None
        if sheet.error is not None or sheet.strict_error is not None or sheet.csv_error is not None \
                or not sheet.exists and sheet.rows \
                or any(rules.ident(row.as_dict()) == rules.ident(plan["current"]) for row in sheet.rows):
            raise UndoConflict("The removed row's absence cannot be confirmed. Reload the list.", plan["label"])
        return None
    if plan.get("action") == "add" and (not sheet.exists or sheet.error is not None \
            or sheet.strict_error is not None or sheet.csv_error is not None):
        raise UndoConflict("The restored row cannot be confirmed. Reload the list.", plan["label"])
    matches = [row for row in sheet.rows if (rules.ident(row.as_dict()) == rules.ident(plan["restore"]) if table == COLLECTION
               else row.id == plan["key"]["id"])]
    if len(matches) != 1:
        raise UndoConflict("The restored row cannot be confirmed. Reload the list.", plan["label"])
    found = matches[0].as_dict()
    found["quantity"] = int(found["quantity"])
    return found


def _current_row(snapshot, source, wanted, space, label):
    from decklab.lib.tokens import ops as token_ops
    table = source["table"]
    sheet = snapshot.collection(space) if table == COLLECTION else snapshot.token_set(space)
    if not sheet.exists or sheet.error is not None or sheet.strict_error is not None:
        raise UndoConflict("The current list cannot be checked. Open its editor before undoing this row.", label)
    if table == COLLECTION:
        matching = [row for row in sheet.rows if rules.ident(row.as_dict()) == rules.ident(wanted)]
    else:
        refuse_unreadable_tokens(sheet)
        matching = [row for row in sheet.rows if token_ops.match_key(row.as_dict()) == token_ops.match_key(_cells(wanted))]
    if len(matching) != 1:
        raise UndoConflict("This row was removed, changed or is ambiguous. Nothing was undone.", label)
    row = matching[0]
    if table == TOKENS and row.id != source["after"]["id"]:
        raise UndoConflict("The original token row was replaced. Nothing was undone.", label)
    actual = row.as_dict()
    actual["quantity"] = int(actual["quantity"])
    if actual != wanted:
        raise UndoConflict("This row changed after the selected change. Nothing was undone.", label)


def _inverse(snapshot, source, wanted, restore, space):
    if source["table"] == COLLECTION:
        from . import ops_collection
        if wanted is None:
            return ops_collection.add(snapshot, space, restore,
                                      sha256=files.rendered_sha256(snapshot.collection(space)))
        if restore is None:
            return ops_collection.remove(snapshot, space, list(rules.ident(wanted)),
                                         sha256=files.rendered_sha256(snapshot.collection(space)),
                                         expect_decks_revision=snapshot.decks_revision)
        return ops_collection.edit(snapshot, space, list(rules.ident(wanted)), restore,
                                   sha256=files.rendered_sha256(snapshot.collection(space)))
    from decklab.lib.tokens import ops as token_ops
    if restore is None:
        from . import undo_tokens
        return undo_tokens.remove(snapshot, source, wanted, space, _label(TOKENS, wanted))
    return token_ops.edit(snapshot, space=space, base=_cells(wanted), row=_cells(restore),
                          sha256=files.rendered_sha256(snapshot.token_set(space)), separate=True)


def _home_products(snapshot, space):
    """An unknown kept-intact choice can hide a physical holder; never treat it as free."""
    if space != "home":
        return set()
    from decklab.lib import pool
    products, sheet = snapshot.products, snapshot.status
    if not products and not sheet.rows and not sheet.error and not sheet.strict_error:
        return set()
    if not sheet.exists or sheet.error or sheet.strict_error or sheet.csv_error:
        raise ValueError("Unknown product status")
    files_seen, statuses = set(), {}
    for product in products:
        if product.file in files_seen:
            raise ValueError("Ambiguous product")
        files_seen.add(product.file)
    for row in sheet.rows:
        file = row.text("file")
        if file in statuses:
            raise ValueError("Ambiguous product status")
        status, intact = row.text("status"), row.text("intact")
        if status not in pool.PRODUCT_STATUSES or intact not in ("", "yes", "no") or status == "owned" and not intact:
            raise ValueError("Unknown kept-intact choice")
        statuses[file] = (status, intact)
    if files_seen - statuses.keys():
        raise ValueError("Missing product status")
    intact = {file.removesuffix(".csv") for file, value in statuses.items() if value == ("owned", "yes")}
    if {f"{stem}.csv" for stem in intact} - files_seen:
        raise ValueError("Missing intact product")
    return intact


def _known_decks(snapshot, space):
    """A missing/ambiguous status is not proof that a possible physical holder is unbuilt."""
    from decklab.lib import decks
    from decklab.lib.decks import assembled
    from .ops_decks import parsed_deck
    found = []
    for stored in snapshot.decks.values():
        if stored.space != space:
            continue
        deck = parsed_deck(stored)
        if deck is None or sum(field.key.casefold() == "status" for field in deck.header) != 1 or deck.status not in decks.STATUSES:
            raise ValueError("Unknown deck status")
        if deck.status == "built":
            fields = [field for field in deck.header if field.key.casefold() == "built version"]
            if len(fields) > 1 or fields and deck.built_version is None:
                raise ValueError("Unknown built list version")
            assembled.get(deck)
            assembled.generation(deck)
        found.append(deck)
    return found


def _reduction(snapshot, after, table, space, label, source):
    from decklab.lib import decks, inventory, pool, tokens
    try:
        intact = _home_products(snapshot, space)
        known_decks = _known_decks(snapshot, space)
    except Exception:
        raise UndoConflict("The products' physical storage choices cannot be checked. Use the normal editor.", label) from None
    if table == COLLECTION:
        from decklab.lib.api.collection_guards import reduction_warnings
        try:
            warnings = reduction_warnings(snapshot, after, space)
            with inventory.pinned(snapshot):
                held = pool.load_pool(space)
            uncertain = bool(getattr(held, "warning_decks", {})) or any(getattr(item, "standin_warnings", []) for item in held.in_use)
        except Exception:
            raise UndoConflict("Cards held by built decks or intact products cannot be checked. Use the normal editor.", label) from None
        if warnings or uncertain:
            raise UndoConflict("This reduction may remove cards held in built decks or intact products. Use the normal editor.", label)
        return
    from decklab.lib.tokens import ops as token_ops
    try:
        with inventory.pinned(snapshot):
            for deck in known_decks:
                if deck.status == "built" and not decks.has_token_cards(deck):
                    raise ValueError("Unknown packed tokens")
            warnings = []
            if space == "home":
                from decklab.lib.tokens import products
                records = products.records(warnings, snapshot)
                if {f"product/{stem}" for stem in intact} - records.keys() \
                        or any(not record["written"] or record["error"] for record in records.values()):
                    raise ValueError("Unknown product packing")
            before_tokens = tokens.read(space=space)
            before_holds = tokens.reserve.holds(before_tokens, space=space, warnings=warnings)
            stored_rows = snapshot.token_set(space).rows
            if len(stored_rows) != len(before_tokens.rows) or any(
                    token_ops.match_key(a.as_dict()) != token_ops.match_key(b)
                    for a, b in zip(stored_rows, before_tokens.rows)):
                raise ValueError("Ambiguous packed token rows")
            target = next(index for index, row in enumerate(stored_rows) if row.id == source["after"]["id"])
            new_quantity = next(row.qty for row in after.token_set(space).rows if row.id == source["after"]["id"])
            held_before = sum(holder["rows"].get(target, 0) for holder in before_holds.values())
            if held_before > new_quantity or any(holder.get("error") or holder.get("unmatched") for holder in before_holds.values()):
                raise ValueError("Current packed copies cannot be removed or reassigned")
            with inventory.pinned(after):
                inv = tokens.read(space=space)
                holds = tokens.reserve.holds(inv, space=space, warnings=warnings)
            quantities = [int(row["quantity"]) for row in inv.rows]
            held = {}
            for holder in holds.values():
                if holder.get("error") or holder.get("unmatched"):
                    raise ValueError("Unknown packed tokens")
                for index, quantity in holder["rows"].items():
                    held[index] = held.get(index, 0) + quantity
            if warnings or any(quantity > quantities[index] for index, quantity in held.items()):
                raise ValueError("Packed tokens exceed remaining physical cards")
    except Exception:
        raise UndoConflict("Packed token quantities cannot safely be reduced here. Use the normal token editor.", label) from None


def _insert_removal(snapshot, after, wanted, space, label, source):
    """No aggregate surplus or probable printing hint proves this row physically free."""
    from decklab.lib import decks, inventory, pool
    from decklab.lib.api.collection_guards import _check_holders
    from decklab.lib.decks import assembled, standins
    unresolved = {}
    try:
        canonical = pool._canonical(wanted["name"], "Undo", unresolved)
    except Exception:
        raise UndoConflict("The inserted card's physical identity cannot be checked. Use the Collection editor.", label) from None
    if decks.is_basic_land(canonical):
        raise UndoUnsupported("Use the Collection editor to remove tracked basic lands.")
    if unresolved:
        raise UndoConflict("The inserted card's physical identity cannot be checked. Use the Collection editor.", label)
    _reduction(snapshot, after, COLLECTION, space, label, source)
    try:
        for deck in _known_decks(snapshot, space):
            if deck.status != "built":
                continue
            if sum(field.key.casefold() == standins.STAND_INS_FIELD.casefold() for field in deck.header) > 1:
                raise ValueError("Ambiguous installed markers")
            installed = standins.installed_for(deck)
            if installed:
                if installed["version"] != assembled.version(deck) or any(row["using"] is None for row in installed["cards"]):
                    raise ValueError("Unknown physical markers")
                standins.validate_rows(installed["cards"], assembled.sections(deck))
        with inventory.pinned(snapshot):
            held = pool.load_pool(space)
            _check_holders(snapshot, space, held)
        if held.unresolved or held.warning_decks or any(holder.standin_warnings for holder in held.in_use):
            raise ValueError("Uncertain physical holders")
        if any(holder.cards[canonical] > 0 for holder in held.in_use):
            raise UndoConflict("This card is used by a built deck or intact product. Use the Collection editor.", label)
    except UndoConflict:
        raise
    except Exception:
        raise UndoConflict("Physical holders cannot safely be checked. Use the Collection editor.", label) from None


def removal_reason(value):
    """The user's explicit reason, normalized like Collection's removal note."""
    from decklab.lib import decks
    if not isinstance(value, str) or len(value) > 200:
        raise Invalid("Removing an added row needs a reason of at most 200 characters.")
    reason = decks.clean_title(value)
    if not reason or re.search(r"[\x00-\x1f\x7f]", reason):
        raise Invalid("Give a nonblank reason for removing the added row.")
    return reason


def _absent_row(snapshot, restore, space, label):
    sheet = snapshot.collection(space)
    if sheet.error is not None or sheet.strict_error is not None or sheet.csv_error is not None \
            or not sheet.exists and sheet.rows:
        raise UndoConflict("The current collection cannot be checked. Use the Collection editor.", label)
    if any(rules.ident(row.as_dict()) == rules.ident(restore) for row in sheet.rows):
        raise UndoConflict("That printing is already in the collection. Nothing was restored.", label)


def _deleted_row(restore):
    """Validate exact historical facts without tidying them or guessing a printing."""
    from decklab.lib import cards
    try:
        cells = _cells(restore)
        checked = rules.parse_cards(io.StringIO(rules.collection_csv_bytes([cells]).decode("utf-8"), newline=""),
                                    "Undo", existing=True)
        if checked != [cells] or rules.ordinary_basic(cells):
            raise ValueError("Unsupported historical row")
        printing = cards.printing(restore["set"], restore["collector_number"])
        if cards.resolve(restore["name"]) != restore["name"] or not isinstance(printing, dict) \
                or not isinstance(cards.printing_card(restore["set"], restore["collector_number"]), dict) \
                or cards.resolve(printing.get("name")) != restore["name"] \
                or not isinstance(printing.get("games"), list) or not isinstance(printing.get("finishes"), list) \
                or any(not isinstance(value, str) for value in [*printing["games"], *printing["finishes"]]) \
                or printing.get("digital") is not False or "paper" not in printing.get("games", []) \
                or restore["finish"] not in printing.get("finishes", []):
            raise ValueError("Historical printing cannot be verified")
    except Exception:
        raise UndoUnsupported("The exact deleted row cannot be restored unchanged with the current card data. Use the Collection editor.") from None


def _added_row(after, summary, restore, space, label):
    counts = summary.counts or {}
    expected = {"added_rows": 1, "bumped_rows": 0, "skipped_basics": 0, "cards": restore["quantity"]}
    if any(type(counts.get(key)) is not int or counts[key] != value for key, value in expected.items()) \
            or counts.get("merged") is not False:
        raise UndoConflict("The deleted row could not be restored exactly. Nothing was saved.", label)
    actual = restored_row(after, {"kind": "collection", "space": space, "action": "add", "restore": restore, "label": label})
    if actual != restore:
        raise UndoConflict("The deleted row would change during restoration. Use the Collection editor.", label)


def _row_map(sheet, label):
    if not sheet.exists or sheet.error is not None or sheet.strict_error is not None or sheet.csv_error is not None:
        raise UndoConflict("The collection cannot be checked. Use the Collection editor.", label)
    result = {}
    for row in sheet.rows:
        values = row.as_dict()
        key = rules.ident(values)
        if key in result:
            raise UndoConflict("The collection has an ambiguous printing. Nothing was undone.", label)
        values["quantity"] = int(values["quantity"])
        result[key] = values
    return result


def restored_rows(snapshot, plan):
    """Actual full rows looked up by identity, returned in the preview's order."""
    found = _row_map(snapshot.collection(plan["space"]), plan["label"])
    restored = []
    for item in plan["rows"]:
        key = rules.ident(item["restore"])
        if key not in found or found[key] != item["restore"]:
            raise UndoConflict("The restored collection rows cannot be confirmed. Reload the collection.", plan["label"])
        restored.append({"key": dict(zip(("set", "collector_number", "finish"), key)), "row": found[key]})
    return restored


def _batch_inverse(snapshot, rows, space, label):
    from . import changes, ops_collection
    after, summary = ops_collection.apply_rows(snapshot, space,
        edits=[(list(rules.ident(item["current"])), item["restore"]) for item in rows], removals=(),
        sha256=files.rendered_sha256(snapshot.collection(space)), expect_decks_revision=snapshot.decks_revision)
    try:
        settled = changes.prepare(snapshot, after)
        counts = summary.counts or {}
        if type(counts.get("edited")) is not int or counts["edited"] != len(rows) \
                or type(counts.get("removed")) is not int or counts["removed"] != 0:
            raise ValueError("Unexpected inverse scope")
        before_rows = _row_map(snapshot.collection(space), label)
        actual = _row_map(settled.collection(space), label)
        expected = {**before_rows, **{rules.ident(item["restore"]): item["restore"] for item in rows}}
        if actual != expected or set(settled.collections) != set(snapshot.collections) \
                or any(settled.collection(owner) != snapshot.collection(owner) for owner in snapshot.collections if owner != space) \
                or settled != snapshot.replace(collections=settled.collections):
            raise ValueError("Unexpected inverse effect")
    except Exception:
        raise UndoConflict("The complete collection change cannot be restored exactly. Nothing was saved.", label) from None
    return settled, summary


def _batch_reductions(snapshot, after, rows, space, label):
    """Prove aggregate capacity against the whole candidate, never printing freedom."""
    if not any(item["restore"]["quantity"] < item["current"]["quantity"] for item in rows):
        return
    from decklab.lib import inventory, pool
    from decklab.lib.api.collection_guards import _check_holders
    from decklab.lib.decks import assembled, standins
    try:
        for deck in _known_decks(snapshot, space):
            if deck.status != "built":
                continue
            if sum(field.key.casefold() == standins.STAND_INS_FIELD.casefold() for field in deck.header) > 1:
                raise ValueError("Ambiguous installed markers")
            installed = standins.installed_for(deck)
            if installed:
                if installed["version"] != assembled.version(deck) or any(row["using"] is None for row in installed["cards"]):
                    raise ValueError("Unknown physical markers")
                standins.validate_rows(installed["cards"], assembled.sections(deck))
        with inventory.pinned(snapshot):
            held = pool.load_pool(space)
            _check_holders(snapshot, space, held)
        if held.unresolved or held.warning_decks or any(holder.standin_warnings for holder in held.in_use):
            raise ValueError("Uncertain physical holders")
    except Exception:
        raise UndoConflict("Physical holders cannot safely be checked. Use the Collection editor.", label) from None
    # COLLECTION ignores source and evaluates every reduced canonical name. One
    # complete candidate catches cumulative reductions and cross-printing offsets.
    _reduction(snapshot, after, COLLECTION, space, label, {"table": COLLECTION})


def _batch_add_inverse(snapshot, rows, space, label):
    """One pure candidate; ordinary adds must preserve every former cell exactly."""
    from . import changes, ops_collection
    for item in rows:
        _absent_row(snapshot, item["restore"], space, item["label"])
    sheet = snapshot.collection(space)
    before_rows = _row_map(sheet, label) if sheet.exists else {}
    after = snapshot
    for item in rows:
        after, summary = ops_collection.add(after, space, item["restore"],
                                             sha256=files.rendered_sha256(after.collection(space)))
        _added_row(after, summary, item["restore"], space, item["label"])
    try:
        settled = changes.prepare(snapshot, after)
        expected = {**before_rows, **{rules.ident(item["restore"]): item["restore"] for item in rows}}
        if _row_map(settled.collection(space), label) != expected \
                or set(settled.collections) != set(snapshot.collections) | {space} \
                or any(settled.collection(owner) != snapshot.collection(owner) for owner in snapshot.collections if owner != space) \
                or settled != snapshot.replace(collections=settled.collections):
            raise ValueError("Unexpected restoration effect")
    except Exception:
        raise UndoConflict("The complete deleted collection rows cannot be restored exactly. Nothing was saved.", label) from None
    return settled, Summary(f"restore {len(rows)} deleted collection rows", counts={"added_rows": len(rows), "bumped_rows": 0,
        "skipped_basics": 0, "merged": False, "cards": sum(item["restore"]["quantity"] for item in rows)})


def _batch_delete_review(change_id, space, snapshot, store, raw):
    if any(row.get("table") != COLLECTION or row.get("op") != "DELETE" or not isinstance(row.get("before"), dict)
           or row["before"].get("space_id") != space or row.get("after") is not None for row in raw):
        raise UndoMissing()
    rows, keys, ids = [], set(), set()
    for record in raw:
        source, _, restore = _source([record], space)
        key, rid = rules.ident(restore), source["id"]
        if key in keys or rid in ids:
            raise UndoUnsupported("A collection batch must name each original row exactly once.")
        keys.add(key)
        ids.add(rid)
        rows.append({"key": source["key"], "row_change_id": rid, "current": None, "restore": restore})
    for item in rows:
        item["label"] = _label(COLLECTION, item["restore"])
        if store.undo_latest(COLLECTION, item["key"]) != item["row_change_id"]:
            raise UndoConflict("A row was touched after the selected change. Nothing was restored.", item["label"])
        _absent_row(snapshot, item["restore"], space, item["label"])
        _deleted_row(item["restore"])
        if "\0" in item["restore"]["notes"]:
            raise UndoUnsupported("The recorded notes cannot be restored as database text.")
    label = f"{len(rows)} deleted collection rows"
    _batch_add_inverse(snapshot, rows, space, label)
    receipt = json.dumps([change_id, raw, snapshot.revision, snapshot.decks_revision], ensure_ascii=False,
                         sort_keys=True, separators=(",", ":"))
    return {"change_id": change_id, "kind": "collection", "space": space, "action": "batch_add",
            "physical_confirmation_required": True, "row_count": len(rows), "rows": rows, "label": label,
            "expect": hashlib.sha256(receipt.encode("utf-8")).hexdigest()}


def _remaining_collection(snapshot, space, label):
    sheet = snapshot.collection(space)
    if sheet.error is not None or sheet.strict_error is not None or sheet.csv_error is not None or not sheet.exists and sheet.rows:
        raise UndoConflict("The remaining collection cannot be checked. Reload Collection.", label)
    return _row_map(sheet, label) if sheet.exists else {}


def removed_keys(snapshot, plan):
    """Confirm actual target absence and all survivors before issuing a removal receipt."""
    actual = _remaining_collection(snapshot, plan["space"], plan["label"])
    if actual != plan["collection_rows_after"] or any(rules.ident(item["current"]) in actual for item in plan["rows"]):
        raise UndoConflict("The removed rows and remaining collection cannot be confirmed. Reload Collection.", plan["label"])
    return [{field: item["current"][field] for field in ("set", "collector_number", "finish")} for item in plan["rows"]]


def _batch_remove_inverse(snapshot, rows, space, label):
    from . import changes, ops_collection
    before_rows = _row_map(snapshot.collection(space), label)
    after, summary = ops_collection.apply_rows(snapshot, space, edits=(),
        removals=[list(rules.ident(item["current"])) for item in rows],
        sha256=files.rendered_sha256(snapshot.collection(space)), expect_decks_revision=snapshot.decks_revision)
    try:
        settled = changes.prepare(snapshot, after)
        counts = summary.counts or {}
        expected = {key: row for key, row in before_rows.items() if key not in {rules.ident(item["current"]) for item in rows}}
        namespaces = set(snapshot.collections) if expected else set(snapshot.collections) - {space}
        if type(counts.get("edited")) is not int or counts["edited"] != 0 \
                or type(counts.get("removed")) is not int or counts["removed"] != len(rows) \
                or _remaining_collection(settled, space, label) != expected or set(settled.collections) != namespaces \
                or any(settled.collection(owner) != snapshot.collection(owner) for owner in snapshot.collections if owner != space) \
                or settled != snapshot.replace(collections=settled.collections):
            raise ValueError("Unexpected removal effect")
    except Exception:
        raise UndoConflict("The complete collection batch cannot be removed exactly. Nothing was saved.", label) from None
    return settled, summary


def _batch_insert_review(change_id, space, snapshot, store, raw):
    if any(row.get("table") != COLLECTION or row.get("op") != "INSERT" or row.get("before") is not None
           or not isinstance(row.get("after"), dict) or row["after"].get("space_id") != space for row in raw):
        raise UndoMissing()
    rows, keys, ids = [], set(), set()
    for record in raw:
        source, wanted, _ = _source([record], space)
        key, rid = rules.ident(wanted), source["id"]
        if key in keys or rid in ids:
            raise UndoUnsupported("A collection batch must name each original row exactly once.")
        keys.add(key)
        ids.add(rid)
        rows.append({"key": source["key"], "row_change_id": rid, "current": wanted, "restore": None})
    for item in rows:
        item["label"] = _label(COLLECTION, item["current"])
        if store.undo_latest(COLLECTION, item["key"]) != item["row_change_id"]:
            raise UndoConflict("A row was touched after the selected change. Nothing was removed.", item["label"])
        _current_row(snapshot, {"table": COLLECTION}, item["current"], space, item["label"])
    label = f"{len(rows)} added collection rows"
    after, _ = _batch_remove_inverse(snapshot, rows, space, label)
    for item in rows:
        _insert_removal(snapshot, after, item["current"], space, item["label"], {"table": COLLECTION})
    receipt = json.dumps([change_id, raw, snapshot.revision, snapshot.decks_revision], ensure_ascii=False,
                         sort_keys=True, separators=(",", ":"))
    return {"change_id": change_id, "kind": "collection", "space": space, "action": "batch_remove", "reason_required": True,
            "row_count": len(rows), "rows": rows, "label": label, "collection_rows_after": _remaining_collection(after, space, label),
            "expect": hashlib.sha256(receipt.encode("utf-8")).hexdigest()}


def _batch_review(change_id, space, snapshot, store):
    reader = getattr(store, "undo_audit_batch", None)
    raw = reader(change_id) if callable(reader) else None
    if not isinstance(raw, list) or not 2 <= len(raw) <= BATCH_MAX:
        raise UndoMissing()
    if all(isinstance(row, dict) and row.get("op") == "DELETE" for row in raw):
        return _batch_delete_review(change_id, space, snapshot, store, raw)
    if all(isinstance(row, dict) and row.get("op") == "INSERT" for row in raw):
        return _batch_insert_review(change_id, space, snapshot, store, raw)
    # Ownership is a separate first pass. Never diagnose an own row before a
    # later hidden/unknown row has made the entire source unavailable.
    if any(not isinstance(row, dict) or row.get("table") != COLLECTION or row.get("op") != "UPDATE"
           or not isinstance(row.get("before"), dict) or not isinstance(row.get("after"), dict)
           or row["before"].get("space_id") != space or row["after"].get("space_id") != space for row in raw):
        raise UndoMissing()
    rows, keys, ids = [], set(), set()
    quantity_changed = False
    for record in raw:
        source, wanted, restore = _source([record], space)
        changed = {key for key in wanted if wanted[key] != restore[key]}
        if not changed or changed - set(BATCH_UPDATE_FIELDS):
            raise UndoUnsupported("Only positive quantity, condition, language and notes updates can be undone in a batch.")
        quantity_changed = quantity_changed or "quantity" in changed
        if "notes" in changed:
            # Historical text is restored verbatim, not run through fresh-input
            # trimming/length/formula policy. PostgreSQL must still represent it.
            try:
                for value in (wanted["notes"], restore["notes"]):
                    if "\0" in value:
                        raise ValueError("NUL is not PostgreSQL text")
                    value.encode("utf-8")
            except (ValueError, UnicodeError):
                raise UndoUnsupported("The recorded notes cannot be restored as database text.") from None
        key, rid = rules.ident(wanted), source["id"]
        if key in keys or rid in ids:
            raise UndoUnsupported("A collection batch must name each original row exactly once.")
        keys.add(key)
        ids.add(rid)
        rows.append({"key": source["key"], "row_change_id": rid, "current": wanted, "restore": restore,
                     "label": _label(COLLECTION, wanted),
                     "fields": [{"field": field, "before": wanted[field], "after": restore[field]}
                                for field in BATCH_UPDATE_FIELDS if field in changed]})
    action = "batch_update" if quantity_changed else "batch_metadata"
    label = f"Updates to {len(rows)} collection rows" if quantity_changed else f"Metadata on {len(rows)} collection rows"
    for item in rows:
        if store.undo_latest(COLLECTION, item["key"]) != item["row_change_id"]:
            raise UndoConflict("A row was touched after the selected change. Nothing was undone.", item["label"])
        _current_row(snapshot, {"table": COLLECTION}, item["current"], space, item["label"])
    after, _ = _batch_inverse(snapshot, rows, space, label)
    if quantity_changed:
        _batch_reductions(snapshot, after, rows, space, label)
    receipt = json.dumps([change_id, raw, snapshot.revision, snapshot.decks_revision], ensure_ascii=False,
                         sort_keys=True, separators=(",", ":"))
    return {"change_id": change_id, "kind": "collection", "space": space, "action": action,
            "row_count": len(rows), "rows": rows, "label": label,
            "expect": hashlib.sha256(receipt.encode("utf-8")).hexdigest()}


def review(change_id, space, snapshot=None):
    """Internal current→restore plan, only after proving the entire source is in space."""
    _identifier(change_id)
    if not isinstance(space, str) or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", space):
        raise UndoMissing()
    store = backend()
    if not callable(getattr(store, "undo_audit", None)) or not callable(getattr(store, "undo_latest", None)):
        raise UndoUnsupported("Undo is available only with the database audit trail.")
    snapshot = current() if snapshot is None else snapshot
    raw = store.undo_audit(change_id)
    if isinstance(raw, list) and len(raw) > 1:
        return _batch_review(change_id, space, snapshot, store)
    source, wanted, restore = _source(raw, space)
    label = _label(source["table"], restore if wanted is None else wanted)
    if store.undo_latest(source["table"], source["key"]) != source["id"]:
        raise UndoConflict("This row was touched after the selected change. Nothing was undone.", label)
    if wanted is None:
        _absent_row(snapshot, restore, space, label)
        _deleted_row(restore)
    else:
        _current_row(snapshot, source, wanted, space, label)
    after, inverse_summary = _inverse(snapshot, source, wanted, restore, space)
    if wanted is None:
        _added_row(after, inverse_summary, restore, space, label)
    elif restore is None and source["table"] == COLLECTION:
        _insert_removal(snapshot, after, wanted, space, label, source)
    elif restore is not None and restore["quantity"] < wanted["quantity"]:
        _reduction(snapshot, after, source["table"], space, label, source)
    receipt = json.dumps([change_id, source, snapshot.revision, snapshot.decks_revision], ensure_ascii=False,
                         sort_keys=True, separators=(",", ":"))
    result = {"change_id": change_id, "row_change_id": source["id"], "kind": SUPPORTED[source["table"]][0],
            "space": space, "key": source["key"], "current": wanted, "restore": restore, "label": label,
            "expect": hashlib.sha256(receipt.encode("utf-8")).hexdigest()}
    if wanted is None:
        result.update(action="add", physical_confirmation_required=True)
    elif restore is None:
        result.update(action="remove", reason_required=True)
        if source["table"] == TOKENS:
            from .undo_tokens import ordered_rows
            result.update(token_row_id=source["after"]["id"], token_position=source["after"]["position"],
                          token_rows_after=ordered_rows(after.token_set(space)))
    else:
        result["fields"] = [{"field": key, "before": wanted[key], "after": restore[key]}
                            for key in wanted if wanted[key] != restore[key]]
    return result


@register("inventory.undo")
def apply_undo(snapshot, *, change_id, space, expect, reason=None, confirm_owned=False):
    """Called inside the existing backend lock; source and latest audit share its connection."""
    if not isinstance(expect, str) or not SHA.fullmatch(expect):
        raise Invalid("Review this Undo before applying it.")
    plan = review(change_id, space, snapshot)
    if plan["expect"] != expect:
        raise UndoConflict("The inventory or decks changed after the Undo preview. Review it again.", plan["label"])
    if plan.get("action") in BATCH_ACTIONS:
        adding = plan["action"] == "batch_add"
        removing = plan["action"] == "batch_remove"
        if adding and confirm_owned is not True:
            raise Invalid("Confirm that you still physically own every recorded copy before restoring these rows.")
        if removing:
            reason = removal_reason(reason)
        inverse = _batch_add_inverse if adding else _batch_remove_inverse if removing else _batch_inverse
        after, summary = inverse(snapshot, plan["rows"], space, plan["label"])
        return after, Summary(f"Undo change #{change_id}: {'remove' if removing else 'restore'} {plan['label']}", {**summary.counts, "undo": 1},
                              {after.collection(space).path: ["add"] if adding else ["remove"] if removing else
                               list(BATCH_UPDATE_FIELDS if plan["action"] == "batch_update" else BATCH_FIELDS)},
                              {**(summary.extra or {}), "undo_of": change_id, "space": space, "kind": "collection",
                               "action": plan["action"], "row_count": plan["row_count"],
                               "row_change_ids": [item["row_change_id"] for item in plan["rows"]],
                               **({"confirmed_owned": True} if adding else {}), **({"undo_reason": reason} if removing else {})})
    removing = plan.get("action") == "remove"
    adding = plan.get("action") == "add"
    if removing:
        reason = removal_reason(reason)
    if adding and confirm_owned is not True:
        raise Invalid("Confirm that you still physically own every recorded copy before restoring this row.")
    table = COLLECTION if plan["kind"] == "collection" else TOKENS
    source = {"table": table}
    if removing and table == TOKENS:
        source["after"] = {"id": plan["token_row_id"], "position": plan["token_position"]}
    after, summary = _inverse(snapshot, source, plan["current"], plan["restore"], space)
    if adding:
        _added_row(after, summary, plan["restore"], space, plan["label"])
    sheet = after.collection(space) if table == COLLECTION else after.token_set(space)
    return after, Summary(f"Undo change #{change_id}: {'remove added row' if removing else 'restore'} {plan['label']}",
                          {**summary.counts, "undo": 1},
                          {sheet.path: ["add"] if adding else ["remove"] if removing else [field["field"] for field in plan["fields"]]},
                          {**(summary.extra or {}), "undo_of": change_id, "space": space,
                           "kind": plan["kind"], "row_change_id": plan["row_change_id"],
                           **({"action": "remove", "undo_reason": reason} if removing else {}),
                           **({"removed_token_row_id": plan["token_row_id"]} if removing and table == TOKENS else {}),
                           **({"action": "add", "confirmed_owned": True} if adding else {})})
