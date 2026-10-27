"""The member-config claim excludes another process and releases its OS lock."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from decklab.lib import config, profile_config


REPO = Path(__file__).resolve().parents[2]
LOCAL_TEMP = (Path(os.environ["USERPROFILE"]) / "AppData" / "Local" / "Temp"
              if os.name == "nt" else Path(tempfile.gettempdir()))
CHILD = """
from pathlib import Path
import sys
from decklab.lib import config, profile_config

config.CONFIG_FILE = Path(sys.argv[1])
try:
    with profile_config.claim():
        print("acquired")
except profile_config.PendingProfileEdit:
    print("busy")
"""


class ProfileConfigLockTests(unittest.TestCase):
    def test_other_process_is_excluded_then_can_acquire_after_release(self):
        with tempfile.TemporaryDirectory(prefix="decklab-profile-lock-", dir=LOCAL_TEMP) as folder:
            config_file = Path(folder) / "decklab" / "config.json"

            def child_result():
                result = subprocess.run([sys.executable, "-c", CHILD, str(config_file)], cwd=REPO,
                                        capture_output=True, text=True, encoding="utf-8", timeout=10)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stderr, "")
                return result.stdout.strip()

            with mock.patch.object(config, "CONFIG_FILE", config_file):
                with profile_config.claim():
                    self.assertEqual(child_result(), "busy")
                self.assertEqual(child_result(), "acquired")
                self.assertFalse(config_file.exists())
                self.assertFalse(profile_config.pending())
