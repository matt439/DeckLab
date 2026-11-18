"""Guarded, no-process checks for the exact-name native qualification plan and its pass/fail boundary."""
from copy import deepcopy
import unittest

from scripts import xmage_qualify as qualify


def response(name):
    supported, requested = qualify.PREFLIGHT_CASES[name]
    return {
        "status": "unsupported",
        "coverage": [
            {"deck_id": "baseline", "status": "supported" if supported else "unsupported",
             "missing": [] if supported else list(requested), "cards": 60 if supported else 59},
            {"deck_id": "opponent", "status": "unsupported", "missing": [qualify.PREFLIGHT_SENTINEL], "cards": 59}],
        "games": [{"status": "unsupported", "winner": None, "turns": 0}],
    }


class XmageNamePreflightTests(unittest.TestCase):
    def test_every_name_case_has_a_deliberately_missing_opponent_and_frozen_exact_names(self):
        fixtures = qualify.fixtures()
        for name, (_, requested) in qualify.PREFLIGHT_CASES.items():
            with self.subTest(name=name):
                manifest, expected = fixtures[name]
                self.assertEqual((manifest["format"], expected), ("casual", "unsupported"))
                self.assertEqual(manifest["decks"][1]["main"], [
                    {"name": "Forest", "quantity": 59}, {"name": qualify.PREFLIGHT_SENTINEL, "quantity": 1}])
                self.assertEqual([r["name"] for r in manifest["decks"][0]["main"]][1:], list(requested))
                self.assertEqual(sum(r["quantity"] for r in manifest["decks"][0]["main"]), 60)
                qualify.verify_preflight(name, manifest, response(name))

    def test_an_unsupported_baseline_cannot_falsely_qualify_canonical_name_admission(self):
        name = "preflight-diacritics"
        manifest = qualify.fixtures()[name][0]
        result = response(name)
        result["coverage"][0].update(status="unsupported", missing=["Andúril, Flame of the West"], cards=59)
        with self.assertRaisesRegex(AssertionError, "canonical list"):
            qualify.verify_preflight(name, manifest, result)

    def test_the_exact_refused_spelling_and_both_adventure_faces_must_survive(self):
        for name in ("preflight-invented-accent", "preflight-wrong-adventure-back",
                     "preflight-adventure-front-only", "preflight-adventure-back-only", "preflight-unimplemented"):
            with self.subTest(name=name):
                manifest = qualify.fixtures()[name][0]
                result = response(name)
                result["coverage"][0]["missing"] = ["A replacement spelling"]
                with self.assertRaisesRegex(AssertionError, "exact card names"):
                    qualify.verify_preflight(name, manifest, result)

    def test_missing_sentinel_or_opponent_coverage_cannot_claim_no_game_qualification(self):
        name = "preflight-adventures"
        manifest = qualify.fixtures()[name][0]
        for changed in ("supported", "missing", "no-coverage", "wrong-deck"):
            with self.subTest(changed=changed):
                result = response(name)
                if changed == "supported":
                    result["coverage"][1].update(status="supported", missing=[], cards=60)
                elif changed == "missing":
                    result["coverage"][1]["missing"] = ["Another missing name"]
                elif changed == "wrong-deck":
                    result["coverage"][1]["deck_id"] = "baseline"
                else:
                    result["coverage"].pop()
                with self.assertRaises(AssertionError):
                    qualify.verify_preflight(name, manifest, result)
        changed = deepcopy(manifest)
        changed["decks"][1]["main"][-1]["name"] = "Forest"
        with self.assertRaisesRegex(AssertionError, "sentinel"):
            qualify.verify_preflight(name, changed, response(name))

    def test_no_coverage_case_can_credit_a_winner_or_game_progress(self):
        name = "preflight-exact-name"
        manifest = qualify.fixtures()[name][0]
        for key, value in (("status", "completed"), ("winner", "subject"), ("turns", 1)):
            with self.subTest(key=key):
                result = response(name)
                result["games"][0][key] = value
                with self.assertRaisesRegex(AssertionError, "game"):
                    qualify.verify_preflight(name, manifest, result)
