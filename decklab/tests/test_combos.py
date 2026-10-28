"""Tests for decklab.lib.combos: reducing Commander Spellbook's export to the
two-card combo list, reading and matching it, and its step of cards.update().
No network: the export is a tiny one written here, and every download is a mock."""
import gzip
import io
import json
import os
import shutil
import tempfile
import unittest
import urllib.error
from datetime import timedelta
from pathlib import Path
from unittest import mock

from decklab.lib import card_index, cards, combos


def use(card_id, name, zones=("B",), must_be_commander=False, quantity=1):
    return {"card": {"id": card_id, "name": name, "oracleId": f"oracle-{card_id}", "spoiler": False,
                     "imageUriFrontPng": "https://example.invalid/a.png"},
            "zoneLocations": list(zones), "mustBeCommander": must_be_commander, "quantity": quantity}


def result(name, status):
    return {"feature": {"id": 1, "name": name, "uncountable": True, "status": status}, "quantity": 1}


def variant(combo_id, uses, produces, requires=(), commander=True, spoiler=False):
    return {"id": combo_id, "status": "OK", "uses": uses, "requires": list(requires), "produces": produces,
            "spoiler": spoiler, "bracketTag": "B", "legalities": {"commander": commander, "vintage": True},
            "description": "Repeat.", "popularity": 3}


EXPORT = {
    "timestamp": "2026-10-21T03:14:00.560664+00:00", "version": "7.3.0",
    "variants": [
        # Standalone and infinite: raises the floor to 3.
        variant("1-2", [use(1, "Alpha"), use(2, "Beta")],
                [result("Infinite creature ETB", "H"), result("Infinite colored mana", "S")]),
        # Helper-only (needs a payoff), like Gravecrawler + Phyrexian Altar.
        variant("3-4", [use(3, "Crawler"), use(4, "Altar")], [result("Infinite death triggers", "H")]),
        # A template piece ("a creature with power 4 or more"): not a two-card combo.
        dict(variant("1-5", [use(1, "Alpha"), use(5, "Gamma")], [result("Win the game", "S")]),
             requires=[{"template": {"id": 1, "name": "a creature"}, "quantity": 1}]),
        # Three cards.
        variant("1-2-6", [use(1, "Alpha"), use(2, "Beta"), use(6, "Delta")], [result("Win the game", "S")]),
        # A piece that works only as the commander, and one that works from the hand or the command zone.
        variant("7-8", [use(7, "Leader", zones=("C",)), use(8, "Helper")],
                [result("Each opponent loses the game", "S")]),
        variant("9-8", [use(9, "Either", zones=("H", "C")), use(8, "Helper")],
                [result("Target opponent loses the game", "S")]),
        # Every result a helper, but it destroys lands: mass land denial all the same.
        variant("10-11", [use(10, "Stasis"), use(11, "Adept")],
                [result("Lock", "H"), result("Mass Land Denial", "H")]),
        # Standalone, and it destroys lands: mass land denial.
        variant("12-13", [use(12, "Wurm"), use(13, "Revolt")],
                [result("Near-infinite lifeloss", "S"), result("Mass Land Denial", "H")]),
        # Ends the game without the words "win" or "loses", like Helm of Obedience + Rest in Peace.
        variant("20-21", [use(20, "Helm"), use(21, "Rest")], [result("Exile target opponent's library", "S")]),
        # Locks: a helper "Lock" alone, and one beside a standalone result (Mindslaver + Academy Ruins).
        variant("22-23", [use(22, "Toph"), use(23, "Coffin")], [result("Lock", "H")]),
        variant("24-25", [use(24, "Slaver"), use(25, "Ruins")],
                [result("You control one opponent on each of their turns", "S"), result("Lock", "H")]),
        # Not Commander-legal, unreleased, two copies of one card: left out.
        variant("14-15", [use(14, "Banned"), use(15, "Other")], [result("Win the game", "S")], commander=False),
        variant("16-17", [use(16, "Spoiled"), use(17, "Other")], [result("Win the game", "S")], spoiler=True),
        variant("18-19", [use(18, "Twice", quantity=2), use(19, "Other")], [result("Win the game", "S")]),
        # Unreadable: skipped, and counted.
        {"id": "broken", "uses": "nonsense"},
    ],
    "aliases": [{"id": "1-2-old", "variant": "1-2"}],
}


class ComboTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        for name, value in (("COMBOS_DIR", self.tmp), ("EXPORT_FILE", self.tmp / "variants.json.gz"),
                            ("META_FILE", self.tmp / "meta.json"), ("TWO_CARD_FILE", self.tmp / "two_card.json"),
                            ("_cache", {"key": None, "data": None}),
                            ("MAX_MALFORMED", 0.1)):       # the fixture's one broken entry of 12
            patcher = mock.patch.object(combos, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.log = []

    def write_export(self, data=EXPORT, path=None):
        path = path or combos.EXPORT_FILE
        with gzip.open(path, "wt", encoding="utf-8") as f:
            json.dump(data, f)
        return path

    def reduced(self):
        self.write_export()
        combos.reduce_export(log=self.log.append)
        return json.loads(combos.TWO_CARD_FILE.read_text(encoding="utf-8"))


class ReduceTests(ComboTestCase):
    def test_keeps_only_commander_legal_two_card_combos_without_templates(self):
        data = self.reduced()
        self.assertEqual((data["timestamp"], data["version"], data["format"]),
                         ("2026-10-21T03:14:00.560664+00:00", "7.3.0", combos.FORMAT))
        self.assertEqual([c["id"] for c in data["combos"]], ["1-2", "3-4", "7-8", "9-8", "10-11", "12-13",
                                                         "20-21", "22-23", "24-25"])
        self.assertEqual(data["count"], 9)
        self.assertIn("1 entries couldn't be read", self.log[-1])

    def test_each_combo_keeps_pieces_results_class_and_link(self):
        found = {c["id"]: c for c in self.reduced()["combos"]}
        self.assertEqual(found["1-2"], {
            "id": "1-2", "url": "https://commanderspellbook.com/combo/1-2/",
            "cards": [{"oracle_id": "oracle-1", "name": "Alpha", "must_be_commander": False},
                      {"oracle_id": "oracle-2", "name": "Beta", "must_be_commander": False}],
            "results": ["Infinite colored mana", "Infinite creature ETB"], "class": "infinite",
            "standalone": True})
        self.assertEqual((found["3-4"]["standalone"], found["3-4"]["class"]), (False, "infinite"))
        self.assertEqual([p["must_be_commander"] for p in found["7-8"]["cards"]], [True, False])
        self.assertEqual([p["must_be_commander"] for p in found["9-8"]["cards"]], [False, False])
        self.assertEqual((found["7-8"]["class"], found["10-11"]["class"]), ("win", "mass_land_denial"))
        self.assertFalse(found["10-11"]["standalone"])
        self.assertEqual((found["12-13"]["class"], found["12-13"]["standalone"]), ("mass_land_denial", True))
        self.assertEqual((found["20-21"]["class"], found["20-21"]["standalone"]), ("win", True))
        self.assertEqual((found["22-23"]["class"], found["22-23"]["standalone"]), ("lock", False))
        self.assertEqual((found["24-25"]["class"], found["24-25"]["standalone"]), ("lock", True))
        self.assertNotIn("bracketTag", json.dumps(found))       # no early-game hint (Matt, 2026-10-21)

    def test_floors(self):
        found = {c["id"]: combos.bracket_floor(c) for c in self.reduced()["combos"]}
        self.assertEqual(found, {"1-2": 3, "3-4": 1, "7-8": 3, "9-8": 3, "10-11": 4, "12-13": 4,
                                 "20-21": 3, "22-23": 1, "24-25": 1})

    def test_result_classes(self):
        for name, expected in (("Infinite colored mana", "infinite"), ("Infinitely large creature", "infinite"),
                               ("Win the game at the beginning of your next upkeep", "win"),
                               ("Each opponent with 20 or more life loses the game", "win"),
                               ("You can't lose the game due to having 0 or less life", "other"),
                               ("Mass Land Denial", "mass_land_denial"), ("Lock", "lock"),
                               ("Draw the game", "draw"), ("Near-infinite damage", "near_infinite"),
                               ("Exile target opponent's library", "win"), ("Exile each opponent's library", "win"),
                               ("Exile all libraries", "win"),
                               ("You control one opponent on each of their turns", "lock"),
                               ("You control your opponents on each of their turns", "lock"),
                               ("Exile target creature", "other"),
                               ("Destroy all creatures opponents control", "other")):
            with self.subTest(name=name):
                self.assertEqual(combos.result_class(name), expected)

    def test_reads_the_export_in_small_chunks_too(self):
        whole = self.reduced()["combos"]
        with mock.patch.object(combos, "CHUNK", 7):
            combos.reduce_export(log=self.log.append)
        self.assertEqual(json.loads(combos.TWO_CARD_FILE.read_text(encoding="utf-8"))["combos"], whole)

    def test_a_plain_json_export_is_read_too(self):
        combos.EXPORT_FILE.write_text(json.dumps(EXPORT), encoding="utf-8")
        self.assertEqual(combos.reduce_export(log=self.log.append), 9)

    def test_a_bad_export_never_replaces_the_list(self):
        self.reduced()
        before = combos.TWO_CARD_FILE.read_bytes()
        undated = {k: v for k, v in EXPORT.items() if k != "timestamp"}
        empty = {**EXPORT, "variants": [EXPORT["variants"][3]]}
        damaged = {**EXPORT, "variants": [{"id": str(i)} for i in range(20)] + EXPORT["variants"][:1]}
        for data in (undated, empty, damaged, [1, 2]):
            with self.subTest(data=str(data)[:40]):
                self.write_export(data)
                with self.assertRaises(ValueError):
                    combos.reduce_export(log=self.log.append)
                self.assertEqual(combos.TWO_CARD_FILE.read_bytes(), before)
        combos.EXPORT_FILE.write_bytes(gzip.compress(b'{"timestamp": "2026-10-21", "variants": [{"id"'))
        with self.assertRaises(ValueError):
            combos.reduce_export(log=self.log.append)
        self.assertEqual(combos.TWO_CARD_FILE.read_bytes(), before)


class MatchTests(ComboTestCase):
    def setUp(self):
        super().setUp()
        self.reduced()

    def ids(self, result):
        return [c["id"] for c in result["matches"]]

    def test_both_pieces_in_the_main_deck(self):
        found = combos.find([], ["oracle-1", "oracle-2", "oracle-3"])
        self.assertEqual(self.ids(found), ["1-2"])
        self.assertEqual((found["timestamp"], found["version"]), ("2026-10-21T03:14:00.560664+00:00", "7.3.0"))
        self.assertEqual(self.ids(combos.find(["oracle-1"], ["oracle-2"])), ["1-2"])

    def test_a_piece_that_must_be_the_commander_counts_only_in_the_commander_section(self):
        self.assertEqual(self.ids(combos.find([], ["oracle-7", "oracle-8"])), [])
        self.assertEqual(self.ids(combos.find(["oracle-7"], ["oracle-8"])), ["7-8"])
        # Hand or command zone: it works from the 99 too.
        self.assertEqual(self.ids(combos.find([], ["oracle-9", "oracle-8"])), ["9-8"])

    def test_most_serious_first(self):
        every = [f"oracle-{n}" for n in range(1, 14)]
        self.assertEqual(self.ids(combos.find(["oracle-7"], every)), ["10-11", "12-13", "9-8", "7-8", "1-2", "3-4"])

    def test_an_unreadable_list_is_an_error_never_no_combos(self):
        for text in ("", "{", json.dumps({"format": 0, "timestamp": "x", "combos": []}),
                     json.dumps({"format": combos.FORMAT, "combos": []}),
                     json.dumps({"format": combos.FORMAT, "timestamp": "2026-10-21",
                                 "combos": [{"cards": [{"oracle_id": "a"}]}]})):
            with self.subTest(text=text[:40]):
                combos.TWO_CARD_FILE.write_text(text, encoding="utf-8")
                with self.assertRaises(combos.ComboListError):
                    combos.find([], ["oracle-1", "oracle-2"])
        combos.TWO_CARD_FILE.unlink()
        with self.assertRaisesRegex(combos.ComboListError, "isn't on the PC yet"):
            combos.find([], ["oracle-1"])

    def test_read_again_when_the_file_changes(self):
        self.assertEqual(self.ids(combos.find([], ["oracle-1", "oracle-2"])), ["1-2"])
        data = json.loads(combos.TWO_CARD_FILE.read_text(encoding="utf-8"))
        data["combos"] = data["combos"][1:]
        combos.TWO_CARD_FILE.write_text(json.dumps(data) + " ", encoding="utf-8")
        self.assertEqual(self.ids(combos.find([], ["oracle-1", "oracle-2"])), [])


class NearTests(ComboTestCase):
    """E9-S25: find's near mode, the combos one card away."""

    def setUp(self):
        super().setUp()
        self.reduced()

    def near(self, commander_ids, deck_ids):
        return [(c["id"], c["missing"]) for c in combos.find(commander_ids, deck_ids, near=True)["matches"]]

    def test_one_piece_in_the_deck_names_the_other(self):
        self.assertEqual(self.near([], ["oracle-1"]), [("1-2", 1)])
        self.assertEqual(self.near([], ["oracle-2"]), [("1-2", 0)])
        self.assertEqual(self.near(["oracle-1"], []), [("1-2", 1)])

    def test_complete_combos_and_combos_with_nothing_in_the_deck_arent_near(self):
        self.assertEqual(self.near([], ["oracle-1", "oracle-2"]), [])
        self.assertEqual(self.near([], ["oracle-99"]), [])

    def test_a_missing_commander_piece_is_never_one_card_away(self):
        # Helper is in both 7-8 (Leader only as the commander) and 9-8 (Either from the hand too).
        self.assertEqual(self.near([], ["oracle-8"]), [("9-8", 0)])
        # Leader in the 99 isn't the piece, and it's already in the deck, so 7-8 isn't near either.
        self.assertEqual(self.near([], ["oracle-7"]), [])
        self.assertEqual(self.near(["oracle-7"], []), [("7-8", 1)])
        # Leader in the 99 with Helper: 9-8 is near (Either missing); 7-8 is neither complete nor near.
        self.assertEqual(self.near([], ["oracle-7", "oracle-8"]), [("9-8", 0)])

    def test_most_serious_first_and_the_list_is_left_as_it_was(self):
        self.assertEqual(self.near([], ["oracle-1", "oracle-3", "oracle-10", "oracle-22"]),
                         [("10-11", 1), ("1-2", 1), ("3-4", 1), ("22-23", 1)])
        self.assertFalse(any("missing" in c for c in combos.load()["combos"]))
        self.assertEqual([c["id"] for c in combos.find([], ["oracle-1", "oracle-2"])["matches"]], ["1-2"])


class UpdateTests(ComboTestCase):
    ETAG, MODIFIED = '"abc123"', "Wed, 21 Oct 2026 03:14:10 GMT"

    def download(self, data=EXPORT, etag='"new"'):
        def fake(url, dest, accept="*/*", timeout=60, headers=None, response_headers=None):
            self.requests.append((url, dict(headers or {})))
            self.write_export(data, dest)
            response_headers.update({"ETag": etag, "Last-Modified": "Thu, 22 Oct 2026 00:00:00 GMT"})
            return dest.stat().st_size
        return fake

    def setUp(self):
        super().setUp()
        self.requests = []

    def old_files(self, days=8):
        self.reduced()
        then = card_index._now() - timedelta(days=days)
        cards._write_json(combos.META_FILE, {"downloaded_at": then.isoformat(timespec="seconds"),
                                             "etag": self.ETAG, "last_modified": self.MODIFIED,
                                             "format": combos.FORMAT})

    def update(self, download, force=False):
        with mock.patch.object(cards, "_download", side_effect=download) as patched:
            changed = combos.update(force=force, log=self.log.append)
        return changed, patched

    def test_a_fresh_list_isnt_downloaded(self):
        self.old_files(days=2)
        changed, patched = self.update(AssertionError("no network"))
        self.assertFalse(changed)
        patched.assert_not_called()

    def test_a_week_old_list_is_asked_for_conditionally_and_reduced_when_new(self):
        self.old_files()
        newer = {**EXPORT, "timestamp": "2026-10-22T01:00:00+00:00"}
        changed, _ = self.update(self.download(newer))
        self.assertTrue(changed)
        url, headers = self.requests[0]
        self.assertEqual(url, combos.EXPORT_URL)
        self.assertEqual((headers["If-None-Match"], headers["If-Modified-Since"]), (self.ETAG, self.MODIFIED))
        meta = cards._read_json(combos.META_FILE, {})
        self.assertEqual((meta["etag"], meta["timestamp"], meta["version"]), ('"new"', newer["timestamp"], "7.3.0"))
        self.assertEqual(combos.load()["timestamp"], newer["timestamp"])

    def test_unchanged_304_restarts_the_clock_and_keeps_the_files(self):
        self.old_files()
        before = (combos.EXPORT_FILE.read_bytes(), combos.TWO_CARD_FILE.read_bytes())
        os.utime(combos.TWO_CARD_FILE)          # reduced after the export was written
        not_modified = urllib.error.HTTPError(combos.EXPORT_URL, 304, "Not Modified", {}, io.BytesIO())
        changed, _ = self.update(not_modified)
        self.assertFalse(changed)
        self.assertEqual((combos.EXPORT_FILE.read_bytes(), combos.TWO_CARD_FILE.read_bytes()), before)
        meta = cards._read_json(combos.META_FILE, {})
        self.assertEqual(meta["etag"], self.ETAG)
        self.assertTrue(combos._fresh(meta))
        self.assertIn("unchanged", " ".join(self.log))

    def test_a_failed_download_keeps_the_old_files_and_doesnt_raise(self):
        self.old_files()
        before = combos.TWO_CARD_FILE.read_bytes()
        os.utime(combos.TWO_CARD_FILE)
        for error in (OSError("timed out"), urllib.error.HTTPError(combos.EXPORT_URL, 503, "Busy", {}, io.BytesIO()),
                      ValueError("cut off")):
            with self.subTest(error=error):
                changed, _ = self.update(error)
                self.assertFalse(changed)
                self.assertEqual(combos.TWO_CARD_FILE.read_bytes(), before)
                self.assertFalse(combos._fresh(cards._read_json(combos.META_FILE, {})))   # tried again next time
        self.assertIn("keeping the local file", " ".join(self.log))

    def test_force_downloads_without_conditions(self):
        self.old_files(days=1)
        changed, _ = self.update(self.download(), force=True)
        self.assertNotIn("If-None-Match", self.requests[0][1])
        self.assertTrue(changed)

    def test_a_bad_download_keeps_the_old_list(self):
        self.old_files()
        before = combos.TWO_CARD_FILE.read_bytes()
        changed, _ = self.update(self.download({"variants": []}))
        self.assertFalse(changed)
        self.assertEqual(combos.TWO_CARD_FILE.read_bytes(), before)
        self.assertIn("keeping the old list", self.log[-1])

    def test_nothing_on_the_pc_and_offline(self):
        changed, _ = self.update(OSError("offline"))
        self.assertFalse(changed)
        with self.assertRaises(combos.ComboListError):
            combos.load()

    def test_a_failing_combo_step_never_fails_the_card_update(self):
        logs = []
        with mock.patch.object(combos, "update", side_effect=RuntimeError("disk full")):
            cards._update_combos(False, logs.append)
        self.assertIn("disk full", logs[-1])


if __name__ == "__main__":
    unittest.main()
