"""Accessory INSERT Undo API over isolated, authoritative audit-shaped rows.

The fake runs the real inverse and actual-result verifier. No database, host
tools, household records, images, network or real writes are used.
"""
import copy
import json
from unittest import mock

from decklab.lib import access, accessory_fetch, cards, inventory
from decklab.lib.api import accessory_undo, activity_undo, guard
from decklab.lib.api.common import ApiError, DATABASE_DOWN
from decklab.lib.inventory import accessory_undo as kernel
from decklab.lib.inventory import changes
from decklab.tests import accessory_undo_support as support
from decklab.tests import household_config
from decklab.tests.test_accessory_undo_api import AuditAccessories
from decklab.tests.test_api import ApiTestCase

CHANGE_ID = support.CHANGE_ID
ROW_ID = support.ROW_ID
DEFAULT = object()
OMIT = object()


class InsertAuditAccessories(AuditAccessories):
    def __init__(self, snapshot):
        super().__init__(snapshot)
        self._initial = snapshot

    def accessory_undo_apply(self, change_id, owners, expect, actor, message, reason=...):
        self.calls.append(("apply", change_id, owners))
        canonical = None
        if reason is not ...:
            source = kernel.source_record(self.undo_audit(change_id), owners)
            if source["op"] != "INSERT":
                raise inventory.Invalid("Restoring accessory text does not take a removal reason.")
            canonical = kernel.removal_reason(reason)
        before = self.snapshot
        operation = kernel.MetadataRestore(change_id, owners, expect, reason=canonical, store=self)
        after, summary = operation.run(changes.detach(before))
        after = changes.prepare(before, after).replace(decks_revision="fixture-saved-decks")
        source = operation.plan["source"]
        actual = [{"id": self.latest + 1, "table": "accessory", "op": "DELETE" if source["op"] == "INSERT" else "UPDATE",
                   "key": copy.deepcopy(source["key"]), "before": copy.deepcopy(source["after"]),
                   "after": copy.deepcopy(source["before"])}]
        result = operation.verify(before, after, actual)
        self.snapshot, self.latest = after, actual[0]["id"]
        self.writes.append({"actor": actor, "message": message, "reason": canonical, "summary": summary, "rows": actual})
        if self.fail_after_commit:
            raise inventory.Unavailable("Synthetic lost reply after commit, with private storage details")
        return result


