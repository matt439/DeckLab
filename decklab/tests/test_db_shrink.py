"""E11-S87: the nightly's and `db status`'s warning when a watched table shrank sharply since
the previous good dump. No database: the dump rows and settings are injected."""
import json
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from decklab.db import backup, check, conn as db, export, nightly, shrink, visits
from decklab.lib import operator_alerts as alerts
from decklab.lib.shops import health

NOW = datetime(2026, 11, 12, 3, 30, tzinfo=timezone.utc)
BASE = {"public.collection_card": 1000, "public.deck": 40, "public.token_card": 60,
        "public.purchase_order": 30, "public.wishlist_entry": 20, "public.accessory": 12,
        "audit.row_change": 5000}
ON = {"shrink_warn": True}


def counts(**changes):
    out = dict(BASE)
    for key, value in changes.items():
        table = "public." + key
        if value is None:
            out.pop(table, None)
        else:
            out[table] = value
    return out


def row(ok, days_ago, data):
    detail = backup.dump_detail(data) if isinstance(data, dict) else data
    return (ok, NOW - timedelta(days=days_ago), detail)


class CompareTests(unittest.TestCase):
    def test_nothing_changed_or_grew(self):
        self.assertEqual(shrink.compare(BASE, BASE), [])
        self.assertEqual(shrink.compare(BASE, counts(collection_card=1500, deck=41)), [])

    def test_sharp_fall_names_table_and_counts(self):
        found = shrink.compare(BASE, counts(collection_card=600))
        self.assertEqual(found, [{"label": "collection", "table": "public.collection_card", "kind": shrink.SHRANK,
                                  "before": 1000, "after": 600}])

    def test_threshold_needs_both_share_and_rows(self):
        # 25% of 1000 exactly is not "more than"; 251 rows is.
        self.assertEqual(shrink.compare(BASE, counts(collection_card=750)), [])
        self.assertEqual(len(shrink.compare(BASE, counts(collection_card=749))), 1)
        # accessories 12 -> 8 is 33% but only 4 rows: below the proposed minimum of 5 rows.
        self.assertEqual(shrink.compare(BASE, counts(accessory=8)), [])
        self.assertEqual(shrink.compare(BASE, counts(accessory=7))[0]["label"], "accessories")
        # A small fall of a big table: many rows but a small share.
        self.assertEqual(shrink.compare(BASE, counts(collection_card=900)), [])

    def test_custom_thresholds(self):
        found = shrink.compare(BASE, counts(collection_card=900), percent=5, min_rows=50)
        self.assertEqual(found[0]["after"], 900)
        self.assertEqual(shrink.compare(BASE, counts(deck=38), percent=1, min_rows=3), [])

    def test_unwatched_tables_never_warn(self):
        self.assertEqual(shrink.compare(BASE, dict(BASE, **{"audit.row_change": 0})), [])

    def test_missing_from_either_dump_cannot_be_compared(self):
        found = shrink.compare(counts(accessory=None), counts(token_card=None))
        self.assertEqual([(f["label"], f["kind"], f["before"], f["after"]) for f in found],
                         [("token cards", shrink.MISSING, 60, None), ("accessories", shrink.MISSING, None, 12)])
        # A count that isn't a whole number counts as missing, not as zero.
        found = shrink.compare(BASE, dict(BASE, **{"public.deck": "40"}))
        self.assertEqual(found[0]["kind"], shrink.MISSING)

    def test_every_watched_label_is_one_the_story_names(self):
        self.assertEqual([label for label, _ in shrink.WATCHED],
                         ["collection", "decks", "token cards", "orders", "wishlists", "accessories"])


