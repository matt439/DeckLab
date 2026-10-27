"""Exact photo-free accessory DELETE inverses over synthetic in-memory evidence."""
import copy
from dataclasses import replace
import unittest
from unittest import mock

from decklab.lib import accessories, accessory_fetch, cards, inventory, profiles
from decklab.lib.inventory import accessory_undo as undo, changes, model, paths, rules
from decklab.lib.inventory.undo import UndoConflict, UndoMissing, UndoUnsupported
from decklab.tests import accessory_undo_support as fixture, household_config


class AccessoryDeleteUndoTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(mock.patch.object(profiles, "read", return_value=copy.deepcopy(household_config.PROFILES)))
        self.store = fixture.AuditAccessoryInventory()
        self.addCleanup(inventory.use(self.store))
        self.seed()

    def seed(self, **kwargs):
        return fixture.seed_delete(self.store, **kwargs)

    def source(self):
        return self.store.audit[fixture.CHANGE_ID][0]

    def review(self, owners=fixture.OWNERS):
        return undo.review(fixture.CHANGE_ID, owners, self.store.snapshot, self.store)

    def operation(self, plan, **extra):
        return undo.MetadataRestore(fixture.CHANGE_ID, fixture.OWNERS, plan["expect"], store=self.store, **extra)

    @staticmethod
    def actual_source(plan, id=fixture.NEW_ROW_ID):
        return [{"id": id, "table": "accessory", "op": "INSERT", "key": copy.deepcopy(plan["source"]["key"]),
                 "before": None, "after": copy.deepcopy(plan["source"]["before"])}]

    def saved(self, plan, after, rows=None):
        return undo.verify_saved(self.store.snapshot, after, plan, self.actual_source(plan) if rows is None else rows)

    def test_preview_restores_full_thirteen_text_cells_in_canonical_order_without_mutation(self):
        before, audit = self.store.snapshot, copy.deepcopy(self.store.audit)
        plan, after = self.review()
        self.assertEqual((plan["kind"], plan["action"], plan["label"]), ("accessory", "accessory_add", self.source()["before"]["name"]))
        self.assertIsNone(plan["current"])
        self.assertEqual(plan["restored"], self.source()["before"])
        self.assertEqual(set(plan["restored"]), set(rules.ACCESSORY_FIELDS))
        self.assertTrue(all(isinstance(value, str) for value in plan["restored"].values()))
        self.assertIs(plan["confirmation_required"], True)
        self.assertNotIn("fields", plan)
        expected = sorted([*undo.raw_rows(before), self.source()["before"]], key=rules.accessory_sort_key)
        self.assertEqual(undo.raw_rows(after), expected)
        self.assertEqual(plan["raw_after"], expected)
        self.assertEqual((self.store.snapshot, self.store.audit), (before, audit))

    def test_add_requires_exact_confirmation_and_never_takes_a_removal_reason(self):
        plan, _ = self.review()
        before = self.store.snapshot
        for confirm in (None, False, 0, 1, "true", [], {}):
            with self.subTest(confirm=confirm), self.assertRaises(inventory.Invalid):
                self.operation(plan, confirm_restore=confirm).run(before)
        with self.assertRaises(inventory.Invalid):
            self.operation(plan).run(before)
        with self.assertRaises(inventory.Invalid):
            self.operation(plan, confirm_restore=True, reason="Not a removal").run(before)
        operation = self.operation(plan, confirm_restore=True)
        after, summary = operation.run(before)
        self.assertEqual(summary.counts["undo"], 1)
        self.assertEqual(operation.verify(before, after, self.actual_source(plan))["restored"], self.source()["before"])
        self.assertIs(self.store.snapshot, before)

    def test_exact_derived_base_and_reproducible_suffix_ids_use_the_ordinary_add(self):
        historical = self.seed()
        base = historical["id"]
        taken = fixture.row(id=base, owner="user1", image="", crop="", name="Private occupied base")
        for rows, expected in (((), base), ((taken,), base + "-2")):
            target = self.seed(taken=rows)
            self.assertEqual(target["id"], expected)
            from decklab.lib.inventory import ops_accessories
            with self.subTest(id=expected), mock.patch.object(ops_accessories, "add_accessory", wraps=ops_accessories.add_accessory) as ordinary:
                plan, after = self.review()
            self.assertEqual(ordinary.call_count, 1)
            self.assertIsNone(ordinary.call_args.kwargs["image"])
            self.assertEqual(set(ordinary.call_args.kwargs["row"]), set(accessories.ROW_KEYS))
            self.assertNotIn("id", ordinary.call_args.kwargs["row"])
            self.assertEqual(self.saved(plan, after)["restored"]["id"], expected)

    def test_global_owner_and_source_shape_proof_precedes_any_private_label_validation(self):
        own = copy.deepcopy(self.source())
        own_bad = copy.deepcopy(own)
        own_bad["before"]["future"] = "Own unknown column"
        hidden = copy.deepcopy(own)
        hidden["before"].update(owner="user1", name="Private accessory name")
        for rows in ([hidden], [own_bad, hidden], [own, own], [{**own, "table": "accessory_image"}],
                     [{**own, "after": {}}], [{key: value for key, value in own.items() if key != "after"}]):
            self.store.audit[fixture.CHANGE_ID] = rows
            with self.subTest(rows=rows), mock.patch.object(accessories, "validate_row", side_effect=AssertionError("No private validation")), \
                    self.assertRaises(UndoMissing) as caught:
                self.review()
            self.assertNotIn("Private accessory", str(caught.exception))

    def test_hidden_id_collision_or_labels_that_cannot_reproduce_id_refuse_generically(self):
        target = self.seed()
        hidden = fixture.row(id=target["id"], owner="user1", image="", crop="", name="Private collision")
        for mode in ("collision", "renamed", "missing-suffix-base"):
            self.seed()
            if mode == "collision":
                self.store.snapshot = self.store.snapshot.with_accessories([*self.store.snapshot.accessories.rows, hidden])
            elif mode == "renamed":
                self.source()["before"]["name"] = "Renamed historical row"
            else:
                self.source()["before"]["id"] += "-2"
                self.source()["key"]["id"] = self.source()["before"]["id"]
            before = self.store.snapshot
            with self.subTest(mode=mode), self.assertRaises((UndoConflict, UndoUnsupported)) as caught:
                self.review()
            self.assertNotIn("Private collision", str(caught.exception))
            self.assertNotIn(hidden["id"], str(caught.exception))
            self.assertIs(self.store.snapshot, before)

    def test_same_value_aba_and_writable_list_changes_invalidate_bound_review(self):
        plan, _ = self.review()
        rows = [row.as_dict() for row in self.store.snapshot.accessories.rows]
        next(row for row in rows if row["id"] == "c-hidden")["notes"] = "Later private edit"
        self.store.snapshot = self.store.snapshot.with_accessories(rows)
        self.assertEqual(self.review()[0]["expect"], plan["expect"])
        after, _ = self.operation(plan, confirm_restore=True).run(self.store.snapshot)
        self.assertEqual(next(row.as_dict() for row in after.accessories.rows if row.accessory_id == "c-hidden")["notes"], "Later private edit")
        for latest in (None, float(fixture.ROW_ID), fixture.ROW_ID + 1):
            self.store.latest = latest
            with self.subTest(latest=latest), self.assertRaises(UndoConflict):
                self.review()
        self.store.latest = fixture.ROW_ID
        rows = [row.as_dict() for row in self.store.snapshot.accessories.rows]
        rows[1]["notes"] = "Later shared edit"
        self.store.snapshot = self.store.snapshot.with_accessories(rows)
        with self.assertRaises(UndoConflict):
            self.operation(plan, confirm_restore=True).run(self.store.snapshot)

    def test_historical_row_requires_exact_raw_text_validation_without_normalization(self):
        for changed in ({"quantity": 1}, {"quantity": "01"}, {"capacity": None}, {"name": " Padded "},
                        {"notes": "two\nlines"}, {"link": "ftp://example.com/item"}, {"future": "Unknown"}):
            self.seed()
            self.source()["before"].update(changed)
            with self.subTest(changed=changed), self.assertRaises(UndoUnsupported):
                self.review()
        self.seed()
        self.source()["key"] = {"id": self.source()["before"]["id"], "owner": "matt"}
        with self.assertRaises(UndoUnsupported):
            self.review()

    def test_historical_photo_crop_or_any_orphan_for_the_id_cannot_be_reattached(self):
        for mode in ("historical-photo", "historical-crop", "current-orphan"):
            target = self.seed()
            if mode == "historical-photo":
                self.source()["before"]["image"] = target["id"] + ".jpg"
            elif mode == "historical-crop":
                self.source()["before"].update(image=target["id"] + ".jpg", crop="0,0,1,1")
            else:
                self.store.snapshot = self.store.snapshot.with_image(target["id"] + ".png", b"Unattached bytes")
            with self.subTest(mode=mode), self.assertRaises((UndoConflict, UndoUnsupported)):
                self.review()

    def test_dangling_target_kit_and_unresolved_other_kit_prevent_implicit_reattachment(self):
        from decklab.lib.inventory.ops_decks import parsed_deck
        for value in ("target", "legacy"):
            target = self.seed()
            deck = self.store.snapshot.deck("casual/fixture")
            reference = target["id"] if value == "target" else "legacy red"
            text = deck.text.replace("- **Built version:** target\n", f"- **Built version:** target\n- **Sleeves:** {reference}\n")
            self.store.snapshot = self.store.snapshot.with_deck(replace(deck, text=text))
            parsed = parsed_deck(self.store.snapshot.deck(deck.id))
            self.assertIsNotNone(parsed)
            self.assertEqual([field.value for field in parsed.header if field.key.casefold() == "sleeves"], [reference])
            with self.subTest(value=value), self.assertRaises(UndoConflict):
                self.review()

    def test_zero_quantity_and_empty_current_list_restore_only_explicit_recorded_facts(self):
        for quantity in ("0", "1", "100"):
            target = self.seed(only=True, row={"quantity": quantity})
            self.assertEqual(self.store.snapshot.accessories, model.Sheet(paths.ACCESSORIES))
            with self.subTest(quantity=quantity), mock.patch.object(cards, "resolve", side_effect=AssertionError("No card lookup")), \
                    mock.patch.object(accessory_fetch, "fetch", side_effect=AssertionError("No picture fetch")):
                plan, after = self.review()
                result = self.saved(plan, after)
            self.assertEqual(undo.raw_rows(after), [target])
            self.assertEqual(result["restored"], target)
            self.assertEqual(after.accessory_images, self.store.snapshot.accessory_images)
            self.assertEqual(result["sha256"], undo.list_sha([target], fixture.OWNERS))

    def test_actual_receipt_requires_one_exact_new_insert_and_preserves_every_survivor(self):
        before = self.store.snapshot
        plan, after = self.review()
        result = self.saved(plan, after)
        self.assertEqual(set(result), {"review", "restored", "added_id", "sha256", "revision"})
        self.assertEqual(result["restored"], self.source()["before"])
        self.assertEqual(result["added_id"], self.source()["before"]["id"])
        self.assertEqual(result["sha256"], undo.list_sha(undo.raw_rows(after), fixture.OWNERS))
        self.assertEqual(result["revision"], str(fixture.NEW_ROW_ID))
        for mode in ("missing", "mixed", "update", "before", "after", "key", "old-id"):
            rows = self.actual_source(plan)
            if mode == "missing":
                rows = []
            elif mode == "mixed":
                rows.append({"id": fixture.NEW_ROW_ID + 1, "table": "accessory_image", "op": "INSERT"})
            elif mode == "update":
                rows[0]["op"] = "UPDATE"
            elif mode == "before":
                rows[0]["before"] = {}
            elif mode == "after":
                rows[0]["after"]["notes"] += " Changed"
            elif mode == "key":
                rows[0]["key"] = {"id": "another-id"}
            else:
                rows[0]["id"] = fixture.ROW_ID
            with self.subTest(mode=mode), self.assertRaises(UndoConflict):
                self.saved(plan, after, rows)
        rows = [row.as_dict() for row in after.accessories.rows]
        next(row for row in rows if row["id"] == "c-hidden")["notes"] = "Wrong survivor"
        with self.assertRaises(UndoConflict):
            self.saved(plan, after.with_accessories(rows))
        self.assertIs(self.store.snapshot, before)

    def test_candidate_settling_cannot_rewrite_stock_photos_or_normalize_recorded_row(self):
        prepare = changes.prepare
        for mode in ("stock", "photo", "row"):
            def corrupt(before, after, *args, **kwargs):
                settled = prepare(before, after, *args, **kwargs)
                if mode == "stock":
                    return settled.with_collection("home", [])
                if mode == "photo":
                    return settled.with_image("a-sleeves.jpg", b"Changed original bytes")
                rows = [row.as_dict() for row in settled.accessories.rows]
                next(row for row in rows if row["id"] == self.source()["before"]["id"])["notes"] = "Rewritten"
                return settled.with_accessories(rows)
            error = UndoUnsupported if mode == "row" else UndoConflict
            with self.subTest(mode=mode), mock.patch.object(changes, "prepare", side_effect=corrupt), self.assertRaises(error):
                self.review()
