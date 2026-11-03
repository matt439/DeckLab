"""Tests for E3-S39's gauntlet mirror rules: a house list never plays (or counts games against) a list
identical to it (field._opponents and forge.gauntlet._members, by card_sha; gauntlet_page._keep
refuses an exact mirror's result), and a trial deck's gauntlet leaves out its own precon's catalogue
copy (gauntlet:precon/<FILE>, whose list fixing may have changed) wherever its samples are used: the
deck page's view and run, the summary and the Popular decks board, whose rows say "trial".

The API tests run in test_gauntlet_api's sandbox (FakeForge, FakeGauntlet, a fresh COORD_JOBS runner);
no Forge game, network, database or real catalogue is used.

Run from the repo root: python scripts/test_fixtures.py decklab.tests.test_precon_trial_gauntlet
"""
import unittest
from unittest import mock

from decklab.lib import gauntlet
from decklab.lib.api import gauntlet_board, gauntlet_page, library_gauntlet
from decklab.lib.forge import field
from decklab.lib.forge import gauntlet as forge_gauntlet
from decklab.tests import test_gauntlet_api
from decklab.tests.test_api import GRUUL as GRUUL_TEXT, _write
from decklab.tests.test_gauntlet_api import POPULAR, SAMPLE, GauntletApiTestCase

PRECON = "gauntlet:precon/GruulTrial_TST"
TRIAL = "casual/gruul-trial"
TRIAL_TEXT = (GRUUL_TEXT.replace("# Gruul Test", "# Gruul Trial")
              .replace("- **Status:** building", "- **Status:** idea\n- **Trial:** precon GruulTrial_TST"))


class SampleTests(unittest.TestCase):

    def test_trial_excluded(self):
        self.assertEqual(gauntlet.trial_excluded({"trial": "GruulTrial_TST"}), (PRECON,))
        for summary in (None, {}, {"trial": None}, {"trial": ""}):
            with self.subTest(summary=summary):
                self.assertEqual(gauntlet.trial_excluded(summary), ())

    def test_without_keeps_the_sample_and_its_id(self):
        sample = {"id": SAMPLE, "format": "constructed", "decks": ["a", PRECON, "b"]}
        self.assertIs(gauntlet.without(sample, ()), sample)
        self.assertIs(gauntlet.without(sample, ("c",)), sample)
        self.assertEqual(gauntlet.without(sample, (PRECON,)), {"id": SAMPLE, "format": "constructed",
                                                               "decks": ["a", "b"]})
        self.assertEqual(sample["decks"], ["a", PRECON, "b"])          # not changed in place