class PairTests(unittest.TestCase):
    def test_newest_two_good_dumps_with_counts(self):
        rows = [row(True, 0, counts(deck=10)), row(False, 1, "pg_dump failed: x"),
                row(True, 2, "no counts"), row(True, 3, BASE), row(True, 4, BASE)]
        previous, current = shrink.pair(rows)
        self.assertEqual(current["counts"]["public.deck"], 10)
        self.assertEqual(previous["started_at"], NOW - timedelta(days=3))

    def test_failed_newest_dump_compares_nothing(self):
        self.assertIsNone(shrink.pair([row(False, 0, "pg_dump failed"), row(True, 1, BASE), row(True, 2, BASE)]))
        # A failed copy keeps its counts after "; rows: ", but the dump didn't work.
        self.assertIsNone(shrink.pair([row(False, 0, "copy to x failed: no; " + backup.dump_detail(BASE)),
                                       row(True, 1, BASE)]))

    def test_an_interim_dump_doesnt_hide_the_shrink(self):
        # A bad import, then an update's pre-migration backup (or a manual one), then the night:
        # the night compares with the night before, not with the interim dump.
        shrunk = counts(collection_card=100)
        rows = [row(True, 0, shrunk), row(True, 0.3, shrunk), row(True, 1, BASE)]
        previous, current = shrink.pair(rows)
        self.assertEqual(previous["started_at"], NOW - timedelta(days=1))
        found, earlier = shrink.judge(rows, ON)
        self.assertEqual([(f["label"], f["before"], f["after"]) for f in found], [("collection", 1000, 100)])
        self.assertEqual(earlier, NOW - timedelta(days=1))
        # db status, after a manual dump during the day, still shows it.
        self.assertEqual(len(shrink.status_lines(rows=[row(True, 0, shrunk)] + rows[1:], s=ON)), 1)

    def test_the_earlier_dump_is_chosen_by_time(self):
        hours = shrink.MIN_GAP_HOURS
        self.assertIsNone(shrink.pair([row(True, 0, BASE), row(True, (hours - 1) / 24, BASE)]))
        previous, _ = shrink.pair([row(True, 0, BASE), row(True, (hours - 1) / 24, BASE),
                                   row(False, hours / 24, BASE), row(True, hours / 24, counts(deck=7))])
        self.assertEqual(previous["counts"]["public.deck"], 7)

    def test_needs_an_earlier_dump(self):
        self.assertIsNone(shrink.pair([]))
        self.assertIsNone(shrink.pair([row(True, 0, BASE)]))
        self.assertIsNone(shrink.pair([row(True, 0, BASE), row(False, 1, BASE)]))


class ThresholdSettingTests(unittest.TestCase):
    def test_defaults_and_overrides(self):
        self.assertEqual(shrink.thresholds({}), (shrink.DEFAULT_PERCENT, shrink.DEFAULT_MIN_ROWS))
        self.assertEqual(shrink.thresholds({"shrink_warn_percent": 10, "shrink_warn_rows": 50}), (10.0, 50))
        for bad in (True, "10", 0, 500, None, -1):
            self.assertEqual(shrink.thresholds({"shrink_warn_percent": bad})[0], shrink.DEFAULT_PERCENT, bad)
        for bad in (True, "10", 0, 10**9, None, -1):
            self.assertEqual(shrink.thresholds({"shrink_warn_rows": bad})[1], shrink.DEFAULT_MIN_ROWS, bad)

    def test_judge_uses_the_settings(self):
        rows = [row(True, 0, counts(collection_card=900)), row(True, 1, BASE)]
        self.assertEqual(shrink.judge(rows, {})[0], [])
        found, earlier = shrink.judge(rows, {"shrink_warn_percent": 5})
        self.assertEqual((found[0]["before"], found[0]["after"], earlier), (1000, 900, NOW - timedelta(days=1)))


class WordingTests(unittest.TestCase):
    def test_lines_give_whole_table_counts_and_the_earlier_date(self):
        earlier = datetime(2026, 11, 11, 3, 30).astimezone()
        found = shrink.compare(BASE, counts(collection_card=12, accessory=None))
        lines = shrink.lines(found, earlier)
        self.assertEqual(lines[0], "the collection table (public.collection_card) shrank from 1,000 rows to 12 "
                                   "since the dump of 2026-11-11 03:30")
        self.assertIn("accessories table (public.accessory) couldn't be compared with the dump of 2026-11-11 03:30", lines[1])
        self.assertIn("the newest dump has no count for it", lines[1])
        both = shrink.lines([{"label": "decks", "table": "public.deck", "kind": shrink.MISSING,
                              "before": None, "after": None}], earlier)
        self.assertIn("either dump", both[0])
        earlier_only = shrink.lines(shrink.compare(counts(deck=None), BASE), earlier)
        self.assertIn("the earlier dump has no count for it", earlier_only[0])

    def test_status_lines(self):
        rows = [row(True, 0, counts(wishlist_entry=2)), row(True, 1, BASE)]
        lines = shrink.status_lines(rows=rows, s=ON)
        self.assertEqual(len(lines), 1)
        self.assertTrue(lines[0].startswith("  WARNING: the wishlists table (public.wishlist_entry) shrank from 20 rows to 2"))
        self.assertTrue(lines[0].endswith("."))
        self.assertEqual(shrink.status_lines(rows=[row(True, 0, BASE), row(True, 1, BASE)], s=ON), [])
        self.assertEqual(shrink.status_lines(rows=[row(True, 0, BASE)], s=ON), [])

    def test_status_read_failure_is_one_line(self):
        with mock.patch.object(shrink, "read_rows", side_effect=db.DbUnavailable("secret host detail")):
            lines = shrink.status_lines(s=ON)
        self.assertEqual(lines, ["  Shrink check: couldn't be read (DbUnavailable)."])

    def test_backup_status_includes_the_warning(self):
        last = {"dump": NOW, "export": NOW, "restore_check": None, "check": None}
        newest = {"dump": {"ok": True, "started_at": NOW, "finished_at": None, "detail": "rows: {}", "path": None}}
        rows = [row(True, 0, counts(deck=3)), row(True, 1, BASE)]
        with mock.patch.object(backup, "last_ok", return_value=last), \
                mock.patch.object(backup, "latest", return_value={k: newest.get(k) for k in
                                                                  ("dump", "export", "check", "restore_check")}), \
                mock.patch.object(backup.db, "settings", return_value=dict(db.DEFAULTS, shrink_warn=True)), \
                mock.patch.object(shrink, "read_rows", return_value=rows):
            lines = backup.status(now=NOW)
        self.assertTrue(any("decks table (public.deck) shrank from 40 rows to 3" in line for line in lines), lines)


