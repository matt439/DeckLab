"""Tests for E3-S51, the turn a deck typically wins and loses in against popular decks: the pure
views.turns / pool_turns / clock_of / clock (the median and middle half of the rounds of games won
and of games lost, draws, timeouts, errors and games without a round count left out and counted,
fewer than five games a count and no median), each gauntlet opponent's clock, each group's and the
overall clock pooled from the games (never by averaging medians), the label and Commander's pod
note, and GET /api/gauntlet passing them on.

The gauntlet view reuses test_gauntlet_run's hand-written catalogue and FakeField (no Forge process
starts); the API test reuses test_gauntlet_api's FakeGauntlet. No test makes a network call or
reads the live database.

Run from the repo root: python scripts/test_fixtures.py decklab.tests.test_gauntlet_clock
"""
import json
import subprocess
import unittest
from unittest import mock

from decklab.lib.api import gauntlet_page
from decklab.lib.forge import gauntlet, views
from decklab.tests.test_gauntlet_api import GRUUL, GauntletApiTestCase
from decklab.tests.test_gauntlet_run import IDS, GauntletCase
from decklab.tests.test_gauntlet_ui import SETUP as UI_SETUP
from decklab.tests.test_workspace_ui import NODE, RUNNER, WEB


def game(outcome, rounds, side=0):
    """One saved game from side's point of view: outcome "won", "lost", "draw", "timeout" or "error"."""
    if outcome in ("won", "lost"):
        return {"w": side if outcome == "won" else 1 - side, "r": "win", "first": 0, "rounds": rounds}
    return {"w": None, "r": outcome, "first": 0, "rounds": rounds}


class ClockTests(unittest.TestCase):

    def test_median_and_middle_half_of_wins_and_losses(self):
        games = [game("won", r) for r in (9, 5, 6, 7, 8)] + [game("lost", r) for r in (10, 12, 11, 14, 13, 15)]
        c = views.clock(games, 0)
        self.assertEqual(c["won"], {"games": 5, "median": 7, "low": 6, "high": 8})
        # Six losses: the median between the middle two, the quartiles interpolated.
        self.assertEqual(c["lost"], {"games": 6, "median": 12.5, "low": 11.2, "high": 13.8})
        self.assertEqual(c["left_out"], {"draws": 0, "timeouts": 0, "errors": 0, "no_rounds": 0})
        json.dumps(c, allow_nan=False)

    def test_the_other_sides_point_of_view_swaps_wins_and_losses(self):
        games = [game("won", r) for r in (4, 5, 6, 7, 8)] + [game("lost", r) for r in (10, 11, 12, 13, 14)]
        mine, theirs = views.clock(games, 0), views.clock(games, 1)
        self.assertEqual(mine["won"], theirs["lost"])
        self.assertEqual(mine["lost"], theirs["won"])

    def test_draws_timeouts_errors_and_missing_rounds_are_left_out_and_counted(self):
        games = ([game("won", r) for r in (5, 6, 7, 8, 9)] + [game("draw", 20), game("draw", None)]
                 + [game("timeout", 30)] * 3 + [game("error", None)]
                 + [game("won", None), game("lost", 0), {"w": 1, "r": "win", "first": 1}, game("won", True)]
                 + [{"w": None, "r": "win", "first": 0, "rounds": 7}])          # no winner: never a win
        c = views.clock(games, 0)
        self.assertEqual(c["won"]["games"], 5)
        self.assertEqual(c["won"]["median"], 7)
        self.assertEqual(c["lost"]["games"], 0)
        self.assertEqual(c["left_out"], {"draws": 3, "timeouts": 3, "errors": 1, "no_rounds": 4})

    def test_fewer_than_five_shows_the_count_and_no_median(self):
        games = [game("won", r) for r in (5, 6, 7, 8)] + [game("lost", 9)]
        c = views.clock(games, 0)
        self.assertEqual(c["won"], {"games": 4, "median": None, "low": None, "high": None})
        self.assertEqual(c["lost"], {"games": 1, "median": None, "low": None, "high": None})
        self.assertEqual(views.CLOCK_MIN_GAMES, 5)
        empty = views.clock([], 0)
        self.assertEqual(empty["won"]["games"], 0)
        self.assertIsNone(empty["won"]["median"])
        self.assertEqual(views.clock_of(None), empty)

    def test_pooling_uses_the_games_never_the_medians(self):
        fast = views.turns([game("won", r) for r in (3, 3, 3, 3, 3, 3, 3, 3, 3)], 0)
        slow = views.turns([game("won", r) for r in (10, 11, 12, 13, 14)] + [game("draw", 9)], 0)
        pooled = views.clock_of(views.pool_turns([fast, slow, None]))
        medians = (views.clock_of(fast)["won"]["median"] + views.clock_of(slow)["won"]["median"]) / 2
        self.assertEqual(pooled["won"]["games"], 14)
        self.assertEqual(pooled["won"]["median"], 3)          # nine of fourteen games ended on turn 3
        self.assertNotEqual(pooled["won"]["median"], medians)
        self.assertEqual(pooled["left_out"]["draws"], 1)
        # Pooling leaves its tallies as they were.
        self.assertEqual(slow["won"], [10, 11, 12, 13, 14])

    def test_labels(self):
        self.assertEqual(views.CLOCK_LABEL["commander"], "simulated Forge games, 1v1, turns each")
        self.assertIn("turns each", views.CLOCK_LABEL["constructed"])
        self.assertIn("four-player pod", views.CLOCK_POD_NOTE)


