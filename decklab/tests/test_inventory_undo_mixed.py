"""Whole-change Undo of a collection import or an order receipt over isolated fixtures.

RecordingInventory is a test double that records audit-shaped rows by comparing the tables a
change leaves, as the database's triggers do. No PostgreSQL, household data or network is
used; test_inventory_undo_mixed_pg.py runs the same shapes through the real audit trail.
"""
import copy
import dataclasses
import hashlib
import json
import unittest

from decklab.lib import inventory
from decklab.lib.inventory import changes, model, ops_collection, paths, receive, rules, undo, undo_mixed
from decklab.lib.inventory.table_rows import tables
from decklab.lib.state import Actor, Invalid
from decklab.tests import test_activity_undo_api as fixture

ACTOR = Actor("matt", "Matt", "home")
REASON = "The file was imported by mistake."
ORDER = "2026-10-20-shop"
CARD = fixture.CARD
NEW = {"name": "Llanowar Elves", "set": "m19", "collector_number": "314", "finish": "nonfoil",
       "quantity": "3", "condition": "", "language": "", "notes": ""}
BUMP = {**CARD, "quantity": "2", "condition": "NM", "language": "en", "notes": ""}
TOKEN = {field: "" for field in rules.TOKEN_FIELDS}
TOKEN.update(front="Treasure", back="", set="tfdn", front_collector_number="12", quantity="2",
             notes="single-sided verified")


def _audit_images(t):
    images = undo_mixed._images(t)
    for position, (rid, *_rest) in enumerate(t[undo.TOKENS]):
        images[undo.TOKENS][undo_mixed._canon(undo.TOKENS, {"id": rid})]["position"] = position
    return images


class RecordingInventory(fixture.AuditInventory):
    """Applies operations to a snapshot and records the rows each change wrote."""

    name = "undo-mixed-fixture"

    def __init__(self, snapshot):
        super().__init__(snapshot)
        self.next_row = 1000
        self.next_change = 500
        self.next_token = 900
        self.next_import = 50
        self.read_rows = 0
        self.reasons = {}

    def saves_decks(self):
        return True

    def undo_audit_rows(self, change_id):
        self.read_rows += 1
        return copy.deepcopy(self.audit.get(change_id, [])[:undo_mixed.MIXED_MAX + 1])

    def undo_change_reason(self, change_id):
        return self.reasons.get(change_id)

    def undo_latest_rows(self, keys):
        wanted = {(table, json.dumps(key, sort_keys=True)) for table, key in keys}
        found = {}
        for rows in self.audit.values():
            for row in rows:
                identity = (row["table"], json.dumps(row["key"], sort_keys=True))
                if identity in wanted and row["id"] > found.get(identity, 0):
                    found[identity] = row["id"]
        return found

    def _ids(self, after):
        tokens = {}
        for space, sheet in after.tokens.items():
            made = []
            for row in sheet.rows:
                if not row.id:
                    self.next_token += 1
                    row = dataclasses.replace(row, id=self.next_token)
                made.append(row)
            tokens[space] = dataclasses.replace(sheet, rows=tuple(made))
        return after.replace(tokens=tokens)

    def _record(self, before, after, imports):
        old, new = _audit_images(tables(before)), _audit_images(tables(after))
        rows = []
        for table in (undo_mixed.STATUS, undo_mixed.COMPONENT, undo.COLLECTION, undo.TOKENS):
            for key in sorted(set(old[table]) | set(new[table])):
                a, b = old[table].get(key), new[table].get(key)
                if a == b:
                    continue
                op = "INSERT" if a is None else "DELETE" if b is None else "UPDATE"
                self.next_row += 1
                rows.append({"id": self.next_row, "table": table, "op": op,
                             "key": json.loads(key), "before": copy.deepcopy(a), "after": copy.deepcopy(b)})
        for deck_id in sorted(set(before.decks) | set(after.decks)):
            if before.decks.get(deck_id) != after.decks.get(deck_id):
                self.next_row += 1
                image = {"id": deck_id, "space_id": after.decks[deck_id].space, "revision": 1}
                rows.append({"id": self.next_row, "table": undo_mixed.DECK, "op": "UPDATE", "key": {"id": deck_id},
                             "before": image, "after": {**image, "revision": 2}})
        for space, name, data in imports:
            self.next_row += 1
            self.next_import += 1
            image = {"id": self.next_import, "space_id": space, "file_name": name, "size": len(data),
                     "sha256": hashlib.sha256(data).hexdigest(), "imported_at": "2026-10-27T00:00:00+00:00"}
            rows.append({"id": self.next_row, "table": undo_mixed.RAW_IMPORT, "op": "INSERT",
                         "key": {"id": self.next_import}, "before": None, "after": image})
        return rows

    def apply(self, op, actor, message, reason=None, expected_revision=None):
        before = self.snapshot
        after, summary = op.run(changes.detach(before))
        after = changes.prepare(before, after, revision=f"{before.revision}-{self.next_change}")
        after = self._ids(after)
        imports = list((summary.extra or {}).get("imports", ()))
        if imports:
            kept = dict(after.imports)
            for space, name, data in imports:
                kept[space] = (*kept.get(space, ()), model.ImportInfo(name, len(data), hashlib.sha256(data).hexdigest()))
            after = after.replace(imports=kept)
        self.next_change += 1
        self.audit[self.next_change] = self._record(before, after, imports)
        self.reasons[self.next_change] = reason
        self.snapshot = after
        self.writes.append((op, actor, message, summary, reason))
        return after, summary


