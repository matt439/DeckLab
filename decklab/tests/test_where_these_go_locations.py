"""Where these go names each card's recorded storage location (E8-S27): the shared name-keyed
lookup (storage_places, which Build decks' storage_locations uses too), the filing advice's and the
receipt's storage_locations from the same saved snapshot, and the command line's merge lines.

Fixture-only: disposable files-backend snapshots, no PostgreSQL, live server or household records.
Run from the repo root: python scripts/test_fixtures.py decklab.tests.test_where_these_go_locations
"""
import json
import unittest
from types import SimpleNamespace
from unittest import mock

from decklab.db import inv_collection
from decklab.lib import inventory
from decklab.lib.api import collection_filing as filing, receipts, storage_places
from decklab.lib.inventory import files, paths, rules
from decklab.tests import test_collection_edit as support, test_collection_filing as filing_tests, test_pool
from decklab.tests import test_receipts_api as receipt_tests

ELVES, deck_text = filing_tests.ELVES, filing_tests.deck_text

setUpModule = test_pool.setUpModule
tearDownModule = test_pool.tearDownModule

ELVES_FOIL = {"name": "Llanowar Elves", "set": "fdn", "collector_number": "227", "finish": "foil"}
ELVES_OLD = {"name": "Llanowar Elves", "set": "lea", "collector_number": "210", "finish": "nonfoil"}


def card_row(card, quantity=1):
    return {**card, "quantity": str(quantity), "condition": "", "language": "", "notes": ""}


def located(snapshot, space, places):
    """snapshot with {(set, number, finish): location} recorded in space."""
    return snapshot.with_locations(space, places)


class LookupTests(unittest.TestCase):

    def inv(self, rows, places, ready=True):
        source = {paths.collection("home"): rules.collection_csv_bytes(rows),
                  paths.STATUS: (",".join(rules.STATUS_FIELDS) + "\n").encode()}
        return located(files.build(source), "home", places).replace(locations_ready=ready)

    def test_places_come_from_any_printing_in_row_order_once_each(self):
        inv = self.inv([card_row(ELVES), card_row(ELVES_FOIL), card_row(ELVES_OLD)],
                       {("fdn", "227", "nonfoil"): "Row 2, B", ("fdn", "227", "foil"): "Binder",
                        ("lea", "210", "nonfoil"): "Row 2, B"})
        # The collection keeps its rows sorted (fdn 227 foil, fdn 227 nonfoil, lea 210 nonfoil).
        self.assertEqual(storage_places.by_name(inv, "home", {"Llanowar Elves", "Shock"}),
                         {"Llanowar Elves": ["Binder", "Row 2, B"]})
        self.assertEqual(storage_places.advice(inv, "home", ["Llanowar Elves", "Shock", "Llanowar Elves"]),
                         {"ready": True, "cards": {"Llanowar Elves": {"places": ["Binder", "Row 2, B"], "more": 0},
                                                   "Shock": {"places": [], "more": 0}}})

    def test_at_most_three_places_then_how_many_more(self):
        printings = [{"name": "Llanowar Elves", "set": f"s{i}", "collector_number": str(i), "finish": "nonfoil"}
                     for i in range(5)]
        inv = self.inv([card_row(card) for card in printings],
                       {(card["set"], card["collector_number"], "nonfoil"): f"Row {i}" for i, card in enumerate(printings)})
        self.assertEqual(storage_places.advice(inv, "home", ["Llanowar Elves"])["cards"]["Llanowar Elves"],
                         {"places": ["Row 0", "Row 1", "Row 2"], "more": 2})

    def test_without_migration_0016_locations_are_unavailable(self):
        inv = self.inv([card_row(ELVES)], {("fdn", "227", "nonfoil"): "Row 2, B"}, ready=False)
        self.assertEqual(storage_places.advice(inv, "home", ["Llanowar Elves"]), {"ready": False, "cards": {}})

    def test_too_many_names_is_a_failed_lookup(self):
        inv = self.inv([], {})
        with self.assertRaises(ValueError):
            storage_places.advice(inv, "home", [f"Card {i}" for i in range(storage_places.MAX_NAMES + 1)])

    def test_another_spaces_locations_never_answer(self):
        source = {paths.collection("home"): rules.collection_csv_bytes([card_row(ELVES)]),
                  paths.collection("user2"): rules.collection_csv_bytes([card_row(ELVES)]),
                  paths.STATUS: (",".join(rules.STATUS_FIELDS) + "\n").encode()}
        inv = located(files.build(source), "user2", {("fdn", "227", "nonfoil"): "Member binder"})
        self.assertEqual(storage_places.advice(inv, "home", ["Llanowar Elves"])["cards"],
                         {"Llanowar Elves": {"places": [], "more": 0}})

    def test_build_decks_keeps_its_answer_through_the_shared_lookup(self):
        from decklab.lib.api import assembly_locations
        answer = {"rows": [], "decks": []}
        assembly_locations.annotate(answer, SimpleNamespace(locations_of=lambda space: {}, locations_ready=False))
        self.assertEqual(answer["storage_locations"], {"ready": False, "cards": {}})


