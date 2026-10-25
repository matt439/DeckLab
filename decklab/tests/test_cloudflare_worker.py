"""Runs the off page's Worker tests (decklab/cloudflare/test/, story E11-S02) under Node's own test
runner, so the usual discover run covers them too. Nothing is deployed and nothing reaches the network:
the tests use a stand-in for the PC. Skipped when Node isn't on PATH.

Run from the repo root: python -m unittest discover -s decklab/tests -t .
(or the Worker's tests alone: node --test "decklab/cloudflare/**/*.test.mjs")
"""
from pathlib import Path
import shutil
import subprocess
import unittest

from decklab.lib import server_http

FOLDER = Path(__file__).resolve().parents[1] / "cloudflare"
NODE = shutil.which("node")


class CloudflareWorkerTests(unittest.TestCase):

    @unittest.skipUnless(NODE, "Node isn't installed")
    def test_the_worker_tests_pass(self):
        tests = sorted(str(p) for p in (FOLDER / "test").glob("*.test.mjs"))
        self.assertTrue(tests)
        done = subprocess.run([NODE, "--test", *tests], cwd=FOLDER, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=120)
        self.assertEqual(done.returncode, 0, done.stdout[-4000:] + done.stderr[-2000:])

    def test_the_worker_looks_for_the_servers_header(self):
        # Without the same header name on both sides, the Worker would replace Deck Lab's own 502s and 503s.
        name, value = server_http.ORIGIN_HEADER
        text = (FOLDER / "worker.mjs").read_text(encoding="utf-8")
        self.assertIn(f'export const ORIGIN_HEADER = "{name}";', text)
        self.assertEqual(value, "1")


if __name__ == "__main__":
    unittest.main()
