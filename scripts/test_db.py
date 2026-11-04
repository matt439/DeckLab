"""Run the database integration tests (every decklab/tests/test_*.py mentioning db_support), or one shard of them.

    python scripts/test_db.py [INDEX COUNT] [--require-db] [--hang-after SECONDS] [--timings-out FILE]

This is NOT the fixture runner: it reads the settings and authenticates to the PostgreSQL they name
(CI's throwaway service container), so on the PC run it only when Matt authorizes it for this PC's
database (decklab/README.md, "Database integration tests"). Its data writes are confined to the
throwaway test databases db_support makes. --require-db fails, instead of skipping every test,
when the database can't be used, so a broken service can't pass as a green run of skips.
"""
import argparse
import faulthandler
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import test_report  # noqa: E402


def modules():
    return sorted("decklab.tests." + p.stem for p in (ROOT / "decklab" / "tests").glob("test_*.py")
                  if "db_support" in p.read_text(encoding="utf-8"))


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("index", type=int, nargs="?", default=0)
    parser.add_argument("count", type=int, nargs="?", default=1)
    parser.add_argument("--require-db", action="store_true", help="fail, not skip, when the database can't be used")
    parser.add_argument("--hang-after", type=int, default=0, help="seconds; 0 waits forever")
    parser.add_argument("--timings-out", help="write {module: seconds} to this JSON file")
    args = parser.parse_args()
    if not 0 <= args.index < args.count:
        parser.error("INDEX must be from 0 to COUNT - 1")
    if "scripts.fixture_runtime" in sys.modules:
        parser.error("the database tests can't run under the fixture guards, which disable PostgreSQL")
    if args.hang_after:
        faulthandler.dump_traceback_later(args.hang_after, exit=True)
    from decklab.tests import db_support
    reason = db_support.unavailable()
    if reason and args.require_db:
        print(f"The database can't be used: {reason}", file=sys.stderr)
        return 2
    loader = unittest.TestLoader()
    every = {name: loader.loadTestsFromName(name) for name in modules()}
    sizes = {name: suite.countTestCases() for name, suite in every.items()}
    bins, _ = test_report.balance(sizes, args.count, {})
    names = bins[args.index]
    suite = unittest.TestSuite(test_report.TimedSuite(name, [every[name]]) for name in names)
    print(f"Database shard {args.index + 1} of {args.count}: {len(names)} modules, "
          f"{suite.countTestCases()} tests", flush=True)
    counted, timed = test_report.sizes(suite), list(suite)
    result = unittest.TextTestRunner(verbosity=1, durations=15).run(suite)
    test_report.report(f"Database shard {args.index + 1} of {args.count}", result, counted, timed,
                       args.timings_out)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
