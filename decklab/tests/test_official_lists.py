"""E9-S24: the newest Commander announcement in Wizards' sitemap, the daily
conditional check that keeps the last good result, and its step of
cards.update(). A small made-up sitemap; no network."""
import gzip
import io
import shutil
import tempfile
import unittest
import urllib.error
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from decklab.lib import card_index, cards, official_lists
from decklab.lib.stats import constants


BASE = "https://magic.wizards.com/en/news/announcements/"
# Each slug style Wizards has used, a generic Banned and Restricted post, an
# Arena one, Commander posts that aren't about the lists, a newer lastmod on an
# older post (lastmod is the last edit, never the publish date) and a page
# outside the announcements.
SITEMAP = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
<url><loc>https://magic.wizards.com/en/news</loc><lastmod>2026-10-20T18:06:24.425Z</lastmod></url>
<url><loc>{BASE}commander-banned-and-restricted-announcement-september-23-2024</loc>
  <lastmod>2026-10-19T00:00:00Z</lastmod></url>
<url><loc>{BASE}commander-bans-and-restrictions-april-22-2025</loc></url>
<url><loc>{BASE}commander-brackets-beta-update-october-21-2025</loc></url>
<url><loc>{BASE}commander-format-panel-update-december-11-2025</loc></url>
<url><loc>{BASE}commander-banned-and-restricted-february-9-2026</loc></url>
<url><loc>{BASE}commander-brackets-beta-update-february-9-2026</loc><lastmod>2026-02-10T00:00:00Z</lastmod></url>
<url><loc>{BASE}commander-banned-list-and-philosophy-update-2019-07-08</loc></url>
<url><loc>{BASE}introducing-commander-brackets-beta</loc><lastmod>2026-10-20T00:00:00Z</lastmod></url>
<url><loc>{BASE}october-12-2026-banned-and-restricted-announcement</loc></url>
<url><loc>{BASE}mtg-arena-banned-and-restricted-announcement-october-22-2026</loc></url>
<url><loc>{BASE}star-trek-commander-decklists</loc></url>
<url><loc>{BASE}starter-commander-decks-available-december-2-2026-09-29</loc></url>
<url><loc>https://magic.wizards.com/en/news/feature/commander-brackets-explained-march-1-2026</loc></url>
</urlset>
""".encode("utf-8")
NEWEST = {"date": "2026-02-09", "url": BASE + "commander-brackets-beta-update-february-9-2026"}


class FakeResponse:
    def __init__(self, body, headers):
        self.body, self.headers = io.BytesIO(body), dict(headers)

    def read(self, size=-1):
        return self.body.read(size)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class SlugTests(unittest.TestCase):
    def test_each_slug_style_has_its_publish_date(self):
        for slug, when in (("commander-brackets-beta-update-february-9-2026", date(2026, 2, 9)),
                           ("commander-bans-and-restrictions-april-22-2025", date(2025, 4, 22)),
                           ("commander-banned-and-restricted-announcement-september-23-2024", date(2024, 9, 23)),
                           ("commander-format-panel-update-december-11-2025", date(2025, 12, 11)),
                           ("commander-banned-list-and-philosophy-update-2019-07-08", date(2019, 7, 8)),
                           ("Commander-Game-Changers-Update-May-4-2027/", date(2027, 5, 4))):
            with self.subTest(slug=slug):
                self.assertEqual(official_lists.announcement_date(slug), when)

    def test_posts_that_dont_count(self):
        for slug in ("october-12-2026-banned-and-restricted-announcement",        # no "commander"
                     "mtg-arena-banned-and-restricted-announcement-october-22-2024",
                     "star-trek-commander-decklists",                             # not about the lists
                     "introducing-commander-brackets-beta",                       # no date
                     "commander-brackets-beta-update-february-30-2026"):          # not a date
            with self.subTest(slug=slug):
                self.assertIsNone(official_lists.announcement_date(slug))

    def test_the_newest_by_its_slug_never_its_lastmod_brackets_first_on_a_date(self):
        self.assertEqual(official_lists.newest_announcement(SITEMAP), NEWEST)

    def test_sitemaps_that_cant_answer(self):
        index = b'<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><sitemap>' \
                b'<loc>https://magic.wizards.com/en/sitemap-1.xml</loc></sitemap></sitemapindex>'
        none = b'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><url><loc>' \
               + (BASE + "star-trek-commander-decklists").encode() + b"</loc></url></urlset>"
        for body, words in ((index, "index of sitemaps"), (none, "no Commander announcement"),
                            (b"<urlset><url>", "isn't readable XML"), (b"<html></html>", "not <urlset>")):
            with self.subTest(words=words), self.assertRaisesRegex(official_lists.SitemapError, words):
                official_lists.newest_announcement(body)


class UpdateTests(unittest.TestCase):
    NOW = datetime(2026, 10, 21, 4, 0, tzinfo=timezone.utc)

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.path = self.tmp / "official_lists.json"
        self.log, self.requests = [], []
        self.now = self.NOW
        for patch in (mock.patch.object(official_lists, "STATE_FILE", self.path),
                      mock.patch.object(official_lists, "_now", lambda: self.now),
                      mock.patch.object(cards, "_open_url", side_effect=AssertionError("no network"))):
            patch.start()
            self.addCleanup(patch.stop)

    def answer(self, body=SITEMAP, gzipped=True, etag='"new"'):
        def fake(url, accept="application/json", timeout=60, headers=None):
            self.requests.append((url, dict(headers or {})))
            if isinstance(body, BaseException):
                raise body
            headers = {"ETag": etag, "Content-Type": "application/xml"}
            if gzipped:
                headers["Content-Encoding"] = "gzip"
            return FakeResponse(gzip.compress(body) if gzipped else body, headers)
        return fake

    def update(self, answer, force=False):
        with mock.patch.object(cards, "_open_url", side_effect=answer):
            return official_lists.update(force=force, log=self.log.append)

    def test_a_gzipped_sitemap_is_asked_for_and_read(self):
        self.assertTrue(self.update(self.answer()))
        url, headers = self.requests[0]
        self.assertEqual(url, official_lists.SITEMAP_URL)
        self.assertEqual(headers, {"Accept-Encoding": "gzip"})      # nothing stored: not conditional
        self.assertEqual(official_lists.read(), {
            "announcement": NEWEST, "checked_at": "2026-10-21T04:00:00+00:00",
            "last_success_at": "2026-10-21T04:00:00+00:00", "error": None})
        self.assertEqual(cards._read_json(self.path, {})["etag"], '"new"')
        self.assertIn("2026-02-09", self.log[-1])

    def test_a_plain_answer_is_read_too(self):
        self.assertTrue(self.update(self.answer(gzipped=False)))
        self.assertEqual(official_lists.read()["announcement"], NEWEST)

    def test_once_a_day_unless_forced(self):
        self.update(self.answer())
        self.now = self.NOW + timedelta(hours=23)
        self.assertFalse(self.update(AssertionError("checked today already")))
        self.assertEqual(len(self.requests), 1)
        self.assertIn("2026-02-09", self.log[-1])
        self.assertTrue(self.update(self.answer(), force=True))
        self.assertEqual(self.requests[-1][1], {"Accept-Encoding": "gzip"})     # forced: not conditional
        self.now = self.NOW + timedelta(hours=49)
        self.assertTrue(self.update(self.answer()))
        self.assertEqual(len(self.requests), 3)

    def test_the_next_day_asks_conditionally_and_304_keeps_the_result(self):
        self.update(self.answer(etag='"abc"'))
        stored = cards._read_json(self.path, {})
        stored["last_modified"] = "Tue, 20 Oct 2026 18:06:24 GMT"
        cards._write_json(self.path, stored)
        self.now = self.NOW + timedelta(days=1)
        not_modified = urllib.error.HTTPError(official_lists.SITEMAP_URL, 304, "Not Modified", {}, io.BytesIO())
        self.assertTrue(self.update(self.answer(not_modified)))
        self.assertEqual(self.requests[-1][1], {"Accept-Encoding": "gzip", "If-None-Match": '"abc"',
                                                "If-Modified-Since": "Tue, 20 Oct 2026 18:06:24 GMT"})
        found = official_lists.read()
        self.assertEqual(found["announcement"], NEWEST)
        self.assertEqual(found["last_success_at"], "2026-10-22T04:00:00+00:00")
        self.assertIn("unchanged", self.log[-1])

    def test_a_failure_keeps_the_last_good_result(self):
        self.update(self.answer())
        self.now = self.NOW + timedelta(days=2)
        failures = (OSError("offline"),
                    urllib.error.HTTPError(official_lists.SITEMAP_URL, 503, "Unavailable", {}, io.BytesIO()),
                    b"<sitemapindex></sitemapindex>", b"<urlset></urlset>", b"not xml")
        for failure in failures:
            with self.subTest(failure=failure):
                self.assertFalse(self.update(self.answer(failure), force=True))
                found = official_lists.read()
                self.assertEqual(found["announcement"], NEWEST)
                self.assertEqual(found["last_success_at"], "2026-10-21T04:00:00+00:00")
                self.assertEqual(found["checked_at"], "2026-10-23T04:00:00+00:00")
                self.assertTrue(found["error"])
                self.assertIn("keeping the last good result (2026-02-09)", self.log[-1])
        self.assertTrue(self.update(self.answer(), force=True))
        self.assertIsNone(official_lists.read()["error"])

    def test_damaged_gzip_or_huge_answers_fail_safely(self):
        def damaged(url, accept=None, timeout=60, headers=None):
            return FakeResponse(b"\x1f\x8bnot gzip", {"Content-Encoding": "gzip"})
        self.assertFalse(self.update(damaged))
        self.assertIsNone(official_lists.read()["announcement"])
        with mock.patch.object(official_lists, "MAX_SITEMAP", 100):
            self.assertFalse(self.update(self.answer(), force=True))
        self.assertIn("bigger than expected", official_lists.read()["error"])

    def test_never_checked_or_damaged_file_reads_as_never_checked(self):
        empty = {"announcement": None, "checked_at": None, "last_success_at": None, "error": None}
        self.assertEqual(official_lists.read(), empty)
        for text in ("not json", "[]", '{"format": 99, "announcement": {"date": "2026-02-09", "url": "x"}}',
                     '{"format": 1, "announcement": {"date": "soon", "url": "x"}, "last_success_at": "2026-10-21"}'):
            with self.subTest(text=text):
                self.path.write_text(text, encoding="utf-8")
                found = official_lists.read()
                self.assertIsNone(found["announcement"])
                self.assertIsNone(found["last_success_at"])

    def test_a_failing_step_never_fails_the_card_update(self):
        logs = []
        with mock.patch.object(official_lists, "update", side_effect=RuntimeError("disk full")):
            cards._update_official_lists(False, logs.append)
        self.assertIn("disk full", logs[-1])


class RulesDateTests(unittest.TestCase):
    def test_the_rules_date_is_at_least_the_newest_brackets_source(self):
        newest = max(value["date"] for key, value in constants.SOURCES.items() if key.startswith("brackets-"))
        self.assertGreaterEqual(date.fromisoformat(constants.BRACKET_RULES_DATE), date.fromisoformat(newest))


if __name__ == "__main__":
    unittest.main()
