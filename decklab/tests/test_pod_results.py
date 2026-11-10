"""Pod results use the existing visible projection, one pinned alias matcher and no extra reads."""
import copy
import json
import unittest
from types import SimpleNamespace
from unittest import mock

from decklab.lib import access, cards, inventory, state
from decklab.lib.api import play_pods, play_records as play, pod_results
from decklab.lib.forge.cardstats import wilson
from decklab.tests import household_config
from decklab.tests.test_api import ApiTestCase, ELF_COMMANDER, _write


TARGET = "commander/pod-stats"


def entry(number, result="s1", count=3, *, label="Private external leader", deck_id=TARGET, space="home"):
    return {"record": {"id": f"{number:032x}", "mode": "pod", "game_version": 2, "space": space,
            "result": result, "notes": "Never quote fixture notes",
            "seats": [{"seat_id": "s1", "type": "deck", "deck": {"id": deck_id}},
                      *[{"seat_id": f"s{index}", "type": "external", "commander": label}
                        for index in range(2, count + 1)]]}}


class PodResultRulesTests(unittest.TestCase):
    def result(self, entries, own="home"):
        return pod_results.summarise(entries, lambda deck_id: deck_id == TARGET, own)

    def test_minimum_is_decided_games_and_no_rates_or_rankings_escape_early(self):
        records = [entry(index, "s2") for index in range(9)] + [entry(100 + index, "draw") for index in range(20)]
        self.assertEqual(self.result(records), {"status": "insufficient", "minimum_games": 10})

    def test_varying_table_sizes_fair_share_wilson_and_draw_denominators(self):
        records = [entry(index, "s1" if index in (0, 5, 7) else "s2", 3 if index < 5 else 4) for index in range(10)]
        records.extend([entry(20, "draw", 3), entry(21, "draw", 4)])
        before = copy.deepcopy(records)
        result = self.result(records)
        self.assertEqual((result["wins"], result["decided"], result["draws"]), (3, 10, 2))
        self.assertAlmostEqual(result["fair_share"], (5 / 3 + 5 / 4) / 10)
        low, high = wilson(3, 10)
        self.assertEqual(result["range"], {"low": low, "high": high})
        self.assertEqual(records, before)
        self.assertNotIn("Never quote fixture notes", json.dumps(result))

    def test_unresolved_repeated_target_invalid_result_and_duplicate_record_cannot_inflate_results(self):
        records = [entry(index) for index in range(10)]
        ambiguous = entry(30)
        ambiguous["record"]["seats"][1] = {"seat_id": "s2", "type": "deck", "deck": {"id": TARGET}}
        hidden = entry(31)
        hidden["record"]["seats"][0]["deck"] = {"hidden": True, "title": "A private deck"}
        result = self.result([*records, records[0], ambiguous, hidden, entry(32, "unknown"), entry(33, [])])
        self.assertEqual((result["wins"], result["decided"], result["excluded"]), (10, 10, 3))

    def test_outside_winners_are_literal_case_folded_bounded_and_recorder_only(self):
        labels = ["Leader // Face, Partner"] * 4 + ["Second"] * 3 + ["Third"] * 2 + ["Fourth"]
        records = [entry(index, "s2", label=label) for index, label in enumerate(labels)]
        result = self.result(records)
        self.assertEqual(result["outside_winners"], [{"commander": "Leader // Face, Partner", "wins": 4},
                         {"commander": "Second", "wins": 3}, {"commander": "Third", "wins": 2}])
        for space in ("user2", None):
            self.assertEqual(self.result(records, space)["outside_winners"], [])
        projected = copy.deepcopy(records)
        for item in projected:
            item["record"].pop("space")
        self.assertEqual(self.result(projected)["outside_winners"], [])

    def test_an_unresolved_visible_selector_is_not_assumed_to_be_a_different_deck(self):
        records = [entry(index) for index in range(10)]
        unresolved = entry(30)
        unresolved["record"]["seats"][1] = {"seat_id": "s2", "type": "deck", "deck": {"id": "unresolved"}}
        def matches(deck_id):
            if deck_id == "unresolved":
                raise ValueError("Unknown alias")
            return deck_id == TARGET
        result = pod_results.summarise([*records, unresolved], matches, "home")
        self.assertEqual((result["decided"], result["excluded"]), (10, 1))

    def test_pinned_alias_resolution_counts_renamed_decks_without_any_further_reader(self):
        records = [entry(index, deck_id="commander/old-name") for index in range(10)]
        snapshot = SimpleNamespace(deck_aliases={"commander/old-name": TARGET})
        with mock.patch.object(inventory, "current", side_effect=AssertionError("No new inventory read")), \
                mock.patch.object(state, "store", side_effect=AssertionError("No new state read")), \
                mock.patch.object(cards, "card", side_effect=AssertionError("No card read")):
            result = play_pods.summary(records, TARGET, snapshot, {"id": "matt", "space": "home"})
        self.assertEqual((result["wins"], result["decided"]), (10, 10))