class GauntletClockTests(GauntletCase):

    def put(self, deck_id, spec):
        """Saved games of alpha against deck_id: spec [(outcome, rounds)] from alpha's point of view."""
        stored = self.gfake.add_games(self.alpha, self.opponent(deck_id), len(spec), rate=0.5)
        p = 0 if stored["sides"][0]["card_sha"] == self.alpha["card_sha"] else 1
        for saved_game, (outcome, rounds) in zip(stored["batches"][-1]["games"], spec):
            saved_game.update(game(outcome, rounds, p), first=saved_game["first"])
        return stored

    def test_each_opponent_group_and_overall_has_its_clock(self):
        # Red Burn (aggro, R): wins fast. Blue Draw (control, U): loses slowly, with draws and a timeout.
        self.put(IDS[0], [("won", 4)] * 9 + [("lost", 8)] * 3)
        self.put(IDS[1], [("won", 12)] * 5 + [("lost", r) for r in (9, 10, 11, 12, 13)] + [("draw", 20)] * 2
                 + [("timeout", 40)])
        self.put(IDS[2], [("won", None)] * 2 + [("error", None)])
        found = gauntlet.view(self.alpha, self.sample)
        self.assertEqual(found["clock_label"], views.CLOCK_LABEL["constructed"])
        self.assertIsNone(found["clock_note"])                   # 60-card: no pod note
        by_id = {o["id"]: o for o in found["opponents"]}
        red = by_id[IDS[0]]["clock"]
        self.assertEqual(red["won"], {"games": 9, "median": 4, "low": 4, "high": 4})
        self.assertEqual(red["lost"], {"games": 3, "median": None, "low": None, "high": None})
        blue = by_id[IDS[1]]["clock"]
        self.assertEqual((blue["won"]["median"], blue["lost"]["median"]), (12, 11))
        self.assertEqual(blue["left_out"], {"draws": 2, "timeouts": 1, "errors": 0, "no_rounds": 0})
        self.assertEqual(by_id[IDS[2]]["clock"]["left_out"], {"draws": 0, "timeouts": 0, "errors": 1, "no_rounds": 2})
        self.assertEqual(by_id[IDS[3]]["clock"]["won"]["games"], 0)            # not played
        overall = found["overall"]["clock"]
        self.assertEqual(overall["won"]["games"], 14)
        self.assertEqual(overall["won"]["median"], 4)            # pooled: nine of fourteen wins on turn 4
        self.assertEqual(overall["lost"]["games"], 8)
        self.assertEqual(overall["left_out"], {"draws": 2, "timeouts": 1, "errors": 1, "no_rounds": 2})
        groups = {name: {g["key"]: g for g in rows} for name, rows in found["groups"].items()}
        self.assertEqual(groups["style"]["aggro"]["clock"], red)
        control = groups["style"]["control"]["clock"]              # Blue Draw and Izzet Spells pooled
        self.assertEqual(control["won"], blue["won"])
        self.assertEqual(control["left_out"], {"draws": 2, "timeouts": 1, "errors": 1, "no_rounds": 2})
        self.assertEqual(groups["colour"]["G"]["clock"]["won"]["games"], 0)
        json.dumps(found, allow_nan=False)

    def test_an_opponent_whose_results_mean_nothing_is_left_out_of_the_clock(self):
        self.put(IDS[0], [("won", 4)] * 6)
        rows = gauntlet._members(self.alpha, self.sample, None, gauntlet.catalogue("constructed"))[1]
        bad = [(deck, dict(row, not_meaningful=True)) for deck, row in rows]
        self.assertEqual(gauntlet._group("all", "", bad)["clock"]["won"]["games"], 0)
        self.assertEqual(gauntlet._opponent(*bad[0])["clock"]["won"]["games"], 0)
        self.assertEqual(gauntlet._group("all", "", rows)["clock"]["won"]["games"], 6)

    def test_a_commander_view_has_the_1v1_label_and_the_pod_note(self):
        with mock.patch.object(gauntlet, "_check"), mock.patch.object(gauntlet, "_members", return_value=([], [])):
            found = gauntlet.view(self.alpha, dict(self.sample, format="commander"), cat={"sha": "a" * 64})
        self.assertEqual(found["clock_label"], "simulated Forge games, 1v1, turns each")
        self.assertEqual(found["clock_note"], views.CLOCK_POD_NOTE)


