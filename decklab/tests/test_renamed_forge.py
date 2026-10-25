"""Renamed decks retain saved Forge evidence, pilot selection and test continuation.

Everything uses captured JSON in a temporary folder or mocked coordinators. No Forge
process starts and the real result/config folders are never written.
"""
import copy
import io
import json
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from decklab.lib import decks, inventory
from decklab.lib.api import forge_runs, variant_page
from decklab.lib.forge import cli_evaluate, deck_identity, field, pilots, rankings, variants

OLD, CURRENT = "casual/old-name", "casual/new-name"
OLD_OTHER, OTHER = "casual/old-opponent", "casual/opponent"


class RenameFixture(unittest.TestCase):
    def setUp(self):
        self.aliases = {OLD: CURRENT, OLD_OTHER: OTHER}
        patch = mock.patch.object(inventory, "current", return_value=SimpleNamespace(deck_aliases=self.aliases))
        patch.start()
        self.addCleanup(patch.stop)

    @staticmethod
    def entry(deck_id, sha="a"):
        return {"id": deck_id, "version": "target", "title": deck_id, "kind": "constructed",
                "card_sha": sha, "card_count": 60}


class SavedMatchupTests(RenameFixture):
    def test_saved_side_uses_current_title_link_and_list_without_changing_capture(self):
        summary = {"id": CURRENT, "title": "New title", "versions": ["target"], "kind": "casual"}
        captured = {"id": OLD, "title": "Old title", "version": "target", "card_sha": "cards",
                    "card_count": 60, "ai": {"private": "not returned"}}
        original = copy.deepcopy(captured)
        forge = SimpleNamespace(card_sha=mock.Mock(return_value="cards"), ForgeError=ValueError)
        with mock.patch.object(decks, "list_decks", return_value=[summary]), \
                mock.patch.object(decks, "beginner_box_pairings", return_value=[]), \
                mock.patch.object(decks, "load_deck", return_value={}) as load:
            today = forge_runs._TodaysLists(forge)
            answer = today.side(captured)
            self.assertEqual((answer["id"], answer["title"], answer["current"]), (CURRENT, "New title", True))
            self.assertNotIn("ai", answer)
            self.assertTrue(today.same(captured, CURRENT, "target"))
            self.assertEqual(today.sha(OLD, "target"), today.sha(CURRENT, "target"))
            self.assertEqual(load.call_count, 1)
        self.assertEqual(captured, original)

    def test_current_list_change_remains_visible_after_rename(self):
        summary = {"id": CURRENT, "title": "New title", "versions": ["target"], "kind": "casual"}
        forge = SimpleNamespace(card_sha=mock.Mock(return_value="new cards"), ForgeError=ValueError)
        with mock.patch.object(decks, "list_decks", return_value=[summary]), \
                mock.patch.object(decks, "beginner_box_pairings", return_value=[]), \
                mock.patch.object(decks, "load_deck", return_value={}):
            side = forge_runs._TodaysLists(forge).side({"id": OLD, "version": "target", "card_sha": "old cards"})
        self.assertEqual(side["id"], CURRENT)
        self.assertFalse(side["current"])

    def test_pairings_keep_order_independent_comparison(self):
        self.assertTrue(field._same_id("pairing/cats+elves", "pairing/elves+cats"))
        self.assertFalse(field._same_id("pairing/cats+elves", "pairing/elves+dogs"))


class ConfigurationTests(RenameFixture):
    def test_pilot_version_specific_former_key_survives_with_current_generic_key(self):
        data = {"lists": {OLD + "@owned": {"profile": "Cautious", "switches": []},
                          CURRENT: {"profile": "Reckless", "switches": []}},
                "default": pilots.DEFAULT_PILOT, "problems": []}
        original = copy.deepcopy(data)
        with mock.patch.object(pilots, "load", return_value=data):
            self.assertEqual(pilots.pilot_for(CURRENT, "owned")["profile"], "Cautious")
            self.assertEqual(pilots.pilot_for(OLD, "target")["profile"], "Reckless")
        self.assertEqual(data, original)

    def test_conflicting_equal_specificity_keys_choose_current_and_report_conflict(self):
        data = {"lists": {OLD: {"profile": "Cautious", "switches": []},
                          CURRENT: {"profile": "Reckless", "switches": []}},
                "default": pilots.DEFAULT_PILOT, "problems": []}
        with mock.patch.object(pilots, "load", return_value=data), mock.patch.object(pilots.common, "_log") as log, \
                mock.patch.object(pilots, "_logged", set()):
            self.assertEqual(pilots.pilot_for(OLD, "target")["profile"], "Reckless")
            self.assertEqual(pilots.pilot_for(CURRENT, "target")["profile"], "Reckless")
            self.assertEqual(log.call_count, 1)
            problems = pilots.problems()
        self.assertEqual(len(problems), 1)
        self.assertIn("conflicting pilots", problems[0])
        self.assertIn(OLD, problems[0])

    def test_field_former_id_can_select_opponent_and_cannot_select_self(self):
        base = self.entry(CURRENT)
        other = self.entry(OTHER, "b")
        self.assertEqual(field._opponents(base, [OLD_OTHER + "@target"], [base, other]), [other])
        with self.assertRaisesRegex(ValueError, "Not in the"):
            field._opponents(base, [OLD], [base, other])

    def test_historical_rankings_associate_captured_old_identity(self):
        result = {"key": "saved", "format": "Constructed", "sides": [
            {"seen_as": [{"id": OLD, "version": "target"}], "card_sha": "old cards"}]}
        rows = [{"id": CURRENT, "version": "target", "versions": ["target"], "card_sha": "new cards",
                 "_entry": None}]
        with mock.patch.object(rankings.saved, "_stored", return_value=[result]), \
                mock.patch.object(field, "_games", return_value=[{}, {}]):
            stale = rankings._historical(rows, "Constructed", None, {"complete": False})
        self.assertEqual(stale[(CURRENT, "target")], 2)

    def test_inventory_outage_keeps_captured_identity_usable(self):
        with mock.patch.object(inventory, "current", side_effect=inventory.Unavailable("Unavailable")):
            self.assertEqual(deck_identity.canonical(OLD), OLD)
            self.assertEqual(deck_identity.lineage(OLD), (OLD,))
            self.assertEqual(forge_runs._TodaysLists._id(OLD), OLD)


