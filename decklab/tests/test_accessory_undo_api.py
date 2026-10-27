"""Accessory metadata Undo boundaries over isolated audit-shaped fixtures.

No PostgreSQL, household records, image downloads, host tools or real writes are
used here. The kernel and guarded PostgreSQL tests prove the inverse itself.
"""
import copy
import json
import unittest
from unittest import mock

from decklab.lib import access, accessories, accessory_fetch, cards, feature_routes, inventory
from decklab.lib.api import accessory_undo, activity_undo, guard
from decklab.lib.api.common import ApiError, DATABASE_DOWN
from decklab.lib.inventory import accessory_undo as kernel
from decklab.lib.inventory import changes
from decklab.tests import accessory_undo_support as support
from decklab.tests import household_config
from decklab.tests.test_api import ApiTestCase

CHANGE_ID = support.CHANGE_ID
ROW_ID = support.ROW_ID
CURRENT = support.row(id="fixture-sleeves", brand="Current brand", colour="blue", image="", crop="", link="", image_source="",
                      notes="Current <b>literal</b> note")
DEFAULT = object()


class AuditAccessories:
    """Synthetic adapter, running the real inverse with no SQL or external I/O."""
    name = "accessory-undo-api-fixture"

    def __init__(self, snapshot):
        self.snapshot = snapshot
        self.audit = {}
        self.latest = ROW_ID
        self.calls = []
        self.writes = []
        self.fail_after_commit = False

    def load(self):
        return self.snapshot

    def undo_audit(self, change_id):
        return copy.deepcopy(self.audit.get(change_id, []))

    def undo_latest(self, table, key):
        return self.latest

    def accessory_undo_review(self, change_id, owners):
        self.calls.append(("review", change_id, owners))
        return kernel.review(change_id, owners, self.snapshot, self)[0]

    def accessory_undo_apply(self, change_id, owners, expect, actor, message, reason=...):
        self.calls.append(("apply", change_id, owners))
        if reason is not ...:
            source = kernel.source_record(self.undo_audit(change_id), owners)
            if source["op"] != "INSERT":
                raise inventory.Invalid("Restoring accessory text does not take a removal reason.")
            reason = kernel.removal_reason(reason)
        before = self.snapshot
        operation = kernel.MetadataRestore(change_id, owners, expect)
        after, summary = operation.run(changes.detach(before))
        after = changes.prepare(before, after).replace(decks_revision="fixture-saved-decks")
        actual = support.actual_source(operation.plan, id=self.latest + 1)
        receipt = operation.verify(before, after, actual)
        self.snapshot, self.latest = after, actual[0]["id"]
        self.writes.append((actor, message, summary, copy.deepcopy(actual)))
        if self.fail_after_commit:
            raise inventory.Unavailable("Synthetic lost reply, with private database details")
        return receipt


