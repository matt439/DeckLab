"""lib/disk_space.py (E11-S86): free disk space and the data folders' sizes, measured with an
injected disk-usage call and a capped walk, judged into status lines naming fixed labels only,
and shown by `db status`, `homenet status` and the nightly."""
import io
import os
import shutil
import tempfile
import unittest
from collections import namedtuple
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from decklab.db import __main__ as db_main
from decklab.db import conn as db
from decklab.db import nightly
from decklab.lib import config, disk_space
from decklab.lib.homenet import commands

Usage = namedtuple("Usage", "total used free")
GB = disk_space.GB


def usage(free_gb, total_gb=500):
    return lambda path: Usage(int(total_gb * GB), int((total_gb - free_gb) * GB), int(free_gb * GB))


class Folders(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="decklab-disk-"))
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)

    def write(self, rel, size):
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x" * size)
        return path

    def labelled(self, **extra):
        out = [("backups", [self.root / "backups"]), ("shops", [self.root / "shops"])]
        return out + [(k, v) for k, v in extra.items()]

    def measure(self, folder_list=None, **options):
        options.setdefault("disk_usage", usage(100))
        options.setdefault("device", lambda path: 1)
        return disk_space.measure(self.labelled() if folder_list is None else folder_list, **options)


class MeasureTests(Folders):
    def test_sizes_add_every_file_below_each_folder(self):
        self.write("backups/a.dump", 1000)
        self.write("backups/old/b.dump", 234)
        self.write("shops/mtgmate.json", 5)
        got = self.measure()
        self.assertEqual([(f["label"], f["bytes"], f["present"], f["reason"]) for f in got["folders"]],
                         [("backups", 1234, True, None), ("shops", 5, True, None)])

    def test_a_label_of_several_folders_adds_them_and_a_missing_one_is_none_yet(self):
        self.write("gauntlet/catalogue.json", 10)
        self.write("forge/gauntlet/results/r.json", 20)
        got = self.measure([("gauntlet", [self.root / "gauntlet", self.root / "forge" / "gauntlet"]),
                            ("card data", [self.root / "scryfall", self.root / "images"])])
        self.assertEqual(got["folders"][0]["bytes"], 30)
        self.assertEqual(got["folders"][1], {"label": "card data", "bytes": 0, "present": False, "reason": None})

    def test_two_folders_on_one_disk_count_the_disk_once(self):
        calls = []
        got = self.measure(disk_usage=lambda path: calls.append(path) or Usage(500 * GB, 400 * GB, 100 * GB))
        self.assertEqual(len(got["disks"]), 1)
        self.assertEqual(got["disks"][0]["labels"], ["backups", "shops"])
        self.assertEqual(len(calls), 1)

    def test_folders_on_two_disks_are_two_disks(self):
        self.write("backups/a", 1)
        got = self.measure(device=lambda path: 2 if "backups" in str(path) else 1)
        self.assertEqual([d["labels"] for d in got["disks"]], [["backups"], ["shops"]])

    def test_a_missing_folder_is_measured_on_its_nearest_parents_disk(self):
        seen = []
        self.measure(device=lambda path: seen.append(Path(path)) or 1)
        self.assertIn(self.root, seen)

    def test_a_folder_that_cant_be_read_is_unknown_never_zero(self):
        self.write("backups/a.dump", 1000)
        real = os.scandir

        def scandir(path):
            if Path(path).name == "backups":
                raise PermissionError(13, "denied", str(path))
            return real(path)
        got = self.measure(scandir=scandir)
        self.assertEqual(got["folders"][0], {"label": "backups", "bytes": None, "present": True,
                                             "reason": disk_space.CANT_READ})
        self.assertEqual(len(got["disks"]), 1)          # its disk still counts

    def test_a_subfolder_that_cant_be_read_makes_the_whole_size_unknown(self):
        self.write("backups/a.dump", 1000)
        self.write("backups/locked/b.dump", 1)
        real = os.scandir

        def scandir(path):
            if Path(path).name == "locked":
                raise PermissionError(13, "denied", str(path))
            return real(path)
        self.assertIsNone(self.measure(scandir=scandir)["folders"][0]["bytes"])

    def test_a_file_or_folder_deleted_during_the_walk_is_skipped_not_unknown(self):
        self.write("backups/a.dump", 1000)
        self.write("backups/gone.dump", 7)
        self.write("backups/vanished/b.dump", 5)
        real = os.scandir

        class Gone:
            def __init__(self, entry):
                self.path, self.name = entry.path, entry.name

            def stat(self, follow_symlinks=True):
                raise FileNotFoundError(2, "gone", self.path)

        class Listing:
            def __init__(self, inner):
                self.inner = inner

            def __enter__(self):
                return (Gone(e) if e.name == "gone.dump" else e for e in self.inner)

            def __exit__(self, *exc):
                self.inner.close()

            def close(self):
                self.inner.close()

        def scandir(path):
            if Path(path).name == "vanished":
                raise FileNotFoundError(2, "gone", str(path))
            return Listing(real(path))
        got = self.measure(scandir=scandir)["folders"][0]
        self.assertEqual((got["bytes"], got["reason"]), (1000, None))

    def test_a_walk_cut_short_by_the_file_cap_is_unknown(self):
        for n in range(5):
            self.write(f"backups/{n}.dump", 10)
        got = self.measure(max_entries=3)
        self.assertEqual((got["folders"][0]["bytes"], got["folders"][0]["reason"]), (None, disk_space.TOO_MANY))
        self.assertEqual(got["folders"][1]["bytes"], 0)         # each label has its own budget

    def test_a_walk_cut_short_by_time_is_unknown(self):
        self.write("backups/a.dump", 10)
        ticks = iter(range(0, 1000, 10))
        got = self.measure(clock=lambda: next(ticks), max_seconds=5)
        self.assertEqual(got["folders"][0]["reason"], disk_space.TOO_SLOW)
        self.assertIsNone(got["folders"][0]["bytes"])

    def test_links_are_never_followed_or_counted(self):
        self.write("elsewhere/big.bin", 5000)
        (self.root / "backups").mkdir()
        try:
            os.symlink(self.root / "elsewhere", self.root / "backups" / "link", target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("this PC can't make symbolic links")
        self.assertEqual(self.measure()["folders"][0]["bytes"], 0)

    def test_a_disk_that_cant_be_read_has_unknown_free_space(self):
        def broken(path):
            raise OSError("no such drive")
        got = self.measure(disk_usage=broken)
        self.assertEqual(got["disks"][0]["free"], None)
        self.assertEqual(got["disks"][0]["total"], None)

    def test_an_unreadable_device_falls_back_to_the_folders_own_disk(self):
        def broken(path):
            raise OSError("stat failed")
        got = self.measure(device=broken)
        self.assertEqual(len(got["disks"]), 1)      # both missing folders sit under one existing parent


class JudgeTests(unittest.TestCase):
    def measurement(self, free_gb, total_gb=500, **folders):
        rows = [{"label": label, "bytes": size, "present": size != 0, "reason": None if size is not None
                 else disk_space.CANT_READ} for label, size in folders.items()]
        return {"folders": rows, "disks": [{"labels": [r["label"] for r in rows] or ["backups"],
                                            "free": None if free_gb is None else int(free_gb * GB),
                                            "total": None if free_gb is None else int(total_gb * GB)}]}

    def test_plenty_of_room_is_ok_with_sizes_by_label(self):
        lines = disk_space.judge(self.measurement(120, backups=1_234_000_000, shops=0, card_data=None))
        self.assertEqual([entry["level"] for entry in lines], ["ok", "ok"])
        self.assertEqual(lines[0]["text"], "Disk: 120.0 GB free of 500.0 GB (24%).")
        self.assertEqual(lines[1]["text"], "Data folders: backups 1.2 GB, shops none yet, "
                                           "card_data unknown (couldn't be read).")

    def test_under_the_threshold_warns(self):
        lines = disk_space.judge(self.measurement(4, backups=10), warn_below_bytes=10 * GB)
        self.assertEqual(lines[0]["level"], "warn")
        self.assertIn("only 4.0 GB free of 500.0 GB (0%), under the 10.0 GB warning level", lines[0]["text"])
        lines = disk_space.judge(self.measurement(11, backups=10), warn_below_bytes=10 * GB)
        self.assertEqual(lines[0]["level"], "ok")

    def test_unknown_free_space_warns(self):
        lines = disk_space.judge(self.measurement(None, backups=10))
        self.assertEqual(lines[0], {"level": "warn", "text": "Disk: free space unknown (the disk couldn't be read)."})

    def test_several_disks_name_the_folders_each_holds(self):
        m = {"folders": [], "disks": [{"labels": ["backups"], "free": 50 * GB, "total": 100 * GB},
                                      {"labels": ["Forge results", "gauntlet", "shops"], "free": 5 * GB,
                                       "total": 100 * GB}]}
        lines = disk_space.judge(m, 10 * GB)
        self.assertTrue(lines[0]["text"].startswith("Disk holding backups: 50.0 GB free"))
        self.assertTrue(lines[1]["text"].startswith("Disk holding Forge results, gauntlet and shops: only 5.0 GB"))
        self.assertEqual(lines[1]["level"], "warn")

    def test_sizes_read_in_decimal_units(self):
        self.assertEqual([disk_space.size_text(n) for n in (0, 999, 1000, 2_500_000, 3 * GB, 4 * 10 ** 12)],
                         ["0 B", "999 B", "1.0 KB", "2.5 MB", "3.0 GB", "4.0 TB"])


class SettingsTests(unittest.TestCase):
    def test_the_warning_level_comes_from_config_or_the_default(self):
        self.assertEqual(disk_space.warn_below({}), 10 * GB)
        self.assertEqual(disk_space.warn_below({"disk_space": {"warn_below_gb": 25}}), 25 * GB)
        self.assertEqual(disk_space.warn_below({"disk_space": {"warn_below_gb": 2.5}}), int(2.5 * GB))
        for bad in (0, -1, "5", True, None):
            self.assertEqual(disk_space.warn_below({"disk_space": {"warn_below_gb": bad}}), 10 * GB, bad)
        self.assertEqual(disk_space.warn_below({"disk_space": 7}), 10 * GB)

    def test_the_fixed_labels_in_order_and_the_staging_setting(self):
        found = disk_space.folders({})
        self.assertEqual(tuple(label for label, _ in found), disk_space.LABELS)
        self.assertEqual(found[0][1], [Path(config.DATA) / "backups"])
        staging = str(Path(tempfile.gettempdir()).resolve() / "decklab-staging")
        found = disk_space.folders({"database": {"staging_dir": staging}})
        self.assertEqual(found[0][1], [Path(staging)])
        with mock.patch("decklab.lib.pathsetting.on_posix", return_value=True):
            found = disk_space.folders({"database": {"staging_dir": "C:\\Backups"}})
        self.assertEqual(found[0][1], [Path(config.DATA) / "backups"])      # unusable: the default


class ReportTests(Folders):
    def test_the_report_never_names_an_absolute_path(self):
        secret = self.root / "private-staging-place"
        (secret / "x").mkdir(parents=True)
        (secret / "x" / "d.dump").write_bytes(b"1" * 10)
        settings = {"database": {"staging_dir": str(secret)}, "disk_space": {"warn_below_gb": 1000}}
        lines = disk_space.report(settings, disk_usage=usage(3), device=lambda path: 1)
        text = " ".join(entry["text"] for entry in lines)
        self.assertIn("backups 10 B", text)
        self.assertNotIn(str(self.root), text)
        self.assertNotIn("private-staging-place", text)
        self.assertEqual(lines[0]["level"], "warn")

    def test_a_failure_is_one_warning_naming_only_its_type(self):
        with mock.patch.object(disk_space, "measure", side_effect=RuntimeError(f"secret {self.root}")):
            lines = disk_space.report({})
        self.assertEqual(lines, [{"level": "warn", "text": "Disk: couldn't check free space (RuntimeError)."}])


class ShownByTests(unittest.TestCase):
    LINES = [{"level": "warn", "text": "Disk: only 1.0 GB free of 500.0 GB (0%), under the 10.0 GB warning level."},
             {"level": "ok", "text": "Data folders: backups 1.0 GB."}]

    def test_db_status_prints_the_lines_with_warnings_marked(self):
        out = io.StringIO()
        with redirect_stdout(out):
            db_main._disk_lines(lambda: self.LINES)
        self.assertEqual(out.getvalue().splitlines(), ["WARNING: " + self.LINES[0]["text"], self.LINES[1]["text"]])

    def test_db_status_prints_the_disk_lines_when_the_database_cant_be_reached(self):
        from decklab.db import migrate
        out = io.StringIO()
        with mock.patch.object(db, "settings", return_value={"name": "decklab", "host": "localhost", "port": 5432}),                 mock.patch.object(migrate, "status", side_effect=OSError("connection refused")),                 mock.patch.object(disk_space, "report", return_value=self.LINES), redirect_stdout(out):
            with self.assertRaises(OSError):
                db_main._status(mock.Mock(dbname=None))
        self.assertEqual(out.getvalue().splitlines(), ["WARNING: " + self.LINES[0]["text"], self.LINES[1]["text"]])

    def test_homenet_status_lines_warn_with_a_fix(self):
        lines = commands.check_disk(self.LINES)
        self.assertEqual([(entry["level"], entry["area"]) for entry in lines], [("WARN", "Disk"), ("OK", "Disk")])
        self.assertIn("Data folders line", lines[0]["fix"])
        self.assertIsNone(lines[1]["fix"])

    def test_homenet_status_when_the_check_didnt_finish(self):
        self.assertEqual(commands.check_disk(None)[0]["level"], "WARN")

    def test_the_nightly_logs_the_lines_and_reports_a_warning_as_false(self):
        logged = []
        with mock.patch.object(db, "log", side_effect=logged.append):
            self.assertFalse(nightly._disk_space(lambda: self.LINES))
            self.assertTrue(nightly._disk_space(lambda: self.LINES[1:]))
        self.assertEqual(logged[0], "Nightly: WARNING: " + self.LINES[0]["text"])
        self.assertEqual(logged[1], "Nightly: " + self.LINES[1]["text"])

    def test_the_nightly_disk_check_failing_is_a_warning_never_an_exception(self):
        logged = []

        def broken():
            raise OSError("C:/private/place")
        with mock.patch.object(db, "log", side_effect=logged.append):
            self.assertFalse(nightly._disk_space(broken))
        self.assertEqual(logged, ["Nightly: disk space couldn't be checked: OSError."])

    def test_disk_space_is_a_heartbeat_step(self):
        from decklab.lib import operator_alerts
        self.assertIn("disk space", operator_alerts.STEPS)


if __name__ == "__main__":
    unittest.main()
