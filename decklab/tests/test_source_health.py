"""E11-S85's Data sources: the fetch receipts (lib/source_health.py), the fetchers that write them,
and GET /api/settings/data-sources. Fake fetches and temporary folders only: no network."""
from datetime import date, datetime, timedelta, timezone
import io
import json
from pathlib import Path
import tempfile
import unittest
import urllib.error
from unittest import mock

from decklab.lib import card_freshness, cards, combos, config, edhrec, precons, rulings, source_health
from decklab.lib.api import data_sources, guard
from decklab.lib.api.common import ApiError
from decklab.lib.gauntlet import catalogue

EARLY = datetime(2026, 11, 10, 3, 0, tzinfo=timezone.utc)
LATE = datetime(2026, 11, 11, 3, 0, tzinfo=timezone.utc)


class Folder(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory(prefix="decklab-sources-")))
        self.enterContext(mock.patch.object(config, "DATA", self.root))
        ticks = iter(range(10_000))     # a clock a second on at each receipt, so their order shows
        self.enterContext(mock.patch.object(source_health, "_now",
                                            side_effect=lambda: EARLY + timedelta(seconds=next(ticks))))

    def entry(self, key):
        return source_health.read().get(key)


class ReceiptTests(Folder):
    def test_a_good_fetch_and_a_failure_keep_their_own_times(self):
        self.assertTrue(source_health.record("edhrec", True, EARLY))
        self.assertTrue(source_health.record("edhrec", False, LATE))
        self.assertEqual(self.entry("edhrec"), {"last_ok": "2026-11-10T03:00:00+00:00",
                                                "last_failure": "2026-11-11T03:00:00+00:00"})
        self.assertEqual(source_health.state(self.entry("edhrec")), "failing")
        source_health.record("edhrec", True, LATE + timedelta(hours=1))
        self.assertEqual(source_health.state(self.entry("edhrec")), "ok")

    def test_only_fixed_keys_and_times_are_kept(self):
        self.assertFalse(source_health.record("https://private.example.com/x", True))
        self.assertFalse(source_health.record("edhrec", "failed"))
        source_health.record("mtgjson", False)
        raw = (self.root / "sources.json").read_text(encoding="utf-8")
        self.assertEqual(set(json.loads(raw)["sources"]), {"mtgjson"})
        self.assertEqual(set(json.loads(raw)["sources"]["mtgjson"]), {"last_ok", "last_failure"})

    def test_the_view_lists_every_source_in_order_with_never_for_the_unrecorded(self):
        source_health.record("scryfall", True, EARLY)
        found = source_health.view()
        self.assertTrue(found["readable"])
        self.assertEqual([row["key"] for row in found["sources"]], [key for key, _ in source_health.SOURCES])
        self.assertEqual(found["sources"][0]["state"], "ok")
        self.assertEqual({row["state"] for row in found["sources"][1:]}, {"never"})

    def test_a_damaged_or_oversized_file_is_unreadable_and_left_alone(self):
        target = self.root / "sources.json"
        for text in ("{broken", json.dumps({"version": 2, "sources": {}}), json.dumps({"version": 1, "sources": {"edhrec": 3}}),
                     " " * (source_health.MAX_BYTES + 1)):
            with self.subTest(text=text[:20]):
                target.write_text(text, encoding="utf-8")
                self.assertFalse(source_health.view()["readable"])
                self.assertFalse(source_health.record("edhrec", True))
                self.assertEqual(target.read_text(encoding="utf-8"), text)

    def test_naive_or_malformed_times_are_dropped(self):
        (self.root / "sources.json").write_text(json.dumps({"version": 1, "sources": {
            "fx": {"last_ok": "2026-11-10T03:00:00", "last_failure": "nonsense"}, "unknown": {}}}), encoding="utf-8")
        self.assertEqual(self.entry("fx"), {"last_ok": None, "last_failure": None})
        self.assertNotIn("unknown", source_health.read())

    def test_a_receipt_that_cant_be_written_never_raises(self):
        with mock.patch.object(source_health.tempfile, "mkstemp", side_effect=OSError("disk full")):
            self.assertFalse(source_health.record("edhrec", True))


