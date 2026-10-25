"""Reprint evidence is read-only and follows each inventory-visible response."""
import copy
import json
import unittest
from unittest import mock

from decklab.lib import api, inventory
from decklab.lib.api import guard, reprints, shopping, shopping_queue
from decklab.tests.test_api import ApiTestCase
from decklab.tests import test_shopping_queue as queue_fixture


UPCOMING = {"ready": True, "as_of": "2026-10-16", "data_date": "2026-10-15",
            "coverage": "Known cached paper printings only", "upcoming": [
                {"set": "abc", "set_name": "Fixture expansion", "released_at": "2026-11-20",
                 "source_url": "https://scryfall.com/card/abc/1"}], "released": [],
            "price_check": {"offered": False, "reason": None, "checked": None}, "notes": [],
            "source_url": "https://scryfall.com/search?q=fixture"}


class ReprintProjectionTests(unittest.TestCase):
    def test_decorates_only_missing_rows_and_never_overwrites_existing_observations(self):
        rows = [{"name": "First", "missing": 1, "checked": "2026-01-02", "listed_aud": "1.25"},
                {"name": "Owned", "missing": 0}]
        with mock.patch.object(reprints, "is_token", return_value=False), \
                mock.patch.object(reprints.catalogue, "for_card", return_value=copy.deepcopy(UPCOMING)) as lookup:
            reprints.enrich(rows)
        self.assertEqual(lookup.call_args_list, [mock.call("First", checked=None, waiting=False)])
        self.assertIn("reprints", rows[0])
        self.assertNotIn("reprints", rows[1])
        self.assertEqual((rows[0]["checked"], rows[0]["listed_aud"]), ("2026-01-02", "1.25"))

    def test_request_cache_keeps_distinct_price_check_dates_and_waiting_states(self):
        rows = [{"name": "Same", "state": "waiting_for_reprint", "checked": "2026-01-01"},
                {"name": "Same", "state": "waiting_for_reprint", "checked": "2026-01-01"},
                {"name": "Same", "state": "waiting_for_reprint", "checked": "2026-02-01"},
                {"name": "Same", "state": "ready", "checked": "2026-01-01"}]
        with mock.patch.object(reprints, "is_token", return_value=False), \
                mock.patch.object(reprints.catalogue, "for_card", return_value=copy.deepcopy(UPCOMING)) as lookup:
            reprints.enrich(rows, queued=True)
        self.assertEqual(lookup.call_count, 3)
        self.assertEqual([call.kwargs for call in lookup.call_args_list], [
            {"checked": "2026-01-01", "waiting": True}, {"checked": "2026-02-01", "waiting": True},
            {"checked": "2026-01-01", "waiting": False}])

    def test_quiet_defaults_and_positive_token_identity_do_not_borrow_card_evidence(self):
        quiet = {**UPCOMING, "upcoming": [], "released": []}
        rows = [{"name": "Normal", "missing": 2}, {"name": "Token", "missing": 1, "is_token": True}]
        with mock.patch.object(reprints, "is_token", return_value=False), \
                mock.patch.object(reprints.catalogue, "for_card", return_value=quiet) as lookup:
            reprints.enrich(rows)
        self.assertEqual(lookup.call_count, 1)
        self.assertTrue(all("reprints" not in row for row in rows))

    def test_optional_enrichment_failure_does_not_raise_after_a_queue_save(self):
        with mock.patch.object(reprints, "is_token", return_value=False), \
                mock.patch.object(reprints.catalogue, "for_card", side_effect=ValueError("Fixture failure")), \
                mock.patch.object(reprints.common, "_log") as logged:
            self.assertIsNone(reprints.evidence({"name": "A", "state": "waiting_for_reprint"}, queued=True))
        logged.assert_called_once()


