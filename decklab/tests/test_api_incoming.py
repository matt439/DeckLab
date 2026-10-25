"""Deck incoming-card sources: pending record identity, useful quantities and inventory privacy."""
import json
from dataclasses import replace
from unittest import mock

from decklab.lib import access, api, inventory, pool
from decklab.lib.api import guard
from decklab.lib.inventory.model import Component, Order
from decklab.tests.test_api import ApiTestCase, _write
from decklab.tests.test_collection_edit import ROLES


class IncomingSourcesTests(ApiTestCase):

    def setUp(self):
        super().setUp()
        _write(self.box.root / "config.json", json.dumps(ROLES))
        _write(self.box.magic / "collection.csv", "name,set,collector_number,finish,quantity\n")
        _write(self.box.magic / "products/status.csv",
               "file,status,intact,notes\nfdn-beginner-box.csv,owned,no,\nfdc-test-precon.csv,owned,no,\n")
        self.deck(4)

    def deck(self, quantity):
        _write(self.box.magic / "decks/casual/incoming.md",
               f"# Incoming\n\n- **Status:** building\n\n## Decklist\n\n```\nDeck\n{quantity} Sol Ring\n```\n")

    def order(self, order_id, *components):
        order = Order.build(order_id, components=components)
        _write(self.box.magic / "orders/records" / order.file, json.dumps(order.record()))
        return order

    def singles(self, order_id, quantity, filename="cards.csv", status="pending"):
        component = Component.build("cards", "cards", filename, status=status)
        _write(self.box.root / component.path,
               f"name,set,collector_number,finish,quantity\nSol Ring,ecc,57,nonfoil,{quantity}\n")
        self.order(order_id, component)

    def view(self, snapshot=None):
        with inventory.pinned(snapshot):
            answer = api.deck_view("casual/incoming", omit={"matchups"})
        return answer

    def row(self, snapshot=None):
        return self.view(snapshot)["owned"]["rows"][0]

    def test_recorded_order_identity_and_only_required_copies(self):
        # The payload's name isn't the order's: use the record, and don't promise unused copies.
        self.singles("2026-10-14-first-shop", 2, "a-first-parcel.csv")
        self.singles("2026-10-14-second-shop", 5, "b-second-parcel.csv")
        row = self.row()
        self.assertEqual(row["missing"], 0)
        self.assertEqual(row["labels"]["incoming_sources"], [
            {"source": "order 2026-10-14-first-shop", "quantity": 2,
             "order_id": "2026-10-14-first-shop", "component_id": "cards", "product_id": None,
             "status": "ordered"},
            {"source": "order 2026-10-14-second-shop", "quantity": 2,
             "order_id": "2026-10-14-second-shop", "component_id": "cards", "product_id": None,
             "status": "ordered"}])
        self.assertEqual(row["labels"]["on_the_way"], [["order a-first-parcel", 2], ["order b-second-parcel", 2]])

    def test_products_keep_identity_and_ordered_or_preordered_status(self):
        self.order("2026-10-14-products",
                   Component.build("first", "product", "first.csv"),
                   Component.build("second", "product", "second.csv"))
        for stem in ("first", "second"):
            _write(self.box.magic / f"products/{stem}.csv",
                   "name,set,collector_number,finish,quantity\nSol Ring,ecc,57,nonfoil,3\n")
        _write(self.box.magic / "products/status.csv",
               "file,status,intact,notes\nfirst.csv,ordered,,\nsecond.csv,preordered,,\n")
        snapshot = self.box.inventory.load()
        # Equal display names must not merge distinct shipments/statuses.
        for stem in ("first", "second"):
            snapshot = snapshot.with_product(replace(snapshot.product(stem), name="Two matching precons"))
        sources = self.row(snapshot)["labels"]["incoming_sources"]
        self.assertEqual(sources, [
            {"source": "Two matching precons", "quantity": 3, "order_id": "2026-10-14-products",
             "component_id": "first", "product_id": "first", "status": "ordered"},
            {"source": "Two matching precons", "quantity": 1, "order_id": "2026-10-14-products",
             "component_id": "second", "product_id": "second", "status": "preordered"}])
        arrived = snapshot.with_status_rows([row.replace(status="owned", intact="no")
                                             for row in snapshot.status.rows])
        self.assertEqual(self.row(arrived)["labels"]["incoming_sources"], [])

    def test_owned_copies_and_missing_copies_are_not_labelled_incoming(self):
        _write(self.box.magic / "collection.csv",
               "name,set,collector_number,finish,quantity\nSol Ring,cmm,400,nonfoil,2\n")
        self.singles("2026-10-14-shop", 1)
        row = self.row()
        self.assertEqual((row["missing"], sum(s["quantity"] for s in row["labels"]["incoming_sources"])), (1, 1))
        self.deck(2)
        self.assertEqual(self.row()["labels"]["incoming_sources"], [])

    def test_received_and_cancelled_singles_are_not_incoming(self):
        self.singles("2026-10-14-received", 4, "received.csv", "received")
        self.singles("2026-10-14-cancelled", 4, "cancelled.csv", "cancelled")
        row = self.row()
        self.assertEqual(row["missing"], 4)
        self.assertEqual(row["labels"]["incoming_sources"], [])

    def test_order_details_use_the_same_pinned_snapshot(self):
        self.singles("2026-10-14-original", 4)
        real_load = self.box.inventory.load
        with mock.patch.object(self.box.inventory, "load", wraps=real_load) as load:
            with inventory.pinned():
                snapshot = inventory.current()
                self.singles("2026-10-14-later", 7, "later.csv")
                answer = api.deck_view("casual/incoming", omit={"matchups"})
                self.assertIs(inventory.current(), snapshot)
            load.assert_called_once()
        self.assertEqual([s["order_id"] for s in answer["owned"]["rows"][0]["labels"]["incoming_sources"]],
                         ["2026-10-14-original"])

    def test_home_sources_hidden_from_other_spaces_without_loading_pool(self):
        self.singles("2026-10-14-private-shop", 4)
        with access.using({"profile": "user2", "email": "", "remote": True}):
            self.assertApiError(404, self.view)         # home's decks are home's alone (E10-S30)
        public = mock.patch.object(guard, "public_deck_spaces", return_value=frozenset({"home"}))
        for remote in (False, True):                    # a home deck made public, its inventory not
            with self.subTest(remote=remote), public, access.viewing("user2"), access.using(
                    {"profile": "user2", "email": "", "remote": True} if remote else None):
                with mock.patch.object(pool, "load_pool", side_effect=AssertionError("private pool read")):
                    answer = self.view()
                self.assertNotIn("owned", answer)
                self.assertNotIn("2026-10-14-private-shop", json.dumps(answer))
        for who in ("matt", "user1"):
            with self.subTest(viewer=who), access.viewing(who), access.using(None):
                self.assertEqual(self.row()["labels"]["incoming_sources"][0]["order_id"],
                                 "2026-10-14-private-shop")

    def test_personal_pool_does_not_count_home_orders(self):
        self.singles("2026-10-14-home", 4)
        _write(self.box.magic / "people/user2/decks/casual/incoming.md",
               "# User2 Incoming\n\n- **Status:** building\n\n## Decklist\n\n```\nDeck\n4 Sol Ring\n```\n")
        with access.viewing("user2"), access.using(None), inventory.pinned():
            answer = api.deck_view("user2/casual/incoming", omit={"matchups"})
        row = answer["owned"]["rows"][0]
        self.assertEqual((row["missing"], row["on_the_way"]), (4, 0))
        self.assertEqual(row["labels"]["incoming_sources"], [])
        self.assertNotIn("2026-10-14-home", json.dumps(answer))