class AccessoryUndoApiTests(ApiTestCase):
    def setUp(self):
        super().setUp()
        household_config.use(self)
        self.store = AuditAccessories(self.box.inventory.load().replace(revision="fixture-inventory", decks_revision="fixture-decks"))
        self.addCleanup(inventory.use(self.store))
        self.enterContext(self.identity("matt"))
        self.seed()

    def identity(self, pid):
        return access.using({"profile": pid, "email": pid + "@example.com", "remote": True})

    def seed(self, owner="matt"):
        current = {**CURRENT, "owner": owner}
        old = {**current, "brand": "Original brand", "name": "Original sleeves", "colour": "black",
               "notes": "Historical <script>plain text</script>"}
        self.store.snapshot = self.store.snapshot.with_accessories([current])
        self.store.audit[CHANGE_ID] = [{"id": ROW_ID, "table": "accessory", "op": "UPDATE", "key": {"id": current["id"]},
                                       "before": old, "after": current}]
        self.store.latest = ROW_ID
        return current, old

    def view(self, change_id=CHANGE_ID):
        return accessory_undo.accessory_undo_view(id=change_id)

    def apply(self, *, expect=DEFAULT, profile="matt", change_id=CHANGE_ID, **extra):
        if expect is DEFAULT:
            expect = self.view(change_id)["expect"]
        return accessory_undo.apply_accessory_undo(json.dumps({"profile": profile, "id": change_id, "expect": expect, **extra}).encode())

    def refused(self, status, function, *args, **kwargs):
        with self.assertRaises(ApiError) as caught:
            function(*args, **kwargs)
        self.assertEqual(caught.exception.status, status, caught.exception.message)
        return caught.exception

    def test_preview_has_exact_nine_plain_fields_without_images_cards_or_global_counters(self):
        current, restored = self.seed()
        before = copy.deepcopy(self.store.audit)
        with mock.patch.object(inventory, "image", side_effect=AssertionError("No image read")), \
                mock.patch.object(cards, "resolve", side_effect=AssertionError("No card lookup")):
            result = self.view()
        self.assertEqual(set(result), {"available", "id", "expect", "kind", "action", "label", "current", "restored", "fields"})
        self.assertEqual((result["kind"], result["action"], result["label"]), ("accessory", "accessory_update", current["name"]))
        self.assertEqual(result["current"], kernel.meta(current))
        self.assertEqual(result["restored"], kernel.meta(restored))
        self.assertEqual(set(result["current"]), {"id", "kind", "owner", "brand", "name", "colour", "notes", "link", "image_source"})
        self.assertEqual(result["fields"], [{"field": field, "before": current[field], "after": restored[field]}
                                            for field in kernel.FIELDS if current[field] != restored[field]])
        self.assertEqual((self.store.audit, self.store.writes), (before, []))

    def test_own_and_shared_saves_return_actual_metadata_and_one_web_actor_audit(self):
        for owner, viewer in (("matt", "matt"), ("shared", "user1")):
            self.seed(owner)
            before = copy.deepcopy(self.store.audit)
            with self.subTest(owner=owner), self.identity(viewer):
                preview = self.view()
                result = self.apply(profile=viewer, expect=preview["expect"])
            self.assertEqual(set(result), {"saved", "source_id", "expect", "kind", "action", "restored", "sha256", "revision", "summary"})
            self.assertIs(result["saved"], True)
            self.assertEqual((result["source_id"], result["expect"], result["restored"]), (CHANGE_ID, preview["expect"], preview["restored"]))
            self.assertEqual(result["sha256"], kernel.list_sha(kernel.raw_rows(self.store.snapshot), frozenset({viewer, "shared"})))
            self.assertEqual(result["revision"], str(self.store.latest))
            actor, message, summary, rows = self.store.writes[-1]
            self.assertEqual((actor.id, actor.source, actor.via), (viewer, "web", "tunnel"))
            self.assertEqual(message, f"Undo accessory change {CHANGE_ID}")
            self.assertEqual((rows[0]["before"], rows[0]["after"]), (before[CHANGE_ID][0]["after"], before[CHANGE_ID][0]["before"]))
            self.assertEqual(self.store.audit, before)
            self.assertEqual(summary.counts["undo"], 1)

    def test_other_home_owner_and_public_kit_never_gain_admin_undo_rights(self):
        self.seed("user1")
        self.box.state.visibility_set("user1", "accessories", True, inventory.Actor("test", "Fixture"), "Public fixture kit")
        self.assertIn("user1", guard.accessory_readers())
        self.assertNotIn("user1", guard.accessory_owners())
        for function, args in ((self.view, ()), (self.apply, ())):
            error = self.refused(404, function, *args, **({"expect": "bad"} if function == self.apply else {}))
            self.assertEqual(error.message, accessory_undo.NO_CHANGE)
        with self.identity("user2"), mock.patch.object(self.store, "accessory_undo_review", side_effect=AssertionError("No source read")):
            self.refused(403, self.view)
            self.refused(403, self.apply, profile="user2", expect="bad")
        self.assertEqual(self.store.writes, [])

    def test_script_and_chooser_follow_ordinary_accessory_writer_semantics(self):
        self.seed("user1")
        with access.using(None), access.viewing(None), access.answering(True):
            self.assertEqual(self.view()["current"]["owner"], "user1")
            self.assertIsNone(self.store.calls[-1][2])
            self.refused(404, self.apply, profile="matt", expect="bad")
            result = self.apply(profile="user1", expect=kernel.review(CHANGE_ID, frozenset({"user1", "shared"}), self.store.snapshot, self.store)[0]["expect"])
            self.assertEqual(result["restored"]["owner"], "user1")
            self.assertEqual(self.store.writes[-1][0].id, "user1")
        with access.using(None), access.viewing(None), access.answering(False), \
                mock.patch.object(self.store, "accessory_undo_review", side_effect=AssertionError("No anonymous source read")):
            self.refused(403, self.view)
        with access.using(None), access.viewing("matt"):
            self.refused(403, self.apply, profile="user1", expect="bad")
        self.refused(403, self.apply, profile="user1", expect="bad")

    def test_whole_source_scope_is_proved_before_bad_receipt_or_private_labels(self):
        own = copy.deepcopy(self.store.audit[CHANGE_ID][0])
        for mode in ("missing", "mixed", "hidden", "owner_move"):
            self.seed()
            if mode == "missing":
                self.store.audit.clear()
            elif mode == "mixed":
                self.store.audit[CHANGE_ID].append({"id": ROW_ID + 1, "table": "accessory_image", "op": "UPDATE"})
                self.store.audit[CHANGE_ID][0]["before"]["notes"] = object()
            else:
                self.store.audit[CHANGE_ID][0]["before"]["owner"] = "user1"
                if mode == "hidden":
                    self.store.audit[CHANGE_ID][0]["after"]["owner"] = "user1"
                self.store.audit[CHANGE_ID][0]["before"]["name"] = "Private fixture label"
            with self.subTest(mode=mode), mock.patch.object(kernel, "raw_row", side_effect=AssertionError("No row proof before scope")):
                for function in (self.view, lambda: self.apply(expect="bad")):
                    error = self.refused(404, function)
                    self.assertEqual((error.message, error.extra), (accessory_undo.NO_CHANGE, {}))
        self.assertEqual(own["before"]["owner"], "matt")
        self.assertEqual(self.store.writes, [])

    def test_strict_three_field_body_and_id_refuse_browser_overrides(self):
        for extra in ({"space": "home"}, {"owner": "shared"}, {"notes": "Override"}, {"restored": {}}, {"rows": []},
                      {"link": "https://example.com/override"}, {"image_source": "https://example.com/override-image"},
                      {"reason": "Override"}, {"confirm_owned": True}, {"revision": "1"}, {"sha256": "a" * 64}, {"action": "accessory_update"}):
            with self.subTest(extra=extra):
                self.refused(400, self.apply, expect="a" * 64, **extra)
        for value in (None, True, 0, -1, 1.5, "../17", 10 ** 18):
            with self.subTest(id=value):
                self.refused(400, self.view, value)
        for body, status in ((b"{", 400), (b"[]", 400), (b"{}", 403), (b'{"profile":"matt","id":17}', 400)):
            with self.subTest(body=body):
                self.refused(status, accessory_undo.apply_accessory_undo, body)
        self.assertEqual(self.store.writes, [])

    def test_stale_or_unsupported_physical_history_never_writes_or_returns_details(self):
        preview = self.view()
        self.store.latest += 1
        self.assertEqual(self.refused(409, self.apply, expect=preview["expect"]).message, accessory_undo.CHANGED)
        for field, value in (("quantity", "99"), ("image", "fixture-sleeves.png"), ("kind", "playmat")):
            self.seed()
            self.store.audit[CHANGE_ID][0]["before"][field] = value
            with self.subTest(field=field):
                self.assertEqual(self.view(), {"available": False, "id": CHANGE_ID, "reason": accessory_undo.UNSUPPORTED})
                self.assertEqual(self.refused(400, self.apply, expect="bad").message, accessory_undo.UNSUPPORTED)
        self.seed()
        preview = self.view()
        self.apply(expect=preview["expect"])
        self.refused(409, self.apply, expect=preview["expect"])
        self.assertEqual(len(self.store.writes), 1)

    def test_malformed_review_and_actual_receipts_fail_closed_without_acknowledgement(self):
        plan = self.store.accessory_undo_review(CHANGE_ID, frozenset({"matt", "shared"}))
        result = {"review": plan, "restored": plan["restored"], "sha256": plan["sha256"], "revision": str(ROW_ID + 1)}
        changed_source = copy.deepcopy(plan)
        changed_source["source"]["before"]["quantity"] = "99"
        for replacement in (None, {**result, "sha256": "0" * 64}, {**result, "revision": str(ROW_ID)},
                            {**result, "revision": "9223372036854775808"}, {**result, "revision": ROW_ID + 1},
                            {**result, "restored": {**plan["restored"], "quantity": "100"}},
                            {**result, "restored": {**plan["restored"], "notes": "Wrong actual note"}},
                            {**result, "review": changed_source}, {**result, "review": {**plan, "owners": None}},
                            {**result, "review": {**plan, "fields": []}}):
            with self.subTest(result=replacement), mock.patch.object(self.store, "accessory_undo_apply", return_value=replacement):
                self.assertEqual(self.refused(503, self.apply, expect=plan["expect"]).message, accessory_undo.UNCONFIRMED)
        self.assertEqual(self.store.writes, [])

    def test_recorded_urls_restore_each_blank_and_mixed_plain_value_without_fetching(self):
        cases = (
            ({"link": "https://example.com/current"}, {"link": "https://example.com/former?text=<b>literal</b>&q=1"}),
            ({"image_source": "https://example.com/current-image"}, {"image_source": "https://example.com/former-image?text=<script>literal</script>"}),
            ({"link": "https://example.com/current", "image_source": "https://example.com/current-image"}, {"link": "", "image_source": ""}),
            ({"link": "", "image_source": ""}, {"link": "https://example.com/former", "image_source": "https://example.com/former-image",
                                                   "notes": "Historical <b>plain text</b>", "colour": "green"}),
        )
        for current_values, historical_values in cases:
            current, restored = self.seed()
            restored.update(current)
            current.update(current_values)
            restored.update(historical_values)
            self.store.snapshot = self.store.snapshot.with_accessories([current])
            before, writes = self.store.snapshot, len(self.store.writes)
            with self.subTest(current=current_values, restored=historical_values), \
                    mock.patch.object(accessory_fetch, "fetch", side_effect=AssertionError("No URL fetch")), \
                    mock.patch.object(accessory_fetch, "_download", side_effect=AssertionError("No image download")), \
                    mock.patch.object(accessory_fetch, "check_host", side_effect=AssertionError("No DNS or host check")), \
                    mock.patch.object(inventory, "image", side_effect=AssertionError("No image read")):
                preview = self.view()
                self.assertEqual(preview["fields"], [{"field": field, "before": current[field], "after": restored[field]}
                                                      for field in kernel.FIELDS if current[field] != restored[field]])
                self.assertEqual((preview["current"], preview["restored"]), (kernel.meta(current), kernel.meta(restored)))
                result = self.apply(expect=preview["expect"])
            self.assertEqual((result["restored"], result["action"]), (kernel.meta(restored), "accessory_update"))
            self.assertEqual(kernel.raw_rows(self.store.snapshot), [restored])
            self.assertEqual(self.store.snapshot.accessory_images, before.accessory_images)
            self.assertEqual(len(self.store.writes), writes + 1)
            audit = self.store.writes[-1][3][0]
            self.assertEqual((audit["before"], audit["after"]), (current, restored))

    def test_invalid_historical_or_current_urls_refuse_without_normalizing_or_fetching(self):
        bad_values = (
            ("link", "javascript:alert(1)"), ("link", "ftp://example.com/item"), ("image_source", "data:image/png;base64,AAAA"),
            ("link", "example.com/item"), ("link", " https://example.com/item"), ("image_source", "https://example.com/image "),
            ("link", "https://example.com/a\nb"), ("link", " "),
            ("link", "https://example.com/" + "x" * accessories.MAX_LINK),
            ("image_source", "https://example.com/" + "x" * accessories.MAX_SOURCE),
        )
        for side in ("before", "after"):
            for field, value in bad_values:
                self.seed()
                self.store.audit[CHANGE_ID][0][side][field] = value
                before = self.store.snapshot
                with self.subTest(side=side, field=field, value=value), \
                        mock.patch.object(accessory_fetch, "fetch", side_effect=AssertionError("No fetch for URL proof")):
                    self.assertEqual(self.view(), {"available": False, "id": CHANGE_ID, "reason": accessory_undo.UNSUPPORTED})
                    self.assertEqual(self.refused(400, self.apply, expect="bad").message, accessory_undo.UNSUPPORTED)
                self.assertEqual(self.store.snapshot, before)
        self.assertEqual(self.store.writes, [])

    def test_actual_url_receipts_and_full_raw_immutable_proofs_must_match(self):
        current, restored = self.seed()
        current.update(link="https://example.com/current", image_source="https://example.com/current-image")
        restored.update(link="https://example.com/former", image_source="https://example.com/former-image")
        self.store.snapshot = self.store.snapshot.with_accessories([current])
        plan = self.store.accessory_undo_review(CHANGE_ID, frozenset({"matt", "shared"}))
        result = {"review": plan, "restored": plan["restored"], "sha256": plan["sha256"], "revision": str(ROW_ID + 1)}
        changed_image = copy.deepcopy(plan)
        changed_image["source"]["before"]["image"] = "fixture-sleeves.png"
        changed_key = copy.deepcopy(plan)
        changed_key["source"]["key"] = {"id": "different-accessory"}
        changed_owner = copy.deepcopy(plan)
        changed_owner["source"]["before"]["owner"] = "shared"
        replacements = (
            {**result, "restored": {**plan["restored"], "link": "https://example.com/wrong-actual"}},
            {**result, "restored": {**plan["restored"], "image_source": "https://example.com/wrong-actual-image"}},
            {**result, "restored": {**plan["restored"], "link": "javascript:alert(1)"}},
            *({**result, "review": changed} for changed in (changed_image, changed_key, changed_owner)),
        )
        for replacement in replacements:
            with self.subTest(result=replacement), mock.patch.object(self.store, "accessory_undo_apply", return_value=replacement), \
                    mock.patch.object(accessory_fetch, "fetch", side_effect=AssertionError("No receipt URL fetch")):
                self.assertEqual(self.refused(503, self.apply, expect=plan["expect"]).message, accessory_undo.UNCONFIRMED)
        self.assertEqual(self.store.writes, [])

    def test_unavailable_or_lost_reply_never_retries_or_falsely_acknowledges_saved(self):
        with mock.patch.object(self.store, "accessory_undo_review", side_effect=inventory.Unavailable("Private storage details")):
            error = self.refused(503, self.view)
            self.assertEqual((error.message, error.extra), (DATABASE_DOWN, {"reason": "database"}))
        with mock.patch.object(self.store, "accessory_undo_review", None):
            self.refused(503, self.view)
        preview = self.view()
        self.store.fail_after_commit = True
        error = self.refused(503, self.apply, expect=preview["expect"])
        self.assertEqual(error.message, DATABASE_DOWN)
        self.assertEqual(len(self.store.writes), 1)
        self.assertEqual(len([call for call in self.store.calls if call[0] == "apply"]), 1)
        self.assertEqual(kernel.meta(kernel.raw_rows(self.store.snapshot)[0]), preview["restored"])
        self.refused(409, self.apply, expect=preview["expect"])
        self.assertEqual(len(self.store.writes), 1)

    def test_activity_hint_uses_writable_owners_and_complete_single_global_source(self):
        change = {"id": CHANGE_ID, "total": 1, "rows": copy.deepcopy(self.store.audit[CHANGE_ID])}
        viewer, shown = guard.viewer(), {"id": CHANGE_ID}
        self.assertEqual(activity_undo.review_hint(change, shown, viewer), {"review": True, "kind": "accessory"})
        for replacement in ({**change, "total": 2}, {**change, "rows": change["rows"] * 2}, {**change, "more": True},
                            {**change, "groups": [{"count": 1}]}):
            with self.subTest(change=replacement):
                self.assertIsNone(activity_undo.review_hint(replacement, shown, viewer))
        self.assertIsNone(activity_undo.review_hint(change, {"id": CHANGE_ID + 1}, viewer))
        with self.identity("user1"):
            self.assertIsNone(activity_undo.review_hint(change, shown, guard.viewer()))


