"""Run default fixture checks safely, or select ordinary unittest module/class/method names.

    python scripts/test_fixtures.py [decklab.tests.test_example ...] [--hang-after SECONDS]

Database integration and known native runtime checks require separate explicit qualification.
"""
import argparse
import faulthandler
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import fixture_runtime  # noqa: E402

# Keep outside main: multiprocessing imports saved scripts as __mp_main__ before workers.
fixture_runtime.install(ROOT)


def load(names=()):
    fixture_runtime.install(ROOT)
    loader = unittest.TestLoader()
    suite = (loader.loadTestsFromNames(names) if names else
             loader.discover(str(ROOT / "decklab" / "tests"), top_level_dir=str(ROOT)))
    return fixture_runtime.protect_suite(suite)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("names", nargs="*")
    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument("--hang-after", type=int, default=0)
    args = parser.parse_args()
    if args.hang_after:
        faulthandler.dump_traceback_later(args.hang_after, exit=True)
    result = unittest.TextTestRunner(verbosity=2 if args.verbose else 1).run(load(args.names))
    return not result.wasSuccessful()


if __name__ == "__main__":
    raise SystemExit(main())