class MixedUndoCase(unittest.TestCase):
    def setUp(self):
        self.case = fixture.ActivityUndoApiTests()
        self.addCleanup(self.case.doCleanups)
        self.case.setUp()
        base = self.case.backend.snapshot
        status = model.Sheet(paths.STATUS, tuple(rules.STATUS_FIELDS),
                             tuple(model.StatusRow.make({**row.as_dict(), "intact": "no" if row.text("status") == "owned" else row.text("intact")})
                                   for row in base.status.rows), True)
        self.store = RecordingInventory(base.replace(decks={}, status=status).with_collection("home", [CARD]))
        self.addCleanup(inventory.use(self.store))

    def write(self, op, message="fixture change"):
        inventory.apply(op, ACTOR, message)
        return self.store.next_change

    def review(self, change_id, space="home"):
        return inventory.undo_mixed_review(change_id, space)

    def undo(self, change_id, plan=None, space="home", reason=REASON):
        plan = self.review(change_id, space) if plan is None else plan
        inventory.apply(inventory.Op("inventory.undo_mixed", {"change_id": change_id, "space": space,
                                                              "expect": plan["expect"], "reason": reason}),
                        ACTOR, f"Undo activity change {change_id}", reason=reason)
        return plan

    def built(self, main, space="home", slug="physical", headers=""):
        text = "# Physical fixture\n\n- **Format:** Casual 60-card, 1v1\n- **Status:** built\n" + headers \
            + "\n## Decklist\n\n```\nDeck\n" + main + "\n```\n"
        self.store.snapshot = self.store.snapshot.with_deck(model.Deck(space, "casual", slug, text))

    def collection(self, space="home"):
        sheet = self.store.snapshot.collection(space)
        return [row.as_dict() for row in sheet.rows] if sheet.exists else []


