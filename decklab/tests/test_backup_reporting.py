"""How backups are reported (E11-S58's WSL qualification, 2026-11-02): `db status` showing a
failed newest dump or export at once, the copy refusal's single full stop, the check's
plurals and the doctor's Backup folders check. No database: the runs, stats and settings are
injected."""
import os
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest import mock

from decklab.db import backup, check, conn, nightly, schedule
from decklab.lib import preflight
from decklab.lib.preflight_local import Local

NOW = datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc)


def _run(ok, hours_ago, detail):
    return {"ok": ok, "started_at": NOW - timedelta(hours=hours_ago), "finished_at": None, "detail": detail}


class StatusLineTests(unittest.TestCase):
    def status(self, newest, last):
        kinds = ("dump", "export", "check", "restore_check")
        with mock.patch.object(backup, "last_ok", return_value=last), \
                mock.patch.object(backup, "latest", return_value={k: newest.get(k) for k in kinds}), \
                mock.patch.object(backup.db, "settings", return_value=dict(conn.DEFAULTS)):
            return backup.status(now=NOW)

    def test_failed_newest_dump_shows_at_once(self):
        last = {"dump": NOW - timedelta(hours=2), "export": NOW - timedelta(hours=2),
                "restore_check": None, "check": None}
        lines = self.status({"dump": _run(False, 1, "copy to /mnt/nas failed: no"),
                             "export": _run(True, 2, "ok")}, last)
        dump = next(line for line in lines if "last dump" in line)
        self.assertIn("FAILED: copy to /mnt/nas failed: no", dump)
        self.assertIn("(the last that worked: ", dump)
        export = next(line for line in lines if "last export" in line)
        self.assertNotIn("FAILED", export)

    def test_failed_export_without_any_good_one(self):
        last = {"dump": NOW, "export": None, "restore_check": None, "check": None}
        lines = self.status({"dump": _run(True, 0, "rows: {}"), "export": _run(False, 0, "push refused")}, last)
        export = next(line for line in lines if "last export" in line)
        self.assertIn("FAILED: push refused", export)
        self.assertNotIn("the last that worked", export)

    def test_healthy_lines_unchanged(self):
        last = {"dump": NOW, "export": None, "restore_check": None, "check": None}
        lines = self.status({"dump": _run(True, 0, "rows: {}")}, last)
        self.assertIn("  last export: never", lines)
        self.assertTrue(any(line.startswith("  last dump: 20") and "FAILED" not in line for line in lines))


class WordingTests(unittest.TestCase):
    def test_sentence_has_one_full_stop(self):
        self.assertEqual(backup.sentence("which this PC can't use."), "which this PC can't use.")
        self.assertEqual(backup.sentence(OSError("disk full")), "disk full.")
        self.assertEqual(backup.sentence("mounted? "), "mounted?")

    def test_plural(self):
        self.assertEqual(check._plural(0, "alias", "aliases"), "0 aliases")
        self.assertEqual(check._plural(1, "alias", "aliases"), "1 alias")
        self.assertEqual(check._plural(2, "deck"), "2 decks")


class NightlyRestoreCheckTests(unittest.TestCase):
    def due(self, newest, last):
        said, ran = [], []
        with mock.patch.object(backup, "last_ok", return_value={"restore_check": last}),                 mock.patch.object(backup, "latest", return_value={"restore_check": newest}),                 mock.patch.object(backup, "run_restore_check", lambda: ran.append(1) or 0),                 mock.patch.object(nightly.db, "settings", return_value=dict(conn.DEFAULTS)),                 mock.patch.object(nightly.db, "log", said.append):
            nightly._restore_check_if_due()
        return ran, said

    def test_a_failed_one_is_tried_again_the_next_night(self):
        recent = datetime.now().astimezone() - timedelta(days=1)
        ran, said = self.due({"ok": False, "started_at": recent, "detail": "differs"}, recent - timedelta(hours=1))
        self.assertEqual(ran, [1])
        self.assertIn("the last one failed", said[0])

    def test_a_recent_good_one_is_not_repeated(self):
        recent = datetime.now().astimezone() - timedelta(days=1)
        ran, said = self.due({"ok": True, "started_at": recent, "detail": ""}, recent)
        self.assertEqual(ran, [])
        self.assertIn("no restore check tonight", said[0])