class MirrorTests(unittest.TestCase):

    def test_field_opponents_leave_out_an_identical_list(self):
        house = {"id": "casual/x", "card_sha": "s" * 64, "kind": "constructed"}
        others = [{"id": "casual/y", "card_sha": "s" * 64, "version": "target"},
                  {"id": "casual/z", "card_sha": "z" * 64, "version": "target"},
                  {"id": "casual/x", "card_sha": "x" * 64, "version": "target"}]
        self.assertEqual([e["id"] for e in field._opponents(house, None, others)], ["casual/z"])

    def catalogue(self):
        deck = {"id": PRECON, "title": "Gruul Trial", "kind": "constructed", "playable": True,
                "cards": {"Main": [[4, "Llanowar Elves"], [56, "Forest"]]}, "source": {}}
        other = dict(deck, id="gauntlet:forge/duels/x", cards={"Main": [[60, "Forest"]]})
        return {"decks": [deck, other], "sha": "c" * 64}, deck

    def test_the_view_leaves_out_a_mirror_and_excluded_ids(self):
        cat, deck = self.catalogue()
        house = dict(forge_gauntlet._to_entry(deck), id=TRIAL)
        chosen = {"id": SAMPLE, "format": "constructed", "catalogue_sha": "c" * 64,
                  "decks": [PRECON, "gauntlet:forge/duels/x"]}
        seen = []

        def rows(entry, opps, results_dir, keep):
            seen.append([o["id"] for o in opps])
            return [{"key": o["id"], "n": 0, "numbers": None, "lead": None, "not_meaningful": False,
                     "problem": None} for o in opps]
        with mock.patch.object(field, "_rows", rows):
            found = forge_gauntlet.view(house, chosen, cat=cat)
            self.assertEqual((seen[-1], found["of"]), (["gauntlet:forge/duels/x"], 1))
            other = dict(house, card_sha="o" * 64)
            self.assertEqual(forge_gauntlet.view(other, chosen, cat=cat)["of"], 2)
            self.assertEqual(forge_gauntlet.view(other, chosen, cat=cat, exclude_ids=(PRECON,))["of"], 1)

    def test_older_counts_the_opponents_the_view_counts(self):
        cat, deck = self.catalogue()
        house = dict(forge_gauntlet._to_entry(deck), id="casual/x")        # an ordinary deck: a mirror's list
        chosen = {"id": SAMPLE, "format": "constructed", "catalogue_sha": "c" * 64,
                  "decks": [PRECON, "gauntlet:forge/duels/x"]}
        result = {"key": "k", "sides": [{"card_sha": house["card_sha"], "id": "casual/x"},
                                        {"card_sha": "o" * 64, "id": "gauntlet:forge/duels/x"}]}
        with mock.patch.object(forge_gauntlet, "notes_keys", return_value=["k"]), \
                mock.patch.object(forge_gauntlet.saved, "load", return_value=result), \
                mock.patch.object(forge_gauntlet.engine, "today", return_value={"complete": False}):
            found = forge_gauntlet.older(house, chosen, cat=cat)
        self.assertEqual((found["reason"], found["of"]), ("unknown", 1))

    def test_plan_and_run_take_excluded_ids(self):
        cat, _ = self.catalogue()
        chosen = {"id": SAMPLE, "format": "constructed", "decks": [PRECON, "gauntlet:forge/duels/x"]}
        house = {"id": TRIAL, "kind": "constructed", "card_sha": "h" * 64}
        asked = []
        with mock.patch.object(forge_gauntlet, "entries", lambda fmt, ids: asked.append(list(ids)) or []), \
                mock.patch.object(field, "plan", return_value={}), \
                mock.patch.object(field, "run_field", return_value={}), \
                mock.patch.object(forge_gauntlet, "results_dir", return_value=mock.MagicMock()),                 mock.patch.object(forge_gauntlet, "standard", return_value={"id": "sample:other"}):
            forge_gauntlet.plan(house, chosen, exclude_ids=(PRECON,))
            forge_gauntlet.run(house, chosen, exclude_ids=(PRECON,))
        self.assertEqual(asked, [["gauntlet:forge/duels/x"]] * 2)

    def test_keep_refuses_an_exact_mirror(self):
        keep = gauntlet_page._keep({"card_sha": "s" * 64})
        mirror = {"sides": [{"card_sha": "s" * 64, "id": PRECON}, {"card_sha": "s" * 64, "id": PRECON}]}
        self.assertFalse(keep(mirror))
        self.assertTrue(keep({"sides": [{"card_sha": "s" * 64, "id": TRIAL}, {"card_sha": "o" * 64, "id": PRECON}]}))
        self.assertFalse(keep({"sides": [{"card_sha": "s" * 64}, {"card_sha": "o" * 64, "id": TRIAL}]}))