class AccessoryUndoRouteTests(unittest.TestCase):
    def handler(self, command="GET"):
        handler = mock.Mock(command=command)
        handler._query.return_value = {"id": "17"}
        handler._deck_id.side_effect = AssertionError("An audit ID is not a deck ID")
        return handler

    def test_get_and_head_keep_audit_id_and_post_forwards_exact_body(self):
        for command in ("GET", "HEAD"):
            handler = self.handler(command)
            with self.subTest(command=command), mock.patch.object(accessory_undo, "accessory_undo_view", return_value={"available": True}) as endpoint:
                self.assertTrue(feature_routes.dispatch(handler, ["activity", "accessory-undo"], "id=17"))
                endpoint.assert_called_once_with(id="17")
                handler._allow.assert_called_once_with("GET", "HEAD")
                handler._query.assert_called_once_with("id=17", ("id",))
                handler._deck_id.assert_not_called()
                handler._send_json.assert_called_once_with(200, {"available": True})
        handler = self.handler("POST")
        body = b'{"profile":"matt","id":17,"expect":"fixture"}'
        handler._write_body.return_value = body
        with mock.patch.object(accessory_undo, "apply_accessory_undo", return_value={"saved": True}) as endpoint:
            self.assertTrue(feature_routes.dispatch(handler, ["activity", "accessory-undo"], ""))
        endpoint.assert_called_once_with(body)
        handler._allow.assert_called_once_with("POST")
        handler._no_query.assert_called_once_with("")
        handler._write_body.assert_called_once_with(None)
        handler._deck_id.assert_not_called()

    def test_route_guards_and_endpoint_errors_never_emit_false_success(self):
        for command, method, query in (("GET", "_query", "id=17&id=18"), ("POST", "_no_query", "owner=matt"),
                                       ("PUT", "_allow", "")):
            handler = self.handler(command)
            error = ApiError(400 if method != "_allow" else 405, "Synthetic route refusal")
            getattr(handler, method).side_effect = error
            with self.subTest(command=command), mock.patch.object(accessory_undo, "accessory_undo_view") as read, \
                    mock.patch.object(accessory_undo, "apply_accessory_undo") as write:
                with self.assertRaises(ApiError) as caught:
                    feature_routes.dispatch(handler, ["activity", "accessory-undo"], query)
                self.assertIs(caught.exception, error)
                read.assert_not_called()
                write.assert_not_called()
                handler._send_json.assert_not_called()
        for command, name in (("GET", "accessory_undo_view"), ("POST", "apply_accessory_undo")):
            handler = self.handler(command)
            error = ApiError(503, DATABASE_DOWN, reason="database")
            with self.subTest(endpoint=name), mock.patch.object(accessory_undo, name, side_effect=error):
                with self.assertRaises(ApiError) as caught:
                    feature_routes.dispatch(handler, ["activity", "accessory-undo"], "" if command == "POST" else "id=17")
                self.assertIs(caught.exception, error)
                handler._send_json.assert_not_called()
