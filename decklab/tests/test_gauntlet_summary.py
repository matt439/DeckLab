"""Tests for a deck's headline against the standard sample of popular decks (E3-S33):
GET /api/gauntlet/summary (api/gauntlet_page.gauntlet_summary).

They run in test_gauntlet_api's sandbox (test_api_permissions' roles and spaces, its FakeForge and
FakeGauntlet), with a FakeGauntlet whose view gives each opponent its own games, so a list can be
untested, partly tested or done. The summary reads saved games only: it never plans, estimates,
saves a sample or plays. No Forge game, network, database or real catalogue is used.

Run from the repo root: python scripts/test_fixtures.py decklab.tests.test_gauntlet_summary
"""
import json
from unittest import mock

from decklab.lib import feature_routes
from decklab.lib.api import gauntlet_page
from decklab.tests.test_gauntlet_api import (ELVES, GRUUL, POPULAR, R_ELVES, SAMPLE, WAIT, FakeGauntlet,
                                             GauntletApiTestCase)

IDS = [p[0] for p in POPULAR]


class PerOpponentGauntlet(FakeGauntlet):
    """FakeGauntlet whose view gives each opponent the games in self.per ({id: (games, rate, verdict,
    updated)}), with forge.gauntlet.view's overall, played, of, tally and updated."""

    def __init__(self, forge, results):
        super().__init__(forge, results)
        self.per = {}

    def plan(self, *args, **kwargs):
        raise AssertionError("the summary never plans")

    def view(self, entry, chosen, keep=None, cat=None):
        self.keeps.append(keep)
        opponents = []
        for deck_id in chosen["decks"]:
            games, rate, verdict, updated = self.per.get(deck_id, (0, None, None, None))
            opponents.append({"id": deck_id, "title": deck_id.rsplit("/", 1)[1], "tier": "medium", "style": "aggro",
                              "games": games, "verdict": verdict, "updated": updated,
                              "rate": {"value": rate, "low": rate - 0.1, "high": rate + 0.1} if games else None,
                              "source": {"kind": "forge", "url": None, "file": "C:/secret.dck"}})
        opponents.sort(key=lambda o: (o["rate"] is None, (o["rate"] or {}).get("low") or 0))
        played = [o for o in opponents if o["games"]]
        tally = {"ahead": 0, "even": 0, "behind": 0, "unsettled": 0}
        for o in played:
            tally[{"ahead": "ahead", "about even": "even", "behind": "behind"}.get(o["verdict"], "unsettled")] += 1
        dates = [o["updated"] for o in played]
        overall = ({"key": "all", "label": "All these opponents", "opponents": len(opponents),
                    "games": sum(o["games"] for o in opponents), "rate": 0.5, "low": 0.4, "high": 0.6,
                    "spread": [0.3, 0.7], "note": ""} if played else None)
        return {"deck": entry["id"], "sample": chosen["id"], "format": chosen["format"], "opponents": opponents,
                "groups": {}, "overall": overall, "played": len(played), "of": len(opponents), "tally": tally,
                "updated": max(dates) if dates else None, "games": sum(o["games"] for o in opponents),
                "note": "Each range covers these 3 sampled opponents only.", "notes": []}


class SummaryTestCase(GauntletApiTestCase):

    def setUp(self):
        super().setUp()
        self.g = PerOpponentGauntlet(self.forge, self.g.results)
        self.forge.gauntlet = self.g

        def never(*args, **kwargs):
            raise AssertionError("the summary never estimates")
        self.forge.estimate.minutes = never

    def summary(self, who, deck_id=GRUUL, version="target"):
        return self.call(who, gauntlet_page.gauntlet_summary, deck_id, version)


class SummaryPrivacyTests(SummaryTestCase):

    def test_a_hidden_deck_answers_as_a_missing_one_first(self):
        self.assertEqual(self.summary("user2", GRUUL), 404)
        self.assertEqual(self.summary("matt", R_ELVES), 404)
        self.assertEqual(self.summary("user2", GRUUL, "nonsense"), 404)      # before the version's 400
        self.g.built = False
        self.assertEqual(self.summary("user2", GRUUL), 404)                  # before anything about the catalogue
        self.assertIsInstance(self.summary("user2", R_ELVES), dict)

    def test_the_raw_id_is_guarded_before_it_is_resolved(self):
        # A renamed deck's old id (an alias) is checked as named, before _field_entry resolves it.
        events = []

        def guarded(target, *args, **kwargs):
            events.append(("guard", target))
            raise gauntlet_page.guard.no_deck(target)
        with mock.patch.object(gauntlet_page.guard, "require_sees_deck", side_effect=guarded), \
                mock.patch.object(gauntlet_page.field_page, "_field_entry",
                                  side_effect=lambda *a: events.append(("entry", a[1]))):
            self.assertEqual(self.summary("matt", "casual/old-gruul"), 404)
        self.assertEqual(events, [("guard", "casual/old-gruul")])

    def test_build_command_is_for_admins_only(self):
        self.g.built = False
        admin, member = self.summary("matt"), self.summary("user1")
        self.assertEqual((admin["state"], member["state"]), ("no_catalogue", "no_catalogue"))
        self.assertEqual(admin["build_command"], "python -m decklab.lib.forge gauntlet build --format constructed")
        self.assertIsNone(member["build_command"])
        self.assertIsNone(self.summary("user1")["sample"])
        self.g.built = True
        self.assertIsNone(self.summary("user1")["build_command"])

    def test_no_title_of_a_house_deck_and_no_file_path(self):
        self.g.per = {i: (100, 0.5, "about even", "2026-11-03T10:00:00") for i in IDS}
        text = json.dumps(self.summary("matt"), allow_nan=False)
        for title in ("Gruul Test", "Elf Commander", "R Elves"):
            self.assertNotIn(title, text)
        self.assertNotIn("secret", text)

    def test_playing_never_names_who_started_it(self):
        self.set_mode("everyone")
        self.playing()
        # Only the explicit start plans its recovery manifest; the read below must not plan.
        with mock.patch.object(self.g, "plan", wraps=FakeGauntlet.plan.__get__(self.g)) as plan:
            self.assertIsInstance(self.run_as("matt", GRUUL), dict)
        plan.assert_called_once()
        self.assertTrue(self.g.started.wait(WAIT))
        found = self.summary("user1")
        self.assertEqual(found["playing"], {"status": "running", "done": 50, "total": 200, "standard": True})
        self.assertNotIn("Matt", json.dumps(found))
        self.assertIsNone(self.summary("user2", R_ELVES)["playing"])       # not their list's run
        self.finish()
        self.assertIsNone(self.summary("user1")["playing"])
        self.assertEqual(self.g.runs[0][1], SAMPLE)                          # the page's default is the standard


