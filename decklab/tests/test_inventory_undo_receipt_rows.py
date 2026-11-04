"""Whole-change Undo of a receipt that corrected its order rows at the door (E11-S08).

The recorder writes order rows as the database does (a changed list DELETEd and INSERTed whole,
purchase_order UPDATEd), over isolated fixtures: no PostgreSQL, household data or network.
"""
import copy
import json
import unittest

from decklab.lib import inventory
from decklab.lib.inventory import order_fulfilment, paths, receive, undo, undo_mixed, undo_receipt_rows
from decklab.lib.inventory.table_rows import ITEM_COLUMNS, tables
from decklab.tests import test_inventory_undo_mixed as mixed
from decklab.tests.test_order_fulfilment import queue

ORDER = mixed.ORDER
TOKEN = mixed.TOKEN
ONE = {**TOKEN, "quantity": "1"}
SPLIT = [{**ONE, "front_details": "colourless"}, {**ONE, "notes": "single-sided verified; creased"}]
CORRECTED = {**mixed.NEW, "condition": "NM", "language": "en"}


class RowRecordingInventory(mixed.RecordingInventory):
    """Also records order rows (whole lists rewritten) and order records, as inventory/pg.py writes them."""

    def _record(self, before, after, imports):
        rows = super()._record(before, after, imports)
        old, new = tables(before), tables(after)
        for table, columns in ITEM_COLUMNS.items():
            for key in sorted(set(old[table]) | set(new[table])):
                was, now = old[table].get(key, ()), new[table].get(key, ())
                if was == now:
                    continue
                for op, items in (("DELETE", was), ("INSERT", now)):
                    for position, cells in enumerate(items):
                        image = {"order_id": key[0], "component_id": key[1], "position": position,
                                 **dict(zip(columns, cells))}
                        self.next_row += 1
                        rows.append({"id": self.next_row, "table": table, "op": op,
                                     "key": {"order_id": key[0], "component_id": key[1], "position": position},
                                     "before": image if op == "DELETE" else None,
                                     "after": image if op == "INSERT" else None})
        fields = ("seller", "ordered_on", "sources", "notes", "audit_notes")
        for oid in sorted(set(old["purchase_order"]) | set(new["purchase_order"])):
            was, now = old["purchase_order"].get(oid), new["purchase_order"].get(oid)
            if was == now:
                continue
            image = lambda v: None if v is None else {"id": oid, **dict(zip(fields, v)), "sources": list(v[2])}  # noqa: E731
            self.next_row += 1
            rows.append({"id": self.next_row, "table": "purchase_order",
                         "op": "INSERT" if was is None else "DELETE" if now is None else "UPDATE",
                         "key": {"id": oid}, "before": image(was), "after": image(now)})
        return rows