class OffByDefaultTests(unittest.TestCase):
    """Off until config.json's database.shrink_warn is true: no status lines, no nightly step."""
    ROWS = [row(True, 0, counts(deck=3)), row(True, 1, BASE)]

    def test_enabled_only_when_set_true(self):
        self.assertFalse(shrink.enabled({}))
        self.assertFalse(shrink.enabled(dict(db.DEFAULTS)))
        for value in ("true", 1, None, False):
            self.assertFalse(shrink.enabled({"shrink_warn": value}), value)
        self.assertTrue(shrink.enabled(ON))

    def test_off_status_says_nothing_and_reads_nothing(self):
        with mock.patch.object(shrink, "read_rows", side_effect=AssertionError("read")):
            self.assertEqual(shrink.status_lines(s={}), [])
        self.assertEqual(shrink.status_lines(rows=self.ROWS, s={"shrink_warn": False}), [])

    def test_off_nightly_logs_and_sends_nothing(self):
        logged = []
        with mock.patch.object(shrink, "read_rows", side_effect=AssertionError("read")):
            self.assertIsNone(shrink.nightly(logged.append, s={}))
        self.assertIsNone(shrink.nightly(logged.append, rows=self.ROWS, s={}))
        self.assertEqual(logged, [])


class NightlyShrinkTests(unittest.TestCase):
    def test_nightly_logs_each_finding(self):
        logged = []
        rows = [row(True, 0, counts(purchase_order=1, token_card=None)), row(True, 1, BASE)]
        self.assertFalse(shrink.nightly(logged.append, rows=rows, s=ON))
        self.assertEqual(len(logged), 2)
        self.assertTrue(all(line.startswith("Nightly: WARNING: the ") for line in logged))
        self.assertIn("orders table (public.purchase_order) shrank from 30 rows to 1", logged[1])
        self.assertIn("token cards table (public.token_card) couldn't be compared", logged[0])

    def test_nightly_quiet_outcomes(self):
        logged = []
        self.assertTrue(shrink.nightly(logged.append, rows=[row(True, 0, BASE), row(True, 1, BASE)], s=ON))
        self.assertIn("no watched table shrank sharply", logged[-1])
        self.assertTrue(shrink.nightly(logged.append, rows=[row(True, 0, BASE)], s=ON))
        self.assertIn("no good dump with counts at least 20 hours older", logged[-1])
        with mock.patch.object(shrink, "read_rows", side_effect=RuntimeError("private")):
            self.assertIsNone(shrink.nightly(logged.append, s=ON))
        self.assertEqual(logged[-1], "Nightly: the shrink check couldn't be read: RuntimeError.")

    def test_nightly_outcome_gives_the_heartbeat_detail(self):
        rows = [row(True, 0, counts(purchase_order=1, token_card=None)), row(True, 1, BASE)]
        ok, detail = shrink.nightly_outcome(lambda line: None, rows=rows, s=ON)
        when = f"{(NOW - timedelta(days=1)).astimezone():%Y-%m-%d}"
        self.assertIs(ok, False)
        self.assertEqual(detail, f"token_card not compared since {when}; purchase_order 30->1 since {when}")
        self.assertEqual(shrink.nightly_outcome(lambda line: None, rows=[row(True, 0, BASE), row(True, 1, BASE)], s=ON),
                         (True, None))
        self.assertEqual(shrink.nightly_outcome(lambda line: None, rows=rows, s={}), (None, None))

    def _run(self, backup_code, shrunk, detail=None):
        def step(code=0):
            return lambda *a, **k: code
        with mock.patch.object(backup, "run_backup", step(backup_code)), \
                mock.patch.object(backup, "run_prune", step()), mock.patch.object(visits, "run_prune", step()), \
                mock.patch.object(export, "run_export", step()), mock.patch.object(check, "run", step()), \
                mock.patch.object(nightly, "_restore_check_if_due", step()), \
                mock.patch.object(nightly, "_shop_prices", step()), mock.patch.object(db, "log"), \
                mock.patch.object(health, "heartbeat_steps", return_value={}), \
                mock.patch.object(shrink, "nightly_outcome", return_value=(shrunk, detail)) as judged, \
                mock.patch.object(alerts, "notify") as notify:
            code = nightly._run()
        self.last_details = notify.call_args.kwargs.get("details")
        return code, notify.call_args.args[0], judged

    def test_a_shrink_warns_the_heartbeat_without_failing_the_night(self):
        code, sent, _ = self._run(0, False, "deck 40->3 since 2026-11-11")
        self.assertEqual(code, 0)
        self.assertIs(sent["shrink"], False)
        self.assertIs(sent["nightly"], True)
        self.assertEqual(self.last_details, {"shrink": "deck 40->3 since 2026-11-11"})

    def test_no_shrink_is_ok_and_unread_sends_nothing(self):
        self.assertIs(self._run(0, True)[1]["shrink"], True)
        self.assertIsNone(self.last_details)
        self.assertNotIn("shrink", self._run(0, None)[1])
        self.assertIsNone(self.last_details)

    def test_a_failing_check_is_neither_sent_nor_fails_the_night(self):
        with mock.patch.object(db, "log"), mock.patch.object(shrink, "nightly_outcome", side_effect=RuntimeError("x")):
            self.assertEqual(nightly._shrink_check(), (None, None))

    def test_no_shrink_check_after_a_failed_backup(self):
        code, sent, judged = self._run(1, False)
        self.assertEqual(code, 1)
        self.assertNotIn("shrink", sent)
        judged.assert_not_called()


