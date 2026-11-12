"""The stats, goldfish and tokens command lines end in one sentence and the documented exit
code (E11-S92): a deck that can't be found or read exits 1 (with --all, it's skipped with a
note), an unreachable database exits 2; and goldfish --all's mull% column shows a Commander
deck's "kept fewer than 7", the deck page's figure, while 60-card decks keep the mulligan rate.

No database, card data or simulation: the deck readers and the simulation are stand-ins.
Run from the repo root: python scripts/test_fixtures.py test_deck_cli_errors
"""
import contextlib
import io
import unittest
from unittest import mock

from decklab.lib import decks, inventory, stats, tokens
from decklab.lib.goldfish import cli as goldfish_cli, results as goldfish_results

UNREACHABLE = inventory.Unavailable("The database isn't reachable: Deck Lab can't read the decks.")


def run(main, argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(argv)
    return code, out.getvalue(), err.getvalue()


def summary(deck_id, kind="casual", versions=("target",), **extra):
    return {"id": deck_id, "kind": kind, "title": deck_id, "space": "home", "versions": list(versions), **extra}


def fake_goldfish(kind, rate, kept7, free_rate=None):
    """A saved goldfish result with only what the --all table reads."""
    setup = "multiplayer" if kind == "commander" else "play"
    kept = [{"cards": 7, "share": kept7}, {"cards": 6, "share": round(1 - kept7, 6)}]
    return {"kind": kind, "seconds": 0.1, "results": {setup: {
        "mulligans": {"rate": rate, "free_rate": free_rate, "kept": kept},
        "land_drops": {"on_time": [{"land": t, "chance": 0.9} for t in range(1, 6)]},
        "colours": {"screw_turns": 0.05}, "flood": {"turns": 0.1}, "first_big": {"by_turn_4": 0.6}}}}


class OneLineErrors:
    """The same cases for stats and goldfish (main and the module that holds deck_stats or runs)."""
    main = None

    def assertOneLine(self, text):
        self.assertEqual(len(text.strip().splitlines()), 1, text)
        self.assertNotIn("Traceback", text)

    def test_missing_deck_exits_1_in_one_line(self):
        with mock.patch.object(decks, "find_summary", return_value=None):
            code, out, err = run(self.main, ["casual/nothing-here"])
        self.assertEqual(code, 1)
        self.assertOneLine(err)
        self.assertIn("casual/nothing-here", err)

    def test_pairing_owned_exits_1_in_one_line(self):
        # HISTORY.md's known low issue: stats <pairing> --owned ended in a DeckNotFound traceback.
        with mock.patch.object(decks, "find_summary", return_value=summary("pairing/a+b")):
            code, out, err = run(self.main, ["pairing/a+b", "--owned"])
        self.assertEqual(code, 1)
        self.assertOneLine(err)
        self.assertIn("only has a Planned list", err)

    def test_missing_play_now_list_exits_1(self):
        with mock.patch.object(decks, "find_summary", return_value=summary("casual/elves")), \
                mock.patch.object(decks, "load_deck", side_effect=decks.DeckNotFound("casual/elves has no Play-now list")):
            code, out, err = run(self.main, ["casual/elves", "--owned"])
        self.assertEqual(code, 1)
        self.assertOneLine(err)
        self.assertIn("no Play-now list", err)

    def test_unreadable_deck_exits_1(self):
        with mock.patch.object(decks, "find_summary", return_value=summary("casual/elves")), \
                mock.patch.object(decks, "load_deck", side_effect=decks.DeckFileError("casual/elves: no decklist")):
            code, out, err = run(self.main, ["casual/elves"])
        self.assertEqual((code, err.strip()), (1, "casual/elves: no decklist"))

    def test_summary_with_an_error_exits_1(self):
        broken = summary("product/bad", error="bad quantity 'x'")
        with mock.patch.object(decks, "find_summary", return_value=broken):
            code, out, err = run(self.main, ["product/bad"])
        self.assertEqual(code, 1)
        self.assertOneLine(err)
        self.assertIn("bad quantity", err)

    def test_unreachable_database_exits_2(self):
        with mock.patch.object(decks, "find_summary", side_effect=UNREACHABLE):
            code, out, err = run(self.main, ["casual/elves"])
        self.assertEqual((code, err.strip()), (2, str(UNREACHABLE)))

    def test_unreachable_database_with_all_exits_2(self):
        with mock.patch.object(decks, "list_decks", side_effect=UNREACHABLE):
            code, out, err = run(self.main, ["--all"])
        self.assertEqual((code, err.strip()), (2, str(UNREACHABLE)))


class StatsErrors(OneLineErrors, unittest.TestCase):
    main = staticmethod(stats.main)

    def test_all_skips_a_deck_it_cant_read_with_a_note(self):
        listed = [summary("casual/good"), summary("casual/gone", versions=("target", "owned")),
                  summary("product/bad", error="bad quantity 'x'")]

        def load(deck_id, version="target"):
            if deck_id == "casual/gone" and version == "owned":
                raise decks.DeckNotFound("casual/gone has no Play-now list")
            return {}

        line = {"cards": 60, "lands": 24, "recommended": 24, "verdict": "ok", "average_mv": 2.5,
                "min_bracket": None, "colour_short": [], "colours_ok": True}
        with mock.patch.object(decks, "list_decks", return_value=listed), \
                mock.patch.object(decks, "load_deck", side_effect=load), \
                mock.patch.object(stats, "deck_stats", return_value={}), \
                mock.patch.object(stats, "headline", return_value=line):
            code, out, err = run(stats.main, ["--all"])
        self.assertEqual(code, 0)
        rows = [r.split()[:2] for r in out.splitlines()[1:]]
        self.assertEqual(rows, [["casual/good", "target"], ["casual/gone", "target"]])
        self.assertIn("Skipped casual/gone (owned): casual/gone has no Play-now list", err)
        self.assertIn("Skipped product/bad: bad quantity 'x'", err)
        self.assertNotIn("Traceback", err)


class GoldfishErrors(OneLineErrors, unittest.TestCase):
    main = staticmethod(goldfish_cli.main)

    def all_table(self, listed, results):
        def simulate(sections, kind, *args, **kwargs):
            return results[sections]

        with mock.patch.object(decks, "list_decks", return_value=listed), \
                mock.patch.object(decks, "load_deck", side_effect=lambda deck_id, version="target": deck_id), \
                mock.patch.object(goldfish_cli.runs, "get_or_simulate", side_effect=simulate):
            return run(goldfish_cli.main, ["--all"])

    def test_all_skips_a_deck_it_cant_read_with_a_note(self):
        listed = [summary("casual/good"), summary("product/bad", error="bad quantity 'x'")]
        code, out, err = self.all_table(listed, {"casual/good": fake_goldfish("constructed", 0.2, 0.8)})
        self.assertEqual(code, 0)
        self.assertIn("casual/good", out)
        self.assertNotIn("product/bad", out)
        self.assertEqual(err.strip(), "Skipped product/bad: bad quantity 'x'")

    def test_all_shows_kept_fewer_than_7_for_a_commander_deck(self):
        # The page's figure: 1 - share of games keeping 7 (12.5%), not the free-mulligan rate (51.0%).
        listed = [summary("commander/giada", kind="commander"), summary("casual/gruul")]
        results = {"commander/giada": fake_goldfish("commander", 0.51, 0.875, free_rate=0.45),
                   "casual/gruul": fake_goldfish("constructed", 0.197, 0.803)}
        code, out, err = self.all_table(listed, results)
        self.assertEqual(code, 0, err)
        rows = {line.split()[0]: line.split() for line in out.splitlines()[1:] if line.split()[0] in results}
        self.assertEqual(rows["commander/giada"][2:4], ["multiplayer", "12.5"])
        self.assertEqual(rows["casual/gruul"][2:4], ["play", "19.7"])     # 60-card: today's rate
        self.assertIn("kept fewer than 7", out.splitlines()[-1])


class KeptFewerThan7(unittest.TestCase):
    def test_headline_has_it_beside_the_unchanged_mulligan_rate(self):
        h = goldfish_results.headline(fake_goldfish("commander", 0.51, 0.875, free_rate=0.45))
        self.assertEqual((h["setup"], h["mulligan_rate"], h["kept_fewer_than_7"]), ("multiplayer", 0.51, 0.125))

    def test_a_chance_near_0_is_not_rounded_to_0(self):
        fewer = goldfish_results._kept_fewer_than_7([{"cards": 7, "share": 1 - 3e-8}])
        self.assertTrue(0 < fewer < 1e-6, fewer)
        self.assertEqual(goldfish_results._kept_fewer_than_7([{"cards": 7, "share": 1.0}]), 0)
        self.assertEqual(goldfish_results._kept_fewer_than_7([{"cards": 6, "share": 1.0}]), 1)
        self.assertIsNone(goldfish_results._kept_fewer_than_7([{"cards": 7, "share": None}]))


class TokensErrors(unittest.TestCase):
    def test_unreachable_database_exits_2(self):
        with mock.patch.object(decks, "find_summary", side_effect=UNREACHABLE):
            code, out, err = run(tokens.main, ["casual/elves"])
        self.assertEqual((code, err.strip()), (2, str(UNREACHABLE)))

    def test_unreachable_database_on_check_exits_2(self):
        with mock.patch.object(tokens, "check", side_effect=UNREACHABLE):
            code, out, err = run(tokens.main, ["--check"])
        self.assertEqual((code, err.strip()), (2, str(UNREACHABLE)))

    def test_missing_deck_exits_1(self):
        with mock.patch.object(decks, "find_summary", return_value=None):
            code, out, err = run(tokens.main, ["casual/nothing-here"])
        self.assertEqual(code, 1)
        self.assertNotIn("Traceback", out + err)

    def test_pairing_owned_exits_1(self):
        with mock.patch.object(decks, "find_summary", return_value=summary("pairing/a+b")):
            code, out, err = run(tokens.main, ["pairing/a+b", "--owned"])
        self.assertEqual(code, 1)
        self.assertIn("only has a Planned list", out)


if __name__ == "__main__":
    unittest.main()
