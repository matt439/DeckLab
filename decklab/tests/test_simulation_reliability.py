"""Caution thresholds over synthetic saved-game rows; no real simulations or records."""
import copy
import json
import subprocess
import unittest
from unittest import mock

from decklab.lib.forge import gauntlet, reliability
from decklab.lib.gauntlet import catalogue, screening
from decklab.tests.test_gauntlet_ui import SETUP
from decklab.tests.test_workspace_ui import NODE, RUNNER, WEB


def games(reasons):
    return [{"r": reason, "first": number % 2, "w": 0 if reason == "win" else None}
            for number, reason in enumerate(reasons)]


class ReliabilityTests(unittest.TestCase):
    def test_strict_threshold_starter_split_and_unknown_starters_keep_all_denominators(self):
        self.assertFalse(reliability.stalled(games(["draw"] + ["win"]*9))["caution"])
        rows = games(["draw", "timeout", "error"] + ["win"]*7)
        rows[2]["first"] = None
        before = copy.deepcopy(rows)
        found = reliability.stalled(rows)
        self.assertEqual((found["stalled"], found["games"], found["share"], found["threshold"]), (3, 10, .3, .1))
        self.assertEqual(found["on_play"], {"games": 4, "stalled": 1})
        self.assertEqual(found["on_draw"], {"games": 5, "stalled": 1})
        self.assertEqual(found["unknown"], {"games": 1, "stalled": 1})
        self.assertIn("Going first 1/4; going second 1/5; unknown starter 1/1", found["words"])
        self.assertEqual(rows, before)
        mirrored = reliability.stalled(rows, 1)
        self.assertEqual(mirrored["on_draw"], found["on_play"])
        self.assertFalse(reliability.stalled([])["caution"])

    def test_group_merge_counts_all_opponents_even_those_below_caution_and_applies_floors(self):
        one = reliability.stalled(games(["draw"]*20 + ["win"]*80))
        two = reliability.stalled(games(["win"]*100))
        merged = reliability.merge_stalled([{"stalled_all": one}, {"stalled_all": two}])
        self.assertEqual((merged["stalled"], merged["games"]), (20, 200))
        self.assertFalse(merged["caution"])
        def row(report):
            return {"numbers": None, "not_meaningful": False, "n": report["games"], "stalled_all": report}
        thin = gauntlet._group("g", "Group", [(None, row(one)), (None, row(two))])
        self.assertTrue(thin["thin"])
        enough = gauntlet._group("g", "Group", [(None, row(two))]*3)
        self.assertNotIn("thin", enough)
        self.assertEqual(enough["games"], 300)

    def test_only_known_ai_screen_exclusions_are_grouped_and_legacy_reasons_stay_unknown(self):
        report = screening.summary({"excluded": [{"id": "not-loaded"}], "decks": [
            {"playable": False, "ai_excluded": True, "identity": "RG", "style": {"primary": "aggro"}},
            {"playable": False, "ai_excluded": False}, {"playable": False}, {"playable": True}]})
        self.assertEqual(report, {"ai_excluded": 1, "other_excluded": 1, "unclassified": 2,
                                  "colour": {"G": 1, "R": 1}, "style": {"aggro": 1}})

    def test_catalogue_screening_provenance_is_only_set_when_ai_screen_rejects_a_valid_source(self):
        record = {"id": "fixture", "kind": "constructed", "title": "Fixture", "source": {},
                  "tier": "medium", "cards": [[60, "Forest"]]}
        tagged = {"identity": "G", "colours": "G", "style": {}, "metrics": {}}
        with mock.patch.object(catalogue.fixing, "resolve", return_value=(record["cards"], [])), \
                mock.patch.object(catalogue, "_tag", return_value=tagged), \
                mock.patch.object(catalogue, "_card_sha", return_value="a"*64), \
                mock.patch.object(catalogue, "_screen", return_value=False) as screen:
            self.assertTrue(catalogue._constructed_entry(record, None)["ai_excluded"])
            screen.reset_mock()
            self.assertFalse(catalogue._constructed_entry({**record, "problems": ["Bad source"]}, None)["ai_excluded"])
            screen.assert_not_called()


@unittest.skipUnless(NODE, "Node.js isn't installed")
class ReliabilityUiTests(unittest.TestCase):
    def test_thin_group_screen_counts_and_stalled_rows_are_visible_without_writes(self):
        scenario = SETUP + """
          const group=gtGroupRow({label:'Thin',opponents:2,games:200,rate:.5,low:.3,high:.7,thin:true,note:'Too few compared opponents/games.'});
          assert(group.getAttribute('class').includes('gt-muted'));assert(group.textContent.includes('Too few'));
          const counts=gtScreening({ai_excluded:2,other_excluded:1,unclassified:3,colour:{R:2},style:{aggro:2}});
          assert(counts.textContent.includes('R: 2'));assert(counts.textContent.includes('unclassified provenance'));
          const answer=played();answer.opponents[0].stalled={words:'Stalled games: caution; Going first 3/5'};
          const output=gtRows(answer).map(node=>node?.textContent||'').join('');
          assert(output.includes('lowest observed first'));assert(output.includes('Going first 3/5'));
          assert.equal(writes.length,0);
        """
        done = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), scenario, True]),
                              capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(done.returncode, 0, done.stderr)