class AccessoryInsertUndoApiTests(ApiTestCase):
    def setUp(self):
        super().setUp()
        household_config.use(self)
        self.store = InsertAuditAccessories(support.build_snapshot())
        self.addCleanup(inventory.use(self.store))
        self.enterContext(self.identity("matt"))
        self.seed()

    def identity(self, pid):
        return access.using({"profile": pid, "email": pid + "@example.com", "remote": True})

    def seed(self, owner="matt", *, only=False):
        current = support.seed_insert(self.store, owner, only)
        self.store.calls.clear()
        return current

    def view(self, change_id=CHANGE_ID):
        return accessory_undo.accessory_undo_view(id=change_id)

    def apply(self, *, profile="matt", change_id=CHANGE_ID, expect=DEFAULT, reason="Accidental fixture addition", **extra):
        if expect is DEFAULT:
            expect = self.view(change_id)["expect"]
        body = {"profile": profile, "id": change_id, "expect": expect, **extra}
        if reason is not OMIT:
            body["reason"] = reason
        return accessory_undo.apply_accessory_undo(json.dumps(body).encode())

    def refused(self, status, function, *args, **kwargs):
        with self.assertRaises(ApiError) as caught:
            function(*args, **kwargs)
        self.assertEqual(caught.exception.status, status, caught.exception.message)
        return caught.exception

    def test_preview_is_full_raw_thirteen_fields_with_reason_and_null_restored_only(self):
        current = self.seed()
        before = self.store.snapshot
        source = copy.deepcopy(self.store.audit)
        with mock.patch.object(inventory, "image", side_effect=AssertionError("No image bytes")), \
                mock.patch.object(accessory_fetch, "fetch", side_effect=AssertionError("No link fetch")), \
                mock.patch.object(cards, "resolve", side_effect=AssertionError("No card index")):
            result = self.view()
        self.assertEqual(set(result), {"available", "id", "expect", "kind", "action", "label", "current", "restored", "reason_required"})
        self.assertEqual((result["kind"], result["action"], result["label"]), ("accessory", "accessory_remove", current["name"]))
        self.assertIs(result["reason_required"], True)
        self.assertIsNone(result["restored"])
        self.assertEqual(result["current"], current)
        self.assertEqual(set(result["current"]), set(kernel.RAW))
        self.assertEqual(len(result["current"]), 13)
        self.assertTrue(all(isinstance(value, str) for value in result["current"].values()))
        self.assertRegex(result["expect"], r"^[a-f0-9]{64}$")
        self.assertEqual((self.store.snapshot, self.store.audit, self.store.writes), (before, source, []))

    def test_own_shared_and_last_row_removals_audit_normalized_reason_and_actual_empty_result(self):
        for owner, viewer, only in (("matt", "matt", False), ("shared", "user1", False), ("matt", "matt", True)):
            current = self.seed(owner, only=only)
            before, source = self.store.snapshot, copy.deepcopy(self.store.audit)
            with self.subTest(owner=owner, only=only), self.identity(viewer):
                preview = self.view()
                result = self.apply(profile=viewer, expect=preview["expect"], reason="  Wrong  fixture\r\n addition  ")
            self.assertEqual(set(result), {"saved", "source_id", "expect", "kind", "action", "restored", "removed_id", "sha256", "revision", "summary"})
            self.assertEqual((result["saved"], result["source_id"], result["expect"], result["action"]),
                             (True, CHANGE_ID, preview["expect"], "accessory_remove"))
            self.assertIsNone(result["restored"])
            self.assertEqual(result["removed_id"], current["id"])
            expected = [row.as_dict() for row in before.accessories.rows if row.accessory_id != current["id"]]
            self.assertEqual([row.as_dict() for row in self.store.snapshot.accessories.rows], expected)
            self.assertEqual(result["sha256"], kernel.list_sha(expected, frozenset({viewer, "shared"})))
            self.assertEqual(result["revision"], str(self.store.latest))
            if only:
                self.assertFalse(self.store.snapshot.accessories.exists)
                self.assertEqual(self.store.snapshot.accessories.rows, ())
            self.assertEqual(len(self.store.writes), 1)
            write = self.store.writes[0]
            self.assertEqual((write["actor"].id, write["actor"].source, write["actor"].via), (viewer, "web", "tunnel"))
            self.assertEqual(write["reason"], "Wrong fixture addition")
            self.assertEqual(write["rows"], [{"id": ROW_ID + 1, "table": "accessory", "op": "DELETE", "key": {"id": current["id"]},
                                             "before": current, "after": None}])
            self.assertEqual(self.store.audit, source)
            self.assertEqual(self.store.snapshot.replace(accessories=before.accessories, revision=before.revision,
                                                         decks_revision=before.decks_revision), before)

    def test_owner_shared_public_and_script_permissions_match_ordinary_accessory_rules(self):
        current = self.seed("user1")
        self.box.state.visibility_set("user1", "accessories", True, inventory.Actor("test", "Fixture"), "Public fixture kit")
        self.assertIn("user1", guard.accessory_readers())
        self.assertNotIn("user1", guard.accessory_owners())
        for function in (self.view, lambda: self.apply(expect="bad", reason=None)):
            self.assertEqual(self.refused(404, function).message, accessory_undo.NO_CHANGE)
        with self.identity("user2"):
            self.refused(403, self.view)
            self.refused(403, self.apply, profile="user2", expect="bad", reason=None)
        with access.using(None), access.viewing(None), access.answering(True):
            self.assertEqual(self.view()["current"]["owner"], "user1")
            self.assertIsNone(self.store.calls[-1][2])
            self.refused(404, self.apply, profile="matt", expect="bad", reason=None)
            expect = self.store.accessory_undo_review(CHANGE_ID, frozenset({"user1", "shared"}))["expect"]
            result = self.apply(profile="user1", expect=expect)
            self.assertEqual(result["removed_id"], current["id"])
            self.assertEqual(self.store.writes[-1]["actor"].id, "user1")
        with access.using(None), access.viewing(None), access.answering(False):
            self.refused(403, self.view)
        with access.using(None), access.viewing("matt"):
            self.refused(403, self.apply, profile="user1", expect="bad", reason=None)
        self.refused(403, self.apply, profile="user1", expect="bad", reason=None)

    def test_complete_global_owner_scope_is_checked_before_bad_reason_receipt_or_private_row_validation(self):
        for mode in ("missing", "mixed", "hidden", "update_with_hidden_side"):
            self.seed()
            if mode == "missing":
                self.store.audit.clear()
            elif mode == "mixed":
                self.store.audit[CHANGE_ID].append({"id": ROW_ID + 1, "table": "accessory_image", "op": "INSERT"})
                self.store.audit[CHANGE_ID][0]["after"]["notes"] = object()
            else:
                source = self.store.audit[CHANGE_ID][0]
                source["after"]["owner"] = "user1"
                source["after"]["name"] = "Private insertion label"
                if mode == "update_with_hidden_side":
                    source["op"], source["before"] = "UPDATE", copy.deepcopy(source["after"])
                    source["after"]["owner"] = "matt"
            with self.subTest(mode=mode), mock.patch.object(kernel, "raw_row", side_effect=AssertionError("No raw row before scope")):
                for function in (self.view, lambda: self.apply(expect="bad", reason={"private": "bad"})):
                    error = self.refused(404, function)
                    self.assertEqual((error.message, error.extra), (accessory_undo.NO_CHANGE, {}))
        self.assertEqual(self.store.writes, [])

    def test_reason_is_mandatory_bounded_normalized_and_not_accepted_for_updates_or_override_fields(self):
        preview = self.view()
        for reason in (OMIT, None, True, 1, [], {}, "", " \t\n ", "x" * 201, "Bad\0reason"):
            with self.subTest(reason=reason):
                self.refused(400, self.apply, expect=preview["expect"], reason=reason)
        for extra in ({"current": preview["current"]}, {"restored": None}, {"fields": []}, {"rows": []}, {"removed_id": "different"},
                      {"space": "home"}, {"owner": "shared"}, {"quantity": "0"}, {"confirm_owned": True}, {"action": "accessory_remove"}):
            with self.subTest(extra=extra):
                self.refused(400, self.apply, expect=preview["expect"], **extra)
        source = self.store.audit[CHANGE_ID][0]
        source.update(op="UPDATE", before={**source["after"], "notes": "Former fixture note"})
        self.assertEqual(self.view()["action"], "accessory_update")
        for reason in ("A removal-only reason", None):
            with self.subTest(update_reason=reason):
                self.refused(400, self.apply, reason=reason)
        self.assertEqual(self.store.writes, [])

    def test_current_latest_scoped_list_and_repeated_source_are_rechecked_without_extra_writes(self):
        for mode in ("latest", "current", "own_list"):
            current = self.seed()
            preview = self.view()
            if mode == "latest":
                self.store.latest += 1
            else:
                rows = [row.as_dict() for row in self.store.snapshot.accessories.rows]
                target = next(row for row in rows if row["id"] == (current["id"] if mode == "current" else "b-shared"))
                target["notes"] = "A later fixture note"
                self.store.snapshot = self.store.snapshot.with_accessories(rows)
            with self.subTest(mode=mode):
                self.refused(409, self.apply, expect=preview["expect"])
                self.assertEqual(self.store.writes, [])
        self.seed()
        preview = self.view()
        self.apply(expect=preview["expect"])
        self.refused(409, self.apply, expect=preview["expect"])
        self.assertEqual(len(self.store.writes), 1)

    def test_malformed_projection_and_actual_delete_receipts_never_acknowledge_saved(self):
        plan = self.store.accessory_undo_review(CHANGE_ID, frozenset({"matt", "shared"}))
        result = {"review": plan, "restored": None, "removed_id": plan["current"]["id"], "sha256": plan["sha256"], "revision": str(ROW_ID + 1)}
        missing_removed = {key: value for key, value in result.items() if key != "removed_id"}
        for replacement in (None, missing_removed, {**result, "removed_id": "different"}, {**result, "restored": {}},
                            {**result, "sha256": "0" * 64}, {**result, "revision": str(ROW_ID)}, {**result, "revision": ROW_ID + 1},
                            {**result, "revision": "9223372036854775808"},
                            *({**result, "review": {**plan, **extra}} for extra in
                              ({"reason_required": False}, {"restored": {}}, {"fields": []}, {"owners": None},
                               {"current": {**plan["current"], "unexpected": "field"}}, {"action": "accessory_update"}))):
            with self.subTest(result=replacement), mock.patch.object(self.store, "accessory_undo_apply", return_value=replacement):
                self.assertEqual(self.refused(503, self.apply, expect=plan["expect"]).message, accessory_undo.UNCONFIRMED)
        self.assertEqual(self.store.writes, [])

    def test_lost_reply_and_unavailable_storage_never_retry_or_falsely_acknowledge(self):
        with mock.patch.object(self.store, "accessory_undo_review", side_effect=inventory.Unavailable("Private fixture detail")):
            error = self.refused(503, self.view)
            self.assertEqual((error.message, error.extra), (DATABASE_DOWN, {"reason": "database"}))
        preview = self.view()
        self.store.fail_after_commit = True
        self.refused(503, self.apply, expect=preview["expect"])
        self.assertEqual(len(self.store.writes), 1)
        self.assertEqual(len([call for call in self.store.calls if call[0] == "apply"]), 1)
        self.assertNotIn(preview["current"]["id"], [row.accessory_id for row in self.store.snapshot.accessories.rows])
        self.refused(409, self.apply, expect=preview["expect"])
        self.assertEqual(len(self.store.writes), 1)

    def test_activity_hint_is_complete_owned_insert_only_and_never_write_authority(self):
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
