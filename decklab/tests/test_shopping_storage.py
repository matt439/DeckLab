"""Shopping's storage fill (E8-S25 slice 7, lib/api/shopping_storage.py): home's containers with a
capacity, how full each is now and once the pending orders arrive, from the Card list's own count and
pending-delivery scenario; only for home-record readers, and left out whenever it can't be said.

Run from the repo root: python scripts/test_fixtures.py decklab.tests.test_shopping_storage
"""
import contextlib
import copy
import unittest
from unittest import mock

from decklab.lib import access, inventory, storage_setting
from decklab.lib.api import collection_edit as ce
from decklab.lib.api import collection_forecast, common, shopping, shopping_storage
from decklab.lib.state import space_storage
from decklab.tests import test_shopping_missing as fixtures


def view(record, source="saved"):
    record = space_storage.normalize(record)
    return lambda space, seed=True: {"space": space, "revision": 1, "ready": True, "source": source, "storage": record}


def forecast(**changes):
    answer = {"status": "partial", "stale": False, "box_candidates": 2, "by_container": {"box": 2, "binder": 3},
              "sources": [{"kind": "cards"}], "omitted_sources": 0, "unknown_sources": 1,
              "pending_products": {"count": 2, "known_reference_cards": 100, "unknown_contents": 0},
              "tokens_excluded": {"known_cards": 4, "unknown_components": 0}}
    answer.update(changes)
    return answer


TWO = {"default": "box", "containers": [
    {"id": "box", "name": "Storage box", "capacity": 10, "sections": ["Row 1"]},
    {"id": "binder", "name": "Binder", "kind": "binder", "capacity": 6},
    {"id": "shelf", "name": "Shelf", "kind": "shelf"}]}


class GatherTests(unittest.TestCase):
    """gather() only joins the Card list's two answers: storage_setup's counts and the scenario's routing."""

    def gather(self, record=TWO, scenario=None, counts=None):
        setup = {"containers": [dict(c, cards=n) for c, n in zip(space_storage.normalize(record)["containers"],
                                                                 counts or (7, 4, 50))]}
        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch.object(storage_setting, "current", view(record)))
            stack.enter_context(mock.patch.object(ce, "_read", return_value=([], "sha")))
            stack.enter_context(mock.patch.object(ce, "_prices", return_value={"rows": {}}))
            stack.enter_context(mock.patch.object(ce, "_storage", return_value={"rows": {}, "error": None}))
            stack.enter_context(mock.patch("decklab.lib.api.collection_locations.storage_setup", return_value=setup))
            stack.enter_context(mock.patch("decklab.lib.api.collection_locations.storage_box", return_value=None))
            built = stack.enter_context(mock.patch.object(collection_forecast, "build",
                                                          return_value=forecast() if scenario is None else scenario))
            return shopping_storage.gather(), built

    def test_each_container_with_a_capacity_now_and_after(self):
        fill, built = self.gather()
        self.assertEqual(built.call_args.args[0], "home")
        self.assertEqual(fill["containers"], [
            {"id": "box", "name": "Storage box", "kind": "box", "capacity": 10, "now": 7, "incoming": 2, "after": 9,
             "over_now": False, "over_after": False},
            {"id": "binder", "name": "Binder", "kind": "binder", "capacity": 6, "now": 4, "incoming": 3, "after": 7,
             "over_now": False, "over_after": True}])                    # the shelf has no capacity
        self.assertEqual((fill["status"], fill["default"], fill["unknown_sources"], fill["pending_products"],
                          fill["tokens_excluded"]), ("partial", "Storage box", 1, 2, True))

    def test_nothing_when_there_is_nothing_to_say(self):
        for scenario in (forecast(status="unknown"), forecast(stale=True), forecast(box_candidates=None),
                         forecast(sources=[], omitted_sources=0), forecast(by_container=None)):
            with self.subTest(scenario=scenario):
                self.assertIsNone(self.gather(scenario=scenario)[0])
        self.assertIsNone(self.gather(counts=(None, None, None))[0])      # the copies in decks unknown
        self.assertIsNone(self.gather(scenario=False)[0])                 # build's None (no home records)

    def test_no_capacity_reads_nothing(self):
        for record in ({"containers": []}, {"default": "shelf", "containers": [{"name": "Shelf", "kind": "shelf"}]}):
            with self.subTest(record=record), mock.patch.object(storage_setting, "current", view(record)), \
                    mock.patch.object(ce, "_read", side_effect=AssertionError("no collection read")):
                self.assertIsNone(shopping_storage.gather())


