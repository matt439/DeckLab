"""Tests for decklab.lib.precon_coverage (E1-S24's first slice): precons
ranked by how much of each a space's free pool covers, from MTGJSON's
cached lists.

A fixture set of precons is written into a temporary cache, and the pools
are fake (lib/pool.Pool built by hand), so nothing needs the database,
the card data or the network; card names resolve as written unless a test
uses the real card index, which skips without it.

Run from the repo root: python -m unittest decklab.tests.test_precon_coverage
"""
import contextlib
import io
import json
import os
import tempfile
import time
import unittest
from collections import Counter
from pathlib import Path
from unittest import mock

from decklab.lib import cards, pool, precon_coverage, precons
from decklab.lib.inventory import entry


def card(name, count=1, code="TST", number="1"):
    return {"name": name, "setCode": code, "number": number, "count": count}


DECK_LIST = {"meta": {"date": "2026-10-08"}, "data": [
    {"code": "TST", "fileName": "Dinos_TST", "name": "Test Dinos", "releaseDate": "2026-10-02",
     "type": "Commander Deck"},
    {"code": "TST", "fileName": "Elves_TST", "name": "Elf Theme", "releaseDate": "2025-01-01",
     "type": "Theme Deck"},
    {"code": "TST", "fileName": "Goblins_TST", "name": "Goblin Theme", "releaseDate": "2024-01-01",
     "type": "Theme Deck"},
    {"code": "TST", "fileName": "NotCached_TST", "name": "Not Cached", "releaseDate": "2026-01-01",
     "type": "Theme Deck"},
    {"code": "SLD", "fileName": "Drop_SLD", "name": "Some Drop", "releaseDate": "2026-09-01",
     "type": "Secret Lair Drop"},
]}
DECKS = {
    "Dinos_TST": {"commander": [card("Ghalta, Primal Hunger")],
                  "displayCommander": [card("Ghalta, Primal Hunger")],
                  "mainBoard": [card("Llanowar Elves", 2), card("Sol Ring"), card("Forest", 30)]},
    "Elves_TST": {"mainBoard": [card("Llanowar Elves", 4), card("Elvish Mystic", 4), card("Forest", 20)],
                  "sideBoard": [card("Pick Your Poison", 2)]},
    "Goblins_TST": {"mainBoard": [card("Goblin Guide", 4), card("Mountain", 20)]},
}


def fake_pool(owned, held=()):
    """A Pool owning owned (name -> copies), with built decks holding held ([Counter])."""
    in_use = [pool.InUse(f"casual/deck-{i}", f"Deck {i}", "built", Counter(c)) for i, c in enumerate(held)]
    return pool.Pool(Counter(owned), {}, in_use)


def as_written(name, set_code, number):
    return name


