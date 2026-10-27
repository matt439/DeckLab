"""Accessory DELETE restoration API over isolated, audit-shaped fixtures only."""
import copy
import json
from unittest import mock

from decklab.lib import access, accessories, accessory_fetch, cards, inventory
from decklab.lib.api import accessory_undo, activity_undo, guard
from decklab.lib.api.common import ApiError, DATABASE_DOWN
from decklab.lib.inventory import accessory_undo as kernel
from decklab.lib.inventory import changes, rules
from decklab.tests import accessory_undo_support as support
from decklab.tests import household_config
from decklab.tests.test_accessory_undo_api import AuditAccessories
from decklab.tests.test_api import ApiTestCase

CHANGE_ID = support.CHANGE_ID
ROW_ID = support.ROW_ID
DEFAULT = object()
OMIT = object()


class DeleteAuditAccessories(AuditAccessories):
    """Same source preflight and operation verification as the real adapter."""
    def __init__(self, snapshot):
        super().__init__(snapshot)
        self._initial = snapshot

    def accessory_undo_apply(self, change_id, owners, expect, actor, message, reason=..., confirm_restore=...):
        self.calls.append(("apply", change_id, owners))
        canonical = None
        if reason is not ... or confirm_restore is not ...:
            source = kernel.source_record(self.undo_audit(change_id), owners)
            if reason is not ...:
                if source["op"] != "INSERT":
                    raise inventory.Invalid("A reason is accepted only for removing an added accessory.")
                canonical = kernel.removal_reason(reason)
            if confirm_restore is not ... and (source["op"] != "DELETE" or confirm_restore is not True):
                raise inventory.Invalid("Confirm restoring the removed accessory.")
        before = self.snapshot
        operation = kernel.MetadataRestore(change_id, owners, expect, reason=canonical if reason is not ... else ...,
                                            confirm_restore=confirm_restore, store=self)
        after, summary = operation.run(changes.detach(before))
        after = changes.prepare(before, after).replace(decks_revision="fixture-saved-decks")
        source = operation.plan["source"]
        actual = [{"id": self.latest + 1, "table": "accessory", "op": {"DELETE": "INSERT", "INSERT": "DELETE", "UPDATE": "UPDATE"}[source["op"]],
                   "key": copy.deepcopy(source["key"]), "before": copy.deepcopy(source["after"]), "after": copy.deepcopy(source["before"])}]
        receipt = operation.verify(before, after, actual)
        self.snapshot, self.latest = after, actual[0]["id"]
        self.writes.append({"actor": actor, "message": message, "reason": canonical, "summary": summary, "rows": actual})
        if self.fail_after_commit:
            raise inventory.Unavailable("Synthetic lost reply after commit, with private database details")
        return receipt


