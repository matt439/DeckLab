"""Complete multi-category accessory corrections over synthetic audited stock."""
import copy
from dataclasses import replace
import itertools
import unittest
from unittest import mock

from decklab.lib import accessory_fetch, inventory, profiles
from decklab.lib.inventory import accessory_undo as undo, changes, files, model, rules
from decklab.tests import accessory_undo_support as support, household_config

KINDS = ("sleeves", "deck_box", "playmat")
CATEGORY_SETS = (("owner", "kind"), ("owner", "quantity"), ("kind", "quantity"), ("owner", "kind", "quantity"))
PRODUCT = b"deck,section,name,quantity,finish,set,collector_number\nFixture,deck,Forest,60,nonfoil,fdn,272\n"


class AccessoryRecordUndoTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(mock.patch.object(profiles, "read", return_value=copy.deepcopy(household_config.PROFILES)))
        self.store = support.AuditAccessoryInventory()
        self.addCleanup(inventory.use(self.store))
        self.seed()

    def seed(self, categories=("owner", "kind", "quantity"), *, current_kind="sleeves", historical_kind="deck_box",
             current_owner="shared", historical_owner="matt", zero=False, mixed=False):
        new = support.row(kind=current_kind, owner=current_owner if "owner" in categories else "matt",
                          quantity="1" if zero and "quantity" in categories else "0" if zero else "100",
                          capacity="100" if current_kind == "deck_box" else "")
        old = dict(new)
        if "owner" in categories:
            old["owner"] = historical_owner
        if "kind" in categories:
            old.update(kind=historical_kind, capacity="100" if historical_kind == "deck_box" else "")
        if "quantity" in categories:
            old["quantity"] = "0" if zero else "40"
        if mixed:
            old.update(name="Historical <b>literal</b> name", notes="Historical fixture note", link="https://example.com/former")
            if old["kind"] == "deck_box":
                old["capacity"] = "60"
        rows = [new, support.row(id="b-sleeves", owner="shared", image="", crop=""),
                support.row(id="c-box", owner="shared", kind="deck_box", quantity="2", capacity="100", image="", crop=""),
                support.row(id="d-playmat", kind="playmat", quantity="1", image="", crop=""),
                support.row(id="z-hidden", owner="user1", image="", crop="")]
        snapshot = support.build_snapshot(rows)
        deck = snapshot.deck("casual/fixture")
        self.store.snapshot = snapshot.with_deck(replace(deck, text=deck.text.replace("- **Sleeves:** a-sleeves\n", "")))
        self.store.audit = {support.CHANGE_ID: [{"id": support.ROW_ID, "table": "accessory", "op": "UPDATE",
                            "key": {"id": new["id"]}, "before": old, "after": new}]}
        self.store.latest = support.ROW_ID
        return new, old

    def source(self):
        return self.store.audit[support.CHANGE_ID][0]

    def review(self, owners=support.OWNERS):
        return undo.review(support.CHANGE_ID, owners, self.store.snapshot, self.store)

    def deck(self, status="built", headers=""):
        stored = self.store.snapshot.deck("casual/fixture")
        text = ("# Synthetic holder\n\n- **Format:** Casual 60-card, 1v1\n- **Played by:** user\n"
                f"- **Status:** {status}\n- **Built version:** target\n{headers}\n## Decklist\n\n```\n60 Forest\n```\n")
        self.store.snapshot = self.store.snapshot.with_deck(replace(stored, text=text))

    def test_four_category_sets_owner_directions_kind_pairs_and_zero_counts_restore_whole_sorted_records(self):
        for categories in CATEGORY_SETS:
            pairs = itertools.permutations(KINDS, 2) if "kind" in categories else ((kind, kind) for kind in KINDS)
            for current_kind, historical_kind in pairs:
                owners = (("shared", "matt"), ("matt", "shared")) if "owner" in categories else (("matt", "matt"),)
                for current_owner, historical_owner in owners:
                    for zero in (False, True):
                        new, old = self.seed(categories, current_kind=current_kind, historical_kind=historical_kind,
                            current_owner=current_owner, historical_owner=historical_owner, zero=zero)
                        before, original = self.store.snapshot, copy.deepcopy(self.store.audit)
                        with self.subTest(categories=categories, kinds=(current_kind, historical_kind), owner=current_owner, zero=zero):
                            plan, after = self.review()
                            self.assertEqual(undo.update_action(old, new), "accessory_record_update")
                            self.assertEqual(plan["action"], "accessory_record_update")
                            self.assertIs(plan["record_confirmation_required"], True)
                            self.assertEqual(plan["current"], undo.stock_meta(new))
                            self.assertEqual(plan["restored"], undo.stock_meta(old))
                            self.assertEqual(len(plan["restored"]), 11)
                            changed = [field for field in ("owner", "kind", "quantity", *undo.FIELDS) if old[field] != new[field]]
                            self.assertEqual(plan["fields"], [{"field": field, "before": new[field], "after": old[field]} for field in changed])
                            expected = sorted([old if row["id"] == "a-sleeves" else row for row in undo.raw_rows(before)], key=rules.accessory_sort_key)
                            self.assertEqual(undo.raw_rows(after), expected)
                            self.assertEqual({row["id"]: row for row in expected if row["id"] != "a-sleeves"},
                                             {row["id"]: row for row in undo.raw_rows(before) if row["id"] != "a-sleeves"})
                            if "kind" in categories:
                                self.assertNotEqual([row["id"] for row in undo.raw_rows(before)], [row["id"] for row in expected])
                            self.assertEqual(after.replace(accessories=before.accessories), before)
                            self.assertEqual(undo.verify_saved(before, after, plan, support.actual_source(plan))["restored"], undo.stock_meta(old))
                            self.assertEqual((self.store.snapshot, self.store.audit), (before, original))

    def test_mixed_recorded_details_keep_the_current_crop_photo_and_all_non_accessory_data(self):
        new, old = self.seed(mixed=True)
        before = self.store.snapshot
        with mock.patch.object(accessory_fetch, "fetch", side_effect=AssertionError("No URL fetch")), \
                mock.patch.object(inventory, "image", side_effect=AssertionError("No image bytes")):
            plan, after = self.review()
        self.assertEqual([field["field"] for field in plan["fields"]], ["owner", "kind", "quantity", "name", "notes", "link", "capacity"])
        self.assertEqual((new["image"], new["crop"]), (old["image"], old["crop"]))
        self.assertEqual(after.accessory_images, before.accessory_images)
        self.assertEqual(after.decks, before.decks)
        self.assertFalse(any(flag in plan for flag in ("reason_required", "confirmation_required", "stock_confirmation_required",
                                                      "owner_confirmation_required", "kind_confirmation_required")))

    def test_record_action_cardinality_cannot_replace_zero_or_one_category_protocols(self):
        for categories, action in (((), "accessory_update"), (("quantity",), "accessory_stock_update"),
                                   (("owner",), "accessory_owner_update"), (("kind",), "accessory_kind_update")):
            self.seed(categories, mixed=True)
            plan, _ = self.review()
            with self.subTest(categories=categories):
                self.assertEqual(undo.update_action(self.source()["before"], self.source()["after"]), action)
                self.assertEqual(plan["action"], action)
                self.assertNotIn("record_confirmation_required", plan)
                operation = undo.MetadataRestore(support.CHANGE_ID, support.OWNERS, plan["expect"], store=self.store, confirm_record=True)
                with self.assertRaises(inventory.Invalid):
                    operation.run(self.store.snapshot)

    def test_complete_source_and_both_writable_owners_precede_private_schema_or_category_validation(self):
        for mode in ("hidden", "owner_move", "mixed", "duplicate"):
            self.seed()
            source = self.source()
            if mode == "mixed":
                self.store.audit[support.CHANGE_ID].append({"table": "accessory_image", "op": "UPDATE"})
            elif mode == "duplicate":
                self.store.audit[support.CHANGE_ID].append(copy.deepcopy(source))
            else:
                source["before"].update(owner="user1", name="Private fixture", kind=object())
                if mode == "hidden":
                    source["after"]["owner"] = "user1"
            with self.subTest(mode=mode), mock.patch.object(undo, "raw_row", side_effect=AssertionError("No private proof")), \
                    self.assertRaises(undo.UndoMissing):
                self.review()

    def test_script_still_requires_exact_shared_configured_home_owner_pair(self):
        for current, historical in (("matt", "user1"), ("shared", "user2"), ("user2", "shared"),
                                    ("shared", "orphan"), ("orphan", "shared")):
            self.seed(current_owner=current, historical_owner=historical)
            with self.subTest(current=current, historical=historical), self.assertRaises(undo.UndoUnsupported):
                self.review(None)
        self.seed(current_owner="shared", historical_owner="user1")
        remaining = [profile for profile in household_config.PROFILES if profile["id"] != "user1"]
        with mock.patch.object(profiles, "read", return_value=remaining), self.assertRaises(undo.UndoUnsupported):
            self.review(None)

    def test_source_cells_are_canonical_and_identity_image_and_crop_remain_immutable(self):
        for side in ("before", "after"):
            for field, value in (("quantity", "01"), ("quantity", 1), ("quantity", "10000"), ("kind", "Deck_Box"),
                                 ("owner", " shared "), ("capacity", "01")):
                self.seed()
                self.source()[side][field] = value
                with self.subTest(side=side, field=field, value=value), self.assertRaises((undo.UndoMissing, undo.UndoUnsupported)):
                    self.review(None)
        for field, value in (("id", "different-id"), ("image", "a-sleeves.png"), ("crop", "")):
            self.seed()
            self.source()["before"][field] = value
            with self.subTest(field=field), self.assertRaises(undo.UndoUnsupported):
                self.review()

    def test_compound_quantity_corrections_require_strict_unused_proof_even_without_kind_change(self):
        for categories in CATEGORY_SETS:
            for status in ("idea", "building", "built"):
                for field in ("Sleeves", "Deck box"):
                    self.seed(categories)
                    self.deck(status, f"- **{field}:** \ta-sleeves \t\n")
                    with self.subTest(categories=categories, status=status, field=field), self.assertRaises(undo.UndoConflict):
                        self.review()
        for headers in ("- **Sleeves:** b-sleeves\n- **sleeves:** \n", "- **Sleeves:** red\n"):
            self.seed(("owner", "quantity"))
            self.deck("idea", headers)
            with self.subTest(headers=headers), self.assertRaises(undo.UndoConflict):
                self.review()

    def test_product_and_unknown_home_holder_records_refuse_without_private_details(self):
        for status, intact in (("owned", "yes"), ("owned", "no"), ("cancelled", "")):
            self.seed()
            raw = dict.fromkeys(rules.STATUS_FIELDS, "")
            raw.update(file="fixture.csv", status=status, intact=intact, deck_box="a-sleeves")
            self.store.snapshot = self.store.snapshot.replace(products=(files._product("fixture", PRODUCT),),
                status=files.status_sheet(rules.csv_bytes([raw], rules.STATUS_FIELDS)))
            with self.subTest(status=status), self.assertRaises(undo.UndoConflict) as caught:
                self.review()
            self.assertNotIn("fixture.csv", str(caught.exception))
        self.seed()
        deck = self.store.snapshot.deck("casual/fixture")
        self.store.snapshot = self.store.snapshot.replace(decks={deck.id: replace(deck, text=None, error="Private path")})
        with self.assertRaises(undo.UndoConflict):
            self.review()

    def test_locked_apply_rechecks_target_use_and_preserves_an_unrelated_known_kit_edit(self):
        plan, _ = self.review()
        self.deck(headers="- **Sleeves:** a-sleeves\n")
        operation = undo.MetadataRestore(support.CHANGE_ID, support.OWNERS, plan["expect"], store=self.store, confirm_record=True)
        with self.assertRaises(undo.UndoConflict):
            operation.run(self.store.snapshot)
        self.seed()
        plan, _ = self.review()
        self.deck(headers="- **Sleeves:** b-sleeves\n- **Deck box:** c-box\n")
        before = self.store.snapshot
        self.assertEqual(self.review()[0]["expect"], plan["expect"])
        operation = undo.MetadataRestore(support.CHANGE_ID, support.OWNERS, plan["expect"], store=self.store, confirm_record=True)
        after, _ = operation.run(changes.detach(before))
        self.assertEqual(after.decks, before.decks)
        self.assertEqual(operation.verify(before, after, support.actual_source(operation.plan))["restored"], plan["restored"])

    def test_entire_record_consent_is_required_and_any_old_action_control_presence_refuses(self):
        plan, _ = self.review()
        options = [{}, {"confirm_record": False}, {"confirm_record": None}, {"confirm_record": 1}, {"confirm_record": "true"}]
        options.extend({"confirm_record": True, flag: None} for flag in ("reason", "confirm_restore", "confirm_stock", "confirm_owner", "confirm_kind"))
        for values in options:
            operation = undo.MetadataRestore(support.CHANGE_ID, support.OWNERS, plan["expect"], store=self.store, **values)
            with self.subTest(options=values), self.assertRaises(inventory.Invalid):
                operation.run(self.store.snapshot)

    def test_actual_all_category_audit_and_full_survivor_photo_proofs_must_match_before_acknowledgement(self):
        self.seed(zero=True)
        plan, after = self.review()
        before = self.store.snapshot
        for side, field, value in (("before", "owner", "matt"), ("after", "owner", "shared"),
                                   ("after", "kind", "playmat"), ("after", "quantity", "1"), ("after", "capacity", "40")):
            rows = support.actual_source(plan)
            rows[0][side][field] = value
            with self.subTest(side=side, field=field), self.assertRaises(undo.UndoConflict):
                undo.verify_saved(before, after, plan, rows)
        for rows in ([], support.actual_source(plan) * 2):
            with self.assertRaises(undo.UndoConflict):
                undo.verify_saved(before, after, plan, rows)
        for changed in (after.with_image("a-sleeves.jpg", b"Unexpected fixture bytes"),
                        after.with_accessories([{**row, "notes": "Unexpected survivor"} if row["id"] == "c-box" else row
                                                for row in undo.raw_rows(after)])):
            with self.assertRaises(undo.UndoConflict):
                undo.verify_saved(before, changed, plan, support.actual_source(plan))

    def test_hidden_scope_edits_and_private_member_decks_preserve_review_but_visible_edits_and_aba_do_not(self):
        plan, _ = self.review()
        private = model.Deck("user2", "casual", "private", None, "Private unreadable fixture")
        self.store.snapshot = self.store.snapshot.replace(decks={**self.store.snapshot.decks, private.id: private})
        self.store.snapshot = self.store.snapshot.with_accessories([
            {**row, "notes": "Private correction"} if row["id"] == "z-hidden" else row for row in undo.raw_rows(self.store.snapshot)])
        scoped, after = self.review()
        self.assertEqual(scoped["expect"], plan["expect"])
        self.assertEqual(after.deck(private.id), private)
        self.store.snapshot = self.store.snapshot.with_accessories([
            {**row, "notes": "Shared correction"} if row["id"] == "b-sleeves" else row for row in undo.raw_rows(self.store.snapshot)])
        self.assertNotEqual(self.review()[0]["expect"], plan["expect"])
        self.store.latest += 1
        with self.assertRaises(undo.UndoConflict):
            self.review()