def _opener():
    opener = mock.Mock()
    opener.open.return_value.__enter__ = lambda s: mock.Mock(status=204)
    opener.open.return_value.__exit__ = lambda *a: None
    return opener


SETTINGS = {"alerts": "https://hooks.example.com/x"}


class HeartbeatDetailTests(unittest.TestCase):
    def sent(self, outcomes, details=None):
        opener = _opener()
        self.assertTrue(alerts.notify(outcomes, details=details, settings=SETTINGS, opener=opener))
        return json.loads(opener.open.call_args.args[0].data)

    def test_detail_names_table_counts_and_date_only(self):
        earlier = NOW - timedelta(days=1)
        findings = shrink.compare(BASE, counts(collection_card=600, deck=3, accessory=None))
        detail = shrink.heartbeat_detail(findings, earlier)
        when = f"{earlier.astimezone():%Y-%m-%d}"
        self.assertEqual(detail, f"collection_card 1000->600 since {when}; deck 40->3 since {when}; "
                                 f"accessory not compared since {when}")
        for word in ("public.", "collection table", "decks", "space", "home"):
            self.assertNotIn(word, detail)
        self.assertIsNone(shrink.heartbeat_detail([], earlier))
        self.assertIsNone(shrink.heartbeat_detail(findings, None))

    def test_without_details_only_the_step_name(self):
        self.assertEqual(self.sent({"shrink": False, "nightly": True}),
                         {"steps": {"nightly": "ok", "shrink": "failed"}})

    def test_a_failed_shrink_carries_its_detail(self):
        self.assertEqual(self.sent({"shrink": False, "nightly": True}, {"shrink": "deck 40->3 since 2026-11-11"}),
                         {"steps": {"nightly": "ok", "shrink": "failed"},
                          "details": {"shrink": "deck 40->3 since 2026-11-11"}})

    def test_detail_only_for_a_failed_detail_step(self):
        self.assertNotIn("details", self.sent({"shrink": True}, {"shrink": "deck 40->3"}))
        self.assertNotIn("details", self.sent({"check": False}, {"check": "PRIVATE"}))
        self.assertNotIn("details", self.sent({"backup": False}, {"shrink": "deck 40->3"}))
        self.assertNotIn("details", self.sent({"shrink": False}, {"shrink": 12}))
        self.assertNotIn("details", self.sent({"shrink": False}, {"shrink": " \n "}))
        self.assertNotIn("details", self.sent({"shrink": False}, ["shrink"]))

    def test_detail_is_bounded_printable_ascii(self):
        sent = self.sent({"shrink": False}, {"shrink": "deck\n40->3é " + "x" * 1000})
        line = sent["details"]["shrink"]
        self.assertEqual(len(line), alerts.MAX_DETAIL)
        self.assertTrue(line.startswith("deck 40->3  x"))
        self.assertTrue(line.endswith("..."))
        self.assertTrue(all(32 <= ord(ch) < 127 for ch in line))


if __name__ == "__main__":
    unittest.main()
