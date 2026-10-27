"""Tests for the paired variant tests' API (decklab/lib/api/variant_page.py, simulation wave 3's
R15, forge-trial/sim-wave3-contract.md section 11.5): POST /api/variant/run (the editor's draft
read with the editor's checks; a size change, a sideboard-only change and no change refused;
deck-order-1 needed), GET /api/variant (status, job, words), POST /api/variant/stop and /more
("Play more", refused once the list has changed), GET /api/variants (running tests, "saved") and
GET /api/variant/estimate.

They use the real forge package over test_api's Sandbox, as test_matchups_api's RealForgeTests
do, with forge.variants.run_test replaced by a stand-in that writes a summary (the coordinator
itself is test_forge_variants.py's), and a fresh COORD_JOBS runner per test.

Run from the repo root: python -m unittest decklab.tests.test_variant_api
"""
import json
import os
import sys
import threading
from unittest import mock

from decklab.lib import api, cards, decks, jobs
from decklab.lib import forge as real_forge
from decklab.tests import test_forge
from decklab.tests.test_api import ApiTestCase, _write
from decklab.tests.test_matchups_api import deck_file

GREEN_ID, RED_ID = "casual/green-test", "casual/red-test"
WAIT = 5
ORDER = ["attack-requirements-in-order-1", "deck-order-1"]


def body(**data):
    return json.dumps(data).encode("utf-8")


def editor_list(text):
    """A decklist as the editor sends it to /api/deck/check: {section: [{qty, name, set?, number?}]}."""
    out = {}
    for section, lines in decks.parse_decklist(text).items():
        out[section] = []
        for line in lines:
            item = {"qty": line.quantity, "name": line.name}
            if line.set:
                item["set"] = line.set
                if line.number:
                    item["number"] = line.number
            out[section].append(item)
    return out


SWAPPED = test_forge.GREEN.replace("1 Fiery Annihilation\n", "").replace("2 Giant Growth", "3 Giant Growth")


