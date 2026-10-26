"""Owner-only Undo API over authoritative audit-shaped fixtures and pure inventory edits.

AuditInventory is deliberately a test double: no PostgreSQL, household data, OS
task, remote endpoint or real audit trail is read or changed by these cases.
"""
import copy
import json
from unittest import mock

from decklab.lib import access, inventory
from decklab.lib.api import activity, activity_undo, guard
from decklab.lib.api.common import ApiError
from decklab.lib.inventory import changes, files, model, rules, undo
from decklab.tests import household_config
from decklab.tests.test_api import ApiTestCase

CHANGE_ID = 17
ROW_ID = 101
CARD = {"name": "Llanowar Elves", "set": "fdn", "collector_number": "227", "finish": "nonfoil",
        "quantity": 2, "condition": "NM", "language": "en", "notes": "Current fixture note"}
TOKEN = {field: "" for field in rules.TOKEN_FIELDS}
TOKEN.update(front="Dog", quantity=2, notes="Current token fixture note")


class AuditInventory:
    name = "undo-api-fixture"

    def __init__(self, snapshot):
        self.snapshot = snapshot
        self.audit = {}
        self.latest = ROW_ID
        self.writes = []

    def load(self):
        return self.snapshot

    def undo_audit(self, change_id):
        return copy.deepcopy(self.audit.get(change_id, []))

    def undo_latest(self, table, key):
        return self.latest

    def apply(self, op, actor, message, reason=None, expected_revision=None):
        before = self.snapshot
        after, summary = op.run(changes.detach(before))
        after = changes.prepare(before, after, revision=before.revision + "-undo")
        self.snapshot = after
        self.writes.append((op, actor, message, summary))
        self.latest += 1
        return after, summary


