"""E11-S85: the card data and exchange rate freshness judge (lib/card_freshness.py) and where it's
shown (the admin's /api/status, homenet status, the nightly's "card data" step). Fixture files only:
no network, no live database, no server."""
from datetime import date, timedelta
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from decklab.db import backup, check, conn as db, export, nightly, visits
from decklab.lib import card_freshness, cards, operator_alerts as alerts, server_run
from decklab.lib.api import carddata, guard
from decklab.lib.homenet import checks
from decklab.lib.shops import health
from decklab.lib.stats import commander

TODAY = date(2026, 11, 12)


class JudgeTests(unittest.TestCase):
    def test_limits_come_from_the_update_intervals_plus_retry_grace(self):
        self.assertEqual(card_freshness.card_limit(), cards.MAX_BULK_AGE + timedelta(days=4))
        self.assertEqual(card_freshness.card_limit().days, 11)
        self.assertEqual(card_freshness.fx_limit().days, 3)
        self.assertEqual(server_run.UPDATE_EVERY, card_freshness.CHECK_EVERY.total_seconds())

    def test_fresh_dates_give_no_warning(self):
        found = card_freshness.judge(TODAY - timedelta(days=11), TODAY - timedelta(days=3), TODAY)
        self.assertFalse(found["stale"])
        self.assertIsNone(found["warning"])
        self.assertEqual(found["cards"], {"date": "2026-11-01", "age_days": 11, "limit_days": 11, "stale": False})
        self.assertEqual(found["fx"]["age_days"], 3)
        json.dumps(found)

    def test_a_day_or_two_of_retries_never_trips_it(self):
        # A weekly download with Scryfall's day-old file, a day between checks and two failed days.
        self.assertFalse(card_freshness.judge(TODAY - timedelta(days=10), TODAY - timedelta(days=2), TODAY)["stale"])

    def test_old_card_data_is_one_fixed_sentence_naming_the_command(self):
        found = card_freshness.judge(TODAY - timedelta(days=12), TODAY, TODAY)
        self.assertTrue(found["stale"])
        self.assertEqual(found["warning"], "Card data may have stopped refreshing: the card data is 12 days old; "
                                           "on the server PC run python -m decklab.lib.cards update.")

    def test_an_old_rate_alone_and_both_together(self):
        found = card_freshness.judge(TODAY, TODAY - timedelta(days=4), TODAY)
        self.assertEqual(found["warning"], "Card data may have stopped refreshing: the exchange rate was last "
                                           "fetched 4 days ago; on the server PC run python -m decklab.lib.cards update.")
        both = card_freshness.judge(TODAY - timedelta(days=30), TODAY - timedelta(days=30), TODAY)["warning"]
        self.assertIn("the card data is 30 days old and the exchange rate was last fetched 30 days ago;", both)
        self.assertEqual((both.count(". "), both.endswith(".")), (0, True))       # one sentence

    def test_unknown_malformed_or_future_dates_have_an_unknown_age(self):
        for value in (None, "", "unknown", "2026-02-30", "2026-11-12broken", 12, {}, "2026-11-14"):
            with self.subTest(value=value):
                found = card_freshness.judge(value, TODAY, TODAY)
                self.assertTrue(found["stale"])
                self.assertIsNone(found["cards"]["age_days"])
                self.assertIn("the card data's age is unknown", found["warning"])
        found = card_freshness.judge(TODAY, "nonsense", TODAY)
        self.assertIn("the exchange rate's age is unknown", found["warning"])
        self.assertFalse(card_freshness.judge("2026-11-13T01:00:00+00:00", TODAY, TODAY)["stale"])   # time zones

    def test_usd_needs_no_rate(self):
        found = card_freshness.judge(TODAY, None, TODAY, fx_needed=False)
        self.assertIsNone(found["fx"])
        self.assertFalse(found["stale"])

    def test_commander_readiness_shares_the_one_date_parser(self):
        self.assertIs(commander._source_date, card_freshness.parse_date)
        self.assertEqual(card_freshness.parse_date("2026-10-14T09:10:11+00:00"), date(2026, 10, 14))


