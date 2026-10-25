"""Api practice tests; shared fixtures remain in test_api."""
import unittest
import json
import sys
import threading
from unittest import mock
from decklab.lib import api, cards, decks, jobs
from decklab.lib import goldfish as real_goldfish
from decklab.tests.test_api import (
    ApiTestCase,
)


class GoldfishTests(ApiTestCase):
    """GET /api/goldfish with the stand-in simulation (the Sandbox's FakeGoldfish)."""

    def setUp(self):
        super().setUp()
        self.fake = self.box.goldfish

    def test_a_first_request_starts_the_run_and_later_ones_get_the_result(self):
        self.fake.gate.clear()
        first = api.goldfish("casual/gruul-test")
        self.assertEqual(first["status"], "running")
        self.assertEqual(set(first), {"status", "queued", "ahead", "progress"})
        self.assertEqual(api.goldfish("casual/gruul-test", "target")["status"], "running")    # joins it
        self.box.wait_for_jobs()
        self.assertEqual(len(self.fake.runs), 1)
        sections, kind, settings = self.fake.runs[0]
        self.assertEqual(sections, decks.load_deck("casual/gruul-test"))
        self.assertEqual((kind, settings), ("constructed", {}))
        done = api.goldfish("casual/gruul-test")
        self.assertEqual(done["status"], "done")
        self.assertEqual(done["result"]["cards"], 23)
        self.assertTrue(done["result"]["cached"])
        json.dumps(done, allow_nan=False)
        self.assertEqual(len(self.fake.runs), 1)

    def test_progress_while_running(self):
        self.fake.gate.clear()
        api.goldfish("casual/gruul-test")
        job = next(iter(api.practice.JOBS._jobs.values()))
        for _ in range(500):            # until the job's thread has reported
            if job.progress[1]:
                break
            threading.Event().wait(0.01)
        answer = api.goldfish("casual/gruul-test")
        self.assertEqual(answer, {"status": "running", "queued": False, "ahead": 0,
                                  "progress": {"done": 100, "total": 400}})

    def test_a_saved_result_answers_at_once(self):
        sections = decks.load_deck("casual/gruul-test")
        key = self.fake.cache_key(sections, "constructed")
        self.fake.saved[key] = {"cache_key": key, "kind": "constructed", "warnings": []}
        answer = api.goldfish("casual/gruul-test")
        self.assertEqual(answer, {"status": "done", "result": {"cache_key": key, "kind": "constructed",
                                                               "warnings": [], "cached": True}})
        self.assertEqual(self.fake.runs, [])
        self.assertEqual(api.practice.JOBS._jobs, {})

    def test_each_list_and_kind(self):
        for deck_id, version, kind in (("casual/gruul-test", "owned", "constructed"),
                                       ("commander/elf-commander", "target", "commander"),
                                       ("product/fdc-test-precon", "target", "commander"),
                                       ("pairing/elves+cats", "target", "constructed")):
            with self.subTest(deck_id=deck_id):
                self.assertIn(api.goldfish(deck_id, version)["status"], ("running", "done"))
                self.box.wait_for_jobs()
                sections, got, _ = self.fake.runs[-1]
                self.assertEqual(got, kind)
                self.assertEqual(sections, decks.load_deck(api._find_summary(deck_id)["id"], version))
                self.assertEqual(api.goldfish(deck_id, version)["status"], "done")

    def test_the_same_cards_under_two_ids_are_one_run(self):
        self.fake.gate.clear()
        api.goldfish("pairing/cats+elves")
        api.goldfish("pairing/elves+cats")
        self.box.wait_for_jobs()
        self.assertEqual(len(self.fake.runs), 1)

    def test_warnings_leak_no_path(self):
        api.goldfish("casual/gruul-test")
        self.box.wait_for_jobs()
        result = api.goldfish("casual/gruul-test")["result"]
        [warning] = result["warnings"]
        self.assertTrue(warning.startswith("magic") and warning.endswith("x.csv: a warning"), warning)
        self.assertNotRegex(warning, r"[A-Za-z]:[\\/]")

    def test_a_failed_run_is_reported_until_retried(self):
        self.fake.error = OSError(13, "Permission denied", str(self.box.data / "goldfish" / "x.json"))
        api.goldfish("casual/gruul-test")
        self.box.wait_for_jobs()
        answer = api.goldfish("casual/gruul-test")
        # The page's box already says the games couldn't be played: the answer says what to do, and the
        # Python error goes to the log only.
        self.assertEqual(answer, {"status": "error", "error": api.RUN_FAILED})
        self.assertNotIn("Permission denied", answer["error"])
        self.assertTrue(any("Traceback" in line and "Permission denied" in line for line in self.box.logs))
        self.assertEqual(api.goldfish("casual/gruul-test")["status"], "error")     # not run again
        self.assertEqual(len(self.fake.runs), 1)
        self.fake.error = None
        self.assertIn(api.goldfish("casual/gruul-test", retry="1")["status"], ("running", "done"))
        self.box.wait_for_jobs()
        self.assertEqual(api.goldfish("casual/gruul-test")["status"], "done")
        self.assertEqual(len(self.fake.runs), 2)

    def test_the_deck_view_includes_a_saved_result_but_never_starts_a_run(self):
        # So a deck page is drawn whole at once, and nothing below Practice hands moves later.
        self.assertIsNone(api.deck_view("casual/gruul-test")["practice"])
        self.assertEqual((self.fake.runs, api.practice.JOBS._jobs), ([], {}))
        api.goldfish("casual/gruul-test")
        self.box.wait_for_jobs()
        practice = api.deck_view("casual/gruul-test")["practice"]
        self.assertEqual(practice, api.goldfish("casual/gruul-test"))
        self.assertEqual((practice["status"], practice["result"]["cached"]), ("done", True))
        self.assertNotRegex(practice["result"]["warnings"][0], r"[A-Za-z]:[\\/]")
        json.dumps(practice, allow_nan=False)
        self.assertIsNone(api.deck_view("casual/gruul-test", "owned")["practice"])     # not played yet
        self.assertEqual(len(self.fake.runs), 1)

    def test_the_deck_view_includes_a_finished_run_that_was_not_saved(self):
        api.goldfish("casual/gruul-test")
        self.box.wait_for_jobs()
        self.fake.saved.clear()             # as when the data folder can't be written
        practice = api.deck_view("casual/gruul-test")["practice"]
        self.assertEqual((practice["status"], practice["result"]["cached"]), ("done", False))
        # A failed run isn't: the page asks goldfish(), which says so and offers Try again.
        self.fake.error = RuntimeError("worker crashed")
        api.goldfish("casual/gruul-test", "owned")
        self.box.wait_for_jobs()
        self.assertIsNone(api.deck_view("casual/gruul-test", "owned")["practice"])

    def test_the_deck_view_says_when_a_deck_is_too_small_to_deal(self):
        self.fake.key_error = ValueError("the deck has 3 cards to draw from; the simulation needs at least 8")
        self.assertEqual(api.deck_view("commander/elf-commander")["practice"], api.goldfish("commander/elf-commander"))

    def test_a_beginner_box_half_gets_no_practice_games_on_its_page(self):
        # Review finding: a 20-card half is only ever played shuffled with another half.
        half = "product/fdn-beginner-box/cats"
        key = self.fake.cache_key(decks.load_deck(half), "constructed")
        self.fake.saved[key] = {"cache_key": key, "kind": "constructed", "warnings": []}
        self.assertTrue(api.is_half(api._find_summary(half)))
        self.assertIsNone(api.deck_view(half)["practice"])
        pairing = "pairing/cats+elves"
        self.assertFalse(api.is_half(api._find_summary(pairing)))
        key = self.fake.cache_key(decks.load_deck(pairing), "constructed")
        self.fake.saved[key] = {"cache_key": key, "kind": "constructed", "warnings": []}
        self.assertEqual(api.deck_view(pairing)["practice"]["status"], "done")

    def test_the_deck_view_survives_a_broken_simulation(self):
        self.fake.key_error = RuntimeError("boom")
        view = api.deck_view("casual/gruul-test")
        self.assertIsNone(view["practice"])
        self.assertEqual(view["summary"]["id"], "casual/gruul-test")
        self.assertTrue(any("can't be looked up" in line and "RuntimeError: boom" in line for line in self.box.logs))
        self.fake.key_error = None
        with mock.patch.dict(sys.modules, {"decklab.lib.goldfish": None}):
            self.assertIsNone(api.deck_view("casual/gruul-test")["practice"])

    def test_a_deck_too_small_to_deal(self):
        self.fake.key_error = ValueError("the deck has 3 cards to draw from; the simulation needs at least 8")
        self.assertEqual(api.goldfish("commander/elf-commander"), {
            "status": "error", "error": "This deck can't be dealt practice hands: the deck has 3 cards to "
                                        "draw from; the simulation needs at least 8."})
        self.assertEqual(self.fake.runs, [])

    def test_one_run_at_a_time_and_a_limit_on_waiting(self):
        self.fake.gate.clear()
        with mock.patch.object(api.practice, "JOBS", jobs.Runner(max_running=1, max_queued=1)):
            self.assertEqual(api.goldfish("casual/gruul-test")["status"], "running")
            for _ in range(500):        # until the first has started
                if self.fake.runs:
                    break
                threading.Event().wait(0.01)
            waiting = api.goldfish("casual/gruul-test", "owned")
            self.assertEqual((waiting["status"], waiting["queued"], waiting["ahead"]), ("running", True, 1))
            self.assertEqual(waiting["progress"], {"done": 0, "total": None})
            self.assertApiError(503, api.goldfish, "commander/elf-commander", contains="busy")
            self.fake.gate.set()
            for job in list(api.practice.JOBS._jobs.values()):
                self.assertTrue(job.wait(5))
        self.assertEqual(len(self.fake.runs), 2)

    def test_bad_requests(self):
        self.assertApiError(400, api.goldfish, "../../CLAUDE")
        self.assertApiError(400, api.goldfish, "casual/gruul-test", "Owned")
        self.assertApiError(400, api.goldfish, "casual/gruul-test", "target", "2")
        self.assertApiError(404, api.goldfish, "casual/nope")
        self.assertApiError(404, api.goldfish, "commander/elf-commander", "owned")
        self.assertApiError(500, api.goldfish, "casual/broken", contains="casual/broken can't be read")
        with self.box.no_index():
            self.assertApiError(503, api.goldfish, "casual/gruul-test")
        self.assertEqual(self.fake.runs, [])

    def test_no_simulation_module(self):
        with mock.patch.dict(sys.modules, {"decklab.lib.goldfish": None}):
            self.assertApiError(500, api.goldfish, "casual/gruul-test", contains="isn't available")
        self.assertIn("ModuleNotFoundError", self.box.logs[-1])