class EnrichTests(unittest.TestCase):
    def setUp(self):
        self.logs = []
        patcher = mock.patch.object(common, "_log", self.logs.append)
        patcher.start()
        self.addCleanup(patcher.stop)

    def enrich(self, *, records=True, inventory_=True, gather=None):
        answer = {"orders": []}
        with mock.patch.object(shopping_storage.guard, "sees_home_records", return_value=records), \
                mock.patch.object(shopping_storage.guard, "sees_inventory", return_value=inventory_), \
                mock.patch.object(shopping_storage, "gather", gather or (lambda: {"containers": []})):
            return shopping_storage.enrich(answer)

    def test_only_for_home_record_and_inventory_readers(self):
        self.assertIn("storage_fill", self.enrich())
        for records, inventory_ in ((False, True), (True, False)):
            with self.subTest(records=records, inventory_=inventory_):
                gather = mock.Mock(side_effect=AssertionError("private"))
                self.assertNotIn("storage_fill", self.enrich(records=records, inventory_=inventory_, gather=gather))
                gather.assert_not_called()

    def test_a_failure_or_none_leaves_shopping_as_it_was(self):
        self.assertEqual(self.enrich(gather=lambda: None), {"orders": []})
        self.assertEqual(self.enrich(gather=mock.Mock(side_effect=ValueError("Binder secret"))), {"orders": []})
        self.assertEqual(len(self.logs), 1)
        self.assertNotIn("Binder secret", self.logs[0])


class ShoppingStorageFillTests(fixtures._Fixture, unittest.TestCase):
    """The fixture inventory: home's built-in box holds 3 free copies and a pending order brings 2 more loose
    cards (plus one product, undecided)."""

    def setUp(self):
        super().setUp()
        patcher = mock.patch.object(inventory, "apply", side_effect=AssertionError("Shopping's storage fill only reads"))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_the_built_in_box_matches_the_card_lists_count_and_scenario(self):
        before = self.backend.load()
        fill = self.overview()["storage_fill"]
        rows = ce.rows_view("home")
        box = rows["storage_setup"]["containers"][0]
        self.assertEqual(fill["containers"], [{"id": "box", "name": "Storage box", "kind": "box", "capacity": 2400,
                                               "now": box["cards"], "incoming": rows["storage_forecast"]["by_container"]["box"],
                                               "after": 5, "over_now": False, "over_after": False}])
        self.assertEqual((box["cards"], fill["default"], fill["pending_products"], fill["unknown_sources"]),
                         (3, "Storage box", 1, 0))
        self.assertEqual(self.backend.load(), before)

    def test_a_saved_setup_names_its_containers(self):
        record = {"default": "binder", "containers": [
            {"id": "box", "name": "Box", "sections": ["Row 1"]},
            {"id": "binder", "name": "Binder", "kind": "binder", "capacity": 4, "sleeved": True}]}
        with mock.patch.object(storage_setting, "current", view(record)):
            fill = self.overview()["storage_fill"]
        self.assertEqual([(c["name"], c["now"], c["after"], c["over_after"]) for c in fill["containers"]],
                         [("Binder", 3, 5, True)])
        self.assertEqual(fill["default"], "Binder")
        with mock.patch.object(storage_setting, "current", view({"containers": []})):
            self.assertNotIn("storage_fill", self.overview())

    def test_an_unreadable_scenario_leaves_it_out(self):
        unknown = collection_forecast._unavailable(None)
        with mock.patch.object(collection_forecast, "build", return_value=copy.deepcopy(unknown)):
            answer = self.overview()
        self.assertNotIn("storage_fill", answer)
        self.assertIn("orders", answer)

    def test_viewers_outside_home_records_get_nothing(self):
        for identity in ({"profile": "user2", "email": "", "remote": True},
                         {"profile": None, "email": "", "remote": False}):
            with self.subTest(identity=identity), access.using(identity), \
                    mock.patch.object(shopping_storage, "gather", side_effect=AssertionError("private")) as gather:
                with self.assertRaises(common.ApiError) as error:
                    shopping.shopping_overview()
                self.assertEqual(error.exception.status, 403)
                gather.assert_not_called()


if __name__ == "__main__":
    unittest.main()
