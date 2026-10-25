"""Exercise CLI signal setup in fresh processes without Appium or a Simulator."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SETUP = r'''
import contextlib, signal, sys
from pathlib import Path
from decklab.safari import environment, runner
output = Path(sys.argv[1])
rows = environment.matrix({}, [])
for row in rows:
    row.update(status="pending", model=row["requested_model"], os_version="test")
runner.environment.source = lambda: {"revision": "a" * 40, "dirty": False}
runner.environment.inspect = lambda *args: {"errors": [], "matrix": rows}
@contextlib.contextmanager
def fake_appium(directory):
    try:
        yield "http://127.0.0.1:1"
    finally:
        (directory / "cleanup.marker").write_text("run-owned cleanup finished", encoding="utf-8")
runner.appium = fake_appium
'''


class SafariCliTests(unittest.TestCase):
    def child(self, script, output):
        env = {key: value for key, value in os.environ.items() if not key.startswith("DECKLAB_")}
        return subprocess.run([sys.executable, "-c", SETUP + script, str(output)],
                              cwd=ROOT, env=env, capture_output=True, text=True,
                              encoding="utf-8", timeout=15)

    def test_cli_replaces_inherited_ignored_sigint_and_finishes_cleanup(self):
        script = r'''
import runpy
signal.signal(signal.SIGINT, signal.SIG_IGN)
def interrupt(*args):
    # raise_signal works on Windows too; with the inherited disposition left
    # untouched, this would return and incorrectly mark the configuration passed.
    signal.raise_signal(signal.SIGINT)
    raise AssertionError("The CLI ignored SIGINT")
runner.run_configuration = interrupt
sys.argv = ["decklab.safari", "--output", str(output)]
runpy.run_module("decklab.safari", run_name="__main__")
'''
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "run"
            result = self.child(script, output)
            self.assertEqual(result.returncode, 130, result.stdout + result.stderr)
            report = json.loads((output / "report.json").read_text(encoding="utf-8"))
            self.assertEqual(report["exit_code"], 130)
            self.assertEqual([row["status"] for row in report["matrix"]],
                             ["interrupted"] + ["not_run"] * 5)
            self.assertTrue((output / "cleanup.marker").is_file())

    def test_library_main_keeps_its_callers_custom_signal_handler(self):
        script = r'''
def caller_handler(signum, frame):
    raise RuntimeError("caller's interrupt policy")
signal.signal(signal.SIGINT, caller_handler)
status = runner.main(["--check", "--output", str(output)])
assert signal.getsignal(signal.SIGINT) is caller_handler
raise SystemExit(status)
'''
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "run"
            result = self.child(script, output)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertFalse((output / "cleanup.marker").exists())


if __name__ == "__main__":
    unittest.main()