class ImportUndoTests(MixedUndoCase):
    def merge(self, rows=(NEW, BUMP), space="home"):
        text = rules.collection_csv_bytes(list(rows)).decode("utf-8")
        return self.write(inventory.Op("collection.import", {"space": space, "sources": [["upload.csv", list(rows)]],
                                                            "uploads": [["upload", text]]}))

    def test_preview_lists_every_row_and_writes_nothing(self):
        before = self.collection()
        change = self.merge()
        snapshot, audit = self.store.snapshot, copy.deepcopy(self.store.audit)
        plan = self.review(change)
        self.assertEqual((plan["kind"], plan["action"], plan["space"], plan["reason_required"]),
                         ("mixed", "import_undo", "home", True))
        self.assertEqual(plan["cards"], 5)
        self.assertEqual([row["set"] for row in plan["collection"]["removed"]], ["m19"])
        self.assertEqual(plan["collection"]["reduced"][0]["restored"]["quantity"], 2)
        self.assertEqual(plan["collection"]["reduced"][0]["current"]["quantity"], 4)
        self.assertEqual(plan["uploads"], ["upload.csv"])
        self.assertRegex(plan["expect"], r"^[a-f0-9]{64}$")
        self.assertEqual((self.store.snapshot, self.store.audit), (snapshot, audit))
        self.assertNotEqual(self.collection(), before)

    def test_undo_puts_the_collection_back_and_keeps_the_upload(self):
        before = self.collection()
        change = self.merge()
        imports = self.store.snapshot.imports
        source = copy.deepcopy(self.store.audit[change])
        self.undo(change)
        self.assertEqual(self.collection(), before)
        self.assertEqual(self.store.snapshot.imports, imports)
        self.assertEqual(self.store.audit[change], source)
        op, actor, message, summary, reason = self.store.writes[-1]
        self.assertEqual((op.kind, message, reason), ("inventory.undo_mixed", f"Undo activity change {change}", REASON))
        self.assertEqual(summary.counts["undo"], 1)
        self.assertEqual((summary.counts["removed"], summary.counts["edited"], summary.counts["cards"]), (1, 1, 5))
        self.assertEqual((summary.extra["undo_of"], summary.extra["action"]), (change, "import_undo"))

    def test_metadata_the_merge_blanked_comes_back(self):
        self.store.snapshot = self.store.snapshot.with_collection("home", [{**CARD, "quantity": "2"}])
        before = self.collection()
        change = self.merge(rows=({**BUMP, "condition": "LP", "language": "de"},))
        self.assertEqual(self.collection()[0]["condition"], "")
        self.undo(change)
        self.assertEqual(self.collection(), before)

    def test_a_later_edit_of_any_row_refuses_naming_it(self):
        change = self.merge()
        sha = ops_collection.sha256_of(self.store.snapshot.collection("home"))
        self.write(inventory.Op("collection.edit", {"space": "home", "original": ["m19", "314", "nonfoil"],
                                                    "row": {**NEW, "notes": "sorted"}, "sha256": sha}))
        with self.assertRaises(undo.UndoConflict) as caught:
            self.review(change)
        self.assertIn("M19 314", caught.exception.label)

    def test_a_later_import_touching_the_same_printing_refuses(self):
        change = self.merge()
        self.merge(rows=(NEW,))
        with self.assertRaises(undo.UndoConflict):
            self.review(change)

    def test_a_later_import_of_other_cards_does_not_block(self):
        change = self.merge()
        other = {**NEW, "set": "dom", "collector_number": "168"}
        self.merge(rows=(other,))
        self.undo(change)
        self.assertEqual([row["set"] for row in self.collection()], ["dom", "fdn"])

    def test_stale_preview_refuses_after_any_inventory_change(self):
        change = self.merge()
        plan = self.review(change)
        self.store.snapshot = self.store.snapshot.replace(revision=self.store.snapshot.revision + "x")
        with self.assertRaises(undo.UndoConflict):
            self.undo(change, plan)

    def test_reason_is_required(self):
        change = self.merge()
        plan = self.review(change)
        for reason in (None, "", "   ", "x" * 201):
            with self.subTest(reason=reason), self.assertRaises(Invalid):
                self.undo(change, plan, reason=reason)
        self.assertEqual(len(self.store.writes), 1)

    def test_a_card_a_built_deck_uses_refuses(self):
        change = self.merge()
        self.built("1 Llanowar Elves\n59 Forest")
        with self.assertRaises(undo.UndoConflict) as caught:
            self.review(change)
        self.assertIn("M19 314", caught.exception.label)

    def test_a_tracked_basic_land_refuses(self):
        basic = {**NEW, "name": "Forest", "set": "unf", "collector_number": "239", "finish": "foil"}
        change = self.merge(rows=(basic,))
        with self.assertRaises(undo.UndoUnsupported):
            self.review(change)

    def test_another_space_is_missing_before_anything_else(self):
        change = self.merge()
        with self.assertRaises(undo.UndoMissing):
            self.review(change, "user2")

    def test_member_space_import_undoes_in_its_own_space(self):
        self.store.snapshot = self.store.snapshot.with_collection("user2", [CARD])
        before = self.collection("user2")
        change = self.merge(space="user2")
        with self.assertRaises(undo.UndoMissing):
            self.review(change, "home")
        self.undo(change, space="user2")
        self.assertEqual(self.collection("user2"), before)

    def test_a_change_with_other_tables_is_unsupported(self):
        change = self.merge()
        self.store.audit[change].append({"id": 99999, "table": "watchlist_item", "op": "UPDATE", "key": {"id": 1},
                                         "before": {"id": 1}, "after": {"id": 1}})
        with self.assertRaises(undo.UndoUnsupported):
            self.review(change)

    def test_a_too_large_change_is_unsupported(self):
        change = self.merge()
        rows = self.store.audit[change]
        self.store.audit[change] = rows + [copy.deepcopy(rows[0]) for _ in range(undo_mixed.MIXED_MAX)]
        with self.assertRaises(undo.UndoUnsupported):
            self.review(change)

    def test_an_altered_record_cannot_pretend_to_be_an_import(self):
        change = self.merge()
        for row in self.store.audit[change]:
            if row["table"] == undo.COLLECTION and row["op"] == "UPDATE":
                row["before"]["quantity"] = 9        # an update that took copies away isn't a merge
        with self.assertRaises(undo.UndoUnsupported):
            self.review(change)

    def test_a_single_row_import_still_needs_its_whole_change(self):
        change = self.merge(rows=(NEW,))
        self.assertEqual({row["table"] for row in self.store.audit[change]}, {undo.COLLECTION, undo_mixed.RAW_IMPORT})
        self.undo(change)
        self.assertEqual(self.collection(), [{**CARD, "quantity": "2"}])


