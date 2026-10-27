"""An intact product's box label (E8-S21): GET /api/deck's box_label over disposable product records.

No server is touched; the inventory is PoolTestCase's temp files.
"""
from unittest import mock

from decklab.lib import access, decks
from decklab.lib.api import product_label, settings
from decklab.lib.decks.identity import CardIdentityError
from decklab.tests.test_assembly_completion import PROFILES
from decklab.tests.test_pool import PoolTestCase, setUpModule, tearDownModule  # noqa: F401

STEM = "fixture-box"


class ProductLabelTests(PoolTestCase):
    def setUp(self):
        super().setUp()
        patch = mock.patch.object(settings, "_config_profiles", return_value=PROFILES)
        patch.start()
        self.addCleanup(patch.stop)
        self.product(f"{STEM}.csv", ("Elves", "Llanowar Elves", 4), ("Elves", "Forest", 20),
                     ("Control", "Rhystic Study", 4), ("Control", "Wrath of God", 4))
        self.status((f"{STEM}.csv", "owned", "yes"))

    def test_an_intact_product_gets_one_label_for_all_its_decks(self):
        routes = [d["id"] for d in decks._product_decks() if d["product"] == STEM]
        for route in routes:                        # the same label from every one of its pages
            with self.subTest(route=route):
                label = product_label.box_label(route)
                self.assertEqual(label["name"], "Fixture Box")
                self.assertEqual(label["colors"], ["W", "U", "G"])
                self.assertEqual([d["title"] for d in label["decks"]], ["Elves", "Control"])
                self.assertEqual([d["id"] for d in label["decks"]], routes)
                self.assertEqual(label["link"], routes[0])

    def test_a_single_unnamed_deck_links_its_own_page(self):
        self.product("solo.csv", ("deck", "Sol Ring", 1), column="section")
        self.status((f"{STEM}.csv", "owned", "yes"), ("solo.csv", "owned", "yes"))
        label = product_label.box_label("product/solo")
        self.assertEqual((label["link"], label["colors"]), ("product/solo", []))
        self.assertEqual(label["decks"], [{"id": "product/solo", "title": "Solo"}])

    def test_only_an_owned_product_kept_intact(self):
        route = f"product/{STEM}/elves"
        for status, intact in (("owned", "no"), ("owned", ""), ("ordered", ""), ("cancelled", "")):
            with self.subTest(status=status, intact=intact):
                self.status((f"{STEM}.csv", status, intact))
                self.assertIsNone(product_label.box_label(route))
        self.assertIsNone(product_label.box_label("casual/anything"))
        self.assertIsNone(product_label.box_label("pairing/a+b"))

    def test_only_viewers_of_home_records(self):
        route = f"product/{STEM}/elves"
        with access.using({"profile": "user1", "email": "", "remote": True}):
            self.assertIsNotNone(product_label.box_label(route))
        with access.using({"profile": "user2", "email": "", "remote": True}), \
                mock.patch.object(decks, "_product_decks", side_effect=AssertionError("guard first")):
            self.assertIsNone(product_label.box_label(route))

    def test_damaged_colour_data_leaves_only_the_colours_out(self):
        with mock.patch.object(product_label, "deck_colors", side_effect=CardIdentityError("bad identity")),                 mock.patch.object(product_label.common, "_log") as log:
            label = product_label.box_label(f"product/{STEM}/elves")
        self.assertIsNone(label["colors"])
        self.assertEqual([d["title"] for d in label["decks"]], ["Elves", "Control"])
        log.assert_called_once()

    def test_a_failure_leaves_the_label_out(self):
        with mock.patch.object(decks, "_product_decks", side_effect=OSError("unreadable")), \
                mock.patch.object(product_label.common, "_log") as log:
            self.assertIsNone(product_label.box_label(f"product/{STEM}/elves"))
        log.assert_called_once()


if __name__ == "__main__":
    import unittest
    unittest.main()
