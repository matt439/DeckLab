"""Visible current-list cache fences, queue reuse and read-only public land trials."""
import json
import sys
from unittest import mock

from decklab.lib import api, cards, decks, goldfish
from decklab.lib.api import guard, practice
from decklab.tests.test_collection_edit import CollectionEditTestCase
from decklab.tests.test_api import FIXTURES


class LandTrialApiTests(CollectionEditTestCase):
    def setUp(self):
        super().setUp()
        sys.modules["decklab.lib.goldfish"] = goldfish
        source = self.box.root / "practice-cards.jsonl"
        source.write_text((FIXTURES / "default_cards.jsonl").read_text(encoding="utf-8") + "\n" +
                          (FIXTURES / "goldfish_cards.jsonl").read_text(encoding="utf-8"), encoding="utf-8")
        index = cards.build_index(source, FIXTURES / "oracle_tags.jsonl", {}, log=lambda *args: None)
        index_path = self.box.root / "practice-index.json.gz"
        cards.write_index(index, index_path)
        previous = cards._index
        self.addCleanup(setattr, cards, "_index", previous)
        cards.load(index_path)
        self.box.stack.enter_context(mock.patch.object(goldfish.runs, "CACHE_DIR", self.box.data / "goldfish"))
        self.box.stack.enter_context(mock.patch.object(goldfish.runs, "default_workers", return_value=1))
        self.box.stack.enter_context(mock.patch.object(practice, "GOLDFISH_SETTINGS", {"games": 12, "turns": 4}))

    def baseline(self):
        api.goldfish("casual/gruul-test")
        self.box.wait_for_jobs()
        return api.goldfish("casual/gruul-test")["result"]

    def request(self, result):
        return json.dumps({"id": "casual/gruul-test", "version": "target", "cut": "Llanowar Elves", "cache_key": result["cache_key"]})

    def test_explicit_trial_uses_same_queue_and_never_changes_deck(self):
        with self.as_("matt"):
            before = decks.load_deck("casual/gruul-test")
            baseline = self.baseline()
            body = self.request(baseline)
            self.assertIn(practice.what_if(body)["status"], ("running", "done"))
            self.box.wait_for_jobs()
            result = practice.what_if(body)
            self.assertEqual(result["status"], "done")
            self.assertEqual(result["result"]["settings"]["seed"], baseline["seed"])
            self.assertTrue(any(key.startswith("goldfish-land:") for key in practice.JOBS._jobs))
            self.assertEqual(decks.load_deck("casual/gruul-test"), before)
            self.assertEqual(self.writes, [])

    def test_hidden_deck_precedes_bad_version_cut_or_key_and_public_is_intrinsic(self):
        body = json.dumps({"id": "casual/gruul-test", "version": "bad", "cut": {}, "cache_key": False})
        with self.as_("user2"):
            self.assertApiError(404, practice.what_if, body)
            self.assertApiError(404, api.goldfish, "casual/gruul-test", "bad", "bad")
        with self.as_("matt"):
            baseline = self.baseline()
        with self.as_("user2"), mock.patch.object(guard, "public_deck_spaces", return_value={"home"}):
            self.assertIn(practice.what_if(self.request(baseline))["status"], ("running", "done"))
            self.box.wait_for_jobs()
            answer = practice.what_if(self.request(baseline))
            self.assertEqual(answer["status"], "done")
            self.assertNotRegex(json.dumps(answer), "sleeves|deck_box|on_the_way|owned|holder")

    def test_stale_key_and_unfinished_baseline_do_not_submit_and_failed_trial_can_retry(self):
        with self.as_("matt"):
            self.assertApiError(409, practice.what_if, self.request({"cache_key": "0" * 40}))
            self.assertEqual(practice.JOBS._jobs, {})
            baseline = self.baseline()
            body = self.request(baseline)
            with mock.patch.object(goldfish.whatif, "run", side_effect=RuntimeError("private path")):
                practice.what_if(body)
                self.box.wait_for_jobs()
            failure = practice.what_if(body)
            self.assertEqual(failure, {"status": "error", "error": practice.RUN_FAILED})
            self.assertNotIn("private path", json.dumps(failure))
            retry = json.loads(body); retry["retry"] = True
            self.assertIn(practice.what_if(json.dumps(retry))["status"], ("running", "done"))
            self.box.wait_for_jobs()
            self.assertEqual(practice.what_if(body)["status"], "done")
