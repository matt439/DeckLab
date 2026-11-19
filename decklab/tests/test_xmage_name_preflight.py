"""Guarded, no-process checks for the exact-name native qualification plan and its pass/fail boundary."""
from copy import deepcopy
import json
from pathlib import Path
import unittest

from decklab.lib.crosscheck import adapters, model
from scripts import xmage_qualify as qualify

RECORDED = {
    "preflight-diacritics": "cc450bd98e28864c60a6302571d812469198bc40cd908bf4b28005cf8dc12123",
    "preflight-adventures": "a4f2b28f01626d29c878ec5a6cb0cf29abe713fbaa5017bd629323339a2ed9e7",
    "preflight-invented-accent": "a7da77e976652ae88dfaa7c4f8273ae1b928e7ebf0718cfc607354531afcdc9a",
    "preflight-incomplete-adventure": "e81b76cd411573e9afbe43eb682884368a9eb773295bcba5764e01f2c8de1f40",
}
PROVENANCE = {
    "source_revision": "79aec614fc29d0c3eebd10fff0d5c1b40852bd52",
    "engine_sha256": "596c4ca03d3be39230714bf28672543d30109c9c8eb8396d6f0ecdec20a67805",
    "bridge_sha256": "56f42a4e14522484d0333a7b7e5928e89f4c02c8ec82c305eeff02948c23eb67",
    "bridge_source_sha256": "17bbb671960da8e1dc9c643b8831a92b22e5a44efadab5c948c2f98727866fcb",
    "identity_sha256": "2ce84b37e1c3b47acec1a20675ee03a1dafa26c52527626bc087de309fd7edcc",
}


def recorded(name):
    folder = Path(__file__).parent / "fixtures" / "crosscheck"
    return tuple(json.loads((folder / f"{name}.{kind}.json").read_text(encoding="utf-8"))
                 for kind in ("request", "result"))


class RecordedXmageNameTests(unittest.TestCase):
    """Actual pinned-runtime preflight responses, not requirements on this PC's installed Java."""

    def test_actual_name_admissions_and_refusals_bind_exact_requests_and_never_count_games(self):
        for name, digest in RECORDED.items():
            with self.subTest(name=name):
                request, result = recorded(name)
                self.assertEqual(model.digest(request), digest)
                self.assertEqual(result["request_sha256"], digest)
                self.assertEqual({k: result[k] for k in PROVENANCE}, PROVENANCE)
                game, _ = adapters.validate_response(result, "xmage", request,
                                                      PROVENANCE["identity_sha256"], PROVENANCE)
                self.assertIsNone(game)
                qualify.verify_preflight(name, request, result)

    def test_a_refused_exact_name_cannot_acquire_a_winner_or_turn_count(self):
        for name in ("preflight-invented-accent", "preflight-incomplete-adventure"):
            request, result = recorded(name)
            for key, value in (("winner", "subject"), ("turns", 1)):
                with self.subTest(name=name, field=key):
                    changed = deepcopy(result)
                    changed["games"][0][key] = value
                    with self.assertRaises(model.CrosscheckError):
                        adapters.validate_response(changed, "xmage", request,
                                                   PROVENANCE["identity_sha256"], PROVENANCE)

    def test_recorded_alias_admission_cannot_be_reused_for_another_spelling(self):
        request, result = recorded("preflight-diacritics")
        request["decks"][0]["main"][1]["name"] = "Anduríl, Flame of the West"
        with self.assertRaises(model.CrosscheckError):
            adapters.validate_response(result, "xmage", request, PROVENANCE["identity_sha256"], PROVENANCE)


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
                     "preflight-adventure-front-only", "preflight-adventure-back-only", "preflight-unimplemented",
                     "preflight-incomplete-adventure"):
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
        for count in (0, 2):
            with self.subTest(stubs=count):
                result = response(name)
                result["games"] *= count
                with self.assertRaisesRegex(AssertionError, "game"):
                    qualify.verify_preflight(name, manifest, result)