class TimerTimesTests(unittest.TestCase):
    def test_unix_times_show_in_the_configured_zone(self):
        at = int(datetime(2026, 11, 2, 16, 30, tzinfo=timezone.utc).timestamp())    # 03:30 in Sydney (AEDT)
        shown = schedule._when(f"@{at}", "Australia/Sydney")
        if shown.startswith("@"):
            self.skipTest("no time zone data here")
        self.assertTrue(shown.startswith("Tue 2026-11-03 03:30 Australia/Sydney"), shown)

    def test_other_text_is_kept(self):
        self.assertEqual(schedule._when("Tue 2026-10-27 03:30:00 AEDT", "Australia/Sydney"),
                         "Tue 2026-10-27 03:30:00 AEDT")
        self.assertIsNone(schedule._when("n/a"))
        self.assertEqual(schedule._seconds("@1793637000"), 1793637000)
        self.assertIsNone(schedule._seconds(""))

    def test_a_service_started_by_hand_is_the_last_run(self):
        from decklab.lib import systemd
        trigger, start = 1793563626, 1793600000
        values = {"decklab-nightly.timer": {"UnitFileState": "enabled", "ActiveState": "active",
                                            "NextElapseUSecRealtime": "@1793637000", "LastTriggerUSec": f"@{trigger}"},
                  "decklab-nightly.service": {"Result": "success", "ExecMainStatus": "0",
                                              "ExecMainStartTimestamp": f"@{start}"}}
        folder = mock.Mock()
        folder.__truediv__ = lambda self, name: mock.Mock(exists=lambda: True)
        with mock.patch.object(systemd, "unit_dir", return_value=folder),                 mock.patch.object(systemd, "show", lambda unit, *p, unix_times=False: values[unit]),                 mock.patch.object(systemd, "linger_note", return_value=None),                 mock.patch.object(schedule, "_units", side_effect=ValueError),                 mock.patch.object(schedule, "_zone", return_value=None):
            lines = schedule.status_systemd()
        last = next(line for line in lines if "Last run" in line)
        self.assertIn("(started by hand, not by the timer), it succeeded.", last)
        values["decklab-nightly.service"]["ExecMainStartTimestamp"] = f"@{trigger + 1}"
        with mock.patch.object(systemd, "unit_dir", return_value=folder),                 mock.patch.object(systemd, "show", lambda unit, *p, unix_times=False: values[unit]),                 mock.patch.object(systemd, "linger_note", return_value=None),                 mock.patch.object(schedule, "_units", side_effect=ValueError),                 mock.patch.object(schedule, "_zone", return_value=None):
            lines = schedule.status_systemd()
        self.assertNotIn("by hand", next(line for line in lines if "Last run" in line))


class DoctorBackupsTests(unittest.TestCase):
    def local(self, database, stat=None, posix=True):
        found = Local(posix=posix, stat=stat or self.stat)
        found._settings = {"database": database}
        return found

    def stat(self, path):
        devices = {"/home/u/staging": 1, "/home/u": 1, "/mnt/nas": 2, "/mnt/nas/DeckLab": 2, "/home/u/backups": 1}
        key = str(path).replace("\\", "/").rstrip("/")
        if key not in devices:
            raise FileNotFoundError(path)
        return SimpleNamespace(st_dev=devices[key])

    def test_codes(self):
        base = {"staging_dir": "/home/u/staging", "export_repo": "/home/u/export"}
        self.assertEqual(self.local(base).probe("backups"), "backups_local_only")
        self.assertEqual(self.local({**base, "backup_dir": "/mnt/nas/DeckLab"}).probe("backups"), "backups_ready")
        self.assertEqual(self.local({**base, "backup_dir": "/mnt/nas/New"}).probe("backups"), "backups_ready")
        self.assertEqual(self.local({**base, "backup_dir": r"\\NAS\Backups\DeckLab"}).probe("backups"),
                         "backups_setting_invalid")
        self.assertEqual(self.local({**base, "backup_dir": "D:/Backups"}).probe("backups"), "backups_setting_invalid")
        self.assertEqual(self.local({**base, "backup_dir": "/mnt/gone/DeckLab"}).probe("backups"),
                         "backups_unreachable")
        self.assertEqual(self.local({**base, "backup_dir": "/home/u/backups"}).probe("backups"),
                         "backups_same_device")
        self.assertEqual(self.local({**base, "backup_dir": "/home/u/backups",
                                     "backup_same_device_ok": True}).probe("backups"), "backups_ready")

    def test_never_writes(self):
        with mock.patch.object(os, "makedirs", side_effect=AssertionError("wrote")):
            self.local({"staging_dir": "/home/u/staging", "export_repo": "/home/u/export",
                        "backup_dir": "/mnt/nas/DeckLab"}).probe("backups")

    def test_catalog(self):
        row = next(c for c in preflight.CHECKS if c[0] == "backups")
        self.assertEqual((row[2], row[3]), ("optional", ("config",)))
        for code in preflight.ALLOWED["backups"]:
            self.assertIn(code, preflight.OUTCOMES)
        self.assertEqual(preflight.OUTCOMES["backups_same_device"][0], "needs_setup")
        self.assertIn("backup_same_device_ok", preflight.OUTCOMES["backups_same_device"][2])


if __name__ == "__main__":
    unittest.main()