class SummaryStateTests(SummaryTestCase):

    def test_untested_partial_and_done(self):
        found = self.summary("matt")
        self.assertEqual((found["state"], found["played"], found["of"], found["games"], found["overall"]),
                         ("untested", 0, 3, 0, None))
        self.assertEqual(found["sample"], {"id": SAMPLE, "size": 24, "tiers": ["medium", "hard"]})
        self.assertEqual(found["deck"], {"id": GRUUL, "version": "target"})
        self.g.per = {IDS[0]: (100, 0.31, "behind", "2026-11-02T10:00:00")}
        found = self.summary("matt")
        self.assertEqual((found["state"], found["played"], found["of"], found["games"]), ("partial", 1, 3, 100))
        self.assertEqual(found["overall"]["label"], "All these opponents")
        self.g.per.update({IDS[1]: (100, 0.62, "ahead", "2026-11-03T09:00:00"),
                           IDS[2]: (100, 0.48, "about even", "2026-11-01T10:00:00")})
        found = self.summary("matt")
        self.assertEqual((found["state"], found["played"], found["games"]), ("done", 3, 300))
        self.assertEqual(found["tally"], {"ahead": 1, "even": 1, "behind": 1, "unsettled": 0})
        self.assertEqual(found["updated"], "2026-11-03T09:00:00")
        self.assertEqual([h["title"] for h in found["hardest"]], ["goblins", "elf-rally", "wall-of-ice"])
        self.assertEqual(set(found["hardest"][0]), {"title", "tier", "style", "rate", "low", "high", "verdict",
                                                    "source"})
        self.assertEqual((found["hardest"][0]["rate"], found["hardest"][0]["verdict"]), (0.31, "behind"))
        self.assertNotIn("file", found["hardest"][0]["source"])
        self.assertIn("sampled opponents only", found["note"])
        self.assertEqual(set(found), {"deck", "format", "state", "playing", "overall", "played", "of", "games",
                                      "tally", "hardest", "updated", "sample", "note", "notes", "build_command", "before",
                                      "compare", "older"})

    def test_a_commander_deck_with_no_standard_decks(self):
        found = self.summary("matt", ELVES)
        self.assertEqual((found["format"], found["state"], found["of"]), ("commander", "untested", 0))

    def test_only_this_lists_games_against_gauntlet_decks_count(self):
        self.summary("matt")
        keep = self.g.keeps[-1]
        entry = gauntlet_page.field_page._field_entry(self.forge, GRUUL, "target")[1]
        sha = entry["card_sha"]
        self.assertTrue(keep({"sides": [{"card_sha": sha, "id": GRUUL}, {"card_sha": "d" * 64, "id": IDS[0]}]}))
        self.assertFalse(keep({"sides": [{"card_sha": sha, "id": GRUUL}, {"card_sha": "e" * 64, "id": ELVES}]}))
        self.assertFalse(keep({"sides": [{"card_sha": "f" * 64, "id": GRUUL}, {"card_sha": "d" * 64, "id": IDS[0]}]}))

    def test_it_never_plans_estimates_saves_or_plays(self):
        self.g.per = {i: (100, 0.5, "about even", "2026-11-03T10:00:00") for i in IDS}
        self.assertEqual(self.summary("matt")["state"], "done")
        self.assertEqual((self.g.saved, self.g.runs, self.g.plans), ({}, [], []))
        self.assertEqual(self.g.draws, [24])          # the standard sample, drawn once and not saved

    def test_the_route_answers_200_while_a_run_plays(self):
        handler = mock.Mock(command="GET")
        handler._query.return_value = {"id": GRUUL}
        with mock.patch.object(gauntlet_page, "gauntlet_summary", return_value={"playing": {"status": "running"},
                                                                                "status": "running"}) as called:
            self.assertTrue(feature_routes.dispatch(handler, ["gauntlet", "summary"], {}))
        called.assert_called_once()
        handler._send_json.assert_called_once_with(200, {"playing": {"status": "running"}, "status": "running"})


if __name__ == "__main__":
    import unittest
    unittest.main()
