"""Complete product-status-only kit inverses through ordinary kit.set, without history storage."""
import copy
import hashlib
import json

from decklab.lib import accessories, inventory
from . import Summary, changes, kit, ops_accessories, paths, rules
from .undo import SHA, UndoConflict, UndoMissing, UndoUnsupported, _identifier

ACTION = "product_kit_restore"
TABLE = "product_status"
MAX_ROWS = 50
RAW = {"file", "position", *rules.STATUS_FIELDS[1:]}
PROOF = "_product_kit_proof"
UNSUPPORTED = "Undo supports a complete change of 1–50 owned intact products' recognised shared kit only. Mixed deck/product changes need Deck History and a separate product-kit review."
CHANGED = "The products or their shared kit changed. Review this Undo again."


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode("utf-8")).hexdigest()


def raw_row(value):
    if isinstance(value, dict) and set(value) == RAW - {"token_cards"}:
        value = {**value, "token_cards": ""}   # precise additive migration0014 default
    if not isinstance(value, dict) or set(value) != RAW or type(value["position"]) is not int or not 0 <= value["position"] < 2 ** 31 \
            or any(not isinstance(cell, str) or "\0" in cell for key, cell in value.items() if key != "position") \
            or not value["file"].endswith(".csv") or not rules.SLUG.fullmatch(value["file"][:-4]) \
            or value["status"] != "owned" or value["intact"] != "yes":
        raise UndoUnsupported(UNSUPPORTED)
    try:
        json.dumps(value, ensure_ascii=False).encode("utf-8", errors="strict")
    except UnicodeError:
        raise UndoUnsupported(UNSUPPORTED) from None
    return dict(value)


def source(rows):
    if not isinstance(rows, list) or not 1 <= len(rows) <= MAX_ROWS \
            or any(not isinstance(row, dict) or row.get("table") != TABLE or row.get("op") != "UPDATE"
                   or not isinstance(row.get("before"), dict) or not isinstance(row.get("after"), dict) for row in rows):
        raise UndoMissing()
    found, ids = {}, set()
    for row in rows:
        _identifier(row.get("id"))
        old, new = raw_row(row["before"]), raw_row(row["after"])
        changed = {key for key in RAW if old[key] != new[key]}
        if not changed or changed - set(kit.FIELDS) or row.get("key") != {"file": new["file"]} \
                or old["file"] != new["file"] or new["file"] in found or row["id"] in ids:
            raise UndoUnsupported(UNSUPPORTED)
        ids.add(row["id"]); found[new["file"]] = {**copy.deepcopy(row), "before": old, "after": new}
    return found


def _status(snapshot):
    sheet = snapshot.status
    if not sheet.exists or sheet.error or sheet.strict_error or sheet.problems or sheet.columns not in (tuple(rules.STATUS_FIELDS), tuple(rules.KIT_STATUS_FIELDS)):
        raise UndoUnsupported(UNSUPPORTED)
    rows = {}
    for position, row in enumerate(sheet.rows):
        value = {**row.as_dict(), "position": position}
        if sheet.columns == tuple(rules.KIT_STATUS_FIELDS):
            value["token_cards"] = ""
        name = value.get("file")
        if not isinstance(name, str) or name in rows or set(value) != RAW:
            raise UndoUnsupported(UNSUPPORTED)
        rows[name] = value
    return rows


def _products(snapshot, names):
    output, proof = {}, {}
    for name in names:
        product = snapshot.product(name[:-4])
        if product is None or product.file != name or product.error or product.strict_error or product.problems \
                or not product.columns or not product.items:
            raise UndoUnsupported(UNSUPPORTED)
        for row in product.items:
            qty = row.text("quantity")
            if not row.text("name").strip() or not qty.isdigit() or int(qty) < 1 or any(not isinstance(value, str) for value in row.as_dict().values()):
                raise UndoUnsupported(UNSUPPORTED)
        output[name] = product.label("shopping")
        proof[name] = [product.name, product.format, list(product.columns), [row.as_dict() for row in product.items]]
    return output, proof


def _shared(snapshot, selected):
    listing = accessories.from_sheet(snapshot.accessories, strict=False)
    output = {}
    for row in selected:
        for field in kit.FIELDS:
            value = row[field]
            if not value:
                continue
            accessory = listing.rows_by_id.get(value)
            if not accessories.valid_id(value) or accessory is None or accessory["owner"] != accessories.SHARED \
                    or accessory["kind"] != field:
                raise UndoUnsupported(UNSUPPORTED)
            output[value] = dict(accessory)
    return output


def _ordinary(snapshot, rows, owners):
    token = kit.status_sha256(snapshot)
    holders = [{"id": "product/" + row["after"]["file"][:-4], "expected": token} for row in rows]
    edits = [{"holder": "product/" + row["after"]["file"][:-4], "field": field, "value": row["before"][field] or None}
             for row in rows for field in kit.FIELDS if row["before"][field] != row["after"][field]]
    try:
        after, _ = ops_accessories.set_kit(snapshot, holders=holders, changes=edits, owners=owners)
        return changes.prepare(snapshot, after)
    except (inventory.Invalid, inventory.Conflict, ValueError, TypeError, KeyError):
        raise UndoConflict(CHANGED) from None


def _capacity(snapshot):
    """Home holder certainty; another member's private deck never participates in home kit."""
    home = snapshot.replace(decks={key: deck for key, deck in snapshot.decks.items() if deck.space == "home"})
    try:
        with inventory.pinned(home):
            warnings = []
            _, strays = accessories._scan(warnings)
    except Exception:
        raise UndoUnsupported("The home kit holders cannot be checked completely. Use Sleeves & boxes to review the assignments.") from None
    if warnings or strays:
        raise UndoUnsupported("The home kit holders cannot be checked completely. Use Sleeves & boxes to review the assignments.")


