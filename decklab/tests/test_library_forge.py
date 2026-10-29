"""The library's Forge line (E11-S30 slice 8): forge.field.averages over test_forge_field's small tree, and
GET /api/library/forge's visibility, cache and failure over a stubbed field (no Forge process starts).

Run from the repo root: python scripts/test_fixtures.py
"""
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from decklab.lib.api import library_forge as api
from decklab.lib.forge import field
from decklab.tests import test_server as support
from decklab.tests.test_forge_field import FieldTestCase


class AveragesTests(FieldTestCase):

    def test_each_field_list_has_the_field_views_average(self):
        alpha, beta, gamma = self.entry("casual/alpha"), self.entry("casual/beta", "owned"), self.entry("casual/gamma")
        self.fake.add_games(alpha, beta, 200, rate=0.7)
        self.fake.add_games(alpha, gamma, 100, rate=0.4)["updated"] = "2026-10-20T10:00:00+10:00"
        self.fake.store[self.fake.key(alpha, beta)]["updated"] = "2026-10-22T10:00:00+10:00"
        found = field.averages("Constructed", self.results)
        self.assertEqual(set(found), {e["id"] for e in field.field_lists("Constructed")})
        self.assertEqual(found["casual/beta"]["version"], "owned")
        for deck_id, entry in (("casual/alpha", alpha), ("casual/gamma", gamma)):
            self.assertEqual(found[deck_id]["average"], field.view(entry, self.results)["average"])
        self.assertEqual(found["casual/alpha"]["games"], 300)
        self.assertEqual(found["casual/alpha"]["tested"], "2026-10-22T10:00:00+10:00")
        self.assertEqual(found["casual/gamma"]["tested"], "2026-10-20T10:00:00+10:00")
        # A list with no games has no average and no date.
        self.assertIsNone(found["product/aggro"]["average"])
        self.assertEqual((found["product/aggro"]["games"], found["product/aggro"]["tested"]), (0, None))
        json.dumps(found, allow_nan=False)

    def test_the_viewers_field_leaves_hidden_decks_out(self):
        alpha, gamma = self.entry("casual/alpha"), self.entry("casual/gamma")
        self.fake.add_games(alpha, gamma, 100, rate=0.4)
        found = field.averages("Constructed", self.results, visible=lambda deck_id: deck_id != "casual/gamma")
        self.assertNotIn("casual/gamma", found)
        self.assertIsNone(found["casual/alpha"]["average"])
        self.assertEqual(found["casual/alpha"]["games"], 0)

    def test_pair_rates_are_each_saved_pair_s_rate_from_both_sides(self):
        alpha, beta, gamma = self.entry("casual/alpha"), self.entry("casual/beta", "owned"), self.entry("casual/gamma")
        self.fake.add_games(alpha, beta, 200, rate=0.7)
        found = field.pair_rates("Constructed", self.results)
        self.assertEqual(set(found), {("casual/alpha", "casual/beta"), ("casual/beta", "casual/alpha")})
        rows = {o["id"]: o for o in field.view(alpha, self.results)["opponents"]}
        self.assertEqual(found[("casual/alpha", "casual/beta")],
                         {"value": rows["casual/beta"]["rate"]["value"], "games": 200,
                          "versions": ("target", "owned")})
        self.assertEqual(found[("casual/beta", "casual/alpha")]["versions"], ("owned", "target"))
        self.assertGreater(found[("casual/alpha", "casual/beta")]["value"], 0.5)
        self.assertLess(found[("casual/beta", "casual/alpha")]["value"], 0.5)
        # A hidden deck's pairs are left out with it.
        self.fake.add_games(alpha, gamma, 100, rate=0.4)
        hidden = field.pair_rates("Constructed", self.results, visible=lambda deck_id: deck_id != "casual/gamma")
        self.assertFalse(any("casual/gamma" in pair for pair in hidden))
        json.dumps({" ".join(k): v for k, v in found.items()}, allow_nan=False)


AVERAGE = {"value": 0.61, "low": 0.59, "high": 0.63, "counted": 3, "of": 4, "partial": True}


