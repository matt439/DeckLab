"""Tests for decklab.lib.config: the defaults PLAN.md promises.

Run from the repo root: python scripts/test_fixtures.py
"""
import io
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from decklab.lib import config


class ConfigTests(unittest.TestCase):

    def test_forge_defaults_are_the_numbers_milestone_0_measured(self):
        # PLAN.md part 6: 16 workers. forge_batch_games no longer changes anything (forge/lists.py's
        # _batch_count); its 200 is kept only so older config.json files still load.
        self.assertEqual((config.DEFAULTS["forge_workers"], config.DEFAULTS["forge_batch_games"]), (16, 200))
        self.assertEqual(config.DEFAULTS["port"], 8642)

    def test_goldfish_workers_default_is_one_per_core_up_to_16(self):
        # The practice-hand simulation: one worker process per core, at most the 16 physical cores.
        self.assertEqual(config.DEFAULTS["goldfish_workers"], min(16, os.cpu_count() or 1))
        self.assertGreaterEqual(config.DEFAULTS["goldfish_workers"], 1)

    def test_config_json_overrides_the_defaults(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp)
        path = tmp / "config.json"
        with mock.patch.object(config, "CONFIG_FILE", path):
            self.assertEqual(config.load(), config.DEFAULTS)
            path.write_text(json.dumps({"forge_workers": 12}), encoding="utf-8")
            self.assertEqual(config.load(), {**config.DEFAULTS, "forge_workers": 12})

    def test_the_harness_extra_file_is_merged_over_config_json(self):
        # DECKLAB_CONFIG_EXTRA (sim-wave3-contract.md section 17): one log line names the file.
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp)
        path, extra = tmp / "config.json", tmp / "extra.json"
        path.write_text(json.dumps({"forge_workers": 12, "forge_pool_idle_s": 60}), encoding="utf-8")
        extra.write_text(json.dumps({"forge_pool_idle_s": 120, "forge_performance_mode": False}), encoding="utf-8")
        config._said.clear()
        self.addCleanup(config._said.clear)
        stderr = io.StringIO()
        with mock.patch.object(config, "CONFIG_FILE", path), mock.patch.dict(os.environ, {config.EXTRA_ENV: str(extra)}), \
                mock.patch("sys.stderr", stderr):
            self.assertEqual(config.load(), {**config.DEFAULTS, "forge_workers": 12, "forge_pool_idle_s": 120,
                                             "forge_performance_mode": False})
            config.load()
            lines = stderr.getvalue().splitlines()
            self.assertEqual(len(lines), 1)
            self.assertIn(str(extra), lines[0])
            # A file that can't be read as settings is left out, and said once.
            for text in ("[1, 2]", "{not json"):
                extra.write_text(text, encoding="utf-8")
                config._said.clear()
                stderr.truncate(0)
                stderr.seek(0)
                self.assertEqual(config.load(), {**config.DEFAULTS, "forge_workers": 12, "forge_pool_idle_s": 60})
                config.load()
                self.assertEqual(len(stderr.getvalue().splitlines()), 1)
                self.assertIn("can't be read", stderr.getvalue())
        with mock.patch.object(config, "CONFIG_FILE", path), mock.patch.dict(os.environ, {config.EXTRA_ENV: ""}):
            self.assertEqual(config.load()["forge_pool_idle_s"], 60)


if __name__ == "__main__":
    unittest.main()