class ReceiptCase(MixedUndoCase):
    def setUp(self):
        super().setUp()
        cards = paths.payload("cards", "pending", f"{ORDER}.csv")
        token_file = paths.payload("tokens", "pending", f"{ORDER}.csv")
        order = model.Order.build(ORDER, "Shop", "2026-10-20", (), "", [
            model.Component.build("cards", "cards", f"{ORDER}.csv", checks=["Confirm the Elves are near mint"]),
            model.Component.build("tokens", "tokens", f"{ORDER}.csv"),
            model.Component.build("fdc-test-precon", "product", "fdc-test-precon.csv")])
        payloads = dict(self.store.snapshot.payloads)
        payloads[cards] = model.Sheet(cards, model.CardRow.COLUMNS, (model.CardRow.make(NEW), model.CardRow.make(BUMP)), True)
        payloads[token_file] = model.Sheet(token_file, model.TokenRow.COLUMNS, (model.TokenRow.make(TOKEN),), True)
        self.store.snapshot = self.store.snapshot.replace(payloads=payloads).with_order(order)

    def receive(self, components=None, date="2026-10-25"):
        components = components or [{"id": "cards", "verified": True}, {"id": "tokens", "verified": True},
                                    {"id": "fdc-test-precon", "intact": "no"}]
        return self.write(receive.op(ORDER, components, date))