class ReprintApiTests(ApiTestCase):
    def test_deck_missing_evidence_is_visible_only_with_inventory(self):
        with mock.patch.object(reprints.catalogue, "for_card", return_value=copy.deepcopy(UPCOMING)) as lookup:
            visible = api.deck_view("casual/gruul-test", omit={"matchups"})
            self.assertTrue(any("reprints" in row for row in visible["owned"]["rows"]))
            self.assertTrue(all(row["missing"] > 0 for row in visible["owned"]["rows"] if "reprints" in row))
            lookup.reset_mock()
            with mock.patch.object(guard, "sees_inventory", return_value=False):
                hidden = api.deck_view("casual/gruul-test", omit={"matchups"})
            self.assertNotIn("owned", hidden)
            lookup.assert_not_called()

    def test_shopping_projects_queue_and_combined_missing_rows_without_writes(self):
        observed = {"name": "Llanowar Elves", "quantity": 2, "state": "waiting_for_reprint",
                    "checked": "2026-01-01", "listed_aud": "0.50", "listed_at": "Fixture shop",
                    "in_stock": "no", "printing": "exact", "source": "", "for": "Fixture"}
        before = inventory.current()
        with mock.patch.object(shopping.purchases, "overview", return_value={"to_buy": [copy.deepcopy(observed)], "orders": [],
                                                                          "checks": [], "warnings": []}), \
                mock.patch.object(shopping, "_cards_ready", return_value=True), \
                mock.patch.object(shopping.shopping_missing, "gather", return_value=(
                    {"ready": True, "rows": [{"name": "Llanowar Elves", "missing": 2}],
                     "errors": [], "warnings": [], "totals": {"cards": 1, "copies": 2}}, [])), \
                mock.patch.object(reprints.catalogue, "for_card", return_value=copy.deepcopy(UPCOMING)), \
                mock.patch.object(inventory, "apply", side_effect=AssertionError("Read must not save")):
            answer = shopping.shopping_overview()
        self.assertIn("reprints", answer["to_buy"][0])
        self.assertTrue(any("reprints" in row for row in answer["missing_cards"]["rows"]))
        self.assertEqual({key: answer["to_buy"][0][key] for key in observed}, observed)
        self.assertEqual(inventory.current(), before)

    def test_shopping_permission_is_checked_before_any_card_evidence(self):
        with mock.patch.object(guard, "require_sees_home_records", side_effect=api.ApiError(403, "Private")), \
                mock.patch.object(reprints.catalogue, "for_card") as lookup:
            self.assertApiError(403, shopping.shopping_overview)
        lookup.assert_not_called()


class QueueReprintProjectionTests(unittest.TestCase):
    setUp = queue_fixture.FileQueueStateTests.setUp
    start = queue_fixture.QueueStateTests.start
    save = queue_fixture.QueueStateTests.save

    def test_a_state_save_returns_fresh_evidence_without_changing_the_price_check(self):
        before = self.backend.load()
        with mock.patch.object(reprints.catalogue, "for_card", return_value=copy.deepcopy(UPCOMING)) as lookup:
            answer = self.save(state="waiting_for_reprint")
        self.assertEqual(answer["reprints"], UPCOMING)
        lookup.assert_called_once_with("Pick Your Poison", checked="2026-10-05", waiting=True)
        after = self.backend.load()
        self.assertEqual(after.watchlist.rows[1].checked, before.watchlist.rows[1].checked)
        self.assertEqual(after.watchlist.rows[1].listed_aud, before.watchlist.rows[1].listed_aud)
        self.assertEqual(after.watchlist.rows[1].printing, "exact")

    def test_an_enrichment_problem_does_not_report_an_already_saved_change_as_failed(self):
        with mock.patch.object(reprints.catalogue, "for_card", side_effect=ValueError("Optional fixture failure")), \
                mock.patch.object(reprints.common, "_log"):
            answer = self.save(state="deferred")
        self.assertTrue(answer["saved"])
        self.assertIsNone(answer["reprints"])
        self.assertEqual(self.backend.load().watchlist.rows[1].state, "deferred")

    def test_stale_queue_save_does_not_prepare_evidence_or_change_observations(self):
        before = self.backend.load()
        with mock.patch.object(reprints, "evidence") as evidence, \
                mock.patch.object(inventory, "apply") as apply, \
                self.assertRaises(api.ApiError) as caught:
            self.save(state="ready", expect="stale")
        self.assertEqual(caught.exception.status, 409)
        evidence.assert_not_called()
        apply.assert_not_called()
        after = self.backend.load()
        self.assertEqual(after.revision, before.revision)
        self.assertEqual(queue_fixture.files.render(after), queue_fixture.files.render(before))
        self.assertEqual((after.watchlist.rows[1].state, after.watchlist.rows[1].checked,
                          after.watchlist.rows[1].listed_aud),
                         ("waiting_for_reprint", "2026-10-05", "0.50"))

    def test_refused_backend_save_does_not_prepare_evidence_or_change_observations(self):
        before = self.backend.load()
        for error, status in ((inventory.Conflict("Fixture conflict"), 409),
                              (inventory.Unavailable("Fixture unavailable"), 503),
                              (inventory.Invalid("Fixture refused"), 400)):
            with self.subTest(status=status), mock.patch.object(reprints, "evidence") as evidence, \
                    mock.patch.object(inventory, "apply", side_effect=error), \
                    self.assertRaises(api.ApiError) as caught:
                self.save(state="ready")
            self.assertEqual(caught.exception.status, status)
            evidence.assert_not_called()
            after = self.backend.load()
            self.assertEqual(after.revision, before.revision)
            self.assertEqual(queue_fixture.files.render(after), queue_fixture.files.render(before))
            self.assertEqual((after.watchlist.rows[1].state, after.watchlist.rows[1].checked,
                              after.watchlist.rows[1].listed_aud),
                             ("waiting_for_reprint", "2026-10-05", "0.50"))