class VariantApiCase(ApiTestCase):

    def setUp(self):
        super().setUp()
        root = self.box.root
        test_forge.make_forge(root / "forge-app")
        settings = {"forge_dir": str(root / "forge-app"), "forge_java": sys.executable, "forge_workers": 2,
                    "forge_batch_games": 200, "forge_clock_s": 120, "forge_xmx": "1024m",
                    "forge_variant_margin": 0.02, "forge_variant_margin_one": 0.03, "forge_field_inflight": 4}
        self.calls = []
        self.gate = threading.Event()
        self.gate.set()
        self.started = threading.Event()
        for target, name, value in ((real_forge.common, "DATA_DIR", self.box.data / "forge"),
                                    (real_forge.common, "_settings", lambda: dict(settings)),
                                    (real_forge.runner, "build_command", test_forge.fake_command),
                                    (real_forge.ai, "TAG_FILE", test_forge.TAGS_FILE),
                                    (real_forge.variants, "run_test", self.fake_run_test),
                                    (real_forge, "status", lambda *a, **k: {"ready": True, "problem": None}),
                                    (real_forge.engine, "today", lambda kind=None: self.today()),
                                    (api.forge_runs, "COORD_JOBS", api.forge_runs._coord_runner())):
            patch = mock.patch.object(target, name, value)
            patch.start()
            self.addCleanup(patch.stop)
        test_forge.pin_override_sets(self)
        self.patches = ORDER
        self.addCleanup(self.forget)
        self.forget()
        env = mock.patch.dict(os.environ)
        env.start()
        self.addCleanup(env.stop)
        index = cards.build_index(test_forge.HERE / "forge_cards.jsonl", test_forge.TAGS_FILE,
                                  {"default_cards": "2026-09-28"}, log=lambda *a: None)
        cards.write_index(index, cards.INDEX_FILE)
        cards._index = None
        _write(self.box.magic / "decks" / "casual" / "red-test.md", deck_file("Red Test", test_forge.RED))
        _write(self.box.magic / "decks" / "casual" / "green-test.md", deck_file("Green Test", test_forge.GREEN))
        sys.modules["decklab.lib.forge"] = real_forge
        self.addCleanup(sys.modules.__setitem__, "decklab.lib.forge", self.box.forge)
        self.addCleanup(self.drain)

    def today(self):
        deployed = real_forge.engine._deployed(self.box.data / "forge" / "user",
                                               {"index": {}, "hash": real_forge.engine.NO_OVERRIDES})
        real = dict(real_forge.engine._engine("decklab", "2.0.15", 120, list(self.patches), deployed, {}, True))
        return real

    def forget(self):
        real_forge.install._status = None
        real_forge.install._scripts.clear()
        real_forge.saved._read_cache.clear()
        cards._tag_cache.clear()

    def drain(self):
        self.gate.set()
        coord = api.forge_runs.COORD_JOBS
        coord.stop()
        coord.join(WAIT)

    def fake_run_test(self, base_entry, variant_cards, against, mode="ahead", *, by, progress=None, results_dir=None,
                      pool=None, local=False, log_dir=None, log_every=1, opponents=None, extend=None,
                      field_options=None):
        """run_test's stand-in: notes the call, reports some progress, waits for the gate, and writes a
        summary with one look ("better" at 200 games a deck)."""
        v = real_forge.variants
        self.calls.append({"base": base_entry["id"], "against": against if against == "field" else against["id"],
                           "mode": mode, "by": by, "extend": extend})
        variant = v.variant_entry(base_entry, variant_cards)
        tid = extend or v.test_id(base_entry, variant, against, mode,
                                 field_space=(field_options or {}).get("space"))
        opponents_ = [against] if against != "field" else []
        summary = v.load_summary(tid, results_dir) or v._new_summary(tid, base_entry, variant, against, mode,
                                                                      opponents_, 0.03, by, None,
                                                                      (field_options or {}).get("space"))
        v._write_summary(summary, results_dir)
        # The same detail each time: a report replaces the last one's, and run_test never reports None, so a
        # None here would race the test's reading of next_look and pairs.
        detail = {"mode": mode, "stage": 1, "next_look": 200, "games_per_opponent": 200,
                  "pairs": {"k" * 64: {"opponent": {"id": RED_ID}, "done": 100, "total": 200,
                                       "wins": 55, "other": 0, "playing": True}}}
        if progress is not None:
            progress(100, 400, detail)
        self.started.set()
        while not self.gate.wait(0.05):
            if progress is not None:
                progress(100, 400, detail)
        if extend:
            summary["mode"] = "ahead"
            for look in summary["looks"]:
                look["interim"] = True
        summary["looks"].append({"games_per_opponent": 200 * (len(summary["looks"]) + 1), "delta": 0.024,
                                 "low": 0.006, "high": 0.042, "z": 2.6, "bound": 2.008, "interim": False,
                                 "stopped": False, "decision": "better"})
        summary["outcome"] = "better"
        v._write_summary(summary, results_dir)
        return summary

    def start(self, text=SWAPPED, against=None, mode=None, profile="matt", version="target"):
        data = {"profile": profile, "id": GREEN_ID, "version": version, "list": editor_list(text),
                "against": against or {"id": RED_ID, "version": "target"}}
        if mode is not None:
            data["mode"] = mode
        return api.run_variant(body(**data))

    def wait_done(self, test):
        job = api.forge_runs.COORD_JOBS.get(f"variant:{test}")
        self.assertTrue(job.wait(WAIT))
        return api.variant_view(test)


