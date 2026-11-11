"""Transaction-local proof for an order lifecycle and its complete queue inverse."""
import copy
import json
import re
from dataclasses import replace

from decklab.lib import decks
from decklab.lib.decks.edit import _card_key, _split_notes

from . import Summary, refresh
from . import order_queue_models as models, pg_decks
from . import undo_order_queue as order_undo
from .undo import UndoConflict


def restoring(summary):
    return (summary.extra or {}).get("action") == order_undo.ACTION \
        and isinstance((summary.extra or {}).get("order_queue"), dict)


def _authored(record):
    parsed = pg_decks.parsed(record.id, record.text) if record.text is not None else None
    if parsed is None:
        raise ValueError("A changed deck cannot be parsed")
    text = parsed.text
    spans = [(start, end, "<derived-table>") for key in ("table", "prices")
             if (span := parsed.spans.get(key)) is not None for start, end in (span,)]
    # The normal refresher changes one actual owned-list heading and one marker.
    # A similarly worded authored heading elsewhere is ordinary prose.
    owned = parsed.spans.get("owned")
    if parsed.owned is not None and owned is not None:
        heading = next((match for match in refresh.HEADING_RE.finditer(text) if 0 < match.start() < owned[0]), None)
        if heading is not None:
            spans.append((heading.start(), heading.end(), heading.group(1) + " <derived-owned-heading>"))
            note = refresh.AVAILABILITY_RE.search(text)
            if note is not None and heading.end() <= note.start() < note.end() <= owned[0]:
                # When newly inserted, the refresher adds exactly two newlines
                # before the marker while keeping the original suffix verbatim.
                prefix = text[heading.end():note.start()]
                start = heading.end() if prefix == parsed.newline * 2 else note.start()
                spans.append((start, note.end(), ""))
    for start, end, marker in sorted(spans, reverse=True):
        text = text[:start] + marker + text[end:]
    notes = {_card_key(row.card): _split_notes(row.notes_cell or "")[1].strip() for row in parsed.rows or []
             if _split_notes(row.notes_cell or "")[1].strip()}
    total = _split_notes(parsed.total.notes_cell or "")[1].strip() if parsed.total is not None else ""
    return text, notes, total


def prepare(before, after, summary):
    """After the ordinary refresh, before SQL: freeze exactly the candidate being written.

    The operation itself kept every current deck. Only the established refresher
    may now change generated tables/availability notes; current authored lists,
    categories, prose, handwritten notes and all private kit stay as they are.
    """
    if not restoring(summary):
        return summary
    extra = dict(summary.extra)
    proof = dict(extra["order_queue"])
    try:
        if set(before.decks) != set(after.decks) or any(getattr(before, field) != getattr(after, field)
                                                       for field in order_undo.UNTOUCHED):
            raise ValueError("An unrelated inventory part changed")
        changed_decks = []
        for identity, was in before.decks.items():
            now = after.decks[identity]
            if was.text != now.text:
                if was.space != "home" or now.space != "home" or _authored(was) != _authored(now):
                    raise ValueError("A current authored deck or private kit changed")
                changed_decks.append(identity)
        if models.images(after) != proof["order_after"]:
            raise ValueError("An order resource changed outside the reviewed inverse")
    except Exception:
        raise UndoConflict(order_undo.UNCONFIRMED) from None
    proof.update(expected_decks={identity: saved.text for identity, saved in after.decks.items()},
                 changed_decks=sorted(changed_decks), expected_order_audit=models.audit_delta(proof["order_before"], proof["order_after"]))
    extra["order_queue"] = proof
    return replace(summary, extra=extra)


def _order_audit(actual):
    out = []
    for row in actual:
        table = row["table"]
        if table not in models.TABLES:
            continue
        operation = row.get("op")
        old = models.normalized(table, row["before"]) if row.get("before") is not None else None
        new = models.normalized(table, row["after"]) if row.get("after") is not None else None
        image = new if new is not None else old
        if operation not in ("INSERT", "UPDATE", "DELETE") or (old is None) != (operation == "INSERT") \
                or (new is None) != (operation == "DELETE") or row.get("key") != {field: image[field] for field in models.KEYS[table]}:
            raise ValueError("Unexpected order audit effect")
        out.append(json.dumps((table, operation, models.key(table, image), old, new),
                              sort_keys=True, ensure_ascii=False, separators=(",", ":")))
    return sorted(out)