class FetcherTests(Folder):
    def test_mtgjson_fetch_success_and_failure(self):
        response = mock.MagicMock()
        response.__enter__.return_value = response
        response.read.return_value = b"{}"
        with mock.patch.object(precons.urllib.request, "urlopen", return_value=response):
            self.assertEqual(precons._fetch("https://mtgjson.example.com/x", 100), b"{}")
        self.assertIsNotNone(self.entry("mtgjson")["last_ok"])
        with mock.patch.object(precons.urllib.request, "urlopen", side_effect=urllib.error.URLError("down")), \
                self.assertRaises(urllib.error.URLError):
            precons._fetch("https://mtgjson.example.com/x", 100)
        self.assertEqual(source_health.state(self.entry("mtgjson")), "failing")

    def test_edhrec_answers_count_and_a_missing_page_is_neither(self):
        response = mock.MagicMock()
        response.__enter__.return_value = response
        response.read.return_value = b'{"ok": 1}'
        with mock.patch.object(edhrec, "MIN_GAP", 0), \
                mock.patch.object(edhrec.urllib.request, "urlopen", return_value=response):
            self.assertEqual(edhrec._request("https://edhrec.example.com/x", "x"), {"ok": 1})
        self.assertEqual(source_health.state(self.entry("edhrec")), "ok")
        missing = urllib.error.HTTPError("https://edhrec.example.com/x", 404, "nope", {}, io.BytesIO())
        before = self.entry("edhrec")
        with mock.patch.object(edhrec, "MIN_GAP", 0), \
                mock.patch.object(edhrec.urllib.request, "urlopen", side_effect=missing), \
                self.assertRaises(edhrec.NoPage):
            edhrec._request("https://edhrec.example.com/x", "x")
        self.assertEqual(self.entry("edhrec"), before)
        with mock.patch.object(edhrec, "MIN_GAP", 0), \
                mock.patch.object(edhrec.urllib.request, "urlopen", side_effect=urllib.error.URLError("down")), \
                self.assertRaises(edhrec.EdhrecError):
            edhrec._request("https://edhrec.example.com/x", "x")
        self.assertEqual(source_health.state(self.entry("edhrec")), "failing")

    def test_the_exchange_rate_fetch(self):
        fx = self.root / "fx.json"
        with mock.patch.object(cards, "fx_file", return_value=fx), mock.patch.object(cards, "_fx", None), \
                mock.patch.object(cards, "_fx_tried_on", None), mock.patch.object(cards, "_fx_tried_at", None), \
                mock.patch.object(cards, "_get_json", return_value={"rates": {"AUD": 1.5}, "date": "2026-11-11"}):
            self.assertEqual(cards.usd_to_aud("AUD"), (1.5, "2026-11-11"))
        self.assertEqual(source_health.state(self.entry("fx")), "ok")
        self.assertEqual(json.loads(fx.read_text(encoding="utf-8"))["fetched_on"], date.today().isoformat())
        with mock.patch.object(cards, "fx_file", return_value=self.root / "none.json"), mock.patch.object(cards, "_fx", None), \
                mock.patch.object(cards, "_fx_tried_on", None), mock.patch.object(cards, "_fx_tried_at", None), \
                mock.patch.object(cards, "_get_json", side_effect=OSError("offline")), self.assertRaises(RuntimeError):
            cards.usd_to_aud("AUD")
        self.assertEqual(source_health.state(self.entry("fx")), "failing")

    def test_scryfall_listing_failure_and_rulings_failure(self):
        scryfall = self.root / "scryfall"
        scryfall.mkdir()
        for kind in cards.BULK_TYPES:
            (scryfall / f"{kind}.jsonl.gz").write_bytes(b"")
        with mock.patch.object(cards, "SCRYFALL_DIR", scryfall), \
                mock.patch.object(cards, "BULK_META_FILE", scryfall / "bulk.json"), \
                mock.patch.object(cards, "_get_json", side_effect=OSError("offline")):
            self.assertEqual(cards.download_bulk(force=True, log=lambda *a: None), [])
            self.assertFalse(rulings.update(force=True, log=lambda *a: None))
        self.assertEqual(source_health.state(self.entry("scryfall")), "failing")
        self.assertEqual(source_health.state(self.entry("rulings")), "failing")

    def test_scryfall_unchanged_counts_as_a_good_fetch(self):
        scryfall = self.root / "scryfall"
        scryfall.mkdir()
        meta = {}
        for kind in cards.BULK_TYPES:
            (scryfall / f"{kind}.jsonl.gz").write_bytes(b"")
            meta[kind] = {"updated_at": "2026-11-10T00:00:00+00:00", "downloaded_at": "2026-01-01T00:00:00+00:00"}
        (scryfall / "bulk.json").write_text(json.dumps(meta), encoding="utf-8")
        listing = {"data": [{"type": kind, "updated_at": "2026-11-10T00:00:00+00:00", "jsonl_download_uri": "x"}
                            for kind in cards.BULK_TYPES]}
        with mock.patch.object(cards, "SCRYFALL_DIR", scryfall), \
                mock.patch.object(cards, "BULK_META_FILE", scryfall / "bulk.json"), \
                mock.patch.object(cards, "_get_json", return_value=listing):
            self.assertEqual(cards.download_bulk(log=lambda *a: None), [])
        self.assertEqual(source_health.state(self.entry("scryfall")), "ok")

    def test_commander_spellbook_download_failure_and_not_modified(self):
        folder = self.root / "combos"
        folder.mkdir()
        patches = dict(META_FILE=folder / "meta.json", EXPORT_FILE=folder / "variants.json.gz",
                       TWO_CARD_FILE=folder / "two_card.json")
        with mock.patch.multiple(combos, **patches), \
                mock.patch.object(cards, "_download", side_effect=OSError("offline")):
            self.assertFalse(combos.update(force=True, log=lambda *a: None))
        self.assertEqual(source_health.state(self.entry("spellbook")), "failing")
        not_modified = urllib.error.HTTPError(combos.EXPORT_URL, 304, "Not Modified", {}, io.BytesIO())
        with mock.patch.multiple(combos, **patches), mock.patch.object(cards, "_download", side_effect=not_modified):
            combos.update(force=True, log=lambda *a: None)
        self.assertEqual(source_health.state(self.entry("spellbook")), "ok")

    def test_a_gauntlet_build_with_a_failed_source_saves_nothing_and_is_a_failure(self):
        with mock.patch.object(catalogue, "_card_data", return_value={}), \
                mock.patch.object(catalogue, "_records", return_value=([], [], ["edhrec"])), \
                mock.patch.object(catalogue, "_kept", return_value=([], [])), \
                mock.patch.object(catalogue, "save") as save, self.assertRaises(catalogue.GauntletError):
            catalogue.build("commander", log=lambda *a: None)
        save.assert_not_called()
        self.assertEqual(source_health.state(self.entry("gauntlet")), "failing")
        with mock.patch.object(catalogue, "_card_data", return_value={}), \
                mock.patch.object(catalogue, "_records", return_value=([], [], [])), \
                mock.patch.object(catalogue, "_kept", return_value=([], [])), \
                mock.patch.object(catalogue, "load", return_value=None), mock.patch.object(catalogue, "save"):
            catalogue.build("commander", log=lambda *a: None)
        self.assertEqual(source_health.state(self.entry("gauntlet")), "ok")