class ReceiptUndoTests(ReceiptCase):

    def test_undo_puts_parts_back_on_order_and_removes_their_cards(self):
        before = self.store.snapshot
        change = self.receive()
        tables_before = tables(before)
        plan = self.review(change)
        self.assertEqual((plan["action"], plan["label"]),
                         ("receipt_undo", f"Receipt of order {ORDER} (cards, tokens, fdc-test-precon)"))
        self.assertEqual({item["component"] for item in plan["components"]}, {"cards", "tokens", "fdc-test-precon"})
        self.assertEqual(plan["products"], [{"product": "fdc-test-precon", "status": "preordered", "intact": "no"}])
        self.assertEqual([row["front"] for row in plan["tokens"]["removed"]], ["Treasure"])
        self.undo(change)
        after = tables(self.store.snapshot)
        for table in ("collection_card", "order_component", "product_status", "purchase_order",
                      "order_card_item", "order_token_item"):
            self.assertEqual(after[table], tables_before[table], table)
        self.assertEqual([row[2:] for row in after["token_card"]], [row[2:] for row in tables_before["token_card"]])
        order = self.store.snapshot.order(ORDER)
        self.assertEqual([(c.status, c.received_on, c.checks, c.verified_checks) for c in order.components],
                         [("pending", "", ["Confirm the Elves are near mint"], None), ("pending", "", [], None),
                          ("pending", "", [], None)])
        self.assertEqual(set(self.store.snapshot.payloads), set(before.payloads))
        summary = self.store.writes[-1][3]
        self.assertEqual((summary.counts["components"], summary.counts["products"]), (3, 1))
        self.assertIn("tables", summary.extra)

    def test_a_receipt_of_one_part_undoes_only_that_part(self):
        change = self.receive([{"id": "cards", "verified": True}])
        self.receive([{"id": "tokens", "verified": True}])
        self.undo(change)
        statuses = {c.id: c.status for c in self.store.snapshot.order(ORDER).components}
        self.assertEqual(statuses, {"cards": "pending", "tokens": "received", "fdc-test-precon": "pending"})

    def test_an_intact_product_the_receipt_kept_goes_back_on_order(self):
        change = self.receive([{"id": "fdc-test-precon", "intact": "yes"}])
        self.assertEqual(next(r.text("intact") for r in self.store.snapshot.status.rows if r.text("file") == "fdc-test-precon.csv"), "yes")
        self.undo(change)
        row = next(r for r in self.store.snapshot.status.rows if r.text("file") == "fdc-test-precon.csv")
        self.assertEqual((row.text("status"), row.text("intact"), row.text("notes")), ("preordered", "", "due soon"))

    def test_a_later_kit_or_status_change_refuses(self):
        change = self.receive([{"id": "fdc-test-precon", "intact": "yes"}])
        rows = [row.as_dict() for row in self.store.snapshot.status.rows]
        for row in rows:
            if row["file"] == "fdc-test-precon.csv":
                row["notes"] += "; boxed"
        self.write(_Set(lambda inv: inv.with_status_rows(rows)))
        with self.assertRaises(undo.UndoConflict) as caught:
            self.review(change)
        self.assertEqual(caught.exception.label, "product fdc-test-precon")

    def test_a_later_token_edit_refuses(self):
        change = self.receive([{"id": "tokens", "verified": True}])
        rows = [dataclasses.replace(row, values=tuple((c, "5" if c == "quantity" else v) for c, v in row.values))
                for row in self.store.snapshot.token_set("home").rows]
        self.write(_Set(lambda inv: inv.with_tokens("home", rows)))
        with self.assertRaises(undo.UndoConflict) as caught:
            self.review(change)
        self.assertEqual(caught.exception.label, "Treasure")

    def test_packed_tokens_refuse(self):
        change = self.receive([{"id": "tokens", "verified": True}])
        self.built("4 Forest", headers="- **Token cards:** 1 Treasure\n")
        with self.assertRaises(undo.UndoConflict):
            self.review(change)

    def test_a_built_deck_without_a_token_line_is_unknown_packing(self):
        change = self.receive([{"id": "tokens", "verified": True}])
        self.built("4 Forest")
        with self.assertRaises(undo.UndoConflict):
            self.review(change)

    def test_cards_a_built_deck_holds_refuse(self):
        change = self.receive([{"id": "cards", "verified": True}])
        self.built("3 Llanowar Elves\n57 Forest", headers="- **Token cards:**\n")
        with self.assertRaises(undo.UndoConflict):
            self.review(change)

    def test_a_partial_receipt_is_unsupported(self):
        change = self.receive([{"id": "cards", "verified": True, "take": [{"row": 1}]}])
        with self.assertRaises(undo.UndoUnsupported):
            self.review(change)

    def test_receipts_are_home_only(self):
        change = self.receive()
        with self.assertRaises(undo.UndoMissing):
            self.review(change, "user2")

    def test_an_undone_receipt_can_be_received_again(self):
        change = self.receive()
        self.undo(change)
        again = self.receive()
        self.assertTrue(all(c.status == "received" for c in self.store.snapshot.order(ORDER).components))
        self.undo(again)

    def test_undoing_twice_refuses(self):
        change = self.receive()
        self.undo(change)
        with self.assertRaises(undo.UndoConflict):
            self.review(change)


@dataclasses.dataclass(frozen=True)
class _Set:
    """A fixture operation: fn(inventory) as one change."""
    fn: object
    kind = "fixture.set"
    params = {}

    def run(self, inv):
        return self.fn(inv), inventory.Summary("fixture")


if __name__ == "__main__":
    unittest.main()