def _deck_audit(actual, changed):
    seen = set()
    for row in actual:
        if row["table"] != "deck":
            continue
        old, new = row.get("before"), row.get("after")
        identity = new.get("id") if isinstance(new, dict) else None
        if identity not in changed or identity in seen:
            raise ValueError("An unreviewed deck changed")
        order_undo._deck_source(row)
        seen.add(identity)
    if seen != set(changed):
        raise ValueError("The refreshed deck audit is incomplete")


def confirm(before, saved, summary, actual, layout, reason):
    """Actual order/item/queue/deck trigger effects must match the frozen candidate."""
    extra = dict(summary.extra)
    proof = extra.pop("order_queue")
    plan = proof["plan"]
    try:
        if not isinstance(actual, list) or any(not isinstance(row, dict) or row.get("table") not in {*models.TABLES, "deck", "watchlist_item"}
                                                for row in actual):
            raise ValueError("An unrelated row was written")
        audit_ids = [row.get("id") for row in actual]
        if any(type(identity) is not int or not 1 <= identity < 2 ** 63 for identity in audit_ids) \
                or len(set(audit_ids)) != len(audit_ids) or any(identity <= max(proof["source_ids"]) for identity in audit_ids):
            raise ValueError("The actual audit rows are not fresh unique transaction effects")
        if reason != extra["undo_reason"] or _order_audit(actual) != proof["expected_order_audit"] \
                or models.images(saved) != proof["order_after"]:
            raise ValueError("The recorded order facts or reason differ from the review")
        _deck_audit(actual, proof["changed_decks"])
        if {identity: record.text for identity, record in saved.decks.items()} != proof["expected_decks"] \
                or any(getattr(before, field) != getattr(saved, field) for field in order_undo.UNTOUCHED):
            raise ValueError("A current deck or unrelated inventory part changed")
        from . import undo_watchlist as updates, undo_watchlist_rows as presence, undo_watchlist_mixed as mixed
        module = {item.__name__: item for item in (updates, presence, mixed)}[proof["queue_module"]]
        permitted = before.replace(orders=saved.orders, payloads=saved.payloads, products=saved.products, status=saved.status)
        queue_audit = [row for row in actual if row["table"] == "watchlist_item"]
        child = proof["queue_summary"]
        if "undo_reason" in child.extra:
            child = replace(child, extra={**child.extra, "undo_reason": reason})
        queue_summary = module.confirm(permitted, saved, child, queue_audit) if module is updates \
            else module.confirm(permitted, saved, child, queue_audit, layout)
    except Exception:
        raise UndoConflict(order_undo.UNCONFIRMED) from None
    receipt = {"order_id": plan["order_id"], "source_action": plan["source_action"], "queue_count": plan["queue_count"],
               "queue_action": plan["queue"]["action"], "queue_summary": queue_summary}
    return Summary(summary.text, summary.counts, summary.changed, {**extra, "order_queue_receipt": receipt})


def confirm_in_transaction(cur, change_set, before, saved, summary):
    proof = summary.extra["order_queue"]
    expected = len(proof["expected_order_audit"]) + proof["plan"]["queue_count"] + len(proof["changed_decks"])
    actual = [{"id": identity, "table": table, "op": operation, "key": key, "before": old, "after": new}
              for identity, table, operation, key, old, new in cur.execute(
                  "select id,table_name,op,row_key,before,after from audit.row_change where change_set_id=%s order by id limit %s",
                  (change_set, expected + 1)).fetchall()]
    layout = [{"id": identity, "position": position} for identity, position in cur.execute(
        "select id,position from watchlist_item order by position,id").fetchall()]
    reason = cur.execute("select reason from audit.change_set where id=%s", (change_set,)).fetchone()
    return confirm(before, saved, summary, actual, layout, reason[0] if reason is not None else None)
