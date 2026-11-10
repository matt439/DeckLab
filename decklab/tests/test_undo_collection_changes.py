"""Ordinary collection identity/mixed source operations over synthetic audited snapshots."""
import copy
import json
import unittest
from unittest import mock

from decklab.lib import access, inventory
from decklab.lib.api import activity_collection_undo, activity_undo
from decklab.lib.api.common import ApiError
from decklab.lib.inventory import changes, model, ops_collection, paths, rules, undo
from decklab.lib.inventory import undo_collection_changes as recovery
from decklab.tests import test_activity_undo_api as fixture
from decklab.tests import test_inventory_undo_mixed as recording

ACTOR = recording.ACTOR
REASON = "Correct the complete fixture change."
OLD = fixture.CARD
OTHER = {**OLD, "set": "m19", "collector_number": "314", "quantity": 3, "notes": "Other printing"}


class AuditedCollection(recording.RecordingInventory):
    def undo_latest(self, table, key):
        rows = [row for batch in self.audit.values() for row in batch if row["table"] == table and row["key"] == key
                and not (row["op"] == "UPDATE" and {k: v for k, v in row["before"].items() if k != "location"}
                         == {k: v for k, v in row["after"].items() if k != "location"})]
        return max((row["id"] for row in rows), default=None)

    def apply(self, op, actor, message, reason=None, expected_revision=None):
        before = self.snapshot
        after, summary = op.run(changes.detach(before))
        after = changes.prepare(before, after, revision=before.revision + "-fixture")
        actual = self._record(before, after, [])
        if recovery.restoring(summary):
            if getattr(self, "mutate", None):
                after, actual, reason = self.mutate(after, actual, reason)
            summary = recovery.confirm(before, after, summary, actual, reason)
        self.next_change += 1
        self.audit[self.next_change] = actual
        self.said[self.next_change] = (reason, message)
        self.snapshot = after
        self.writes.append((op, actor, message, summary, reason))
        return after, summary


class CollectionChangesCase(unittest.TestCase):
    def setUp(self):
        self.case = fixture.ActivityUndoApiTests()
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        initial = self.case.backend.snapshot.replace(decks={}, products=(),
            status=model.Sheet(paths.STATUS, tuple(rules.STATUS_FIELDS), (), True)).with_collection("home", [OLD])
        self.store = AuditedCollection(initial)
        self.addCleanup(inventory.use(self.store))

    def write(self, kind, **params):
        inventory.apply(inventory.Op(kind, {"space": "home", **params}), ACTOR, "Synthetic forward operation")
        return self.store.next_change

    def review(self, source):
        return recovery.review(source, "home", self.store.snapshot, self.store)

    def inverse(self, source, plan=None, **extra):
        plan = self.review(source) if plan is None else plan
        after, summary = recovery.apply(self.store.snapshot, plan, source, "home", reason=extra.get("reason"))
        actual = self.store._record(self.store.snapshot, after, [])
        summary = recovery.confirm(self.store.snapshot, after, summary, actual, extra.get("reason"))
        return after, summary

    def identity(self, **extra):
        return self.write("collection.edit", original=list(rules.ident(OLD)), row=OTHER, **extra)


