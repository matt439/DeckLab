"""Guarded inverse of one supported audited row, never a historical rewrite.

Audit row shape is authoritative; messages cannot prove which command made a change.
Same-identity edits and an unheld nonbasic collection insertion are supported. Every check runs again in
the ordinary PostgreSQL inventory transaction before its pure edit helper is called.
"""
import hashlib
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
        if table != COLLECTION or sheet.error is not None or sheet.strict_error is not None or sheet.csv_error is not None \
                or not sheet.exists and sheet.rows \
                or any(rules.ident(row.as_dict()) == rules.ident(plan["current"]) for row in sheet.rows):
            raise UndoConflict("The removed row's absence cannot be confirmed. Reload the list.", plan["label"])
        return None
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
        if restore is None:
            return ops_collection.remove(snapshot, space, list(rules.ident(wanted)),
                                         sha256=files.rendered_sha256(snapshot.collection(space)),
                                         expect_decks_revision=snapshot.decks_revision)
        return ops_collection.edit(snapshot, space, list(rules.ident(wanted)), restore,
                                   sha256=files.rendered_sha256(snapshot.collection(space)))
    from decklab.lib.tokens import ops as token_ops
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


def review(change_id, space, snapshot=None):
    """Internal current→restore plan, only after proving the entire source is in space."""
    _identifier(change_id)
    if not isinstance(space, str) or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", space):
        raise UndoMissing()
    store = backend()
    if not callable(getattr(store, "undo_audit", None)) or not callable(getattr(store, "undo_latest", None)):
        raise UndoUnsupported("Undo is available only with the database audit trail.")
    snapshot = current() if snapshot is None else snapshot
    source, wanted, restore = _source(store.undo_audit(change_id), space)
    label = _label(source["table"], wanted)
    if store.undo_latest(source["table"], source["key"]) != source["id"]:
        raise UndoConflict("This row was touched after the selected change. Nothing was undone.", label)
    _current_row(snapshot, source, wanted, space, label)
    after, _ = _inverse(snapshot, source, wanted, restore, space)
    if restore is None:
        _insert_removal(snapshot, after, wanted, space, label, source)
    elif restore["quantity"] < wanted["quantity"]:
        _reduction(snapshot, after, source["table"], space, label, source)
    receipt = json.dumps([change_id, source, snapshot.revision, snapshot.decks_revision], ensure_ascii=False,
                         sort_keys=True, separators=(",", ":"))
    result = {"change_id": change_id, "row_change_id": source["id"], "kind": SUPPORTED[source["table"]][0],
            "space": space, "key": source["key"], "current": wanted, "restore": restore, "label": label,
            "expect": hashlib.sha256(receipt.encode("utf-8")).hexdigest()}
    if restore is None:
        result.update(action="remove", reason_required=True)
    else:
        result["fields"] = [{"field": key, "before": wanted[key], "after": restore[key]}
                            for key in wanted if wanted[key] != restore[key]]
    return result


@register("inventory.undo")
def apply_undo(snapshot, *, change_id, space, expect, reason=None):
    """Called inside the existing backend lock; source and latest audit share its connection."""
    if not isinstance(expect, str) or not SHA.fullmatch(expect):
        raise Invalid("Review this Undo before applying it.")
    plan = review(change_id, space, snapshot)
    if plan["expect"] != expect:
        raise UndoConflict("The inventory or decks changed after the Undo preview. Review it again.", plan["label"])
    removing = plan.get("action") == "remove"
    if removing:
        reason = removal_reason(reason)
    table = COLLECTION if plan["kind"] == "collection" else TOKENS
    after, summary = _inverse(snapshot, {"table": table}, plan["current"], plan["restore"], space)
    sheet = after.collection(space) if table == COLLECTION else after.token_set(space)
    return after, Summary(f"Undo change #{change_id}: {'remove added row' if removing else 'restore'} {plan['label']}",
                          {**summary.counts, "undo": 1},
                          {sheet.path: ["remove"] if removing else [field["field"] for field in plan["fields"]]},
                          {**(summary.extra or {}), "undo_of": change_id, "space": space,
                           "kind": plan["kind"], "row_change_id": plan["row_change_id"],
                           **({"action": "remove", "undo_reason": reason} if removing else {})})
