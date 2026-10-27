"""Pure accessory metadata inverses, using only explicit in-memory snapshots."""
import copy
import unittest
from unittest import mock

from decklab.lib import accessories, accessory_fetch, inventory, profiles
from decklab.lib.inventory import accessory_undo as undo, changes, paths
from decklab.tests import accessory_undo_support as fixture, household_config


class AccessoryUndoTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(mock.patch.object(profiles, "read", return_value=copy.deepcopy(household_config.PROFILES)))
        self.store = fixture.AuditAccessoryInventory()
        self.addCleanup(inventory.use(self.store))

    def source(self):
        return self.store.audit[fixture.CHANGE_ID][0]

    def review(self, owners=fixture.OWNERS):
        return undo.review(fixture.CHANGE_ID, owners, self.store.snapshot, self.store)

    def saved(self, plan=None, after=None, rows=None):
        if plan is None:
            plan, after = self.review()
        return undo.verify_saved(self.store.snapshot, after, plan,
                                 fixture.actual_source(plan) if rows is None else rows)

    def test_exact_review_projects_only_nine_metadata_fields_and_preserves_inputs(self):
        before, audit = self.store.snapshot, copy.deepcopy(self.store.audit)
        plan, after = self.review()
        self.assertEqual((plan["kind"], plan["action"], plan["label"]), ("accessory", "accessory_update", "Current sleeves"))
        self.assertEqual(plan["current"], fixture.meta(self.source()["after"]))
        self.assertEqual(plan["restored"], fixture.meta(self.source()["before"]))
        self.assertEqual(set(plan["current"]), {"id", "kind", "owner", "brand", "name", "colour", "notes", "link", "image_source"})
        self.assertEqual(plan["fields"], [{"field": field, "before": self.source()["after"][field],
                                          "after": self.source()["before"][field]} for field in fixture.FIELDS])
        self.assertEqual((plan["owners"], plan["row_change_id"]), (["matt", "shared"], fixture.ROW_ID))
        self.assertRegex(plan["expect"], r"^[a-f0-9]{64}$")
        self.assertEqual(self.store.snapshot, before)
        self.assertEqual(self.store.audit, audit)
        self.assertNotEqual(after.accessories, before.accessories)

    def test_each_allowed_text_field_and_permitted_blanks_restore_exactly(self):
        for field in fixture.FIELDS:
            values = ("Original name",) if field == "name" else (
                ("https://example.com/original-" + field, "") if field in ("link", "image_source") else ("Original " + field, ""))
            for old in values:
                self.store.seed()
                self.source()["before"] = copy.deepcopy(self.source()["after"])
                self.source()["before"][field] = old
                with self.subTest(field=field, old=old):
                    plan, after = self.review()
                    self.assertEqual(plan["fields"], [{"field": field, "before": self.source()["after"][field], "after": old}])
                    self.assertEqual(self.saved(plan, after)["restored"][field], old)

    def test_complete_global_owner_proof_precedes_labels_and_schema_validation(self):
        source = copy.deepcopy(self.source())
        hidden = copy.deepcopy(source)
        hidden["before"]["owner"] = hidden["after"]["owner"] = "user1"
        hidden["before"]["name"] = "Private household item"
        malformed = copy.deepcopy(source)
        malformed["after"]["future"] = "Own detail"
        for rows in ([], [hidden], [malformed, hidden], [source, source], [{**source, "table": "profile_email"}]):
            self.store.audit[fixture.CHANGE_ID] = copy.deepcopy(rows)
            with self.subTest(rows=len(rows)), mock.patch.object(accessories, "validate_row", side_effect=AssertionError("No private validation")), \
                    self.assertRaises(undo.UndoMissing) as caught:
                self.review()
            self.assertNotIn("Private household", str(caught.exception))
        self.store.audit[fixture.CHANGE_ID] = [source]
        for side in ("before", "after"):
            self.store.audit[fixture.CHANGE_ID] = [copy.deepcopy(source)]
            self.source()[side]["owner"] = "user1"
            with self.subTest(side=side), self.assertRaises(undo.UndoMissing):
                self.review()

    def test_shared_rows_are_writable_only_in_explicit_owner_scope(self):
        self.store.seed(owner="shared")
        plan, after = self.review()
        self.assertEqual(self.saved(plan, after)["restored"]["owner"], "shared")
        for owners in (frozenset({"matt"}), frozenset(), [None], "matt"):
            with self.subTest(owners=owners), self.assertRaises(undo.UndoMissing):
                self.review(owners)
        self.store.seed(owner="user1")
        with self.assertRaises(undo.UndoMissing):
            self.review()

    def test_source_requires_exact_thirteen_text_fields_key_and_supported_update(self):
        for mode in ("missing", "extra", "quantity-int", "null", "key", "id", "audit-id", "insert", "delete", "noop"):
            self.store.seed()
            source = self.source()
            if mode == "missing":
                del source["before"]["link"]
            elif mode == "extra":
                source["after"]["future"] = "Unknown"
            elif mode == "quantity-int":
                source["before"]["quantity"] = 100
            elif mode == "null":
                source["before"]["capacity"] = None
            elif mode == "key":
                source["key"]["owner"] = "matt"
            elif mode == "id":
                source["before"]["id"] = "another-id"
            elif mode == "audit-id":
                source["id"] = True
            elif mode in ("insert", "delete"):
                source["op"] = mode.upper()
                source["before" if mode == "insert" else "after"] = None
            else:
                source["before"] = copy.deepcopy(source["after"])
            with self.subTest(mode=mode), self.assertRaises((undo.UndoMissing, undo.UndoUnsupported)):
                self.review()

    def test_raw_validation_refuses_silent_text_numeric_crop_and_url_normalization(self):
        cases = ({"name": " Padded name "}, {"brand": "Two  spaces"}, {"notes": "two\nlines"},
                 {"colour": "bad\0colour"}, {"quantity": "0100"}, {"quantity": " 100 "},
                 {"link": " https://example.com/item "}, {"link": "javascript:alert(1)"},
                 {"image_source": "one\ttwo"}, {"crop": "0.10,0.10,0.80,0.80"},
                 {"notes": "\ud800"}, {"name": ""}, {"notes": "n" * 301})
        for changed in cases:
            with self.subTest(changed=changed), self.assertRaises(undo.UndoUnsupported):
                undo.raw_row(fixture.row(**changed))

    def test_quantity_capacity_kind_owner_image_and_crop_changes_are_not_text_undo(self):
        cases = ({"quantity": "101"}, {"kind": "playmat"}, {"owner": "shared"},
                 {"image": "", "crop": ""}, {"crop": "0,0,1,1"})
        for changed in cases:
            self.store.seed()
            self.source()["before"].update(changed)
            with self.subTest(changed=changed), self.assertRaises(undo.UndoUnsupported):
                self.review()
        self.store.seed()
        self.source()["before"].update(kind="deck_box", quantity="1", capacity="80")
        self.source()["after"].update(kind="deck_box", quantity="1", capacity="100")
        with self.assertRaises(undo.UndoUnsupported):
            self.review()

    def test_url_fields_restore_individually_as_blank_http_or_https_preferences(self):
        pairs = (("", "https://example.com/current"), ("http://example.com/original", ""),
                 ("https://example.com/unknown/path?q=fixture%2Fvalue&v=2#image", "HTTP://example.com/current"))
        for field in ("link", "image_source"):
            limit = accessories.MAX_LINK if field == "link" else accessories.MAX_SOURCE
            prefix = "https://example.com/"
            for old, current in (*pairs, (prefix + "a" * (limit - len(prefix)), "")):
                self.store.seed()
                self.source()["before"] = copy.deepcopy(self.source()["after"])
                self.source()["before"][field], self.source()["after"][field] = old, current
                rows = [row.as_dict() for row in self.store.snapshot.accessories.rows]
                rows[0][field] = current
                self.store.snapshot = self.store.snapshot.with_accessories(rows)
                inputs = copy.deepcopy(self.store.audit), self.store.snapshot
                with self.subTest(field=field, old=old, current=current):
                    plan, after = self.review()
                    self.assertEqual(plan["fields"], [{"field": field, "before": current, "after": old}])
                    self.assertEqual(self.saved(plan, after)["restored"][field], old)
                    self.assertEqual(next(row for row in undo.raw_rows(after) if row["id"] == "a-sleeves"), self.source()["before"])
                    self.assertEqual((self.store.audit, self.store.snapshot), inputs)

    def test_historical_and_current_url_errors_or_normalization_never_restore_silently(self):
        for field, limit in (("link", accessories.MAX_LINK), ("image_source", accessories.MAX_SOURCE)):
            invalid = (None, 1, "ftp://example.com/image", "javascript:alert(1)", "https://example.com/two words",
                       " https://example.com/padded ", "https://example.com/line\nbreak", "https://example.com/tab\tbreak",
                       "https://example.com/nul\0byte", "https://example.com/" + "a" * limit)
            for side in ("before", "after"):
                for value in invalid:
                    self.store.seed()
                    self.source()[side][field] = value
                    if side == "after":
                        rows = [row.as_dict() for row in self.store.snapshot.accessories.rows]
                        rows[0][field] = value
                        self.store.snapshot = self.store.snapshot.with_accessories(rows)
                    with self.subTest(field=field, side=side, value=value), self.assertRaises(undo.UndoUnsupported):
                        self.review()

    def test_mixed_url_inverse_keeps_current_photos_crop_and_provenance_without_fetching(self):
        self.source()["before"] = copy.deepcopy(self.source()["after"])
        self.source()["before"].update(link="http://example.com/unknown-product?fixture=1",
                                        image_source="https://example.com/unknown-image?fixture=2#literal")
        before = self.store.snapshot
        with mock.patch.object(accessory_fetch, "fetch", side_effect=AssertionError("No URL fetch or enrichment")), \
                mock.patch.object(accessory_fetch, "_download", side_effect=AssertionError("No download")), \
                mock.patch.object(accessory_fetch, "staged_file", side_effect=AssertionError("No staging read")):
            plan, after = self.review()
            result = self.saved(plan, after)
        self.assertEqual([field["field"] for field in plan["fields"]], ["link", "image_source"])
        self.assertEqual(result["restored"], fixture.meta(self.source()["before"]))
        self.assertEqual(after.accessory_images, before.accessory_images)
        target = next(row for row in undo.raw_rows(after) if row["id"] == "a-sleeves")
        for field in ("image", "crop", "quantity", "capacity"):
            self.assertEqual(target[field], self.source()["after"][field])
        self.assertEqual(after.replace(accessories=before.accessories, revision=before.revision,
                                       decks_revision=before.decks_revision), before)

    def test_current_full_row_and_latest_target_refuse_missing_edits_and_same_value_aba(self):
        for mode in ("missing", "notes", "link", "quantity", "latest", "float-latest", "missing-latest"):
            self.store.seed()
            if mode == "missing":
                self.store.snapshot = self.store.snapshot.with_accessories([row for row in self.store.snapshot.accessories.rows if row.accessory_id != "a-sleeves"])
            elif mode in ("latest", "float-latest", "missing-latest"):
                self.store.latest = {"latest": fixture.ROW_ID + 1, "float-latest": float(fixture.ROW_ID), "missing-latest": None}[mode]
            else:
                rows = [row.as_dict() for row in self.store.snapshot.accessories.rows]
                rows[0][mode] = {"notes": "Later note", "link": "https://example.com/later", "quantity": "101"}[mode]
                self.store.snapshot = self.store.snapshot.with_accessories(rows)
            with self.subTest(mode=mode), self.assertRaises(undo.UndoConflict):
                self.review()

    def test_only_writable_owner_rows_bind_expect_and_scoped_result_digest(self):
        plan, _ = self.review()
        original = self.store.snapshot
        rows = [row.as_dict() for row in original.accessories.rows]
        rows[-1]["notes"] = "A later hidden-owner edit"
        self.store.snapshot = original.with_accessories(rows).with_collection("home", []).without_deck("casual/fixture").replace(
            revision="inventory-2", decks_revision="decks-2")
        hidden_plan, _ = self.review()
        self.assertEqual((hidden_plan["expect"], hidden_plan["sha256"]), (plan["expect"], plan["sha256"]))
        rows[1]["notes"] = "A later shared edit"
        self.store.snapshot = original.with_accessories(rows)
        visible_plan, _ = self.review()
        self.assertNotEqual(visible_plan["expect"], plan["expect"])
        self.assertNotEqual(visible_plan["sha256"], plan["sha256"])

    def test_ordinary_edit_keeps_photographs_every_other_source_and_all_raw_cells(self):
        from decklab.lib.inventory import ops_accessories
        before = self.store.snapshot
        self.assertTrue(before.collection("home").rows)
        self.assertTrue(before.collection("user2").rows)
        self.assertTrue(before.imports.get("home"))
        self.assertIsNotNone(before.deck("casual/fixture"))
        _, usage_before = ops_accessories.usage(before)
        self.assertEqual([(use["holder"], use["need"]) for use in usage_before.get("a-sleeves", ())], [("casual/fixture", 60)])
        with mock.patch.object(ops_accessories, "edit_accessory", wraps=ops_accessories.edit_accessory) as ordinary:
            plan, after = self.review()
        self.assertEqual(ordinary.call_count, 1)
        self.assertEqual(ordinary.call_args.kwargs["image"], "keep")
        self.assertEqual(ordinary.call_args.kwargs["row"], {field: self.source()["before"][field] for field in fixture.FIELDS})
        self.assertEqual(after.replace(accessories=before.accessories, revision=before.revision, decks_revision=before.decks_revision), before)
        self.assertEqual(after.accessory_images, before.accessory_images)
        self.assertEqual(ops_accessories.usage(after)[1], usage_before)
        self.assertEqual(undo.raw_rows(after), plan["raw_after"])
        target = next(row for row in undo.raw_rows(after) if row["id"] == "a-sleeves")
        self.assertEqual(target, self.source()["before"])
        self.assertEqual([row for row in undo.raw_rows(after) if row["id"] != "a-sleeves"],
                         [row for row in undo.raw_rows(before) if row["id"] != "a-sleeves"])

    def test_candidate_settling_cannot_rewrite_other_rows_sources_or_image_metadata(self):
        prepare = changes.prepare
        for mode in ("other-row", "stock", "image"):
            def corrupt(before, after, *args, **kwargs):
                settled = prepare(before, after, *args, **kwargs)
                if mode == "image":
                    return settled.with_image("a-sleeves.jpg", b"Unexpected replacement bytes")
                if mode == "stock":
                    return settled.with_collection("home", [])
                rows = [row.as_dict() for row in settled.accessories.rows]
                rows[-1]["notes"] = "Unexpected hidden row rewrite"
                return settled.with_accessories(rows)
            with self.subTest(mode=mode), mock.patch.object(changes, "prepare", side_effect=corrupt), self.assertRaises(undo.UndoConflict):
                self.review()

    def test_actual_receipt_requires_one_fresh_exact_inverse_audit_row_and_full_result(self):
        plan, after = self.review()
        result = self.saved(plan, after)
        self.assertEqual(set(result), {"review", "restored", "sha256", "revision"})
        self.assertEqual(result["restored"], plan["restored"])
        self.assertEqual((result["sha256"], result["revision"]), (plan["sha256"], str(fixture.NEW_ROW_ID)))
        for mode in ("missing", "mixed", "table", "op", "key", "before", "after", "old-id", "boolean-id"):
            rows = fixture.actual_source(plan)
            if mode == "missing":
                rows = []
            elif mode == "mixed":
                rows.append({"id": fixture.NEW_ROW_ID + 1, "table": "accessory_image", "op": "UPDATE"})
            elif mode in ("table", "op", "key"):
                rows[0][mode] = {"table": "accessory_image", "op": "INSERT", "key": {"id": "another"}}[mode]
            elif mode in ("before", "after"):
                rows[0][mode]["notes"] += " Unexpected"
            else:
                rows[0]["id"] = fixture.ROW_ID if mode == "old-id" else True
            with self.subTest(mode=mode), self.assertRaises(undo.UndoConflict):
                self.saved(plan, after, rows)
        self.assertEqual(self.store.snapshot.accessories.rows[0].as_dict(), self.source()["after"])

    def test_saved_scope_or_images_cannot_drift_and_failed_verification_does_not_publish(self):
        before = self.store.snapshot
        plan, after = self.review()
        variants = [after.with_image("a-sleeves.jpg", b"Replaced"), after.with_collection("home", [])]
        for target in ("a-sleeves", "c-hidden"):
            rows = [row.as_dict() for row in after.accessories.rows]
            next(row for row in rows if row["id"] == target)["notes"] = "Wrong saved note"
            variants.append(after.with_accessories(rows))
        for changed in variants:
            with self.subTest(after=changed), self.assertRaises(undo.UndoConflict):
                self.saved(plan, changed)
            self.assertIs(self.store.snapshot, before)

    def test_trusted_operation_rechecks_bound_expect_and_verifies_actual_result(self):
        plan, _ = self.review()
        operation = undo.MetadataRestore(fixture.CHANGE_ID, fixture.OWNERS, plan["expect"])
        with self.assertRaises(inventory.Invalid):
            operation.verify(self.store.snapshot, self.store.snapshot, [])
        after, summary = operation.run(self.store.snapshot)
        self.assertEqual((summary.counts["undo"], summary.extra["undo_of"]), (1, fixture.CHANGE_ID))
        self.assertEqual(set(summary.changed), {paths.ACCESSORIES})
        self.assertEqual(operation.verify(self.store.snapshot, after, fixture.actual_source(operation.plan))["restored"], plan["restored"])
        rows = [row.as_dict() for row in self.store.snapshot.accessories.rows]
        rows[1]["notes"] = "Changed shared row"
        self.store.snapshot = self.store.snapshot.with_accessories(rows)
        with self.assertRaises(undo.UndoConflict):
            undo.MetadataRestore(fixture.CHANGE_ID, fixture.OWNERS, plan["expect"]).run(self.store.snapshot)