class RealGoldfishTests(ApiTestCase):
    """The real goldfish module through the API: 300 games, in this process,
    saved in the sandbox's data folder."""

    def test_a_real_run(self):
        name = "decklab.lib.goldfish"
        sys.modules[name] = real_goldfish       # the Sandbox puts its own entry back afterwards
        folder = self.box.data / "goldfish"
        with mock.patch.object(real_goldfish.runs, "CACHE_DIR", folder), \
                mock.patch.object(real_goldfish.runs, "default_workers", return_value=1), \
                mock.patch.object(api.practice, "GOLDFISH_SETTINGS", {"games": 300}):
            self.assertIn(api.goldfish("casual/gruul-test")["status"], ("running", "done"))
            self.box.wait_for_jobs()
            answer = api.goldfish("casual/gruul-test")
            self.assertEqual(answer["status"], "done")
            result = answer["result"]
            self.assertTrue(result["cached"])
            self.assertEqual((result["games"], result["workers"], result["kind"]), (300, 1, "constructed"))
            self.assertEqual([s["id"] for s in result["setups"]], ["play", "draw"])
            self.assertEqual(list(result["results"]), ["play", "draw"])
            self.assertIn("Opt", [c["name"] for c in result["cards"]["unresolved"]])
            self.assertEqual(len(list(folder.glob("*.json"))), 1)
            json.dumps(answer, allow_nan=False)
            # A three-card Commander deck can't be dealt a hand.
            small = api.goldfish("commander/elf-commander")
            self.assertEqual(small["status"], "error")
            self.assertIn("can't be dealt practice hands", small["error"])



