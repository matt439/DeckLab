"""The fake-process start log can be read during an append; no processes are started here."""
import tempfile
import types
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from decklab.tests.test_forge import ForgeCase
from decklab.tests.fixtures import fake_forge


class StartLogTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix="decklab-start-log-")
        self.addCleanup(folder.cleanup)
        self.log = Path(folder.name) / "starts.log"
        self.case = types.SimpleNamespace(log=self.log)

    def starts(self):
        return ForgeCase.starts(self.case)

    def test_missing_log_has_no_starts(self):
        self.assertEqual(self.starts(), [])

    def test_concurrent_appends_and_blank_records_preserve_complete_starts(self):
        self.log.write_text("\n  \t\n123 7 1.25\n\n456 8 2.5\n\n", encoding="utf-8")
        self.assertEqual(self.starts(), [(123, 7, 1.25), (456, 8, 2.5)])
        with ThreadPoolExecutor(max_workers=2) as writers:
            list(writers.map(lambda seed: fake_forge.log_start(self.log, seed), range(100, 108)))
        rows = self.starts()
        self.assertEqual(len(rows), 10)
        self.assertEqual({seed for _, seed, _ in rows}, {7, 8, *range(100, 108)})
        self.assertLess(self.log.stat().st_size, 1024)  # locking beyond EOF added no padding

    def test_incomplete_trailing_record_appears_only_after_its_newline(self):
        self.log.write_text("123 7 1.25\n456 ", encoding="utf-8")
        self.assertEqual(self.starts(), [(123, 7, 1.25)])
        with self.log.open("a", encoding="utf-8") as stream:
            stream.write("8 2.5")
        self.assertEqual(self.starts(), [(123, 7, 1.25)])
        with self.log.open("a", encoding="utf-8") as stream:
            stream.write("\n")
        self.assertEqual(self.starts(), [(123, 7, 1.25), (456, 8, 2.5)])

    def test_malformed_complete_records_are_still_rejected(self):
        for record in ("123 7\n", "123 7 1.25 extra\n", "bad 7 1.25\n", "123 7 bad\n"):
            with self.subTest(record=record):
                self.log.write_text("123 7 1.25\n" + record, encoding="utf-8")
                with self.assertRaises(ValueError):
                    self.starts()