class AccessoryDeleteUndoApiTests(ApiTestCase):
    def setUp(self):
        super().setUp()
        household_config.use(self)
        self.store = DeleteAuditAccessories(support.build_snapshot())
        self.addCleanup(inventory.use(self.store))
        self.enterContext(self.identity("matt"))
        self.seed()

    def identity(self, pid):
        return access.using({"profile": pid, "email": pid + "@example.com", "remote": True})

    def seed(self, owner="matt", *, only=False, quantity="100"):
        support.seed_delete(self.store, owner, only)
        self.store.audit[CHANGE_ID][0]["before"]["quantity"] = quantity
        self.store.calls.clear()
        return copy.deepcopy(self.store.audit[CHANGE_ID][0]["before"])

    def view(self, change_id=CHANGE_ID):
        return accessory_undo.accessory_undo_view(id=change_id)

    def apply(self, *, profile="matt", change_id=CHANGE_ID, expect=DEFAULT, confirm_restore=True, **extra):
        if expect is DEFAULT:
            expect = self.view(change_id)["expect"]
        body = {"profile": profile, "id": change_id, "expect": expect, **extra}
        if confirm_restore is not OMIT:
            body["confirm_restore"] = confirm_restore
        return accessory_undo.apply_accessory_undo(json.dumps(body).encode())

    def refused(self, status, function, *args, **kwargs):
        with self.assertRaises(ApiError) as caught:
            function(*args, **kwargs)
        self.assertEqual(caught.exception.status, status, caught.exception.message)
        return caught.exception

    def test_preview_is_confirmed_add_shape_with_exact_thirteen_historical_plain_fields(self):
        restored = self.seed()
        before, source = self.store.snapshot, copy.deepcopy(self.store.audit)
        with mock.patch.object(inventory, "image", side_effect=AssertionError("No picture read")), \
                mock.patch.object(accessory_fetch, "fetch", side_effect=AssertionError("No URL fetch")), \
                mock.patch.object(cards, "resolve", side_effect=AssertionError("No card index")):
            result = self.view()
        self.assertEqual(set(result), {"available", "id", "expect", "kind", "action", "label", "current", "restored", "confirmation_required"})
        self.assertEqual((result["kind"], result["action"], result["label"]), ("accessory", "accessory_add", restored["name"]))
        self.assertIsNone(result["current"])
        self.assertIs(result["confirmation_required"], True)
        self.assertEqual(result["restored"], restored)
        self.assertEqual(set(result["restored"]), set(kernel.RAW))
        self.assertEqual(len(result["restored"]), 13)
        self.assertTrue(all(isinstance(value, str) for value in result["restored"].values()))
        self.assertEqual((self.store.snapshot, self.store.audit, self.store.writes), (before, source, []))

    def test_own_shared_empty_zero_and_positive_restores_preserve_id_and_one_actual_insert(self):
        for owner, viewer, only, quantity in (("matt", "matt", False, "100"), ("shared", "user1", False, "2"),
                                               ("matt", "matt", True, "0"), ("matt", "matt", True, "100")):
            restored = self.seed(owner, only=only, quantity=quantity)
            before, source = self.store.snapshot, copy.deepcopy(self.store.audit)
            with self.subTest(owner=owner, only=only, quantity=quantity), self.identity(viewer):
                preview = self.view()
                result = self.apply(profile=viewer, expect=preview["expect"])
            self.assertEqual(set(result), {"saved", "source_id", "expect", "kind", "action", "restored", "added_id", "sha256", "revision", "summary"})
            self.assertEqual((result["saved"], result["source_id"], result["expect"], result["action"]),
                             (True, CHANGE_ID, preview["expect"], "accessory_add"))
            self.assertEqual((result["added_id"], result["restored"]), (restored["id"], restored))
            expected = sorted([*[row.as_dict() for row in before.accessories.rows], restored], key=rules.accessory_sort_key)
            actual = [row.as_dict() for row in self.store.snapshot.accessories.rows]
            self.assertEqual(actual, expected)
            self.assertEqual(result["sha256"], kernel.list_sha(actual, frozenset({viewer, "shared"})))
            self.assertEqual(result["revision"], str(self.store.latest))
            self.assertEqual(len(self.store.writes), 1)
            write = self.store.writes[0]
            self.assertEqual((write["actor"].id, write["actor"].source, write["actor"].via), (viewer, "web", "tunnel"))
            self.assertIsNone(write["reason"])
            self.assertEqual(write["rows"], [{"id": ROW_ID + 1, "table": "accessory", "op": "INSERT", "key": {"id": restored["id"]},
                                             "before": None, "after": restored}])
            self.assertEqual(self.store.audit, source)
            self.assertEqual(self.store.snapshot.replace(accessories=before.accessories, revision=before.revision,
                                                         decks_revision=before.decks_revision), before)

    def test_other_owner_public_kit_and_ordinary_script_cannot_override_the_named_writer(self):
        restored = self.seed("user1")
        self.box.state.visibility_set("user1", "accessories", True, inventory.Actor("test", "Fixture"), "Public fixture kit")
        self.assertIn("user1", guard.accessory_readers())
        self.assertNotIn("user1", guard.accessory_owners())
        for function in (self.view, lambda: self.apply(expect="bad", confirm_restore=None)):
            self.assertEqual(self.refused(404, function).message, accessory_undo.NO_CHANGE)
        with self.identity("user2"):
            self.refused(403, self.view)
            self.refused(403, self.apply, profile="user2", expect="bad", confirm_restore=None)
        with access.using(None), access.viewing(None), access.answering(True):
            self.assertEqual(self.view()["restored"]["owner"], "user1")
            self.assertIsNone(self.store.calls[-1][2])
            self.refused(404, self.apply, profile="matt", expect="bad", confirm_restore=None)
            expect = self.store.accessory_undo_review(CHANGE_ID, frozenset({"user1", "shared"}))["expect"]
            self.assertEqual(self.apply(profile="user1", expect=expect)["added_id"], restored["id"])
        with access.using(None), access.viewing(None), access.answering(False):
            self.refused(403, self.view)
        with access.using(None), access.viewing("matt"):
            self.refused(403, self.apply, profile="user1", expect="bad", confirm_restore=None)
        self.refused(403, self.apply, profile="user1", expect="bad", confirm_restore=None)

    def test_whole_source_ownership_precedes_bad_flags_receipt_and_private_row_validation(self):
        for mode in ("missing", "mixed", "hidden"):
            self.seed()
            if mode == "missing":
                self.store.audit.clear()
            elif mode == "mixed":
                self.store.audit[CHANGE_ID].append({"id": ROW_ID + 1, "table": "accessory_image", "op": "DELETE"})
                self.store.audit[CHANGE_ID][0]["before"]["notes"] = object()
            else:
                self.store.audit[CHANGE_ID][0]["before"].update(owner="user1", name="Private removed fixture")
            with self.subTest(mode=mode), mock.patch.object(kernel, "raw_row", side_effect=AssertionError("No private row proof")):
                for function in (self.view, lambda: self.apply(expect="bad", confirm_restore={"bad": True}, reason=None)):
                    error = self.refused(404, function)
                    self.assertEqual((error.message, error.extra), (accessory_undo.NO_CHANGE, {}))
        self.assertEqual(self.store.writes, [])

    def test_only_true_confirmation_is_accepted_and_flags_cannot_cross_actions(self):
        preview = self.view()
        for value in (OMIT, None, False, 0, 1, "true", [], {}):
            with self.subTest(confirm=value):
                self.refused(400, self.apply, expect=preview["expect"], confirm_restore=value)
        for reason in (None, "A removal-only reason", False):
            with self.subTest(reason=reason):
                self.refused(400, self.apply, expect=preview["expect"], reason=reason)
        for extra in ({"current": None}, {"restored": preview["restored"]}, {"row": preview["restored"]}, {"rows": []}, {"fields": []},
                      {"added_id": "override"}, {"owner": "shared"}, {"space": "home"}, {"quantity": "1"}, {"action": "accessory_add"}):
            with self.subTest(extra=extra):
                self.refused(400, self.apply, expect=preview["expect"], **extra)
        for op in ("UPDATE", "INSERT"):
            for confirm in (True, None, False):
                restored = self.seed()
                self.store.snapshot = self.store.snapshot.with_accessories([*[row.as_dict() for row in self.store.snapshot.accessories.rows], restored])
                source = self.store.audit[CHANGE_ID][0]
                source.update(op=op, after=copy.deepcopy(restored), before=None if op == "INSERT" else {**restored, "notes": "Former fixture note"})
                with self.subTest(op=op, confirm=confirm):
                    self.refused(400, self.apply, expect="a" * 64, confirm_restore=confirm)
        self.assertEqual(self.store.writes, [])

    def test_id_collision_latest_and_list_changes_refuse_without_generating_another_name_or_replay(self):
        for mode in ("collision", "latest", "own_list"):
            restored = self.seed()
            preview = self.view()
            if mode == "collision":
                rows = [row.as_dict() for row in self.store.snapshot.accessories.rows]
                self.store.snapshot = self.store.snapshot.with_accessories([*rows, {**restored, "notes": "Current distinct occupant"}])
            elif mode == "latest":
                self.store.latest += 1
            else:
                rows = [row.as_dict() for row in self.store.snapshot.accessories.rows]
                next(row for row in rows if row["id"] == "b-shared")["notes"] = "Later own/shared list change"
                self.store.snapshot = self.store.snapshot.with_accessories(rows)
            before = self.store.snapshot
            with self.subTest(mode=mode):
                if mode == "collision":
                    with mock.patch.object(accessories, "new_id", side_effect=AssertionError("No alternate generated ID")):
                        self.refused(409, self.apply, expect=preview["expect"])
                else:
                    self.refused(409, self.apply, expect=preview["expect"])
            self.assertEqual((self.store.snapshot, self.store.writes), (before, []))
        self.seed()
        preview = self.view()
        self.apply(expect=preview["expect"])
        self.refused(409, self.apply, expect=preview["expect"])
        self.assertEqual(len(self.store.writes), 1)

    def test_malformed_add_projection_full_row_and_actual_receipts_never_acknowledge_saved(self):
        plan = self.store.accessory_undo_review(CHANGE_ID, frozenset({"matt", "shared"}))
        result = {"review": plan, "restored": plan["restored"], "added_id": plan["restored"]["id"], "sha256": plan["sha256"], "revision": str(ROW_ID + 1)}
        missing_added = {key: value for key, value in result.items() if key != "added_id"}
        for replacement in (None, missing_added, {**result, "added_id": "different"}, {**result, "added_id": 1},
                            {**result, "restored": kernel.meta(plan["restored"])}, {**result, "restored": {**plan["restored"], "quantity": "9999"}},
                            {**result, "sha256": "0" * 64}, {**result, "revision": str(ROW_ID)}, {**result, "revision": "9223372036854775808"},
                            *({**result, "review": {**plan, **extra}} for extra in
                              ({"current": {}}, {"confirmation_required": False}, {"fields": []}, {"reason_required": True}, {"owners": None},
                               {"restored": {**plan["restored"], "unexpected": "field"}}, {"action": "accessory_update"}))):
            with self.subTest(result=replacement), mock.patch.object(self.store, "accessory_undo_apply", return_value=replacement):
                self.assertEqual(self.refused(503, self.apply, expect=plan["expect"]).message, accessory_undo.UNCONFIRMED)
        self.assertEqual(self.store.writes, [])

    def test_unavailable_and_committed_lost_reply_never_retry_or_falsely_acknowledge(self):
        with mock.patch.object(self.store, "accessory_undo_review", side_effect=inventory.Unavailable("Private fixture storage")):
            error = self.refused(503, self.view)
            self.assertEqual((error.message, error.extra), (DATABASE_DOWN, {"reason": "database"}))
        preview = self.view()
        self.store.fail_after_commit = True
        self.refused(503, self.apply, expect=preview["expect"])
        self.assertEqual(len(self.store.writes), 1)
        self.assertEqual(len([call for call in self.store.calls if call[0] == "apply"]), 1)
        self.assertEqual([row.as_dict() for row in self.store.snapshot.accessories.rows if row.accessory_id == preview["restored"]["id"]], [preview["restored"]])
        self.refused(409, self.apply, expect=preview["expect"])
        self.assertEqual(len(self.store.writes), 1)

    def test_activity_hint_requires_one_complete_owned_delete_and_is_never_authority(self):
        change = {"id": CHANGE_ID, "total": 1, "rows": copy.deepcopy(self.store.audit[CHANGE_ID])}
        shown, viewer = {"id": CHANGE_ID}, guard.viewer()
        self.assertEqual(activity_undo.review_hint(change, shown, viewer), {"review": True, "kind": "accessory"})
        for replacement in ({**change, "total": 2}, {**change, "rows": change["rows"] * 2}, {**change, "more": True}, {**change, "groups": [{"count": 1}]}):
            with self.subTest(change=replacement):
                self.assertIsNone(activity_undo.review_hint(replacement, shown, viewer))
        self.assertIsNone(activity_undo.review_hint(change, {"id": CHANGE_ID + 1}, viewer))
        with self.identity("user1"):
            self.assertIsNone(activity_undo.review_hint(change, shown, guard.viewer()))