class TrialGauntletTests(GauntletApiTestCase):

    def setUp(self):
        super().setUp()
        _write(self.box.magic / "decks" / "casual" / "gruul-trial.md", TRIAL_TEXT)
        patcher = mock.patch.object(test_gauntlet_api, "POPULAR",
                                    POPULAR + [(PRECON, "Gruul Trial", "RG", "midrange", "medium")])
        patcher.start()
        self.addCleanup(patcher.stop)
        gauntlet_board.clear_cache()
        self.addCleanup(gauntlet_board.clear_cache)

    def test_the_view_and_summary_leave_out_its_own_precon(self):
        trial = self.call("matt", gauntlet_page.gauntlet_view, TRIAL, "target")
        self.assertEqual(trial["sample"]["decks"], 3)
        self.assertNotIn(PRECON, [o["id"] for o in trial["opponents"]])
        other = self.call("matt", gauntlet_page.gauntlet_view, "casual/gruul-test", "target")
        self.assertEqual(other["sample"]["decks"], 4)            # every other deck plays it
        self.assertIn(PRECON, [o["id"] for o in other["opponents"]])
        with mock.patch.object(self.g, "view", wraps=self.g.view) as viewed:
            summary = self.call("matt", gauntlet_page.gauntlet_summary, TRIAL, "target")
        self.assertIsInstance(summary, dict, summary)
        self.assertEqual(viewed.call_args.args[1]["decks"], [p[0] for p in POPULAR])

    def test_a_run_plays_the_rest(self):
        self.assertEqual(self.set_mode("everyone")["mode"], "everyone")
        answer = self.run_as("matt", TRIAL)
        self.assertIsInstance(answer, dict, answer)
        self.finish()
        job = gauntlet_page.forge_runs.COORD_JOBS.get(gauntlet_page.job_key(
            gauntlet_page.field_page._field_entry(self.forge, TRIAL, "target")[1], SAMPLE, (PRECON,)))
        self.assertNotIn(PRECON, job.fn.sample["decks"])
        self.assertEqual(len(job.fn.sample["decks"]), 3)
        self.assertIn(PRECON, self.g.saved[SAMPLE]["decks"])      # the saved sample is everyone's

    def test_a_deck_of_the_same_list_never_joins_the_trials_run(self):
        # casual/gruul-test has the trial's list (the bought precon): same card_sha, same space.
        self.assertEqual(self.set_mode("everyone")["mode"], "everyone")
        self.playing()
        self.assertIsInstance(self.run_as("matt", TRIAL), dict)
        try:
            twin = self.call("matt", gauntlet_page.gauntlet_view, "casual/gruul-test", "target")
            self.assertEqual(twin["sample"]["decks"], 4)          # its own sample, the precon included
            self.assertIn(PRECON, [o["id"] for o in twin["opponents"]])
            self.assertEqual(self.run_as("matt", "casual/gruul-test"), 409)     # not joined
            trial = self.call("matt", gauntlet_page.gauntlet_view, TRIAL, "target")
            self.assertEqual(trial["sample"]["decks"], 3)
        finally:
            self.finish()
        entry = gauntlet_page.field_page._field_entry(self.forge, TRIAL, "target")[1]
        self.assertNotEqual(gauntlet_page.job_key(entry, SAMPLE, (PRECON,)), gauntlet_page.job_key(entry, SAMPLE))

    def test_the_board_and_library_mark_it(self):
        board = self.call("matt", gauntlet_board.board_view, "constructed")
        rows = {row["deck"]["id"]: row for row in board["rows"]}
        self.assertTrue(rows[TRIAL]["trial"])
        self.assertFalse(rows["casual/gruul-test"]["trial"])
        figure = self.call("matt", library_gauntlet.library_gauntlet_view)
        self.assertTrue(figure["decks"][TRIAL]["trial"])
        self.assertFalse(figure["decks"]["casual/gruul-test"]["trial"])



class CliSampleTests(unittest.TestCase):
    """The command line's plan, play and view leave a trial's own precon out too (cli_gauntlet._house_sample),
    and its "sample" action stays the catalogue's own sample command (no name clash)."""

    def test_house_sample_drops_the_trial_precon(self):
        from decklab import lib
        from decklab.lib.forge import cli_gauntlet
        sample = {"id": SAMPLE, "format": "constructed", "decks": ["a", PRECON, "b"]}
        fake = mock.Mock(format_of=mock.Mock(return_value="constructed"))
        for summary, decks in (({"trial": "GruulTrial_TST"}, ["a", "b"]), ({"trial": None}, ["a", PRECON, "b"]),
                               (None, ["a", PRECON, "b"])):
            with self.subTest(summary=summary), mock.patch.object(cli_gauntlet, "_g", return_value=fake),                     mock.patch.object(cli_gauntlet, "_draw", return_value=sample),                     mock.patch.object(lib.decks, "find_summary", return_value=summary):
                self.assertEqual(cli_gauntlet._house_sample(mock.Mock(), {"id": TRIAL})["decks"], decks)
        self.assertEqual(cli_gauntlet._sample.__code__.co_argcount, 1)

if __name__ == "__main__":
    unittest.main()
