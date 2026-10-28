"""Single-card Add filing over disposable inventory fixtures; use scripts/test_fixtures.py."""
import json
from unittest import mock

from decklab.lib import inventory
from decklab.lib.api import collection_edit as ce, collection_filing as filing
from decklab.lib.inventory import ops_collection as ops
from decklab.tests import test_collection_edit as support
from decklab.tests.test_api import _write
from decklab.tests.test_collection_filing import ELVES, deck_text


class AddFilingTests(support.CollectionEditTestCase):

    def add(self, quantity=2, **options):
        row = options.pop("row", {**ELVES, "quantity": quantity})
        with self.as_("user2"):
            return self.save("user2", "user2", action="add", row=row, **options)

    def test_merged_add_captures_only_actual_positive_printing_delta_and_keeps_metadata_rules(self):
        before = self.backend.load()
        answer = self.add(3, row={**ELVES, "quantity": 3, "condition": "LP", "language": "ja", "notes": "gift"})
        self.assertTrue(answer["ok"])
        self.assertTrue(answer["merged"])
        self.assertEqual(answer["added"], {"rows": 0, "cards": 3})
        self.assertEqual(answer["rows"][0]["quantity"], "5")
        self.assertEqual((answer["rows"][0]["condition"], answer["rows"][0]["language"]), ("", ""))
        self.assertIn("differing or unreported condition", answer["rows"][0]["notes"])
        self.assertIn("differing or unreported language", answer["rows"][0]["notes"])
        facts = self.writes[-1][3].extra["added_printings"]
        self.assertEqual(facts, [{**ELVES, "quantity": 3, "before_quantity": 2, "after_quantity": 5}])
        self.assertEqual(set(self.writes[-1][3].extra), {"shown", "added_printings"})
        self.assertEqual(answer["filing"]["added"], [{**ELVES, "quantity": 3}])
        self.assertEqual(answer["filing"]["destinations"], [{"kind": "storage", "row": 0, "quantity": 3}])
        self.assertEqual(answer["filing"]["status"], "ready")
        after = self.backend.load()
        self.assertEqual(after.decks, before.decks)
        self.assertEqual(after.imports, before.imports)
        self.assertNotIn("raw", answer)
        self.assertNotIn("before_quantity", json.dumps(answer))
        json.dumps(facts, allow_nan=False)
        self.assertEqual(len(self.writes), 1)

    def test_new_printing_uses_canonical_saved_identity_and_not_whole_name_stock(self):
        answer = self.add(row={"name": "llanowar elves", "set": "M19", "collector_number": "314",
                               "finish": "nonfoil", "quantity": 1})
        canonical = {**ELVES, "set": "m19", "collector_number": "314"}
        self.assertFalse(answer["merged"])
        self.assertEqual(answer["added"], {"rows": 1, "cards": 1})
        self.assertEqual(answer["filing"]["added"], [{**canonical, "quantity": 1}])
        self.assertEqual(self.writes[-1][3].extra["added_printings"],
                         [{**canonical, "quantity": 1, "before_quantity": 0, "after_quantity": 1}])

    def test_prior_free_stock_is_consumed_globally_before_suggesting_new_copies(self):
        for slug in ("a", "b"):
            _write(self.box.magic / f"people/user2/decks/casual/{slug}.md", deck_text(slug.upper(), 2))
        answer = self.add(2)
        self.assertEqual(answer["filing"]["status"], "ready")
        self.assertEqual(answer["filing"]["destinations"], [{"kind": "deck", "row": 0, "quantity": 2,
                         "deck": {"id": "user2/casual/b", "title": "B", "status": "building"}}])

    def test_requested_location_saves_once_and_does_not_change_the_pool_invariant(self):
        answer = self.add(1, location="Row 2, B")
        self.assertEqual(answer["locations"]["rows"], {"fdn|227|nonfoil": "Row 2, B"})
        self.assertEqual(answer["filing"]["status"], "ready")
        self.assertEqual(answer["filing"]["destinations"], [{"kind": "storage", "row": 0, "quantity": 1}])
        self.assertEqual(len(self.writes), 1)
        self.assertNotIn("raw", self.writes[-1][3].extra)

    def test_response_and_guide_use_actual_saved_snapshot_without_a_later_load(self):
        real = inventory.apply
        patchers, saved = [], []

        def save(*args, **kwargs):
            after, summary = real(*args, **kwargs)
            saved.append(after)
            patcher = mock.patch.object(self.backend, "load", side_effect=AssertionError("later snapshot"))
            patcher.start()
            patchers.append(patcher)
            return after, summary

        try:
            with mock.patch.object(inventory, "apply", side_effect=save):
                answer = self.add(1, location="Binder")
            self.assertEqual(answer["filing"]["status"], "ready")
            self.assertEqual(answer["sha256"], ops.sha256_of(saved[0].collection("user2")))
            self.assertEqual(answer["locations"]["rows"], {"fdn|227|nonfoil": "Binder"})
        finally:
            for patcher in patchers:
                patcher.stop()

    def test_invalid_delta_is_unknown_and_never_changes_success_to_failed_add(self):
        real = inventory.apply

        def save(*args, **kwargs):
            after, summary = real(*args, **kwargs)
            extra = {**summary.extra, "added_printings": [{**ELVES, "quantity": 2,
                                                          "before_quantity": 20, "after_quantity": 4}]}
            return after, inventory.Summary(summary.text, summary.counts, summary.changed, extra)

        with mock.patch.object(inventory, "apply", side_effect=save):
            answer = self.add()
        self.assertTrue(answer["ok"])
        self.assertEqual(answer["filing"]["status"], "unknown")
        self.assertEqual(answer["filing"]["message"], filing.ADD_UNKNOWN)
        self.assertEqual(answer["filing"]["destinations"], [{"kind": "unknown", "row": 0, "quantity": 2}])
        self.assertEqual(self.rows("user2")["rows"][0]["quantity"], "4")
        self.assertEqual(len(self.writes), 1)

    def test_advice_exception_keeps_success_once_and_exposes_no_error_detail(self):
        with mock.patch.object(filing, "after_add", side_effect=RuntimeError("private fixture error")):
            answer = self.add()
        self.assertTrue(answer["ok"])
        self.assertEqual(answer["filing"]["status"], "unknown")
        self.assertEqual(answer["filing"]["message"], filing.ADD_UNKNOWN)
        self.assertNotIn("private fixture error", json.dumps(answer))
        self.assertEqual(self.rows("user2")["rows"][0]["quantity"], "4")
        self.assertEqual(len(self.writes), 1)

    def test_edits_including_increases_swaps_reductions_and_removal_have_no_advice(self):
        original = {key: ELVES[key] for key in ("set", "collector_number", "finish")}
        with self.as_("user2"), mock.patch.object(filing, "after_add", side_effect=AssertionError("edit advice")) as advice:
            for row in ({**ELVES, "quantity": 2, "condition": "LP", "notes": "metadata"},
                        {**ELVES, "quantity": 5}, {**ELVES, "quantity": 5, "finish": "foil"},
                        {**ELVES, "quantity": 1, "finish": "foil"}):
                answer = self.save("user2", "user2", action="edit", original=original, row=row)
                original = {key: row[key] for key in ("set", "collector_number", "finish")}
                self.assertNotIn("filing", answer)
                self.assertNotIn("added", answer)
                self.assertNotIn("added_printings", self.writes[-1][3].extra)
            answer = self.save("user2", "user2", action="remove", original=original, reason="fixture removal")
            self.assertNotIn("filing", answer)
            self.assertNotIn("added", answer)
            advice.assert_not_called()

    def test_default_add_operation_retains_only_shown_extra_and_does_not_create_imports(self):
        before = self.backend.load()
        after, summary = ops.add(before, "user2", {**ELVES, "quantity": "1"})
        self.assertEqual(set(summary.extra), {"shown"})
        self.assertEqual(after.imports, before.imports)
        self.assertEqual(self.backend.load(), before)

    def test_stale_permissions_and_plain_basic_refusals_do_not_run_advice_or_write(self):
        before = self.magic_files()
        with mock.patch.object(filing, "after_add", side_effect=AssertionError("refusal advice")) as advice:
            with self.as_("matt"):
                self.assertApiError(403, self.call, ce.save_card, "matt", action="add", space="user2",
                                    sha256="invalid", row={})
            self.assertApiError(409, self.add, sha256="0" * 64)
            self.assertApiError(400, self.add, row={"name": "Forest", "set": "fdn", "collector_number": "280",
                                                   "finish": "nonfoil", "quantity": 3})
            advice.assert_not_called()
        self.assertEqual(self.magic_files(), before)
        self.assertEqual(self.writes, [])

    def test_no_index_special_basic_add_is_saved_but_never_inferred_as_storage(self):
        # The fixture index omits basics; exercise the endpoint's supported no-index save path.
        with mock.patch.object(ce, "_ready", return_value=False):
            answer = self.add(row={"name": "Forest", "set": "fdn", "collector_number": "280",
                                   "finish": "foil", "quantity": 2, "notes": "full art"})
        self.assertTrue(answer["ok"])
        self.assertEqual(answer["added"], {"rows": 1, "cards": 2})
        self.assertEqual(answer["filing"]["status"], "unknown")
        self.assertEqual(answer["filing"]["destinations"], [{"kind": "unknown", "row": 0, "quantity": 2}])
        self.assertEqual(len(self.writes), 1)
