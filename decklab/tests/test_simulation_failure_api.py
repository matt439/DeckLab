"""Failed field/popular runs retain their explanation through the real job/API boundary.

Every run is a fixture exception: no Forge process, live data or network is used.
"""
from unittest import mock

from decklab.lib import api
from decklab.lib.api import gauntlet_page
from decklab.tests.test_field_api import ELVES, FieldApiTestCase
from decklab.tests.test_gauntlet_api import GRUUL, GauntletApiTestCase


FAILURE = ("No new games could be played. Forge doesn't know this card, so the matchup can't be played: "
           "Test Card.")


class FieldFailureApiTests(FieldApiTestCase):

    def check_failure(self, saved_games):
        self.field.games = saved_games
        with mock.patch.object(self.field, "run_field", side_effect=self.forge.ForgeError(FAILURE)):
            self.play()
            self.finish()
        answer = api.field_view(ELVES, "target", "matt")
        self.assertEqual(answer["error"], FAILURE)
        self.assertEqual(answer["status"], "done" if saved_games else "error")
        self.assertIsNone(answer["job"])
        self.assertIsNone(answer["notice"])
        self.assertTrue(all(o["games"] == saved_games for o in answer["opponents"]))

    def test_failed_first_run_keeps_the_reason(self):
        self.check_failure(0)

    def test_saved_games_do_not_hide_a_failed_top_up(self):
        self.check_failure(200)


class PopularFailureApiTests(GauntletApiTestCase):

    def check_failure(self, saved_games):
        self.g.games = saved_games
        with mock.patch.object(self.g, "run", side_effect=self.forge.ForgeError(FAILURE)):
            answer = self.run_as("matt", GRUUL)
            self.assertIsInstance(answer, dict, answer)
            self.finish()
        answer = self.call("matt", gauntlet_page.gauntlet_view, GRUUL, "target")
        self.assertIsInstance(answer, dict, answer)
        self.assertEqual(answer["error"], FAILURE)
        self.assertEqual(answer["status"], "done" if saved_games else "error")
        self.assertIsNone(answer["job"])
        self.assertIsNone(answer["notice"])
        self.assertTrue(all(o["games"] == saved_games for o in answer["opponents"]))

    def test_failed_first_run_keeps_the_reason(self):
        self.check_failure(0)

    def test_saved_games_do_not_hide_a_failed_top_up(self):
        self.check_failure(200)