class RunTests(VariantApiCase):

    def test_a_live_base_matchup_keeps_its_score_and_range_in_the_requested_order(self):
        self.gate.clear()
        answer = self.start(mode="quick")
        self.assertTrue(self.started.wait(WAIT))
        test_id = answer["test"]["test"]
        coord = api.forge_runs.COORD_JOBS
        job = coord.get(f"variant:{test_id}")
        snap = coord.snapshot(job)
        key = real_forge.engine.matchup_key(job.fn.base, job.fn.against)
        variant = real_forge.variants.variant_entry(job.fn.base, job.fn.cards)
        paired_key = real_forge.variants.paired_key(key, 0, variant["card_sha"], variant["dck_sha"])
        pair = {"opponent": {"id": RED_ID, "version": "target", "title": "Red Test"},
                "done": 50, "total": 200, "wins": 30, "other": 2, "playing": True}
        snap["detail"] = {"pairs": {key: pair, paired_key: pair}}
        with mock.patch.object(coord, "snapshot", return_value=snap):
            by_key = api.matchup(key=key)
            first = api.matchup(GREEN_ID, "target", RED_ID, "target")
            other = api.matchup(RED_ID, "target", GREEN_ID, "target")
            self.assertEqual((by_key["status"], first["status"], other["status"]), ("running",) * 3)
            self.assertEqual(first["job"]["wins"], [30, 18])
            self.assertEqual(other["job"]["wins"], [18, 30])
            self.assertEqual(first["job"]["range"]["value"], 0.6)
            self.assertEqual(other["job"]["range"]["value"], 0.36)
            self.assertEqual(first["job"]["via"]["link"], f"#/variant?test={test_id}")
            self.assertApiError(404, lambda: api.matchup(key=paired_key))

    def test_a_test_plays_in_the_background_then_its_view_answers(self):
        self.gate.clear()
        answer = self.start()
        self.assertIn(answer["status"], ("queued", "running"))
        self.assertTrue(self.started.wait(WAIT))
        test = answer["test"]["test"]
        playing = api.variant_view(test)
        self.assertEqual(playing["status"], "running")
        self.assertIsNone(playing["words"])             # no verdict while it plays
        job = playing["job"]
        self.assertEqual((job["done"], job["total"], job["next_look"], job["by"]), (100, 400, 200, "Matt"))
        self.assertEqual(len(job["pairs"]), 1)
        self.assertEqual(self.calls[0], {"base": GREEN_ID, "against": RED_ID, "mode": "ahead", "by": "Matt",
                                         "extend": None})
        self.assertEqual(playing["test"]["variant"]["changes"],
                         {"remove": [[1, "Fiery Annihilation"]], "add": [[1, "Giant Growth"]]})
        self.gate.set()
        done = self.wait_done(test)
        self.assertEqual((done["status"], done["verdict"], done["job"]), ("done", "better", None))
        self.assertEqual(done["words"], "Better against Red Test: +2.4 points of win rate (+0.6 to +4.2)")
        json.dumps(done, allow_nan=False)
        # The same draft again joins nothing new: the same test id.
        again = self.start()
        self.assertEqual(again["test"]["test"], test)

    def test_quick_and_the_field(self):
        answer = self.start(mode="quick")
        self.wait_done(answer["test"]["test"])
        self.assertEqual(self.calls[-1]["mode"], "quick")
        with mock.patch.object(real_forge.field, "opponents", side_effect=NotImplementedError):
            self.assertApiError(400, lambda: self.start(against="field"), contains="field view")
        with mock.patch.object(real_forge.field, "opponents",
                               return_value=[real_forge.variants.base_entry(RED_ID)]):
            answer = self.start(against="field")
            self.wait_done(answer["test"]["test"])
        self.assertEqual(self.calls[-1]["against"], "field")

    def test_refusals(self):
        removed = test_forge.GREEN.replace("1 Fiery Annihilation\n", "")
        self.assertApiError(400, lambda: self.start(removed), contains="Keep the same number of cards")
        sideboard = test_forge.GREEN.replace("2 Lightning Bolt", "1 Lightning Bolt")
        self.assertApiError(400, lambda: self.start(sideboard), contains="Sideboard changes aren't tested")
        self.assertApiError(400, lambda: self.start(test_forge.GREEN), contains="no change to test")
        unknown = SWAPPED.replace("3 Giant Growth", "2 Giant Growth\n1 Giant Grwoth")
        self.assertApiError(400, lambda: self.start(unknown), contains="isn't a card name")
        self.assertApiError(400, lambda: self.start(mode="slow"))
        self.assertApiError(403, lambda: self.start(profile="nobody"))
        self.patches = ["attack-requirements-in-order-1"]
        self.assertApiError(503, lambda: self.start(), contains="deck-order patch")
        self.assertEqual(self.calls, [])
        self.assertApiError(400, lambda: api.variant_view("nope"))
        self.assertApiError(404, lambda: api.variant_view("a" * 64))