class CollectionChangesTests(CollectionChangesCase):
    def test_one_identity_change_uses_complete_normal_source_and_preserves_current_transported_location(self):
        self.store.snapshot = self.store.snapshot.with_locations("home", {rules.ident(OLD): "Row 1"})
        source = self.identity()
        original = copy.deepcopy(self.store.audit[source])
        self.write("collection.locations", keys=[list(rules.ident(OTHER))],
                   sha256=ops_collection.sha256_of(self.store.snapshot.collection("home")),
                   locations_sha256=ops_collection.locations_sha256_of(self.store.snapshot, "home"), location="Row 4")
        plan = self.review(source)
        self.assertEqual((plan["row_count"], plan["reason_required"], plan["physical_confirmation_required"]), (2, True, True))
        self.assertEqual(plan["location_transfer"]["location"], "Row 4")
        after, summary = self.inverse(source, plan, reason=REASON)
        self.assertEqual(undo._remaining_collection(after, "home", "Fixture"), {rules.ident(OLD): OLD})
        self.assertEqual(after.locations_of("home"), {rules.ident(OLD): "Row 4"})
        self.assertTrue(summary.extra["collection_confirmed"])
        self.assertEqual(self.store.audit[source], original)

    def test_merge_without_upload_restores_the_complete_mixed_insert_update_and_preserves_survivor_location(self):
        self.store.snapshot = self.store.snapshot.with_locations("home", {rules.ident(OLD): "Row 2"})
        source = self.write("collection.import", sources=[("fixture", [{**OLD, "quantity": 2}, OTHER])])
        self.assertTrue(recovery.handles(self.store.audit[source]))
        plan = self.review(source)
        self.assertTrue(plan["reason_required"])
        self.assertFalse(plan["physical_confirmation_required"])
        after, _ = self.inverse(source, plan, reason=REASON)
        self.assertEqual(undo._remaining_collection(after, "home", "Fixture"), {rules.ident(OLD): OLD})
        self.assertEqual(after.locations_of("home"), {rules.ident(OLD): "Row 2"})

    def test_mixed_normal_apply_restores_deleted_rows_and_updates_whole_with_no_partial_source(self):
        self.store.snapshot = self.store.snapshot.with_collection("home", [OLD, OTHER])
        source = self.write("collection.apply", edits=[(list(rules.ident(OLD)), {**OLD, "notes": "Changed"})],
                            removals=[list(rules.ident(OTHER))])
        plan = self.review(source)
        self.assertFalse(plan["reason_required"])
        self.assertTrue(plan["physical_confirmation_required"])
        after, _ = self.inverse(source, plan)
        self.assertEqual(undo._remaining_collection(after, "home", "Fixture"), {rules.ident(OLD): OLD, rules.ident(OTHER): OTHER})

    def test_same_key_name_correction_requires_both_identity_confirmation_and_reason(self):
        source = self.write("collection.edit", original=list(rules.ident(OLD)), row={**OLD, "name": "Elvish Mystic"})
        plan = self.review(source)
        self.assertEqual(plan["row_count"], 1)
        self.assertTrue(plan["reason_required"] and plan["physical_confirmation_required"])
        after, _ = self.inverse(source, plan, reason=REASON)
        self.assertEqual(undo._remaining_collection(after, "home", "Fixture"), {rules.ident(OLD): OLD})

    def test_same_key_count_details_and_location_correction_restores_card_facts_but_preserves_current_location(self):
        self.store.snapshot = self.store.snapshot.with_locations("home", {rules.ident(OLD): "Row 1"})
        source = self.write("collection.edit", original=list(rules.ident(OLD)), row={**OLD, "quantity": 5, "notes": "Count correction"}, location="Row 2")
        self.assertTrue(recovery.handles(self.store.audit[source]))
        plan = self.review(source)
        self.assertFalse(plan["reason_required"] or plan["physical_confirmation_required"])
        after, _ = self.inverse(source, plan)
        self.assertEqual(undo._remaining_collection(after, "home", "Fixture"), {rules.ident(OLD): OLD})
        self.assertEqual(after.locations_of("home"), {rules.ident(OLD): "Row 2"})

    def test_foreign_source_precedes_schema_count_and_card_data_checks(self):
        source = self.identity()
        raw = self.store.audit[source]
        raw[0]["before"]["space_id"] = "user2"
        self.store.audit[source] *= 30
        with mock.patch.object(recovery, "_deleted_row", side_effect=AssertionError("No hidden card data")), \
                self.assertRaises(undo.UndoMissing):
            self.review(source)

    def test_physical_holder_refuses_printing_replacement_even_when_aggregate_name_quantity_is_sufficient(self):
        source = self.identity()
        text = "# Built fixture\n\n- **Format:** Casual 60-card, 1v1\n- **Status:** built\n\n## Decklist\n\n```\nDeck\n1 Llanowar Elves\n59 Forest\n```\n"
        self.store.snapshot = self.store.snapshot.with_deck(model.Deck("home", "casual", "built", text))
        with self.assertRaises(undo.UndoConflict):
            self.review(source)

    def test_whole_candidate_checks_combined_stock_after_restore_offsets_and_quantity_reductions(self):
        self.store.snapshot = self.store.snapshot.with_collection("home", [OLD, OTHER])
        source = self.write("collection.apply", edits=[(list(rules.ident(OLD)), {**OLD, "quantity": 6})],
                            removals=[list(rules.ident(OTHER))])
        text = "# Capacity fixture\n\n- **Format:** Casual 60-card, 1v1\n- **Status:** built\n\n## Decklist\n\n```\nDeck\n6 Llanowar Elves\n54 Forest\n```\n"
        self.store.snapshot = self.store.snapshot.with_deck(model.Deck("home", "casual", "capacity", text))
        # The complete inverse returns three copies but lowers the other row by four: five remain, six are held.
        with self.assertRaises(undo.UndoConflict):
            self.review(source)

    def test_multiple_replacements_restore_blank_locations_but_refuse_ambiguous_current_location_transfer(self):
        self.store.snapshot = self.store.snapshot.with_collection("home", [OLD, OTHER])
        new = [{**OLD, "set": "tst", "collector_number": "100"}, {**OTHER, "set": "tst", "collector_number": "101"}]
        source = self.write("collection.apply", edits=[(list(rules.ident(old)), row) for old, row in zip((OLD, OTHER), new)])
        plan = self.review(source)
        self.assertIsNone(plan["location_transfer"])
        after, _ = self.inverse(source, plan, reason=REASON)
        self.assertEqual(undo._remaining_collection(after, "home", "Fixture"), {rules.ident(OLD): OLD, rules.ident(OTHER): OTHER})
        self.store.snapshot = self.store.snapshot.with_locations("home", {rules.ident(new[0]): "Row 2"})
        before = self.store.snapshot
        with self.assertRaisesRegex(undo.UndoUnsupported, "ambiguous current storage locations"):
            self.review(source)
        self.assertEqual(self.store.snapshot, before)

    def test_changed_or_touched_keys_refuse_and_unrelated_hidden_changes_do_not_change_receipt(self):
        source = self.identity()
        original = self.review(source)["expect"]
        self.store.snapshot = self.store.snapshot.with_collection("user2", [{**OLD, "quantity": 88}]).replace(revision="hidden-change", decks_revision="hidden-deck-change")
        self.assertEqual(self.review(source)["expect"], original)
        self.write("collection.edit", original=list(rules.ident(OTHER)), row={**OTHER, "notes": "Temporary"})
        self.write("collection.edit", original=list(rules.ident(OTHER)), row=OTHER)
        with self.assertRaises(undo.UndoConflict):
            self.review(source)

    def test_extra_actual_audit_wrong_reason_or_other_space_mutation_cannot_pass_precommit_proof(self):
        source = self.identity()
        plan = self.review(source)
        before = self.store.snapshot
        after, summary = recovery.apply(before, plan, source, "home", REASON)
        actual = self.store._record(before, after, [])
        for saved, written, reason in ((after, actual + actual, REASON), (after, actual, None),
                                      (after.with_collection("user2", [OTHER]), actual, REASON)):
            with self.subTest(reason=reason, rows=len(written)), self.assertRaises(undo.UndoConflict):
                recovery.confirm(before, saved, summary, written, reason)

    def test_old_duplicate_nonpositive_or_malformed_actual_audit_ids_refuse_the_whole_inverse(self):
        source = self.identity()
        plan = self.review(source)
        before = self.store.snapshot
        after, summary = recovery.apply(before, plan, source, "home", REASON)
        actual = self.store._record(before, after, [])
        for rid in (0, -1, True, "new", max(summary.extra["row_change_ids"]), actual[1]["id"]):
            written = copy.deepcopy(actual)
            written[0]["id"] = rid
            with self.subTest(audit_id=rid), self.assertRaises(undo.UndoConflict):
                recovery.confirm(before, after, summary, written, REASON)

    def test_tampered_actual_audit_id_rolls_back_the_whole_registered_operation(self):
        source = self.identity()
        plan = self.review(source)
        before, writes, audit = self.store.snapshot, len(self.store.writes), copy.deepcopy(self.store.audit)
        def tamper(after, actual, reason):
            actual[0]["id"] = max(item["row_change_id"] for item in plan["rows"])
            return after, actual, reason
        self.store.mutate = tamper
        with self.assertRaises(undo.UndoConflict):
            inventory.apply(inventory.Op("inventory.undo", {"change_id": source, "space": "home", "expect": plan["expect"],
                "reason": REASON, "confirm_owned": True}), ACTOR, "Synthetic guarded inverse", reason=REASON)
        self.assertEqual((self.store.snapshot, len(self.store.writes), self.store.audit), (before, writes, audit))

    def test_location_only_source_is_explicitly_outside_undo_and_old_noncanonical_facts_are_not_invented(self):
        source = self.write("collection.locations", keys=[list(rules.ident(OLD))],
                            sha256=ops_collection.sha256_of(self.store.snapshot.collection("home")),
                            locations_sha256=ops_collection.locations_sha256_of(self.store.snapshot, "home"), location="Row 3")
        self.assertFalse(recovery.handles(self.store.audit[source]))
        with self.assertRaises(undo.UndoUnsupported):
            self.review(source)
        source = self.identity()
        row = next(row for row in self.store.audit[source] if row["op"] == "DELETE")
        row["before"]["name"] = "unverified historical identity"
        with self.assertRaises(undo.UndoUnsupported):
            self.review(source)


