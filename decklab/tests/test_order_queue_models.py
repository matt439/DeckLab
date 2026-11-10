"""Order audit projections roundtrip independently of another member's private sources."""
import copy

from decklab.lib import inventory
from decklab.lib.inventory import model, order_queue_models as projection
from decklab.tests import test_collection_edit as fixture


class OrderQueueModelTests(fixture.CollectionEditTestCase):
    def setUp(self):
        super().setUp()
        order = model.Order.build("fixture-order", "Fixture shop", "2026-11-11", [], "", [
            model.Component.build("cards", "cards", "fixture-order.csv")])
        card = {"name": "Llanowar Elves", "set": "fdn", "collector_number": "227", "finish": "nonfoil",
                "quantity": "2", "condition": "", "language": "", "notes": ""}
        source = inventory.current().with_order(order).set_component_rows(order.id, "cards", [card])
        self.backend.load = lambda: source

    def test_order_resource_images_rebuild_exactly_without_touching_any_collection_or_deck(self):
        before = inventory.current()
        images = projection.images(before)
        rebuilt = projection.restore(before, images, images)
        self.assertEqual(rebuilt, before)
        self.assertTrue(images[projection.ORDER])
        for image in images[projection.ORDER].values():
            self.assertEqual(set(image), {"id", "seller", "ordered_on", "sources", "notes", "audit_notes"})

    def test_current_member_parse_failures_never_enter_the_home_order_projection(self):
        before = inventory.current()
        expected = projection.images(before)
        other = model.Deck("user2", "casual", "unreadable", None, "Synthetic private read failure")
        unknown = before.replace(decks={**before.decks, other.id: other})
        self.assertEqual(projection.images(unknown), expected)
        self.assertEqual(projection.restore(unknown, expected, expected), unknown)

    def test_known_additive_check_metadata_is_the_only_legacy_component_schema_bridge(self):
        image = next(iter(projection.images(inventory.current())[projection.COMPONENT].values()))
        historical = {key: value for key, value in image.items() if key != "check_links"}
        self.assertEqual(projection.normalized(projection.COMPONENT, historical), {**image, "check_links": None})
        with self.assertRaises(ValueError):
            projection.normalized(projection.COMPONENT, {**image, "unexpected": "No"})

    def test_one_order_header_edit_rebuilds_only_that_header_and_predicts_one_audited_update(self):
        before = inventory.current()
        old = projection.images(before)
        wanted = copy.deepcopy(old)
        identity = next(iter(wanted[projection.ORDER]))
        oid = wanted[projection.ORDER][identity]["id"]
        wanted[projection.ORDER][identity]["notes"] = "Historical fixture note"
        after = projection.restore(before, old, wanted)
        self.assertEqual(after.order(oid).notes, "Historical fixture note")
        self.assertEqual(after.collections, before.collections)
        self.assertEqual(after.decks, before.decks)
        delta = projection.audit_delta(old, projection.images(after))
        self.assertEqual(len(delta), 1)
        self.assertIn('"purchase_order","UPDATE"', delta[0])