def _unchanged(before, after):
    if after.replace(status=before.status, revision=before.revision, decks_revision=before.decks_revision) != before:
        raise UndoConflict("The product-kit inverse would change other data.")


def review(change_id, owners, snapshot, store):
    _identifier(change_id)
    if owners is not None and accessories.SHARED not in owners:
        raise UndoMissing()
    records = source(store.undo_audit_batch(change_id))
    if snapshot.stale or not snapshot.persisted:
        raise UndoConflict(CHANGED)
    rows = [records[name] for name in sorted(records)]
    current = _status(snapshot)
    labels, products = _products(snapshot, records)
    latest = []
    for row in rows:
        touch = store.undo_latest(TABLE, row["key"])
        if type(touch) is not int or touch != row["id"] or current.get(row["after"]["file"]) != row["after"]:
            raise UndoConflict(CHANGED)
        latest.append(touch)
    shared = _shared(snapshot, [image for row in rows for image in (row["before"], row["after"])])
    _capacity(snapshot)
    after = _ordinary(snapshot, rows, owners)
    _capacity(after)
    _unchanged(snapshot, after)
    expected = copy.deepcopy(current)
    for row in rows:
        expected[row["before"]["file"]] = row["before"]
    if _status(after) != expected:
        raise UndoConflict("The whole product-kit change cannot be reproduced exactly.")
    scope = None if owners is None else sorted(owners)
    digest = _digest([change_id, rows, latest, shared, products, scope])
    projected = [{"file": row["after"]["file"], "title": labels[row["after"]["file"]], "current": {field: row["after"][field] for field in kit.FIELDS},
                  "restored": {field: row["before"][field] for field in kit.FIELDS}} for row in rows]
    return {"change_id": change_id, "kind": "product_kit", "action": ACTION, "label": "Complete product-kit change",
            "row_count": len(rows), "rows": projected, "expect": digest, "owners": scope, "kit_confirmation_required": True,
            "proof": {"expected": expected, "source": rows}, "sha256": _digest([[row["file"], row["restored"]] for row in projected])}


class Restore:
    kind = "product-kit.undo"
    params = {}

    def __init__(self, change_id, owners, expect, confirm_kit, store):
        self.change_id, self.owners, self.expect, self.confirm_kit, self.store = change_id, owners, expect, confirm_kit, store

    def run(self, snapshot):
        plan = review(self.change_id, self.owners, snapshot, self.store)
        if not isinstance(self.expect, str) or self.expect != plan["expect"]:
            raise UndoConflict(CHANGED)
        if self.confirm_kit is not True:
            raise inventory.Invalid("Confirm every restored product-kit assignment before saving Undo.")
        after = _ordinary(snapshot, plan["proof"]["source"], self.owners)
        _unchanged(snapshot, after)
        if _status(after) != plan["proof"]["expected"]:
            raise UndoConflict(CHANGED)
        return after, Summary(f"Undo change #{self.change_id}: restore the complete product-kit change", {"undo": 1, "products": plan["row_count"]},
                              {paths.STATUS: ["kit"]}, {PROOF: plan})


def confirm(before, saved, summary, actual, reason):
    plan = summary.extra.get(PROOF)
    if not isinstance(plan, dict):
        raise UndoConflict(CHANGED)
    expected = plan["proof"]["source"]
    try:
        _unchanged(before, saved)
        if reason is not None or _status(saved) != plan["proof"]["expected"] or not isinstance(actual, list) or len(actual) != len(expected):
            raise ValueError("Wrong effects")
        by_file, ids = {}, set()
        for row in actual:
            rid = row.get("id")
            if type(rid) is not int or not max(item["id"] for item in expected) < rid < 2 ** 63 or rid in ids \
                    or row.get("table") != TABLE or row.get("op") != "UPDATE" or row.get("key") != {"file": row.get("after", {}).get("file")}:
                raise ValueError("Wrong audit")
            ids.add(rid); by_file[row["after"]["file"]] = {**row, "before": raw_row(row["before"]), "after": raw_row(row["after"])}
        for row in expected:
            changed = by_file.get(row["after"]["file"])
            if changed is None or changed.get("before") != row["after"] or changed.get("after") != row["before"]:
                raise ValueError("Wrong opposite audit")
    except (inventory.Invalid, inventory.Conflict, ValueError, TypeError, KeyError, AttributeError):
        raise UndoConflict("The complete product-kit inverse could not be confirmed.") from None
    receipt = {"saved": True, "source_id": plan["change_id"], "expect": plan["expect"], "kind": "product_kit", "action": ACTION,
               "rows": plan["rows"], "row_count": plan["row_count"], "sha256": plan["sha256"], "revision": str(max(ids)),
               "summary": "Restored every reviewed product-kit assignment as one new change."}
    return Summary(summary.text, summary.counts, summary.changed, {"product_kit_undo": receipt})


def confirm_in_transaction(cur, change_set, before, saved, summary):
    actual = [{"id": rid, "table": table, "op": op, "key": key, "before": old, "after": new}
              for rid, table, op, key, old, new in cur.execute("select id,table_name,op,row_key,before,after from audit.row_change where change_set_id=%s order by id limit 51", (change_set,)).fetchall()]
    reason = cur.execute("select reason from audit.change_set where id=%s", (change_set,)).fetchone()
    return confirm(before, saved, summary, actual, reason[0] if reason else "unknown")
