"""A personal upgrade checklist works without card data, saved decks or a counted inventory."""
import json
from unittest import mock

from decklab.lib import access, cards, inventory, state
from decklab.lib.api import deck_checklist
from decklab.lib.api.common import ApiError, MAX_EDIT_BODY
from decklab.lib.state.upgrade_checklist import MissingSchema
from decklab.tests.test_api_permissions import PermissionTestCase


class DeckChecklistTests(PermissionTestCase):
    def test_linked_lists_are_private_to_each_profile_and_separate_by_deck(self):
        deck = "casual/gruul-test"
        rows = [{"name": "Mind Stone", "choice": "buy"}, {"name": "Mind Stone", "choice": "set_aside"}]
        with access.viewing("matt"):
            form = {"expect": 0, "title": "", "rows": rows}
            saved = deck_checklist.save("matt", self.body("matt", **form), deck)
            self.assertEqual(deck_checklist.view("matt", deck), saved)
            self.assertEqual(deck_checklist.view("matt", "commander/elf-commander")["rows"], [])
            self.assertEqual(deck_checklist.view("matt")["rows"], [])
            with self.assertRaises(ApiError) as stale:
                deck_checklist.save("matt", self.body("matt", **form), deck)
            self.assertEqual(stale.exception.status, 409)
        with access.viewing("user1"):
            self.assertEqual(deck_checklist.view("user1", deck)["rows"], [])
            with self.assertRaises(ApiError) as private:
                deck_checklist.view("matt", deck)
            self.assertEqual(private.exception.status, 403)
            self.assertEqual(deck_checklist.save("user1", self.body("user1", **form), deck)["rows"], rows)
        with access.using({"profile": "user2", "email": "", "remote": True}):
            self.assertEqual(deck_checklist.view("user2", "user2/casual/r-elves")["rows"], [])
            for deck in ("casual/gruul-test", "user2/casual/does-not-exist"):
                with self.subTest(deck=deck), self.assertRaises(ApiError) as hidden:
                    deck_checklist.view("user2", deck)
                self.assertEqual((hidden.exception.status, hidden.exception.message), (404, f"No deck {deck!r}"))
        self.assertEqual(self.box.state.changes(), [])

    def test_member_can_split_copies_and_reopen_without_inventory_or_card_data(self):
        rows = [{"name": "Mind Stone", "choice": choice} for choice in ("set_aside", "buy", "check")]
        with access.using({"profile": "user2", "email": "", "remote": True}), \
                mock.patch.object(inventory, "current", side_effect=AssertionError("unexpected inventory read")), \
                mock.patch.object(cards, "resolve", side_effect=AssertionError("unexpected card lookup")):
            start = deck_checklist.view("user2")
            self.assertEqual(start, {"revision": 0, "title": "", "rows": []})
            body = {"title": "Friday upgrades", "rows": rows, "expect": start["revision"]}
            saved = deck_checklist.save("user2", json.dumps(body))
            self.assertEqual(saved, {"revision": 1, "title": body["title"], "rows": rows})
            self.assertEqual(deck_checklist.view("user2"), saved)
            with self.assertRaises(ApiError) as stale:
                deck_checklist.save("user2", json.dumps(dict(body, rows=[])))
            self.assertEqual(stale.exception.status, 409)
            self.assertEqual(deck_checklist.view("user2"), saved)
        self.assertEqual(self.box.state.changes(), [])

    def test_other_owner_missing_owner_and_nobody_refuse_before_parsing_or_store_access(self):
        with mock.patch.object(state, "store", side_effect=AssertionError("unexpected store access")):
            for who, script in (("matt", False), ("user1", False), (None, True), (None, False)):
                with self.subTest(viewer=who, script=script), access.using(None), \
                        access.viewing(who), access.answering(script):
                    for owner in ("user2", "unknown"):
                        for endpoint, args in ((deck_checklist.view, (owner,)), (deck_checklist.save, (owner, b"{"))):
                            with self.assertRaises(ApiError) as hidden:
                                endpoint(*args)
                            self.assertEqual((hidden.exception.status, hidden.exception.message),
                                             (403, deck_checklist.PRIVATE))
            with access.viewing("matt"):
                with self.assertRaises(ApiError) as other:
                    deck_checklist.view("user1")
                self.assertEqual(other.exception.status, 403)

    def test_unavailable_store_returns_database_error_without_losing_private_details_to_errors(self):
        with access.viewing("matt"), mock.patch.object(self.box.state, "checklist",
                side_effect=state.Unavailable("private marker")):
            with self.assertRaises(ApiError) as error:
                deck_checklist.view("matt")
            self.assertEqual(error.exception.status, 503)
            self.assertEqual(error.exception.extra, {"reason": "database"})
            self.assertNotIn("private marker", error.exception.message)

    def test_pre_migration_install_identifies_the_required_update_on_read_and_save(self):
        with access.viewing("matt"):
            for method, endpoint, args in (("checklist", deck_checklist.view, ("matt",)),
                    ("checklist_put", deck_checklist.save, ("matt", self.body("matt", expect=0, title="", rows=[])))):
                with self.subTest(method=method), mock.patch.object(self.box.state, method, side_effect=MissingSchema), \
                        self.assertRaises(ApiError) as error:
                    endpoint(*args)
                self.assertEqual((error.exception.status, error.exception.extra), (503, {"reason": "migration"}))
                self.assertIn("database update", error.exception.message)

    def test_invalid_requests_and_foreign_body_profile_leave_owner_copy_intact(self):
        original = {"expect": 0, "rows": [{"name": "Kindred Discovery", "choice": "check"}], "title": ""}
        with access.viewing("matt"):
            saved = deck_checklist.save("matt", self.body("matt", **original))
            valid = dict(original, expect=saved["revision"])
            for body, status in ((dict(valid, profile="user1"), 403), (dict(valid, expect=True), 400),
                                 (dict(valid, rows=[{"name": "Any", "choice": "owned"}]), 400),
                                 (dict(valid, rows=valid["rows"] * 201), 400), (dict(valid, title="x" * 151), 400),
                                 (dict(valid, notes="unexpected"), 400), ({}, 400)):
                with self.subTest(status=status, keys=list(body)), self.assertRaises(ApiError) as error:
                    deck_checklist.save("matt", json.dumps(body))
                self.assertEqual(error.exception.status, status)
            with self.assertRaises(ApiError) as oversized:
                deck_checklist.save("matt", b" " * (MAX_EDIT_BODY + 1))
            self.assertEqual(oversized.exception.status, 413)
            self.assertEqual(deck_checklist.view("matt"), saved)
