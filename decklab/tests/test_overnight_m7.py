"""Tests for the combined run's M7 (D4b): the external decks and published human win rates in
forge-trial/m7, prepare-inputs copying them, the m7 leg's counting, and the report's comparison
(Spearman, Bradley-Terry, favourite agreement), which is P3 and never a gate.

Run from the repo root: python -m unittest discover -s decklab/tests -t .
"""
import json
import re
import sys
import tempfile
import unicodedata
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parents[1] / "forge-trial"
sys.path.insert(0, str(HERE))

import overnight                 # noqa: E402
import overnight_legs            # noqa: E402
import overnight_report          # noqa: E402

M7 = HERE / "m7"
SCRIPTS = HERE.parent / "data" / "forge" / "cardscripts-2.0.15.json"


def _main_lines(path):
    section, rows = None, []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line.startswith("[") and line.endswith("]"):
            section = line.lower()
            continue
        m = re.match(r"^(\d+)\s+(.+?)\s*$", line)
        if m and section in ("[main]", "[sideboard]"):
            rows.append((section, int(m[1]), m[2]))
    return rows


def _row(a, b, play, draw, games=None):
    return {"a": a, "b": b, "games": games or play[0] + draw[0], "play": list(play), "draw": list(draw),
            "no_winner": 0}


class InputsTest(unittest.TestCase):
    def setUp(self):
        self.human = json.loads((M7 / "human.json").read_text(encoding="utf-8"))

    def test_decks_and_cells(self):
        ids = [d["id"] for d in self.human["decks"]]
        self.assertTrue(6 <= len(ids) <= 8)
        self.assertEqual(len(ids), len(set(ids)))
        for d in self.human["decks"]:
            rows = _main_lines(M7 / d["file"])
            self.assertEqual(sum(q for s, q, _ in rows if s == "[main]"), 60, d["id"])
            for key in ("pilot", "event", "date", "list_url"):
                self.assertTrue(d.get(key), (d["id"], key))
        self.assertTrue(self.human["source"]["url"].startswith("https://"))
        self.assertTrue(self.human["source"]["fetched"])
        seen = set()
        for c in self.human["cells"]:
            self.assertIn(c["a"], ids)
            self.assertIn(c["b"], ids)
            pair = frozenset((c["a"], c["b"]))
            self.assertNotIn(pair, seen)
            seen.add(pair)
            if c["pct"] is not None:
                self.assertTrue(0 <= c["pct"] <= 100)
                self.assertGreaterEqual(c["n"], 5)         # the source shows no win rate under 5 matches
        self.assertGreaterEqual(sum(c["pct"] is not None for c in self.human["cells"]), 15)

    @unittest.skipUnless(SCRIPTS.is_file(), "Forge's card scripts aren't downloaded")
    def test_every_card_is_in_forge(self):
        names = json.loads(SCRIPTS.read_text(encoding="utf-8"))["names"]

        def fold(s):
            return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c)).lower()
        for d in self.human["decks"]:
            for _, _, name in _main_lines(M7 / d["file"]):
                self.assertEqual(names.get(fold(name)), name, (d["id"], name))

    def test_prepare_copies_the_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertTrue(overnight_legs._copy_m7_inputs(tmp))
            copied = json.loads((Path(tmp) / "m7" / "human.json").read_text(encoding="utf-8"))
            self.assertEqual(copied, self.human)
            for d in copied["decks"]:
                self.assertTrue((Path(tmp) / "m7" / d["file"]).is_file())

    def test_prepare_copies_nothing_without_a_deck_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "src"
            src.mkdir()
            (src / "human.json").write_text(json.dumps({"decks": [{"id": "x", "file": "x.dck"},
                                                                  {"id": "y", "file": "y.dck"}]}), encoding="utf-8")
            (src / "x.dck").write_text("[Main]\n60 Island\n", encoding="utf-8")
            self.assertFalse(overnight_legs._copy_m7_inputs(Path(tmp) / "out", src))
            self.assertFalse((Path(tmp) / "out" / "m7").exists())
            self.assertFalse(overnight_legs._copy_m7_inputs(Path(tmp) / "out", Path(tmp) / "none"))


class PlanTest(unittest.TestCase):
    def test_leg_is_built_and_plan_runs_it_with_inputs(self):
        self.assertIn("m7", overnight.leg_names())
        plan = overnight.load_plan()
        built = {p: {"built": True} for p in overnight.PACKAGES}
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "inputs" / "m7").mkdir(parents=True)
            found = overnight.resolve(plan, tmp, main="M", built=built, legs=overnight.leg_names())
            d4b = next(i for i in found["items"] if i["id"] == "D4b")
            self.assertEqual(d4b["status"], "pending")
            argv, _ = overnight.expand(d4b["cmds"][0], {"OUT": "o", "MAIN": "m"})
            parsed = self._parse(argv[argv.index("m7"):])          # the leg's own parser reads the item's options
            self.assertEqual(parsed.games, 400)
            self.assertEqual(parsed.max_min, 45)
        with tempfile.TemporaryDirectory() as tmp:
            found = overnight.resolve(plan, tmp, main="M", built=built, legs=overnight.leg_names())
            d4b = next(i for i in found["items"] if i["id"] == "D4b")
            self.assertEqual(d4b["status"], "skipped")
            self.assertEqual(d4b["why"], "no inputs (m7)")

    def _parse(self, argv):
        seen = {}

        def fake(args):
            seen["args"] = args
            return 0
        old = overnight_legs.leg_m7
        overnight_legs.leg_m7 = fake
        try:
            self.assertEqual(overnight_legs.main(argv), 0)
        finally:
            overnight_legs.leg_m7 = old
        return seen["args"]

    def test_counts(self):
        games = [{"first": 0, "w": 0}, {"first": 0, "w": 1}, {"first": 1, "w": 0}, {"first": 1, "w": None}]
        self.assertEqual(overnight_legs._m7_counts(games, 0), {"play": [2, 1], "draw": [2, 1], "no_winner": 1})
        self.assertEqual(overnight_legs._m7_counts(games, 1), {"play": [2, 0], "draw": [2, 1], "no_winner": 1})


