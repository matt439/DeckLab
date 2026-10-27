"""Unused accessory owner recovery over synthetic snapshots and complete audit rows."""
import copy
from dataclasses import replace
import unittest
from unittest import mock

from decklab.lib import accessories, inventory, profiles
from decklab.lib.inventory import accessory_undo as undo, changes, files, model, rules
from decklab.tests import accessory_undo_support as support, household_config

PRODUCT = b"deck,section,name,quantity,finish,set,collector_number\nFixture,deck,Forest,60,nonfoil,fdn,272\n"


class AccessoryOwnerUndoTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(mock.patch.object(profiles, "read", return_value=copy.deepcopy(household_config.PROFILES)))
        self.store = support.AuditAccessoryInventory()
        self.addCleanup(inventory.use(self.store))
        self.seed()

    def seed(self, current="shared", historical="matt", *, kind="sleeves", quantity="100", mixed=False):
        new = support.row(owner=current, kind=kind, quantity=quantity, capacity="100" if kind == "deck_box" else "")
        old = {**new, "owner": historical}
        if mixed:
            old.update(name="Historical <b>literal</b> name", notes="Historical fixture note", link="https://example.com/former")
            if kind == "deck_box":
                old["capacity"] = "60"
        rows = [new if row.accessory_id == new["id"] else row.as_dict() for row in support.build_snapshot().accessories.rows]
        snapshot = support.build_snapshot(rows)
        deck = snapshot.deck("casual/fixture")
        snapshot = snapshot.with_deck(replace(deck, text=deck.text.replace("- **Sleeves:** a-sleeves\n", "")))
        self.store.snapshot = snapshot
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

    def test_both_shared_home_directions_all_kinds_and_zero_counts_have_exact_owner_review(self):
        for profile in ("matt", "user1"):
            owners = frozenset({profile, "shared"})
            for current, historical in (("shared", profile), (profile, "shared")):
                for kind in ("sleeves", "deck_box", "playmat"):
                    for quantity in ("0", "100"):
                        new, old = self.seed(current, historical, kind=kind, quantity=quantity)
                        before, source = self.store.snapshot, copy.deepcopy(self.store.audit)
                        with self.subTest(profile=profile, current=current, kind=kind, quantity=quantity):
                            plan, after = self.review(owners)
                            self.assertEqual(plan["action"], "accessory_owner_update")
                            self.assertIs(plan["owner_confirmation_required"], True)
                            self.assertEqual(plan["current"], undo.stock_meta(new))
                            self.assertEqual(plan["restored"], undo.stock_meta(old))
                            self.assertEqual(len(plan["restored"]), 11)
                            self.assertEqual(plan["fields"], [{"field": "owner", "before": current, "after": historical}])
                            self.assertNotIn("stock_confirmation_required", plan)
                            self.assertNotIn("reason_required", plan)
                            self.assertNotIn("confirmation_required", plan)
                            receipt = undo.verify_saved(before, after, plan, support.actual_source(plan))
                            self.assertEqual(receipt["restored"], undo.stock_meta(old))
                            self.assertEqual(after.replace(accessories=before.accessories), before)
                            self.assertEqual((self.store.snapshot, self.store.audit), (before, source))

    def test_mixed_metadata_and_capacity_keep_quantity_photos_and_other_owners_exactly(self):
        self.seed(kind="deck_box", mixed=True)
        before = self.store.snapshot
        plan, after = self.review()
        self.assertEqual([field["field"] for field in plan["fields"]], ["owner", "name", "notes", "link", "capacity"])
        self.assertEqual(next(row for row in undo.raw_rows(after) if row["id"] == "a-sleeves"), self.source()["before"])
        self.assertEqual(plan["current"]["quantity"], plan["restored"]["quantity"])
        self.assertEqual(after.accessory_images, before.accessory_images)
        self.assertEqual(after.replace(accessories=before.accessories), before)

    def test_unnamed_script_still_requires_one_configured_home_owner_and_shared(self):
        for current, historical in (("matt", "user1"), ("shared", "user2"), ("user2", "shared"),
                                    ("shared", "orphan"), ("orphan", "shared")):
            self.seed(current, historical)
            with self.subTest(current=current, historical=historical), self.assertRaises(undo.UndoUnsupported):
                self.review(None)
        self.seed("shared", "user1")
        remaining = [profile for profile in household_config.PROFILES if profile["id"] != "user1"]
        with mock.patch.object(profiles, "read", return_value=remaining), self.assertRaises(undo.UndoUnsupported):
            self.review(None)
        self.seed("shared", "matt")
        self.assertEqual(self.review(None)[0]["action"], "accessory_owner_update")

    def test_owner_scope_and_complete_source_precede_private_row_validation(self):
        for mode in ("hidden", "owner_move", "mixed", "duplicate"):
            self.seed()
            source = self.source()
            if mode == "mixed":
                self.store.audit[support.CHANGE_ID].append({"table": "accessory_image", "op": "UPDATE"})
            elif mode == "duplicate":
                self.store.audit[support.CHANGE_ID].append(copy.deepcopy(source))
            else:
                source["before"].update(owner="user1", name="Private fixture label", quantity=object())
                if mode == "hidden":
                    source["after"]["owner"] = "user1"
            with self.subTest(mode=mode), mock.patch.object(undo, "raw_row", side_effect=AssertionError("No raw proof before scope")), \
                    self.assertRaises(undo.UndoMissing):
                self.review()

    def test_owner_change_cannot_also_change_quantity_kind_identity_image_or_crop(self):
        for field, value in (("quantity", "99"), ("kind", "playmat"), ("id", "other-id"),
                             ("image", "a-sleeves.png"), ("crop", "")):
            self.seed()
            self.source()["before"][field] = value
            with self.subTest(field=field), self.assertRaises(undo.UndoUnsupported):
                self.review()

    def test_target_references_block_even_wrong_kind_unbuilt_strays_and_duplicate_headers(self):
        for status in ("idea", "building", "built"):
            for field in ("Sleeves", "Deck box"):
                self.seed()
                self.deck(status, f"- **{field}:** \ta-sleeves \t\n")
                with self.subTest(status=status, field=field), self.assertRaises(undo.UndoConflict):
                    self.review()
        for headers in ("- **Sleeves:** b-shared\n- **sleeves:** \n", "- **Sleeves:** red\n"):
            self.seed()
            self.deck("idea", headers)
            with self.subTest(headers=headers), self.assertRaises(undo.UndoConflict):
                self.review()

    def test_product_references_and_unreadable_home_holder_evidence_refuse_generically(self):
        for status, intact in (("owned", "yes"), ("owned", "no"), ("ordered", "no"), ("cancelled", "")):
            self.seed()
            raw = dict.fromkeys(rules.STATUS_FIELDS, "")
            raw.update(file="fixture.csv", status=status, intact=intact, deck_box="a-sleeves")
            self.store.snapshot = self.store.snapshot.replace(products=(files._product("fixture", PRODUCT),),
                status=files.status_sheet(rules.csv_bytes([raw], rules.STATUS_FIELDS)))
            with self.subTest(status=status, intact=intact), self.assertRaises(undo.UndoConflict) as caught:
                self.review()
            self.assertNotIn("fixture.csv", str(caught.exception))
        self.seed()
        stored = self.store.snapshot.deck("casual/fixture")
        for changed in (replace(stored, text=None, error="Private path"),
                        replace(stored, text=stored.text.replace("- **Status:** built\n", ""))):
            self.store.snapshot = self.store.snapshot.replace(decks={stored.id: changed})
            with self.assertRaises(undo.UndoConflict):
                self.review()

    def test_preview_does_not_authorize_later_target_use_but_unrelated_known_kit_is_preserved(self):
        plan, _ = self.review()
        self.deck(headers="- **Sleeves:** a-sleeves\n")
        op = undo.MetadataRestore(support.CHANGE_ID, support.OWNERS, plan["expect"], store=self.store, confirm_owner=True)
        with self.assertRaises(undo.UndoConflict):
            op.run(self.store.snapshot)
        self.seed()
        plan, _ = self.review()
        self.deck(headers="- **Sleeves:** b-shared\n")
        before = self.store.snapshot
        self.assertEqual(self.review()[0]["expect"], plan["expect"])
        op = undo.MetadataRestore(support.CHANGE_ID, support.OWNERS, plan["expect"], store=self.store, confirm_owner=True)
        after, _ = op.run(changes.detach(before))
        self.assertEqual(after.decks, before.decks)
        self.assertEqual(op.verify(before, after, support.actual_source(op.plan))["restored"]["owner"], "matt")

    def test_exact_owner_consent_is_required_and_other_action_controls_are_rejected(self):
        plan, _ = self.review()
        for options in ({}, {"confirm_owner": False}, {"confirm_owner": None}, {"confirm_owner": 1},
                        {"confirm_owner": "true"}, {"confirm_owner": True, "reason": None},
                        {"confirm_owner": True, "confirm_restore": None}, {"confirm_owner": True, "confirm_stock": None}):
            op = undo.MetadataRestore(support.CHANGE_ID, support.OWNERS, plan["expect"], store=self.store, **options)
            with self.subTest(options=options), self.assertRaises(inventory.Invalid):
                op.run(self.store.snapshot)
        self.store.seed()
        self.deck()
        plain, _ = self.review()
        for value in (True, False, None):
            op = undo.MetadataRestore(support.CHANGE_ID, support.OWNERS, plain["expect"], store=self.store, confirm_owner=value)
            with self.subTest(value=value), self.assertRaises(inventory.Invalid):
                op.run(self.store.snapshot)

    def test_actual_owner_receipts_require_exact_opposite_audit_and_unchanged_survivors_photos(self):
        plan, after = self.review()
        before = self.store.snapshot
        for side, owner in (("before", "matt"), ("after", "shared")):
            rows = support.actual_source(plan)
            rows[0][side]["owner"] = owner
            with self.subTest(side=side), self.assertRaises(undo.UndoConflict):
                undo.verify_saved(before, after, plan, rows)
        for rows in ([], support.actual_source(plan) * 2):
            with self.assertRaises(undo.UndoConflict):
                undo.verify_saved(before, after, plan, rows)
        for changed in (after.with_image("a-sleeves.jpg", b"Unexpected fixture picture"),
                        after.with_accessories([{**row, "owner": "matt"} if row["id"] == "b-shared" else row
                                                for row in undo.raw_rows(after)])):
            with self.assertRaises(undo.UndoConflict):
                undo.verify_saved(before, changed, plan, support.actual_source(plan))

    def test_scoped_list_staleness_latest_touch_and_out_of_home_deck_preservation(self):
        plan, _ = self.review()
        private = model.Deck("user2", "casual", "private", None, "Private unreadable fixture")
        self.store.snapshot = self.store.snapshot.replace(decks={**self.store.snapshot.decks, private.id: private})
        self.store.snapshot = self.store.snapshot.with_accessories([
            {**row, "notes": "Private correction"} if row["id"] == "c-hidden" else row for row in undo.raw_rows(self.store.snapshot)])
        updated, after = self.review()
        self.assertEqual(updated["expect"], plan["expect"])
        self.assertEqual(after.deck(private.id), private)
        self.store.snapshot = self.store.snapshot.with_accessories([
            {**row, "notes": "Shared correction"} if row["id"] == "b-shared" else row for row in undo.raw_rows(self.store.snapshot)])
        self.assertNotEqual(self.review()[0]["expect"], plan["expect"])
        self.store.latest += 1
        with self.assertRaises(undo.UndoConflict):
            self.review()
