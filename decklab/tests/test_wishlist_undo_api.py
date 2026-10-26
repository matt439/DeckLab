"""Owner-only wishlist Undo over an audited memory fixture, without PostgreSQL."""
import copy
import json
import unittest
from unittest import mock

from decklab.lib import access, cards, feature_routes, inventory, state
from decklab.lib.api import activity_undo, guard, wishlist_undo
from decklab.lib.api.common import ApiError, DATABASE_DOWN
from decklab.lib.state import wishlist_undo as kernel
from decklab.tests import household_config, test_api, wishlist_undo_support as support

DEFAULT = object()


class WishlistUndoApiTests(test_api.ApiTestCase):
    def setUp(self):
        super().setUp()
        household_config.use(self)
        self.install()
        self.enterContext(self.identity("matt"))

    def identity(self, pid):
        return access.using({"profile": pid, "email": pid + "@example.com", "remote": True})

    def install(self):
        self.store = support.AuditWishlistMemory()
        self.addCleanup(state.use(self.store))
        self.change_id = support.seed(self.store)

    def view(self, change_id=None):
        return wishlist_undo.wishlist_undo_view(id=self.change_id if change_id is None else change_id)

    def apply(self, *, expect=DEFAULT, profile="matt", change_id=None, **extra):
        if expect is DEFAULT:
            expect = self.view()["expect"]
        body = {"profile": profile, "id": self.change_id if change_id is None else change_id, "expect": expect, **extra}
        return wishlist_undo.apply_wishlist_undo(json.dumps(body).encode())

    def refused(self, status, function, *args, **kwargs):
        with self.assertRaises(ApiError) as caught:
            function(*args, **kwargs)
        self.assertEqual(caught.exception.status, status, caught.exception.message)
        return caught.exception

    def unchanged(self):
        return copy.deepcopy((self.store._wishlists, self.store.changes()))

    def test_preview_preserves_five_plain_fields_without_inventory_or_card_index(self):
        before = self.unchanged()
        with mock.patch.object(inventory, "current", side_effect=AssertionError("No inventory")), \
                mock.patch.object(inventory, "backend", side_effect=AssertionError("No inventory")), \
                mock.patch.object(cards, "resolve", side_effect=AssertionError("No card index")):
            result = self.view()
        self.assertEqual(set(result), {"available", "id", "expect", "kind", "action", "profile", "label", "current", "restored", "fields"})
        self.assertEqual((result["kind"], result["action"], result["profile"], result["label"]),
                         ("wishlist", "wishlist_update", "matt", "Opt"))
        for entry in (result["current"], result["restored"]):
            self.assertEqual(set(entry), {"name", "set", "number", "notes", "source"})
            self.assertEqual((entry["set"], entry["number"]), ("", ""))
        self.assertEqual(result["restored"]["notes"], "  Former note\r\nsecond line\t  ")
        self.assertEqual(result["restored"]["source"], "  magic/reports/example.md  ")
        self.assertEqual([item["field"] for item in result["fields"]], ["notes", "source"])
        self.assertRegex(result["expect"], r"^[a-f0-9]{64}$")
        self.assertEqual(self.unchanged(), before)

    def test_saved_receipt_matches_one_actual_audit_update_and_web_actor(self):
        preview, before = self.view(), self.unchanged()
        source = self.store.raw_source(self.change_id)
        result = self.apply(expect=preview["expect"])
        self.assertEqual(set(result), {"saved", "source_id", "expect", "kind", "action", "profile", "restored", "sha256", "revision", "summary"})
        self.assertIs(result["saved"], True)
        self.assertEqual(result["source_id"], self.change_id)
        self.assertEqual(result["expect"], preview["expect"])
        self.assertEqual(result["restored"], preview["restored"])
        self.assertEqual(result["sha256"], kernel.list_sha(self.store.raw_entries("matt")))
        self.assertEqual(result["revision"], str(self.store.latest("matt")))
        history = self.store.changes()
        self.assertEqual(history[:-1], before[1])
        self.assertEqual((history[-1]["actor"], history[-1]["source"], history[-1]["via"]), ("matt", "web", "tunnel"))
        self.assertEqual(history[-1]["message"], f"Undo wishlist change {self.change_id}")
        self.assertEqual(history[-1]["reason"], None)
        self.assertEqual(history[-1]["rows"], [{"table": "wishlist_entry", "op": "UPDATE", "key": source[0]["key"],
                                               "before": source[0]["after"], "after": source[0]["before"]}])
        self.assertEqual(self.store.raw_source(self.change_id), source)
        self.assertEqual(len([call for call in self.store.calls if call[0] == "apply"]), 1)

    def test_anonymous_script_cannot_establish_viewer_from_body_before_any_parse_or_store(self):
        before = self.unchanged()
        with access.using(None), access.viewing(None), \
                mock.patch.object(wishlist_undo, "_parse_body", side_effect=AssertionError("No body read")), \
                mock.patch.object(wishlist_undo, "_writer", side_effect=AssertionError("No body actor")), \
                mock.patch.object(state, "store", side_effect=AssertionError("No store read")):
            for function, args in ((wishlist_undo.wishlist_undo_view, ("bad",)),
                                   (wishlist_undo.apply_wishlist_undo, (b'{"profile":"matt"}',))):
                self.assertEqual(self.refused(404, function, *args).message, wishlist_undo.NO_CHANGE)
        self.assertEqual(self.unchanged(), before)
        self.assertEqual(self.store.calls, [])

    def test_owner_only_even_same_home_admin_and_other_member_before_bad_expect(self):
        own = self.change_id
        home_other, member_other = support.seed(self.store, "user1"), support.seed(self.store, "user2")
        before = self.unchanged()
        for viewer, change in (("matt", home_other), ("matt", member_other), ("user1", own), ("user2", own)):
            with self.subTest(viewer=viewer, change=change), self.identity(viewer):
                self.assertEqual(self.refused(404, self.view, change).message, wishlist_undo.NO_CHANGE)
                self.assertEqual(self.refused(404, self.apply, change_id=change, profile=viewer, expect="bad").message,
                                 wishlist_undo.NO_CHANGE)
        self.assertEqual(self.unchanged(), before)
        with self.identity("user1"):
            preview = self.view(home_other)
            result = self.apply(change_id=home_other, profile="user1", expect=preview["expect"])
        self.assertEqual((result["profile"], result["restored"]), ("user1", preview["restored"]))

    def test_body_profile_cannot_override_authenticated_owner_or_home_chooser(self):
        preview, before = self.view(), self.unchanged()
        for profile in ("user1", "user2", None, "missing"):
            with self.subTest(profile=profile):
                self.refused(403, self.apply, expect=preview["expect"], profile=profile)
        with access.using(None), access.viewing("matt"):
            self.refused(403, self.apply, expect=preview["expect"], profile="user1")
        self.assertEqual(self.unchanged(), before)
        self.assertFalse([call for call in self.store.calls if call[0] == "apply"])

    def test_global_mixed_or_hidden_source_is_missing_before_bad_expect_and_labels(self):
        for mode in ("settings", "hidden"):
            self.install()
            support.seed(self.store, "user2")
            actor = state.Actor("matt", "Matt", via="tunnel")
            with self.store.batch(actor, "Mixed fixture change"):
                self.store.wishlist_set("matt", "Opt", actor, "Fixture", notes="Own later note")
                if mode == "settings":
                    self.store.settings_put("matt", {"theme": "dark"}, actor, "Fixture")
                else:
                    self.store.wishlist_set("user2", "Opt", actor, "Fixture", notes="Private member note")
            self.change_id = self.store.changes()[-1]["id"]
            self.store._changes[-1]["rows"][0]["after"]["bad_own_shape"] = "Never project this"
            before = self.unchanged()
            with self.subTest(mode=mode):
                self.assertEqual(self.refused(404, self.view).message, wishlist_undo.NO_CHANGE)
                self.assertEqual(self.refused(404, self.apply, expect="bad").message, wishlist_undo.NO_CHANGE)
                self.assertEqual(self.unchanged(), before)

    def test_own_list_change_and_target_aba_reject_stale_review_without_second_write(self):
        for mode in ("other_entry", "target_aba"):
            self.install()
            preview = self.view()
            actor = state.Actor("matt", "Matt", via="tunnel")
            if mode == "other_entry":
                self.store.wishlist_set("matt", "Forest", actor, "Fixture", notes="Later own-list edit")
            else:
                self.store.wishlist_set("matt", "Opt", actor, "Fixture", notes="Temporary note")
                self.store.wishlist_set("matt", "Opt", actor, "Fixture", notes=preview["current"]["notes"])
            before = self.unchanged()
            with self.subTest(mode=mode):
                self.assertEqual(self.refused(409, self.apply, expect=preview["expect"]).message, wishlist_undo.CHANGED)
                self.assertEqual(self.unchanged(), before)
                self.assertEqual(len([call for call in self.store.calls if call[0] == "apply"]), 1)

    def test_other_profile_changes_do_not_invalidate_owner_review_or_get_rewritten(self):
        preview = self.view()
        support.seed(self.store, "user2")
        actor = state.Actor("user2", "User2", via="tunnel")
        self.store.wishlist_set("user2", "Forest", actor, "Fixture", notes="Unrelated private edit")
        other = self.store.raw_entries("user2")
        self.assertEqual(self.view()["expect"], preview["expect"])
        self.assertEqual(self.apply(expect=preview["expect"])["restored"], preview["restored"])
        self.assertEqual(self.store.raw_entries("user2"), other)

    def test_client_cannot_supply_rows_metadata_reason_confirmation_space_or_restored_values(self):
        preview, before = self.view(), self.unchanged()
        for extra in ({"rows": []}, {"raw_restore": {}}, {"restored": preview["restored"]}, {"notes": "Override"},
                      {"reason": "Override"}, {"confirm_owned": True}, {"space": "home"}, {"revision": "1"},
                      {"sha256": "a" * 64}, {"action": "wishlist_update"}):
            with self.subTest(extra=extra):
                self.refused(400, self.apply, expect=preview["expect"], **extra)
        self.assertEqual(self.unchanged(), before)
        self.assertFalse([call for call in self.store.calls if call[0] == "apply"])

    def test_malformed_request_and_unsupported_printing_history_never_write(self):
        before = self.unchanged()
        for value in (None, True, 0, -1, 1.5, "1.0", "../1", 10 ** 18):
            with self.subTest(id=value):
                self.refused(400, wishlist_undo.wishlist_undo_view, id=value)
        for expect in (None, True, 1, [], {}, "", "a" * 63, "A" * 64):
            with self.subTest(expect=expect):
                self.refused(400, self.apply, expect=expect)
        for body in (b"{", b"[]", b"{}", b'{"profile":"matt","id":1}'):
            with self.subTest(body=body):
                self.refused(400, wishlist_undo.apply_wishlist_undo, body)
        self.assertEqual(self.unchanged(), before)
        actor = state.Actor("matt", "Matt", via="tunnel")
        self.store.wishlist_set("matt", "Opt", actor, "Fixture printing edit", set="dom", number="60")
        self.change_id = self.store.changes()[-1]["id"]
        before = self.unchanged()
        self.assertEqual(self.view(), {"available": False, "id": self.change_id, "reason": wishlist_undo.UNSUPPORTED})
        self.assertEqual(self.refused(400, self.apply, expect="a" * 64).message, wishlist_undo.UNSUPPORTED)
        self.assertEqual(self.unchanged(), before)

    def test_failed_actual_receipt_rolls_back_wishlist_and_audit(self):
        preview, before = self.view(), self.unchanged()
        source = self.store.raw_source(self.change_id)
        self.store.fail_receipt = True
        self.assertEqual(self.refused(409, self.apply, expect=preview["expect"]).message, wishlist_undo.CHANGED)
        self.assertEqual(self.unchanged(), before)
        self.assertEqual(self.store.raw_source(self.change_id), source)
        self.assertEqual(len([call for call in self.store.calls if call[0] == "apply"]), 1)

    def test_lost_reply_reports_unavailable_after_one_commit_and_old_review_cannot_repeat(self):
        preview, before = self.view(), self.unchanged()
        self.store.lose_reply = True
        error = self.refused(503, self.apply, expect=preview["expect"])
        self.assertEqual((error.message, error.extra), (DATABASE_DOWN, {"reason": "database"}))
        self.assertEqual(len(self.store.changes()), len(before[1]) + 1)
        self.assertEqual(self.store.wishlist("matt")[0], preview["restored"])
        self.assertEqual(len([call for call in self.store.calls if call[0] == "apply"]), 1)
        committed = self.unchanged()
        self.assertEqual(self.refused(409, self.apply, expect=preview["expect"]).message, wishlist_undo.CHANGED)
        self.assertEqual(self.unchanged(), committed)

    def test_unavailable_inactive_and_unconfirmed_results_fail_without_false_saved_receipt(self):
        preview, before = self.view(), self.unchanged()
        self.store.down = True
        self.assertEqual(self.refused(503, self.view).extra, {"reason": "database"})
        self.store.down = False
        self.store.inactive.add("matt")
        self.assertEqual(self.refused(404, self.view).message, wishlist_undo.NO_CHANGE)
        self.store.inactive.clear()
        with mock.patch.object(self.store, "wishlist_undo_review", None):
            self.refused(503, self.view)
        plan = self.store.wishlist_undo_review(self.change_id, "matt")
        bad = {"review": plan, "restored": plan["restored"], "sha256": plan["sha256"], "revision": "2"}
        for replacement in (None, {**bad, "restored": {**plan["restored"], "position": 0}},
                            {**bad, "revision": 2}, {**bad, "sha256": "bad"},
                            {**bad, "sha256": "0" * 64 if plan["sha256"] != "0" * 64 else "1" * 64},
                            {**bad, "revision": "1"}, {**bad, "revision": "9223372036854775808"},
                            {**bad, "review": {**plan, "fields": []}}):
            with self.subTest(result=replacement), mock.patch.object(self.store, "wishlist_undo_apply", return_value=replacement):
                self.assertEqual(self.refused(503, self.apply, expect=preview["expect"]).message, wishlist_undo.UNCONFIRMED)
        self.assertEqual(self.unchanged(), before)

    def test_activity_hint_is_owner_only_advisory_and_requires_complete_single_global_row(self):
        change = self.store.changes()[0]
        shown, viewer = {"id": change["id"]}, guard.viewer()
        self.assertEqual(activity_undo.review_hint(change, shown, viewer), {"review": True, "kind": "wishlist"})
        unsupported = copy.deepcopy(change)
        unsupported["rows"][0]["after"]["set_code"] = "dom"
        self.assertEqual(activity_undo.review_hint(unsupported, shown, viewer), {"review": True, "kind": "wishlist"})
        for replacement in ({**change, "total": 2}, {**change, "more": True}, {**change, "groups": [{"count": 1}]},
                            {**change, "rows": change["rows"] * 2}):
            with self.subTest(change=replacement):
                self.assertIsNone(activity_undo.review_hint(replacement, shown, viewer))
        self.assertIsNone(activity_undo.review_hint(change, {"id": change["id"] + 1}, viewer))
        self.assertIsNone(activity_undo.review_hint(change, shown, None))
        for pid in ("user1", "user2"):
            with self.identity(pid):
                self.assertIsNone(activity_undo.review_hint(change, shown, guard.viewer()))


