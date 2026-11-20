"""Alias scheduling, saved work and checkpoints. FakeRuns writes synthetic game files only."""
from unittest import mock

from decklab.lib.forge import common, engine, variants, variants_gauntlet
from decklab.tests.test_variant_gauntlet import GauntletVariantCase


class SharedVariantWorkTests(GauntletVariantCase):
    def setUp(self):
        super().setUp()
        self.alias = dict(self.red, id="gauntlet:forge/duels/other-source", title="Other source")
        self.entries = [self.red, self.alias]
        self.enterContext(mock.patch.object(variants_gauntlet, "opponents", return_value=self.entries))

    def test_aliases_share_work_even_with_two_workers_and_reuse_a_different_tests_saved_pairs(self):
        progress = []
        summary = self.run_test(mode=20, progress=lambda done, total, detail: progress.append((done, total)))
        self.assertEqual([call["games"] for call in self.runs.calls], [20, 20])
        self.assertEqual((progress[0], progress[-1]), ((0, 40), (40, 40)))
        first, alias = summary["opponents"]
        self.assertEqual([first["title"], alias["title"]], ["Red Burn", "Other source"])
        for field in ("base_key", "paired_key", "base_side", "variant_side"):
            self.assertIsNotNone(first[field])
            self.assertEqual(first[field], alias[field])
        progress.clear()
        self.runs.calls.clear()
        self.run_test(mode=21, progress=lambda done, total, detail: progress.append((done, total)))
        self.assertEqual([call["games"] for call in self.runs.calls], [1, 1])
        self.assertEqual((progress[0], progress[-1]), ((0, 2), (2, 2)))

    def test_stop_records_shared_partial_pair_and_resume_fills_only_missing_games(self):
        self.runs(self.base, self.red, 20, by="Fixture")
        self.runs.stop_after = 5
        with self.assertRaises(common.Stopped):
            self.run_test(mode=20)
        stopped, = variants.tests_for(self.base["id"], "target", self.folder)
        self.assertEqual(stopped["outcome"], "stopped")
        first, alias = stopped["opponents"]
        self.assertEqual(first["paired_key"], alias["paired_key"])
        self.assertIsNotNone(alias["paired_key"])
        self.runs.calls.clear()
        progress = []
        self.run_test(mode=20, progress=lambda done, total, detail: progress.append((done, total)))
        self.assertEqual([call["numbers"] for call in self.runs.calls], [list(range(5, 20))])
        self.assertEqual((progress[0], progress[-1]), ((0, 15), (15, 15)))

    def test_failed_shared_pair_drops_both_sources_and_a_distinct_pair_continues(self):
        self.entries.append(self.blue)
        self.runs.fail[self.red["card_sha"]] = "Synthetic pilot error."
        summary = self.run_test(mode=10)
        first, alias, other = summary["opponents"]
        self.assertIn("Synthetic pilot error", first["dropped"])
        self.assertEqual(alias["dropped"], first["dropped"])
        self.assertIsNone(other["dropped"])
        self.assertCountEqual([call["b"] for call in self.runs.calls],
                              [self.red["id"], self.blue["id"], self.blue["id"]])

    def test_same_cards_with_different_pilots_still_play_two_distinct_pairs(self):
        self.alias["pilot"] = {"profile": "Other pilot", "switches": []}
        eng = engine._engine("decklab", "fixture", 120, [variants.DECK_ORDER], {"hash": "", "index": {}},
                             {"Default": "a" * 64, "Other pilot": "b" * 64}, True)
        with mock.patch.object(self.runs, "key", lambda a, b: engine.key(a, b, eng)):
            summary = self.run_test(mode=20)
        first, alias = summary["opponents"]
        self.assertNotEqual(first["base_key"], alias["base_key"])
        self.assertNotEqual(first["paired_key"], alias["paired_key"])
        self.assertCountEqual([call["b"] for call in self.runs.calls],
                              [self.red["id"], self.red["id"], self.alias["id"], self.alias["id"]])

    def test_unresolved_keys_are_independent_estimates(self):
        unreadable = mock.Mock(side_effect=common.ForgeError("Fixture key unavailable."))
        self.assertEqual(variants.opponent_work(self.base, self.entries, matchup_key=unreadable),
                         [(None, [self.red]), (None, [self.alias])])

    def test_a_conflicting_saved_pair_is_refused_before_any_new_games(self):
        records = [{"base_key": "base", "paired_key": key} for key in ("paired-1", "paired-2")]
        with self.assertRaisesRegex(common.ForgeError, variants.ENGINE_CHANGED), \
                mock.patch.object(variants, "_play_pair") as play:
            variants._play_shared({}, 20, "base", self.red, records)
        play.assert_not_called()