class DiskTests(unittest.TestCase):
    def setUp(self):
        self.folder = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.meta = self.folder / "bulk.json"
        self.fx = self.folder / "fx.json"

    def write(self, path, data):
        path.write_text(json.dumps(data) if not isinstance(data, str) else data, encoding="utf-8")

    def test_reads_the_index_stamp_and_the_rate_fetch_day(self):
        self.write(self.meta, {"index": {"version": 9, "default_cards": "2026-11-10T09:00:00.000+00:00"},
                               "default_cards": {"updated_at": "2026-01-01T00:00:00+00:00"}})
        self.write(self.fx, {"rate": 1.5, "date": "2026-11-07", "fetched_on": "2026-11-11"})
        self.assertEqual(card_freshness.card_date_on_disk(self.meta), date(2026, 11, 10))
        self.assertEqual(card_freshness.fx_fetched_on("AUD", self.fx), date(2026, 11, 11))
        found = card_freshness.check(TODAY, "AUD", meta_file=self.meta, fx_file=self.fx)
        self.assertFalse(found["stale"])

    def test_missing_damaged_oversized_or_other_currency_files_are_unknown(self):
        self.assertIsNone(card_freshness.card_date_on_disk(self.meta))
        for text in ("{broken", "[]", json.dumps({"index": "x"}), " " * (card_freshness.MAX_META_BYTES + 1)):
            self.write(self.meta, text)
            self.assertIsNone(card_freshness.card_date_on_disk(self.meta))
        self.write(self.fx, {"rate": 0.9, "fetched_on": "2026-11-12", "to": "EUR"})
        self.assertIsNone(card_freshness.fx_fetched_on("AUD", self.fx))
        self.assertEqual(card_freshness.fx_fetched_on("EUR", self.fx), TODAY)
        found = card_freshness.check(TODAY, "AUD", meta_file=self.meta, fx_file=self.fx)
        self.assertIn("the card data's age is unknown and the exchange rate's age is unknown", found["warning"])
        self.assertNotIn(str(self.folder), found["warning"])

    def test_check_skips_the_rate_for_usd(self):
        self.write(self.meta, {"index": {"default_cards": "2026-11-12"}})
        self.assertIsNone(card_freshness.check(TODAY, "USD", meta_file=self.meta, fx_file=self.fx)["fx"])


class StatusTests(unittest.TestCase):
    INFO = {"built_at": "2026-11-11T00:00:00+00:00", "bulk": {"default_cards": "2026-10-01T00:00:00+00:00"},
            "roles": {}, "cards": 1, "tokens": 0}

    def setUp(self):
        self.enterContext(mock.patch.object(carddata, "_index_info", return_value=(self.INFO, None)))
        self.enterContext(mock.patch.object(cards, "price_date", return_value="2026-10-01"))
        self.enterContext(mock.patch.object(carddata, "_cached_rate", return_value={"rate": 1.5, "date": "2026-11-11"}))
        self.enterContext(mock.patch.object(carddata.pricing_setting, "settings", return_value={}))
        self.enterContext(mock.patch.object(card_freshness, "fx_fetched_on", return_value=date.today()))
        self.viewer = self.enterContext(mock.patch.object(guard, "viewer"))

    def test_a_named_admin_gets_the_one_sentence(self):
        self.viewer.return_value = {"id": "matt", "role": "admin"}
        found = carddata.status()["cards"]["freshness"]
        self.assertTrue(found["stale"])
        self.assertRegex(found["warning"], r"^Card data may have stopped refreshing: the card data is \d+ days old; "
                                           r"on the server PC run python -m decklab\.lib\.cards update\.$")
        self.assertEqual(set(found), {"stale", "warning"})

    def test_a_member_nobody_or_a_missing_index_gets_none(self):
        for profile in ({"id": "user1", "role": "member"}, None):
            self.viewer.return_value = profile
            self.assertIsNone(carddata.status()["cards"]["freshness"])
        self.viewer.return_value = {"id": "matt", "role": "admin"}
        with mock.patch.object(carddata, "_index_info", return_value=(None, "There's no card data on the PC yet")):
            self.assertIsNone(carddata.status()["cards"]["freshness"])

    def test_a_judge_failure_never_breaks_status(self):
        self.viewer.return_value = {"id": "matt", "role": "admin"}
        with mock.patch.object(card_freshness, "judge", side_effect=ValueError("C:/private")):
            self.assertIsNone(carddata.status()["cards"]["freshness"])