class SavedVariantTests(RenameFixture):
    def summary(self):
        return {"test": "f" * 64, "base": self.entry(OLD), "variant": {"card_sha": "changed"},
                "against": self.entry(OLD_OTHER, "b"), "opponents": [
                    {**self.entry(OLD_OTHER, "b"), "base_key": "key", "paired_key": None,
                     "dropped": None}], "created": "2026-10-01", "looks": [], "mode": "ahead"}

    def test_tests_for_follows_base_alias_without_rewriting_json_or_test_id(self):
        summary = self.summary()
        with tempfile.TemporaryDirectory() as tmp:
            folder = variants._tests_dir(Path(tmp))
            folder.mkdir(parents=True)
            path = folder / (summary["test"] + ".json")
            path.write_text(json.dumps(summary), encoding="utf-8")
            original = path.read_bytes()
            current = variants.tests_for(CURRENT, "target", Path(tmp))
            old = variants.tests_for(OLD, "target", Path(tmp))
            self.assertEqual(current, old)
            self.assertEqual(current[0]["test"], summary["test"])
            self.assertEqual(current[0]["base"]["id"], OLD)
            self.assertEqual(path.read_bytes(), original)

    def test_variant_response_links_and_titles_are_current_without_editing_capture(self):
        summary = self.summary()
        found = {"test": summary, "opponents": summary["opponents"]}
        original = copy.deepcopy(found)
        def find(deck_id):
            canonical = deck_identity.canonical(deck_id)
            return {"id": canonical, "title": "Current " + canonical}
        with mock.patch.object(decks, "find_summary", side_effect=find):
            answer = variant_page._current_test(found)
        self.assertEqual(answer["test"]["base"]["id"], CURRENT)
        self.assertEqual(answer["test"]["against"]["id"], OTHER)
        self.assertEqual(answer["opponents"][0]["title"], "Current " + OTHER)
        self.assertEqual(answer["test"]["test"], summary["test"])
        self.assertEqual(found, original)

    def test_opponent_continuation_uses_captured_record_for_current_id(self):
        summary = self.summary()
        other = self.entry(OTHER, "b")
        record = summary["opponents"][0]
        self.assertIs(variants._opponent_record(summary, other), record)
        with mock.patch.object(variants, "_base_key", return_value="key"):
            self.assertTrue(variants._keys_today(summary, self.entry(CURRENT), [other]))
        self.assertFalse(variants._dropped(summary, other))
        with mock.patch.object(variants, "_play_pair") as play:
            variants._stage({"inflight": 1, "stopping": threading.Event()}, summary, [other], 25)
        play.assert_called_once()
        self.assertIs(play.call_args.args[1], record)
        self.assertEqual(record["id"], OLD_OTHER)
        self.assertIsNone(variants._opponent_record(summary, self.entry(OTHER, "changed cards")))

    def test_resume_filters_current_opponents_by_alias_before_returning_final_capture(self):
        summary = self.summary()
        summary["outcome"] = "better"
        original = copy.deepcopy(summary)
        with mock.patch.object(variants, "_opponent_entries", return_value=[self.entry(OTHER, "b")]), \
                mock.patch.object(variants, "_base_key", return_value="key"):
            answer = variants._run_test(summary["test"], summary, self.entry(CURRENT), {}, "field", True,
                                       "Constructed", "ahead", None, None, by="Fixture", progress=None,
                                       results_dir=None, pool=None, local=False, log_dir=None, log_every=1)
        self.assertIs(answer, summary)
        self.assertEqual(summary, original)

    def test_cli_play_more_accepts_current_id_for_captured_old_base(self):
        summary = self.summary()
        summary["variant"]["cards"] = {"Main": [[60, "Forest"]]}
        args = SimpleNamespace(field=False, against=None, opponents=None, until=None, games=None, quick=False,
                               more=summary["test"], results_dir=None, deck=CURRENT, owned=False,
                               by="Fixture", local=False, json=True)
        with mock.patch.object(cli_evaluate.shared, "_cli_entry", side_effect=[self.entry(CURRENT),
                                                                             self.entry(OTHER, "b")]), \
                mock.patch.object(variants, "load_summary", return_value=summary), \
                mock.patch.object(variants, "variant_entry", return_value={"changes": {"remove": [], "add": []}}), \
                mock.patch.object(variants, "run_test", return_value=summary) as run, \
                mock.patch.object(variants, "view", return_value={"test": summary}), \
                mock.patch("sys.stdout", io.StringIO()), mock.patch("sys.stderr", io.StringIO()):
            self.assertEqual(cli_evaluate._cmd_variant(args), 0)
        self.assertEqual(run.call_args.kwargs["extend"], summary["test"])