class FilingLocationTests(support.CollectionEditTestCase):
    profile = filing_tests.FilingTests.profile
    snapshot = filing_tests.FilingTests.snapshot
    facts = filing_tests.FilingTests.facts
    advice = filing_tests.FilingTests.advice

    def storage_snapshot(self, places=None, space="home"):
        """Four Elves owned and no deck waiting: two added copies go to storage."""
        snapshot = self.snapshot(4, [("a", deck_text("A", need=1, status="built"))], space=space)
        return located(snapshot, space, places if places is not None else {("fdn", "227", "nonfoil"): "Row 2, B"})

    def test_to_storage_cards_name_where_their_copies_are(self):
        answer = self.advice(self.storage_snapshot())
        self.assertEqual(answer["status"], "ready")
        self.assertEqual([d["kind"] for d in answer["destinations"]], ["storage"])
        self.assertEqual(answer["storage_locations"],
                         {"ready": True, "cards": {"Llanowar Elves": {"places": ["Row 2, B"], "more": 0}}})
        json.dumps(answer, allow_nan=False)

    def test_no_location_yet_is_said_and_deck_destinations_are_not_looked_up(self):
        answer = self.advice(self.storage_snapshot({}))
        self.assertEqual(answer["storage_locations"]["cards"], {"Llanowar Elves": {"places": [], "more": 0}})
        waiting = self.advice()        # every added copy goes to a waiting deck
        self.assertEqual({d["kind"] for d in waiting["destinations"]}, {"deck"})
        self.assertEqual(waiting["storage_locations"], {"ready": True, "cards": {}})

    def test_without_migration_0016_the_advice_says_unavailable(self):
        answer = self.advice(self.storage_snapshot().replace(locations_ready=False))
        self.assertEqual(answer["status"], "ready")
        self.assertEqual(answer["storage_locations"], {"ready": False, "cards": {}})

    def test_a_failed_lookup_leaves_the_rest_of_the_advice(self):
        snapshot = self.storage_snapshot()
        expected = self.advice(snapshot)
        expected.pop("storage_locations")
        with mock.patch.object(storage_places, "advice", side_effect=RuntimeError("fixture")):
            answer = self.advice(snapshot)
        self.assertEqual(answer, expected)
        self.assertEqual(answer["status"], "ready")

    def test_unknown_advice_has_no_locations(self):
        answer = self.advice(self.storage_snapshot(), facts=self.facts(before=9))
        self.assertEqual(answer["status"], "unknown")
        self.assertNotIn("storage_locations", answer)

    def test_a_members_advice_reads_only_their_own_spaces_locations(self):
        snapshot = located(self.storage_snapshot(space="user2"), "home", {("fdn", "227", "nonfoil"): "Home row"})
        answer = self.advice(snapshot, space="user2")
        self.assertEqual(answer["storage_locations"]["cards"]["Llanowar Elves"]["places"], ["Row 2, B"])
        self.assertNotIn("Home row", json.dumps(answer))

    def test_single_card_add_and_cli_merge_carry_them_too(self):
        snapshot = self.storage_snapshot()
        added = filing.after_add(snapshot, "home", self.profile(), self.facts(), 2)
        self.assertEqual(added["storage_locations"]["cards"]["Llanowar Elves"]["places"], ["Row 2, B"])
        merged = filing.after_cli_merge(snapshot, "home", self.facts(), 2)
        self.assertEqual(merged["storage_locations"]["cards"]["Llanowar Elves"]["places"], ["Row 2, B"])
        lines = inv_collection._merge_filing_lines(merged)
        self.assertIn("    2 x Llanowar Elves (FDN 227, nonfoil): usually in Row 2, B", lines)