class CorrectedReceiptTests(mixed.ReceiptCase):
    def setUp(self):
        super().setUp()
        self.store = RowRecordingInventory(self.store.snapshot)
        self.addCleanup(inventory.use(self.store))

    def ledger(self):
        """The order keeps a fulfilment ledger: the Treasure cards fulfil a queued request."""
        inv = self.store.snapshot.with_watchlist([queue("Treasure", 2, **{"for": "Tokens"})])
        order = order_fulfilment.record(inv, inv, inv.order(ORDER), [{"select": "#1", "quantity": 2}])
        self.store.snapshot = self.store.snapshot.with_order(order)

    def receive_tokens(self, rows=SPLIT):
        return self.write(receive.op(ORDER, [{"id": "tokens", "verified": True, "rows": rows}], "2026-10-25"))

    def payload(self, kind):
        component = next(c for c in self.store.snapshot.order(ORDER).components if c.id == kind)
        return [row.as_dict() for row in self.store.snapshot.payloads[component.path].rows]

    def test_corrected_token_rows_go_back_as_ordered_with_the_ledger(self):
        self.ledger()
        before = tables(self.store.snapshot)
        change = self.receive_tokens()
        written = {row["table"] for row in self.store.audit[change]}
        self.assertTrue({"order_token_item", "purchase_order"} <= written, written)
        plan = self.review(change)
        self.assertEqual(plan["action"], "receipt_undo")
        self.assertEqual([item["corrected"] for item in plan["components"]], [{"ordered": 1, "received": 2}])
        self.undo(change)
        after = tables(self.store.snapshot)
        for table in ("order_component", "order_token_item", "order_card_item", "purchase_order", "collection_card"):
            self.assertEqual(after[table], before[table], table)
        self.assertEqual([row[2:] for row in after["token_card"]], [row[2:] for row in before["token_card"]])
        self.assertEqual(self.payload("tokens"), [TOKEN])
        self.assertEqual(self.store.snapshot.order(ORDER).components[1].status, "pending")

    def test_corrected_card_rows_go_back_as_ordered(self):
        before = tables(self.store.snapshot)
        change = self.write(receive.op(ORDER, [{"id": "cards", "verified": True, "rows": [CORRECTED, mixed.BUMP]}],
                                       "2026-10-25"))
        self.assertIn("order_card_item", {row["table"] for row in self.store.audit[change]})
        self.assertEqual(self.review(change)["components"][0]["corrected"], {"ordered": 2, "received": 2})
        self.undo(change)
        after = tables(self.store.snapshot)
        for table in ("order_card_item", "collection_card", "order_component"):
            self.assertEqual(after[table], before[table], table)

    def test_an_uncorrected_part_says_so(self):
        change = self.receive_tokens([TOKEN])
        self.assertNotIn("order_token_item", {row["table"] for row in self.store.audit[change]})
        self.assertEqual(self.review(change)["components"][0]["corrected"], None)

    def test_a_later_correction_of_the_received_rows_refuses(self):
        change = self.receive_tokens()
        component = next(c for c in self.store.snapshot.order(ORDER).components if c.id == "tokens")
        rows = [{**SPLIT[0], "notes": "single-sided verified; sleeved"}, SPLIT[1]]
        self.write(mixed._Set(lambda inv: inv.set_component_rows(ORDER, component.id, rows)))
        with self.assertRaises(undo.UndoConflict) as caught:
            self.review(change)
        self.assertEqual(caught.exception.label, f"order {ORDER} (tokens)")

    def test_a_later_order_record_edit_refuses(self):
        self.ledger()
        change = self.receive_tokens()
        order = self.store.snapshot.order(ORDER)
        data = order.record()
        data["audit_notes"] += " Checked by phone."
        self.write(mixed._Set(lambda inv: inv.with_order(type(order)(order.file, data))))
        with self.assertRaises(undo.UndoConflict) as caught:
            self.review(change)
        self.assertEqual(caught.exception.label, f"order {ORDER}")

    def test_order_rows_outside_the_received_parts_are_unsupported(self):
        change = self.receive_tokens()
        for row in self.store.audit[change]:
            if row["table"] == "order_token_item":
                image = row["before"] or row["after"]
                image["component_id"] = row["key"]["component_id"] = "other"
        with self.assertRaises(undo.UndoUnsupported):
            self.review(change)

    def test_a_list_with_a_missing_position_is_unsupported(self):
        change = self.receive_tokens()
        rows = self.store.audit[change]
        last = max(i for i, row in enumerate(rows) if row["table"] == "order_token_item" and row["op"] == "INSERT"
                   and row["key"]["position"] == 0)
        del rows[last]
        with self.assertRaises(undo.UndoUnsupported):
            self.review(change)

    def test_an_order_record_change_beyond_its_ledger_is_unsupported(self):
        self.ledger()
        change = self.receive_tokens()
        for row in self.store.audit[change]:
            if row["table"] == "purchase_order":
                row["after"]["notes"] = "edited"
        with self.assertRaises(undo.UndoUnsupported):
            self.review(change)

    def test_order_rows_never_join_an_import(self):
        found = {"id": 1, "table": "order_card_item", "op": "INSERT", "key": {}, "before": None, "after": {}}
        with self.assertRaises(undo.UndoUnsupported):
            undo_mixed._check_row(found, undo_mixed.IMPORT)

    def test_the_activity_hint_offers_a_corrected_receipt(self):
        change = self.receive_tokens()
        rows = self.store.audit[change]
        self.assertEqual(undo_mixed.looks_like(rows, None, paths.HOME), undo_mixed.RECEIPT)

    def test_groups_reject_a_position_named_twice(self):
        change = self.receive_tokens()
        rows = copy.deepcopy(self.store.audit[change])
        rows.append(next(copy.deepcopy(row) for row in rows if row["table"] == "order_token_item" and row["op"] == "INSERT"))
        received = {(ORDER, "tokens"): "tokens"}
        with self.assertRaises(undo_receipt_rows.Refused):
            undo_receipt_rows.groups(rows, received)
        self.assertEqual(json.loads(undo_receipt_rows.key_json({"b": 1, "a": 2})), {"a": 2, "b": 1})


if __name__ == "__main__":
    unittest.main()
