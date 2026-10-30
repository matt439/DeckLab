"""Activity reviews a deleted token card and restores it only as a confirmed, freshly identified row."""
import copy
import json
from unittest import mock

from decklab.lib import access, inventory
from decklab.lib.api import activity_undo as api, guard, saving
from decklab.lib.inventory import files, undo_token_delete as deleted
from decklab.lib.api.common import ApiError
from decklab.tests import test_activity_undo_api as fixture
from decklab.tests.test_inventory_undo_token_restore import FRESH, TokenRestoreFixture


class TokenDeleteApiTests(TokenRestoreFixture):
    def view(self):
        return api.undo_view(id=str(fixture.CHANGE_ID))

    def apply(self, profile="matt", **extra):
        return api.apply_undo(json.dumps({"profile": profile, "id": fixture.CHANGE_ID,
                                          "expect": "0" * 64, **extra}).encode())

    def refused(self, status, call, *args, **kwargs):
        with self.assertRaises(ApiError) as caught:
            call(*args, **kwargs)
        self.assertEqual(caught.exception.status, status)
        return caught.exception

    def test_exact_packet_has_only_authorized_token_facts_and_fixed_policy(self):
        answer = self.view()
        self.assertEqual(set(answer), {"available", "id", "expect", "kind", "space", "label", "action",
            "current", "restored", "identity_policy", "physical_confirmation_required", "packing_restored"})
        self.assertEqual(answer["restored"], self.old)
        self.assertEqual((answer["action"], answer["identity_policy"]), (deleted.ACTION, deleted.IDENTITY_POLICY))
        self.assertIs(answer["available"], True)
        self.assertIsNone(answer["current"])
        self.assertIs(answer["packing_restored"], False)
        self.assertNotIn("id", answer["restored"])
        self.assertNotIn("position", answer["restored"])
        self.assertEqual(self.store.writes, [])

    def test_confirmed_apply_restores_one_fresh_row_and_returns_its_actual_receipt(self):
        preview = self.view()
        answer = self.apply(expect=preview["expect"], confirm_owned=True)
        self.assertEqual(set(answer), {"saved", "source_id", "expect", "kind", "space", "action", "added_token_row_id",
                                       "restored", "sha256", "revision", "summary"})
        self.assertEqual((answer["action"], answer["added_token_row_id"], answer["restored"]), (deleted.ACTION, FRESH, self.old))
        self.assertEqual(answer["sha256"], files.rendered_sha256(self.store.snapshot.token_set("home")))
        op, actor, message, summary = self.store.writes[0]
        self.assertEqual(dict(op.params), {"change_id": fixture.CHANGE_ID, "space": "home", "expect": preview["expect"],
                                           "confirm_owned": True})
        self.assertEqual((actor.id, message), ("matt", f"Undo activity change {fixture.CHANGE_ID}"))
        self.assertEqual(len(self.store.writes), 1)
        replay = self.refused(409, self.apply, expect=preview["expect"], confirm_owned=True)
        self.assertIn("Angel / The Monarch", replay.message)
        self.assertEqual(len(self.store.writes), 1)

    def test_missing_confirmation_reason_and_stale_receipt_refuse_before_any_write(self):
        preview = self.view()
        with mock.patch.object(saving, "apply_op", side_effect=AssertionError("No write entry point")):
            for extra in ({}, {"confirm_owned": False}, {"confirm_owned": "true"},
                          {"confirm_owned": True, "reason": "Not a removal"}):
                with self.subTest(extra=extra):
                    self.refused(400, self.apply, expect=preview["expect"], **extra)
            self.refused(400, self.apply, expect="bad", confirm_owned=True)
            self.refused(409, self.apply, expect="0" * 64, confirm_owned=True)
        self.assertEqual(self.store.writes, [])

    def test_unproved_backend_result_is_never_reported_as_saved(self):
        preview = self.view()
        self.store.apply = fixture.AuditInventory.apply.__get__(self.store)  # No transaction-local proof.
        self.refused(503, self.apply, expect=preview["expect"], confirm_owned=True)

    def test_member_restores_in_own_space_and_cannot_reach_home_or_be_reached_by_admin(self):
        self.store.snapshot = self.store.snapshot.with_tokens("home", [self.zombie()])
        self.seed(space="user2")
        self.refused(404, self.view)  # Matt (admin) cannot see user2's source.
        self.refused(404, self.apply, expect="0" * 64, confirm_owned=True)
        with access.using({"profile": "user2", "email": "user2@example.com", "remote": True}):
            preview = self.view()
            self.assertEqual(preview["space"], "user2")
            self.assertNotIn("Zombie", json.dumps(preview))
            answer = self.apply(profile="user2", expect=preview["expect"], confirm_owned=True)
        self.assertEqual((answer["space"], answer["added_token_row_id"]), ("user2", FRESH))
        self.assertEqual([row.id for row in self.store.snapshot.token_set("home").rows], [80])
        self.seed()
        with access.using({"profile": "user2", "email": "user2@example.com", "remote": True}):
            self.refused(404, self.view)
            self.refused(404, self.apply, profile="user2", expect="0" * 64, confirm_owned=True)
        self.assertEqual(len(self.store.writes), 1)

    def test_missing_hidden_and_mixed_sources_reveal_no_notes_or_private_refusal_details(self):
        original = copy.deepcopy(self.source())
        self.source()["before"] = {"space_id": "user2", "notes": "Private audit note"}
        hidden = self.refused(404, self.apply, expect="bad")
        self.store.audit[fixture.CHANGE_ID] = []
        missing = self.refused(404, self.apply, expect="bad")
        self.store.audit[fixture.CHANGE_ID] = [original, {**original, "table": "collection_import"}]
        mixed = self.refused(404, self.apply, expect="bad")
        self.assertEqual([error.message for error in (hidden, missing, mixed)], [api.NO_CHANGE] * 3)
        self.assertEqual([error.extra for error in (hidden, missing, mixed)], [{}, {}, {}])

    def test_admin_public_visibility_and_browser_space_do_not_open_another_members_source(self):
        self.seed(space="user2")
        self.refused(404, self.view)
        self.refused(400, self.apply, space="user2")
        self.box = self.case.box
        self.box.state.visibility_set("user2", "collection", True, inventory.Actor("test", "Fixture"),
                                      "Publish fixture collection")
        self.refused(404, self.view)

    def test_member_and_other_home_profile_get_only_their_own_space_review(self):
        with access.using({"profile": "user1", "email": "user1@example.com", "remote": True}):
            self.assertEqual(self.view()["space"], "home")
        self.seed(space="user2")
        with access.using({"profile": "user2", "email": "user2@example.com", "remote": True}):
            self.assertEqual(self.view()["space"], "user2")
        self.refused(404, self.view)

    def test_write_scope_is_required_even_though_review_itself_is_readonly(self):
        with mock.patch.object(guard, "require_space_write", side_effect=ApiError(403, "Fixture refusal")):
            self.refused(403, self.view)
        self.assertEqual(self.store.writes, [])

    def test_advisory_hint_is_distinct_and_never_uses_displayed_rows_as_source_authority(self):
        change = {"id": fixture.CHANGE_ID, "total": 1, "rows": [copy.deepcopy(self.source())]}
        hint = api.review_hint(change, {"id": fixture.CHANGE_ID}, guard.viewer())
        self.assertEqual(hint, {"review": True})
        self.store.audit[fixture.CHANGE_ID] = []
        self.refused(404, self.view)
        for extra in ({"total": 2}, {"more": True}, {"groups": {"token_card": 1}}):
            self.assertIsNone(api.review_hint({**change, **extra}, {"id": fixture.CHANGE_ID}, guard.viewer()))

    def test_historical_notes_are_literal_owned_facts_but_extra_audit_fields_are_not_projected(self):
        self.source()["before"]["notes"] = '<img src=x onerror="fixture"> & paired faces verified'
        packet = self.view()
        self.assertEqual(packet["restored"]["notes"], self.source()["before"]["notes"])
        self.assertNotIn("message", packet)
        self.assertNotIn("reason", packet)
        self.source()["message"] = "Private change message"
        self.assertEqual(self.view(), {"available": False, "id": fixture.CHANGE_ID, "reason": api.UNSUPPORTED})

    def test_projection_refuses_weakened_policy_malformed_row_and_unrecognized_identity_proof(self):
        plan = self.review()
        mutations = [lambda p: p.update(read_only=True), lambda p: p.update(identity_policy="reuse_id"),
                     lambda p: p.update(row_change_id=True), lambda p: p.update(row_change_id=None),
                     lambda p: p.update(physical_confirmation_required=False), lambda p: p.update(packing_restored=True),
                     lambda p: p.update(current={}), lambda p: p.update(kind="collection"),
                     lambda p: p.update(expect="bad"), lambda p: p["restore"].update(quantity=True),
                     lambda p: p["restore"].update(notes="line\nline"), lambda p: p["restore"].update(id=71),
                     lambda p: p["restore"].update(finish=""), lambda p: p["restore"].update(notes="pairing unknown")]
        for mutate in mutations:
            changed = copy.deepcopy(plan)
            mutate(changed)
            with self.subTest(changed=changed):
                self.refused(503, api._project, changed)

    def test_stale_conflict_does_not_quote_packing_holder_names_or_raw_errors(self):
        self.latest += 1
        error = self.refused(409, self.view)
        self.assertIn("Angel / The Monarch", error.message)
        self.assertNotIn("physical", error.message)
        self.assertEqual(self.store.writes, [])
