"""Last changed metadata on the library and deck page (E11-S30).

The files sandbox keeps no history; fixed metadata stands in for the inventory's
latest meaningful deck edits, without opening a database or reading revision text.
"""
import json
from datetime import datetime, timedelta, timezone
from unittest import mock

from decklab.lib import access, api, decks, inventory
from decklab.lib.api import library
from decklab.tests.test_api import ApiTestCase
from decklab.tests.test_api_permissions import PermissionTestCase


DECK_ID = "casual/gruul-test"
EDITED = datetime(2026, 10, 25, 15, 4, 3, 987654, tzinfo=timezone(timedelta(hours=10)))
EDITED_UTC = "2026-10-25T05:04:03+00:00"


class LastChangedTests(ApiTestCase):

    def test_both_lists_match_the_librarys_utc_timestamp(self):
        with mock.patch.object(inventory, "deck_edited", return_value={DECK_ID: EDITED}) as read:
            index = {d["id"]: d for d in api.decks_index()["decks"]}
            self.assertEqual(index[DECK_ID]["edited"], EDITED_UTC)
            read.assert_called_once_with()       # one metadata read for the whole shelf
            for version in ("target", "owned"):
                with self.subTest(version=version):
                    read.reset_mock()
                    view = api.deck_view(DECK_ID, version, omit={"matchups"})
                    self.assertEqual(view["summary"]["edited"], index[DECK_ID]["edited"])
                    read.assert_called_once_with()

    def test_unknown_dates_and_products_and_pairings_are_null(self):
        for deck_id in (DECK_ID, "product/fdc-test-precon", "pairing/cats+elves"):
            with self.subTest(deck=deck_id):
                # The files backend has no edit history; a product/pairing has no deck text.
                self.assertIsNone(api.deck_view(deck_id)["summary"]["edited"])

    def test_a_naive_metadata_timestamp_is_utc(self):
        at = EDITED.replace(tzinfo=None)
        with mock.patch.object(inventory, "deck_edited", return_value={DECK_ID: at}):
            self.assertEqual(api.deck_view(DECK_ID)["summary"]["edited"], "2026-10-25T15:04:03+00:00")

    def test_read_failure_leaves_the_deck_usable_and_details_only_in_the_log(self):
        detail = "hidden/casual/secret revision actor@example.com"
        with mock.patch.object(inventory, "deck_edited", side_effect=RuntimeError(detail)):
            view = api.deck_view(DECK_ID)
            index = api.decks_index()
        self.assertIsNone(view["summary"]["edited"])
        self.assertTrue(view["sections"]["Deck"])
        self.assertTrue(all(d["edited"] is None for d in index["decks"]))
        self.assertNotIn(detail, json.dumps([view, index]))
        self.assertTrue(any(detail in line for line in self.box.logs))

    def test_timestamp_projection_reads_no_decklists_or_revision_history(self):
        with mock.patch.object(inventory, "deck_edited", return_value={DECK_ID: EDITED}) as read, \
                mock.patch.object(decks, "list_decks", side_effect=AssertionError("no deck scan")), \
                mock.patch.object(decks, "load_deck", side_effect=AssertionError("no deck load")), \
                mock.patch.object(inventory, "deck_revisions_with_text", side_effect=AssertionError("no revision history")):
            self.assertEqual(library.edited_at(DECK_ID), EDITED_UTC)
        read.assert_called_once_with()


class LastChangedVisibilityTests(PermissionTestCase):

    def test_hidden_and_missing_decks_are_denied_before_the_metadata_read(self):
        with access.using({"profile": "user2", "email": "", "remote": True}), \
                mock.patch.object(inventory, "deck_edited", side_effect=AssertionError("no hidden metadata")) as read:
            for deck_id in (DECK_ID, "casual/no-such-deck"):
                with self.subTest(deck=deck_id):
                    error = self.assertApiError(404, api.deck_view, deck_id)
                    self.assertEqual(error.message, f"No deck {deck_id!r}")
                    self.assertEqual(error.extra, {})
        read.assert_not_called()

    def test_only_the_requested_visible_decks_timestamp_is_returned(self):
        own_id = "user2/casual/r-elves"
        other_at = datetime(2026, 10, 24, 1, 2, 3, tzinfo=timezone.utc)
        with access.using({"profile": "user2", "email": "", "remote": True}), \
                mock.patch.object(inventory, "deck_edited", return_value={own_id: EDITED, DECK_ID: other_at}):
            view = api.deck_view(own_id)
        self.assertEqual(view["summary"]["edited"], EDITED_UTC)
        shown = json.dumps(view)
        self.assertNotIn(DECK_ID, shown)
        self.assertNotIn(other_at.isoformat(), shown)
