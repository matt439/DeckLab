"""Read and resume old paired tests whose catalogue entries pointed to the same games."""
import json
from unittest import mock

from decklab.lib.forge import common, field, runner, variants
from decklab.tests.test_forge_variants import CoordinatorCase


class SavedSharedTests(CoordinatorCase):
    def setUp(self):
        super().setUp()
        self.alias = dict(self.red, id="casual/red-alias", title="Red alias")
        with mock.patch.object(field, "opponents", return_value=[self.red, self.blue]):
            self.original = self.run_test("field", mode=50)
        self.test_id = self.original["test"]
        self.path = self.tmp / "paired" / "tests" / (self.test_id + ".json")
        self.legacy = json.loads(self.path.read_text(encoding="utf-8"))
        self.legacy["version"] = 1
        self.legacy["opponents"].append(dict(self.legacy["opponents"][0], id=self.alias["id"],
                                             title=self.alias["title"]))
        self.legacy.update(outcome="worse", decision="worse", starter_mismatch={"games": 11, "of": 150})
        self.legacy["looks"][-1].update(delta=-.9, low=-.99, high=-.7, decision="worse")
        self.runs.calls.clear()

    def write(self):
        self.path.write_text(json.dumps(self.legacy), encoding="utf-8")
        return self.path.read_bytes()

    def test_read_and_list_withhold_old_looks_but_show_current_game_evidence(self):
        content = self.write()
        before = variants.load_summary(self.test_id, self.tmp)
        self.assertTrue(before["needs_recheck"])
        self.assertEqual(before["looks"], [])
        self.assertIsNone(before["outcome"])
        self.assertIsNone(before["decision"])
        self.assertEqual(before["starter_mismatch"], {"games": 0, "of": 0})
        self.assertEqual(variants.tests_for(self.base["id"], "target", self.tmp), [before])
        seen = variants.view(self.test_id, self.tmp)
        self.assertIsNone(seen["verdict"])
        self.assertIn("share games", seen["words"])
        self.assertAlmostEqual(seen["field"]["low"], self.original["looks"][-1]["low"])
        self.assertEqual([r["title"] for r in seen["opponents"]], ["Red", "Blue", "Red alias"])
        visible = variants.visible_summary(before, lambda deck: deck != self.alias["id"])
        self.assertNotIn("needs_recheck", visible)
        self.assertIsNone(variants.verdict_words(visible))
        self.assertEqual(self.path.read_bytes(), content)
        self.assertEqual(self.runs.calls, [])

    def test_matching_receipts_rejudge_without_new_games(self):
        self.write()
        with mock.patch.object(field, "opponents", return_value=[self.red, self.blue, self.alias]):
            corrected = self.run_test("field", mode=50)
        self.assertEqual(corrected["looks"], self.original["looks"])
        self.assertEqual(corrected["outcome"], self.original["outcome"])
        self.assertEqual(corrected["starter_mismatch"], self.original["starter_mismatch"])
        self.assertEqual(corrected["version"], variants.SUMMARY_VERSION)
        self.assertNotIn("needs_recheck", corrected)
        self.assertEqual(variants.load_summary(self.test_id, self.tmp), corrected)
        self.assertEqual(self.runs.calls, [])

    def test_missing_game_files_cannot_restore_a_historical_verdict(self):
        content = self.write()
        with mock.patch.object(variants.saved, "load", return_value=None), \
                mock.patch.object(variants, "load_paired", return_value=None):
            seen = variants.view(self.test_id, self.tmp)
        self.assertIsNone(seen["field"])
        self.assertIsNone(seen["verdict"])
        self.assertTrue(seen["test"]["needs_recheck"])
        self.assertEqual(self.path.read_bytes(), content)
        self.assertEqual(self.runs.calls, [])

    def test_a_missing_distinct_opponent_cannot_be_lost_from_the_saved_verdict(self):
        content = self.write()
        with mock.patch.object(field, "opponents", return_value=[self.red, self.alias]):
            with self.assertRaisesRegex(common.ForgeError, "opponents have changed"):
                self.run_test("field", mode=50, extend=self.test_id)
        self.assertEqual(self.path.read_bytes(), content)
        self.assertEqual(self.runs.calls, [])

    def test_retry_observes_another_run_that_finished_before_it_claimed_the_test(self):
        self.write()
        claim = runner._claim

        def claim_after_completed_write(folder, key):
            self.path.write_text(json.dumps(self.original), encoding="utf-8")
            return claim(folder, key)

        with mock.patch.object(runner, "_claim", side_effect=claim_after_completed_write), \
                mock.patch.object(field, "opponents", return_value=[self.red, self.blue]):
            result = self.run_test("field", mode=50)
        self.assertEqual(result, self.original)
        self.assertEqual(self.runs.calls, [])

    def test_a_stopped_or_dropped_opponent_does_not_prove_an_earlier_look(self):
        self.legacy.update(outcome="stopped")
        self.legacy["opponents"][-1]["dropped"] = "couldn't be played"
        self.write()
        loaded = variants.load_summary(self.test_id, self.tmp)
        self.assertEqual(loaded["looks"], [])
        self.assertEqual(loaded["outcome"], "stopped")
        self.assertTrue(loaded["needs_recheck"])

    def test_old_summaries_with_independent_evidence_are_preserved(self):
        self.legacy["opponents"][-1].update(base_key="c" * 64, paired_key="d" * 64)
        self.write()
        self.assertEqual(variants.load_summary(self.test_id, self.tmp), self.legacy)
