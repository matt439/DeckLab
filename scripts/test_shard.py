"""Run one shard of the unittest suite: every Nth test module, for CI's parallel jobs.

Run from the repo root: python scripts/test_shard.py INDEX COUNT [--hang-after SECONDS].
Modules are dealt round-robin in name order, so the shards stay within about 10% of each
other without a timing file to keep up. A shard still running after --hang-after seconds
prints every thread's stack and exits, so a hang shows where it is instead of running into
the job's timeout with no output.
"""
import argparse
import faulthandler
import sys
import unittest
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def tests_of(suite):
    for test in suite:
        if isinstance(test, unittest.TestSuite):
            yield from tests_of(test)
        else:
            yield test


def shard(index, count):
    """The tests of shard index (0-based) of count, by module."""
    loader = unittest.TestLoader()
    by_module = defaultdict(list)
    for test in tests_of(loader.discover(str(ROOT / "decklab" / "tests"), top_level_dir=str(ROOT))):
        by_module[type(test).__module__].append(test)      # modules that can't import: unittest.loader's
    modules = sorted(by_module)[index::count]
    return modules, unittest.TestSuite(t for m in modules for t in by_module[m])


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("index", type=int)
    parser.add_argument("count", type=int)
    parser.add_argument("--hang-after", type=int, default=0, help="seconds; 0 waits forever")
    args = parser.parse_args()
    if not 0 <= args.index < args.count:
        parser.error("INDEX must be from 0 to COUNT - 1")
    sys.path.insert(0, str(ROOT))
    if args.hang_after:
        faulthandler.dump_traceback_later(args.hang_after, exit=True)
    modules, suite = shard(args.index, args.count)
    print(f"Shard {args.index + 1} of {args.count}: {len(modules)} modules, {suite.countTestCases()} tests",
          flush=True)
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
