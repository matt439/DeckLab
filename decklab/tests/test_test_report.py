"""scripts/test_report.py: the shards' balancing, the skip ledger and the timing files."""
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import test_db, test_report


class BalanceTests(unittest.TestCase):
    def test_every_module_lands_in_exactly_one_shard(self):
        sizes = {f"m{i:02}": i % 7 + 1 for i in range(40)}
        bins, _ = test_report.balance(sizes, 4, {"m03": 30.0, "m10": 1.0})
        joined = [m for b in bins for m in b]
        self.assertEqual(sorted(joined), sorted(sizes))
        self.assertEqual(len(joined), len(set(joined)))

    def test_heavy_modules_are_spread_and_the_plan_is_deterministic(self):
        sizes = {"a": 1, "b": 1, "c": 1, "d": 1, "e": 1}
        weights = {"a": 100.0, "b": 90.0, "c": 10.0, "d": 10.0, "e": 5.0}
        bins, loads = test_report.balance(sizes, 2, weights)
        self.assertEqual(bins, test_report.balance(sizes, 2, weights)[0])
        self.assertNotEqual(next(i for i, b in enumerate(bins) if "a" in b),
                            next(i for i, b in enumerate(bins) if "b" in b))
        self.assertLessEqual(max(loads) - min(loads), 10.0)

    def test_an_unknown_module_is_estimated_from_its_test_count(self):
        bins, loads = test_report.balance({"known": 10, "new": 20}, 2, {"known": 5.0})
        self.assertEqual(sorted(loads), [5.0, 10.0])
        self.assertEqual([m for b in bins for m in b if m == "new"], ["new"])

    def test_without_weights_it_balances_by_test_count(self):
        bins, loads = test_report.balance({"a": 300, "b": 100, "c": 100, "d": 100}, 2, {})
        self.assertEqual(sorted(map(sorted, bins)), [["a"], ["b", "c", "d"]])

    def test_weights_file_falls_back_to_the_other_os_and_tolerates_junk(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "w.json"
            path.write_text(json.dumps({"windows": {"x": 2}}), encoding="utf-8")
            self.assertEqual(test_report.load_weights(path), {"x": 2.0})
            path.write_text("not json", encoding="utf-8")
            self.assertEqual(test_report.load_weights(path), {})
            self.assertEqual(test_report.load_weights(Path(folder) / "missing.json"), {})


def _samples():
    """Sample cases, made here so discovery doesn't collect them as real tests."""
    class _Skips(unittest.TestCase):
        def test_one(self):
            self.skipTest("needs a thing")

        def test_two(self):
            self.skipTest("needs a thing")

        def test_runs(self):
            pass

    class _ClassSkip(unittest.TestCase):
        @classmethod
        def setUpClass(cls):
            raise unittest.SkipTest("whole class off")

        def test_a(self):
            pass

        def test_b(self):
            pass

        def test_c(self):
            pass

    return _Skips, _ClassSkip


class LedgerTests(unittest.TestCase):
    def run_quietly(self, suite):
        counted, timed = test_report.sizes(suite), list(suite)
        result = unittest.TextTestRunner(stream=io.StringIO(), verbosity=0).run(suite)
        return result, counted, timed

    def test_a_class_skip_counts_every_test_of_its_class(self):
        loader = unittest.TestLoader()
        _Skips, _ClassSkip = _samples()
        suite = unittest.TestSuite([
            test_report.TimedSuite("skips", [loader.loadTestsFromTestCase(_Skips)]),
            test_report.TimedSuite("class", [loader.loadTestsFromTestCase(_ClassSkip)]),
        ])
        result, counted, timed = self.run_quietly(suite)
        self.assertEqual(test_report.skip_ledger(result, counted),
                         [("whole class off", 3), ("needs a thing", 2)])
        self.assertTrue(all(s.seconds >= 0 for s in timed))

    def test_the_report_writes_the_summary_and_the_timings(self):
        suite = unittest.TestSuite([test_report.TimedSuite(
            "skips", [unittest.TestLoader().loadTestsFromTestCase(_samples()[0])])])
        result, counted, timed = self.run_quietly(suite)
        with tempfile.TemporaryDirectory() as folder:
            summary, timings = Path(folder) / "summary.md", Path(folder) / "timings-linux-0.json"
            with mock.patch.dict(os.environ, {"GITHUB_STEP_SUMMARY": str(summary)}), \
                    mock.patch("sys.stdout", io.StringIO()) as out:
                test_report.report("Linux shard 1 of 1", result, counted, timed, timings)
            self.assertIn("2  needs a thing", out.getvalue())
            self.assertIn("| 2 | needs a thing |", summary.read_text(encoding="utf-8"))
            self.assertEqual(list(json.loads(timings.read_text(encoding="utf-8"))), ["skips"])
            weights = Path(folder) / "weights.json"
            self.assertEqual(test_report.merge_timings(folder, weights), {"linux": 1})
            self.assertEqual(list(json.loads(weights.read_text(encoding="utf-8"))), ["linux"])


class DatabaseModuleTests(unittest.TestCase):
    def test_it_selects_the_database_modules(self):
        names = test_db.modules()
        self.assertIn("decklab.tests.test_db_core", names)
        self.assertNotIn("decklab.tests.test_test_report", names)
        self.assertEqual(names, sorted(names))


if __name__ == "__main__":
    unittest.main()