class HomenetTests(unittest.TestCase):
    def test_fresh_is_an_ok_line_and_stale_a_warning_with_the_sentence(self):
        fresh = checks.check_card_data(card_freshness.judge(TODAY - timedelta(days=1), TODAY, TODAY))
        self.assertEqual([(entry["level"], entry["area"]) for entry in fresh], [("OK", "Card data")])
        self.assertEqual(fresh[0]["text"], "Refreshing: Scryfall's data of 2026-11-11 (1 day old); "
                                           "the exchange rate fetched 2026-11-12.")
        stale = card_freshness.judge(None, TODAY, TODAY)
        self.assertEqual(checks.check_card_data(stale), [{"level": "WARN", "area": "Card data",
                                                         "text": stale["warning"], "fix": None}])

    def test_a_check_that_fails_is_a_warning_without_its_error(self):
        with mock.patch.object(card_freshness, "check", side_effect=OSError("C:/private/path")):
            found = checks.card_data_lines()
        self.assertEqual(found[0]["level"], "WARN")
        self.assertNotIn("private", json.dumps(found))
        self.assertIn("python -m decklab.lib.cards update", found[0]["fix"])


class NightlyTests(unittest.TestCase):
    def run_nightly(self, freshness):
        logged = []
        with mock.patch.object(nightly, "_step", return_value=True), \
                mock.patch.object(db, "log", side_effect=logged.append), \
                mock.patch.object(health, "heartbeat_steps", return_value={}), \
                mock.patch.object(card_freshness, "check", **freshness), \
                mock.patch.object(alerts, "notify") as notify:
            result = nightly._run()
        return result, notify.call_args.args[0], logged

    def test_stale_card_data_is_a_failed_step_in_the_alerts_without_failing_the_night(self):
        stale = card_freshness.judge(TODAY - timedelta(days=20), TODAY, TODAY)
        result, outcomes, logged = self.run_nightly({"return_value": stale})
        self.assertEqual(result, 0)
        self.assertEqual((outcomes["card data"], outcomes["nightly"]), (False, True))
        self.assertIn("Nightly: " + stale["warning"], logged)

    def test_fresh_card_data_is_ok_and_logs_nothing(self):
        result, outcomes, logged = self.run_nightly({"return_value": card_freshness.judge(TODAY, TODAY, TODAY)})
        self.assertTrue(outcomes["card data"])
        self.assertFalse([text for text in logged if "Card data" in text])

    def test_a_check_that_raises_is_failed_and_logs_no_error_words(self):
        result, outcomes, logged = self.run_nightly({"side_effect": OSError("C:/private/path")})
        self.assertEqual(result, 0)
        self.assertFalse(outcomes["card data"])
        self.assertNotIn("private", " ".join(logged))

    def test_the_heartbeat_sends_the_card_data_step(self):
        self.assertIn("card data", alerts.STEPS)
        response = mock.MagicMock(status=204)
        response.__enter__.return_value = response
        opener = mock.Mock()
        opener.open.return_value = response
        self.assertTrue(alerts.notify({"card data": False}, settings={"alerts": "https://monitor.example.com/x"},
                                      opener=opener))
        self.assertEqual(json.loads(opener.open.call_args.args[0].data), {"steps": {"card data": "failed"}})

    def test_the_night_still_runs_every_database_step(self):
        ran = []
        def step(name):
            return lambda *args: ran.append(name) or 0
        with mock.patch.object(backup, "run_backup", step("backup")), \
                mock.patch.object(backup, "run_prune", step("prune")), \
                mock.patch.object(visits, "run_prune", step("visits")), \
                mock.patch.object(export, "run_export", step("export")), \
                mock.patch.object(check, "run", step("check")), \
                mock.patch.object(nightly, "_restore_check_if_due", step("restore check")), \
                mock.patch.object(nightly, "_shop_prices", step("shop prices")), \
                mock.patch.object(db, "log"), mock.patch.object(health, "heartbeat_steps", return_value={}), \
                mock.patch.object(nightly, "_card_data", return_value=False), \
                mock.patch.object(alerts, "notify") as notify:
            self.assertEqual(nightly._run(), 0)
        self.assertEqual(len(ran), 7)
        self.assertFalse(notify.call_args.args[0]["card data"])


if __name__ == "__main__":
    unittest.main()