class StopAndMoreTests(VariantApiCase):

    def test_stop(self):
        self.gate.clear()
        answer = self.start()
        self.assertTrue(self.started.wait(WAIT))
        test = answer["test"]["test"]
        stopped = api.stop_variant(body(profile="user1", test=test))
        self.assertNotIn(stopped["status"], ("queued", "running"))
        job = api.forge_runs.COORD_JOBS.get(f"variant:{test}")
        self.assertEqual(api.forge_runs.COORD_JOBS.snapshot(job)["error"], jobs.STOPPED)
        self.assertEqual(job.cancelled_by, "User1")

    def test_play_more(self):
        test = self.start(mode="quick")["test"]["test"]
        self.wait_done(test)
        more = api.more_variant(body(profile="user1", test=test))
        self.assertIn(more["status"], ("queued", "running", "done"))
        done = self.wait_done(test)
        self.assertEqual(self.calls[-1]["extend"], test)
        self.assertEqual(self.calls[-1]["by"], "User1")
        self.assertEqual(done["test"]["mode"], "ahead")
        self.assertTrue(done["test"]["looks"][0]["interim"])
        # The list changing since makes "Play more" a 409.
        _write(self.box.magic / "decks" / "casual" / "green-test.md",
               deck_file("Green Test", test_forge.GREEN.replace("6 Forest", "5 Forest\n1 Mountain")))
        self.assertApiError(409, lambda: api.more_variant(body(profile="matt", test=test)), contains="changed")
        self.assertApiError(404, lambda: api.more_variant(body(profile="matt", test="b" * 64)))


class ListAndEstimateTests(VariantApiCase):

    def test_the_tests_of_a_list(self):
        test = self.start()["test"]["test"]
        self.wait_done(test)
        listed = api.variant_tests(GREEN_ID, "target")["tests"]
        self.assertEqual([t["test"] for t in listed], [test])
        item = listed[0]
        self.assertEqual((item["against"], item["verdict"], item["saved"], item["running"]),
                         ("Red Test", "better", False, False))
        self.assertEqual(item["changes"]["add"], [[1, "Giant Growth"]])
        # The last look's difference and its range (the swap result's verdict pill and range line).
        self.assertEqual((item["delta"], item["low"], item["high"]), (0.024, 0.006, 0.042))
        self.assertEqual(api.variant_tests(GREEN_ID, "owned")["tests"], [])
        # Once the deck is saved with the tested change, it's marked saved.
        _write(self.box.magic / "decks" / "casual" / "green-test.md", deck_file("Green Test", SWAPPED))
        self.assertTrue(api.variant_tests(GREEN_ID, "target")["tests"][0]["saved"])

    def test_a_running_test_is_listed(self):
        self.gate.clear()
        test = self.start()["test"]["test"]
        self.assertTrue(self.started.wait(WAIT))
        listed = api.variant_tests(GREEN_ID, "target")["tests"]
        self.assertEqual((listed[0]["test"], listed[0]["running"], listed[0]["done"]), (test, True, 100))
        self.assertEqual((listed[0]["delta"], listed[0]["low"], listed[0]["high"]), (None, None, None))
        self.gate.set()

    def test_estimate(self):
        answer = api.variant_estimate(GREEN_ID, "target", RED_ID, "target")
        self.assertEqual((answer["opponents"], answer["available"]), (1, True))
        for span in (answer["quick"], answer["ahead"]):     # A's estimator: (low, high) minutes
            self.assertEqual(len(span), 2)
            self.assertLessEqual(span[0], span[1])
        self.assertEqual(answer["max"], {"quick": 200, "ahead": 3200})
        seen = []

        def minutes(pairs):
            seen.append([games for _, _, games in pairs])
            return (pairs[0][2] / 100, pairs[0][2] / 50)

        with mock.patch.object(real_forge.estimate, "minutes", minutes):
            answer = api.variant_estimate(GREEN_ID, "target", RED_ID, "target")
        self.assertEqual(seen[0], [400])            # 200 base games to play first, then the variant's 200
        self.assertEqual(answer["quick"], [4.0, 8.0])
        self.assertEqual(answer["ahead"], [8.0, 128.0])
        self.assertEqual(answer["default"], "quick")        # the worst case passes 30 minutes
        with mock.patch.object(real_forge.field, "opponents", side_effect=NotImplementedError):
            field = api.variant_estimate(GREEN_ID, "target", "field")
        self.assertEqual((field["available"], field["opponents"]), (False, 0))
        self.assertIn("field view", field["problem"])
