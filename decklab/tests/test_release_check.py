"""Whether a newer release is out (E11-S49, lib/release_check.py): only a release install asks, at most
once a day, from a background thread, and nothing is downloaded. The network is replaced throughout:
urlopen fails the test if anything reaches it unexpectedly, and the saved answer is in a temporary folder."""
import io
import json
import tempfile
import unittest
import urllib.error
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from decklab.lib import build, config, release_check

NOW = datetime(2026, 11, 5, 3, 0, tzinfo=timezone.utc)


class _Answer(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def _github(tag="v1.3.0", url="https://github.com/matt439/DeckLab/releases/tag/v1.3.0"):
    return _Answer(json.dumps({"tag_name": tag, "html_url": url, "assets": [{"browser_download_url": "x"}]}).encode())


class VersionTests(unittest.TestCase):
    def test_versions_compare_as_semantic_versions(self):
        self.assertTrue(release_check.is_newer("v1.10.0", "1.9.3"))
        self.assertTrue(release_check.is_newer("1.2.0", "1.2.0-rc.2"))
        self.assertTrue(release_check.is_newer("1.2.0-rc.10", "1.2.0-rc.2"))
        self.assertTrue(release_check.is_newer("1.2.0-rc.1", "1.2.0-1"))
        self.assertFalse(release_check.is_newer("V1.2.0", "1.2.0"))
        self.assertFalse(release_check.is_newer("1.2.0+build.5", "1.2.0"))
        self.assertFalse(release_check.is_newer("1.1.9", "1.2.0"))
        for bad in ("latest", "1.2", "", None, "1.2.0-", "1.2.0-a..b"):
            with self.subTest(bad=bad):
                self.assertIsNone(release_check.is_newer(bad, "1.2.0"))


class ReleaseCheckTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix="decklab-release-check-")
        self.addCleanup(folder.cleanup)
        self.file = Path(folder.name) / "data" / "release-check.json"
        mock.patch.object(release_check, "cache_file", return_value=self.file).start()
        self.settings = {}
        mock.patch.object(config, "load", side_effect=lambda: dict(self.settings)).start()
        self.release = mock.patch.object(build, "is_release", return_value=True).start()
        mock.patch.object(build, "status", return_value={"version": "1.2.0"}).start()
        self.now = NOW
        mock.patch.object(release_check, "_now", side_effect=lambda: self.now).start()
        self.urlopen = mock.patch("urllib.request.urlopen", side_effect=AssertionError("no network")).start()
        self.start_patch = mock.patch.object(release_check, "_start")
        self.start = self.start_patch.start()
        mock.patch.object(release_check, "_thread", None).start()
        self.addCleanup(mock.patch.stopall)

    def saved(self):
        return json.loads(self.file.read_text(encoding="utf-8"))

    def test_a_git_checkout_asks_nothing(self):
        self.release.return_value = False
        self.assertIsNone(release_check.view())
        self.start.assert_not_called()
        self.urlopen.assert_not_called()
        self.assertFalse(self.file.exists())

    def test_turned_off_in_config_asks_nothing(self):
        for setting in (False, "not a repo", 3):
            with self.subTest(setting=setting):
                self.settings = {"release_check": setting}
                found = release_check.view()
                self.assertEqual((found["enabled"], found["current"], found["checking"]), (False, "1.2.0", False))
        self.start.assert_not_called()

    def test_first_view_starts_a_check_without_waiting(self):
        found = release_check.view()
        self.start.assert_called_once_with("matt439/DeckLab")
        self.assertEqual((found["checking"], found["latest"], found["newer"], found["checked_on"]), (True, None, None, None))
        self.settings = {"release_check": "someone/fork"}
        release_check.view()
        self.start.assert_called_with("someone/fork")

    def test_a_check_saves_the_latest_release_and_downloads_nothing(self):
        self.urlopen.side_effect = None
        self.urlopen.return_value = _github()
        release_check.check("matt439/DeckLab")
        request = self.urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "https://api.github.com/repos/matt439/DeckLab/releases/latest")
        self.assertEqual(request.get_header("Accept"), "application/vnd.github+json")
        self.assertNotIn("@", request.get_header("User-agent"))
        self.assertLessEqual(self.urlopen.call_args.kwargs["timeout"], 10)
        self.assertEqual(self.urlopen.call_count, 1)
        self.assertEqual(self.saved()["latest"], "v1.3.0")
        found = release_check.view()
        self.assertEqual((found["newer"], found["latest"], found["url"], found["checked_on"], found["failed"], found["checking"]),
                         (True, "v1.3.0", "https://github.com/matt439/DeckLab/releases/tag/v1.3.0", "2026-11-05", False, False))
        self.start.assert_not_called()

    def test_at_most_once_a_day(self):
        self.urlopen.side_effect = None
        self.urlopen.return_value = _github(tag="v1.2.0")
        release_check.check("matt439/DeckLab")
        self.now = NOW + timedelta(hours=23)
        self.assertFalse(release_check.view()["newer"])
        self.start.assert_not_called()
        self.now = NOW + timedelta(days=1)
        self.assertTrue(release_check.view()["checking"])
        self.start.assert_called_once_with("matt439/DeckLab")
        self.start.reset_mock()
        self.now = NOW - timedelta(days=2)       # the clock put back: asks again rather than never
        release_check.view()
        self.start.assert_called_once_with("matt439/DeckLab")

    def test_a_failure_keeps_the_last_good_answer_and_its_date(self):
        self.urlopen.side_effect = None
        self.urlopen.return_value = _github()
        release_check.check("matt439/DeckLab")
        self.now = NOW + timedelta(days=2)
        for failure in (urllib.error.URLError("offline"), TimeoutError(), ValueError("bad json"),
                        urllib.error.HTTPError("u", 403, "rate limited", {}, None)):
            with self.subTest(failure=failure):
                self.urlopen.side_effect = failure
                release_check.check("matt439/DeckLab")
                found = release_check.view()
                self.assertEqual((found["failed"], found["latest"], found["checked_on"], found["newer"]),
                                 (True, "v1.3.0", "2026-11-05", True))
                self.start.assert_not_called()      # the failed attempt counts: asked again tomorrow

    def test_no_release_yet_or_an_odd_answer(self):
        self.urlopen.side_effect = urllib.error.HTTPError("u", 404, "Not Found", {}, None)
        release_check.check("matt439/DeckLab")
        found = release_check.view()
        self.assertEqual((found["failed"], found["latest"], found["newer"], found["checked_on"]), (False, None, False, "2026-11-05"))
        self.urlopen.side_effect = None
        self.urlopen.return_value = _github(tag="nightly")
        release_check.check("matt439/DeckLab")
        self.assertTrue(release_check.view()["failed"])
        self.urlopen.return_value = _github(url="https://example.com/elsewhere")
        release_check.check("matt439/DeckLab")
        self.assertEqual(release_check.view()["url"], "https://github.com/matt439/DeckLab/releases")

    def test_another_repository_ignores_the_saved_answer(self):
        self.urlopen.side_effect = None
        self.urlopen.return_value = _github()
        release_check.check("matt439/DeckLab")
        self.settings = {"release_check": "someone/fork"}
        found = release_check.view()
        self.assertEqual((found["latest"], found["checking"]), (None, True))
        self.start.assert_called_once_with("someone/fork")

    def test_one_background_thread_at_a_time(self):
        self.start_patch.stop()
        thread = mock.Mock()
        thread.is_alive.return_value = True
        with mock.patch("threading.Thread", return_value=thread) as made:
            release_check._start("matt439/DeckLab")
            release_check._start("matt439/DeckLab")
        made.assert_called_once()
        self.assertTrue(made.call_args.kwargs["daemon"])
        thread.start.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