class GauntletClockApiTests(GauntletApiTestCase):

    def test_the_view_passes_the_clock_on(self):
        before = self.call("matt", gauntlet_page.gauntlet_view, GRUUL, "target")
        self.assertEqual((before["clock_label"], before["clock_note"]), (None, None))
        clock = views.clock([game("won", r) for r in (5, 6, 7, 8, 9)], 0)
        overall = {"key": "all", "rate": 0.4, "low": 0.3, "high": 0.5, "clock": clock}
        group = {"key": "R", "label": "Red", "opponents": 3, "games": 300, "rate": 0.4, "low": 0.3, "high": 0.5,
                 "spread": [0.4, 0.4], "note": "", "clock": clock}
        with mock.patch.object(self.g, "view", side_effect=lambda entry, chosen, keep=None, cat=None: {
                "opponents": [{"id": d, "title": d, "games": 100, "clock": clock} for d in chosen["decks"]],
                "groups": {"colour": [group]}, "games": 300, "note": None, "notes": [], "overall": overall,
                "played": 3, "of": 3, "tally": {}, "updated": None,
                "clock_label": views.CLOCK_LABEL["commander"], "clock_note": views.CLOCK_POD_NOTE}):
            answer = self.call("matt", gauntlet_page.gauntlet_view, GRUUL, "target")
        self.assertEqual(answer["overall"]["clock"], clock)
        self.assertEqual(answer["groups"]["colour"][0]["clock"], clock)
        self.assertTrue(all(o["clock"] == clock for o in answer["opponents"]))
        self.assertEqual((answer["clock_label"], answer["clock_note"]),
                         (views.CLOCK_LABEL["commander"], views.CLOCK_POD_NOTE))
        json.dumps(answer, allow_nan=False)