class SearchTests(ApiTestCase):

    def test_search(self):
        self.assertEqual(api.search("llan"), {"names": ["Llanowar Elves"], "did_you_mean": []})
        self.assertEqual(api.search("  LLAN  ", "5"), {"names": ["Llanowar Elves"], "did_you_mean": []})
        self.assertEqual(api.search(""), {"names": [], "did_you_mean": []})
        self.assertEqual(api.search("oracle of"), {"names": [], "did_you_mean": []})     # digital-only is left out
        self.assertEqual(len(api.search("i", "2")["names"]), 2)

    def test_word_starts_and_did_you_mean(self):
        # Typed words start the name's words, in order; "did_you_mean" is always
        # there: close spellings (not already in names) when fewer than 3 names match.
        self.assertEqual(api.search("llan elv"), {"names": ["Llanowar Elves"], "did_you_mean": []})
        self.assertEqual(api.search("llanowar elfs"), {"names": [], "did_you_mean": ["Llanowar Elves"]})
        self.assertEqual(api.search("black lotsu", "8", "1")["did_you_mean"], ["Black Lotus"])
        self.assertEqual(api.search("zzzzqqq"), {"names": [], "did_you_mean": []})
        many = api.search("l", "8")
        self.assertGreaterEqual(len(many["names"]), 3)
        self.assertEqual(many["did_you_mean"], [])
        # A small limit still counts every match: 3 or more, so no guesses.
        self.assertEqual(api.search("l", "1")["did_you_mean"], [])
        with mock.patch.object(cards, "close_names", wraps=cards.close_names) as close:
            api.search("l", "8")
            close.assert_not_called()           # difflib only runs when few names match

    def test_detail(self):
        # What the editor's suggestions show: the card's type and cost, the printing a new line gets
        # (the one the pool has most of), and how many copies of any printing are in the pool.
        answer = api.search("llan", "5", "1")
        self.assertEqual(answer["names"], ["Llanowar Elves"])
        card, = answer["cards"]
        self.assertEqual((card["name"], card["mana_cost"], card["type_line"]),
                         ("Llanowar Elves", "{G}", "Creature — Elf Druid"))
        self.assertEqual(card["default"], {"set": "fdn", "number": "227", "finish": "nonfoil", "why": "owned"})
        self.assertEqual(card["img_small"], "/img/fdn/227/small")
        self.assertGreater(card["have"]["owned"], 0)
        self.assertEqual(set(card["have"]), {"owned", "on_the_way"})
        self.assertEqual(api.search("llan", None, "0"), {"names": ["Llanowar Elves"], "did_you_mean": []})
        self.assertEqual(api.search("", None, "1"), {"names": [], "did_you_mean": [], "cards": []})
        for detail in ("2", "yes", "true"):
            with self.subTest(detail=detail):
                self.assertApiError(400, api.search, "llan", None, detail)

    def test_bad_limits_and_text(self):
        for limit in ("0", "51", "x", "-1", "1.5", " 5", "1e2", 0, 51):
            with self.subTest(limit=limit):
                self.assertApiError(400, api.search, "llan", limit)
        self.assertApiError(400, api.search, "a" * (api.MAX_SEARCH + 1))
        self.assertApiError(400, api.search, "llan\x00")



