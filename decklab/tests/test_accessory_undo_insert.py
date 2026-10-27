"""Complete-record unused proof for synthetic accessory INSERT inverses."""
import copy
from dataclasses import replace
import unittest
from unittest import mock

from decklab.lib import accessories, accessory_fetch, cards, inventory, profiles
from decklab.lib.inventory import accessory_undo_remove as guard, changes, files, model, ops_accessories, paths, rules
from decklab.lib.inventory.undo import UndoConflict
from decklab.tests import accessory_undo_support as fixture, household_config

RID = "a-sleeves"
PRODUCT = b"deck,section,name,quantity,finish,set,collector_number\nFixture,deck,Forest,60,nonfoil,fdn,272\n"


class AccessoryInsertUndoTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(mock.patch.object(profiles, "read", return_value=copy.deepcopy(household_config.PROFILES)))
        self.store = fixture.AuditAccessoryInventory()
        self.addCleanup(inventory.use(self.store))
        self.seed()

    def seed(self, only=False):
        return fixture.seed_insert(self.store, only=only)

    def source(self):
        return self.store.audit[fixture.CHANGE_ID][0]

    def unused(self):
        return guard.unused(self.store.snapshot, RID)

    def refused(self):
        before, audit = self.store.snapshot, copy.deepcopy(self.store.audit)
        with self.assertRaises(UndoConflict) as caught:
            self.unused()
        self.assertEqual(str(caught.exception), guard.REFUSED)
        self.assertEqual(caught.exception.conflicts, [])
        self.assertIs(self.store.snapshot, before)
        self.assertEqual(self.store.audit, audit)

    def deck(self, status="built", headers="", *, space="home", slug="fixture"):
        text = ("# Synthetic holder\n\n- **Format:** Casual 60-card, 1v1\n- **Played by:** user\n"
                f"- **Status:** {status}\n- **Built version:** target\n{headers}\n## Decklist\n\n```\n60 Forest\n```\n")
        stored = model.Deck(space, "casual", slug, text)
        self.store.snapshot = self.store.snapshot.with_deck(stored)
        return stored

    def product(self, *, status="owned", intact="no", sleeves="", deck_box=""):
        raw = dict.fromkeys(rules.STATUS_FIELDS, "")
        raw.update(file="fixture.csv", status=status, intact=intact, sleeves=sleeves, deck_box=deck_box)
        sheet = files.status_sheet(rules.csv_bytes([raw], rules.STATUS_FIELDS))
        product = files._product("fixture", PRODUCT)
        self.store.snapshot = self.store.snapshot.replace(products=(product,), status=sheet)
        return product, sheet

    def test_unused_guard_has_no_card_photo_network_or_config_side_effects(self):
        before, audit = self.store.snapshot, copy.deepcopy(self.store.audit)
        with mock.patch.object(cards, "resolve", side_effect=AssertionError("No card lookup")), \
                mock.patch.object(cards, "printing", side_effect=AssertionError("No printing lookup")), \
                mock.patch.object(accessory_fetch, "fetch", side_effect=AssertionError("No network")), \
                mock.patch.object(accessory_fetch, "staged_file", side_effect=AssertionError("No photo staging")):
            self.assertIsNone(self.unused())
        self.assertIs(self.store.snapshot, before)
        self.assertEqual(self.store.audit, audit)

    def test_any_status_sleeves_or_box_reference_blocks_even_wrong_kind_or_padded_id(self):
        for status in ("idea", "building", "built"):
            for field in ("Sleeves", "Deck box"):
                self.seed()
                self.deck(status, f"- **{field}:** \t{RID} \t\n")
                with self.subTest(status=status, field=field):
                    self.refused()

    def test_duplicate_accessory_headers_are_ambiguous_even_if_last_is_blank(self):
        for field in ("Sleeves", "Deck box"):
            for first in (RID, "another-id", ""):
                self.seed()
                self.deck("idea", f"- **{field}:** {first}\n- **{field.lower()}:** \n")
                with self.subTest(field=field, first=first):
                    self.refused()

    def test_home_deck_read_parse_status_and_built_version_uncertainty_refuse(self):
        for mode in ("unreadable", "error-with-text", "missing-list", "missing-status", "unknown-status", "duplicate-status", "bad-built", "assembly", "nul"):
            self.seed()
            stored = self.store.snapshot.deck("casual/fixture")
            if mode == "unreadable":
                stored = replace(stored, text=None, error="Private path read failure")
            elif mode == "error-with-text":
                stored = replace(stored, error="Private path read failure")
            else:
                changes_by_mode = {
                    "missing-list": stored.text.replace("## Decklist", "## Missing list"),
                    "missing-status": stored.text.replace("- **Status:** built\n", ""),
                    "unknown-status": stored.text.replace("- **Status:** built", "- **Status:** unknown"),
                    "duplicate-status": stored.text.replace("- **Status:** built", "- **Status:** idea\n- **Status:** built"),
                    "bad-built": stored.text.replace("- **Built version:** target", "- **Built version:** unknown"),
                    "assembly": stored.text.replace("- **Built version:** target", "- **Built version:** target\n- **Assembled:** not-json"),
                    "nul": stored.text + "\0",
                }
                stored = replace(stored, text=changes_by_mode[mode])
            self.store.snapshot = self.store.snapshot.replace(decks={**self.store.snapshot.decks, stored.id: stored})
            with self.subTest(mode=mode):
                self.refused()

    def test_member_deck_is_outside_home_kit_scope_without_relaying_its_text(self):
        private = model.Deck("user2", "casual", "private", None, "Private unreadable deck")
        self.store.snapshot = self.store.snapshot.replace(decks={**self.store.snapshot.decks, private.id: private})
        self.assertIsNone(self.unused())
        self.assertEqual(self.store.snapshot.deck(private.id), private)

    def test_status_sheet_must_be_present_readable_complete_and_unambiguous(self):
        initial = self.store.snapshot
        variants = ({"exists": False}, {"error": "Private read failure"}, {"strict_error": "Private strict failure"},
                    {"csv_error": "Private CSV failure"}, {"problems": ("Private warning",)},
                    {"columns": tuple(rules.STATUS_FIELDS[:-1])}, {"columns": (*rules.STATUS_FIELDS, "sleeves")})
        for changed in variants:
            self.store.snapshot = initial.replace(status=replace(initial.status, **changed))
            with self.subTest(changed=changed):
                self.refused()

    def test_all_product_status_references_block_even_cancelled_nonintact_and_wrong_kind(self):
        for status, intact in (("owned", "yes"), ("owned", "no"), ("ordered", "no"), ("cancelled", "")):
            for field in ("sleeves", "deck_box"):
                self.seed()
                self.product(status=status, intact=intact, **{field: f" \t{RID} \t"})
                with self.subTest(status=status, intact=intact, field=field):
                    self.refused()

    def test_products_and_statuses_must_match_even_for_nonintact_or_unowned_records(self):
        for mode in ("missing-product", "missing-status", "duplicate-product", "duplicate-status", "unknown-status", "unknown-intact", "owned-blank"):
            self.seed()
            product, sheet = self.product(status="ordered", intact="no")
            if mode == "missing-product":
                self.store.snapshot = self.store.snapshot.replace(products=())
            elif mode == "missing-status":
                self.store.snapshot = self.store.snapshot.replace(status=files.status_sheet((",".join(rules.STATUS_FIELDS) + "\n").encode()))
            elif mode == "duplicate-product":
                self.store.snapshot = self.store.snapshot.replace(products=(product, product))
            elif mode == "duplicate-status":
                self.store.snapshot = self.store.snapshot.replace(status=replace(sheet, rows=sheet.rows * 2))
            else:
                raw = sheet.rows[0].as_dict()
                raw.update({"unknown-status": {"status": "unknown"}, "unknown-intact": {"intact": "unknown"},
                            "owned-blank": {"status": "owned", "intact": ""}}[mode])
                self.store.snapshot = self.store.snapshot.replace(status=replace(sheet, rows=(model.StatusRow.make(raw),)))
            with self.subTest(mode=mode):
                self.refused()

    def test_product_layout_and_every_status_row_cell_must_be_known(self):
        for mode in ("product-error", "product-problems", "product-columns", "product-overflow", "product-cell", "status-overflow", "status-duplicate-cell", "status-type"):
            self.seed()
            product, sheet = self.product()
            if mode == "product-error":
                product = replace(product, error="Private read failure")
            elif mode == "product-problems":
                product = replace(product, problems=("Private problem",))
            elif mode == "product-columns":
                product = replace(product, columns=None)
            elif mode == "product-overflow":
                product = replace(product, items=(replace(product.items[0], overflow=("Extra",)),))
            elif mode == "product-cell":
                values = tuple((key, None if key == "name" else value) for key, value in product.items[0].values)
                product = replace(product, items=(replace(product.items[0], values=values),))
            elif mode == "status-overflow":
                sheet = replace(sheet, rows=(replace(sheet.rows[0], overflow=("Extra",)),))
            elif mode == "status-duplicate-cell":
                sheet = replace(sheet, rows=(replace(sheet.rows[0], values=(("sleeves", RID), *sheet.rows[0].values)),))
            else:
                values = tuple((key, None if key == "notes" else value) for key, value in sheet.rows[0].values)
                sheet = replace(sheet, rows=(replace(sheet.rows[0], values=values),))
            self.store.snapshot = self.store.snapshot.replace(products=(product,), status=sheet)
            with self.subTest(mode=mode):
                self.refused()

    def test_scan_warnings_target_strays_usage_and_unknown_kind_refs_cannot_be_ignored(self):
        def warning(warnings):
            warnings.append("Private warning")
            return [], []
        variants = (warning, ([], [("private", "sleeves", RID)]),
                    ([{"sleeves": "", "deck_box": RID}], []), ([], [("malformed",)]))
        for result in variants:
            patch = mock.patch.object(accessories, "_scan", side_effect=result) if callable(result) else mock.patch.object(accessories, "_scan", return_value=result)
            with self.subTest(result=result), patch:
                self.refused()
        for state in ("unknown", "text", "kind_mismatch"):
            with self.subTest(state=state), mock.patch.object(accessories, "_usage", return_value={"another-reference": [{"state": state}]}):
                self.refused()

    def test_only_known_linked_other_kit_passes_while_legacy_text_and_strays_refuse(self):
        self.deck("built", "- **Sleeves:** b-shared\n")
        self.assertIsNone(self.unused())
        self.product(status="ordered", intact="no")
        self.assertIsNone(self.unused())
        for status in ("idea", "built"):
            self.deck(status, "- **Sleeves:** red\n")
            with self.subTest(status=status):
                self.refused()

    def test_ordinary_removal_after_proof_preserves_every_other_source_and_can_empty_list(self):
        for only, empty_home in ((False, False), (True, False), (True, True)):
            self.seed(only=only)
            if empty_home:
                self.store.snapshot = files.build({paths.ACCESSORIES: accessories.csv_bytes([self.source()["after"]])},
                                                  revision="empty-1", decks_revision="empty-decks")
            before = self.store.snapshot
            self.assertIsNone(self.unused())
            listing = accessories.from_sheet(before.accessories, strict=True)
            after, _ = ops_accessories.remove_accessory(before, id=RID, owners=fixture.OWNERS,
                                                       sha256=accessories.view_sha256(listing, fixture.OWNERS))
            after = changes.prepare(before, after)
            self.assertEqual([row.as_dict() for row in after.accessories.rows],
                             [row.as_dict() for row in before.accessories.rows if row.accessory_id != RID])
            self.assertEqual(after.replace(accessories=before.accessories, revision=before.revision,
                                           decks_revision=before.decks_revision), before)
            self.assertEqual(bool(after.accessories.rows), not only)