class CoverageTestCase(unittest.TestCase):

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.cache = Path(tmp.name) / "mtgjson"
        self.seed("DeckList.json", DECK_LIST)
        self.seed("SetList.json", {"data": [{"code": "TST", "name": "Test Set"}]})
        for file, data in DECKS.items():
            self.seed(f"decks/{file}.json", {"data": data})
        self.fetch = mock.Mock(side_effect=AssertionError("no network"))
        for name, value in (("CACHE", self.cache), ("_fetch", self.fetch), ("_failed", {}), ("_kept", {})):
            patcher = mock.patch.object(precons, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def seed(self, name, data):
        path = self.cache / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    def rank(self, owned, held=(), **kw):
        return precon_coverage.rank(pool.free_copies(fake_pool(owned, held)), resolve=as_written, **kw)


class RankTests(CoverageTestCase):

    def test_best_first_with_basics_left_out(self):
        result = self.rank({"Llanowar Elves": 4, "Elvish Mystic": 2, "Sol Ring": 1, "Forest": 40})
        got = [(r["file"], r["have"], r["total"]) for r in result["precons"]]
        # Dinos: Ghalta, 2 Elves, Sol Ring (not its display commander) = 4 cards, 3 free.
        # Elves: 4 + 4 + 2 sideboard = 10, 6 free. Goblins: 4, none free. Forests never count.
        self.assertEqual(got, [("Dinos_TST", 3, 4), ("Elves_TST", 6, 10), ("Goblins_TST", 0, 4)])
        self.assertEqual(result["precons"][0]["share"], 0.75)
        self.assertEqual(result["precons"][0]["missing"], 1)
        self.assertEqual(result["precons"][0]["format"], "commander")
        self.assertEqual(result["precons"][0]["set_name"], "Test Set")
        self.assertEqual((result["date"], result["listed"], result["cached"]), ("2026-10-08", 4, 3))
        self.fetch.assert_not_called()

    def test_copies_built_decks_hold_arent_free(self):
        result = self.rank({"Llanowar Elves": 4, "Elvish Mystic": 4},
                           held=[{"Llanowar Elves": 4}, {"Elvish Mystic": 1}])
        elves = next(r for r in result["precons"] if r["file"] == "Elves_TST")
        self.assertEqual((elves["have"], elves["total"]), (3, 10))

    def test_format_and_limit(self):
        owned = {"Goblin Guide": 4}
        self.assertEqual([r["file"] for r in self.rank(owned, fmt="commander")["precons"]], ["Dinos_TST"])
        casual = self.rank(owned, fmt="casual")
        self.assertEqual([r["file"] for r in casual["precons"]], ["Goblins_TST", "Elves_TST"])
        self.assertEqual((casual["listed"], casual["cached"]), (3, 2))
        self.assertEqual([r["file"] for r in self.rank(owned, limit=1)["precons"]], ["Goblins_TST"])

    def test_a_tie_goes_to_more_cards_covered_then_the_newest(self):
        result = self.rank({})
        self.assertEqual([r["file"] for r in result["precons"]], ["Dinos_TST", "Elves_TST", "Goblins_TST"])
        # Half of each: the Elf Theme's 5 of 10 beat the Goblin Theme's 2 of 4.
        result = self.rank({"Llanowar Elves": 4, "Pick Your Poison": 1, "Goblin Guide": 2}, fmt="casual")
        self.assertEqual([r["file"] for r in result["precons"]], ["Elves_TST", "Goblins_TST"])

    def test_nothing_cached(self):
        (self.cache / "DeckList.json").unlink()
        with self.assertRaisesRegex(precon_coverage.NotCached, "precons fetch"):
            self.rank({})
        self.seed("DeckList.json", DECK_LIST)
        for file in DECKS:
            (self.cache / "decks" / f"{file}.json").unlink()
        with self.assertRaisesRegex(precon_coverage.NotCached, "precons fetch --format casual"):
            self.rank({}, fmt="casual")

    def test_an_unreadable_deck_file_is_left_out(self):
        (self.cache / "decks" / "Goblins_TST.json").write_text("{not json", encoding="utf-8")
        result = self.rank({})
        self.assertNotIn("Goblins_TST", [r["file"] for r in result["precons"]])
        self.assertEqual(result["cached"], 2)

    def test_the_summary_is_kept_and_follows_a_changed_file(self):
        self.rank({})
        summary = self.cache / precon_coverage.SUMMARY
        self.assertTrue(summary.is_file())
        with mock.patch.object(precons, "cards_of", side_effect=AssertionError("read again")):
            self.rank({})                       # every file unchanged: read from the summary
        path = self.seed("decks/Goblins_TST.json", {"data": {"mainBoard": [card("Goblin Guide", 2)]}})
        later = time.time() + 5
        os.utime(path, (later, later))
        goblins = next(r for r in self.rank({"Goblin Guide": 4})["precons"] if r["file"] == "Goblins_TST")
        self.assertEqual((goblins["have"], goblins["total"]), (2, 2))


class FetchTests(CoverageTestCase):

    def test_fetches_only_the_listed_decks_not_cached(self):
        self.fetch.side_effect = lambda url, limit: json.dumps({"data": {"mainBoard": []}}).encode()
        with mock.patch.object(precons, "TTL", 10 ** 9):
            fetched, failed, todo = precon_coverage.fetch(out=io.StringIO(), pause=0)
        self.assertEqual((fetched, failed, todo), (1, 0, 1))
        self.assertEqual([c.args[0] for c in self.fetch.call_args_list], [precons.DECK_URL.format("NotCached_TST")])
        self.assertTrue((self.cache / "decks" / "NotCached_TST.json").is_file())

    def test_a_format_fetches_only_its_decks(self):
        with mock.patch.object(precons, "TTL", 10 ** 9):
            self.assertEqual(precon_coverage.fetch("commander", out=io.StringIO(), pause=0), (0, 0, 0))
        self.fetch.assert_not_called()


class CommandLineTests(CoverageTestCase):

    def run_cli(self, *argv, owned=None):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(pool, "load_pool", return_value=fake_pool(owned or {})) as load, \
                mock.patch.object(entry, "command", contextlib.nullcontext), \
                mock.patch.object(precon_coverage, "card_name", as_written), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = precon_coverage.main(["coverage", *argv])
        return code, out.getvalue(), err.getvalue(), load

    def test_prints_the_ranking(self):
        code, out, _, load = self.run_cli("--space", "user2", "--format", "casual", owned={"Goblin Guide": 4})
        self.assertEqual(code, 0)
        load.assert_called_once_with("user2")
        lines = out.splitlines()
        self.assertIn("user2 pool", lines[0])
        self.assertIn("100%  4/4  Goblin Theme (Test Set, Theme Deck, 2024-01-01)  Goblins_TST", lines[1])
        self.assertIn("0/10  Elf Theme", lines[2])
        self.assertIn("Only 2 of the 3 listed precons are cached", lines[3])
        self.assertIn("precons fetch --format casual", lines[3])

    def test_json(self):
        code, out, _, _ = self.run_cli("--json", "--limit", "1")
        self.assertEqual(code, 0)
        self.assertEqual([r["file"] for r in json.loads(out)["precons"]], ["Dinos_TST"])

    def test_no_cache_says_what_to_fetch_without_reading_the_pool(self):
        (self.cache / "DeckList.json").unlink()
        code, _, err, load = self.run_cli()
        self.assertEqual(code, 1)
        self.assertIn("python -m decklab.lib.precons fetch", err)
        load.assert_not_called()


INDEX = cards.INDEX_FILE


@unittest.skipUnless(Path(INDEX).is_file(), "no card index (python -m decklab.lib.cards update)")
class RealCardNameTests(CoverageTestCase):

    def test_a_printing_names_its_card(self):
        free = Counter({"Llanowar Elves": 4})
        lines = [["Deck", "llanowar elves", "zzz", "0", 2], ["Deck", "Forest", "zzz", "0", 9]]
        self.assertEqual(precon_coverage.score(lines, free)["have"], 2)


if __name__ == "__main__":
    unittest.main()