class ImageTests(ApiTestCase):

    def test_downloads_once_into_the_data_folder(self):
        path = api.image_file("fdn", "227", "small")
        self.assertEqual(path, self.box.data / "images" / "small" / "fdn" / "227.jpg")
        self.assertEqual(api.image_file("fdn", "227", "small"), path)
        self.assertEqual(len(self.box.downloads), 1)
        star = api.image_file("pdmu", "1★", "normal")
        star.resolve().relative_to((self.box.data / "images").resolve())

    def test_unknown_or_malformed_printings_are_404(self):
        for args in (("fdn", "99999", "small"), ("zzz", "1", "small"), ("fdn", "227", "huge"),
                     ("FDN", "227", "small"), ("..", "227", "small"), ("fdn", "..", "small"),
                     ("fdn", "../227", "small"), ("fdn", "227.jpg", "small"), ("f", "1", "small"),
                     ("fdn", "", "small"), ("fdn", "1" * 17, "small"), ("fdn", "22\\7", "small")):
            with self.subTest(args=args):
                self.assertApiError(404, api.image_file, *args)
        self.assertEqual(self.box.downloads, [])

    def test_a_failed_download_is_503(self):
        with mock.patch.object(cards, "_download", side_effect=OSError("timed out")):
            self.assertApiError(503, api.image_file, "fdn", "227", "normal", contains="timed out")

    def test_a_cache_that_cant_be_written_is_500_and_names_no_path(self):
        # A local disk problem isn't Scryfall's fault, and the path stays in the log.
        folder = str(self.box.data / "images" / "normal" / "woe")
        error = FileExistsError(183, "Cannot create a file when that file already exists", folder)
        with mock.patch.object(cards, "_download", side_effect=error):
            caught = self.assertApiError(500, api.image_file, "fdn", "227", "normal",
                                         contains="couldn't be saved on the PC")
        self.assertNotIn("Scryfall", caught.message)
        self.assertNotIn(str(self.box.root), caught.message)
        self.assertTrue(any(folder.replace("\\", "\\\\") in line for line in self.box.logs))

    def test_image_urls_match_what_image_file_accepts(self):
        self.assertEqual(api.image_url("pdmu", "1★", "small"), "/img/pdmu/1%E2%98%85/small")
        self.assertIsNone(api.image_url("fdn", "../x", "small"))
        self.assertIsNone(api.image_url("FDN", "1", "small"))



if __name__ == "__main__":
    unittest.main()
