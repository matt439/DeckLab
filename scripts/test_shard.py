"""Run one shard of the unittest suite, for CI's parallel jobs.

Run from the repo root: python scripts/test_shard.py INDEX COUNT [--hang-after SECONDS] [--timings-out FILE].
Modules are dealt heaviest first onto the lightest shard, by the seconds each took in CI
(scripts/test_weights.json, per OS; a module it doesn't list is estimated from its test count),
so the shards finish close together. A stale weights file only costs balance, never coverage.
After the run it prints why tests skipped (with how many), the slowest modules and tests, and on
GitHub Actions adds them to the job summary. A shard still running after --hang-after seconds
prints every thread's stack and exits, so a hang shows where it is instead of running into the
job's timeout with no output.

    python scripts/test_shard.py --merge-timings DIR   # CI's timing artifacts -> scripts/test_weights.json
"""
import argparse
import faulthandler
import sys
import unittest
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import fixture_runtime  # noqa: E402
from scripts import test_report  # noqa: E402  (standard library only, imports no decklab code)

# Install before discovery and on saved-script multiprocessing child imports.
fixture_runtime.install(ROOT)

tests_of = test_report.tests_of


def shard(index, count, weights=None):
    """The modules and tests of shard index (0-based) of count, one TimedSuite per module."""
    fixture_runtime.install(ROOT)
    loader = unittest.TestLoader()
    by_module = defaultdict(list)
    for test in tests_of(loader.discover(str(ROOT / "decklab" / "tests"), top_level_dir=str(ROOT))):
        by_module[type(test).__module__].append(test)      # modules that can't import: unittest.loader's
    sizes = {m: len(tests) for m, tests in by_module.items()}
    bins, _ = test_report.balance(sizes, count, test_report.load_weights() if weights is None else weights)
    modules = bins[index]
    suite = unittest.TestSuite(test_report.TimedSuite(m, by_module[m]) for m in modules)
    return modules, fixture_runtime.protect_suite(suite)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("index", type=int, nargs="?")
    parser.add_argument("count", type=int, nargs="?")
    parser.add_argument("--hang-after", type=int, default=0, help="seconds; 0 waits forever")
    parser.add_argument("--timings-out", help="write {module: seconds} to this JSON file")
    parser.add_argument("--merge-timings", metavar="DIR", help="merge CI timing artifacts into the weights file")
    args = parser.parse_args()
    if args.merge_timings:
        print(test_report.merge_timings(args.merge_timings))
        return 0
    if args.index is None or args.count is None:
        parser.error("INDEX and COUNT are required")
    if not 0 <= args.index < args.count:
        parser.error("INDEX must be from 0 to COUNT - 1")
    sys.path.insert(0, str(ROOT))
    if args.hang_after:
        faulthandler.dump_traceback_later(args.hang_after, exit=True)
    modules, suite = shard(args.index, args.count)
    print(f"Shard {args.index + 1} of {args.count}: {len(modules)} modules, {suite.countTestCases()} tests",
          flush=True)
    counted, timed = test_report.sizes(suite), list(suite)
    result = unittest.TextTestRunner(verbosity=1, durations=15).run(suite)
    test_report.report(f"{test_report.platform_key().title()} shard {args.index + 1} of {args.count}",
                       result, counted, timed, args.timings_out)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
