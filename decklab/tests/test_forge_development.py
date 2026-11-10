"""Optional round protocol, pooling and warm deltas over disposable synthetic game logs."""
import copy
import unittest
from unittest import mock

from decklab.lib.forge import cardlog, development, development_data as data, lists, logreader, pool_models
from decklab.tests.test_forge_cardlog import HEADER, Script, dl
from decklab.lib.api import development as development_api
from decklab.tests.test_role_cards import RoleCardsTestCase, GHALTA_ID
from decklab.tests.test_deck_privacy_readers import _as
from decklab.tests.test_web import NODE, _run_page


def observed(lands=2, drawn=1, rounds=2):
    return data.game({1: {round: (lands+round-1, drawn+round-1) for round in range(1, rounds+1)},
                      2: {round: (lands+round, drawn+round) for round in range(1, rounds+1)}}, lambda seat: seat-1)


class DevelopmentDataTests(unittest.TestCase):
    def test_histograms_merge_median_observed_spread_and_missing_rounds(self):
        first, second = observed(), observed(4, 3, 1)
        before = copy.deepcopy((first, second))
        merged = data.merge(data.merge(None, first), second)
        self.assertTrue(data.valid(merged, 2))
        pooled = data.pooled()
        data.add_side(pooled, merged, 0, 3)
        summary = data.summary(pooled)
        self.assertEqual((summary["games"], summary["untallied"]), (2, 1))
        self.assertEqual(summary["rounds"][0], {"round": 1, "games": 2,
            "lands": {"median": 3, "low": 2, "high": 4}, "drawn": {"median": 2, "low": 1, "high": 3}})
        self.assertEqual(summary["rounds"][1]["games"], 1)
        self.assertIsNone(summary["rounds"][2]["lands"])
        self.assertEqual((first, second), before)

    def test_legacy_invalid_and_partial_protocol_are_unknown_not_zero(self):
        for value in (None, {}, {**observed(), "games": True}, {**observed(), "v": 2}):
            self.assertFalse(data.valid(value))
            pooled = data.pooled()
            data.add_side(pooled, value, 0, 3)
            self.assertEqual((pooled["games"], pooled["untallied"]), (0, 3))
        broken = observed()
        broken["rounds"][1].pop("2")
        self.assertFalse(data.valid(broken))
        broken = observed()
        broken["rounds"][0]["1"]["lands"]["NaN"] = 1
        self.assertFalse(data.valid(broken))
        self.assertIsNone(data.game({1: {1: (1, 2)}, 2: {}}, lambda seat: seat-1))

    def test_delta_and_card_record_merge_preserve_optional_subset_coverage(self):
        first = cardlog.new_record()
        first["games"] = 1
        first["development"] = observed()
        before = copy.deepcopy(first)
        second = cardlog.new_record()
        second["games"] = 1
        second["development"] = observed(4, 3, 1)
        both = cardlog.merge_record(copy.deepcopy(first), second)
        difference = pool_models._cards_delta(both, before)
        self.assertEqual(difference["development"], second["development"])
        rebuilt = cardlog.merge_record(copy.deepcopy(first), difference)
        self.assertEqual(rebuilt, both)
        legacy = cardlog.new_record()
        legacy["games"] = 3
        mixed = cardlog.merge_record(legacy, first)
        pooled = data.pooled()
        data.add_side(pooled, mixed["development"], 0, mixed["games"])
        self.assertEqual((pooled["games"], pooled["untallied"]), (1, 3))
        self.assertEqual(first, before)


class DevelopmentProtocolTests(unittest.TestCase):
    def read(self, packets):
        script = Script().keep([1, 3, 5], [21, 23, 24])
        if packets:
            script.lines.append(packets[0])
        script.at(2).at(3)
        script.lines.extend(packets[1:])
        script.finish()
        reader = logreader.LogReader(0, card_log=True)
        for line in [HEADER, *script.lines]:
            reader.feed(line)
        return reader.cards

    def test_new_packets_count_both_seats_and_leave_existing_statistics_identical(self):
        packets = [dl("development", 1, "start"), dl("development", 1, 1, 1, 2, 1),
                   dl("development", 1, 1, 2, 3, 2)]
        normal, tallied = self.read([]), self.read(packets)
        value = tallied.pop("development")
        self.assertEqual(tallied, normal)
        self.assertTrue(data.valid(value, normal["games"]))
        self.assertEqual(value["games"], 1)
        self.assertEqual(value["rounds"][0]["1"]["drawn"], {"1": 1})

    def test_optional_bad_or_incomplete_packets_do_not_poison_normal_card_data(self):
        normal = self.read([])
        for packets in ([dl("development", 2, "start")],
                        [dl("development", 1, "start"), dl("development", 1, 1, 1, 2, 1)],
                        [dl("development", 1, "start"), dl("development_error", 1)]):
            value = self.read(packets)
            optional = value.pop("development")
            self.assertEqual(value, normal)
            self.assertEqual((optional["games"], optional["bad"]), (0, 1))