class StatsTest(unittest.TestCase):
    def test_spearman(self):
        sp = overnight_report.spearman
        self.assertAlmostEqual(sp([1, 2, 3, 4], [10, 20, 30, 40]), 1.0)
        self.assertAlmostEqual(sp([1, 2, 3, 4], [4, 3, 2, 1]), -1.0)
        self.assertAlmostEqual(sp([1, 2, 2, 3], [1, 2, 2, 3]), 1.0)
        self.assertIsNone(sp([1, 2], [1, 2]))
        self.assertIsNone(sp([1, 1, 1], [1, 2, 3]))

    def test_bradley_terry_orders_and_stays_finite(self):
        bt = overnight_report.bradley_terry(["a", "b", "c"], [("a", "b", 70, 100), ("b", "c", 70, 100),
                                                              ("a", "c", 100, 100)])
        self.assertGreater(bt["a"], bt["b"])
        self.assertGreater(bt["b"], bt["c"])
        self.assertAlmostEqual(sum(bt.values()), 0, places=3)
        lone = overnight_report.bradley_terry(["a", "b", "z"], [("a", "b", 5, 10)])
        self.assertEqual(lone["z"], lone["z"])          # an unplayed deck keeps a finite rating


class ReportTest(unittest.TestCase):
    HUMAN = {"source": {"name": "S", "url": "https://x", "fetched": "2026-10-03", "window": "w"},
             "decks": [{"id": "a", "archetype": "A", "file": "a.dck"}, {"id": "b", "archetype": "B", "file": "b.dck"},
                       {"id": "c", "archetype": "C", "file": "c.dck"}],
             "cells": [{"a": "a", "b": "b", "pct": 70, "n": 10}, {"a": "c", "b": "b", "pct": 30, "n": 10},
                       {"a": "a", "b": "c", "pct": None, "n": 2}]}

    def write(self, tmp, rows):
        folder = Path(tmp) / "D" / "m7"
        folder.mkdir(parents=True)
        (folder / "result.json").write_text(json.dumps({"leg": "m7", "args": {"games": 400}, "human": self.HUMAN,
                                                        "rows": rows, "complete": True}), encoding="utf-8")

    def test_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.write(tmp, [_row("a", "b", (200, 140), (200, 120)), _row("a", "c", (200, 180), (200, 160)),
                             _row("b", "c", (200, 80), (200, 80))])
            m7 = overnight_report.m7_summary(tmp)
        self.assertTrue(m7["ran"])
        self.assertEqual(m7["pairs_played"], 3)
        self.assertEqual(len(m7["cells"]), 2)                       # the cell without a win rate is left out
        cells = {(c["a"], c["b"]): c for c in m7["cells"]}
        self.assertAlmostEqual(cells[("a", "b")]["forge"], 0.65)
        self.assertAlmostEqual(cells[("c", "b")]["forge"], 0.6)       # from b's row, turned round
        self.assertEqual((m7["sign_agree"], m7["sign_decided"]), (1, 2))
        self.assertGreater(m7["bt_forge"]["a"], m7["bt_forge"]["c"])
        text = "\n".join(overnight_report._m7_markdown(m7))
        self.assertIn("never a gate", text)
        self.assertIn("| A vs B | 70% (10) | 65% | yes |", text)
        self.assertIn("| C vs B | 30% (10) | 60% | no |", text)
        self.assertIn("Caveat", text)

    def test_errors_listed_and_not_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.write(tmp, [_row("a", "b", (200, 140), (200, 120)), {"a": "a", "b": "c", "error": "ForgeError: x"},
                             {"a": "b", "b": "c", "skipped": "over the leg's 75 minutes"}])
            m7 = overnight_report.m7_summary(tmp)
            self.assertEqual(m7["pairs_played"], 1)
            text = "\n".join(overnight_report._m7_markdown(m7))
            self.assertIn("a vs c (ForgeError: x)", text)
        with tempfile.TemporaryDirectory() as tmp:
            state = {"items": {"D4b": {"status": "skipped", "note": "no inputs (m7)"}}}
            m7 = overnight_report.m7_summary(tmp, state, {})
            self.assertEqual(m7, {"ran": False, "why": "no inputs (m7)"})
            self.assertIn("M7 didn't run: no inputs (m7).", overnight_report._m7_markdown(m7))

    def test_report_never_fails_or_gates_on_m7(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / "D" / "m7"
            folder.mkdir(parents=True)
            (folder / "result.json").write_text('{"human": {"decks": [{"no_id": 1}]}}', encoding="utf-8")
            found = overnight_report.build(tmp)
            self.assertFalse(found["m7"]["ran"])
            self.assertIn("couldn't read it", found["m7"]["why"])
            self.assertNotIn("M7", found["gates"])
            self.assertNotIn("D4b", [g for g in found["gates"]])
            overnight_report.write(tmp)
            self.assertIn("## External check (M7", (Path(tmp) / "REPORT.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
