"""Atomic partial receipts over isolated files and disposable PostgreSQL fixtures."""
import contextlib
import csv
import io
import unittest
from unittest import mock

from decklab.lib import config, inventory, pool
from decklab.lib.inventory import files, order_fulfilment, receive, rules
from decklab.lib.inventory.model import Component, Order, QUEUE_FIELDS
from decklab.lib.state import Actor, Invalid
from decklab.tests import db_support, test_inventory_contract as contract
from decklab.tests import test_inventory_orders as support

ACTOR = Actor("matt", "Matt", None, "receipt")
CHECKS = ["Record the condition", "Confirm the language"]
RABBIT = {"front": "Rabbit", "back": "Rabbit", "set": "tblb", "front_collector_number": "8",
          "back_collector_number": "8", "finish": "nonfoil", "quantity": "2",
          "front_details": "1/1", "back_details": "1/1", "notes": ""}
DOG = {key: "" for key in rules.TOKEN_FIELDS}
DOG.update(front="Dog", quantity="1", notes="Check physical pairing")


def partial_tree(case):
    for folder in ("orders/records", "orders/tokens", "orders/cancelled", "buylists"):
        (case.magic / folder).mkdir(parents=True, exist_ok=True)
    case.cards_csv("collection.csv", ("Elvish Mystic", "cmm", "648", "nonfoil", 1))
    case.cards_csv("orders/partial.csv", ("Elvish Mystic", "cmm", "648", "nonfoil", 2),
                   ("Llanowar Elves", "fdn", "227", "nonfoil", 4))
    case.write("orders/tokens/partial.csv", rules.csv_bytes([RABBIT, DOG], rules.TOKEN_FIELDS).decode("utf-8"))
    case.cards_csv("products/kit.csv", ("Pick Your Poison", "mkm", "170", "nonfoil", 1))
    case.write("products/status.csv", ",".join(rules.STATUS_FIELDS) + "\nkit.csv,ordered,,,,,\n")
    record = Order.build("partial", seller="Fixture shop", ordered_on="2026-10-01", components=[
        Component.build("cards", "cards", "partial.csv", checks=CHECKS),
        Component.build("tokens", "tokens", "partial.csv", checks=["Check physical pairs"]),
        Component.build("kit", "product", "kit.csv", checks=["Inspect product tokens"]),
    ])
    case.write("orders/records/partial.json", rules.json_bytes(record.data).decode("utf-8"))
    case.deck("partial", "Partial deck", "idea", "Deck\n4 Llanowar Elves\n1 Elvish Mystic\n20 Forest\n", table="\n")
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, QUEUE_FIELDS, lineterminator="\n")
    writer.writeheader()
    writer.writerow({**dict.fromkeys(QUEUE_FIELDS, ""), "name": "Llanowar Elves", "quantity": "4",
                     "for": "Partial deck", "printing": "any", "state": "ready"})
    case.write("watchlist.csv", stream.getvalue())


class _Fixture:
    def setUp(self):
        super().setUp()
        self.case = contract.build_tree(partial_tree, adapted=False)
        self.addCleanup(self.case.doCleanups)
        self.root, self.backend = self.case.inventory.root, self.case.inventory
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(contract.fixture_world())
        stack.enter_context(mock.patch.object(config, "REPO", self.root))
        stack.enter_context(inventory.use(self.backend))

    def operation(self, *components, order="partial"):
        return receive.op(order, list(components), "2026-10-15")

    def apply(self, *components, order="partial"):
        return inventory.apply(self.operation(*components, order=order), ACTOR, "Receive arrived fixture copies")

    def component(self, snapshot, component="cards", order="partial"):
        return next(part for part in snapshot.order(order).components if part.id == component)

    def rows(self, snapshot, component="cards", order="partial"):
        return receive.payload_rows(snapshot, self.component(snapshot, component, order))

    def unchanged(self, before):
        after = self.backend.load()
        self.assertEqual(files.render(after, decks=True), files.render(before, decks=True))
        self.assertEqual((after.revision, after.decks_revision), (before.revision, before.decks_revision))

    def refuse(self, component):
        before = self.backend.load()
        with self.assertRaises(Invalid):
            self.apply(component)
        self.unchanged(before)

    def quantity(self, snapshot, name):
        return sum(row.qty for row in snapshot.collection().rows if row.name == name)

    def tracked_order(self, rows=None, fulfilled=4):
        return inventory.apply(inventory.Op("order.add", {"record": {"id": "tracked", "seller": "Fixture shop",
                    "ordered_on": "2026-10-01", "sources": [], "notes": ""},
                    "cards": {"rows": rows or [support.card("Llanowar Elves", "fdn", "227", 4)]},
                    "fulfils": [{"select": "Llanowar Elves", "quantity": fulfilled}], "repo": str(self.root)}),
                    ACTOR, "Order queued fixture copies")[0]