class ViewTests(Folder):
    def setUp(self):
        super().setUp()
        self.viewer = self.enterContext(mock.patch.object(guard, "viewer", return_value={"id": "matt", "role": "admin"}))
        self.script = self.enterContext(mock.patch.object(guard, "script", return_value=False))
        self.fresh = card_freshness.judge(date.today(), date.today(), date.today())
        self.check = self.enterContext(mock.patch.object(card_freshness, "check", return_value=self.fresh))

    def test_an_admin_reads_every_source(self):
        source_health.record("edhrec", False, EARLY)
        answer = data_sources.data_sources_view()
        self.assertEqual(answer["card_data"], {"stale": False, "warning": None})
        row = next(row for row in answer["sources"] if row["key"] == "edhrec")
        self.assertEqual(row, {"key": "edhrec", "label": "EDHREC", "last_ok": None,
                               "last_failure": "2026-11-10T03:00:00+00:00", "state": "failing"})
        json.dumps(answer)

    def test_stale_card_data_or_rate_is_marked_even_after_a_good_fetch(self):
        source_health.record("scryfall", True, EARLY)
        self.check.return_value = card_freshness.judge(None, date.today(), date.today())
        answer = data_sources.data_sources_view()
        states = {row["key"]: row["state"] for row in answer["sources"]}
        self.assertEqual((states["scryfall"], states["fx"]), ("stale", "never"))
        self.assertIn("python -m decklab.lib.cards update", answer["card_data"]["warning"])

    def test_a_freshness_check_that_raises_still_shows_the_receipts(self):
        self.check.side_effect = OSError("C:/private")
        answer = data_sources.data_sources_view()
        self.assertIsNone(answer["card_data"])
        self.assertNotIn("private", json.dumps(answer))

    def test_only_an_admin_or_a_script_naming_nobody_reads_it(self):
        for profile in ({"id": "user1", "role": "member"}, {"id": "user5", "role": "member"}, None):
            self.viewer.return_value = profile
            with self.subTest(profile=profile), self.assertRaises(ApiError) as caught:
                data_sources.data_sources_view()
            self.assertEqual(caught.exception.status, 403)
        self.viewer.return_value = None
        self.script.return_value = True
        self.assertEqual(len(data_sources.data_sources_view()["sources"]), len(source_health.SOURCES))


if __name__ == "__main__":
    unittest.main()