class CliLineTests(unittest.TestCase):

    def guide(self, found):
        return {"status": "ready", "cards": 2, "added": [{**ELVES, "quantity": 2}],
                "destinations": [{"kind": "storage", "row": 0, "quantity": 2}],
                **({"storage_locations": found} if found is not None else {})}

    def test_each_storage_line_says_where_or_that_none_is_recorded(self):
        many = {"ready": True, "cards": {"Llanowar Elves": {"places": ["Row 1", "Row 2", "Binder"], "more": 2}}}
        self.assertIn("    2 x Llanowar Elves (FDN 227, nonfoil): usually in Row 1; Row 2; Binder and 2 more",
                      inv_collection._merge_filing_lines(self.guide(many)))
        none = {"ready": True, "cards": {"Llanowar Elves": {"places": [], "more": 0}}}
        self.assertIn("    2 x Llanowar Elves (FDN 227, nonfoil): no location recorded yet",
                      inv_collection._merge_filing_lines(self.guide(none)))

    def test_unavailable_or_missing_lookups(self):
        lines = inv_collection._merge_filing_lines(self.guide({"ready": False, "cards": {}}))
        self.assertTrue(any("aren't available yet" in line for line in lines))
        self.assertIn("    2 x Llanowar Elves (FDN 227, nonfoil)", lines)
        self.assertIn("    2 x Llanowar Elves (FDN 227, nonfoil)", inv_collection._merge_filing_lines(self.guide(None)))


class ReceiptLocationTests(receipt_tests.FilesReceiptCase):
    request_data = receipt_tests.WebReceiptTests.request_data
    prepare = receipt_tests.WebReceiptTests.prepare
    record_web = receipt_tests.WebReceiptTests.record_web

    def setUp(self):
        super().setUp()
        self.cards_csv("collection.csv", ("Elvish Mystic", "cmm", "648", "nonfoil", 1),
                       ("Llanowar Elves", "lea", "210", "nonfoil", 1))
        self.write("locations.csv", "set,collector_number,finish,location\nlea,210,nonfoil,\"Row 2, B\"\n")

    def test_the_receipt_answer_names_where_received_cards_are_filed(self):
        result = self.record_web(self.prepare())
        self.assertTrue(result["received"])
        self.assertEqual(result["storage_locations"],
                         {"ready": True, "cards": {"Llanowar Elves": {"places": ["Row 2, B"], "more": 0}}})

    def test_no_location_recorded_yet(self):
        self.write("locations.csv", "set,collector_number,finish,location\n")
        result = self.record_web(self.prepare())
        self.assertEqual(result["storage_locations"]["cards"], {"Llanowar Elves": {"places": [], "more": 0}})

    def test_only_for_viewers_who_see_homes_inventory(self):
        from decklab.lib.api import guard
        preview = self.prepare()
        with mock.patch.object(guard, "sees_inventory", return_value=False):
            result = self.record_web(preview)
        self.assertTrue(result["received"])
        self.assertNotIn("storage_locations", result)

    def test_a_failed_lookup_leaves_the_receipt_and_its_other_advice(self):
        preview = self.prepare()
        with mock.patch.object(storage_places, "advice", side_effect=RuntimeError("fixture")), \
                mock.patch.object(receipts.common, "_log") as log:
            result = self.record_web(preview)
        self.assertTrue(result["received"])
        self.assertNotIn("storage_locations", result)
        self.assertIn("casual/test", result["readiness"])
        self.assertIn("storage locations", log.call_args.args[0])

    def test_without_migration_0016_they_are_unavailable(self):
        real = inventory.apply

        def apply(*args, **kwargs):
            after, summary = real(*args, **kwargs)
            return after.replace(locations_ready=False), summary
        preview = self.prepare()
        with mock.patch.object(inventory, "apply", apply):
            result = self.record_web(preview)
        self.assertEqual(result["storage_locations"], {"ready": False, "cards": {}})


if __name__ == "__main__":
    unittest.main()