class FilePartialReceiptTests(_Fixture, unittest.TestCase):
    def test_preview_and_apply_split_one_quantity_with_one_apply_and_conserve_physical_supply(self):
        before = self.backend.load()
        operation = self.operation({"id": "cards", "verified": True, "take": [{"row": 2, "quantity": 1}]})
        preview, summary = inventory.preview(operation)
        self.unchanged(before)
        assignment = {"source": "cards", "received": "cards-received-1", "pending": "cards",
                      "received_quantity": 1, "pending_quantity": 5}
        self.assertEqual(summary.extra["assignments"], [assignment])
        self.assertEqual(summary.extra["components"], ["cards-received-1"])
        with mock.patch.object(inventory, "apply", wraps=inventory.apply) as apply:
            after, saved = inventory.apply(operation, ACTOR, "Receive arrived fixture copies")
        self.assertEqual(apply.call_count, 1)
        self.assertEqual(saved.extra["assignments"], summary.extra["assignments"])
        self.assertEqual(files.render(after, decks=True), files.render(preview, decks=True))
        self.assertEqual(self.quantity(after, "Llanowar Elves"), 1)
        self.assertEqual(sum(int(row["quantity"]) for row in self.rows(after)), 5)
        self.assertEqual(self.rows(after, "cards-received-1")[0]["quantity"], "1")
        pending, arrived = self.component(after), self.component(after, "cards-received-1")
        self.assertEqual((pending.status, pending.checks, pending.received_on), ("pending", CHECKS, ""))
        self.assertEqual((arrived.status, arrived.checks, arrived.verified_checks, arrived.received_on),
                         ("received", [], CHECKS, "2026-10-15"))
        self.assertEqual(dict(saved.extra["totals"])["playable cards"]["cards"], 1)
        supplies = []
        for snapshot in (before, after):
            with inventory.pinned(snapshot):
                supplies.append(pool.load_pool())
        self.assertEqual(supplies[0].owned, supplies[1].owned)
        self.assertFalse(supplies[1].warnings)
        self.assertEqual(sum(qty for _, qty in supplies[1].on_the_way["Llanowar Elves"]), 3)

    def test_newly_received_copy_explains_the_clean_pending_remainder_without_blocking_tables(self):
        self.case.cards_csv("collection.csv")
        self.case.cards_csv("orders/partial.csv", ("Llanowar Elves", "fdn", "227", "nonfoil", 2))
        before = self.backend.load()
        with inventory.pinned(before):
            self.assertFalse(pool.load_pool().warnings)
        after, summary = self.apply({"id": "cards", "verified": True, "take": [{"row": 1, "quantity": 1}]})
        self.assertEqual(self.quantity(after, "Llanowar Elves"), 1)
        self.assertEqual(self.rows(after)[0]["quantity"], "1")
        self.assertIn("cards", rules.extra_copies(after.order("partial").audit_notes))
        self.assertIsNone(summary.extra["tables"]["error"])
        self.assertIn("casual/partial", [row["id"] for row in summary.extra["tables"]["written"]])
        with inventory.pinned(after):
            supply = pool.load_pool()
        self.assertEqual(supply.owned["Llanowar Elves"], 2)  # one physical copy plus one incoming
        self.assertEqual(sum(qty for _, qty in supply.on_the_way["Llanowar Elves"]), 1)
        self.assertFalse(supply.warnings)

    def test_partial_receipt_does_not_clear_a_preexisting_duplicate_acquisition_warning(self):
        self.case.cards_csv("collection.csv", ("Llanowar Elves", "fdn", "227", "nonfoil", 2))
        self.case.cards_csv("orders/partial.csv", ("Llanowar Elves", "fdn", "227", "nonfoil", 2))
        before = self.backend.load()
        with inventory.pinned(before):
            self.assertTrue(any("every card in" in warning for warning in pool.load_pool().warnings))
        preview, summary = inventory.preview(self.operation({"id": "cards", "verified": True,
                                                           "take": [{"row": 1, "quantity": 1}]}))
        self.assertNotIn("cards", rules.extra_copies(preview.order("partial").audit_notes))
        with inventory.pinned(preview):
            self.assertTrue(any("every card in" in warning for warning in pool.load_pool().warnings))
        self.assertTrue(summary.extra["tables"]["error"])
        self.unchanged(before)

    def test_matching_arrival_explains_remainder_when_one_copy_was_already_owned(self):
        self.case.cards_csv("collection.csv", ("Llanowar Elves", "fdn", "227", "nonfoil", 1))
        self.case.cards_csv("orders/partial.csv", ("Llanowar Elves", "fdn", "227", "nonfoil", 2))
        with inventory.pinned(self.backend.load()):
            self.assertFalse(pool.load_pool().warnings)
        after, summary = self.apply({"id": "cards", "verified": True, "take": [{"row": 1, "quantity": 1}]})
        self.assertEqual(self.quantity(after, "Llanowar Elves"), 2)
        self.assertEqual(self.rows(after)[0]["quantity"], "1")
        self.assertIn("cards", rules.extra_copies(after.order("partial").audit_notes))
        self.assertIsNone(summary.extra["tables"]["error"])
        with inventory.pinned(after):
            supply = pool.load_pool()
        self.assertEqual(supply.owned["Llanowar Elves"], 3)
        self.assertEqual(sum(qty for _, qty in supply.on_the_way["Llanowar Elves"]), 1)
        self.assertFalse(supply.warnings)

    def test_arrival_of_another_card_does_not_explain_a_remainder_that_was_already_owned(self):
        self.case.cards_csv("collection.csv", ("Llanowar Elves", "fdn", "227", "nonfoil", 2))
        self.case.cards_csv("orders/partial.csv", ("Llanowar Elves", "fdn", "227", "nonfoil", 2),
                           ("Elvish Mystic", "cmm", "648", "nonfoil", 1))
        before = self.backend.load()
        with inventory.pinned(before):
            self.assertFalse(pool.load_pool().warnings)
        index = next(index for index, row in enumerate(self.rows(before), 1) if row["name"] == "Elvish Mystic")
        preview, summary = inventory.preview(self.operation({"id": "cards", "verified": True, "take": [{"row": index}]}))
        self.assertNotIn("cards", rules.extra_copies(preview.order("partial").audit_notes))
        self.assertEqual(self.quantity(preview, "Elvish Mystic"), 1)
        with inventory.pinned(preview):
            self.assertTrue(any("every card in" in warning for warning in pool.load_pool().warnings))
        self.assertTrue(summary.extra["tables"]["error"])
        self.unchanged(before)

    def test_reordered_rows_and_split_printings_select_submitted_indexes_before_sorting(self):
        rows = [support.card("Llanowar Elves", "m19", "314", 3, condition="", language="", notes="Printing inspected"),
                support.card("Llanowar Elves", "fdn", "227", 1, "foil", "LP", "fr"),
                support.card("Elvish Mystic", "cmm", "648", 2, condition="NM", language="en")]
        after, _ = self.apply({"id": "cards", "verified": True, "rows": rows, "take": [{"row": 1, "quantity": 1}]})
        received = self.rows(after, "cards-received-1")
        self.assertEqual([(row["name"], row["set"], row["quantity"], row["condition"], row["language"]) for row in received],
                         [("Llanowar Elves", "m19", "1", "", "")])
        self.assertEqual({(row["set"], row["finish"]): int(row["quantity"]) for row in self.rows(after)},
                         {("cmm", "nonfoil"): 2, ("fdn", "foil"): 1, ("m19", "nonfoil"): 2})

    def test_unticked_unknown_printing_is_left_pending_while_selected_printing_is_checked(self):
        rows = [support.card("Llanowar Elves", "fdn", "227", 4), support.card("Elvish Mystic", "cmm", "9999", 2)]
        after, _ = self.apply({"id": "cards", "verified": True, "rows": rows, "take": [{"row": 1, "quantity": 1}]})
        self.assertEqual(next(row for row in self.rows(after) if row["name"] == "Elvish Mystic")["collector_number"], "9999")
        self.assertEqual(self.quantity(after, "Llanowar Elves"), 1)
        pending = self.rows(after)
        unknown = next(index for index, row in enumerate(pending, 1) if row["collector_number"] == "9999")
        self.refuse({"id": "cards", "verified": True, "rows": pending, "take": [{"row": unknown, "quantity": 1}]})

    def test_stored_printings_are_checked_for_arrived_rows_even_when_no_edited_rows_are_submitted(self):
        self.case.cards_csv("orders/partial.csv", ("Elvish Mystic", "cmm", "9999", "nonfoil", 2),
                           ("Llanowar Elves", "fdn", "227", "nonfoil", 4))
        self.refuse({"id": "cards", "verified": True, "take": [{"row": 1, "quantity": 1}]})
        after, _ = self.apply({"id": "cards", "verified": True, "take": [{"row": 2, "quantity": 1}]})
        self.assertEqual(self.quantity(after, "Llanowar Elves"), 1)
        self.assertTrue(any(row["collector_number"] == "9999" for row in self.rows(after)))

    def test_partial_tokens_count_physical_cards_and_leave_unverified_unticked_pairing_untouched(self):
        before = self.backend.load()
        self.refuse({"id": "tokens", "verified": False, "take": [{"row": 1, "quantity": 1}]})
        after, summary = self.apply({"id": "tokens", "verified": True, "rows": [dict(RABBIT), dict(DOG)],
                                     "take": [{"row": 1, "quantity": 1}]})
        self.assertEqual([(row.front, row.back, row.qty) for row in after.token_set().rows], [("Rabbit", "Rabbit", 1)])
        self.assertEqual(dict(summary.extra["totals"])["physical tokens"]["cards"], 1)
        pending = self.rows(after, "tokens")
        self.assertIn(DOG, pending)
        self.assertEqual(sum(int(row["quantity"]) for row in pending), 2)
        self.assertEqual(self.component(after, "tokens").checks, ["Check physical pairs"])
        self.assertEqual(self.component(after, "tokens-received-1").verified_checks, ["Check physical pairs"])
        self.assertEqual(after.collection(), before.collection())

    def test_take_all_rows_keeps_original_component_id(self):
        after, summary = self.apply({"id": "cards", "verified": True, "take": [{"row": 2}, {"row": 1}]})
        self.assertEqual(summary.extra["assignments"], [{"source": "cards", "received": "cards", "pending": None,
                          "received_quantity": 6, "pending_quantity": 0}])
        self.assertEqual(summary.extra["components"], ["cards"])
        self.assertEqual([part.id for part in after.order("partial").components], ["cards", "tokens", "kit"])
        self.assertEqual(self.component(after).status, "received")
        self.assertEqual(self.quantity(after, "Llanowar Elves"), 4)
        self.refuse({"id": "cards", "verified": True, "take": [{"row": 1}]})

    def test_invalid_selections_are_refused_without_saving_anything(self):
        selections = (None, [], {}, True, "1", [None], [{"row": 0}], [{"row": -1}], [{"row": True}],
                      [{"row": "1"}], [{"row": 1.0}], [{"row": 3}], [{"row": 1}, {"row": 1}],
                      [{"row": 1, "quantity": 0}], [{"row": 1, "quantity": -1}], [{"row": 1, "quantity": 3}],
                      [{"row": 1, "quantity": True}], [{"row": 1, "quantity": "1"}], [{"row": 1, "quantity": 1.0}],
                      [{"row": 1, "quantity": None}], [{"row": 1, "other": 1}])
        for take in selections:
            with self.subTest(take=take):
                self.refuse({"id": "cards", "verified": True, "take": take})
        self.refuse({"id": "missing", "verified": True, "take": [{"row": 1}]})
        before = self.backend.load()
        with self.assertRaises(Invalid):
            self.apply()
        self.unchanged(before)

    def test_products_always_refuse_individual_row_selection(self):
        for take in (None, [], [{"row": 1}]):
            with self.subTest(take=take):
                self.refuse({"id": "kit", "intact": "no", "take": take})

    def test_full_submitted_rows_must_retain_shape_card_names_and_total_quantities(self):
        original = self.rows(self.backend.load())
        for rows in ([original[0]], [{**original[0], "quantity": "1"}, original[1]],
                     [{**original[0], "name": "Opt"}, original[1]],
                     [{key: value for key, value in original[0].items() if key != "notes"}, original[1]]):
            with self.subTest(rows=rows):
                self.refuse({"id": "cards", "verified": True, "rows": rows, "take": [{"row": 1, "quantity": 1}]})

    def test_new_received_ids_skip_component_and_any_status_payload_collisions(self):
        before = self.backend.load()
        record = before.order("partial").record()
        record["components"].append(Component.build("cards-received-1", "cards", "previous.csv", "cancelled").record())
        self.case.write("orders/records/partial.json", rules.json_bytes(record).decode("utf-8"))
        self.case.cards_csv("orders/cancelled/previous.csv", ("Llanowar Elves", "fdn", "227", "nonfoil", 1))
        collision = Order.build("other", components=[Component.build("other", "cards", "partial-cards-received-2.csv", "cancelled")])
        self.case.write("orders/records/other.json", rules.json_bytes(collision.data).decode("utf-8"))
        self.case.cards_csv("orders/cancelled/partial-cards-received-2.csv", ("Llanowar Elves", "fdn", "227", "nonfoil", 1))
        operation = self.operation({"id": "cards", "verified": True, "take": [{"row": 2, "quantity": 1}]})
        preview, proposed = inventory.preview(operation)
        after, summary = inventory.apply(operation, ACTOR, "Receive with fixture collisions")
        self.assertEqual(summary.extra["assignments"][0]["received"], "cards-received-3")
        self.assertEqual(summary.extra["assignments"], proposed.extra["assignments"])
        self.assertEqual(files.render(preview, decks=True), files.render(after, decks=True))

    def test_a_bad_second_component_cannot_save_a_successful_first_partial_receipt(self):
        before = self.backend.load()
        with self.assertRaises(Invalid):
            self.apply({"id": "cards", "verified": True, "take": [{"row": 2, "quantity": 1}]},
                       {"id": "tokens", "verified": True, "rows": [dict(RABBIT), dict(DOG)], "take": [{"row": 2}]})
        self.unchanged(before)

    def test_partial_receipt_preserves_ledger_intent_only_for_pending_copies(self):
        before = self.tracked_order()
        self.assertIsNotNone(order_fulfilment.read(before.order("tracked")))
        self.assertFalse(before.watchlist.rows)
        after, _ = self.apply({"id": "cards", "verified": True, "take": [{"row": 1, "quantity": 1}]}, order="tracked")
        self.assertEqual(self.quantity(after, "Llanowar Elves"), 1)
        after, summary = inventory.apply(inventory.Op("order.cancel", {"order": "tracked", "component": "cards",
                 "reason": "Rest was not supplied", "restore_queue": True}), ACTOR, "Cancel pending fixture copies")
        self.assertEqual([(row["name"], row["quantity"]) for row in summary.extra["queue"]["restored"]], [("Llanowar Elves", "3")])
        self.assertEqual([(row.text("name"), row.qty) for row in after.watchlist.rows], [("Llanowar Elves", 3)])
        self.assertEqual(self.component(after, "cards-received-1", "tracked").status, "received")
        before = self.backend.load()
        with self.assertRaisesRegex(Invalid, "any component has been received"):
            inventory.apply(inventory.Op("order.remove", {"order": "tracked", "reason": "Mistaken order"}), ACTOR, "Refuse removal")
        self.unchanged(before)

    def test_arrived_identical_copies_take_the_fulfilled_claim_before_unfulfilled_pending_copies(self):
        before = self.tracked_order(rows=[support.card("Llanowar Elves", "fdn", "227", 2)], fulfilled=1)
        reduced = before.watchlist
        self.assertEqual(reduced.rows[0].qty, 3)
        self.apply({"id": "cards", "verified": True, "take": [{"row": 1, "quantity": 1}]}, order="tracked")
        after, summary = inventory.apply(inventory.Op("order.cancel", {"order": "tracked", "component": "cards",
                 "reason": "Unfulfilled extra copy not supplied", "restore_queue": True}), ACTOR, "Cancel pending extra copy")
        self.assertEqual(summary.extra["queue"]["restored"], [])
        self.assertEqual(after.watchlist, reduced)
        self.assertEqual(self.quantity(after, "Llanowar Elves"), 1)

    def test_arrival_of_another_printing_cannot_take_an_exact_printing_fulfilment_claim(self):
        inventory.apply(inventory.Op("watchlist.set", {"select": "#1", "values": {"quantity": "1", "printing": "exact",
                        "set": "fdn", "collector_number": "227", "finish": "nonfoil"}, "repo": str(self.root)}),
                        ACTOR, "Choose exact fixture printing")
        before = self.tracked_order(rows=[support.card("Llanowar Elves", "m19", "314", 1),
                                         support.card("Llanowar Elves", "fdn", "227", 1)], fulfilled=1)
        self.assertFalse(before.watchlist.rows)
        index = next(index for index, row in enumerate(self.rows(before, order="tracked"), 1) if row["set"] == "m19")
        self.apply({"id": "cards", "verified": True, "take": [{"row": index}]}, order="tracked")
        after, summary = inventory.apply(inventory.Op("order.cancel", {"order": "tracked", "component": "cards",
                 "reason": "Exact printing not supplied", "restore_queue": True}), ACTOR, "Cancel pending exact printing")
        self.assertEqual([(row["set"], row["collector_number"], row["quantity"]) for row in summary.extra["queue"]["restored"]],
                         [("fdn", "227", "1")])
        self.assertEqual([(row.text("set"), row.qty) for row in after.watchlist.rows], [("fdn", 1)])


