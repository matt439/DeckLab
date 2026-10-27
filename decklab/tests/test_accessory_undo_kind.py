"""Unused accessory kind correction, with synthetic stock and complete audit rows."""
import copy
from dataclasses import replace
import itertools
import unittest
from unittest import mock

from decklab.lib import accessories, accessory_fetch, inventory, profiles
from decklab.lib.inventory import accessory_undo as undo, changes, files, model, rules
from decklab.tests import accessory_undo_support as support, household_config

KINDS = ("sleeves", "deck_box", "playmat")
PRODUCT = b"deck,section,name,quantity,finish,set,collector_number\nFixture,deck,Forest,60,nonfoil,fdn,272\n"


class AccessoryKindUndoTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(mock.patch.object(profiles, "read", return_value=copy.deepcopy(household_config.PROFILES)))
        self.store = support.AuditAccessoryInventory()
        self.addCleanup(inventory.use(self.store))
        self.seed()

    def seed(self, current="sleeves", historical="deck_box", *, quantity="100", owner="matt", mixed=False):
        new = support.row(kind=current, owner=owner, quantity=quantity, capacity="100" if current == "deck_box" else "")
        old = {**new, "kind": historical, "capacity": "100" if historical == "deck_box" else ""}
        if mixed:
            old.update(name="Historical <b>literal</b> name", notes="Historical fixture note", link="https://example.com/former")
            if historical == "deck_box":
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

    def test_all_six_directed_kind_pairs_and_zero_stock_restore_exact_canonically_sorted_rows(self):
        for current, historical in itertools.permutations(KINDS, 2):
            for quantity in ("0", "100"):
                new, old = self.seed(current, historical, quantity=quantity)
                before, source = self.store.snapshot, copy.deepcopy(self.store.audit)
                with self.subTest(current=current, historical=historical, quantity=quantity):
                    plan, after = self.review()
                    self.assertEqual(plan["action"], "accessory_kind_update")
                    self.assertIs(plan["kind_confirmation_required"], True)
                    self.assertEqual(plan["current"], undo.stock_meta(new))
                    self.assertEqual(plan["restored"], undo.stock_meta(old))
                    self.assertEqual(len(plan["restored"]), 11)
                    self.assertEqual([item["field"] for item in plan["fields"]],
                                     ["kind", *(["capacity"] if "deck_box" in (current, historical) else [])])
                    expected = sorted([old if row["id"] == "a-sleeves" else row for row in undo.raw_rows(before)],
                                      key=rules.accessory_sort_key)
                    self.assertEqual(undo.raw_rows(after), expected)
                    self.assertNotEqual([row["id"] for row in undo.raw_rows(before)], [row["id"] for row in expected])
                    self.assertEqual({row["id"]: row for row in expected if row["id"] != "a-sleeves"},
                                     {row["id"]: row for row in undo.raw_rows(before) if row["id"] != "a-sleeves"})
                    receipt = undo.verify_saved(before, after, plan, support.actual_source(plan))
                    self.assertEqual(receipt["restored"], undo.stock_meta(old))
                    self.assertEqual(after.replace(accessories=before.accessories), before)
                    self.assertEqual((self.store.snapshot, self.store.audit), (before, source))

    def test_mixed_details_capacity_and_photograph_are_retained_without_fetching(self):
        new, old = self.seed("playmat", "deck_box", mixed=True)
        before = self.store.snapshot
        with mock.patch.object(accessory_fetch, "fetch", side_effect=AssertionError("No URL fetch")), \
                mock.patch.object(inventory, "image", side_effect=AssertionError("No image bytes")):
            plan, after = self.review()
        self.assertEqual([field["field"] for field in plan["fields"]], ["kind", "name", "notes", "link", "capacity"])
        self.assertEqual((plan["current"]["quantity"], plan["restored"]["quantity"]), ("100", "100"))
        self.assertEqual((new["image"], new["crop"]), (old["image"], old["crop"]))
        self.assertEqual(next(row for row in undo.raw_rows(after) if row["id"] == "a-sleeves"), old)
        self.assertEqual(after.accessory_images, before.accessory_images)
        self.assertEqual(after.decks, before.decks)

    def test_both_raw_kinds_and_box_capacities_must_be_canonical(self):
        for side in ("before", "after"):
            for value in (None, True, "", "Sleeves", " deck_box ", "unknown"):
                self.seed()
                self.source()[side]["kind"] = value
                with self.subTest(side=side, kind=value), self.assertRaises(undo.UndoUnsupported):
                    self.review()
        for value in ("0", "01", "10000", "+40", " 40 ", None, 40):
            self.seed()
            self.source()["before"]["capacity"] = value
            with self.subTest(capacity=value), self.assertRaises(undo.UndoUnsupported):
                self.review()
        self.seed()
        self.source()["after"]["capacity"] = "40"
        with self.assertRaises(undo.UndoUnsupported):
            self.review()

    def test_kind_correction_cannot_also_change_owner_quantity_identity_image_or_crop(self):
        for field, value in (("owner", "shared"), ("quantity", "99"), ("id", "different-id"),
                             ("image", "a-sleeves.png"), ("crop", "")):
            self.seed()
            self.source()["before"][field] = value
            with self.subTest(field=field):
                if field in ("quantity", "owner"):
                    plan, _ = self.review()
                    self.assertEqual(plan["action"], "accessory_record_update")
                    self.assertNotIn("kind_confirmation_required", plan)
                    with self.assertRaises(inventory.Invalid):
                        undo.MetadataRestore(support.CHANGE_ID, support.OWNERS, plan["expect"], store=self.store,
                                             confirm_kind=True).run(self.store.snapshot)
                else:
                    with self.assertRaises(undo.UndoUnsupported):
                        self.review()

    def test_complete_source_and_both_writable_owners_precede_private_validation(self):
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
            with self.subTest(mode=mode), mock.patch.object(undo, "raw_row", side_effect=AssertionError("No private validation")), \
                    self.assertRaises(undo.UndoMissing):
                self.review()

    def test_any_target_reference_including_wrong_kind_unbuilt_or_uncertain_holder_refuses(self):
        for status in ("idea", "building", "built"):
            for field in ("Sleeves", "Deck box"):
                self.seed()
                self.deck(status, f"- **{field}:** \ta-sleeves \t\n")
                with self.subTest(status=status, field=field), self.assertRaises(undo.UndoConflict):
                    self.review()
        for headers in ("- **Sleeves:** b-sleeves\n- **sleeves:** \n", "- **Sleeves:** red\n"):
            self.seed()
            self.deck("idea", headers)
            with self.subTest(headers=headers), self.assertRaises(undo.UndoConflict):
                self.review()
        self.seed()
        deck = self.store.snapshot.deck("casual/fixture")
        self.store.snapshot = self.store.snapshot.replace(decks={deck.id: replace(deck, text=None, error="Private path")})
        with self.assertRaises(undo.UndoConflict):
            self.review()

    def test_product_and_stray_references_are_not_reinterpreted_as_an_unused_kind(self):
        for status, intact in (("owned", "yes"), ("owned", "no"), ("ordered", "no"), ("cancelled", "")):
            self.seed()
            raw = dict.fromkeys(rules.STATUS_FIELDS, "")
            raw.update(file="fixture.csv", status=status, intact=intact, deck_box="a-sleeves")
            self.store.snapshot = self.store.snapshot.replace(products=(files._product("fixture", PRODUCT),),
                status=files.status_sheet(rules.csv_bytes([raw], rules.STATUS_FIELDS)))
            with self.subTest(status=status, intact=intact), self.assertRaises(undo.UndoConflict) as caught:
                self.review()
            self.assertNotIn("fixture.csv", str(caught.exception))

    def test_locked_kind_save_rechecks_new_target_use_and_preserves_unrelated_known_kit(self):
        plan, _ = self.review()
        self.deck(headers="- **Sleeves:** a-sleeves\n")
        operation = undo.MetadataRestore(support.CHANGE_ID, support.OWNERS, plan["expect"], store=self.store, confirm_kind=True)
        with self.assertRaises(undo.UndoConflict):
            operation.run(self.store.snapshot)
        self.seed()
        plan, _ = self.review()
        self.deck(headers="- **Sleeves:** b-sleeves\n- **Deck box:** c-box\n")
        before = self.store.snapshot
        self.assertEqual(self.review()[0]["expect"], plan["expect"])
        operation = undo.MetadataRestore(support.CHANGE_ID, support.OWNERS, plan["expect"], store=self.store, confirm_kind=True)
        after, _ = operation.run(changes.detach(before))
        self.assertEqual(after.decks, before.decks)
        self.assertEqual(operation.verify(before, after, support.actual_source(operation.plan))["restored"]["kind"], "deck_box")

    def test_exact_kind_confirmation_is_required_and_other_action_controls_refuse(self):
        plan, _ = self.review()
        for options in ({}, {"confirm_kind": False}, {"confirm_kind": None}, {"confirm_kind": 1},
                        {"confirm_kind": "true"}, {"confirm_kind": True, "reason": None},
                        {"confirm_kind": True, "confirm_restore": None}, {"confirm_kind": True, "confirm_stock": None},
                        {"confirm_kind": True, "confirm_owner": None}):
            operation = undo.MetadataRestore(support.CHANGE_ID, support.OWNERS, plan["expect"], store=self.store, **options)
            with self.subTest(options=options), self.assertRaises(inventory.Invalid):
                operation.run(self.store.snapshot)
        self.store.seed()
        self.deck()
        plain, _ = self.review()
        for value in (True, False, None):
            operation = undo.MetadataRestore(support.CHANGE_ID, support.OWNERS, plain["expect"], store=self.store, confirm_kind=value)
            with self.subTest(value=value), self.assertRaises(inventory.Invalid):
                operation.run(self.store.snapshot)

    def test_actual_kind_and_zero_quantity_receipts_require_the_exact_opposite_audit_and_snapshot(self):
        self.seed(quantity="0")
        plan, after = self.review()
        before = self.store.snapshot
        for side, field, value in (("before", "kind", "playmat"), ("after", "kind", "playmat"),
                                   ("after", "quantity", "1"), ("after", "owner", "shared")):
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

    def test_scoped_private_edits_preserve_review_while_visible_edits_and_latest_target_touch_stale_it(self):
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