class WishlistUndoRouteTests(unittest.TestCase):
    def handler(self, command="GET"):
        handler = mock.Mock(command=command)
        handler._query.return_value = {"id": "17"}
        handler._deck_id.side_effect = AssertionError("A source change ID is not a deck ID")
        return handler

    def test_get_and_head_keep_source_change_id_without_deck_lookup(self):
        for command in ("GET", "HEAD"):
            handler = self.handler(command)
            with self.subTest(command=command), mock.patch.object(wishlist_undo, "wishlist_undo_view", return_value={"available": True}) as endpoint:
                self.assertTrue(feature_routes.dispatch(handler, ["activity", "wishlist-undo"], "id=17"))
                handler._allow.assert_called_once_with("GET", "HEAD")
                handler._query.assert_called_once_with("id=17", ("id",))
                endpoint.assert_called_once_with(id="17")
                handler._deck_id.assert_not_called()
                handler._send_json.assert_called_once_with(200, {"available": True})

    def test_post_forwards_exact_body_through_ordinary_write_guards(self):
        handler = self.handler("POST")
        body = b'{"profile":"matt","id":17,"expect":"fixture"}'
        handler._write_body.return_value = body
        with mock.patch.object(wishlist_undo, "apply_wishlist_undo", return_value={"saved": True}) as endpoint:
            self.assertTrue(feature_routes.dispatch(handler, ["activity", "wishlist-undo"], ""))
        handler._allow.assert_called_once_with("POST")
        handler._no_query.assert_called_once_with("")
        handler._write_body.assert_called_once_with(None)
        handler._query.assert_not_called()
        handler._deck_id.assert_not_called()
        endpoint.assert_called_once_with(body)
        handler._send_json.assert_called_once_with(200, {"saved": True})

    def test_route_guard_errors_stop_before_endpoint_or_success_response(self):
        for command, method, query in (("GET", "_query", "id=17&id=18"), ("POST", "_no_query", "space=home"),
                                       ("PUT", "_allow", "")):
            handler = self.handler(command)
            refusal = ApiError(400 if method != "_allow" else 405, "Synthetic route guard refusal")
            getattr(handler, method).side_effect = refusal
            with self.subTest(command=command), mock.patch.object(wishlist_undo, "wishlist_undo_view") as read, \
                    mock.patch.object(wishlist_undo, "apply_wishlist_undo") as write:
                with self.assertRaises(ApiError) as caught:
                    feature_routes.dispatch(handler, ["activity", "wishlist-undo"], query)
                self.assertIs(caught.exception, refusal)
                read.assert_not_called()
                write.assert_not_called()
                handler._send_json.assert_not_called()

    def test_endpoint_errors_propagate_unchanged_to_normal_server_error_boundary(self):
        for command, name in (("GET", "wishlist_undo_view"), ("POST", "apply_wishlist_undo")):
            handler = self.handler(command)
            error = ApiError(503, DATABASE_DOWN, reason="database")
            with self.subTest(command=command), mock.patch.object(wishlist_undo, name, side_effect=error):
                with self.assertRaises(ApiError) as caught:
                    feature_routes.dispatch(handler, ["activity", "wishlist-undo"], "" if command == "POST" else "id=17")
                self.assertIs(caught.exception, error)
                self.assertEqual(caught.exception.extra, {"reason": "database"})
                handler._send_json.assert_not_called()
