"""Complete ordinary order/queue forward shapes, reviewed over isolated audit fixtures."""
import copy
import json
from types import SimpleNamespace
from unittest import mock

from decklab.lib import inventory
from decklab.lib.inventory import changes, model, order_queue_models, orders, pg, rules, undo, undo_order_queue as inverse
from decklab.lib.inventory import undo_order_queue_verify as verify
from decklab.tests import test_collection_edit as fixture
from decklab.tests import test_undo_order_queue_pg as pg_facts
from decklab.tests.test_inventory_undo_watchlist import image as queue_image

OID = "2026-11-11-fixture-order"
CHANGE = 42
REASON = "Correct the mistaken order record"


def queued(quantity=3, **values):
    return {**dict.fromkeys(model.QUEUE_FIELDS, ""), "name": "Llanowar Elves", "quantity": str(quantity),
            "printing": "exact", "set": "m19", "collector_number": "314", "finish": "nonfoil", "for": "Fixture deck",
            "state": "ready", **values}


def card(quantity=3):
    return {"name": "Llanowar Elves", "set": "m19", "collector_number": "314", "finish": "nonfoil",
            "quantity": str(quantity), "condition": "", "language": "", "notes": "Synthetic row facts"}


def recorded(before, after, positions, *, first_audit=1000):
    """A small audit double; PostgreSQL integration independently supplies real trigger rows."""
    found = []
    for encoded in order_queue_models.audit_delta(order_queue_models.images(before), order_queue_models.images(after)):
        table, operation, identity, old, new = json.loads(encoded)
        found.append({"table": table, "op": operation, "key": json.loads(identity), "before": old, "after": new})
    old = {row.id: row for row in before.watchlist.rows}
    new = {row.id: row for row in after.watchlist.rows}
    after_positions = pg._positions([row.id for row in after.watchlist.rows], positions)
    layout = dict(zip([row.id for row in after.watchlist.rows], after_positions))
    for identity in old.keys() | new.keys():
        was = queue_image(old[identity].as_dict(), identity, positions[identity]) if identity in old else None
        now = queue_image(new[identity].as_dict(), identity, layout[identity]) if identity in new else None
        if was != now:
            found.append({"table": "watchlist_item", "op": "INSERT" if was is None else "DELETE" if now is None else "UPDATE",
                          "key": {"id": identity}, "before": was, "after": now})
    for number, row in enumerate(found, first_audit):
        row["id"] = number
    return found, layout