class LibraryForgeApiTests(unittest.TestCase):

    def setUp(self):
        self.results = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.results, True)
        self.forge = mock.Mock()
        self.forge.common._results_dir.return_value = self.results
        self.forge.field.field_lists.return_value = [{"id": "casual/otters", "version": "target", "card_sha": "a"},
                                                     {"id": "casual/hidden", "version": "target", "card_sha": "b"}]
        self.forge.field.averages.return_value = {
            "casual/otters": {"version": "target", "card_sha": "a", "average": AVERAGE, "games": 800,
                              "tested": "2026-10-22T10:00:00+10:00"},
            "casual/hidden": {"version": "target", "card_sha": "b", "average": None, "games": 0, "tested": None}}
        seen = mock.Mock(space="home", everything=False)
        seen.deck.side_effect = lambda deck_id: deck_id != "casual/hidden"
        for target, name, value in ((api.forge_runs, "_forge_module", lambda: self.forge),
                                    (api.forge_runs, "_Seen", lambda: seen),
                                    (api.guard, "public_deck_spaces", lambda: set()),
                                    (api, "_cache", {})):
            patcher = mock.patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.seen = seen

    def test_visible_decks_get_their_rate_and_date(self):
        answer = api.library_forge_view()
        self.assertEqual(answer, {"error": None, "decks": {"casual/otters": {
            "version": "target", "card_sha": "a", "rate": {"value": 0.61, "low": 0.59, "high": 0.63}, "partial": True, "counted": 3,
            "of": 4, "games": 800, "tested": "2026-10-22T10:00:00+10:00"}}})
        args, options = self.forge.field.averages.call_args
        self.assertEqual(args, ("Constructed",))
        self.assertEqual(options["space"], "home")
        self.assertIs(options["visible"], self.seen.deck)
        self.assertTrue(options["product_notes"])

    def test_the_answer_is_cached_until_a_result_or_a_list_changes(self):
        api.library_forge_view()
        api.library_forge_view()
        self.assertEqual(self.forge.field.averages.call_count, 1)
        (self.results / "abc.json").write_text("{}", encoding="utf-8")
        api.library_forge_view()
        self.assertEqual(self.forge.field.averages.call_count, 2)
        self.forge.field.field_lists.return_value = [{"id": "casual/otters", "version": "target", "card_sha": "c"}]
        api.library_forge_view()
        self.assertEqual(self.forge.field.averages.call_count, 3)
        with mock.patch.object(api.time, "monotonic", return_value=api.time.monotonic() + api.CACHE_S + 1):
            api.library_forge_view()
        self.assertEqual(self.forge.field.averages.call_count, 4)
        # Another space's viewer has a field of their own.
        self.seen.space = "user2"
        api.library_forge_view()
        self.assertEqual(self.forge.field.averages.call_count, 5)

    def test_a_failure_is_said_not_shown_as_untested(self):
        self.forge.field.averages.side_effect = RuntimeError("boom")
        with mock.patch.object(api.common, "_log") as log:
            self.assertEqual(api.library_forge_view(), {"decks": {}, "error": api.NO_NUMBERS})
        log.assert_called_once()

    def test_identical_playable_lists_switching_version_invalidate_cached_metadata(self):
        self.assertEqual(api.library_forge_view()["decks"]["casual/otters"]["version"], "target")
        self.forge.field.field_lists.return_value[0]["version"] = "owned"
        self.forge.field.averages.return_value["casual/otters"]["version"] = "owned"
        found = api.library_forge_view()["decks"]["casual/otters"]
        self.assertEqual((found["version"], found["card_sha"]), ("owned", "a"))
        self.assertEqual(self.forge.field.averages.call_count, 2)

    def test_pair_rates_share_the_cache_and_keep_only_visible_pairs(self):
        self.forge.field.pair_rates.return_value = {("casual/otters", "casual/hidden"): {"value": 0.4, "games": 50},
                                                    ("casual/otters", "casual/elves"): {"value": 0.6, "games": 80}}
        self.assertEqual(api.pair_rates(), ({("casual/otters", "casual/elves"): {"value": 0.6, "games": 80}}, None))
        api.pair_rates()
        api.library_forge_view()
        self.assertEqual((self.forge.field.pair_rates.call_count, self.forge.field.averages.call_count), (1, 1))
        args, options = self.forge.field.pair_rates.call_args
        self.assertEqual((args, options["space"]), (("Constructed",), "home"))
        self.forge.field.pair_rates.side_effect = RuntimeError("boom")
        (self.results / "abc.json").write_text("{}", encoding="utf-8")
        with mock.patch.object(api.common, "_log") as log:
            self.assertEqual(api.pair_rates(), ({}, api.NO_NUMBERS))
        log.assert_called_once()


class LibraryForgeHttpTests(support.ServerTestCase):

    def test_get_routes_to_the_cached_numbers_and_starts_no_games(self):
        answer = {"decks": {}, "error": None}
        with mock.patch.object(api, "library_forge_view", return_value=answer) as view:
            self.assertEqual(self.get_json("/api/library/forge"), answer)
            view.assert_called_once_with()
            self.assertError("/api/library/forge?x=1", 400)
            code, headers, _ = self.request("POST", "/api/library/forge", b"{}")
            self.assertEqual((code, headers["Allow"]), (405, "GET, HEAD"))
        self.assertFalse(self.box.forge.runs)


if __name__ == "__main__":
    unittest.main()
