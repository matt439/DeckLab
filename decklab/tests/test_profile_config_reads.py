"""E11-S89: one profile read checks each guarded path for links once, and still refuses
a pending edit (before or during the read) and a linked config, control or data folder."""
import os
from collections import Counter
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from decklab.lib import config, profile_config


class ProfileConfigReadTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="decklab-profile-read-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.config_file = self.root / "decklab" / "config.json"
        self.control = self.config_file.parent / "data" / "profile-config"
        self.journal = self.control / "pending.json"
        patch = mock.patch.object(config, "CONFIG_FILE", self.config_file)
        patch.start()
        self.addCleanup(patch.stop)
        self.settings = {"profiles": [{"id": "user1", "emails": ["user1@example.com"]}]}
        load = mock.patch.object(config, "load", side_effect=lambda: dict(self.settings))
        self.load = load.start()
        self.addCleanup(load.stop)

    def _counting(self, linked=()):
        """Patch Path.is_symlink to count each path checked; paths in `linked` read as links."""
        counts = Counter()
        original = Path.is_symlink

        def is_symlink(path):
            counts[Path(path)] += 1
            return Path(path) in linked or original(path)

        return counts, mock.patch.object(Path, "is_symlink", is_symlink)

    def test_each_guarded_path_is_checked_once_per_read(self):
        counts, patch = self._counting()
        with patch:
            self.assertEqual(profile_config.read_settings(), self.settings)
        for path in (self.config_file, self.control, self.journal, self.control.parent,
                     self.config_file.parent, self.root):
            self.assertEqual(counts[path], 1, path)
        self.assertEqual(max(counts.values()), 1, counts)

    def test_old_require_ready_walked_the_shared_folders_three_times(self):
        # The comparison the story's evidence measured: a read used to call this twice.
        counts, patch = self._counting()
        with patch:
            profile_config.require_ready()
        self.assertEqual(counts[self.root], 3)

    def test_no_cache_across_calls(self):
        counts, patch = self._counting()
        with patch:
            profile_config.read_settings()
            profile_config.read_settings()
        self.assertEqual(counts[self.journal], 2)
        self.assertEqual(self.load.call_count, 2)

    def test_pending_edit_before_the_read_is_refused(self):
        self.control.mkdir(parents=True)
        self.journal.write_text("{}", encoding="utf-8")
        with self.assertRaises(profile_config.PendingProfileEdit):
            profile_config.read_settings()
        self.load.assert_not_called()

    def test_pending_edit_appearing_during_the_read_is_refused(self):
        def load():
            self.control.mkdir(parents=True)
            self.journal.write_text("{}", encoding="utf-8")
            return dict(self.settings)

        self.load.side_effect = load
        with self.assertRaises(profile_config.PendingProfileEdit) as caught:
            profile_config.read_settings()
        self.assertEqual(str(caught.exception), profile_config.PENDING)

    def test_linked_paths_are_refused(self):
        for linked in (self.control, self.control.parent, self.config_file.parent, self.config_file,
                       self.journal):
            with self.subTest(linked=linked):
                counts, patch = self._counting(linked={linked})
                with patch, self.assertRaises(profile_config.InvalidProfileEdit):
                    profile_config.read_settings()
                self.load.assert_not_called()

    def test_a_real_linked_data_folder_is_refused(self):
        target = self.root / "elsewhere"
        target.mkdir()
        self.config_file.parent.mkdir(parents=True)
        try:
            os.symlink(target, self.config_file.parent / "data", target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("this account can't make symbolic links")
        with self.assertRaises(profile_config.InvalidProfileEdit):
            profile_config.read_settings()
        with self.assertRaises(profile_config.InvalidProfileEdit):
            profile_config.require_ready()
        self.load.assert_not_called()

    def test_a_junction_reads_as_linked(self):
        with mock.patch.object(Path, "is_junction", lambda path: Path(path) == self.control):
            with self.assertRaises(profile_config.InvalidProfileEdit):
                profile_config.read_settings()

    def test_read_and_require_ready_check_the_same_journal(self):
        # One layout helper: read_settings(), require_ready() and the edit journal agree.
        self.assertEqual(profile_config._guarded_pending(), profile_config.journal_file())
        self.assertEqual(profile_config.journal_file(), self.journal)
        self.assertEqual(profile_config.control(), self.control)


if __name__ == "__main__":
    unittest.main()