class PodSummaryApiTests(ApiTestCase):
    def setUp(self):
        super().setUp()
        household_config.use(self)
        identity = access.using({"profile": "matt", "email": "matt@example.com", "remote": True})
        identity.__enter__()
        self.addCleanup(identity.__exit__, None, None, None)
        _write(self.box.magic / "decks/commander/pod-stats.md", ELF_COMMANDER.replace("Elf Commander", "Pod statistics fixture").replace("wife", "user"))
        self.snapshot = play._snapshot(TARGET, "target")

    def seed(self, count=10):
        for index in range(count):
            content = entry(index + 1, "s1" if index % 3 == 0 else "s2")["record"]
            content["seats"][0]["deck"] = copy.deepcopy(self.snapshot)
            for seat in content["seats"]:
                seat["player"] = "Private fixture player"
            record = {**content, "version": 1, "kind": "games", "revision": 1,
                      "date": "2026-10-28", "created_on": "2026-10-28T00:00:00+00:00",
                      "updated_on": "2026-10-28T00:00:00+00:00", "updated_by": "Matt"}
            self.box.state.play_put("games", record, None, state.Actor("matt", "Matt"), "Seed fixture pod")

    def test_filtered_overview_rolls_up_its_own_projection_and_never_writes(self):
        self.seed()
        count = len(self.box.state.changes())
        with mock.patch.object(self.box.state, "play_list", wraps=self.box.state.play_list) as read:
            answer = play.play_overview(TARGET)
        self.assertEqual((answer["pod_summary"]["wins"], answer["pod_summary"]["decided"]), (4, 10))
        self.assertEqual(read.call_args_list, [mock.call("games"), mock.call("sideboards")])
        self.assertEqual(len(self.box.state.changes()), count)
        self.assertNotIn("pod_summary", play.play_overview())

    def test_hidden_games_never_count_and_public_outsiders_never_receive_private_labels(self):
        self.seed()
        self.box.state.visibility_set("home", "decks", True, state.Actor("matt", "Matt"), "Publish fixture decks")
        with access.using({"profile": "user2", "email": "user2@example.com", "remote": True}):
            hidden = play.play_overview(TARGET)
        self.assertEqual(hidden["pods"], [])
        self.assertEqual(hidden["pod_summary"], {"status": "insufficient", "minimum_games": 10})
        self.box.state.visibility_set("home", "games", True, state.Actor("matt", "Matt"), "Publish fixture games")
        with access.using({"profile": "user2", "email": "user2@example.com", "remote": True}):
            shown = play.play_overview(TARGET)
        self.assertEqual(shown["pod_summary"]["decided"], 10)
        self.assertEqual(shown["pod_summary"]["outside_winners"], [])
        self.assertNotIn("Private external leader", json.dumps(shown))

    def test_optional_rollup_failure_keeps_the_game_records_without_claiming_zero_results(self):
        self.seed()
        with mock.patch.object(pod_results, "summarise", side_effect=ValueError("Never echo private error")):
            answer = play.play_overview(TARGET)
        self.assertEqual(answer["pod_summary"], {"status": "unavailable", "minimum_games": 10})
        self.assertEqual(len(answer["pods"]), 10)
        self.assertNotIn("Never echo private error", json.dumps(answer))