@unittest.skipUnless(NODE, "Node.js isn't installed")
class GauntletClockUiTests(unittest.TestCase):
    """web/gauntlet.js's clock lines through its real renderers over test_gauntlet_ui's isolated Node DOM."""

    def run_js(self, scenario):
        result = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), UI_SETUP + scenario, True]),
                                capture_output=True, text=True, encoding="utf-8", timeout=25)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")

    def test_overall_group_and_opponent_lines_with_the_commander_label_and_pod_note(self):
        self.run_js("""
          const side=(games,median,low,high)=>({games,median,low,high});
          const clock=(won,lost,left={})=>({won,lost,left_out:{draws:0,timeouts:0,errors:0,no_rounds:0,...left}});
          const a=played();
          Object.assign(a,{format:'commander',overall:{key:'all',label:'All these opponents',opponents:3,games:300,
              rate:.47,low:.39,high:.55,clock:clock(side(120,8,7,10),side(150,11.5,9,13),{draws:2,timeouts:1,no_rounds:3})},
            played:3,of:3,tally:{ahead:1,even:1,behind:1,unsettled:0},
            clock_label:'simulated Forge games, 1v1, turns each',clock_note:'The gauntlet plays 1v1, not a four-player pod.'});
          a.groups.colour[0].clock=clock(side(40,9,8,9),side(3,null,null,null));
          a.opponents[0].clock=clock(side(0,null,null,null),side(4,null,null,null));
          a.opponents[1].clock=clock(side(6,7,7,7),side(0,null,null,null),{draws:1});
          a.opponents[2].clock=clock(side(0,null,null,null),side(0,null,null,null),{timeouts:2});
          answers=[a];
          const node=await draw();
          const box=node.querySelector('.gt-clock');
          assert(box,'no overall clock');
          assert.equal(box.querySelector('.gt-clock-what').textContent,'Wins on turn 8 (7–10), loses on turn 11.5 (9–13).');
          assert(box.textContent.includes('Median and middle half: simulated Forge games, 1v1, turns each.'),box.textContent);
          assert(box.textContent.includes('Left out: 2 draws, 1 timeout and 3 games without a round count.'),box.textContent);
          assert(box.textContent.includes('not a four-player pod'));
          const group=node.querySelector('.gt-groups').querySelector('.gt-clock-line');
          assert.equal(group.textContent,'Wins on turn 9 (8–9), 3 losses, too few for a typical turn.');
          const lines=node.querySelector('.gt-rows').querySelectorAll('.gt-clock-line').map(n=>n.textContent);
          same(lines,['4 losses, too few for a typical turn.','Wins on turn 7. Left out: 1 draw.','Left out: 2 timeouts.']);
        """)

    def test_every_game_left_out_still_counts_them(self):
        self.run_js("""
          const a=played();
          Object.assign(a,{overall:{key:'all',label:'All these opponents',opponents:3,games:300,rate:.47,low:.39,high:.55,
            clock:{won:{games:0,median:null,low:null,high:null},lost:{games:0,median:null,low:null,high:null},
              left_out:{draws:5,timeouts:0,errors:0,no_rounds:0}}},played:3,of:3,
            tally:{ahead:0,even:0,behind:0,unsettled:3},clock_label:'simulated Forge games, turns each',clock_note:null});
          answers=[a];
          const node=await draw();
          const box=node.querySelector('.gt-clock');
          assert(box,'no overall clock for an all-draws gauntlet');
          assert.equal(box.querySelector('.gt-clock-what').textContent,"No game was won or lost, so there's no typical turn.");
          assert(box.textContent.includes('Left out: 5 draws.'),box.textContent);
          assert(!box.textContent.includes('Median and middle half'),box.textContent);
          assert.equal(node.querySelector('.gt-clock-line'),null);
        """)

    def test_no_clock_without_any_game(self):
        self.run_js("""
          const a=played();
          const none={games:0,median:null,low:null,high:null};
          Object.assign(a,{overall:{key:'all',label:'All these opponents',opponents:3,games:0,rate:null,low:null,high:null,
            clock:{won:none,lost:none,left_out:{draws:0,timeouts:0,errors:0,no_rounds:0}}},played:3,of:3,
            tally:{ahead:0,even:0,behind:0,unsettled:3},clock_label:'simulated Forge games, turns each',clock_note:null});
          answers=[a];
          const node=await draw();
          assert.equal(node.querySelector('.gt-clock'),null);
        """)


if __name__ == "__main__":
    unittest.main()