class OrderQueueUndoTests(fixture.CollectionEditTestCase):
    def setUp(self):
        super().setUp()
        fixture.ce._require_cards()
        self.initial = model.Inventory("inventory-1", backend="db", decks_revision="decks-1").with_watchlist([
            model.WatchRow.make(queued(), id=7)])
        self.forward, _ = orders.add_order(self.initial, record={"id": OID, "seller": "Fixture shop", "ordered_on": "2026-11-11"},
                         cards={"rows": [card()]}, fulfils=[{"select": "#1", "quantity": 2}])
        self.source(self.initial, self.forward)

    def source(self, before, after):
        # Ordinary source creation here kept one queue row; insertion/deletion variants
        # get explicit persistent ids just as PostgreSQL assigns them.
        next_id = max([row.id for row in before.watchlist.rows] + [100])
        rows = []
        for row in after.watchlist.rows:
            if row.id <= 0:
                next_id += 1
                row = model.WatchRow.make(row.as_dict(), id=next_id)
            rows.append(row)
        after = after.with_watchlist(rows)
        raw, positions = recorded(before, after, {row.id: (number + 1) * 1024 for number, row in enumerate(before.watchlist.rows)})
        order_latest = max(row["id"] for row in raw if row["table"] in order_queue_models.TABLES)
        touched = {row["key"]["id"]: row["id"] for row in raw if row["table"] == "watchlist_item"}
        self.store = SimpleNamespace(snapshot=after, raw=raw, order_latest=order_latest, positions=positions)
        self.store.undo_audit_rows = lambda change_id: copy.deepcopy(self.store.raw)
        self.store.undo_order_queue_latest = lambda oid, products: self.store.order_latest
        self.store.undo_latest = lambda table, key: touched.get(key["id"])
        self.store.undo_watchlist_positions = lambda: [{"id": row.id, "position": self.store.positions[row.id]} for row in self.store.snapshot.watchlist.rows]
        self.store.undo_watchlist_latest = lambda: max(touched.values(), default=None)
        return after

    def review(self, space="home"):
        return inverse.review(CHANGE, space, self.store.snapshot, self.store)

    def test_added_fulfilling_order_restores_both_queue_intent_and_recorded_order_absence(self):
        before = self.store.snapshot
        plan = self.review()
        self.assertEqual((plan["source_action"], plan["queue_count"], plan["space"]), ("added", 1, "home"))
        self.assertEqual(plan["current"]["components"][0]["rows"], [card()])
        self.assertIsNone(plan["restore"])
        self.assertEqual(self.store.snapshot, before)
        with inventory.use(self.store):
            after, summary = inverse.apply(before, change_id=CHANGE, space="home", expect=plan["expect"], reason=REASON)
        self.assertIsNone(after.order(OID))
        self.assertEqual(after.watchlist.rows[0].as_dict(), queued())
        self.assertEqual(summary.extra["undo_reason"], REASON)
        self.assertEqual(after.collections, before.collections)

    def test_cancellation_that_returned_copies_reopens_the_part_and_reduces_queue_together(self):
        cancelled, _ = orders.cancel_order(self.forward, order=OID, component="cards", reason="Not supplied", restore_queue=True)
        self.source(self.forward, cancelled)
        plan = self.review()
        self.assertEqual(plan["source_action"], "state")
        with inventory.use(self.store):
            after, _ = inverse.apply(self.store.snapshot, change_id=CHANGE, space="home", expect=plan["expect"], reason=REASON)
        self.assertEqual(after.order(OID), self.forward.order(OID))
        self.assertEqual(after.watchlist, self.forward.watchlist)
        self.assertEqual(after.payloads, self.forward.payloads)

    def test_removal_that_returned_copies_restores_header_checks_payload_and_original_queue(self):
        removed, _ = inventory.Op("order.remove", {"order": OID, "reason": "Mistaken record"}).run(self.forward)
        self.source(self.forward, removed)
        plan = self.review()
        self.assertEqual(plan["source_action"], "removed")
        with inventory.use(self.store):
            after, _ = inverse.apply(self.store.snapshot, change_id=CHANGE, space="home", expect=plan["expect"], reason=REASON)
        self.assertEqual(after.order(OID), self.forward.order(OID))
        self.assertEqual(after.payloads, self.forward.payloads)
        self.assertEqual(after.watchlist, self.forward.watchlist)

    def test_later_order_or_queue_edit_refuses_whole_and_members_never_read_the_source(self):
        before = self.store.snapshot
        self.store.order_latest += 1
        with self.assertRaises(undo.UndoConflict):
            self.review()
        self.store.order_latest -= 1
        self.store.snapshot = before.with_watchlist([before.watchlist.rows[0].replace(quantity="2")])
        with self.assertRaises((undo.UndoConflict, undo.UndoUnsupported)):
            self.review()
        with mock.patch.object(self.store, "undo_audit_rows", side_effect=AssertionError("Private source read")), self.assertRaises(undo.UndoMissing):
            self.review("user2")

    def test_partial_or_cross_space_source_never_becomes_a_partial_order_inverse(self):
        complete = copy.deepcopy(self.store.raw)
        self.store.raw = [row for row in complete if row["table"] != "order_card_item"]
        with self.assertRaises((undo.UndoConflict, undo.UndoUnsupported)):
            self.review()
        self.store.raw = complete + [{"id": 9000, "table": "collection_card", "op": "UPDATE", "key": {},
                                     "before": {"space_id": "user2"}, "after": {"space_id": "user2"}}]
        with self.assertRaises(undo.UndoMissing):
            self.review()

    def test_precommit_proves_real_order_queue_effects_and_rejects_any_extra_audited_row(self):
        before, plan = self.store.snapshot, self.review()
        with inventory.use(self.store):
            after, summary = inverse.apply(before, change_id=CHANGE, space="home", expect=plan["expect"], reason=REASON)
        summary = verify.prepare(before, after, summary)
        actual, positions = recorded(before, after, self.store.positions, first_audit=max(row["id"] for row in self.store.raw) + 1)
        layout = [{"id": row.id, "position": positions[row.id]} for row in after.watchlist.rows]
        confirmed = verify.confirm(before, after, summary, actual, layout, REASON)
        self.assertEqual(confirmed.extra["order_queue_receipt"]["order_id"], OID)
        self.assertNotIn("order_queue", confirmed.extra)
        with self.assertRaises(undo.UndoConflict):
            verify.confirm(before, after, summary, actual + [{"table": "collection_card", "op": "UPDATE"}], layout, REASON)
        with self.assertRaises(undo.UndoConflict):
            verify.confirm(before, after, summary, actual, layout, "A different reason")
        for value in (self.store.raw[-1]["id"], True, None):
            malformed = copy.deepcopy(actual)
            malformed[0]["id"] = value
            with self.subTest(audit_id=value), self.assertRaises(undo.UndoConflict):
                verify.confirm(before, after, summary, malformed, layout, REASON)
        duplicate = copy.deepcopy(actual)
        duplicate[1]["id"] = duplicate[0]["id"]
        with self.assertRaises(undo.UndoConflict):
            verify.confirm(before, after, summary, duplicate, layout, REASON)

    def test_authored_heading_and_blank_lines_are_exact_even_when_they_resemble_generated_notes(self):
        authored = pg_facts.TEXT + "\n### Substitute version private tactical notes\n\nKeep this exact paragraph.\n"
        record = model.Deck("home", "casual", "queue-fixture", authored)
        changed = record.replace(text=authored.replace("private tactical notes", "ERASED authored heading"))
        self.assertNotEqual(verify._authored(record), verify._authored(changed))
        changed = record.replace(text=authored.replace("\n\nKeep this exact paragraph.", "\n\n\nKeep this exact paragraph."))
        self.assertNotEqual(verify._authored(record), verify._authored(changed))
        before = self.store.snapshot.with_deck(record)
        self.store.snapshot = before
        plan = self.review()
        with inventory.use(self.store):
            after, summary = inverse.apply(before, change_id=CHANGE, space="home", expect=plan["expect"], reason=REASON)
        with self.assertRaises(undo.UndoConflict):
            verify.prepare(before, after.with_deck(changed), summary)

    def test_only_the_actual_owned_heading_and_inserted_note_are_derived(self):
        from decklab.lib.inventory import refresh
        heading = "### Owned-only version for Friday"
        text = pg_facts.TEXT + "\n## Substitutes\n\n" + heading + "\n\n```\nDeck\n1 Llanowar Elves (FDN) 227\n20 Forest\n```\n"
        record = model.Deck("home", "casual", "queue-fixture", text)
        generated = text.replace(heading, refresh.HEADING + "\n\n" + refresh.substitute_note())
        self.assertEqual(verify._authored(record), verify._authored(record.replace(text=generated)))

    def test_composed_preview_ignores_member_and_private_kit_only_changes_but_keeps_fresh_data(self):
        home = model.Deck("home", "casual", "queue-fixture", pg_facts.TEXT)
        self.store.snapshot = self.store.snapshot.with_deck(home)
        before = self.review()
        private = {**card(2), "notes": "Private member fixture"}
        self.store.snapshot = self.store.snapshot.with_collection("user2", [private]).with_deck(home.replace(
            text=home.text.replace("private-legacy-sleeves", "new-private-sleeves").replace("private-legacy-box", "new-private-box"))).replace(
                revision="member-or-kit-only-inventory-revision", decks_revision="member-or-kit-only-deck-revision")
        after = self.review()
        self.assertEqual(after["expect"], before["expect"])
        self.assertEqual(after["queue"]["expect"], before["queue"]["expect"])
        with inventory.use(self.store):
            restored, _ = inverse.apply(self.store.snapshot, change_id=CHANGE, space="home", expect=before["expect"], reason=REASON)
        self.assertIn("new-private-sleeves", restored.deck(home.id).text)
        self.assertIn("new-private-box", restored.deck(home.id).text)
        self.assertEqual(restored.collection("user2").rows[0].text("notes"), "Private member fixture")

    def test_home_card_context_or_intrinsic_draft_change_invalidates_only_the_composed_receipt(self):
        shown = self.review()
        self.store.snapshot = self.store.snapshot.with_collection("home", [card(9)])
        self.assertNotEqual(self.review()["expect"], shown["expect"])
        with inventory.use(self.store), self.assertRaises(undo.UndoConflict):
            inverse.apply(self.store.snapshot, change_id=CHANGE, space="home", expect=shown["expect"], reason=REASON)

    def test_fulfilling_new_product_handles_sorted_status_survivors_and_keeps_current_kit(self):
        columns = ("name", "set", "collector_number", "finish", "quantity")
        cells = {field: card(1)[field] for field in columns}
        product = model.Product("z-existing", columns, (model.ProductItem.make(cells, columns),))
        old_order = model.Order.build("2026-11-01-existing", components=[model.Component.build("existing", "product", "z-existing.csv", status="received", received_on="2026-11-01")])
        before = self.initial.with_product(product).with_order(old_order).with_status_rows([
            {"file": "z-existing.csv", "status": "owned", "intact": "yes", "sleeves": "old-kit", "deck_box": "old-box", "notes": ""}])
        after, _ = orders.add_order(before, record={"id": OID}, product={"stem": "a-new", "columns": columns, "rows": [cells]},
                                   fulfils=[{"select": "#1", "quantity": 1}])
        self.source(before, after)
        raw_status = [row for row in self.store.raw if row["table"] == "product_status"]
        self.assertEqual({row["op"] for row in raw_status}, {"INSERT", "UPDATE"})
        original = self.review()
        current = [{**row.as_dict(), "sleeves": "new-current-kit", "deck_box": "new-current-box"} if row.text("file") == "z-existing.csv"
                   else row.as_dict() for row in self.store.snapshot.status.rows]
        self.store.snapshot = self.store.snapshot.with_status_rows(current).replace(revision="kit-only-global-change")
        self.assertEqual(self.review()["expect"], original["expect"])
        with inventory.use(self.store):
            restored, _ = inverse.apply(self.store.snapshot, change_id=CHANGE, space="home", expect=original["expect"], reason=REASON)
        self.assertIsNone(restored.product("a-new"))
        self.assertEqual([row.text("file") for row in restored.status.rows], ["z-existing.csv"])
        self.assertEqual(restored.status.rows[0].text("sleeves"), "new-current-kit")
        self.assertEqual(restored.status.rows[0].text("deck_box"), "new-current-box")