class ActivityUndoApiTests(ApiTestCase):
    def setUp(self):
        super().setUp()
        household_config.use(self)
        self.backend = AuditInventory(self.box.inventory.load().with_collection("home", [CARD]))
        self.addCleanup(inventory.use(self.backend))
        active = access.using({"profile": "matt", "email": "matt@example.com", "remote": True})
        active.__enter__()
        self.addCleanup(active.__exit__, None, None, None)
        self.seed()

    def seed(self, kind="collection", space="home"):
        current = copy.deepcopy(CARD if kind == "collection" else TOKEN)
        restore = {**current, "quantity": 5, "notes": "Original fixture note"}
        if kind == "collection":
            restore["condition"] = "LP"
            self.backend.snapshot = self.backend.snapshot.with_collection(space, [current])
        else:
            self.backend.snapshot = self.backend.snapshot.with_tokens(space, [model.TokenRow.make(current, id=7)])
        def raw(row):
            answer = {"set_code" if key == "set" else key: value for key, value in row.items()}
            answer["space_id"] = space
            if kind == "tokens":
                answer.update(id=7, position=0)
            return answer
        old, new = raw(restore), raw(current)
        key = {field: new[field] for field in undo.COLLECTION_KEYS} if kind == "collection" else {"id": 7}
        self.backend.audit[CHANGE_ID] = [{"id": ROW_ID, "table": undo.COLLECTION if kind == "collection" else undo.TOKENS,
                                        "op": "UPDATE", "key": key, "before": old, "after": new}]
        return current, restore

    def view(self, **params):
        return activity_undo.undo_view(**{"id": str(CHANGE_ID), **params})

    def apply(self, *, id=CHANGE_ID, expect=None, **extra):
        if expect is None:
            expect = self.view()["expect"]
        return activity_undo.apply_undo(json.dumps({"profile": "matt", "id": id, "expect": expect, **extra}).encode())

    def refused(self, code, call, *args, **kwargs):
        with self.assertRaises(ApiError) as caught:
            call(*args, **kwargs)
        self.assertEqual(caught.exception.status, code, caught.exception.message)
        return caught.exception

    def test_preview_reads_authoritative_source_and_returns_only_ordinary_owner_rows(self):
        current, restore = self.seed()
        original = copy.deepcopy(self.backend.audit)
        answer = self.view()
        self.assertEqual(set(answer), {"available", "id", "expect", "kind", "space", "label", "fields", "current", "restored"})
        self.assertEqual((answer["available"], answer["id"], answer["kind"], answer["space"]), (True, CHANGE_ID, "collection", "home"))
        self.assertEqual((answer["current"], answer["restored"]), (current, restore))
        self.assertEqual(answer["fields"], [{"field": "quantity", "before": 2, "after": 5},
                                           {"field": "condition", "before": "NM", "after": "LP"},
                                           {"field": "notes", "before": "Current fixture note", "after": "Original fixture note"}])
        self.assertRegex(answer["expect"], r"^[a-f0-9]{64}$")
        self.assertEqual(self.backend.audit, original)
        self.assertEqual(self.backend.writes, [])

    def test_apply_runs_only_server_source_receipt_and_confirms_actual_saved_row(self):
        preview = self.view()
        history = copy.deepcopy(self.backend.audit)
        answer = self.apply(expect=preview["expect"])
        self.assertEqual((answer["saved"], answer["source_id"], answer["expect"], answer["kind"], answer["space"]),
                         (True, CHANGE_ID, preview["expect"], "collection", "home"))
        self.assertEqual(answer["restored"], preview["restored"])
        self.assertEqual(answer["sha256"], files.rendered_sha256(self.backend.snapshot.collection("home")))
        self.assertEqual(answer["revision"], self.backend.snapshot.revision)
        op, actor, message, summary = self.backend.writes[0]
        self.assertEqual((op.kind, dict(op.params)), ("inventory.undo", {"change_id": CHANGE_ID, "space": "home", "expect": preview["expect"]}))
        self.assertEqual((actor.id, actor.source, message), ("matt", "web", f"Undo activity change {CHANGE_ID}"))
        self.assertTrue(summary.changed)
        self.assertEqual(summary.counts["undo"], 1)
        self.assertEqual(self.backend.audit, history)
        self.assertEqual(len(self.backend.writes), 1)

    def test_tokens_keep_stable_identity_and_return_actual_ordinary_row(self):
        current, restore = self.seed("tokens")
        preview = self.view()
        self.assertEqual((preview["kind"], preview["current"], preview["restored"]), ("tokens", current, restore))
        answer = self.apply(expect=preview["expect"])
        self.assertEqual(answer["restored"], restore)
        self.assertEqual(self.backend.snapshot.token_set("home").rows[0].id, 7)
        self.assertNotIn("id", answer["restored"])
        self.assertNotIn("position", answer["restored"])

    def test_missing_hidden_and_mixed_sources_are_identical_before_receipt_validation(self):
        unknown = self.refused(404, self.apply, id=99, expect="bad")
        self.seed(space="user2")
        hidden = self.refused(404, self.apply, expect="bad")
        self.seed()
        self.backend.audit[CHANGE_ID].append(copy.deepcopy(self.backend.audit[CHANGE_ID][0]))
        self.backend.audit[CHANGE_ID][1]["after"]["space_id"] = "user2"
        mixed = self.refused(404, self.apply, expect="bad")
        self.assertEqual([error.message for error in (unknown, hidden, mixed)], [activity_undo.NO_CHANGE] * 3)
        self.assertEqual([error.extra for error in (unknown, hidden, mixed)], [{}, {}, {}])
        self.assertEqual(self.backend.writes, [])

    def test_admin_cannot_target_another_space_and_public_visibility_does_not_widen_undo(self):
        self.seed(space="user2")
        self.box.state.visibility_set("user2", "collection", True, inventory.Actor("test", "Fixture"), "Publish fixture collection")
        self.refused(404, self.view)
        self.refused(404, self.apply, expect="0" * 64)
        self.assertEqual(self.backend.writes, [])

    def test_each_member_derives_their_own_space_without_a_browser_space_selector(self):
        self.seed(space="user2")
        with access.using({"profile": "user2", "email": "user2@example.com", "remote": True}):
            preview = self.view()
            result = activity_undo.apply_undo(json.dumps({"profile": "user2", "id": CHANGE_ID, "expect": preview["expect"]}).encode())
        self.assertEqual((preview["space"], result["space"]), ("user2", "user2"))
        self.assertEqual(self.backend.writes[0][1].id, "user2")

    def test_another_household_profile_can_review_and_undo_home_rows(self):
        with access.using({"profile": "user1", "email": "user1@example.com", "remote": True}):
            preview = self.view()
            result = activity_undo.apply_undo(json.dumps({"profile": "user1", "id": CHANGE_ID, "expect": preview["expect"]}).encode())
        self.assertEqual(result["space"], "home")
        self.assertEqual(self.backend.writes[0][1].id, "user1")

    def test_unsupported_owned_fact_change_is_review_only_and_never_applied(self):
        self.backend.audit[CHANGE_ID][0]["before"]["name"] = "Elvish Mystic"
        self.assertEqual(self.view(), {"available": False, "id": CHANGE_ID, "reason": activity_undo.UNSUPPORTED})
        self.refused(400, self.apply, expect="0" * 64)
        self.assertEqual(self.backend.writes, [])

    def test_malformed_and_stale_receipts_are_refused_after_owned_source_lookup(self):
        self.refused(400, self.apply, expect="bad")
        self.refused(409, self.apply, expect="0" * 64)
        self.assertEqual(self.backend.writes, [])

    def test_later_touch_and_repeated_old_source_conflict_without_another_write(self):
        preview = self.view()
        self.apply(expect=preview["expect"])
        error = self.refused(409, self.apply, expect=preview["expect"])
        self.assertIn(preview["label"], error.message)
        self.assertEqual(error.extra, {"conflicts": [{"label": preview["label"], "reason": activity_undo.CHANGED}]})
        self.assertEqual(len(self.backend.writes), 1)

    def test_conflict_names_only_the_authorized_row_without_backend_holder_details(self):
        label = self.view()["label"]
        with mock.patch.object(self.backend, "undo_latest", side_effect=undo.UndoConflict("Fixture hidden holder detail", label)):
            error = self.refused(409, self.view)
        self.assertIn(label, error.message)
        self.assertNotIn("hidden", error.message)
        self.assertEqual(error.extra, {"conflicts": [{"label": label, "reason": activity_undo.CHANGED}]})

    def test_browser_cannot_supply_restored_rows_space_or_a_different_actor(self):
        for extra in ({"space": "user2"}, {"restored": CARD}, {"change_id": 99}):
            self.refused(400, self.apply, expect="0" * 64, **extra)
        body = json.dumps({"profile": "user1", "id": CHANGE_ID, "expect": "0" * 64}).encode()
        self.refused(403, activity_undo.apply_undo, body)
        self.assertEqual(self.backend.writes, [])

    def test_own_write_permission_is_required_before_a_stale_receipt_is_compared(self):
        original = guard.require_space_write
        def deny(profile, action, space):
            self.assertEqual((action, space), ("collection.edit", "home"))
            raise ApiError(403, "Fixture permission denied")
        with mock.patch.object(guard, "require_space_write", side_effect=deny):
            self.refused(403, self.apply, expect="bad")
        self.assertTrue(callable(original))
        self.assertEqual(self.backend.writes, [])

    def test_unavailable_storage_uses_generic_database_error_without_source_details(self):
        with mock.patch.object(self.backend, "undo_audit", side_effect=inventory.Unavailable("Fixture private storage detail")):
            error = self.refused(503, self.view)
        self.assertEqual(error.extra, {"reason": "database"})
        self.assertNotIn("private", error.message)

    def test_a_postsave_wrong_row_or_missing_summary_proof_is_an_unconfirmed_outcome(self):
        preview = self.view()
        after = self.backend.snapshot.with_collection("home", [preview["restored"]])
        proof = inventory.Summary("Fixture undo", {"undo": 1}, {"magic/collection.csv": ["quantity"]},
                                  {"undo_of": CHANGE_ID, "kind": "collection", "space": "home"})
        for result in ((self.backend.snapshot, proof), (after, inventory.Summary("Fixture empty proof"))):
            with self.subTest(result=result), mock.patch.object(activity_undo.saving, "apply_op", return_value=result):
                error = self.refused(503, self.apply, expect=preview["expect"])
                self.assertEqual(error.message, activity_undo.UNCONFIRMED)

    def test_invalid_or_missing_change_ids_are_not_audit_lookups(self):
        for value in (None, "", "0", -1, True, "1.5", [], "9" * 19, 10 ** 18):
            with self.subTest(value=value), mock.patch.object(self.backend, "undo_audit", side_effect=AssertionError("Bad id read")):
                self.refused(400, self.view, id=value)

    def test_anonymous_http_viewer_has_no_preview_even_when_inventory_is_public(self):
        with access.using(None), access.viewing(None), access.answering(False), \
                mock.patch.object(self.backend, "undo_audit", side_effect=AssertionError("Anonymous audit read")):
            self.refused(404, self.view)

    def test_activity_hint_uses_global_raw_total_and_supported_own_update_only(self):
        row = copy.deepcopy(self.backend.audit[CHANGE_ID][0])
        change = {"id": CHANGE_ID, "total": 1, "rows": [row]}
        shown = {"id": CHANGE_ID}
        profile = guard.viewer()
        self.assertEqual(activity_undo.review_hint(change, shown, profile), {"review": True})
        for extra in ({"total": 2}, {"more": 1}, {"groups": [{"table": "collection_card"}]}):
            self.assertIsNone(activity_undo.review_hint({**change, **extra}, shown, profile))
        for mutate in (lambda value: value.update(op="INSERT"),
                       lambda value: value.update(table="watchlist_item"),
                       lambda value: value["after"].update(space_id="user2")):
            changed = copy.deepcopy(change)
            mutate(changed["rows"][0])
            self.assertIsNone(activity_undo.review_hint(changed, shown, profile))

    def test_activity_list_adds_only_a_review_hint_without_calling_authoritative_preview(self):
        source = {"id": CHANGE_ID, "at": "2026-10-26T01:00:00+00:00", "actor": "matt", "source": "web", "via": "home",
                  "message": "Fixture single edit", "reason": None, "total": 1, "rows": copy.deepcopy(self.backend.audit[CHANGE_ID])}
        def listing(before, limit, visible, inventory):
            return {"changes": [visible(source)], "next": None}
        with mock.patch.object(self.box.state, "activity", side_effect=listing), \
                mock.patch.object(activity, "row_cards", return_value={}), \
                mock.patch.object(self.backend, "undo_audit", side_effect=AssertionError("Listing fetched undo preview")):
            answer = activity.activity_view()
        self.assertEqual(answer["changes"][0]["undo"], {"review": True})
        self.assertNotIn("expect", answer["changes"][0])