class PgPartialReceiptTests(_Fixture, db_support.DbTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from decklab.db import profiles_sync
        profiles_sync.sync(listed=contract.FIXTURE_PROFILES, dbname=cls.dbname)

    def setUp(self):
        super().setUp()
        from decklab.lib.inventory import pg
        from decklab.lib.state import pg as state_pg
        db_support.reset(self.dbname, db_support.INVENTORY_TABLES)
        pg.write_model(contract.adapt(self.backend.load()), contract.CLAUDE, "Import partial-receipt fixture",
                       contents={}, dbname=self.dbname, decks=True)
        self.backend = pg.PgInventory(dbname=self.dbname, breaker=state_pg.Breaker())
        self.addCleanup(inventory.use(self.backend))

    def count(self):
        with self.connect() as connection:
            return connection.execute("select count(*) from audit.change_set").fetchone()[0]

    def test_received_copies_pending_remainder_tables_revisions_and_audit_save_together(self):
        before, count = self.backend.load(), self.count()
        after, summary = self.apply({"id": "cards", "verified": True, "take": [{"row": 2, "quantity": 1}]})
        self.assertEqual(self.count(), count + 1)
        self.assertEqual(self.quantity(after, "Llanowar Elves"), 1)
        self.assertEqual(self.component(after).status, "pending")
        self.assertEqual(self.component(after, "cards-received-1").status, "received")
        self.assertNotEqual(after.revision, before.revision)
        self.assertNotEqual(after.decks_revision, before.decks_revision)
        self.assertEqual(after.decks["casual/partial"].revision, before.decks["casual/partial"].revision + 1)
        self.assertIsNone(summary.extra["tables"]["error"])
        with self.connect() as connection:
            self.assertEqual(connection.execute("select actor, source from audit.change_set order by id desc limit 1").fetchone(),
                             ("matt", "receipt"))
            tables = {row[0] for row in connection.execute("select table_name from audit.row_change "
                      "where change_set_id=(select max(id) from audit.change_set)")}
        self.assertTrue({"collection_card", "order_component", "order_card_item", "deck"} <= tables, tables)

    def test_database_refusal_after_row_writes_rolls_back_split_receipt_revision_and_audit(self):
        from decklab.lib.inventory import pg
        before, count, diff = self.backend.load(), self.count(), pg._diff

        def fail(*args):
            diff(*args)
            raise RuntimeError("Injected partial receipt database failure")

        with mock.patch.object(pg, "_diff", side_effect=fail), self.assertRaisesRegex(Exception, "Injected partial receipt"):
            self.apply({"id": "cards", "verified": True, "take": [{"row": 2, "quantity": 1}]})
        self.unchanged(before)
        self.assertEqual(self.count(), count)