class CollectionChangesApiTests(CollectionChangesCase):
    def post(self, source, **extra):
        return activity_undo.apply_undo(json.dumps({"profile": "matt", "id": source, **extra}).encode())

    def test_only_complete_server_rows_are_projected_and_both_explicit_requirements_gate_the_write(self):
        source = self.identity()
        shown = activity_undo.undo_view(str(source))
        self.assertEqual(shown["action"], recovery.ACTION)
        self.assertTrue(shown["reason_required"] and shown["physical_confirmation_required"])
        self.assertNotIn("row_change_id", str(shown))
        self.assertNotIn("proof", shown)
        writes = len(self.store.writes)
        for fields in ({"reason": REASON}, {"confirm_owned": True}, {"reason": " ", "confirm_owned": True}):
            with self.subTest(fields=fields), self.assertRaises(ApiError) as refused:
                self.post(source, expect=shown["expect"], **fields)
            self.assertEqual(refused.exception.status, 400)
            self.assertEqual(len(self.store.writes), writes)
        answer = self.post(source, expect=shown["expect"], reason=REASON, confirm_owned=True)
        self.assertTrue(answer["saved"])
        self.assertEqual(answer["row_count"], 2)
        self.assertNotIn("revision", answer)
        self.assertEqual(len(self.store.writes), writes + 1)
        with self.assertRaises(ApiError) as stale:
            self.post(source, expect=shown["expect"], reason=REASON, confirm_owned=True)
        self.assertEqual(stale.exception.status, 409)

    def test_other_space_source_is_missing_before_malformed_receipt_or_printing_validation(self):
        source = self.identity()
        with access.using({"profile": "user2", "email": "user2@example.com", "remote": True}), \
                mock.patch.object(recovery, "_deleted_row", side_effect=AssertionError("No hidden card validation")):
            with self.assertRaises(ApiError) as hidden:
                activity_undo.undo_view(str(source))
            self.assertEqual(hidden.exception.status, 404)
            with self.assertRaises(ApiError) as hidden:
                activity_undo.apply_undo(json.dumps({"profile": "user2", "id": source, "expect": "malformed"}).encode())
            self.assertEqual(hidden.exception.status, 404)

    def test_changed_current_location_refuses_old_preview_without_silently_reapplying_it(self):
        source = self.identity()
        shown = activity_undo.undo_view(str(source))
        self.write("collection.locations", keys=[list(rules.ident(OTHER))],
                   sha256=ops_collection.sha256_of(self.store.snapshot.collection("home")),
                   locations_sha256=ops_collection.locations_sha256_of(self.store.snapshot, "home"), location="Row 3")
        with self.assertRaises(ApiError) as changed:
            self.post(source, expect=shown["expect"], reason=REASON, confirm_owned=True)
        self.assertEqual(changed.exception.status, 409)
        self.assertEqual(self.store.snapshot.locations_of("home"), {rules.ident(OTHER): "Row 3"})

    def test_projector_refuses_omitted_targets_wrong_flags_or_invented_location_transfer(self):
        source = self.identity()
        plan = self.review(source)
        for change in ({"rows": plan["rows"][:1]}, {"reason_required": False}, {"physical_confirmation_required": False},
                       {"location_transfer": None}):
            with self.subTest(change=change), self.assertRaises(ApiError) as malformed:
                activity_collection_undo.project({**plan, **change})
            self.assertEqual(malformed.exception.status, 503)

    def test_ambiguous_nonblank_location_refusal_is_explicit_and_writes_nothing(self):
        self.store.snapshot = self.store.snapshot.with_collection("home", [OLD, OTHER])
        new = [{**OLD, "set": "tst", "collector_number": "100"}, {**OTHER, "set": "tst", "collector_number": "101"}]
        source = self.write("collection.apply", edits=[(list(rules.ident(old)), row) for old, row in zip((OLD, OTHER), new)])
        self.store.snapshot = self.store.snapshot.with_locations("home", {rules.ident(new[0]): "Row 2"})
        writes = len(self.store.writes)
        shown = activity_undo.undo_view(str(source))
        self.assertFalse(shown["available"])
        self.assertIn("ambiguous current storage locations", shown["reason"])
        self.assertNotIn("Row 2", shown["reason"])
        self.assertEqual(len(self.store.writes), writes)

    def test_reader_cap_withholds_source_counts_when_whole_change_ownership_is_unknown(self):
        source = self.identity()
        self.store.audit[source] *= 1001  # database reader returns only MIXED_MAX+1
        with mock.patch.object(recovery, "_deleted_row", side_effect=AssertionError("No incomplete-source card data")), \
                self.assertRaises(ApiError) as hidden:
            activity_undo.undo_view(str(source))
        self.assertEqual(hidden.exception.status, 404)
        self.assertNotIn("2001", hidden.exception.message)