class DevelopmentPoolingTests(unittest.TestCase):
    def test_visibility_filter_runs_before_counting_and_experiment_arms_never_enter(self):
        sections = {"Deck": []}
        sha = lists._list_text(lists._section_cards(sections), "constructed")[1]
        record = {"v": cardlog.RECORD_VERSION, "games": 1, "development": observed()}
        result = {"key": "own", "sides": [{"card_sha": sha}, {"card_sha": "other"}],
                  "batches": [{"games": [{}], "cards": record}]}
        hidden = {**result, "key": "hidden", "batches": [{"games": [{}]*1000, "cards": {"development": "PRIVATE"}}]}
        arm = {**result, "kind": "placebo"}
        before = copy.deepcopy((result, hidden, arm))
        answer = development.list_development(sections, "constructed", [result, hidden, arm], keep=lambda row: row["key"] != "hidden")
        self.assertEqual((answer["games"], answer["untallied"], answer["matchups"]), (1, 0, 1))
        self.assertEqual((result, hidden, arm), before)

    def test_legacy_batches_say_no_tallied_games_without_fabricating_zero_rounds(self):
        sections = {"Deck": []}
        sha = lists._list_text(lists._section_cards(sections), "constructed")[1]
        record = {"v": cardlog.RECORD_VERSION, "games": 12}
        result = {"sides": [{"card_sha": sha}, {"card_sha": "other"}], "batches": [{"games": [{}]*12, "cards": record}]}
        answer = development.list_development(sections, "constructed", [result])
        self.assertEqual((answer["games"], answer["untallied"]), (0, 12))
        self.assertIn("No tallied", answer["why"])
        self.assertTrue(all(row["lands"] is None and row["drawn"] is None for row in answer["rounds"]))


class DevelopmentApiTests(RoleCardsTestCase):
    def test_hidden_deck_refused_before_saved_results_and_optional_failure_is_neutral(self):
        with _as("user2"), mock.patch.object(development_api, "_forge_module", side_effect=AssertionError("hidden")) as load:
            self.assertApiError(404, development_api.development_view, GHALTA_ID)
        load.assert_not_called()
        with mock.patch.object(development_api, "_forge_module", side_effect=RuntimeError("PRIVATE DETAILS")):
            answer = development_api.development_view(GHALTA_ID)
        self.assertEqual(answer["games"], 0)
        self.assertNotIn("PRIVATE", str(answer))

    def test_filter_and_current_list_pilot_are_passed_without_loading_inventory(self):
        from decklab.lib import forge
        from decklab.lib.api import forge_runs
        with mock.patch.object(forge.development, "list_development", return_value={"games": 3}) as read, \
                mock.patch.object(development_api, "_forge_module", return_value=forge), \
                mock.patch.object(forge_runs._Seen, "result", return_value=False) as sees, \
                mock.patch.object(forge.pilots, "pilot_for", return_value={"profile": "Default", "switches": []}), \
                mock.patch.object(development_api.common, "_log") as log:
            answer = development_api.development_view(GHALTA_ID)
            self.assertTrue(read.called, log.call_args_list)
            self.assertFalse(read.call_args.kwargs["keep"]({"key": "hidden"}))
        self.assertEqual(answer, {"games": 3})
        self.assertEqual(read.call_args.kwargs["pilot"], {"profile": "Default", "switches": []})
        sees.assert_called_once()


@unittest.skipUnless(NODE, "needs Node.js")
class DevelopmentUiTests(unittest.TestCase):
    def test_real_renderer_shows_observed_ranges_unknown_data_and_ignores_stale_profile(self):
        tallied = {"games": 2, "untallied": 4, "bad": 1, "note": "Actual draws exclude opening hands.",
                   "rounds": [{"round": 1, "games": 2, "lands": {"median": 2.5, "low": 2, "high": 3},
                               "drawn": {"median": 1, "low": 0, "high": 2}},
                              {"round": 2, "games": 0, "lands": None, "drawn": None}]}
        import json
        text, empty, stale = _run_page([
            "await (async()=>{state.profile={id:'matt'};api=async()=>(" + json.dumps(tallied) + ");const part=deckDevelopmentPart({summary:{id:'casual/example'}});part.isConnected=true;await new Promise(r=>setTimeout(r,5));return part;})()",
            "await (async()=>{api=async()=>({games:0,why:'No tallied development games yet.'});const part=deckDevelopmentPart({summary:{id:'casual/example'}});part.isConnected=true;await new Promise(r=>setTimeout(r,5));return part;})()",
            "await (async()=>{let reply;api=()=>new Promise(r=>reply=r);const part=deckDevelopmentPart({summary:{id:'casual/example'}});part.isConnected=true;await new Promise(r=>setTimeout(r,5));state.profile={id:'user1'};reply({games:100,why:'STALE PRIVATE RESULT'});await Promise.resolve();return part;})()"
        ])
        self.assertIn("2 tallied list appearances", text)
        self.assertIn("2.5 (2–3)", text)
        self.assertIn("0–2", text)
        self.assertIn("—", text)
        self.assertIn("No tallied", empty)
        self.assertNotIn("Lands in play", empty)
        self.assertNotIn("STALE", stale)
